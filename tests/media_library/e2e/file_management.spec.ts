import {test,expect,APIRequestContext} from '@playwright/test';

test.beforeEach(async({request})=>{await request.delete('/toolbox/media-library/folder-visits',{data:{}});});

async function removeTestFolder(request:APIRequestContext,path:string){
  const files=await(await request.get('/toolbox/media-library/files',{params:{folder:path,recursive:'1'}})).json();
  if(files.items?.length){
    const plan=await(await request.post('/toolbox/media-library/operations/plan',{data:{op:'delete',ids:files.items.map((item:any)=>item.id)}})).json();
    await request.post('/toolbox/media-library/operations/apply',{data:{token:plan.token,confirmed:true}});
  }
  const response=await request.post('/toolbox/media-library/folders/delete/plan',{data:{path}});
  if(response.ok())await request.post('/toolbox/media-library/folders/delete/apply',{data:{token:(await response.json()).token,confirmed:true}});
}

test('context menu renames and moves selected assets then deletes the empty folder',async({page,request})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  const info=await(await request.get('/fixture/info')).json(),path=info.root+'/右键管理测试';
  try{
    await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
    await page.locator('#new-folder').click();await page.locator('#new-folder-name').fill('右键管理测试');await page.locator('#folder-action-submit').click();
    await expect(page.locator('#folder-action-dialog')).toBeHidden();await expect(page.locator(`.directory-card[data-path="${path}"]`)).toBeVisible();
    for(const name of ['右键文件一.txt','右键文件二.txt'])expect((await request.post('/upload/image',{multipart:{image:{name,mimeType:'text/plain',buffer:Buffer.from(name)},type:'input'}})).ok()).toBeTruthy();
    await page.locator('#scan').click();await expect(page.locator('.card').filter({hasText:'右键文件一.txt'})).toBeVisible();
    const first=page.locator('.card').filter({hasText:'右键文件一.txt'}),second=page.locator('.card').filter({hasText:'右键文件二.txt'});
    await first.locator('input').check();await second.locator('input').check();await first.click({button:'right'});
    const menu=page.locator('#asset-context-menu');await expect(menu).toContainText('已选择 2 项素材');
    await expect(menu.getByRole('menuitem')).toHaveText(['重命名所选 2 项','移动所选 2 项','删除所选 2 项']);
    await menu.getByRole('menuitem',{name:'重命名所选 2 项'}).click();await page.locator('#rename-template').fill('已改名_{index:02d}');await page.locator('#plan-operation').click();await page.locator('#apply-operation').click();
    await expect(page.locator('#operation-dialog')).toBeHidden();
    const renamed=page.locator('.card').filter({hasText:/已改名_0[12]\.txt/});await expect(renamed).toHaveCount(2);
    await renamed.nth(0).locator('input').check();await renamed.nth(1).locator('input').check();await renamed.first().click({button:'right'});
    await menu.getByRole('menuitem',{name:'移动所选 2 项'}).click();await page.locator('.move-directories').getByRole('button',{name:'右键管理测试',exact:true}).click();await page.locator('#apply-operation').click();
    await expect(page.locator('#operation-dialog')).toBeHidden();await expect(renamed).toHaveCount(0);
    const folder=page.locator(`.directory-card[data-path="${path}"]`);await folder.click({button:'right'});await menu.getByRole('menuitem',{name:'删除空目录'}).click();
    await expect(page.locator('#folder-action-error')).toContainText('只能删除空目录');await expect(page.locator('#folder-action-submit')).toBeDisabled();await page.locator('[data-close="folder-action-dialog"]').last().click();
    await folder.locator('.directory-open').click();await expect(page.locator('.card')).toHaveCount(2);
    for(const input of await page.locator('.card input').all())await input.check();
    await page.locator('.card').first().click({button:'right'});await menu.getByRole('menuitem',{name:'删除所选 2 项'}).click();await page.locator('#apply-operation').click();await expect(page.locator('#operation-dialog')).toBeHidden();
    await page.locator('#roots .root-row').first().locator('button').first().click();
    const current=page.locator(`#roots .root-row[data-path="${path}"]`);await current.locator('.root-name').click({button:'right'});await menu.getByRole('menuitem',{name:'删除空目录'}).click();
    await expect(page.locator('#folder-action-submit')).toBeEnabled();await page.screenshot({path:'test-results/media-library/delete-empty-folder.png'});await page.locator('#folder-action-submit').click();
    await expect(page.locator('#folder-action-dialog')).toBeHidden();await expect(page.locator('#breadcrumb')).toHaveText(info.root);await expect(folder).toHaveCount(0);
    const visits=await(await request.get('/toolbox/media-library/folder-visits')).json();expect(visits.items.some((visit:any)=>visit.path===path)).toBe(false);
    expect(errors).toEqual([]);
  }finally{
    // Remove only files created by this test if an earlier UI assertion failed.
    for(const folder of [path,info.root]){
      const listing=await(await request.get('/toolbox/media-library/files',{params:{folder}})).json();
      const ids=(listing.items||[]).filter((item:any)=>/^(右键文件[一二]|已改名_0[12])\.txt$/.test(item.name)).map((item:any)=>item.id);
      if(ids.length){const plan=await(await request.post('/toolbox/media-library/operations/plan',{data:{op:'delete',ids}})).json();await request.post('/toolbox/media-library/operations/apply',{data:{token:plan.token,confirmed:true}});}
    }
    await removeTestFolder(request,path);
  }
});

test('directory creation detects conflicts and a file arriving after confirmation prevents deletion',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json(),path=info.root+'/空目录限制测试';
  try{
    await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click({button:'right'});
    const menu=page.locator('#asset-context-menu');await expect(menu.getByRole('menuitem',{name:'删除空目录'})).toBeDisabled();
    await menu.getByRole('menuitem',{name:'新建目录'}).click();await page.locator('#new-folder-name').fill('空目录限制测试');await page.locator('#folder-action-submit').click();await expect(page.locator('#folder-action-dialog')).toBeHidden();
    await page.locator('#roots .root-name').first().click();await page.locator('#new-folder').click();await page.locator('#new-folder-name').fill('空目录限制测试');await page.locator('#folder-action-submit').click();await expect(page.locator('#folder-action-error')).toContainText('已经存在');await page.keyboard.press('Escape');
    const folder=page.locator(`.directory-card[data-path="${path}"]`);await folder.locator('.directory-open').focus();await page.keyboard.press('Shift+F10');
    await expect(menu).toBeVisible();await expect(menu.getByRole('menuitem')).toHaveText(['新建目录','重命名目录','删除空目录']);
    await page.screenshot({path:'test-results/media-library/folder-context-menu.png'});
    await menu.getByRole('menuitem',{name:'删除空目录'}).click();await expect(page.locator('#folder-action-submit')).toBeEnabled();
    await request.post('/upload/image',{multipart:{image:{name:'.hidden',mimeType:'text/plain',buffer:Buffer.from('keep')},type:'input',subfolder:'空目录限制测试'}});
    await page.locator('#folder-action-submit').click();await expect(page.locator('#folder-action-error')).toContainText('只能删除空目录');await expect(page.locator('#folder-action-submit')).toBeDisabled();
    const detail=await request.get('/toolbox/media-library/detail',{params:{path:path+'/.hidden'}});expect(detail.ok()).toBeTruthy();
  }finally{await removeTestFolder(request,path);}
});
