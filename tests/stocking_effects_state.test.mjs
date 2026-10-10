import test from "node:test";
import assert from "node:assert/strict";
import { readEffects, effectPatch, damageStroke, upgradeEffectsValue } from "../web/js/stocking_effects_state.mjs";
import { STYLE_REGISTRY } from "../web/js/stocking_style_registry.mjs";
import { GuideDraft } from "../web/js/stocking_editor_state.mjs";
import { recordsForSave } from "../web/js/stocking_unified_state.mjs";
import { translate } from "../web/js/stocking_i18n.mjs";

test("thirteen styles retain the original IDs and effects default to disabled", () => {
    assert.equal(STYLE_REGISTRY.length,13);
    assert.deepEqual(STYLE_REGISTRY.slice(0,5).map(s=>s.id),["knit","loops","lines","grain","oily"]);
    const a = readEffects(); a.text.content = "Changed";
    assert.equal(readEffects().text.content,"BALENCIAGA");
    assert.equal(readEffects().damage.enabled,false);
});

test("legacy summary widgets cannot shift into the optional effects input",()=>{
    assert.equal(upgradeEffectsValue("手工 / 原有点选 · 细线 · 自动强度"),"{}");
    assert.equal(upgradeEffectsValue(null),"{}");
    assert.equal(upgradeEffectsValue('{"text":{"enabled":true}}'),'{"text":{"enabled":true}}');
    assert.equal(upgradeEffectsValue("invalid-json"),"invalid-json");
});

test("all pattern labels and hints translate without changing style IDs",()=>{
    for (const style of STYLE_REGISTRY) {
        assert.equal(translate(style.label,"en"),style.label_en);
        assert.equal(translate(style.hint,"en"),style.hint_en);
    }
    assert.equal(translate("损伤方式","en"),"Damage placement");
});

test("effect controls preserve letter case, clamp numbers and reject unsupported text", () => {
    const raw = effectPatch("{}","text","content","My Brand 2026!");
    assert.equal(readEffects(raw).text.content,"My Brand 2026!");
    assert.equal(effectPatch(raw,"text","content","中文"),null);
    assert.equal(effectPatch(raw,"text","content","a".repeat(129)),null);
    assert.equal(effectPatch(raw,"pattern","size",""),null);
    assert.equal(readEffects(effectPatch(raw,"pattern","size",999)).pattern.size,400);
});

test("manual damage is a cancellable image-specific draft and survives explicit save", () => {
    const original = {version:1,width:100,height:200,frames:[{regions:[{id:"a",name:"left",damage_strokes:[]} ]},{regions:[{id:"b",name:"right",damage_strokes:[]} ]}]};
    const draft = new GuideDraft("{}","per_image",original);
    draft.doc.frames[1].regions[0].damage_strokes.push(damageStroke([[30,50],[32,90]],"ladder",3));
    assert.equal(original.frames[1].regions[0].damage_strokes.length,0);
    const stored = JSON.parse(recordsForSave("{}",draft.doc,["first","second"],original));
    assert.deepEqual(Object.keys(stored.records),["second"]);
    assert.equal(stored.records.second.frames[0].regions[0].damage_strokes[0].type,"ladder");
    const before = JSON.stringify(draft.doc);
    draft.doc.frames[1].regions[0].damage_strokes.pop();
    draft.doc = JSON.parse(before);
    assert.equal(draft.doc.frames[1].regions[0].damage_strokes.length,1);
});
