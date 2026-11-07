import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { File } from 'node:buffer';

test('traditional and Nodes 2.0 widgets preserve DOM, serialization and scope checks',async()=>{
  let extension;
  class Element{constructor(){this.style={};this.children=[];}append(...x){this.children.push(...x);}}
  class Node{constructor(){this.widgets=[{name:'file_path',value:''},{name:'asset_id',value:''}];this.dom=[];}addDOMWidget(name,type,element,options){this.dom.push({name,type,element,options});}setSize(){}setDirtyCanvas(){}}
  const context=vm.createContext({document:{createElement:()=>new Element()},URLSearchParams,
    createMediaLibraryToolbar:()=>({}),openMediaLibrary:()=>({close(){}}),app:{registerExtension:x=>extension=x,graph:{change(){}}},api:{apiURL:x=>x},window:{addEventListener(){},removeEventListener(){}},location:{origin:'http://test'}});
  const code=readFileSync(new URL('../../web/js/media_library.js',import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'');
  vm.runInContext(code,context);await extension.beforeRegisterNodeDef(Node,{name:'ToolBoxMediaLibrary'});const node=new Node();node.onNodeCreated();
  const native=new Set(['button','text','string','STRING','image','video','audio','markdown']);
  for(const widget of node.dom){assert.ok(!native.has(widget.type));assert.equal(widget.options.serialize,false);assert.ok(widget.element);}
  assert.equal(node.widgets[1].value,'');assert.equal(node.widgets[1].hidden,true);
  assert.match(code,/event\.origin !== location\.origin/);assert.match(code,/event\.source !== preview\.contentWindow/);
});

async function pasteNode(fetch){
  let extension;
  class Element{constructor(){this.style={};this.children=[];this.contentWindow={};}append(...children){this.children.push(...children);}}
  class Node{constructor(){this.widgets=[{name:'file_path',value:''},{name:'asset_id',value:''}];this.dom=[];}addDOMWidget(name,type,element){this.dom.push({name,type,element});}setSize(){}setDirtyCanvas(){}}
  const context=vm.createContext({document:{createElement:()=>new Element()},URLSearchParams,FormData,File,setTimeout,clearTimeout,fetch,
    createMediaLibraryToolbar:()=>({}),openMediaLibrary:()=>({close(){}}),app:{registerExtension:value=>extension=value,graph:{change(){}}},api:{apiURL:path=>path},window:{addEventListener(){},removeEventListener(){}},location:{origin:'http://test'}});
  const code=readFileSync(new URL('../../web/js/media_library.js',import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'');
  vm.runInContext(code,context);await extension.beforeRegisterNodeDef(Node,{name:'ToolBoxMediaLibrary'});
  const node=new Node();node.onNodeCreated();return node;
}

test('native image paste uses official upload, pasted subfolder and returned canonical path',async()=>{
  const requests=[];
  const item={id:'pasted-asset',path:'/server/input/pasted/image (1).png'};
  const node=await pasteNode(async(url,options)=>{
    requests.push({url,options});
    const value=url.endsWith('/roots')?{roots:[{id:'builtin-input',path:'/server/input'}]}:
      url==='/upload/image'?{name:'image (1).png',subfolder:'pasted',type:'input'}:item;
    return {ok:true,json:async()=>value};
  });
  assert.equal(node.previewMediaType,'image');
  const image=new File(['image data'],'image.png',{type:'image/png'});
  await node.pasteFiles([new File(['text'],'text.txt',{type:'text/plain'}),image]);
  const uploads=requests.filter(request=>request.url==='/upload/image');
  assert.equal(uploads.length,1);
  assert.equal(uploads[0].options.method,'POST');
  assert.equal(uploads[0].options.body.get('subfolder'),'pasted');
  assert.equal(uploads[0].options.body.get('type'),'input');
  assert.equal(uploads[0].options.body.get('overwrite'),null);
  assert.equal(uploads[0].options.body.get('image').name,'image.png');
  assert.equal(node.widgets[0].value,item.path);assert.equal(node.widgets[1].value,item.id);
  assert.ok(requests.some(request=>new URL(request.url,'http://test').searchParams.get('path')===item.path));
  assert.equal(requests.some(request=>request.url.includes('/select')),false);
  node.onRemoved();
});

test('paste failure preserves existing asset and prevents parallel duplicate uploads',async()=>{
  let finishUpload,started;
  const uploadStarted=new Promise(resolve=>started=resolve);
  let uploads=0;
  const node=await pasteNode(async url=>{
    if(url.endsWith('/roots'))return {ok:true,json:async()=>({roots:[{id:'builtin-input',path:'/server/input'}]})};
    if(url==='/upload/image'){
      uploads++;started();return await new Promise(resolve=>finishUpload=resolve);
    }
    throw new Error('unexpected request');
  });
  node.widgets[0].value='/existing.png';node.widgets[1].value='existing-id';
  const image=new File(['image'],'image.png',{type:'image/png'});
  const pending=node.pasteFiles([image]);await uploadStarted;
  await node.pasteFiles([image]);assert.equal(uploads,1);
  finishUpload({ok:false,status:413});await pending;
  assert.equal(node.widgets[0].value,'/existing.png');assert.equal(node.widgets[1].value,'existing-id');
  assert.equal(node.isUploading,false);
  node.onRemoved();
});
