"""Load a server image directly from its path without copying it to input."""

import hashlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


def _image_path(path):
    if not isinstance(path, str):
        raise ValueError("Image path must be a string.")
    value = path.strip()
    if not value:
        raise ValueError("Image path cannot be empty.")
    source = Path(value).expanduser()
    if not source.is_file():
        raise ValueError(f"Image file does not exist: {source}")
    return source


class ToolBoxLoadImagePath:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"path": ("STRING", {
            "default": "",
            "multiline": False,
            "tooltip": "Server image path. Enter an absolute path or connect the media library path output.",
        })}}

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "width", "height")
    FUNCTION = "load_image"
    CATEGORY = "eazy-toolbox/image"
    DESCRIPTION = "Load an image from a server file path. Applies EXIF orientation; animated files use the first frame."

    def load_image(self, path):
        import numpy as np
        import torch

        source = _image_path(path)
        try:
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original)
                # RGBA also expands grayscale and palette transparency correctly.
                rgba = np.array(image.convert("RGBA"), dtype=np.float32) / 255.0
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            raise ValueError(f"Cannot load image ({source}): {error}") from error

        pixels = torch.from_numpy(rgba[:, :, :3].copy()).unsqueeze(0)
        mask = torch.from_numpy(1.0 - rgba[:, :, 3]).unsqueeze(0)
        height, width = rgba.shape[:2]
        return pixels, mask, width, height

    @classmethod
    def VALIDATE_INPUTS(cls, path=None):
        # Linked values are unavailable during ComfyUI prompt validation.
        if path is None:
            return True
        try:
            _image_path(path)
        except (ValueError, OSError) as error:
            return str(error)
        return True

    @classmethod
    def IS_CHANGED(cls, path):
        try:
            digest = hashlib.sha256()
            with _image_path(path).open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except (ValueError, OSError):
            return float("nan")


NODE_CLASS_MAPPINGS = {"ToolBoxLoadImagePath": ToolBoxLoadImagePath}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxLoadImagePath": "tb-load-image-path"}
