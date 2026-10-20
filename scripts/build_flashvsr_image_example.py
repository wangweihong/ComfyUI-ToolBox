#!/usr/bin/env python3
"""Build a native FlashVSR still-image graph; no additional custom nodes."""
import argparse
import json
from pathlib import Path
import urllib.request


TITLE = '08_FlashVSR_图像8K_4320x7680_原生分块_效果一般'
WORKFLOW_ID = 'd06a2c26-93ab-54cb-96a5-6532a73f75c5'
SOURCE = 'b2139c3af8040e0c69ba6a4f279b5882.png'


def graph():
    return {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': SOURCE}},
        '2': {'class_type': 'SplitImageToTileList', 'inputs': {
            'image': ['1', 0], 'tile_width': 512, 'tile_height': 640, 'overlap': 128}},
        '3': {'class_type': 'FlashVSR_SM_Model', 'inputs': {
            'dit': 'turbo_dit_plus.safetensors', 'proj_pt': 'lq_proj_in_plus_turbo.safetensors',
            'emb_pt': 'posi_prompt_plus.pth', 'version': 'plus_turbo', 'tiny_long': False,
            'offload': False, 'plus_temporal': '4', 'plus_attn': 'triton_block_sparse'}},
        '4': {'class_type': 'FlashVSR_SM_KSampler', 'inputs': {
            'model': ['3', 0], 'image': ['2', 0], 'width': 512, 'height': 640,
            'seed': 20261019, 'scale': 3, 'kv_ratio': 3.5, 'local_range': 11,
            'steps': 1, 'cfg': 1.0, 'sparse_ratio': 2.0}},
        '5': {'class_type': 'FlashVSR_SM_Vae', 'inputs': {
            'vae': 'none', 'tcd_encoder': 'TCDecoder_plus.ckpt', 'lite_vae': 'none'}},
        '6': {'class_type': 'FlashVSR_SM_Decoder', 'inputs': {
            'vae': ['5', 0], 'latent': ['4', 0], 'full_tiled': True,
            'color_fix': True, 'fix_method': 'wavelet'}},
        '7': {'class_type': 'ImageMergeTileList', 'inputs': {
            'image_list': ['6', 0], 'final_width': 4320, 'final_height': 7680, 'overlap': 384}},
        '8': {'class_type': 'SaveImage', 'inputs': {
            'images': ['7', 0], 'filename_prefix': 'FlashVSR/Images/b2139c3a_8K'}},
    }


