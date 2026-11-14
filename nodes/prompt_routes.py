"""Same-origin prompt browser API. SQLite work runs outside the event loop."""
import asyncio
import json
import sqlite3

from . import prompt_library as library
from .prompt_nodes import PromptConflict
from . import prompt_examples as examples


def register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return

    async def respond(operation, *args, status=200):
        try:
            result = await asyncio.to_thread(operation, *args)
            if status == 201 and result.get("action") == "updated":
                status = 200
            return web.json_response(result, status=status, headers={"Cache-Control": "no-store"})
        except PromptConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except library.PromptNotFound as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (sqlite3.Error, OSError) as exc:
            return web.json_response({"error": f"提示词数据库不可用：{exc}"}, status=503)

    async def listing(request):
        return await respond(library.list_prompts, dict(request.query))

    async def tags(request):
        return await respond(library.list_tags, dict(request.query))

    async def options(_request):
        return web.json_response(library.browser_options())

    async def get(request):
        def operation():
            return library.detail(library.positive_int(request.match_info["id"], "id"))
        return await respond(operation)

    async def save(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "请使用 application/json"}, status=415)
        raw = bytearray()
        async for chunk in request.content.iter_chunked(16384):
            raw.extend(chunk)
            if len(raw) > 2_100_000:
                return web.json_response({"error": "提示词数据过大"}, status=413)
        def operation():
            if request.method == "POST":
                return library.create_prompt(json.loads(raw))
            prompt_id = library.positive_int(request.match_info["id"], "id")
            return library.save_prompt(prompt_id, json.loads(raw))
        return await respond(operation, status=201 if request.method == "POST" else 200)

    async def example_list(request):
        return await respond(examples.list_examples, dict(request.query), request.match_info.get("id"))

    async def remove(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "请使用 application/json"}, status=415)
        raw = bytearray()
        async for chunk in request.content.iter_chunked(16384):
            raw.extend(chunk)
            if len(raw) > 16384:
                return web.json_response({"error": "删除请求过大"}, status=413)
        def operation():
            payload = json.loads(raw)
            if "id" not in request.match_info:
                return library.delete_tag(payload)
            return library.delete_prompt(library.positive_int(request.match_info["id"], "id"), payload)
        return await respond(operation)

    async def example_write(request):
        removing = request.method == "DELETE" and "id" in request.match_info
        if removing and not request.can_read_body:
            return await respond(examples.remove, request.match_info["id"])
        if request.content_type != "application/json":
            return web.json_response({"error":"请使用 application/json"}, status=415)
        raw=bytearray()
        async for chunk in request.content.iter_chunked(16384):
            raw.extend(chunk)
            if len(raw)>1_100_000:
                return web.json_response({"error":"示例请求过大"}, status=413)
        if removing:
            return await respond(lambda: examples.remove(request.match_info["id"], json.loads(raw)))
        operation = examples.register if request.path.endswith("/register") else examples.cleanup if request.method == "DELETE" else examples.check
        return await respond(lambda: operation(json.loads(raw)))

    instance.routes.get("/toolbox/prompts/options")(options)
    instance.routes.get("/toolbox/prompts/tags")(tags)
    instance.routes.delete("/toolbox/prompts/tags")(remove)
    instance.routes.get("/toolbox/prompts")(listing)
    instance.routes.post("/toolbox/prompts")(save)
    instance.routes.get("/toolbox/prompts/{id}")(get)
    instance.routes.patch("/toolbox/prompts/{id}")(save)
    instance.routes.delete("/toolbox/prompts/{id}")(remove)
    instance.routes.get("/toolbox/prompts/{id}/examples")(example_list)
    instance.routes.get("/toolbox/prompt-examples")(example_list)
    instance.routes.post("/toolbox/prompt-examples/register")(example_write)
    instance.routes.post("/toolbox/prompt-examples/check")(example_write)
    instance.routes.delete("/toolbox/prompt-examples/invalid")(example_write)
    instance.routes.delete("/toolbox/prompt-examples/{id}")(example_write)


register_routes()
