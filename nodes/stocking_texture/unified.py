"""Identity-bound manual editing and per-image semantic processing.

This adapter borrows Easy-Sam3's image processor; it never downloads weights.
The original ViT-B point-selection adapter remains independent.
"""
import copy
from contextlib import nullcontext, contextmanager
import json
import threading
import time
import uuid
import weakref

import cv2
import numpy as np

from . import data
from .engine import depth_batch, raster, solve_one, render_one, label_masks, interrupt
from .cache import ByteLRU

_model_registry_lock = threading.RLock()
_model_records = weakref.WeakKeyDictionary()
SEMANTIC_CACHE = ByteLRU(64 * 1024**2)


def validate_semantic(handle, prompt, threshold):
    if not isinstance(handle, dict) or handle.get("segmentor") != "image" or handle.get("model") is None or handle.get("processor") is None:
        raise ValueError("SAM3 语义模式需要连接 Easy-Sam3 的 image 模型加载器")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("SAM3 文本提示不能为空，例如 stockings / pantyhose / tights")
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("SAM3 阈值必须在 [0,1]")


@contextmanager
def coordinate_device(model, device):
    """Move Easy-Sam3's unregistered coordinate caches through ModelPatcher.

    The installed decoder preallocates these on CUDA; Module.to() cannot move
    ordinary tuple/dict attributes. Object patches are temporary and restored.
    """
    import torch
    decoder = getattr(getattr(model, "transformer", None), "decoder", None)
    if decoder is None or not hasattr(decoder, "compilable_cord_cache"):
        yield
        return
    caches = decoder.compilable_cord_cache
    other = decoder.coord_cache
    needs_move = (caches is not None and any(v.device != device for v in caches)) or any(
        v.device != device for pair in other.values() for v in pair)
    if not needs_move:
        yield
        return
    from comfy.model_patcher import ModelPatcher
    patcher = ModelPatcher(model, device, torch.device("cpu"))
    if caches is not None:
        patcher.add_object_patch("transformer.decoder.compilable_cord_cache", tuple(v.to(device) for v in caches))
    patcher.add_object_patch("transformer.decoder.coord_cache", {key: tuple(v.to(device) for v in pair) for key, pair in other.items()})
    try:
        patcher.patch_model(load_weights=False)
        yield
    finally:
        patcher.unpatch_model(unpatch_weights=False)


def semantic_regions(image, handle, prompt="stockings", threshold=0.4):
    import torch
    from PIL import Image
    validate_semantic(handle, prompt, threshold)
    with _model_registry_lock:
        lock, model_token = _model_records.setdefault(handle["model"], (threading.RLock(), uuid.uuid4().hex))
    key = data.digest(data.rgb8(image), prompt, threshold, model_token)
    with lock:
        hit = SEMANTIC_CACHE.get(key)
        if hit is not None:
            return copy.deepcopy(hit)
        model, processor = handle["model"], handle["processor"]
        device = torch.device(handle.get("device", "cpu"))
        dtype = handle.get("dtype", torch.float32)
        previous_device = processor.device
        previous_threshold = processor.confidence_threshold
        start = time.perf_counter()
        state = None
        try:
            # Easy-Sam3 is built in ComfyUI inference mode. Moving its parameters
            # in normal mode mixes tensor version metadata and breaks later views.
            with torch.inference_mode():
                model.to(device)
            processor.device = str(device)
            processor.confidence_threshold = float(threshold)
            # Easy-Sam3 creates this tensor structure on CUDA even for a CPU loader.
            for name, val in vars(processor.find_stage).items():
                if isinstance(val, torch.Tensor):
                    with torch.inference_mode():
                        setattr(processor.find_stage, name, val.to(device))
            autocast = torch.autocast(device.type, dtype=dtype) if device.type != "cpu" and dtype != torch.float32 else nullcontext()
            with torch.inference_mode(), autocast, coordinate_device(model, device):
                state = processor.set_image(Image.fromarray(data.rgb8(image)))
                result = processor.set_text_prompt(prompt=prompt.strip(), state=state)
                masks = result.get("masks")
                scores = result.get("scores")
                if masks is None:
                    masks = np.zeros((0, *image.shape[:2]), np.float32)
                    scores = []
                else:
                    masks = masks.detach().float().cpu().numpy().reshape(-1, *image.shape[:2])
                    scores = scores.detach().float().cpu().numpy().reshape(-1).tolist()
            regions = [{"id": f"sam3-{j}", "name": f"SAM3 {j + 1} ({score:.2f})", "external": False,
                        "mask": data.encode_mask((mask > 0.5).astype(np.float32)), "erase": "", "strokes": [], "walls": []}
                       for j, (mask, score) in enumerate(zip(masks, scores)) if score >= threshold and np.any(mask > 0.5)]
            if len(regions) > data.MAX_REGIONS:
                raise ValueError("SAM3 返回部位过多，请提高识别阈值")
            response = {"regions": regions, "scores": scores, "seconds": time.perf_counter() - start, "device": str(device)}
            SEMANTIC_CACHE.put(key, response)
            return copy.deepcopy(response)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("SAM3 stocking segmentation failed")
            raise
        finally:
            state = None
            with torch.inference_mode():
                model.to("cpu")
            processor.device = previous_device
            processor.confidence_threshold = previous_threshold


