"""Isolated sample library for browser tests; never reads a real ComfyUI directory."""
import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from aiohttp import web
from PIL import Image, ImageDraw, PngImagePlugin
from support import Library, register_routes, ROOT, PROJECT

parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8919);args=parser.parse_args()
temp=tempfile.TemporaryDirectory(prefix='tb-media-library-qa-');base=Path(temp.name)
root=base/'素材';root.mkdir();(root/'归档').mkdir()
lib=Library(base/'data'/'prompts.sqlite3',base/'cache',{'input':str(root)})
extra=PngImagePlugin.PngInfo();extra.add_text('parameters','a quiet coastline, cinematic light\nNegative prompt: blurry\nSteps: 20, Sampler: Euler, CFG scale: 6, Seed: 20261105, Model: coastline-v1')
# Generated geometry makes visual fixtures deterministic and avoids any external material.
for n,(name,color) in enumerate([('海岸参考.png','#446b76'),('光影研究.png','#a28268'),('角色构图.png','#657384'),('森林色彩.png','#526d5a')]):
    im=Image.new('RGB',(960,640),color);draw=ImageDraw.Draw(im)
    draw.ellipse((400,-150,1050,500),fill=['#c3d4cf','#ddc6a9','#a8b7c6','#9db9a1'][n]);draw.polygon([(0,540),(550,160),(960,640),(0,640)],fill=['#264958','#625044','#323e54','#314b3a'][n]);im.save(root/name,pnginfo=extra)
(root/'拍摄提示词.txt').write_text('清晨海岸，人物站在远处，柔和的逆光。\n镜头缓慢向前推进。',encoding='utf-8')
(root/'点云.ply').write_text('ply\nformat ascii 1.0\nelement vertex 1024\nproperty float x\nproperty float y\nproperty float z\nelement face 0\nend_header\n')
(root/'素材备份.zip').write_bytes(b'PK\x05\x06'+bytes(18))
subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-metadata','comment=中文海岸视频\nNegative prompt: blurry\nSteps: 12, Sampler: Euler, CFG scale: 3, Seed: 123, Model: video-test',str(root/'海岸运动.mp4')],check=True)
subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=220:duration=2','-c:a','pcm_s16le',str(root/'环境音.wav')],check=True)
(root/'归档'/'更深层').mkdir()
custom=PngImagePlugin.PngInfo();custom.add_text('prompt',json.dumps({'9':{'class_type':'Drama3Generate','inputs':{'text':'你好，海岸','seed':123,'temperature':0.7}}}))
Image.new('RGB',(992,736),'red').save(root/'归档'/'子目录图片.png',pnginfo=custom)
(root/'归档'/'更深层'/'深层文本.txt').write_text('深层内容')
lib.scan()
app=web.Application();routes=web.RouteTableDef();register_routes(routes,lambda:lib);app.add_routes(routes)

async def script(request):
    name=request.match_info['name']
    if name=='app.js':return web.Response(text='export const app=window.mockApp;',content_type='text/javascript')
    if name=='api.js':return web.Response(text='export const api={apiURL:x=>x};',content_type='text/javascript')
    return web.FileResponse(PROJECT/'web'/'js'/name)
app.router.add_get('/scripts/{name}',script)
app.router.add_get('/extensions/ComfyUI-ToolBox/js/{name}',script)
async def comfy(request):
    return web.FileResponse(PROJECT/'tests'/'media_library'/'comfy_fixture.html')
app.router.add_get('/fixture/comfy',comfy)
async def info(request):
    return web.json_response({'root':str(root),'items':lib.files()['items']})
app.router.add_get('/fixture/info',info)

async def upload(request):
    form = await request.post()
    image = form['image']
    folder = (root / str(form.get('subfolder', ''))).resolve()
    if not folder.is_relative_to(root):
        raise web.HTTPBadRequest()
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(image.filename).name
    target = folder / name
    if target.exists():
        raise web.HTTPConflict()
    target.write_bytes(image.file.read())
    return web.json_response({'name': name, 'subfolder': str(folder.relative_to(root)), 'type': 'input'})
app.router.add_post('/upload/image', upload)
web.run_app(app,host='127.0.0.1',port=args.port,print=lambda *x:print(*x,flush=True))
