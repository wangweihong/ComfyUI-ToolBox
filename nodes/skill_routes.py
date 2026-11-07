"""Same-origin skill/template API; SQLite work stays off the event loop."""
import asyncio
import json
import sqlite3
import base64
from urllib.parse import quote

from . import skill_library as library
from . import skill_files


def register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return

    async def respond(operation, *args, creating=False):
        try:
            data = await asyncio.to_thread(operation, *args)
            if isinstance(data, web.StreamResponse):
                return data
            status = 201 if creating and data.get("action") == "created" else 200
            return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})
        except library.SkillConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except library.SkillNotFound as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except skill_files.SkillCapacityError as exc:
            return web.json_response({"error":str(exc)}, status=413)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (sqlite3.Error, OSError) as exc:
            return web.json_response({"error": f"Skill/模板数据库不可用：{exc}"}, status=503)

    async def listing(request):
        return await respond(library.list_entries, dict(request.query))

    async def tags(request):
        return await respond(library.list_tags, dict(request.query))

    async def storage(request):
        return await respond(library.storage)

    async def get(request):
        return await respond(library.detail, request.match_info["id"])

    async def save(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "请使用 application/json"}, status=415)
        raw = bytearray()
        async for chunk in request.content.iter_chunked(16384):
            raw.extend(chunk)
            if len(raw) > skill_files.MAX_JSON_BYTES:
                return web.json_response({"error": "内容过大"}, status=413)

        def operation():
            payload = json.loads(raw)
            return library.create_entry(payload) if request.method == "POST" else library.save_entry(request.match_info["id"], payload)
        return await respond(operation, creating=request.method == "POST")

    async def upload(request):
        if request.content_type != "multipart/form-data":
            return web.json_response({"error":"请使用 multipart/form-data 上传"}, status=415)
        try:
            reader = await request.multipart()
            paths, uploads, size = None, [], 0
            async for part in reader:
                if part.name == "paths" and paths is None and not uploads:
                    raw = bytearray()
                    while chunk := await part.read_chunk():
                        raw.extend(chunk)
                        if len(raw) > 120000:
                            raise ValueError("文件路径列表过大")
                    paths = json.loads(raw)
                    if not isinstance(paths, list) or not paths or len(paths) > skill_files.MAX_FILES:
                        raise ValueError("一次上传 1–200 个文件")
                    for path in paths:
                        skill_files.safe_path(path)
                elif part.name == "file" and paths is not None and len(uploads) < len(paths):
                    raw = bytearray()
                    while chunk := await part.read_chunk():
                        raw.extend(chunk)
                        size += len(chunk)
                        if size > skill_files.MAX_UPLOAD_BYTES:
                            return web.json_response({"error":"上传总大小最多 21 MiB"}, status=413)
                    uploads.append((paths[len(uploads)], bytes(raw)))
                else:
                    raise ValueError("请先提交 paths，再按顺序提交 file")
            if paths is None or len(paths) != len(uploads):
                raise ValueError("文件数量与路径不一致")
        except (ValueError, TypeError, AssertionError) as exc:
            return web.json_response({"error":str(exc)}, status=400)
        return await respond(skill_files.import_uploads, uploads)

    async def download(request):
        def operation():
            row = library.detail(request.match_info["id"])
            if request.path.endswith("/download"):
                if not row["files"]:
                    files = [skill_files.file_item("SKILL.md" if row["entry_type"] == "skill" else "template.md", row["content"].encode("utf-8"))]
                else:
                    files = row["files"]
                    if not row["primary_path"] and row["content"]:
                        paths = {item["path"] for item in files}
                        name = "content.md"
                        while name in paths:
                            name = "_" + name
                        files = [*files, skill_files.file_item(name, row["content"].encode("utf-8"))]
                data, name = skill_files.archive_bytes(files), f'skill-{row["id"]}.zip'
                media_type = "application/zip"
            else:
                path = skill_files.safe_path(request.query.get("path"))
                item = next((item for item in row["files"] if item["path"] == path), None)
                if item is None:
                    raise library.SkillNotFound("文件不存在")
                data, name, media_type = base64.b64decode(item["data"]), path.split("/")[-1], "application/octet-stream"
            return web.Response(body=data, content_type=media_type, headers={"Cache-Control":"no-store",
                "Content-Disposition":f"attachment; filename*=UTF-8''{quote(name, safe='')}", "X-Content-Type-Options":"nosniff"})
        return await respond(operation)

    instance.routes.get("/toolbox/skills/tags")(tags)
    instance.routes.get("/toolbox/skills/storage")(storage)
    instance.routes.post("/toolbox/skills/upload")(upload)
    instance.routes.get("/toolbox/skills")(listing)
    instance.routes.post("/toolbox/skills")(save)
    instance.routes.get("/toolbox/skills/{id}")(get)
    instance.routes.patch("/toolbox/skills/{id}")(save)
    instance.routes.get("/toolbox/skills/{id}/download")(download)
    instance.routes.get("/toolbox/skills/{id}/files")(download)


register_routes()
