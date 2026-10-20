"""Migration contracts and synthetic CPU fixtures; no models or downloads."""

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import re
import sys
import types
from unittest.mock import patch

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "nodes/flux2_klein"


def load_package(path, name):
    spec = importlib.util.spec_from_file_location(
        name, path / "__init__.py", submodule_search_locations=[str(path)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return package


@pytest.fixture(scope="module")
def klein():
    # Only ComfyUI services are replaced. All tensor operations use real PyTorch.
    comfy = types.ModuleType("comfy")
    management = types.ModuleType("comfy.model_management")
    management.get_torch_device = lambda: torch.device("cpu")
    management.load_models_gpu = lambda models: None
    management.throw_exception_if_processing_interrupted = lambda: None
    utils = types.ModuleType("comfy.utils")
    utils.ProgressBar = lambda steps: types.SimpleNamespace(update=lambda count: None)
    preview = types.ModuleType("latent_preview")
    preview.prepare_callback = lambda model, steps: None
    comfy.model_management, comfy.utils = management, utils
    with patch.dict(sys.modules, {
        "comfy": comfy, "comfy.model_management": management,
        "comfy.utils": utils, "latent_preview": preview,
    }):
        yield load_package(MODULE, "tb_flux2_klein_test")


class Model:
    def __init__(self):
        self.model_options = {}
        self.attn_patch = None
        self.output_patch = None

    def clone(self):
        return copy.deepcopy(self)

    def set_model_attn1_patch(self, function):
        self.attn_patch = function

    def set_model_attn1_output_patch(self, function):
        self.output_patch = function


def conditioning(dtype=torch.float32):
    generator = torch.Generator().manual_seed(317)
    return [[torch.randn(1, 12, 9, generator=generator).to(dtype), {
        "attention_mask": torch.tensor([[1] * 8 + [0] * 4]),
        "reference_latents": [torch.randn(1, 3, 4, 4, generator=generator).to(dtype)],
    }]]


def schema(package):
    result = {}
    with patch.object(torch.cuda, "is_available", return_value=False):
        for node_id, cls in package.NODE_CLASS_MAPPINGS.items():
            inputs = cls.INPUT_TYPES()
            result[node_id] = {
                "display_name": package.NODE_DISPLAY_NAME_MAPPINGS[node_id],
                "inputs": inputs,
                "input_order": {kind: list(values) for kind, values in inputs.items()},
                "return_types": cls.RETURN_TYPES,
                "return_names": getattr(cls, "RETURN_NAMES", None),
                "function": cls.FUNCTION,
                "signature": str(inspect.signature(getattr(cls, cls.FUNCTION))),
                "output_node": getattr(cls, "OUTPUT_NODE", False),
            }
    return json.loads(json.dumps(result))


def test_all_sixteen_interfaces_match_source_snapshot(klein):
    expected = json.loads((ROOT / "tests/fixtures/flux2_klein_node_schemas.json").read_text())
    assert len(klein.NODE_CLASS_MAPPINGS) == 16
    assert schema(klein) == expected
    assert all(cls.CATEGORY == "ToolBox/Flux2Klein" for cls in klein.NODE_CLASS_MAPPINGS.values())


def test_computation_and_examples_match_pinned_hashes():
    manifest = json.loads((MODULE / "provenance.json").read_text())
    assert len(manifest["sha256"]) == 19
    for relative, expected in manifest["sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative


def test_total_registry_merges_nodes_without_collisions(klein):
    # Run the real aggregate registration with other groups isolated. Their real
    # registration keys are collected statically, without starting optional services.
    tree = ast.parse((ROOT / "node_mappings.py").read_text())
    originals = {}
    for path in (ROOT / "nodes").rglob("*.py"):
        if MODULE in path.parents:
            continue
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "NODE_CLASS_MAPPINGS" for t in node.targets
            ) and isinstance(node.value, ast.Dict):
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        originals[key.value] = object()
    assert originals
    assert not set(originals).intersection(klein.NODE_CLASS_MAPPINGS)
    modules = {"tb_registry_test.nodes.flux2_klein": klein}
    relative_modules = {n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.level == 1}
    relative_modules.update({"nodes.3dgs", "nodes.stocking_texture.routes"})
    for name in relative_modules - {"nodes.flux2_klein"}:
        module = types.ModuleType("tb_registry_test." + name)
        module.NODE_CLASS_MAPPINGS = originals
        module.NODE_DISPLAY_NAME_MAPPINGS = {}
        modules[module.__name__] = module
    modules["tb_registry_test.nodes.stocking_texture"].routes = modules[
        "tb_registry_test.nodes.stocking_texture.routes"
    ]
    spec = importlib.util.spec_from_file_location("tb_registry_test.node_mappings", ROOT / "node_mappings.py")
    registry = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(registry)
    assert set(registry.NODE_CLASS_MAPPINGS) == set(originals) | set(klein.NODE_CLASS_MAPPINGS)
    for key, cls in originals.items():
        assert registry.NODE_CLASS_MAPPINGS[key] is cls
    for key, cls in klein.NODE_CLASS_MAPPINGS.items():
        assert registry.NODE_CLASS_MAPPINGS[key] is cls
        assert registry.NODE_DISPLAY_NAME_MAPPINGS[key] == klein.NODE_DISPLAY_NAME_MAPPINGS[key]


@pytest.mark.parametrize("node_id", ["Flux2KleinEnhancer", "Flux2KleinTextEnhancer"])
@pytest.mark.parametrize("dtype", [torch.float32, torch.float16])
def test_neutral_enhancers_pass_through_and_preserve_inputs(klein, node_id, dtype):
    cond = conditioning(dtype)
    before = copy.deepcopy(cond)
    result, = klein.NODE_CLASS_MAPPINGS[node_id]().enhance(cond)
    assert result is cond
    torch.testing.assert_close(cond[0][0], before[0][0], rtol=0, atol=0)


def test_enhancer_scales_active_layer_slices_only(klein):
    cond = conditioning(torch.float16)
    before = cond[0][0].clone()
    result, = klein.Flux2KleinEnhancer().enhance(
        cond, active_scale=1.5, early_layer_scale=2.0, late_layer_scale=0.5, device="cpu"
    )
    expected = before.float()
    expected[:, :8] *= 1.5
    expected[:, :8, :3] *= 2.0
    expected[:, :8, 6:] *= 0.5
    torch.testing.assert_close(result[0][0], expected.half(), rtol=0, atol=0)
    torch.testing.assert_close(cond[0][0], before, rtol=0, atol=0)
    assert result[0][1] is cond[0][1]


def test_text_enhancer_preserves_bos_and_padding(klein):
    cond = conditioning()
    before = cond[0][0].clone()
    result, = klein.NODE_CLASS_MAPPINGS["Flux2KleinTextEnhancer"]().enhance(cond, magnitude=2.0)
    expected = before.clone()
    expected[:, 1:8] *= 2
    torch.testing.assert_close(result[0][0], expected, rtol=0, atol=0)
    torch.testing.assert_close(cond[0][0], before, rtol=0, atol=0)


def test_multi_reference_expands_batches_in_input_order(klein):
    cond = conditioning()
    first = torch.ones(2, 3, 4, 4, requires_grad=True)
    second = torch.full((1, 3, 2, 2), 7.0)
    result, = klein.NODE_CLASS_MAPPINGS["Flux2KleinMultiReferenceLatent"]().apply(
        cond, {"samples": first}, latent_3={"samples": second}, latent_2=None
    )
    refs = result[0][1]["reference_latents"]
    assert len(refs) == 3
    assert all(not ref.requires_grad for ref in refs)
    torch.testing.assert_close(refs[0], first[:1])
    torch.testing.assert_close(refs[1], first[1:])
    torch.testing.assert_close(refs[2], second)
    assert result[0][1]["reference_latents_method"] == "index"
    assert len(cond[0][1]["reference_latents"]) == 1


def test_sectioned_encoder_ranges_drive_detail_controller(klein):
    tokenizer = lambda text, **kwargs: {"input_ids": list(range(len(text)))}
    clip = types.SimpleNamespace(
        tokenizer=types.SimpleNamespace(qwen3_8b=types.SimpleNamespace(tokenizer=tokenizer)),
        tokenize=lambda text: text,
        encode_from_tokens=lambda tokens, **kwargs: (torch.ones(1, 512, 9), torch.ones(1, 9)),
    )
    cond, front, mid, end, prompt = klein.Flux2KleinSectionedEncoder().encode_sectioned(
        clip, combined_prompt="[FRONT]A[MID]BC[END]D", show_preview=False
    )
    assert (front, mid, end, prompt) == ("A", "BC", "D", "A, BC, D")
    sections = cond[0][1]["klein_sections"]
    assert sections["front"][1] - sections["front"][0] == 1
    assert sections["mid"] == (sections["front"][1] + 2, sections["front"][1] + 4)
    assert sections["end"] == (sections["mid"][1] + 2, sections["mid"][1] + 3)
    result, = klein.Flux2KleinDetailController().control(
        cond, front_mult=2.0, mid_mult=3.0, end_mult=4.0, device="cpu"
    )
    expected = cond[0][0].clone()
    for key, scale in [("front", 2), ("mid", 3), ("end", 4)]:
        start, stop = sections[key]
        expected[:, start:stop] *= scale
    torch.testing.assert_close(result[0][0], expected, rtol=0, atol=0)


@pytest.mark.parametrize("balance,text_scale,ref_scale", [(0.25, 0.5, 1.0), (0.75, 1.0, 0.5)])
def test_text_reference_balance_and_weight_target_correct_tokens(klein, balance, text_scale, ref_scale):
    model = Model()
    cond = conditioning()
    balanced, _ = klein.NODE_CLASS_MAPPINGS["Flux2KleinTextRefBalance"]().balance_streams(model, cond, balance)
    weighted, = klein.NODE_CLASS_MAPPINGS["Flux2KleinRefLatentWeight"]().execute(model, 0, 0.25)
    q = torch.ones(1, 2, 12, 3)
    options = {"img_slice": [2, 12], "reference_image_num_tokens": [2, 3]}
    expected = q.clone()
    expected[:, :, :2] *= text_scale
    expected[:, :, -5:] *= ref_scale
    result = balanced.attn_patch(q, q, q, options)
    torch.testing.assert_close(result["k"], expected)
    torch.testing.assert_close(result["v"], expected)
    expected = q.clone()
    expected[:, :, -5:-3] *= 0.25
    result = weighted.attn_patch(q, q, q, options)
    torch.testing.assert_close(result["k"], expected)
    torch.testing.assert_close(result["v"], expected)
    assert model.attn_patch is None and torch.all(q == 1)


@pytest.mark.parametrize("invert,feather", [(False, 0), (True, 0), (False, 2)])
def test_mask_reference_attenuates_selected_reference_only(klein, invert, feather):
    cond = conditioning(torch.float16)
    cond[0][1]["reference_latents"].append(torch.ones(1, 3, 4, 4, dtype=torch.float16))
    before = copy.deepcopy(cond)
    mask = torch.zeros(1, 4, 4)
    mask[:, :, 2:] = 1
    node = klein.Flux2KleinMaskRefController()
    result, = node.apply_mask(cond, mask, strength=0.75, invert_mask=invert,
                             feather=feather, reference_index=1)
    spatial = 1 - mask if invert else mask
    if feather:
        spatial = node._feather_mask(spatial.unsqueeze(1), feather)
    expected = (0.25 + 0.75 * spatial).half().expand_as(before[0][1]["reference_latents"][1])
    torch.testing.assert_close(result[0][1]["reference_latents"][1], expected, rtol=0, atol=0)
    assert result[0][1]["reference_latents"][0] is cond[0][1]["reference_latents"][0]
    torch.testing.assert_close(cond[0][1]["reference_latents"][1], before[0][1]["reference_latents"][1])


def test_reference_patch_changes_only_selected_kv(klein):
    model = Model()
    cond = conditioning()
    patched, returned = klein.NODE_CLASS_MAPPINGS["Flux2KleinRefLatentController"]().control(
        model, cond, strength=2.0, reference_index=1
    )
    q = torch.ones(1, 2, 12, 3)
    result = patched.attn_patch(q, q, q, {"reference_image_num_tokens": [2, 3]})
    expected = q.clone()
    expected[:, :, -3:] *= 2
    assert result["q"] is q and returned is cond
    torch.testing.assert_close(result["k"], expected)
    torch.testing.assert_close(result["v"], expected)
    assert torch.all(q == 1) and model.attn_patch is None
    assert patched.attn_patch(q, q, q, {}) == {}


@pytest.mark.parametrize("node_id", ["IdentityFeatureTransfer", "IdentityFeatureTransferAdvanced",
                                     "IdentityFeatureTransferV3", "IdentityFeatureTransferFinal"])
def test_identity_versions_patch_generation_only_and_clone_model(klein, node_id):
    model = Model()
    patched, = klein.NODE_CLASS_MAPPINGS[node_id]().apply(model)
    generator = torch.Generator().manual_seed(789)
    attn = torch.randn(1, 12, 9, generator=generator)
    before = attn.clone()
    options = {"reference_image_num_tokens": [4], "img_slice": [2, 12],
               "block_type": "double", "block_index": 0}
    result = patched.output_patch(attn, options)
    assert torch.isfinite(result).all()
    assert not torch.equal(result[:, 2:8], attn[:, 2:8])
    torch.testing.assert_close(result[:, :2], before[:, :2], rtol=0, atol=0)
    torch.testing.assert_close(result[:, 8:], before[:, 8:], rtol=0, atol=0)
    torch.testing.assert_close(attn, before, rtol=0, atol=0)
    assert model.output_patch is None
    assert patched.output_patch(attn, {}) is attn


def test_guidance_and_color_callbacks_clone_without_changing_source(klein):
    model = Model()
    cond = conditioning()
    ref = cond[0][1]["reference_latents"][0]
    guided, = klein.IdentityGuidance().apply(model, {"samples": ref}, strength=0.25, mode="direct")
    denoised = torch.zeros_like(ref)
    callback = guided.model_options["sampler_post_cfg_function"][0]
    torch.testing.assert_close(callback({"denoised": denoised, "sigma": torch.tensor([0.5])}), ref * 0.25)
    torch.testing.assert_close(callback({"denoised": denoised, "sigma": torch.tensor([0.0])}), denoised)
    anchored, = klein.Flux2KleinColorAnchor().apply(model, cond, strength=0.5, ramp_curve=1.0)
    callback = anchored.model_options["sampler_post_cfg_function"][0]
    result = callback({"denoised": denoised, "sigma": torch.tensor([1.0])})
    torch.testing.assert_close(result, (ref.mean((-2, -1), keepdim=True) * 0.25).expand_as(ref))
    assert model.model_options == {} and torch.all(denoised == 0)


@pytest.mark.parametrize("denoise,cfg", [(1.0, 1.0), (0.5, 2.0)])
def test_experimental_sampler_seed_and_cfg_with_mock_diffusion(klein, denoise, cfg):
    diffusion = types.SimpleNamespace(dtype=torch.float32, patch_size=2,
                                     params=types.SimpleNamespace(guidance_embed=False))
    diffusion.forward = lambda x, t, cond, **kwargs: torch.ones_like(x) * cond.mean()
    model = Model()
    model.model = types.SimpleNamespace(diffusion_model=diffusion)
    node = klein.NODE_CLASS_MAPPINGS["Flux2KleinKSamplerExperimental"]()
    arguments = dict(model=model, positive=[[torch.ones(1, 2, 3), {}]],
                     negative=[[torch.zeros(1, 2, 3), {}]], cfg_scale=cfg,
                     latent_image={"samples": torch.zeros(1, 3, 4, 4)},
                     steps=4, seed=1234, denoise=denoise)
    result, = node.sample(**arguments)
    repeated, = node.sample(**arguments)
    noise = torch.randn((1, 3, 4, 4), generator=torch.Generator().manual_seed(1234))
    module = sys.modules[node.__class__.__module__]
    schedule = module._get_schedule(4, 4)
    start = next(t for t in schedule if t <= denoise)
    expected = start * noise - start * cfg
    torch.testing.assert_close(result["samples"], expected)
    torch.testing.assert_close(result["samples"], repeated["samples"], rtol=0, atol=0)


def test_original_workflows_resolve_migrated_nodes_and_docs_link_locally(klein):
    files = list((ROOT / "examples/flux2_klein").glob("*.json"))
    assert len(files) == 8
    for path in files:
        for node in json.loads(path.read_text())["nodes"]:
            if node["type"].startswith(("Flux2Klein", "Identity")):
                assert node["type"] in klein.NODE_CLASS_MAPPINGS, (path.name, node["type"])
    for path in [ROOT / "docs/flux2_klein.md", ROOT / "examples/flux2_klein/README.md"]:
        for link in re.findall(r"\]\((<[^>]+>|[^)]+)\)", path.read_text()):
            target = link.strip("<>").split("#")[0]
            if target and "://" not in target:
                assert (path.parent / target).exists(), (path.name, target)
