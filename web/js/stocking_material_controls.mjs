import {STYLE_LABELS} from './stocking_style_registry.mjs?v=20261011-material6';
import {SCHEMA,normalizeEffects,cleanLayer,cleanV2,fields} from './stocking_config.mjs?v=20261011-material6';
export function createMaterialControls({el,globalValue,setValue}) {
    return class {
        globalMaterial() {
            const params=Object.fromEntries(Object.entries(SCHEMA.appearance).map(([k,s])=>[k,globalValue(this.node,k,s.default)]));
            const n=normalizeEffects(params.style,globalValue(this.node,'effects_json','{}'));
            return {params:{...params,style:n.style},effects:n.effects};
        }
        effectiveMaterial() {
            const global=this.globalMaterial(),r=this.region();
            if(this.materialScope!=='region'||!r)return global;
            const patch=r.material??{params:{}};
            return {params:{...global.params,...patch.params},effects:{...global.effects,
                layers:patch.layers??global.effects.layers,damage:{...global.effects.damage,...patch.damage}}};
        }
        effects() {return this.effectiveMaterial().effects;}
        materialReadOnly() {return this.materialScope!=='region'&&(this.payload.material_connected||this.node.inputs?.some(i=>i.name==='effects_json'&&i.link!=null));}
        setMaterialEffects(effects) {
            effects=cleanV2(effects);
            if(this.materialReadOnly())return;
            if(this.materialScope==='region') {
                const r=this.region();if(!r)return;
                r.material ||= {params:{}};r.material.layers=effects.layers;
                this.updateDraft();
            } else {
                const base=this.globalMaterial().params.style;
                if(this.unified || this.renderMode){this.settings.style=base;this.settings.effects_json=JSON.stringify(effects);}
                else {setValue(this.node,'style',base);setValue(this.node,'effects_json',JSON.stringify(effects));}
                this.updateSaveState();this.scheduleDraftSave();this.schedule();
            }
        }
        editEffects(fn,rebuild=true) {
            if(this.materialReadOnly())return;
            const cfg=structuredClone(this.effects());if(this.draft)this.remember();fn(cfg);this.setMaterialEffects(cfg);
            if(rebuild)this.refreshEffectControls();
        }
        changeEffect(group,key,raw) {
            if(group!=='damage')return;
            const spec=SCHEMA.groups.damage[key];let v=raw;
            if(spec.type==='number'){if(String(raw).trim()===''||!Number.isFinite(Number(raw)))return;v=Number(raw);}
            if(this.materialScope==='region') {
                const r=this.region();if(!r)return;this.remember();r.material ||= {params:{}};
                r.material.damage=fields({...r.material.damage,[key]:v},SCHEMA.groups.damage,true);
                this.updateDraft();return;
            }
            this.editEffects(c=>{c.damage=fields({...c.damage,[key]:v},SCHEMA.groups.damage);},false);
        }
        buildEffectControls() {
            this.materialPanel=el('section',null,this.sidebar);
            const scope=el('select',null,el('label','材质编辑范围',this.materialPanel));scope.setAttribute('aria-label','材质编辑范围');
            el('option','全局材质',scope,{value:'global'});
            if(this.draft)el('option','当前部位',scope,{value:'region'});
            scope.value=this.materialScope||'global';scope.onchange=()=>{this.materialScope=scope.value;this.refreshRenderControls();};
            this.layerPanel=el('section',null,this.materialPanel);this.refreshEffectControls();
        }
        schemaControl(parent,key,spec,current,onchange,disabled=false) {
            const label=el('label',spec.label||key,parent);let input;
            if(spec.type==='enum') {
                input=el('select',null,label);for(const v of spec.options)el('option',STYLE_LABELS[v]??({fabric:'织物',print:'印花',random:'随机',manual:'手工',both:'随机＋手工',snag:'钩丝',ladder:'梯状抽丝',mixed:'钩丝＋抽丝'}[v]??v),input,{value:v});input.value=current;
            } else input=el('input',null,label,{type:spec.type==='boolean'?'checkbox':spec.type==='number'?'number':spec.type==='color'?'color':'text',
                value:String(current??''),checked:current===true,min:spec.min,max:spec.max,maxLength:spec.maxLength??4096,step:1});
            input.setAttribute('aria-label',spec.label||key);input.title=spec.hint||spec.label||key;input.disabled=disabled;
            const apply=()=>{let v=input.type==='checkbox'?input.checked:input.value;if(spec.type==='number'){if(v===''||!Number.isFinite(Number(v)))return;v=Number(v);}try{onchange(v);}catch(e){this.error(e);}};
            input.onchange=apply;if(['number','text','color'].includes(input.type))input.oninput=apply;return input;
        }
        refreshEffectControls() {
            if(!this.layerPanel)return;
            const cfg=this.effects(),locked=this.materialReadOnly(),regional=this.materialScope==='region';
            const active=this.layerPanel.contains(document.activeElement),priorFocus=document.activeElement;
            if(active&&!this.rebuildLayers) return;
            this.layerPanel.replaceChildren();this.rebuildLayers=false;
            if(regional) {
                const r=this.region();if(!r){el('small','请先选择部位',this.layerPanel);return;}
                el('strong',r.name+' · 部位材质',this.layerPanel);
                this.button(this.layerPanel,'全部继承全局',()=>{this.remember();delete r.material;this.updateDraft();this.rebuildLayers=true;this.refreshRenderControls();});
                const label=el('label','独立图层（替换全局）',this.layerPanel),toggle=el('input',null,label,{type:'checkbox',checked:r.material?.layers!==undefined});
                toggle.onchange=()=>{this.remember();r.material ||= {params:{}};if(toggle.checked)r.material.layers=structuredClone(cfg.layers);else delete r.material.layers;this.updateDraft();this.rebuildLayers=true;this.refreshEffectControls();};
                this.button(this.layerPanel,'复制全局图层',()=>{this.remember();r.material ||= {params:{}};r.material.layers=structuredClone(this.globalMaterial().effects.layers);this.updateDraft();this.rebuildLayers=true;this.refreshEffectControls();});
                for(const [key,spec] of Object.entries(SCHEMA.appearance)) {
                    const row=el('div',null,this.layerPanel),cb=el('input',null,el('label','覆盖 '+spec.label,row),{type:'checkbox',checked:key in (r.material?.params??{})});
                    cb.onchange=()=>{this.remember();r.material ||= {params:{}};if(cb.checked)r.material.params[key]=this.effectiveMaterial().params[key];else delete r.material.params[key];this.updateDraft();this.rebuildLayers=true;this.refreshRenderControls();};
                    this.schemaControl(row,key,spec,this.effectiveMaterial().params[key],v=>{
                        this.remember();r.material ||= {params:{}};r.material.params=fields({...r.material.params,[key]:v},SCHEMA.appearance,true);this.updateDraft();this.refreshRenderControls();
                    },!cb.checked);
                }
            }
            el('h3','效果图层',this.layerPanel);
            if(locked)el('small','全局材质由上游输入控制；部位覆盖仍可编辑。',this.layerPanel);
            const actions=el('div',null,this.layerPanel,{className:'tb-stocking-candidates'});
            for(const [type,label] of Object.entries(SCHEMA.types).filter(([,v])=>v.layer).map(([k,v])=>[k,'添加'+v.label+'层'])) {
                const b=this.button(actions,label,()=>{this.rebuildLayers=true;this.editEffects(c=>c.layers.push(cleanLayer({id:crypto.randomUUID(),type,params:{}})));});b.disabled=locked||cfg.layers.length>=SCHEMA.max_layers;
            }
            for(const [index,layer] of cfg.layers.entries()) {
                const box=el('fieldset',null,this.layerPanel);el('legend',`${index+1}. ${SCHEMA.types[layer.type].label}`,box);
                for(const [op,label] of [['copy','复制层'],['delete','删除层'],['up','上移'],['down','下移']]) {
                    const b=this.button(box,label,()=>{this.rebuildLayers=true;this.editEffects(c=>{
                        if(op==='delete')c.layers.splice(index,1);
                        if(op==='copy'){const v=structuredClone(c.layers[index]);v.id=crypto.randomUUID();c.layers.splice(index+1,0,v);}
                        const j=op==='up'?index-1:index+1;if(['up','down'].includes(op)&&j>=0&&j<c.layers.length)[c.layers[index],c.layers[j]]=[c.layers[j],c.layers[index]];
                    });});b.disabled=locked||op==='copy'&&cfg.layers.length>=SCHEMA.max_layers||op==='up'&&index===0||op==='down'&&index===cfg.layers.length-1;
                }
                for(const [key,spec] of Object.entries(SCHEMA.groups[layer.type]))this.schemaControl(box,key,spec,layer.params[key],v=>{
                    this.editEffects(c=>{c.layers[index].params=fields({...c.layers[index].params,[key]:v},SCHEMA.groups[layer.type]);},false);
                },locked);
            }
            const damage=el('section',null,this.layerPanel);el('h3','最终损伤',damage);
            for(const [key,spec] of Object.entries(SCHEMA.groups.damage))this.schemaControl(damage,key,spec,cfg.damage[key],v=>this.changeEffect('damage',key,v),locked);
            if(regional&&this.region()?.material?.damage)this.button(damage,'继承全局损伤',()=>{this.remember();delete this.region().material.damage;this.updateDraft();this.rebuildLayers=true;this.refreshEffectControls();});
            if(this.draft) {
                this.button(damage,'手工定位损伤',()=>{this.tool='damage';this.markTools();});
                this.button(damage,'删除最后损伤',()=>this.removeLast('damage_strokes'));
                this.button(damage,'撤销',()=>this.undo());this.button(damage,'重做',()=>this.redo());
            }
        }
    };
}
