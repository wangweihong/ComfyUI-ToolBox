import {attachPackageEditor} from "./skill_package_editor.mjs";
import {createTagField} from "./tag_picker.mjs";
const TYPES = { skill:"Skill", prompt_template:"提示词模板" };

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function button(text, action, className = "") {
    const node = el("button", className, text); node.type = "button"; node.onclick = action; return node;
}

function field(parent, label, name, value, choices = null, multiline = false) {
    const wrapper = el("label", "tbp-field"); wrapper.append(el("span", "", label));
    const input = el(choices ? "select" : multiline ? "textarea" : "input");
    input.name = name; input.setAttribute("aria-label", label);
    if (choices) for (const [key,text] of Object.entries(choices)) {
        const option = el("option", "", text); option.value = key; input.append(option);
    }
    input.value = value; wrapper.append(input); parent.append(wrapper); return input;
}

export function openSkillBrowser({ request, currentId, onSelect, onClose = () => {} }) {
    if (!document.querySelector("link[data-toolbox-prompts]")) {
        const css = el("link"); css.rel = "stylesheet";
        css.href = new URL("../css/prompt_reader.css", import.meta.url).href;
        css.dataset.toolboxPrompts = "true"; document.head.append(css);
    }
    const dialog = el("dialog", "tb-prompts tb-skill-library"); dialog.setAttribute("aria-label", "Skill 与提示词模板库");
    const detail = el("dialog", "tb-prompts tbp-detail-dialog tb-skill-detail"); detail.setAttribute("aria-label", "Skill/模板详情");
    const lifetime = new AbortController();
    let closed = false, dirty = false, saving = false, page = 1, pages = 1, kind = "全部";
    let selected = currentId > 0 ? {id:Number(currentId)} : null;
    let listRequest, detailRequest, tagsRequest, searchTimer, packageEditor, tagEditor;
    const selectedTags = new Set(); let allTags = [], counts = {};
    const discard = () => !dirty || window.confirm("有未保存的修改，放弃修改？");
    const close = (force = false) => {
        if (closed || (!force && (saving || !discard()))) return;
        closed = true; clearTimeout(searchTimer);
        packageEditor?.destroy();
        tagEditor?.destroy();
        lifetime.abort(); listRequest?.abort(); detailRequest?.abort(); tagsRequest?.abort();
        detail.close(); detail.remove(); dialog.close(); dialog.remove(); onClose();
    };
    const closeDetail = () => {
        if (saving || !discard()) return;
        detailRequest?.abort(); detailRequest = null;
        packageEditor?.destroy();
        tagEditor?.destroy();
        detail.close(); detail.replaceChildren(); dirty = false;
    };
    const header = el("header", "tbp-header");
    header.append(el("strong", "", "Skill / 提示词模板库"));
    const actions = el("div", "tbp-header-actions");
    actions.append(button("新增 Skill / 模板", () => openNew(), "tbp-primary"), button("关闭", () => close())); header.append(actions);
    const filters = el("form", "tbp-filters tbp-skill-filters");
    const search = field(filters, "搜索名称、简述或正文", "q", ""); search.placeholder = "输入关键词";
    const typeControls = el("div", "tbp-skill-types"); typeControls.append(el("span", "tbp-filter-hint", "类型"));
    const typeButtons = el("div", "tbp-segmented");
    for (const [key,label] of Object.entries({"全部":"全部", ...TYPES})) {
        const control = button(label, () => { kind = key; updateTypes(); page = 1; loadList(); });
        control.dataset.entryType = key; typeButtons.append(control);
    }
    typeControls.append(typeButtons); filters.append(typeControls);
    function updateTypes() {
        for (const control of typeButtons.children) control.setAttribute("aria-pressed", String(control.dataset.entryType === kind));
    }
    updateTypes();
    const tagPanel = el("details", "tbp-tag-picker"); tagPanel.open = true;
    const tagSummary = el("summary", "", "标签");
    const toolbar = el("div", "tbp-tag-toolbar");
    const tagSearch = el("input"); tagSearch.type = "search"; tagSearch.placeholder = "搜索标签名称"; tagSearch.setAttribute("aria-label", "搜索标签");
    const clear = button("清空已选", () => { selectedTags.clear(); renderTags(); page = 1; loadList(); });
    toolbar.append(tagSearch, clear);
    const chosen = el("div", "tbp-selected-tags"); chosen.setAttribute("aria-label", "已选标签");
    const tagStatus = el("p", "tbp-status"); tagStatus.setAttribute("role", "status");
    const cloud = el("div", "tbp-tag-cloud"); cloud.setAttribute("aria-label", "全部标签");
    tagPanel.append(tagSummary, toolbar, chosen, tagStatus, cloud); filters.append(tagPanel);
    const results = el("section", "tbp-results");
    const resultHeader = el("div", "tbp-result-heading");
    const summary = el("strong", "", "正在加载…");
    resultHeader.append(summary, button("刷新列表", () => { loadList(); loadTags(); }));
    const listStatus = el("p", "tbp-status"); listStatus.setAttribute("role", "status");
    const capacity = el("p","tbp-status tbp-storage");
    const cards = el("div", "tbp-cards");
    const pagination = el("nav", "tbp-pagination"); pagination.setAttribute("aria-label", "内容分页");
    const previous = button("上一页", () => { if (page > 1) { page--; loadList(); } });
    const next = button("下一页", () => { if (page < pages) { page++; loadList(); } });
    const pageLabel = el("span"); pagination.append(previous, pageLabel, next);
    results.append(resultHeader, capacity, listStatus, cards, pagination);
    const layout = el("div", "tbp-layout"); layout.append(results); dialog.append(header, filters, layout);

    async function fetchJSON(path, options = {}) {
        const response = await request(path, {...options, signal:options.signal ?? lifetime.signal});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.error || `请求失败：HTTP ${response.status}`); error.status = response.status; throw error;
        }
        return data;
    }

    function highlight() {
        for (const card of cards.children) card.setAttribute("aria-pressed", String(Number(card.dataset.id) === selected?.id));
    }

    async function loadList() {
        clearTimeout(searchTimer); if (closed) return;
        listRequest?.abort(); const controller = listRequest = new AbortController();
        const query = new URLSearchParams({q:search.value, entry_type:kind, tags:[...selectedTags].join(","), page:String(page), page_size:"50"});
        listStatus.textContent = "正在加载…"; previous.disabled = next.disabled = true;
        try {
            const data = await fetchJSON(`?${query}`, {signal:controller.signal});
            if (closed || listRequest !== controller) return;
            pages = Math.max(1, Math.ceil(data.total / data.page_size));
            if (page > pages) { page = pages; return loadList(); }
            summary.textContent = `${data.total.toLocaleString()} 条内容`; cards.replaceChildren();
            if(data.storage) capacity.textContent=`库容量 ${(data.storage.used_bytes/1048576).toFixed(2)} / ${(data.storage.max_library_bytes/1048576).toFixed(0)} MiB · 单文件最多 5 MiB · 每条正文或文件包最多 20 MiB`;
            for (const item of data.items) {
                const card = button("", () => loadDetail(item.id), "tbp-card tbp-skill-card"); card.dataset.id = String(item.id);
                const badges = el("div", "tbp-badges");
                badges.append(el("span", "tbp-meta-chip tbp-language", TYPES[item.entry_type]), el("span", "tbp-id", `#${item.id}`));
                if(item.file_count) badges.append(el("span","tbp-meta-chip tbp-media",`${item.file_count} 个文件`));
                card.append(badges, el("h3", "tbp-skill-name", item.name));
                if (item.description) card.append(el("p", "tbp-skill-description", item.description));
                card.append(el("p", "tbp-preview", item.preview));
                const chips = el("div", "tbp-tags");
                for (const tag of item.tags.slice(0,12)) chips.append(el("span", "tbp-prompt-tag", `# ${tag}`));
                if (item.tags.length > 12) chips.append(el("span", "", `+${item.tags.length-12}`));
                card.append(chips); cards.append(card);
            }
            highlight(); pageLabel.textContent = `${page} / ${pages}`;
            previous.disabled = page <= 1; next.disabled = page >= pages;
            listStatus.textContent = data.total ? "" : search.value || selectedTags.size || kind !== "全部"
                ? "没有匹配的内容，请调整筛选。" : "暂无内容，点击右上角“新增 Skill / 模板”开始添加。";
        } catch (error) {
            if (error.name !== "AbortError" && !closed && listRequest === controller) {
                cards.replaceChildren(); summary.textContent = "加载失败"; listStatus.textContent = error.message;
            }
        }
    }

    function toggleTag(tag) {
        selectedTags.has(tag) ? selectedTags.delete(tag) : selectedTags.add(tag);
        renderTags(); page = 1; loadList();
    }

    function renderTags() {
        tagSummary.textContent = `标签 ${allTags.length} · 已选 ${selectedTags.size}（多选时全部匹配）`;
        chosen.replaceChildren(); clear.disabled = !selectedTags.size; chosen.hidden = !selectedTags.size;
        for (const tag of selectedTags) {
            const remove = button(`${tag} ×`, () => toggleTag(tag), "tbp-selected-tag"); remove.setAttribute("aria-label", `移除标签 ${tag}`); chosen.append(remove);
        }
        cloud.replaceChildren();
        const visible = allTags.filter(tag => tag.toLowerCase().includes(tagSearch.value.trim().toLowerCase()));
        for (const tag of visible) {
            const control = button("", () => toggleTag(tag), "tbp-tag-option"); control.dataset.tag = tag;
            control.setAttribute("aria-pressed", String(selectedTags.has(tag)));
            control.append(el("span", "", tag), el("span", "tbp-tag-count", String(counts[tag] ?? 0))); cloud.append(control);
        }
        tagStatus.textContent = allTags.length ? visible.length ? "" : "没有匹配的标签" : "暂无标签，保存内容时可添加。";
    }

    async function loadTags() {
        tagsRequest?.abort(); const controller = tagsRequest = new AbortController();
        try {
            const names = [], usage = {}; let tagPage = 1, more = true;
            while (more) {
                const data = await fetchJSON(`/tags?page=${tagPage}&page_size=500`, {signal:controller.signal});
                if (closed || tagsRequest !== controller) return;
                names.push(...data.items); Object.assign(usage, data.counts); more = data.has_more; tagPage++;
            }
            allTags = [...new Set(names)]; counts = usage; renderTags();
        } catch (error) {
            if (error.name !== "AbortError" && !closed && tagsRequest === controller) tagStatus.textContent = error.message;
        }
    }

    async function loadDetail(id) {
        if (closed || saving || !discard()) return;
        detailRequest?.abort(); const controller = detailRequest = new AbortController();
        try {
            const data = await fetchJSON(`/${id}`, {signal:controller.signal});
            if (closed || detailRequest !== controller) return;
            selected = data; dirty = false; renderDetail(); highlight(); if (!detail.open) detail.showModal();
        } catch (error) {
            if (error.name !== "AbortError" && !closed && detailRequest === controller) {
                const status = detail.open ? detail.querySelector('[data-editor-status]') : listStatus;
                if (status) status.textContent = error.message;
            }
        }
    }

    function openNew() {
        if (closed || saving || !discard()) return;
        detailRequest?.abort(); detailRequest = null;
        selected = {id:0, name:"", entry_type:"skill", description:"", content:"", tags:[]};
        dirty = false; renderDetail(); highlight(); if (!detail.open) detail.showModal(); detail.querySelector('[name="name"]').focus();
    }

    function renderDetail() {
        packageEditor?.destroy();
        tagEditor?.destroy();
        const creating = selected.id === 0; detail.replaceChildren();
        const title = el("header", "tbp-header");
        title.append(el("h3", "", creating ? "新增 Skill / 模板" : `${TYPES[selected.entry_type]} #${selected.id}`), button("返回列表", closeDetail));
        const body = el("div", "tbp-detail-body");
        body.append(el("p", "tbp-meta", creating ? "每次新增都创建新记录；正文与文件原样保存，不执行脚本或替换变量。"
            : `SHA-1：${selected.shasum}\n创建：${selected.created_at}\n更新：${selected.updated_at}`));
        const editor = el("form", "tbp-editor");
        let storageMode=selected.files?.length ? "files" : "text";
        const grid = el("div", "tbp-editor-grid");
        const fields = {
            name:field(grid, "名称", "name", selected.name),
            entry_type:field(grid, "类型", "entry_type", selected.entry_type, TYPES),
        };
        fields.name.required = true; fields.name.maxLength = 200;
        fields.description = field(editor, "简述（可选）", "description", selected.description, null, true);
        fields.description.className = "tbp-skill-summary"; fields.description.maxLength = 20000;
        editor.prepend(grid);
        fields.content = field(editor, "正文（纯文本 / Markdown）", "content", selected.content, null, true);
        fields.content.className = "tbp-skill-content"; fields.content.required = true; fields.content.spellcheck = false;
        tagEditor=createTagField({parent:editor,value:selected.tags.join(", "),request,allowCreate:true});
        fields.tags=tagEditor.input;
        const status = el("p", "tbp-status"); status.setAttribute("role", "status"); status.dataset.editorStatus="true";
        packageEditor = attachPackageEditor({parent:editor, fields, initial:selected, request:fetchJSON,
            onDirty:()=>{dirty=true;status.textContent="有未保存的修改";}});
        const modeField=el("fieldset","tbp-content-modes");modeField.append(el("legend","","内容来源（二选一）"));
        const modeChoices=el("div","tbp-segmented");modeChoices.setAttribute("aria-label","内容来源");
        const modeHint=el("p","tbp-status");
        function showMode() {
            fields.content.parentElement.hidden=storageMode!=="text";
            fields.content.disabled=storageMode!=="text";fields.content.required=storageMode==="text";
            packageEditor.panel.hidden=storageMode!=="files";
            for(const choice of modeChoices.children) choice.setAttribute("aria-pressed",String(choice.dataset.storageMode===storageMode));
            modeHint.textContent=storageMode==="text" ? "直接填写正文。保存时只保留正文，不保存文件包。" : "只保存文件包。可选择其中一个文本文件作为节点正文输出，不另填独立正文。";
        }
        for(const [value,label] of [["text","正文"],["files","文件包"]]) {
            const choice=button(label,()=>{if(storageMode===value)return;storageMode=value;showMode();dirty=true;status.textContent="有未保存的修改；保存时只保留所选模式，另一种模式的内容将被替换。";});
            choice.dataset.storageMode=value;modeChoices.append(choice);
        }
        modeField.append(modeChoices,modeHint);grid.after(modeField);showMode();
        const actions = el("div", "tbp-actions");
        const save = button(creating ? "保存内容" : "保存修改", () => editor.requestSubmit(), "tbp-primary");
        const use = button("使用此内容", () => {
            if (!discard()) return;
            try {
                onSelect(selected.id, selected); close(true);
            } catch (error) {
                status.textContent = `无法使用此内容：${error.message || error}`;
            }
        }, "tbp-primary");
        use.disabled = creating; if (creating) use.title = "请先保存内容";
        actions.append(save); if (!creating) actions.append(button("重新加载详情", () => loadDetail(selected.id))); actions.append(use);
        editor.append(status, actions);
        editor.oninput = editor.onchange = () => { dirty = true; status.textContent = "有未保存的修改"; };
        editor.onsubmit = async event => {
            event.preventDefault(); if (saving || !editor.reportValidity()) return;
            if (storageMode==="files" && packageEditor.isBusy()) {status.textContent="文件正在上传，请完成后再保存。";return;}
            const packageData=storageMode==="files" ? packageEditor.snapshot() : {storage_mode:"text",files:[],primary_path:""};
            if(storageMode==="files" && !packageData.files.length) {status.textContent="文件包模式请至少上传一个文件。";return;}
            saving = true; detailRequest?.abort();
            const payload = creating ? {} : {version:selected.version};
            for (const [key,input] of Object.entries(fields)) payload[key] = input.value;
            Object.assign(payload,packageData);
            // Textareas normalize CRLF; retain the original bytes on unrelated edits.
            if (storageMode==="text" && !creating && payload.content === selected.content.replace(/\r\n?/g,"\n")) payload.content = selected.content;
            const controls = [...editor.querySelectorAll("input,select,textarea,button")].map(control => ({control,disabled:control.disabled}));
            controls.forEach(({control}) => { control.disabled = true; }); status.textContent = "正在保存…";
            try {
                const data = await fetchJSON(creating ? "" : `/${selected.id}`, {method:creating ? "POST" : "PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
                if (closed || !detail.open) return;
                selected = data; dirty = false; if (creating) page = 1; renderDetail();
                const notice = detail.querySelector('[data-editor-status]');
                notice.textContent = creating ? `已新增记录 #${data.id}，可直接使用。` : `已保存记录 #${data.id}`;
                if (creating) notice.dataset.writeAction = data.action;
                notice.scrollIntoView({block:"nearest"});
                await Promise.all([loadList(), loadTags()]);
                if (creating && !closed && detail.open && !cards.querySelector(`[data-id="${data.id}"]`)) notice.textContent += " 当前筛选下未显示，可直接使用或调整筛选。";
            } catch (error) {
                if (!closed && error.name !== "AbortError") status.textContent = error.status === 409
                    ? "记录已被修改。当前输入已保留，请复制需要的内容后重新加载详情。" : error.message;
            } finally { saving = false; controls.forEach(({control,disabled}) => { control.disabled = disabled; }); }
        };
        body.append(editor); detail.append(title, body);
    }

    filters.onsubmit = event => { event.preventDefault(); page = 1; loadList(); };
    search.oninput = () => { clearTimeout(searchTimer); page = 1; searchTimer = setTimeout(loadList,250); };
    tagSearch.oninput = () => renderTags();
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); }, {signal:lifetime.signal});
    dialog.addEventListener("click", event => { if (event.target === dialog) close(); }, {signal:lifetime.signal});
    detail.addEventListener("cancel", event => { event.preventDefault(); closeDetail(); }, {signal:lifetime.signal});
    detail.addEventListener("click", event => { if (event.target === detail) closeDetail(); }, {signal:lifetime.signal});
    document.body.append(dialog,detail); dialog.showModal(); loadList(); loadTags();
    return {dialog, close:() => close(true)};
}

export function attachSkillReader(node, app, api) {
    const id = node.widgets?.find(widget => widget.name === "id"); if (!id) return;
    let browser = null;
    const controls = el("div"); controls.style.cssText = "display:flex;align-items:center;width:100%;padding:4px;box-sizing:border-box";
    const browse = button("浏览 Skill / 模板库 · 搜索 / 编辑", () => {
        if (browser) return;
        browser = openSkillBrowser({currentId:Number(id.value), request:(path,options) => api.fetchApi(`/toolbox/skills${path}`,options),
            onSelect:value => { id.value=value; id.callback?.(value); node.setDirtyCanvas(true,true); app.graph.change(); },
            onClose:() => { browser=null; }});
    });
    browse.style.cssText = "width:100%;padding:8px;cursor:pointer;border-radius:6px"; controls.append(browse);
    node.addDOMWidget("skill_browser","toolbox_skill_browser",controls,{serialize:false,hideOnZoom:false,getMinHeight:()=>44,getMaxHeight:()=>44});
    const removed = node.onRemoved; node.onRemoved = function () { browser?.close(); removed?.apply(this,arguments); };
    node.setSize([Math.max(node.size?.[0] || 0,350),Math.max(node.size?.[1] || 0,120)]);
}
