import './style.css';

type Item = {id:string; path:string; name:string; kind:string; extension:string; size:number; mtime:number; missing:number; properties:Record<string,unknown>; errors:string[]};
type GenerationNode={node_id:string;node_type:string;title:string;fields:{name:string;label:string;value:string}[];highlight:boolean};
type Detail = Item & {generation_nodes:GenerationNode[];has_workflow:boolean;generation_truncated:boolean;raw:Record<string,unknown>; summary:Record<string,unknown>; text:string; truncated:boolean; metadata_state:string};
type Folder = {name:string;path:string;root_id?:string};
type Root = {id:string; path:string; name:string; builtin:number};
type Action = {source:string; target:string|null};
type Plan = {token:string; op:string; entries:{id:string; error?:string; actions:Action[]}[]};
const $ = <T extends HTMLElement = HTMLElement>(id:string) => document.getElementById(id) as T;
function el<K extends keyof HTMLElementTagNameMap>(tag:K, className='', text=''):HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); node.className = className; node.textContent = text; return node;
}
const params = new URLSearchParams(location.search);
const previewOnly = params.get('mode') === 'preview';
const base = location.pathname.replace(/\/gallery\/?$/, '');
const url = (path:string) => base + path;
const api = async <T = any>(path:string, data?:unknown, method=data === undefined ? 'GET' : 'POST'):Promise<T> => {
  const response = await fetch(url(path), {method, headers:data === undefined ? {} : {'Content-Type':'application/json'}, body:data === undefined ? undefined : JSON.stringify(data)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `请求失败 ${response.status}`);
  if(Array.isArray(value.folders))value.folders=value.folders.filter((folder:Folder)=>!folder.name.startsWith('.'));
  return value as T;
};
const names:Record<string,string> = {image:'图片',video:'视频',audio:'音频',text:'文本',ply:'PLY',other:'其他'};
const glyphs:Record<string,string> = {image:'▧',video:'▷',audio:'♫',text:'TXT',ply:'PLY',other:'FILE'};
const state = {roots:[] as Root[], root:'', folder:'', q:'', kind:'', sort:'time', direction:'desc', recent:false, recursive:false, selectionMode:false, focusId:'',offset:0, folders:[] as Folder[], items:[] as Item[], total:0, selected:new Set<string>(), current:null as Detail|null};
let renderedScope='',statusEpoch=0,locationEpoch=0,lastLocation='';
let listEpoch=0, detailEpoch=0, toastTimer=0, statusTimer=0, previewTimer=0;
let plan:Plan|null=null, operationIds:string[]=[], operation='',moveDestination='';
let operationEpoch=0,moveEpoch=0;
let stopPreview=()=>{};
function toast(text:string) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=window.setTimeout(()=>$('toast').hidden=true,5000); }
async function copy(text:string) {
  try { await navigator.clipboard.writeText(text); }
  catch { const area=el('textarea'); area.value=text; area.style.position='fixed'; area.style.opacity='0'; document.body.append(area); area.select(); const ok=document.execCommand('copy'); area.remove(); if(!ok) throw new Error('浏览器拒绝复制，请手动选择路径复制'); }
  toast('已复制');
}
function action(label:string, handler:()=>void|Promise<void>, className='') {
  const b=el('button',className,label); b.type='button'; b.onclick=()=>Promise.resolve(handler()).catch(e=>toast(e.message)); return b;
}
function folderIcon(){
  const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.setAttribute('focusable','false');icon.classList.add('folder-icon');
  const shape=document.createElementNS('http://www.w3.org/2000/svg','path');
  shape.setAttribute('d','M3 8V6a2 2 0 0 1 2-2h4.5l2 2H19a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z');
  shape.setAttribute('fill','currentColor');shape.setAttribute('fill-opacity','.14');shape.setAttribute('stroke','currentColor');shape.setAttribute('stroke-width','1.6');shape.setAttribute('stroke-linejoin','round');
  icon.append(shape);return icon;
}
function folderButton(name:string,handler:()=>void|Promise<void>){
  const button=action('',handler,'root-name');button.append(folderIcon(),el('span','root-label',name));return button;
}
function size(value:number) { const units=['B','KB','MB','GB','TB']; let i=0; while(value>=1024&&i<units.length-1){value/=1024;i++;} return `${value.toFixed(i?1:0)} ${units[i]}`; }
function duration(value:unknown) { const seconds=Number(value); return `${Math.floor(seconds/60)}:${Math.floor(seconds%60).toString().padStart(2,'0')}`; }
function when(value:number) { return new Date(value*1000).toLocaleString('zh-CN',{hour12:false}); }

