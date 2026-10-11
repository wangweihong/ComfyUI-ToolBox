"""Effects preserve the image/layer/crop contracts of the existing renderer."""
import copy
import json

import numpy as np
import pytest

from test_stocking_texture import fixture, pipeline, OFF
from tb_stocking_test import data, engine, effects
from tb_stocking_test.core import look
from tb_stocking_test.styles import PATTERNS, STYLES


@pytest.fixture(autouse=True)
def clear_effect_cache():
    effects.EFFECT_CACHE.clear()
    yield
    effects.EFFECT_CACHE.clear()


def render(image, fields, style, cfg=None, seed=20261005):
    return engine.render_one(image, fields, dict(OFF, style=style, effects_json=json.dumps(cfg or {})), seed=seed)


@pytest.mark.parametrize("style", PATTERNS)
def test_patterns_crop_outside_and_layer_contract(style):
    image,mask,doc = fixture(h=360,w=240,occlusion=True)
    _,_,fields = pipeline(image,doc)
    cfg = {"pattern":{"size":150,"mode":"print","color":"#331155"}}
    full,layer,alpha,_,info = render(image,fields["frames"][0],style,cfg)
    assert info["style"] == style and info["changed_pixels"] > 0
    assert np.array_equal(full[~mask],image[~mask])
    assert np.array_equal(layer*alpha[...,None]+image*(1-alpha[...,None]),full)
    crop = engine.render_one(image,fields["frames"][0],dict(OFF,style=style,effects_json=json.dumps(cfg)),rect=[40,80,180,280])[0]
    assert np.array_equal(crop,full[80:280,40:180])


@pytest.mark.parametrize("style", look.STYLES)
def test_disabled_effects_preserve_upstream_pixels(style):
    image,mask,doc = fixture()
    _,_,fields = pipeline(image,doc)
    f = fields["frames"][0]
    scene = engine.scene_for(image,f)
    params = dict(OFF,style=style)
    expected,_ = scene.render(engine.clean_params(params,False))
    out = render(image,f,style,{"text":{"enabled":False},"damage":{"enabled":False}})[0]
    changed = (scene.R>0) & np.any(expected[...,::-1]!=data.rgb8(image),axis=-1)
    reference = image.copy(); reference[changed] = expected[...,::-1][changed].astype(np.float32)/255
    assert np.array_equal(reference,out)


def test_patterns_are_distinct_and_fabric_print_differ():
    images = []
    for style in PATTERNS:
        tile = effects.pattern_tile(style)[0][0]
        assert tile.min() < .1 and tile.max() > .8
        images.append(data.digest(tile))
    # Small/large fishnet deliberately share a motif and differ in surface repeat size.
    assert len(set(images)) >= 7
    image,_,doc = fixture()
    _,_,fields = pipeline(image,doc)
    print_image = render(image,fields["frames"][0],"lace",{"pattern":{"mode":"print"}})[0]
    fabric = render(image,fields["frames"][0],"lace")[0]
    assert not np.array_equal(print_image,fabric)


def test_text_variants_and_no_mirror_orientation():
    image,mask,doc = fixture(h=360,w=240)
    _,_,fields = pipeline(image,doc); f = fields["frames"][0]
    outputs = [render(image,f,"knit",{"text":{"enabled":True,"content":text,"color":"#eeeeee","size":size,"rotation":angle}})[0]
               for text,size,angle in (("BALENCIAGA",100,0),("PARIS",100,0),("My Brand 2026!",160,25))]
    assert len({data.digest(out) for out in outputs}) == 3
    for out in outputs:
        assert np.array_equal(out[~mask],image[~mask])
    scene = engine.scene_for(image,f)
    scene.A = -np.indices(scene.R.shape)[1].astype(np.float32)
    scene.V = -np.indices(scene.R.shape)[0].astype(np.float32)
    a,v = effects.surface_coordinates(scene)
    assert np.median(np.gradient(a)[1][mask]) > 0
    assert np.median(np.gradient(v)[0][mask]) > 0


