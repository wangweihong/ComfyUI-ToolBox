import {test, before, after} from "node:test";
import assert from "node:assert/strict";
import {createServer} from "node:http";
import {readFile} from "node:fs/promises";
import {once} from "node:events";
import {chromium} from "playwright";
import {freeLayout, fillLayout, frameRect} from "../web/js/image_compare_view.mjs";

let server, browser, base;
before(async () => {
    const source = await readFile(new URL("../web/js/image_compare_view.mjs", import.meta.url));
    server = createServer((request, response) => {
        if (request.url === "/view.mjs") {
            response.setHeader("Content-Type", "text/javascript"); response.end(source);
        } else {
            response.setHeader("Content-Type", "text/html");
            response.end('<!doctype html><html><head><meta charset="utf-8"></head><body style="background:#313640;margin:30px"><main style="width:760px;height:560px"></main></body></html>');
        }
    });
    server.listen(0, "127.0.0.1"); await once(server, "listening"); base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({headless: true});
});
after(async () => {await browser?.close(); await new Promise(resolve => server?.close(resolve));});

async function fixture(t, withSizes = false) {
    const page = await browser.newPage({viewport: {width: 1050, height: 740}}); t.after(() => page.close());
    await page.goto(base);
    await page.evaluate(async withSizes => {
        const {attachImageCompare} = await import("/view.mjs");
        window.changes = 0;
        window.node = {
            size: [300, 200], properties: {}, inputs: [{name: "image_1", type: "IMAGE", link: null}], widgets: [{name:"width",value:1024},{name:"height",value:768},{name:"layout",value:"{}"}],
            graph: {change() {window.changes++;}},
            addInput(name, type) {this.inputs.push({name, type, link: null});},
            removeInput(index) {this.inputs.splice(index, 1);},
            setSize(size) {this.size = size;},
            addDOMWidget(name, type, element, options) {
                document.querySelector("main").append(element);
                const widget = {name, type, options}; this.widgets.push(widget); return widget;
            },
            onExecuted() {window.originalExecuted = true;},
            onConfigure() {window.originalConfigured = true;},
        };
        for(const widget of node.widgets){widget.type=widget.name==='layout'?'text':'number';widget.options={};widget.computeSize=()=>[200,20];}
        const ratioData={'1:1 方图':['1440 x 1440','4096 x 4096'],'16:9 横屏':['1920 x 1080','2560 x 1440'],'9:16 竖屏':['1080 x 1920','1440 x 2560']};
        if(withSizes) node.widgets.push({name:'ratio',value:'1:1 方图',type:'combo',options:{}},{name:'resolution',value:'1440 x 1440',type:'combo',options:{values:Object.values(ratioData).flat()}});
        window.viewer = attachImageCompare(node, {chinese: true,ratioData});
        window.connect = async () => {
            node.inputs.at(-1).link = node.inputs.length;
            node.onConnectionsChange(1, node.inputs.length - 1, true);
            await new Promise(resolve => queueMicrotask(resolve));
        };
        window.preview = () => node.onExecuted({toolbox_image_compare: node.inputs.filter(input => input.link != null).map(input => ({input: input.name,
            images: ["red", "blue"].map(filename => ({filename: `${filename}-${input.name}`, type: "temp", subfolder: "", width: 600, height: 400}))}))});
    }, withSizes);
    return page;
}



function assertFilled(layout) {
    const rects=Object.values(layout.frames);
    assert.ok(Math.abs(rects.reduce((sum,r)=>sum+r.w*r.h,0)-1)<1e-10);
    for(let i=0;i<rects.length;i++) {
        const a=rects[i]; assert.ok(a.x>=0&&a.y>=0&&a.x+a.w<=1+1e-10&&a.y+a.h<=1+1e-10);
        for(const b of rects.slice(i+1)) assert.ok(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)<1e-10||Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)<1e-10);
    }
}

