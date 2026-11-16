import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../web/js/zimage_logic.js", import.meta.url), "utf8")
    .replace('import { app } from "../../../scripts/app.js";', "");
const legacyRatioData = { "16:9 横屏": ["1920 x 1088"], "9:16 竖屏": ["1088 x 1920"] };
const ratioData = {
    "1:1 方图": ["1440 x 1440", "8192 x 8192"],
    "16:9 横屏": ["1920 x 1080", "7680 x 4320"],
    "32:9 横屏": ["4096 x 1152", "8192 x 2304"],
    "9:16 竖屏": ["1080 x 1920", "1440 x 2560"],
    "9:32 竖屏": ["1152 x 4096", "2304 x 8192"],
};

async function setup(auto = false, reactiveVisibility = false) {
    let extension;
    const callbacks = [];
    const hooks = [];
    const app = { registerExtension: value => { extension = value; } };
    const document = {
        createElement: tagName => ({
            tagName, style: {}, children: [], attributes: {},
            setAttribute(name, value) { this.attributes[name] = value; },
            append(...elements) { this.children.push(...elements); },
        }),
    };
    vm.runInNewContext(source, { app, document, setTimeout: fn => callbacks.push(fn) });
    class Node {
        constructor() {
            this.size = [350, 300];
            const values = auto
                ? { source_width: 1024, source_height: 1024, ratio: "保持原图比例", size_mode: "按倍数缩放", scale_by: 1, long_edge: 2048, alignment: "1" }
                : { ratio: "1:1 方图", resolution: "1440 x 1440", custom_width: 1024, custom_height: 1024 };
            this.widgets = Object.entries(values).map(([name, value]) => ({ name, value, type: "number", options: {}, computeSize: () => [200, 20] }));
            if (reactiveVisibility) {
                // Modern ComfyUI reapplies options.hidden when changing widget type.
                for (const widget of this.widgets) {
                    let type = widget.type;
                    let hidden = false;
                    Object.defineProperties(widget, {
                        type: {
                            get: () => type,
                            set(value) { type = value; hidden = value === "toolboxHidden" || Boolean(widget.options.hidden); },
                        },
                        hidden: {
                            get: () => hidden,
                            set(value) { hidden = value; if (type !== "toolboxHidden") widget.options.hidden = value; },
                        },
                    });
                }
            }
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
        input: { required: { resolution: [[], { toolbox_ratio_data: ratioData, toolbox_legacy_ratio_data: legacyRatioData }] } },
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

test("modern widget setters restore editable custom dimensions and the preset selector", async () => {
    const { node, widget } = await setup(false, true);
    for (let count = 0; count < 3; count++) {
        widget("ratio").value = "自定义尺寸";
        widget("ratio").callback();
        for (const name of ["custom_width", "custom_height"]) {
            assert.equal(widget(name).type, "number");
            assert.equal(widget(name).hidden, false);
            assert.equal(widget(name).options.hidden, false);
            assert.equal(widget(name).computeSize()[1], 20);
        }
        assert.equal(widget("resolution").hidden, true);
        widget("custom_width").value = 2048;
        widget("custom_width").callback();
        widget("custom_height").value = 1536;
        widget("custom_height").callback();
        assert.equal(node.toolboxSizePreview.widthLabel.textContent, "2048 px");
        assert.equal(node.toolboxSizePreview.heightLabel.textContent, "1536 px");
        node.onConfigure();
        assert.equal(widget("custom_width").hidden, false);
        assert.equal(widget("custom_height").hidden, false);
        widget("ratio").value = "16:9 横屏";
        widget("ratio").callback();
        assert.equal(widget("resolution").hidden, false);
        assert.equal(widget("resolution").options.hidden, false);
        assert.equal(widget("custom_width").hidden, true);
        assert.equal(widget("custom_height").hidden, true);
    }
});

test("restoring old aligned dimensions preserves output until a new preset is selected", async () => {
    const { node, widget } = await setup();
    widget("ratio").value = "16:9 wide";
    widget("resolution").value = "1920 x 1088";
    node.onConfigure();
    assert.equal(widget("ratio").value, "16:9 横屏");
    assert.equal(widget("resolution").value, "1920 x 1088");
    assert.deepEqual(widget("resolution").options.values, [...ratioData["16:9 横屏"], "1920 x 1088"]);
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "1088 px");
    assert.match(node.toolboxSizePreview.label.textContent, /旧版尺寸/);
    node.toolboxUpdateSizeWidgets();
    assert.equal(widget("resolution").value, "1920 x 1088");
    const values = ["16:9 横屏", "1920 x 1088", 1024, 1024];
    const info = { widgets_values: [...values, "preview"] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, values);
    widget("resolution").value = "1920 x 1080";
    widget("resolution").callback();
    assert.deepEqual(widget("resolution").options.values, ratioData["16:9 横屏"]);
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "1080 px");
    assert.doesNotMatch(node.toolboxSizePreview.label.textContent, /旧版尺寸/);
    widget("ratio").value = "9:16 竖屏";
    widget("ratio").callback();
    assert.equal(widget("resolution").value, "1080 x 1920");
});

test("pixel count updates immediately on ratio, resolution and custom dimension changes", async () => {
    const { node, widget } = await setup();
    assert.match(node.toolboxSizeStatus.value, /207\.4 万像素（2\.07 MP）/);
    widget("ratio").value = "16:9 横屏";
    widget("ratio").callback();
    assert.match(node.toolboxSizeStatus.value, /1920×1080.*207\.4 万像素（2\.07 MP）/);
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

test("preview and edge labels use exact standard presets", async () => {
    const { node, widget } = await setup();
    const { frame, label } = node.toolboxSizePreview;
    assert.equal(frame.hidden, false);
    assert.equal(frame.style.aspectRatio, "1 / 1");
    for (const ratio of ["16:9 横屏", "9:16 竖屏", "32:9 横屏", "9:32 竖屏"]) {
        widget("ratio").value = ratio;
        widget("ratio").callback();
        const [width, height] = ratio.split(" ")[0].split(":").map(Number);
        assert.equal(frame.style.aspectRatio, `${width} / ${height}`);
        assert.equal(frame.style.width, `min(100%, ${118 * width / height}px)`);
        assert.match(label.textContent, /比例示意/);
        assert.match(label.title, /实际输出尺寸以像素标注为准/);
    }
    widget("ratio").value = "16:9 横屏";
    widget("ratio").callback();
    assert.equal(frame.style.aspectRatio, "16 / 9");
    assert.match(node.toolboxSizeStatus.value, /1920×1080 px/);
    assert.equal(node.toolboxSizePreview.widthLabel.textContent, "1920 px");
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "1080 px");
    widget("resolution").value = "7680 x 4320";
    widget("resolution").callback();
    assert.equal(frame.style.aspectRatio, "16 / 9");
    assert.match(node.toolboxSizeStatus.value, /7680×4320 px/);
    assert.equal(node.toolboxSizePreview.widthLabel.textContent, "7680 px");
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "4320 px");
});

test("custom preview follows edits, hides invalid dimensions and recovers", async () => {
    const { node, widget } = await setup();
    const { frame, label } = node.toolboxSizePreview;
    widget("ratio").value = "自定义尺寸";
    widget("ratio").callback();
    widget("custom_width").value = 2048;
    widget("custom_width").callback();
    assert.equal(frame.style.aspectRatio, "2048 / 1024");
    widget("custom_height").value = 4096;
    widget("custom_height").callback();
    assert.equal(frame.style.aspectRatio, "2048 / 4096");
    assert.equal(node.toolboxSizePreview.widthLabel.textContent, "2048 px");
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "4096 px");
    assert.equal(label.textContent, "自定义比例");
    assert.equal(label.title, "");
    for (const value of [0, -8, NaN, Infinity]) {
        widget("custom_width").value = value;
        widget("custom_width").callback();
        assert.equal(frame.hidden, true);
        assert.equal(node.toolboxSizePreview.widthLabel.textContent, "");
        assert.equal(node.toolboxSizePreview.heightLabel.textContent, "");
        assert.equal(node.toolboxSizeStatus.value, "请选择有效尺寸");
    }
    widget("custom_width").value = 8192;
    widget("custom_width").callback();
    assert.equal(frame.hidden, false);
    assert.equal(frame.style.aspectRatio, "8192 / 4096");
    assert.equal(node.toolboxSizePreview.widthLabel.textContent, "8192 px");
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "4096 px");
});

