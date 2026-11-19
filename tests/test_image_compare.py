import sys
import types

import pytest
import torch

from nodes.image_compare_node import ToolBoxImageCompare


@pytest.fixture
def preview_dir(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "folder_paths", types.SimpleNamespace(get_temp_directory=lambda: str(tmp_path)))
    return tmp_path


def test_dynamic_inputs_keep_image_type_and_reject_unrelated_names():
    inputs = ToolBoxImageCompare.INPUT_TYPES()["optional"]
    assert list(inputs) == ["image_1", "ratio", "resolution"]
    for name in ["image_1", "image_3", "image_200"]:
        assert name in inputs and inputs[name] == ("IMAGE",)
    for name in ["other", "image_0", "image_-1", "image_01", "image_2abc"]:
        assert name not in inputs
        with pytest.raises(KeyError):
            _ = inputs[name]


def test_multiple_sizes_batches_channels_and_numeric_socket_order(preview_dir):
    first = torch.tensor([[[[-1., .5, 2., 0.25]]]], requires_grad=True)
    original = first.detach().clone()
    result = ToolBoxImageCompare().compare(image_10=[torch.ones(2, 3, 5, 1)], image_2=[first], image_1=None)
    groups = result["ui"]["toolbox_image_compare"]
    assert result["result"][0].shape == (1, 768, 1024, 3)
    assert [group["input"] for group in groups] == ["image_2", "image_10"]
    assert [len(group["images"]) for group in groups] == [1, 2]
    assert torch.equal(first.detach(), original)
    assert groups[0]["images"] == [{"width": 1, "height": 1}]
    assert groups[1]["images"] == [{"width": 5, "height": 3}] * 2
    pixel = ToolBoxImageCompare().compare(width=1, height=1, image_2=[first])["result"][0][0, 0, 0]
    torch.testing.assert_close(pixel, torch.tensor([0, 32, 64]) / 255)
    assert list(preview_dir.iterdir()) == []


def test_image_lists_return_only_dimensions_and_never_write_source_previews(preview_dir):
    node = ToolBoxImageCompare()
    batches = [torch.zeros(1, 2, 3, 3), torch.ones(2, 4, 5, 3)]
    first = node.compare(image_1=batches)["ui"]["toolbox_image_compare"]
    second = node.compare(image_1=batches)["ui"]["toolbox_image_compare"]
    assert len(first) == 1 and len(first[0]["images"]) == 3
    assert first == second
    assert first[0]["images"] == [{"width": 3, "height": 2}, {"width": 5, "height": 4}, {"width": 5, "height": 4}]
    assert list(preview_dir.iterdir()) == []


def test_empty_input_creates_no_files(preview_dir):
    assert ToolBoxImageCompare().compare()["ui"]["toolbox_image_compare"] == []
    assert list(preview_dir.iterdir()) == []


@pytest.mark.parametrize("image", [torch.zeros(1, 2, 3), torch.zeros(0, 2, 3, 3),
                                   torch.zeros(1, 2, 3, 2), torch.zeros(1, 2, 3, 3, dtype=torch.uint8)])
def test_invalid_images_fail_with_socket_name(preview_dir, image):
    with pytest.raises(ValueError, match="image_3: expected"):
        ToolBoxImageCompare().compare(image_3=[image])


def test_three_partitions_fill_every_pixel_and_follow_divider_weights(preview_dir):
    import json
    red = torch.tensor([1., 0., 0.]).expand(1, 5, 7, 3)
    green = torch.tensor([0., 1., 0.]).expand(1, 8, 3, 3)
    blue = torch.tensor([0., 0., 1.]).expand(1, 2, 10, 3)
    keys = ["image_1", "image_2", "image_3"]
    weights = dict(zip(keys, [.2, .3, .5]))
    for axis, width, height in [("x", 10, 7), ("y", 7, 10)]:
        layout = json.dumps({"axis": axis, "keys": keys, "weights": weights})
        out = ToolBoxImageCompare().compare(width=[width], height=[height], layout=[layout],
            image_1=[red], image_2=[green], image_3=[blue])["result"][0]
        assert out.shape == (1, height, width, 3)
        pixels = out[0, 0] if axis == "x" else out[0, :, 0]
        assert torch.equal(pixels[:2], torch.tensor([1., 0., 0.]).expand(2, 3))
        assert torch.equal(pixels[2:5], torch.tensor([0., 1., 0.]).expand(3, 3))
        assert torch.equal(pixels[5:], torch.tensor([0., 0., 1.]).expand(5, 3))
        assert torch.all(out.sum(-1) == 1)  # No blank cells, borders or UI labels.


def test_selected_batch_and_output_cache_input(preview_dir):
    import json
    images = torch.stack([torch.zeros(4, 4, 3), torch.ones(4, 4, 3)])
    node = ToolBoxImageCompare()
    before = node.compare(width=4, height=4, image_1=[images])["result"][0]
    after = node.compare(width=4, height=4,
        layout=json.dumps({"indices": {"image_1": 1}}), image_1=[images])["result"][0]
    assert before.count_nonzero() == 0 and torch.all(after == 1)
    assert node.RETURN_TYPES == ("IMAGE",)
    assert "layout" in node.INPUT_TYPES()["required"]


