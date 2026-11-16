import json
import math
import os
from pathlib import Path

import pytest
import torch
from PIL import Image

from nodes.image_path_nodes import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    ToolBoxLoadImagePath,
)


def test_rgb_path_and_cache_replacement(tmp_path):
    path = tmp_path / "中文 image.png"
    Image.new("RGB", (7, 5), (255, 128, 0)).save(path)
    before = path.read_bytes()
    node = ToolBoxLoadImagePath()
    image, mask, width, height = node.load_image(f"  {path}  ")
    assert (width, height) == (7, 5)
    assert type(width) is type(height) is int
    assert image.shape == (1, 5, 7, 3)
    assert mask.shape == (1, 5, 7)
    assert image.dtype == mask.dtype == torch.float32
    torch.testing.assert_close(image[0, 0, 0], torch.tensor([1, 128 / 255, 0]))
    assert torch.count_nonzero(mask) == 0
    assert path.read_bytes() == before
    assert node.VALIDATE_INPUTS(str(path)) is True
    old_hash = node.IS_CHANGED(str(path))
    assert old_hash == node.IS_CHANGED(str(path))
    stat = path.stat()
    Image.new("RGB", (7, 5), (0, 128, 255)).save(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert old_hash != node.IS_CHANGED(str(path))
    changed, _, _, _ = node.load_image(str(path))
    assert not torch.equal(changed, image)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_alpha_and_palette_transparency(tmp_path, mode):
    path = tmp_path / "transparent.png"
    if mode == "P":
        source = Image.new("P", (3, 1))
        source.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * 759)
        source.putdata([0, 1, 2])
        source.info["transparency"] = bytes([0, 128, 255])
    else:
        source = Image.new(mode, (3, 1))
        source.putdata([(255, 0, 0, a) if mode == "RGBA" else (128, a)
                        for a in [0, 128, 255]])
    source.save(path)
    image, mask, width, height = ToolBoxLoadImagePath().load_image(str(path))
    assert (width, height) == (3, 1)
    assert image.shape == (1, 1, 3, 3)
    torch.testing.assert_close(mask, torch.tensor([[[1, 1 - 128 / 255, 0]]]))


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".webp"])
def test_grayscale_and_common_formats(tmp_path, suffix):
    path = tmp_path / ("gray" + suffix)
    Image.new("L", (4, 2), 128).save(path)
    image, mask, width, height = ToolBoxLoadImagePath().load_image(str(path))
    assert (width, height) == (4, 2)
    torch.testing.assert_close(image, torch.full((1, 2, 4, 3), 128 / 255))
    assert not mask.any()


def test_exif_orientation_rotates_pixels_and_mask_together(tmp_path):
    path = tmp_path / "rotated.png"
    source = Image.new("RGBA", (3, 2), (255, 0, 0, 255))
    source.putpixel((0, 0), (0, 255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6
    source.save(path, exif=exif)
    image, mask, width, height = ToolBoxLoadImagePath().load_image(str(path))
    assert (width, height) == (2, 3)
    assert image.shape == (1, 3, 2, 3)
    assert mask.shape == (1, 3, 2)
    torch.testing.assert_close(image[0, 0, 1], torch.tensor([0., 1., 0.]))
    assert mask[0, 0, 1] == 1
    assert mask.sum() == 1


def test_first_frame_and_path_resolution(tmp_path, monkeypatch):
    path = tmp_path / "animated.gif"
    Image.new("RGB", (4, 2), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (4, 2), "blue")],
        duration=100, loop=0,
    )
    monkeypatch.chdir(tmp_path)
    node = ToolBoxLoadImagePath()
    for value in [str(path), "animated.gif"]:
        image, _, width, height = node.load_image(value)
        assert (width, height) == (4, 2)
        assert image.shape == (1, 2, 4, 3)
        torch.testing.assert_close(image[0, 0, 0], torch.tensor([1., 0., 0.]))


def test_missing_empty_directory_and_corrupt_files(tmp_path):
    node = ToolBoxLoadImagePath()
    for value in ["", "  ", str(tmp_path / "missing.png"), str(tmp_path)]:
        assert isinstance(node.VALIDATE_INPUTS(value), str)
        assert math.isnan(node.IS_CHANGED(value))
        with pytest.raises(ValueError):
            node.load_image(value)
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="Cannot load image"):
        node.load_image(str(corrupt))


def test_connected_path_defers_validation_until_execution(tmp_path):
    node = ToolBoxLoadImagePath()
    assert node.VALIDATE_INPUTS(None) is True
    assert node.VALIDATE_INPUTS() is True
    assert math.isnan(node.IS_CHANGED(None))
    for value in [None, "", str(tmp_path / "missing.png")]:
        with pytest.raises(ValueError):
            node.load_image(value)
    path = tmp_path / "from_upstream.png"
    Image.new("RGB", (9, 6), "red").save(path)
    image, mask, width, height = node.load_image(str(path))
    assert (width, height) == (9, 6)
    assert image.shape == (1, 6, 9, 3)
    assert mask.shape == (1, 6, 9)


def test_node_is_exported_registered_and_localized():
    assert NODE_CLASS_MAPPINGS["ToolBoxLoadImagePath"] is ToolBoxLoadImagePath
    assert NODE_DISPLAY_NAME_MAPPINGS["ToolBoxLoadImagePath"] == "tb-load-image-path"
    root = Path(__file__).resolve().parents[1]
    for language in ["en", "zh"]:
        entry = json.loads((root / f"locales/{language}/nodeDefs.json").read_text())["ToolBoxLoadImagePath"]
        assert entry["display_name"] == "tb-load-image-path"
        assert set(entry["inputs"]) == {"path"}
        assert set(entry["outputs"]) == {"0", "1", "2", "3"}
