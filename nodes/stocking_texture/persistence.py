"""User-scoped presets and recoverable drafts, independent of node serialization."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
from . import data
from .render_options import DEFAULTS, clean_options

LOCK = threading.RLock()
MAX_DRAFTS = 8
MAX_DRAFT_BYTES = 512 * 1024**2
MATERIAL_KEYS = ("style", "density", "tilt", "strength", "strength_auto", "color_exclude",
                 "sparkle_depth", "sparkle_bright", "sparkle_painted", "sparkle_even", "seed", "effects_json", *DEFAULTS)


def material(params):
    from .engine import clean_params
    from .effects import clean_effects
    q = {k: v for k, v in params.items() if k in MATERIAL_KEYS}
    q.update(clean_options(q))
    clean_params(q)
    from .config import normalize_effects
    base,cfg=normalize_effects(q.get("style","knit"),q.get("effects_json","{}"))
    q.update(style=base,effects_json=json.dumps(cfg,ensure_ascii=False))
    seed = q.get("seed", 20261005)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xffffffffffffffff:
        raise ValueError("seed 必须为非负 64 位整数")
    if q.get("strength_auto", True):
        q["strength"] = 100
    return q


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf8") as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def presets(root, action="list", name=None, params=None):
    path = Path(root) / "presets.json"
    with LOCK:
        raw = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(raw, dict):
            raise ValueError("预设文件格式无效")
        if action in ("save", "delete"):
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40 or not name.isprintable():
                raise ValueError("预设名称需为 1–40 个可打印字符")
            name = name.strip()
            if action == "save":
                raw[name] = material(params)
            elif name in raw:
                del raw[name]
            else:
                raise ValueError("预设不存在")
            atomic_json(path, raw)
        elif action != "list":
            raise ValueError("未知预设操作")
        result = []
        for name, p in raw.items():
            try:
                # Future keys make this unreadable, rather than silently losing them.
                if not isinstance(p, dict) or set(p) - set(MATERIAL_KEYS):
                    raise ValueError("未知预设参数")
                q = material(p)
            except (ValueError, TypeError, KeyError):
                q = None
            result.append(dict(name=name, params=q))
        return result


def draft_path(root, editor_id, identity):
    if not isinstance(editor_id, str) or not 1 <= len(editor_id) <= 128 or not isinstance(identity, str) or len(identity) != 32:
        raise ValueError("草稿身份无效")
    key = hashlib.sha256((editor_id + ":" + identity).encode()).hexdigest()
    return Path(root) / "drafts" / (key + ".npz")


def _pack(value, arrays):
    if isinstance(value, np.ndarray):
        key = f"a{len(arrays)}"; arrays[key] = value
        return ["array", key]
    if isinstance(value, dict):
        return ["dict", [[k, _pack(v, arrays)] for k, v in value.items()]]
    if isinstance(value, (list, tuple)):
        return ["list", [_pack(v, arrays) for v in value]]
    if isinstance(value, np.generic):
        value = value.item()
    return ["value", value]


def _unpack(value, arrays):
    kind, v = value
    if kind == "array":
        return arrays[v].copy()
    if kind == "dict":
        return {k: _unpack(x, arrays) for k, x in v}
    if kind == "list":
        return [_unpack(x, arrays) for x in v]
    if kind != "value":
        raise ValueError("草稿数据格式无效")
    return v


def save_draft(root, editor_id, identity, session, state):
    path = draft_path(root, editor_id, identity)
    if data.digest(session["images"]) != identity:
        raise ValueError("草稿图片身份不一致")
    if len(json.dumps(state, ensure_ascii=False).encode()) > data.MAX_JSON_BYTES:
        raise ValueError("草稿编辑数据超过 32 MiB")
    safe = {k: v for k, v in session.items() if k not in ("sam", "sam3_model", "revisions", "owner")}
    arrays = {}
    meta = dict(version=1, identity=identity, editor_id=editor_id, saved=time.time(),
                session=_pack(safe, arrays), state=state)
    if sum(a.nbytes for a in arrays.values()) > MAX_DRAFT_BYTES:
        raise ValueError("此草稿超过 512 MiB，仍可正常保存节点")
    arrays["meta"] = np.array(json.dumps(meta, ensure_ascii=False, allow_nan=False))
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as f:
                np.savez_compressed(f, **arrays)
            if os.path.getsize(tmp) > MAX_DRAFT_BYTES:
                raise ValueError("此草稿超过 512 MiB")
            os.replace(tmp, path)
            files = sorted(path.parent.glob("*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
            size = 0
            for i, p in enumerate(files):
                size += p.stat().st_size
                if i >= MAX_DRAFTS or size > MAX_DRAFT_BYTES:
                    p.unlink()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return meta["saved"]


def load_draft(root, editor_id, identity):
    path = draft_path(root, editor_id, identity)
    with LOCK:
        if not path.exists():
            return None
        with np.load(path, allow_pickle=False) as arrays:
            meta = json.loads(str(arrays["meta"]))
            if meta.get("version") != 1 or meta.get("identity") != identity or meta.get("editor_id") != editor_id:
                raise ValueError("草稿版本或身份不一致")
            meta["session"] = _unpack(meta["session"], arrays)
        os.utime(path, None)
        return meta


def delete_draft(root, editor_id, identity):
    with LOCK:
        draft_path(root, editor_id, identity).unlink(missing_ok=True)
