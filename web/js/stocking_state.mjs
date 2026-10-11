export function createState(runtime) {
    const {app,api,fitView,imagePoint,zoomAt,isCurrent,GuideDraft,samHint,SAMRequests,STYLE_LABELS,STYLE_HINTS,PARAM_KEYS,SLIDERS,parameterPatch,applyCandidate,selectionCoverage,maskBoundarySegments,splitRatio,compareKey,canvasMetrics,translate,SETTING_KEYS,recordsForSave,capturePrompt,PATTERN_STYLES,readEffects,effectPatch,damageStroke,upgradeEffectsValue,RENDER_DEFAULTS,MATERIAL_DEFAULTS,nearestPath,nearestPoint,claimPixels,linkedSparklePatch,SCHEMA,normalizeEffects,API_ROOT,COLORS,widget,value,globalValue,setValue,el,imageFrom,decodePNG,post,plane,rasterPaint}=runtime;
    return class {
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
                this.mirrorInfo=null;
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
        this.updateSaveState(); this.scheduleDraftSave();
        this.schedule();
    }

    snapshot() { return JSON.stringify({ doc: this.doc, mode: this.batchMode, selected: this.selected, index: this.index, settings: this.settings,
        initialDocument:this.initialDocument, initialSettings:this.initialSettings }); }

    remember() {
        this.flushPlanes(); this.history.push(this.snapshot()); this.future = [];
        while (this.history.length > 30 || this.history.reduce((sum, s) => sum + s.length, 0) > 16 * 1024 * 1024) this.history.shift();
    }

    restore(raw) {
        const s = JSON.parse(raw); this.doc = s.doc; this.selected = s.selected; this.rebuildLayers=true;
        if(s.initialDocument)this.initialDocument=s.initialDocument;
        if(s.initialSettings)this.initialSettings=s.initialSettings;
        if (s.settings) this.settings = s.settings;
        this.draft.mode = s.mode; this.updateDraft(); this.buildRegionControls();
        if (this.materialPanel || this.styleSelect) this.refreshRenderControls();
        if (s.index !== this.index) {
            this.indexSelect.value = String(s.index); this.loadIndex(s.index).catch(e => this.error(e));
        } else this.loadPlanes().catch(e => this.error(e));
    }

    undo() { if (this.history.length) { this.flushPlanes(); this.future.push(this.snapshot()); this.restore(this.history.pop()); } }

    redo() { if (this.future.length) { this.flushPlanes(); this.history.push(this.snapshot()); this.restore(this.future.pop()); } }
    };
}
