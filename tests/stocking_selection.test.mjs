import test from "node:test";
import assert from "node:assert/strict";
import { applyCandidate, selectionCoverage, maskBoundarySegments, splitRatio, compareKey, canvasMetrics } from "../web/js/stocking_selection.mjs";

const rgba = values => Uint8ClampedArray.from(values.flatMap(v => [v, v, v, 255]));

test("SAM preview matches explicit add/subtract application, including external MASK and soft erasing", () => {
    for (const subtract of [false, true]) {
        const paint = rgba([0, 200, 255, 25]), erase = rgba([0, 128, 255, 0]);
        const external = rgba([128, 128, 255, 0]), candidate = rgba([255, 0, 255, 0]);
        const beforePaint = paint.slice(), beforeErase = erase.slice();
        const projected = selectionCoverage(paint, erase, external, candidate, subtract);
        assert.deepEqual(paint, beforePaint); assert.deepEqual(erase, beforeErase);
        applyCandidate(paint, erase, candidate, subtract);
        assert.deepEqual(projected, selectionCoverage(paint, erase, external));
        assert.deepEqual(Array.from(projected), subtract ? [0, 100, 0, 25] : [255, 100, 255, 25]);
    }
});

test("switching candidates never accumulates masks or changes the draft", () => {
    const paint = rgba([0, 0, 255]), erase = rgba([0, 0, 0]);
    const small = rgba([255, 0, 0]), large = rgba([255, 255, 0]);
    const before = paint.slice(), first = selectionCoverage(paint, erase, null, small);
    assert.deepEqual(Array.from(selectionCoverage(paint, erase, null, large)), [255, 255, 255]);
    assert.deepEqual(selectionCoverage(paint, erase, null, small), first);
    assert.deepEqual(paint, before);
    // A later brush stroke survives application; it is not replaced by an old snapshot.
    paint[4] = paint[5] = paint[6] = 77;
    applyCandidate(paint, erase, small, false);
    assert.deepEqual(Array.from(selectionCoverage(paint, erase)), [255, 77, 255]);
});

test("mask outline encloses image edges and internal holes without joining disjoint selections", () => {
    const segments = Array.from(maskBoundarySegments(Uint8Array.from([255, 0, 255]), 3, 1));
    assert.deepEqual(segments, [[0, 0, 1, 0], [2, 0, 3, 0], [0, 1, 1, 1], [2, 1, 3, 1], [0, 0, 0, 1], [1, 0, 1, 1], [2, 0, 2, 1], [3, 0, 3, 1]]);
    assert.deepEqual(Array.from(maskBoundarySegments(new Uint8Array(4), 2, 2)), []);
});

test("comparison divider uses viewport CSS coordinates independently of image zoom and screen scaling", () => {
    for (const width of [300, 600, 1200]) {
        const rect = { left: 50, width };
        assert.equal(splitRatio(50 + width / 2, rect), 0.5);
        assert.equal(splitRatio(50 - 20, rect), 0);
        assert.equal(splitRatio(50 + width + 20, rect), 1);
    }
});

test("comparison keyboard reaches exact endpoints and clamps arrows", () => {
    assert.equal(compareKey(0.5, "Home"), 0);
    assert.equal(compareKey(0.5, "End"), 1);
    assert.equal(compareKey(0, "ArrowLeft"), 0);
    assert.equal(compareKey(1, "ArrowRight"), 1);
    assert.equal(compareKey(0.5, "ArrowRight"), 0.51);
    assert.equal(compareKey(0.5, "Escape"), null);
});

test("fractional viewports at DPI 1, 1.25 and 2 preserve CSS pointer coordinates", () => {
    const sizes = [[1, 1007, 366], [1.25, 1259, 458], [2, 2014, 733]];
    for (const [dpr, width, height] of sizes) {
        const m = canvasMetrics(1006.8, 366.3, dpr);
        assert.equal(m.width, width); assert.equal(m.height, height);
        // Drawing a point into the raster and displaying it at the CSS size
        // must land on the same CSS coordinate used by mouse events.
        assert.ok(Math.abs(300.3 * m.scaleX * 1006.8 / width - 300.3) < 1e-9);
        assert.ok(Math.abs(155.7 * m.scaleY * 366.3 / height - 155.7) < 1e-9);
    }
    assert.deepEqual(canvasMetrics(0, 0, 1), { width: 1, height: 1, scaleX: 1, scaleY: 1 });
});

test("invalid candidate dimensions cannot partially mutate an applied mask", () => {
    const paint = rgba([0, 20]), erase = rgba([0, 0]), original = paint.slice();
    assert.throws(() => applyCandidate(paint, erase, rgba([255]), false), /尺寸/);
    assert.deepEqual(paint, original);
});
