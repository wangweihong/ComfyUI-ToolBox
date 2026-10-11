export function createDrawing(runtime) {
    const {app,api,fitView,imagePoint,zoomAt,isCurrent,GuideDraft,samHint,SAMRequests,STYLE_LABELS,STYLE_HINTS,PARAM_KEYS,SLIDERS,parameterPatch,applyCandidate,selectionCoverage,maskBoundarySegments,splitRatio,compareKey,canvasMetrics,translate,SETTING_KEYS,recordsForSave,capturePrompt,PATTERN_STYLES,readEffects,effectPatch,damageStroke,upgradeEffectsValue,RENDER_DEFAULTS,MATERIAL_DEFAULTS,nearestPath,nearestPoint,claimPixels,linkedSparklePatch,SCHEMA,normalizeEffects,API_ROOT,COLORS,widget,value,globalValue,setValue,el,imageFrom,decodePNG,post,plane,rasterPaint}=runtime;
    return class {
    point(e) { return imagePoint(e.clientX, e.clientY, this.canvas.getBoundingClientRect(), this.view, this.payload.width, this.payload.height); }

    down(e) {
        if (!this.base || this.loading || this.planeLoading || this.loadedIndex !== this.index) return;
        this.canvas.setPointerCapture(e.pointerId);
        if (this.tool === "pan" || this.space || e.button === 1 || (this.renderMode && this.tool !== "damage")) {
            this.fitMode = false;
            this.drag = { pan: true, x: e.clientX, y: e.clientY, view: { ...this.view } }; return;
        }
        if (!this.region()) { this.status.textContent = "请先新增部位"; return; }
        if (this.tool === "sam") { this.samClick(this.point(e), e.button === 2).catch(err => this.error(err)); return; }
        if (e.button === 2 && ["stroke","wall","damage"].includes(this.tool)) { this.removeAt(this.point(e)); return; }
        if (this.tool !== "cut") this.remember(); this.drag = { points: [this.point(e)], tool: e.button === 2 && this.tool === "paint" ? "erase" : this.tool, regionId: this.region().id, index: this.index };
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
        if (d.tool === "cut") {
            if (d.points.length>1) this.regionOperation("split",d.points).catch(e=>this.error(e));
            return;
        } else if (d.tool === "damage") {
            const cfg = this.effects().damage;
            const type = this.manualDamageType || (cfg.type === "mixed" ? ((r.damage_strokes?.length || 0) % 2 ? "ladder" : "snag") : cfg.type);
            const scale = Math.sqrt(this.payload.width*this.payload.height/(1280*1920));
            (r.damage_strokes ||= []).push(damageStroke(d.points,type,Math.max(1,4*scale*cfg.width/100)));
            if (this.unified) {
                this.changeEffect("damage","enabled",true);
                this.changeEffect("damage","mode",cfg.mode === "random" ? "both" : cfg.mode);
            }
        } else if (["paint", "erase"].includes(d.tool) && p) {
            rasterPaint(p.mask, d.points, this.radius, d.tool === "paint" ? "white" : "black");
            rasterPaint(p.erase, d.points, this.radius, d.tool === "erase" ? "white" : "black");
            p.dirty = true; this.overlays.delete(r.id);
            if (d.tool === "paint") this.claimStroke(d.points);
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
        const v = this.coverageVisual(selectionCoverage(pixels.paint, pixels.erased, pixels.external), r.color || COLORS[index % COLORS.length]);
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
                for (const s of r.damage_strokes || []) this.drawLines(ctx,[s.points],s.type === "ladder" ? "#ef9af2" : "#b9e6ff",Math.max(1/this.view.scale,s.width));
            });
            if (sam) this.drawCoverage(ctx, sam.change, 0.5, true);
        }
        if (this.unified && !this.renderMode && this.basicLines?.length) {
            ctx.setLineDash([6 / this.view.scale, 4 / this.view.scale]); this.drawLines(ctx, this.basicLines, "#8edcff", 1 / this.view.scale); ctx.setLineDash([]);
        }
        if (!this.renderMode) {
            for (const [key,color] of [["courses","#66dbff"],["wales","#e7a3ff"],["auto_walls","#ff795e"]]) {
                if(key==="auto_walls") ctx.setLineDash([5/this.view.scale,4/this.view.scale]);
                this.drawLines(ctx,this.guideOverlays[key]||[],color,1/this.view.scale); ctx.setLineDash([]);
            }
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

    };
}
