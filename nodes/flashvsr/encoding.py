"""Explicit encoders: probe the target before writing (and before deferred inference)."""
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

ENCODERS = ["auto", "libx264", "libx265", "h264_nvenc", "hevc_nvenc"]


def nvenc_env():
    env = os.environ.copy()
    # Optional bridge for this machine's existing video-driver mount. Portable
    # installations normally use NVIDIA_DRIVER_CAPABILITIES=...video instead.
    try:
        import folder_paths
        p = Path(folder_paths.get_input_directory())/'.flashvsr_runtime/nvenc.json'
        if p.exists():
            m = json.loads(p.read_text())
            driver = subprocess.check_output(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], text=True).splitlines()[0].strip()
            if driver != m['driver']:
                raise RuntimeError("Mounted NVENC library version differs from the host driver; synchronize the video libraries.")
            env['LD_LIBRARY_PATH'] = m['library_directory'] + (':'+env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    except ImportError:
        pass
    return env


def codec_options(encoder, quality, preset):
    if encoder.endswith('_nvenc'):
        if preset!='auto' and preset not in ['p1','p2','p3','p4','p5','p6','p7']:
            raise ValueError('NVENC preset must be auto or p1–p7.')
        return ['-c:v', encoder, '-preset', preset if preset in ['p1','p2','p3','p4','p5','p6','p7'] else 'p5',
                '-rc', 'vbr', '-cq', str(quality), '-b:v', '0']
    if encoder in ('libx264', 'libx265'):
        if preset!='auto' and preset not in ['ultrafast','superfast','veryfast','faster','fast','medium','slow']:
            raise ValueError('CPU encoder preset must be auto/ultrafast/veryfast/fast/medium/slow.')
        args = ['-c:v', encoder, '-preset', preset if preset in ['ultrafast','superfast','veryfast','faster','fast','medium','slow'] else 'fast', '-crf', str(quality), '-threads', '4']
        if encoder == 'libx265':
            args += ['-x265-params', 'pools=2:frame-threads=2:log-level=error']
        return args
    raise ValueError("Unsupported encoder.")


def select_encoder(requested, plan, quality=18, preset='auto'):
    if requested not in ENCODERS:
        raise ValueError("Select auto, libx264, libx265, h264_nvenc or hevc_nvenc.")
    # Auto is itself an explicit user choice; never substitute another encoder
    # when a concrete encoder was selected.
    candidates = (['hevc_nvenc', 'libx264'] if max(plan['width'], plan['height']) > 4096
                  else ['h264_nvenc', 'libx264']) if requested == 'auto' else [requested]
    errors = []
    for candidate in candidates:
        try:
            env = nvenc_env() if candidate.endswith('_nvenc') else os.environ.copy()
            cmd = ['ffmpeg','-hide_banner','-v','error','-filter_threads','2','-f','lavfi','-i',
                   f"color=black:s={plan['width']}x{plan['height']}:r={plan['fps']}", '-frames:v','1']
            cmd += codec_options(candidate, quality, preset) + ['-pix_fmt','yuv420p','-f','null','-']
            r = subprocess.run(cmd, env=env, capture_output=True, timeout=45)
            if r.returncode:
                raise RuntimeError(r.stderr.decode(errors='replace')[-1800:])
            return candidate, env, errors
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(f'{candidate}: {exc}')
    raise RuntimeError('Encoder preflight failed at target dimensions; final video encoding did not start. '+ ' | '.join(errors))


def write_video(frames, plan, destination, encoder, *, quality=18, preset='auto', env=None, guard=None, metadata=None):
    """One bounded RGB pipe, and one continuous audio/video encode or cache mux."""
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    if guard:
        guard.output_directory=destination.parent
        guard.sample();guard.check()
    partial = destination.with_name(destination.stem+'.'+uuid.uuid4().hex[:8]+'.part'+destination.suffix)
    cmd = ['ffmpeg','-hide_banner','-v','error','-y','-filter_threads','2','-f','rawvideo','-pix_fmt','rgb24',
           '-color_range','pc','-s:v',f"{plan['width']}x{plan['height']}",'-r',plan['fps'],'-i','pipe:0',
           '-ss',str(plan['start_seconds']),'-i',plan['source'],'-map','0:v:0','-map','1:a:0?']
    if encoder == 'raw':
        cmd += ['-c:v','rawvideo','-pix_fmt','rgb24','-c:a','pcm_f32le','-f','nut']
    elif encoder == 'lossless':
        cmd += ['-c:v','ffv1','-level','3','-g','1','-threads','4','-pix_fmt','bgr0','-c:a','pcm_f32le','-f','matroska']
    else:
        cmd += codec_options(encoder, quality, preset)
        if encoder in ('libx265','hevc_nvenc') and destination.suffix == '.mp4':
            cmd += ['-tag:v','hvc1']
        cmd += ['-vf','scale=out_color_matrix=bt709:out_range=tv','-pix_fmt','yuv420p',
                '-color_primaries','bt709','-color_trc','iec61966-2-1','-colorspace','bt709','-c:a','aac','-b:a','192k']
        if destination.suffix == '.mp4':
            cmd += ['-movflags','+faststart']
    if metadata:
        value = json.dumps(metadata, ensure_ascii=False)
        if len(value.encode()) <= 64000:
            cmd += ['-metadata', 'comment='+value]
    cmd += ['-t',str(plan['duration_seconds']),str(partial)]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log, env=env)
        iterator = iter(frames); count = 0
        try:
            for frame in iterator:
                if guard:
                    guard.check()
                if frame.shape != (plan['height'], plan['width'], 3) or str(frame.dtype) != 'uint8':
                    raise ValueError('Encoder requires target-size RGB8 frames.')
                proc.stdin.write(frame.tobytes()); count += 1
            proc.stdin.close()
            rc = proc.wait(timeout=120)
            log.seek(0); error = log.read().decode(errors='replace')[-4000:]
            if rc or count != plan['frames']:
                raise RuntimeError(f'Video writer failed ({rc}); frames {count}/{plan["frames"]}. {error}')
            if guard:
                # Include the flushed file in quota checks before publishing it.
                guard.sample();guard.check()
            partial.replace(destination)
            return count
        except BaseException as exc:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            partial.unlink(missing_ok=True)
            if isinstance(exc, BrokenPipeError):
                log.seek(0)
                raise RuntimeError('FFmpeg pipe failed: '+log.read().decode(errors='replace')[-4000:]) from exc
            raise
        finally:
            close = getattr(iterator, 'close', None)
            if close:
                close()
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
