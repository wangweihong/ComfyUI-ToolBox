"""The five public ComfyUI nodes. Heavy optional imports happen at execution."""
import json
import uuid
from collections import OrderedDict
import threading

import numpy as np

from . import data
from .cache import SESSION_CACHE
from .models import SAMHandle, sam_choices, depth_choices, resolve_local

CATEGORY = "南风节点/丝袜纹理"
_node_sessions = OrderedDict()
_session_lock = threading.RLock()


def session_epoch(node_id):
    """Invalidate ComfyUI's cached UI tokens after LRU eviction, without disabling queue caching."""
    with _session_lock:
        record = _node_sessions.setdefault(str(node_id), {"epoch": 0, "tokens": []})
        live = [token for token in record["tokens"] if SESSION_CACHE.contains(token)]
        if len(live) != len(record["tokens"]):
            record["epoch"] += 1
            record["tokens"] = live
        _node_sessions.move_to_end(str(node_id))
        while len(_node_sessions) > 128:
            _node_sessions.popitem(last=False)
        return record["epoch"]


def session_payload(session, **metadata):
    key = uuid.uuid4().hex
    SESSION_CACHE.put(key, session)
    node_id = str(metadata.get("node_id", ""))
    with _session_lock:
        session_epoch(node_id)
        _node_sessions[node_id]["tokens"].append(key)
    return {"session": key, "preview_available": SESSION_CACHE.contains(key),
            "width": session["images"].shape[2], "height": session["images"].shape[1],
            "batch": len(session["images"]), "identity": data.digest(session["images"]), **metadata}


class NFStockingEditor:
    @classmethod
    def IS_CHANGED(cls, unique_id="", **kwargs):
        return session_epoch(unique_id)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",),
                             "guides_json": ("STRING", {"default": "{}", "multiline": True}),
                             "batch_mode": (["shared", "per_image"], {"default": "shared"})},
                "optional": {"mask": ("MASK",), "sam": ("NF_STOCKING_SAM",)},
                "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("NF_STOCKING_GUIDES", "MASK", "IMAGE")
    RETURN_NAMES = ("guides", "regions_mask", "guides_preview")
    FUNCTION = "edit"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True  # An empty editor must execute to acquire its upstream image.

    def edit(self, images, guides_json="{}", batch_mode="shared", mask=None, sam=None, unique_id=""):
        from .engine import build_guides, label_masks, raster, tensor
        arr = data.image_batch(images)
        guides, external = build_guides(arr, guides_json, mask, batch_mode)
        masks, previews = [], []
        for i, image in enumerate(arr):
            frame = guides["document"]["frames"][0 if batch_mode == "shared" else i]
            reg, soft = label_masks(guides["masks"][i], image.shape[:2])
            preview = data.rgb8(image)
            inside = reg > 0
            preview[inside] = np.round(preview[inside] * 0.6 + np.array([70, 230, 180]) * 0.4).astype(np.uint8)
            for r in frame["regions"]:
                preview[raster(r.get("strokes", []), reg.shape) > 0] = (255, 230, 70)
                preview[raster(r.get("walls", []), reg.shape, width=3) > 0] = (255, 100, 80)
            masks.append(soft)
            previews.append(preview / 255)
        payload = session_payload({"kind": "editor", "images": arr, "external": external, "sam": sam,
                                   "guides": guides, "revisions": {}}, document=guides["document"],
                                  batch_mode=batch_mode, sam_available=sam is not None, has_mask=mask is not None, node_id=str(unique_id))
        return {"ui": {"nf_stocking": [payload]}, "result": (guides, tensor(np.stack(masks)), tensor(np.stack(previews)))}


class NFStockingSolve:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "guides": ("NF_STOCKING_GUIDES",),
                             "depth_direction": (["white_near", "black_near"], {"default": "white_near"}),
                             "auto_walls": ("BOOLEAN", {"default": True})}, "optional": {"depth": ("IMAGE",)}}

    RETURN_TYPES = ("NF_STOCKING_FIELDS", "IMAGE")
    RETURN_NAMES = ("fields", "isolines_preview")
    FUNCTION = "solve"
    CATEGORY = CATEGORY

    def solve(self, images, guides, depth_direction="white_near", auto_walls=True, depth=None):
        from .engine import solve_batch, isolines, tensor
        arr = data.image_batch(images)
        fields = solve_batch(arr, guides, depth, depth_direction, auto_walls)
        # Retain just serializable guides/masks for editing previews, not a mutable desktop Document.
        fields["guides"] = guides
        fields["depth_direction"] = depth_direction
        fields["auto_walls"] = auto_walls
        return fields, tensor(np.stack([isolines(im, f) / 255 for im, f in zip(arr, fields["frames"])]))


