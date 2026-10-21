#!/usr/bin/env python3
"""Deploy only ToolBox/DanceMV changes to an existing local ComfyUI container."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IDS = ('DanceMVAnalyzeAudio', 'DanceMVIntentPlanner', 'DanceMVSaveWav',
       'DanceMVChoreography', 'DanceMVAfterVideo')
REMOTE_ROOT = '/root/ComfyUI/custom_nodes/ComfyUI-ToolBox'

PATCH_RUNTIME = r'''
import json
from pathlib import Path
import sys
p=json.load(sys.stdin)
root=Path('/root/ComfyUI/custom_nodes/ComfyUI-ToolBox')
f=root/'node_mappings.py';s=f.read_text()
if 'as dance_mv_nodes_mapping' not in s:
    imports='from .nodes.dance_mv import NODE_CLASS_MAPPINGS as dance_mv_nodes_mapping\nfrom .nodes.dance_mv import NODE_DISPLAY_NAME_MAPPINGS as dance_mv_display_mapping\n\n'
    s=s.replace('NODE_CLASS_MAPPINGS = {',imports+'NODE_CLASS_MAPPINGS = {',1)
    s=s.replace('NODE_CLASS_MAPPINGS = {\n','NODE_CLASS_MAPPINGS = {\n    **dance_mv_nodes_mapping,\n',1)
    s=s.replace('NODE_DISPLAY_NAME_MAPPINGS = {\n','NODE_DISPLAY_NAME_MAPPINGS = {\n    **dance_mv_display_mapping,\n',1)
f.write_text(s)
for language,entries in p['locales'].items():
    f=root/'locales'/language/'nodeDefs.json'
    current=json.loads(f.read_text());current.update(entries)
    f.write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
f=root/'README.md';s=f.read_text();start='<!-- TOOLBOX_DANCE_MV -->';end='<!-- /TOOLBOX_DANCE_MV -->'
fragment=start+p['readme_section']+end
if start in s and end in s:
    begin=s.index(start);finish=s.index(end,begin)+len(end)
    s=s[:begin]+fragment+s[finish:]
elif start not in s:
    s=s.rstrip()+'\n\n'+fragment+'\n'
f.write_text(s)
'''


def docker(container, *args, **kwargs):
    return subprocess.run(['docker', 'exec', container, *args], check=True, **kwargs)


def wait_idle(base):
    last_message=0
    while True:
        with urllib.request.urlopen(base+'/queue', timeout=15) as response:
            queue=json.load(response)
        if not queue['queue_running'] and not queue['queue_pending']:
            return
        if time.monotonic()-last_message>=30:
            print('Waiting for existing ComfyUI jobs to finish before disabling the standalone package and restarting.',flush=True)
            last_message=time.monotonic()
        time.sleep(3)


def deploy(container, backup, restart=False, base='http://127.0.0.1:8188'):
    backup.mkdir(parents=True, exist_ok=True)
    runtime=backup/'runtime_before'
    for rel in ['node_mappings.py','README.md','locales/en/nodeDefs.json','locales/zh/nodeDefs.json']:
        target=runtime/rel;target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['docker','cp',container+':'+REMOTE_ROOT+'/'+rel,str(target)],check=True)
    present=subprocess.check_output(['docker','exec',container,'python3.13','-c',
        'from pathlib import Path;print(Path("/root/ComfyUI/custom_nodes/ComfyUI-H3-DanceMV").is_dir())'],text=True).strip()=='True'
    if present:
        subprocess.run(['docker','cp',container+':/root/ComfyUI/custom_nodes/ComfyUI-H3-DanceMV',str(backup/'standalone_runtime')],check=True)
    subprocess.run(['docker','cp',str(ROOT/'nodes/dance_mv'),container+':'+REMOTE_ROOT+'/nodes/'],check=True)
    docker(container,'mkdir','-p',REMOTE_ROOT+'/docs',REMOTE_ROOT+'/examples/dance_mv')
    for source,destination in [(ROOT/'docs/dance_mv.md',REMOTE_ROOT+'/docs/dance_mv.md'),
        (ROOT/'requirements-dance-mv.txt',REMOTE_ROOT+'/requirements-dance-mv.txt')]:
        subprocess.run(['docker','cp',str(source),container+':'+destination],check=True)
    subprocess.run(['docker','cp',str(ROOT/'examples/dance_mv')+'/.',container+':'+REMOTE_ROOT+'/examples/dance_mv/'],check=True)
    locales={}
    for language in ['en','zh']:
        data=json.loads((ROOT/'locales'/language/'nodeDefs.json').read_text())
        locales[language]={key:data[key] for key in IDS}
    readme=(ROOT/'README.md').read_text()
    section=readme.split('<!-- TOOLBOX_DANCE_MV -->',1)[1].split('<!-- /TOOLBOX_DANCE_MV -->',1)[0]
    subprocess.run(['docker','exec','-i',container,'python3.13','-c',PATCH_RUNTIME],
        input=json.dumps({'locales':locales,'readme_section':section},ensure_ascii=False).encode(),check=True)
    # No inference/tests are run. Queue inspection only protects existing work.
    wait_idle(base)
    inactive='/root/ComfyUI-disabled/DanceMV-'+backup.name
    if present:
        code='from pathlib import Path;import shutil;src=Path("/root/ComfyUI/custom_nodes/ComfyUI-H3-DanceMV");dst=Path('+repr(inactive)+');dst.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(src),str(dst))'
        docker(container,'python3.13','-c',code)
    permanent=Path('/media/wwhvw/备份/comfyui/custom_nodes/ComfyUI-H3-DanceMV')
    if permanent.exists():
        shutil.move(str(permanent),str(backup/'standalone_persistent'))
    state={'source':str(ROOT/'nodes/dance_mv'),'container':container,'runtime':REMOTE_ROOT+'/nodes/dance_mv',
           'standalone_runtime_backup':inactive if present else None,'backup':str(backup),
           'tests':'skipped_by_user','music_or_video_generation':'not_run','restarted':False,'service_ready':False}
    if restart:
        # Recheck immediately before restart in case a new job was queued.
        wait_idle(base)
        subprocess.run(['docker','restart',container],check=True)
        state['restarted']=True
        for attempt in range(90):
            try:
                with urllib.request.urlopen(base+'/system_stats',timeout=2) as response:
                    if response.status==200:
                        state['service_ready']=True
                        break
            except (OSError,ValueError):
                pass
            if attempt%15==0:print('Waiting for ComfyUI startup...',flush=True)
            time.sleep(2)
    (backup/'deployment.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(state,ensure_ascii=False,indent=2),flush=True)
    return state


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--container',default='comfyui-test-cu130-megapak-pt211')
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--restart',action='store_true')
    args=parser.parse_args()
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S')
    backup=args.backup_dir or Path.home()/'.cache/comfyui-toolbox/dance_mv_migrations'/stamp
    deploy(args.container,backup,args.restart)
