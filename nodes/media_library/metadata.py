"""Read-only, bounded media inspection; no ComfyUI dependency."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageOps
from .vendor.image_meta import read_raw_metadata
from .generation import extract, PARSER_VERSION

IMAGE = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.avif'}
VIDEO = {'.mp4', '.webm', '.mov', '.mkv', '.avi', '.m4v', '.mpg', '.mpeg', '.wmv', '.ts'}
AUDIO = {'.mp3', '.wav', '.ogg', '.opus', '.flac', '.m4a', '.aac', '.aiff', '.wma'}
TEXT = {'.txt', '.md', '.json', '.yaml', '.yml', '.csv', '.tsv', '.log', '.srt', '.vtt', '.toml', '.xml', '.ini', '.py', '.js', '.ts', '.css', '.html', '.prompt'}
TEXT_LIMIT = 2 * 1024 * 1024


def kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.ts':
        try:
            with path.open('rb') as source: head = source.read(377)
            return 'video' if len(head) > 376 and head[0] == head[188] == head[376] == 0x47 else 'text'
        except OSError: return 'text'
    return 'image' if ext in IMAGE else 'video' if ext in VIDEO else 'audio' if ext in AUDIO else 'text' if ext in TEXT else 'ply' if ext == '.ply' else 'other'


def sidecars(path: Path) -> list[Path]:
    """Only unambiguous metadata companions; never guess that a .txt is a prompt."""
    candidates = [Path(str(path) + '.xmp'), Path(str(path) + '.json')]
    stem_xmp = path.with_suffix('.xmp')
    # A shared stem.xmp is ambiguous when e.g. clip.png and clip.mp4 coexist.
    if stem_xmp.is_file() and stem_xmp != path:
        siblings = [p for p in path.parent.glob(path.stem + '.*') if p != stem_xmp and p.suffix.lower() != '.xmp']
        if len(siblings) == 1 and siblings[0] == path:
            candidates.append(stem_xmp)
    return [p for p in candidates if p != path and p.is_file() and not p.is_symlink()]


def signature(path: Path) -> str:
    def stamp(p):
        s = p.stat()
        return f'{p}:{s.st_mtime_ns}:{s.st_size}:{s.st_ino}'
    return '|'.join(stamp(p) for p in [path, *sidecars(path)])


def read_text(path: Path) -> tuple[str, bool]:
    with path.open('rb') as f:
        data = f.read(TEXT_LIMIT + 1)
    clipped = len(data) > TEXT_LIMIT
    data = data[:TEXT_LIMIT]
    for encoding in ('utf-8-sig', 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8', 'gb18030'):
        try:
            return data.decode(encoding), clipped
        except UnicodeError:
            continue
    return data.decode('utf-8', errors='replace'), clipped


def inspect(path: Path) -> dict:
    category = kind(path)
    result = {'kind': category, 'properties': {}, 'raw': {}, 'summary': {}, 'text': '', 'errors': [], 'truncated': False}
    props, raw = result['properties'], result['raw']
    try:
        if category == 'image':
            with Image.open(path) as im:
                # Rotation must agree with the displayed image, without decoding it just for dimensions.
                w, h = im.size
                if im.getexif().get(274) in (5, 6, 7, 8):
                    w, h = h, w
                props.update(width=w, height=h, format=im.format, frames=getattr(im, 'n_frames', 1))
        elif category in ('video', 'audio'):
            if not shutil.which('ffprobe'):
                raise RuntimeError('未找到 ffprobe：无法读取媒体尺寸、时长及编码信息')
            proc = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=30)
            if proc.returncode:
                raise RuntimeError(proc.stderr.decode(errors='replace')[:1000] or 'ffprobe 无法读取文件')
            probe = json.loads(proc.stdout)
            raw['ffprobe'] = probe
            fmt = probe.get('format', {})
            streams = probe.get('streams', [])
            video = next((s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), {})
            audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
            duration = fmt.get('duration') or video.get('duration') or audio.get('duration')
            if duration is not None:
                value = float(duration)
                if math.isfinite(value): props['duration'] = value
            if video:
                props.update(width=video.get('width'), height=video.get('height'), video_codec=video.get('codec_name'))
                rotation = next((s.get('rotation', 0) for s in video.get('side_data_list', []) if 'rotation' in s), video.get('tags', {}).get('rotate', 0))
                if int(float(rotation)) % 180:
                    props['width'], props['height'] = props['height'], props['width']
                rate = video.get('avg_frame_rate') or video.get('r_frame_rate')
                try: props['fps'] = float(Fraction(rate))
                except (ValueError, ZeroDivisionError, TypeError): pass
                if video.get('sample_aspect_ratio') not in (None, '0:1', '1:1'):
                    props['sample_aspect_ratio'] = video['sample_aspect_ratio']
            if audio:
                props.update(audio_codec=audio.get('codec_name'), sample_rate=audio.get('sample_rate'), channels=audio.get('channels'))
            for tags in [fmt.get('tags', {}), *(s.get('tags', {}) for s in streams)]:
                for key, value in tags.items():
                    raw.setdefault(key, value)
        elif category == 'text':
            result['text'], result['truncated'] = read_text(path)
        elif category == 'ply':
            header = []
            with path.open('rb') as f:
                for _ in range(4096):
                    line = f.readline(8193)
                    if len(line) > 8192: raise ValueError('PLY 头部行过长')
                    if not line: raise ValueError('PLY 头部不完整')
                    text = line.decode('ascii', errors='replace').strip()
                    header.append(text)
                    parts = text.split()
                    if parts[:2] == ['element', 'vertex']: props['vertices'] = int(parts[2])
                    if parts[:2] == ['element', 'face']: props['faces'] = int(parts[2])
                    if parts[:1] == ['format']: props['format'] = ' '.join(parts[1:])
                    if text == 'end_header': break
                else: raise ValueError('PLY 头部超出读取限制')
            if header[0] != 'ply': raise ValueError('不是有效的 PLY 文件')
            raw['ply_header'] = '\n'.join(header)
    except Exception as exc:
        result['errors'].append(str(exc))
    if props.get('width') and props.get('height'):
        ratio = Fraction(props['width'], props['height'])
        props['aspect_ratio'] = f'{ratio.numerator}:{ratio.denominator}'
    try:
        embedded, clipped = read_raw_metadata(str(path)) if category in ('image', 'video') else ({}, False)
        raw.update(embedded)
        result['truncated'] |= clipped
        for sidecar in sidecars(path):
            text, clipped = read_text(sidecar)
            raw['sidecar:' + sidecar.name] = text
            result['truncated'] |= clipped
            if sidecar.suffix == '.json':
                try:
                    content = json.loads(text)
                    if isinstance(content, dict):
                        for k, v in content.items(): raw.setdefault(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
                except ValueError: result['errors'].append(f'{sidecar.name}：JSON 格式无效')
        # Some video muxers store the graph envelope in the container comment.
        for key in ('comment', 'COMMENT', 'Comment', 'description', 'Description'):
            value = raw.get(key)
            if isinstance(value, str):
                try:
                    envelope = json.loads(value)
                    if isinstance(envelope, dict):
                        for k in ('prompt', 'workflow'):
                            if k in envelope: raw.setdefault(k, envelope[k] if isinstance(envelope[k], str) else json.dumps(envelope[k], ensure_ascii=False))
                except ValueError: pass
        refresh_generation(result)
    except Exception as exc:
        result['errors'].append('元数据读取失败：' + str(exc))
    result['metadata_state'] = 'error' if result['errors'] else 'present' if raw else 'none'
    return result


def refresh_generation(info):
    info.update(extract(info.get('raw', {})))
    return info
