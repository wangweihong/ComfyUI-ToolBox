"""Tag selector integration fixture. All writes use a disposable database."""
import argparse
import importlib
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from aiohttp import web
from nodes import prompt_nodes,skill_library


def create_app():
    routes=web.RouteTableDef()
    server=types.ModuleType('server');server.PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
    with patch.dict(sys.modules,{'server':server}):
        for name in ('nodes.prompt_routes','nodes.skill_routes'):
            existing=name in sys.modules
            module=importlib.import_module(name)
            if existing:module.register_routes()
    app=web.Application(client_max_size=45*1024*1024);app.add_routes(routes);return app


async def page(_request):
    return web.Response(content_type='text/html',text='''<!doctype html><html><head><meta charset="utf-8"><title>Tag picker synthetic test</title></head><body>
    <button id="prompts">Prompt library</button><button id="skills">Skill library</button>
    <button id="failure">Toggle catalog failure</button><button id="connected">Toggle random connection</button>
    <button id="restore">Restore writer tags</button><button id="save-writer">Execute synthetic writer</button><button id="remove">Remove nodes</button>
    <p id="report"></p><p id="failure-status">Catalog available</p><p id="save-status"></p>
    <script type="module">
    import {attachNodeTags} from '/web/js/tag_picker.mjs';
    import {openPromptBrowser} from '/web/js/prompt_browser.mjs';
    import {openSkillBrowser} from '/web/js/skill_browser.mjs';
    let fail=false;
    const api={fetchApi:(path,options)=>fail&&path.includes('/tags?')?Promise.resolve(new Response(JSON.stringify({error:'Synthetic catalog unavailable'}),{status:503})):fetch(path,options)};
    document.querySelector('#failure').onclick=()=>{fail=!fail;document.querySelector('#failure-status').textContent=fail?'Catalog unavailable':'Catalog available'};
    const nodes=[];
    for(const kind of ['writer','random']){
        const section=document.createElement('section');section.setAttribute('aria-label',kind);document.body.append(section);
        const node={widgets:[{name:'first',value:'keep-position'},{name:'tags',value:kind==='random'?'legacy-missing':''},{name:'last',value:9}],inputs:[],size:[350,300],
            computeSize:()=>[350,300],setSize:size=>node.size=size,setDirtyCanvas:()=>{},
            addDOMWidget:(name,type,content,options)=>{section.append(content);node.control=content;const widget={name,options,serializeValue:()=>undefined};node.widgets.push(widget);return widget;},
        };
        attachNodeTags(node,{graph:{change:()=>report()}},api,{allowCreate:kind==='writer'});nodes.push(node);
    }
    function report(){document.querySelector('#report').textContent=JSON.stringify(nodes.map(node=>({tags:node.widgets[1].value,names:node.widgets.map(w=>w.name),connected:node.inputs[0]?.link!=null})));}
    report();
    document.querySelector('#connected').onclick=()=>{const node=nodes[1];node.inputs=[{name:'tags',link:node.inputs[0]?.link==null?1:null}];node.onConnectionsChange();report();};
    document.querySelector('#restore').onclick=()=>{nodes[0].widgets[1].value='restored,alpha';nodes[0].onConfigure();report();};
    document.querySelector('#remove').onclick=()=>nodes.forEach(node=>node.onRemoved());
    document.addEventListener('keydown',event=>{if(event.key==='F8')nodes.forEach(node=>node.onRemoved());});
    document.querySelector('#save-writer').onclick=async()=>{
        const row=await (await fetch('/toolbox/prompts/1')).json();
        const names=['prompt','language','media_type','prompt_type','nsfw','content_format','dynamic','width','height','sensitivity_level','extreme','horror','gore','minor'];
        const payload=Object.fromEntries(names.map(name=>[name,row[name]]));payload.tags=nodes[0].widgets[1].value;payload.prompt='Synthetic writer test output';
        const response=await fetch('/toolbox/prompts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        document.querySelector('#save-status').textContent=response.ok?'Writer saved':'Writer failed';
    };
    document.querySelector('#prompts').onclick=()=>openPromptBrowser({request:(path,options)=>api.fetchApi('/toolbox/prompts'+path,options),currentId:0,onSelect:()=>{}});
    document.querySelector('#skills').onclick=()=>openSkillBrowser({request:(path,options)=>api.fetchApi('/toolbox/skills'+path,options),currentId:0,onSelect:()=>{}});
    </script></body></html>''')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18773);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='toolbox-tags-test-') as directory:
        prompt_nodes.DEFAULT_PROMPT_DB=Path(directory)/'prompts.sqlite3'
        prompt_nodes.ToolBoxPromptWriter().write_prompt(0,'Synthetic prompt for tag tests','zh','image','natural',False,'plaintext',False,1024,768,'alpha,beta')
        # A catalog longer than one API page, without reading the real prompt DB.
        with prompt_nodes.connect_db() as conn:
            conn.executemany('INSERT INTO tags(name) VALUES(?)',[(f'tag-{i:03d}',) for i in range(505)])
        skill_library.create_entry(dict(name='Synthetic skill',entry_type='skill',content='# Skill',description='',tags='skill-only'))
        app=create_app();app.router.add_get('/',page);app.router.add_static('/web',ROOT/'web')
        web.run_app(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
