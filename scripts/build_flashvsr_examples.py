#!/usr/bin/env python3
"""Build explicit four-node graphs; the cache selection stays unselected."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import urllib.request
import uuid

OLD_NAMES=[
 '01_FlashVSR+_Turbo_2K_2560x1440.json','02_FlashVSR+_Turbo_4K_3840x2160.json',
 '03_本地2K_完整视频.json','04_本地4K_自动分段合并.json','05_本地8K_自动分块合成.json',
 '06_本地8K_竖屏优化_常驻NVENC.json','07_本地4K_竖屏优化_60fps_NVENC.json']
CASES=[
 ('01_FlashVSR_2K_5秒_三节点','clean_00005_.mp4','2K','landscape',5.),
 ('02_FlashVSR_4K_5秒_三节点','clean_00005_.mp4','4K','landscape',5.),
 ('03_FlashVSR_2K_完整视频_三节点','flashvsr_wallpaper_10s.mp4','2K','landscape',10.),
 ('04_FlashVSR_4K_横屏_三节点','flashvsr_wallpaper_10s.mp4','4K','landscape',10.),
 ('05_FlashVSR_8K_横屏_三节点','flashvsr_wallpaper_10s.mp4','8K','landscape',10.),
 ('06_FlashVSR_8K_竖屏_三节点','flashvsr_nv111_opt.mp4','8K','portrait',10.),
 ('07_FlashVSR_4K_竖屏60fps_三节点','动作参考.mp4','4K','portrait',18.3)]


def build(g,schemas,title):
    nodes=[];links=[]
    positions={1:[580,0],2:[0,0],3:[1020,0],4:[1020,360]}
    for key,item in g.items():
        schema=schemas[item['class_type']];fields={**schema['input'].get('required',{}),**schema['input'].get('optional',{})}
        node=dict(id=int(key),type=item['class_type'],title=schema.get('display_name',item['class_type']),pos=positions[int(key)],
                  size=[520 if int(key)==2 else 380 if int(key)==1 else 420,1080 if int(key)==2 else 480 if int(key)==4 else 760 if int(key)==1 else 240],flags={},order=int(key)-1,mode=0,inputs=[],
                  outputs=[dict(name=name,type=typ,links=[]) for typ,name in zip(schema['output'],schema.get('output_name',schema['output']))],
                  properties={'Node name for S&R':item['class_type']},widgets_values=[])
        for name,spec in fields.items():
            typ=spec[0];opt=spec[1] if len(spec)>1 else {};combo=isinstance(typ,list) or typ=='COMBO'
            widget=combo or typ in ('INT','FLOAT','STRING','BOOLEAN')
            default=opt.get('default',typ[0] if isinstance(typ,list) else opt.get('options',[''])[0] if combo else '' if typ=='STRING' else False if typ=='BOOLEAN' else 0)
            value=item['inputs'].get(name,default)
            port=dict(name=name,type='COMBO' if combo else typ,link=None)
            if widget:port['widget']={'name':name}
            if isinstance(value,list) and len(value)==2 and str(value[0]) in g:
                index=len(links)+1;links.append([index,int(value[0]),value[1],int(key),len(node['inputs']),port['type']]);port['link']=index
            if widget:
                node['widgets_values'].append(default if isinstance(value,list) else value)
                if opt.get('control_after_generate'):node['widgets_values'].append('fixed')
            node['inputs'].append(port)
        nodes.append(node)
    index={n['id']:n for n in nodes}
    for lid,src,slot,*_ in links:index[src]['outputs'][slot]['links'].append(lid)
    for n in nodes:
        for out in n['outputs']:
            if not out['links']:out['links']=None
    note='''# ToolBox FlashVSR · 显式节点连接

先在 Config.cache_mode **选择**缓存方式，再运行；默认“请选择”不会启动模型。

raw：完整RGB8磁盘缓存，便于重复编码；lossless：FFV1无损缓存，大小依内容变化且增加编解码；stream：不存整段帧，实际超分在编码节点执行，重编码通常需重推理。

10秒8K24fps原始帧约22.25GiB，18.22秒4K60fps约25.33GiB，另有分块暂存。这是磁盘，不是内存/显存需求。

低内存默认8帧、LQ256×256、重叠32、分块磁盘暂存。可选均衡、已测几何或custom，开放分段、块宽高、重叠、RAM与磁盘预算。保护不能保证拦截瞬时OOM，不自动替你改参数。

Video Encode可选CPU/NVENC/auto，保存到temp或output。auto会记录实际编码器及回退原因。CPU编码不代表CPU超分。质量CRF/CQ数值不等价。

输出video为标准VIDEO；info_json为JSON文本，可自行连接显示/解析/保存。没有强制导出的报告路径。stream准备时status=prepared，编码完成后才有最终统计。

默认fps=0保留原片，时长上限遇片尾停止，保留完整比例并必要时灰边适配。示例依赖本机已有输入视频；仓库不包含视频或模型。详细依赖与历史实测见ComfyUI-ToolBox/docs/flashvsr.md。
'''
    nodes.append(dict(id=900,type='MarkdownNote',title='模式选择与资源说明',pos=[580,820],size=[380,1050],flags={},order=4,mode=0,inputs=[],outputs=[],properties={},widgets_values=[note]))
    return dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL,'toolbox/flashvsr/'+title)),revision=0,last_node_id=900,last_link_id=len(links),nodes=nodes,links=links,groups=[],config={},
                extra={'workflowName':title,'ds':{'scale':.7,'offset':[600,260]}},version=.4)


def main():
    a=argparse.ArgumentParser();a.add_argument('--url',default='http://127.0.0.1:8188');a.add_argument('--publish');a.add_argument('--backup-dir')
    args=a.parse_args();root=Path(__file__).resolve().parents[1];dst=root/'examples/flashvsr';dst.mkdir(parents=True,exist_ok=True)
    schemas={}
    for kind in ('LoadVideo','ToolBoxFlashVSRConfig','ToolBoxFlashVSRUpscale','ToolBoxVideoEncode'):
        schemas.update(json.load(urllib.request.urlopen(args.url+'/object_info/'+kind,timeout=20)))
    defaults={}
    s=schemas['ToolBoxFlashVSRConfig']
    for name,spec in {**s['input']['required'],**s['input'].get('optional',{})}.items():
        opt=spec[1] if len(spec)>1 else {};defaults[name]=opt.get('default',spec[0][0] if isinstance(spec[0],list) else '')
    for name,source,res,orientation,duration in CASES:
        cfg=dict(defaults,cache_mode='请选择',resolution=res,orientation=orientation,duration_seconds=duration,fps=0.)
        g={'1':{'class_type':'LoadVideo','inputs':{'file':source}},'2':{'class_type':'ToolBoxFlashVSRConfig','inputs':cfg},
           '3':{'class_type':'ToolBoxFlashVSRUpscale','inputs':{'video':['1',0],'config':['2',0]}},
           '4':{'class_type':'ToolBoxVideoEncode','inputs':{'video':['3',0],'encoder':'auto','quality':18,'preset':'auto','container':'mp4','save_to':'temp','filename_prefix':'FlashVSR/'+name}}}
        (dst/(name+'.json')).write_text(json.dumps(build(g,schemas,name),ensure_ascii=False,indent=2))
        (dst/'api').mkdir(exist_ok=True);(dst/'api'/(name+'.json')).write_text(json.dumps(g,ensure_ascii=False,indent=2))
    (dst/'README.md').write_text('# FlashVSR 示例\n\n01–07视频示例使用LoadVideo、Config、Upscale、Encode显式连接，缓存模式均保留“请选择”，使用者需先选择。默认低内存配置、原片帧率和比例；目标分辨率与片段见文件名及Config。\n\n08为上游原生图像分块超分，1440×2560参考图放大到4320×7680，不依赖ToolBox视频节点。尺寸/接口已验证，但本图出现过强的皮肤和织物纹理，作为可复现试验保留，不代表画质验收通过。换图需同步修改合成尺寸。生成脚本：scripts/build_flashvsr_image_example.py。\n\n[使用说明与依赖](../../docs/flashvsr.md) · [视频实测及对比截图](../../docs/testing/flashvsr_2026-10-19.md) · [图像试验与画质诊断](../../docs/testing/flashvsr_image_2026-10-19.md)。示例不包含原图、视频或模型。\n')
    if args.publish:
        target=Path(args.publish);target.mkdir(parents=True,exist_ok=True)
        if not args.backup_dir:raise ValueError('Publishing requires --backup-dir outside the active workflow tree.')
        backup=Path(args.backup_dir)/('workflows_'+datetime.now().strftime('%Y%m%d_%H%M%S'));backup.mkdir(parents=True)
        for name in OLD_NAMES:
            p=target/name
            if p.exists():shutil.move(str(p),str(backup/name))
        # The frontend also lists .md/.txt/metadata JSON as workflows. Keep
        # only executable examples in this directory; docs live in ToolBox.
        for name in ['README.md','4K60fps_动作参考_实测报告.md','8K优化_实测报告.md','FlashVSR_依赖与安装.md',
                     'models-sha256.json','requirements-local-helper.txt','requirements-upstream.txt','已安装依赖版本.txt']:
            p=target/name
            if p.exists():shutil.move(str(p),str(backup/name))
        for p in dst.glob('*.json'):
            previous=target/p.name
            if previous.exists() and previous.read_bytes()!=p.read_bytes():shutil.copy2(previous,backup/p.name)
            shutil.copy2(p,previous)
        print('Published 7 workflows; previous graphs backed up to',backup)
    print(dst)


if __name__=='__main__':main()
