import {test,expect} from '@playwright/test';

test.beforeEach(async({request})=>{await request.delete('/toolbox/media-library/folder-visits',{data:{}});});

test('deep directory visits persist and reopen automatically with direct history jumps',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('.directory-card').filter({hasText:'归档'}).locator('.directory-open').click();
  await page.locator('.directory-card').filter({hasText:'更深层'}).locator('.directory-open').click();
  await expect(page.locator('#breadcrumb')).toHaveText(info.root+'/归档/更深层');
  await expect.poll(async()=>(await(await request.get('/toolbox/media-library/folder-visits')).json()).items[0]?.path).toBe(info.root+'/归档/更深层');
  await page.reload();await expect(page.locator('#breadcrumb')).toHaveText(info.root+'/归档/更深层');
  await expect(page.locator('#search')).toHaveValue('');await expect(page.locator('#recursive')).not.toBeChecked();
  await page.locator('#recent').click();await expect(page.locator('#view-title')).toContainText('最近访问目录');
  await page.locator('#grid .directory-card').filter({hasText:'归档'}).filter({has:page.locator('strong',{hasText:/^归档$/})}).locator('.directory-open').click();
  await expect(page.locator('#breadcrumb')).toHaveText(info.root+'/归档');
  const rows=(await(await request.get('/toolbox/media-library/folder-visits')).json()).items;
  expect(rows.filter((row:any)=>row.path===info.root+'/归档')).toHaveLength(1);
  await page.screenshot({path:'test-results/media-library/recent-folders.png'});
});

test('explicit node asset location takes precedence over the last visited folder',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  const image=info.items.find((item:any)=>item.name==='海岸参考.png');
  await request.post('/toolbox/media-library/folder-visits',{data:{path:info.root+'/归档/更深层'}});
  await page.goto('/toolbox/media-library/gallery?current_id='+image.id);
  await expect(page.locator('#breadcrumb')).toHaveText(info.root);await expect(page.locator(`.card[data-id="${image.id}"]`)).toBeVisible();
});

test('copied metadata is structured JSON, while raw copying preserves source strings',async({page})=>{
  await page.addInitScript(()=>{
    Object.defineProperty(navigator,'clipboard',{value:{writeText:async(text:string)=>{(window as any).copiedMetadata=text;}},configurable:true});
  });
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('.card').filter({hasText:'海岸参考.png'}).click();await page.locator('#show-generation').click();
  await page.locator('#copy-generation').click();
  let copied=await page.evaluate(()=>JSON.parse((window as any).copiedMetadata));
  expect(typeof copied.raw.prompt).toBe('object');expect(typeof copied.raw.workflow).toBe('object');expect(copied.raw.prompt.seed.inputs.seed).toBe(123);
  await page.locator('#copy-generation-raw').click();copied=await page.evaluate(()=>JSON.parse((window as any).copiedMetadata));expect(typeof copied.raw.prompt).toBe('string');
  await page.locator('#show-all-info').click();await page.locator('#json-copy').click();copied=await page.evaluate(()=>JSON.parse((window as any).copiedMetadata));expect(copied.raw.workflow.nodes).toHaveLength(1);
});

test('regenerate preflights before confirmation and saves a new batch without changing the source',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();const image=info.items.find((item:any)=>item.name==='海岸参考.png');
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await page.locator(`.card[data-id="${image.id}"]`).click();
  await page.locator('#regenerate-image').click();const dialog=page.locator('#regeneration-dialog');
  await expect(dialog.getByText('预检通过。确认下方参数后再排队，不覆盖原图。')).toBeVisible();
  await expect(dialog).toContainText('保留原流程批次：2');await expect(dialog.locator('.regeneration-seeds code')).toContainText('123 →');
  expect((await(await request.get('/toolbox/media-library/regenerations?source_id='+image.id)).json()).items).toHaveLength(0);
  await dialog.getByRole('button',{name:'确认排队生成'}).click();await expect(dialog.locator('.regeneration-progress')).toContainText('生成完成',{timeout:10000});
  await expect(dialog.locator('.regeneration-progress button')).toHaveCount(2);await page.screenshot({path:'test-results/media-library/regeneration.png'});
  const jobs=(await(await request.get('/toolbox/media-library/regenerations?source_id='+image.id)).json()).items;
  expect(jobs).toHaveLength(1);expect(jobs[0].outputs).toHaveLength(2);
  expect(jobs[0].outputs.every((output:any)=>output.path.startsWith(info.root+'/海岸参考_regen_'))).toBe(true);
  const original=await(await request.get('/toolbox/media-library/detail?id='+image.id)).json();expect(JSON.parse(original.raw.prompt).seed.inputs.seed).toBe(123);
  await dialog.locator('.regeneration-progress button').first().click();await expect(page.locator('#detail-dialog .detail-name')).toContainText('海岸参考_regen_');
  const cleanup=await(await request.post('/toolbox/media-library/operations/plan',{data:{op:'delete',ids:jobs[0].outputs.map((output:any)=>output.id)}})).json();
  await request.post('/toolbox/media-library/operations/apply',{data:{token:cleanup.token,confirmed:true}});
});

test('unsupported metadata explains why regeneration cannot run',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();const path=info.root+'/归档/子目录图片.png';
  const detail=await(await request.get('/toolbox/media-library/detail?'+new URLSearchParams({path}))).json();
  await page.goto('/toolbox/media-library/gallery?current_id='+detail.id);await page.locator(`.card[data-id="${detail.id}"]`).click();await page.locator('#regenerate-image').click();
  await expect(page.locator('#regeneration-dialog')).toContainText('受支持的图片保存节点');await expect(page.getByRole('button',{name:'确认排队生成'})).toBeHidden();
});

test('structured metadata preserves the exact digits of large integer seeds',async({page})=>{
  await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async(text:string)=>{(window as any).copiedMetadata=text;}},configurable:true});});
  await page.route('**/toolbox/media-library/detail?*',async route=>{
    const response=await route.fetch(),value=await response.json();
    value.raw.prompt='{"seed":{"class_type":"Seed (rgthree)","inputs":{"seed":18446744073709551615,"text":"{\\"subject\\":\\"person\\"}"}}}';
    await route.fulfill({response,json:value});
  });
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();await page.locator('.card').filter({hasText:'海岸参考.png'}).click();await page.locator('#show-generation').click();await page.locator('#copy-generation').click();
  const copied=await page.evaluate(()=>JSON.parse((window as any).copiedMetadata));expect(copied.raw.prompt.seed.inputs.seed).toBe('18446744073709551615');
  expect(copied.raw.prompt.seed.inputs.text).toBe('{"subject":"person"}');
});
