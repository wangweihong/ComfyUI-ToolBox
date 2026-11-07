import { test, expect } from '@playwright/test';

test('video plays, seeks, exposes metadata and keeps original path',async({page,request})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const fixture=await(await request.get('/fixture/info')).json();
  const item=fixture.items.find((i:any)=>i.kind==='video');
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  const fileCard=page.locator(`.card[data-id="${item.id}"]`);
  await expect(fileCard).not.toContainText(item.path);
  await expect(fileCard).toHaveAttribute('title',item.name);
  await expect(fileCard.locator('.card-path')).toHaveCount(0);
  await fileCard.click();
  await expect(page.locator('.detail-name')).toHaveText(item.name);
  await expect(page.locator('.path-box code')).toHaveText(item.path);
  await expect(page.locator('.property').filter({hasText:'宽高比'})).toContainText('16:9');
  await page.locator('#show-generation').click();
  await expect(page.locator('.generation-row').filter({hasText:'种子'}).first()).toContainText('123');
  await page.locator('#generation-close').click();
  const video=page.locator('video');
  await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.readyState)).toBeGreaterThanOrEqual(2);
  await video.evaluate((v:HTMLVideoElement)=>v.play());
  await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.currentTime)).toBeGreaterThan(.1);
  await video.evaluate((v:HTMLVideoElement)=>{v.pause();v.currentTime=2;});
  await expect.poll(()=>video.evaluate((v:HTMLVideoElement)=>v.currentTime)).toBeGreaterThanOrEqual(1.9);
  await page.screenshot({path:'test-results/media-library/gallery-video.png',fullPage:true});
  await page.getByRole('button',{name:'使用此文件'}).click();
  await page.locator('#recent').click();
  await expect(page.locator('.card[data-id="'+item.id+'"]').first()).toBeVisible();
  expect(errors).toEqual([]);
  await expect(page.locator('#view-title')).toContainText('最近使用');
});

test('text, PLY, ZIP and search work without interpreting archives',async({page})=>{
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('#search').fill('缓慢向前');
  await expect(page.locator('.card')).toHaveCount(1);
  await page.locator('.card').click();await expect(page.locator('.preview pre')).toContainText('柔和的逆光');
  await page.locator('.detail-top button').click();
  await page.locator('#search').fill('点云.ply');await expect(page.locator('.card-name')).toHaveText('点云.ply');await page.locator('.card').click();
  await expect(page.locator('.property').filter({hasText:'顶点数'})).toContainText('1024');
  await page.locator('.detail-top button').click();
  await page.locator('#search').fill('素材备份.zip');await expect(page.locator('.card-name')).toHaveText('素材备份.zip');await page.locator('.card').click();
  await expect(page.locator('.preview .file-glyph')).toHaveText('ZIP');
  await expect(page.locator('video,audio,.preview pre')).toHaveCount(0);
});

test('delete opens one confirmation with no preview step or extra checkbox',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();const item=info.items.find((i:any)=>i.kind==='ply');
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await page.locator(`.card[data-id="${item.id}"] input`).check();
  await page.locator('#bulk-delete').click();await expect(page.locator('#operation-list')).toContainText(item.name);
  await expect(page.locator('#plan-operation')).toBeHidden();
  await expect(page.locator('#operation-dialog input[type="checkbox"]')).toHaveCount(0);
  await expect(page.locator('#apply-operation')).toHaveText('永久删除');
  expect((await request.get('/toolbox/media-library/detail?id='+item.id)).ok()).toBeTruthy();
  await page.locator('#operation-cancel').click();expect((await request.get('/toolbox/media-library/detail?id='+item.id)).ok()).toBeTruthy();
});

