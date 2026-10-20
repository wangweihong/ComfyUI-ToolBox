"""Metadata-only planning. Never import/load a model here."""
import hashlib
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

CACHE_MODES = ["请选择", "raw", "lossless", "stream"]
PRESETS = ["low_memory", "balanced", "tested", "custom"]
ALGORITHM_VERSION = '1.0.0'
WEIGHTS = {
    "dit": "turbo_dit_plus.safetensors",
    "projector": "lq_proj_in_plus_turbo.safetensors",
    "decoder": "TCDecoder_plus.ckpt",
    "prompt_tensor": "posi_prompt_plus.pth",
}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def probe(path):
    try:
        return json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:stream_tags=rotate:stream_side_data=rotation:format=duration",
            "-of", "json", str(path)], text=True))
    except FileNotFoundError as exc:
        raise RuntimeError("FlashVSR requires FFmpeg and ffprobe on PATH.") from exc


def file_source(video):
    # The base VIDEO implementation encodes to BytesIO. Do not invoke that
    # implicitly on an arbitrarily large IMAGE batch.
    method = getattr(video, "get_stream_source", None)
    if method is None or getattr(method, "__qualname__", "").startswith("VideoInput."):
        raise ValueError("Use a file-backed VIDEO, e.g. ComfyUI LoadVideo; implicit whole-video materialization is disabled.")
    source = method()
    if not isinstance(source, (str, Path)) or not Path(source).is_file():
        raise ValueError("FlashVSR input must be a local, file-backed VIDEO.")
    # A cropped VideoFromFile changes display geometry but its stream source is
    # still the original. Refuse to silently ignore that transform.
    meta = probe(source)
    stream = next(s for s in meta["streams"] if s["codec_type"] == "video")
    rotations=[x.get('rotation',0) for x in stream.get('side_data_list',[])]+[stream.get('tags',{}).get('rotate',0)]
    if any(float(x)%360 for x in rotations):
        raise ValueError('Input has rotation metadata. Normalize/save it first so its actual pixels match its display dimensions.')
    if tuple(video.get_dimensions()) != (stream["width"], stream["height"]):
        raise ValueError("Input has a virtual crop/rotation. Save it first, then load the resulting file.")
    trim = video.get_active_trim_window() if hasattr(video, "get_active_trim_window") else (0, 0)
    return Path(source).resolve(), meta, trim


def configuration(**kwargs):
    defaults = dict(cache_mode="请选择", preset="low_memory", resolution="4K", orientation="auto",
                    fps=0., start_seconds=0., duration_seconds=0., seed=20261018,
                    chunk_frames=8, tile_width=256, tile_height=256, overlap_x=32, overlap_y=32,
                    tile_storage="disk", memory_budget_gib=0., memory_reserve_gib=2.,
                    disk_budget_gib=0., disk_reserve_gib=1., cache_directory="",
                    cache_retention="cleanup_after_encode", attention="triton_block_sparse",
                    custom_width=0, custom_height=0, **WEIGHTS)
    defaults.update(kwargs)
    if defaults["cache_mode"] not in CACHE_MODES:
        raise ValueError("Unknown cache mode.")
    if defaults["preset"] not in PRESETS:
        raise ValueError("Unknown resource preset.")
    if defaults["resolution"] not in ("2K", "4K", "8K") or defaults["orientation"] not in ("auto", "landscape", "portrait"):
        raise ValueError("Invalid target size/orientation.")
    if defaults["tile_storage"] not in ("disk", "ram") or defaults["cache_retention"] not in ("cleanup_after_encode", "keep"):
        raise ValueError("Invalid storage or retention policy.")
    if defaults["attention"] not in ("triton_block_sparse", "sdpa"):
        raise ValueError("Invalid attention backend.")
    for k in ("fps", "start_seconds", "duration_seconds", "memory_budget_gib", "disk_budget_gib"):
        if not math.isfinite(float(defaults[k])) or float(defaults[k]) < 0:
            raise ValueError(f"{k} must be finite and nonnegative.")
    for k in ("memory_reserve_gib", "disk_reserve_gib"):
        if not math.isfinite(float(defaults[k])) or float(defaults[k]) < .25:
            raise ValueError(f"{k} must be at least 0.25 GiB.")
    for k in WEIGHTS:
        if Path(defaults[k]).name != defaults[k]:
            raise ValueError("Select model filenames from models/FlashVSR, not arbitrary paths.")
    return defaults


def positions(length, tile, overlap):
    if tile < 128 or tile % 32:
        raise ValueError("LQ tile dimensions must be >=128 and divisible by 32.")
    if overlap < 0 or overlap >= tile:
        raise ValueError("LQ overlap must be >=0 and smaller than the tile.")
    points = [0]
    while points[-1] + tile < length:
        points.append(min(points[-1] + tile - overlap, length - tile))
    return points


