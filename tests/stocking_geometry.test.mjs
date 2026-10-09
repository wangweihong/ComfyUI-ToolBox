import test from "node:test";
import assert from "node:assert/strict";
import { fitView, imagePoint, zoomAt, isCurrent } from "../web/js/stocking_geometry.mjs";

test("image coordinates remain correct with fit, pan and screen offsets", () => {
    const view = fitView(1280, 1920, 960, 720);
    const rect = { left: 100, top: 55 };
    for (const [x, y] of [[0, 0], [640, 960], [1279, 1919]]) {
        const p = imagePoint(rect.left + view.x + x * view.scale, rect.top + view.y + y * view.scale, rect, view, 1280, 1920);
        assert.ok(Math.abs(p[0] - x) < 1e-8 && Math.abs(p[1] - y) < 1e-8);
    }
});

test("zoom preserves the image point beneath the cursor and clamps scale", () => {
    const view = { scale: 0.75, x: 20, y: 30 }, rect = { left: 0, top: 0 };
    const before = imagePoint(300, 400, rect, view, 1280, 1920);
    const after = imagePoint(300, 400, rect, zoomAt(view, 300, 400, 2), 1280, 1920);
    assert.deepEqual(before, after);
    assert.equal(zoomAt(view, 300, 400, 1000).scale, 16);
});

test("late or closed previews cannot replace newer data or another image", () => {
    assert.equal(isCurrent(2, 3, false, 0, 0), false);
    assert.equal(isCurrent(3, 3, true, 0, 0), false);
    assert.equal(isCurrent(3, 3, false, 0, 1), false);
    assert.equal(isCurrent(3, 3, false, 1, 1), true);
});
