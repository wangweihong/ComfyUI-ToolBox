"""Preview-only routes; final queue results always come from saved node inputs."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import functools
import json

import numpy as np

from . import data
from .cache import SESSION_CACHE, REGION_CACHE, SCENE_CACHE

_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tb-stocking")
_gate = asyncio.Semaphore(2)


def get_session(token):
    session = SESSION_CACHE.get(token)
    if session is None:
        raise ValueError("预览缓存已释放，请重新执行此节点取得底图")
    return session


def image_index(value, session):
    i = int(value)
    if not 0 <= i < len(session["images"]):
        raise ValueError("批次索引超出范围")
    return i


def preview_sync(session, payload):
    from .engine import solve_one, render_one, isolines, guide_overlays
    i = image_index(payload.get("index", 0), session)
    image = session["images"][i]
    overview = None
    if session["kind"] == "unified" and not payload.get("advanced"):
        from .unified import process_one
        settings = dict(session["settings"], **payload.get("settings", {}))
        doc = data.parse_guides(payload.get("guides_json", "{}"), *image.shape[:2], len(session["images"]), "per_image", external=session["external"][i] is not None)
        frame = doc["frames"][i]
        depth = session["depths"][i]
        if depth is not None and settings.get("depth_direction", "white_near") != session["depth_direction"]:
            depth = 1 - depth
        rendered = process_one(image, frame, session["external"][i], depth, session["painted"][i],
            payload.get("params", settings), bool(settings.get("color_exclude", True)), settings.get("seed", 20261005),
            bool(settings.get("auto_direction", True)), bool(settings.get("auto_walls", True)))
        output, _, _, diag, _, info, field = rendered
        out = isolines(image, field) if payload.get("view") == "guides" else data.rgb8(diag if payload.get("diagnostics") else output)
        if payload.get("overlay_settings") is not None:
            info["overlays"] = guide_overlays(field, payload["overlay_settings"])
            if payload.get("view") == "guides":
                out = data.rgb8(image)
        rect = payload.get("rect")
        if rect is not None:
            if not isinstance(rect, list) or len(rect) != 4 or any(not isinstance(v, int) for v in rect):
                raise ValueError("预览 rect 必须为四个整数")
            x0, y0, x1, y1 = rect
            if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
                raise ValueError("预览区域超出图像")
        if payload.get("overview"):
            from PIL import Image
            thumb = Image.fromarray(out)
            thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
            overview = base64.b64encode(data.png_bytes(np.asarray(thumb))).decode()
        if rect:
            out = out[y0:y1, x0:x1]
    elif session["kind"] == "editor" or payload.get("advanced"):
        # Work on only the selected image, while validating all per-image guide entries.
        doc = data.parse_guides(payload.get("guides_json", "{}"), image.shape[0], image.shape[1],
                                len(session["images"]), payload.get("batch_mode", "shared"), external=session["external"][i] is not None)
        frame = doc["frames"][0 if payload.get("batch_mode", "shared") == "shared" else i]
        masks = data.frame_masks(frame, *image.shape[:2], session["external"][i])
        f = solve_one(image, frame, masks)
        out = isolines(image, f)
        info = {"solve_seconds": f["solve_seconds"], "cache_hits": f["cache_hits"], "cache_misses": f["cache_misses"],
                "unguided_pixels": int(f["unguided"].sum()), "notes": f["notes"]}
        if payload.get("overlay_settings") is not None:
            info["overlays"] = guide_overlays(f, payload["overlay_settings"])
            out = data.rgb8(image)
    else:
        f = session["fields"]["frames"][i]
        rect = payload.get("rect")
        if rect is not None:
            if not isinstance(rect, list) or len(rect) != 4 or any(not isinstance(v, int) for v in rect):
                raise ValueError("预览 rect 必须为四个整数")
            x0, y0, x1, y1 = rect
            if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
                raise ValueError("预览区域超出图像")
        params = payload.get("params", session["params"])
        if not isinstance(params, dict):
            raise ValueError("纹理参数必须为对象")
        seed = payload.get("seed", session["seed"])
        if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("seed 必须为非负 64 位整数")
        # An updated overview and detail come from the same full render. Pan-only
        # requests keep the crop path; no second render or solver pass is needed.
        with_overview = payload.get("overview") is True
        out, _, _, diag, info = render_one(image, f, params, bool(payload.get("color_exclude", session["color_exclude"])),
                                          seed, session["painted"][i], rect=None if with_overview else rect)
        out = data.rgb8(diag if payload.get("diagnostics") else out)
        if with_overview:
            from PIL import Image
            thumb = Image.fromarray(out)
            thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
            overview = base64.b64encode(data.png_bytes(np.asarray(thumb))).decode()
            if rect is not None:
                out = out[y0:y1, x0:x1]
    result = {"png": base64.b64encode(data.png_bytes(out)).decode(), "info": info,
              "revision": payload["revision"], "index": i}
    if overview is not None:
        result["overview_png"] = overview
    return result


def register_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return

    async def source(request):
        try:
            s = get_session(request.query.get("session", ""))
            i = image_index(request.query.get("index", 0), s)
            kind = request.query.get("kind", "image")
            if kind == "external" and s["kind"] in ("editor", "unified"):
                arr = s["external"][i]
                if arr is None:
                    import numpy as np
                    arr = np.zeros(s["images"].shape[1:3], np.float32)
                arr = (arr * 255).round().astype("uint8")
            elif kind == "image":
                arr = data.rgb8(s["images"][i])
            else:
                raise ValueError("未知底图类型")
            async with _gate:
                body = await asyncio.get_running_loop().run_in_executor(_workers, data.png_bytes, arr)
            return web.Response(body=body, content_type="image/png", headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def post_body(request):
        if request.content_length is not None and request.content_length > data.MAX_JSON_BYTES:
            raise ValueError("请求超过 32 MiB")
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("请求必须为 JSON 对象")
        return body

    async def preview(request):
        try:
            p = await post_body(request)
            s = get_session(p.get("session", ""))
            rev, client = p.get("revision"), p.get("client", "")
            if not isinstance(rev, int) or rev < 0 or not isinstance(client, str) or not 1 <= len(client) <= 128:
                raise ValueError("预览 revision 或 client 无效")
            revisions = s["revisions"]
            if len(revisions) >= 64 and client not in revisions:
                revisions.pop(next(iter(revisions)))
            if rev < revisions.get(client, -1):
                return web.json_response({"stale": True, "revision": rev})
            revisions[client] = rev
            async with _gate:
                if revisions.get(client) != rev:
                    return web.json_response({"stale": True, "revision": rev})
                result = await asyncio.get_running_loop().run_in_executor(_workers, functools.partial(preview_sync, s, p))
            SESSION_CACHE.reweigh()
            if revisions.get(client) != rev:
                return web.json_response({"stale": True, "revision": rev})
            return web.json_response(result)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Stocking preview failed")
            return web.json_response({"error": str(exc)}, status=500)

    async def sam(request):
        try:
            p = await post_body(request)
            s = get_session(p.get("session", ""))
            i = image_index(p.get("index", 0), s)
            handle = s.get("sam")
            if handle is None:
                raise ValueError("未连接 SAM 模型；画笔和引导功能仍可使用")
            rgb = data.rgb8(s["images"][i])
            identity = data.digest(rgb)
            async with _gate:
                masks, scores, info = await asyncio.get_running_loop().run_in_executor(
                    _workers, functools.partial(handle.segment, rgb, identity, float(p["x"]), float(p["y"]), with_info=True))
            return web.json_response({"masks": [data.encode_mask(m.astype("float32")) for m in masks],
                                      "scores": scores.tolist(), "best": int(scores.argmax()), "identity": identity, "info": info})
        except (ValueError, TypeError, KeyError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("ToolBox SAM request failed")
            return web.json_response({"error": str(exc)}, status=500)

    async def prepare(request):
        try:
            p = await post_body(request)
            import nodes
            from .nodes import prepare_session
            def load():
                images, _ = nodes.LoadImage().load_image(p["image"])
                handle = None
                if p.get("sam"):
                    from .nodes import NFStockingSAMLoader
                    handle = NFStockingSAMLoader().load(**p["sam"])[0]
                return prepare_session(images, p.get("settings", {}), p.get("guides_json", "{}"), sam=handle)
            async with _gate:
                result = await asyncio.get_running_loop().run_in_executor(_workers, load)
            return web.json_response(result)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def semantic(request):
        try:
            p = await post_body(request)
            s = get_session(p.get("session", ""))
            i = image_index(p.get("index", 0), s)
            from .unified import semantic_regions
            while instance.prompt_queue.get_current_queue()[0]:
                await asyncio.sleep(0.2)
                if request.transport is None or request.transport.is_closing():
                    return web.json_response({"error": "请求已关闭"}, status=499)
            async with _gate:
                result = await asyncio.get_running_loop().run_in_executor(_workers, functools.partial(
                    semantic_regions, s["images"][i], s.get("sam3_model"), p.get("prompt", "stockings"), float(p.get("threshold", 0.4))))
            return web.json_response(result)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    instance.routes.post("/toolbox/stocking/prepare")(prepare)
    instance.routes.post("/toolbox/stocking/semantic")(semantic)
    instance.routes.get("/toolbox/stocking/image")(source)
    instance.routes.post("/toolbox/stocking/preview")(preview)
    instance.routes.post("/toolbox/stocking/sam")(sam)
    from .feature_routes import register
    register(instance, get_session, post_body, _workers, _gate)


register_routes()
