"""Versioned, self-contained guide format shared by nodes and the editor."""
import base64
import hashlib
import io
import json

import numpy as np
from PIL import Image

VERSION = 1
MAX_PIXELS = 16_777_216
MAX_JSON_BYTES = 32 * 1024**2
MAX_REGIONS = 64
MAX_POINTS = 100_000


def image_batch(images):
    import torch
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] not in (1, 3, 4):
        raise ValueError("IMAGE 必须是 [B,H,W,C] 张量，C 为 1、3 或 4")
    if images.shape[0] < 1 or images.shape[1] < 1 or images.shape[2] < 1:
        raise ValueError("IMAGE 不能为空")
    if images.shape[1] * images.shape[2] > MAX_PIXELS:
        raise ValueError(f"单张图像最多支持 {MAX_PIXELS} 像素")
    arr = images.detach().to(device="cpu", dtype=torch.float32).numpy()
    if not np.isfinite(arr).all():
        raise ValueError("IMAGE 包含 NaN 或 Inf")
    if np.any(arr < 0) or np.any(arr > 1):
        raise ValueError("IMAGE 数值必须在 [0,1]")
    arr = arr[..., :3]
    return np.repeat(arr, 3, axis=-1) if arr.shape[-1] == 1 else np.ascontiguousarray(arr)


def mask_batch(mask, batch, height, width):
    if mask is None:
        return [None] * batch
    arr = mask.detach().cpu().float().numpy() if hasattr(mask, "detach") else np.asarray(mask, np.float32)
    if arr.ndim == 2:
        arr = arr[None]
    if arr.ndim != 3 or arr.shape[1:] != (height, width):
        raise ValueError("MASK 必须是 [B,H,W]，且尺寸与 IMAGE 一致")
    if len(arr) not in (1, batch):
        raise ValueError("MASK 数量必须为 1 或 IMAGE 批次数")
    if not np.isfinite(arr).all() or np.any(arr < 0) or np.any(arr > 1):
        raise ValueError("MASK 必须是有限的 [0,1] 数值")
    return [arr[0 if len(arr) == 1 else i] for i in range(batch)]


def rgb8(image):
    return np.round(image * 255).astype(np.uint8)


