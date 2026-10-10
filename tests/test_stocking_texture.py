"""Public synthetic fixtures: no private illustration or model downloads required."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tb_stocking_test", ROOT / "nodes/stocking_texture/__init__.py", submodule_search_locations=[str(ROOT / "nodes/stocking_texture")])
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)
from tb_stocking_test import data, engine, models, routes
from tb_stocking_test.cache import ByteLRU, REGION_CACHE, SCENE_CACHE, SESSION_CACHE
from tb_stocking_test.core import guide_fields as gf, coverage, look, tiles
from tb_stocking_test.nodes import NFStockingEditor, NFStockingSolve, NFStockingRender, session_epoch, session_payload

OFF = dict(sparkle_depth=0, sparkle_bright=0, sparkle_painted=0, sparkle_even=0, strength_auto=False)


@pytest.fixture(autouse=True)
def empty_caches():
    for cache in (REGION_CACHE, SCENE_CACHE, SESSION_CACHE):
        cache.clear()
    yield
    for cache in (REGION_CACHE, SCENE_CACHE, SESSION_CACHE):
        cache.clear()


def fixture(h=240, w=160, light=0.72, occlusion=False):
    y, x = np.mgrid[:h, :w]
    mask = ((x - w / 2) / (w * 0.3)) ** 2 + ((y - h / 2) / (h * 0.46)) ** 2 < 1
    if occlusion:
        mask[h // 3:h // 3 + 18, w // 3:2 * w // 3] = False
    image = np.empty((h, w, 3), np.float32)
    image[...] = np.array([light, light * 0.96, light * 0.98])
    image += (0.03 * np.cos((x - w / 2) / w * np.pi))[..., None]
    # Deliberately preserve sub-8-bit input precision outside the mask.
    image[~mask] += 0.00037
    region = {"id": "left", "name": "左腿", "external": False, "mask": data.encode_mask(mask.astype(np.float32)),
              "erase": "", "strokes": [[[w * 0.27, h * 0.5], [w * 0.5, h * 0.46], [w * 0.73, h * 0.5]]], "walls": []}
    doc = {"version": 1, "width": w, "height": h, "frames": [{"regions": [region]}]}
    return image, mask, doc


def pipeline(image, doc):
    images = image[None]
    guides, _ = engine.build_guides(images, data.dump_guides(doc))
    return images, guides, engine.solve_batch(images, guides)


@pytest.mark.parametrize("style", look.STYLES)
def test_five_styles_crop_layer_and_outside_exact(style):
    image, mask, doc = fixture(occlusion=True)
    images, _, fields = pipeline(image, doc)
    out, layer, alpha, diag, report = engine.render_batch(images, fields, dict(OFF, style=style, sparkle_even=100))
    assert np.array_equal(out[0][~mask], image[~mask])
    assert np.array_equal(layer * alpha[..., None] + images * (1 - alpha[..., None]), out)
    assert np.isfinite(out).all() and out.min() >= 0 and out.max() <= 1
    assert report[0]["notes"] and report[0]["seed"] == look.SEED
    for rect in [(0, 0, 25, 30), (20, 40, 135, 200), (120, 200, 160, 240)]:
        crop = engine.render_one(image, fields["frames"][0], dict(OFF, style=style, sparkle_even=100), rect=rect)[0]
        x0, y0, x1, y1 = rect
        assert np.array_equal(crop, out[0, y0:y1, x0:x1])
    # The adapter retains the pinned renderer's pixels wherever it legitimately changed the art.
    f = fields["frames"][0]
    scene = engine.scene_for(image, f)
    reference, _ = scene.render(dict(OFF, style=style, sparkle_even=100, sparkle_link=False))
    changed = alpha[0] > 0
    assert np.max(np.abs(data.rgb8(out[0])[changed].astype(int) - reference[..., ::-1][changed].astype(int)), initial=0) <= 1


def test_spacing_not_stroke_density():
    mc = np.zeros((400, 240), bool); mc[10:390, 10:230] = True
    alpha = np.zeros(mc.shape, np.uint8)
    for y in (40, 60, 80, 140, 200, 260, 320):
        cv2.line(alpha, (25, y), (215, y + 8), 255, 5)
    V = gf.solve_region(mc, alpha)[0]
    g = np.hypot(*np.gradient(V))
    assert 0.9 < g[45:75, 40:200].mean() / g[160:300, 40:200].mean() < 1.1
    assert abs(np.median(g[20:380, 20:220]) - 1) < 0.03
    few = np.zeros_like(alpha)
    for y in (40, 320): cv2.line(few, (25, y), (215, y + 8), 255, 5)
    delta = (V - gf.solve_region(mc, few)[0])[20:380, 20:220]
    assert np.percentile(np.abs(delta - np.median(delta)), 99) < 1


def test_occlusion_does_not_change_visible_phase():
    image, mask, doc = fixture(occlusion=True)
    _, _, fields = pipeline(image, doc)
    f = fields["frames"][0]
    assert not f["unguided"][mask].any()
    assert np.isfinite(f["V"][mask]).all()


def test_ripmap_separate_axis_and_frequency_fade():
    tile = np.arange(16, dtype=np.float32).reshape(4, 4)
    rip = tiles.ripmap(tile)
    v, u = np.mgrid[:4, :4]
    sample = tiles.sample(rip, (u + 0.5) / 4, (v + 0.5) / 4 + 3, np.full(u.shape, 1e-3), np.full(u.shape, 1e-3))
    assert np.allclose(sample, tile)
    blurred = tiles.sample(rip, (u + 0.5) / 4, (v + 0.5) / 4, np.full(u.shape, 2.0), np.full(u.shape, 1e-3))
    assert np.allclose(blurred, tile.mean(1, keepdims=True).repeat(4, 1))
    h = w = 240
    y, x = np.mgrid[:h, :w]; reg = np.ones((h, w), np.int8)
    art = np.broadcast_to(np.array([223, 216, 226], np.uint8), (h, w, 3)).copy()
    scene = look.Scene(art, reg, y * 1.6, x.astype(float), np.ones((h, w), bool), np.ones((h, w)), ["left"])
    out = scene.render(dict(OFF, style="knit"))[0]
    assert np.abs(out.astype(int) - scene.src.astype(int))[20:-20, 20:-20].max() <= 2


def test_cache_only_changed_region_and_no_resolve_for_style():
    image, _, doc = fixture(320, 256)
    import copy
    second = dict(copy.deepcopy(doc["frames"][0]["regions"][0]), id="right", name="右腿")
    m1 = data.decode_mask(second["mask"], 320, 256); m1[:, 128:] = 0
    m2 = data.decode_mask(second["mask"], 320, 256); m2[:, :128] = 0
    doc["frames"][0]["regions"][0]["mask"] = data.encode_mask(m1)
    second["mask"] = data.encode_mask(m2)
    doc["frames"][0]["regions"].append(second)
    images, guides, fields = pipeline(image, doc)
    assert fields["frames"][0]["cache_misses"] == 2
    again = engine.solve_batch(images, guides)["frames"][0]
    assert again["cache_hits"] == 2
    doc["frames"][0]["regions"][0]["strokes"].append([[76, 90], [120, 100]])
    changed, _ = engine.build_guides(images, data.dump_guides(doc))
    next_fields = engine.solve_batch(images, changed)
    assert next_fields["frames"][0]["cache_hits"] == 1
    assert next_fields["frames"][0]["cache_misses"] == 1
    with patch.object(gf, "solve_region", side_effect=AssertionError("render must not solve")):
        for style in look.STYLES: engine.render_batch(images, next_fields, dict(OFF, style=style))


def test_seed_and_increasing_sparkles():
    image, _, doc = fixture(320, 256)
    images, _, fields = pipeline(image, doc)
    base = engine.render_batch(images, fields, dict(OFF, style="lines"))[0]
    low = engine.render_batch(images, fields, dict(OFF, style="lines", sparkle_even=50), seed=99)[0]
    high = engine.render_batch(images, fields, dict(OFF, style="lines", sparkle_even=200), seed=99)[0]
    repeat = engine.render_batch(images, fields, dict(OFF, style="lines", sparkle_even=50), seed=99)[0]
    assert np.array_equal(low, repeat)
    low_hit = np.any(low != base, axis=-1); high_hit = np.any(high != base, axis=-1)
    assert low_hit.sum() > 0 and (high_hit | ~low_hit).all()
    other = engine.render_batch(images, fields, dict(OFF, style="lines", sparkle_even=50), seed=100)[0]
    assert not np.array_equal(low, other)


def test_batch_matches_single_and_external_mask_edits():
    image, mask, doc = fixture()
    r = doc["frames"][0]["regions"][0]; r["external"] = True; r["mask"] = ""
    erase = np.zeros(mask.shape, np.float32); erase[:80] = 1; r["erase"] = data.encode_mask(erase)
    images = np.stack([image, image * 0.7])
    guides, _ = engine.build_guides(images, data.dump_guides(doc), mask=mask.astype(np.float32)[None])
    assert not guides["masks"][0][0][:80].any()
    fields = engine.solve_batch(images, guides)
    batch = engine.render_batch(images, fields, dict(OFF, style="grain", sparkle_even=50))[0]
    for i in range(2):
        one, _ = engine.build_guides(images[i:i + 1], data.dump_guides(doc), mask=mask.astype(np.float32)[None])
        solo = engine.render_batch(images[i:i + 1], engine.solve_batch(images[i:i + 1], one), dict(OFF, style="grain", sparkle_even=50))[0]
        assert np.array_equal(batch[i], solo[0])
    per = dict(doc, frames=[doc["frames"][0], doc["frames"][0]])
    assert engine.build_guides(images, data.dump_guides(per), mask=mask.astype(np.float32)[None], mode="per_image")
    with pytest.raises(ValueError, match="逐图"):
        engine.build_guides(images, data.dump_guides(doc), mask=mask.astype(np.float32)[None], mode="per_image")


def test_depth_direction_gray_and_constant():
    image, _, _ = fixture(); images = image[None]
    arr = np.repeat(np.linspace(0, 1, 40, dtype=np.float32)[None, None, :, None], 3, axis=-1)
    depth = torch.from_numpy(np.repeat(arr, 60, axis=1))
    white = engine.depth_batch(depth, images)[0]; black = engine.depth_batch(depth, images, "black_near")[0]
    assert white.shape == image.shape[:2] and np.allclose(white + black, 1)
    assert engine.depth_batch(torch.ones(1, 60, 40, 3), images) == [None]
    color = depth.clone(); color[..., 1] = 0
    with pytest.raises(ValueError, match="伪彩色"): engine.depth_batch(color, images)


def test_external_depth_auto_walls_with_numpy_two_float_promotion():
    image, _, doc = fixture()
    images, guides, _ = pipeline(image, doc)
    yy, xx = np.mgrid[:240, :160]
    d = np.repeat((np.clip(1 - ((xx - 80) / 80) ** 2, 0, 1).astype(np.float32))[None, ..., None], 3, axis=-1)
    fields = engine.solve_batch(images, guides, torch.from_numpy(d))
    assert fields["frames"][0]["depth"] is not None
    assert np.isfinite(engine.render_batch(images, fields, dict(OFF, sparkle_depth=100))[0]).all()


@pytest.mark.parametrize("h,w", [(1, 1), (3, 20), (20, 3), (8, 8)])
def test_tiny_empty_and_unguided_are_finite(h, w):
    image = np.full((h, w, 3), 0.5, np.float32)
    doc = {"version": 1, "height": h, "width": w, "frames": [{"regions": [dict(data.default_frame()["regions"][0], mask=data.encode_mask(np.ones((h, w))))]}]}
    images, _, fields = pipeline(image, doc)
    for style in look.STYLES:
        out = engine.render_batch(images, fields, dict(OFF, style=style))[0]
        assert np.array_equal(out, images)


def test_no_regions_and_invalid_inputs():
    image, _, doc = fixture(); doc["frames"][0]["regions"] = []
    images, _, fields = pipeline(image, doc)
    assert np.array_equal(engine.render_batch(images, fields, OFF)[0], images)
    for text in ("[1]", "{bad", '{"version":2}', '{"version":1,"width":4,"height":4,"frames":[]}'):
        with pytest.raises(ValueError): engine.build_guides(images, text)
    nan = torch.zeros(1, 5, 5, 3); nan[0, 0, 0, 0] = float("nan")
    with pytest.raises(ValueError, match="NaN"): data.image_batch(nan)
    with pytest.raises(ValueError): data.mask_batch(torch.zeros(3, 240, 160), 2, 240, 160)
    with pytest.raises(ValueError): data.decode_mask(data.encode_mask(np.zeros((5, 5))), 240, 160)
    with pytest.raises(ValueError): engine.render_batch(images, fields, dict(density=float("nan")))


def test_color_exclusion_and_auto_strength():
    image, mask, doc = fixture(light=0.88)
    image[115:130, 60:100] = [0.95, 0.65, 0.1]
    _, _, fields = pipeline(image, doc)
    excluded = engine.scene_for(image, fields["frames"][0], True)
    included = engine.scene_for(image, fields["frames"][0], False)
    assert excluded.R[118:127, 65:95].sum() == 0
    assert included.R[118:127, 65:95].sum() > 0
    assert excluded.suggested_strength() < 100


def test_cache_byte_bound_after_mutation_and_many_previews():
    cache = ByteLRU(1024, 5)
    item = {"arr": np.zeros(100, np.float32)}; cache.put("first", item)
    item["more"] = np.ones(200, np.float32); cache.reweigh()
    assert cache.get("first") is None
    for i in range(100): cache.put(str(i), np.ones(100, np.float32))
    assert cache.stats()["bytes"] <= 1024 and cache.stats()["items"] <= 5
    image, _, doc = fixture(120, 80)
    images, _, fields = pipeline(image, doc)
    for i in range(100):
        engine.render_batch(images, fields, dict(OFF, style="lines", sparkle_even=i), seed=i)
    assert SCENE_CACHE.stats()["bytes"] <= SCENE_CACHE.max_bytes
    assert SCENE_CACHE.stats()["items"] <= SCENE_CACHE.max_items


def test_validity_checks_do_not_refresh_lru_order():
    cache = ByteLRU(1024, 2)
    cache.put("old", {"x": 1}); cache.put("current", {"x": 2})
    assert cache.contains("old")
    assert not cache.contains("missing")
    cache.put("new", {"x": 3})
    assert not cache.contains("old")
    assert cache.contains("current") and cache.contains("new")


def test_nodes_saved_json_without_session_and_preview_matches_queue():
    image, _, doc = fixture(); inp = torch.from_numpy(image[None])
    editor = NFStockingEditor().edit(inp, data.dump_guides(doc))
    guides = editor["result"][0]
    fields = NFStockingSolve().solve(inp, guides)[0]
    render = NFStockingRender().render(inp, fields, **dict(OFF, style="loops"))
    token = render["ui"]["nf_stocking"][0]["session"]
    p = {"revision": 4, "index": 0, "params": dict(OFF, style="loops"), "rect": [20, 30, 130, 210]}
    preview = routes.preview_sync(routes.get_session(token), p)
    from PIL import Image
    import io, base64
    pixels = np.array(Image.open(io.BytesIO(base64.b64decode(preview["png"]))))
    assert np.array_equal(pixels, data.rgb8(render["result"][0].numpy()[0, 30:210, 20:130]))
    SESSION_CACHE.clear()
    again = NFStockingEditor().edit(inp, data.dump_guides(doc))["result"][0]
    assert np.array_equal(again["masks"][0][0], guides["masks"][0][0])
    assert len(json.loads(render["result"][4])) == 1


def test_optional_models_do_not_download_or_block_import(tmp_path):
    with patch.object(models, "model_root", return_value=tmp_path):
        with pytest.raises(ValueError, match="缺少本地模型"): models.resolve_local("sams/missing.pth")
        with pytest.raises(ValueError, match="models"): models.resolve_local("../../outside")
        assert models.sam_choices() == ["sams/sam_vit_b_01ec64.pth"]


def test_explicit_cuda_does_not_follow_comfy_cpu_preference():
    from types import ModuleType
    comfy = ModuleType("comfy")
    mm = ModuleType("comfy.model_management")
    mm.get_torch_device = lambda: torch.device("cpu")
    comfy.model_management = mm
    with patch.dict(sys.modules, {"comfy": comfy, "comfy.model_management": mm}), \
         patch.object(torch.cuda, "is_available", return_value=True), \
         patch.object(torch.cuda, "current_device", return_value=2):
        assert str(models.device_for("cuda")) == "cuda:2"
        assert str(models.device_for("auto")) == "cpu"
        assert str(models.device_for("cpu")) == "cpu"
    with patch.object(torch.cuda, "is_available", return_value=False):
        assert str(models.device_for("cuda")) == "cpu"


def test_sam_reports_actual_device_isolates_embeddings_and_offloads_on_failure(tmp_path):
    from types import SimpleNamespace
    checkpoint = tmp_path / "sam_vit_b.pth"
    checkpoint.touch()
    movements, encodings = [], []

    class TensorStandIn:
        def to(self, dev):
            movements.append(str(dev))
            return self

    class Model(TensorStandIn):
        def eval(self): return self

    class Predictor:
        def __init__(self, model):
            self.model = model
            self.features = None
        def set_image(self, rgb):
            self.features = TensorStandIn()
            encodings.append(int(rgb[0, 0, 0]))
            if rgb[0, 0, 0] == 99: raise RuntimeError("encoding failed")
        def predict(self, **kwargs):
            masks = np.zeros((3, 8, 8), bool)
            masks[0, :6] = True; masks[1, :2] = True; masks[2, :4] = True
            return masks, np.array([0.9, 0.7, 0.8]), None

    sam_module = SimpleNamespace(SamPredictor=Predictor, sam_model_registry={"vit_b": lambda **kw: Model()})
    rgb = np.zeros((8, 8, 3), np.uint8)
    with patch.dict(sys.modules, {"segment_anything": sam_module}), \
         patch.object(models, "resolve_local", return_value=checkpoint), \
         patch.object(models, "device_for", return_value=torch.device("cuda:1")), \
         patch.object(models, "_sam_cache", None):
        handle = models.SAMHandle("sam_vit_b.pth", "cuda")
        masks, scores, info = handle.segment(rgb, "image-a", 3, 4, with_info=True)
        assert info["device"] == "cuda:1" and info["requested_device"] == "cuda"
        assert not info["embedding_cached"] and info["offloaded_to_cpu"]
        assert masks.sum(axis=(1, 2)).tolist() == [16, 32, 48]
        assert scores.tolist() == [0.7, 0.8, 0.9]
        assert movements[-2:] == ["cpu", "cpu"]
        assert handle.segment(rgb, "image-a", 3, 4, with_info=True)[2]["embedding_cached"]
        handle.segment(rgb + 1, "image-b", 3, 4)
        assert encodings == [0, 1]
        with pytest.raises(RuntimeError, match="encoding failed"):
            handle.segment(rgb + 99, "image-failed", 3, 4)
        assert movements[-2:] == ["cpu", "cpu"]
        assert models._sam_cache[2] is None
        handle.segment(rgb + 1, "image-b", 3, 4)
        assert encodings == [0, 1, 99, 1]  # An old identity cannot use the failed encoder's features.


@pytest.mark.parametrize("style", look.STYLES)
@pytest.mark.parametrize("diagnostics", [False, True])
def test_overview_and_native_detail_share_queue_pixels(style, diagnostics):
    import base64
    import io
    from PIL import Image
    image, _, doc = fixture()
    inp = torch.from_numpy(image[None])
    guides = NFStockingEditor().edit(inp, data.dump_guides(doc))["result"][0]
    fields = NFStockingSolve().solve(inp, guides)[0]
    render = NFStockingRender().render(inp, fields, **dict(OFF, style=style, strength=160, sparkle_even=100))
    session = routes.get_session(render["ui"]["nf_stocking"][0]["session"])
    p = {"revision": 1, "index": 0, "rect": [20, 30, 130, 210], "overview": True, "diagnostics": diagnostics}
    preview = routes.preview_sync(session, p)
    decode = lambda key: np.array(Image.open(io.BytesIO(base64.b64decode(preview[key]))))
    full = data.rgb8(render["result"][3 if diagnostics else 0].numpy()[0])
    assert np.array_equal(decode("overview_png"), full)  # Small fixture needs no downscale.
    assert np.array_equal(decode("png"), full[30:210, 20:130])
    crop = routes.preview_sync(session, dict(p, revision=2, overview=False))
    assert "overview_png" not in crop
    assert crop["png"] == preview["png"]


def test_overview_is_bounded_without_downscaling_native_detail():
    import base64
    import io
    from PIL import Image
    image = np.full((700, 300, 3), 0.4, np.float32)
    doc = {"version": 1, "width": 300, "height": 700, "frames": [{"regions": []}]}
    images, _, fields = pipeline(image, doc)
    session = {"kind": "renderer", "images": images, "fields": fields, "params": OFF, "seed": 1,
               "painted": [None], "color_exclude": True}
    result = routes.preview_sync(session, {"revision": 1, "overview": True, "rect": [0, 0, 300, 700]})
    decode = lambda key: Image.open(io.BytesIO(base64.b64decode(result[key])))
    assert decode("png").size == (300, 700)
    assert max(decode("overview_png").size) <= 640


def test_evicted_ui_session_invalidates_queue_cache():
    image, _, doc = fixture(); inp = torch.from_numpy(image[None])
    node_id = "eviction-test"
    before = session_epoch(node_id)
    NFStockingEditor().edit(inp, data.dump_guides(doc), unique_id=node_id)
    assert session_epoch(node_id) == before
    SESSION_CACHE.clear()
    assert session_epoch(node_id) == before + 1
    assert session_epoch(node_id) == before + 1


def test_two_workflows_with_same_node_id_keep_independent_sessions():
    image, _, doc = fixture(); inp = torch.from_numpy(image[None])
    node_id = "two-workflows"
    before = session_epoch(node_id)
    first = NFStockingEditor().edit(inp, data.dump_guides(doc), unique_id=node_id)["ui"]["nf_stocking"][0]["session"]
    second = NFStockingEditor().edit(inp * 0.8, data.dump_guides(doc), unique_id=node_id)["ui"]["nf_stocking"][0]["session"]
    for i in range(7): SESSION_CACHE.put(f"unrelated-{i}", {"arr": np.zeros(10)})
    assert SESSION_CACHE.get(first) is None and SESSION_CACHE.get(second) is not None
    assert session_epoch(node_id) == before + 1


def test_repeated_five_style_workflow_keeps_the_new_editor_image():
    # One editor plus five renderers fits in the eight-session budget. Merely
    # checking prior executions must not make those old snapshots more recent.
    node_ids = ["image-switch-editor", *[f"image-switch-render-{i}" for i in range(5)]]
    for run in range(4):
        tokens = []
        for node_id in node_ids:
            # Cache signature discovery can revisit other output nodes while
            # the current execution is still publishing its new snapshots.
            for prior_node in node_ids:
                session_epoch(prior_node)
            payload = session_payload({"images": np.full((1, 64, 64, 3), run / 4, np.float32)}, node_id=node_id)
            tokens.append(payload["session"])
        assert all(SESSION_CACHE.get(token) is not None for token in tokens), "new bottom image was evicted by old UI snapshots"


def test_occluded_courses_match_unoccluded_reference():
    # Adapted from the pinned upstream's public MIT-licensed synthetic regression.
    full = np.zeros((900, 400), bool); full[:, 60:340] = True
    alpha = np.zeros(full.shape, np.uint8)
    for y in (200, 450, 700): cv2.line(alpha, (80, y), (320, y + 25), 255, 5)
    occ = full.copy()
    for x0 in (110, 180, 250): occ[:160, x0:x0 + 24] = False
    occ[400:510, 150:240] = False; occ[600:680, 280:340] = False
    ref, got = gf.solve_region(full, alpha), gf.solve_region(occ, alpha)
    sel = cv2.erode(occ.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    assert np.percentile(np.abs(got[0] - ref[0])[sel], 99) < 2
    th = np.deg2rad(32)
    ang = [np.arctan2(*np.gradient(np.cos(th) * V + np.sin(th) * A)) for V, A in ((ref[0], ref[3]), (got[0], got[3]))]
    delta = np.degrees(np.abs((ang[1] - ang[0] + np.pi) % (2 * np.pi) - np.pi))
    assert np.percentile(delta[sel], 99) < 3


def test_fold_wall_separates_directions_and_knee_remains_smooth():
    mc = np.zeros((420, 380), bool); mc[10:410, 40:340] = True
    alpha = np.zeros(mc.shape, np.uint8)
    cv2.line(alpha, (60, 120), (175, 180), 255, 5); cv2.line(alpha, (205, 150), (325, 150), 255, 5)
    wall = np.zeros(mc.shape, bool); wall[10:300, 189:192] = True
    info = {}; V, NX, NY, A = gf.solve_region(mc, alpha, wall, info)
    angle = lambda y, x: np.degrees(np.arctan2(NY[y, x], NX[y, x])) % 180
    thigh, calf = angle(150, 175), angle(150, 205)
    assert abs(thigh - (90 + np.degrees(np.arctan2(60, 115)))) < 6 and abs(calf - 90) < 6
    assert abs(angle(60, 183) - angle(60, 197)) > 0.8 * abs(thigh - calf)
    knee = cv2.erode(mc.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool); knee[:330] = False
    g = np.hypot(*np.gradient(V))[knee]
    assert g.min() > 0.6 and g.max() < 1.4
    assert info["cut"][150, 190] and not info["cut"][350].any()


@pytest.mark.parametrize("style", look.STYLES)
def test_strength_does_not_rescale_sparkle_lift(style):
    image, _, doc = fixture(320, 256, light=0.4)
    images, _, fields = pipeline(image, doc)
    scene = engine.scene_for(image, fields["frames"][0], False)
    def lift(strength):
        p = dict(OFF, style=style, strength=strength)
        base = scene.render(p)[0].astype(float)
        out = scene.render(dict(p, sparkle_even=100))[0].astype(float)
        hit = np.any(out != base, axis=-1) & (base.sum(axis=-1) > 90) & (out.max(axis=-1) < 250)
        return hit, out.sum(axis=-1) / np.maximum(base.sum(axis=-1), 1) - 1
    a, lo = lift(30); b, hi = lift(200); both = a & b
    assert both.sum() > 100
    assert abs(np.median(lo[both]) / np.median(hi[both]) - 1) < 0.1


def test_flat_oily_art_does_not_invent_a_glint():
    image, _, doc = fixture()
    image[:] = 0.3
    _, _, fields = pipeline(image, doc)
    scene = engine.scene_for(image, fields["frames"][0], False)
    maps = scene.oily_maps()
    assert not maps[1].any()  # specular core


def test_unified_mask_without_hand_guides_produces_texture():
    from tb_stocking_test.unified import process_batch
    image, mask, _ = fixture()
    result = process_batch(image[None], "{}", "mask", dict(OFF, style="knit", strength=160), mask=mask[None], color_exclude=False)
    out, layer, alpha, diagnostics, regions, sources, report = result
    assert report[0]["changed_pixels"] > 0
    assert report[0]["direction_source"] == "basic+manual"
    assert np.array_equal(out[0][~mask], image[~mask])
    np.testing.assert_array_equal(layer * alpha[..., None] + sources * (1 - alpha[..., None]), out)
    assert np.array_equal(regions[0] > 0, mask)


def test_unified_identity_and_legacy_never_reuse_same_size_mask():
    from tb_stocking_test.unified import read_records, manual_frame
    image, _, doc = fixture()
    records = read_records(json.dumps({"version": 2, "records": {data.digest(image): doc}}))
    assert manual_frame(records, image) == doc["frames"][0]
    assert manual_frame(records, image * 0.9) is None
    assert manual_frame(read_records(data.dump_guides(doc)), image) is None


def test_unified_batch_skips_failed_and_aligns_originals():
    from tb_stocking_test.unified import process_batch
    image, mask, _ = fixture()
    images = np.stack([image * 0.9, image])
    masks = np.stack([np.zeros_like(mask), mask]).astype(np.float32)
    result = process_batch(images, "{}", "mask", dict(OFF, style="loops", strength=130), mask=masks, color_exclude=False)
    assert all(len(x) == 1 for x in result[:6])
    np.testing.assert_array_equal(result[5][0], image)
    assert result[6][0]["output_index"] is None
    assert result[6][1]["input_index"] == 1 and result[6][1]["output_index"] == 0
    solo = process_batch(image[None], "{}", "mask", dict(OFF, style="loops", strength=130), mask=mask[None], color_exclude=False)
    np.testing.assert_array_equal(result[0], solo[0])


def test_unified_all_fail_and_global_invalid_model():
    from tb_stocking_test.unified import process_batch
    image, mask, _ = fixture()
    with pytest.raises(ValueError, match="所有图像"):
        process_batch(image[None], "{}", "mask", OFF, mask=np.zeros_like(mask)[None])
    with pytest.raises(ValueError, match="Easy-Sam3"):
        process_batch(image[None], "{}", "semantic", OFF)


def test_unified_preview_matches_final_and_cache_reused():
    from tb_stocking_test.unified import process_batch
    from tb_stocking_test.nodes import prepare_session
    image, mask, doc = fixture()
    doc["frames"][0]["regions"][0]["strokes"] = []
    raw = json.dumps({"version": 2, "records": {data.digest(image): doc}})
    params = dict(OFF, style="grain", strength=140, seed=20261005, color_exclude=False)
    payload = prepare_session(torch.from_numpy(image[None]), params, raw)
    session = SESSION_CACHE.get(payload["session"])
    p = dict(guides_json=data.dump_guides(payload["document"]), index=0, revision=0, params=params, settings=params)
    preview = routes.preview_sync(session, p)
    out = process_batch(image[None], raw, "manual", params, color_exclude=False)[0][0]
    import base64, io
    from PIL import Image
    np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(base64.b64decode(preview["png"])))), data.rgb8(out))
    p["params"] = dict(params, style="loops")
    next_preview = routes.preview_sync(session, p)
    assert next_preview["info"]["cache_hits"] == 1
    for i in range(100):
        p["revision"] = i
        routes.preview_sync(session, p)
    assert REGION_CACHE.bytes <= REGION_CACHE.max_bytes and SCENE_CACHE.bytes <= SCENE_CACHE.max_bytes


def test_unified_manual_guides_take_precedence():
    from tb_stocking_test.unified import basic_guides
    image, mask, doc = fixture()
    frame, generated = basic_guides(doc["frames"][0], [mask.astype(np.float32)])
    assert not generated
    assert frame == doc["frames"][0]


def test_semantic_adapter_caches_by_model_image_prompt_and_restores_device_on_failure():
    from types import SimpleNamespace
    from tb_stocking_test.unified import semantic_regions, SEMANTIC_CACHE
    SEMANTIC_CACHE.clear()
    class Model:
        def __init__(self): self.moves = []
        def to(self, device): self.moves.append(str(device)); return self
    class Processor:
        device = "cpu"
        confidence_threshold = 0.3
        def __init__(self):
            self.calls = 0
            self.fail = False
            self.find_stage = SimpleNamespace(img_ids=torch.tensor([0]))
        def set_image(self, image): return {"size": image.size}
        def set_text_prompt(self, prompt, state):
            self.calls += 1
            if self.fail: raise RuntimeError("inference failed")
            w, h = state["size"]
            masks = torch.zeros((1, 1, h, w)); masks[..., 10:40, 10:40] = 1
            return {"masks": masks, "scores": torch.tensor([0.8])}
    model, processor = Model(), Processor()
    handle = dict(model=model, processor=processor, segmentor="image", device="cpu", dtype=torch.float32)
    image, _, _ = fixture()
    result = semantic_regions(image, handle)
    assert len(result["regions"]) == 1 and model.moves[-1] == "cpu"
    assert processor.device == "cpu" and processor.confidence_threshold == 0.3
    semantic_regions(image, handle)
    assert processor.calls == 1
    result["regions"].clear()
    assert len(semantic_regions(image, handle)["regions"]) == 1
    semantic_regions(image * 0.9, handle)
    assert processor.calls == 2
    processor.fail = True
    with pytest.raises(RuntimeError, match="inference failed"):
        semantic_regions(image, handle, prompt="tights")
    assert model.moves[-1] == "cpu" and processor.confidence_threshold == 0.3
    assert SEMANTIC_CACHE.bytes <= SEMANTIC_CACHE.max_bytes


def test_prepare_stale_dimensions_acquires_new_source_without_parsing_old_masks():
    from tb_stocking_test.nodes import prepare_session
    image, _, doc = fixture()
    payload = prepare_session(torch.from_numpy(image[None, ::2, ::2].copy()), {}, data.dump_guides(doc))
    assert payload["width"] == image.shape[1] // 2 and payload["height"] == image.shape[0] // 2
    assert payload["legacy"] == doc
    assert payload["document"]["frames"][0]["regions"][0]["mask"] == ""


def test_sam3_coordinate_device_patch_restores_caches_even_on_failure():
    from types import SimpleNamespace, ModuleType
    from tb_stocking_test.unified import coordinate_device
    class Coordinate:
        def __init__(self, device): self.device = torch.device(device)
        def to(self, device): return Coordinate(device)
    original = (Coordinate("cuda"), Coordinate("cuda"))
    decoder = SimpleNamespace(compilable_cord_cache=original, coord_cache={(63, 63): original})
    model = SimpleNamespace(transformer=SimpleNamespace(decoder=decoder))
    class Patcher:
        def __init__(self, model, load_device, offload_device): self.patches = {}; self.backup = {}
        def add_object_patch(self, name, value): self.patches[name.split(".")[-1]] = value
        def patch_model(self, load_weights):
            assert not load_weights
            for key, val in self.patches.items(): self.backup[key] = getattr(decoder, key); setattr(decoder, key, val)
        def unpatch_model(self, unpatch_weights):
            assert not unpatch_weights
            for key, val in self.backup.items(): setattr(decoder, key, val)
    module = ModuleType("comfy.model_patcher"); module.ModelPatcher = Patcher
    with patch.dict(sys.modules, {"comfy": ModuleType("comfy"), "comfy.model_patcher": module}):
        with pytest.raises(RuntimeError, match="failure"):
            with coordinate_device(model, torch.device("cpu")):
                assert all(v.device.type == "cpu" for v in decoder.compilable_cord_cache)
                assert all(v.device.type == "cpu" for pair in decoder.coord_cache.values() for v in pair)
                raise RuntimeError("failure")
    assert decoder.compilable_cord_cache is original
    assert decoder.coord_cache[(63, 63)] is original


def test_identical_batch_frames_keep_independent_reports_and_match_pixels():
    from tb_stocking_test.unified import process_batch
    image, mask, _ = fixture()
    images = np.stack([image, image])
    out = process_batch(images, "{}", "mask", dict(OFF, style="loops", strength=140), mask=mask[None], color_exclude=False)
    assert [r["input_index"] for r in out[6]] == [0, 1]
    assert [r["output_index"] for r in out[6]] == [0, 1]
    assert out[6][0] is not out[6][1]
    assert out[6][0]["cache_misses"] == 1 and out[6][1]["cache_hits"] == 1
    np.testing.assert_array_equal(out[0][0], out[0][1])
    np.testing.assert_array_equal(out[5], images)


def test_semantic_preparation_does_not_implicitly_apply_external_mask():
    from tb_stocking_test.nodes import prepare_session
    image, mask, _ = fixture()
    images = torch.from_numpy(image[None])
    semantic = prepare_session(images, {"source_mode": "semantic"}, mask=mask[None], sam3_model={})
    assert semantic["has_mask"] and not semantic["document"]["frames"][0]["regions"][0]["external"]
    manual = prepare_session(images, {"source_mode": "manual"}, mask=mask[None])
    assert manual["document"]["frames"][0]["regions"][0]["external"]
