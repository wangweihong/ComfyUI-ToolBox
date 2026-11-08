import {marked} from 'marked';
import DOMPurify from 'dompurify';

export function renderMarkdown(source) {
    return DOMPurify.sanitize(marked.parse(source, {gfm: true, async: false}), {
        USE_PROFILES: {html: true},
        FORBID_TAGS: ['style', 'form', 'button', 'textarea', 'select', 'iframe', 'video', 'audio'],
        FORBID_ATTR: ['style', 'id', 'name'],
    });
}

export function attachMarkdownEditor(textarea, {label = '正文', preview = false} = {}) {
    const field = textarea.parentElement;
    const panel = document.createElement('section');
    panel.className = 'tbp-markdown-editor';
    panel.setAttribute('aria-label', label);
    const header = document.createElement('div'); header.className = 'tbp-markdown-header';
    const heading = document.createElement('strong'); heading.textContent = label;
    const tabs = document.createElement('div'); tabs.className = 'tbp-segmented';
    tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', `${label}显示方式`);
    const rendered = document.createElement('div'); rendered.className = 'tbp-markdown-preview';
    rendered.setAttribute('role', 'region'); rendered.setAttribute('aria-label', `${label} Markdown 预览`);
    rendered.tabIndex = 0;
    const choices = new Map();
    function show(mode) {
        const isPreview = mode === 'preview';
        field.hidden = isPreview; rendered.hidden = !isPreview;
        for (const [key, control] of choices) control.setAttribute('aria-pressed', String(key === mode));
        if (isPreview) {
            rendered.innerHTML = renderMarkdown(textarea.value);
            if (!textarea.value.trim()) rendered.textContent = '暂无正文';
            for (const link of rendered.querySelectorAll('a[href]')) {
                link.target = '_blank'; link.rel = 'noopener noreferrer';
            }
            for (const input of rendered.querySelectorAll('input')) {
                input.type = 'checkbox'; input.disabled = true;
            }
        }
    }
    for (const [mode, text] of [['edit', '编辑'], ['preview', '预览']]) {
        const control = document.createElement('button'); control.type = 'button'; control.textContent = text;
        control.onclick = () => show(mode); tabs.append(control); choices.set(mode, control);
    }
    header.append(heading, tabs); field.before(panel); panel.append(header, field, rendered);
    textarea.addEventListener('invalid', () => show('edit'));
    show(preview ? 'preview' : 'edit');
    return {element: panel};
}