async function loadRoots() {
  const data=await api<{roots:Root[];tools:{ffmpeg:boolean;ffprobe:boolean}}>('/roots'); state.roots=data.roots;
  $('tools').textContent=`FFmpeg ${data.tools.ffmpeg?'已就绪':'未安装'} · ffprobe ${data.tools.ffprobe?'已就绪':'未安装'}`;
  renderRoots(); renderRootSettings();
}
function renderRoots() {
  $('roots').replaceChildren();
  for(const root of state.roots) {
    const holder=el('div');
    const row=el('div',`root-row ${state.root===root.id&&!state.folder?'active':''}`);row.dataset.path=root.path;
    const children=el('div','root-children'); children.hidden=true;
    const toggle=action('›',async()=>{children.hidden=!children.hidden;toggle.textContent=children.hidden?'›':'⌄';if(!children.hidden) await fillFolders(children,root.path,root.id);});
    const name=folderButton(root.name,()=>chooseFolder(root.id,'')); name.title=root.path;
    row.append(toggle,name);holder.append(row,children);$('roots').append(holder);
  }
}
async function fillFolders(container:HTMLElement,path:string,rootId:string) {
  const data=await api<{folders:{name:string;path:string}[]}>('/folders?path='+encodeURIComponent(path));
  container.replaceChildren();
  for(const folder of data.folders) {
    const holder=el('div'),row=el('div','root-row'),nested=el('div','root-children');row.dataset.path=folder.path;nested.hidden=true;
    const toggle=action('›',async()=>{nested.hidden=!nested.hidden;toggle.textContent=nested.hidden?'›':'⌄';if(!nested.hidden)await fillFolders(nested,folder.path,rootId);});
    const name=folderButton(folder.name,()=>chooseFolder(rootId,folder.path));name.title=folder.path;
    row.append(toggle,name);holder.append(row,nested);container.append(holder);
  }
  if(!data.folders.length)container.append(el('div','muted','没有子目录'));
}
function currentPath(){return state.folder||state.roots.find(r=>r.id===state.root)?.path||'';}
function resetRecursive(){state.recursive=false;$<HTMLInputElement>('recursive').checked=false;}
function clearSearch(){state.q='';$<HTMLInputElement>('search').value='';}
async function chooseFolder(root:string,folder:string) {
  state.root=root;state.folder=folder===state.roots.find(r=>r.id===root)?.path?'':folder;state.recent=false;state.focusId='';state.offset=0;resetRecursive();clearSearch();clearSelection();
  await loadFiles();
  await api('/scan',{path:currentPath(),recursive:false});void pollStatus();
}
function rootForItem(item:Detail){return state.roots.find(root=>root.id===(item as Detail&{root_id?:string}).root_id)||[...state.roots].sort((a,b)=>b.path.length-a.path.length).find(root=>item.path.startsWith(root.path+'/')||item.path.startsWith(root.path+'\\'));}
async function revealFolder(root:Root,folder:string){
  let row=Array.from($('roots').querySelectorAll<HTMLElement>('.root-row')).find(node=>node.dataset.path===root.path),path=root.path;
  const segments=folder.slice(root.path.length).split(/[\\/]/).filter(Boolean);
  for(const segment of segments){
    if(!row)break;
    const children=row.nextElementSibling as HTMLElement;children.hidden=false;row.querySelector('button')!.textContent='⌄';
    await fillFolders(children,path,root.id);
    path=path.replace(/[\\/]$/,'')+(root.path.includes('\\')?'\\':'/')+segment;
    row=Array.from(children.querySelectorAll<HTMLElement>('.root-row')).find(node=>node.dataset.path===path);
  }
  updateHeading();
}
async function locateItem(item:Detail){
  const root=rootForItem(item);if(!root)throw new Error('当前素材不在已配置的目录中');
  const folder=parentPath(item.path);
  state.root=root.id;state.folder=folder===root.path?'':folder;state.recent=false;state.kind='';state.offset=0;state.focusId=item.id;
  resetRecursive();clearSearch();clearSelection();
  for(const button of $('types').children)button.classList.toggle('active',(button as HTMLElement).dataset.kind==='');
  await loadFiles();await revealFolder(root,folder);
  $('grid').querySelector<HTMLElement>(`.card[data-id="${item.id}"]`)?.scrollIntoView({block:'center'});
  await api('/scan',{path:folder,recursive:false});void pollStatus();
}
async function locateCurrent(id:string,path:string){
  const key=id+'\n'+path;if(lastLocation===key)return;
  lastLocation=key;const epoch=++locationEpoch;
  try{
    const item=await api<Detail>('/detail?'+new URLSearchParams({id,path}));
    if(epoch===locationEpoch)await locateItem(item);
  }catch(error){lastLocation='';toast((error as Error).message);}
}
async function uploadFiles(files:File[],destination?:string){
  if(!files.length)return;
  const button=$<HTMLButtonElement>('upload'),inputRoot=state.roots.find(root=>root.id==='builtin-input');
  if(button.disabled){toast('正在上传，请稍候再粘贴');return;}
  if(!inputRoot){toast('找不到 ComfyUI input 目录');return;}
  const folder=currentPath(),inInput=folder===inputRoot.path||folder.startsWith(inputRoot.path+'/')||folder.startsWith(inputRoot.path+'\\');
  const subfolder=destination??(inInput?folder.slice(inputRoot.path.length).replace(/^[\\/]+/,'').replaceAll('\\','/'):'tb_media_library');
  const failures:string[]=[],uploaded:Detail[]=[];let saved=0;button.disabled=true;
  try{
    for(const[index,file]of files.entries()){
      button.textContent=`上传 ${index+1}/${files.length}…`;
      try{
        const form=new FormData();form.append('image',file,file.name);form.append('type','input');form.append('subfolder',subfolder);
        const response=await fetch(base.replace(/\/toolbox\/media-library$/,'')+'/upload/image',{method:'POST',body:form});
        const text=await response.text();
        if(!response.ok)throw new Error(response.status===413?'超过当前 ComfyUI 的上传大小限制':`上传失败（${response.status}）`);
        const data=JSON.parse(text) as {name:string;subfolder:string;type:string};
        if(!data.name)throw new Error('官方上传接口未返回文件名');saved++;
        const root=state.roots.find(value=>value.id==='builtin-'+data.type)||inputRoot;
        const separator=root.path.includes('\\')?'\\':'/';
        const path=[root.path.replace(/[\\/]$/,''),...(data.subfolder||'').split(/[\\/]/).filter(Boolean),data.name].join(separator);
        try{uploaded.push(await api<Detail>('/detail?'+new URLSearchParams({path})));}
        catch(error){failures.push(`${file.name}：已上传，但无法读取信息：${(error as Error).message}`);}
      }catch(error){failures.push(`${file.name}：${(error as Error).message}`);}
    }
    if(uploaded.length)await locateItem(uploaded[uploaded.length-1]);
    toast(`已上传 ${saved}/${files.length} 个文件${failures.length?'\n'+failures.join('\n'):''}`);
  }catch(error){toast((error as Error).message);}
  finally{button.disabled=false;button.textContent='↑ 上传素材';$<HTMLInputElement>('upload-files').value='';}
}
async function home(){state.root='';state.folder='';state.recent=false;state.focusId='';state.offset=0;resetRecursive();clearSearch();clearSelection();await loadFiles();}
function updateHeading() {
  const homeView=!state.recent&&!state.root;
  $('all').classList.toggle('active',homeView);$('recent').classList.toggle('active',state.recent);
  const root=state.roots.find(r=>r.id===state.root);
  $('view-title').replaceChildren(document.createTextNode(state.recent?'最近使用':state.folder?state.folder.split(/[\\/]/).pop()||'素材':root?.name||'素材目录'),$('count'));
  $('count').textContent=homeView?`${state.roots.length} 个位置`:`${state.total} 个文件`;
  $('breadcrumb').textContent=state.recent?'最近使用的 20 个文件':currentPath()||'选择一个目录开始浏览';
  $('scope-hint').textContent=homeView?'选择目录后才加载文件':state.recent?'只显示最近使用的文件':state.recursive?'递归平铺 · 包含全部子目录':'当前层 · 保留子目录结构';
  $('prune').hidden=!state.recent;
  $('multi-select').hidden=homeView;
  $('parent').hidden=!state.root||state.recent;
  $<HTMLInputElement>('recursive').disabled=!state.root||state.recent;
  $<HTMLInputElement>('search').disabled=homeView;
  $<HTMLButtonElement>('scan').disabled=homeView||state.recent;
  const inputRoot=state.roots.find(r=>r.id==='builtin-input'),folder=currentPath();
  const uploadPath=inputRoot&&(folder===inputRoot.path||folder.startsWith(inputRoot.path+'/')||folder.startsWith(inputRoot.path+'\\'))?folder:'input/tb_media_library';
  $('upload').title=`上传到 ${uploadPath}；粘贴图片则保存到 input/pasted`;
  for(const row of document.querySelectorAll<HTMLElement>('.root-row'))row.classList.toggle('active',row.dataset.path===currentPath());
}
async function loadFiles(append=false) {
  const epoch=++listEpoch;
  if(!state.root&&!state.recent){state.items=[];state.folders=[];state.total=0;renderedScope='home';renderGrid();updateHeading();updateSelection();$('from-start').hidden=true;$('more').hidden=true;$('paging').textContent='';return;}
  const query=new URLSearchParams({focus_id:append?'':state.focusId,q:state.q,kind:state.kind,root_id:state.root,folder:state.folder,recursive:state.recursive?'1':'0',sort:state.sort,direction:state.direction,recent:state.recent?'1':'0',offset:String(append?state.offset+state.items.length:state.offset),limit:'80'});
  const showFolders=!state.recent&&!state.recursive;
  try {
    const [data,directories]=await Promise.all([
      api<{items:Item[];total:number;offset:number}>('/files?'+query),
      showFolders?api<{folders:Folder[]}>('/folders?'+new URLSearchParams({path:currentPath()})):Promise.resolve({folders:[] as Folder[]})
    ]);
    if(epoch!==listEpoch)return;
    const items=append?[...state.items,...data.items]:data.items;
    const scope=JSON.stringify([state.root,state.folder,state.recent,state.recursive,state.q,state.kind,state.sort,state.direction]);
    const changed=renderedScope!==scope||JSON.stringify([items,directories.folders])!==JSON.stringify([state.items,state.folders]);renderedScope=scope;
    if(!append)state.offset=data.offset;
    state.items=items;state.folders=directories.folders;state.total=data.total;
    if(changed||!$('grid').childElementCount)renderGrid();updateHeading();updateSelection();
    $('from-start').hidden=state.offset===0;
    $('more').hidden=state.offset+state.items.length>=data.total;$('paging').textContent=data.total?`已加载 ${state.items.length} / ${data.total}${state.offset?` · 从第 ${state.offset+1} 项开始`:''}`:'';
  } catch(e) {if(epoch===listEpoch){$('grid').replaceChildren(el('div','empty-grid',(e as Error).message));toast((e as Error).message);}}
}
function directoryCard(folder:Folder,rootId:string){
  const card=action('',()=>chooseFolder(rootId,folder.path),'directory-card');card.title=folder.path;card.dataset.path=folder.path;
  const label=el('div','folder-label');label.append(el('strong','',folder.name),el('span','muted','点击进入目录'));card.append(folderIcon(),label);return card;
}
function renderGrid() {
  const grid=$('grid');grid.replaceChildren();
  const directories=el('div','directory-grid');
  if(!state.root&&!state.recent){for(const root of state.roots)directories.append(directoryCard({name:root.name,path:root.path},root.id));grid.append(directories);return;}
  if(state.folders.length){for(const folder of state.folders)directories.append(directoryCard(folder,state.root));grid.append(directories);}
  if(!state.items.length&&!state.folders.length){grid.append(el('div','empty-grid',state.recent?'还没有使用记录。选择素材并点击“使用”后，将保留最近 20 项。':'没有匹配的素材。可更换筛选、添加目录或刷新索引。'));return;}
  for(const item of state.items) {
    const card=el('article',`card ${(state.current?.id===item.id||state.focusId===item.id)?'selected':''} ${item.missing?'missing':''}`);card.tabIndex=0;card.title=item.name;card.dataset.id=item.id;
    const thumb=el('div','thumb');const glyph=el('span','file-glyph',item.kind==='other'?(item.extension.slice(1).toUpperCase()||'FILE'):glyphs[item.kind]);thumb.append(glyph);
    if(['image','video'].includes(item.kind)&&!item.missing) {
      const img=el('img');img.loading='lazy';img.alt=item.name;img.src=url('/thumb?id='+item.id);img.onerror=()=>img.remove();img.onload=()=>glyph.remove();thumb.append(img);
    }
    const badge=item.missing?'已失效':item.kind==='video'||item.kind==='audio'?(item.properties.duration!==undefined?duration(item.properties.duration):names[item.kind]):names[item.kind];
    thumb.append(el('span','type-badge',badge));
    const checkLabel=el('label','card-check'),check=el('input');check.type='checkbox';check.checked=state.selected.has(item.id);check.setAttribute('aria-label','选择 '+item.name);
    checkLabel.onclick=e=>e.stopPropagation();check.onchange=()=>{state.selectionMode=true;if(check.checked)state.selected.add(item.id);else state.selected.delete(item.id);updateSelection();};checkLabel.append(check);
    const body=el('div','card-body');const meta=el('div','card-meta');meta.append(el('span','',size(item.size)));
    if(item.properties.width)meta.append(el('span','',`${item.properties.width} × ${item.properties.height}`));else meta.append(el('span','',item.extension||'无扩展名'));
    body.append(el('div','card-name',item.name),meta);card.append(checkLabel,thumb,body);
    card.onclick=e=>{if(state.selectionMode||e.ctrlKey||e.metaKey)toggleSelection(item.id);else void openDetail(item.id);};
    card.ondblclick=e=>{if((e.target as Element).closest('.card-check'))return;e.preventDefault();e.stopPropagation();closeAssetMenu();void openDetail(item.id);};
    card.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();openAssetMenu(item,e.clientX,e.clientY);};
    card.onkeydown=e=>{if(e.target!==card)return;if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){e.preventDefault();const rect=card.getBoundingClientRect();openAssetMenu(item,rect.left+20,rect.top+30);}else if(e.key==='Enter'||e.key===' '){e.preventDefault();if(state.selectionMode||e.ctrlKey||e.metaKey)toggleSelection(item.id);else void openDetail(item.id);}};
    grid.append(card);
  }
}
function clearSelection(){state.selected.clear();state.selectionMode=false;}
function toggleSelection(id:string){state.selectionMode=true;if(state.selected.has(id))state.selected.delete(id);else state.selected.add(id);updateSelection();}
function updateSelection(){
  const n=state.selected.size;$('bulk').hidden=!state.selectionMode&&n===0;$('selection-count').textContent=`已选择 ${n} 项`;
  const mode=$<HTMLButtonElement>('multi-select');mode.textContent=state.selectionMode?'完成多选':'多选';mode.classList.toggle('active',state.selectionMode);mode.setAttribute('aria-pressed',String(state.selectionMode));
  for(const op of ['rename','move','delete'])$<HTMLButtonElement>('bulk-'+op).disabled=n===0;
  $<HTMLInputElement>('select-page').checked=state.items.length>0&&state.items.every(i=>state.selected.has(i.id));
  for(const card of $('grid').querySelectorAll<HTMLElement>('.card')){const selected=state.selected.has(card.dataset.id||'');card.classList.toggle('is-checked',selected);const checkbox=card.querySelector<HTMLInputElement>('input[type="checkbox"]');if(checkbox)checkbox.checked=selected;}
}
function closeAssetMenu(){$('asset-context-menu').hidden=true;}
function openAssetMenu(item:Item,x:number,y:number){
  if(!state.selected.has(item.id)){clearSelection();state.selected.add(item.id);updateSelection();}
  const ids=[...state.selected],menu=$('asset-context-menu');menu.replaceChildren(el('div','context-selection',`已选择 ${ids.length} 项素材`));
  const remove=action(ids.length>1?`删除所选 ${ids.length} 项`:'删除',()=>{closeAssetMenu();return openOperation('delete',ids);},'context-delete');remove.setAttribute('role','menuitem');menu.append(remove);
  menu.hidden=false;const rect=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(x,window.innerWidth-rect.width-8))+'px';menu.style.top=Math.max(8,Math.min(y,window.innerHeight-rect.height-8))+'px';remove.focus();
}
function releaseMedia() {stopPreview();stopPreview=()=>{};clearTimeout(previewTimer);for(const media of $('detail').querySelectorAll('video,audio')){const m=media as HTMLMediaElement;m.pause();m.removeAttribute('src');m.load();}}
async function openDetail(id='',path='') {
  const epoch=++detailEpoch;releaseMedia();
  try {
    const item=await api<Detail>('/detail?'+new URLSearchParams({id,path}));if(epoch!==detailEpoch)return;
    if(!previewOnly&&!$<HTMLDialogElement>('detail-dialog').open)$<HTMLDialogElement>('detail-dialog').showModal();
    state.current=item;state.focusId=item.id;renderDetail(item);for(const card of $('grid').children)card.classList.toggle('selected',(card as HTMLElement).dataset.id===item.id);
  }catch(e){if(epoch!==detailEpoch)return;state.current=null;if(!previewOnly&&!$<HTMLDialogElement>('detail-dialog').open)$<HTMLDialogElement>('detail-dialog').showModal();$('detail').classList.add('has-item');$('detail').replaceChildren(el('div','detail-content error',(e as Error).message),action('关闭',closeDetail));if(!previewOnly)toast((e as Error).message);}
}
function closeDetail(){++detailEpoch;releaseMedia();$<HTMLDialogElement>('json-dialog').close();$<HTMLDialogElement>('generation-dialog').close();$<HTMLDialogElement>('detail-dialog').close();state.current=null;$('detail').classList.remove('has-item');$('detail').replaceChildren(el('div','empty-detail','选择文件以查看详情'));}
function renderDetail(item:Detail) {
  const panel=$('detail');panel.classList.add('has-item');panel.replaceChildren();
  const head=el('div','detail-top');head.append(el('h2','','素材详情'),action('×',closeDetail));
  const preview=el('div','preview'),compat=el('div','compat');compat.hidden=true;let media:HTMLMediaElement|null=null,stopped=false;
  stopPreview=()=>{stopped=true;};
  if(item.kind==='image') {const image=el('img');image.alt=item.name;image.src=url('/file?id='+item.id);image.onerror=()=>preview.replaceChildren(el('p','error','图片无法预览'));preview.append(image);}
  else if(item.kind==='video'||item.kind==='audio') {
    media=el(item.kind==='video'?'video':'audio');media.controls=true;media.preload='metadata';
    if(media instanceof HTMLVideoElement){media.playsInline=true;media.poster=url('/thumb?id='+item.id);}
    media.src=url('/file?id='+item.id);preview.append(media);
    const label=el('p','muted',previewOnly?'此文件需要兼容预览。':'原文件无法播放时，可生成兼容预览。输出路径始终指向原文件。');
    const button=action('生成兼容预览',()=>pollCompatible(true));compat.append(label,button);compat.hidden=previewOnly;
    let fetching=false;
    async function pollCompatible(retry=false) {
      if(stopped||fetching)return;fetching=true;button.disabled=true;
      try{
        const job=await api<{state:string;url:string;error?:string}>('/preview',{id:item.id,retry});if(stopped)return;
        if(job.state==='ready') {media!.src=job.url.replace(/^\/toolbox\/media-library(?=\/)/,base);media!.load();label.textContent=previewOnly?'正在播放兼容预览':'正在播放兼容预览 · 使用时仍输出原文件路径';button.hidden=true;}
        else if(job.state==='error'){label.textContent=job.error||'转换失败';button.textContent='重试生成兼容预览';button.disabled=false;}
        else{label.textContent=job.state==='queued'?'兼容预览等待处理中…':'正在生成兼容预览…';previewTimer=window.setTimeout(()=>void pollCompatible(),2000);}
      }catch(e){if(!stopped){label.textContent=(e as Error).message;button.disabled=false;}}
      finally{fetching=false;}
    }
    let attempted=false;media.onerror=()=>{if(!attempted&&!stopped){attempted=true;compat.hidden=false;label.textContent='浏览器无法播放原文件，正在准备兼容预览…';void pollCompatible();}};
  } else if(item.kind==='text') {const text=el('pre','',item.text);preview.append(text);}
  else preview.append(el('span','file-glyph',item.kind==='other'?(item.extension.slice(1).toUpperCase()||'FILE'):glyphs[item.kind]));
  if(previewOnly){
    const parts:string[]=[],props=item.properties;
    const hasDuration=props.duration!==undefined&&props.duration!==null&&Number.isFinite(Number(props.duration));
    if(item.kind!=='audio'||!hasDuration)parts.push(size(item.size));
    if((item.kind==='image'||item.kind==='video')&&props.width&&props.height)parts.push(`${props.width} × ${props.height}`);
    if((item.kind==='video'||item.kind==='audio')&&hasDuration)parts.push(duration(props.duration));
    const footer=el('div','node-media-info');footer.setAttribute('aria-label','素材信息');
    for(const part of parts)footer.append(el('span','',part));
    panel.append(preview,compat,footer);return;
  }
  const content=el('div','detail-content');content.append(el('h2','detail-name',item.name));
  const pathBox=el('div','path-box');pathBox.append(el('code','',item.path),action('复制路径',()=>copy(item.path)));content.append(pathBox);
  const use=action('使用此文件  ↗',async()=>{
    const chosen=await api<Detail>('/select',{id:item.id});
    if(window.parent!==window)window.parent.postMessage({type:'tb-media-library-select',id:chosen.id,path:chosen.path},location.origin);
    else {await copy(chosen.path);toast('已使用并复制原文件路径');closeDetail();if(state.recent)await loadFiles();}
  },'primary use');content.append(use);
  if(item.truncated)content.append(el('p','error','信息达到读取上限，当前内容已截断；复制全部信息会包含此标记。'));
  for(const error of item.errors)content.append(el('p','error',error));
  const info=el('section','info-section');info.append(el('div','info-title','文件信息'));const dl=el('dl');
  const props:Record<string,unknown>={'类型':names[item.kind],'文件大小':size(item.size),'修改时间':when(item.mtime)};
  const labels:Record<string,string>={width:'宽度（像素）',height:'高度（像素）',aspect_ratio:'宽高比',duration:'时长',fps:'帧率',video_codec:'视频编码',audio_codec:'音频编码',sample_rate:'采样率（Hz）',channels:'声道',vertices:'顶点数',faces:'面数量',format:'格式',frames:'帧数',sample_aspect_ratio:'像素宽高比'};
  if(item.properties.width!=null&&item.properties.height!=null)props['宽×高（像素）']=`${item.properties.width} × ${item.properties.height}`;
  if(item.properties.aspect_ratio)props['宽高比']=item.properties.aspect_ratio;
  for(const [key,value] of Object.entries(item.properties))if(value!==null&&value!==undefined&&!['width','height','aspect_ratio'].includes(key))props[labels[key]||key]=key==='duration'?`${duration(value)}（${Number(value).toFixed(2)} 秒）`:value;
  for(const [key,value]of Object.entries(props)){const row=el('div','property');row.append(el('dt','',key),el('dd','',String(value)));dl.append(row);}info.append(dl);content.append(info);
  const meta=el('section','info-section');
  const show=action('',()=>openGeneration(item),'generation-open');show.id='show-generation';
  const text=el('span');text.append(el('strong','','生成信息'),el('small','','查看提示词、模型等关键信息'));show.append(text,el('span','','›'));meta.append(show);
  if(item.kind==='text')meta.append(action('复制文本内容',()=>copy(item.text)));
  content.append(meta);
  const actions=el('div','file-actions');actions.append(action('重命名',()=>openOperation('rename',[item.id])),action('移动',()=>openOperation('move',[item.id])),action('删除',()=>openOperation('delete',[item.id]),'danger'));content.append(actions);
  panel.append(head,preview,compat,content);
}
function parameterTable(){
  const table=el('table','generation-table'),header=el('thead'),row=el('tr');row.append(el('th','','标题'),el('th','','数据'));header.append(row);const body=el('tbody');table.append(header,body);return{table,body};
}
function parameterRow(body:HTMLElement,label:string,value:string){
  const row=el('tr','generation-row'),heading=el('th','',label);heading.scope='row';
  const cell=el('td'),content=el('div','generation-value');content.append(el('pre','',value),action('复制',()=>copy(value)));cell.append(content);row.append(heading,cell);body.append(row);
}
function keyGenerationValues(item:Detail){
  const specs=[
    {key:'positive',label:'正向提示词',names:['positive','positive_prompt','positive_text']},
    {key:'negative',label:'负向提示词',names:['negative','negative_prompt','negative_text']},
    {key:'prompt',label:'提示词',names:['prompt','text','text_g','text_l','string']},
    {key:'model',label:'模型',names:['model','model_name','ckpt_name','unet_name','model_path','checkpoint']},
    {key:'lora',label:'LoRA',names:['lora_name','lora_names']},
    {key:'seed',label:'种子',names:['seed','noise_seed']},
    {key:'steps',label:'步数',names:['steps','num_inference_steps']},
    {key:'cfg',label:'CFG',names:['cfg','cfg_scale','guidance_scale']},
    {key:'sampler',label:'采样器',names:['sampler','sampler_name']},
    {key:'scheduler',label:'调度器',names:['scheduler']},
    {key:'denoise',label:'降噪强度',names:['denoise','denoise_strength']},
  ];
  const rows:{label:string;value:string}[]=[];
  const roleKnown=['positive','negative'].some(key=>Object.prototype.hasOwnProperty.call(item.summary,key))||(item.generation_nodes||[]).some(node=>node.fields.some(field=>['positive','positive_prompt','positive_text','negative','negative_prompt','negative_text'].includes(field.name.toLowerCase())));
  for(const spec of specs){
    if(spec.key==='prompt'&&roleKnown)continue;
    const primary=item.summary[spec.key]??(spec.key==='model'?item.summary.checkpoint:undefined);
    const values=new Set<string>();
    if(primary!==undefined&&primary!==null)values.add(String(primary)||'（空）');
    else for(const node of item.generation_nodes||[])for(const field of node.fields){
      if(!spec.names.includes(field.name.toLowerCase())||!field.value.trim())continue;
      if(!['prompt','positive','negative'].includes(spec.key)&&/^[{[]/.test(field.value.trim()))continue;
      values.add(field.value);
    }
    for(const value of values)rows.push({label:spec.label,value});
  }
  return rows;
}
function openGeneration(item:Detail){
  $('generation-file').textContent=item.name;
  const content=$('generation-content');content.replaceChildren();
  const {table,body}=parameterTable(),values=keyGenerationValues(item);
  for(const row of values)parameterRow(body,row.label,row.value);
  if(values.length)content.append(table);
  else content.append(el('p','muted','没有读取到提示词、模型等关键信息。'));
  $('show-all-info').onclick=()=>openAllInfo(item);
  $('copy-generation').onclick=()=>void copy(JSON.stringify(item,null,2));
  $<HTMLDialogElement>('generation-dialog').showModal();
}
function jsonTreeNode(key:string,value:unknown,root=false):HTMLElement{
  let data=value,encoded=false;
  if(typeof value==='string'&&value.length){
    let decoded:unknown=value;
    for(let i=0;i<2&&typeof decoded==='string';i++){
      try{decoded=JSON.parse(decoded);}catch{break;}
    }
    if(decoded!==null&&typeof decoded==='object'){data=decoded;encoded=true;}
  }
  const label=()=>el('span','json-key',key);
  if(data!==null&&typeof data==='object'){
    const branch=el('details','json-branch'),heading=el('summary');
    const entries:Array<[string,unknown]>=Array.isArray(data)?data.map((entry,index)=>[String(index),entry]):Object.entries(data);
    heading.append(label(),el('span','json-count',`${encoded?'JSON 字符串 · ':''}${Array.isArray(data)?'['+entries.length+']':'{'+entries.length+'}'}`));
    branch.append(heading);let mounted=false;
    const mount=()=>{if(mounted)return;mounted=true;const children=el('div','json-children');for(const[name,entry]of entries)children.append(jsonTreeNode(name,entry));branch.append(children);};
    branch.addEventListener('toggle',()=>{if(branch.open)mount();});
    if(root){mount();branch.open=true;}
    return branch;
  }
  const row=el('div','json-leaf');row.append(label(),el('span','json-colon',':'));
  const text=JSON.stringify(value)??String(value),literal=el('span','json-literal '+(value===null?'json-null':'json-'+typeof value),text.length>350?text.slice(0,350)+'…':text);row.append(literal);
  if(text.length>350){let expanded=false;const more=action('展开文本',()=>{expanded=!expanded;literal.textContent=expanded?text:text.slice(0,350)+'…';more.textContent=expanded?'收起文本':'展开文本';},'json-more');row.append(more);}
  return row;
}
function openAllInfo(item:Detail){
  $('json-file').textContent=item.name;$('json-tree').replaceChildren(jsonTreeNode('root',item,true));
  $('json-copy').onclick=()=>void copy(JSON.stringify(item,null,2));
  $('json-expand').onclick=()=>{for(const branch of Array.from($('json-tree').querySelectorAll<HTMLDetailsElement>('details:not([open])')))branch.open=true;};
  $('json-collapse').onclick=()=>{for(const branch of $('json-tree').querySelectorAll<HTMLDetailsElement>('details'))branch.open=false;};
  $<HTMLDialogElement>('json-dialog').showModal();
}
function renderRootSettings(){const area=$('root-settings');area.replaceChildren();for(const root of state.roots){const row=el('div','root-setting'),label=el('div','',root.name);label.append(el('small','',root.path));row.append(label);if(root.builtin)row.append(el('span','muted','默认目录'));else row.append(action('移除',async()=>{await api('/roots/'+root.id,{},'DELETE');state.root='';state.folder='';await loadRoots();await loadFiles();}));area.append(row);}}
function showSettings(){renderRootSettings();$<HTMLDialogElement>('settings-dialog').showModal();}
function fileName(path:string){return path.split(/[\\/]/).filter(Boolean).pop()||path;}
function parentPath(path:string){const parent=path.replace(/[\\/][^\\/]+[\\/]?$/,'');return /^[A-Za-z]:$/.test(parent)?parent+'\\':parent||'/';}
async function openOperation(op:string,ids:string[]) {
  const epoch=++operationEpoch;
  operation=op;operationIds=ids;plan=null;moveDestination='';++moveEpoch;
  $('operation-list').replaceChildren();$('operation-fields').replaceChildren();
  $('apply-operation').hidden=true;$<HTMLButtonElement>('apply-operation').disabled=false;
  $('plan-operation').hidden=op!=='rename';$('operation-cancel').textContent='取消';
  $('operation-title').textContent=({rename:'重命名文件',move:'移动文件',delete:'删除文件'} as Record<string,string>)[op];
  $('operation-description').textContent=op==='delete'?`确定永久删除以下文件？此操作无法撤销。`:op==='move'?`已选择 ${ids.length} 项。进入目标文件夹后，点击“移动到这里”。`:`已选择 ${ids.length} 项。修改名称后预览结果。`;
  $('apply-operation').classList.toggle('danger',op==='delete');
  $('operation-fields').oninput=()=>{if(operation==='rename'){plan=null;$('apply-operation').hidden=true;$('operation-list').replaceChildren();}};
  $<HTMLDialogElement>('operation-dialog').showModal();
  if(op==='rename'){
    const label=el('label','','名称模板（扩展名自动保留；支持 {name}、{index}、{index:03d}）'),input=el('input');input.id='rename-template';input.value=ids.length===1?(state.items.find(i=>i.id===ids[0])?.name||state.current?.name||'').replace(/\.[^.]+$/,''):'{name}_{index:03d}';label.append(input);$('operation-fields').append(label);
    const startLabel=el('label','','序号起始值'),start=el('input');start.type='number';start.id='rename-start';start.value='1';startLabel.append(start);$('operation-fields').append(startLabel);
  }else if(op==='delete'){
    try{
      const result=await api<Plan>('/operations/plan',{op,ids});if(epoch!==operationEpoch)return;plan=result;
      for(const entry of result.entries){
        const row=el('div','delete-file');
        if(entry.error)row.append(el('p','error',entry.error));
        for(const a of entry.actions){const name=el('div','',fileName(a.source));name.title=a.source;row.append(name);}
        $('operation-list').append(row);
      }
      $('apply-operation').textContent='永久删除';$('apply-operation').hidden=!result.entries.some(e=>!e.error);
    }catch(e){if(epoch===operationEpoch)$('operation-list').append(el('p','error',(e as Error).message));}
  }else if(op==='move'){
    const current=state.items.find(i=>i.id===ids[0])||state.current;
    const path=current?.path||(await api<Detail>('/detail?id='+ids[0])).path;
    if(epoch===operationEpoch)await loadMoveDirectory(parentPath(path));
  }
}
async function loadMoveDirectory(path:string){
  const epoch=++moveEpoch;plan=null;moveDestination=path;
  const apply=$<HTMLButtonElement>('apply-operation');apply.hidden=false;apply.disabled=true;apply.textContent='移动到这里';
  $('operation-list').replaceChildren();const picker=el('div','move-picker'),address=el('div','move-address',path||'素材目录'),list=el('div','move-directories');
  picker.append(address,list);$('operation-fields').replaceChildren(picker);
  try{
    const folders=path?(await api<{folders:Folder[]}>('/folders?'+new URLSearchParams({path}))).folders:state.roots;
    if(epoch!==moveEpoch||operation!=='move')return;
    if(path){
      const parent=parentPath(path),inside=state.roots.some(r=>parent===r.path||parent.startsWith(r.path+'/')||parent.startsWith(r.path+'\\'));
      const up=action('',()=>loadMoveDirectory(inside?parent:''),'move-directory');up.setAttribute('aria-label','..');up.append(el('span','move-up','..'),el('span','','上一级'));list.append(up);
    }
    for(const folder of folders){const b=action('',()=>loadMoveDirectory(folder.path),'move-directory');b.setAttribute('aria-label',folder.name);b.append(folderIcon(),el('span','',folder.name),el('span','move-chevron','›'));list.append(b);}
    if(!folders.length)list.append(el('p','muted','此目录下没有子目录，可移动到当前目录。'));
    apply.disabled=!path;
  }catch(e){if(epoch===moveEpoch)list.append(el('p','error',(e as Error).message));}
}
async function previewOperation(){
  if(operation!=='rename')return;
  const epoch=operationEpoch;plan=null;$('apply-operation').hidden=true;const button=$<HTMLButtonElement>('plan-operation');button.disabled=true;
  try{
    const result=await api<Plan>('/operations/plan',{op:operation,ids:operationIds,template:$<HTMLInputElement>('rename-template').value,start:Number($<HTMLInputElement>('rename-start').value||1)});
    if(epoch!==operationEpoch)return;plan=result;$('operation-list').replaceChildren();
    for(const entry of result.entries){const card=el('div','operation-entry');if(entry.error)card.append(el('div','error',entry.error));for(const a of entry.actions)card.append(el('div','',a.source),el('div','target','→ '+a.target));$('operation-list').append(card);}
    $('apply-operation').hidden=!result.entries.some(e=>!e.error);$('apply-operation').textContent='确认重命名';
  }catch(e){if(epoch===operationEpoch)$('operation-list').replaceChildren(el('p','error',(e as Error).message));}finally{button.disabled=false;}
}
async function applyOperation(){
  const epoch=operationEpoch,op=operation,ids=[...operationIds],destination=moveDestination;
  const button=$<HTMLButtonElement>('apply-operation');button.disabled=true;
  try{
    if(op==='move'){const prepared=await api<Plan>('/operations/plan',{op:'move',ids,destination});if(epoch!==operationEpoch)return;plan=prepared;}
    if(!plan||epoch!==operationEpoch)return;
    const result=await api<{results:{ok:boolean;error?:string;completed?:Action[]}[]}>('/operations/apply',{token:plan.token,confirmed:true});plan=null;
    if(epoch!==operationEpoch){toast('文件操作已完成');return;}
    $('operation-list').replaceChildren();let ok=0;
    result.results.forEach(r=>{if(r.ok)ok++;const card=el('div','operation-entry');card.append(el('div',r.ok?'target':'error',r.ok?'已完成':r.error||'操作失败'));for(const a of r.completed||[])card.append(el('div','',a.source+(a.target?' → '+a.target:' → 已删除')));$('operation-list').append(card);});
    button.hidden=true;toast(`已完成 ${ok} / ${result.results.length} 项`);clearSelection();
    if(ok===result.results.length)$<HTMLDialogElement>('operation-dialog').close();
    await loadFiles();
    if(state.current){if(op==='delete'&&ids.includes(state.current.id)&&ok)closeDetail();else await openDetail(state.current.id);}
    window.parent.postMessage({type:'tb-media-library-changed'},location.origin);
  }catch(e){$('operation-list').replaceChildren(el('p','error',(e as Error).message));}finally{button.disabled=false;}
}
let lastFinished:number|null=null,lastRevision=-1,wasScanning=false;
async function pollStatus(){
  const epoch=++statusEpoch;clearTimeout(statusTimer);
  try{
    const s=await api<{running:boolean;scanned:number;finished_at:number|null;errors:string[];revision:number}>('/status');
    if(epoch!==statusEpoch)return;
    $('scan-status').textContent=!s.running&&!s.finished_at?'按需索引 · 选择目录开始浏览':s.running?`正在索引 · 已扫描 ${s.scanned} 个文件`:`索引就绪 · ${s.scanned} 个文件${s.errors.length?' · 部分文件读取失败':''}`;
    $('scan-status').title=s.errors.join('\n');
    if(s.finished_at!==lastFinished||s.revision!==lastRevision||wasScanning&& !s.running){lastFinished=s.finished_at;lastRevision=s.revision;await loadFiles();
      if(state.current){const item=state.items.find(i=>i.id===state.current!.id);if(item&&(item.path!==state.current.path||item.size!==state.current.size||item.mtime!==state.current.mtime))await openDetail(item.id);}}wasScanning=s.running;
    if(epoch===statusEpoch)statusTimer=window.setTimeout(()=>void pollStatus(),s.running?1500:5000);
  }catch(e){if(epoch!==statusEpoch)return;$('scan-status').textContent=(e as Error).message;statusTimer=window.setTimeout(()=>void pollStatus(),5000);}
}
async function main(){
  document.addEventListener('paste',event=>{
    if(event.defaultPrevented||(event.target as Element)?.closest?.('input,textarea,[contenteditable]:not([contenteditable="false"])'))return;
    const files=Array.from(event.clipboardData?.files||[]).filter(file=>file.type.startsWith('image/'));
    if(!files.length||previewOnly&&window.parent===window)return;
    event.preventDefault();event.stopPropagation();
    if(previewOnly)window.parent.postMessage({type:'tb-media-library-paste-image',file:files[0]},location.origin);
    else void uploadFiles(files,'pasted');
  });
  if(previewOnly){document.body.classList.add('preview-only');$<HTMLDialogElement>('detail-dialog').open=true;const id=params.get('id')||'',path=params.get('path')||'';if(id||path)await openDetail(id,path);else $('detail').replaceChildren(el('p','muted','点击浏览素材库选择文件'));return;}
  const viewer=$<HTMLDialogElement>('detail-dialog');viewer.addEventListener('cancel',event=>{event.preventDefault();closeDetail();});viewer.addEventListener('click',event=>{if(event.target===viewer)closeDetail();});
  for(const [key,label]of Object.entries({'':'全部',...names})){const button=action(label,async()=>{state.kind=key;state.offset=0;state.focusId='';for(const b of $('types').children)b.classList.toggle('active',(b as HTMLElement).dataset.kind===key);clearSelection();await loadFiles();});button.dataset.kind=key;button.classList.toggle('active',!key);$('types').append(button);}
  $('all').onclick=()=>void home();
  $('recent').onclick=()=>{state.root='';state.folder='';state.recent=true;state.focusId='';state.offset=0;resetRecursive();clearSearch();clearSelection();void loadFiles();};
  $('parent').onclick=()=>{const root=state.roots.find(r=>r.id===state.root);if(!root||currentPath()===root.path){void home();return;}const parent=currentPath().replace(/[\\/][^\\/]+[\\/]?$/,'');void chooseFolder(root.id,parent||root.path);};
  $('recursive').onchange=async()=>{state.recursive=$<HTMLInputElement>('recursive').checked;state.offset=0;state.focusId='';clearSelection();await loadFiles();await api('/scan',{path:currentPath(),recursive:state.recursive});void pollStatus();};
  $('upload').onclick=()=>$<HTMLInputElement>('upload-files').click();
  $('upload-files').onchange=()=>void uploadFiles(Array.from($<HTMLInputElement>('upload-files').files||[]));
  $('settings').onclick=showSettings;$('add-root').onclick=showSettings;
  $('scan').onclick=async()=>{try{await api('/scan',{path:currentPath(),recursive:state.recursive});toast(state.recursive?'已开始刷新当前目录及子目录':'已开始刷新当前层目录');clearTimeout(statusTimer);void pollStatus();}catch(e){toast((e as Error).message);}};
  $('from-start').onclick=()=>{state.offset=0;state.focusId='';clearSelection();void loadFiles();};
  $('more').onclick=()=>void loadFiles(true);$('prune').onclick=async()=>{await api('/recents/prune',{});await loadFiles();};
  let debounce=0;$('search').oninput=()=>{clearTimeout(debounce);debounce=window.setTimeout(()=>{state.q=$<HTMLInputElement>('search').value;state.offset=0;state.focusId='';clearSelection();void loadFiles();},240);};
  $('sort').onchange=()=>{state.sort=$<HTMLSelectElement>('sort').value;state.offset=0;state.focusId='';void loadFiles();};$('direction').onclick=()=>{state.direction=state.direction==='desc'?'asc':'desc';state.offset=0;state.focusId='';$('direction').textContent=state.direction==='desc'?'↓':'↑';void loadFiles();};
  $('multi-select').onclick=()=>{state.selectionMode=!state.selectionMode;updateSelection();};
  document.addEventListener('pointerdown',e=>{if(!$('asset-context-menu').contains(e.target as Node))closeAssetMenu();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeAssetMenu();});
  document.addEventListener('scroll',closeAssetMenu,true);window.addEventListener('resize',closeAssetMenu);
  $('select-page').onchange=()=>{state.selectionMode=true;if($<HTMLInputElement>('select-page').checked)state.items.forEach(i=>state.selected.add(i.id));else state.items.forEach(i=>state.selected.delete(i.id));updateSelection();};
  $('clear-selection').onclick=()=>{clearSelection();updateSelection();};
  for(const op of ['rename','move','delete'])$('bulk-'+op).onclick=()=>openOperation(op,[...state.selected]);
  $('operation-dialog').addEventListener('close',()=>{++operationEpoch;++moveEpoch;plan=null;});
  $('plan-operation').onclick=()=>void previewOperation();$('apply-operation').onclick=()=>void applyOperation();
  for(const b of document.querySelectorAll<HTMLButtonElement>('[data-close]'))b.onclick=()=>$<HTMLDialogElement>(b.dataset.close!).close();
  $<HTMLFormElement>('root-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget as HTMLFormElement,button=form.querySelector('button')!;button.disabled=true;try{const data=new FormData(form);await api('/roots',{name:data.get('name'),path:data.get('path')});form.reset();$('root-error').textContent='';await loadRoots();await loadFiles();toast('目录已添加，正在后台索引');}catch(e){$('root-error').textContent=(e as Error).message;}finally{button.disabled=false;}};
  window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==window.parent||event.data?.type!=='tb-media-library-current')return;if(event.data.id||event.data.path)void locateCurrent(String(event.data.id||''),String(event.data.path||''));});
  await loadRoots();const initialId=params.get('current_id')||'',initialPath=params.get('current_path')||'';if(initialId||initialPath)await locateCurrent(initialId,initialPath);else await loadFiles();void pollStatus();window.parent.postMessage({type:'tb-media-library-ready'},location.origin);
}
window.addEventListener('pagehide',()=>{++statusEpoch;releaseMedia();clearTimeout(statusTimer);});
void main().catch(e=>toast(e.message));
