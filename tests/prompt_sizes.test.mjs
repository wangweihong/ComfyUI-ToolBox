import test from "node:test";
import assert from "node:assert/strict";
import { SIZE_PRESETS, DEFAULT_SIZE, sizeFilter, sizeSelection } from "../web/js/prompt_sizes.mjs";

test("each displayed ratio matches its actual pixel dimensions", () => {
    for (const [ratio, sizes] of Object.entries(SIZE_PRESETS)) {
        const [x,y] = ratio.split(":").map(Number);
        for (const [width,height] of sizes) {
            assert.equal(width * y, height * x, `${ratio}: ${width}×${height}`);
        }
    }
});

test("default size preserves existing metadata filter behavior", () => {
    assert.deepEqual(sizeFilter({ enabled:true, ...DEFAULT_SIZE }), { match_size:true, width:1024, height:768 });
    assert.deepEqual(sizeFilter({ enabled:false, ratio:"custom", width:0, height:"invalid" }), { match_size:false, width:1024, height:768 });
});

test("ratio choices resolve to exact pixels, and incompatible choices are rejected", () => {
    assert.deepEqual(sizeFilter({ enabled:true, ratio:"9:16", resolution:"864x1536" }), { match_size:true, width:864, height:1536 });
    assert.throws(() => sizeFilter({ enabled:true, ratio:"4:3", resolution:"864x1536" }), /有效尺寸/);
    assert.throws(() => sizeFilter({ enabled:true, ratio:"unknown", resolution:"1024x768" }), /有效尺寸/);
});

test("custom sizes accept arbitrary positive integer pairs within database limits", () => {
    assert.deepEqual(sizeFilter({ enabled:true, ratio:"custom", width:"1024", height:"769" }), { match_size:true, width:1024, height:769 });
    assert.deepEqual(sizeFilter({ enabled:true, ratio:"custom", width:1, height:16384 }), { match_size:true, width:1, height:16384 });
    for (const value of ["", 0, -1, 1.5, 16385, "not a number"]) {
        assert.throws(() => sizeFilter({ enabled:true, ratio:"custom", width:value, height:768 }), /自定义宽高/);
    }
});

test("editing preserves preset, non-preset and nonstandard existing dimensions", () => {
    for (const [width,height,ratio] of [[1024,768,"4:3"],[900,1200,"3:4"],[1024,769,"custom"]]) {
        const selection = sizeSelection(width,height);
        assert.equal(selection.ratio, ratio);
        assert.deepEqual(sizeFilter({ enabled:true, ...selection }), { match_size:true, width, height });
    }
});
