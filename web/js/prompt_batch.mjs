import {PROMPTS_EVENT} from './prompt_actions.mjs';
import {ensureTagStyles} from './tag_picker.mjs';

export function attachPromptBatchPreview(node) {
    if (node.__toolboxBatchPreview) return;
    ensureTagStyles();
    node.__toolboxBatchPreview = true;
    const lifetime = new AbortController();
    const controls = document.createElement('div'); controls.className = 'tbp-batch-preview';
    const status = document.createElement('p'); status.setAttribute('role', 'status');
    status.textContent = '运行后显示匹配总数及本批提示词';
    const items = document.createElement('div'); items.className = 'tbp-batch-items';
    controls.append(status, items);
    let preview, executedKey;
    const inputNames = new Set(['language','media_type','prompt_type','safety','content_format','dynamic',
        'match_size','width','height','tags','sensitivity_level','nsfw','extreme','horror','gore','minor',
        'sensitivity_mode','sensitivity_levels','start_index','limit']);
    const key = () => JSON.stringify([
        (node.widgets || []).filter(widget => inputNames.has(widget.name)).map(widget => [widget.name,widget.value]),
        (node.inputs || []).map(input => [input.name,input.link]),
    ]);
    function refresh() {
        if (!preview) return;
        const pending = key() !== executedKey;
        controls.dataset.pending = String(pending);
        status.textContent = pending ? '参数已改变，预览待更新。运行节点获取新批次。' : preview.count
            ? `匹配 ${preview.total} 条 · 本批 ${preview.count} 条 · 索引 ${preview.start_index}–${preview.start_index + preview.count - 1}（从 0 开始）`
            : preview.total ? `匹配 ${preview.total} 条 · 起始索引 ${preview.start_index} 越界，本批 0 条`
                : '没有匹配的提示词 · 本批 0 条';
    }
    const executed = node.onExecuted;
    node.onExecuted = function(message) {
        const result = executed?.apply(this, arguments);
        const data = message?.toolbox_prompt_batch?.[0];
        if (data) {
            preview = data;
            const linked = new Set((node.inputs || []).filter(input => input.link != null).map(input => input.name));
            const matches = (node.widgets || []).filter(widget => inputNames.has(widget.name) && !linked.has(widget.name))
                .every(widget => data.inputs?.[widget.name] === widget.value);
            executedKey = matches ? key() : null;
            items.replaceChildren();
            for (const item of data.items) {
                const row = document.createElement('div');
                const id = document.createElement('strong'); id.textContent = `#${item.id}`;
                const text = document.createElement('pre'); text.textContent = item.prompt;
                row.append(id, text); items.append(row);
            }
            refresh(); node.setDirtyCanvas?.(true, true);
        }
        return result;
    };
    for (const name of ['onConfigure','onWidgetChanged','onConnectionsChange','onDrawForeground']) {
        const original = node[name];
        node[name] = function() { const result = original?.apply(this, arguments); refresh(); return result; };
    }
    const display = node.addDOMWidget('batch_preview', 'toolbox_batch_preview', controls, {
        serialize:false, hideOnZoom:false, getMinHeight:() => 220, getMaxHeight:() => 320,
    });
    if (display) { display.serialize = false; display.serializeValue = () => undefined; }
    window.addEventListener(PROMPTS_EVENT, () => {
        if (preview) { executedKey = null; refresh(); }
    }, {signal:lifetime.signal});
    const removed = node.onRemoved;
    node.onRemoved = function() { lifetime.abort(); return removed?.apply(this, arguments); };
    node.setSize?.([Math.max(node.size?.[0] || 0, 400), Math.max(node.size?.[1] || 0, node.computeSize?.()[1] || 400)]);
    return {controls};
}
