import { SIZE_PRESETS, DEFAULT_SIZE, sizeFilter, sizeSelection } from "./prompt_sizes.mjs";
import {createTagField} from "./tag_picker.mjs";
import {createExamplesPanel,openExampleManager,EXAMPLES_EVENT} from "./prompt_examples.mjs";

const CATEGORY_LABELS = {
    nsfw: "NSFW", extreme: "重口味", horror: "恐怖", gore: "血腥", minor: "未成年",
};
const LEVELS = [
    "L0 安全",
    "L1 轻度性化：丝袜/腿部特写/恋物/紧身/短裙/透视；轻微恐怖氛围",
    "L2 性意味着装：内衣/内裤/比基尼/泳装；重口味（束缚捆绑未裸露）；中度血腥",
    "L3 裸露/性器官/性行为；触手/异种；肢解虐杀级血腥",
    "L4 未成年 + 任意性化内容",
];
const FILTERS = {
    language: ["语言", ["全部", "zh", "en"]],
    media_type: ["媒体", ["全部", "image", "video", "audio", "music"]],
    prompt_type: ["提示词类型", ["全部", "natural", "danbooru"]],
    content_format: ["格式", ["全部", "plaintext", "json"]],
    dynamic: ["动态性", ["全部", "dynamic", "static"]],
};

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function field(parent, label, name, choices, value = "") {
    const wrapper = element("label", "tbp-field");
    wrapper.append(element("span", "", label));
    const input = element(choices ? "select" : "input");
    input.name = name;
    input.setAttribute("aria-label", label);
    if (choices) {
        for (const choice of choices) {
            const [key, text] = Array.isArray(choice) ? choice : [choice, choice];
            const option = element("option", "", text);
            option.value = key;
            input.append(option);
        }
    }
    input.value = value;
    wrapper.append(input);
    parent.append(wrapper);
    return input;
}

function button(text, action, className = "") {
    const node = element("button", className, text);
    node.type = "button";
    node.onclick = action;
    return node;
}

