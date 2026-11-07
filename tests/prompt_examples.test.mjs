import {test} from 'node:test';
import assert from 'node:assert/strict';
import {processExampleBatches,attachMediaStatus,openExampleConfirmation} from '../web/js/prompt_examples.mjs';

test('association confirmation is modal, cancel-focused, dismissible without changes and confirms only once',t=>{
    class Element{
        constructor(tag){this.tag=tag;this.children=[];this.handlers={};this.attributes={};this.isConnected=true;}
        append(...children){this.children.push(...children);}
        setAttribute(name,value){this.attributes[name]=value;}
        addEventListener(name,handler){this.handlers[name]=handler;}
        showModal(){this.open=true;this.modal=true;}
        close(){this.open=false;}
        remove(){this.isConnected=false;}
        focus(){document.activeElement=this;}
    }
    const previousDocument=globalThis.document,opener=new Element('button');
    globalThis.document={createElement:tag=>new Element(tag),body:new Element('body'),activeElement:opener};
    t.after(()=>{globalThis.document=previousDocument;});
    let confirmed=0,closed=0;
    const open=()=>openExampleConfirmation({text:'移除示例 #9？',details:'images/test.png',onConfirm:()=>{confirmed++;},onClose:()=>{closed++;}});
    let view=open();
    assert.equal(view.dialog.modal,true);
    assert.equal(document.activeElement.textContent,'取消操作');
    assert.ok(view.dialog.attributes['aria-labelledby']);
    document.activeElement.onclick();
    assert.equal(confirmed,0);assert.equal(document.activeElement,opener);
    view=open();let prevented=false;
    view.dialog.handlers.cancel({preventDefault:()=>{prevented=true;}});
    assert.equal(prevented,true);assert.equal(confirmed,0);
    view=open();
    const confirm=view.dialog.children.at(-1).children.at(-1);
    assert.equal(confirm.className,'tbp-danger');
    confirm.onclick();confirm.onclick();
    assert.equal(confirmed,1);assert.equal(closed,3);assert.equal(view.dialog.open,false);
    view=open();view.close();
    assert.equal(confirmed,1);assert.equal(closed,4);
});

test('manual checks split into bounded batches and report progress without a scheduled worker',async()=>{
    const calls=[],progress=[],ids=Array.from({length:450},(_,i)=>i+1);
    const result=await processExampleBatches(ids,{send:async batch=>{calls.push(batch);return {deleted:[batch[0]]};},onProgress:(...args)=>progress.push(args)});
    assert.deepEqual(calls.map(batch=>batch.length),[200,200,50]);assert.deepEqual(calls.flat(),ids);
    assert.deepEqual(progress,[[200,1],[400,2],[450,3]]);assert.deepEqual(result,{done:450,removed:3});
});

test('stopping during an active request allows it to finish and starts no further batch',async()=>{
    let stop=false,calls=0;
    const result=await processExampleBatches(Array.from({length:450},(_,i)=>i+1),{send:async()=>{calls++;stop=true;return {deleted:[]};},shouldStop:()=>stop});
    assert.equal(calls,1);assert.equal(result.done,200);
    assert.deepEqual(await processExampleBatches([1],{send:()=>{throw new Error('not called')},shouldStop:()=>true}),{done:0,removed:0});
});

test('save-status control retries registration without invoking generation or saving, and stays out of serialization',async t=>{
    class Element{constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};}append(...children){this.children.push(...children);}}
    const previousDocument=globalThis.document,previousWindow=globalThis.window;
    globalThis.document={createElement:tag=>new Element(tag)};globalThis.window={dispatchEvent:()=>{}};
    t.after(()=>{globalThis.document=previousDocument;globalThis.window=previousWindow;});
    let callbackCalled=false,request;
    const node={size:[350,180],setSize:()=>{},onExecuted:()=>{callbackCalled=true;},addDOMWidget:(name,type,content,options)=>{node.control=content;return node.display={options};}};
    attachMediaStatus(node,{fetchApi:async(path,options)=>{request={path,payload:JSON.parse(options.body)};return {ok:true,json:async()=>({registered:1})};}});
    node.onExecuted({toolbox_prompt_media:[{prompt_id:9,shasum:'a'.repeat(40),paths:['images/test.png'],registration:'failed',message:'保存成功，关联失败',job_id:'job-1',node_id:'save-1'}]});
    assert.equal(callbackCalled,true);assert.equal(node.control.dataset.registration,'failed');assert.equal(node.display.serialize,false);
    assert.equal(node.display.serializeValue(),undefined);
    const retry=node.control.children.find(element=>element.tag==='button');assert.equal(retry.disabled,false);await retry.onclick();
    assert.equal(request.path,'/toolbox/prompt-examples/register');assert.deepEqual(request.payload.paths,['images/test.png']);assert.equal(request.payload.job_id,'job-1');
    assert.equal(node.control.dataset.registration,'registered');assert.equal(retry.disabled,true);node.onRemoved();
});
