import test from "node:test";
import assert from "node:assert/strict";
import { GuideDraft, samHint } from "../web/js/stocking_editor_state.mjs";

const document = () => ({ version: 1, width: 100, height: 200,
    frames: [{ regions: [{ id: "left", name: "左腿", mask: "", erase: "", strokes: [], walls: [] }] }] });

test("canceling edits leaves saved masks, guides and mode unchanged", () => {
    const nodeInputs = { guides_json: JSON.stringify(document()), batch_mode: "shared" };
    const original = structuredClone(nodeInputs);
    const draft = new GuideDraft(nodeInputs.guides_json, nodeInputs.batch_mode, document());
    draft.doc.frames[0].regions[0].mask = "new-mask";
    draft.doc.frames[0].regions[0].strokes.push([[1, 2], [3, 4]]);
    draft.mode = "per_image";
    assert.equal(draft.dirty, true);
    // Closing without save never calls the writer; a new editor reads saved inputs.
    const reopened = new GuideDraft(nodeInputs.guides_json, nodeInputs.batch_mode, document());
    assert.deepEqual(nodeInputs, original);
    assert.equal(reopened.doc.frames[0].regions[0].mask, "");
    assert.deepEqual(reopened.doc.frames[0].regions[0].strokes, []);
    assert.equal(reopened.mode, "shared");
});

test("explicit save persists both document and batch mode", () => {
    const inputs = { guides_json: "{}", batch_mode: "shared" };
    const draft = new GuideDraft(inputs.guides_json, inputs.batch_mode, document());
    draft.doc.frames[0].regions[0].walls.push([[5, 6], [7, 8]]);
    draft.mode = "per_image";
    draft.save((key, val) => inputs[key] = val);
    const reopened = new GuideDraft(inputs.guides_json, inputs.batch_mode, document());
    assert.deepEqual(reopened.doc.frames[0].regions[0].walls, [[[5, 6], [7, 8]]]);
    assert.equal(reopened.mode, "per_image");
    assert.equal(draft.dirty, false);
});

test("an empty widget's fallback document is not mutated by a draft", () => {
    const fallback = document(), original = structuredClone(fallback);
    const draft = new GuideDraft("{}", "shared", fallback);
    draft.doc.frames[0].regions[0].name = "重命名";
    assert.deepEqual(fallback, original);
    assert.equal(draft.dirty, true);
    draft.doc.frames[0].regions[0].name = "左腿";
    assert.equal(draft.dirty, false);
});

test("SAM hints distinguish unconnected, pending and ready models", () => {
    assert.match(samHint(false), /未连接 SAM/);
    assert.match(samHint(false), /sam 输入/);
    assert.match(samHint(false, true), /重新执行/);
    assert.match(samHint(true, true), /左键添加，右键减去/);
});
