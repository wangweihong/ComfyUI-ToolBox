import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { predictSize, roundEven } from "../web/js/image_scale_view.mjs";

test("previews preserve native half-even rounding and alignment behavior", () => {
    assert.equal(roundEven(16.5), 16);
    assert.equal(roundEven(15.5), 16);
    assert.deepEqual(predictSize([33, 17], {resize_type: "scale by multiplier", multiplier: .5}).output, [16, 8]);
    assert.deepEqual(predictSize([1600, 900], {resize_type: "scale width", width: 800}, 32).output, [800, 448]);
    assert.deepEqual(predictSize([1500, 1000], {resize_type: "scale to multiple", multiple: 32}).output, [1472, 992]);
    assert.deepEqual(predictSize([31, 17], {resize_type: "scale to multiple", multiple: 32}).output, [31, 17]);
    assert.deepEqual(predictSize([1024, 1024], {resize_type: "scale total pixels", megapixels: 16}, 32).output, [4096, 4096]);
    assert.equal(predictSize([1600, 900], {resize_type: "match size"}), null);
    assert.equal(predictSize([1, 100], {resize_type: "scale by multiplier", multiplier: .01}), null);
});

test("optional native integration reports agree with the live preview for every mode", { skip: !process.env.SCALE_NATIVE_REPORT }, () => {
    const report = JSON.parse(readFileSync(process.env.SCALE_NATIVE_REPORT, "utf8"));
    assert.equal(report.ok, true);
    for (const row of report.cases) {
        const predicted = predictSize(row.source, row.parameters, row.multiple_of, row.match);
        assert.deepEqual(predicted.output, row.output, JSON.stringify(row));
        assert.deepEqual(predicted.resized, row.resized, JSON.stringify(row));
    }
});
