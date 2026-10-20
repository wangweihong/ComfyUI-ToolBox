#!/usr/bin/env python3
"""Incremental FlashVSR deployment; never replace the complete live ToolBox."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

REGISTRATION = '''
# ToolBox FlashVSR managed extension
from .nodes.flashvsr import NODE_CLASS_MAPPINGS as _tb_flashvsr_nodes, NODE_DISPLAY_NAME_MAPPINGS as _tb_flashvsr_names
NODE_CLASS_MAPPINGS.update(_tb_flashvsr_nodes)
NODE_DISPLAY_NAME_MAPPINGS.update(_tb_flashvsr_names)
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--container',default='comfyui-test-cu130-megapak-pt211')
    parser.add_argument('--url',default='http://127.0.0.1:8188');parser.add_argument('--no-restart',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    q=json.load(urllib.request.urlopen(args.url+'/queue',timeout=10))
    if q['queue_running'] or q['queue_pending']:raise RuntimeError('ComfyUI queue is busy; deploy after it becomes idle.')
    mounts=json.loads(subprocess.check_output(['docker','inspect',args.container,'--format','{{json .Mounts}}'],text=True))
    mounts={x['Destination']:Path(x['Source']) for x in mounts if x['Type']=='bind'}
    live=mounts['/root/ComfyUI/custom_nodes']/'ComfyUI-ToolBox'
    runtime=mounts['/root/ComfyUI/input']/'.flashvsr_runtime';runtime.mkdir(exist_ok=True)
    backup=runtime/'migration_backups'/datetime.now().strftime('%Y%m%d_%H%M%S');backup.mkdir(parents=True)
    for p in [live/'node_mappings.py',runtime/'activate.sh']:
        if p.exists():shutil.copy2(p,backup/p.name)
    if (live/'nodes/flashvsr').exists():shutil.copytree(live/'nodes/flashvsr',backup/'previous_flashvsr')
    bundle=runtime/'toolbox_module';bundle.mkdir(exist_ok=True)
    shutil.copytree(root/'nodes/flashvsr',bundle/'flashvsr',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root/'web/js/flashvsr.js',bundle/'flashvsr.js')
    # Re-applied at startup to an ephemeral custom_nodes mount. Keep every
    # unrelated live module/registration as-is, including its database bind.
    activation='''#!/usr/bin/env bash
set -e
flashvsr_runtime_root="/root/ComfyUI/input/.flashvsr_runtime"
if [ -d "$flashvsr_runtime_root/custom_nodes/ComfyUI_FlashVSR" ]; then
  if [ -L /root/ComfyUI/custom_nodes/ComfyUI_FlashVSR ] || [ ! -e /root/ComfyUI/custom_nodes/ComfyUI_FlashVSR ]; then
    ln -sfn "$flashvsr_runtime_root/custom_nodes/ComfyUI_FlashVSR" /root/ComfyUI/custom_nodes/ComfyUI_FlashVSR
  fi
fi
python3.13 - <<'TB_FLASHVSR'
from pathlib import Path
import shutil
runtime=Path('/root/ComfyUI/input/.flashvsr_runtime')
toolbox=Path('/root/ComfyUI/custom_nodes/ComfyUI-ToolBox')
if not (toolbox/'node_mappings.py').exists():
    raise RuntimeError('Install ComfyUI-ToolBox before restoring its FlashVSR module.')
shutil.copytree(runtime/'toolbox_module/flashvsr',toolbox/'nodes/flashvsr',dirs_exist_ok=True)
(toolbox/'web/js').mkdir(parents=True,exist_ok=True)
shutil.copy2(runtime/'toolbox_module/flashvsr.js',toolbox/'web/js/flashvsr.js')
p=toolbox/'node_mappings.py';text=p.read_text()
if 'from .nodes.flashvsr import' not in text:
    p.write_text(text+REGISTRATION_TEXT)
old=Path('/root/ComfyUI/custom_nodes/ComfyUI-LocalFlashVSR')
if old.is_symlink():
    old.unlink()
elif old.exists():
    target=runtime/'retired_local_wrapper'
    if target.exists():raise RuntimeError('Archive the existing retired wrapper before replacing it.')
    shutil.move(str(old),str(target))
TB_FLASHVSR
'''.replace('REGISTRATION_TEXT',repr(REGISTRATION))
    (runtime/'activate.sh').write_text(activation)
    # Use container permissions only for its runtime; no chmod/chown of the
    # complete repository or shared model/workflow volumes.
    subprocess.run(['docker','exec',args.container,'bash','/root/ComfyUI/input/.flashvsr_runtime/activate.sh'],check=True)
    (backup/'deployment.json').write_text(json.dumps({'source':str(root),'live':str(live),'persistent_module':str(bundle),
                                                   'removed_node_ids':['LocalFlashVSRVideo','LocalFlashVSR8KOptimizedCore']},indent=2))
    if not args.no_restart:subprocess.run(['docker','restart',args.container],check=True)
    print('Incremental FlashVSR deployment complete. Backup:',backup)


if __name__=='__main__':main()
