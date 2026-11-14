"""Restore recorded API graphs, preflight them, and queue a new image branch."""
from __future__ import annotations

import asyncio
import copy
import json
import re
import secrets
import time
import uuid
from pathlib import Path, PurePosixPath

from . import metadata
from .library import LibraryError

SAVE_NODES = {'SaveImage', 'ToolBoxPromptSaveImage'}
SEED_FIELDS = {'seed', 'noise_seed', 'random_seed'}
MAX_SAFE_INTEGER = 2**53 - 1


def decoded_object(value):
    for _ in range(3):
        if not isinstance(value, str): break
        try: value = json.loads(value)
        except ValueError: return None
    return value if isinstance(value, dict) else None


def recorded_graph(item):
    if item.get('kind') != 'image': raise LibraryError('当前仅支持重新生成图片')
    if item.get('truncated'): raise LibraryError('素材元数据已截断，无法安全恢复完整执行图')
    graph = decoded_object(item.get('raw', {}).get('prompt'))
    if not graph or any(not isinstance(node, dict) or not isinstance(node.get('class_type'), str) or not isinstance(node.get('inputs'), dict) for node in graph.values()):
        raise LibraryError('没有完整的 ComfyUI API 执行图；仅凭提示词摘要或画布工作流无法直接重新生成')
    return {str(key): value for key, value in graph.items()}


def link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int) and not isinstance(value[1], bool)


def branch_graph(graph, output):
    result, visiting = {}, set()

    def visit(node_id):
        if node_id in visiting: raise LibraryError('执行图存在循环引用')
        if node_id in result: return
        if node_id not in graph: raise LibraryError(f'执行图缺少节点：{node_id}')
        visiting.add(node_id)
        node = graph[node_id]
        for value in node['inputs'].values():
            if link(value): visit(value[0])
        visiting.remove(node_id)
        result[node_id] = copy.deepcopy(node)

    visit(output)
    return result


