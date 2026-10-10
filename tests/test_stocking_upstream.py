"""Upstream opt-in, editable guides, private persistence and PSD round trips."""
import copy
import json
import numpy as np
import pytest
from test_stocking_texture import fixture, pipeline, OFF
from tb_stocking_test import data, engine, editing, persistence, psd
from tb_stocking_test.upstream import look


def render(image, doc, **params):
    _, _, fields = pipeline(image, doc)
    f = fields["frames"][0]
    return engine.render_one(image, f, dict(OFF, renderer_version="upstream_f74c8ac", **params)), f


@pytest.mark.parametrize("style", ["coil", "knit", "loops", "lines", "grain", "oily", "lace"])
def test_new_renderer_crop_soft_layer_and_seed(style):
    image, mask, doc = fixture(h=360, w=240, light=.26, occlusion=True)
    (out, layer, alpha, _, info), f = render(image, doc, style=style, layer_mode="soft",
        effects_json=json.dumps({"text":{"enabled":True,"content":"PARIS"},"damage":{"enabled":True}}))
    assert np.array_equal(out[~mask], image[~mask])
    assert np.max(np.abs(layer * alpha[...,None] + image * (1-alpha[...,None]) - out)) <= 1e-6
    assert (alpha[~mask] == 0).all() and (layer[~mask] == 0).all()
    assert info["renderer_version"] == "upstream_f74c8ac" and info["changed_pixels"] > 0
    png_composite = data.rgb8(layer).astype(float) * alpha[...,None] + data.rgb8(image) * (1-alpha[...,None])
    assert np.max(np.abs(np.round(png_composite) - data.rgb8(out))) <= 1
    p = dict(OFF, renderer_version="upstream_f74c8ac", style=style, layer_mode="soft",
             effects_json=json.dumps({"text":{"enabled":True,"content":"PARIS"},"damage":{"enabled":True}}))
    crop = engine.render_one(image, f, p, rect=[40,80,180,280])[0]
    assert np.array_equal(crop, out[80:280,40:180])
    assert np.array_equal(out, engine.render_one(image,f,p)[0])


def test_moire_depth_strength_area_and_geometry():
    image, mask, doc = fixture(h=360,w=240)
    guides,_=engine.build_guides(image[None],data.dump_guides(doc))
    y,x=np.indices(mask.shape);depth=np.exp(-(((x-120)/65)**2+((y-180)/120)**2)).astype(np.float32)
    fields=engine.solve_one(image,doc["frames"][0],guides["masks"][0],depth)
    params=dict(OFF,renderer_version="upstream_f74c8ac",style="coil")
    plain=engine.render_one(image,fields,params)[0]
    full=engine.render_one(image,fields,dict(params,moire_on=True,moire=100,moire_area=100))[0]
    small=engine.render_one(image,fields,dict(params,moire_on=True,moire=100,moire_area=20))[0]
    weak=engine.render_one(image,fields,dict(params,moire_on=True,moire=20,moire_area=100))[0]
    assert len({data.digest(a) for a in (plain,full,small,weak)})==4
    assert np.array_equal(full[~mask],image[~mask])
    with pytest.raises(ValueError,match="深度"):
        render(image,doc,style="coil",moire_on=True)
    with pytest.raises(ValueError,match="新版渲染"):
        engine.render_one(image,fields,dict(OFF,style="coil"))


def test_coil_skin_visibility_and_glossy_occlusion_fill():
    image,mask,doc=fixture(h=360,w=240,light=.2,occlusion=True)
    (new,*_),f=render(image,doc,style="oily")
    old=engine.render_one(image,f,dict(OFF,style="oily"))[0]
    assert not np.array_equal(old,new)
    assert f["fill"] and any((m & ~mask).any() for m in f["fill"].values())
    scene=engine.scene_for(image,f,renderer_version="upstream_f74c8ac")
    assert scene.fill and len(scene.oily_maps())==7
    warm=image.copy();warm[...,0]+=.1;warm[...,2]-=.07
    a=look.skin_visibility(data.rgb8(image)[...,::-1],f["reg"],scene.alpha,.3)
    b=look.skin_visibility(data.rgb8(warm)[...,::-1],f["reg"],scene.alpha,.3)
    assert not np.array_equal(a,b)


def test_split_merge_paths_and_mirror_and_clear():
    image,mask,doc=fixture(h=360,w=240)
    frame=doc["frames"][0]
    frame["regions"][0]["damage_strokes"]=[dict(type="snag",width=3,points=[[110,80],[130,280]])]
    divided,info=editing.edit_frame(image,frame,None,"split","left",points=[[120,10],[120,350]])
    assert len(divided["regions"])==2
    masks=data.frame_masks(divided,*mask.shape)
    assert not ((masks[0]>.5)&(masks[1]>.5)).any()
    assert np.array_equal((masks[0]+masks[1])>.5,mask)
    for r,m in zip(divided["regions"],masks):
        for path in r["damage_strokes"]:
            xy=np.round(path["points"]).astype(int);assert (m[xy[:,1],xy[:,0]]>.5).all()
    mirrored,mi=editing.edit_frame(image,divided,None,"mirror",divided["regions"][0]["id"],divided["regions"][1]["id"])
    assert mi["strokes"]>0 and np.isfinite(mi["fit_error"])
    merged,_=editing.edit_frame(image,divided,None,"merge",divided["regions"][0]["id"],divided["regions"][1]["id"])
    assert len(merged["regions"])==1
    assert np.array_equal(data.frame_masks(merged,*mask.shape)[0]>.5,mask)
    empty,_=editing.edit_frame(image,merged,None,"clear",merged["regions"][0]["id"])
    assert len(empty["regions"])==1 and not data.frame_masks(empty,*mask.shape)[0].any()
    automatic,_=editing.edit_frame(image,frame,None,"split","left")
    assert len(automatic["regions"])==2


