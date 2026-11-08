import {openSkillBrowser} from './skill_browser.mjs';

export function addSkillReaderToCanvas(app, skillId, {createNode = name => globalThis.LiteGraph?.createNode(name)} = {}) {
    const id = Number(skillId);
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error('请选择已保存的 Skill 或提示词模板。');
    const canvas = app.canvas, graph = canvas?.graph;
    if (!graph || canvas.read_only || canvas.allow_interaction === false) {
        throw new Error('当前没有可编辑画布，请返回工作流编辑界面后再试。');
    }
    const bounds = canvas.canvas?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0 || !canvas.convertCanvasToOffset) {
        throw new Error('当前画布尚未准备好，请稍后重试。');
    }
    const center = canvas.convertCanvasToOffset([bounds.width / 2, bounds.height / 2]);
    if (!center || !Number.isFinite(center[0]) || !Number.isFinite(center[1])) throw new Error('无法确定当前画布位置。');
    const node = createNode('ToolBoxSkillReader');
    if (!node) throw new Error('tb-skill-reader 尚未注册，请刷新页面后重试。');
    const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
    let changing = false;
    try {
        const widget = node.widgets?.find(widget => widget.name === 'id');
        if (!widget) throw new Error('tb-skill-reader 缺少 ID 控件，请刷新页面后重试。');
        node.title = 'tb-skill-reader - 读取 Skill 或提示词模板';
        node.pos = [center[0] - node.size[0] / 2, center[1] - node.size[1] / 2];
        tracker?.captureCanvasState?.();
        if (canvas.emitBeforeChange) canvas.emitBeforeChange();
        else graph.beforeChange();
        changing = true;
        graph.add(node);
        if (node.graph !== graph) throw new Error('无法将节点添加到当前画布。');
        widget.value = id;
        widget.callback?.(id);
        canvas.selectNode(node, false);
        graph.change();
        node.setDirtyCanvas(true, true);
        canvas.canvas.focus?.();
        return node;
    } catch (error) {
        if (node.graph === graph) graph.remove(node);
        else node.onRemoved?.();
        throw error;
    } finally {
        if (changing) {
            if (canvas.emitAfterChange) canvas.emitAfterChange();
            else graph.afterChange();
            // Third-party canvas hooks may defer capture until the next pointer event.
            // Capturing identical state is a no-op in ComfyUI's workflow tracker.
            tracker?.captureCanvasState?.();
        }
    }
}

export function createSkillLibraryToolbar({app, api, openBrowser = openSkillBrowser, createNode}) {
    let browser = null;
    return {
        icon: 'pi pi-file',
        label: 'Skill / 模板库',
        tooltip: '浏览 Skill / 提示词模板库，选择内容并添加 tb-skill-reader 节点',
        onClick() {
            if (browser) return;
            browser = openBrowser({
                currentId: 0,
                request: (path, options) => api.fetchApi(`/toolbox/skills${path}`, options),
                onSelect: id => addSkillReaderToCanvas(app, id, {createNode}),
                onClose: () => {
                    browser = null;
                    app.canvas?.canvas?.focus?.();
                },
            });
        },
    };
}
