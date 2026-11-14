import {PROMPTS_EVENT, openPromptTagManager} from './prompt_actions.mjs?v=20261114-prompt-library-management';

export function normalizeTag(value) { return String(value).trim().toLowerCase(); }
export function parseTags(value) { return [...new Set(String(value || "").split(",").map(normalizeTag).filter(Boolean))]; }
export function newTagName(value) {
    const name=normalizeTag(value);
    if(!name) throw new Error("请输入标签名称");
    if(name.includes(",") || /[\r\n\x00]/.test(name)) throw new Error("一次新增一个标签，名称不能包含逗号或换行");
    return name;
}

export async function loadTagCatalog(request, signal) {
    const counts=new Map();let page=1,more=true;
    while(more) {
        const response=await request(`/tags?page_size=500&page=${page}`,{signal});
        const data=await response.json().catch(()=>({}));
        if(!response.ok) throw new Error(data.error || `标签加载失败：HTTP ${response.status}`);
        if(!Array.isArray(data.items) || typeof data.has_more!=="boolean") throw new Error("标签目录格式异常");
        for(const value of data.items) {
            const name=normalizeTag(value);if(name) counts.set(name,Number(data.counts?.[value] || 0));
        }
        more=data.has_more;page++;
    }
    return [...counts].map(([name,count])=>({name,count})).sort((a,b)=>a.name.localeCompare(b.name));
}

function el(tag,text,className="") {
    const node=document.createElement(tag);node.className=className;if(text!==undefined)node.textContent=text;return node;
}
function button(text,callback,className="") {
    const node=el("button",text,className);node.type="button";node.onclick=callback;return node;
}
export function ensureTagStyles() {
    if(document.querySelector('link[data-toolbox-prompts]'))return;
    const css=el("link");css.rel="stylesheet";css.href=new URL("../css/prompt_reader.css?v=20261114-prompt-library-management",import.meta.url).href;
    css.dataset.toolboxPrompts="true";document.head.append(css);
}

