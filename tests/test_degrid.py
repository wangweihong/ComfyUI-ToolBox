"""Numerical fixtures are synthetic and require no models or network access."""

import hashlib
import json
from pathlib import Path

import pytest
import torch

from nodes.degrid import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from nodes.degrid.degrid_core import degrid, extract_grid, lattice_amp
from nodes.degrid.nodes import ToolBoxVAEDeGrid

ROOT = Path(__file__).resolve().parents[1]
DEVICES = ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])


def test_pinned_upstream_core_is_unchanged():
    digest = hashlib.sha256((ROOT / "nodes/degrid/degrid_core.py").read_bytes()).hexdigest()
    assert digest == "cee414b123ae19e7bc6770757818389ad6ededd7830c30065dd68477e1cc40ca"


def test_notch_preserves_constant_and_linear_gradient_interior():
    ramp = torch.linspace(0.2, 0.7, 128).view(1, 1, 1, 128).expand(1, 3, 96, 128)
    correction = extract_grid(ramp)
    assert correction[..., 4:-4, 4:-4].abs().max().item() < 1e-7
    amp, _, _, _ = lattice_amp(correction)
    assert amp.item() < 0.5 / 255


def grid_image(kind="checker", h=96, w=128, amplitude=0.008, dtype=torch.float32, device="cpu"):
    y = torch.arange(h, device=device).view(h, 1)
    x = torch.arange(w, device=device).view(1, w)
    phase = {"checker": x + y, "vstripe": x.expand(h, w), "hstripe": y.expand(h, w)}[kind]
    pattern = (1 - 2 * (phase % 2)).to(dtype)
    return (0.45 + amplitude * pattern)[None, ..., None].expand(1, h, w, 3).clone()


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("kind", ["checker", "vstripe", "hstripe"])
def test_three_grid_orientations_removed(kind, device):
    image = grid_image(kind, device=device)
    cleaned, vis, stats = degrid(image)
    assert torch.max(torch.abs(cleaned - 0.45)).item() < 2e-7
    assert stats[0]["amp_255"] == pytest.approx(0.016 * 255, abs=1e-4)
    components = {k: stats[0][k + "_255"] for k in ["checker", "vstripe", "hstripe"]}
    assert max(components, key=components.get) == kind
    assert not stats[0]["skipped"]
    assert vis.max() > 0.5 and vis.min() < 0.5


@pytest.mark.parametrize("dtype", [torch.float16, torch.float32, torch.float64])
@pytest.mark.parametrize("device", DEVICES)
def test_bypass_and_clean_pixels_exact(dtype, device):
    image = torch.full((1, 65, 97, 3), 0.123456789123, dtype=dtype, device=device)
    for enabled in [False, True]:
        out = ToolBoxVAEDeGrid().process(image, enabled=enabled)
        cleaned, preview = out["result"]
        assert cleaned is image
        assert torch.equal(preview, torch.full_like(preview, 0.5))
        assert cleaned.dtype == preview.dtype == dtype
        assert cleaned.device == preview.device == image.device
        if enabled:
            assert out["ui"]["degrid"][0]["stats"][0]["skipped"]


def test_busy_clean_image_is_not_mistaken_for_grid():
    rng = torch.Generator().manual_seed(41)
    image = torch.rand((1, 512, 512, 3), generator=rng) * 0.3 + 0.3
    out = ToolBoxVAEDeGrid().process(image)
    s = out["ui"]["degrid"][0]["stats"][0]
    assert s["amp_255"] < 0.5 and s["texture_255"] > 1
    assert out["result"][0] is image
    forced = ToolBoxVAEDeGrid().process(image, skip_when_clean=False)
    assert not forced["ui"]["degrid"][0]["stats"][0]["skipped"]
    assert not torch.equal(forced["result"][0], image)
    assert "filtered anyway" in forced["ui"]["degrid"][0]["text"]


def test_manual_cap_protects_real_edges_and_zero_limit():
    image = grid_image()
    image[:, :, 64:] += 0.3
    out = ToolBoxVAEDeGrid().process(image, mode="manual", limit=0.004)
    correction = image - out["result"][0]
    assert correction.abs().max().item() <= 0.004 + 1e-7
    assert out["ui"]["degrid"][0]["stats"][0]["clipped_pct"] > 0
    zero = ToolBoxVAEDeGrid().process(image, mode="manual", limit=0)
    assert torch.equal(zero["result"][0], image)