def digest(*values):
    h = hashlib.blake2b(digest_size=16)
    for value in values:
        if isinstance(value, np.ndarray):
            h.update(str((value.shape, value.dtype)).encode())
            h.update(np.ascontiguousarray(value).tobytes())
        else:
            h.update(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
    return h.hexdigest()


def png_bytes(arr):
    stream = io.BytesIO()
    Image.fromarray(arr).save(stream, format="PNG")
    return stream.getvalue()


def encode_mask(mask):
    return base64.b64encode(png_bytes(np.round(np.clip(mask, 0, 1) * 255).astype(np.uint8))).decode()


def decode_mask(encoded, height, width):
    if not encoded:
        return np.zeros((height, width), np.float32)
    if not isinstance(encoded, str) or len(encoded) > MAX_JSON_BYTES:
        raise ValueError("遮罩 PNG 无效或过大")
    # Browser canvases emit RGBA PNGs; their red channel stores coverage, not their alpha.
    if encoded.startswith("data:image/png;base64,"):
        encoded = encoded.split(",", 1)[1]
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.format != "PNG" or im.size != (width, height):
                raise ValueError("引导遮罩必须是与 IMAGE 同尺寸的 PNG")
            return np.asarray(im.convert("L"), np.float32) / 255
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取引导遮罩: {exc}") from exc


def default_frame(external=False):
    return {"regions": [{"id": "region-1", "name": "输入遮罩" if external else "左腿",
                         "external": external, "mask": "", "erase": "", "strokes": [], "walls": []}]}


def parse_guides(text, height, width, batch, mode="shared", external=False):
    if not isinstance(text, str) or len(text.encode()) > MAX_JSON_BYTES:
        raise ValueError("引导 JSON 无效或超过 32 MiB")
    try:
        data = json.loads(text or "{}")
    except (ValueError, RecursionError) as exc:
        raise ValueError("引导 JSON 格式错误") from exc
    if not isinstance(data, dict):
        raise ValueError("引导 JSON 顶层必须为对象")
    if not data:
        data = {"version": VERSION, "width": width, "height": height,
                "frames": [default_frame(external)]}
    if data.get("version") != VERSION:
        raise ValueError("不支持此引导格式版本")
    if (data.get("height"), data.get("width")) != (height, width):
        raise ValueError("引导尺寸与 IMAGE 不一致，请在编辑器中重建引导；不会自动拉伸")
    frames = data.get("frames")
    if not isinstance(frames, list) or len(frames) not in (1, batch):
        raise ValueError("引导帧数必须为 1 或 IMAGE 批次数")
    if mode not in ("shared", "per_image"):
        raise ValueError("未知批次模式")
    if mode == "per_image" and len(frames) != batch:
        raise ValueError("逐图模式需要每张图完整对应的引导数据")
    if mode == "shared" and len(frames) != 1:
        raise ValueError("共享模式仅接受一份引导")
    points = 0
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("regions"), list):
            raise ValueError("每帧必须包含 regions 数组")
        regions = frame["regions"]
        if len(regions) > MAX_REGIONS:
            raise ValueError(f"每帧最多 {MAX_REGIONS} 个部位")
        ids = set()
        for region in regions:
            if not isinstance(region, dict):
                raise ValueError("部位必须为对象")
            rid = region.get("id")
            if not isinstance(rid, str) or not rid or rid in ids:
                raise ValueError("部位 id 必须唯一且非空")
            ids.add(rid)
            if not isinstance(region.get("name"), str):
                raise ValueError("部位 name 必须为字符串")
            if not isinstance(region.get("external", False), bool):
                raise ValueError("external 必须为布尔值")
            for key in ("mask", "erase"):
                if not isinstance(region.get(key, ""), str):
                    raise ValueError(f"{key} 必须为 PNG base64 字符串")
            damage = region.get("damage_strokes", [])
            if not isinstance(damage, list) or len(damage) > 512:
                raise ValueError("每个部位最多支持 512 条损伤路径")
            for stroke in damage:
                if not isinstance(stroke, dict) or stroke.get("type") not in ("snag", "ladder"):
                    raise ValueError("损伤类型必须为 snag 或 ladder")
                thickness = stroke.get("width")
                if isinstance(thickness, bool) or not isinstance(thickness, (int, float)) or not np.isfinite(thickness) or not 1 <= thickness <= 256:
                    raise ValueError("损伤宽度必须在 [1,256]")
                try:
                    coords = np.asarray(stroke.get("points"), np.float64)
                except (ValueError, TypeError) as exc:
                    raise ValueError("损伤坐标无效") from exc
                if coords.ndim != 2 or coords.shape[1] != 2 or not len(coords) or not np.isfinite(coords).all():
                    raise ValueError("损伤路径至少需要一个有限的 [x,y] 坐标")
                if (coords[:,0] < 0).any() or (coords[:,0] >= width).any() or (coords[:,1] < 0).any() or (coords[:,1] >= height).any():
                    raise ValueError("损伤坐标超出图像范围")
                points += len(coords)
                if points > MAX_POINTS:
                    raise ValueError("引导点数超过限制")
            for key in ("strokes", "walls"):
                lines = region.get(key, [])
                if not isinstance(lines, list):
                    raise ValueError(f"{key} 必须为折线数组")
                for line in lines:
                    try:
                        a = np.asarray(line, np.float64)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("折线坐标无效") from exc
                    if a.ndim != 2 or a.shape[1] != 2 or len(a) < 2 or not np.isfinite(a).all():
                        raise ValueError("折线必须包含至少两个有限的 [x,y] 坐标")
                    if (a[:, 0] < 0).any() or (a[:, 0] >= width).any() or (a[:, 1] < 0).any() or (a[:, 1] >= height).any():
                        raise ValueError("折线坐标超出图像范围")
                    points += len(a)
                    if points > MAX_POINTS:
                        raise ValueError("引导点数超过限制")
    return data


def frame_masks(frame, height, width, external=None):
    masks = []
    for r in frame["regions"]:
        painted = decode_mask(r.get("mask", ""), height, width)
        erased = decode_mask(r.get("erase", ""), height, width)
        if r.get("external"):
            if external is None:
                raise ValueError("引导引用了外部 MASK，请连接遮罩输入")
            painted = np.maximum(external, painted)
        masks.append(painted * (1 - erased))
    return masks


def dump_guides(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