export function openTagPicker({request,value="",allowCreate=false,managePrompts=false,title="选择标签",focusNew=false,onApply,onClose=()=>{}}) {
    ensureTagStyles();const selected=new Set(parseTags(value));
    let catalog=[],loaded=false,closed=false,controller,manager;
    const lifetime=new AbortController();
    const dialog=el("dialog",undefined,"tb-prompts tbt-dialog");dialog.setAttribute("aria-label",title);
    const close=()=>{if(closed)return;closed=true;controller?.abort();lifetime.abort();manager?.close();dialog.close();dialog.remove();onClose();};
    const header=el("header",undefined,"tbp-header");header.append(el("strong",title),button("关闭",close));
    const body=el("div",undefined,"tbt-body");
    const selectedLabel=el("strong"),chosen=el("div",undefined,"tbp-selected-tags tbt-chosen");chosen.setAttribute("aria-label","已选标签");
    const clear=button("清空已选",()=>{selected.clear();render();});
    const selectedHeader=el("div",undefined,"tbt-heading");selectedHeader.append(selectedLabel,clear);
    const searchLabel=el("label",undefined,"tbp-field");searchLabel.append(el("span","搜索已有标签"));
    const search=el("input");search.type="search";search.setAttribute("aria-label","搜索已有标签");search.placeholder="按名称搜索，点击标签多选";searchLabel.append(search);
    const state=el("p",undefined,"tbp-status");state.setAttribute("role","status");
    const reload=button("刷新标签",()=>load());
    const manage=button("管理提示词标签",()=>{if(!manager)manager=openPromptTagManager({request,onClose:()=>{manager=null;}});});
    const list=el("div",undefined,"tbp-tag-cloud tbt-options");list.setAttribute("aria-label","已有标签");
    const createArea=el("div",undefined,"tbt-create");
    const addName=el("input");addName.setAttribute("aria-label","新标签名称");addName.placeholder="输入一个新标签名称";
    const addStatus=el("p",undefined,"tbp-status");addStatus.setAttribute("role","status");
    const add=button("＋新增标签",()=>{
        try {
            if(!loaded)return;
            const name=newTagName(addName.value),next=new Set([...selected,name]);
            if([...next].join(",").length>10000)throw new Error("已选标签总长度不能超过 10000 字符");
            selected.add(name);addName.value="";render();
            addStatus.textContent=catalog.some(item=>item.name===name) ? "已选中已有标签" : "已加入待保存标签，保存内容或执行 writer 写入后才入库。";
        }catch(error){addStatus.textContent=error.message;}
    });
    if(allowCreate){createArea.append(el("span","不存在的标签可通过＋新增；此处不会立即写入数据库。","tbp-status"),addName,add,addStatus);}
    const footer=el("footer",undefined,"tbp-actions tbt-footer");
    footer.append(button("取消",close),button("应用",()=>{const result=[...selected].join(", ");close();onApply(result);},"tbp-primary"));
    body.append(selectedHeader,chosen,searchLabel,reload);
    if(managePrompts)body.append(manage);
    body.append(state,list,createArea);dialog.append(header,body,footer);
    function render() {
        selectedLabel.textContent=`已选 ${selected.size} 个标签`;clear.disabled=!selected.size;chosen.replaceChildren();
        const known=new Set(catalog.map(item=>item.name));
        for(const name of selected){
            const suffix=loaded&&!known.has(name) ? allowCreate ? " · 待保存" : " · 库中不存在" : "";
            const chip=button(`${name}${suffix} ×`,()=>{selected.delete(name);render();},"tbp-selected-tag");
            chip.setAttribute("aria-label",`移除标签 ${name}`);chosen.append(chip);
        }
        list.replaceChildren();const query=normalizeTag(search.value);
        const visible=catalog.filter(item=>item.name.includes(query));
        for(const item of visible){
            const control=button("",()=>{
                if(selected.has(item.name))selected.delete(item.name);
                else if([...selected,item.name].join(",").length>10000){state.textContent="已选标签总长度不能超过 10000 字符";return;}
                else selected.add(item.name);render();
            },"tbp-tag-option");
            control.dataset.tag=item.name;control.setAttribute("aria-pressed",String(selected.has(item.name)));
            control.append(el("span",item.name),el("span",String(item.count),"tbp-tag-count"));list.append(control);
        }
        if(loaded)state.textContent=catalog.length ? visible.length ? `${catalog.length} 个已有标签 · 多选时全部匹配` : "没有匹配的已有标签" : "暂无已有标签";
        add.disabled=addName.disabled=!loaded;
        add.textContent=catalog.some(item=>item.name===normalizeTag(addName.value))?"选择已有标签":"＋新增标签";
    }
    async function load() {
        controller?.abort();const current=controller=new AbortController();loaded=false;render();state.textContent="正在加载标签…";
        try{const data=await loadTagCatalog(request,current.signal);if(closed||controller!==current)return;catalog=data;loaded=true;render();if(focusNew&&allowCreate){addName.focus();focusNew=false;}}
        catch(error){if(!closed&&controller===current&&error.name!=="AbortError"){render();state.textContent=`${error.message}，请重试刷新。已选标签已保留。`;}}
    }
    search.oninput=render;addName.oninput=()=>{add.textContent=catalog.some(item=>item.name===normalizeTag(addName.value))?"选择已有标签":"＋新增标签";};
    addName.onkeydown=event=>{if(event.key==="Enter"){event.preventDefault();add.click();}};
    dialog.addEventListener("cancel",event=>{event.preventDefault();close();},{signal:lifetime.signal});
    dialog.addEventListener("click",event=>{if(event.target===dialog)close();},{signal:lifetime.signal});
    if(managePrompts)window.addEventListener(PROMPTS_EVENT,event=>{
        for(const name of event.detail?.deleted_tags||[])selected.delete(normalizeTag(name));
        load();
    },{signal:lifetime.signal});
    document.body.append(dialog);render();dialog.showModal();load();if(focusNew&&allowCreate)addName.focus();else search.focus();
    return {dialog,close};
}

