"""Free spatial rectangles and a matching IMAGE composition."""

import json
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .latent_nodes import CUSTOM_RATIO, LEGACY_RATIO_NAMES, LEGACY_RESOLUTIONS, RATIO_DATA, ToolBoxLatentSize


def region_names(keys, value):
    saved = value.get("names", {})
    saved = saved if isinstance(saved, dict) else {}
    names = {}
    for key in keys:
        name = " ".join(saved[key].split())[:120] if isinstance(saved.get(key), str) else ""
        names[key] = key if not name or value.get("names_version") != 2 and name == f"image {key.split('_')[1]}" else name
    return names


@lru_cache(maxsize=32)
def label_font(size):
    for path in (
        "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_name(tile, name):
    # Draw inside each tile so a label can never escape its own spatial region.
    width, height = tile.size
    if width < 12 or height < 12:
        return tile
    font_size = max(8, min(48, int(min(width, height) * .07)))
    padding = max(2, font_size // 4)
    font = label_font(font_size)
    draw = ImageDraw.Draw(tile)
    text = name
    available = max(1, width - padding * 4)
    while text and draw.textlength(text, font=font) > available:
        text = text[:-1]
    if text != name and len(text) > 1:
        text = text[:-1] + "…"
    if not text:
        return tile
    box = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = box[2] - box[0], box[3] - box[1]
    draw.rounded_rectangle((padding, padding, min(width - 1, text_width + padding * 3),
                            min(height - 1, text_height + padding * 3)), radius=padding, fill=(24, 28, 36))
    draw.text((padding * 2 - box[0], padding * 2 - box[1]), text, font=font, fill="white")
    return tile


def normalize_layout(keys, value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid image comparison layout JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Image comparison layout must be an object")
    indices = value.get("indices", {})
    if value.get("version") == 3:
        saved = value.get("frames", {})
        saved = saved if isinstance(saved, dict) else {}
        frames = {}
        for i, key in enumerate(keys):
            rect = saved.get(key, {})
            rect = rect if isinstance(rect, dict) else {}
            def number(name, fallback):
                item = rect.get(name, fallback)
                return float(item) if isinstance(item, (float, int)) and np.isfinite(item) else fallback
            w = min(1.0, max(1e-9, number("w", .28)))
            h = min(1.0, max(1e-9, number("h", .32)))
            frames[key] = {"x": min(1 - w, max(0.0, number("x", .04 + (i % 3) * .31))),
                           "y": min(1 - h, max(0.0, number("y", .08 + (i // 3 % 3) * .3))),
                           "w": w, "h": h, "z": min(1000000, max(1, number("z", i + 1)))}
        return {"version": 3, "keys": keys, "frames": frames, "filled": value.get("filled") is True,
                "indices": indices if isinstance(indices, dict) else {}, "names_version": 2, "names": region_names(keys, value)}
    # Keep existing workflows and API requests using the previous strip layout valid.
    saved_weights = value.get("weights", {}) if value.get("keys") == keys else {}
    if not isinstance(saved_weights, dict):
        saved_weights = {}
    weights = []
    for key in keys:
        weight = saved_weights.get(key, 1)
        weights.append(float(weight) if isinstance(weight, (float, int)) and np.isfinite(weight) and weight > 0 else 1.0)
    total = sum(weights)
    frames, position = {}, 0.0
    for i, (key, weight) in enumerate(zip(keys, weights)):
        end = 1.0 if i == len(keys) - 1 else position + weight / total
        frames[key] = ({"x": 0, "y": position, "w": 1, "h": end - position, "z": i + 1}
                       if value.get("axis") == "y" else
                       {"x": position, "y": 0, "w": end - position, "h": 1, "z": i + 1})
        position = end
    return {"version": 3, "keys": keys, "frames": frames, "filled": True,
            "indices": indices if isinstance(indices, dict) else {}, "names_version": 2, "names": region_names(keys, value)}


def one(value):
    return value[0] if isinstance(value, (list, tuple)) else value


class ImageInputs(dict):
    """Advertise one socket while accepting typed, dynamically added IMAGE sockets."""

    def __contains__(self, key):
        return dict.__contains__(self, key) or isinstance(key, str) and re.fullmatch(r"image_[1-9]\d*", key) is not None

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if key in self:
            return ("IMAGE",)
        raise KeyError(key)


class ToolBoxImageCompare:
    @classmethod
    def INPUT_TYPES(cls):
        sizes = ToolBoxLatentSize.INPUT_TYPES()["required"]
        return {"required": {
            "width": ("INT", {"default": 1024, "min": 1, "max": 8192, "step": 1}),
            "height": ("INT", {"default": 768, "min": 1, "max": 8192, "step": 1}),
            "layout": ("STRING", {"default": "{}", "multiline": False}),
        }, "optional": ImageInputs(image_1=("IMAGE",), ratio=sizes["ratio"], resolution=sizes["resolution"])}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("comparison",)
    FUNCTION = "compare"
    CATEGORY = "ToolBox/Image"
    OUTPUT_NODE = True
    INPUT_IS_LIST = True
    DESCRIPTION = "Move and resize numbered rectangles freely. Fill Canvas arranges them into a gapless layout. Outputs the composed IMAGE without source previews."

    def compare(self, width=1024, height=768, layout="{}", ratio=None, resolution=None, **kwargs):
        import torch

        width, height = int(one(width)), int(one(height))
        ratio, resolution = one(ratio), one(resolution)
        if ratio is not None and ratio != CUSTOM_RATIO:
            ratio = LEGACY_RATIO_NAMES.get(ratio, ratio)
            if ratio not in RATIO_DATA:
                raise ValueError("Choose a valid comparison aspect ratio")
            if resolution is None:
                resolution = RATIO_DATA[ratio][0]
            if resolution not in RATIO_DATA[ratio] + LEGACY_RESOLUTIONS.get(ratio, []):
                raise ValueError("Comparison resolution does not match the selected aspect ratio")
            try:
                width, height = map(int, resolution.split(" x "))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("Choose a valid comparison resolution") from exc
        if not 1 <= width <= 8192 or not 1 <= height <= 8192:
            raise ValueError("Comparison width and height must be between 1 and 8192 pixels")
        groups, sources = [], {}
        for name in sorted((key for key in kwargs if key in ImageInputs()),
                           key=lambda key: int(key.split("_")[1])):
            batches = kwargs[name]
            if batches is None:
                continue
            if not isinstance(batches, (list, tuple)):
                batches = [batches]
            frames, metadata = [], []
            for batch in batches:
                if (not hasattr(batch, "is_floating_point") or not batch.is_floating_point()
                        or batch.ndim != 4 or min(batch.shape) < 1
                        or batch.shape[-1] not in (1, 3, 4)):
                    raise ValueError(f"{name}: expected a non-empty floating-point IMAGE [B,H,W,C]")
                for frame in batch:
                    frames.append(frame)
                    metadata.append({"width": frame.shape[1], "height": frame.shape[0]})
            if frames:
                groups.append({"input": name, "images": metadata})
                sources[name] = frames
        keys = [group["input"] for group in groups]
        settings = normalize_layout(keys, one(layout))
        canvas = Image.new("RGB", (width, height))
        for key in sorted(keys, key=lambda key: settings["frames"][key]["z"]):
            index = settings["indices"].get(key, 0)
            index = max(0, min(int(index), len(sources[key]) - 1)) if isinstance(index, (int, float)) and np.isfinite(index) else 0
            settings["indices"][key] = index
            rect = settings["frames"][key]
            pixel = lambda value: int(np.floor(value + .5))
            box = (pixel(rect["x"] * width), pixel(rect["y"] * height),
                   pixel((rect["x"] + rect["w"]) * width), pixel((rect["y"] + rect["h"]) * height))
            if box[2] > box[0] and box[3] > box[1]:
                pixels = sources[key][index].detach().float().cpu().numpy()
                pixels = np.nan_to_num(pixels, nan=0, posinf=1, neginf=0)
                pixels = (np.clip(pixels, 0, 1) * 255).round().astype(np.uint8)
                if pixels.shape[-1] == 1:
                    pixels = pixels[..., 0]
                picture = Image.fromarray(pixels).convert("RGBA")
                background = Image.new("RGBA", picture.size, (0, 0, 0, 255))
                picture = Image.alpha_composite(background, picture).convert("RGB")
                tile = ImageOps.fit(picture, (box[2] - box[0], box[3] - box[1]), method=Image.Resampling.LANCZOS)
                canvas.paste(draw_name(tile, settings["names"][key]), box[:2])
        output = torch.from_numpy(np.asarray(canvas).copy()).float().unsqueeze(0) / 255.0
        return {"ui": {"toolbox_image_compare": groups,
                       "toolbox_image_compare_result": [{"width": width, "height": height, "layout": settings}]},
                "result": (output,)}


NODE_CLASS_MAPPINGS = {"ToolBoxImageCompare": ToolBoxImageCompare}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxImageCompare": "tb-image-compare"}
