"""ComfyUI PSD adaptation. Original documents are never overwritten."""
import json
from pathlib import Path
import uuid

import cv2
import numpy as np
from . import data
from .editing import clip_line
from .upstream import trace


def io_module():
    try:
        from .upstream import psd_io
    except ImportError as exc:
        raise ValueError("PSD 功能需要安装 requirements-stocking-psd.txt (psd-tools>=1.24)") from exc
    return psd_io


def read(path):
    module = io_module()
    psd = module.PSDImage.open(path)
    if psd.width * psd.height > data.MAX_PIXELS:
        raise ValueError("PSD 超过支持的图像像素上限")
    g = module.read_guide_layers(path)
    image = g["art"].astype(np.float32) / 255
    h, w = image.shape[:2]
    colors = {}
    for group in psd:
        if group.is_group() and group.name in module.both(module.GUIDE_GROUP):
            for layer in group:
                if layer.name in g["regions"]:
                    sample = layer.topil()
                    if sample is not None:
                        rgb = np.asarray(sample.convert("RGB"))[0, 0]
                        colors[layer.name] = "#" + "".join(f"{v:02x}" for v in rgb)
    courses = trace.trace_lines(g["strokes"]) if g["strokes"] is not None else []
    dividers = trace.trace_lines(g["dividers"]) if g["dividers"] is not None else []
    regions = []
    # Match later-region priority in the adapter before assigning raster guide paths.
    labels = np.zeros((h, w), np.int16)
    for i, mask in enumerate(g["regions"].values(), 1):
        labels[mask] = i
    for i, (name, mask) in enumerate(g["regions"].items(), 1):
        owned = labels == i
        regions.append(dict(id=uuid.uuid4().hex, name=name, color=colors.get(name, "#ffc400"),
            external=False, mask=data.encode_mask(mask.astype(np.float32)), erase="",
            strokes=[p for line in courses for p in clip_line(line, owned)],
            walls=[p for line in dividers for p in clip_line(line, owned)]))
    sparkle = np.zeros((h, w), np.float32) if g["sparkle"] is None else g["sparkle"].astype(np.float32) / 255
    frame = dict(regions=regions, wall_erasures=[], sparkle=data.encode_mask(sparkle) if sparkle.any() else "")
    doc = dict(version=1, width=w, height=h, frames=[frame])
    data.parse_guides(data.dump_guides(doc), h, w, 1)
    records = dict(version=2, records={data.digest(image): doc})
    return image, doc, records, sparkle


def frame_from_json(text, image, index=0):
    raw = json.loads(text or "{}")
    h, w = image.shape[:2]
    if raw.get("version") == 2:
        raw = raw.get("records", {}).get(data.digest(image))
        if raw is None:
            raise ValueError("PSD 引导没有对应此图片指纹的记录")
    count = len(raw.get("frames", [])) or 1
    doc = data.parse_guides(data.dump_guides(raw), h, w, count, "shared" if count == 1 else "per_image")
    if count > 1 and index >= count:
        raise ValueError("引导批次索引超出范围")
    return doc["frames"][0 if count == 1 else index]


def write(path, image, frame, external=None, sparkle=None):
    module = io_module()
    h, w = image.shape[:2]
    masks = data.frame_masks(frame, h, w, external)
    regions, colors = {}, {}
    for r, m in zip(frame["regions"], masks):
        name = r["name"]
        while name in regions or name in (*module.both(module.STROKE_LAYER), *module.both(module.SPARKLE_LAYER), *module.both(module.DIVIDER_LAYER)):
            name += "_"
        regions[name] = m > .5
        colors[name] = r.get("color", "#ffc400")
    courses = trace.draw_lines([p for r in frame["regions"] for p in r.get("strokes", [])], (h, w), 5)
    dividers = trace.draw_lines([p for r in frame["regions"] for p in r.get("walls", [])], (h, w), 3)
    imported = data.decode_mask(frame.get("sparkle", ""), h, w)
    painted = imported if sparkle is None else np.maximum(imported, sparkle)
    module.write_guides(path, data.rgb8(image), regions, courses, colors,
                        np.round(painted * 255).astype(np.uint8) if painted.any() else None,
                        dividers if dividers.any() else None)
    return str(path)


def input_path(filename):
    import folder_paths
    root = Path(folder_paths.get_input_directory()).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in (".psd", ".psb") or not path.is_file():
        raise ValueError("请选择 input 目录内有效 PSD/PSB 文件")
    return path


class NFStockingPSDLoad:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        root = Path(folder_paths.get_input_directory())
        files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.suffix.lower() in (".psd", ".psb") and p.is_file())
        return {"required": {"psd_file": (files or [""],)}}
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "MASK", "STRING")
    RETURN_NAMES = ("images", "guides_json", "advanced_guides_json", "sparkle_mask", "report")
    FUNCTION = "load"
    CATEGORY = "南风节点/丝袜纹理"

    @classmethod
    def IS_CHANGED(cls, psd_file):
        import hashlib
        return hashlib.sha256(input_path(psd_file).read_bytes()).hexdigest()

    def load(self, psd_file):
        from .engine import tensor
        image, doc, records, sparkle = read(input_path(psd_file))
        return tensor(image[None]), data.dump_guides(records), data.dump_guides(doc), tensor(sparkle[None]), json.dumps(dict(regions=len(doc["frames"][0]["regions"])), ensure_ascii=False)


class NFStockingPSDSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "filename_prefix": ("STRING", {"default": "Stocking/guides"})},
                "optional": {"guides": ("NF_STOCKING_GUIDES",), "guides_json": ("STRING", {"default": "{}", "multiline": True}),
                             "sparkle_mask": ("MASK",)}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("files",)
    FUNCTION = "save"
    CATEGORY = "南风节点/丝袜纹理"
    OUTPUT_NODE = True

    def save(self, images, filename_prefix="Stocking/guides", guides=None, guides_json="{}", sparkle_mask=None):
        import folder_paths
        arr = data.image_batch(images)
        painted = data.mask_batch(sparkle_mask, len(arr), *arr.shape[1:3])
        folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(filename_prefix, folder_paths.get_output_directory(), arr.shape[2], arr.shape[1])
        files = []
        for i, image in enumerate(arr):
            frame = (guides["document"]["frames"][0 if guides["mode"] == "shared" else i] if guides is not None
                     else frame_from_json(guides_json, image, i))
            path = Path(folder) / f"{name}_{counter + i:05d}_{uuid.uuid4().hex[:8]}.psd"
            if guides is not None:
                # Materialise external masks from the connected advanced guide object.
                import copy
                frame = copy.deepcopy(frame)
                for r, mask in zip(frame["regions"], guides["masks"][i]):
                    r.update(external=False, mask=data.encode_mask(mask), erase="")
            write(path, image, frame, sparkle=painted[i])
            files.append(dict(filename=path.name, subfolder=subfolder, type="output"))
        return {"ui": {"stocking_psd": files}, "result": (json.dumps(files, ensure_ascii=False),)}
