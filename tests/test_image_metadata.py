import base64
import json
import os
import struct
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from PIL.TiffImagePlugin import IFDRational

from nodes.image_metadata_nodes import (
    ToolBoxImageMetadataReader,
    _json_value,
    read_image_metadata,
)


class ImageMetadataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def png(self, name="example.png", **texts):
        path = self.root / name
        info = PngImagePlugin.PngInfo()
        for key, text in texts.items():
            info.add_itxt(key, text)
        Image.new("RGB", (12, 8)).save(path, pnginfo=info)
        return path

    def test_comfyui_json_and_unicode_text_preserve_originals(self):
        prompt = '{"1": {"inputs": {"text": "合成测试\\nsecond line"}}}'
        workflow = '{"nodes": [], "extra": {"value": 7}}'
        path = self.png(prompt=prompt, workflow=workflow, parameters="raw text\n  indented")
        original = path.read_bytes()
        value = read_image_metadata(path)
        self.assertEqual(value["metadata"]["prompt"], prompt)
        self.assertEqual(value["comfyui"]["prompt"], json.loads(prompt))
        self.assertEqual(value["comfyui"]["workflow"], json.loads(workflow))
        self.assertEqual(value["metadata"]["parameters"], "raw text\n  indented")
        self.assertEqual(value["image"]["width"], 12)
        self.assertEqual(value["image"]["height"], 8)
        self.assertEqual(path.read_bytes(), original)

    def test_text_after_image_data_is_read(self):
        path = self.png()
        data = path.read_bytes()
        payload = b"trailing\0after IDAT"
        chunk = (struct.pack(">I", len(payload)) + b"tEXt" + payload
                 + struct.pack(">I", zlib.crc32(b"tEXt" + payload)))
        path.write_bytes(data[:-12] + chunk + data[-12:])
        self.assertEqual(read_image_metadata(path)["metadata"]["trailing"], "after IDAT")

    def test_plain_image_and_invalid_embedded_json(self):
        value = read_image_metadata(self.png())
        self.assertEqual(value["metadata"], {})
        self.assertEqual(value["exif"], {})
        self.assertEqual(value["comfyui"], {})
        value = read_image_metadata(self.png(prompt="not JSON", workflow="{"))
        self.assertEqual(value["metadata"]["prompt"], "not JSON")
        self.assertEqual(value["comfyui"], {})

    def test_jpeg_exif_nested_comments_and_binary(self):
        path = self.root / "camera.jpg"
        exif = Image.Exif()
        exif[271] = "Synthetic camera"
        exif[274] = 6
        comment = b"UNICODE\0" + "中文注释".encode("utf-16")
        exif[34665] = {37510: comment, 33434: IFDRational(1, 125)}
        exif[34853] = {1: "N", 2: (IFDRational(30, 1), IFDRational(5, 1), IFDRational(0, 1))}
        Image.new("RGB", (12, 8)).save(path, exif=exif)
        result = read_image_metadata(path)
        self.assertEqual(result["exif"]["Make"], "Synthetic camera")
        self.assertEqual(result["exif"]["Orientation"], 6)
        self.assertEqual(result["exif"]["ExifIFD"]["UserCommentText"], "中文注释")
        self.assertEqual(result["exif"]["ExifIFD"]["ExposureTime"], {"numerator": 1, "denominator": 125})
        self.assertEqual(result["exif"]["GPSInfo"]["GPSLatitudeRef"], "N")
        self.assertTrue(base64.b64decode(result["metadata"]["exif"]["data"]))
        json.dumps(result, allow_nan=False)

    def test_webp_exif_and_xmp(self):
        path = self.root / "sample.webp"
        exif = Image.Exif()
        exif[270] = "Synthetic description"
        Image.new("RGB", (12, 8)).save(path, exif=exif, xmp=b"<synthetic/>")
        result = read_image_metadata(path)
        self.assertEqual(result["exif"]["ImageDescription"], "Synthetic description")
        self.assertEqual(base64.b64decode(result["metadata"]["xmp"]["data"]), b"<synthetic/>")

    def test_missing_directory_and_corrupt_files(self):
        bad = self.root / "bad.png"
        bad.write_text("not an image")
        for path in (self.root / "missing.png", self.root, bad):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_image_metadata(path)

    def test_strict_json_binary_rationals_and_nonfinite_numbers(self):
        result = _json_value({"bytes": b"\x00\xff", "ratio": IFDRational(1, 0),
                              "array": (1, float("nan"), float("inf"))})
        self.assertEqual(base64.b64decode(result["bytes"]["data"]), b"\x00\xff")
        self.assertEqual(result["ratio"], {"numerator": 1, "denominator": 0})
        self.assertEqual(result["array"], [1, "nan", "inf"])
        json.dumps(result, allow_nan=False)

    def test_upload_schema_validation_output_and_cache_replacement(self):
        path = self.png(prompt='{"version": 1}')
        (self.root / "not_image.txt").write_text("ignore me")
        folders = types.SimpleNamespace(
            get_input_directory=lambda: str(self.root),
            filter_files_content_types=lambda files, _: [f for f in files if f.endswith(".png")],
            get_annotated_filepath=lambda name: str(self.root / name.removesuffix(" [input]")),
            exists_annotated_filepath=lambda name: (self.root / name).is_file(),
        )
        node = ToolBoxImageMetadataReader()
        with patch.dict(sys.modules, {"folder_paths": folders}):
            schema = node.INPUT_TYPES()["required"]["image"]
            self.assertEqual(schema, (["example.png"], {"image_upload": True}))
            self.assertIs(node.VALIDATE_INPUTS("example.png"), True)
            self.assertIsInstance(node.VALIDATE_INPUTS("missing.png"), str)
            old_hash = node.IS_CHANGED("example.png")
            stat = path.stat()
            output, = node.read_metadata("example.png [input]")
            self.assertEqual(json.loads(output)["comfyui"]["prompt"], {"version": 1})
            self.png(prompt='{"version": 2}')
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertNotEqual(old_hash, node.IS_CHANGED("example.png"))
            output, = node.read_metadata("example.png")
            self.assertEqual(json.loads(output)["comfyui"]["prompt"], {"version": 2})


if __name__ == "__main__":
    unittest.main()
