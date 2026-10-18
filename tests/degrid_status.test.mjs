import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../web/js/degrid.js", import.meta.url), "utf8")
    .replace('import { app } from "../../../scripts/app.js";', "");

function setup(locale, name = "ToolBoxVAEDeGrid") {
    let extension;
    const calls = [];
    const app = { extensionManager: { setting: { get: () => locale } },
        registerExtension: value => { extension = value; } };
    const document = { createElement: () => ({ style: {}, setAttribute() {} }) };
    vm.runInNewContext(source, { app, document });
    class Node {
        constructor() { this.widgets = Array.from({ length: 6 }, () => ({})); this.size = [360, 350]; }
        onNodeCreated() { calls.push("created"); }
        onExecuted() { calls.push("executed"); }
        onSerialize() { calls.push("serialized"); }
        addDOMWidget(name, type, element, options) {
            const widget = { name, type, element, options };
            this.widgets.push(widget);
            return widget;
        }
    }
    extension.beforeRegisterNodeDef(Node, { name });
    const node = new Node();
    node.onNodeCreated();
    return { node, calls };
}

const detected = { enabled: true, mode: "auto", text: "grid 2.00/255 (checker)", stats: [{
    amp_255: 2, checker_255: 2, vstripe_255: 0.2, hstripe_255: 0.1,
    limit: 0.02, clipped_pct: 1.2, skipped: false,
}] };

test("readonly status preserves lifecycle hooks and cannot enter workflow parameters", () => {
    const { node, calls } = setup("en");
    node.onExecuted({ degrid: [detected] });
    assert.equal(node.degridStatus.value, detected.text);
    assert.equal(node.degridStatus.readOnly, true);
    assert.equal(node.widgets.at(-1).serialize, false);
    assert.equal(node.widgets.at(-1).serializeValue(), undefined);
    const info = { widgets_values: [true, "auto", 0.02, true, 10, "4x zoom", "status", undefined] };
    node.onSerialize(info);
    assert.deepEqual(info.widgets_values, [true, "auto", 0.02, true, 10, "4x zoom"]);
    assert.deepEqual(calls, ["created", "executed", "serialized"]);
});

test("Chinese status includes orientation, cap, protection and first-frame batch", () => {
    const { node } = setup("zh-CN");
    node.onExecuted({ degrid: [{ ...detected, stats: [...detected.stats, ...detected.stats] }] });
    assert.match(node.degridStatus.value, /棋盘.*0\.020 自动/);
    assert.match(node.degridStatus.value, /边缘保护：1\.2%/);
    assert.match(node.degridStatus.value, /批次 2 张（显示首图）/);
    node.onExecuted({ degrid: [{ enabled: false, stats: [] }] });
    assert.equal(node.degridStatus.value, "已旁路（启用关闭）");
});

test("clean, forced and manual states are distinguished", () => {
    const { node } = setup("zh");
    const stats = [{ ...detected.stats[0], amp_255: 0.1, skipped: true }];
    node.onExecuted({ degrid: [{ ...detected, stats }] });
    assert.match(node.degridStatus.value, /未检测到网格，原图透传/);
    stats[0].skipped = false;
    node.onExecuted({ degrid: [{ ...detected, stats }] });
    assert.match(node.degridStatus.value, /仍执行滤波/);
    node.onExecuted({ degrid: [{ ...detected, mode: "manual" }] });
    assert.match(node.degridStatus.value, /手动/);
    const previous = node.degridStatus.value;
    node.onExecuted({});
    assert.equal(node.degridStatus.value, previous);
});

test("other nodes are unchanged", () => {
    const { node } = setup("en", "VAEDeGrid");
    assert.equal(node.widgets.length, 6);
    assert.equal(node.degridStatus, undefined);
});
