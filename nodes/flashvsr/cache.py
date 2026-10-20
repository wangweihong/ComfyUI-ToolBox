"""Owned cache handles and generation-based ComfyUI cache invalidation."""
import json
import shutil
import threading
from pathlib import Path

LOCK = threading.RLock()
HANDLES = {}


def validate_existing(directory,signature):
    directory=Path(directory)
    if directory.is_symlink():
        raise ValueError('Refusing a symlink as a managed FlashVSR task directory.')
    if directory.exists() and any(directory.iterdir()):
        m=read_manifest(directory)
        if m.get('owner')!='toolbox_flashvsr' or m.get('signature')!=signature:
            raise ValueError('Refusing an existing non-owned cache directory; choose another cache_directory.')


def ensure_owned(directory,signature):
    validate_existing(directory,signature)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    m=read_manifest(directory)
    if not m.get('owner'):
        m.update(owner='toolbox_flashvsr',signature=signature)
        write_manifest(directory,m)
    return m


def read_manifest(directory):
    p = Path(directory)/"manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"generation": 0, "complete": False}


def write_manifest(directory, data):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    p = directory/"manifest.json"; tmp = directory/"manifest.json.part"
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False))
    tmp.replace(p)


def register(handle):
    with LOCK:
        HANDLES[handle.plan["signature"]] = handle


def generation(directory):
    with LOCK:
        validate_existing(directory,Path(directory).name)
        m = read_manifest(directory)
        if m.get("complete") and not (Path(directory)/m["file"]).is_file():
            m.update(complete=False, generation=m.get("generation", 0)+1)
            write_manifest(directory, m)
        return m.get("generation", 0)


def clear(directory, signature):
    with LOCK:
        directory = Path(directory)
        validate_existing(directory,signature)
        m = read_manifest(directory)
        if m.get("owner") != "toolbox_flashvsr" or m.get("signature") != signature:
            raise ValueError("Refusing to clear a cache not owned by this FlashVSR task.")
        for p in directory.iterdir():
            if p.name == "manifest.json":
                continue
            if p.is_symlink():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        write_manifest(directory, dict(owner="toolbox_flashvsr", signature=signature,
                                       complete=False, generation=m.get("generation", 0)+1))


def register_routes():
    try:
        from server import PromptServer
        from aiohttp import web
        server = PromptServer.instance
    except (ImportError, AttributeError):
        return
    @server.routes.post('/toolbox/flashvsr/cache/clear')
    async def clear_route(request):
        data = await request.json()
        with LOCK:
            handle = HANDLES.get(data.get("signature"))
        if handle is None:
            return web.json_response({"error": "Unknown cache. Run its Upscale node to register the handle."}, status=404)
        if handle.busy:
            return web.json_response({"error": "Task is currently executing."}, status=409)
        try:
            handle.clear_cache()
        except (ValueError,RuntimeError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        return web.json_response({"status": "cleared"})
