"""Shared aiohttp routes used by ComfyUI and the standalone verification server."""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from aiohttp import web
from PIL import Image, ImageOps
from .library import LibraryError
from . import metadata
from .regeneration import Regenerator

BASE = Path(__file__).parent
PREFIX = '/toolbox/media-library'


def register_routes(routes, get_library, on_change=lambda: None, *, regeneration_runtime=None, app=None):
    regeneration = Regenerator(get_library, regeneration_runtime, on_change)
    if app is not None: app.on_cleanup.append(regeneration.close)
    scan_tasks = set()
    preview_jobs = {}
    conversion_gate = asyncio.Semaphore(1)
    thumbnail_gate = asyncio.Semaphore(3)
    thumbnail_locks = [asyncio.Lock() for _ in range(64)]

    async def work(func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    scan_worker = None
    pending_scan = None

    def start_scan(folder='', recursive=False):
        nonlocal scan_worker, pending_scan
        pending_scan = (folder, recursive)
        if scan_worker and not scan_worker.done(): return

        async def run_scans():
            nonlocal pending_scan
            while pending_scan is not None:
                scope = pending_scan
                pending_scan = None
                done = await work(get_library().scan, *scope)
                if done is False:
                    if pending_scan is None: pending_scan = scope
                    await asyncio.sleep(0.1)

        scan_worker = asyncio.create_task(run_scans())
        scan_tasks.add(scan_worker)
        scan_worker.add_done_callback(scan_tasks.discard)

    def endpoint(method, path):
        def wrap(handler):
            async def guarded(request):
                try:
                    response = await handler(request)
                    response.headers['X-Content-Type-Options'] = 'nosniff'
                    return response
                except (LibraryError, ValueError, TypeError, KeyError) as exc:
                    return web.json_response({'error': str(exc)}, status=400)
                except sqlite3.Error as exc:
                    return web.json_response({'error': f'素材数据库不可用，请稍后重试：{exc}'}, status=503)
                except (PermissionError, OSError) as exc:
                    return web.json_response({'error': str(exc)}, status=403)
            routes.route(method, PREFIX + path)(guarded)
            return guarded
        return wrap

    async def body(request):
        if request.content_type != 'application/json': raise LibraryError('请求必须使用 application/json')
        origin = request.headers.get('Origin')
        if origin and origin != f'{request.scheme}://{request.host}': raise LibraryError('拒绝跨来源文件操作')
        value = await request.json()
        if not isinstance(value, dict): raise LibraryError('请求内容必须为 JSON 对象')
        return value

    @endpoint('GET', '/gallery')
    async def gallery(request):
        return web.FileResponse(BASE / 'web' / 'dist' / 'gallery.html', headers={'Cache-Control': 'no-cache'})

    @endpoint('GET', '/assets/{filename}')
    async def assets(request):
        name = request.match_info['filename']
        if Path(name).name != name: raise LibraryError('无效资源路径')
        path = BASE / 'web' / 'dist' / 'assets' / name
        if not path.is_file(): raise web.HTTPNotFound()
        return web.FileResponse(path)

    @endpoint('GET', '/roots')
    async def roots(request):
        lib = get_library()
        return web.json_response({'roots': lib.roots(), 'tools': {'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe'))}})

    @endpoint('POST', '/roots')
    async def add_root(request):
        data = await body(request)
        value = await work(get_library().add_root, data.get('path', ''), data.get('name', ''))
        start_scan(data.get('path', ''))
        return web.json_response({'roots': value})

    @endpoint('DELETE', '/roots/{id}')
    async def remove_root(request):
        await body(request)
        await work(get_library().remove_root, request.match_info['id'])
        return web.json_response({'roots': get_library().roots()})

    @endpoint('GET', '/status')
    async def status(request):
        return web.json_response({**get_library().status, 'revision': get_library().revision})

    @endpoint('POST', '/scan')
    async def scan(request):
        data = await body(request)
        path = data.get('path', '')
        if path:
            checked, _ = get_library().check_path(path)
            if not checked.is_dir(): raise LibraryError('不是目录')
        start_scan(path, data.get('recursive') is True)
        return web.json_response({'ok': True})

    @endpoint('GET', '/files')
    async def files(request):
        q = request.query
        if not (q.get('root_id') or q.get('folder') or q.get('recent') == '1'):
            return web.json_response({'items': [], 'total': 0, 'offset': 0, 'limit': 80, 'focus': None})
        payload = await work(get_library().files, focus_id=q.get('focus_id', ''), recursive=q.get('recursive') == '1', q=q.get('q', ''), kind=q.get('kind', ''), root_id=q.get('root_id', ''), folder=q.get('folder', ''), sort=q.get('sort', 'time'), direction=q.get('direction', 'desc'), offset=q.get('offset', 0), limit=q.get('limit', 80), recent=q.get('recent') == '1')
        return web.json_response(payload)

    @endpoint('GET', '/folders')
    async def folders(request):
        return web.json_response({'folders': await work(get_library().folders, request.query.get('path', ''))})

    @endpoint('GET', '/folder-visits')
    async def folder_visits(request):
        return web.json_response({'items': await work(get_library().folder_visits)})

    @endpoint('POST', '/folder-visits')
    async def visit_folder(request):
        data = await body(request)
        return web.json_response({'items': await work(get_library().visit_folder, data.get('path', ''), data.get('root_id', ''))})

    @endpoint('POST', '/folder-visits/prune')
    async def prune_folder_visits(request):
        await body(request)
        return web.json_response({'items': await work(get_library().prune_folder_visits)})

    @endpoint('DELETE', '/folder-visits')
    async def clear_folder_visits(request):
        await body(request)
        def clear():
            with get_library().transaction() as db: db.execute('DELETE FROM media_folder_visits')
        await work(clear)
        return web.json_response({'items': []})

    @endpoint('GET', '/regenerations/options')
    async def regeneration_options(request):
        return web.json_response(await work(regeneration.options, request.query.get('id', '')))

    @endpoint('POST', '/regenerations/prepare')
    async def regeneration_prepare(request):
        data = await body(request)
        return web.json_response(await regeneration.prepare(data.get('id', ''), data.get('output_node', '')))

    @endpoint('POST', '/regenerations/submit')
    async def regeneration_submit(request):
        data = await body(request)
        return web.json_response(await regeneration.submit(data.get('token', '')))

    @endpoint('POST', '/regenerations/release')
    async def regeneration_release(request):
        data = await body(request)
        return web.json_response(await regeneration.release(data.get('token', '')))

    @endpoint('GET', '/regenerations')
    async def regeneration_jobs(request):
        return web.json_response({'items': await work(regeneration.jobs, request.query.get('source_id', ''))})

    @endpoint('GET', '/regenerations/{id}')
    async def regeneration_status(request):
        return web.json_response(await regeneration.status(request.match_info['id']))

    @endpoint('POST', '/folders/rename')
    async def rename_folder(request):
        data = await body(request)
        result = await work(get_library().rename_folder, data.get('path', ''), data.get('name', ''))
        on_change()
        return web.json_response(result)

    @endpoint('GET', '/detail')
    async def detail(request):
        return web.json_response(await work(get_library().detail, request.query.get('id', ''), request.query.get('path', '')))

    @endpoint('POST', '/select')
    async def select(request):
        data = await body(request)
        return web.json_response(await work(get_library().select, data.get('id', ''), data.get('path', '')))

    @endpoint('POST', '/recents/prune')
    async def prune(request):
        await body(request)
        await work(get_library().prune_recents)
        return web.json_response({'ok': True})

    @endpoint('GET', '/file')
    async def file(request):
        p = await work(get_library().resolve, request.query.get('id', ''), request.query.get('path', ''))
        category = metadata.kind(p)
        # Never execute local HTML/SVG in the service origin.
        mime = mimetypes.guess_type(p.name)[0] if category in ('image', 'video', 'audio') else 'application/octet-stream'
        mime = mime or 'application/octet-stream'
        return web.FileResponse(p, headers={'Content-Type': mime, 'Content-Disposition': 'inline' if category in ('image', 'video', 'audio') else 'attachment', 'Cache-Control': 'no-cache'})

    def cache_target(item, suffix):
        lib = get_library()
        sig = metadata.signature(Path(item['path']))
        digest = hashlib.sha256(sig.encode()).hexdigest()[:24]
        return lib.cache / f"{item['id']}-{digest}{suffix}"

    def make_thumb(item, target):
        p = get_library().resolve(item['id'])
        temp = target.with_suffix('.tmp.webp')
        try:
            if item['kind'] == 'image':
                with Image.open(p) as source:
                    im = ImageOps.exif_transpose(source)
                    im.thumbnail((480, 360))
                    im.convert('RGB').save(temp, 'WEBP', quality=78)
            elif item['kind'] == 'video':
                if not shutil.which('ffmpeg'): raise LibraryError('未找到 ffmpeg：无法生成视频封面')
                run = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(p), '-frames:v', '1', '-vf', 'scale=480:360:force_original_aspect_ratio=decrease', '-y', str(temp)], capture_output=True, timeout=45)
                if run.returncode: raise LibraryError(run.stderr.decode(errors='replace')[-1000:])
            else: raise LibraryError('该文件类型没有缩略图')
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)

    @endpoint('GET', '/thumb')
    async def thumb(request):
        async with thumbnail_gate:
            item = await work(get_library().detail, request.query.get('id', ''))
            target = await work(cache_target, item, '.webp')
            async with thumbnail_locks[hash(item['id']) % 64]:
                if not target.is_file(): await work(make_thumb, item, target)
        return web.FileResponse(target, headers={'Content-Type': 'image/webp', 'Cache-Control': 'private, max-age=86400'})

    def transcode(item, target):
        p = get_library().resolve(item['id'])
        if not shutil.which('ffmpeg'): raise LibraryError('未找到 ffmpeg：无法生成兼容预览，请安装 FFmpeg 后重试')
        temp = target.with_name(target.stem + '.tmp' + target.suffix)
        args = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(p)]
        if item['kind'] == 'video':
            args += ['-map', '0:v:0', '-map', '0:a:0?', '-vf', "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart']
        else: args += ['-vn', '-c:a', 'aac', '-movflags', '+faststart']
        try:
            run = subprocess.run([*args, '-y', str(temp)], capture_output=True, timeout=1800)
            if run.returncode: raise LibraryError(run.stderr.decode(errors='replace')[-1800:] or '兼容预览转换失败')
            # A file mutation during conversion must not publish a cache for the wrong source.
            if cache_target(get_library().detail(item['id']), target.suffix) != target:
                raise LibraryError('文件已变化，请重新生成预览')
            temp.replace(target)
            get_library().clean_cache(protected=target)
        finally: temp.unlink(missing_ok=True)

    async def run_preview(item, target, job):
        async with conversion_gate:
            job['state'] = 'running'
            try:
                await work(transcode, item, target)
                job['state'] = 'ready'
            except Exception as exc:
                job.update(state='error', error=str(exc))

    @endpoint('POST', '/preview')
    async def preview(request):
        data = await body(request)
        item = await work(get_library().detail, data.get('id', ''))
        if item['kind'] not in ('video', 'audio'): raise LibraryError('仅视频和音频需要兼容预览')
        target = await work(cache_target, item, '.mp4' if item['kind'] == 'video' else '.m4a')
        key = target.name
        url = PREFIX + '/preview/file?id=' + item['id']
        if target.is_file(): return web.json_response({'state': 'ready', 'url': url})
        job = preview_jobs.get(key)
        if not job or job['state'] == 'ready' or (data.get('retry') and job['state'] == 'error'):
            # Keep status memory bounded; queued/running jobs are retained.
            for old in list(preview_jobs):
                if len(preview_jobs) <= 100: break
                if preview_jobs[old]['state'] in ('ready', 'error'): preview_jobs.pop(old)
            job = {'state': 'queued'}
            preview_jobs[key] = job
            task = asyncio.create_task(run_preview(item, target, job))
            scan_tasks.add(task); task.add_done_callback(scan_tasks.discard)
        return web.json_response({**job, 'url': url})

    @endpoint('GET', '/preview/file')
    async def preview_file(request):
        item = await work(get_library().detail, request.query.get('id', ''))
        target = await work(cache_target, item, '.mp4' if item['kind'] == 'video' else '.m4a')
        if not target.is_file(): raise web.HTTPNotFound(text='兼容预览尚未就绪')
        return web.FileResponse(target, headers={'Content-Type': 'video/mp4' if item['kind'] == 'video' else 'audio/mp4'})

    @endpoint('POST', '/operations/plan')
    async def plan(request):
        data = await body(request)
        return web.json_response(await work(get_library().plan, data.get('op'), data.get('ids'), destination=data.get('destination', ''), template=data.get('template', '{name}_{index}'), start=data.get('start', 1)))

    @endpoint('POST', '/operations/apply')
    async def apply(request):
        data = await body(request)
        result = await work(get_library().apply, data.get('token'), data.get('confirmed', False))
        on_change()
        return web.json_response(result)

    return start_scan
