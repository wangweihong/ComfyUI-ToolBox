#!/usr/bin/env python3
"""Short real-model API checks; media stay outside the repository and are removed."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid


def main():
    a=argparse.ArgumentParser();a.add_argument('--url',default='http://127.0.0.1:8188');a.add_argument('--container',default='comfyui-test-cu130-megapak-pt211')
    a.add_argument('--evidence',default='/tmp/toolbox_flashvsr_validation/live.json');a.add_argument('--resume',action='store_true');a.add_argument('--final-only',action='store_true');args=a.parse_args()
    def req(path,data=None):
        payload=json.dumps(data).encode() if data is not None else None
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(args.url+path,payload,{'Content-Type':'application/json'}),timeout=20))
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode()) from e
    info=req('/object_info');q=req('/queue');assert not(q['queue_running'] or q['queue_pending'])
    assert all(x in info for x in ['ToolBoxFlashVSRConfig','ToolBoxFlashVSRUpscale','ToolBoxVideoEncode'])
    assert not any(x in info for x in ['LocalFlashVSRVideo','LocalFlashVSR8KOptimizedCore'])
    defaults={}
    for name,spec in info['ToolBoxFlashVSRConfig']['input']['required'].items():
        opt=spec[1] if len(spec)>1 else {}
        defaults[name]=opt.get('default',spec[0][0] if isinstance(spec[0],list) else '')
    cases=[];artifacts=[];signatures=set()
    evidence=Path(args.evidence);evidence.parent.mkdir(parents=True,exist_ok=True)
    if args.resume and evidence.exists():cases=json.loads(evidence.read_text())['cases']
    def save():evidence.write_text(json.dumps({'cases':cases,'new_node_ids':[x for x in info if x.startswith('ToolBoxFlashVSR') or x=='ToolBoxVideoEncode'],
                                              'old_node_ids_absent':True,'media_retained':False},ensure_ascii=False,indent=2))
    def graph(mode='stream',**updates):
        cfg=dict(defaults,cache_mode=mode,preset='custom',duration_seconds=.125,chunk_frames=2,tile_width=128,tile_height=128,
                 overlap_x=16,overlap_y=16,custom_width=512,custom_height=384,cache_retention='keep',
                 cache_directory='/root/ComfyUI/temp/toolbox_flashvsr_validation')
        cfg.update(updates)
        return {'1':{'class_type':'LoadVideo','inputs':{'file':'clean_00005_.mp4'}},
                '2':{'class_type':'ToolBoxFlashVSRConfig','inputs':cfg},
                '3':{'class_type':'ToolBoxFlashVSRUpscale','inputs':{'video':['1',0],'config':['2',0]}},
                '4':{'class_type':'ToolBoxVideoEncode','inputs':{'video':['3',0],'encoder':'libx264','quality':18,'preset':'ultrafast',
                     'container':'mp4','save_to':'temp','filename_prefix':'toolbox_flashvsr_validation_outputs/video'}}}
    def execute(label,g,expect_error=False,expected_size=None,frames=3,fps=24):
        if args.resume:
            old=next((x for x in cases if x['case']==label),None)
            if old:return old
        started=time.monotonic();s=req('/prompt',{'prompt':g,'client_id':str(uuid.uuid4())});pid=s['prompt_id'];print('SUBMITTED',label,pid,flush=True)
        for _ in range(1200):
            history=req('/history/'+pid)
            if pid in history:break
            time.sleep(.5)
        else:raise RuntimeError('API timeout')
        h=history[pid];status=h['status']['status_str']
        record={'case':label,'status':status,'prompt_id':pid,'wall_seconds':time.monotonic()-started}
        if expect_error:
            assert status=='error',h
            record['error']=[v.get('exception_message') for k,v in h['status']['messages'] if k=='execution_error']
            assert '选择缓存模式' in str(record['error'])
        else:
            assert status=='success',h['status']
            for key,field in [('3','upscale_info'),('4','encode_info')]:
                values=h['outputs'].get(key,{}).get('flashvsr_info')
                if values:
                    record[field]=json.loads(values[0])
                    signature=record[field].get('signature')
                    if signature:signatures.add(signature)
            output=h['outputs']['4']['images'][0]
            root='/root/ComfyUI/temp' if output['type']=='temp' else '/root/ComfyUI/output'
            path=str(Path(root)/output['subfolder']/output['filename']);artifacts.append(path)
            raw=subprocess.check_output(['docker','exec',args.container,'ffprobe','-v','error','-show_entries',
                                         'stream=codec_name,codec_type,width,height,nb_frames,avg_frame_rate,duration:format=duration','-of','json',path])
            probe=json.loads(raw);v=next(x for x in probe['streams'] if x['codec_type']=='video')
            assert int(v['nb_frames'])==frames and v['avg_frame_rate']==f'{fps}/1',(label,probe)
            assert any(x['codec_type']=='audio' for x in probe['streams']),(label,probe)
            if expected_size:assert (v['width'],v['height'])==expected_size
            subprocess.run(['docker','exec',args.container,'ffmpeg','-v','error','-xerror','-threads','2','-i',path,'-f','null','-'],check=True)
            record['ffprobe']=probe
            record['cached_nodes']=[v.get('nodes',[]) for k,v in h['status']['messages'] if k=='execution_cached']
        cases.append(record);save();print('PASS',label,round(record['wall_seconds'],2),flush=True)
        return record
    try:
        if args.final_only:
            r=execute('final_stream_preflight_metadata',graph('stream'),expected_size=(512,384))
            assert r['upscale_info']['preflight']['disk_free_bytes']>0
            assert r['upscale_info']['resource_limits']['memory_reserve_gib']==2
            assert r['encode_info']['algorithm_version']=='1.0.0'
            prior=next(x for x in cases if x['case']=='real_model_stream')
            assert r['encode_info']['preencode_rgb_sha256']==prior['encode_info']['preencode_rgb_sha256']
            r=execute('final_owned_raw_cleanup',graph('raw',cache_retention='cleanup_after_encode'),expected_size=(512,384))
            assert r['encode_info']['cache']['valid'] is False
            r=execute('final_atomic_publish_guard',graph('stream'),expected_size=(512,384))
            assert r['encode_info']['status']=='completed' and r['encode_info']['preflight']['disk_free_bytes']>0
            print('FINAL FOCUSED VALIDATION COMPLETE',flush=True)
            return
        execute('unselected_stops_before_model',graph('请选择'),expect_error=True)
        hashes=[]
        for mode in ['raw','lossless','stream']:
            record=execute('real_model_'+mode,graph(mode),expected_size=(512,384))
            value=record['encode_info'];hashes.append(value['preencode_rgb_sha256'])
            assert value['model_load_count']==value['decoder_load_count']==1
            assert record['upscale_info']['status']==('prepared' if mode=='stream' else 'upscaled')
        assert len(set(hashes))==1,'Real model preencode RGB differs between cache modes'
        g=graph('raw');g['4']['inputs'].update(encoder='libx265',preset='fast')
        record=execute('cached_cpu_hevc_reencode',g,expected_size=(512,384))
        assert record.get('upscale_info',{}).get('cache_reused') or any('3' in row for row in record['cached_nodes']),record
        sig=record['encode_info']['signature'];assert req('/toolbox/flashvsr/cache/clear',{'signature':sig})['status']=='cleared'
        record=execute('cleared_cache_recomputes',graph('raw'),expected_size=(512,384))
        assert not any('3' in row for row in record['cached_nodes']) and not record.get('upscale_info',{}).get('cache_reused'),record
        g=graph('stream');g['4']={'class_type':'SaveVideo','inputs':{'video':['3',0],'format':'mp4','filename_prefix':'_toolbox_flashvsr_validation_standard/video'}}
        execute('standard_SaveVideo_connection',g,expected_size=(512,384))
        g=graph('stream',preset='balanced',custom_width=0,custom_height=0,resolution='2K',orientation='landscape')
        g['4']['inputs'].update(encoder='h264_nvenc',preset='p5')
        execute('2k_nvenc_balanced',g,expected_size=(2560,1440))
        g=graph('stream',preset='low_memory',custom_width=0,custom_height=0,resolution='4K',orientation='portrait')
        execute('4k_low_memory',g,expected_size=(2160,3840))
        g=graph('stream',preset='tested',custom_width=0,custom_height=0,resolution='8K',orientation='portrait',duration_seconds=2/24)
        g['1']['inputs']['file']='flashvsr_nv111_opt.mp4'
        execute('8k_tested_geometry',g,expected_size=(4320,7680),frames=2)
        g=graph('stream',duration_seconds=5/60)
        g['1']['inputs']['file']='动作参考.mp4'
        g['4']['inputs'].update(encoder='hevc_nvenc',preset='p5')
        execute('native_60fps_tail',g,expected_size=(512,384),frames=5,fps=60)
    finally:
        for signature in signatures:
            try:req('/toolbox/flashvsr/cache/clear',{'signature':signature})
            except Exception:pass
        # Only exact media paths produced by this script; do not touch user
        # source videos, historical artifacts or other ComfyUI output folders.
        if artifacts:
            code='from pathlib import Path\n'+''.join(f'Path({p!r}).unlink(missing_ok=True)\n' for p in artifacts)
            subprocess.run(['docker','exec',args.container,'python3.13','-c',code],check=True)
        save()
    print('LIVE VALIDATION COMPLETE',len(cases),flush=True)


if __name__=='__main__':main()