test("preview restores saved dimensions and stays within the existing nonserialized widget", async () => {
    const { node, widget } = await setup();
    widget("ratio").value = "16:9 wide";
    widget("resolution").value = "7680 x 4320";
    node.onConfigure();
    assert.equal(node.toolboxSizePreview.frame.style.aspectRatio, "16 / 9");
    assert.match(node.toolboxSizeStatus.value, /7680×4320 px/);
    widget("ratio").value = "自定义尺寸";
    widget("custom_width").value = 1000;
    widget("custom_height").value = 1500;
    node.onConfigure();
    assert.equal(node.toolboxSizePreview.frame.style.aspectRatio, "1000 / 1500");
    assert.equal(node.toolboxSizePreview.widthLabel.textContent, "1000 px");
    assert.equal(node.toolboxSizePreview.heightLabel.textContent, "1500 px");
    const display = widget("size_status");
    assert.equal(node.widgets.length, 5);
    assert.equal(display.element.children[2], node.toolboxSizeStatus);
    assert.equal(display.options.getMinHeight(), 234);
    assert.equal(display.options.getMaxHeight(), 234);
    assert.equal(display.computeSize()[1], 234);
    assert.equal(display.serializeValue(), undefined);
    const values = ["自定义尺寸", "7680 x 4320", 1000, 1500];
    const info = { widgets_values: [...values, "preview"] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, values);
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
    assert.equal(node.toolboxSizePreview, undefined);
    assert.equal(node.widgets.at(-1).element, node.toolboxSizeStatus);
    assert.equal(node.widgets.at(-1).serialize, false);
    assert.equal(node.widgets.at(-1).serializeValue(), undefined);
    const values = [1024, 1024, "保持原图比例", "按倍数缩放", 4, 2048, "1"];
    const info = { widgets_values: [...values, "status"] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, values);
    assert.deepEqual(hooks, ["created", "executed", "serialize"]);
});
