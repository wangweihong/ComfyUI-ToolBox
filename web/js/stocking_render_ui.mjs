export function createRenderUi(runtime) {
    const {app,api,fitView,imagePoint,zoomAt,isCurrent,GuideDraft,samHint,SAMRequests,STYLE_LABELS,STYLE_HINTS,PARAM_KEYS,SLIDERS,parameterPatch,applyCandidate,selectionCoverage,maskBoundarySegments,splitRatio,compareKey,canvasMetrics,translate,SETTING_KEYS,recordsForSave,capturePrompt,PATTERN_STYLES,readEffects,effectPatch,damageStroke,upgradeEffectsValue,RENDER_DEFAULTS,MATERIAL_DEFAULTS,nearestPath,nearestPoint,claimPixels,linkedSparklePatch,SCHEMA,normalizeEffects,API_ROOT,COLORS,widget,value,globalValue,setValue,el,imageFrom,decodePNG,post,plane,rasterPaint}=runtime;
    return class {
    buildRenderControls() {
        el("h3", "基础织物", this.sidebar);
        const label = el("label", "样式", this.sidebar);
        this.styleSelect = el("select", null, label, { value: value(this.node, "style", "knit") });
        for (const [val, text] of Object.entries(STYLE_LABELS).filter(([val])=>!PATTERN_STYLES.has(val))) el("option", text, this.styleSelect, { value: val });
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
        this.buildUpstreamControls();
        this.buildEffectControls();
        this.refreshRenderControls();
        el("small", this.unified ? "滑杆自动更新草稿预览；保存并关闭后运行工作流得到正式输出。取消不保存参数。整体定位细节，拖动分界线对比原图。" : "滑杆自动更新参数草稿；保存并关闭后写入本渲染节点。取消放弃修改。修改引导后需重新运行求解节点。", this.sidebar);
    }


    changeParameter(key, raw) {
        let patch = parameterPatch(key, raw); if (!patch) return;
        if(this.materialScope==="region" && key in SCHEMA.appearance){
            const r=this.region();if(!r)return;this.remember();r.material ||= {params:{}};r.material.params={...r.material.params,...patch};this.updateDraft();this.refreshRenderControls();return;
        }
        if(this.payload.material_connected && key in SCHEMA.appearance)return;
        if(key==="style") {const cfg=this.effects();this.setMaterialEffects(cfg);}
        patch = linkedSparklePatch(patch, value(this.node,"sparkle_link",false),value(this.node,"sparkle_depth",100));
        for (const [name, val] of Object.entries(patch)) {
            if (this.unified || this.renderMode) {
                if (this.node.inputs?.some(i => i.name === name && i.link != null)) continue;
                this.settings[name] = val;
            } else setValue(this.node, name, val);
        }
        this.refreshRenderControls(); this.schedule();
        this.updateSaveState(); this.scheduleDraftSave();
    }


    refreshRenderControls(info) {
        if(!this.styleSelect){this.refreshEffectControls();return;}
        const style = value(this.node, "style", "knit"), auto = value(this.node, "strength_auto", true);
        this.styleSelect.value = PATTERN_STYLES.has(style)?"knit":style;
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
        for(const {input,key} of this.upstreamControls||[]) {
            if(input.type==="checkbox")input.checked=value(this.node,key,RENDER_DEFAULTS[key]);
            else input.value=value(this.node,key,RENDER_DEFAULTS[key]);
            input.disabled=this.node.inputs?.some(i=>i.link!=null && (i.name===key || key==="sparkle_link" && ["sparkle_depth","sparkle_bright"].includes(i.name)));
        }
        for(const control of this.overlay.querySelectorAll("[data-setting]")) {
            if(control.dataset.setting in SCHEMA.appearance)control.disabled=this.materialScope!=="region" && this.payload.material_connected || this.node.inputs?.some(i=>i.name===control.dataset.setting&&i.link!=null);
        }
        this.refreshEffectControls();
    }


    buildUpstreamControls() {
        this.upstreamControls=[];
        for(const [key,label,choices] of [
            ["renderer_version","渲染版本",[["legacy","兼容旧版"],["upstream_f74c8ac","上游新版 f74c8ac"]]],
            ["layer_mode","透明图层",[["replacement","精确替换图层"],["soft","柔和丝袜图层"]]]]) {
            const input=el("select",null,el("label",label,this.sidebar));
            for(const [v,t] of choices)el("option",t,input,{value:v});
            input.dataset.setting=key;input.value=value(this.node,key,RENDER_DEFAULTS[key]);
            input.onchange=()=>this.changeParameter(key,input.value);this.upstreamControls.push({input,key});
        }
        for(const [key,label] of [["moire_on","摩尔纹（需要新版与深度）"],["sparkle_link","关联深度 / 亮部亮点"]]) {
            const input=el("input",null,el("label",label,this.sidebar),{type:"checkbox",checked:value(this.node,key,false)});
            input.dataset.setting=key;
            input.onchange=()=>this.changeParameter(key,input.checked);this.upstreamControls.push({input,key});
        }
        el("small","Coil 与摩尔纹需选择上游新版。新版油光增加柔光带、暗边与跨遮挡连续高光，仍为试验样式。",this.sidebar);
        const group=el("div",null,this.sidebar);
        el("strong","材质预设",group);
        this.presetSelect=el("select",null,group,{title:"材质预设"});
        this.button(group,"加载预设",()=>this.applyMaterial(this.presets?.find(p=>p.name===this.presetSelect.value)?.params));
        this.button(group,"保存 / 覆盖预设",async()=>{
            const name=prompt("预设名称（最多 40 字）",this.presetSelect.value||"");if(!name)return;
            const existing=this.presets?.some(p=>p.name===name.trim());
            if(existing&&!confirm("覆盖同名材质预设？"))return;
            const params=Object.fromEntries(Object.entries(MATERIAL_DEFAULTS).map(([k,v])=>[k,value(this.node,k,v)]));
            await post("feature/presets",{action:"save",name,params});await this.loadPresets();
        });
        this.button(group,"删除预设",async()=>{
            if(!this.presetSelect.value)return;
            await post("feature/presets",{action:"delete",name:this.presetSelect.value});await this.loadPresets();
        });
        this.button(group,"恢复材质默认",()=>this.applyMaterial(MATERIAL_DEFAULTS));
        this.loadPresets().catch(e=>this.error(e));
    }

    };
}