test('node bridge scopes selection, persists ID, restores after rename and clears ID for manual path',async({page,request})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  const info=await(await request.get('/fixture/info')).json();const image=info.items.find((i:any)=>i.kind==='image');
  await page.goto('/fixture/comfy');await page.waitForFunction(()=>window['ready']);
  await page.locator('[data-node="1"] button').click();
  const gallery=page.frameLocator('dialog iframe');await gallery.locator('#roots .root-name').first().click();await gallery.locator(`.card[data-id="${image.id}"]`).click();await gallery.getByRole('button',{name:'使用此文件'}).click();
  await expect(page.locator('[data-node="1"]')).toHaveAttribute('data-path',image.path);
  await expect(page.locator('[data-node="2"]')).not.toHaveAttribute('data-path',image.path);
  const saved=await page.evaluate(()=>window['nodes'][0].widgets.map((w:any)=>w.value));
  const plan=await(await request.post('/toolbox/media-library/operations/plan',{data:{op:'rename',ids:[image.id],template:'重命名测试'}})).json();
  const applied=await(await request.post('/toolbox/media-library/operations/apply',{data:{token:plan.token,confirmed:true}})).json();expect(applied.results[0].ok).toBeTruthy();
  await page.evaluate(values=>window['createNode'](values),saved);
  await expect(page.locator('[data-node="3"]')).toHaveAttribute('data-path',/重命名测试\.png$/);
  const changed=info.items.find((i:any)=>i.kind==='text');
  await page.evaluate(path=>{const node=window['nodes'][0];node.widgets[0].value=path;node.widgets[0].callback();},changed.path);
  await expect(page.locator('[data-node="1"]')).toHaveAttribute('data-path',changed.path);
  const actualId=await page.evaluate(()=>window['nodes'][0].widgets[1].value);expect(actualId).toBe(changed.id);
  expect(errors).toEqual([]);
});

test('narrow layout keeps directory navigation and closeable modal detail',async({page})=>{
  await page.setViewportSize({width:760,height:900});await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('.card').first().click();await expect(page.locator('.detail.has-item')).toBeVisible();
  await page.locator('.detail-top button').click();await expect(page.locator('.detail')).toBeHidden();
});


test('viewer opens only on click and preserves search, selections and scroll on close',async({page})=>{
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await expect(page.locator('#detail-dialog')).toBeHidden();
  await page.locator('#search').fill('png');await expect(page.locator('.card')).toHaveCount(4);
  const card=page.locator('.card').first();await card.locator('input').check();
  await card.dblclick();await expect(page.locator('#detail-dialog')).toBeVisible();
  await page.keyboard.press('Escape');await expect(page.locator('#detail-dialog')).toBeHidden();
  await expect(page.locator('#search')).toHaveValue('png');await expect(card.locator('input')).toBeChecked();
  await page.screenshot({path:'test-results/media-library/gallery-overview.png',fullPage:true});
});


test('home does not load files, thumbs or scans; directories remain hierarchical until explicitly flattened',async({page,request})=>{
  const requests:string[]=[];page.on('request',r=>requests.push(r.url()));
  await page.goto('/toolbox/media-library/gallery');
  await expect(page.locator('.directory-card')).toHaveCount(1);
  await expect(page.locator('.card')).toHaveCount(0);
  await page.waitForTimeout(350);
  expect(requests.filter(u=>/\/toolbox\/media-library\/(files|thumb|file|scan)(?:[?]|$)/.test(u))).toEqual([]);
  await expect(page.locator('#recursive')).not.toBeChecked();
  await page.locator('.directory-card').click();
  await expect(page.locator('.directory-card')).toHaveCount(1);
  await expect(page.locator('.card-name').filter({hasText:'子目录图片.png'})).toHaveCount(0);
  const child=page.locator('.directory-card').filter({hasText:'归档'});
  await expect(child).toBeVisible();await child.click();
  await expect(page.locator('#recursive')).not.toBeChecked();
  await expect(page.locator('.card-name')).toHaveText(['子目录图片.png'],{timeout:10000});
  await expect(page.locator('.directory-card')).toHaveCount(1);
  await page.locator('#recursive').check();
  await expect(page.locator('.card')).toHaveCount(2,{timeout:10000});
  await expect(page.locator('.directory-card')).toHaveCount(0);
  await expect(page.locator('.card-name').filter({hasText:'深层文本.txt'})).toBeVisible();
  await page.locator('#parent').click();
  await expect(page.locator('#recursive')).not.toBeChecked();
  await expect(page.locator('.directory-card').filter({hasText:'归档'})).toBeVisible();
  await expect(page.locator('.card-name').filter({hasText:'子目录图片.png'})).toHaveCount(0);
  await page.screenshot({path:'test-results/media-library/directory-hierarchy.png'});
});

