// Uses a temporary synthetic database and output directory only.
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
    server=spawn(process.env.PROMPT_TEST_PYTHON||'python3',['-u','tests/prompt_examples_fixture.py','--port',String(port)],{stdio:['ignore','pipe','pipe']});
    let logs='';server.stdout.on('data',data=>{logs+=data;});server.stderr.on('data',data=>{logs+=data;});
    for(let attempt=0;attempt<100;attempt++){
        if(server.exitCode!==null)throw new Error(logs);
        try{if((await fetch(base)).ok)break;}catch{}
        if(attempt===99)throw new Error(`Fixture did not start: ${logs}`);
        await new Promise(resolve=>setTimeout(resolve,50));
    }
    browser=await chromium.launch({headless:true});
});
after(async()=>{await browser?.close();if(server&&server.exitCode===null){server.kill('SIGTERM');await once(server,'exit');}});

test('example unlink checkbox cancels safely, preserves files by default and deletes files when checked',async t=>{
    const page=await browser.newPage();t.after(()=>page.close());
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);
    await page.locator('section[aria-label="reader"]').getByRole('button',{name:'查看示例',exact:true}).click();
    await page.locator('.tbp-example-item').waitFor();
    const item=(await (await page.request.get(`${base}/toolbox/prompt-examples`)).json()).items[0];
    const confirmation=page.locator('.tbp-example-confirm');
    const remove=page.getByRole('button',{name:'移除关联',exact:true});
    await remove.click();
    const checkbox=confirmation.getByRole('checkbox',{name:'同步移除示例素材',exact:true});
    assert.equal(await checkbox.isChecked(),false);
    await checkbox.check();await confirmation.getByRole('button',{name:'取消操作',exact:true}).click();
    assert.equal((await page.request.get(`${base}${item.url}`)).status(),200);
    assert.equal((await (await page.request.get(`${base}/toolbox/prompt-examples`)).json()).total,1);

    await remove.click();assert.equal(await checkbox.isChecked(),false);
    const unlinked=page.waitForResponse(response=>response.request().method()==='DELETE');
    await confirmation.getByRole('button',{name:'确认移除关联',exact:true}).click();
    assert.deepEqual((await unlinked).request().postDataJSON(),{delete_file:false});
    await page.locator('.tbp-example-item').waitFor({state:'detached'});
    assert.equal((await page.request.get(`${base}${item.url}`)).status(),200);

    const response=await page.request.post(`${base}/toolbox/prompt-examples/register`,{data:{prompt_id:1,shasum:item.prompt_shasum,paths:[item.relative_path]}});
    assert.equal(response.status(),200);
    await page.getByRole('button',{name:'刷新示例列表',exact:true}).click();
    await remove.click();await checkbox.check();
    const deleted=page.waitForResponse(response=>response.request().method()==='DELETE');
    await confirmation.getByRole('button',{name:'确认移除关联并删除素材',exact:true}).click();
    assert.deepEqual((await deleted).request().postDataJSON(),{delete_file:true});
    await page.locator('.tbp-example-item').waitFor({state:'detached'});
    assert.equal((await page.request.get(`${base}${item.url}`)).status(),404);
    assert.equal((await (await page.request.get(`${base}/toolbox/prompt-examples`)).json()).total,0);
    assert.deepEqual(errors,[]);
});
