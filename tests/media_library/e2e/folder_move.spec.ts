import {test,expect} from '@playwright/test';

for(const entry of ['card','tree','recent'])test(`directory move from ${entry} preserves asset IDs and follows the current folder`,async({page,request})=>{
  await request.delete('/toolbox/media-library/folder-visits',{data:{}});
  const {root}=await(await request.get('/fixture/info')).json();
  const name=`目录移动_${entry}`,source=root+'/'+name,destination=root+'/目标_'+entry,target=destination+'/'+name;
  const create=async(path:string,name:string)=>expect((await request.post('/toolbox/media-library/folders/create',{data:{path,name}})).ok()).toBeTruthy();
  const remove=async(path:string)=>{
    const plan=await request.post('/toolbox/media-library/folders/delete/plan',{data:{path}});
    if(plan.ok())expect((await request.post('/toolbox/media-library/folders/delete/apply',{data:{token:(await plan.json()).token,confirmed:true}})).ok()).toBeTruthy();
  };
  try{
    await create(root,name);await create(source,'nested');await create(root,'目标_'+entry);
    expect((await request.post('/upload/image',{multipart:{image:{name:'移动验证.txt',mimeType:'text/plain',buffer:Buffer.from('目录移动后仍可读取')},type:'input',subfolder:name+'/nested'}})).ok()).toBeTruthy();
    const file=await(await request.get('/toolbox/media-library/detail',{params:{path:source+'/nested/移动验证.txt'}})).json();
    await request.post('/toolbox/media-library/folder-visits',{data:{path:source}});
    await page.goto('/toolbox/media-library/gallery?current_id='+file.id);
    await expect(page.locator('#breadcrumb')).toHaveText(source+'/nested');
    if(entry==='card'){
      await page.locator('#roots .root-name').first().click();
      await page.locator(`.directory-card[data-path="${source}"]`).click({button:'right'});
    }else if(entry==='tree')await page.locator(`#roots .root-row[data-path="${source}"] .root-name`).click({button:'right'});
    else await page.locator('#recent-folders .recent-folder').filter({hasText:name}).filter({hasNotText:'nested'}).click({button:'right'});
    await page.locator('#asset-context-menu').getByRole('menuitem',{name:'移动目录',exact:true}).click();
    const dialog=page.locator('#operation-dialog');await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button',{name,exact:true})).toBeDisabled();
    await expect(page.locator('#apply-operation')).toBeDisabled();
    await dialog.getByRole('button',{name:'目标_'+entry,exact:true}).click();
    await expect(dialog.locator('.move-address')).toHaveText(destination);
    if(entry==='card'){
      await create(destination,name);await page.locator('#apply-operation').click();
      await expect(page.locator('#operation-list')).toContainText('已经存在');await expect(dialog).toBeVisible();await remove(target);
    }
    await page.screenshot({path:`test-results/media-library/folder-move-${entry}.png`});
    await page.locator('#apply-operation').click();await expect(dialog).toBeHidden();
    await expect(page.locator('#breadcrumb')).toHaveText(entry==='card'?root:target+'/nested');
    const updated=await(await request.get('/toolbox/media-library/detail',{params:{id:file.id}})).json();
    expect(updated.path).toBe(target+'/nested/移动验证.txt');expect(updated.text).toContain('目录移动后仍可读取');
    const old=await request.get('/toolbox/media-library/folders',{params:{path:source}});expect(old.ok()).toBe(false);
    const visits=await(await request.get('/toolbox/media-library/folder-visits')).json();
    expect(visits.items.some((visit:any)=>visit.path===source||visit.path.startsWith(source+'/'))).toBe(false);
    if(entry!=='card')await expect(page.locator('.card').filter({hasText:'移动验证.txt'})).toBeVisible();
  }finally{
    for(const path of [source,target]){
      const response=await request.get('/toolbox/media-library/detail',{params:{path:path+'/nested/移动验证.txt'}});
      if(response.ok()){
        const file=await response.json(),plan=await(await request.post('/toolbox/media-library/operations/plan',{data:{op:'delete',ids:[file.id]}})).json();
        await request.post('/toolbox/media-library/operations/apply',{data:{token:plan.token,confirmed:true}});
      }
      await remove(path+'/nested');await remove(path);
    }
    await remove(destination);
  }
});
