import test from 'node:test';
import assert from 'node:assert/strict';
import {SCHEMA,normalizeEffects,cleanEffects,cleanV2,cleanOverride} from '../web/js/stocking_config.mjs';
import {GuideDraft} from '../web/js/stocking_editor_state.mjs';
import {recordsForSave} from '../web/js/stocking_unified_state.mjs';
test('V1 migration retains pattern and text ordering and fabric mode without rewriting input',()=>{
    const raw=JSON.stringify({text:{enabled:true,content:'PARIS'}}),n=normalizeEffects('lace',raw);
    assert.equal(n.style,'knit');assert.deepEqual(n.effects.layers.map(l=>l.type),['pattern','text']);
    assert.equal(n.effects.layers[1].params.mode,'fabric');assert.equal(n.effects.sampling,'v1');assert.equal(JSON.parse(raw).version,undefined);
});
test('independent layers retain ids and reject future types and duplicate ids',()=>{
    const l={id:'a',type:'text',params:{content:'Paris!',enabled:true,mode:'print'}};
    const c=cleanV2({version:2,layers:[l]});assert.equal(c.layers[0].params.content,'Paris!');
    assert.throws(()=>cleanV2({version:2,layers:[l,l]}));assert.throws(()=>cleanEffects({version:3}));
    assert.throws(()=>cleanV2({version:2,layers:[{...l,type:'asset'}]}));assert.equal(SCHEMA.max_layers,16);
});
test('region overrides replace layers and survive draft save while cancel preserves the node',()=>{
    const doc={version:1,width:80,height:120,frames:[{regions:[{id:'leg',name:'leg',mask:'',strokes:[],walls:[]}]}]};
    const original=JSON.stringify(doc),draft=new GuideDraft(original,'shared',doc);
    draft.doc.frames[0].regions[0].material=cleanOverride({params:{style:'coil'},layers:[]});
    assert.equal(JSON.parse(original).frames[0].regions[0].material,undefined);
    const saved=JSON.parse(recordsForSave('{}',draft.doc,['image']));assert.deepEqual(saved.records.image.frames[0].regions[0].material.layers,[]);
    assert.throws(()=>cleanOverride({params:{seed:5}}));
});

test('regional damage inherits layers and changing a layer keeps damage inherited',async()=>{
 const {createMaterialControls}=await import('../web/js/stocking_material_controls.mjs');
 const region={id:'left'};
 const C=createMaterialControls({el:()=>{},globalValue:(_n,k,f)=>f,setValue:()=>{throw new Error('Node must not be written');}});
 const ui=new C();Object.assign(ui,{node:{},payload:{},materialScope:'region',region:()=>region,remember:()=>{},updateDraft:()=>{},draft:{},refreshEffectControls:()=>{}});
 ui.changeEffect('damage','strength',25);
 assert.deepEqual(region.material,{params:{},damage:{strength:25}});
 ui.setMaterialEffects({version:2,layers:[{id:'a',type:'text',params:{content:'PARIS'}}]});
 assert.equal(region.material.layers.length,1);assert.deepEqual(region.material.damage,{strength:25});
 const untouched={id:'right'};ui.region=()=>untouched;ui.setMaterialEffects({version:2,layers:[]});
 assert.equal('damage' in untouched.material,false);
});

test('connected global material cannot change effects while region edits remain available',async()=>{
 const {createMaterialControls}=await import('../web/js/stocking_material_controls.mjs');
 const C=createMaterialControls({el:()=>{},globalValue:(_n,k,f)=>f,setValue:()=>{throw new Error('Connected node is read-only');}});
 const ui=new C();Object.assign(ui,{node:{},payload:{material_connected:true},materialScope:'global'});
 assert.equal(ui.materialReadOnly(),true);ui.setMaterialEffects({version:2,layers:[]});
 ui.materialScope='region';assert.equal(ui.materialReadOnly(),false);
});