def test_mixed_batch_calibrates_each_frame_and_restores_clean_precision():
    clean = torch.full((1, 96, 128, 3), 0.123456789123, dtype=torch.float64)
    batch = torch.cat([grid_image(dtype=torch.float64), clean, grid_image(amplitude=0.012, dtype=torch.float64)])
    original = batch.clone()
    out = ToolBoxVAEDeGrid().process(batch)
    cleaned = out["result"][0]
    stats = out["ui"]["degrid"][0]["stats"]
    assert [s["skipped"] for s in stats] == [False, True, False]
    assert stats[0]["limit"] < stats[2]["limit"]
    assert torch.equal(cleaned[1], batch[1])
    assert torch.equal(batch, original)
    assert "batch of 3 (first shown)" in out["ui"]["degrid"][0]["text"]
    for index in [0, 2]:
        alone = ToolBoxVAEDeGrid().process(batch[index:index + 1])["result"][0]
        assert torch.equal(cleaned[index], alone[0])


@pytest.mark.parametrize("shape", [(1, 1), (4, 7), (8, 8), (9, 9), (65, 97)])
@pytest.mark.parametrize("dtype", [torch.float16, torch.float32])
@pytest.mark.parametrize("device", DEVICES)
def test_small_odd_shapes_dtype_device_and_preview_isolation(shape, dtype, device):
    image = grid_image(h=shape[0], w=shape[1], dtype=dtype, device=device)
    original = image.clone()
    results = [ToolBoxVAEDeGrid().process(image, grid_gain=gain, grid_view=view)["result"]
               for gain, view in [(1, "full frame"), (10, "4x zoom"), (50, "8x zoom")]]
    for cleaned, preview in results:
        assert cleaned.shape == image.shape
        assert cleaned.dtype == preview.dtype == dtype
        assert cleaned.device == preview.device == image.device
        assert torch.isfinite(cleaned).all() and torch.isfinite(preview).all()
        assert cleaned.min() >= 0 and cleaned.max() <= 1
        assert preview.min() >= 0 and preview.max() <= 1
        assert preview.numel() > 0
        assert torch.equal(cleaned, results[0][0])
    assert torch.equal(image, original)


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_adapter_matches_unmodified_core_for_filtered_frames(mode):
    image = grid_image(h=65, w=97)
    cleaned, vis, stats = degrid(image, mode=mode, grid_view="8x zoom")
    out = ToolBoxVAEDeGrid().process(image, mode=mode, grid_view="8x zoom")
    assert torch.equal(out["result"][0], cleaned)
    assert torch.equal(out["result"][1], vis)
    assert out["ui"]["degrid"][0]["stats"] == stats


def test_registration_defaults_locales_and_example_links():
    assert NODE_CLASS_MAPPINGS == {"ToolBoxVAEDeGrid": ToolBoxVAEDeGrid}
    assert NODE_DISPLAY_NAME_MAPPINGS == {"ToolBoxVAEDeGrid": "tb-vae-degrid"}
    assert ToolBoxVAEDeGrid.OUTPUT_NODE is True
    inputs = ToolBoxVAEDeGrid.INPUT_TYPES()["required"]
    api = json.loads((ROOT / "examples/degrid/01-去网格对比.api.json").read_text())
    workflow = json.loads((ROOT / "examples/degrid/01-去网格对比.json").read_text())
    nodes = {n["id"]: n for n in workflow["nodes"]}
    defaults = {name: spec[1]["default"] for name, spec in inputs.items() if name != "image"}
    assert nodes[2]["widgets_values"] == list(defaults.values())
    assert api["2"]["inputs"] == {"image": ["1", 0], **defaults}
    for link, source, source_slot, target, target_slot, kind in workflow["links"]:
        assert link in nodes[source]["outputs"][source_slot]["links"]
        target_input = nodes[target]["inputs"][target_slot]
        assert target_input["link"] == link and target_input["type"] == kind
        assert api[str(target)]["inputs"][target_input["name"]] == [str(source), source_slot]
    for lang in ["en", "zh"]:
        entry = json.loads((ROOT / f"locales/{lang}/nodeDefs.json").read_text())["ToolBoxVAEDeGrid"]
        assert set(entry["inputs"]) == set(inputs)
        assert set(entry["outputs"]) == {"0", "1"}


@pytest.mark.parametrize("image", [torch.empty(0, 10, 10, 3), torch.empty(1, 0, 10, 3), torch.zeros(10, 10, 3), torch.zeros(1, 10, 10, 3, dtype=torch.uint8)])
def test_invalid_image_batch_has_clear_error(image):
    with pytest.raises(ValueError, match="non-empty floating-point IMAGE"):
        ToolBoxVAEDeGrid().process(image)
