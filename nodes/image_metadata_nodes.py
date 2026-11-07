"""Read embedded metadata from the original image file, without model inference."""

import base64
import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError
from PIL.TiffImagePlugin import IFDRational


def _json_value(value):
    """Keep binary data lossless and emit strict JSON, including EXIF rationals."""
    if isinstance(value, IFDRational):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _exif_fields(values, names):
    result = {}
    for tag_id, value in values.items():
        name = names.get(tag_id, str(tag_id))
        result[name] = _json_value(value)
        if tag_id == 37510 and isinstance(value, bytes):  # EXIF UserComment
            prefix, text = value[:8], value[8:]
            encoding = {
                b"ASCII\0\0\0": "ascii",
                b"UNICODE\0": "utf-16",
                b"JIS\0\0\0\0\0": "shift_jis",
            }.get(prefix)
            if encoding:
                try:
                    result["UserCommentText"] = text.decode(encoding).rstrip("\0")
                except UnicodeError:
                    pass  # The original bytes are still available above.
    return result


def read_image_metadata(image_path):
    """Return image properties, raw metadata and named EXIF fields as JSON data."""
    image_path = Path(image_path)
    if not image_path.is_file():
        raise ValueError(f"Image file does not exist: {image_path.name}")
    try:
        with Image.open(image_path) as image:
            # PNG text chunks can follow IDAT. Loading the first frame reads those
            # chunks too; do not iterate/decode all frames of animated images.
            image.load()
            result = {
                "image": {
                    "filename": image_path.name,
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                },
                "metadata": _json_value(image.info),
                "exif": {},
                "comfyui": {},
            }
            try:
                exif = image.getexif()
                result["exif"] = _exif_fields(exif, ExifTags.TAGS)
                for tag_id, name, names in (
                    (34665, "ExifIFD", ExifTags.TAGS),
                    (34853, "GPSInfo", ExifTags.GPSTAGS),
                ):
                    if tag_id in exif:
                        result["exif"][name] = _exif_fields(exif.get_ifd(tag_id), names)
            except (OSError, ValueError, TypeError, SyntaxError) as error:
                result["warnings"] = [f"Could not fully decode EXIF: {error}"]
            for key in ("prompt", "workflow"):
                value = image.info.get(key)
                if isinstance(value, str):
                    try:
                        result["comfyui"][key] = _json_value(json.loads(value))
                    except (ValueError, TypeError):
                        pass  # Raw text remains unchanged in metadata.
            return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError(f"Cannot read image metadata ({image_path.name}): {error}") from error


class ToolBoxImageMetadataReader:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths

        input_dir = folder_paths.get_input_directory()
        files = [name for name in os.listdir(input_dir)
                 if os.path.isfile(os.path.join(input_dir, name))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        return {"required": {"image": (sorted(files), {"image_upload": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("metadata",)
    FUNCTION = "read_metadata"
    CATEGORY = "eazy-toolbox/image"
    DESCRIPTION = "Read embedded image metadata (PNG text, ComfyUI prompt/workflow and EXIF) as JSON."
    SEARCH_ALIASES = ["image metadata", "EXIF", "PNG info"]

    def read_metadata(self, image):
        import folder_paths

        result = read_image_metadata(folder_paths.get_annotated_filepath(image))
        return (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),)

    @classmethod
    def IS_CHANGED(cls, image):
        import folder_paths

        digest = hashlib.sha256()
        with open(folder_paths.get_annotated_filepath(image), "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        import folder_paths

        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True


NODE_CLASS_MAPPINGS = {"ToolBoxImageMetadataReader": ToolBoxImageMetadataReader}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxImageMetadataReader": "tb-image-metadata-reader"}
