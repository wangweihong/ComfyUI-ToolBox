// Real API and browser interactions against a disposable synthetic database only.
import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import net from 'node:net';
import {chromium} from 'playwright';

let server,browser,base;
before(async()=>{
    const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');
    const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));base=`http://127.0.0.1:${port}`;
    server=spawn(process.env.PROMPT_TEST_PYTHON||'python3',['-u','tests/skill_test_fixture.py','--port',String(port),'--seed'],{stdio:['ignore','pipe','pipe']});
    let logs='';server.stdout.on('data',data=>{logs+=data;});server.stderr.on('data',data=>{logs+=data;});
    for(let attempt=0;attempt<100;attempt++){
        if(server.exitCode!==null)throw new Error(logs);
        try{if((await fetch(base)).ok)break;}catch{}
        if(attempt===99)throw new Error(logs);
        await new Promise(resolve=>setTimeout(resolve,50));
    }
    browser=await chromium.launch({headless:true});
});
after(async()=>{await browser?.close();if(server&&server.exitCode===null){server.kill('SIGTERM');await once(server,'exit');}});

async function pageFor(t){
    const page=await browser.newPage({viewport:{width:1440,height:1000}});t.after(()=>page.close());
    page.on('dialog',dialog=>dialog.accept());
    await page.goto(base);return page;
}
async function create(page,changes={}){
    const response=await page.request.post(`${base}/toolbox/skills`,{data:{name:'Synthetic management entry',
        entry_type:'skill',description:'Synthetic summary',content:'# Synthetic body',tags:'management-tag',...changes}});
    assert.equal(response.status(),201);return response.json();
}
async function openRow(page,row){
    await page.locator('#open').click();
    await page.locator('.tb-skill-library [name="q"]').fill(row.name);
    await page.locator(`.tbp-card[data-id="${row.id}"]`).click();
    return page.getByRole('dialog',{name:'Skill/模板详情',exact:true});
}
async function cleanup(id){
    const response=await fetch(`${base}/toolbox/skills/${id}`);if(!response.ok)return;
    const row=await response.json();
    await fetch(`${base}/toolbox/skills/${id}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:row.version})});
}

test('Skill text and template package delete through confirmation, preserve cancel and refresh capacity',async t=>{
    for(const kind of ['skill','prompt_template']){
        const page=await pageFor(t);
        const files=kind==='prompt_template'?[{path:'template.md',data:Buffer.from('# Template body').toString('base64')}]:[];
        const row=await create(page,{name:`Synthetic delete ${kind}`,entry_type:kind,
            ...(files.length?{content:'',storage_mode:'files',primary_path:'template.md',files}:{})});
        t.after(()=>cleanup(row.id));
        const detail=await openRow(page,row);
        await detail.getByRole('button',{name:'删除内容',exact:true}).click();
        const confirmation=page.getByRole('dialog',{name:kind==='skill'?'删除Skill':'删除提示词模板',exact:true});
        assert.match(await confirmation.textContent(),new RegExp(`${files.length} 个文件`));
        await page.keyboard.press('Escape');
        assert.equal((await page.request.get(`${base}/toolbox/skills/${row.id}`)).status(),200);
        await detail.getByRole('button',{name:'删除内容',exact:true}).click();
        const response=page.waitForResponse(response=>response.request().method()==='DELETE');
        await confirmation.getByRole('button',{name:'确认删除',exact:true}).click();
        assert.deepEqual((await response).request().postDataJSON(),{version:row.version});
        await detail.waitFor({state:'hidden'});
        assert.equal((await page.request.get(`${base}/toolbox/skills/${row.id}`)).status(),404);
        assert.equal((await page.request.get(`${base}/toolbox/skills/${row.id}/download`)).status(),404);
        await page.locator('.tb-skill-library').getByRole('status').filter({hasText:/没有匹配/}).waitFor();
    }
});

test('delete version conflict preserves unsaved editor, reload allows retry',async t=>{
    const page=await pageFor(t);const row=await create(page,{name:'Synthetic stale deletion'});t.after(()=>cleanup(row.id));
    const detail=await openRow(page,row);
    const payload={name:row.name,entry_type:row.entry_type,description:'External edit',content:row.content,
        tags:row.tags.join(','),version:row.version};
    assert.equal((await page.request.patch(`${base}/toolbox/skills/${row.id}`,{data:payload})).status(),200);
    await detail.getByLabel('名称',{exact:true}).fill('unsaved name to preserve');
    await detail.getByRole('button',{name:'删除内容',exact:true}).click();
    await page.getByRole('dialog',{name:'删除Skill',exact:true}).getByRole('button',{name:'确认删除',exact:true}).click();
    await detail.locator('[data-editor-status]').filter({hasText:/记录已被修改/}).waitFor();
    assert.equal(await detail.getByLabel('名称',{exact:true}).inputValue(),'unsaved name to preserve');
    await detail.getByRole('button',{name:'重新加载详情',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.tb-skill-detail [name="description"]').value==='External edit');
    assert.equal(await detail.getByLabel('名称',{exact:true}).inputValue(),row.name);
});

test('tag picker manager spans both content types and syncs other windows without discarding drafts',async t=>{
    const page=await pageFor(t);
    const first=await create(page,{name:'Synthetic tag manager first',tags:'delete-shared-skill-tag'});
    const second=await create(page,{name:'Synthetic tag manager second',entry_type:'prompt_template',tags:'delete-shared-skill-tag'});
    t.after(()=>cleanup(first.id));t.after(()=>cleanup(second.id));
    await page.locator('#open').click();
    const library=page.getByRole('dialog',{name:'Skill 与提示词模板库',exact:true}).first();
    await library.locator('.tbp-tag-option[data-tag="delete-shared-skill-tag"]').click();
    await library.locator(`.tbp-card[data-id="${first.id}"]`).click();
    const detail=page.getByRole('dialog',{name:'Skill/模板详情',exact:true}).first();
    await detail.getByLabel('名称',{exact:true}).fill('draft survives tag delete');
    await page.evaluate(()=>document.querySelector('#second').click());
    const other=page.getByRole('dialog',{name:'Skill 与提示词模板库',exact:true}).nth(1);
    await other.locator(`.tbp-card[data-id="${second.id}"]`).click();
    const secondDetail=page.getByRole('dialog',{name:'Skill/模板详情',exact:true}).nth(1);
    await secondDetail.getByRole('button',{name:'选择标签',exact:true}).click();
    const picker=page.getByRole('dialog',{name:'选择或新增标签',exact:true});
    await picker.getByRole('button',{name:'管理 Skill / 模板标签',exact:true}).click();
    const manager=page.getByRole('dialog',{name:'管理 Skill / 模板标签',exact:true});
    await manager.getByRole('searchbox').fill('delete-shared-skill-tag');
    await manager.getByRole('button',{name:'删除标签',exact:true}).click();
    const confirmation=page.getByRole('dialog',{name:'删除标签',exact:true});
    assert.match(await confirmation.textContent(),/2 条Skill／模板/);
    await confirmation.getByRole('button',{name:'取消操作',exact:true}).click();
    assert.deepEqual((await (await page.request.get(`${base}/toolbox/skills/${first.id}`)).json()).tags,['delete-shared-skill-tag']);
    await manager.getByRole('button',{name:'删除标签',exact:true}).click();
    await confirmation.getByRole('button',{name:'确认删除',exact:true}).click();
    await manager.getByRole('status').filter({hasText:/解除 2 条关联/}).waitFor();
    assert.equal(await detail.getByLabel('名称',{exact:true}).inputValue(),'draft survives tag delete');
    assert.equal(await library.locator('.tbp-selected-tag').count(),0);
    assert.match(await detail.locator('[data-editor-status]').textContent(),/当前输入已保留/);
    for(const row of [first,second])assert.deepEqual((await (await page.request.get(`${base}/toolbox/skills/${row.id}`)).json()).tags,[]);
    await manager.getByRole('button',{name:'关闭',exact:true}).click();
    await picker.getByRole('button',{name:'取消',exact:true}).click();
    await secondDetail.getByRole('button',{name:'返回列表',exact:true}).click();
    await other.getByRole('button',{name:'管理 Skill / 模板标签',exact:true}).click();
    await manager.getByRole('searchbox').fill('delete-shared-skill-tag');
    await manager.getByRole('status').filter({hasText:/共/}).waitFor();
    assert.equal(await manager.locator('.tbp-tag-manager-row').count(),0);
});
