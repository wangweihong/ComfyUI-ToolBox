import test from "node:test";
import assert from "node:assert/strict";
import { parameterPatch } from "../web/js/stocking_render_controls.mjs";

test("manual strength overrides auto without changing independent sparkle sources", () => {
    const state = { strength: 100, strength_auto: true, sparkle_bright: 80, sparkle_even: 120 };
    Object.assign(state, parameterPatch("strength", "160"));
    assert.deepEqual(state, { strength: 160, strength_auto: false, sparkle_bright: 80, sparkle_even: 120 });
    Object.assign(state, parameterPatch("strength_auto", true));
    assert.equal(state.strength_auto, true);
    assert.equal(state.strength, 160);
});

test("numeric controls keep valid values when cleared or invalid and clamp committed limits", () => {
    for (const input of ["", " ", "abc", "NaN", "Infinity"]) assert.equal(parameterPatch("density", input), null);
    assert.deepEqual(parameterPatch("density", "39"), { density: 40 });
    assert.deepEqual(parameterPatch("density", "201"), { density: 200 });
    assert.deepEqual(parameterPatch("tilt", "80"), { tilt: 75 });
    assert.deepEqual(parameterPatch("sparkle_even", "305"), { sparkle_even: 300 });
});
