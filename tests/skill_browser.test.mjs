import {test, before, after} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {chromium} from '@playwright/test';

const markdown = '# Skill 标题\r\n\r\n简洁的 **Markdown** 正文。\r\n\r\n## 步骤\r\n\r\n1. 读取输入\r\n2. 输出结果\r\n\r\n| 参数 | 值 |\r\n| --- | --- |\r\n| 模型 | demo |\r\n\r\n```js\r\nconst value = "<script>literal</script>";\r\n```\r\n\r\n[文档](https://example.com)\r\n';
const encode = value => Buffer.from(value).toString('base64');
const baseRecord = {entry_type:'skill',description:'用于验证简述保持紧凑，正文拥有主要阅读空间。',tags:[],storage_mode:'text',files:[],primary_path:'',shasum:'fixture-sha1',version:'fixture-version',created_at:'2026-11-08 10:00',updated_at:'2026-11-08 11:00'};
let server, browser, base, records, writes;
before(async()=>{
    server=createServer(async(req,res)=>{
        try {
            const url=new URL(req.url,'http://localhost'), path=url.pathname;
            if(path==='/') {
                res.setHeader('Content-Type','text/html');return res.end(`<!doctype html><meta charset="utf-8"><button id="open">打开库</button><script type="module">
                    import {openSkillBrowser} from '/web/js/skill_browser.mjs';
                    document.querySelector('#open').onclick=()=>openSkillBrowser({currentId:0,request:(path,options)=>fetch('/toolbox/skills'+path,options),onSelect:id=>window.selectedId=id});
                </script>`);
            }
            if(/^\/web\/(js|css)\/[\w./-]+$/.test(path) && !path.includes('..')) {
                res.setHeader('Content-Type',path.endsWith('.css')?'text/css':'text/javascript');
                return res.end(await readFile(new URL('..'+path,import.meta.url)));
            }
            res.setHeader('Content-Type','application/json');
            if(path==='/toolbox/skills/tags')return res.end(JSON.stringify({items:[],counts:{},has_more:false}));
            const id=Number(path.split('/').at(-1));
            if(req.method==='PATCH' || req.method==='POST') {
                let raw='';for await(const chunk of req)raw+=chunk;const payload=JSON.parse(raw);writes.push(payload);
                const saved={...baseRecord,...records.get(id),...payload,tags:payload.tags.split(',').map(tag=>tag.trim()).filter(Boolean),id:id||19};records.set(saved.id,saved);
                return res.end(JSON.stringify(saved));
            }
            if(records.has(id))return res.end(JSON.stringify(records.get(id)));
            if(path==='/toolbox/skills')return res.end(JSON.stringify({items:[...records.values()].map(row=>({...row,preview:row.content})),total:records.size,page_size:50}));
            res.writeHead(404);res.end('{}');
        } catch(error) {res.writeHead(500);res.end(JSON.stringify({error:error.message}));}
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));base=`http://127.0.0.1:${server.address().port}`;
    browser=await chromium.launch({headless:true,args:['--no-proxy-server']});
});
after(async()=>{await browser?.close();await new Promise(resolve=>server?.close(resolve));});

async function detailFor(t,{id=17,viewport={width:1440,height:1000}}={}) {
    writes=[];records=new Map([
        [17,{...baseRecord,id:17,name:'正文 Skill',content:markdown}],
        [18,{...baseRecord,id:18,name:'文件包 Skill',storage_mode:'files',primary_path:'SKILL.md',content:markdown,files:[{path:'SKILL.md',data:encode(markdown)},{path:'image.bin',data:Buffer.from([0,255,0]).toString('base64')}]}],
    ]);
    const page=await browser.newPage({viewport});t.after(()=>page.close());page.setDefaultTimeout(8000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);await page.locator('#open').click();await page.locator(`.tbp-card[data-id="${id}"]`).click();
    const detail=page.getByRole('dialog',{name:'Skill/模板详情',exact:true});await detail.waitFor();
    return {page,detail,errors};
}

test('details prioritize Markdown content, keep the summary compact and collapse record metadata',async t=>{
    const {page,detail,errors}=await detailFor(t);
    const preview=detail.getByRole('region',{name:'正文 Markdown 预览',exact:true});
    assert.equal(await preview.locator('h1').innerText(),'Skill 标题');
    assert.equal(await preview.locator('table').count(),1);assert.equal(await preview.locator('ol li').count(),2);
    assert.match(await preview.locator('pre code').innerText(),/<script>literal<\/script>/);
    const bodyBox=await preview.boundingBox(),summaryBox=await detail.getByLabel('简述（可选）',{exact:true}).boundingBox();
    assert.ok(bodyBox.height>summaryBox.height*4);assert.ok(bodyBox.width>summaryBox.width*2);
    assert.equal(await detail.locator('.tbp-skill-record').getAttribute('open'),null);
    assert.equal(await detail.getByText(/SHA-1：/).isVisible(),false);
    await detail.getByText('记录信息',{exact:true}).click();assert.equal(await detail.getByText(/SHA-1：/).isVisible(),true);
    await detail.getByText('记录信息',{exact:true}).click();
    assert.equal(await detail.locator('.tbp-skill-footer').isVisible(),true);
    assert.deepEqual(errors,[]);assert.equal(writes.length,0);
    if(process.env.SKILL_TEST_SCREENSHOTS)await page.screenshot({path:'/tmp/skill-detail-desktop.png'});
});