def make_plan(video, cfg):
    cfg = configuration(**cfg)
    if cfg["cache_mode"] == "请选择":
        raise ValueError("请先选择缓存模式：raw=未压缩磁盘缓存；lossless=无损压缩磁盘缓存；stream=编码阶段流式执行。不会自动替你选择。")
    source, meta, trim = file_source(video)
    s = next(s for s in meta["streams"] if s["codec_type"] == "video")
    rate = Fraction(str(cfg["fps"])) if cfg["fps"] else Fraction(s.get("avg_frame_rate") or s["r_frame_rate"])
    if rate <= 0:
        raise ValueError("Input has no valid frame rate; set fps explicitly.")
    raw_duration = float(s.get("duration", meta["format"]["duration"]))
    trim_start, trim_duration = map(float, trim)
    start = trim_start + cfg["start_seconds"]
    end = min(raw_duration, trim_start + trim_duration) if trim_duration > 0 else raw_duration
    if cfg["duration_seconds"] > 0:
        end = min(end, start + cfg["duration_seconds"])
    frames = math.floor((end - start) * float(rate) + 1e-4)
    if frames <= 0:
        raise ValueError("Selected video interval has no frames.")
    portrait = s["height"] > s["width"] if cfg["orientation"] == "auto" else cfg["orientation"] == "portrait"
    w, h = {"2K": (2560, 1440), "4K": (3840, 2160), "8K": (7680, 4320)}[cfg["resolution"]]
    if portrait:
        w, h = h, w
    if cfg["custom_width"] or cfg["custom_height"]:
        w, h = int(cfg["custom_width"]), int(cfg["custom_height"])
        if min(w, h) < 128 or max(w, h) > 8192 or w % 4 or h % 4:
            raise ValueError("Custom output dimensions must both be 128–8192 and divisible by 4.")
    bw, bh = w // 4, h // 4
    if cfg["preset"] == "low_memory":
        chunk, tw, th, ox, oy = 8, 256, 256, 32, 32
    elif cfg["preset"] == "balanced":
        chunk, tw, th, ox, oy = 32, 384, 384, 64, 64
    elif cfg["preset"] == "tested":
        chunk = 120
        if cfg["resolution"] == "8K":
            tw, th, ox, oy = (576, 704, 72, 96) if portrait else (704, 576, 96, 72)
        elif cfg["resolution"] == "4K" and portrait:
            tw, th, ox, oy = 320, 960, 100, 0
        else:
            tw, th = math.ceil(bw/32)*32, math.ceil(bh/32)*32
            ox = oy = 0
    else:
        chunk = int(cfg["chunk_frames"])
        tw, th, ox, oy = (int(cfg[k]) for k in ("tile_width", "tile_height", "overlap_x", "overlap_y"))
    if not 1 <= chunk <= 240:
        raise ValueError("chunk_frames must be between 1 and 240.")
    # Validate requested values before bounding a tile to the padded whole frame.
    positions(max(bw, tw), tw, ox); positions(max(bh, th), th, oy)
    tw, th = min(tw, max(128, math.ceil(bw/32)*32)), min(th, max(128, math.ceil(bh/32)*32))
    ox, oy = min(ox, tw-1), min(oy, th-1)
    lw, lh = max(bw, tw), max(bh, th)
    xs, ys = positions(lw, tw, ox), positions(lh, th, oy)
    scale = min(bw / s["width"], bh / s["height"])
    fitw, fith = round(s["width"]*scale), round(s["height"]*scale)
    tile_bytes = min(chunk, frames)*tw*th*16*3*len(xs)*len(ys)
    raw_bytes = frames*w*h*3
    stat = source.stat()
    compute_cfg = {k:v for k,v in cfg.items() if k not in ('cache_retention','cache_directory','memory_budget_gib','memory_reserve_gib','disk_budget_gib','disk_reserve_gib')}
    model_identity = {}
    try:
        import folder_paths
        for k in WEIGHTS:
            p = Path(folder_paths.models_dir)/'FlashVSR'/cfg[k]
            if p.is_file():
                st=p.stat();model_identity[k]=[st.st_size,st.st_mtime_ns]
    except ImportError:
        pass
    signature = hashlib.sha256(json_text({"algorithm":ALGORITHM_VERSION,"source": str(source), "mtime": stat.st_mtime_ns, "bytes": stat.st_size,
                                         "config": compute_cfg, "models":model_identity,"trim": trim}).encode()).hexdigest()
    return dict(config=cfg, signature=signature, source=str(source), source_size=[s["width"], s["height"]],source_fps=s.get('avg_frame_rate',s['r_frame_rate']),
                width=w, height=h, frames=frames, fps=str(rate), start_seconds=start,
                duration_seconds=float(frames/rate), has_audio=any(x["codec_type"]=="audio" for x in meta["streams"]),
                lq_width=lw, lq_height=lh, base_width=bw, base_height=bh,
                crop_x=(lw-bw)//2*4, crop_y=(lh-bh)//2*4,
                fit_width=fitw, fit_height=fith, fit_x=(lw-bw)//2+(bw-fitw)//2, fit_y=(lh-bh)//2+(bh-fith)//2,
                chunk_frames=chunk, tile_width=tw, tile_height=th, xs=xs, ys=ys,overlap_x=ox,overlap_y=oy,
                estimates={"raw_frame_cache_bytes": raw_bytes, "tile_cache_peak_bytes": tile_bytes,
                           "image_working_bytes": min(chunk, frames)*tw*th*16*3*4*6,
                           "lossless_cache_size": "content-dependent; raw size is a reference, not a guarantee"})