class NFStockingRender:
    @classmethod
    def IS_CHANGED(cls, unique_id="", **kwargs):
        return session_epoch(unique_id)

    @classmethod
    def INPUT_TYPES(cls):
        amount = lambda default: ("FLOAT", {"default": default, "min": 0, "max": 300, "step": 1})
        return {"required": {"images": ("IMAGE",), "fields": ("NF_STOCKING_FIELDS",),
                             "style": (["knit", "loops", "lines", "grain", "oily"], {"default": "knit"}),
                             "density": ("FLOAT", {"default": 100, "min": 40, "max": 200, "step": 1}),
                             "tilt": ("FLOAT", {"default": 32, "min": 0, "max": 75, "step": 1}),
                             "strength": ("FLOAT", {"default": 100, "min": 0, "max": 250, "step": 1}),
                             "strength_auto": ("BOOLEAN", {"default": True}),
                             "color_exclude": ("BOOLEAN", {"default": True}),
                             "sparkle_depth": amount(100), "sparkle_bright": amount(100),
                             "sparkle_painted": amount(0), "sparkle_even": amount(0),
                             "seed": ("INT", {"default": 20261005, "min": 0, "max": 0xFFFFFFFFFFFFFFFF})},
                "optional": {"sparkle_mask": ("MASK",)}, "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("image", "stocking_layer", "layer_alpha", "diagnostics", "report")
    FUNCTION = "render"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def render(self, images, fields, style="knit", density=100, tilt=32, strength=100, strength_auto=True,
               color_exclude=True, sparkle_depth=100, sparkle_bright=100, sparkle_painted=0, sparkle_even=0,
               seed=20261005, sparkle_mask=None, unique_id=""):
        from .engine import render_batch, tensor
        if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("seed 必须为非负 64 位整数")
        arr = data.image_batch(images)
        params = dict(style=style, density=density, tilt=tilt, strength=strength, strength_auto=strength_auto,
                      sparkle_depth=sparkle_depth, sparkle_bright=sparkle_bright, sparkle_painted=sparkle_painted, sparkle_even=sparkle_even)
        out, layer, alpha, diag, report = render_batch(arr, fields, params, color_exclude, seed, sparkle_mask)
        painted = data.mask_batch(sparkle_mask, len(arr), *arr.shape[1:3])
        payload = session_payload({"kind": "renderer", "images": arr, "fields": fields,
                                   "painted": painted, "params": params, "color_exclude": color_exclude,
                                   "seed": seed, "revisions": {}}, params=params, seed=seed, node_id=str(unique_id))
        return {"ui": {"nf_stocking": [payload]}, "result": (tensor(out), tensor(layer), tensor(alpha), tensor(diag),
                                                                 json.dumps(report, ensure_ascii=False, allow_nan=False))}


class NFStockingSAMLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"checkpoint": (sam_choices(),), "device": (["auto", "cpu", "cuda"],)}}

    RETURN_TYPES = ("NF_STOCKING_SAM",)
    FUNCTION = "load"
    CATEGORY = CATEGORY

    def load(self, checkpoint, device="auto"):
        resolve_local(checkpoint)
        return (SAMHandle(checkpoint, device),)


class NFStockingDepth:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "model": (depth_choices(),), "device": (["auto", "cpu", "cuda"],)}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("depth_white_near",)
    FUNCTION = "estimate"
    CATEGORY = CATEGORY

    def estimate(self, images, model, device="auto"):
        from .engine import tensor
        from .models import estimate_depth
        return (tensor(estimate_depth(data.image_batch(images), model, device)),)


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (NFStockingEditor, NFStockingSolve, NFStockingRender, NFStockingSAMLoader, NFStockingDepth)}
NODE_DISPLAY_NAME_MAPPINGS = {"NFStockingEditor": "tb-丝袜引导编辑器", "NFStockingSolve": "tb-丝袜走向求解",
                              "NFStockingRender": "tb-丝袜纹理（油光为试验）", "NFStockingSAMLoader": "tb-丝袜 SAM 点选模型",
                              "NFStockingDepth": "tb-丝袜深度辅助 Small"}
