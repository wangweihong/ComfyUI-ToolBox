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
from tb_stocking_test.nodes import NFStockingEditor, NFStockingSolve, NFStockingRender, session_epoch

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
