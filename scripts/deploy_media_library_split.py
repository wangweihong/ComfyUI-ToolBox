"""Deploy the ToolBox/StockingTexture split with a persistent code backup.

Run from the host: python3 scripts/deploy_media_library_split.py [container].
The original media-library plugin is disabled by renaming, never deleted.
"""
from pathlib import Path
import argparse
import json
import subprocess
import tarfile
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
STOCKING = ROOT.parent / "ComfyUI-StockingTexture"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def read_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


CONTAINER_DEPLOY = r'''
from pathlib import Path
import json, shutil, sys, tarfile
mode, stage, backup = sys.argv[1:]
stage, backup = Path(stage), Path(backup)
custom = Path('/root/ComfyUI/custom_nodes')
toolbox = custom / 'ComfyUI-ToolBox'
stocking = custom / 'ComfyUI-StockingTexture'
media = custom / 'comfyui-media-library'
disabled = custom / 'comfyui-media-library.disabled'
keep = {'.git', 'data', 'prompts'}

def copy_code(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('.git', 'data', 'prompts', '__pycache__', '.pytest_cache', 'node_modules'))

def clear_code(path):
    for entry in path.iterdir():
        if entry.name in keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()

if mode == 'deploy':
    if media.exists() and disabled.exists():
        raise RuntimeError('Both active and disabled media-library directories exist; refusing to overwrite either')
    backup.mkdir(parents=True, exist_ok=False)
    state = {'stocking_existed': stocking.exists(), 'media_disabled': media.exists()}
    (backup / 'state.json').write_text(json.dumps(state))
    copy_code(toolbox, backup / 'ComfyUI-ToolBox')
    if stocking.exists():
        copy_code(stocking, backup / 'ComfyUI-StockingTexture')
    (backup / 'ready').touch()
    # Remove obsolete code, including old stocking extension entry points. Data stays in place.
    clear_code(toolbox)
    with tarfile.open(stage / 'toolbox.tar') as archive:
        archive.extractall(toolbox, filter='data')
    stocking.mkdir(exist_ok=True)
    if state['stocking_existed']:
        clear_code(stocking)
    with tarfile.open(stage / 'stocking.tar') as archive:
        archive.extractall(stocking, filter='data')
    if state['media_disabled']:
        media.rename(disabled)
    print(str(backup))
else:
    if not (backup / 'ready').exists():
        print('Deployment did not reach the mutation phase; no restore needed.')
        sys.exit(0)
    state = json.loads((backup / 'state.json').read_text())
    clear_code(toolbox)
    copy_code(backup / 'ComfyUI-ToolBox', toolbox)
    if state['stocking_existed']:
        clear_code(stocking)
        copy_code(backup / 'ComfyUI-StockingTexture', stocking)
    elif stocking.exists():
        stocking.rename(backup / 'failed-StockingTexture')
    if state['media_disabled'] and disabled.exists():
        disabled.rename(media)
    print('Restored plugin code from', backup)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('container', nargs='?', default='comfyui-test-cu130-megapak-pt211')
    parser.add_argument('--url', default='http://127.0.0.1:8188')
    args = parser.parse_args()
    queue = read_json(args.url + '/queue')
    if queue['queue_running'] or queue['queue_pending']:
        raise SystemExit('ComfyUI queue is not empty; deployment was not started.')
    stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    stage = '/tmp/toolbox-media-split-' + stamp
    backup = '/root/ComfyUI/user/toolbox-plugin-backups/media-split-' + stamp
    with tempfile.TemporaryDirectory(prefix='toolbox-media-split-') as temporary:
        temporary = Path(temporary)
        for name, repo in [('toolbox', ROOT), ('stocking', STOCKING)]:
            files = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-co', '--exclude-standard', '-z']).decode().split('\0')
            with tarfile.open(temporary / (name + '.tar'), 'w') as archive:
                for relative in sorted(set(files)):
                    path = repo / relative
                    if relative and path.is_file():
                        archive.add(path, arcname=relative, recursive=False)
        run('docker', 'exec', args.container, 'mkdir', '-p', stage)
        for name in ['toolbox.tar', 'stocking.tar']:
            run('docker', 'cp', str(temporary / name), args.container + ':' + stage + '/' + name)
        try:
            run('docker', 'exec', '-i', args.container, 'python3.13', '-', 'deploy', stage, backup, input=CONTAINER_DEPLOY)
            run('docker', 'restart', args.container)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    nodes = read_json(args.url + '/object_info')
                    roots = read_json(args.url + '/toolbox/media-library/roots')
                    if 'ToolBoxMediaLibrary' not in nodes or 'NFStockingTexture' not in nodes or 'MediaLibraryPath' in nodes:
                        raise RuntimeError('Unexpected node registry after restart')
                    assert roots['roots']
                    print('Deployment ready. Backup:', backup)
                    return
                except Exception:
                    time.sleep(2)
            raise RuntimeError('ComfyUI did not pass startup verification within 180 seconds')
        except BaseException:
            run('docker', 'exec', '-i', args.container, 'python3.13', '-', 'rollback', stage, backup, input=CONTAINER_DEPLOY)
            run('docker', 'restart', args.container)
            raise


if __name__ == '__main__':
    main()
