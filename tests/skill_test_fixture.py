"""Browser fixture; writes only to a disposable SQLite database."""
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
from nodes import prompt_nodes, skill_library


def create_app():
    routes = web.RouteTableDef()
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
    with patch.dict(sys.modules, {"server":server}):
        module = importlib.import_module("nodes.skill_routes")
        if not routes:
            module.register_routes()
    app = web.Application(client_max_size=3_000_000)
    app.add_routes(routes)
    return app


async def fixture_page(_request):
    return web.Response(content_type="text/html", text='''<!doctype html><html><head><meta charset="utf-8">
        <title>Skill library synthetic test</title></head><body>
        <button id="open">Open</button><button id="second">Second</button>
        <button id="remove">Remove first node</button>
        <label><input id="mock-discard" type="checkbox">Test discard confirmation</label>
        <p id="selected"></p><p id="discard"></p>
        <script type="module">
        import {attachSkillReader} from '/web/js/skill_browser.mjs';
        window.testNodes=[];
        const confirm = window.confirm.bind(window);
        window.confirm = message => {
            if (!document.querySelector('#mock-discard').checked) return confirm(message);
            document.querySelector('#discard').textContent = message;
            return false;
        };
        for (const button of document.querySelectorAll('#open,#second')) {
            const node = {widgets:[{name:'id',value:1}],size:[200,80],setSize:size=>node.size=size,
                setDirtyCanvas:()=>node.dirty=true,
                addDOMWidget:(name,type,content)=>{document.body.append(content);node.control=content},
            };
            attachSkillReader(node,{graph:{change:()=>{document.querySelector('#selected').textContent=`${button.id}: #${node.widgets[0].value}`}}},
                {fetchApi:(path,options)=>fetch(path,options)});
            button.onclick=()=>node.control.querySelector('button').click();
            window.testNodes.push(node);
        }
        document.querySelector('#remove').onclick=()=>window.testNodes[0].onRemoved();
        document.addEventListener('keydown',event=>{if(event.key==='F8') window.testNodes[0].onRemoved()});
        </script></body></html>''')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18771)
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="toolbox-skills-test-") as directory:
        prompt_nodes.DEFAULT_PROMPT_DB = Path(directory) / "prompts.sqlite3"
        if args.seed:
            for number in range(55):
                skill_library.create_entry(dict(name=f"Synthetic {number:03d}", entry_type="skill" if number%2 else "prompt_template",
                    description="Synthetic summary", content=f"# Synthetic {number}\n\n    {{variable}}\n<script>literal</script>",
                    tags="alpha,beta" if number%2 else "alpha,gamma"))
        app = create_app()
        app.router.add_get("/", fixture_page)
        app.router.add_static("/web", ROOT / "web")
        web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
