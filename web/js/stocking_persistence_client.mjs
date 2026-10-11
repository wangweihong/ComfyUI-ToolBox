export function createPersistenceClient(runtime) {
    const {app,api,fitView,imagePoint,zoomAt,isCurrent,GuideDraft,samHint,SAMRequests,STYLE_LABELS,STYLE_HINTS,PARAM_KEYS,SLIDERS,parameterPatch,applyCandidate,selectionCoverage,maskBoundarySegments,splitRatio,compareKey,canvasMetrics,translate,SETTING_KEYS,recordsForSave,capturePrompt,PATTERN_STYLES,readEffects,effectPatch,damageStroke,upgradeEffectsValue,RENDER_DEFAULTS,MATERIAL_DEFAULTS,nearestPath,nearestPoint,claimPixels,linkedSparklePatch,SCHEMA,normalizeEffects,API_ROOT,COLORS,widget,value,globalValue,setValue,el,imageFrom,decodePNG,post,plane,rasterPaint}=runtime;
    return class {
    async loadPresets() {
        const result=await post("feature/presets",{action:"list"});if(this.closed)return;
        this.presets=result.presets;this.presetSelect.replaceChildren();
        for(const p of this.presets)el("option",p.name+(p.params?"":"（不可读取）"),this.presetSelect,{value:p.name,disabled:!p.params});
    }


    applyMaterial(params) {
        if(!params)throw new Error("请选择可读取的预设");
        if(this.draft)this.remember();
        else {this.materialHistory ||= [];this.materialHistory.push(Object.fromEntries(Object.entries(MATERIAL_DEFAULTS).map(([k,v])=>[k,value(this.node,k,v)])));}
        if(this.materialScope==='region' && this.region()) {
            const r=this.region(),n=normalizeEffects(params.style||this.globalMaterial().params.style,params.effects_json||'{}');
            r.material={params:Object.fromEntries(Object.entries(params).filter(([k])=>k in SCHEMA.appearance)),layers:n.effects.layers,damage:n.effects.damage};
            r.material.params.style=n.style;this.rebuildLayers=true;this.updateDraft();this.refreshRenderControls();return;
        }
        const skipped=[];
        for(const [k,v] of Object.entries({...MATERIAL_DEFAULTS,...params})) {
            if(this.payload.material_connected && (k in SCHEMA.appearance || k==="effects_json")){skipped.push(k);continue;}
            if(this.node.inputs?.some(i=>i.link!=null && (i.name===k || k==="sparkle_link" && ["sparkle_depth","sparkle_bright"].includes(i.name)))){skipped.push(k);continue;}
            if(this.unified || this.renderMode)this.settings[k]=v;else setValue(this.node,k,v);
        }
        this.refreshRenderControls();this.updateSaveState();this.schedule();this.scheduleDraftSave();
        if(skipped.length)this.status.textContent="已跳过连接输入："+skipped.join(", ");
    }


    scheduleDraftSave() {
        if(this.closed || !this.draft || this.recoveryPending)return;
        clearTimeout(this.draftTimer);
        this.draftTimer=setTimeout(()=>{
            this.flushPlanes();const state=JSON.parse(this.snapshot());
            this.pendingDraft=(this.pendingDraft||Promise.resolve()).catch(()=>{}).then(()=>{
                if(this.closed)return;
                return post("feature/draft",{action:"save",editor_id:this.editorId,identity:this.payload.identity,session:this.payload.session,state});
            });
            this.pendingDraft.catch(e=>this.error(new Error("草稿恢复保存失败；仍可保存节点："+e.message)));
        },1000);
    }


    async offerRecovery() {
        if(!this.draft || this.closed)return;
        this.recoveryPending=true;
        try {
            const result=await post("feature/draft",{action:"load",editor_id:this.editorId,identity:this.payload.identity,session:this.payload.session});
            if(this.closed || !result.draft)return;
            const row=el("div",null,this.head,{className:"tb-stocking-candidates"});
            el("span","发现未保存草稿",row);
            this.button(row,"恢复草稿",async()=>{
                this.payload=result.draft.payload;this.restore(JSON.stringify(result.draft.state));row.remove();this.recoveryPending=false;
                this.scheduleDraftSave();
            });
            this.button(row,"丢弃草稿",async()=>{
                await post("feature/draft",{action:"delete",editor_id:this.editorId,identity:this.payload.identity});row.remove();this.recoveryPending=false;
            });
        } catch(e){this.error(e);} finally {if(!this.head.textContent.includes("发现未保存草稿"))this.recoveryPending=false;}
    }

    };
}
