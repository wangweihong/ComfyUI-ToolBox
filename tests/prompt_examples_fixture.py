"""Original-media browser fixture. Never reads/writes the real database or output."""
import argparse
import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from aiohttp import web
from nodes import prompt_nodes as prompts,prompt_examples as examples
from prompt_test_fixture import create_app

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lL8AAAAASUVORK5CYII=')


async def page(_request):
    return web.Response(content_type='text/html',text='''<!doctype html><html><head><meta charset="utf-8"><title>Prompt examples synthetic test</title></head><body>
    <button id="open">Prompt library</button><button id="delete">Delete synthetic image</button><button id="restore">Restore synthetic image</button>
    <button id="execute">Emit random execution</button><p id="mutation"></p>
    <script type="module">
    import {openPromptBrowser} from '/web/js/prompt_browser.mjs';
    import {attachExampleCounter} from '/web/js/prompt_examples.mjs';
    const api={fetchApi:(path,options)=>fetch(path,options)};
    document.querySelector('#open').onclick=()=>openPromptBrowser({request:(path,options)=>fetch('/toolbox/prompts'+path,options),currentId:1,onSelect:()=>{}});
    for(const kind of ['reader','random']){
        const section=document.createElement('section');section.setAttribute('aria-label',kind);section.append(kind);document.body.append(section);
        const node={widgets:kind==='reader'?[{name:'id',value:1}]:[],inputs:[],size:[350,180],setSize:()=>{},computeSize:()=>[350,180],setDirtyCanvas:()=>{},
            addDOMWidget:(name,type,content,options)=>{section.append(content);return {name,options};}};
        attachExampleCounter(node,{graph:{change:()=>{}}},api,{reader:kind==='reader',openBrowser:openPromptBrowser});
        if(kind==='random')document.querySelector('#execute').onclick=async()=>{const data=await(await fetch('/toolbox/prompts/1')).json();node.onExecuted({toolbox_prompt:[{id:1,shasum:data.shasum}]});};
    }
    for(const operation of ['delete','restore']) document.querySelector('#'+operation).onclick=async()=>{await fetch('/fixture/'+operation,{method:'POST'});document.querySelector('#mutation').textContent=operation+' completed';};
    </script></body></html>''')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18774);parser.add_argument('--many',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='toolbox-examples-fixture-') as directory:
        root=Path(directory);prompts.database.DEFAULT_DB=root/'prompts.sqlite3';examples.OUTPUT_ROOT=root/'output';examples.OUTPUT_ROOT.mkdir()
        writer=prompts.ToolBoxPromptWriter()
        writer.write_prompt(0,'Synthetic prompt for original examples','zh','image','natural',False,'plaintext',False,64,64,'synthetic')
        image=examples.OUTPUT_ROOT/'images/model/example.png';image.parent.mkdir(parents=True);image.write_bytes(PNG)
        manual=examples.OUTPUT_ROOT/'images/model/manual.png';manual.write_bytes(PNG)
        metadata=json.loads(prompts.ToolBoxPromptReader().read_prompt(1)[-1])
        examples.register({'prompt_id':1,'shasum':metadata['shasum'],'paths':[str(image)],'source':'generated'})
        if args.many:
            paths=[]
            for index in range(205):
                path=examples.OUTPUT_ROOT/f'images/model/batch-{index}.png';path.write_bytes(PNG);paths.append(str(path))
            for offset in range(0,len(paths),200):examples.register({'prompt_id':1,'shasum':metadata['shasum'],'paths':paths[offset:offset+200],'source':'generated'})
        app=create_app();app.router.add_get('/',page);app.router.add_static('/web',ROOT/'web')
        @web.middleware
        async def check_latency(request,handler):
            if request.path=='/toolbox/prompt-examples/check':await asyncio.sleep(0.4)
            return await handler(request)
        app.middlewares.append(check_latency)
        async def view(request):
            if request.query.get('type')!='output':raise web.HTTPBadRequest()
            target,_,_=examples.normalize_path(str(Path(request.query.get('subfolder',''))/request.query.get('filename','')))
            if not target.is_file():raise web.HTTPNotFound()
            return web.FileResponse(target)
        async def remove(_request):
            image.unlink(missing_ok=True);return web.json_response({'ok':True})
        async def restore(_request):
            image.write_bytes(PNG);return web.json_response({'ok':True})
        app.router.add_get('/view',view);app.router.add_post('/fixture/delete',remove);app.router.add_post('/fixture/restore',restore)
        print(f'Synthetic output root: {examples.OUTPUT_ROOT}',flush=True)
        web.run_app(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
