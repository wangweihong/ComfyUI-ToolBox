import { app } from "../../../scripts/app.js";

function chineseLocale() {
    return (app.extensionManager?.setting?.get("Comfy.Locale") || "en").startsWith("zh");
}

function statusText(payload) {
    if (!chineseLocale()) return payload.text;
    if (!payload.enabled) return "已旁路（启用关闭）";
    const s = payload.stats[0];
    let verdict;
    if (s.amp_255 < 0.5) {
        verdict = `网格 ${s.amp_255.toFixed(2)}/255 — 未检测到网格，${s.skipped ? "原图透传" : "仍执行滤波"}`;
    } else {
        const parts = [["棋盘", s.checker_255], ["竖条", s.vstripe_255], ["横条", s.hstripe_255]];
        const kind = parts.reduce((best, part) => part[1] > best[1] ? part : best)[0];
        verdict = `网格 ${s.amp_255.toFixed(2)}/255（${kind}）— 已滤波（限制 ${s.limit.toFixed(3)} ${payload.mode === "auto" ? "自动" : "手动"}）`;
    }
    const batch = payload.stats.length > 1 ? ` · 批次 ${payload.stats.length} 张（显示首图）` : "";
    return `${verdict} · 边缘保护：${s.clipped_pct.toFixed(1)}%${batch}`;
}

app.registerExtension({
    name: "eazy.toolbox.degrid",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ToolBoxVAEDeGrid") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            this.degridInputWidgetCount = this.widgets?.length || 0;
            const text = document.createElement("textarea");
            text.readOnly = true;
            text.value = chineseLocale() ? "运行后显示网格检测结果" : "Run to measure the VAE grid";
            text.setAttribute("aria-label", chineseLocale() ? "去网格状态" : "DeGrid status");
            Object.assign(text.style, {
                width: "100%", height: "100%", resize: "none", boxSizing: "border-box",
                fontSize: "12px", padding: "6px", color: "var(--input-text)",
                background: "var(--comfy-input-bg)", border: "none",
            });
            this.degridStatus = text;
            const widget = this.addDOMWidget("degrid_status", "customtext", text, { serialize: false });
            widget.serialize = false;
            widget.serializeValue = () => undefined;
            widget.computeSize = () => [this.size[0], 100];
            return result;
        };
        const executed = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = executed?.apply(this, arguments);
            const payload = message?.degrid?.[0];
            if (payload && this.degridStatus) this.degridStatus.value = statusText(payload);
            return result;
        };
        const serialized = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (info) {
            const result = serialized?.apply(this, arguments);
            if (Array.isArray(info.widgets_values)) {
                info.widgets_values = info.widgets_values.slice(0, this.degridInputWidgetCount);
            }
            return result;
        };
    },
});
