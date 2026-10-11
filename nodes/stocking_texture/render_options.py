"""Explicit opt-in for the newer renderer; omitted settings retain old pixels."""
import numpy as np

from .config import SCHEMA

DEFAULTS = {k: (SCHEMA['globals'].get(k) or SCHEMA['appearance'][k])['default']
            for k in ('renderer_version','layer_mode','moire_on','moire','moire_area','sparkle_link')}


def clean_options(params):
    q = {k: params.get(k, v) for k, v in DEFAULTS.items()}
    if q["renderer_version"] not in ("legacy", "upstream_f74c8ac"):
        raise ValueError("未知渲染版本")
    if q["layer_mode"] not in ("replacement", "soft"):
        raise ValueError("未知透明图层模式")
    for k in ("moire_on", "sparkle_link"):
        if not isinstance(q[k], bool):
            raise ValueError(f"{k} 必须为布尔值")
    for k in ("moire", "moire_area"):
        v = q[k]
        if isinstance(v, bool) or not isinstance(v, (float, int)) or not np.isfinite(v) or not 0 <= v <= 100:
            raise ValueError(f"{k} 必须在 [0,100]")
    if q["renderer_version"] == "legacy" and (params.get("style") == "coil" or q["moire_on"]):
        raise ValueError("Coil / 摩尔纹需要切换到 upstream_f74c8ac 新版渲染")
    return q


def soft_layer(source, result, coverage, allowed):
    """Represent the final float image, increasing alpha only to keep RGB in gamut."""
    delta = result.astype(np.float64) - source.astype(np.float64)
    src = source.astype(np.float64)
    need = np.where(delta >= 0, delta / np.maximum(1 - src, 1e-12),
                    -delta / np.maximum(src, 1e-12)).max(axis=-1)
    alpha = np.where(allowed, np.maximum(coverage, need), 0)
    # Round opacity upwards, so 8-bit PNG export never clips an otherwise valid colour.
    alpha = (np.ceil(np.clip(alpha, 0, 1) * 255) / 255).astype(np.float32)
    rgb = np.zeros_like(result)
    on = alpha > 0
    rgb[on] = np.clip(src[on] + delta[on] / alpha[on, None], 0, 1)
    return rgb, alpha
