import test from "node:test";
import assert from "node:assert/strict";
import { recordsForSave, capturePrompt } from "../web/js/stocking_unified_state.mjs";

test("capture includes only dependencies and never downstream save nodes", () => {
    const graph = { "1": { class_type: "LoadImage", inputs: { image: "a.png" } },
        "2": { class_type: "ImageScale", inputs: { image: ["1", 0] } },
        "3": { class_type: "SaveImage", inputs: { images: ["2", 0] } } };
    const result = capturePrompt(graph, { images: ["2", 0] }, "capture");
    assert.deepEqual(Object.keys(result).sort(), ["1", "2", "capture"]);
    assert.equal(result.capture.class_type, "NFStockingPrepare");
    assert.equal(graph.capture, undefined);
});

test("identity records preserve other images and do not bind untouched frames", () => {
    const frame = { regions: [] }, doc = { version: 1, width: 80, height: 120, frames: [frame] };
    const unchanged = JSON.parse(recordsForSave("{}", doc, ["a"], doc));
    assert.deepEqual(unchanged.records, {});
    const old = JSON.stringify({ version: 2, records: { b: { test: true } } });
    const saved = JSON.parse(recordsForSave(old, doc, ["a"]));
    assert.equal(saved.records.b.test, true);
    assert.deepEqual(saved.records.a.frames, [frame]);
    assert.equal(saved.records.a.width, 80);
});

import { translate } from "../web/js/stocking_i18n.mjs";
test("localized labels do not change stored enum/style values", () => {
    assert.equal(translate("油光（试验）", "en"), "Oily (experimental)");
    assert.equal(translate("部位", "zh"), "部位");
    for (const key of ["knit", "loops", "lines", "grain", "oily", "semantic", "manual", "mask"])
        assert.equal(translate(key, "en"), key);
    assert.equal(translate("选区 9.00% · 实际变化 7.43% · 纹理已生效", "en"), "Selection 9.00% · Changed pixels 7.43% · Texture applied");
});

test("editing only the second image binds its frame and leaves the first image unrecorded", () => {
    const initial = { version: 1, width: 80, height: 120, frames: [{ regions: [] }, { regions: [] }] };
    const changed = structuredClone(initial);
    changed.frames[1].regions.push({ id: "second", mask: "saved-png", strokes: [] });
    const saved = JSON.parse(recordsForSave("{}", changed, ["first-image", "second-image"], initial));
    assert.deepEqual(Object.keys(saved.records), ["second-image"]);
    assert.equal(saved.records["second-image"].frames[0].regions[0].id, "second");
});