def test_cover_crop_does_not_stretch(preview_dir):
    # A tall center strip remains green when a wide source covers a square region.
    image = torch.zeros(1, 4, 12, 3)
    image[:, :, :4, 0] = 1
    image[:, :, 4:8, 1] = 1
    image[:, :, 8:, 2] = 1
    output = ToolBoxImageCompare().compare(width=4, height=4, image_1=[image])["result"][0]
    assert torch.equal(output, torch.tensor([0., 1., 0.]).expand(1, 4, 4, 3))


def test_free_rectangles_use_both_coordinates_and_respect_stacking(preview_dir):
    import json
    red = torch.tensor([1., 0., 0.]).expand(1, 4, 4, 3)
    blue = torch.tensor([0., 0., 1.]).expand(1, 4, 4, 3)
    settings = {"version": 3, "frames": {
        "image_1": {"x": .1, "y": .2, "w": .5, "h": .4, "z": 2},
        "image_2": {"x": .3, "y": .4, "w": .5, "h": .5, "z": 1}}}
    out = ToolBoxImageCompare().compare(width=10, height=10, layout=json.dumps(settings), image_1=[red], image_2=[blue])["result"][0][0]
    assert out[0, 0].sum() == 0
    assert torch.equal(out[2, 1], torch.tensor([1., 0., 0.]))
    assert torch.equal(out[4, 3], torch.tensor([1., 0., 0.]))
    assert torch.equal(out[8, 7], torch.tensor([0., 0., 1.]))
    assert out[9, 9].sum() == 0


def test_t_shaped_filled_layout_outputs_no_gaps(preview_dir):
    import json
    colors = [torch.tensor(v).expand(1, 3, 3, 3) for v in [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]]
    frames = {"image_1": {"x": 0, "y": 0, "w": .5, "h": .6},
              "image_2": {"x": .5, "y": 0, "w": .5, "h": .6},
              "image_3": {"x": 0, "y": .6, "w": 1, "h": .4}}
    out = ToolBoxImageCompare().compare(width=10, height=10, layout=json.dumps({"version": 3, "frames": frames, "filled": True}),
        **{f"image_{i+1}": [image] for i, image in enumerate(colors)})["result"][0][0]
    assert torch.equal(out[:6, :5], torch.tensor([1., 0., 0.]).expand(6, 5, 3))
    assert torch.equal(out[:6, 5:], torch.tensor([0., 1., 0.]).expand(6, 5, 3))
    assert torch.equal(out[6:], torch.tensor([0., 0., 1.]).expand(4, 10, 3))
    assert torch.all(out.sum(-1) == 1)


def test_names_are_normalized_and_rendered_inside_each_output_region(preview_dir):
    import json
    from nodes.image_compare_node import normalize_layout
    keys = ["image_1", "image_2"]
    assert normalize_layout(keys, {})["names"] == {"image_1": "image_1", "image_2": "image_2"}
    assert normalize_layout(keys, {"names": {"image_1": "image 1", "image_2": "Edited"}})["names"] == {"image_1": "image_1", "image_2": "Edited"}
    assert normalize_layout(keys, {"names_version": 2, "names": {"image_1": "image 1"}})["names"]["image_1"] == "image 1"
    image = torch.ones(1, 128, 256, 3)
    settings = {"names": {"image_1": "Original", "image_2": "Edited"}}
    output = ToolBoxImageCompare().compare(width=512, height=256, layout=json.dumps(settings), image_1=[image], image_2=[image])
    assert output["ui"]["toolbox_image_compare_result"][0]["layout"]["names"] == settings["names"]
    pixels = output["result"][0][0]
    for x in [0, 256]:
        assert torch.any(pixels[:30, x:x+140] < 1)  # The name is drawn over the source.
        assert torch.all(pixels[80:, x:x+256] == 1)  # Labels stay inside their own top area.
    alternate = ToolBoxImageCompare().compare(width=512, height=256,
        layout=json.dumps({"names": {"image_1": "Changed", "image_2": "Edited"}}), image_1=[image], image_2=[image])["result"][0]
    assert not torch.equal(output["result"][0], alternate)


def test_aspect_ratio_and_resolution_share_latent_size_presets(preview_dir):
    from nodes.latent_nodes import RATIO_DATA, ToolBoxLatentSize
    schema = ToolBoxImageCompare.INPUT_TYPES()["optional"]
    latent = ToolBoxLatentSize.INPUT_TYPES()["required"]
    assert schema["ratio"] == latent["ratio"] and schema["resolution"] == latent["resolution"]
    image = torch.ones(1, 8, 8, 3)
    for ratio in ["16:9 横屏", "9:16 竖屏"]:
        resolution = RATIO_DATA[ratio][2]
        expected_width, expected_height = map(int, resolution.split(" x "))
        out = ToolBoxImageCompare().compare(width=100, height=100, ratio=[ratio], resolution=[resolution], image_1=[image])
        assert out["result"][0].shape == (1, expected_height, expected_width, 3)
    custom = ToolBoxImageCompare().compare(width=11, height=7, ratio="自定义尺寸", image_1=[image])
    assert custom["result"][0].shape == (1, 7, 11, 3)
