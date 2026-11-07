import {openMediaLibrary} from './media_library_browser.mjs';

export function addMediaLibraryToCanvas(app, asset, {createNode = name => globalThis.LiteGraph?.createNode(name)} = {}) {
    if (typeof asset?.id !== 'string' || !asset.id || typeof asset?.path !== 'string' || !asset.path) {
        throw new Error('请选择有效的素材文件。');
    }
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
    const node = createNode('ToolBoxMediaLibrary');
    if (!node) throw new Error('tb-media-library 尚未注册，请刷新页面后重试。');
    const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
    let changing = false;
    try {
        const path = node.widgets?.find(widget => widget.name === 'file_path');
        const id = node.widgets?.find(widget => widget.name === 'asset_id');
        if (!path || !id) throw new Error('tb-media-library 缺少路径控件，请刷新页面后重试。');
        node.title = 'tb-media-library - 读取素材原文件路径';
        node.pos = [center[0] - node.size[0] / 2, center[1] - node.size[1] / 2];
        tracker?.captureCanvasState?.();
        if (canvas.emitBeforeChange) canvas.emitBeforeChange();
        else graph.beforeChange();
        changing = true;
        graph.add(node);
        if (node.graph !== graph) throw new Error('无法将节点添加到当前画布。');
        // Set both fields together: the manual-path callback deliberately clears asset_id.
        path.value = asset.path;
        id.value = asset.id;
        node.refreshMediaLibrary?.();
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

export function createMediaLibraryToolbar({app, api, openBrowser = openMediaLibrary, createNode}) {
    let browser = null;
    return {
        icon: 'pi pi-images',
        label: '素材库',
        tooltip: '浏览素材库，选择文件并添加 tb-media-library 节点',
        onClick() {
            if (browser) return;
            browser = openBrowser({
                api,
                onSelect: asset => addMediaLibraryToCanvas(app, asset, {createNode}),
                onClose: () => {
                    browser = null;
                    app.canvas?.canvas?.focus?.();
                },
            });
        },
    };
}
