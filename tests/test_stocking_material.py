import copy
import json
import numpy as np
import pytest
from test_stocking_texture import fixture,pipeline,OFF
from tb_stocking_test import data,engine,effects
from tb_stocking_test.config import normalize_effects,clean_effects,clean_override,SCHEMA
from tb_stocking_test.layer_renderer import SAMPLE_CACHE,DAMAGE_CACHE
from tb_stocking_test.material_nodes import NFStockingPatternLayer,NFStockingTextLayer,NFStockingLayerStack,NFStockingMaterial


@pytest.mark.parametrize('style',['knit','loops','lines','grain','oily','polka','hearts','diamonds','fishnet_small','fishnet_large','lace','floral','leopard','coil'])
@pytest.mark.parametrize('mode',['fabric','print'])
def test_v1_migration_is_pixel_identical(style,mode):
    image,mask,doc=fixture(h=360,w=240,occlusion=True)
    doc['frames'][0]['regions'][0]['damage_strokes']=[dict(type='ladder',points=[[120,160]],width=3)]
    _,_,fields=pipeline(image,doc);f=fields['frames'][0]
    cfg=dict(pattern=dict(mode=mode,rotation=15),text=dict(enabled=True,content='PARIS',rotation=-12),damage=dict(enabled=True,mode='both',strength=67))
    p=dict(OFF,style=style,renderer_version='upstream_f74c8ac' if style=='coil' else 'legacy',effects_json=json.dumps(cfg))
    old=engine.render_one(image,f,p)[0]
    base,new=normalize_effects(style,cfg)
    actual=engine.render_one(image,f,dict(p,style=base,effects_json=json.dumps(new)))[0]
    assert np.array_equal(actual,old),np.max(np.abs(actual-old))
    cropped=engine.render_one(image,f,dict(p,style=base,effects_json=json.dumps(new)),rect=[40,80,180,280])[0]
    assert np.array_equal(cropped,actual[80:280,40:180])


def layers():
    a=NFStockingPatternLayer().build(pattern='lace',unique_id='a')[0]
    b=NFStockingTextLayer().build(content='PARIS',enabled=True,color='#eeeedd',unique_id='b')[0]
    return [a,b]


def test_layers_order_disabled_and_material_nodes():
    image,mask,doc=fixture();_,_,fields=pipeline(image,doc);f=fields['frames'][0]
    ls=layers();material=NFStockingMaterial().build(style='coil',layers=ls)[0]
    p=dict(OFF,renderer_version='upstream_f74c8ac',material=material)
    out=engine.render_one(image,f,p)[0]
    material2=copy.deepcopy(material);material2['effects']['layers'].reverse()
    assert not np.array_equal(out,engine.render_one(image,f,dict(p,material=material2))[0])
    assert np.array_equal(out[~mask],image[~mask])
    stacked=NFStockingLayerStack().build(layer_1=ls[0],layer_2=ls[0])[0]
    assert len({l['id'] for l in stacked})==2
    for layer in material2['effects']['layers']:layer['params']['enabled']=False
    bare=engine.render_one(image,f,dict(material2['params'],renderer_version='upstream_f74c8ac'))[0]
    assert np.array_equal(bare,engine.render_one(image,f,dict(p,material=material2))[0])


def test_region_overrides_reuse_geometry_and_preserve_other_region():
    image,mask,doc=fixture(h=360,w=240)
    left=mask & (np.indices(mask.shape)[1]<120);right=mask & ~left
    r=doc['frames'][0]['regions'][0];r['mask']=data.encode_mask(left.astype(np.float32))
    other=copy.deepcopy(r);other.update(id='right',name='右腿',mask=data.encode_mask(right.astype(np.float32)))
    doc['frames'][0]['regions'].append(other)
    _,_,fields=pipeline(image,doc);f=fields['frames'][0]
    p=dict(OFF,style='knit',renderer_version='upstream_f74c8ac',layer_mode='soft')
    base=engine.render_one(image,f,p)[0]
    changed=copy.deepcopy(doc);changed['frames'][0]['regions'][0]['material']=dict(params=dict(style='coil'),layers=layers())
    _,_,newfields=pipeline(image,changed);new=newfields['frames'][0]
    assert new['signature']==f['signature'] and new['cache_misses']==0
    out,layer,alpha,_,info=engine.render_one(image,new,p)
    assert np.array_equal(out[right],base[right]) and not np.array_equal(out[left],base[left])
    assert np.max(np.abs(layer*alpha[...,None]+image*(1-alpha[...,None])-out))<=1e-6
    assert info['region_materials'][0]['style']=='coil'
    assert np.array_equal(engine.render_one(image,new,p,rect=[40,80,180,280])[0],out[80:280,40:180])