def read_records(text):
    if not isinstance(text, str) or len(text.encode()) > data.MAX_JSON_BYTES:
        raise ValueError("引导 JSON 无效或超过 32 MiB")
    try:
        doc = json.loads(text or "{}")
    except (ValueError, RecursionError) as exc:
        raise ValueError("引导 JSON 格式错误") from exc
    if not isinstance(doc, dict):
        raise ValueError("引导 JSON 顶层必须为对象")
    if not doc:
        return {"version": 2, "records": {}}
    if doc.get("version") == 1:
        # Never silently bind a same-size historical mask to an unrelated picture.
        return {"version": 2, "records": {}, "legacy": doc}
    if doc.get("version") != 2 or not isinstance(doc.get("records"), dict):
        raise ValueError("不支持的引导记录版本")
    return doc


def manual_frame(records, image, external=None):
    identity = data.digest(image)
    record = records["records"].get(identity)
    if record is None:
        return None
    h, w = image.shape[:2]
    doc = data.parse_guides(data.dump_guides(record), h, w, 1, "shared", external=external is not None)
    return copy.deepcopy(doc["frames"][0])


def basic_guides(frame, masks):
    """Add transverse PCA guides only to components without a usable hand stroke."""
    frame = copy.deepcopy(frame)
    generated = []
    reg, _ = label_masks(masks, masks[0].shape) if masks else (None, None)
    for rid, region in enumerate(frame["regions"], 1):
        mask = reg == rid
        n, components = cv2.connectedComponents(mask.astype(np.uint8))
        existing = raster(region.get("strokes", []), mask.shape) > 0
        for component in range(1, n):
            part = components == component
            if np.count_nonzero(existing & part) >= 30:
                continue
            ys, xs = np.nonzero(part)
            if len(xs) < 32:
                continue
            points = np.column_stack((xs, ys)).astype(np.float64)
            center = points.mean(axis=0)
            _, vectors = np.linalg.eigh(np.cov(points, rowvar=False))
            longitudinal = vectors[:, -1]
            transverse = np.array([-longitudinal[1], longitudinal[0]])
            along = (points - center) @ longitudinal
            across = (points - center) @ transverse
            for fraction in (0.25, 0.5, 0.75):
                t = np.quantile(along, fraction)
                nearby = np.abs(along - t) < max(3, np.ptp(along) * 0.04)
                if nearby.sum() < 4:
                    continue
                lo, hi = np.min(across[nearby]), np.max(across[nearby])
                pts = center + longitudinal * t + np.array([lo, hi])[:, None] * transverse
                pts[:, 0] = np.clip(pts[:, 0], 0, part.shape[1] - 1)
                pts[:, 1] = np.clip(pts[:, 1], 0, part.shape[0] - 1)
                line = pts.tolist()
                region.setdefault("strokes", []).append(line)
                generated.append(line)
    return frame, generated


def empty_frame(external=False):
    frame = data.default_frame(external)
    if not external:
        frame["regions"][0]["name"] = "部位 1"
    return frame