test('fill retains two-above-one-below spatial grouping and covers the canvas',()=>{
    const keys=['image_1','image_2','image_3'];
    const original=freeLayout(keys,{frames:{
        image_1:{x:.08,y:.08,w:.25,h:.25},image_2:{x:.6,y:.08,w:.25,h:.25},image_3:{x:.3,y:.65,w:.3,h:.25}
    }});
    const snapshot=structuredClone(original),filled=fillLayout(original);assert.deepEqual(original,snapshot);assertFilled(filled);
    const {image_1:a,image_2:b,image_3:c}=filled.frames;
    assert.equal(a.y,0);assert.equal(b.y,0);assert.ok(c.y>0);assert.equal(c.x,0);assert.equal(c.w,1);
    assert.equal(a.x,0);assert.ok(b.x>a.x);
    for(let count=1;count<=20;count++){
        const keys=Array.from({length:count},(_,i)=>`image_${i+1}`);
        const frames=Object.fromEntries(keys.map((key,i)=>[key,{x:(i*17%71)/100,y:(i*29%61)/100,w:.1+(i%3)*.05,h:.12+(i%4)*.03}]));
        assertFilled(fillLayout(freeLayout(keys,{frames})));
    }
});

test('connections create independent movable frames without rearranging existing ones',async t=>{
    const page=await fixture(t);
    await page.evaluate(async()=>{await connect();await connect();await connect();});
    assert.equal(await page.locator('.tbic-frame').count(),3);
    const before=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    assert.ok(before.frames.image_1.w<1&&before.frames.image_1.h<1);
    await page.evaluate(async()=>{node.inputs[1].link=null;node.onConnectionsChange();await Promise.resolve();});
    const after=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    assert.deepEqual(after.frames.image_1,before.frames.image_1);assert.deepEqual(after.frames.image_3,before.frames.image_3);
    assert.deepEqual(await page.evaluate(()=>node.inputs.map(i=>i.name)),['image_1','image_3','image_4']);
});

test('real pointer drag moves both axes, corner resize changes both dimensions, fill and undo are explicit',async t=>{
    const page=await fixture(t);const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.evaluate(async()=>{await connect();await connect();await connect();preview();
        document.querySelector('main').style.transformOrigin='top left';document.querySelector('main').style.transform='scale(.85)';});
    assert.equal(await page.locator('.tbic img').count(),0);assert.equal(await page.locator('.tbic-divider').count(),0);
    const frame=page.locator('[data-input="image_1"]'),box=await frame.boundingBox();
    const initial=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    await page.mouse.move(box.x+20,box.y+12);await page.mouse.down();await page.mouse.move(box.x+80,box.y+102,{steps:6});await page.mouse.up();
    let layout=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    assert.ok(layout.frames.image_1.x>initial.frames.image_1.x+.08&&layout.frames.image_1.y>initial.frames.image_1.y+.15);
    for(const key of ['image_2','image_3']) for(const dim of ['x','y','w','h']) assert.equal(layout.frames[key][dim],initial.frames[key][dim]);
    const handle=page.getByRole('button',{name:'调整 image_1 大小',exact:true}),corner=await handle.boundingBox();
    await page.mouse.move(corner.x+10,corner.y+10);await page.mouse.down();await page.mouse.move(corner.x+45,corner.y+45,{steps:4});await page.mouse.up();
    layout=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    assert.ok(layout.frames.image_1.w>initial.frames.image_1.w&&layout.frames.image_1.h>initial.frames.image_1.h);
    await page.getByRole('combobox',{name:'image_3 批次图片',exact:true}).selectOption('1');
    const beforeFill=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    await page.getByRole('button',{name:'铺满画布',exact:true}).click();
    layout=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));assertFilled(layout);assert.equal(layout.indices.image_3,1);
    if(process.env.IMAGE_COMPARE_SCREENSHOT) await page.screenshot({path:process.env.IMAGE_COMPARE_SCREENSHOT});
    await page.getByRole('button',{name:'撤销铺满',exact:true}).click();
    assert.deepEqual(await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value)),beforeFill);
    await frame.focus();await page.keyboard.press('ArrowDown');
    assert.ok(await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value).frames.image_1.y)>beforeFill.frames.image_1.y);
    assert.deepEqual(errors,[]);
});

