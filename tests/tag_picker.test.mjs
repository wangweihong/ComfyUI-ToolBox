import {test} from 'node:test';
import assert from 'node:assert/strict';
import {normalizeTag,parseTags,newTagName,loadTagCatalog,attachNodeTags} from '../web/js/tag_picker.mjs';

test('tag names match backend normalization and adding one name cannot inject a CSV',()=>{
    assert.equal(normalizeTag('  NIGHT  '),'night');
    assert.deepEqual(parseTags(' Night,day, NIGHT, , 中文 '),['night','day','中文']);
    assert.equal(newTagName(' New Tag '),'new tag');
    for(const name of [' ', 'one,two','bad\nname','bad\0name'])assert.throws(()=>newTagName(name));
});

test('catalog reads all pages past 500 tags and retains normalized usage counts',async()=>{
    const calls=[],signal=new AbortController().signal;
    const data=await loadTagCatalog(async(path,options)=>{
        calls.push(path);assert.equal(options.signal,signal);
        const second=path.endsWith('page=2');
        const items=second?[' Tag500 ','tag000']:Array.from({length:500},(_,i)=>`tag${String(i).padStart(3,'0')}`);
        return {ok:true,json:async()=>({items,counts:{' Tag500 ':3,tag000:2},has_more:!second})};
    },signal);
    assert.equal(calls.length,2);assert.equal(data.length,501);
    assert.deepEqual(data.find(item=>item.name==='tag500'),{name:'tag500',count:3});
    assert.equal(data.find(item=>item.name==='tag000').count,2);
});

test('empty catalog succeeds while request and malformed catalog failures remain errors',async()=>{
    assert.deepEqual(await loadTagCatalog(async()=>({ok:true,json:async()=>({items:[],counts:{},has_more:false})})),[]);
    await assert.rejects(loadTagCatalog(async()=>({ok:false,status:503,json:async()=>({error:'unavailable'})})),/unavailable/);
    await assert.rejects(loadTagCatalog(async()=>({ok:true,json:async()=>({items:[]})})),/格式异常/);
    const abort=new Error('aborted');abort.name='AbortError';
    await assert.rejects(loadTagCatalog(async()=>{throw abort}),{name:'AbortError'});
});

test('node adapter preserves widget positions, serialization, callbacks, restored values and connected inputs',t=>{
    class Element {
        constructor(tag){this.tag=tag;this.children=[];this.style={};this.attributes={};this.textContent='';}
        append(...children){this.children.push(...children);}
        replaceChildren(...children){this.children=[...children];}
        setAttribute(name,value){this.attributes[name]=value;}
    }
    const original=globalThis.document;
    globalThis.document={querySelector:()=>({}),createElement:tag=>new Element(tag)};
    t.after(()=>{globalThis.document=original;});
    const serialize=()=> 'original serialization',seedCallback=()=>{},calls=[];
    const tags={name:'tags',type:'text',value:'alpha',serializeValue:serialize,inputEl:{style:{}},callback:()=>calls.push('tag')};
    const first={name:'seed',value:1,beforeQueued:seedCallback},last={name:'other',value:9};
    const node={widgets:[first,tags,last],inputs:[],size:[300,300],setSize:()=>{},computeSize:()=>[350,300],
        onConfigure:()=>{calls.push('configure');return 17},onDrawForeground:()=>calls.push('draw'),
        onConnectionsChange:()=>calls.push('connection'),onRemoved:()=>calls.push('removed'),
        addDOMWidget:(name,type,content,options)=>{node.control=content;const widget={name,options};node.widgets.push(widget);return widget;}};
    attachNodeTags(node,{graph:{}},{fetchApi:()=>{throw new Error('No network until picker opens');}},{allowCreate:true});
    const flatten=element=>[element,...element.children.flatMap(flatten)];
    const input=flatten(node.control).find(element=>element.name==='tags');
    const buttons=flatten(node.control).filter(element=>element.tag==='button');
    assert.deepEqual(node.widgets.slice(0,3),[first,tags,last]);
    assert.equal(tags.serializeValue,serialize);assert.equal(first.beforeQueued,seedCallback);
    assert.equal(node.widgets[3].options.serialize,false);assert.equal(tags.hidden,true);
    assert.equal(node.widgets[3].serialize,false);assert.equal(node.widgets[3].serializeValue(),undefined);
    tags.value='restored, beta';assert.equal(node.onConfigure(),17);assert.equal(input.value,tags.value);
    tags.value='undo-value';node.onDrawForeground();assert.equal(input.value,'undo-value');
    node.inputs=[{name:'tags',link:5}];tags.type='converted-widget';node.onConnectionsChange();
    assert.equal(tags.type,'converted-widget');assert.ok(buttons.every(button=>button.disabled));
    assert.ok(flatten(node.control).some(element=>element.textContent==='由连接输入提供'));
    node.inputs[0].link=null;node.onConnectionsChange();assert.ok(buttons.every(button=>!button.disabled));
    node.onRemoved();assert.ok(calls.includes('removed'));assert.ok(calls.includes('draw'));
});