def frame_for(image, records, source_mode, external=None, handle=None, prompt="stockings", threshold=0.4):
    manual = manual_frame(records, image, external)
    if manual is not None:
        return manual, "manual"
    if source_mode == "semantic":
        return {"regions": semantic_regions(image, handle, prompt, threshold)["regions"]}, "sam3"
    return empty_frame(external is not None), "mask" if external is not None else "manual"


def process_one(image, frame, external, depth, painted, params, color_exclude, seed, auto_direction=True, auto_walls=True, rect=None):
    masks = data.frame_masks(frame, *image.shape[:2], external)
    resolved, generated = basic_guides(frame, masks) if auto_direction else (frame, [])
    fields = solve_one(image, resolved, masks, depth, auto_walls)
    out, layer, alpha, diagnostics, info = render_one(image, fields, params, color_exclude, seed, painted, rect=rect)
    report_region=fields["reg"] if rect is None else fields["reg"][rect[1]:rect[3],rect[0]:rect[2]]
    info.update(coverage_fraction=float(np.mean(report_region > 0)), changed_fraction=float(np.mean(alpha > 0)),
                direction_source="basic+manual" if generated else "manual", basic_guides=generated)
    if not masks or not np.any(fields["reg"]):
        reason = "没有目标选区"
    elif np.all(fields["unguided"][fields["reg"] > 0]):
        reason = "没有有效走向；请启用基础走向或绘制横向引导"
    elif info["changed_pixels"] == 0:
        reason = "未改变任何像素：请检查颜色排除、纹理/亮点强度及过密衰减"
    else:
        reason = None
    info["failure_reason"] = reason
    region_mask=fields["soft"] if rect is None else fields["soft"][rect[1]:rect[3],rect[0]:rect[2]]
    return out, layer, alpha, diagnostics, region_mask, info, fields


def process_batch(images, guides_json, source_mode, params, mask=None, depth=None, sparkle_mask=None,
                  sam3_model=None, prompt="stockings", threshold=0.4, failure_mode="skip",
                  auto_direction=True, depth_direction="white_near", auto_walls=True, color_exclude=True, seed=20261005):
    from .effects import clean_effects
    from .styles import base_style
    clean_effects(params.get("effects_json", "{}"))
    base_style(params.get("style", "knit"))
    if source_mode not in ("semantic", "manual", "mask") or failure_mode not in ("skip", "error"):
        raise ValueError("未知来源或失败处理模式")
    if source_mode == "semantic":
        validate_semantic(sam3_model, prompt, threshold)
    if source_mode == "mask" and mask is None:
        raise ValueError("外部遮罩模式需要 MASK 输入")
    if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("seed 必须为非负 64 位整数")
    records = read_records(guides_json)
    external = data.mask_batch(mask, len(images), *images.shape[1:3])
    depths = depth_batch(depth, images, depth_direction)
    painted = data.mask_batch(sparkle_mask, len(images), *images.shape[1:3])
    success, sources, report = [], [], []
    for index, image in enumerate(images):
        interrupt()
        try:
            frame, source = frame_for(image, records, source_mode, external[index], sam3_model, prompt, threshold)
            result = process_one(image, frame, external[index], depths[index], painted[index], params, color_exclude, seed, auto_direction, auto_walls)
            info = result[5]
            info.update(input_index=index, identity=data.digest(image), region_source=source)
            if info["failure_reason"]:
                raise ValueError(info["failure_reason"])
            info.pop("basic_guides", None)
            info["output_index"] = len(success)
            success.append(result)
            sources.append(image)
            report.append(info)
        except Exception as exc:
            if type(exc).__name__ == "InterruptProcessingException":
                raise
            if failure_mode == "error":
                raise ValueError(f"图像 {index + 1}: {exc}") from exc
            report.append({"input_index": index, "output_index": None, "failure_reason": str(exc)})
    if not success:
        raise ValueError("所有图像均未产生纹理，未输出原图。" + "；".join(f"图像 {r['input_index'] + 1}: {r['failure_reason']}" for r in report))
    return tuple(np.stack([r[j] for r in success]) for j in range(5)) + (np.stack(sources), report)