export function openPromptBrowser({ request, currentId, onSelect, onClose = () => {}, initialExamples=false, exampleShasum=null, exampleRequest=(path,options)=>fetch(path,options), allowUse=true }) {
    if (!document.querySelector("link[data-toolbox-prompts]")) {
        const css = element("link");
        css.rel = "stylesheet";
        css.href = new URL("../css/prompt_reader.css", import.meta.url).href;
        css.dataset.toolboxPrompts = "true";
        document.head.append(css);
    }
    const dialog = element("dialog", "tb-prompts");
    dialog.setAttribute("aria-label", "提示词库");
    const detail = element("dialog", "tb-prompts tbp-detail-dialog");
    detail.setAttribute("aria-label", "提示词详情");
    const lifetime = new AbortController();
    let closed = false, dirty = false, saving = false, page = 1, pages = 1, selected = currentId > 0 ? { id: Number(currentId) } : null;
    let listingRequest, detailRequest, tagRequest, searchTimer, tagEditor, examplePanel, exampleManager;
    let examplesOpen=initialExamples,activeExampleShasum=exampleShasum;
    let levelMode = "all";
    const exactLevels = new Set([0]);
    const selectedTags = new Set();
    let allTags = [], tagCounts = {};
    const header = element("header", "tbp-header");
    const heading = element("div");
    heading.append(element("strong", "", "提示词库"), element("span", "tbp-subtitle", "浏览 · 筛选 · 编辑 · 使用"));
    const confirmDiscard = () => !dirty || window.confirm("有未保存的修改，放弃修改？");
    const close = (force = false) => {
        if (closed || (!force && !confirmDiscard())) return;
        closed = true;
        tagEditor?.destroy();
        examplePanel?.destroy();exampleManager?.close();
        clearTimeout(searchTimer);
        lifetime.abort(); listingRequest?.abort(); detailRequest?.abort(); tagRequest?.abort();
        detail.close(); detail.remove(); dialog.close(); dialog.remove(); onClose();
    };
    const closeDetail = (force = false) => {
        if (!force && (saving || !confirmDiscard())) return;
        detailRequest?.abort(); detailRequest = null;
        tagEditor?.destroy();
        examplePanel?.destroy();
        detail.close(); detail.replaceChildren(); dirty = false;
    };
    const headerActions = element("div", "tbp-header-actions");
    headerActions.append(button("示例素材管理",()=>{if(!exampleManager)exampleManager=openExampleManager({request:exampleRequest,onChanged:()=>loadList(),onClose:()=>{exampleManager=null;}});}));
    headerActions.append(button("新增提示词", () => openNewPrompt(), "tbp-primary"), button("关闭", () => close()));
    header.append(heading, headerActions);
    const filters = element("form", "tbp-filters");
    const q = field(filters, "搜索正文", "q");
    q.placeholder = "输入关键词搜索";
    const levelGroup = element("fieldset", "tbp-level-filter");
    levelGroup.append(element("legend", "", "敏感等级"));
    const levelModes = element("div", "tbp-segmented");
    const modeButtons = new Map();
    for (const [mode, label] of [["all", "不限"], ["exact", "指定级别"], ["max", "等级及以下"]]) {
        const control = button(label, () => { levelMode = mode; updateLevelControls(); page = 1; loadList(); });
        control.dataset.levelMode = mode; modeButtons.set(mode, control); levelModes.append(control);
    }
    const levelChoices = element("div", "tbp-level-choices");
    const levelButtons = [];
    for (let level = 0; level <= 4; level++) {
        const control = button(`L${level}`, () => {
            exactLevels.has(level) ? exactLevels.delete(level) : exactLevels.add(level);
            updateLevelControls(); page = 1; loadList();
        }, "tbp-level-choice");
        control.dataset.level = String(level); control.title = LEVELS[level];
        levelButtons.push(control); levelChoices.append(control);
    }
    levelGroup.append(levelModes, levelChoices);
    const maxLevel = field(levelGroup, "最高等级（含）", "sensitivity_level",
        LEVELS.map((label, level) => [`L${level}`, `L${level} 及以下`]), "L2");
    maxLevel.title = LEVELS.join("\n");
    const levelHint = element("small", "tbp-filter-hint"); levelHint.setAttribute("aria-live", "polite");
    levelGroup.append(levelHint); filters.append(levelGroup);
    function updateLevelControls() {
        for (const [mode, control] of modeButtons) control.setAttribute("aria-pressed", String(mode === levelMode));
        levelChoices.hidden = levelMode !== "exact";
        maxLevel.disabled = levelMode !== "max";
        maxLevel.closest("label").hidden = levelMode !== "max";
        for (let level = 0; level <= 4; level++) levelButtons[level].setAttribute("aria-pressed", String(exactLevels.has(level)));
        levelHint.textContent = levelMode === "all" ? "包含 L0–L4" : levelMode === "max"
            ? `包含 L0–${maxLevel.value}` : exactLevels.size
                ? `仅匹配 ${[...exactLevels].sort().map(level => `L${level}`).join("、")}` : "请选择至少一个级别";
    }
    updateLevelControls();
    const tagPanel = element("details", "tbp-tag-picker"); tagPanel.open = true;
    const tagSummary = element("summary");
    const tagTitle = element("strong", "", "标签");
    const tagDescription = element("span", "tbp-filter-hint", "多选时全部匹配");
    tagSummary.append(tagTitle, tagDescription);
    const tagToolbar = element("div", "tbp-tag-toolbar");
    const tagSearch = element("input"); tagSearch.type = "search";
    tagSearch.placeholder = "搜索标签名称"; tagSearch.setAttribute("aria-label", "搜索标签");
    const clearTags = button("清空已选", () => { selectedTags.clear(); renderTagPicker(); page = 1; loadList(); });
    tagToolbar.append(tagSearch, clearTags);
    const selectedTagChips = element("div", "tbp-selected-tags");
    selectedTagChips.setAttribute("aria-label", "已选标签");
    const tagStatus = element("p", "tbp-status", "正在加载全部标签…"); tagStatus.setAttribute("role", "status");
    const tagCloud = element("div", "tbp-tag-cloud"); tagCloud.setAttribute("aria-label", "全部标签");
    tagPanel.append(tagSummary, tagToolbar, selectedTagChips, tagStatus, tagCloud);
    const normalizeTag = value => value.trim().toLowerCase();
    function toggleTag(value) {
        const name = normalizeTag(value);
        selectedTags.has(name) ? selectedTags.delete(name) : selectedTags.add(name);
        renderTagPicker(); page = 1; loadList();
    }
    function renderTagPicker() {
        tagTitle.textContent = `标签 ${allTags.length} · 已选 ${selectedTags.size}`;
        clearTags.disabled = selectedTags.size === 0;
        selectedTagChips.replaceChildren();
        for (const name of selectedTags) {
            const label = allTags.find(tag => normalizeTag(tag) === name) || name;
            const remove = button(`${label} ×`, () => toggleTag(name), "tbp-selected-tag");
            remove.setAttribute("aria-label", `移除标签 ${label}`); selectedTagChips.append(remove);
        }
        selectedTagChips.hidden = selectedTags.size === 0;
        const search = normalizeTag(tagSearch.value);
        const visible = allTags.filter(tag => normalizeTag(tag).includes(search));
        tagCloud.replaceChildren();
        for (const tag of visible) {
            const control = button("", () => toggleTag(tag), "tbp-tag-option");
            control.dataset.tag = tag; control.setAttribute("aria-pressed", String(selectedTags.has(normalizeTag(tag))));
            control.append(element("span", "", tag), element("span", "tbp-tag-count", String(tagCounts[tag] ?? 0)));
            tagCloud.append(control);
        }
        if (allTags.length) tagStatus.textContent = visible.length ? "" : "没有匹配的标签";
    }
    async function loadTags() {
        tagRequest?.abort(); const controller = tagRequest = new AbortController();
        const collected = [], counts = {};
        try {
            let tagPage = 1, more = true;
            while (more) {
                const data = await fetchJSON(`/tags?page_size=500&page=${tagPage}`, { signal: controller.signal });
                if (closed || tagRequest !== controller) return;
                collected.push(...data.items); Object.assign(counts, data.counts);
                more = Boolean(data.has_more); tagPage++;
            }
            allTags = [...new Set(collected)]; tagCounts = counts;
            tagStatus.textContent = allTags.length ? "" : "暂无标签";
            renderTagPicker();
        } catch (error) {
            if (error.name !== "AbortError" && !closed && tagRequest === controller) tagStatus.textContent = error.message;
        }
    }
    tagSearch.oninput = event => { event.stopPropagation(); renderTagPicker(); };
    tagSearch.onchange = event => event.stopPropagation();

    const commonFilters = element("div", "tbp-common-filters");
    for (const [key, [label, choices]] of Object.entries(FILTERS)) field(commonFilters, label, key, choices, "全部");
    for (const [key, label] of Object.entries(CATEGORY_LABELS)) field(commonFilters, label, key, ["全部", "是", "否"], "全部");
    filters.append(commonFilters);
    const sizeControls = element("div", "tbp-size-filter");
    const matchSize = field(sizeControls, "匹配宽高", "match_size");
    matchSize.type = "checkbox";
    const sizeRatio = field(sizeControls, "画面比例", "size_ratio",
        [...Object.keys(SIZE_PRESETS).map(ratio => [ratio, ratio]), ["custom", "自定义"]], DEFAULT_SIZE.ratio);
    const pixelSize = field(sizeControls, "像素尺寸", "size_resolution", [], "");
    const width = field(sizeControls, "自定义宽度", "width", null, "1024");
    const height = field(sizeControls, "自定义高度", "height", null, "768");
    for (const input of [width, height]) {
        input.type = "number"; input.min = "1"; input.max = "16384"; input.step = "1"; input.required = true;
    }
    const sizeHint = element("small", "tbp-filter-hint", "按库中建议像素精确匹配");
    function updateSizeControls(rebuild = false) {
        const custom = sizeRatio.value === "custom";
        if (!custom && rebuild) {
            const previous = `${width.value}x${height.value}`;
            const sizes = SIZE_PRESETS[sizeRatio.value];
            pixelSize.replaceChildren(...sizes.map(pair => {
                const option = element("option", "", `${pair[0]} × ${pair[1]}`);
                option.value = pair.join("x"); return option;
            }));
            pixelSize.value = sizes.some(pair => pair.join("x") === previous) ? previous : sizes[0].join("x");
        }
        if (!custom) {
            const pair = pixelSize.value.split("x");
            width.value = pair[0]; height.value = pair[1];
        }
        sizeRatio.disabled = !matchSize.checked;
        pixelSize.disabled = !matchSize.checked || custom;
        pixelSize.closest("label").hidden = custom;
        for (const input of [width, height]) {
            input.closest("label").hidden = !custom;
            input.disabled = !matchSize.checked || !custom;
        }
    }
    updateSizeControls(true);
    const reset = button("重置筛选", () => {
        for (const input of commonFilters.querySelectorAll("select")) input.value = "全部";
        levelMode = "all"; maxLevel.value = "L2"; exactLevels.clear(); exactLevels.add(0); updateLevelControls();
        selectedTags.clear(); tagSearch.value = ""; renderTagPicker();
        q.value = ""; matchSize.checked = false;
        width.value = "1024"; height.value = "768"; sizeRatio.value = DEFAULT_SIZE.ratio; updateSizeControls(true);
        sort.value = "updated_desc";
        page = 1; loadList();
    });
    sizeControls.append(sizeHint, reset);
    filters.append(sizeControls, tagPanel);
    const layout = element("div", "tbp-layout");
    const results = element("section", "tbp-results");
    const resultHeading = element("div", "tbp-result-heading");
    const summary = element("strong", "", "正在加载…");
    const refresh = button("刷新列表", () => loadList());
    const listTools = element("div", "tbp-list-tools");
    const sort = field(listTools, "排序", "sort", [
        ["updated_desc", "最近更新优先"], ["updated_asc", "最早更新优先"],
        ["id_desc", "ID 从大到小"], ["id_asc", "ID 从小到大"],
    ], "updated_desc");
    sort.onchange = () => { page = 1; loadList(); };
    listTools.append(refresh);
    resultHeading.append(summary, listTools);
    const listStatus = element("p", "tbp-status");
    listStatus.setAttribute("role", "status");
    const cards = element("div", "tbp-cards");
    const pagination = element("nav", "tbp-pagination");
    pagination.setAttribute("aria-label", "提示词分页");
    const previous = button("上一页", () => { if (page > 1) { page--; loadList(); } });
    const pageLabel = element("span");
    const next = button("下一页", () => { if (page < pages) { page++; loadList(); } });
    pagination.append(previous, pageLabel, next);
    results.append(resultHeading, listStatus, cards, pagination);
    layout.append(results);
    dialog.append(header, filters, layout);

    async function fetchJSON(path, options = {}) {
        const response = await request(path, { ...options, signal: options.signal ?? lifetime.signal });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.error || `请求失败：HTTP ${response.status}`);
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function selectCards() {
        for (const card of cards.children) card.setAttribute("aria-pressed", String(Number(card.dataset.id) === selected?.id));
    }

    async function loadList() {
        clearTimeout(searchTimer);
        if (!filters.reportValidity() || closed) return;
        listingRequest?.abort();
        const controller = listingRequest = new AbortController();
        const query = new URLSearchParams(new FormData(filters));
        query.set("sensitivity_mode", levelMode === "exact" ? "exact" : "max");
        query.set("sensitivity_level", levelMode === "max" ? maxLevel.value : "全部");
        query.set("sensitivity_levels", levelMode === "exact" ? [...exactLevels].sort().map(level => `L${level}`).join(",") : "");
        query.set("tags", [...selectedTags].join(","));
        query.delete("size_ratio"); query.delete("size_resolution");
        const dimensions = sizeFilter({ enabled:matchSize.checked, ratio:sizeRatio.value,
            resolution:pixelSize.value, width:width.value, height:height.value });
        query.set("match_size", String(dimensions.match_size));
        query.set("width", String(dimensions.width)); query.set("height", String(dimensions.height));
        query.set("page", String(page)); query.set("page_size", "50");
        query.set("sort", sort.value);
        listStatus.textContent = "正在加载…";
        previous.disabled = next.disabled = true;
        try {
            const data = await fetchJSON(`?${query}`, { signal: controller.signal });
            if (closed || listingRequest !== controller) return;
            pages = Math.max(1, Math.ceil(data.total / data.page_size));
            if (page > pages) { page = pages; return loadList(); }
            cards.replaceChildren();
            summary.textContent = `${data.total.toLocaleString()} 条提示词`;
            for (const item of data.items) {
                const card = button("", event => loadDetail(item.id,Boolean(event.target.closest('[data-example-count]'))), "tbp-card");
                card.dataset.id = String(item.id);
                const badges = element("div", "tbp-badges");
                const levelBadge = element("span", "tbp-level", `L${item.sensitivity_level}`);
                levelBadge.dataset.level = String(item.sensitivity_level); levelBadge.title = LEVELS[item.sensitivity_level];
                badges.append(levelBadge, element("span", "tbp-id", `#${item.id}`),
                    element("span", "tbp-meta-chip tbp-language", {zh:"中文",en:"English"}[item.language] || item.language),
                    element("span", "tbp-meta-chip tbp-media", {image:"图像",video:"视频",audio:"音频",music:"音乐"}[item.media_type] || item.media_type));
                const examplesBadge=element('span','tbp-meta-chip tbp-example-count',`示例素材 ${item.example_count||0} 个`);examplesBadge.dataset.exampleCount='true';badges.append(examplesBadge);
                const preview = element("p", "tbp-preview", item.preview);
                const chips = element("div", "tbp-tags");
                for (const [key, label] of Object.entries(CATEGORY_LABELS)) if (item[key]) chips.append(element("span", "tbp-category", label));
                for (const tag of item.tags.slice(0, 12)) chips.append(element("span", "tbp-prompt-tag", `# ${tag}`));
                if (item.tags.length > 12) chips.append(element("span", "", `+${item.tags.length - 12}`));
                const updated = element("time", "tbp-updated");
                if (item.updated_at) {
                    updated.dateTime = item.updated_at;
                    const date = new Date(item.updated_at);
                    updated.textContent = `更新于 ${Number.isNaN(date.getTime()) ? item.updated_at : date.toLocaleString()}`;
                    updated.title = item.updated_at;
                }
                card.append(badges, preview, chips, updated); cards.append(card);
            }
            selectCards();
            listStatus.textContent = data.total ? "" : "没有匹配的提示词，请调整筛选。";
            pageLabel.textContent = `${page} / ${pages}`;
            previous.disabled = page <= 1; next.disabled = page >= pages;
        } catch (error) {
            if (error.name !== "AbortError" && !closed && listingRequest === controller) {
                cards.replaceChildren(); summary.textContent = "加载失败";
                listStatus.textContent = error.message;
            }
        }
    }

    async function loadDetail(id, showExamples = false, shasum=null) {
        if (closed || saving || !confirmDiscard()) return;
        detailRequest?.abort();
        const controller = detailRequest = new AbortController();
        // Keep a dirty form intact if reloading fails.
        try {
            const record = await fetchJSON(`/${id}`, { signal: controller.signal });
            if (closed || detailRequest !== controller) return;
            selected = record; dirty = false; examplesOpen=showExamples;activeExampleShasum=shasum;renderDetail(); selectCards();
            if (!detail.open) detail.showModal();
        } catch (error) {
            if (error.name !== "AbortError" && !closed && detailRequest === controller) {
                const status = detail.open ? detail.querySelector('[role="status"]') : listStatus;
                if (status) status.textContent = error.message;
            }
        }
    }

    function openNewPrompt() {
        if (closed || saving || !confirmDiscard()) return;
        detailRequest?.abort(); detailRequest = null;
        selected = {
            id:0, prompt:"", language:"zh", media_type:"image", prompt_type:"natural",
            content_format:"plaintext", sensitivity_level:0, width:1024, height:768, tags:[],
            nsfw:false, extreme:false, horror:false, gore:false, minor:false, dynamic:false,
        };
        dirty = false;examplesOpen=false;activeExampleShasum=null;renderDetail(); selectCards();
        if (!detail.open) detail.showModal();
        detail.querySelector("textarea").focus();
    }

    function renderDetail() {
        tagEditor?.destroy();
        examplePanel?.destroy();examplePanel=null;
        const creating = selected.id === 0;
        detail.replaceChildren();
        const detailHeader = element("header", "tbp-header");
        const title = element("h3", "", creating ? "新增提示词" : `提示词 #${selected.id}`);
        detailHeader.append(title, button("返回列表", () => closeDetail()));
        const body = element("div", "tbp-detail-body");
        const info = element("p", "tbp-meta", creating ? "填写提示词和元数据，保存后即可用于工作流。"
            : `SHA-1：${selected.shasum}\n更新时间：${selected.created_at}`);
        const editor = element("form", "tbp-editor");
        const promptLabel = element("label", "tbp-field");
        promptLabel.append(element("span", "", "提示词正文"));
        const prompt = element("textarea");
        prompt.name = "prompt"; prompt.setAttribute("aria-label", "提示词正文"); prompt.value = selected.prompt; prompt.required = true;
        promptLabel.append(prompt); editor.append(promptLabel);
        const grid = element("div", "tbp-editor-grid");
        const fields = { prompt };
        for (const key of ["language", "media_type", "prompt_type", "content_format"]) {
            const [label, choices] = FILTERS[key];
            fields[key] = field(grid, label, key, choices.slice(1), selected[key]);
        }
        fields.sensitivity_level = field(grid, "敏感等级（手动标注）", "sensitivity_level",
            LEVELS.map((label, level) => [String(level), `L${level}`]), String(selected.sensitivity_level));
        fields.sensitivity_level.title = LEVELS.join("\n");
        tagEditor=createTagField({parent:grid,value:selected.tags.join(", "),request,allowCreate:true});
        fields.tags=tagEditor.input;
        const editSizes = element("div", "tbp-editor-sizes");
        const initialSize = sizeSelection(selected.width, selected.height);
        const rememberedSizes = new Map([[initialSize.ratio, initialSize.resolution]]);
        const editRatio = field(editSizes, "画面比例", "edit_ratio",
            [...Object.keys(SIZE_PRESETS).map(ratio => [ratio, ratio]), ["custom", "自定义"]], initialSize.ratio);
        const editPixels = field(editSizes, "像素尺寸", "edit_resolution", [], "");
        for (const key of ["width", "height"]) {
            fields[key] = field(editSizes, key === "width" ? "自定义宽度" : "自定义高度", key, null, String(selected[key]));
            fields[key].type = "number"; fields[key].min = "1"; fields[key].max = "16384"; fields[key].required = true;
        }
        function updateEditSize(rebuild = false) {
            const custom = editRatio.value === "custom";
            if (!custom && rebuild) {
                const sizes = SIZE_PRESETS[editRatio.value].map(pair => pair.join("x"));
                const previous = rememberedSizes.get(editRatio.value);
                if (previous && !sizes.includes(previous)) sizes.push(previous);
                editPixels.replaceChildren(...sizes.map(value => {
                    const option = element("option", "", value.replace("x", " × "));
                    option.value = value; return option;
                }));
                editPixels.value = previous || sizes[0];
            }
            if (!custom) {
                const pair = editPixels.value.split("x");
                fields.width.value = pair[0]; fields.height.value = pair[1];
                rememberedSizes.set(editRatio.value, editPixels.value);
            }
            editSizes.dataset.custom = String(custom);
            editPixels.closest("label").hidden = custom; editPixels.disabled = custom;
            for (const key of ["width", "height"]) {
                fields[key].closest("label").hidden = !custom;
                fields[key].disabled = !custom;
            }
        }
        updateEditSize(true);
        editRatio.oninput = editRatio.onchange = () => updateEditSize(true);
        editPixels.oninput = editPixels.onchange = () => updateEditSize();
        grid.append(editSizes);
        const checks = element("div", "tbp-checks");
        for (const [key, label] of Object.entries({ ...CATEGORY_LABELS, dynamic: "动态提示词" })) {
            fields[key] = field(checks, label, key);
            fields[key].type = "checkbox"; fields[key].checked = Boolean(selected[key]);
        }
        const legend = element("details", "tbp-legend");
        legend.append(element("summary", "", "查看分级说明"));
        for (const description of LEVELS) legend.append(element("p", "", description));
        const status = element("p", "tbp-status");
        status.setAttribute("role", "status");
        const actions = element("div", "tbp-actions");
        const save = button(creating ? "保存提示词" : "保存修改", () => editor.requestSubmit(), "tbp-primary");
        const reload = button("重新加载详情", () => loadDetail(selected.id));
        const use = button("使用此提示词", () => {
            if (!confirmDiscard()) return;
            onSelect(selected.id, selected); close(true);
        }, "tbp-primary");
        use.disabled = creating;
        use.hidden=!allowUse;
        if (creating) use.title = "请先保存提示词";
        actions.append(save);
        if (!creating) actions.append(reload);
        actions.append(use);
        editor.append(grid, checks, legend, status, actions);
        editor.oninput = () => { dirty = true; status.textContent = "有未保存的修改"; };
        editor.onchange = editor.oninput;
        editor.onsubmit = async event => {
            event.preventDefault();
            if (saving || !editor.reportValidity()) return;
            saving = true; detailRequest?.abort();
            const payload = creating ? {} : { version: selected.version };
            for (const [key, input] of Object.entries(fields)) {
                payload[key] = input.type === "checkbox" ? input.checked :
                    ["width", "height", "sensitivity_level"].includes(key) ? Number(input.value) : input.value;
            }
            // Disable the whole form so in-flight saves cannot erase later edits.
            const controls = [...editor.querySelectorAll("input,select,textarea,button")]
                .map(control => ({ control, disabled:control.disabled }));
            controls.forEach(({control}) => { control.disabled = true; });
            status.textContent = creating ? "正在新增…" : "正在保存…";
            try {
                const result = await fetchJSON(creating ? "" : `/${selected.id}`, {
                    method: creating ? "POST" : "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
                });
                if (closed || !detail.open) return;
                selected = result; dirty = false; renderDetail();
                window.dispatchEvent(new CustomEvent(EXAMPLES_EVENT,{detail:{prompt_ids:[result.id]}}));
                if (creating) page = 1;
                const notice = detail.querySelector('[role="status"]');
                notice.textContent = creating ? result.action === "updated"
                    ? `相同正文已存在，已更新记录 #${result.id}。`
                    : `已新增记录 #${result.id}，可直接使用此提示词。` : "已保存";
                if (creating) {
                    notice.dataset.writeAction = result.action;
                    notice.scrollIntoView({ block:"nearest" });
                }
                await Promise.all([loadList(), loadTags()]);
                if (creating && !closed && detail.open && !cards.querySelector(`[data-id="${result.id}"]`)) {
                    notice.textContent += " 当前筛选下未显示该记录，可直接使用或调整筛选。";
                }
            } catch (error) {
                if (!closed && error.name !== "AbortError") status.textContent = error.status === 409
                    ? "记录已被修改。当前输入已保留，请复制需要的内容后重新加载详情。" : error.message;
            } finally { saving = false; controls.forEach(({control,disabled}) => { control.disabled = disabled; }); }
        };
        const editPane=element('div');editPane.append(info,editor);
        const tabs=element('div','tbp-example-toolbar');
        const editTab=button('编辑提示词',()=>showPane(false)),examplesTab=button('示例素材',()=>showPane(true));examplesTab.disabled=creating;
        tabs.append(editTab,examplesTab);body.append(tabs,editPane);
        if(!creating)examplePanel=createExamplesPanel({parent:body,record:selected,initialShasum:activeExampleShasum,request:exampleRequest,canAdd:()=>!dirty&&!saving,onChanged:()=>loadList()});
        function showPane(show){
            examplesOpen=show&&!creating;editPane.hidden=examplesOpen;editTab.setAttribute('aria-pressed',String(!examplesOpen));examplesTab.setAttribute('aria-pressed',String(examplesOpen));
            if(examplePanel){examplePanel.container.hidden=!examplesOpen;if(examplesOpen)examplePanel.load();else for(const video of examplePanel.container.querySelectorAll('video'))video.pause();}
        }
        showPane(examplesOpen);
        detail.append(detailHeader, body);
    }

    filters.onsubmit = event => { event.preventDefault(); page = 1; loadList(); };
    filters.oninput = event => {
        clearTimeout(searchTimer); page = 1;
        if ([matchSize, sizeRatio, pixelSize].includes(event.target)) updateSizeControls(event.target === sizeRatio);
        searchTimer = setTimeout(loadList, 250);
    };
    filters.onchange = event => {
        clearTimeout(searchTimer); updateLevelControls();
        if ([matchSize, sizeRatio, pixelSize].includes(event.target)) updateSizeControls(event.target === sizeRatio);
        page = 1; loadList();
    };
    dialog.addEventListener("cancel", event => { event.preventDefault(); close(); }, { signal: lifetime.signal });
    dialog.addEventListener("click", event => { if (event.target === dialog) close(); }, { signal: lifetime.signal });
    detail.addEventListener("cancel", event => { event.preventDefault(); closeDetail(); }, { signal: lifetime.signal });
    detail.addEventListener("click", event => { if (event.target === detail) closeDetail(); }, { signal: lifetime.signal });
    window.addEventListener(EXAMPLES_EVENT,()=>loadList(),{signal:lifetime.signal});
    document.body.append(dialog, detail); dialog.showModal();
    loadList(); loadTags();
    if(initialExamples&&currentId>0)loadDetail(currentId,true,exampleShasum);
    return { close: () => close(true), dialog };
}

