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
        <script type="module">
        import {openPromptBrowser,attachPromptReader} from '/web/js/prompt_browser.mjs';
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
        </script></body></html>""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="toolbox-prompts-browser-") as directory:
        prompts.DEFAULT_PROMPT_DB = Path(directory) / "prompts.sqlite3"
        seed_records()
        app = create_app()
        app.router.add_get("/", fixture_page)
        app.router.add_static("/web", ROOT / "web")
        web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
