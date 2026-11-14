import {ensureTagStyles} from './tag_picker.mjs';
import {PROMPTS_EVENT} from './prompt_actions.mjs';

const STATUS={available:'有效',missing:'文件不存在',unavailable:'暂不可访问',changed:'文件已变化'};
function el(tag,text,className=''){const node=document.createElement(tag);node.className=className;if(text!==undefined)node.textContent=text;return node;}
function button(text,callback,className=''){const node=el('button',text,className);node.type='button';node.onclick=callback;return node;}
async function json(request,path,options={}){
    const response=await request(path,options),data=await response.json().catch(()=>({}));
    if(!response.ok){const error=new Error(data.error||`请求失败：HTTP ${response.status}`);error.status=response.status;throw error;}return data;
}
const body=value=>({headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
export const EXAMPLES_EVENT='toolbox-prompt-examples-changed';
function changed(ids){window.dispatchEvent(new CustomEvent(EXAMPLES_EVENT,{detail:{prompt_ids:ids}}));}

let confirmationId=0;
export function openExampleConfirmation({text,details='',title='确认移除示例关联',confirmLabel='确认移除关联',allowDeleteFile=false,onConfirm,onClose=()=>{}}){
    const dialog=el('dialog',undefined,'tb-prompts tbp-example-confirm');
    const id=`tbp-example-confirm-${++confirmationId}`;
    const heading=el('h3',title);heading.id=`${id}-title`;
    const description=el('p',text);description.id=`${id}-description`;
    dialog.setAttribute('aria-labelledby',heading.id);dialog.setAttribute('aria-describedby',description.id);
    dialog.append(heading,description);
    if(details)dialog.append(el('p',details,'tbp-example-confirm-path'));
    const note=el('p','仅移除数据库中的示例关联，素材文件会保留。','tbp-example-confirm-note');
    const deleteFile=el('input');deleteFile.type='checkbox';deleteFile.checked=false;
    const confirm=button(confirmLabel,()=>{if(closed)return;const removeFile=allowDeleteFile&&deleteFile.checked;close();onConfirm(removeFile);},'tbp-danger');
    if(allowDeleteFile){
        const choice=el('label',undefined,'tbp-example-delete-file');choice.append(deleteFile,el('span','同步移除示例素材'));dialog.append(choice);
        deleteFile.onchange=()=>{
            note.textContent=deleteFile.checked?'将同时删除原始素材文件，无法撤销；其他关联也将无法访问该文件。':'仅移除数据库中的示例关联，素材文件会保留。';
            confirm.textContent=deleteFile.checked?'确认移除关联并删除素材':confirmLabel;
        };
    }
    dialog.append(note);
    let closed=false;
    const opener=document.activeElement;
    const close=()=>{if(closed)return;closed=true;dialog.close();dialog.remove();if(opener?.isConnected)opener.focus({preventScroll:true});onClose();};
    const actions=el('div',undefined,'tbp-actions');
    const cancel=button('取消操作',close);cancel.autofocus=true;
    actions.append(cancel,confirm);
    dialog.append(actions);
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    dialog.addEventListener('close',close);
    document.body.append(dialog);dialog.showModal();cancel.focus();
    return {close,dialog};
}

export async function processExampleBatches(ids,{send,shouldStop=()=>false,onProgress=()=>{}}){
    let done=0,removed=0;
    for(let offset=0;offset<ids.length&&!shouldStop();offset+=200){const data=await send(ids.slice(offset,offset+200));done+=Math.min(200,ids.length-offset);removed+=data.deleted?.length||0;onProgress(done,removed);}
    return {done,removed};
}

export function createExamplesPanel({parent,record=null,initialShasum=null,request=(path,options)=>fetch(path,options),canAdd=()=>true,onChanged=()=>{}}){
    let page=1,pages=1,closed=false,busy=false,stopping=false,loadController,confirmation;
    const lifetime=new AbortController(),selected=new Set();
    const root=el('section',undefined,'tbp-examples');root.setAttribute('aria-label',record?'生成示例素材':'示例素材管理');
    root.append(el('h3',record?`提示词 #${record.id} 的示例素材`:'已登记示例素材管理'),el('p','只记录 output 路径。正常浏览不检查路径状态，不生成缩略图；检查与清理由人工发起。','tbp-status'));
    const controls=el('div',undefined,'tbp-example-toolbar');
    const version=el('select');version.setAttribute('aria-label','示例版本');
    if(record){
        for(const [value,text] of [[record.shasum,'当前已保存正文版本'],['all','全部历史版本']]){const option=el('option',text);option.value=value;version.append(option);}
        if(initialShasum&&initialShasum!==record.shasum){const option=el('option','本次执行的历史版本');option.value=initialShasum;version.append(option);}
        version.value=initialShasum||record.shasum;controls.append(version);
    }
    const statusFilter=el('select');statusFilter.setAttribute('aria-label','示例路径状态');
    for(const [value,text] of Object.entries({all:'全部检查状态',...STATUS})){const option=el('option',text);option.value=value;statusFilter.append(option);}controls.append(statusFilter);
    const summary=el('strong'),message=el('p',undefined,'tbp-status');message.setAttribute('role','status');
    const newPath=el('input');newPath.setAttribute('aria-label','示例文件路径');newPath.placeholder='相对于 output 的路径，例如 images/model/example.png；也支持服务器绝对路径';
    const addRow=el('div',undefined,'tbp-example-add');addRow.hidden=true;
    const addSubmit=button('添加路径',async()=>{
        if(!canAdd()||version.value!==record.shasum){message.textContent='请先保存提示词修改，并切换到当前已保存版本后添加。';return;}
        await action(async()=>{await json(request,'/toolbox/prompt-examples/register',{method:'POST',...body({prompt_id:record.id,shasum:record.shasum,paths:[newPath.value],source:'manual',version:record.version}),signal:lifetime.signal});newPath.value='';message.textContent='示例路径已登记，相同路径不会重复增加数量。';await refreshChanged([record.id]);});
    });addRow.append(newPath,addSubmit);
    const add=button('＋添加示例路径',()=>{
        if(!canAdd()||version.value!==record.shasum){message.textContent='请先保存提示词修改，并切换到当前已保存版本后添加。';return;}
        addRow.hidden=!addRow.hidden;if(!addRow.hidden)newPath.focus();
    });
    if(record)controls.append(add);
    const refresh=button('刷新示例列表',()=>load());controls.append(refresh);
    const checkSelected=button('检查选中路径',()=>run([...selected],'check'));
    const checkAll=button(record?'检查本条提示词全部路径':'检查当前范围全部路径',()=>collectAndRun('check'));
    const clean=button('清理失效关联',()=>collectAndRun('cleanup'));
    const stop=button('停止后续批次',()=>{stopping=true;message.textContent='已停止后续批次，当前请求完成后结束。';});stop.hidden=true;
    const maintenance=el('div',undefined,'tbp-example-toolbar');maintenance.append(checkSelected,checkAll,clean,stop);
    const cards=el('div',undefined,'tbp-example-items'),nav=el('nav',undefined,'tbp-pagination');nav.setAttribute('aria-label','示例分页');
    const previous=button('上一页示例',()=>{if(page>1){page--;load();}}),next=button('下一页示例',()=>{if(page<pages){page++;load();}}),pageLabel=el('span');nav.append(previous,pageLabel,next);
    root.append(controls,addRow,summary,maintenance,message,cards,nav);parent.append(root);
    function query(overrides={}){return {page:String(page),page_size:'20',...(record?{prompt_id:String(record.id),shasum:version.value}:{}),status:statusFilter.value,...overrides};}
    const endpoint=params=>`/toolbox/prompt-examples?${new URLSearchParams(params)}`;
    async function refreshChanged(ids){changed(ids);onChanged();await load();}
    function setBusy(value){busy=value;for(const control of [...controls.querySelectorAll('button,select'),...cards.querySelectorAll('button,input'),checkSelected,checkAll,clean,newPath,addSubmit,previous,next])control.disabled=value;stop.hidden=!value;}
    async function action(callback){if(busy||closed)return;setBusy(true);try{await callback();}catch(error){if(!closed&&error.name!=='AbortError')message.textContent=error.message;}finally{if(!closed){setBusy(false);previous.disabled=page<=1;next.disabled=page>=pages;}}}
    async function load(){
        if(closed)return;loadController?.abort();const controller=loadController=new AbortController();
        try{
            const data=await json(request,endpoint(query()),{signal:controller.signal});if(closed||loadController!==controller)return;
            pages=Math.max(1,Math.ceil(data.total/data.page_size));if(page>pages){page=pages;return load();}
            summary.textContent=`${data.total} 个示例素材`;pageLabel.textContent=`${page} / ${pages}`;previous.disabled=busy||page<=1;next.disabled=busy||page>=pages;
            cards.replaceChildren();if(!data.items.length)cards.append(el('p','暂无已登记示例，可在当前已保存版本手动添加 output 路径。','tbp-status'));
            for(const item of data.items){
                const card=el('article',undefined,'tbp-example-item');
                const heading=el('div',undefined,'tbp-example-toolbar');
                const choice=el('input');choice.type='checkbox';choice.checked=selected.has(item.id);choice.setAttribute('aria-label',`选中示例 #${item.id}`);
                choice.onchange=()=>{choice.checked?selected.add(item.id):selected.delete(item.id);};
                heading.append(choice,el('strong',`#${item.id} · ${item.media_type==='image'?'图像':'视频'}`),el('span',STATUS[item.status]||item.status,'tbp-meta-chip'));
                card.append(heading,el('p',item.relative_path,'tbp-example-path'),el('p',`提示词 #${item.prompt_id} · ${item.prompt_shasum}\n登记：${item.created_at}\n最后检查：${item.checked_at||'未检查'}${item.message?'\n'+item.message:''}`,'tbp-meta'));
                if(record&&item.url){
                    const media=el(item.media_type==='image'?'img':'video');media.className='tbp-example-media';
                    if(item.media_type==='image'){media.loading='lazy';media.alt=`示例 #${item.id}`;}else{media.controls=true;media.preload='metadata';}
                    const failure=el('p',undefined,'tbp-status');media.addEventListener('error',()=>{failure.textContent='原始素材加载失败或格式不受浏览器支持；可下载文件，或手动检查路径。';});
                    media.src=item.url;card.append(media,failure);
                }
                const links=el('div',undefined,'tbp-example-toolbar');
                if(item.url){
                    const open=el('a','打开原文件');open.href=item.url;open.target='_blank';open.rel='noopener';
                    const download=el('a','下载原文件');download.href=item.url;download.download=item.relative_path.split('/').pop();links.append(open,download);
                }
                links.append(button('检查此路径',()=>run([item.id],'check')),button('移除关联',()=>confirmAction(`移除示例 #${item.id} 的关联？`,deleteFile=>action(async()=>{
                    await json(request,`/toolbox/prompt-examples/${item.id}`,{method:'DELETE',...body({delete_file:deleteFile}),signal:lifetime.signal});selected.delete(item.id);await refreshChanged([item.prompt_id]);
                }),{details:item.relative_path,allowDeleteFile:true})));card.append(links);cards.append(card);
            }
        }catch(error){if(!closed&&error.name!=='AbortError'&&loadController===controller)message.textContent=error.message;}
    }
    function confirmAction(text,callback,options={}){
        if(closed||busy)return;
        confirmation?.close();
        confirmation=openExampleConfirmation({text,...options,onConfirm:deleteFile=>{if(!closed)callback(deleteFile);},onClose:()=>{confirmation=null;}});
    }
    async function collectAndRun(mode){
        if(busy)return;stopping=false;
        let pendingCleanup=null;
        await action(async()=>{
            const ids=new Set(),scope=query({page_size:'100',page:'1',...(mode==='cleanup'?{status:'missing'}:{status:'all'}),...(record?{shasum:'all'}:{})});
            let offset=1;
            while(!stopping&&!closed){const data=await json(request,endpoint({...scope,page:String(offset)}),{signal:lifetime.signal});data.items.forEach(item=>ids.add(item.id));message.textContent=`正在收集已登记记录：${ids.size} / ${data.total}`;if(offset*data.page_size>=data.total)break;offset++;}
            if(stopping||closed)return;
            if(!ids.size){message.textContent=mode==='cleanup'?'没有已标记为“文件不存在”的关联，请先手动检查。':'没有需要检查的已登记记录。';return;}
            if(mode==='cleanup'){
                // action() is still busy while collecting; show the confirmation
                // after releasing its guard so confirming can start the cleanup.
                pendingCleanup={text:`将复查并清理 ${ids.size} 条失效关联；已恢复或暂不可访问的文件将保留关联。`,ids:[...ids]};
            }
            else await batches([...ids],mode);
        });
        if(pendingCleanup&&!closed){const pending=pendingCleanup;pendingCleanup=null;confirmAction(pending.text,()=>run(pending.ids,mode),{title:'确认清理失效关联',confirmLabel:'确认复查并清理'});}
    }
    async function batches(ids,mode){
        stopping=false;await processExampleBatches(ids,{shouldStop:()=>stopping||closed,send:batch=>json(request,mode==='cleanup'?'/toolbox/prompt-examples/invalid':'/toolbox/prompt-examples/check',{
            method:mode==='cleanup'?'DELETE':'POST',...body({ids:batch}),signal:lifetime.signal}),
            onProgress:(done,removed)=>{message.textContent=`${mode==='cleanup'?'复查清理':'检查'}进度：${done} / ${ids.length}${mode==='cleanup'?`，已移除 ${removed} 条关联`:''}`;}});
        if(stopping)message.textContent+= ' · 已停止后续批次';onChanged();changed(record?[record.id]:[]);await load();
    }
    async function run(ids,mode){if(!ids.length){message.textContent='请先选择记录。';return;}await action(()=>batches(ids,mode));}
    version.onchange=statusFilter.onchange=()=>{page=1;load();};
    window.addEventListener(EXAMPLES_EVENT,event=>{if(!root.hidden&&!busy&&(!record||!event.detail?.prompt_ids?.length||event.detail.prompt_ids.includes(record.id)))load();},{signal:lifetime.signal});
    window.addEventListener(PROMPTS_EVENT,event=>{
        const deleted=event.detail?.deleted_prompt_ids||[];
        if(!deleted.length||busy)return;
        if(!record){selected.clear();load();}
        else if(deleted.includes(record.id)){
            loadController?.abort();selected.clear();
            for(const media of cards.querySelectorAll('video'))media.pause();
            cards.replaceChildren();summary.textContent='0 个示例素材';
            message.textContent=`提示词 #${record.id} 已删除，全部示例关联已清理，原始素材文件保留。`;
            for(const control of root.querySelectorAll('button,input,select'))control.disabled=true;
        }
    },{signal:lifetime.signal});
    return {container:root,load,destroy:()=>{closed=true;stopping=true;confirmation?.close();loadController?.abort();lifetime.abort();for(const media of root.querySelectorAll('video')){media.pause();media.removeAttribute('src');media.load();}}};
}

export function openExampleManager({request,onChanged=()=>{},onClose=()=>{}}={}){
    ensureTagStyles();const dialog=el('dialog',undefined,'tb-prompts tbp-examples-manager');dialog.setAttribute('aria-label','示例素材管理');
    let panel,closed=false;const close=()=>{if(closed)return;closed=true;panel.destroy();dialog.close();dialog.remove();onClose();};
    const header=el('header',undefined,'tbp-header');header.append(el('strong','示例素材管理'),button('关闭管理',close));dialog.append(header);
    const parent=el('div',undefined,'tbp-detail-body');dialog.append(parent);panel=createExamplesPanel({parent,request,onChanged});
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});document.body.append(dialog);dialog.showModal();panel.load();return {close};
}

