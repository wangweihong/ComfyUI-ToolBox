import {test} from 'node:test';
import assert from 'node:assert/strict';
import {addPromptReaderToCanvas, createPromptLibraryToolbar} from '../web/js/prompt_toolbar.mjs';

function fixture() {
    const events=[], history=[];
    const graph={nodes:[],beforeChange(){events.push('before');},afterChange(){events.push('after');history.push(this.nodes.map(node=>({id:node.widgets[0].value,pos:[...node.pos]})));},
        add(node){events.push('add');node.graph=this;this.nodes.push(node);},
        remove(node){events.push('remove');this.nodes=this.nodes.filter(item=>item!==node);node.graph=null;node.onRemoved?.();},
        change(){events.push('change');}};
    const canvas={graph,canvas:{getBoundingClientRect:()=>({width:1000,height:600})},
        convertCanvasToOffset:([x,y])=>[x/2-100,y/2+20],selectNode:node=>{canvas.selected=node;}};
    const root={nodes:[]}, app={canvas,graph:root};
    const createNode=type=>{assert.equal(type,'ToolBoxPromptReader');return {size:[350,180],widgets:[{name:'id',value:1,callback:value=>events.push(`id:${value}`)}],setDirtyCanvas:()=>events.push('dirty'),onRemoved:()=>events.push('disposed')};};
    return {app,graph,canvas,root,createNode,events,history};
}

test('toolbar selection adds an initialized reader at viewport center in the active subgraph in one history operation',()=>{
    const f=fixture(),node=addPromptReaderToCanvas(f.app,29,{createNode:f.createNode});
    assert.equal(f.root.nodes.length,0);assert.deepEqual(f.graph.nodes,[node]);
    assert.equal(node.widgets[0].value,29);assert.deepEqual(node.pos,[-25,80]);
    assert.equal(f.canvas.selected,node);assert.equal(node.title,'tb-prompt-reader - 读取提示词库记录');
    assert.deepEqual(f.events,['before','add','id:29','change','dirty','after']);
    assert.deepEqual(f.history,[[{id:29,pos:[-25,80]}]]);
});

test('missing, readonly, hidden and unregistered canvases report errors without changing the graph',()=>{
    for(const mutation of [f=>{f.app.canvas=null;},f=>{f.canvas.read_only=true;},f=>{f.canvas.allow_interaction=false;},f=>{f.canvas.canvas.getBoundingClientRect=()=>({width:0,height:0});}]){
        const f=fixture();mutation(f);
        assert.throws(()=>addPromptReaderToCanvas(f.app,3,{createNode:()=>assert.fail('should not create')}));
        assert.equal(f.graph.nodes.length,0);assert.equal(f.events.length,0);
    }
    const f=fixture();
    assert.throws(()=>addPromptReaderToCanvas(f.app,3,{createNode:()=>null}),/尚未注册/);
    for(const id of [0,-1,'bad',1.5,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>addPromptReaderToCanvas(f.app,id,{createNode:f.createNode}),/已保存/);
    assert.equal(f.events.length,0);
});

test('failed node initialization rolls back and cleans up, and retry creates just one node',()=>{
    const f=fixture();
    assert.throws(()=>addPromptReaderToCanvas(f.app,3,{createNode:()=>({widgets:[],onRemoved:()=>f.events.push('disposed')})}),/ID 控件/);
    assert.deepEqual(f.events,['disposed']);f.events.length=0;
    assert.throws(()=>addPromptReaderToCanvas(f.app,3,{createNode:()=>{
        const node=f.createNode('ToolBoxPromptReader');node.widgets[0].callback=()=>{throw new Error('synthetic failure');};return node;
    }}),/synthetic failure/);
    assert.equal(f.graph.nodes.length,0);assert.deepEqual(f.events,['before','add','remove','disposed','after']);
    addPromptReaderToCanvas(f.app,3,{createNode:f.createNode});assert.equal(f.graph.nodes.length,1);
});

test('toolbar is a singleton per browser opening, routes requests correctly and resolves the active workflow at selection time',()=>{
    const first=fixture(),second=fixture(),calls=[],requests=[];
    const api={fetchApi:(...args)=>{requests.push(args);return {};}};
    const toolbar=createPromptLibraryToolbar({app:first.app,api,createNode:first.createNode,openBrowser:options=>{calls.push(options);return {};}});
    assert.equal(toolbar.label,'提示词库');assert.ok(toolbar.icon);assert.ok(toolbar.tooltip);
    toolbar.onClick();toolbar.onClick();assert.equal(calls.length,1);assert.equal(calls[0].currentId,0);
    calls[0].request('?sort=updated_desc',{});calls[0].exampleRequest('/toolbox/prompt-examples',{});
    assert.deepEqual(requests.map(item=>item[0]),['/toolbox/prompts?sort=updated_desc','/toolbox/prompt-examples']);
    first.app.canvas=second.canvas;calls[0].onSelect(17);
    assert.equal(first.graph.nodes.length,0);assert.equal(second.graph.nodes[0].widgets[0].value,17);
    calls[0].onClose();toolbar.onClick();assert.equal(calls.length,2);
});
