"""Pure frame edits shared by UI operations and headless verification."""
import copy
import uuid
import cv2
import numpy as np
from . import data
from .upstream import split, symmetry


def clip_line(points, mask, single=False):
    p = np.asarray(points, np.float64)
    if len(p) == 1:
        x, y = np.round(p[0]).astype(int)
        return [p.tolist()] if single and 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x] else []
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    if distance[-1] < 1e-6:
        return []
    t = np.linspace(0, distance[-1], min(100000, max(2, int(np.ceil(distance[-1])) + 1)))
    q = np.column_stack([np.interp(t, distance, p[:, i]) for i in (0, 1)])
    xy = np.round(q).astype(int)
    h, w = mask.shape
    inside = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
    valid = np.flatnonzero(inside)
    inside[valid] &= mask[xy[valid, 1], xy[valid, 0]]
    bounds = np.flatnonzero(np.diff(np.r_[False, inside, False]))
    out = []
    for a, b in zip(bounds[::2], bounds[1::2]):
        if b - a >= 2:
            line = cv2.approxPolyDP(q[a:b].astype(np.float32).reshape(-1, 1, 2), .3, False).reshape(-1, 2)
            if len(line) >= 2:
                out.append(line.tolist())
    return out


def assign_paths(region, originals, mask):
    for key in ("strokes", "walls"):
        region[key] = [p for r in originals for line in r.get(key, []) for p in clip_line(line, mask)]
    region["damage_strokes"] = [dict(copy.deepcopy(s), points=p) for r in originals for s in r.get("damage_strokes", [])
                                for p in clip_line(s["points"], mask, single=True)]


def edit_frame(image, frame, external, operation, source, target=None, points=None, snap_radius=0):
    frame = copy.deepcopy(frame)
    h, w = image.shape[:2]
    regions = frame["regions"]
    a = next((i for i, r in enumerate(regions) if r["id"] == source), None)
    if a is None:
        raise ValueError("源部位不存在")
    masks = data.frame_masks(frame, h, w, external)
    # Existing later-region priority is respected when materialising external masks.
    labels = np.zeros((h, w), np.int16)
    for i, m in enumerate(masks):
        labels[m > .5] = i + 1
    selected = labels == a + 1
    src = regions[a]
    info = {}
    if operation == "clear":
        src.update(external=False, mask="", erase="")
    elif operation == "split":
        result = split.cut_mask(selected, points, data.rgb8(image), snap_radius) if points else split.split_mask(selected, data.rgb8(image))
        if result is None:
            raise ValueError("切线没有将部位分成两块，或部位过小")
        left, right, axis = result
        original = copy.deepcopy(src)
        new = copy.deepcopy(src)
        new["id"] = uuid.uuid4().hex
        src["name"] += "-左" if axis == "x" else "-上"
        new["name"] += "-右" if axis == "x" else "-下"
        for r, m in ((src, left), (new, right)):
            r.update(mask=data.encode_mask(m.astype(np.float32)), erase="", external=False)
            assign_paths(r, [original], m)
        regions.insert(a + 1, new)
        info["new_region"] = new["id"]
    elif operation in ("merge", "mirror"):
        b = next((i for i, r in enumerate(regions) if r["id"] == target), None)
        if b is None or a == b:
            raise ValueError("请选择其他目标部位")
        dst = regions[b]
        other = labels == b + 1
        if operation == "merge":
            mask = selected | other
            originals = [copy.deepcopy(src), copy.deepcopy(dst)]
            dst.update(mask=data.encode_mask(mask.astype(np.float32)), erase="", external=False)
            assign_paths(dst, originals, mask)
            regions.pop(a)
        else:
            if not selected.any() or not other.any() or not src.get("strokes"):
                raise ValueError("镜像需要两个非空部位，且源部位已有走向线")
            matrix, error = symmetry.fit_mirror(selected, other)
            strokes = [q for p in src["strokes"] for q in clip_line(np.asarray(p) @ matrix[:2, :2].T + matrix[:2, 2], other)]
            if not strokes:
                raise ValueError("镜像走向线全部落在目标部位外")
            dst["strokes"] = strokes
            info.update(fit_error=error, strokes=len(strokes))
    else:
        raise ValueError("未知部位操作")
    data.parse_guides(data.dump_guides(dict(version=1, width=w, height=h, frames=[frame])), h, w, 1)
    return frame, info
