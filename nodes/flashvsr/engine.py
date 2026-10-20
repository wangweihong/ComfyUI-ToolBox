"""Resident model adapter and bounded, normalized spatial composition."""
import contextlib
import gc
import hashlib
import importlib
import math
import subprocess
import tempfile
import time
from pathlib import Path


def read_exact(pipe, size):
    out = bytearray(size); view = memoryview(out); offset = 0
    while offset < size:
        n = pipe.readinto(view[offset:])
        if not n:
            raise RuntimeError(f'Video ended early: read {offset}/{size} bytes.')
        offset += n
    return out


def decode_frames(path, width, height, fps, count, start=0):
    import numpy as np
    cmd = ['ffmpeg','-hide_banner','-v','error','-xerror','-threads','2','-ss',str(start),'-i',str(path),
           '-map','0:v:0','-an','-vf','fps='+str(fps),'-frames:v',str(count),'-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)
        try:
            for _ in range(count):
                yield np.frombuffer(read_exact(p.stdout, width*height*3), np.uint8).reshape(height,width,3)
            rc = p.wait(timeout=30)
            if rc:
                log.seek(0); raise RuntimeError(log.read().decode(errors='replace'))
        finally:
            if p.poll() is None:
                p.kill(); p.wait()
            p.stdout.close()


def axis_weight(tile, points, index):
    import numpy as np
    weight = np.ones(tile*4, np.float32)
    if index:
        overlap = (points[index-1]+tile-points[index])*4
        if overlap:
            weight[:overlap] *= (np.arange(overlap, dtype=np.float32)+.5)/overlap
    if index+1 < len(points):
        overlap = (points[index]+tile-points[index+1])*4
        if overlap:
            weight[-overlap:] *= (np.arange(overlap, dtype=np.float32)[::-1]+.5)/overlap
    return weight


@contextlib.contextmanager
def load_backend(plan, info, guard):
    import torch
    import folder_paths
    import comfy.model_management as mm
    if not torch.cuda.is_available():
        raise RuntimeError('FlashVSR inference requires a supported NVIDIA CUDA GPU; CPU encoding does not provide CPU inference.')
    try:
        plus = importlib.import_module('custom_nodes.ComfyUI_FlashVSR.flashvsr_plus_node')
        utils = importlib.import_module('custom_nodes.ComfyUI_FlashVSR.model_loader_utils')
    except ImportError as exc:
        raise RuntimeError('Install the pinned ComfyUI_FlashVSR optional dependency; see ToolBox FlashVSR documentation.') from exc
    cfg = plan['config']; root = Path(folder_paths.models_dir)/'FlashVSR'
    for key in ('dit','projector','decoder','prompt_tensor'):
        if not (root/cfg[key]).is_file():
            raise RuntimeError(f'Missing FlashVSR model: {root/cfg[key]}')
    mm.unload_all_models(); mm.soft_empty_cache(); torch.cuda.reset_peak_memory_stats()
    model = decoder = None
    started = time.monotonic()
    try:
        guard.check()
        model = plus.build_plus_pipeline(str(root/cfg['dit']),str(root/cfg['projector']),plus_mode='turbo',
                                         plus_temporal='4',offload=False,plus_attn=cfg['attention'],emb_pt_path=str(root/cfg['prompt_tensor']))
        decoder = utils.load_vae_model('none',cfg['decoder'],'none',torch.device('cuda'))
        info['model_load_count'] = info['decoder_load_count'] = 1
        info['timings']['model_load_seconds'] = time.monotonic()-started
        def infer(image):
            guard.check(); t = time.monotonic()
            latent = plus.run_plus_denoise(model,image,plan['tile_width'],plan['tile_height'],cfg['seed'],4)
            info['timings']['denoise_seconds'] += time.monotonic()-t
            guard.check(); t = time.monotonic()
            images = plus.decode_plus_latents(latent,decoder,False,'wavelet')
            info['timings']['decode_seconds'] += time.monotonic()-t
            del latent
            return images
        yield infer
    except torch.OutOfMemoryError as exc:
        raise RuntimeError('FlashVSR CUDA OOM. Reduce tile_width/tile_height and chunk_frames; no silent parameter change was made.') from exc
    finally:
        del model, decoder
        gc.collect(); torch.cuda.empty_cache()


def release_mapping(raw):
    import numpy as np
    if isinstance(raw, np.memmap):
        raw.flush()
        try:
            import mmap
            raw._mmap.madvise(mmap.MADV_DONTNEED)
        except (AttributeError, OSError):
            pass


def iter_upscaled(plan, directory, info, guard):
    import numpy as np
    import torch
    from comfy.utils import common_upscale, ProgressBar
    directory = Path(directory); tiles_dir = directory/'tiles'; tiles_dir.mkdir(exist_ok=True)
    tw, th = plan['tile_width']*4, plan['tile_height']*4
    ww, wh = plan['lq_width']*4, plan['lq_height']*4
    wx = [axis_weight(plan['tile_width'],plan['xs'],i) for i in range(len(plan['xs']))]
    wy = [axis_weight(plan['tile_height'],plan['ys'],i) for i in range(len(plan['ys']))]
    coverage = np.zeros((wh,ww),np.float32)
    for r,y in enumerate(plan['ys']):
        for c,x in enumerate(plan['xs']):
            coverage[y*4:y*4+th,x*4:x*4+tw] += wy[r][:,None]*wx[c][None,:]
    if not np.all(coverage > 0):
        raise RuntimeError('Spatial plan contains uncovered pixels.')
    normalize = float(np.max(np.abs(coverage-1))) >= 1e-6
    acc = np.zeros((wh,ww,3),np.float32)
    count_tiles = math.ceil(plan['frames']/plan['chunk_frames'])*len(wx)*len(wy)
    bar = ProgressBar(count_tiles+plan['frames']); digest = hashlib.sha256()
    source = decode_frames(plan['source'],*plan['source_size'],plan['fps'],plan['frames'],plan['start_seconds'])
    tiles = []
    try:
        with load_backend(plan,info,guard) as infer:
            for offset in range(0,plan['frames'],plan['chunk_frames']):
                guard.check(); count = min(plan['chunk_frames'],plan['frames']-offset); t = time.monotonic()
                original = torch.from_numpy(np.stack([next(source) for _ in range(count)])).float().div_(255)
                scaled = common_upscale(original.movedim(-1,1),plan['fit_width'],plan['fit_height'],'lanczos','disabled').movedim(1,-1)
                canvas = torch.full((count,plan['lq_height'],plan['lq_width'],3),.5,dtype=torch.float32)
                fx,fy = plan['fit_x'],plan['fit_y'];canvas[:,fy:fy+plan['fit_height'],fx:fx+plan['fit_width']]=scaled
                del original,scaled
                info['timings']['prepare_seconds'] += time.monotonic()-t
                for r,y in enumerate(plan['ys']):
                    for c,x in enumerate(plan['xs']):
                        guard.check()
                        images = infer(canvas[:,y:y+plan['tile_height'],x:x+plan['tile_width']])
                        if tuple(images.shape) != (count,th,tw,3):
                            raise RuntimeError(f'Unexpected decoder shape: {tuple(images.shape)}')
                        t = time.monotonic(); shape = (count,th,tw,3)
                        path = tiles_dir/f'{r}_{c}.rgb'
                        raw = np.memmap(path,mode='w+',dtype=np.uint8,shape=shape) if plan['config']['tile_storage']=='disk' else np.empty(shape,np.uint8)
                        # Register before writing so cancellation also closes the
                        # current partially written map (important on Windows).
                        tiles.append((r,c,x*4,y*4,raw,path))
                        for f in range(count):
                            guard.check();raw[f]=np.clip(images[f].cpu().numpy()*255+.5,0,255).astype(np.uint8)
                        release_mapping(raw)
                        info['timings']['quantize_seconds'] += time.monotonic()-t
                        info['tile_calls'] += 1
                        del images; gc.collect(); bar.update(1)
                del canvas; t = time.monotonic()
                for f in range(count):
                    guard.check(); acc.fill(0)
                    for r,c,x,y,raw,path in tiles:
                        a=raw[f].astype(np.float32);a*=wy[r][:,None,None];a*=wx[c][None,:,None]
                        acc[y:y+th,x:x+tw]+=a
                        del a
                        if isinstance(raw,np.memmap):
                            try:
                                import mmap
                                raw._mmap.madvise(mmap.MADV_DONTNEED)
                            except (AttributeError,OSError):
                                pass
                    if normalize:
                        np.divide(acc,coverage[:,:,None],out=acc)
                    cx,cy=plan['crop_x'],plan['crop_y']
                    cropped=acc[cy:cy+plan['height'],cx:cx+plan['width']]
                    np.clip(cropped,0,255,out=cropped); np.rint(cropped,out=cropped)
                    rgb=cropped.astype(np.uint8);digest.update(memoryview(rgb))
                    info['frames_produced'] += 1;bar.update(1)
                    yield rgb
                info['timings']['compose_and_sink_seconds'] += time.monotonic()-t
                for *_,raw,path in tiles:
                    if isinstance(raw,np.memmap):raw._mmap.close()
                    path.unlink(missing_ok=True)
                tiles.clear();gc.collect()
        info['preencode_rgb_sha256'] = digest.hexdigest()
    finally:
        source.close()
        for *_,raw,path in tiles:
            if isinstance(raw,np.memmap):raw._mmap.close()
            path.unlink(missing_ok=True)
        for path in tiles_dir.glob('*.rgb'):
            path.unlink(missing_ok=True)
        tiles_dir.rmdir()
