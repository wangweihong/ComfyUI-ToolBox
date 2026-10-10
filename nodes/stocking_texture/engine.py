"""Headless solver/render pipeline. The browser and queue use these same functions."""
import threading
import copy
import time
import warnings

import cv2
import numpy as np
from scipy.sparse.linalg import MatrixRankWarning

from . import data
from .cache import REGION_CACHE, SCENE_CACHE
from .core import coverage, guide_fields as gf, look, walls
from .styles import base_style, PATTERNS
from .effects import clean_effects, render_effects
from .render_options import clean_options, soft_layer

ALGORITHM_VERSION = "ad4cc92-v1"
_solve_lock = threading.RLock()


def interrupt():
    try:
        import comfy.model_management as mm
    except ImportError:
        return
    mm.throw_exception_if_processing_interrupted()


def tensor(arr):
    import torch
    return torch.from_numpy(np.ascontiguousarray(arr, dtype=np.float32))


def build_guides(images, text, mask=None, mode="shared"):
    b, h, w, _ = images.shape
    doc = data.parse_guides(text, h, w, b, mode, external=mask is not None)
    external = data.mask_batch(mask, b, h, w)
    masks = [data.frame_masks(doc["frames"][0 if mode == "shared" else i], h, w, external[i]) for i in range(b)]
    return {"document": doc, "masks": masks, "mode": mode}, external


def depth_batch(depth, images, direction="white_near"):
    if depth is None:
        return [None] * len(images)
    arr = data.image_batch(depth)
    b, h, w, _ = images.shape
    if len(arr) not in (1, b):
        raise ValueError("深度数量必须为 1 或 IMAGE 批次数")
    if not np.allclose(arr[..., 0], arr[..., 1], atol=1 / 255) or not np.allclose(arr[..., 0], arr[..., 2], atol=1 / 255):
        raise ValueError("深度必须是灰度图，不能使用伪彩色深度图")
    if direction not in ("white_near", "black_near"):
        raise ValueError("未知深度方向")
    result = []
    for i in range(b):
        d = arr[0 if len(arr) == 1 else i, ..., 0]
        d = cv2.resize(d, (w, h), interpolation=cv2.INTER_LINEAR)
        lo, hi = float(d.min()), float(d.max())
        # A constant map contains no geometric information, including for sparkle weights.
        result.append(None if hi - lo < 1e-6 else ((d - lo) / (hi - lo) if direction == "white_near" else (hi - d) / (hi - lo)))
    return result


def raster(lines, shape, value=255, width=5):
    result = np.zeros(shape, np.uint8)
    for line in lines:
        pts = np.round(np.asarray(line, np.float64) * 16).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(result, [pts], False, value, width, cv2.LINE_8, 4)
    return result


def label_masks(masks, shape):
    reg = np.zeros(shape, np.int8)
    soft = np.zeros(shape, np.float32)
    for i, m in enumerate(masks, 1):
        inside = m > 0.5
        reg[inside] = i
        soft[inside] = m[inside]
    return reg, soft


