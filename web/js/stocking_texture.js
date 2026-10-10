import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { fitView, imagePoint, zoomAt, isCurrent } from "./stocking_geometry.mjs?v=20261010-unified";
import { GuideDraft, samHint, SAMRequests } from "./stocking_editor_state.mjs?v=20261010-unified";
import { STYLE_LABELS, STYLE_HINTS, PARAM_KEYS, SLIDERS, parameterPatch } from "./stocking_render_controls.mjs?v=20261010-unified";
import { applyCandidate, selectionCoverage, maskBoundarySegments, splitRatio, compareKey, canvasMetrics } from "./stocking_selection.mjs?v=20261010-unified";

import { translate, localizeDialog } from "./stocking_i18n.mjs?v=20261010-unified";
import { SETTING_KEYS, recordsForSave, capturePrompt } from "./stocking_unified_state.mjs?v=20261010-unified";
const CLASSES = new Set(["NFStockingEditor", "NFStockingRender", "NFStockingTexture"]);
const API_ROOT = "/toolbox/stocking";
const COLORS = ["#48dfaf", "#ffb45a", "#96aaff", "#ff78c8"];
const widget = (node, name) => node.widgets?.find(w => w.name === name);
const value = (node, name, fallback) => node.__stockingDialog?.unified && name in node.__stockingDialog.settings
    ? node.__stockingDialog.settings[name] : widget(node, name)?.value ?? fallback;

function setValue(node, name, val) {
    const w = widget(node, name);
    if (w) { w.value = val; w.callback?.(val); node.graph?.setDirtyCanvas?.(true, true); }
}

function el(tag, text, parent, attrs = {}) {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    Object.assign(item, attrs);
    parent?.append(item);
    return item;
}

async function imageFrom(url, signal) {
    const response = await api.fetchApi(url, { signal });
    if (!response.ok) throw new Error((await response.json()).error || "读取底图失败");
    return await createImageBitmap(await response.blob());
}

async function decodePNG(encoded) {
    const raw = encoded.startsWith("data:") ? encoded : `data:image/png;base64,${encoded}`;
    const img = new Image();
    img.src = raw;
    await img.decode();
    return img;
}

