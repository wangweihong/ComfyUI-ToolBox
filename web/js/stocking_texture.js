import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { fitView, imagePoint, zoomAt, isCurrent } from "./stocking_geometry.mjs";
import { GuideDraft, samHint } from "./stocking_editor_state.mjs";

const CLASSES = new Set(["NFStockingEditor", "NFStockingRender"]);
const API_ROOT = "/toolbox/stocking";
const COLORS = ["#48dfaf", "#ffb45a", "#96aaff", "#ff78c8"];
const STYLE_LABELS = { knit: "细线", loops: "针织", lines: "斜单线", grain: "加濑风", oily: "油光（试验）" };
const PARAM_KEYS = ["style", "density", "tilt", "strength", "strength_auto", "sparkle_depth", "sparkle_bright", "sparkle_painted", "sparkle_even"];
const widget = (node, name) => node.widgets?.find(w => w.name === name);
const value = (node, name, fallback) => widget(node, name)?.value ?? fallback;

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
    .tb-stocking-stage{flex:1;min-width:0;position:relative;background:#11151b;overflow:hidden}.tb-stocking-stage canvas{width:100%;height:100%;touch-action:none;display:block}
    .tb-stocking-dialog button,.tb-stocking-dialog input,.tb-stocking-dialog select{background:#303743;color:#eee;border:1px solid #596273;border-radius:5px;padding:6px}
    .tb-stocking-dialog button{cursor:pointer}.tb-stocking-dialog button:disabled{opacity:.4;cursor:default}.tb-stocking-dialog button.active{background:#236457;border-color:#56d7b7}
    .tb-stocking-sidebar label{display:flex;flex-direction:column;margin:9px 0;gap:5px}.tb-stocking-sidebar select,.tb-stocking-sidebar input{max-width:100%}
    .tb-stocking-status{padding:9px 14px;color:#c9d1db;font-size:12px;min-height:18px;white-space:pre-wrap}.tb-stocking-sidebar small{color:#b8c3d0;display:block;line-height:1.6}
    .tb-stocking-sam-hint{padding:8px 14px;background:#28303b;color:#d8e4ef;font-size:12px;line-height:1.5}.tb-stocking-save-state{color:#ffd37a;font-size:12px}
    @media(max-width:760px){.tb-stocking-sidebar{width:160px}.tb-stocking-dialog{height:96vh}.tb-stocking-head,.tb-stocking-tools{padding:6px}}
    `;
}

class StockingDialog {
    constructor(node, payload, render) {
        this.node = node; this.payload = payload; this.renderMode = render;
        this.index = 0; this.revision = 0; this.planeSerial = 0; this.client = crypto.randomUUID(); this.closed = false;
        this.selected = 0; this.tool = render ? "pan" : "paint"; this.radius = 14;
        this.draft = null;
        this.history = []; this.future = []; this.planes = new Map(); this.overlays = new Map();
        this.controller = new AbortController(); this.pending = null; this.previewBitmap = null; this.requestSerial = 0;
        styles();
        this.overlay = el("div", null, document.body, { className: "tb-stocking-overlay" });
        const dialog = el("div", null, this.overlay, { className: "tb-stocking-dialog" });
        dialog.setAttribute("role", "dialog"); dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-label", render ? "丝袜纹理预览" : "丝袜引导编辑器");
        const head = el("div", null, dialog, { className: "tb-stocking-head" });
        el("strong", render ? "丝袜纹理 · 自动细节预览" : "丝袜引导 · 部位、走向与隔开", head);
        this.indexSelect = el("select", null, head, { title: "当前图像" });
        for (let i = 0; i < payload.batch; i++) el("option", `图像 ${i + 1}/${payload.batch}`, this.indexSelect, { value: String(i) });
        this.indexSelect.onchange = () => this.loadIndex(Number(this.indexSelect.value)).catch(e => this.error(e));
        this.button(head, "适应", () => { this.view = fitView(payload.width, payload.height, this.stage.clientWidth, this.stage.clientHeight); this.draw(); });
        this.button(head, "100%", () => { this.view = { scale: 1, x: 0, y: 0 }; this.draw(); });
        this.button(head, "200%", () => { this.view = { scale: 2, x: 0, y: 0 }; this.draw(); });
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
        if (!render) {
            for (const [key, label] of [["paint", "画笔 B"], ["erase", "橡皮 E"], ["stroke", "走向 P"], ["wall", "隔开 W"], ["sam", "点选 S"], ["pan", "平移"]]) {
                const b = this.button(tools, label, () => { this.tool = key; this.markTools(); });
                b.dataset.tool = key;
                if (key === "sam") {
                    b.disabled = !payload.sam_available;
                    const connected = this.node.inputs?.find(i => i.name === "sam")?.link != null;
                    b.title = samHint(!!payload.sam_available, connected);
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
            el("div", samHint(!!payload.sam_available, connected), dialog, { className: "tb-stocking-sam-hint" });
        }
        const body = el("div", null, dialog, { className: "tb-stocking-body" });
        this.sidebar = el("div", null, body, { className: "tb-stocking-sidebar" });
        this.stage = el("div", null, body, { className: "tb-stocking-stage" });
        this.canvas = el("canvas", null, this.stage);
        this.status = el("div", "正在读取底图…", dialog, { className: "tb-stocking-status" });
        this.view = fitView(payload.width, payload.height, this.stage.clientWidth, this.stage.clientHeight);
        this.resize = new ResizeObserver(() => this.draw()); this.resize.observe(this.stage);
        this.keyboard = e => this.key(e); document.addEventListener("keydown", this.keyboard);
        this.canvas.onpointerdown = e => this.down(e); this.canvas.onpointermove = e => this.move(e);
        this.canvas.onpointerup = e => this.up(e); this.canvas.onpointercancel = () => { this.drag = null; this.draw(); };
        this.canvas.oncontextmenu = e => e.preventDefault();
        this.canvas.onwheel = e => {
            e.preventDefault(); const r = this.canvas.getBoundingClientRect();
            this.view = zoomAt(this.view, e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.001)); this.draw();
            if (this.renderMode) this.schedule();
        };
        this.markTools();
        if (render) this.buildRenderControls(); else this.readDocument();
        this.loadIndex(0).catch(e => this.error(e));
    }

    button(parent, label, fn) {
        const b = el("button", label, parent, { type: "button" });
        b.onclick = () => { Promise.resolve(fn(b)).catch(e => this.error(e)); };
        return b;
    }

    error(e) { if (!this.closed && e.name !== "AbortError") this.status.textContent = e.message; }
    markTools() { for (const b of this.overlay.querySelectorAll("[data-tool]")) b.classList.toggle("active", b.dataset.tool === this.tool); }

    readDocument() {
        const raw = value(this.node, "guides_json", "{}");
        try { this.draft = new GuideDraft(raw, value(this.node, "batch_mode", "shared"), this.payload.document); }
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
        this.sidebar.replaceChildren();
        const modeLabel = el("label", "批次引导", this.sidebar);
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
        this.regionSelect.onchange = () => { this.selected = Number(this.regionSelect.value); this.sourceCheck.checked = !!this.region()?.external; this.draw(); };
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
    }

    refreshRegions() {
        if (!this.regionSelect) return;
        this.regionSelect.replaceChildren();
        this.frame()?.regions.forEach((r, i) => el("option", `${i + 1}. ${r.name}${r.external ? "（输入遮罩）" : ""}`, this.regionSelect, { value: String(i) }));
        this.regionSelect.value = String(this.selected);
        if (this.sourceCheck) this.sourceCheck.checked = !!this.region()?.external;
    }

    buildRenderControls() {
        for (const key of [...PARAM_KEYS, "color_exclude", "seed"]) {
            const w = widget(this.node, key); if (!w) continue;
            const label = el("label", ({ style: "样式", density: "密度 %", tilt: "斜度 °", strength: "纹理强度 %",
                strength_auto: "自动强度", color_exclude: "颜色排除", sparkle_depth: "深度亮点 %", sparkle_bright: "高光亮点 %",
                sparkle_painted: "遮罩亮点 %", sparkle_even: "均匀亮点 %", seed: "随机种子" })[key], this.sidebar);
            let input;
            if (key === "style") {
                input = el("select", null, label);
                for (const [val, text] of Object.entries(STYLE_LABELS)) el("option", text, input, { value: val });
                input.value = w.value;
            } else if (typeof w.value === "boolean") input = el("input", null, label, { type: "checkbox", checked: w.value });
            else input = el("input", null, label, { type: "number", value: String(w.value), min: String(w.options?.min ?? 0), max: String(w.options?.max ?? 300), step: "1" });
            input.setAttribute("aria-label", label.firstChild.textContent);
            input.onchange = () => { setValue(this.node, key, input.type === "checkbox" ? input.checked : key === "style" ? input.value : Number(input.value)); this.schedule(); };
        }
        el("small", "预览使用上次执行的走向结果。修改引导后，重新执行工作流即可更新。平移/缩放会自动请求可见区域的原像素细节。", this.sidebar);
    }

    async loadIndex(index) {
        this.flushPlanes(); this.index = index; this.revision++; this.pending?.abort(); this.previewBitmap = null;
        const serial = ++this.requestSerial;
        this.samControls?.replaceChildren();
        const path = `${API_ROOT}/image?session=${this.payload.session}&index=${index}`;
        const bitmap = await imageFrom(path, this.controller.signal);
        if (this.closed || serial !== this.requestSerial) { bitmap.close(); return; }
        this.base?.close(); this.base = bitmap;
        if (!this.renderMode) {
            const external = await imageFrom(path + "&kind=external", this.controller.signal);
            if (this.closed || serial !== this.requestSerial) { external.close(); return; }
            this.external?.close(); this.external = external;
            this.selected = Math.min(this.selected, Math.max(0, (this.frame()?.regions.length || 1) - 1));
            await this.loadPlanes();
        }
        this.draw(); this.status.textContent = `底图 ${this.payload.identity.slice(0, 10)} · ${this.payload.width}×${this.payload.height} · 图像 ${index + 1}`;
        this.schedule();
    }

    async loadPlanes() {
        const serial = ++this.planeSerial;
        const next = new Map();
        for (const r of this.frame()?.regions || []) {
            const pair = { mask: plane(this.payload.width, this.payload.height), erase: plane(this.payload.width, this.payload.height) };
            for (const key of ["mask", "erase"]) if (r[key]) pair[key].getContext("2d").drawImage(await decodePNG(r[key]), 0, 0);
            next.set(r.id, pair);
        }
        if (this.closed || serial !== this.planeSerial) return;
        this.planes = next; this.overlays.clear(); this.refreshRegions(); this.draw(); this.schedule();
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
        if (this.saveState) this.saveState.textContent = this.draft.dirty ? "有未保存修改" : "尚未修改";
        this.schedule();
    }
    snapshot() { return JSON.stringify({ doc: this.doc, mode: this.batchMode, selected: this.selected }); }
    remember() {
        this.flushPlanes(); this.history.push(this.snapshot()); this.future = [];
        while (this.history.length > 30 || this.history.reduce((sum, s) => sum + s.length, 0) > 16 * 1024 * 1024) this.history.shift();
    }
    restore(raw) {
        const s = JSON.parse(raw); this.doc = s.doc; this.selected = s.selected;
        this.draft.mode = s.mode; this.updateDraft(); this.buildRegionControls(); this.loadPlanes();
    }
    undo() { if (this.history.length) { this.flushPlanes(); this.future.push(this.snapshot()); this.restore(this.history.pop()); } }
    redo() { if (this.future.length) { this.flushPlanes(); this.history.push(this.snapshot()); this.restore(this.future.pop()); } }
    removeLast(key) { if (this.region()?.[key]?.length) { this.remember(); this.region()[key].pop(); this.updateDraft(); this.draw(); } }

    point(e) { return imagePoint(e.clientX, e.clientY, this.canvas.getBoundingClientRect(), this.view, this.payload.width, this.payload.height); }
    down(e) {
        if (!this.base || this.loading) return;
        this.canvas.setPointerCapture(e.pointerId);
        if (this.tool === "pan" || this.space || e.button === 1 || this.renderMode) {
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

    overlayFor(r, index) {
        if (this.overlays.has(r.id)) return this.overlays.get(r.id);
        const p = this.planes.get(r.id); if (!p) return null;
        const w = this.payload.width, h = this.payload.height;
        const paint = p.mask.getContext("2d").getImageData(0, 0, w, h).data;
        const erased = p.erase.getContext("2d").getImageData(0, 0, w, h).data;
        let base;
        if (r.external && this.external) {
            const c = plane(w, h); c.getContext("2d").drawImage(this.external, 0, 0);
            base = c.getContext("2d").getImageData(0, 0, w, h).data;
        }
        const c = document.createElement("canvas"); c.width = w; c.height = h;
        const ctx = c.getContext("2d"), out = ctx.createImageData(w, h);
        const color = COLORS[index % COLORS.length].match(/\w\w/g).map(v => parseInt(v, 16));
        for (let k = 0; k < paint.length; k += 4) {
            out.data[k] = color[0]; out.data[k + 1] = color[1]; out.data[k + 2] = color[2];
            out.data[k + 3] = Math.round(Math.max(paint[k], base?.[k] || 0) * (1 - erased[k] / 255) * 0.38);
        }
        ctx.putImageData(out, 0, 0); this.overlays.set(r.id, c); return c;
    }

    draw() {
        if (this.closed || !this.canvas) return;
        const w = this.stage.clientWidth, h = this.stage.clientHeight, dpr = window.devicePixelRatio || 1;
        if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
            this.canvas.width = Math.round(w * dpr); this.canvas.height = Math.round(h * dpr);
        }
        const ctx = this.canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
        ctx.save(); ctx.translate(this.view.x, this.view.y); ctx.scale(this.view.scale, this.view.scale);
        ctx.imageSmoothingEnabled = this.view.scale < 1;
        if (this.base) ctx.drawImage(this.base, 0, 0);
        if (this.previewBitmap && !this.showOriginal) ctx.drawImage(this.previewBitmap, ...(this.previewRect ? [this.previewRect[0], this.previewRect[1]] : [0, 0]));
        if (!this.renderMode && this.doc) {
            this.frame()?.regions.forEach((r, i) => {
                const o = this.overlayFor(r, i); if (o) ctx.drawImage(o, 0, 0);
                this.drawLines(ctx, r.strokes, i === this.selected ? "#ffe563" : COLORS[i % COLORS.length], 2 / this.view.scale);
                this.drawLines(ctx, r.walls, "#ff795e", 3 / this.view.scale);
            });
        }
        if (this.drag?.points) this.drawLines(ctx, [this.drag.points], this.drag.tool === "erase" ? "#ff7777" : "#ffffff", ["paint", "erase"].includes(this.drag.tool) ? this.radius * 2 : 2 / this.view.scale);
        ctx.restore();
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
        let rect = null;
        if (this.renderMode) {
            body.params = Object.fromEntries(PARAM_KEYS.map(k => [k, value(this.node, k, this.payload.params[k])]));
            body.seed = value(this.node, "seed", 20261005); body.color_exclude = value(this.node, "color_exclude", true);
            body.diagnostics = !!this.diagnostics;
            if (this.view.scale >= 1) {
                const x0 = Math.max(0, Math.min(this.payload.width - 1, Math.floor(-this.view.x / this.view.scale)));
                const y0 = Math.max(0, Math.min(this.payload.height - 1, Math.floor(-this.view.y / this.view.scale)));
                rect = [x0, y0, Math.max(x0 + 1, Math.min(this.payload.width, Math.ceil((this.stage.clientWidth - this.view.x) / this.view.scale))),
                    Math.max(y0 + 1, Math.min(this.payload.height, Math.ceil((this.stage.clientHeight - this.view.y) / this.view.scale)))];
                body.rect = rect;
            }
        } else {
            body.guides_json = JSON.stringify(this.doc); body.batch_mode = this.batchMode;
        }
        this.status.textContent = `底图 ${this.payload.identity.slice(0, 10)} · 计算版本 ${revision}…`;
        const result = await post("preview", body, controller.signal);
        if (result.stale || !isCurrent(revision, this.revision, this.closed, index, this.index)) return;
        const bitmap = await decodePNG(result.png);
        if (!isCurrent(revision, this.revision, this.closed, index, this.index)) return;
        this.previewBitmap = bitmap; this.previewRect = rect; this.draw();
        const info = result.info;
        this.status.textContent = this.renderMode
            ? `版本 ${revision} · 周期 ${info.period.toFixed(2)}px · 自动强度 ${info.effective_strength}% · 过密衰减 ${(100 * info.faded_fraction).toFixed(1)}% · ${(1000 * info.render_seconds).toFixed(0)}ms${info.clamped ? " · 已限制过高密度" : ""}`
            : `底图 ${this.payload.identity.slice(0, 10)} · 版本 ${revision} · 求解 ${(1000 * info.solve_seconds).toFixed(0)}ms · 部位缓存 ${info.cache_hits} 命中 / ${info.cache_misses} 重算 · 未引导 ${info.unguided_pixels} 像素`;
    }

    async samClick(point, subtract) {
        const index = this.index, r = this.region(), rev = this.revision;
        this.status.textContent = "SAM 分析中；可继续使用画笔…";
        const result = await post("sam", { session: this.payload.session, index, x: point[0], y: point[1] }, this.controller.signal);
        if (this.closed || index !== this.index || r !== this.region() || rev !== this.revision) return;
        this.samControls.replaceChildren();
        el("small", subtract ? "选择减去范围" : "选择添加范围", this.samControls);
        ["小", "中", "大"].forEach((label, k) => this.button(this.samControls, `${label}${k === result.best ? " ✓" : ""}`, async () => {
            if (this.closed || index !== this.index || r !== this.region()) return;
            const selected = await decodePNG(result.masks[k]);
            this.remember(); const p = this.planes.get(r.id), w = this.payload.width, h = this.payload.height;
            const c = plane(w, h); c.getContext("2d").drawImage(selected, 0, 0);
            const candidate = c.getContext("2d").getImageData(0, 0, w, h).data;
            for (const key of ["mask", "erase"]) {
                const ctx = p[key].getContext("2d"), pixels = ctx.getImageData(0, 0, w, h);
                for (let j = 0; j < candidate.length; j += 4) if (candidate[j] > 127) {
                    const val = (key === "erase") === subtract ? 255 : 0;
                    pixels.data[j] = pixels.data[j + 1] = pixels.data[j + 2] = val;
                }
                ctx.putImageData(pixels, 0, 0);
            }
            p.dirty = true; this.overlays.delete(r.id); this.updateDraft(); this.draw();
        }));
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
        if (!this.renderMode && save && this.draft) {
            this.flushPlanes(); this.draft.save((name, val) => setValue(this.node, name, val));
        }
        this.closed = true; clearTimeout(this.timer); this.controller.abort(); this.pending?.abort(); this.resize.disconnect();
        document.removeEventListener("keydown", this.keyboard); this.base?.close(); this.external?.close(); this.overlay.remove();
        if (this.node.__stockingDialog === this) this.node.__stockingDialog = null;
    }
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
            this.addWidget("button", nodeData.name === "NFStockingEditor" ? "编辑丝袜引导" : "纹理细节预览", null, () => {
                if (!this.__stockingPayload) { app.extensionManager?.toast?.add({ severity: "info", summary: "先执行一次此节点，获取上游底图", life: 5000 }); return; }
                if (this.__stockingPayload.preview_available === false) { app.extensionManager?.toast?.add({ severity: "info", summary: "批次超过预览内存上限，请分批执行后编辑或预览", life: 5000 }); return; }
                this.__stockingDialog?.close();
                try { this.__stockingDialog = new StockingDialog(this, this.__stockingPayload, nodeData.name === "NFStockingRender"); }
                catch (e) { console.error(e); }
            }, { serialize: false });
            if (nodeData.name === "NFStockingEditor") this.addWidget("button", "清空引导（底图尺寸改变时）", null, () => {
                this.__stockingDialog?.close(); setValue(this, "guides_json", "{}"); this.__stockingPayload = null;
            }, { serialize: false });
            this.size[0] = Math.max(this.size[0], 300);
            return result;
        };
        const executed = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = executed?.apply(this, arguments);
            const payload = message?.nf_stocking?.[0];
            if (payload) { this.__stockingDialog?.close(); this.__stockingPayload = payload; }
            return result;
        };
        const removed = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () { this.__stockingDialog?.close(); return removed?.apply(this, arguments); };
    },
});

document.addEventListener("keyup", e => { if (e.code === "Space") for (const node of app.graph?._nodes || []) if (node.__stockingDialog) node.__stockingDialog.space = false; });