test('directory cards stay compact beside media and show folder icons at narrow widths',async({page,request})=>{
  const fixture=await(await request.get('/fixture/info')).json();
  const names=['.flashvsr_runtime','.h3_editor_models','clipspace','FlashVSR_Images','inpaint_tutorial','input','pixaroma','pose_gallery_video','图片','巨物','很长很长的中文目录名称_用于验证文字不会撑开卡片','very_long_directory_name_that_should_not_change_the_height'];
  await page.route('**/toolbox/media-library/folders?*',route=>route.fulfill({json:{folders:names.map((name,i)=>({name,path:fixture.root+'/folder_'+i}))}}));
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await expect(page.locator('.directory-card')).toHaveCount(names.filter(name=>!name.startsWith('.')).length);
  await expect(page.locator('.card').first()).toBeVisible();
  for(const width of [1440,620]){
    await page.setViewportSize({width,height:1100});
    const heights=await page.locator('.directory-card').evaluateAll(cards=>cards.map(card=>card.getBoundingClientRect().height));
    expect(Math.max(...heights)-Math.min(...heights)).toBeLessThanOrEqual(1);
    expect(Math.max(...heights)).toBeLessThanOrEqual(96);
    expect(await page.locator('.directory-card svg.folder-icon').count()).toBe(names.filter(name=>!name.startsWith('.')).length);
    expect(await page.locator('#roots .root-name svg.folder-icon').count()).toBeGreaterThan(0);
    expect(await page.locator('.directory-grid').evaluate(grid=>grid.getBoundingClientRect().bottom)).toBeLessThanOrEqual(await page.locator('.card').first().evaluate(card=>card.getBoundingClientRect().top));
  }
  await page.screenshot({path:'test-results/media-library/directory-compact-icons.png'});
});


test('custom generator JSON is readable and dimensions sit directly above ratio',async({page})=>{
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('.directory-card').filter({hasText:'归档'}).click();await page.locator('.card').filter({hasText:'子目录图片.png'}).click();
  await expect(page.getByText('未发现可识别的生成信息')).toHaveCount(0);
  const labels=await page.locator('.property dt').allTextContents();
  expect(labels).not.toContain('宽度（像素）');expect(labels).not.toContain('高度（像素）');
  expect(labels.indexOf('宽高比')).toBe(labels.indexOf('宽×高（像素）')+1);
  await expect(page.locator('.property').filter({hasText:'宽×高（像素）'})).toContainText('992 × 736');
  await page.screenshot({path:'test-results/media-library/structured-generation-dimensions.png'});
  await expect(page.locator('#generation-dialog')).toBeHidden();await page.locator('#show-generation').click();
  await expect(page.locator('#generation-dialog')).toBeVisible();
  await expect(page.locator('.generation-table thead th')).toHaveText(['标题','数据']);
  await expect(page.locator('.generation-row').filter({hasText:'提示词'})).toContainText('你好，海岸');
  await expect(page.locator('.generation-row').filter({hasText:'种子'})).toContainText('123');
  await page.screenshot({path:'test-results/media-library/generation-title-value-dialog.png'});
  await page.locator('#generation-close').click();await expect(page.locator('#detail-dialog')).toBeVisible();
});

test('move browses folders and .. then moves directly with one destination action',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();const item=info.items.find((i:any)=>i.kind==='ply');
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await page.locator(`.card[data-id="${item.id}"] input`).check();
  await page.locator('#bulk-move').click();const dialog=page.locator('#operation-dialog');
  await expect(dialog.locator('.move-address')).toHaveText(info.root);
  await expect(dialog.locator('#plan-operation')).toBeHidden();await expect(dialog.locator('input')).toHaveCount(0);
  await dialog.getByRole('button',{name:'归档',exact:true}).click();await expect(dialog.locator('.move-address')).toHaveText(info.root+'/归档');
  await dialog.getByRole('button',{name:'更深层',exact:true}).click();await expect(dialog.locator('.move-address')).toHaveText(info.root+'/归档/更深层');
  await dialog.getByRole('button',{name:'..',exact:true}).click();await expect(dialog.locator('.move-address')).toHaveText(info.root+'/归档');
  await expect(dialog.locator('#apply-operation')).toHaveText('移动到这里');await dialog.locator('#apply-operation').click();
  await expect(dialog).toBeHidden();const detail=await(await request.get('/toolbox/media-library/detail?id='+item.id)).json();expect(detail.path).toBe(info.root+'/归档/'+item.name);
});