def test_presets_unknown_survive_read_and_user_isolation(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    params=dict(OFF,style="coil",renderer_version="upstream_f74c8ac",strength_auto=True,strength=41,
                effects_json=json.dumps({"text":{"enabled":True,"content":"PARIS"}}))
    assert persistence.presets(a,"save","My fabric",params)[0]["params"]["strength"]==100
    assert persistence.presets(b)==[]
    path=a/'presets.json';raw=json.loads(path.read_text());raw['future']={'future_parameter':1};path.write_text(json.dumps(raw));before=path.read_bytes()
    assert persistence.presets(a)[1]['params'] is None and path.read_bytes()==before
    assert persistence.presets(a,"delete","My fabric")==[{'name':'future','params':None}]


def test_auto_wall_deletion_persists_and_invalidates_only_geometry(monkeypatch):
    image,mask,doc=fixture(h=360,w=240)
    frame=doc['frames'][0];masks=data.frame_masks(frame,*mask.shape)
    def found(ridges,stock,scale):
        wall=np.zeros_like(stock,bool);wall[:,wall.shape[1]//2]=True;return wall
    monkeypatch.setattr(engine.walls,'find_walls',found)
    depth=np.indices(mask.shape)[0].astype(np.float32)/360
    before=engine.solve_one(image,frame,masks,depth)
    yy,xx=np.nonzero(before['auto_walls']);assert len(xx)>0
    frame['wall_erasures']=[[float(xx[len(xx)//2]),float(yy[len(yy)//2])]]
    after=engine.solve_one(image,frame,masks,depth)
    reopened=data.parse_guides(data.dump_guides(doc),*mask.shape,1)['frames'][0]
    again=engine.solve_one(image,reopened,masks,depth)
    assert not after['auto_walls'].any() and not again['auto_walls'].any()
    assert before['signature']!=after['signature'] and after['signature']==again['signature']


def test_overlays_and_option_validation():
    from tb_stocking_test.render_options import clean_options
    image,_,doc=fixture();_,_,fields=pipeline(image,doc)
    overlays=engine.guide_overlays(fields['frames'][0],dict(courses=True,wales=True,auto_walls=True))
    assert overlays['courses'] and overlays['wales']
    for value in (dict(moire=float('nan')),dict(moire_on='yes'),dict(layer_mode='future'),dict(renderer_version='future')):
        with pytest.raises(ValueError):clean_options(value)


def test_draft_round_trip_limits_and_ownership(tmp_path,monkeypatch):
    image,_,doc=fixture();identity=data.digest(image[None])
    session=dict(kind='unified',images=image[None],external=[None],depths=[None],painted=[None],settings=dict(OFF),revisions={},sam=object())
    state=dict(doc=doc,mode='shared',index=0,selected=0,settings=dict(OFF))
    persistence.save_draft(tmp_path,'editor',identity,session,state)
    restored=persistence.load_draft(tmp_path,'editor',identity)
    assert np.array_equal(restored['session']['images'],image[None]) and restored['state']==state
    assert 'sam' not in restored['session']
    assert persistence.load_draft(tmp_path,'other',identity) is None
    assert persistence.load_draft(tmp_path/'user2','editor',identity) is None
    monkeypatch.setattr(persistence,'MAX_DRAFTS',2)
    for i in range(3):persistence.save_draft(tmp_path,f'e{i}',identity,session,state)
    assert len(list((tmp_path/'drafts').glob('*.npz')))==2
    monkeypatch.setattr(persistence,'MAX_DRAFT_BYTES',1)
    with pytest.raises(ValueError,match='512 MiB'):persistence.save_draft(tmp_path,'big',identity,session,state)
    persistence.delete_draft(tmp_path,'e2',identity)
    assert persistence.load_draft(tmp_path,'e2',identity) is None


@pytest.mark.parametrize('english',[False,True])
@pytest.mark.parametrize('large',[False,True])
def test_psd_psb_round_trip_color_layers(tmp_path,english,large,monkeypatch):
    image,mask,doc=fixture();frame=doc['frames'][0];frame['regions'][0]['color']='#4080c0'
    frame['regions'][0]['walls']=[[[80,50],[80,190]]]
    sparkle=np.zeros(mask.shape,np.float32);sparkle[110:125,65:85]=.75
    module=psd.io_module()
    if english:monkeypatch.setattr(module,'tr',lambda x:module.both(x)[1])
    if large:
        original = module.PSDImage._make_header
        def header(*args, **kwargs):
            h = original(*args, **kwargs); h.version = 2; return h
        monkeypatch.setattr(module.PSDImage, '_make_header', header)
    path=tmp_path/('guides.psb' if large else 'guides.psd')
    psd.write(path,image,frame,sparkle=sparkle)
    im,advanced,records,sp=psd.read(path)
    assert np.array_equal(data.rgb8(im),data.rgb8(image))
    recovered=advanced['frames'][0]
    assert np.array_equal(data.frame_masks(recovered,*mask.shape)[0]>.5,mask)
    assert recovered['regions'][0]['color']=='#4080c0'
    assert recovered['regions'][0]['strokes'] and recovered['regions'][0]['walls']
    assert np.max(np.abs(sp-sparkle))<=1/255
    assert data.digest(im) in records['records']
