import {test,expect} from '@playwright/test';

test.beforeEach(async({request})=>{await request.delete('/toolbox/media-library/folder-visits',{data:{}});});

test('viewer buttons and arrow keys follow the filtered order and respect other dialogs',async({page})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('#search').fill('png');await expect(page.locator('.card')).toHaveCount(4);
  const names=await page.locator('.card-name').allTextContents();
  await page.locator('.card input').first().check();await page.locator('.card').first().dblclick();
  await expect(page.locator('#detail-previous')).toBeDisabled();await expect(page.locator('#detail-next')).toBeEnabled();
  await expect(page.locator('#detail-position')).toHaveText('1 / 4');
  await page.locator('#detail-next').click();await expect(page.locator('.detail-name')).toHaveText(names[1]);
  await expect(page.locator('#detail-previous')).toBeEnabled();await page.keyboard.press('ArrowLeft');
  await expect(page.locator('.detail-name')).toHaveText(names[0]);await expect(page.locator('#detail-previous')).toBeDisabled();
  await page.keyboard.press('ArrowLeft');await expect(page.locator('.detail-name')).toHaveText(names[0]);
  await page.locator('#show-generation').click();await expect(page.locator('#generation-dialog')).toBeVisible();
  await page.keyboard.press('ArrowRight');await expect(page.locator('.detail-name')).toHaveText(names[0]);
  await page.locator('#generation-close').click();
  await page.locator('#detail .file-actions').getByRole('button',{name:'重命名',exact:true}).click();
  await page.locator('#rename-template').focus();await page.keyboard.press('ArrowRight');
  await expect(page.locator('.detail-name')).toHaveText(names[0]);await page.locator('#operation-cancel').click();
  await page.locator('#detail-next').focus();await page.keyboard.press('ArrowRight');
  await expect(page.locator('.detail-name')).toHaveText(names[1]);await expect(page.locator('#detail-next')).toBeEnabled();
  await page.screenshot({path:'test-results/media-library/viewer-navigation.png'});
  await page.setViewportSize({width:390,height:844});
  expect(await page.locator('.detail-top').evaluate(node=>node.scrollWidth<=node.clientWidth)).toBe(true);
  await page.screenshot({path:'test-results/media-library/viewer-navigation-mobile.png'});
  await page.keyboard.press('Escape');await expect(page.locator('#detail-dialog')).toBeHidden();
  await expect(page.locator('#search')).toHaveValue('png');await expect(page.locator('.card input').first()).toBeChecked();
  expect(errors).toEqual([]);
});

test('directory rename handles conflicts and follows the current directory after success',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await expect(page.locator('#rename-folder')).toBeHidden(); // The ComfyUI input root is fixed.
  const source=info.root+'/归档',target=info.root+'/归档已改名';
  const listing=await(await request.get('/toolbox/media-library/files',{params:{folder:source,recursive:'1'}})).json();
  const item=listing.items.find((item:any)=>item.name==='子目录图片.png');expect(item).toBeTruthy();
  await page.locator('.directory-card').filter({hasText:'归档'}).locator('.folder-rename').click();
  const dialog=page.locator('#folder-rename-dialog');await expect(dialog).toBeVisible();
  await expect(page.locator('#folder-name')).toHaveValue('归档');
  await page.locator('#folder-name').fill('海岸参考.png');await page.locator('#folder-rename-submit').click();
  await expect(page.locator('#folder-rename-error')).toContainText('已经存在');await expect(dialog).toBeVisible();
  await page.locator('#folder-name').fill('归档已改名');await page.locator('#folder-rename-submit').click();
  await expect(dialog).toBeHidden();
  try{
    const folder=page.locator('.directory-card').filter({hasText:'归档已改名'});await expect(folder).toBeVisible();
    expect((await(await request.get('/toolbox/media-library/detail',{params:{id:item.id}})).json()).path).toBe(target+'/子目录图片.png');
    await folder.locator('.directory-open').click();await expect(page.locator('#breadcrumb')).toHaveText(target);
    await page.locator('#rename-folder').click();await page.locator('#folder-name').fill('归档');await page.locator('#folder-rename-submit').click();
    await expect(dialog).toBeHidden();await expect(page.locator('#breadcrumb')).toHaveText(source);
    await expect(page.locator('.card-name').filter({hasText:'子目录图片.png'})).toBeVisible();
    expect((await(await request.get('/toolbox/media-library/detail',{params:{id:item.id}})).json()).path).toBe(source+'/子目录图片.png');
  }finally{
    const response=await request.get('/toolbox/media-library/folders',{params:{path:info.root}});
    if((await response.json()).folders.some((folder:any)=>folder.path===target))await request.post('/toolbox/media-library/folders/rename',{data:{path:target,name:'归档'}});
  }
});

test('arrow keys switch assets when the video player has focus',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  const video=info.items.find((item:any)=>item.kind==='video');expect(video).toBeTruthy();
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator(`.card[data-id="${video.id}"]`).click();
  await expect(page.locator('#detail-next')).toBeEnabled();await page.locator('video').focus();
  await page.keyboard.press('ArrowRight');await expect(page.locator('.detail-name')).not.toHaveText(video.name);
  await expect(page.locator('#detail-previous')).toBeEnabled();await page.keyboard.press('ArrowLeft');
  await expect(page.locator('.detail-name')).toHaveText(video.name);
});

test('arrow navigation reaches the next server page without loading all assets',async({page,request})=>{
  const info=await(await request.get('/fixture/info')).json();
  await Promise.all(Array.from({length:83},(_,index)=>request.post('/upload/image',{multipart:{
    image:{name:`${String(index).padStart(3,'0')}.txt`,mimeType:'text/plain',buffer:Buffer.from(`page ${index}`)},type:'input',subfolder:'键盘分页',
  }}).then(response=>expect(response.ok()).toBeTruthy())));
  await page.goto('/toolbox/media-library/gallery');await page.locator('#roots .root-name').first().click();
  await page.locator('.directory-card').filter({hasText:'键盘分页'}).locator('.directory-open').click();
  await page.locator('#sort').selectOption('name');await page.locator('#direction').click();
  await expect(page.locator('.card')).toHaveCount(80);await expect(page.locator('#more')).toBeVisible();
  await expect(page.getByText('080.txt',{exact:true})).toHaveCount(0);
  await page.getByText('079.txt',{exact:true}).click();await expect(page.locator('#detail-next')).toBeEnabled();
  await expect(page.locator('#detail-position')).toHaveText('80 / 83');
  for(const name of ['080.txt','081.txt','082.txt']){
    await page.keyboard.press('ArrowRight');await expect(page.locator('.detail-name')).toHaveText(name);
    if(name!=='082.txt')await expect(page.locator('#detail-next')).toBeEnabled();
  }
  await expect(page.locator('#detail-next')).toBeDisabled();await expect(page.locator('#detail-position')).toHaveText('83 / 83');
  await page.keyboard.press('ArrowRight');await expect(page.locator('.detail-name')).toHaveText('082.txt');
  await page.keyboard.press('ArrowLeft');await expect(page.locator('.detail-name')).toHaveText('081.txt');
  await page.keyboard.press('Escape');await expect(page.locator('#breadcrumb')).toHaveText(info.root+'/键盘分页');
  await expect(page.locator('#sort')).toHaveValue('name');
});