export function attachPromptReader(node, app, api) {
    const id = node.widgets?.find(widget => widget.name === "id");
    if (!id) return;
    let browser = null;
    const controls = element("div", "tbp-node-controls");
    controls.style.cssText = "display:flex;align-items:center;width:100%;padding:4px;box-sizing:border-box";
    const browse = button("浏览提示词库 · 筛选 / 详情 / 编辑", () => {
        if (browser) return;
        browser = openPromptBrowser({
            currentId: Number(id.value), request: (path, options) => api.fetchApi(`/toolbox/prompts${path}`, options),
            exampleRequest:(path,options)=>api.fetchApi(path,options),
            onSelect: value => {
                id.value = value; id.callback?.(value); node.setDirtyCanvas(true, true); app.graph.change();
            },
            onClose: () => { browser = null; },
        });
    });
    browse.style.cssText = "width:100%;padding:8px;cursor:pointer;border-radius:6px";
    controls.append(browse);
    node.addDOMWidget("prompt_browser", "toolbox_prompt_browser", controls, {
        serialize: false, hideOnZoom: false, getMinHeight: () => 44, getMaxHeight: () => 44,
    });
    const removed = node.onRemoved;
    node.onRemoved = function () { browser?.close(); removed?.apply(this, arguments); };
    node.setSize([Math.max(node.size?.[0] || 0, 340), Math.max(node.size?.[1] || 0, 120)]);
}