export function attachExampleCounter(node,app,api,{reader=false,openBrowser}){
    const idWidget=node.widgets?.find(widget=>widget.name==='id');let browser=null,source=null,lastKey,closed=false,controller;
    const lifetime=new AbortController(),controls=el('div',undefined,'tbp-example-node');
    const label=el('span','运行后显示选中提示词的示例数量'),view=button('查看示例',()=>{
        if(browser||!source)return;
        browser=openBrowser({currentId:source.id,initialExamples:true,exampleShasum:source.shasum,
            allowUse:reader&&!node.inputs?.some(input=>input.name==='id'&&input.link!=null),
            request:(path,options)=>api.fetchApi(`/toolbox/prompts${path}`,options),exampleRequest:(path,options)=>api.fetchApi(path,options),
            onSelect:id=>{if(idWidget){idWidget.value=id;idWidget.callback?.(id);app.graph.change();node.setDirtyCanvas(true,true);}},onClose:()=>{browser=null;}});
    });view.disabled=true;
    const retry=button('刷新数量',()=>load());controls.append(label,view,retry);
    async function load(){
        if(!source||closed)return;controller?.abort();const current=controller=new AbortController(),snapshot={...source};label.textContent='正在读取示例数量…';
        try{const query=new URLSearchParams({page_size:'1',...(snapshot.shasum?{shasum:snapshot.shasum}:{})});
            const data=await json((path,options)=>api.fetchApi(path,options),`/toolbox/prompts/${snapshot.id}/examples?${query}`,{signal:current.signal});
            if(closed||controller!==current)return;label.textContent=`示例素材 ${data.total} 个 · 提示词 #${snapshot.id}`;view.disabled=false;
        }catch(error){if(!closed&&error.name!=='AbortError'&&controller===current){label.textContent=`示例读取失败：${error.message}`;view.disabled=true;}}
    }
    function refresh(){
        if(!reader)return;const linked=node.inputs?.some(input=>input.name==='id'&&input.link!=null);
        const key=linked?'linked':`id:${idWidget?.value}`;if(key===lastKey)return;lastKey=key;
        controller?.abort();source=linked?null:{id:Number(idWidget?.value)};view.disabled=true;
        if(source&&source.id>0)load();else label.textContent='运行后显示实际输入提示词的示例数量';
    }
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.apply(this,arguments);const record=message?.toolbox_prompt?.[0];if(record?.id&&record.shasum){source={id:Number(record.id),shasum:record.shasum};load();}};
    for(const name of ['onConfigure','onConnectionsChange','onDrawForeground']){const original=node[name];node[name]=function(){const result=original?.apply(this,arguments);refresh();return result;};}
    const display=node.addDOMWidget('prompt_examples','toolbox_prompt_examples',controls,{serialize:false,hideOnZoom:false,getMinHeight:()=>64,getMaxHeight:()=>64});
    if(display){display.serialize=false;display.serializeValue=()=>undefined;}
    const removed=node.onRemoved;node.onRemoved=function(){closed=true;lifetime.abort();controller?.abort();browser?.close();return removed?.apply(this,arguments);};
    window.addEventListener(EXAMPLES_EVENT,event=>{if(source&&(!event.detail?.prompt_ids?.length||event.detail.prompt_ids.includes(source.id)))load();},{signal:lifetime.signal});
    window.addEventListener(PROMPTS_EVENT,event=>{
        if(source&&event.detail?.deleted_prompt_ids?.includes(source.id)){
            controller?.abort();label.textContent=`提示词 #${source.id} 已删除 · 示例关联已清理`;view.disabled=true;
        }
    },{signal:lifetime.signal});
    refresh();node.setSize([Math.max(node.size?.[0]||0,350),Math.max(node.size?.[1]||0,node.computeSize?.()[1]||180)]);
}

