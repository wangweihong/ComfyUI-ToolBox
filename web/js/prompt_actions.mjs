export const PROMPTS_EVENT = 'toolbox-prompts-changed';
export const SKILLS_EVENT = 'toolbox-skills-changed';

export function promptsChanged(detail) {
    window.dispatchEvent(new CustomEvent(PROMPTS_EVENT, {detail}));
}

function el(tag, text, className = '') {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function button(text, action, className = '') {
    const node = el('button', text, className);
    node.type = 'button'; node.onclick = action;
    return node;
}

export async function promptJSON(request, path, options = {}) {
    const response = await request(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || `请求失败：HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }
    return data;
}

export function confirmPromptDeletion({title, text, details, onConfirm, onClose = () => {}}) {
    const dialog = el('dialog', undefined, 'tb-prompts tbp-example-confirm');
    dialog.setAttribute('aria-label', title);
    dialog.append(el('h3', title), el('p', text), el('p', details, 'tbp-example-confirm-path'));
    const opener = document.activeElement;
    let closed = false;
    const close = () => {
        if (closed) return;
        closed = true; dialog.close(); dialog.remove();
        if (opener?.isConnected) opener.focus({preventScroll:true});
        onClose();
    };
    const cancel = button('取消操作', close);
    cancel.autofocus = true;
    const actions = el('div', undefined, 'tbp-actions');
    actions.append(cancel, button('确认删除', () => { if (closed) return; close(); onConfirm(); }, 'tbp-danger'));
    dialog.append(actions);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('close', close);
    document.body.append(dialog); dialog.showModal(); cancel.focus();
    return {dialog, close};
}

export function openPromptTagManager({request, onClose = () => {}}) {
    return openLibraryTagManager({request, onClose});
}

export function openLibraryTagManager({request, onClose = () => {}, title = '管理提示词标签',
    libraryLabel = '提示词库', entryLabel = '提示词', preservationText = '提示词及原始素材文件保留', eventName = PROMPTS_EVENT}) {
    const dialog = el('dialog', undefined, 'tb-prompts tbt-dialog tbp-tag-manager');
    dialog.setAttribute('aria-label', title);
    const lifetime = new AbortController();
    let closed = false, busy = false, catalog = [], controller, confirmation;
    const close = () => {
        if (closed) return;
        closed = true; controller?.abort(); lifetime.abort(); confirmation?.close();
        dialog.close(); dialog.remove(); onClose();
    };
    const header = el('header', undefined, 'tbp-header');
    header.append(el('strong', title), button('关闭', close));
    const body = el('div', undefined, 'tbt-body');
    const search = el('input'); search.type = 'search'; search.placeholder = '搜索标签名称';
    search.setAttribute('aria-label', '搜索管理标签');
    const status = el('p', '', 'tbp-status'); status.setAttribute('role', 'status');
    const list = el('div', undefined, 'tbp-tag-manager-list');
    const reload = button('刷新标签', () => load());
    body.append(search, reload, status, list); dialog.append(header, body);

    function render() {
        list.replaceChildren();
        for (const item of catalog.filter(item => item.name.toLowerCase().includes(search.value.trim().toLowerCase()))) {
            const row = el('div', undefined, 'tbp-tag-manager-row'); row.dataset.tag = item.name;
            row.append(el('span', item.name), el('span', `${item.count} 条${entryLabel}`, 'tbp-tag-count'));
            const remove = button('删除标签', () => {
                if (busy) return;
                confirmation = confirmPromptDeletion({title:'删除标签',
                    text:`从整个${libraryLabel}删除“${item.name}”？当前关联 ${item.count} 条${entryLabel}。`,
                    details:`将解除该标签的全部关联，${preservationText}。此操作无法撤销。`,
                    onClose:() => { confirmation = null; }, onConfirm:() => removeTag(item.name)});
            }, 'tbp-danger');
            remove.disabled = busy; row.append(remove); list.append(row);
        }
        reload.disabled = busy;
    }

    async function load() {
        if (closed) return;
        controller?.abort(); const current = controller = new AbortController();
        status.textContent = '正在加载全部标签…';
        try {
            const items = [];
            for (let page = 1, more = true; more; page++) {
                const data = await promptJSON(request, `/tags?page_size=500&page=${page}`, {signal:current.signal});
                if (closed || controller !== current) return;
                items.push(...data.items.map(name => ({name, count:data.counts[name] || 0})));
                more = data.has_more;
            }
            catalog = items; render(); status.textContent = `共 ${items.length} 个标签`;
        } catch (error) {
            if (!closed && error.name !== 'AbortError' && controller === current) status.textContent = error.message;
        }
    }

    async function removeTag(name) {
        if (busy || closed) return;
        busy = true; render(); status.textContent = '正在删除标签…';
        try {
            const data = await promptJSON(request, '/tags', {method:'DELETE',
                headers:{'Content-Type':'application/json'}, body:JSON.stringify({name})});
            window.dispatchEvent(new CustomEvent(eventName,{detail:{deleted_tags:data.deleted}}));
            if (closed) return;
            await load();
            status.textContent = `已删除标签“${name}”，解除 ${data.affected_count} 条关联。`;
        } catch (error) {
            if (!closed) status.textContent = error.message;
        } finally { busy = false; if (!closed) render(); }
    }
    search.oninput = render;
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    window.addEventListener(eventName, () => { if (!busy) load(); }, {signal:lifetime.signal});
    document.body.append(dialog); dialog.showModal(); load(); search.focus();
    return {dialog, close};
}