def solve_one(image, frame, masks, depth=None, auto_walls=True):
    start = time.perf_counter()
    h, w = image.shape[:2]
    reg, soft = label_masks(masks, (h, w))
    values = [np.zeros((h, w), np.float32) for _ in range(4)]
    cut = np.zeros((h, w), bool)
    wall_map = np.zeros((h, w), bool)
    auto_map = np.zeros((h, w), bool)
    filled = {}
    guided = np.zeros((h, w), bool)
    stock, _ = coverage.stocking_coverage(coverage.lab_of(data.rgb8(image)), reg)
    scale = float(np.sqrt(h * w / look.REF_AREA))
    ridges = walls.ridges(depth, scale) if depth is not None and auto_walls and min(h, w) >= 2 else None
    hits, misses = 0, 0
    notes = []
    with _solve_lock:
        for i, region in enumerate(frame["regions"], 1):
            interrupt()
            m = reg == i
            box = gf.region_box(m, margin=8)
            if box is None:
                continue
            y0, y1, x0, x1 = box
            sl = (slice(y0, y1), slice(x0, x1))
            mc = m[sl]
            # Transform the region's polylines to its crop before rasterizing.
            shift = np.array([x0, y0])
            strokes = [(np.asarray(p) - shift).tolist() for p in region.get("strokes", [])]
            dividers = [(np.asarray(p) - shift).tolist() for p in region.get("walls", [])]
            stroke = raster(strokes, mc.shape)
            wall = raster(dividers, mc.shape, value=1, width=3) > 0
            if ridges is not None and strokes:
                auto = walls.find_walls(walls.crop(ridges, sl), stock[sl] & mc, scale)
                erased = frame.get("wall_erasures", [])
                if erased and auto.any():
                    _, labels = cv2.connectedComponents(auto.astype(np.uint8), connectivity=8)
                    ys, xs = np.nonzero(labels)
                    gone = set()
                    for x, y in erased:
                        near = np.hypot(xs + x0 - x, ys + y0 - y) <= 12 * scale
                        gone.update(labels[ys[near], xs[near]].tolist())
                    auto &= ~np.isin(labels, list(gone))
                auto_map[sl] |= auto & mc
                wall |= auto
            wall_map[sl] |= wall & mc
            sig = data.digest(ALGORITHM_VERSION, mc, stroke, wall)
            cached = REGION_CACHE.get(sig)
            if cached is None:
                misses += 1
                info = {}
                # A domain smaller than the 1/4 grid or a vanished thin component cannot constrain a field.
                grid = cv2.resize(mc.astype(np.uint8), (max(1, mc.shape[1] // gf.SC), max(1, mc.shape[0] // gf.SC)), interpolation=cv2.INTER_NEAREST)
                res = None
                if min(mc.shape) >= 8 and grid.sum() >= 4 and np.count_nonzero(stroke & mc) >= gf.MIN_STROKE_PX:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", MatrixRankWarning)
                        try:
                            res = gf.solve_region(mc, stroke, wall if wall.any() else None, info)
                        except MatrixRankWarning:
                            notes.append(f"{region['name']}: 部位过窄或引导无法约束求解")
                cached = {"result": res, "cut": info.get("cut")}
                REGION_CACHE.put(sig, cached)
            else:
                hits += 1
            res = cached["result"]
            if res is None:
                continue
            valid = mc & np.isfinite(res[0])
            if not all(np.isfinite(z[valid]).all() for z in res):
                raise ValueError(f"{region['name']}: 求解产生非有限数值，请检查走向或隔开线")
            guided[sl] |= valid
            for dst, src in zip(values, res):
                dst[sl][valid] = src[valid]
            if cached["cut"] is not None:
                cut[sl] |= cached["cut"] & mc
            gap = gf.fill_occlusions(mc) & ~mc & (reg[sl] == 0)
            if cached["cut"] is not None:
                gap &= ~cached["cut"]
            if gap.any():
                filled[i] = np.zeros((h, w), bool)
                filled[i][sl] = gap
    if depth is None:
        notes.append("未提供有效深度：跳过自动隔开与深度亮点")
    result = {"reg": reg, "soft": soft, "V": values[0], "NX": values[1], "NY": values[2], "A": values[3],
              "cut": cut, "walls": wall_map, "unguided": (reg > 0) & ~guided, "depth": depth,
              "names": [r["name"] for r in frame["regions"]], "solve_seconds": time.perf_counter() - start,
              "cache_hits": hits, "cache_misses": misses, "notes": notes}
    result.update(auto_walls=auto_map, fill=filled, sparkle=frame.get("sparkle", ""))
    result["damage_strokes"] = [copy.deepcopy(r.get("damage_strokes", [])) for r in frame["regions"]]
    result["signature"] = data.digest(ALGORITHM_VERSION, reg, soft, values[0], values[3], cut, depth, result["names"], result["unguided"])
    return result


def solve_batch(images, guides, depth=None, direction="white_near", auto_walls=True):
    h, w = images.shape[1:3]
    doc = guides.get("document", {})
    if (doc.get("height"), doc.get("width")) != (h, w) or len(guides.get("masks", [])) != len(images):
        raise ValueError("引导与 IMAGE 的尺寸或批次数不一致，请重新运行编辑节点")
    disparities = depth_batch(depth, images, direction)
    fields = []
    for i, image in enumerate(images):
        interrupt()
        frame = doc["frames"][0 if guides["mode"] == "shared" else i]
        fields.append(solve_one(image, frame, guides["masks"][i], disparities[i], auto_walls))
    return {"frames": fields, "shape": tuple(images.shape)}


def isolines(image, field, step=16):
    import contourpy
    out = data.rgb8(image).copy()
    reg = field["reg"]
    colors = [(70, 230, 180), (255, 180, 90), (150, 170, 255), (255, 120, 200)]
    for i in range(1, len(field["names"]) + 1):
        m = (reg == i) & ~field["unguided"] & ~field["cut"]
        if not m.any() or min(m.shape) < 2:
            continue
        v = field["V"]
        lo, hi = np.percentile(v[m], [0.5, 99.5])
        gen = contourpy.contour_generator(z=np.ma.array(v, mask=~m))
        for lv in np.arange(lo, hi, step):
            pts = [np.round(p).astype(np.int32).reshape(-1, 1, 2) for p in gen.lines(lv) if len(p) >= 2]
            cv2.polylines(out, pts, False, colors[(i - 1) % len(colors)], 1, cv2.LINE_AA)
    out[field["walls"]] = (255, 100, 80)
    out[field["unguided"]] = np.round(0.6 * out[field["unguided"]] + np.array([255, 220, 0]) * 0.4).astype(np.uint8)
    return out


def scene_for(image, f, color_exclude=True, seed=look.SEED, painted=None, renderer_version="legacy"):
    renderer = look
    if renderer_version == "upstream_f74c8ac":
        from .upstream import look as renderer
    if f.get("sparkle"):
        imported = data.decode_mask(f["sparkle"], *image.shape[:2])
        painted = imported if painted is None else np.maximum(imported, painted)
    art = data.rgb8(image)
    fill_signature = data.digest(*[data.digest(k, v) for k, v in f.get("fill", {}).items()]) if renderer_version != "legacy" else ""
    key = data.digest(ALGORITHM_VERSION, renderer_version, art, f["signature"], fill_signature, color_exclude, int(seed), painted)
    scene = SCENE_CACHE.get(key)
    if scene is None:
        reg = np.where(f["unguided"], 0, f["reg"]).astype(np.int8)
        stock, alpha = coverage.stocking_coverage(coverage.lab_of(art), reg, exclude=color_exclude)
        alpha *= f["soft"]
        depth_value = f["depth"]
        extra = {"fill": f.get("fill")} if renderer_version != "legacy" else {}
        scene = renderer.Scene(art, reg, f["V"], f["A"], stock, alpha, f["names"],
                           sparkle=None if painted is None else np.round(painted * 255).astype(np.uint8),
                           disparity=(lambda: depth_value) if depth_value is not None else None, cut=f["cut"], seed=seed, **extra)
        scene._nf_depth = depth_value  # Include the callback's retained map in the byte budget.
        SCENE_CACHE.put(key, scene)
    return scene


def guide_overlays(field, options):
    """Bounded vector overlays for selection/deletion in image coordinates."""
    import contourpy
    result = {}
    valid = (field["reg"] > 0) & ~field["unguided"]
    for key, name in (("V", "courses"), ("A", "wales")):
        if not options.get(name) or not valid.any():
            continue
        value = field[key]
        low, high = np.percentile(value[valid], [1, 99])
        step = max(.5, (high - low) / 48)
        gen = contourpy.contour_generator(z=np.ma.array(value, mask=~valid))
        paths = []
        count = 0
        for level in np.arange(low, high, step):
            for p in gen.lines(level):
                p = p[::max(1, len(p) // 256)]
                if count + len(p) > 50000:
                    break
                paths.append(p.tolist()); count += len(p)
        result[name] = paths
    if options.get("auto_walls"):
        from .upstream.trace import trace_lines
        result["auto_walls"] = [p.tolist() for p in trace_lines(field.get("auto_walls", np.zeros_like(valid)).astype(np.uint8) * 255)]
    return result


def clean_params(params, depth_available=True):
    options = clean_options(params)
    renderer = look
    if options["renderer_version"] != "legacy":
        from .upstream import look as renderer
    for k, value in params.items():
        if isinstance(value, (int, float)) and not np.isfinite(value):
            raise ValueError(f"参数 {k} 必须为有限数值")
    # Sources stay independent in ComfyUI; the desktop's linked sliders are a UI convenience.
    q = renderer.clean_params(dict(params, style=base_style(params.get("style", "knit")), sparkle_link=options["sparkle_link"]))
    if options["moire_on"] and options["moire"] > 0 and not depth_available:
        raise ValueError("摩尔纹需要有效灰度深度图，请连接 depth 输入")
    if not depth_available:
        q["sparkle_depth"] = 0.0
    return q


def render_one(image, f, params, color_exclude=True, seed=look.SEED, painted=None, rect=None, diagnostics=True):
    start = time.perf_counter()
    options = clean_options(params)
    scene = scene_for(image, f, color_exclude, seed, painted, options["renderer_version"])
    q = clean_params(params, f["depth"] is not None)
    style = params.get("style", "knit")
    effects = clean_effects(params.get("effects_json", "{}"))
    extended = style in PATTERNS or effects["text"]["enabled"] or effects["damage"]["enabled"]
    sl = (slice(None), slice(None)) if rect is None else (slice(rect[1], rect[3]), slice(rect[0], rect[2]))
    if scene.R.any():
        out_bgr, info = scene.render(q, rect=None if extended else rect)
        # Scene caches geometry metadata; per-frame diagnostics must not mutate it.
        info = dict(info)
        fraction, fade = scene.fade(q)
        if extended:
            out_bgr, effect_info = render_effects(scene, f, out_bgr, style, effects, q)
            out_bgr = out_bgr[sl]
            info.update(effect_info)
    else:
        # Empty/unguided domains need no render, including images too small for np.gradient.
        out_bgr = scene.src[sl].copy()
        info = dict(look.geometry(q["density"], scene.w, scene.h), style=q["style"], sparkles_ready=True)
        fraction, fade = 0.0, np.zeros(f["reg"].shape, np.float32)
    original = image[sl]
    art = data.rgb8(original)
    rendered = out_bgr[..., ::-1].astype(np.float32) / 255
    allowed = (scene.R[sl] > 0) & (f["soft"][sl] > 0)
    changed = allowed & np.any(out_bgr[..., ::-1] != art, axis=-1)
    out = original.copy()
    out[changed] = rendered[changed]
    # This is an exact replacement layer, not a second application of the renderer's feathered alpha.
    layer_alpha = changed.astype(np.float32)
    layer = out.copy()
    if options["layer_mode"] == "soft":
        layer, layer_alpha = soft_layer(original, out, scene.alpha[sl], allowed)
    diag = out.copy()
    if diagnostics:
        faded = (fade[sl] > 0.5) & allowed
        excluded = (scene.REG[sl] > 0) & (scene.R[sl] == 0)
        unguided = f["unguided"][sl]
        for mask, color in [(faded, (1, 0.15, 0.15)), (excluded, (0.1, 0.4, 1)), (unguided, (1, 0.85, 0))]:
            diag[mask] = diag[mask] * 0.5 + np.array(color) * 0.5
    info.update(style=style, **options, faded_fraction=fraction, seed=int(seed), effective_strength=scene.resolve(q)["strength"],
                solve_seconds=f["solve_seconds"], render_seconds=time.perf_counter() - start,
                cache_hits=f["cache_hits"], cache_misses=f["cache_misses"],
                unguided_pixels=int(f["unguided"].sum()), changed_pixels=int(changed.sum()), notes=f["notes"])
    SCENE_CACHE.reweigh()
    return out, layer, layer_alpha, diag, info


def render_batch(images, fields, params, color_exclude=True, seed=look.SEED, painted=None):
    if tuple(images.shape) != fields.get("shape") or len(fields.get("frames", [])) != len(images):
        raise ValueError("求解结果与 IMAGE 尺寸或批次数不一致")
    painted_masks = data.mask_batch(painted, len(images), *images.shape[1:3])
    results = []
    for i, image in enumerate(images):
        interrupt()
        results.append(render_one(image, fields["frames"][i], params, color_exclude, seed, painted_masks[i]))
    return tuple(np.stack([r[j] for r in results]) for j in range(4)) + ([r[4] for r in results],)