export function attachMediaStatus(node,api){
    let report=null,closed=false;const lifetime=new AbortController(),controls=el('div',undefined,'tbp-example-node'),label=el('span','保存后显示关联结果');
    const retry=button('重新登记',async()=>{if(!report?.paths?.length)return;retry.disabled=true;try{
        for(let offset=0;offset<report.paths.length&&!closed;offset+=200)await json((path,options)=>api.fetchApi(path,options),'/toolbox/prompt-examples/register',{method:'POST',...body({prompt_id:report.prompt_id,shasum:report.shasum,paths:report.paths.slice(offset,offset+200),source:'generated',...(report.job_id?{job_id:report.job_id}:{}),...(report.node_id?{node_id:report.node_id}:{})}),signal:lifetime.signal});
        if(closed)return;
        report.registration='registered';controls.dataset.registration='registered';label.textContent='文件已重新登记，无需重新生成';changed([report.prompt_id]);
    }catch(error){if(!closed)label.textContent=`关联失败：${error.message}`;}finally{if(!closed)retry.disabled=report.registration==='registered';}});retry.disabled=true;controls.append(label,retry);
    const display=node.addDOMWidget('example_save_status','toolbox_example_save_status',controls,{serialize:false,hideOnZoom:false,getMinHeight:()=>64,getMaxHeight:()=>64});if(display){display.serialize=false;display.serializeValue=()=>undefined;}
    const executed=node.onExecuted;node.onExecuted=function(message){executed?.apply(this,arguments);const data=message?.toolbox_prompt_media?.[0];if(data){report=data;label.textContent=data.message;controls.dataset.registration=data.registration;retry.disabled=data.registration!=='failed';}};
    const removed=node.onRemoved;node.onRemoved=function(){closed=true;lifetime.abort();return removed?.apply(this,arguments);};
    node.setSize([Math.max(node.size?.[0]||0,350),Math.max(node.size?.[1]||0,node.computeSize?.()[1]||180)]);
}