def test_sampling_cache_ignores_color_opacity_and_reorder():
    SAMPLE_CACHE.clear();DAMAGE_CACHE.clear()
    image,_,doc=fixture();_,_,fields=pipeline(image,doc);f=fields['frames'][0]
    cfg=dict(version=2,layers=layers());p=dict(OFF,effects_json=json.dumps(cfg))
    first=engine.render_one(image,f,p)[4]['effect_cache'];assert first['sample_misses']==2
    cfg['layers'][0]['params']['color']='#ffeecc';cfg['layers'][0]['params']['opacity']=32;cfg['layers'].reverse()
    second=engine.render_one(image,f,dict(p,effects_json=json.dumps(cfg)))[4]['effect_cache']
    assert second['sample_hits']==2 and second['sample_misses']==0
    assert SAMPLE_CACHE.bytes+DAMAGE_CACHE.bytes+effects.EFFECT_CACHE.bytes<=128*1024**2


def test_versions_limits_and_region_forbidden_globals():
    for cfg in (dict(version=3),dict(version=2,layers=layers()*9),dict(version=2,layers=[dict(id='future',type='asset',params={})])):
        with pytest.raises(ValueError):clean_effects(cfg)
    for params in (dict(seed=5),dict(renderer_version='legacy'),dict(layer_mode='soft')):
        with pytest.raises(ValueError):clean_override(dict(params=params))


def test_split_merge_and_draft_keep_material_ownership(tmp_path):
    from tb_stocking_test import editing,persistence
    image,_,doc=fixture(h=360,w=240);frame=doc['frames'][0]
    patch=dict(params=dict(style='coil'),layers=layers(),damage=dict(strength=25))
    frame['regions'][0]['material']=patch
    divided,_=editing.edit_frame(image,frame,None,'split','left',points=[[120,10],[120,350]])
    assert all(r['material']==patch for r in divided['regions'])
    divided['regions'][1]['material']['params']['style']='oily'
    assert divided['regions'][0]['material']['params']['style']=='coil'
    merged,_=editing.edit_frame(image,divided,None,'merge',divided['regions'][0]['id'],divided['regions'][1]['id'])
    assert merged['regions'][0]['material']['params']['style']=='oily'
    cfg=dict(version=2,layers=layers())
    doc['frames'][0]=divided
    state=dict(doc=doc,mode='shared',index=0,selected=0,settings=dict(OFF,effects_json=json.dumps(cfg)))
    session=dict(kind='unified',images=image[None],external=[None],depths=[None],painted=[None],settings=state['settings'],revisions={})
    identity=data.digest(image[None]);persistence.save_draft(tmp_path,'material',identity,session,state)
    assert persistence.load_draft(tmp_path,'material',identity)['state']==state
    assert persistence.load_draft(tmp_path,'material',data.digest(image[None] + .01)) is None


def test_cache_geometry_change_and_skip_preserve_pixels(monkeypatch):
    from tb_stocking_test.cache import SCENE_CACHE
    from tb_stocking_test.surface import context
    image,_,doc=fixture();_,_,fields=pipeline(image,doc);f=fields['frames'][0];cfg=dict(version=2,layers=layers());p=dict(OFF,effects_json=json.dumps(cfg))
    SAMPLE_CACHE.clear();effects.EFFECT_CACHE.clear();SCENE_CACHE.clear()
    before=engine.render_one(image,f,p)[0]
    cfg['layers'][0]['params']['size']=175
    info=engine.render_one(image,f,dict(p,effects_json=json.dumps(cfg)))[4]['effect_cache'];assert info['sample_hits']==1 and info['sample_misses']==1
    ctx,_=context(engine.scene_for(image,f),f);assert not ctx.horizontal.flags.writeable
    for cache in (SAMPLE_CACHE,DAMAGE_CACHE,effects.EFFECT_CACHE,SCENE_CACHE):
        cache.clear();monkeypatch.setattr(cache,'max_bytes',1)
    assert np.array_equal(before,engine.render_one(image,f,p)[0])
    assert all(c.bytes<=1 for c in (SAMPLE_CACHE,DAMAGE_CACHE,effects.EFFECT_CACHE,SCENE_CACHE))


def test_shared_node_schema_and_appended_material_input():
    from tb_stocking_test.nodes import NFStockingRender,NFStockingTexture
    from tb_stocking_test.material_nodes import inputs
    for cls in (NFStockingRender,NFStockingTexture):assert list(cls.INPUT_TYPES()['optional'])[-1]=='material'
    assert NFStockingPatternLayer.INPUT_TYPES()['required']==inputs(SCHEMA['groups']['pattern'])
    assert NFStockingMaterial.INPUT_TYPES()['required']==inputs(SCHEMA['appearance'])


def test_v2_batch_failure_keeps_original_success_index():
    from tb_stocking_test.unified import process_batch
    image,_,doc=fixture();other=image.copy();other[...,0]+=.01
    records={'version':2,'records':{data.digest(other):doc}}
    cfg=dict(version=2,layers=layers())
    result=process_batch(np.stack([image,other]),json.dumps(records),'manual',dict(OFF,effects_json=json.dumps(cfg)),failure_mode='skip')
    assert len(result[0])==1 and np.array_equal(result[5][0],other)
    assert result[6][0]['output_index'] is None
    assert result[6][1]['input_index']==1 and result[6][1]['output_index']==0