test('single delete confirmation removes the selected file on confirm',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();const item=info.items.find((i:any)=>i.name==='素材备份.zip');
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await page.locator(`.card[data-id="${item.id}"] input`).check();
  await page.locator('#bulk-delete').click();await expect(page.locator('#apply-operation')).toBeVisible();await page.locator('#apply-operation').click();
  await expect(page.locator('#operation-dialog')).toBeHidden();expect((await request.get('/toolbox/media-library/detail?id='+item.id)).ok()).toBeFalsy();
});

test('toolbar opens once, cancels without adding and creates a selected path node only on use', async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  const item=info.items.find((item:any)=>item.kind==='image'&&item.path===info.root+'/'+item.name);
  await page.goto('/fixture/comfy');await page.waitForFunction(()=>window['ready']);
  await page.locator('#toolbar-library').click();
  await page.evaluate(()=>document.getElementById('toolbar-library')!.click());
  await expect(page.locator('dialog')).toHaveCount(1);
  expect(await page.evaluate(()=>window['mockApp'].canvas.graph.nodes.length)).toBe(2);
  await page.keyboard.press('Escape');await expect(page.locator('dialog')).toHaveCount(0);
  expect(await page.evaluate(()=>window['mockApp'].canvas.graph.nodes.length)).toBe(2);
  await page.locator('#toolbar-library').click();
  const gallery=page.frameLocator('dialog iframe');
  await gallery.locator('#roots .root-name').first().click();
  await gallery.locator(`.card[data-id="${item.id}"]`).click();
  await gallery.getByRole('button',{name:'使用此文件'}).click();
  await expect(page.locator('dialog')).toHaveCount(0);
  const state=await page.evaluate(()=>({values:window['selectedNode'].widgets.map((w:any)=>w.value),
    count:window['mockApp'].canvas.graph.nodes.length,history:window['mockApp'].canvas.graph.history.length}));
  expect(state).toEqual({values:[item.path,item.id],count:3,history:1});
});

test('iframe selection rejects messages from other windows and origins', async({page})=>{
  await page.goto('/fixture/comfy');await page.waitForFunction(()=>window['ready']);
  await page.locator('#toolbar-library').click();
  await page.evaluate(()=>{
    window.postMessage({type:'tb-media-library-select',id:'forged',path:'/wrong/file'},location.origin);
    const frame=document.querySelector<HTMLIFrameElement>('dialog iframe')!;
    window.dispatchEvent(new MessageEvent('message',{origin:'https://wrong.example',source:frame.contentWindow,
      data:{type:'tb-media-library-select',id:'forged',path:'/wrong/file'}}));
  });
  await expect(page.locator('dialog')).toHaveCount(1);
  expect(await page.evaluate(()=>window['mockApp'].canvas.graph.nodes.length)).toBe(2);
});

test('gallery upload uses the official endpoint and the new default upload directory', async({page})=>{
  const uploads:string[]=[];page.on('request',request=>{if(request.method()==='POST'&&request.url().includes('upload'))uploads.push(new URL(request.url()).pathname);});
  await page.goto('/toolbox/media-library/gallery');
  await page.locator('input[type="file"]').setInputFiles({name:'上传测试.txt',mimeType:'text/plain',buffer:Buffer.from('新素材库上传测试')});
  await expect(page.locator('.card-name').filter({hasText:'上传测试.txt'})).toBeVisible();
  expect(uploads).toEqual(['/upload/image']);
  await page.locator('.card-name').filter({hasText:'上传测试.txt'}).click();
  await expect(page.locator('.path-box code')).toContainText('/tb_media_library/上传测试.txt');
});