def randomize_seeds(graph, definitions):
    fields = set()

    def seed_source(node_id, field, seen=None):
        seen = set() if seen is None else seen
        key = (node_id, field)
        if key in seen: raise LibraryError('随机种子连接存在循环')
        seen.add(key)
        value = graph[node_id]['inputs'][field]
        if not link(value):
            if isinstance(value, bool) or not isinstance(value, int): raise LibraryError(f'节点 {node_id} 的随机种子不是整数')
            return key
        source, slot = value
        inputs = graph[source]['inputs']
        candidates = [name for name in SEED_FIELDS if name in inputs]
        if not candidates and graph[source]['class_type'] == 'PrimitiveInt' and 'value' in inputs: candidates = ['value']
        if slot != 0 or len(candidates) != 1: raise LibraryError(f'无法确定节点 {node_id} 的种子来源，请先在原工作流中使用明确的整数种子节点')
        return seed_source(source, candidates[0], seen)

    for node_id, node in graph.items():
        schema = definitions[node['class_type']]
        inputs = {**schema.get('required', {}), **schema.get('optional', {})}
        for field in SEED_FIELDS & node['inputs'].keys():
            if inputs.get(field, [None])[0] == 'INT': fields.add(seed_source(node_id, field))
    if not fields: raise LibraryError('未找到可调整的整数随机种子，不能保证生成新结果')
    changes = []
    for node_id, field in sorted(fields):
        node = graph[node_id]
        schema = definitions[node['class_type']]
        spec = {**schema.get('required', {}), **schema.get('optional', {})}.get(field)
        if not spec or spec[0] != 'INT': raise LibraryError(f'节点 {node_id} 没有可验证的整数种子输入')
        options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        minimum = max(0, int(options.get('min', 0)))
        maximum = min(MAX_SAFE_INTEGER, int(options.get('max', MAX_SAFE_INTEGER)))
        step = max(1, int(options.get('step', 1)))
        count = (maximum - minimum) // step + 1
        if count < 2: raise LibraryError(f'节点 {node_id} 的种子范围不足以生成新种子')
        old = node['inputs'][field]
        value = minimum + secrets.randbelow(count) * step
        if value == old: value = minimum + ((value - minimum) // step + 1) % count * step
        node['inputs'][field] = value
        changes.append({'node_id': node_id, 'title': node.get('_meta', {}).get('title', node['class_type']), 'field': field, 'before': old, 'after': value})
    return changes


def output_prefix(source, output_root, graph, job_id):
    source, output_root = Path(source), Path(output_root).resolve()
    stem = re.sub(r'[\\/\x00-\x1f%]', '_', source.stem)[:100] or 'image'
    if source.is_relative_to(output_root):
        directory = PurePosixPath(source.parent.relative_to(output_root).as_posix())
    else:
        model = 'unspecified'
        for node in graph.values():
            if node['class_type'] in {'UNETLoader', 'CheckpointLoaderSimple', 'CheckpointLoader'}:
                name = node['inputs'].get('unet_name') or node['inputs'].get('ckpt_name')
                if isinstance(name, str): model = re.sub(r'[^\w.-]', '_', Path(name).stem)[:80] or model
                break
        directory = PurePosixPath('images') / model / 'regenerated'
    return str(directory / f'{stem}_regen_{job_id[:8]}')


class ComfyRuntime:
    """Use the installed ComfyUI validator and native HTTP queue contract."""

    def output_root(self):
        import folder_paths
        return Path(folder_paths.get_output_directory()).resolve()

    def definitions(self, graph):
        import nodes
        result = {}
        for node in graph.values():
            name = node['class_type']
            cls = nodes.NODE_CLASS_MAPPINGS.get(name)
            if cls is None: raise LibraryError(f'缺少 ComfyUI 节点：{name}')
            result[name] = cls.INPUT_TYPES()
        return result

    async def validate(self, prompt_id, graph, target):
        import execution
        result = await execution.validate_prompt(prompt_id, copy.deepcopy(graph), [target])
        if not result[0]:
            raise LibraryError('ComfyUI 预检未通过：' + json.dumps({'error': result[1], 'nodes': result[3]}, ensure_ascii=False))

    async def submit(self, payload):
        import aiohttp
        from server import PromptServer
        server = PromptServer.instance
        # Fixed local destination, never an address supplied by the browser or metadata.
        endpoint = f'http://127.0.0.1:{server.port}/prompt'
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(endpoint, json=payload, headers={'Comfy-Usage-Source': 'comfyui-frontend'}) as response:
                result = await response.json()
                if response.status >= 500: raise asyncio.TimeoutError('ComfyUI 返回服务器错误，提交状态待确认')
                if response.status != 200: raise LibraryError('ComfyUI 拒绝入队：' + json.dumps(result, ensure_ascii=False))
                if result.get('prompt_id') != payload['prompt_id']: raise asyncio.TimeoutError('未能确认提交的任务 ID')

    def status(self, prompt_id, output_node):
        from server import PromptServer
        queue = PromptServer.instance.prompt_queue
        history = queue.get_history(prompt_id=prompt_id).get(prompt_id)
        if history:
            status = history.get('status', {})
            if status.get('status_str') == 'error':
                return {'status': 'failed', 'error': json.dumps(status.get('messages', []), ensure_ascii=False)}
            if status.get('completed'):
                return {'status': 'complete', 'images': history.get('outputs', {}).get(output_node, {}).get('images', [])}
        running, pending = queue.get_current_queue_volatile()
        if any(item[1] == prompt_id for item in running): return {'status': 'running'}
        if any(item[1] == prompt_id for item in pending): return {'status': 'queued'}
        return {'status': 'unknown', 'error': '暂时无法从 ComfyUI 队列或历史确认任务状态；不会自动重复入队'}


class Regenerator:
    def __init__(self, get_library, runtime=None, on_change=lambda: None):
        self.get_library = get_library
        self.runtime = runtime or ComfyRuntime()
        self.on_change = on_change
        self.prepared = {}
        self.lock = asyncio.Lock()
        self.tasks = set()

    async def close(self, _app=None):
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def options(self, asset_id):
        item = self.get_library().detail(asset_id)
        try:
            graph = recorded_graph(item)
            outputs = [{'id': key, 'title': node.get('_meta', {}).get('title', node['class_type']), 'prefix': node['inputs'].get('filename_prefix', '')}
                       for key, node in graph.items() if node['class_type'] in SAVE_NODES and 'images' in node['inputs']]
            if not outputs: raise LibraryError('没有受支持的图片保存节点；目前支持 SaveImage 与 tb-prompt-save-image')
            return {'available': True, 'outputs': outputs}
        except LibraryError as exc:
            return {'available': False, 'outputs': [], 'reason': str(exc)}

    async def prepare(self, asset_id, target):
        library = self.get_library()
        item = await asyncio.to_thread(library.detail, asset_id)
        signature = await asyncio.to_thread(metadata.signature, Path(item['path']))
        original = recorded_graph(item)
        if target not in original or original[target]['class_type'] not in SAVE_NODES: raise LibraryError('请选择受支持的图片保存分支')
        graph = branch_graph(original, target)
        if any(key != target and node['class_type'] in SAVE_NODES for key, node in graph.items()):
            raise LibraryError('该分支依赖其他保存节点，无法保证只保存本次生成结果')
        images = graph[target]['inputs'].get('images')
        if not link(images): raise LibraryError('图片保存节点缺少可恢复的图像输入')
        job_id = str(uuid.uuid4())
        output_root = await asyncio.to_thread(self.runtime.output_root)
        prefix = output_prefix(item['path'], output_root, graph, job_id)
        graph[target] = {'class_type': 'SaveImage', 'inputs': {'images': images, 'filename_prefix': prefix}, '_meta': {'title': 'SaveImage - 保存重新生成图像'}}
        definitions = await asyncio.to_thread(self.runtime.definitions, graph)
        changes = randomize_seeds(graph, definitions)
        for node in graph.values():
            title = node.get('_meta', {}).get('title', '')
            if ' - ' not in title: node['_meta'] = {**node.get('_meta', {}), 'title': node['class_type'] + ' - 复用原素材生成参数'}
        await self.runtime.validate(job_id, graph, target)
        if await asyncio.to_thread(metadata.signature, Path(item['path'])) != signature: raise LibraryError('原素材已变化，请重新预检')
        models = sorted({value for node in graph.values() for field, value in node['inputs'].items()
                         if (field in {'ckpt_name', 'unet_name', 'lora_name', 'vae_name', 'clip_name'} or re.fullmatch(r'lora_\d+_name|clip_name\d+', field))
                         and isinstance(value, str) and value != 'None'})
        batches = [{'node_id': key, 'batch_size': node['inputs']['batch_size']} for key, node in graph.items() if 'batch_size' in node['inputs']]
        details = {'source_path': item['path'], 'target': target, 'prefix': prefix, 'seed_changes': changes, 'models': models, 'batches': batches}
        provenance = {'source_id': item['id'], 'source_path': item['path'], 'seed_changes': changes,
                      'source_workflow': decoded_object(item.get('raw', {}).get('workflow'))}
        payload = {'prompt_id': job_id, 'prompt': graph, 'partial_execution_targets': [target],
                   'extra_data': {'extra_pnginfo': {'tb_media_regeneration': provenance}}}
        async with self.lock:
            self.prepared = {key: value for key, value in self.prepared.items() if time.monotonic() - value['created'] < 600}
            if len(self.prepared) >= 32: raise LibraryError('待确认任务过多，请稍后重试')
            token = str(uuid.uuid4())
            self.prepared[token] = {'created': time.monotonic(), 'id': job_id, 'source_id': asset_id, 'signature': signature,
                                    'path': item['path'], 'payload': payload, 'details': details, 'submitted': False}
        return {'token': token, 'expires_in': 600, **details}

    def _job(self, job_id):
        library = self.get_library()
        with library.lock: row = library.db.execute('SELECT * FROM media_regenerations WHERE id=?', (job_id,)).fetchone()
        if row is None: raise LibraryError('重新生成任务不存在')
        result = dict(row)
        result['details'], result['outputs'] = json.loads(result['details']), json.loads(result['outputs'])
        return result

    def jobs(self, asset_id):
        library = self.get_library()
        with library.lock:
            ids = [row[0] for row in library.db.execute('SELECT id FROM media_regenerations WHERE source_id=? ORDER BY created_at DESC LIMIT 10', (asset_id,))]
        return [self._job(job_id) for job_id in ids]

    def _update(self, job_id, status, error='', outputs=None):
        with self.get_library().transaction() as db:
            if outputs is None: db.execute('UPDATE media_regenerations SET status=?,error=?,updated_at=? WHERE id=?', (status, error, time.time_ns(), job_id))
            else: db.execute('UPDATE media_regenerations SET status=?,error=?,outputs=?,updated_at=? WHERE id=?', (status, error, json.dumps(outputs, ensure_ascii=False), time.time_ns(), job_id))

    async def submit(self, token):
        async with self.lock:
            plan = self.prepared.get(token)
            if not plan or time.monotonic() - plan['created'] >= 600: raise LibraryError('预检已过期，请重新检查')
            if plan['submitted']: return await asyncio.to_thread(self._job, plan['id'])
            library = self.get_library()
            source = await asyncio.to_thread(library.resolve, plan['source_id'])
            if str(source) != plan['path'] or await asyncio.to_thread(metadata.signature, source) != plan['signature']:
                raise LibraryError('原素材或路径已变化，请重新预检')
            await self.runtime.validate(plan['id'], plan['payload']['prompt'], plan['details']['target'])
            with library.transaction() as db:
                now = time.time_ns()
                db.execute('INSERT INTO media_regenerations(id,source_id,status,created_at,updated_at,details) VALUES(?,?,?,?,?,?)',
                           (plan['id'], plan['source_id'], 'submitting', now, now, json.dumps(plan['details'], ensure_ascii=False)))
            plan['submitted'] = True
            try:
                await self.runtime.submit(copy.deepcopy(plan['payload']))
                await asyncio.to_thread(self._update, plan['id'], 'queued')
            except LibraryError as exc:
                await asyncio.to_thread(self._update, plan['id'], 'failed', str(exc))
            except Exception as exc:
                await asyncio.to_thread(self._update, plan['id'], 'unknown', f'提交状态待确认，不会自动重试：{exc}')
            task = asyncio.create_task(self._watch(plan['id']))
            self.tasks.add(task); task.add_done_callback(self.tasks.discard)
            return await asyncio.to_thread(self._job, plan['id'])

    def _index_outputs(self, images):
        library, outputs, errors = self.get_library(), [], []
        root = Path(self.runtime.output_root()).resolve()
        for image in images:
            try:
                if not isinstance(image, dict): raise LibraryError('保存节点返回了无效的输出文件')
                name, folder = image.get('filename'), image.get('subfolder', '')
                if image.get('type') != 'output' or not isinstance(name, str) or not name or PurePosixPath(name).name != name or '\\' in name:
                    raise LibraryError('保存节点返回了无效的输出文件')
                subfolder = PurePosixPath(folder)
                if subfolder.is_absolute() or '..' in subfolder.parts or '\\' in folder: raise LibraryError('输出目录超出范围')
                path = root / folder / name
                if not path.resolve().is_relative_to(root): raise LibraryError('输出文件超出 output 目录')
                item = library.detail(path=str(path))
                outputs.append({'id': item['id'], 'path': item['path'], 'name': item['name']})
            except (LibraryError, OSError, TypeError, ValueError) as exc:
                errors.append(str(exc))
        if not images: errors.append('任务已完成，但保存节点没有返回图片')
        return outputs, '\n'.join(errors)

    async def status(self, job_id):
        async with self.lock:
            job = await asyncio.to_thread(self._job, job_id)
            if job['status'] in {'complete', 'failed'}: return job
            state = await asyncio.to_thread(self.runtime.status, job_id, job['details']['target'])
            status, error = state['status'], state.get('error', '')
            if status == 'complete':
                outputs, error = await asyncio.to_thread(self._index_outputs, state.get('images', []))
                await asyncio.to_thread(self._update, job_id, status, error, outputs)
                self.on_change()
            else: await asyncio.to_thread(self._update, job_id, status, error)
            return await asyncio.to_thread(self._job, job_id)

    async def _watch(self, job_id):
        try:
            while True:
                await asyncio.sleep(2)
                job = await self.status(job_id)
                if job['status'] in {'complete', 'failed', 'unknown'}: return
        except asyncio.CancelledError: raise
        except Exception as exc:
            await asyncio.to_thread(self._update, job_id, 'unknown', f'任务状态暂不可用：{exc}')
