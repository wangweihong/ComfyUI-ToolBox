const ENDPOINT='/toolbox/database/backups';

function el(tag,className='',text) {
    const node=document.createElement(tag);node.className=className;
    if(text!==undefined)node.textContent=text;
    return node;
}
function button(text,handler,className='') {
    const node=el('button',className,text);node.type='button';node.onclick=handler;return node;
}
function size(bytes) {
    return bytes>=1024**3?`${(bytes/1024**3).toFixed(2)} GiB`:`${(bytes/1024**2).toFixed(2)} MiB`;
}
export function ensureDatabaseBackupStyles() {
    if(document.querySelector('link[data-toolbox-database-backups]'))return;
    const link=el('link');link.rel='stylesheet';link.href=new URL('../css/database_backups.css?v=20261115-delete',import.meta.url).href;
    link.dataset.toolboxDatabaseBackups='true';document.head.append(link);
}

export function openDatabaseBackups({request,onClose=()=>{}}) {
    ensureDatabaseBackupStyles();
    const dialog=el('dialog','tb-prompts tbp-backup-dialog');dialog.setAttribute('aria-label','数据库备份');
    const header=el('header','tbp-header'),body=el('div','tbp-backup-body');
    const status=el('p','tbp-backup-status');status.setAttribute('role','status');
    const location=el('p','tbp-backup-location'),list=el('div','tbp-backup-list');
    let closed=false,submitting=false,cleaning=false,deleting=false,pollTimer,listingController,active=null,downloadBase,cleanupDialog,deleteDialog,totalBackups=0;
    const close=()=>{
        if(closed)return;closed=true;clearTimeout(pollTimer);listingController?.abort();
        cleanupDialog?.close();deleteDialog?.close();dialog.close();dialog.remove();onClose();
    };
    const create=button('立即备份',()=>void createBackup(),'tbp-primary');
    const refresh=button('刷新列表',()=>void load());
    const cleanup=button('清理旧备份',()=>openCleanup());
    header.append(el('strong','','数据库备份'),button('关闭',close));
    const actions=el('div','tbp-backup-actions');actions.append(create,refresh,cleanup);
    body.append(el('p','tbp-backup-description','备份整个 ToolBox 数据库，包含提示词、标签、Skill / 模板及内嵌文件、素材索引和历史记录。素材原文件不包含在备份中。'),
        actions,status,location,list);
    dialog.append(header,body);document.body.append(dialog);
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.showModal();

    async function json(path,options={}) {
        const response=await request(path,options);
        const data=await response.json().catch(()=>({}));
        if(!response.ok)throw new Error(data.error||`请求失败：HTTP ${response.status}`);
        return {data,response};
    }
    function updateActive() {
        const busy=submitting||cleaning||deleting||Boolean(active);
        create.disabled=cleanup.disabled=busy;
        for(const control of list.querySelectorAll('[data-delete-backup]'))control.disabled=busy;
        if(active)status.textContent=active.phase==='deleting'?'正在删除备份…':active.phase==='cleaning'?'正在清理旧备份…':active.phase==='verifying'?'正在校验备份完整性…':`正在备份数据库… ${active.percent}%`;
        clearTimeout(pollTimer);
        if(!closed&&(submitting||active))pollTimer=setTimeout(()=>void load(),1000);
    }
    function render(data) {
        const wasActive=Boolean(active);
        active=data.active;
        totalBackups=data.total;
        if(wasActive&&!active&&!submitting)status.textContent='备份任务已结束，请查看下方备份列表。';
        location.textContent=`服务器保存目录：${data.directory}`;
        list.replaceChildren();
        if(!data.items.length)list.append(el('p','tbp-status','还没有手动备份。'));
        for(const item of data.items) {
            const row=el('div','tbp-backup-row'),info=el('div');
            info.append(el('strong','',new Date(item.created_at).toLocaleString()),el('span','tbp-status',`${size(item.size_bytes)} · ${item.filename}`));
            const download=el('a','tbp-backup-download','下载');
            const url=new URL(downloadBase);url.pathname=url.pathname.replace(/\/$/,'')+'/'+encodeURIComponent(item.filename);
            download.href=url.href;download.download=item.filename;
            const remove=button('删除',()=>openDelete(item),'tbp-backup-delete');remove.dataset.deleteBackup=item.filename;
            const actions=el('div','tbp-backup-row-actions');actions.append(download,remove);
            row.append(info,actions);list.append(row);
        }
        if(data.total>data.items.length)list.append(el('p','tbp-status',`共 ${data.total} 个备份，显示最近 ${data.items.length} 个。`));
        updateActive();
    }
    async function load() {
        listingController?.abort();const current=listingController=new AbortController();
        try {
            const {data,response}=await json(ENDPOINT,{signal:current.signal});
            if(closed||current!==listingController)return;
            // Keep ComfyUI's /api prefix (or reverse-proxy prefix) for streamed downloads.
            downloadBase=new URL(response.url||ENDPOINT,window.location.href);downloadBase.search='';downloadBase.hash='';
            render(data);
            if(!submitting&&!active&&!status.textContent)status.textContent='备份完成后自动校验，可下载到本机保存。';
        } catch(error) {
            if(!closed&&error.name!=='AbortError'&&current===listingController){status.textContent=`备份列表读取失败：${error.message}`;updateActive();}
        }
    }
    async function createBackup() {
        if(submitting||cleaning||deleting||active||closed)return;
        submitting=true;status.textContent='正在备份数据库…';updateActive();
        try {
            // Closing the dialog does not cancel a backup that the user already started.
            const {data}=await json(ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
            if(closed)return;
            active=null;status.textContent=`备份完成，完整性校验通过：${data.filename}`;
        } catch(error) {
            if(!closed)status.textContent=`备份失败：${error.message}`;
        } finally {
            submitting=false;
            if(!closed){updateActive();await load();}
        }
    }
    function openDelete(item) {
        if(closed||submitting||cleaning||deleting||active||cleanupDialog||deleteDialog)return;
        const view=el('dialog','tb-prompts tbp-backup-dialog tbp-backup-delete-dialog');view.setAttribute('aria-label','删除备份');
        const head=el('header','tbp-header'),content=el('div','tbp-backup-body');
        const message=el('p','tbp-backup-status','确认永久删除这份备份？');message.setAttribute('role','status');
        const info=el('div','tbp-backup-candidate');info.append(el('strong','',new Date(item.created_at).toLocaleString()),el('span','tbp-status',`${size(item.size_bytes)} · ${item.filename}`));
        if(totalBackups===1)info.append(el('p','tbp-backup-last','这是最后一份手动备份，删除后备份列表将为空。'));
        let dismissed=false;
        const closeDelete=()=>{if(dismissed)return;dismissed=true;view.close();view.remove();deleteDialog=null;};
        const apply=button('确认删除',()=>void remove(),'tbp-backup-danger');
        const footer=el('div','tbp-backup-actions tbp-backup-cleanup-actions');footer.append(button('取消',closeDelete),apply);
        head.append(el('strong','','删除备份'),button('关闭',closeDelete));content.append(message,info,footer);
        view.append(head,content);document.body.append(view);view.addEventListener('cancel',event=>{event.preventDefault();closeDelete();});
        deleteDialog={close:closeDelete};view.showModal();

        async function remove() {
            if(deleting||apply.disabled||dismissed)return;
            deleting=true;apply.disabled=true;message.textContent='正在删除备份…';updateActive();
            try {
                const {data}=await json(ENDPOINT+'/'+encodeURIComponent(item.filename),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:item.version,confirmed:true})});
                if(closed)return;
                active=null;await load();status.textContent=`已删除备份 ${data.deleted}，释放 ${size(data.size_bytes)}，剩余 ${data.remaining_count} 份。`;closeDelete();
            } catch(error) {
                if(!closed){await load();status.textContent=`删除失败：${error.message}`;}
                if(!dismissed)message.textContent=`删除失败：${error.message} 请关闭弹窗，刷新列表后重试。`;
            } finally {
                deleting=false;if(!closed)updateActive();
            }
        }
    }
    function openCleanup() {
        if(closed||submitting||cleaning||deleting||active||cleanupDialog||deleteDialog)return;
        const view=el('dialog','tb-prompts tbp-backup-dialog tbp-backup-cleanup-dialog');view.setAttribute('aria-label','清理旧备份');
        const head=el('header','tbp-header'),content=el('div','tbp-backup-body');
        const field=el('label','tbp-backup-retention');field.append(el('span','','保留最近'));
        const keep=el('input');keep.type='number';keep.min='1';keep.max='1000';keep.step='1';keep.required=true;keep.value='5';keep.setAttribute('aria-label','保留最近备份数量');
        field.append(keep,el('span','','份备份'));
        const summary=el('p','tbp-backup-status','先预览将清理的旧备份，再确认删除。');summary.setAttribute('role','status');
        const candidates=el('div','tbp-backup-candidates');
        let dismissed=false,applying=false,plan=null,controller;
        const closeCleanup=()=>{if(dismissed)return;dismissed=true;controller?.abort();view.close();view.remove();cleanupDialog=null;};
        const preview=button('预览清理',()=>void previewCleanup());
        const apply=button('确认清理',()=>void applyCleanup(),'tbp-backup-danger');apply.disabled=true;
        const actions=el('div','tbp-backup-actions');actions.append(field,preview);
        const footer=el('div','tbp-backup-actions tbp-backup-cleanup-actions');footer.append(button('取消',closeCleanup),apply);
        head.append(el('strong','','清理旧备份'),button('关闭',closeCleanup));
        content.append(el('p','tbp-backup-description','保留最新的备份，永久删除其余旧备份。至少保留 1 份；清理范围仅限本功能创建的已完成备份。'),actions,summary,candidates,footer);
        view.append(head,content);document.body.append(view);view.addEventListener('cancel',event=>{event.preventDefault();closeCleanup();});
        keep.oninput=()=>{controller?.abort();plan=null;apply.disabled=true;candidates.replaceChildren();summary.textContent='保留数量已改变，请重新预览。';};
        cleanupDialog={close:closeCleanup};view.showModal();

        async function previewCleanup() {
            if(!keep.reportValidity()||applying)return;
            controller?.abort();const current=controller=new AbortController();
            plan=null;preview.disabled=keep.disabled=apply.disabled=true;summary.textContent='正在预览清理…';candidates.replaceChildren();
            try {
                const {data}=await json(ENDPOINT+'/cleanup/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keep_latest:Number(keep.value)}),signal:current.signal});
                if(dismissed||controller!==current)return;
                plan=data;
                summary.textContent=data.count?`将清理 ${data.count} 份旧备份，预计释放 ${size(data.size_bytes)}；保留最新 ${data.retained_count} 份。`:`没有可清理的旧备份，当前保留 ${data.retained_count} 份。`;
                for(const item of data.items) {
                    const row=el('div','tbp-backup-candidate');row.append(el('strong','',new Date(item.created_at).toLocaleString()),el('span','tbp-status',`${size(item.size_bytes)} · ${item.filename}`));candidates.append(row);
                }
                apply.disabled=!data.count;
            } catch(error) {
                if(!dismissed&&error.name!=='AbortError'&&controller===current)summary.textContent=`预览失败：${error.message}`;
            } finally {
                if(!dismissed&&controller===current)preview.disabled=keep.disabled=false;
            }
        }
        async function applyCleanup() {
            if(!plan?.count||applying)return;
            const token=plan.token;plan=null;applying=cleaning=true;apply.disabled=preview.disabled=keep.disabled=true;summary.textContent='正在清理旧备份…';updateActive();
            try {
                const {data}=await json(ENDPOINT+'/cleanup/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,confirmed:true})});
                if(closed)return;
                active=null;await load();
                status.textContent=`已清理 ${data.deleted_count} 份旧备份，释放 ${size(data.size_bytes)}，保留 ${data.retained_count} 份。`;
                if(data.errors.length) {
                    const message='部分文件未能清理：'+data.errors.map(item=>`${item.filename}：${item.error}`).join('；');
                    status.textContent+=message;
                    if(!dismissed){summary.textContent=message+' 请重新预览。';candidates.replaceChildren();}
                } else closeCleanup();
            } catch(error) {
                if(!closed)status.textContent=`清理失败：${error.message}`;
                if(!dismissed)summary.textContent=`清理失败：${error.message} 请重新预览。`;
            } finally {
                applying=cleaning=false;
                if(!dismissed)preview.disabled=keep.disabled=false;
                if(!closed)updateActive();
            }
        }
    }
    void load();
    return {close,dialog};
}
