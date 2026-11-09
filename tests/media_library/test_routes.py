import asyncio
import json
import subprocess
import sqlite3
from unittest.mock import patch
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
from PIL import Image
from support import register_routes

@pytest.fixture
async def client(lib):
    app=web.Application();routes=web.RouteTableDef();register_routes(routes,lambda:lib);app.add_routes(routes)
    async with TestClient(TestServer(app)) as client: yield client

async def test_routes_select_and_range(client,lib):
    root=Path(lib.roots()[0]['path']);p=root/'data.mp4';p.write_bytes(bytes(range(256))*40);fid=lib.upsert(p)
    response=await client.get('/toolbox/media-library/file?id='+fid,headers={'Range':'bytes=10-19'})
    assert response.status==206 and await response.read()==p.read_bytes()[10:20]
    assert response.headers['Content-Range']=='bytes 10-19/10240'
    response=await client.post('/toolbox/media-library/select',json={'id':fid})
    assert response.status==200 and (await response.json())['path']==str(p)
    assert lib.files(recent=True)['total']==1

async def test_unknown_file_is_attachment(client,lib):
    p=Path(lib.roots()[0]['path'])/'page.html';p.write_text('<script>alert(1)</script>');fid=lib.upsert(p)
    response=await client.get('/toolbox/media-library/file?id='+fid)
    assert response.headers['Content-Type']=='application/octet-stream'
    assert response.headers['Content-Disposition']=='attachment'

async def test_operation_confirmation_and_origin(client,lib):
    p=Path(lib.roots()[0]['path'])/'a.txt';p.write_text('A');fid=lib.upsert(p)
    response=await client.post('/toolbox/media-library/operations/plan',json={'op':'delete','ids':[fid]})
    plan=await response.json()
    response=await client.post('/toolbox/media-library/operations/apply',json={'token':plan['token']})
    assert response.status==400 and p.exists()
    response=await client.post('/toolbox/media-library/operations/apply',json={'token':plan['token'],'confirmed':True},headers={'Origin':'https://evil.example'})
    assert response.status==400 and p.exists()
    response=await client.post('/toolbox/media-library/operations/apply',data=json.dumps({'token':plan['token'],'confirmed':True}))
    assert response.status==400 and p.exists()
    response=await client.post('/toolbox/media-library/operations/apply',json={'token':plan['token'],'confirmed':True})
    assert response.status==200 and not p.exists()

async def test_concurrent_thumbnails(client,lib):
    p=Path(lib.roots()[0]['path'])/'a.png';Image.new('RGB',(160,90),'blue').save(p);fid=lib.upsert(p)
    results=await asyncio.gather(*(client.get('/toolbox/media-library/thumb?id='+fid) for _ in range(5)))
    assert [r.status for r in results]==[200]*5
    for r in results: assert (await r.read()).startswith(b'RIFF')

async def test_actual_video_metadata_and_preview(client,lib):
    root=Path(lib.roots()[0]['path']);p=root/'影片.mkv'
    params='海边人物\nNegative prompt: blurry\nSteps: 12, Sampler: Euler, CFG scale: 3, Seed: 123, Model: video-test'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','1','-c:v','mpeg4','-metadata','comment='+params,str(p)],check=True)
    fid=lib.upsert(p);item=lib.detail(fid)
    assert item['properties']['width']==320 and item['properties']['height']==180
    assert item['properties']['fps']==12 and item['properties']['duration']>=1
    assert item['summary']['seed']=='123'
    assert item['summary']['positive']=='海边人物'
    for _ in range(60):
        response=await client.post('/toolbox/media-library/preview',json={'id':fid});job=await response.json()
        if job['state'] in ('ready','error'): break
        await asyncio.sleep(.1)
    assert job['state']=='ready',job
    response=await client.get(job['url'],headers={'Range':'bytes=0-15'})
    assert response.status==206
    assert lib.resolve(fid)==p
    # Evicting a finished cache must schedule a new job, not return a stale ready URL.
    for cached in lib.cache.glob(fid+'-*.mp4'): cached.unlink()
    response=await client.post('/toolbox/media-library/preview',json={'id':fid})
    assert (await response.json())['state'] in ('queued','running')
    for _ in range(60):
        response=await client.post('/toolbox/media-library/preview',json={'id':fid});job=await response.json()
        if job['state'] in ('ready','error'): break
        await asyncio.sleep(.1)
    assert job['state']=='ready',job

async def test_static_gallery_and_assets(client):
    response=await client.get('/toolbox/media-library/gallery')
    assert response.status==200
    assert '素材库' in await response.text()

async def test_default_browse_is_unscoped_empty_and_recursion_is_opt_in(client,lib):
    root=Path(lib.roots()[0]['path']);(root/'sub').mkdir()
    (root/'top.txt').write_text('a');(root/'sub'/'child.txt').write_text('b');lib.scan(recursive=True)
    response=await client.get('/toolbox/media-library/files')
    assert (await response.json())['total']==0
    response=await client.get('/toolbox/media-library/files?root_id='+lib.roots()[0]['id'])
    assert [r['name'] for r in (await response.json())['items']]==['top.txt']
    response=await client.get('/toolbox/media-library/files?root_id='+lib.roots()[0]['id']+'&recursive=1')
    assert (await response.json())['total']==2


async def test_directory_rename_updates_detail_path_and_checks_origin(client,lib):
    root=Path(lib.roots()[0]['path']);source=root/'before';source.mkdir()
    file=source/'file.txt';file.write_text('original');file_id=lib.upsert(file)
    response=await client.post('/toolbox/media-library/folders/rename',json={'path':str(source),'name':'after'},headers={'Origin':'https://other.example'})
    assert response.status==400 and source.exists()
    response=await client.post('/toolbox/media-library/folders/rename',json={'path':str(source),'name':'after'})
    assert response.status==200
    assert (await response.json())['path']==str(root/'after')
    response=await client.get('/toolbox/media-library/detail',params={'id':file_id})
    assert (await response.json())['path']==str(root/'after'/'file.txt')
    response=await client.get('/toolbox/media-library/folders',params={'path':str(root)})
    assert (await response.json())['folders']==[{'name':'after','path':str(root/'after')}]


async def test_file_list_exposes_neighbors_in_the_same_query(client,lib):
    root=Path(lib.roots()[0]['path']);ids=[]
    for name in ['first.txt','second.txt','third.zip']:
        path=root/name;path.write_text('text');ids.append(lib.upsert(path))
    response=await client.get('/toolbox/media-library/files',params={'root_id':lib.roots()[0]['id'],'sort':'name','direction':'asc','kind':'text','focus_id':ids[0],'limit':'1'})
    result=await response.json()
    assert result['focus']=={'position':0,'previous_id':None,'next_id':ids[1]}
    assert result['total']==2 and len(result['items'])==1


async def test_rename_validation_and_database_errors_are_reported(client,lib):
    root=Path(lib.roots()[0]['path']);source=root/'before';source.mkdir()
    response=await client.post('/toolbox/media-library/folders/rename',json={'path':str(source),'name':'../escape'})
    assert response.status==400 and source.exists()
    with patch.object(lib,'rename_folder',side_effect=sqlite3.OperationalError('database is locked')):
        response=await client.post('/toolbox/media-library/folders/rename',json={'path':str(source),'name':'after'})
    assert response.status==503 and 'database is locked' in (await response.json())['error']