async function post(path, body, signal) {
    const response = await api.fetchApi(`${API_ROOT}/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
}

function plane(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.fillStyle = "black"; ctx.fillRect(0, 0, w, h);
    return c;
}

function rasterPaint(c, points, radius, gray) {
    const ctx = c.getContext("2d");
    ctx.strokeStyle = ctx.fillStyle = gray;
    ctx.lineWidth = radius * 2; ctx.lineCap = ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(...points[0]);
    for (const p of points.slice(1)) ctx.lineTo(...p);
    ctx.stroke();
    for (const p of [points[0], points.at(-1)]) {
        ctx.beginPath(); ctx.arc(...p, radius, 0, 2 * Math.PI); ctx.fill();
    }
}

let cssReady = false;
function styles() {
    if (cssReady) return;
    cssReady = true;
    const s = el("style", null, document.head);
    s.textContent = `.tb-stocking-overlay{position:fixed;inset:0;z-index:10000;background:#000a;display:grid;place-items:center;color:#eee;font:14px system-ui}
    .tb-stocking-dialog{width:min(1320px,96vw);height:90vh;background:#20242b;border:1px solid #667;border-radius:12px;display:flex;flex-direction:column;box-shadow:0 24px 90px #0008}
    .tb-stocking-head,.tb-stocking-tools{display:flex;align-items:center;gap:8px;padding:10px 14px;flex-wrap:wrap;border-bottom:1px solid #424854}
    .tb-stocking-head strong{flex:1}.tb-stocking-body{display:flex;min-height:0;flex:1}.tb-stocking-sidebar{width:220px;overflow:auto;padding:12px;flex-shrink:0}
    .tb-stocking-stage{flex:1;min-width:0;min-height:0;position:relative;background:#11151b;overflow:hidden}.tb-stocking-stage canvas{width:100%;height:100%;touch-action:none;display:block}
    .tb-stocking-dialog button,.tb-stocking-dialog input,.tb-stocking-dialog select{background:#303743;color:#eee;border:1px solid #596273;border-radius:5px;padding:6px}
    .tb-stocking-dialog button{cursor:pointer}.tb-stocking-dialog button:disabled{opacity:.4;cursor:default}.tb-stocking-dialog button.active{background:#236457;border-color:#56d7b7}
    .tb-stocking-sidebar label{display:flex;flex-direction:column;margin:9px 0;gap:5px}.tb-stocking-sidebar select,.tb-stocking-sidebar input{max-width:100%}
    .tb-stocking-status{padding:9px 14px;color:#c9d1db;font-size:12px;height:54px;flex-shrink:0;box-sizing:border-box;overflow:auto;white-space:pre-wrap}.tb-stocking-sidebar small{color:#b8c3d0;display:block;line-height:1.6}
    .tb-stocking-sam-hint{padding:8px 14px;background:#28303b;color:#d8e4ef;font-size:12px;line-height:1.5}.tb-stocking-save-state{color:#ffd37a;font-size:12px}
    .tb-stocking-dialog [hidden]{display:none!important}.tb-stocking-slider-row{display:flex;align-items:center;gap:6px}.tb-stocking-slider-row input[type=range]{flex:1;min-width:40px;padding:0;accent-color:#56d7b7}.tb-stocking-slider-row input[type=number]{width:66px}
    .tb-stocking-overview{width:34%;min-width:170px;display:flex;flex-direction:column;border-right:1px solid #424854;background:#11151b}.tb-stocking-overview-area{flex:1;min-height:0}.tb-stocking-overview canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair}
    .tb-stocking-pane-title{padding:9px 12px;background:#28303b;color:#d8e4ef;font-size:12px;flex-shrink:0}.tb-stocking-compare{display:flex;gap:8px;padding:8px;align-items:center;font-size:12px}.tb-stocking-compare input{flex:1;min-width:30px;accent-color:#56d7b7}.tb-stocking-detail{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0}
    .tb-stocking-divider{position:absolute;top:0;bottom:0;width:24px;margin-left:-12px;cursor:ew-resize;touch-action:none;z-index:2;outline:none}.tb-stocking-divider:before{content:"";position:absolute;left:11px;width:2px;top:0;bottom:0;background:white;box-shadow:0 0 3px #000}.tb-stocking-divider:after{content:"↔";position:absolute;top:50%;left:0;width:24px;text-align:center;background:#285d50;border:1px solid #bcecdf;border-radius:5px;padding:5px 0}.tb-stocking-divider:focus-visible:after{outline:2px solid #ffd37a}
    .tb-stocking-compare-label{position:absolute;top:8px;padding:4px 7px;background:#000b;border-radius:4px;pointer-events:none;font-size:12px}.tb-stocking-candidates{display:flex;gap:5px;flex-wrap:wrap;margin:8px 0}
    @media(max-width:760px){.tb-stocking-sidebar{width:160px}.tb-stocking-dialog{height:96vh}.tb-stocking-head,.tb-stocking-tools{padding:6px}}
    `;
}

class StockingDialog {
    constructor(node, payload, render) {
        this.node = node; this.payload = payload; this.renderMode = render;
        this.unified = node.comfyClass === "NFStockingTexture";
        this.settings = { ...payload.params };
        if (this.unified && !payload.sam3_available && this.settings.source_mode === "semantic") this.settings.source_mode = "manual";
        this.initialDocument = JSON.stringify(payload.document);
        if (this.unified) node.__stockingDialog = this;
        this.index = 0; this.revision = 0; this.planeSerial = 0; this.client = crypto.randomUUID(); this.closed = false;
        this.selected = 0; this.tool = render ? "pan" : "paint"; this.radius = 14;
        this.draft = null;
        this.history = []; this.future = []; this.planes = new Map(); this.overlays = new Map();
        this.controller = new AbortController(); this.pending = null; this.previewBitmap = null; this.requestSerial = 0;
        this.samRequests = new SAMRequests(); this.samPending = false;
        this.editorCompare = 0.5; this.editorCompareEnabled = false; this.fitMode = !render;
        styles();
        this.overlay = el("div", null, document.body, { className: "tb-stocking-overlay" });
        const dialog = el("div", null, this.overlay, { className: "tb-stocking-dialog" });
        dialog.setAttribute("role", "dialog"); dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-label", this.unified ? "丝袜纹理 · 编辑与预览" : render ? "丝袜纹理预览" : "丝袜引导编辑器");
        const head = el("div", null, dialog, { className: "tb-stocking-head" });
        el("strong", this.unified ? "丝袜纹理 · 编辑与预览" : render ? "丝袜纹理 · 选样式、调参数" : "丝袜引导 · 部位、走向与隔开", head);
        this.head = head;
        this.indexSelect = el("select", null, head, { title: "当前图像" });
        for (let i = 0; i < payload.batch; i++) el("option", `图像 ${i + 1}/${payload.batch}`, this.indexSelect, { value: String(i) });
        this.indexSelect.onchange = () => this.loadIndex(Number(this.indexSelect.value)).catch(e => this.error(e));
        this.button(head, "适应", () => { this.fitMode = true; this.view = fitView(payload.width, payload.height, this.stage.clientWidth, this.stage.clientHeight); this.draw(); if (this.renderMode) this.schedule(); });
        this.button(head, "100%", () => this.setZoom(1));
        this.button(head, "200%", () => this.setZoom(2));
        if (render) this.button(head, "关闭", () => this.close());
        else {
            this.saveState = el("small", "尚未修改", head, { className: "tb-stocking-save-state" });
            this.button(head, "保存并关闭", () => this.close(true));
            const cancel = this.button(head, "取消", () => this.close());
            cancel.title = "放弃本次修改并关闭；Esc 也可取消";
            const dismiss = this.button(head, "×", () => this.close());
            dismiss.setAttribute("aria-label", "关闭编辑器（不保存）");
            dismiss.title = "关闭编辑器，不保存本次修改";
        }
        const tools = el("div", null, dialog, { className: "tb-stocking-tools" });
        this.tools = tools;
        if (!render) {
            for (const [key, label] of [["paint", "画笔 B"], ["erase", "橡皮 E"], ["stroke", "走向 P"], ["wall", "隔开 W"], ["sam", "点选 S"], ["pan", "平移"]]) {
                const b = this.button(tools, label, () => { this.tool = key; this.markTools(); });
                b.dataset.tool = key;
                if (key === "sam") {
                    b.disabled = !payload.sam_available;
                    const connected = this.node.inputs?.find(i => i.name === "sam")?.link != null;
                    b.title = samHint(!!payload.sam_available, connected, payload.sam_device || "auto");
                }
            }
            const size = el("input", null, tools, { type: "number", value: "14", min: "1", max: "256", title: "笔刷半径（图像像素）" });
            size.style.width = "65px"; size.onchange = () => this.radius = Math.max(1, Math.min(256, Number(size.value) || 14));
            this.button(tools, "撤销", () => this.undo()); this.button(tools, "重做", () => this.redo());
            this.button(tools, "删除最后走向", () => this.removeLast("strokes"));
            this.button(tools, "删除最后隔开", () => this.removeLast("walls"));
        } else {
            this.button(tools, "标出问题", e => { this.diagnostics = !this.diagnostics; e.classList.toggle("active", this.diagnostics); this.schedule(); });
            this.button(tools, "对比原图", e => { this.showOriginal = !this.showOriginal; e.classList.toggle("active", this.showOriginal); this.draw(); });
        }
        if (!render) {
            const connected = this.node.inputs?.find(i => i.name === "sam")?.link != null;
            el("div", samHint(!!payload.sam_available, connected, payload.sam_device || "auto"), dialog, { className: "tb-stocking-sam-hint" });
            this.samStatus = el("div", null, dialog, { className: "tb-stocking-sam-hint", hidden: true });
            this.samStatus.setAttribute("role", "status"); this.samStatus.setAttribute("aria-live", "polite");
            this.samText = el("span", "", this.samStatus);
            this.samCancel = this.button(this.samStatus, "取消等待", () => this.cancelSAM("已取消 SAM 等待；已开始的后台推理可能仍在完成，可继续绘制。"));
            this.samCancel.style.marginLeft = "12px";
        }
        const body = el("div", null, dialog, { className: "tb-stocking-body" });
        this.body = body;
        this.sidebar = el("div", null, body, { className: "tb-stocking-sidebar" });
        if (render) this.buildOverview(body);
        const detail = el("div", null, body, { className: "tb-stocking-detail" });
        if (render || this.unified) this.detailTitle = el("div", "细节 · 拖动平移，滚轮缩放", detail, { className: "tb-stocking-pane-title" });
        this.stage = el("div", null, detail, { className: "tb-stocking-stage" });
        this.canvas = el("canvas", null, this.stage);
        if (!render) this.buildEditorComparison(tools, detail);
        this.status = el("div", "正在读取底图…", dialog, { className: "tb-stocking-status" });
        this.view = fitView(payload.width, payload.height, this.stage.clientWidth, this.stage.clientHeight);
        if (render) this.view = { scale: 1, x: (this.stage.clientWidth - payload.width) / 2, y: (this.stage.clientHeight - payload.height) / 2 };
        this.resize = new ResizeObserver(() => {
            if (this.fitMode) this.view = fitView(payload.width, payload.height, this.stage.clientWidth, this.stage.clientHeight);
            this.draw(); if (this.base && this.renderMode) this.schedule();
        }); this.resize.observe(this.stage);
        if (this.overviewArea) this.resize.observe(this.overviewArea);
        this.keyboard = e => this.key(e); document.addEventListener("keydown", this.keyboard);
        this.canvas.onpointerdown = e => this.down(e); this.canvas.onpointermove = e => this.move(e);
        this.canvas.onpointerup = e => this.up(e); this.canvas.onpointercancel = () => { this.drag = null; this.draw(); };
        this.canvas.oncontextmenu = e => e.preventDefault();
        this.stage.onwheel = e => {
            e.preventDefault(); this.fitMode = false; const r = this.canvas.getBoundingClientRect();
            this.view = zoomAt(this.view, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.001)); this.draw();
            if (this.renderMode) this.schedule();
        };
        this.markTools();
        if (render) this.buildRenderControls(); else this.readDocument();
        if (this.unified) this.buildUnified();
        this.localeObserver = localizeDialog(this.overlay, app.extensionManager?.setting?.get("Comfy.Locale") || app.ui?.settings?.getSettingValue("Comfy.Locale") || "zh");
        this.loadIndex(0).catch(e => this.error(e));
    }

    button(parent, label, fn) {
        const b = el("button", label, parent, { type: "button" });
        b.onclick = async () => { try { await fn(b); } catch (e) { this.error(e); } };
        return b;
    }

    error(e) { if (!this.closed && e.name !== "AbortError") this.status.textContent = e.message; }
    markTools() { for (const b of this.overlay.querySelectorAll("[data-tool]")) b.classList.toggle("active", b.dataset.tool === this.tool); }

    readDocument() {
        let raw = this.unified ? "{}" : value(this.node, "guides_json", "{}");
        const prior = JSON.parse(raw || "{}");
        if (prior.width && (prior.width !== this.payload.width || prior.height !== this.payload.height)) raw = "{}";
        try { this.draft = new GuideDraft(raw, this.unified ? "per_image" : value(this.node, "batch_mode", "shared"), this.payload.document); }
        catch { throw new Error("引导 JSON 无效，请修正后重新打开"); }
        if (this.doc.width !== this.payload.width || this.doc.height !== this.payload.height) {
            this.sidebar.textContent = "底图尺寸改变，原引导不能自动拉伸。";
            this.button(this.sidebar, "为新尺寸重建引导", () => {
                this.doc = structuredClone(this.payload.document); this.updateDraft(); this.loadIndex(this.index);
            });
            throw new Error("引导尺寸与底图不一致，请重建引导");
        }
        this.buildRegionControls();
    }

    get doc() { return this.draft?.doc; }
    set doc(doc) { this.draft.doc = doc; }
    get batchMode() { return this.draft?.mode || "shared"; }
    frame() { return this.doc?.frames[this.batchMode === "shared" ? 0 : this.index]; }
    region() { return this.frame()?.regions[this.selected]; }

    buildRegionControls() {
        this.unifiedControls?.remove();
        this.sidebar.replaceChildren();
        const modeLabel = el("label", "批次引导", this.sidebar);
        modeLabel.hidden = this.unified;
        const mode = el("select", null, modeLabel);
        el("option", "共享引导", mode, { value: "shared" }); el("option", "逐图引导", mode, { value: "per_image" });
        mode.value = this.batchMode;
        mode.onchange = () => {
            this.remember();
            if (mode.value === "per_image") this.doc.frames = Array.from({ length: this.payload.batch }, (_, i) => structuredClone(this.doc.frames[i] || this.doc.frames[0]));
            else this.doc.frames = [structuredClone(this.doc.frames[this.index] || this.doc.frames[0])];
            this.draft.mode = mode.value; this.selected = 0; this.updateDraft(); this.loadPlanes();
        };
        el("label", "部位（靠后者优先）", this.sidebar);
        this.regionSelect = el("select", null, this.sidebar);
        this.refreshRegions();
        this.regionSelect.onchange = () => { this.cancelSAM(); this.selected = Number(this.regionSelect.value); this.sourceCheck.checked = !!this.region()?.external; this.draw(); };
        const sourceLabel = el("label", "使用输入 MASK 作底图", this.sidebar);
        this.sourceCheck = el("input", null, sourceLabel, { type: "checkbox", checked: !!this.region()?.external, disabled: !this.payload.has_mask });
        this.sourceCheck.onchange = () => {
            if (!this.region()) return; this.remember(); this.region().external = this.sourceCheck.checked;
            this.overlays.delete(this.region().id); this.updateDraft(); this.refreshRegions(); this.draw();
        };
        this.button(this.sidebar, "新增部位", () => {
            this.remember(); this.frame().regions.push({ id: crypto.randomUUID(), name: `部位 ${this.frame().regions.length + 1}`,
                external: false, mask: "", erase: "", strokes: [], walls: [] });
            this.selected = this.frame().regions.length - 1; this.updateDraft(); this.loadPlanes();
        });
        this.button(this.sidebar, "重命名", () => {
            if (!this.region()) return; const name = prompt("部位名称", this.region().name);
            if (name?.trim()) { this.remember(); this.region().name = name.trim(); this.updateDraft(); this.refreshRegions(); }
        });
        this.button(this.sidebar, "删除部位", () => {
            if (!this.region()) return; this.remember(); this.frame().regions.splice(this.selected, 1);
            this.selected = Math.max(0, this.selected - 1); this.updateDraft(); this.loadPlanes();
        });
        this.samControls = el("div", null, this.sidebar);
        el("small", "走向线横穿部位，决定弧度；隔开线画在折叠交界。滚轮缩放，中键或空格拖动平移。修改先保留在草稿中，自动更新预览；保存并关闭后再运行工作流。取消或 Esc 会放弃本次修改。", this.sidebar);
        if (!this.unified) el("small", "高级分步工作流：在渲染节点设置样式和强度。推荐使用一体化丝袜纹理节点。", this.sidebar);
        if (this.unifiedControls) this.sidebar.append(this.unifiedControls);
    }

    refreshRegions() {
        if (!this.regionSelect) return;
        this.regionSelect.replaceChildren();
        this.frame()?.regions.forEach((r, i) => el("option", `${i + 1}. ${r.name}${r.external ? "（输入遮罩）" : ""}`, this.regionSelect, { value: String(i) }));
        this.regionSelect.value = String(this.selected);
        if (this.sourceCheck) this.sourceCheck.checked = !!this.region()?.external;
    }

    buildEditorComparison(tools, parent) {
        this.editorCompareToggle = this.button(tools, "原图 / 选区对比", () => this.setEditorCompare(!this.editorCompareEnabled));
        this.editorCompareToggle.setAttribute("aria-pressed", "false");
        this.button(tools, "对比居中", () => { this.setEditorCompare(true); this.setEditorSplit(0.5); });
        this.editorDivider = el("div", null, this.stage, { className: "tb-stocking-divider", tabIndex: 0, hidden: true });
        for (const [key, val] of Object.entries({ role: "slider", "aria-label": "原图与选区预览分界", "aria-orientation": "horizontal", "aria-valuemin": "0", "aria-valuemax": "100" })) this.editorDivider.setAttribute(key, val);
        this.editorLeftLabel = el("span", "原图", this.stage, { className: "tb-stocking-compare-label", hidden: true });
        this.editorLeftLabel.style.left = "8px";
        this.editorRightLabel = el("span", "选区预览", this.stage, { className: "tb-stocking-compare-label", hidden: true });
        this.editorRightLabel.style.right = "8px";
        const row = el("div", null, parent, { className: "tb-stocking-compare" });
        el("span", "原图", row);
        this.editorCompareInput = el("input", null, row, { type: "range", min: "0", max: "100", step: "1", value: "50", disabled: true });
        this.editorCompareInput.setAttribute("aria-label", "原图与选区预览对比位置");
        this.editorCompareInput.oninput = () => this.setEditorSplit(Number(this.editorCompareInput.value) / 100);
        el("span", "选区预览", row);
        this.editorDivider.onpointerdown = e => {
            e.preventDefault(); e.stopPropagation();
            if (e.button !== 0 || this.space) { this.down(e); return; }
            this.editorDivider.setPointerCapture(e.pointerId); this.drag = { compare: true };
            this.setEditorSplit(splitRatio(e.clientX, this.stage.getBoundingClientRect()));
        };
        this.editorDivider.onpointermove = e => { if (this.drag?.compare) this.setEditorSplit(splitRatio(e.clientX, this.stage.getBoundingClientRect())); };
        this.editorDivider.onpointerup = this.editorDivider.onpointercancel = () => { this.drag = null; this.draw(); };
        this.editorDivider.oncontextmenu = e => e.preventDefault();
        this.editorDivider.onkeydown = e => {
            const next = compareKey(this.editorCompare, e.key);
            if (next === null) return;
            e.preventDefault(); e.stopPropagation(); this.setEditorSplit(next);
        };
        this.syncEditorComparison();
    }

    setEditorCompare(enabled) { this.editorCompareEnabled = enabled; this.syncEditorComparison(); this.draw(); }
    setEditorSplit(ratio) { this.editorCompare = Math.max(0, Math.min(1, ratio)); this.syncEditorComparison(); this.draw(); }
    syncEditorComparison() {
        if (!this.editorDivider) return;
        const percent = Math.round(this.editorCompare * 100);
        this.editorDivider.hidden = this.editorLeftLabel.hidden = this.editorRightLabel.hidden = !this.editorCompareEnabled;
        this.editorDivider.style.left = `${this.editorCompare * 100}%`;
        this.editorDivider.setAttribute("aria-valuenow", String(percent));
        this.editorCompareInput.disabled = !this.editorCompareEnabled; this.editorCompareInput.value = String(percent);
        this.editorCompareToggle.classList.toggle("active", this.editorCompareEnabled);
        this.editorCompareToggle.setAttribute("aria-pressed", String(this.editorCompareEnabled));
    }

    buildRenderControls() {
        const label = el("label", "样式", this.sidebar);
        this.styleSelect = el("select", null, label, { value: value(this.node, "style", "knit") });
        for (const [val, text] of Object.entries(STYLE_LABELS)) el("option", text, this.styleSelect, { value: val });
        this.styleSelect.value = value(this.node, "style", "knit");
        this.styleSelect.dataset.setting = "style";
        this.styleSelect.onchange = () => this.changeParameter("style", this.styleSelect.value);
        this.styleSelect.setAttribute("aria-label", "样式");
        this.styleHint = el("small", "", this.sidebar);
        const autoLabel = el("label", "自动强度（按丝袜深浅）", this.sidebar);
        this.autoInput = el("input", null, autoLabel, { type: "checkbox", checked: value(this.node, "strength_auto", true) });
        this.autoInput.setAttribute("aria-label", "自动强度");
        this.autoInput.dataset.setting = "strength_auto";
        this.autoInput.onchange = () => this.changeParameter("strength_auto", this.autoInput.checked);
        this.strengthHint = el("small", "", this.sidebar);
        this.renderSliders = new Map();
        for (const spec of SLIDERS) {
            if (!widget(this.node, spec.key) && !(spec.key in this.settings)) continue;
            const group = el("label", `${spec.label} ${spec.unit}`, this.sidebar);
            const row = el("span", null, group, { className: "tb-stocking-slider-row" });
            const attrs = { min: String(spec.min), max: String(spec.max), step: "1", value: String(value(this.node, spec.key, 0)), title: spec.hint };
            const slider = el("input", null, row, { ...attrs, type: "range" });
            const number = el("input", null, row, { ...attrs, type: "number" });
            slider.dataset.setting = number.dataset.setting = spec.key;
            slider.setAttribute("aria-label", spec.label); number.setAttribute("aria-label", `${spec.label}数值`);
            slider.oninput = () => this.changeParameter(spec.key, slider.value);
            number.oninput = () => {
                const n = Number(number.value);
                if (number.value !== "" && n >= spec.min && n <= spec.max) this.changeParameter(spec.key, number.value);
            };
            number.onchange = () => { this.changeParameter(spec.key, number.value); number.value = String(value(this.node, spec.key, 0)); };
            this.renderSliders.set(spec.key, { group, slider, number });
        }
        el("small", "亮点与纹理强度独立，多种来源可混用。深度来源需连接灰度深度图，遮罩来源需连接 sparkle_mask。", this.sidebar);
        const colorLabel = el("label", "颜色排除", this.sidebar);
        const color = el("input", null, colorLabel, { type: "checkbox", checked: value(this.node, "color_exclude", true) });
        color.setAttribute("aria-label", "颜色排除");
        color.dataset.setting = "color_exclude";
        color.onchange = () => this.changeParameter("color_exclude", color.checked);
        el("small", "排除金边、皮肤等异色；透肤膝盖被误排除时可关闭。", this.sidebar);
        const seedLabel = el("label", "随机种子", this.sidebar);
        // Reject rounded integers instead of silently changing the random field.
        const seed = el("input", null, seedLabel, { type: "text", inputMode: "numeric", value: String(value(this.node, "seed", 20261005)) });
        seed.setAttribute("aria-label", "随机种子");
        seed.dataset.setting = "seed";
        seed.onchange = () => {
            const n = Number(seed.value);
            if (/^\d+$/.test(seed.value) && Number.isSafeInteger(n)) this.changeParameter("seed", n);
            else { seed.value = String(value(this.node, "seed", 20261005)); this.status.textContent = "种子请输入有效整数；超出浏览器精确整数范围的种子请使用 API。"; }
        };
        this.refreshRenderControls();
        el("small", this.unified ? "滑杆自动更新草稿预览；保存并关闭后运行工作流得到正式输出。取消不保存参数。整体定位细节，拖动分界线对比原图。" : "拖动滑杆自动预览并写入本渲染节点；关闭后运行工作流得到正式输出。整体点击定位细节，拖分界线对比；细节使用导出的原像素。修改引导后需重新运行工作流。", this.sidebar);
    }

    changeParameter(key, raw) {
        const patch = parameterPatch(key, raw); if (!patch) return;
        for (const [name, val] of Object.entries(patch)) {
            if (this.unified) {
                if (this.node.inputs?.some(i => i.name === name && i.link != null)) continue;
                this.settings[name] = val;
            } else setValue(this.node, name, val);
        }
        this.refreshRenderControls(); this.schedule();
    }

    refreshRenderControls(info) {
        const style = value(this.node, "style", "knit"), auto = value(this.node, "strength_auto", true);
        this.styleHint.textContent = STYLE_HINTS[style] || "";
        this.autoInput.checked = auto;
        this.strengthHint.textContent = auto
            ? `自动强度${info ? `：${Number(info.effective_strength).toFixed(1)}%` : "：预览计算中"}；拖动强度滑杆可切换为手动。`
            : `手动强度：${value(this.node, "strength", 100)}%；亮点由各来源单独控制。`;
        for (const [key, control] of this.renderSliders) {
            control.group.hidden = key === "tilt" && style !== "lines";
            const val = value(this.node, key, 0);
            control.slider.value = val;
            if (document.activeElement !== control.number) control.number.value = val;
        }
    }

    setZoom(scale) {
        this.fitMode = false;
        const w = this.stage.clientWidth, h = this.stage.clientHeight;
        this.view = zoomAt(this.view, w / 2, h / 2, scale / this.view.scale);
        this.draw(); if (this.renderMode) this.schedule();
    }

    buildOverview(body) {
        const pane = el("div", null, body, { className: "tb-stocking-overview" });
        el("div", "整体 · 点击定位细节，拖分界线对比", pane, { className: "tb-stocking-pane-title" });
        this.overviewArea = el("div", null, pane, { className: "tb-stocking-overview-area" });
        this.overviewCanvas = el("canvas", null, this.overviewArea);
        this.compare = 0.5;
        const row = el("div", null, pane, { className: "tb-stocking-compare" });
        el("span", "原图", row);
        this.compareInput = el("input", null, row, { type: "range", min: "0", max: "100", value: "50" });
        this.compareInput.setAttribute("aria-label", "原图与纹理对比分界");
        this.compareInput.oninput = () => { this.compare = Number(this.compareInput.value) / 100; this.drawOverview(); };
        el("span", "纹理", row);
        this.overviewCanvas.onpointerdown = e => {
            if (!this.base) return;
            const r = this.overviewCanvas.getBoundingClientRect(), v = this.overviewView;
            const boundary = v.x + this.payload.width * v.scale * this.compare;
            this.overviewDragging = Math.abs(e.clientX - r.left - boundary) <= 14 ? "compare" : "detail";
            this.overviewCanvas.setPointerCapture(e.pointerId); this.moveOverview(e);
        };
        this.overviewCanvas.onpointermove = e => { if (this.overviewDragging) this.moveOverview(e); };
        this.overviewCanvas.onpointerup = this.overviewCanvas.onpointercancel = () => { this.overviewDragging = null; };
    }

    moveOverview(e) {
        const r = this.overviewCanvas.getBoundingClientRect(), v = this.overviewView;
        if (this.overviewDragging === "compare") {
            this.compare = Math.max(0, Math.min(1, (e.clientX - r.left - v.x) / (this.payload.width * v.scale)));
            this.compareInput.value = String(this.compare * 100); this.drawOverview();
        } else {
            const [x, y] = imagePoint(e.clientX, e.clientY, r, v, this.payload.width, this.payload.height);
            this.view.x = this.stage.clientWidth / 2 - x * this.view.scale;
            this.view.y = this.stage.clientHeight / 2 - y * this.view.scale;
            this.draw(); this.schedule();
        }
    }

    drawOverview() {
        if (!this.overviewCanvas || this.closed) return;
        const w = this.overviewArea.clientWidth, h = this.overviewArea.clientHeight, dpr = window.devicePixelRatio || 1;
        this.overviewCanvas.width = Math.round(w * dpr); this.overviewCanvas.height = Math.round(h * dpr);
        const ctx = this.overviewCanvas.getContext("2d"), v = fitView(this.payload.width, this.payload.height, w, h);
        this.overviewView = v;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        if (!this.base) return;
        const iw = this.payload.width * v.scale, ih = this.payload.height * v.scale, boundary = v.x + iw * this.compare;
        ctx.drawImage(this.base, v.x, v.y, iw, ih);
        if (this.overviewBitmap) {
            ctx.save(); ctx.beginPath(); ctx.rect(boundary, v.y, iw * (1 - this.compare), ih); ctx.clip();
            ctx.drawImage(this.overviewBitmap, v.x, v.y, iw, ih); ctx.restore();
        }
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(boundary, v.y); ctx.lineTo(boundary, v.y + ih); ctx.stroke();
        ctx.strokeStyle = "#56d7b7"; ctx.lineWidth = 1;
        ctx.save(); ctx.beginPath(); ctx.rect(v.x, v.y, iw, ih); ctx.clip();
        ctx.strokeRect(v.x - this.view.x / this.view.scale * v.scale, v.y - this.view.y / this.view.scale * v.scale,
            this.stage.clientWidth / this.view.scale * v.scale, this.stage.clientHeight / this.view.scale * v.scale); ctx.restore();
    }

    async loadIndex(index) {
        this.loading = true; this.loadedIndex = null; this.planeSerial++;
        const serial = ++this.requestSerial;
        try {
            this.cancelSAM();
            this.externalRaster = null;
            this.flushPlanes();
            this.base?.close(); this.base = null; this.external?.close(); this.external = null;
            this.planes.clear(); this.overlays.clear(); this.basicLines = [];
            this.index = index; this.revision++; this.pending?.abort(); this.previewBitmap = null;
            this.overviewBitmap = null; this.overviewKey = null;
            this.samControls?.replaceChildren();
            const path = `${API_ROOT}/image?session=${this.payload.session}&index=${index}`;
            const bitmap = await imageFrom(path, this.controller.signal);
            if (this.closed || serial !== this.requestSerial) { bitmap.close(); return; }
            this.base?.close(); this.base = bitmap;
            if (!this.renderMode || this.unified) {
                const external = await imageFrom(path + "&kind=external", this.controller.signal);
                if (this.closed || serial !== this.requestSerial) { external.close(); return; }
                this.external?.close(); this.external = external;
                this.selected = Math.min(this.selected, Math.max(0, (this.frame()?.regions.length || 1) - 1));
                await this.loadPlanes();
            }
            if (this.closed || serial !== this.requestSerial) return;
            this.loadedIndex = index;
            this.draw(); this.status.textContent = `底图 ${this.payload.identity.slice(0, 10)} · ${this.payload.width}×${this.payload.height} · 图像 ${index + 1}`;
            this.schedule();
            if (this.unified && this.settings.source_mode === "semantic" && this.payload.sam3_available && !this.frame()?.regions.some(r => r.mask || r.external)) {
                this.semantic().catch(e => this.error(e));
            }
        } finally { if (serial === this.requestSerial) { this.loading = false; this.draw(); } }
    }

    async loadPlanes() {
        this.planeLoading = true;
        const serial = ++this.planeSerial;
        try {
            this.cancelSAM();
            const next = new Map();
            for (const r of this.frame()?.regions || []) {
                const pair = { mask: plane(this.payload.width, this.payload.height), erase: plane(this.payload.width, this.payload.height) };
                for (const key of ["mask", "erase"]) if (r[key]) pair[key].getContext("2d").drawImage(await decodePNG(r[key]), 0, 0);
                next.set(r.id, pair);
            }
            if (this.closed || serial !== this.planeSerial) return;
            this.planes = next; this.overlays.clear(); this.refreshRegions(); this.draw(); this.schedule();
        } finally { if (serial === this.planeSerial) this.planeLoading = false; }
    }

    flushPlanes() {
        // Only dirty planes are encoded; unchanged masks are already in the JSON.
        for (const r of this.frame()?.regions || []) {
            const p = this.planes.get(r.id);
            if (!p?.dirty) continue;
            r.mask = p.mask.toDataURL("image/png").split(",")[1];
            r.erase = p.erase.toDataURL("image/png").split(",")[1]; p.dirty = false;
        }
    }

    updateDraft() {
        this.flushPlanes(); this.previewBitmap = null;
        if (this.samCandidates) this.samCandidates.visual = null;
        if (this.saveState) this.saveState.textContent = this.draft.dirty ? "有未保存修改" : "尚未修改";
        this.schedule();
    }
    snapshot() { return JSON.stringify({ doc: this.doc, mode: this.batchMode, selected: this.selected, index: this.index }); }
    remember() {
        this.flushPlanes(); this.history.push(this.snapshot()); this.future = [];
        while (this.history.length > 30 || this.history.reduce((sum, s) => sum + s.length, 0) > 16 * 1024 * 1024) this.history.shift();
    }
    restore(raw) {
        const s = JSON.parse(raw); this.doc = s.doc; this.selected = s.selected;
        this.draft.mode = s.mode; this.updateDraft(); this.buildRegionControls();
        if (s.index !== this.index) {
            this.indexSelect.value = String(s.index); this.loadIndex(s.index).catch(e => this.error(e));
        } else this.loadPlanes().catch(e => this.error(e));
    }
    undo() { if (this.history.length) { this.flushPlanes(); this.future.push(this.snapshot()); this.restore(this.history.pop()); } }
    redo() { if (this.future.length) { this.flushPlanes(); this.history.push(this.snapshot()); this.restore(this.future.pop()); } }
    removeLast(key) { if (this.region()?.[key]?.length) { this.remember(); this.region()[key].pop(); this.updateDraft(); this.draw(); } }

    point(e) { return imagePoint(e.clientX, e.clientY, this.canvas.getBoundingClientRect(), this.view, this.payload.width, this.payload.height); }
    down(e) {
        if (!this.base || this.loading || this.planeLoading || this.loadedIndex !== this.index) return;
        this.canvas.setPointerCapture(e.pointerId);
        if (this.tool === "pan" || this.space || e.button === 1 || this.renderMode) {
            this.fitMode = false;
            this.drag = { pan: true, x: e.clientX, y: e.clientY, view: { ...this.view } }; return;
        }
        if (!this.region()) { this.status.textContent = "请先新增部位"; return; }
        if (this.tool === "sam") { this.samClick(this.point(e), e.button === 2).catch(err => this.error(err)); return; }
        if (e.button === 2) { this.removeLast(this.tool === "wall" ? "walls" : "strokes"); return; }
        this.remember(); this.drag = { points: [this.point(e)], tool: this.tool, regionId: this.region().id, index: this.index };
        this.draw();
    }
    move(e) {
        if (!this.drag) return;
        if (this.drag.pan) this.view = { ...this.drag.view, x: this.drag.view.x + e.clientX - this.drag.x, y: this.drag.view.y + e.clientY - this.drag.y };
        else {
            const p = this.point(e), last = this.drag.points.at(-1);
            if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 1) this.drag.points.push(p);
        }
        this.draw();
    }
    up() {
        const d = this.drag; this.drag = null; if (!d) return;
        if (d.pan) { if (this.renderMode) this.schedule(); this.draw(); return; }
        if (d.index !== this.index || d.regionId !== this.region()?.id) return;
        const p = this.planes.get(d.regionId), r = this.region();
        if (["paint", "erase"].includes(d.tool) && p) {
            rasterPaint(p.mask, d.points, this.radius, d.tool === "paint" ? "white" : "black");
            rasterPaint(p.erase, d.points, this.radius, d.tool === "erase" ? "white" : "black");
            p.dirty = true; this.overlays.delete(r.id);
        } else if (d.points.length > 1) r[d.tool === "stroke" ? "strokes" : "walls"].push(d.points);
        this.updateDraft(); this.draw();
    }

    regionPixels(r) {
        const p = this.planes.get(r.id); if (!p) return null;
        const w = this.payload.width, h = this.payload.height;
        const paint = p.mask.getContext("2d").getImageData(0, 0, w, h).data;
        const erased = p.erase.getContext("2d").getImageData(0, 0, w, h).data;
        let external = null;
        if (r.external && this.external) {
            if (!this.externalRaster) {
                const c = plane(w, h); c.getContext("2d").drawImage(this.external, 0, 0);
                this.externalRaster = c.getContext("2d").getImageData(0, 0, w, h).data;
            }
            external = this.externalRaster;
        }
        return { paint, erased, external };
    }

    coverageVisual(coverage, color) {
        const w = this.payload.width, h = this.payload.height;
        const c = document.createElement("canvas"); c.width = w; c.height = h;
        const ctx = c.getContext("2d"), out = ctx.createImageData(w, h);
        const rgb = color.match(/\w\w/g).map(v => parseInt(v, 16));
        for (let j = 0, k = 0; j < coverage.length; j++, k += 4) {
            out.data[k] = rgb[0]; out.data[k + 1] = rgb[1]; out.data[k + 2] = rgb[2]; out.data[k + 3] = coverage[j];
        }
        ctx.putImageData(out, 0, 0);
        return { canvas: c, coverage, color, path: null };
    }

    drawCoverage(ctx, visual, opacity, outline = false) {
        if (!visual) return;
        ctx.save(); ctx.globalAlpha = opacity; ctx.drawImage(visual.canvas, 0, 0); ctx.restore();
        if (!outline) return;
        if (!visual.path) {
            visual.path = new Path2D();
            if (visual.coverage.some(v => v > 127)) for (const [x0, y0, x1, y1] of maskBoundarySegments(visual.coverage, this.payload.width, this.payload.height)) {
                visual.path.moveTo(x0, y0); visual.path.lineTo(x1, y1);
            }
        }
        ctx.strokeStyle = visual.color; ctx.lineWidth = 2 / this.view.scale; ctx.stroke(visual.path);
    }

    overlayFor(r, index) {
        if (this.overlays.has(r.id)) return this.overlays.get(r.id);
        const pixels = this.regionPixels(r); if (!pixels) return null;
        const v = this.coverageVisual(selectionCoverage(pixels.paint, pixels.erased, pixels.external), COLORS[index % COLORS.length]);
        this.overlays.set(r.id, v); return v;
    }

    samVisual() {
        const group = this.samCandidates;
        if (!group?.rgba || !this.samRequests.matches(group.token, this.closed, this.index, this.region())) return null;
        if (!group.visual) {
            const p = this.regionPixels(this.region()); if (!p) return null;
            const projected = selectionCoverage(p.paint, p.erased, p.external, group.rgba, group.subtract);
            const before = group.subtract ? selectionCoverage(p.paint, p.erased, p.external) : null;
            const change = group.subtract ? before.map((v, i) => Math.max(0, v - projected[i])) : Uint8Array.from({ length: projected.length }, (_, i) => group.rgba[i * 4] > 127 ? 255 : 0);
            group.visual = {
                result: this.coverageVisual(projected, COLORS[this.selected % COLORS.length]),
                change: this.coverageVisual(change, group.subtract ? "#ff625b" : "#48dfaf"),
            };
        }
        return group.visual;
    }

    draw() {
        if (this.closed || !this.canvas) return;
        const rect = this.stage.getBoundingClientRect(), w = Math.max(1, rect.width), h = Math.max(1, rect.height);
        const metrics = canvasMetrics(w, h, window.devicePixelRatio || 1);
        if (this.canvas.width !== metrics.width || this.canvas.height !== metrics.height) {
            this.canvas.width = metrics.width; this.canvas.height = metrics.height;
        }
        const ctx = this.canvas.getContext("2d");
        ctx.setTransform(metrics.scaleX, 0, 0, metrics.scaleY, 0, 0); ctx.clearRect(0, 0, w, h);
        if (!this.base || this.loading) return;
        ctx.save(); ctx.translate(this.view.x, this.view.y); ctx.scale(this.view.scale, this.view.scale);
        ctx.imageSmoothingEnabled = this.view.scale < 1;
        if (this.base) ctx.drawImage(this.base, 0, 0);
        ctx.restore();
        ctx.save();
        if (this.editorCompareEnabled && (!this.renderMode || this.unified)) {
            const split = w * this.editorCompare;
            ctx.beginPath(); ctx.rect(split, 0, w - split, h); ctx.clip();
        }
        ctx.translate(this.view.x, this.view.y); ctx.scale(this.view.scale, this.view.scale);
        ctx.imageSmoothingEnabled = this.view.scale < 1;
        const sam = this.renderMode ? null : this.samVisual();
        if (this.semanticMaskPreview && !this.renderMode) {
            const c = this.semanticMaskPreview, ctxMask = c.getContext("2d");
            const image = ctxMask.getImageData(0, 0, c.width, c.height);
            for (let k = 0; k < image.data.length; k += 4) {
                const alpha = image.data[k]; image.data[k] = 70; image.data[k + 1] = 230; image.data[k + 2] = 160; image.data[k + 3] = alpha / 2;
            }
            const overlay = document.createElement("canvas"); overlay.width = c.width; overlay.height = c.height;
            overlay.getContext("2d").putImageData(image, 0, 0); ctx.drawImage(overlay, 0, 0);
        }
        if (this.previewBitmap && !this.showOriginal && !sam && !this.semanticMaskPreview) ctx.drawImage(this.previewBitmap, ...(this.previewRect ? [this.previewRect[0], this.previewRect[1]] : [0, 0]));
        if (!this.renderMode && this.doc) {
            this.frame()?.regions.forEach((r, i) => {
                this.drawCoverage(ctx, sam && i === this.selected ? sam.result : this.overlayFor(r, i), i === this.selected ? 0.45 : 0.22, i === this.selected && !sam);
                this.drawLines(ctx, r.strokes, i === this.selected ? "#ffe563" : COLORS[i % COLORS.length], 2 / this.view.scale);
                this.drawLines(ctx, r.walls, "#ff795e", 3 / this.view.scale);
            });
            if (sam) this.drawCoverage(ctx, sam.change, 0.5, true);
        }
        if (this.unified && !this.renderMode && this.basicLines?.length) {
            ctx.setLineDash([6 / this.view.scale, 4 / this.view.scale]); this.drawLines(ctx, this.basicLines, "#8edcff", 1 / this.view.scale); ctx.setLineDash([]);
        }
        if (this.drag?.points) this.drawLines(ctx, [this.drag.points], this.drag.tool === "erase" ? "#ff7777" : "#ffffff", ["paint", "erase"].includes(this.drag.tool) ? this.radius * 2 : 2 / this.view.scale);
        ctx.restore();
        if (this.renderMode) {
            this.detailTitle.textContent = `细节 · ${(this.view.scale * 100).toFixed(0)}% · 拖动平移，滚轮缩放`;
            this.drawOverview();
        }
    }

    drawLines(ctx, lines = [], color, width) {
        ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineCap = ctx.lineJoin = "round";
        for (const line of lines) {
            if (!line.length) continue;
            ctx.beginPath(); ctx.moveTo(...line[0]); for (const p of line.slice(1)) ctx.lineTo(...p); ctx.stroke();
        }
    }

    schedule() {
        if (this.closed) return;
        this.revision++; this.pending?.abort(); clearTimeout(this.timer);
        this.timer = setTimeout(() => this.preview().catch(e => this.error(e)), 300);
    }

    async preview() {
        if (!this.base || this.closed) return;
        const revision = this.revision, index = this.index;
        const controller = new AbortController(); this.pending = controller;
        const body = { session: this.payload.session, revision, client: this.client, index };
        let rect = null, overviewKey = null;
        if (this.renderMode) {
            body.params = Object.fromEntries(PARAM_KEYS.map(k => [k, value(this.node, k, this.payload.params[k])]));
            body.seed = value(this.node, "seed", 20261005); body.color_exclude = value(this.node, "color_exclude", true);
            body.diagnostics = !!this.diagnostics;
            overviewKey = JSON.stringify([index, body.params, body.seed, body.color_exclude, body.diagnostics]);
            body.overview = overviewKey !== this.overviewKey;
            if (this.view.scale >= 1) {
                const x0 = Math.max(0, Math.min(this.payload.width - 1, Math.floor(-this.view.x / this.view.scale)));
                const y0 = Math.max(0, Math.min(this.payload.height - 1, Math.floor(-this.view.y / this.view.scale)));
                rect = [x0, y0, Math.max(x0 + 1, Math.min(this.payload.width, Math.ceil((this.stage.clientWidth - this.view.x) / this.view.scale))),
                    Math.max(y0 + 1, Math.min(this.payload.height, Math.ceil((this.stage.clientHeight - this.view.y) / this.view.scale)))];
                body.rect = rect;
            }
        } else {
            body.guides_json = JSON.stringify(this.doc); body.batch_mode = this.batchMode; body.advanced = !this.unified;
        }
        if (this.unified) {
            this.flushPlanes(); body.guides_json = JSON.stringify(this.doc); body.settings = this.settings;
            body.view = this.renderMode ? "texture" : "guides";
            overviewKey = JSON.stringify([this.doc, this.settings, index, this.diagnostics]);
            body.overview = this.renderMode && overviewKey !== this.overviewKey;
            this.previewRect = rect;
        }
        this.status.textContent = `底图 ${this.payload.identity.slice(0, 10)} · 计算版本 ${revision}…`;
        const result = await post("preview", body, controller.signal);
        if (result.stale || !isCurrent(revision, this.revision, this.closed, index, this.index)) return;
        const bitmap = await decodePNG(result.png);
        const overview = result.overview_png ? await decodePNG(result.overview_png) : null;
        if (!isCurrent(revision, this.revision, this.closed, index, this.index)) return;
        if (overview) { this.overviewBitmap = overview; this.overviewKey = overviewKey; }
        this.previewBitmap = bitmap; this.previewRect = rect; this.draw();
        const info = result.info;
        this.basicLines = info.basic_guides || [];
        if (this.renderMode) this.refreshRenderControls(info);
        this.status.textContent = this.renderMode
            ? `版本 ${revision} · 周期 ${info.period.toFixed(2)}px · ${body.params.strength_auto ? "自动" : "手动"}强度 ${Number(info.effective_strength).toFixed(1)}% · 过密衰减 ${(100 * info.faded_fraction).toFixed(1)}% · ${(1000 * info.render_seconds).toFixed(0)}ms${info.clamped ? " · 已限制过高密度" : ""}${info.notes?.length ? `\n${info.notes.join("；")}` : ""}`
            : `底图 ${this.payload.identity.slice(0, 10)} · 版本 ${revision} · 求解 ${(1000 * info.solve_seconds).toFixed(0)}ms · 部位缓存 ${info.cache_hits} 命中 / ${info.cache_misses} 重算 · 未引导 ${info.unguided_pixels} 像素`;
        if (this.unified) this.status.textContent += `\n选区 ${(100 * info.coverage_fraction).toFixed(2)}% · 实际变化 ${(100 * info.changed_fraction).toFixed(2)}% · ${info.direction_source === "manual" ? "手绘走向" : "基础走向（虚线）+ 手绘优先"}${info.failure_reason ? " · 未生效：" + info.failure_reason : " · 纹理已生效"}`;
    }

    buildUnified() {
        this.tabs = el("div", null, this.head, { className: "tb-stocking-candidates" });
        for (const [tab, title] of [["parts", "部位"], ["guides", "走向"], ["texture", "纹理"]]) {
            this.button(this.tabs, title, () => this.switchTab(tab)).dataset.tab = tab;
        }
        this.regionPanel = this.sidebar;
        this.texturePanel = el("div", null, this.body, { className: "tb-stocking-sidebar", hidden: true });
        this.body.insertBefore(this.texturePanel, this.regionPanel);
        this.sidebar = this.texturePanel; this.buildRenderControls(); this.sidebar = this.regionPanel;
        this.buildOverview(this.body); this.overviewPane = this.overviewArea.parentElement;
        this.body.insertBefore(this.overviewPane, this.stage.parentElement);
        this.resize.observe(this.overviewArea);
        const group = el("div", null, this.regionPanel); this.unifiedControls = group;
        const sourceLabel = el("label", "选区来源（未编辑图片逐图处理）", group);
        this.sourceInput = el("select", null, sourceLabel);
        for (const [v, label] of [["semantic", "SAM3 语义识别"], ["manual", "手工 / 原有点选"], ["mask", "外部 MASK"]]) el("option", label, this.sourceInput, { value: v });
        this.sourceInput.dataset.setting = "source_mode";
        this.sourceInput.value = this.settings.source_mode;
        this.sourceInput.onchange = () => { this.settings.source_mode = this.sourceInput.value; };
        const promptLabel = el("label", "SAM3 提示词", group);
        this.promptInput = el("input", null, promptLabel, { value: this.settings.prompt || "stockings" });
        this.promptInput.dataset.setting = "prompt";
        this.promptInput.onchange = () => this.settings.prompt = this.promptInput.value;
        const thresholdLabel = el("label", "识别阈值", group);
        this.thresholdInput = el("input", null, thresholdLabel, { type: "number", min: 0, max: 1, step: 0.01, value: this.settings.threshold ?? 0.4 });
        this.thresholdInput.dataset.setting = "threshold";
        this.thresholdInput.onchange = () => this.settings.threshold = Number(this.thresholdInput.value);
        this.semanticButton = this.button(group, "SAM3 识别当前图片", () => this.semantic());
        this.semanticButton.disabled = !this.payload.sam3_available;
        el("small", this.payload.sam3_available ? "stockings / pantyhose / tights；识别结果先预览，应用后可用原有点选和画笔修边。" : "语义识别需连接 Easy-Sam3 image 模型；原有 ViT-B 点选和画笔可独立使用。", group);
        const autoLabel = el("label", "无手绘走向时生成基础走向", group);
        const auto = el("input", null, autoLabel, { type: "checkbox", checked: this.settings.auto_direction !== false });
        auto.dataset.setting = "auto_direction";
        auto.onchange = () => { this.settings.auto_direction = auto.checked; this.schedule(); };
        if (this.payload.legacy) this.button(group, "导入旧引导并绑定当前图片", () => {
            if (this.payload.legacy.width !== this.payload.width || this.payload.legacy.height !== this.payload.height) throw new Error("旧引导尺寸不同，不能自动拉伸");
            if (!confirm("请确认旧引导属于当前底图。导入后检查选区，并保存以绑定图片。")) return;
            this.remember(); this.doc.frames[this.index] = structuredClone(this.payload.legacy.frames[0]); this.updateDraft(); this.loadPlanes();
        });
        const failureLabel = el("label", "失败图片处理", group);
        const failure = el("select", null, failureLabel); failure.dataset.setting = "failure_mode";
        el("option", "跳过并报告（默认）", failure, { value: "skip" }); el("option", "立即停止", failure, { value: "error" });
        failure.value = this.settings.failure_mode || "skip"; failure.onchange = () => this.settings.failure_mode = failure.value;
        const directionLabel = el("label", "深度方向", group);
        const direction = el("select", null, directionLabel); direction.dataset.setting = "depth_direction";
        el("option", "白色更近", direction, { value: "white_near" }); el("option", "黑色更近", direction, { value: "black_near" });
        direction.value = this.settings.depth_direction || "white_near";
        direction.onchange = () => { this.settings.depth_direction = direction.value; this.schedule(); };
        const wallsLabel = el("label", "深度自动隔开", group);
        const walls = el("input", null, wallsLabel, { type: "checkbox", checked: this.settings.auto_walls !== false }); walls.dataset.setting = "auto_walls";
        walls.onchange = () => { this.settings.auto_walls = walls.checked; this.schedule(); };
        for (const control of this.overlay.querySelectorAll("[data-setting]")) {
            if (this.node.inputs?.some(i => i.name === control.dataset.setting && i.link != null)) {
                control.disabled = true; control.title = "由上游输入控制；预览使用已解析值";
            }
        }
        this.switchTab("texture");
    }

    switchTab(tab) {
        this.flushPlanes(); this.tab = tab; this.renderMode = tab === "texture";
        this.regionPanel.hidden = this.renderMode; this.texturePanel.hidden = !this.renderMode;
        this.overviewPane.hidden = !this.renderMode;
        this.tools.hidden = this.renderMode;
        this.tool = this.renderMode ? "pan" : tab === "guides" ? "stroke" : "paint";
        this.previewBitmap = null; this.overviewKey = null;
        if (this.renderMode) this.setEditorCompare(true);
        this.editorRightLabel.textContent = this.renderMode ? "纹理效果" : "选区预览";
        for (const b of this.tabs.querySelectorAll("button")) b.classList.toggle("active", b.dataset.tab === tab);
        this.markTools(); this.draw(); this.schedule();
    }

    async semantic() {
        if (this.samPending) return;
        this.cancelSAM();
        const index = this.index, region = this.region(), token = this.samRequests.begin(index, region);
        const current = () => this.samRequests.matches(token, this.closed, this.index, this.region());
        this.samController = new AbortController(); this.samStatus.hidden = false; this.samCancel.hidden = false; this.samPending = true;
        this.samText.textContent = "SAM3 语义识别中；可继续画笔编辑，GPU 正式队列忙时等待。";
        this.samTimeout = setTimeout(() => this.cancelSAM("SAM3 等待超过 120 秒，请检查模型和队列；可继续手工编辑。"), 120000);
        let result;
        try {
            result = await post("semantic", { session: this.payload.session, index, prompt: this.settings.prompt, threshold: this.settings.threshold }, this.samController.signal);
        } catch (e) {
            if (current()) this.samText.textContent = `SAM3 失败：${e.message}；可继续手工编辑。`;
            return;
        } finally {
            if (current()) { clearTimeout(this.samTimeout); this.samPending = false; this.samCancel.hidden = true; }
        }
        if (!current()) return;
        if (!result.regions.length) { this.samText.textContent = "没有检测到目标；可修改提示词/阈值，或使用原有点选与画笔。"; return; }
        this.switchTab("parts"); this.semanticPreview = result.regions;
        this.samText.textContent = `SAM3 检测到 ${result.regions.length} 个部位 · ${result.seconds.toFixed(2)}s；选择要应用的实例。`;
        this.samControls.replaceChildren();
        const picks = result.regions.map(r => {
            const row = el("label", r.name, this.samControls);
            return el("input", null, row, { type: "checkbox", checked: true });
        });
        let serial = 0;
        const refresh = async () => {
            const revision = ++serial, preview = plane(this.payload.width, this.payload.height);
            for (let i = 0; i < result.regions.length; i++) if (picks[i].checked) {
                const image = await decodePNG(result.regions[i].mask);
                if (!current() || revision !== serial) return;
                const ctx = preview.getContext("2d"); ctx.globalCompositeOperation = "lighten"; ctx.drawImage(image, 0, 0);
            }
            if (!current() || revision !== serial) return;
            this.semanticMaskPreview = preview; this.setEditorCompare(true); this.draw();
        };
        for (const pick of picks) pick.onchange = () => refresh().catch(e => this.error(e));
        await refresh();
        if (!current()) return;
        this.button(this.samControls, "应用语义选区", () => {
            if (!current()) return;
            this.remember(); this.frame().regions.push(...result.regions.filter((r, i) => picks[i].checked).map(r => ({ ...r, id: crypto.randomUUID() })));
            this.selected = this.frame().regions.length - 1; this.cancelSAM(); this.updateDraft(); this.loadPlanes();
        });
        this.button(this.samControls, "取消语义选区", () => this.cancelSAM());
    }

    cancelSAM(message = "") {
        this.samRequests.invalidate(); this.samController?.abort(); this.samPending = false;
        this.samCandidates = null; this.semanticMaskPreview = null; this.semanticPreview = null;
        clearTimeout(this.samTimeout); clearInterval(this.samTicker);
        this.samControls?.replaceChildren();
        if (this.samStatus) { this.samStatus.hidden = !message; this.samText.textContent = message; this.samCancel.hidden = true; }
        this.draw();
    }

    async samClick(point, subtract) {
        if (this.samPending) return; // One request per editor; repeated clicks do not queue more encoders.
        this.cancelSAM();
        const index = this.index, r = this.region(), token = this.samRequests.begin(index, r);
        const controller = new AbortController(); this.samController = controller;
        const current = () => this.samRequests.matches(token, this.closed, this.index, this.region());
        this.samPending = true; this.samStatus.hidden = false; this.samCancel.hidden = false;
        const start = performance.now();
        const progress = () => {
            const seconds = Math.floor((performance.now() - start) / 1000);
            this.samText.textContent = `SAM 分析中 ${seconds}s · 会话设备 ${this.payload.sam_device || "auto"} · 首次点击需加载模型并计算图像 embedding；可继续使用画笔。`;
        };
        progress(); this.samTicker = setInterval(progress, 1000);
        this.samTimeout = setTimeout(() => this.cancelSAM("SAM 等待超过 120 秒，已停止等待；请检查容器 SAM 日志。后台已开始的推理可能仍在完成。"), 120000);
        let result;
        try {
            result = await post("sam", { session: this.payload.session, index, x: point[0], y: point[1] }, controller.signal);
        } catch (e) {
            if (current()) this.samText.textContent = `SAM 失败：${e.message}；可继续绘制或重新点选。`;
            return;
        } finally {
            if (current()) { clearTimeout(this.samTimeout); clearInterval(this.samTicker); this.samPending = false; this.samCancel.hidden = true; }
        }
        if (!current()) return;
        const info = result.info;
        this.samText.textContent = `SAM 完成 · ${info?.device || "设备未报告"} · ${(info?.seconds ?? (performance.now() - start) / 1000).toFixed(2)}s${info?.embedding_cached ? " · 复用图像 embedding" : ""} · 已预览推荐范围；切换小 / 中 / 大后，点击应用选区。${info?.offloaded_to_cpu ? "模型已移回 CPU。" : ""}`;
        this.samControls.replaceChildren();
        el("small", subtract ? "红色：预览将减去的范围（尚未应用）" : "绿色：预览将添加的范围（尚未应用）", this.samControls);
        this.samCandidates = { token, masks: result.masks, subtract, best: result.best, selected: -1, serial: 0, decoded: new Map(), rgba: null, visual: null };
        const row = el("div", null, this.samControls, { className: "tb-stocking-candidates" });
        this.samCandidateButtons = ["小", "中", "大"].map((label, k) => this.button(row, `${label}${k === result.best ? "（推荐）" : ""}`, () => this.selectSAMCandidate(k)));
        this.samApply = this.button(this.samControls, "应用选区", () => this.applySAMSelection()); this.samApply.disabled = true;
        this.button(this.samControls, "取消本次点选", () => this.cancelSAM("已取消本次点选，已有选区未改变。"));
        this.setEditorCompare(true);
        await this.selectSAMCandidate(result.best);
        if (!current()) return;
        this.samControls.scrollIntoView({ block: "nearest" });
    }

    async selectSAMCandidate(index) {
        const group = this.samCandidates;
        const current = () => this.samCandidates === group && this.samRequests.matches(group.token, this.closed, this.index, this.region());
        if (!group || !current()) return;
        const serial = ++group.serial;
        group.selected = index; group.rgba = null; group.visual = null; this.samApply.disabled = true;
        this.samCandidateButtons.forEach((b, k) => { b.classList.toggle("active", k === index); b.setAttribute("aria-pressed", String(k === index)); });
        this.draw();
        if (!group.decoded.has(index)) {
            const selected = await decodePNG(group.masks[index]);
            if (!current() || serial !== group.serial) return;
            const w = this.payload.width, h = this.payload.height;
            if (selected.naturalWidth !== w || selected.naturalHeight !== h) throw new Error("SAM 候选遮罩尺寸与底图不一致");
            const c = plane(w, h); c.getContext("2d").drawImage(selected, 0, 0);
            group.decoded.set(index, c.getContext("2d").getImageData(0, 0, w, h).data);
        }
        if (!current() || serial !== group.serial) return;
        group.rgba = group.decoded.get(index); this.samApply.disabled = false; this.draw();
    }

    applySAMSelection() {
        const group = this.samCandidates;
        if (!group?.rgba || !this.samRequests.matches(group.token, this.closed, this.index, this.region())) return;
        const p = this.planes.get(this.region().id); if (!p) return;
        this.remember();
        const w = this.payload.width, h = this.payload.height;
        const maskContext = p.mask.getContext("2d"), eraseContext = p.erase.getContext("2d");
        const paint = maskContext.getImageData(0, 0, w, h), erase = eraseContext.getImageData(0, 0, w, h);
        applyCandidate(paint.data, erase.data, group.rgba, group.subtract);
        maskContext.putImageData(paint, 0, 0); eraseContext.putImageData(erase, 0, 0);
        p.dirty = true; this.overlays.delete(this.region().id);
        const label = ["小", "中", "大"][group.selected];
        this.cancelSAM(`已${group.subtract ? "减去" : "添加"} SAM ${label}候选；保存并关闭后写入工作流。`);
        this.updateDraft(); this.draw();
    }

    key(e) {
        if (this.closed) return;
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.close(); return; }
        if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
        if (e.code === "Space") { this.space = true; e.preventDefault(); }
        if (!this.renderMode) {
            const key = e.key.toLowerCase();
            const map = { b: "paint", e: "erase", p: "stroke", w: "wall", s: "sam" };
            if (map[key] && (key !== "s" || this.payload.sam_available)) { this.tool = map[key]; this.markTools(); }
            if ((e.ctrlKey || e.metaKey) && key === "z") { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); }
        }
    }

    close(save = false) {
        if (this.closed) return;
        if (save && this.draft && this.unified) {
            this.flushPlanes();
            setValue(this.node, "guides_json", recordsForSave(widget(this.node, "guides_json")?.value, this.doc, this.payload.identities, JSON.parse(this.initialDocument)));
            for (const [key, val] of Object.entries(this.settings)) {
                if (SETTING_KEYS.includes(key) && !this.node.inputs?.some(i => i.name === key && i.link != null)) setValue(this.node, key, val);
            }
        } else if (!this.renderMode && save && this.draft) {
            this.flushPlanes(); this.draft.save((name, val) => setValue(this.node, name, val));
        }
        if (this.unified) updateSummary(this.node);
        this.closed = true; clearTimeout(this.timer); this.controller.abort(); this.pending?.abort(); this.resize.disconnect();
        this.cancelSAM(); this.localeObserver?.disconnect();
        document.removeEventListener("keydown", this.keyboard); this.base?.close(); this.external?.close(); this.overlay.remove();
        if (this.node.__stockingDialog === this) this.node.__stockingDialog = null;
    }
}

function updateSummary(node) {
    const summary = node.__stockingSummary;
    if (!summary) return;
    const locale = app.extensionManager?.setting?.get("Comfy.Locale") || "zh";
    const style = widget(node, "style")?.value || "knit";
    const mode = widget(node, "source_mode")?.value || "semantic";
    const source = { semantic: "SAM3 语义识别", manual: "手工 / 原有点选", mask: "外部 MASK" }[mode];
    summary.value = translate(`${source} · ${STYLE_LABELS[style]} · ${widget(node, "strength_auto")?.value ? "自动强度" : "手动强度 " + widget(node, "strength")?.value + "%"}`, locale);
    node.graph?.setDirtyCanvas?.(true, true);
}

async function prepareNode(node, attempt = 0) {
    const graph = await app.graphToPrompt();
    const inputs = graph.output[String(node.id)]?.inputs;
    if (!inputs?.images) throw new Error("请连接 IMAGE 底图");
    const settings = Object.fromEntries(SETTING_KEYS.map(k => [k, inputs[k]]).filter(([, v]) => v !== undefined && !Array.isArray(v)));
    const source = Array.isArray(inputs.images) ? graph.output[inputs.images[0]] : null;
    const sampler = Array.isArray(inputs.sam) ? graph.output[inputs.sam[0]] : null;
    const direct = source?.class_type === "LoadImage" && typeof source.inputs.image === "string"
        && !["mask", "depth", "sparkle_mask", "sam3_model"].some(k => inputs[k] !== undefined)
        && !SETTING_KEYS.some(k => Array.isArray(inputs[k]))
        && (!inputs.sam || sampler?.class_type === "NFStockingSAMLoader");
    const assertCurrent = async payload => {
        const latest = (await app.graphToPrompt()).output;
        const actual = latest[String(node.id)]?.inputs;
        const signature = (graph, resolved) => JSON.stringify(capturePrompt(graph, { ...resolved }, "recipe"));
        if (!actual || signature(latest, actual) !== signature(graph.output, inputs)) {
            if (attempt >= 2) throw new Error("上游持续变化，请稳定底图后重新打开编辑器");
            return prepareNode(node, attempt + 1);
        }
        return payload;
    };
    if (direct) return assertCurrent(await post("prepare", { image: source.inputs.image, settings, guides_json: inputs.guides_json || "{}", sam: sampler?.inputs }));
    const captureId = `stocking-prepare-${crypto.randomUUID()}`;
    const captureInputs = { images: inputs.images, guides_json: inputs.guides_json || "{}", settings_json: JSON.stringify(settings) };
    for (const k of ["mask", "depth", "sparkle_mask", "sam", "sam3_model", ...SETTING_KEYS]) if (inputs[k] !== undefined) captureInputs[k] = inputs[k];
    const prompt = capturePrompt(graph.output, captureInputs, captureId);
    const response = await api.fetchApi("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, client_id: api.clientId, partial_execution_targets: [captureId] }) });
    const queued = await response.json();
    if (!response.ok) throw new Error(queued.error?.message || JSON.stringify(queued.node_errors || queued));
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline) {
        if (node.__stockingPrepareCancelled) throw new Error("已取消准备");
        const history = await (await api.fetchApi(`/history/${queued.prompt_id}`)).json();
        const entry = history[queued.prompt_id];
        if (entry) {
            const payload = entry.outputs?.[captureId]?.nf_stocking?.[0];
            if (payload) return assertCurrent(payload);
            const error = entry.status?.messages?.find(m => m[0] === "execution_error")?.[1];
            throw new Error(error?.exception_message || "底图准备失败；请检查上游节点");
        }
        await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error("底图准备超时，请检查 ComfyUI 队列");
}

app.registerExtension({
    name: "ToolBox.StockingTexture",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!CLASSES.has(nodeData.name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            const w = widget(this, "guides_json");
            if (w) { w.type = "hidden"; w.computeSize = () => [0, -4]; if (w.inputEl) w.inputEl.style.display = "none"; }
            if (nodeData.name === "NFStockingRender") {
                const strength = widget(this, "strength"), callback = strength?.callback, node = this;
                if (strength) strength.callback = function () {
                    setValue(node, "strength_auto", false);
                    return callback?.apply(this, arguments);
                };
            }
            const unified = nodeData.name === "NFStockingTexture";
            if (unified) {
                for (const w of this.widgets || []) {
                    w.type = "hidden"; w.computeSize = () => [0, -4];
                    if (w.inputEl) w.inputEl.style.display = "none";
                }
                this.__stockingSummary = this.addWidget("text", translate("状态", app.extensionManager?.setting?.get("Comfy.Locale") || "zh"), "", () => {}, { serialize: false });
                updateSummary(this);
            }
            if (nodeData.name !== "NFStockingRender") this.addWidget("button", translate(unified ? "编辑与预览" : "编辑丝袜引导", app.extensionManager?.setting?.get("Comfy.Locale") || "zh"), null, async () => {
                if (this.__stockingPreparing) return;
                this.__stockingPreparing = true;
                app.extensionManager?.toast?.add({ severity: "info", summary: "正在准备当前底图；只执行必要上游，不运行下游保存节点", life: 4000 });
                try {
                    let payload = await prepareNode(this);
                    if (!unified) {
                        // The advanced editor keeps its v1 schema. A new picture gets
                        // an independent draft; a stale size cannot prevent opening.
                        const raw = JSON.parse(value(this, "guides_json", "{}"));
                        if (raw.version === 1 && raw.width === payload.width && raw.height === payload.height) payload.document = raw;
                        else if (value(this, "batch_mode", "shared") === "shared") payload.document.frames = [payload.document.frames[0]];
                    }
                    if (payload.preview_available === false) throw new Error("底图超过预览内存上限，请用单图编辑或缩小预览批次；正式批次仍可运行");
                    this.__stockingPayload = payload;
                    this.__stockingDialog?.close();
                    this.__stockingDialog = new StockingDialog(this, payload, false);
                } catch (e) { app.extensionManager?.toast?.add({ severity: "error", summary: e.message, life: 8000 }); console.error(e); }
                finally { this.__stockingPreparing = false; }
            }, { serialize: false });
            this.size[0] = Math.max(this.size[0], 300);
            return result;
        };
        const configured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = configured?.apply(this, arguments); updateSummary(this); return result;
        };
        const executed = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = executed?.apply(this, arguments);
            const payload = message?.nf_stocking?.[0];
            if (payload) { this.__stockingDialog?.close(); this.__stockingPayload = payload; updateSummary(this); }
            return result;
        };
        const removed = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () { this.__stockingDialog?.close(); return removed?.apply(this, arguments); };
    },
});

document.addEventListener("keyup", e => { if (e.code === "Space") for (const node of app.graph?._nodes || []) if (node.__stockingDialog) node.__stockingDialog.space = false; });
