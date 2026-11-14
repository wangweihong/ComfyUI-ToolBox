"""Local browser/API fixture with synthetic records and a temporary database."""
import argparse
import importlib
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiohttp import web
from nodes import prompt_nodes as prompts


def create_app():
    routes = web.RouteTableDef()
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
    with patch.dict(sys.modules, {"server": server}):
        module = importlib.import_module("nodes.prompt_routes")
        if not routes:
            module.register_routes()
    app = web.Application(client_max_size=3_000_000)
    app.add_routes(routes)
    return app


def seed_records():
    writer = prompts.ToolBoxPromptWriter()
    for number in range(65):
        writer.write_prompt(
            0, f"Synthetic prompt {number:03d}: a quiet landscape. <script>not executable</script>",
            "en", "image", "natural", number % 2 == 1, "plaintext", False,
            1024, 768, "landscape,night" if number % 2 else "landscape,day",
            sensitivity_level=number % 5, gore=number % 3 == 0, horror=False,
            extreme=False, minor=False,
        )


async def fixture_page(_request):
    return web.Response(content_type="text/html", text="""<!doctype html><html><head><meta charset="utf-8">
        <title>Prompt browser test</title></head><body>
        <button id="open">Open</button><button id="second">Second</button>
        <button id="toolbar">提示词库（工具栏测试）</button>
        <label><input id="readonly" type="checkbox">只读画布测试</label>
        <pre id="toolbar-result">[]</pre>
        <script type="module">
        import {openPromptBrowser,attachPromptReader} from '/web/js/prompt_browser.mjs';
        import {createPromptLibraryToolbar} from '/web/js/prompt_toolbar.mjs';
        import {attachPromptBatchPreview} from '/web/js/prompt_batch.mjs';
        import {attachNodeTags} from '/web/js/tag_picker.mjs';
        const graph={nodes:[],beforeChange(){},afterChange(){},
            add(node){node.graph=this;this.nodes.push(node);},remove(node){this.nodes=this.nodes.filter(item=>item!==node);node.graph=null;},
            change(){document.querySelector('#toolbar-result').textContent=JSON.stringify(this.nodes.map(node=>({id:node.widgets[0].value,title:node.title,pos:node.pos})));}};
        const app={canvas:{graph,canvas:{getBoundingClientRect:()=>({width:1000,height:600})},convertCanvasToOffset:point=>point,selectNode(){}}};
        const toolbar=createPromptLibraryToolbar({app,api:{fetchApi:(path,options)=>fetch(path,options)},
            createNode:()=>({size:[350,180],widgets:[{name:'id',value:1}],setDirtyCanvas(){}})});
        document.querySelector('#toolbar').onclick=toolbar.onClick;
        document.querySelector('#readonly').onchange=event=>app.canvas.read_only=event.target.checked;
        window.browsers = [];
        const request = (path,options) => fetch('/toolbox/prompts'+path,options);
        document.querySelector('#open').onclick = () => window.browsers.push(openPromptBrowser({
            request,currentId:0,onSelect:id=>window.selected=id,
        }));
        document.querySelector('#second').onclick = () => window.browsers.push(openPromptBrowser({
            request,currentId:0,onSelect:id=>window.secondSelected=id,
        }));
        window.attachTestNode = () => {
            const node = { widgets:[{name:'id',value:1}], size:[200,80],
                setSize:size=>node.size=size, setDirtyCanvas:()=>node.dirty=true,
                addDOMWidget:(name,type,content,options)=>{document.body.append(content);node.control=content;node.options=options;},
            };
            attachPromptReader(node,{graph:{change:()=>node.changed=true}},
                {fetchApi:(path,options)=>fetch(path,options)});
            window.testNode=node;
        };
        window.attachBatchTestNode = () => {
            const node={widgets:Object.entries({tags:'landscape',start_index:0,limit:100,
                    nsfw:'否',extreme:'否',horror:'否',gore:'否',minor:'否'}).map(([name,value])=>({name,value,type:'text'})),
                inputs:[],size:[400,400],setDirtyCanvas(){},setSize(){},
                addDOMWidget(name,type,content,options){content.style.width='400px';content.style.height=`${options.getMinHeight()}px`;document.body.append(content);return {name,options};}};
            attachPromptBatchPreview(node);
            attachNodeTags(node,{graph:{}},{fetchApi:(path,options)=>fetch(path,options)});
            window.batchNode=node;
            window.runBatch=async()=>{
                const data=await (await fetch('/batch-preview',{method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify(Object.fromEntries(node.widgets.map(widget=>[widget.name,widget.value])))})).json();
                window.batchResult=data;node.onExecuted(data.ui);return data;
            };
        };
        </script></body></html>""")


async def batch_preview(request):
    return web.json_response(prompts.ToolBoxPromptsByTag().execute_prompt(**await request.json()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="toolbox-prompts-browser-") as directory:
        prompts.database.DEFAULT_DB = Path(directory) / "prompts.sqlite3"
        seed_records()
        app = create_app()
        app.router.add_get("/", fixture_page)
        app.router.add_post('/batch-preview', batch_preview)
        app.router.add_static("/web", ROOT / "web")
        web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
