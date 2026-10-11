export function createPreviewClient(runtime) {
    const {app,api,fitView,imagePoint,zoomAt,isCurrent,GuideDraft,samHint,SAMRequests,STYLE_LABELS,STYLE_HINTS,PARAM_KEYS,SLIDERS,parameterPatch,applyCandidate,selectionCoverage,maskBoundarySegments,splitRatio,compareKey,canvasMetrics,translate,SETTING_KEYS,recordsForSave,capturePrompt,PATTERN_STYLES,readEffects,effectPatch,damageStroke,upgradeEffectsValue,RENDER_DEFAULTS,MATERIAL_DEFAULTS,nearestPath,nearestPoint,claimPixels,linkedSparklePatch,SCHEMA,normalizeEffects,API_ROOT,COLORS,widget,value,globalValue,setValue,el,imageFrom,decodePNG,post,plane,rasterPaint}=runtime;
    return class {
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
            body.overlay_settings = this.overlayOptions;
        }
        if (this.unified) {
            this.flushPlanes(); body.guides_json = JSON.stringify(this.doc); body.settings = this.settings;
            body.view = this.renderMode ? "texture" : "guides";
            if (!this.renderMode) body.overlay_settings = this.overlayOptions;
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
        this.guideOverlays = info.overlays || {};
        if (this.renderMode) this.refreshRenderControls(info);
        this.status.textContent = this.renderMode
            ? `版本 ${revision} · 周期 ${info.period.toFixed(2)}px · ${body.params.strength_auto ? "自动" : "手动"}强度 ${Number(info.effective_strength).toFixed(1)}% · 过密衰减 ${(100 * info.faded_fraction).toFixed(1)}% · ${(1000 * info.render_seconds).toFixed(0)}ms${info.clamped ? " · 已限制过高密度" : ""}${info.notes?.length ? `\n${info.notes.join("；")}` : ""}`
            : `底图 ${this.payload.identity.slice(0, 10)} · 版本 ${revision} · 求解 ${(1000 * info.solve_seconds).toFixed(0)}ms · 部位缓存 ${info.cache_hits} 命中 / ${info.cache_misses} 重算 · 未引导 ${info.unguided_pixels} 像素`;
        if (this.mirrorInfo) this.status.textContent += `\n镜像完成 · 轮廓拟合误差 ${this.mirrorInfo.fit_error.toFixed(2)}px`;
        if (this.unified) this.status.textContent += `\n选区 ${(100 * info.coverage_fraction).toFixed(2)}% · 实际变化 ${(100 * info.changed_fraction).toFixed(2)}% · ${info.direction_source === "manual" ? "手绘走向" : "基础走向（虚线）+ 手绘优先"}${info.failure_reason ? " · 未生效：" + info.failure_reason : " · 纹理已生效"}`;
    }

    };
}