test('saved free rectangles, batch selection and labels restore without image requests',async t=>{
    const page=await fixture(t),imageRequests=[];page.on('request',r=>{if(r.resourceType()==='image')imageRequests.push(r.url());});
    await page.evaluate(async()=>{
        await connect();await connect();await connect();preview();
        const widget=node.widgets.find(w=>w.name==='layout'),saved=JSON.parse(widget.value);
        saved.frames.image_1={x:.1,y:.4,w:.2,h:.3,z:2};saved.indices.image_3=1;widget.value=JSON.stringify(saved);node.onConfigure();await Promise.resolve();
    });
    assert.equal(await page.locator('[data-input="image_1"]').evaluate(el=>el.style.top),'40%');
    assert.equal(await page.locator('[data-input="image_1"] .tbic-proportion').textContent(),'20.0% × 30.0%');
    assert.equal(await page.getByRole('combobox',{name:'image_3 批次图片',exact:true}).inputValue(),'1');
    assert.equal(await page.locator('.tbic img').count(),0);assert.deepEqual(imageRequests,[]);
});


test('names default to socket names, edit independently, and survive fill and workflow restore',async t=>{
    const page=await fixture(t);
    await page.evaluate(async()=>{await connect();await connect();await connect();});
    assert.equal(await page.getByRole('textbox',{name:'image_1 名称',exact:true}).inputValue(),'image_1');
    assert.equal(await page.locator('.tbic-title').count(),0);
    const inputBefore=await page.evaluate(()=>({...node.inputs.find(i=>i.name==='image_1')}));
    const before=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value).frames.image_1);
    await page.getByRole('textbox',{name:'image_1 名称',exact:true}).fill('原始图');
    await page.getByRole('textbox',{name:'image_1 名称',exact:true}).press('Enter');
    let layout=await page.evaluate(()=>JSON.parse(node.widgets.find(w=>w.name==='layout').value));
    assert.equal(layout.names.image_1,'原始图');assert.deepEqual(layout.frames.image_1,before);
    assert.deepEqual(await page.evaluate(()=>({...node.inputs.find(i=>i.name==='image_1')})),inputBefore);
    await page.getByRole('button',{name:'铺满画布',exact:true}).click();
    await page.evaluate(()=>node.onConfigure());
    assert.equal(await page.getByRole('textbox',{name:'image_1 名称',exact:true}).inputValue(),'原始图');
    await page.evaluate(()=>{node.inputs.find(i=>i.name==='image_1').label='原始图';node.onConfigure();});
    assert.equal(await page.evaluate(()=>node.inputs.find(i=>i.name==='image_1').label),'image_1');
    assert.equal(await page.getByRole('textbox',{name:'image_1 名称',exact:true}).inputValue(),'原始图');
});

test('aspect ratio filters resolutions and custom dimensions restore without shifting old saved values',async t=>{
    const page=await fixture(t,true);
    assert.deepEqual(await page.evaluate(()=>node.widgets.slice(0,5).map(w=>w.name)),['ratio','resolution','width','height','layout']);
    await page.evaluate(()=>{const w=node.widgets.find(w=>w.name==='ratio');w.value='16:9 横屏';w.callback();});
    assert.deepEqual(await page.evaluate(()=>node.widgets.find(w=>w.name==='resolution').options.values),['1920 x 1080','2560 x 1440']);
    assert.equal(await page.locator('.tbic-board').evaluate(el=>el.style.aspectRatio),'1920 / 1080');
    assert.equal(await page.evaluate(()=>node.widgets.find(w=>w.name==='width').hidden),true);
    await page.evaluate(()=>{const w=node.widgets.find(w=>w.name==='resolution');w.value='2560 x 1440';w.callback();});
    assert.match(await page.locator('.tbic-count').textContent(),/2560×1440/);
    await page.evaluate(()=>{const w=node.widgets.find(w=>w.name==='ratio');w.value='自定义尺寸';w.callback();node.widgets.find(w=>w.name==='width').value=1200;node.widgets.find(w=>w.name==='height').value=800;node.widgets.find(w=>w.name==='height').callback();});
    assert.equal(await page.evaluate(()=>node.widgets.find(w=>w.name==='width').hidden),false);
    assert.equal(await page.locator('.tbic-board').evaluate(el=>el.style.aspectRatio),'1200 / 800');
    await page.evaluate(()=>node.onConfigure({widgets_values:[640,480,'{}']}));
    assert.equal(await page.evaluate(()=>node.widgets.find(w=>w.name==='ratio').value),'自定义尺寸');
    assert.equal(await page.locator('.tbic-board').evaluate(el=>el.style.aspectRatio),'640 / 480');
});
