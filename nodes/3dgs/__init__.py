"""ToolBox 3DGS nodes; optional native dependencies are checked at execution."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np
from PIL import Image
import torch
import folder_paths

PACK = Path(__file__).resolve().parent


def require_pycolmap():
    if importlib.util.find_spec('pycolmap') is None:
        raise RuntimeError('PyCOLMAP is missing. Install the optional 3DGS dependencies from '
                           'Wheels-Containerfiles release 3dgs-v1, or build ComfyUI-Custom '
                           'with INSTALL_3DGS=true. See ComfyUI-ToolBox/docs/3dgs/README.md.')


def require_brush():
    binary = Path('/opt/3dgs/bin/brush_app')
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError('Brush is missing or not executable at /opt/3dgs/bin/brush_app. '
                           'Install the optional 3DGS dependencies or build ComfyUI-Custom '
                           'with INSTALL_3DGS=true. See ComfyUI-ToolBox/docs/3dgs/README.md.')
    return binary


def safe_name(name):
    name = name.strip()
    if not re.fullmatch(r'[\w\-]+', name):
        raise ValueError('Project name must contain only letters, numbers, underscores or hyphens.')
    return name


def run_logged(args, logfile, env=None):
    with open(logfile, 'w') as log:
        log.write('Command: ' + json.dumps(args, ensure_ascii=False) + '\n')
        log.flush()
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            while process.poll() is None:
                import comfy.model_management
                comfy.model_management.throw_exception_if_processing_interrupted()
                time.sleep(0.5)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        log.write(f'\nExit code: {process.returncode}\n')
    if process.returncode:
        raise RuntimeError(f'Command failed ({process.returncode}). Log: {logfile}\n' + Path(logfile).read_text(errors='replace')[-5000:])


class LocalCOLMAPDataset:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'images': ('IMAGE',),
            'project_name': ('STRING', {'default': 'orbit_test'}),
            'frame_step': ('INT', {'default': 2, 'min': 1, 'max': 24}),
            'drop_last': ('BOOLEAN', {'default': True}),
            'mapper': (['global', 'incremental'],),
            'matcher': (['exhaustive', 'sequential'],),
            'max_features': ('INT', {'default': 8192, 'min': 1024, 'max': 32768, 'step': 1024}),
        }}

    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('dataset_path', 'report')
    FUNCTION = 'export'
    CATEGORY = 'ToolBox/3DGS'
    OUTPUT_NODE = True

    def export(self, images, project_name, frame_step, drop_last, mapper, matcher, max_features):
        require_pycolmap()
        root = Path(folder_paths.get_output_directory()) / 'h3_gaussian_splat' / safe_name(project_name)
        # Every execution uses a new folder; previous experiments stay intact.
        root.mkdir(parents=True, exist_ok=True)
        import tempfile
        dataset = Path(tempfile.mkdtemp(prefix='dataset_', dir=root))
        dataset.chmod(0o755)
        frames = dataset / 'images'
        frames.mkdir()
        stop = len(images) - (1 if drop_last else 0)
        selected = list(range(0, stop, frame_step))
        if len(selected) < 4:
            raise ValueError('At least four distinct video frames are required.')
        for i, index in enumerate(selected):
            array = (images[index].detach().cpu().numpy().clip(0, 1) * 255).round().astype(np.uint8)
            Image.fromarray(array).save(frames / f'{i:05d}.png')
        cfg = dict(mapper=mapper, matcher=matcher, max_features=max_features,
                   selected_source_indices=selected, source_frames=len(images), camera_model='SIMPLE_PINHOLE')
        (dataset / 'config.json').write_text(json.dumps(cfg, indent=2))
        run_logged([sys.executable, str(PACK / 'sfm_worker.py'), str(dataset)], dataset / 'sfm.log')
        report = (dataset / 'report.json').read_text()
        return {'ui': {'text': [str(dataset), report]}, 'result': (str(dataset), report)}


class LocalVideoFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video_path': ('STRING', {'default': ''}),
                             'max_frames': ('INT', {'default': 500, 'min': 4, 'max': 2000})}}

    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'load'
    CATEGORY = 'ToolBox/3DGS'

    def load(self, video_path, max_frames):
        import cv2
        path = Path(video_path).expanduser().resolve()
        allowed = [Path(folder_paths.get_input_directory()).resolve(), Path(folder_paths.get_output_directory()).resolve()]
        if not any(path.is_relative_to(p) for p in allowed) or not path.is_file():
            raise ValueError('Select a video file inside ComfyUI input or output.')
        cap = cv2.VideoCapture(str(path))
        frames = []
        try:
            while len(frames) < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(torch.from_numpy(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).float() / 255)
        finally:
            cap.release()
        if len(frames) < 4:
            raise ValueError('Video contains fewer than four readable frames.')
        return (torch.stack(frames),)


class LocalBrushTrain:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'dataset_path': ('STRING', {'default': ''}),
            'steps': ('INT', {'default': 5000, 'min': 1000, 'max': 30000, 'step': 1000}),
            'max_resolution': ('INT', {'default': 768, 'min': 256, 'max': 2048, 'step': 64}),
            'max_splats': ('INT', {'default': 500000, 'min': 10000, 'max': 3000000, 'step': 10000}),
            'eval_every_nth': ('INT', {'default': 8, 'min': 0, 'max': 50}),
        }}

    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('ply_path', 'training_report')
    FUNCTION = 'train'
    OUTPUT_NODE = True
    CATEGORY = 'ToolBox/3DGS'

    def train(self, dataset_path, steps, max_resolution, max_splats, eval_every_nth):
        binary = require_brush()
        if not dataset_path.strip():
            raise ValueError('Select an existing COLMAP dataset under ComfyUI output; run workflow 01 or 02 first.')
        dataset = Path(dataset_path).resolve()
        if not dataset.is_relative_to(Path(folder_paths.get_output_directory()).resolve()):
            raise ValueError('Dataset must be inside ComfyUI output.')
        report = json.loads((dataset / 'report.json').read_text())
        if report['registered_images'] < 8:
            raise ValueError('Fewer than eight registered cameras; improve the orbit before training.')
        import comfy.model_management
        comfy.model_management.unload_all_models()
        comfy.model_management.soft_empty_cache()
        import tempfile
        dest = Path(tempfile.mkdtemp(prefix='brush_', dir=dataset))
        dest.chmod(0o755)
        env = os.environ.copy()
        env.setdefault('WGPU_BACKEND', 'vulkan')
        env.setdefault('XDG_RUNTIME_DIR', '/tmp')
        args = [str(binary), str(dataset), '--total-steps', str(steps), '--max-resolution', str(max_resolution),
                '--max-splats', str(max_splats), '--export-every', str(steps), '--export-path', str(dest),
                '--export-name', 'scene_{iter}.ply', '--eval-every', str(min(1000, steps)), '--eval-save-to-disk']
        if eval_every_nth:
            args += ['--eval-split-every', str(eval_every_nth)]
        start = time.monotonic()
        run_logged(args, dest / 'train.log', env)
        ply = dest / f'scene_{steps}.ply'
        if not ply.is_file() or ply.stat().st_size < 1000:
            raise RuntimeError(f'Brush exited without the expected PLY: {ply}')
        result = dict(ply_path=str(ply), seconds=round(time.monotonic()-start, 3), steps=steps,
                      max_resolution=max_resolution, max_splats=max_splats, eval_every_nth=eval_every_nth,
                      command=args, dataset_report=report)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        (dest / 'training_report.json').write_text(text)
        return {'ui': {'text': [text]}, 'result': (str(ply), text)}


class LocalPLYFile:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'ply_path': ('STRING', {'default': ''})}}

    RETURN_TYPES = ('FILE_3D_PLY',)
    FUNCTION = 'load'
    CATEGORY = 'ToolBox/3DGS'

    def load(self, ply_path):
        from comfy_api.latest import Types
        if not ply_path.strip():
            raise ValueError('Select a trained Gaussian PLY under ComfyUI output; run workflow 01, 02 or 03 first.')
        path = Path(ply_path).resolve()
        if not path.is_relative_to(Path(folder_paths.get_output_directory()).resolve()) or path.suffix.lower() != '.ply' or not path.is_file():
            raise ValueError('Select an existing PLY inside ComfyUI output.')
        return (Types.File3D(str(path)),)


NODE_CLASS_MAPPINGS = {'LocalCOLMAPDataset': LocalCOLMAPDataset, 'LocalVideoFrames': LocalVideoFrames,
                       'LocalBrushTrain': LocalBrushTrain, 'LocalPLYFile': LocalPLYFile}
NODE_DISPLAY_NAME_MAPPINGS = {'LocalCOLMAPDataset': 'COLMAP Dataset · Linux',
                              'LocalVideoFrames': 'Video Frames · Linux', 'LocalBrushTrain': 'Brush 3DGS Train · Linux',
                              'LocalPLYFile': 'Load Gaussian PLY · Linux'}
