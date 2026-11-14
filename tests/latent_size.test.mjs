import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../web/js/zimage_logic.js", import.meta.url), "utf8")
    .replace('import { app } from "../../../scripts/app.js";', "");
const ratioData = {
    "1:1 方图": ["1440 x 1440", "8192 x 8192"],
    "16:9 横屏": ["1920 x 1088", "7680 x 4320"],
    "32:9 横屏": ["4096 x 1152", "8192 x 2304"],
};

async function setup(auto = false) {
    let extension;
    const callbacks = [];
    const hooks = [];
    const app = { registerExtension: value => { extension = value; } };
    const document = { createElement: () => ({ style: {}, setAttribute() {} }) };
    vm.runInNewContext(source, { app, document, setTimeout: fn => callbacks.push(fn) });
    class Node {
        constructor() {
            this.size = [350, 300];
            const values = auto
                ? { source_width: 1024, source_height: 1024, ratio: "保持原图比例", size_mode: "按倍数缩放", scale_by: 1, long_edge: 2048, alignment: "1" }
                : { ratio: "1:1 方图", resolution: "1440 x 1440", custom_width: 1024, custom_height: 1024 };
            this.widgets = Object.entries(values).map(([name, value]) => ({ name, value, type: "number", options: {}, computeSize: () => [200, 20] }));
        }
        onNodeCreated() { hooks.push("created"); return 17; }
        onConfigure() { hooks.push("configure"); }
        onExecuted() { hooks.push("executed"); }
        onSerialize() { hooks.push("serialize"); }
        computeSize() { return [350, 300]; }
        setSize(value) { this.size = value; }
        setDirtyCanvas() {}
        addDOMWidget(name, type, element, options) {
            const widget = { name, type, element, options };
            this.widgets.push(widget);
            return widget;
        }
    }
    await extension.beforeRegisterNodeDef(Node, {
        name: auto ? "ToolBoxLatentSizeAuto" : "ToolBoxLatentSize",
        input: { required: { resolution: [[], { toolbox_ratio_data: ratioData }] } },
    });
    const node = new Node();
    assert.equal(node.onNodeCreated(), 17);
    callbacks.forEach(fn => fn());
    return { node, hooks, widget: name => node.widgets.find(item => item.name === name) };
}

test("server presets drive larger resolutions and new ratios", async () => {
    const { node, widget } = await setup();
    widget("ratio").value = "32:9 横屏";
    widget("ratio").callback();
    assert.deepEqual(widget("resolution").options.values, ratioData["32:9 横屏"]);
    assert.equal(widget("resolution").value, "4096 x 1152");
    widget("resolution").value = "8192 x 2304";
    node.onConfigure();
    assert.equal(widget("resolution").value, "8192 x 2304");
});

test("old workflows restore resolution and normalize legacy English ratio names", async () => {
    const { node, widget } = await setup();
    widget("ratio").value = "16:9 wide";
    widget("resolution").value = "7680 x 4320";
    node.onConfigure();
    assert.equal(widget("ratio").value, "16:9 横屏");
    assert.equal(widget("resolution").value, "7680 x 4320");
    assert.deepEqual(widget("resolution").options.values, ratioData["16:9 横屏"]);
});

test("custom dimensions retain their values through hiding and reloading", async () => {
    const { node, widget } = await setup();
    widget("ratio").value = "自定义尺寸";
    widget("custom_width").value = 16384;
    node.onConfigure();
    assert.equal(widget("resolution").hidden, true);
    assert.equal(widget("custom_width").hidden, false);
    assert.equal(widget("custom_width").value, 16384);
    widget("ratio").value = "1:1 方图";
    widget("ratio").callback();
    assert.equal(widget("resolution").hidden, false);
    assert.equal(widget("custom_width").hidden, true);
    assert.equal(widget("custom_width").value, 16384);
});

test("pixel count updates immediately on ratio, resolution and custom dimension changes", async () => {
    const { node, widget } = await setup();
    assert.match(node.toolboxSizeStatus.value, /207\.4 万像素（2\.07 MP）/);
    widget("ratio").value = "16:9 横屏";
    widget("ratio").callback();
    assert.match(node.toolboxSizeStatus.value, /1920×1088.*208\.9 万像素（2\.09 MP）/);
    widget("resolution").value = "7680 x 4320";
    widget("resolution").callback();
    assert.match(node.toolboxSizeStatus.value, /3317\.8 万像素（33\.18 MP）/);
    widget("ratio").value = "自定义尺寸";
    widget("ratio").callback();
    widget("custom_width").value = 16384;
    widget("custom_width").callback();
    assert.match(node.toolboxSizeStatus.value, /1677\.7 万像素（16\.78 MP）/);
    widget("custom_height").value = 8192;
    widget("custom_height").callback();
    assert.match(node.toolboxSizeStatus.value, /13421\.8 万像素（134\.22 MP）/);
    const values = ["自定义尺寸", "7680 x 4320", 16384, 8192];
    const info = { widgets_values: [...values, "pixel status"] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, values);
    assert.equal(node.widgets.at(-1).serialize, false);
});

test("auto node exposes only the active adjustment and restores it on load", async () => {
    const { node, widget, hooks } = await setup(true);
    assert.equal(widget("scale_by").hidden, false);
    assert.equal(widget("long_edge").hidden, true);
    widget("size_mode").value = "指定长边";
    node.onConfigure();
    assert.equal(widget("scale_by").hidden, true);
    assert.equal(widget("long_edge").hidden, false);
    widget("size_mode").value = "按倍数缩放";
    widget("size_mode").callback();
    assert.equal(widget("scale_by").type, "number");
    assert.equal(widget("scale_by").hidden, false);
    assert.deepEqual(hooks, ["created", "configure"]);
});

test("execution shows the actual output without serializing status as an input", async () => {
    const { node, hooks } = await setup(true);
    node.onExecuted({ text: ["原图 1001×777", "输出 4004×3108"] });
    assert.equal(node.toolboxSizeStatus.value, "原图 1001×777\n输出 4004×3108");
    assert.equal(node.toolboxSizeStatus.readOnly, true);
    assert.equal(node.widgets.at(-1).serialize, false);
    assert.equal(node.widgets.at(-1).serializeValue(), undefined);
    const values = [1024, 1024, "保持原图比例", "按倍数缩放", 4, 2048, "1"];
    const info = { widgets_values: [...values, "status"] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, values);
    assert.deepEqual(hooks, ["created", "executed", "serialize"]);
});
