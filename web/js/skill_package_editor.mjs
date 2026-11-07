function element(tag, text, className = "") {
    const node = document.createElement(tag); node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function action(text, callback) {
    const node = element("button", text); node.type = "button"; node.onclick = callback; return node;
}

export function encodeText(text) {
    const bytes = new TextEncoder().encode(text); let raw = "";
    for (let index = 0; index < bytes.length; index += 32768) raw += String.fromCharCode(...bytes.subarray(index,index+32768));
    return btoa(raw);
}

export function decodeText(data) {
    try {
        const text = new TextDecoder("utf-8",{fatal:true,ignoreBOM:true}).decode(Uint8Array.from(atob(data),char=>char.charCodeAt(0)));
        return text.includes("\0") ? null : text;
    } catch { return null; }
}

export function retainLineEndings(value, original) {
    return original !== null && value === original.replace(/\r\n?/g,"\n") ? original : value;
}

export function preparePackage(initial) {
    const files=(initial.files || []).map(item=>({...item}));let primary=initial.primary_path || "", note="";
    if(files.length && !primary && initial.content) {
        const match=files.find(file=>decodeText(file.data)===initial.content);
        if(match) primary=match.path;
        else {
            primary="content.md";while(files.some(file=>file.path===primary)) primary="_"+primary;
            files.push({path:primary,data:encodeText(initial.content)});
        }
        note=`旧记录的独立正文已保留为 ${primary}，保存后统一使用文件包模式。`;
    }
    return {files,primary,note};
}

export function attachPackageEditor({parent, fields, initial, request, onDirty}) {
    const prepared=preparePackage(initial);
    let files=prepared.files,primary=prepared.primary,active=primary || files[0]?.path || "";
    let busy = false, destroyed = false, controller;
    const panel = element("section",undefined,"tbp-package"); panel.setAttribute("aria-label","Skill 文件包");
    panel.append(element("strong","文件包"),element("p","上传多文件、文件夹或 ZIP，保留相对目录；文件包模式不另填正文。最多 200 个文件，单文件 5 MiB，文件包合计 20 MiB，全库 200 MiB。同名路径上传会替换；保存后才写入数据库。","tbp-status"));
    if(prepared.note) panel.append(element("p",prepared.note,"tbp-status"));
    const toolbar = element("div",undefined,"tbp-package-actions");
    const input = element("input"); input.type="file"; input.multiple=true; input.hidden=true; input.setAttribute("aria-label","上传多个文件或 ZIP");
    const folder = element("input"); folder.type="file"; folder.multiple=true; folder.hidden=true; folder.setAttribute("webkitdirectory",""); folder.setAttribute("aria-label","上传文件夹");
    const upload = action("上传文件 / ZIP",()=>input.click()), directory = action("上传文件夹",()=>folder.click());
    toolbar.append(upload,directory,input,folder);
    if (initial.id > 0) {
        const download = element("a","下载已保存 ZIP","tbp-file-download");
        download.href=`/toolbox/skills/${initial.id}/download`; download.download=""; toolbar.append(download);
    }
    const status = element("p",undefined,"tbp-status"); status.setAttribute("role","status");
    const primaryLabel = element("label",undefined,"tbp-field"); primaryLabel.append(element("span","节点输出正文的文件"));
    const primarySelect = element("select"); primarySelect.setAttribute("aria-label","节点输出正文的文件"); primaryLabel.append(primarySelect);
    const summary = element("p",undefined,"tbp-status"), tree = element("div",undefined,"tbp-file-list"); tree.setAttribute("aria-label","文件列表");
    const viewer = element("div",undefined,"tbp-file-viewer");
    panel.append(toolbar,status,primaryLabel,summary,tree,viewer); parent.append(panel);
    const changed = () => { onDirty(); };

    function render() {
        primarySelect.replaceChildren();
        const independent = element("option","不输出正文（仅文件包）"); independent.value=""; primarySelect.append(independent);
        for (const file of files) if (decodeText(file.data) !== null) {
            const option = element("option",file.path); option.value=file.path; primarySelect.append(option);
        }
        primarySelect.value=primary;
        summary.textContent=files.length ? `${files.length} 个文件 · ${(files.reduce((n,file)=>n+atob(file.data).length,0)/1024).toFixed(1)} KiB` : "请上传至少一个文件，或切换到正文模式。";
        tree.replaceChildren();
        for (const file of files) {
            const row=element("div",undefined,"tbp-file-row");
            const select=action(`${file.path}${file.path===primary ? " · 正文" : ""}`,()=>{active=file.path;render();});
            select.className="tbp-file-path"; select.setAttribute("aria-pressed",String(active===file.path));
            select.title=file.path; select.setAttribute("aria-label",`查看文件 ${file.path}`);
            const remove=action("移除",()=>{
                files=files.filter(item=>item.path!==file.path);
                if(primary===file.path) primary="";
                if(active===file.path) active="";
                changed(); status.textContent="已从待保存文件包移除；保存后生效。";render();
            }); remove.setAttribute("aria-label",`移除文件 ${file.path}`);
            row.append(select,element("span",`${(atob(file.data).length/1024).toFixed(1)} KiB`,"tbp-file-size"),remove);tree.append(row);
        }
        renderViewer();
    }

    function renderViewer() {
        viewer.replaceChildren(); const file=files.find(item=>item.path===active); if(!file) return;
        viewer.append(element("strong",file.path));
        const text=decodeText(file.data);
        if(text===null) viewer.append(element("p","二进制或非 UTF-8 文件，保留原始字节，可下载。","tbp-status"));
        else {
            const editor=element("textarea",undefined,"tbp-skill-file-content"); editor.setAttribute("aria-label",`文件内容 ${file.path}`);
            editor.value=text; editor.spellcheck=false;
            editor.oninput=()=>{file.data=encodeText(retainLineEndings(editor.value,text));changed();};viewer.append(editor);
        }
        const download=action("下载此文件",()=>{
            const data=file.data;
            const blob=new Blob([Uint8Array.from(atob(data),char=>char.charCodeAt(0))],{type:"application/octet-stream"});
            const url=URL.createObjectURL(blob), link=element("a");link.href=url;link.download=file.path.split("/").pop();link.click();
            setTimeout(()=>URL.revokeObjectURL(url),1000);
        });viewer.append(download);
    }

    primarySelect.onchange=()=>{
        primary=primarySelect.value; active=primary || active;changed();render();
    };

    async function importFiles(source) {
        if(!source.files.length || busy) return;
        const chosen=[...source.files]; source.value="";
        if(chosen.length>200 || chosen.reduce((sum,file)=>sum+file.size,0)>21*1024*1024) {status.textContent="一次最多上传 200 个文件、21 MiB。";return;}
        busy=true;upload.disabled=directory.disabled=true;controller=new AbortController();status.textContent="正在读取文件包…";
        try {
            const body=new FormData();body.append("paths",JSON.stringify(chosen.map(file=>file.webkitRelativePath || file.name)));
            for(const file of chosen) body.append("file",file,file.name);
            const data=await request("/upload",{method:"POST",body,signal:controller.signal});
            if(destroyed) return;
            const next=new Map(files.map(file=>[file.path,file]));let replaced=0;
            for(const file of data.files) {if(next.has(file.path)) replaced++;next.set(file.path,file);}
            const merged=[...next.values()].sort((a,b)=>a.path.localeCompare(b.path));
            if(merged.length>200 || merged.reduce((sum,file)=>sum+atob(file.data).length,0)>20*1024*1024) throw new Error("合并后超过 200 个文件或 20 MiB，请先移除部分文件。");
            files=merged;
            if(primary && data.files.some(file=>file.path===primary)) {
                const text=decodeText(files.find(file=>file.path===primary).data);
                if(text===null) primary="";
            }
            if(!primary && data.primary_path) primary=data.primary_path;
            if(!fields.name.value.trim()) {
                const path=data.primary_path || files[0]?.path || chosen[0].name;
                fields.name.value=(path.includes("/") ? path.split("/")[0] : chosen[0].name.replace(/\.[^.]+$/,"")) || "新 Skill";
            }
            active=primary || data.files[0]?.path || "";changed();render();
            status.textContent=`已导入 ${data.files.length} 个文件${replaced ? `，替换 ${replaced} 个同名路径` : ""}；请保存内容。`;
        } catch(error) {if(!destroyed && error.name!=="AbortError") status.textContent=error.message;}
        finally {busy=false;if(!destroyed) upload.disabled=directory.disabled=false;}
    }
    input.onchange=()=>importFiles(input);folder.onchange=()=>importFiles(folder);render();
    return {
        isBusy:()=>busy,
        panel,
        snapshot:()=>({storage_mode:"files",files:files.map(file=>({path:file.path,data:file.data})),primary_path:primary,content:""}),
        destroy:()=>{destroyed=true;controller?.abort();},
    };
}
