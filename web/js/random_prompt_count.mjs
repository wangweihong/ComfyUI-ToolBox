import {PROMPTS_EVENT} from './prompt_actions.mjs?v=20261114-skill-library-management';
import {ensureTagStyles} from './tag_picker.mjs?v=20261114-skill-library-management';

const FILTER_DEFAULTS={
    language:'全部',media_type:'全部',prompt_type:'全部',safety:'全部',content_format:'全部',dynamic:'全部',
    match_size:false,width:1024,height:768,tags:'',sensitivity_level:'全部',
    nsfw:'否',extreme:'否',horror:'否',gore:'否',minor:'否',sensitivity_mode:'max',sensitivity_levels:'',
};

function selection(node) {
    const filters={...FILTER_DEFAULTS};
    for(const widget of node.widgets||[])if(Object.hasOwn(filters,widget.name))filters[widget.name]=widget.value;
    const active=new Set(Object.keys(filters));
    if(!filters.match_size){active.delete('width');active.delete('height');}
    active.delete(filters.sensitivity_mode==='exact'?'sensitivity_level':'sensitivity_levels');
    const linked=(node.inputs||[]).filter(input=>input.link!=null&&active.has(input.name)).map(input=>input.name);
    const query=new URLSearchParams({page_size:'1'});
    for(const name of active)query.set(name,String(filters[name]));
    return {query,linked,key:JSON.stringify([query.toString(),linked])};
}

export function attachRandomPromptCount(node,api) {
    if(node.__toolboxRandomPromptCount)return;
    node.__toolboxRandomPromptCount=true;
    ensureTagStyles();
    const controls=document.createElement('div');controls.className='tbp-example-node tbp-random-count';controls.style.flexWrap='nowrap';
    const label=document.createElement('span');label.setAttribute('role','status');label.style.flex='1';
    const retry=document.createElement('button');retry.type='button';retry.textContent='刷新数量';
    retry.style.flexShrink='0';
    controls.append(label,retry);
    const lifetime=new AbortController();
    let lastKey,controller,timer,closed=false;

    async function load(snapshot) {
        if(closed)return;
        const current=controller=new AbortController();
        try {
            // Reuse the library's shared filter SQL and total; only fetch one preview row.
            const response=await api.fetchApi(`/toolbox/prompts?${snapshot.query}`,{signal:current.signal});
            const data=await response.json();
            if(!response.ok)throw new Error(data.error||`请求失败 ${response.status}`);
            if(!Number.isSafeInteger(data.total)||data.total<0)throw new Error('返回的匹配数量无效');
            if(closed||controller!==current||selection(node).key!==snapshot.key)return;
            label.textContent=`当前条件匹配 ${data.total.toLocaleString('zh-CN')} 条`;
            node.setDirtyCanvas?.(true,true);
        } catch(error) {
            if(!closed&&error.name!=='AbortError'&&controller===current&&selection(node).key===snapshot.key)
                label.textContent=`数量读取失败：${error.message}`;
        }
    }
    function refresh(force=false) {
        if(closed)return;
        const snapshot=selection(node);
        if(!force&&snapshot.key===lastKey)return;
        lastKey=snapshot.key;clearTimeout(timer);controller?.abort();controller=null;
        retry.disabled=snapshot.linked.length>0;
        if(snapshot.linked.length){label.textContent='筛选条件由连线提供，无法预先统计';return;}
        label.textContent='正在统计匹配数量…';
        timer=setTimeout(()=>void load(snapshot),250);
    }
    retry.onclick=()=>refresh(true);
    for(const widget of node.widgets||[]) {
        if(!Object.hasOwn(FILTER_DEFAULTS,widget.name))continue;
        const callback=widget.callback;
        widget.callback=function(){const result=callback?.apply(this,arguments);refresh();return result;};
    }
    for(const name of ['onConfigure','onWidgetChanged','onConnectionsChange','onDrawForeground']) {
        const original=node[name];
        node[name]=function(){const result=original?.apply(this,arguments);refresh();return result;};
    }
    window.addEventListener(PROMPTS_EVENT,()=>refresh(true),{signal:lifetime.signal});
    const display=node.addDOMWidget('matching_prompt_count','toolbox_matching_prompt_count',controls,{
        serialize:false,hideOnZoom:false,getMinHeight:()=>48,getMaxHeight:()=>48,
    });
    if(display){display.serialize=false;display.serializeValue=()=>undefined;}
    const removed=node.onRemoved;
    node.onRemoved=function(){closed=true;clearTimeout(timer);controller?.abort();lifetime.abort();return removed?.apply(this,arguments);};
    refresh();
    node.setSize?.([Math.max(node.size?.[0]||0,350),Math.max(node.size?.[1]||0,node.computeSize?.()[1]||180)]);
    return {controls};
}
