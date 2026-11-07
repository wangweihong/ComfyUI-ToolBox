"""Read structured generation parameters without guessing custom node semantics."""
from __future__ import annotations

import json
from collections import deque
from .vendor.image_meta import parse_generation_meta

PARSER_VERSION = 2
LABELS = {
    'positive': '正向提示词', 'positive_prompt': '正向提示词', 'negative': '负向提示词',
    'negative_prompt': '负向提示词', 'prompt': '提示词', 'text': '文本', 'text_g': '文本 G',
    'text_l': '文本 L', 'string': '文本', 'seed': '种子', 'noise_seed': '种子',
    'steps': '步数', 'cfg': 'CFG', 'cfg_scale': 'CFG', 'sampler_name': '采样器',
    'sampler': '采样器', 'scheduler': '调度器', 'model': '模型', 'model_name': '模型',
    'ckpt_name': '模型', 'unet_name': '模型', 'model_path': '模型路径',
    'temperature': '温度', 'top_p': 'Top P', 'top_k': 'Top K', 'transcript': '参考音频文本',
}
ALIASES = {'comment': 'Comment', 'usercomment': 'UserComment', 'description': 'Description',
           'imagedescription': 'ImageDescription', 'parameters': 'parameters', 'prompt': 'prompt', 'workflow': 'workflow'}


def extract(raw):
    normalized = {ALIASES.get(k.casefold(), k): v for k, v in raw.items() if isinstance(v, str)}
    source, summary = parse_generation_meta(normalized)
    # A workflow with an unknown sampler must not mask an existing A1111 parameter block.
    if not summary:
        for key in ('parameters', 'UserComment', 'Comment', 'Description', 'ImageDescription'):
            candidate_source, candidate = parse_generation_meta({key: normalized.get(key, '')})
            if candidate:
                source, summary = candidate_source, candidate
                break
    api_groups, ui_groups, named_groups = [], [], []
    seen_strings, seen_groups = set(), set()
    queue = deque([(raw, 'metadata', 0)])
    workflow = False
    fields_left, visited, clipped = 512, 0, False

    def group(node_id, node_type, title, values, origin, ui=False):
        nonlocal fields_left, clipped
        fields = []
        for key, value in values:
            if value is None: continue
            # An API link is a reference, never a seed or prompt value.
            if not ui and isinstance(value, list) and len(value) == 2 and isinstance(value[1], int) and str(value[0]) in graph:
                continue
            if fields_left <= 0:
                clipped = True
                break
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            if len(text) > 512 * 1024:
                text = text[:512 * 1024]
                clipped = True
            key = str(key)
            fields.append({'name': key, 'label': LABELS.get(key.casefold(), key), 'value': text})
            fields_left -= 1
        identity = json.dumps([node_id, node_type, fields], sort_keys=True, ensure_ascii=False)
        if not fields or identity in seen_groups: return None
        seen_groups.add(identity)
        return {'node_id': str(node_id), 'node_type': node_type, 'title': title or node_type,
                'origin': origin, 'fields': fields,
                'highlight': any(f['name'].casefold() in LABELS for f in fields) or (ui and any(word in node_type.casefold() for word in ('text','prompt','voice','tts','generate')))}

    graph = {}
    while queue and visited < 128:
        data, origin, depth = queue.popleft()
        if depth > 8: clipped = True; continue
        visited += 1
        if isinstance(data, str):
            if data in seen_strings or not data.lstrip().startswith(('{', '[', '"')): continue
            seen_strings.add(data)
            try: queue.append((json.loads(data), origin, depth + 1))
            except (ValueError, TypeError): pass
            continue
        if isinstance(data, list):
            for i, value in enumerate(data[:128]):
                if isinstance(value, (dict, list, str)): queue.append((value, f'{origin}[{i}]', depth + 1))
            continue
        if not isinstance(data, dict): continue
        nodes = {str(k): v for k, v in data.items() if isinstance(v, dict) and isinstance(v.get('class_type'), str)}
        if nodes:
            workflow = True
            graph = nodes
            if not summary:
                parsed_source, parsed = parse_generation_meta({'prompt': json.dumps(nodes, ensure_ascii=False)})
                if parsed: source, summary = parsed_source, parsed
            for node_id, node in nodes.items():
                inputs = node.get('inputs', {})
                if not isinstance(inputs, dict): continue
                meta = node.get('_meta', {})
                title = meta.get('title', '') if isinstance(meta, dict) else ''
                item = group(node_id, node['class_type'], title, inputs.items(), origin)
                if item: api_groups.append(item)
            continue
        if isinstance(data.get('nodes'), list):
            workflow = True
            if not summary:
                parsed_source, parsed = parse_generation_meta({'workflow': json.dumps(data, ensure_ascii=False)})
                if parsed: source, summary = parsed_source, parsed
            for node in data['nodes'][:256]:
                if not isinstance(node, dict): continue
                widgets = node.get('widgets_values', [])
                if isinstance(widgets, dict): values = widgets.items()
                elif isinstance(widgets, list): values = [(f'控件 {i + 1}', value) for i, value in enumerate(widgets)]
                else: continue
                item = group(node.get('id', ''), str(node.get('type', '')), node.get('title', ''), values, origin, ui=True)
                if item: ui_groups.append(item)
            continue
        named = []
        for key, value in data.items():
            if key.casefold() not in LABELS or isinstance(value, (dict, list)): continue
            if isinstance(value, str):
                try:
                    if isinstance(json.loads(value), (dict, list)): continue
                except (ValueError, TypeError): pass
            named.append((key, value))
        if named:
            graph = {}
            item = group('', '', '嵌入的生成参数', named, origin)
            if item: named_groups.append(item)
        for key, value in data.items():
            if key == 'ffprobe': continue
            if isinstance(value, (dict, list, str)): queue.append((value, f'{origin}.{key}', depth + 1))
    if queue: clipped = True
    groups = api_groups or ui_groups or named_groups
    return {'source': source if source != 'none' else 'comfyui' if workflow else 'none',
            'summary': summary, 'generation_nodes': groups, 'has_workflow': workflow,
            'generation_truncated': clipped, 'parser_version': PARSER_VERSION}
