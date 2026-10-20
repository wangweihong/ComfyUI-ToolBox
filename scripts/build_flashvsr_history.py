#!/usr/bin/env python3
"""Import existing measurements and extract real same-time comparisons only.

Does not run inference or add source/generated videos to the repository.
"""
import argparse
import io
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    from PIL import Image,ImageDraw,ImageFont
    a=argparse.ArgumentParser();a.add_argument('--evidence-root',default='/home/wwhvw/文档/ChatGPT/生图/results')
    args=a.parse_args();e=Path(args.evidence_root);root=Path(__file__).resolve().parents[1]
    images=root/'docs/images';images.mkdir(exist_ok=True);docs=root/'docs/testing';docs.mkdir(exist_ok=True)
    read=lambda p:json.loads((e/p).read_text())
    records=[]
    def add(id,source,sha,video,width,height,seconds,frames,fps,pipeline,vram,total,rss,method,codec,scope,wall=None,crop=None):
        records.append(dict(id=id,status='historical_success',source_name=Path(source).name,source_sha256=sha,
                            width=width,height=height,duration_seconds=seconds,frames=frames,fps=fps,
                            pipeline_seconds=pipeline,end_to_end_seconds=wall,gpu_process_peak_gib=vram,gpu_total_peak_gib=total,
                            process_tree_rss_peak_gib=rss,method=method,codec=codec,timing_scope=scope,
                            comparison_image=f'../images/{id}.png'))
        return dict(record=records[-1],source=Path(source),video=Path(video),crop=crop)
    source='/home/wwhvw/视频/壁纸系列1.mp4';sha=read('flashvsr_10s_wallpaper/input_manifest.json')['sha256']
    work=[]
    for x in read('flashvsr_10s_wallpaper/summary.json')['outputs']:
        k=x['case'];w,h=(2560,1440) if k=='2k' else (3840,2160)
        work.append(add(f'flashvsr_wallpaper_10s_{k}',source,sha,x['video'],w,h,10,240,24,x['seconds'],x['vram_gib'],x['whole_gpu_vram_gib'],x['rss_gib'],x['mode'],'H264/libx264',
                        'Successful node execution plus final mux; isolated server startup excluded.',crop=(8,1,1360,765)))
    x=read('flashvsr_8k/summary.json')
    work.append(add('flashvsr_wallpaper_10s_8k',source,sha,x['video'],7680,4320,10,240,24,x['successful_pipeline_seconds'],x['gpu_process_peak_gib'],x['gpu_total_peak_gib'],x['rss_peak_gib'],
                    '3x2 overlapping tiles; two 5-second temporal segments; FFV1 intermediates','H264/libx264',
                    'Successful tile node execution + final composition/encode; failed native OOM and server startup excluded.',crop=(8,1,1360,765)))
    x=read('flashvsr_8k_optimized/opt_240f_ui/report.json');inp=read('flashvsr_8k_optimized/input.json')
    work.append(add('flashvsr_nv111_10s_8k',inp['source'],inp['sha256'],x['video'],4320,7680,10,240,24,x['pipeline_seconds'],x['sampled_peak_gpu_process_gib'],x['sampled_peak_gpu_total_gib'],x['sampled_peak_rss_gib'],
                    'Resident model; 120-frame chunks; six tiles; RAM tiles; streaming encode','HEVC/hevc_nvenc',
                    'Pipeline execution excludes isolated server startup; main UI wall time recorded separately.',wall=x['main_ui_wall_seconds']))
    x=read('flashvsr_action_4k/report.json');inp=read('flashvsr_action_4k/input.json')
    work.append(add('flashvsr_action_18s_4k',inp['source'],inp['sha256'],x['video'],2160,3840,1093/60,1093,60,x['pipeline_seconds'],x['sampled_peak_gpu_process_gib'],x['sampled_peak_gpu_total_gib'],x['sampled_peak_rss_gib'],
                    'Resident model; 120-frame chunks; two horizontal tiles; RAM tiles; streaming encode','HEVC/hevc_nvenc',
                    'Pipeline execution excludes isolated server startup; complete benchmark wall time recorded separately.',wall=x['end_to_end_seconds']))
    assets=read('flashvsr/sources/input_manifest.json')
    for x in read('flashvsr/summary.json'):
        records.append(dict(id='flashvsr_assets_5s_'+x['case'],status='historical_success',source_name=Path(assets['path']).name,source_sha256=assets['sha256'],
                            width=x['width'],height=x['height'],duration_seconds=5,frames=120,fps=24,pipeline_seconds=x['server_seconds'],end_to_end_seconds=None,
                            gpu_process_peak_gib=x['gpu_process_peak_gib'],gpu_total_peak_gib=x['gpu_total_peak_gib'],process_tree_rss_peak_gib=x['process_tree_rss_peak_gib'],
                            method='Native full spatial frame; one 5-second temporal segment',codec='H264/libx264',timing_scope='Cold model per isolated execution; warmed Triton; server startup excluded.',
                            comparison_image='../images/flashvsr_assets_5s.png',comparison_timestamp_seconds=2.,
                            comparison_note='Existing historical contact sheet uses source/output frame 48 at 24fps.'))
    for path,sha in [(Path(source),sha),(Path(inp['source']),inp['sha256']),(Path(assets['path']),assets['sha256'])]+[(x['source'],x['record']['source_sha256']) for x in work]:
        assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==sha,f'Historical source changed: {path}'
    shutil.copy2(e/'flashvsr/comparison.png',images/'flashvsr_assets_5s.png')
    fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font=ImageFont.truetype(fontpath,18);small=ImageFont.truetype(fontpath,14)
    def frame(path,t):
        data=subprocess.check_output(['ffmpeg','-hide_banner','-v','error','-threads','2','-ss',str(t),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'])
        return Image.open(io.BytesIO(data)).convert('RGB')
    for item in work:
        r=item['record'];t=(r['frames']//2)/r['fps'];original=frame(item['source'],t);out=frame(item['video'],t)
        assert out.size==(r['width'],r['height'])
        if item['crop']:
            x,y,w,h=item['crop'];original=original.crop((x,y,x+w,y+h))
        ratio=min(out.width/original.width,out.height/original.height)
        fitted=original.resize((round(original.width*ratio),round(original.height*ratio)),Image.Resampling.LANCZOS)
        reference=Image.new('RGB',out.size,(128,128,128));reference.paste(fitted,((out.width-fitted.width)//2,(out.height-fitted.height)//2))
        portrait=out.height>out.width;pw,ph=(360,640) if portrait else (768,432);cw=max(2*pw,1024);ch=ph+512+145
        canvas=Image.new('RGB',(cw,ch),(20,20,20));d=ImageDraw.Draw(canvas)
        d.text((16,12),f"{r['id']} | t={t:.3f}s | {out.width}x{out.height}",font=font,fill='white')
        x0=(cw-2*pw)//2
        d.text((x0+8,42),'SOURCE: Lanczos for display alignment',font=small,fill='white')
        d.text((x0+pw+8,42),'FLASHVSR OUTPUT: display scaled',font=small,fill='white')
        canvas.paste(reference.resize((pw,ph),Image.Resampling.LANCZOS),(x0,68));canvas.paste(out.resize((pw,ph),Image.Resampling.LANCZOS),(x0+pw,68))
        center=(.53,.20) if 'wallpaper' in r['id'] else (.52,.32) if 'action' in r['id'] else (.5,.5)
        cy=ph+100;rx=max(0,min(out.width-512,round(out.width*center[0])-256));ry=max(0,min(out.height-512,round(out.height*center[1])-256));roi=(rx,ry,rx+512,ry+512);dx=(cw-1024)//2
        d.text((dx+8,cy-25),'SOURCE ROI: aligned by Lanczos',font=small,fill='white')
        d.text((dx+520,cy-25),'OUTPUT ROI: 512x512 at 1:1',font=small,fill='white')
        canvas.paste(reference.crop(roi),(dx,cy));canvas.paste(out.crop(roi),(dx+512,cy))
        canvas.save(images/(r['id']+'.png'),optimize=True)
        r['comparison_timestamp_seconds']=t;r['comparison_roi_output_pixels']=list(roi)
        r['comparison_note']='Same timestamp; historical source crop/letterbox alignment; full views scaled for display. Source detail uses Lanczos alignment, not true high-resolution ground truth.'
        print('SCREENSHOT',r['id'],flush=True)
    pending=[dict(duration_seconds=15,resolution=k,status='not_tested',frames=None,fps=None,pipeline_seconds=None,gpu_process_peak_gib=None,process_tree_rss_peak_gib=None) for k in ('2K','4K','8K')]
    data=dict(date='2026-10-19',kind='Historical measurements, not full-length validation of the migrated ToolBox implementation',
              environment=dict(gpu='RTX 5090 D 32GB',ram_gib_approx=94,torch='2.11.0+cu130',python='3.13.12',triton='3.6.0',driver='595.58.03'),
              resource_method='Legacy isolated inference server + child processes; NVML process measurements exclude PIDs existing before server startup; RSS sums shared mappings; 0.1s sampling.',
              records=records,untested=pending,media_in_repository=False)
    (docs/'flashvsr_history_2026-10-19.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    def row(r):
        wall='—' if r['end_to_end_seconds'] is None else f"{r['end_to_end_seconds']:.3f}"
        return f"| {r['source_name']} / {r['width']}×{r['height']} | {r['duration_seconds']:.4f} | {r['frames']} / {r['fps']} | {r['pipeline_seconds']:.3f} | {wall} | {r['gpu_process_peak_gib']:.2f} / {r['gpu_total_peak_gib']:.2f} | {r['process_tree_rss_peak_gib']:.2f} |"
    text='''# FlashVSR 历史实测与迁移验证（2026-10-19）

## 已有历史记录

以下是迁移前真实记录，**不是新ToolBox实现的完整性能复测**。机器为RTX5090D 32GB、约94GiB主机RAM、Python3.13.12、Torch2.11/cu130、Triton3.6、驱动595.58.03。仅记录成功处理流程耗时，失败的整幅8K/OOM尝试不并入成功耗时。

| 素材 / 输出 | 时长s | 帧数 / fps | 流程耗时s | 端到端s | 进程 / 整卡显存GiB | 进程树RSS GiB |
|---|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(row(x) for x in records[:5])+'''

前三项同为壁纸10秒：2K整段、4K两个5秒段、8K两个5秒段×六块/FFV1；最后两项为不同素材/画幅的常驻流式优化。不同素材、画幅、codec和分块方式不能直接计算加速比。流程耗时通常排除临时服务启动，端到端仅在原始记录有此数据时列出，不补推。

| 15秒目标 | 状态 |
|---|---|
| 2K | 未测试 |
| 4K | 未测试 |
| 8K | 未测试 |

### 5秒补充记录

| 素材 / 输出 | 时长s | 帧数 / fps | 流程耗时s | 端到端s | 进程 / 整卡显存GiB | 进程树RSS GiB |
|---|---:|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(row(x) for x in records[5:])+'''

峰值来自0.1秒采样。旧记录为隔离ComfyUI与子进程，RSS可能重复计共享映射，整卡显存包含桌面/其他进程。完整参数、来源SHA256、编码与计时口径见[结构化历史数据](flashvsr_history_2026-10-19.json)。仓库不保存源视频、输出视频、模型或运行缓存，也不把新增纹理当作真实细节。

## 原片与输出截图

每项使用同一中间时间点，历史横屏裁切/竖屏补边按记录对齐。上排全景仅为显示缩放；下排输出为512×512的1:1细节，原片对应区域经Lanczos对齐，非真实4K/8K参考。截图取自实际视频，没有AI重绘。

'''
    for r in records[:5]:text+=f"### {r['id']}\n\n![原片与超分对比]({r['comparison_image']})\n\n"
    text+='### 早期5秒记录\n\n![同帧全景与局部](../images/flashvsr_assets_5s.png)\n\n## 本次迁移验证\n\n迁移验证采用短片，不补跑完整10/15秒矩阵。结果见 [迁移验证](flashvsr_migration_2026-10-19.json)。\n'
    document=docs/'flashvsr_2026-10-19.md'
    marker='\n### 本次验证结果\n'
    if document.exists() and marker in document.read_text():
        text+=marker+document.read_text().split(marker,1)[1]
    document.write_text(text)


if __name__=='__main__':main()