@pytest.mark.parametrize("mode", ["random","manual","both"])
def test_damage_modes_seed_crop_and_geometry_cache(mode):
    image,mask,doc = fixture(h=360,w=240)
    doc["frames"][0]["regions"][0]["damage_strokes"] = [
        {"type":"snag","points":[[105,90],[100,130],[115,200]],"width":3},
        {"type":"ladder","points":[[135,100]],"width":4}]
    _,_,fields = pipeline(image,doc); f = fields["frames"][0]
    cfg = {"text":{"enabled":True,"content":"PARIS"},"damage":{"enabled":True,"mode":mode,"count":4}}
    out,layer,alpha,_,info = render(image,f,"hearts",cfg)
    assert info["damage_count"] >= (2 if mode=="manual" else 1)
    assert np.array_equal(out[~mask],image[~mask])
    assert np.array_equal(layer*alpha[...,None]+image*(1-alpha[...,None]),out)
    effects.EFFECT_CACHE.clear()
    assert np.array_equal(out,render(image,f,"hearts",cfg)[0])
    crop = engine.render_one(image,f,dict(OFF,style="hearts",effects_json=json.dumps(cfg)),rect=[70,80,160,240])[0]
    assert np.array_equal(crop,out[80:240,70:160])
    if mode != "manual":
        assert not np.array_equal(out,render(image,f,"hearts",cfg,seed=20261006)[0])
    changed = copy.deepcopy(doc)
    changed["frames"][0]["regions"][0]["damage_strokes"][0]["points"] = [[115,120],[120,170]]
    _,_,next_fields = pipeline(image,changed)
    assert next_fields["frames"][0]["signature"] == f["signature"]
    assert next_fields["frames"][0]["cache_misses"] == 0
    if mode != "random":
        assert not np.array_equal(out,render(image,next_fields["frames"][0],"hearts",cfg)[0])


@pytest.mark.parametrize("invalid", [
    {"version":3}, {"text":{"content":"中文"}}, {"text":{"content":"a"*129}},
    {"text":{"content":"a\nb"}}, {"pattern":{"color":"red"}}, {"pattern":{"size":float("nan")}},
    {"damage":{"mode":"invalid"}}, {"damage":{"enabled":"true"}}, {"text":[]},
])
def test_invalid_effect_configs_fail_clearly(invalid):
    with pytest.raises(ValueError):
        effects.clean_effects(invalid)


def test_stroke_validation_and_legacy_widget_order():
    from tb_stocking_test.nodes import NFStockingRender, NFStockingTexture
    assert NFStockingRender.INPUT_TYPES()["required"]["style"][0] == list(STYLES)
    assert list(NFStockingRender.INPUT_TYPES()["required"])[-1] == "seed"
    assert list(NFStockingTexture.INPUT_TYPES()["required"])[-1] == "failure_mode"
    assert list(NFStockingTexture.INPUT_TYPES()["optional"])[:6] == ["mask", "depth", "sparkle_mask", "sam", "sam3_model", "effects_json"]
    assert list(NFStockingRender.INPUT_TYPES()["optional"])[:2] == ["sparkle_mask", "effects_json"]
    image,_,doc = fixture()
    broken = copy.deepcopy(doc)
    broken["frames"][0]["regions"][0]["damage_strokes"] = [{"type":"ladder","points":[[-1,10]],"width":2}]
    with pytest.raises(ValueError,match="超出"):
        data.parse_guides(json.dumps(broken),*image.shape[:2],1)


def test_effect_cache_is_bounded_and_tiny_empty_inputs_are_safe():
    image,_,doc = fixture()
    _,_,fields = pipeline(image,doc)
    for size in range(25,125):
        render(image,fields["frames"][0],"leopard",{"pattern":{"size":size}})
    assert effects.EFFECT_CACHE.bytes <= effects.EFFECT_CACHE.max_bytes
    assert len(effects.EFFECT_CACHE._items) <= 8
    image,_,doc = fixture(h=1,w=1)
    doc["frames"][0]["regions"] = []
    _,_,fields = pipeline(image,doc)
    assert np.array_equal(render(image,fields["frames"][0],"polka")[0],image)


def test_combined_effects_keep_image_bound_damage_and_filtered_batch_indices():
    from tb_stocking_test.unified import process_batch, read_records, manual_frame
    image,_,doc = fixture(h=240,w=160)
    doc["frames"][0]["regions"][0]["damage_strokes"] = [{"type":"ladder","points":[[80,100]],"width":3}]
    records=json.dumps({"version":2,"records":{data.digest(image):doc}})
    blank=np.zeros_like(image)
    assert manual_frame(read_records(records),blank) is None
    params=dict(OFF,style="polka",effects_json=json.dumps({"text":{"enabled":True,"content":"PARIS"},"damage":{"enabled":True,"mode":"manual"}}))
    result=process_batch(np.stack([blank,image]),records,"manual",params)
    assert [(r["input_index"],r["output_index"]) for r in result[-1]] == [(0,None),(1,0)]
    assert result[-1][1]["damage_count"]==1
    assert np.array_equal(result[-2][0],image)


def test_long_damage_length_is_preserved_with_bounded_path_sampling():
    from types import SimpleNamespace
    scene=SimpleNamespace(w=100,h=1000,R=np.ones((1000,100),np.int8))
    field={"NX":np.zeros((1000,100)),"NY":np.ones((1000,100))}
    path=effects._follow(scene,field,50,100,600)
    assert len(path)<=129
    assert np.allclose(path[-1],[50,700])
