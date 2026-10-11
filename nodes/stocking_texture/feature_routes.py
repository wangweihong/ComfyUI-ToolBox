"""Editor operations, private persistence and document exchange routes."""
import asyncio
import base64
import copy
import json
from pathlib import Path
import tempfile
import uuid

import numpy as np
from . import data, persistence, psd
from .editing import edit_frame


def register(instance, get_session, post_body, workers, gate):
    from aiohttp import web

    def root(request):
        manager = instance.user_manager
        return Path(manager.get_request_user_filepath(request, "toolbox_stocking/store", create_dir=True)).parent

    def session(request, body):
        value = get_session(body.get("session", ""))
        user = instance.user_manager.get_request_user_id(request)
        if value.get("owner", user) != user:
            raise ValueError("此预览属于其他用户")
        value["owner"] = user
        return value

    async def run(fn, *args, **kwargs):
        import functools
        async with gate:
            return await asyncio.get_running_loop().run_in_executor(workers, functools.partial(fn, *args, **kwargs))

    async def handle(request):
        try:
            p = await post_body(request)
            feature = request.match_info["feature"]
            user_root = root(request)
            if feature == "presets":
                return web.json_response({"presets": await run(persistence.presets, user_root, p.get("action", "list"), p.get("name"), p.get("params"))})
            if feature == "draft":
                action = p.get("action", "load")
                editor, identity = p.get("editor_id"), p.get("identity")
                if action == "save":
                    s = session(request, p)
                    state = p.get("state")
                    if not isinstance(state, dict):
                        raise ValueError("草稿状态必须为对象")
                    doc = state.get("doc")
                    if doc is not None:
                        data.parse_guides(data.dump_guides(doc), s["images"].shape[1], s["images"].shape[2], len(s["images"]), state.get("mode", "shared"), external=any(x is not None for x in s.get("external", [])))
                    if "settings" in state:
                        persistence.material(state["settings"])
                    saved = await run(persistence.save_draft, user_root, editor, identity, s, state)
                    return web.json_response({"saved": saved})
                if action == "delete":
                    await run(persistence.delete_draft, user_root, editor, identity)
                    return web.json_response({"deleted": True})
                if action != "load":
                    raise ValueError("未知草稿操作")
                saved = await run(persistence.load_draft, user_root, editor, identity)
                if saved is None:
                    return web.json_response({"draft": None})
                from .nodes import session_payload
                recovered = saved.pop("session")
                recovered.update(sam=None, sam3_model=None, revisions={}, owner=instance.user_manager.get_request_user_id(request))
                state = saved["state"]
                # Prefer current model handles when an upstream capture is already available.
                if p.get("session"):
                    current = session(request, p)
                    if data.digest(current["images"]) != identity:
                        raise ValueError("恢复底图身份不一致")
                    for key in ("sam", "sam3_model"):
                        recovered[key] = current.get(key)
                payload = session_payload(recovered, document=state.get("doc"), batch_mode=state.get("mode", "shared"),
                    params=state.get("settings", recovered.get("settings", recovered.get("params", {}))), saved_guides_json=recovered.get("saved_guides_json", "{}"),
                    identities=[data.digest(im) for im in recovered["images"]],
                    has_mask=any(x is not None for x in recovered.get("external", [])),
                    material_connected=recovered.get("material") is not None, sam_available=recovered.get("sam") is not None, sam3_available=recovered.get("sam3_model") is not None)
                saved["payload"] = payload
                return web.json_response({"draft": saved})
            s = session(request, p)
            index = int(p.get("index", 0))
            if not 0 <= index < len(s["images"]):
                raise ValueError("批次索引超出范围")
            image = s["images"][index]
            doc = data.parse_guides(p.get("guides_json", "{}"), *image.shape[:2], len(s["images"]), p.get("batch_mode", "shared"), external=any(x is not None for x in s.get("external", [])))
            fi = 0 if p.get("batch_mode", "shared") == "shared" else index
            frame = doc["frames"][fi]
            external = s.get("external", [None] * len(s["images"]))[index]
            if feature == "edit":
                points = p.get("points")
                if points is not None:
                    # Validate the cut as an ordinary guide, including image bounds/point budget.
                    probe = dict(version=1, width=image.shape[1], height=image.shape[0], frames=[dict(regions=[dict(id="cut", name="cut", strokes=[points])])])
                    data.parse_guides(data.dump_guides(probe), *image.shape[:2], 1)
                radius = float(p.get("snap_radius", 0))
                if not np.isfinite(radius) or not 0 <= radius <= 80:
                    raise ValueError("贴线半径无效")
                edited, info = await run(edit_frame, image, frame, external, p.get("operation"), p.get("source"), p.get("target"), points, radius)
                return web.json_response({"frame": edited, "info": info})
            if feature == "export":
                kind = p.get("kind", "png")
                if kind == "guides":
                    with tempfile.TemporaryDirectory() as tmp:
                        path = Path(tmp) / "stocking-guides.psd"
                        await run(psd.write, path, image, frame, external, s.get("painted", [None] * len(s["images"]))[index])
                        return web.Response(body=path.read_bytes(), content_type="application/octet-stream", headers={"Content-Disposition": 'attachment; filename="stocking-guides.psd"'})
                from .engine import solve_one, render_one
                if kind not in ("png", "cutout"):
                    raise ValueError("未知导出类型")
                params = dict(s.get("settings", s.get("params", {})), **p.get("settings", {}))
                params["layer_mode"] = "soft"
                params["material"] = s.get("material")
                if s["kind"] == "unified":
                    from .unified import process_one
                    depth = s["depths"][index]
                    if depth is not None and params.get("depth_direction", "white_near") != s["depth_direction"]:
                        depth = 1 - depth
                    result = await run(process_one, image, frame, external, depth, s["painted"][index], params,
                                       params.get("color_exclude", True), params.get("seed", 20261005), params.get("auto_direction", True), params.get("auto_walls", True))
                else:
                    fields = s["fields"]["frames"][index] if s["kind"] == "renderer" else await run(solve_one, image, frame, data.frame_masks(frame, *image.shape[:2], external))
                    result = await run(render_one, image, fields, params, params.get("color_exclude", True), params.get("seed", 20261005), s.get("painted", [None] * len(s["images"]))[index])
                out, layer, alpha = result[:3]
                pixels = data.rgb8(out) if kind == "png" else np.dstack((data.rgb8(layer), np.round(alpha * 255).astype(np.uint8)))
                body = await run(data.png_bytes, pixels)
                return web.Response(body=body, content_type="image/png", headers={"Content-Disposition": f'attachment; filename="stocking-{kind}.png"'})
            raise ValueError("未知编辑接口")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Stocking feature route failed")
            return web.json_response({"error": str(exc)}, status=500)

    async def import_psd(request):
        try:
            fields = await request.post()
            token = fields.get("session", "")
            s = session(request, dict(session=token))
            index = int(fields.get("index", 0))
            if not 0 <= index < len(s["images"]):
                raise ValueError("批次索引超出范围")
            file = fields.get("file")
            if file is None or not hasattr(file, "file"):
                raise ValueError("请选择 PSD/PSB 文件")
            body = file.file.read(128 * 1024**2 + 1)
            if len(body) > 128 * 1024**2:
                raise ValueError("上传 PSD 超过 128 MiB")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "import.psd"; path.write_bytes(body)
                image, doc, records, sparkle = await run(psd.read, path)
            original = s["images"][index]
            if image.shape != original.shape or not np.array_equal(data.rgb8(image), data.rgb8(original)):
                raise ValueError("PSD 底图不匹配，请使用 PSD 加载节点导入新底图")
            return web.json_response({"document": doc, "identity": data.digest(original)})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    instance.routes.post("/toolbox/stocking/feature/{feature}")(handle)
    instance.routes.post("/toolbox/stocking/psd/import")(import_psd)
