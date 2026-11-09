import {openPromptBrowser} from './prompt_browser.mjs?v=20261109-example-delete';

export function addPromptReaderToCanvas(app, promptId, {createNode = name => globalThis.LiteGraph?.createNode(name)} = {}) {
    const id = Number(promptId);
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error('请选择已保存的提示词记录。');
    // app.graph is the root workflow; canvas.graph follows the active subgraph.
    const canvas = app.canvas, graph = canvas?.graph;
    if (!graph || canvas.read_only || canvas.allow_interaction === false) {
        throw new Error('当前没有可编辑画布，请返回工作流编辑界面后再试。');
    }
    const bounds = canvas.canvas?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0 || !canvas.convertCanvasToOffset) {
        throw new Error('当前画布尚未准备好，请稍后重试。');
    }
    const center = canvas.convertCanvasToOffset([bounds.width / 2, bounds.height / 2]);
    if (!center || !Number.isFinite(center[0]) || !Number.isFinite(center[1])) {
        throw new Error('无法确定当前画布位置，请稍后重试。');
    }
    const node = createNode('ToolBoxPromptReader');
    if (!node) throw new Error('tb-prompt-reader 尚未注册，请刷新页面后重试。');
    let changing = false;
    try {
        const widget = node.widgets?.find(item => item.name === 'id');
        if (!widget) throw new Error('tb-prompt-reader 缺少 ID 控件，请刷新页面后重试。');
        widget.value = id;
        node.title = 'tb-prompt-reader - 读取提示词库记录';
        node.pos = [center[0] - node.size[0] / 2, center[1] - node.size[1] / 2];
        graph.beforeChange();
        changing = true;
        graph.add(node);
        if (node.graph !== graph) throw new Error('无法将节点添加到当前画布。');
        widget.callback?.(id);
        canvas.selectNode(node, false);
        graph.change();
        node.setDirtyCanvas(true, true);
        return node;
    } catch (error) {
        if (node.graph === graph) graph.remove(node);
        else node.onRemoved?.();
        throw error;
    } finally {
        if (changing) graph.afterChange();
    }
}

export function createPromptLibraryToolbar({app, api, openBrowser = openPromptBrowser, createNode}) {
    let browser = null;
    return {
        icon: 'pi pi-book',
        label: '提示词库',
        tooltip: '打开提示词库：浏览、编辑并添加 reader 节点',
        onClick() {
            if (browser) return;
            browser = openBrowser({
                currentId: 0,
                request: (path, options) => api.fetchApi(`/toolbox/prompts${path}`, options),
                exampleRequest: (path, options) => api.fetchApi(path, options),
                onSelect: id => addPromptReaderToCanvas(app, id, {createNode}),
                onClose: () => { browser = null; },
            });
        },
    };
}