export function createTagField({parent,value="",request,allowCreate=true,managePrompts=false,label="标签",hint,onChange=()=>{}}) {
    ensureTagStyles();let picker=null,destroyed=false;
    const container=el("div",undefined,"tbp-field tbt-field");container.append(el("span",label));
    const input=el("input");input.type="hidden";input.name="tags";input.value=value;
    const chips=el("div",undefined,"tbp-tags tbt-summary");chips.setAttribute("aria-label","当前标签");
    const controls=el("div",undefined,"tbt-field-actions");
    const launch=focusNew=>{
        if(picker||destroyed||choose.disabled)return;
        picker=openTagPicker({request,value:input.value,allowCreate,managePrompts,title:allowCreate?"选择或新增标签":"选择筛选标签",focusNew,
            onApply:next=>{if(next===input.value)return;input.value=next;render();onChange(next);input.dispatchEvent(new Event("input",{bubbles:true}));},
            onClose:()=>{picker=null;if(choose.isConnected&&!choose.disabled)choose.focus();}});
    };
    const choose=button("选择标签",()=>launch(false));controls.append(choose);
    if(allowCreate){const plus=button("＋",()=>launch(true));plus.setAttribute("aria-label","新增标签");controls.append(plus);}
    const help=el("small",hint || (allowCreate?"新标签随内容保存时入库":"多个标签全部匹配；不选表示不限"));
    container.append(input,chips,controls,help);parent.append(container);
    function render(){chips.replaceChildren();const tags=parseTags(input.value);if(!tags.length)chips.append(el("span","未选择标签"));
        for(const name of tags)chips.append(el("span",`# ${name}`,"tbp-prompt-tag"));}
    render();
    return {input,container,
        setValue:next=>{if(next===input.value)return;picker?.close();input.value=next;render();},
        setDisabled:disabled=>{for(const control of controls.children)control.disabled=disabled;if(disabled)picker?.close();},
        setHint:text=>{help.textContent=text;},
        destroy:()=>{destroyed=true;picker?.close();},
    };
}

export function attachNodeTags(node,app,api,{allowCreate=false}={}) {
    const widget=node.widgets?.find(item=>item.name==="tags");if(!widget||node.__toolboxTagPicker)return;
    node.__toolboxTagPicker=true;let previousValue,previousLinked;
    const controls=el("div",undefined,"tb-tag-node");
    const hiddenSize=()=>[0,-4];
    const hint=allowCreate?"新标签在节点执行写入时入库":"多个标签全部匹配；不选表示不限";
    const field=createTagField({parent:controls,value:widget.value,allowCreate,managePrompts:true,hint,request:(path,options)=>api.fetchApi(`/toolbox/prompts${path}`,options),
        onChange:value=>{app.graph?.beforeChange?.();widget.value=value;widget.callback?.(value);app.graph?.afterChange?.();app.graph?.change?.();node.setDirtyCanvas?.(true,true);refresh();}});
    function refresh(){
        const slot=node.inputs?.find(input=>input.name==="tags"),linked=slot?.link!=null;
        widget.hidden=true;if(!String(widget.type).includes("converted"))widget.type="toolboxHidden";
        widget.computeSize=hiddenSize;if(widget.inputEl)widget.inputEl.style.display="none";
        if(previousValue!==widget.value){previousValue=widget.value;field.setValue(String(widget.value||""));}
        if(previousLinked!==linked){previousLinked=linked;field.setDisabled(linked);field.setHint(linked?"由连接输入提供":hint);}
    }
    const display=node.addDOMWidget("tag_selector","toolbox_tag_selector",controls,{serialize:false,hideOnZoom:false,getMinHeight:()=>106,getMaxHeight:()=>106});
    // Current LiteGraph checks the widget property; older builds use serializeValue.
    if(display){display.serialize=false;display.serializeValue=()=>undefined;}
    const callback=widget.callback;widget.callback=function(){const result=callback?.apply(this,arguments);refresh();return result;};
    for(const name of ["onConfigure","onConnectionsChange","onDrawForeground"]){
        const original=node[name];node[name]=function(){const result=original?.apply(this,arguments);refresh();return result;};
    }
    const removed=node.onRemoved;node.onRemoved=function(){field.destroy();return removed?.apply(this,arguments);};
    refresh();node.setSize?.([Math.max(node.size?.[0]||0,350),Math.max(node.size?.[1]||0,node.computeSize?.()[1]||120)]);
}