def workflow(g, schemas):
    positions = {1: [0, 0], 2: [360, 0], 3: [0, 600], 4: [760, 0],
                 5: [360, 600], 6: [1140, 0], 7: [1140, 360], 8: [1520, 0]}
    titles = {1: '原图 · 1440×2560', 2: '切块 · 512×640 / 重叠128',
              3: 'FlashVSR+ Turbo · 共享模型', 4: 'FlashVSR · 每块3倍超分',
              5: 'TCDecoder · 共享解码器', 6: '解码与颜色校正',
              7: '融合 · 4320×7680 / 重叠384', 8: '保存8K PNG'}
    nodes, links = [], []
    for key, item in g.items():
        ident = int(key)
        schema = schemas[item['class_type']]
        fields = {**schema['input'].get('required', {}), **schema['input'].get('optional', {})}
        node = dict(id=ident, type=item['class_type'], title=titles[ident],
                    pos=positions[ident], size=[400 if ident == 8 else 330, 700 if ident == 8 else 500 if ident in (1, 4) else 360 if ident == 3 else 260],
                    flags={}, order=ident-1, mode=0, inputs=[], outputs=[],
                    properties={'Node name for S&R': item['class_type']}, widgets_values=[])
        for slot, (typ, name) in enumerate(zip(schema['output'], schema.get('output_name', schema['output']))):
            out = dict(name=name, type=typ, links=[])
            if schema.get('output_is_list', [False] * len(schema['output']))[slot]:
                out['shape'] = 6
            node['outputs'].append(out)
        for name, spec in fields.items():
            typ = spec[0]
            opt = spec[1] if len(spec) > 1 else {}
            combo = isinstance(typ, list) or typ == 'COMBO'
            widget = combo or typ in ('INT', 'FLOAT', 'STRING', 'BOOLEAN')
            default = opt.get('default', typ[0] if isinstance(typ, list) else opt.get('options', [''])[0] if combo else '' if typ == 'STRING' else False if typ == 'BOOLEAN' else 0)
            value = item['inputs'].get(name, default)
            port = dict(name=name, type='COMBO' if combo else typ, link=None)
            if widget:
                port['widget'] = {'name': name}
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in g:
                lid = len(links)+1
                links.append([lid, int(value[0]), value[1], ident, len(node['inputs']), port['type']])
                port['link'] = lid
            if widget:
                node['widgets_values'].append(default if isinstance(value, list) else value)
                # ComfyUI adds this frontend widget for seed INTs by default,
                # even when object_info does not explicitly advertise it.
                if opt.get('control_after_generate') or (typ == 'INT' and name in ('seed', 'noise_seed') and opt.get('control_after_generate', True)):
                    node['widgets_values'].append('fixed')
            node['inputs'].append(port)
        nodes.append(node)
    index = {n['id']: n for n in nodes}
    for lid, src, slot, *_ in links:
        index[src]['outputs'][slot]['links'].append(lid)
    for n in nodes:
        for out in n['outputs']:
            if not out['links']:
                out['links'] = None
    note = '''# FlashVSR 原生图像超分 · 此图8K配置

直接使用上游 ComfyUI_FlashVSR；不依赖 ToolBox 视频节点，不转视频。

画质试验：本图尺寸与流程已跑通，但皮肤/布料有过强的生成纹理；保留供复现，不代表推荐画质。对照和后续策略见docs/testing/flashvsr_image_2026-10-19.md。

原图1440×2560 → 每块3倍模型超分 → 4320×7680 PNG；完整画面，不裁切、不拉伸。切块为512×640（原图像素）、重叠128；本图共4列×5行=20块。输出块1536×1920，合并重叠384。

这是IMAGE列表，每块作为单张图片分别推理；不要改成IMAGE批次，否则会将不同空间块作为连续视频帧处理。模型加载节点共享；上游IMAGE/LATENT列表会占用主机内存，本流程不等同于ToolBox视频的磁盘暂存和预算保护。

需要：上游FlashVSR固定版本、四个Turbo权重、支持的CUDA环境。分块/合成来自当前ComfyUI内置节点，无需另外安装分块插件。

plus_temporal=4 是上游单图内部时序扩展；输出仍为一张图。Plus模式下steps/cfg/kv_ratio/local_range/sparse_ratio不生效；Decoder.full_tiled也不控制Plus空间分块，空间块由左侧切块节点控制。

修改配置：KSampler.width/height应与切块宽高一致；切块宽高×scale必须128对齐，以避免上游中心裁切。合并overlap=切块overlap×scale；合并宽高=实际原图宽高×scale。换图时必须同步修改合并尺寸。本工作流的4320×7680专为1440×2560参考图设置。

减小块可降低单次显存峰值，但可能更慢且影响接缝；不能保证所有硬件运行。完整说明见ToolBox/docs/flashvsr.md。
'''
    nodes.append(dict(id=900, type='MarkdownNote', title='图像超分 · 参数与限制', pos=[760, 670],
                      size=[1050, 660], flags={}, order=8, mode=0, inputs=[], outputs=[],
                      properties={}, widgets_values=[note]))
    return dict(id=WORKFLOW_ID, revision=0,
                last_node_id=900, last_link_id=len(links), nodes=nodes, links=links, groups=[], config={},
                extra={'workflowName': TITLE, 'ds': {'scale': .65, 'offset': [120, 100]}}, version=.4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    parser.add_argument('--publish')
    args = parser.parse_args()
    g = graph()
    schemas = {}
    for kind in {v['class_type'] for v in g.values()}:
        schemas.update(json.load(urllib.request.urlopen(args.url+'/object_info/'+kind, timeout=20)))
    ui = workflow(g, schemas)
    root = Path(__file__).resolve().parents[1]
    dst = root/'examples/flashvsr'
    (dst/'api').mkdir(parents=True, exist_ok=True)
    data = json.dumps(ui, ensure_ascii=False, indent=2)
    (dst/(TITLE+'.json')).write_text(data)
    (dst/'api'/(TITLE+'.json')).write_text(json.dumps(g, ensure_ascii=False, indent=2))
    if args.publish:
        target = Path(args.publish)/(TITLE+'.json')
        if target.exists() and target.read_text() != data:
            raise FileExistsError('Existing image workflow differs; preserve it before replacing: '+str(target))
        target.write_text(data)
    print(dst/(TITLE+'.json'))


if __name__ == '__main__':
    main()
