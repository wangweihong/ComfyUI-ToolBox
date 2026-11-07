import {test} from 'node:test';
import assert from 'node:assert/strict';
import {addMediaLibraryToCanvas, createMediaLibraryToolbar} from '../web/js/media_library_toolbar.mjs';

const asset = {id: 'stable-id', path: '/server/input/素材.png'};
function fixture() {
    const events = [], history = [];
    const graph = {nodes: [], beforeChange() {events.push('before');}, afterChange() {events.push('after');history.push([...this.nodes]);},
        add(node) {node.graph = this;this.nodes.push(node);},
        remove(node) {this.nodes = this.nodes.filter(item => item !== node);node.graph = null;node.onRemoved?.();}, change() {events.push('change');}};
    const canvas = {graph, canvas: {getBoundingClientRect: () => ({width: 1000, height: 600}), focus() {this.focused = true;}},
        convertCanvasToOffset: ([x,y]) => [x/2-100, y/2+20], selectNode(node) {this.selected = node;}};
    const app = {canvas, graph: {nodes: []}};
    const createNode = name => {
        assert.equal(name, 'ToolBoxMediaLibrary');
        return {size: [390,420], widgets: [{name: 'file_path', value: ''}, {name: 'asset_id', value: ''}],
            refreshMediaLibrary() {events.push('refresh');}, setDirtyCanvas() {}, onRemoved() {events.push('disposed');}};
    };
    return {app, graph, canvas, createNode, events, history};
}

test('selection adds path and ID together to the active subgraph in one undo operation', () => {
    const f = fixture(), node = addMediaLibraryToCanvas(f.app, asset, f);
    assert.deepEqual(node.widgets.map(w => w.value), [asset.path, asset.id]);
    assert.deepEqual(node.pos, [-45,-40]);
    assert.deepEqual(f.graph.nodes, [node]);assert.equal(f.app.graph.nodes.length, 0);
    assert.equal(f.canvas.selected, node);assert.equal(f.history.length, 1);
    assert.equal(f.canvas.canvas.focused, true);
    assert.deepEqual(f.events, ['before','refresh','change','after']);
});

test('invalid assets, missing and readonly canvases never create a node', () => {
    const f = fixture();
    for (const value of [null, {}, {id: '', path: asset.path}, {id: asset.id, path: 12}]) {
        assert.throws(() => addMediaLibraryToCanvas(f.app, value, f), /有效/);
    }
    for (const mutate of [f => f.app.canvas = null, f => f.canvas.read_only = true,
        f => f.canvas.allow_interaction = false, f => f.canvas.canvas.getBoundingClientRect = () => ({width:0,height:0})]) {
        const f = fixture();mutate(f);
        assert.throws(() => addMediaLibraryToCanvas(f.app, asset, {createNode: () => assert.fail('created')}));
        assert.equal(f.graph.nodes.length, 0);
    }
});

test('initialization failure removes partial nodes and permits retry', () => {
    const f = fixture();
    assert.throws(() => addMediaLibraryToCanvas(f.app, asset, {createNode: () => null}), /尚未注册/);
    assert.throws(() => addMediaLibraryToCanvas(f.app, asset, {createNode: () => ({widgets: [], onRemoved() {f.events.push('disposed');}})}), /控件/);
    assert.throws(() => addMediaLibraryToCanvas(f.app, asset, {createNode: name => {
        const node = f.createNode(name);node.refreshMediaLibrary = () => {throw Error('synthetic failure');};return node;
    }}), /synthetic/);
    assert.equal(f.graph.nodes.length, 0);assert.equal(f.events.at(-1), 'after');
    addMediaLibraryToCanvas(f.app, asset, f);assert.equal(f.graph.nodes.length, 1);
});

test('workflow tracker captures the baseline and completed addition without waiting for a pointer event', () => {
    const f = fixture(), captures = [];
    f.app.extensionManager = {workflow: {activeWorkflow: {changeTracker: {
        captureCanvasState() {captures.push(f.graph.nodes.map(n => n.widgets.map(w => w.value)));},
    }}}};
    addMediaLibraryToCanvas(f.app, asset, f);
    assert.deepEqual(captures, [[], [[asset.path, asset.id]]]);
});

test('native canvas history events take precedence over legacy graph hooks', () => {
    const f = fixture(), calls = [];
    f.canvas.emitBeforeChange = () => calls.push('before');
    f.canvas.emitAfterChange = () => calls.push('after');
    f.graph.beforeChange = f.graph.afterChange = () => assert.fail('legacy hook called');
    addMediaLibraryToCanvas(f.app, asset, f);
    assert.deepEqual(calls, ['before', 'after']);
});

test('toolbar opens one browser, cancellation adds nothing, and selection follows the current canvas', () => {
    const first = fixture(), second = fixture(), calls = [];
    const toolbar = createMediaLibraryToolbar({app: first.app, api: {}, createNode: first.createNode,
        openBrowser: options => {calls.push(options);return {};}});
    assert.equal(toolbar.label, '素材库');toolbar.onClick();toolbar.onClick();assert.equal(calls.length, 1);
    calls[0].onClose();assert.equal(first.graph.nodes.length, 0);assert.equal(first.canvas.canvas.focused, true);toolbar.onClick();
    first.app.canvas = second.canvas;calls[1].onSelect(asset);
    assert.equal(first.graph.nodes.length, 0);assert.equal(second.graph.nodes.length, 1);
});