test('preview reflects unsaved edits, strips active HTML, and preserves original Markdown on unrelated saves',async t=>{
    const {page,detail,errors}=await detailFor(t);
    const editor=detail.locator('.tbp-skill-workspace>.tbp-markdown-editor');
    await editor.getByRole('button',{name:'编辑',exact:true}).click();
    assert.equal(await detail.getByLabel('正文（纯文本 / Markdown）',{exact:true}).inputValue(),markdown.replace(/\r\n/g,'\n'));
    await editor.getByRole('button',{name:'预览',exact:true}).click();
    assert.equal(await detail.locator('[data-editor-status]').innerText(),'');
    await detail.getByLabel('简述（可选）',{exact:true}).fill('修改简述');
    await detail.getByRole('button',{name:'保存修改',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-editor-status]')?.textContent.startsWith('已保存'));
    assert.equal(writes[0].content,markdown);assert.equal(writes[0].description,'修改简述');
    await detail.locator('.tbp-markdown-header').getByRole('button',{name:'编辑',exact:true}).click();
    const attack='# 修改后的标题\n\n<script>window.previewExecuted=true</script><img src="x" onerror="window.previewExecuted=true"><a href="javascript:window.previewExecuted=true">危险链接</a><iframe srcdoc="<script>alert(1)</script>"></iframe>\n\n**保留格式**';
    await detail.getByLabel('正文（纯文本 / Markdown）',{exact:true}).fill(attack);
    await detail.locator('.tbp-markdown-header').getByRole('button',{name:'预览',exact:true}).click();
    const preview=detail.getByRole('region',{name:'正文 Markdown 预览',exact:true});
    assert.equal(await preview.locator('h1').innerText(),'修改后的标题');assert.equal(await preview.locator('strong').innerText(),'保留格式');
    assert.equal(await preview.locator('script,iframe,[onerror],[href^="javascript:"]').count(),0);
    assert.equal(await page.evaluate(()=>Boolean(window.previewExecuted)),false);
    await detail.getByRole('button',{name:'保存修改',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-editor-status]')?.textContent.startsWith('已保存'));
    assert.equal(writes[1].content,attack);assert.deepEqual(errors,[]);
});

test('Markdown files preview and edit the same package bytes while binary files retain their viewer',async t=>{
    const {page,detail,errors}=await detailFor(t,{id:18});
    const preview=detail.getByRole('region',{name:'文件正文 Markdown 预览',exact:true});
    assert.equal(await preview.locator('h1').innerText(),'Skill 标题');
    await detail.locator('.tbp-package .tbp-markdown-header').getByRole('button',{name:'编辑',exact:true}).click();
    const source=detail.getByLabel('文件内容 SKILL.md',{exact:true});await source.fill('# 文件已编辑\n\n**文件正文**');
    await detail.locator('.tbp-package .tbp-markdown-header').getByRole('button',{name:'预览',exact:true}).click();
    assert.equal(await preview.locator('h1').innerText(),'文件已编辑');
    await detail.getByRole('button',{name:'查看文件 image.bin',exact:true}).click();
    assert.equal(await detail.getByText('二进制或非 UTF-8 文件，保留原始字节，可下载。',{exact:true}).isVisible(),true);
    await detail.getByRole('button',{name:'保存修改',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-editor-status]')?.textContent.startsWith('已保存'));
    assert.equal(Buffer.from(writes[0].files.find(file=>file.path==='SKILL.md').data,'base64').toString(),'# 文件已编辑\n\n**文件正文**');
    assert.equal(writes[0].primary_path,'SKILL.md');assert.equal(writes[0].storage_mode,'files');assert.deepEqual(errors,[]);
});

test('narrow details keep the main content readable and the footer accessible without horizontal overflow',async t=>{
    const {page,detail,errors}=await detailFor(t,{viewport:{width:390,height:844}});
    assert.equal(await detail.getByRole('region',{name:'正文 Markdown 预览',exact:true}).isVisible(),true);
    await detail.getByRole('button',{name:'使用此内容',exact:true}).scrollIntoViewIfNeeded();
    assert.equal(await detail.getByRole('button',{name:'使用此内容',exact:true}).isVisible(),true);
    assert.equal(await detail.evaluate(node=>node.scrollWidth<=node.clientWidth),true);
    assert.deepEqual(errors,[]);
    if(process.env.SKILL_TEST_SCREENSHOTS)await page.screenshot({path:'/tmp/skill-detail-mobile.png'});
});

test('new content starts in edit mode, empty previews remain validatable, and source switches preserve draft text',async t=>{
    const {page,detail,errors}=await detailFor(t);
    await detail.getByRole('button',{name:'返回列表',exact:true}).click();
    await page.getByRole('button',{name:'新增 Skill / 模板',exact:true}).click();
    const source=detail.getByLabel('正文（纯文本 / Markdown）',{exact:true});assert.equal(await source.isVisible(),true);
    await detail.getByLabel('名称',{exact:true}).fill('新的 Skill');
    await detail.locator('.tbp-markdown-header').getByRole('button',{name:'预览',exact:true}).click();
    await detail.getByRole('button',{name:'保存内容',exact:true}).click();
    assert.equal(await source.isVisible(),true);assert.equal(writes.length,0);
    await source.fill('# 新正文\n\n保留 {{variable}}');
    await detail.locator('.tbp-markdown-header').getByRole('button',{name:'预览',exact:true}).click();
    await detail.locator('[data-storage-mode="files"]').click();
    await detail.locator('[data-storage-mode="text"]').click();
    assert.equal(await detail.getByRole('region',{name:'正文 Markdown 预览',exact:true}).locator('h1').innerText(),'新正文');
    assert.equal(await detail.getByRole('button',{name:'使用此内容',exact:true}).isDisabled(),true);
    await detail.getByRole('button',{name:'保存内容',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-editor-status]')?.textContent.startsWith('已新增'));
    assert.equal(writes[0].content,'# 新正文\n\n保留 {{variable}}');assert.deepEqual(errors,[]);
});
