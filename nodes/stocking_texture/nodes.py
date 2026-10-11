"""The five public ComfyUI nodes. Heavy optional imports happen at execution."""
import json
import uuid
from collections import OrderedDict
import threading

import numpy as np

from . import data
from .cache import SESSION_CACHE
from .models import SAMHandle, sam_choices, depth_choices, resolve_local
from .styles import STYLES
from .render_options import DEFAULTS as RENDER_DEFAULTS
from .config import resolve_material


def render_inputs():
    from .config import SCHEMA
    from .material_nodes import inputs
    return inputs({k: SCHEMA['globals'].get(k) or SCHEMA['appearance'][k]
                   for k in ('renderer_version','layer_mode','moire_on','moire','moire_area','sparkle_link')})


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
                                   "guides": guides, "saved_guides_json": guides_json, "revisions": {}}, document=guides["document"],
                                  batch_mode=batch_mode, sam_available=sam is not None,
                                  sam_device=sam.device if sam is not None else None,
                                  has_mask=mask is not None, node_id=str(unique_id), saved_guides_json=guides_json)
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
        from .material_nodes import inputs
        from .config import APPEARANCE
        specs=inputs(APPEARANCE)
        required={"images":("IMAGE",),"fields":("NF_STOCKING_FIELDS",)}
        for key in ("style","density","tilt","strength","strength_auto","color_exclude","sparkle_depth","sparkle_bright","sparkle_painted","sparkle_even"):
            required[key]=specs[key]
        required["style"]=(list(STYLES),{"default":"knit"})
        required["seed"]=("INT",{"default":20261005,"min":0,"max":0xffffffffffffffff})
        return {"required":required,"optional":{"sparkle_mask":("MASK",),"effects_json":("STRING",{"default":"{}","multiline":True}),**render_inputs(),"material":("NF_STOCKING_MATERIAL",)},"hidden":{"unique_id":"UNIQUE_ID"}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("image", "stocking_layer", "layer_alpha", "diagnostics", "report")
    FUNCTION = "render"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def render(self, images, fields, style="knit", density=100, tilt=32, strength=100, strength_auto=True,
               color_exclude=True, sparkle_depth=100, sparkle_bright=100, sparkle_painted=0, sparkle_even=0,
               seed=20261005, sparkle_mask=None, unique_id="", effects_json="{}", material=None, **options):
        from .engine import render_batch, tensor
        if not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("seed 必须为非负 64 位整数")
        arr = data.image_batch(images)
        params = dict(style=style, density=density, tilt=tilt, strength=strength, strength_auto=strength_auto,
                      sparkle_depth=sparkle_depth, sparkle_bright=sparkle_bright, sparkle_painted=sparkle_painted, sparkle_even=sparkle_even,
                      effects_json=effects_json, **options)
        params=resolve_material(params,material)
        color_exclude=params.get("color_exclude",color_exclude)
        out, layer, alpha, diag, report = render_batch(arr, fields, params, color_exclude, seed, sparkle_mask)
        painted = data.mask_batch(sparkle_mask, len(arr), *arr.shape[1:3])
        payload = session_payload({"kind": "renderer", "images": arr, "fields": fields, "material": material,
                                   "painted": painted, "params": params, "color_exclude": color_exclude,
                                   "seed": seed, "revisions": {}}, params=dict(params, seed=seed, color_exclude=color_exclude), seed=seed, node_id=str(unique_id),
                                   document=fields["guides"]["document"], batch_mode=fields["guides"]["mode"],
                                   identities=[data.digest(im) for im in arr], material_connected=material is not None)
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


def prepare_session(images, settings, guides_json="{}", mask=None, sam=None, sam3_model=None, depth=None, sparkle_mask=None, unique_id="", material=None):
    from .unified import read_records, manual_frame, empty_frame
    settings=resolve_material(settings,material)
    from .engine import depth_batch
    arr = data.image_batch(images)
    external = data.mask_batch(mask, len(arr), *arr.shape[1:3])
    records = read_records(guides_json)
    frames = [manual_frame(records, image, external[i]) or empty_frame(external[i] is not None and (settings.get("source_mode") != "semantic" or sam3_model is None))
              for i, image in enumerate(arr)]
    document = {"version": 1, "height": arr.shape[1], "width": arr.shape[2], "frames": frames}
    session = {"kind": "unified", "images": arr, "material": material, "external": external, "sam": sam, "sam3_model": sam3_model,
               "depths": depth_batch(depth, arr, settings.get("depth_direction", "white_near")),
               "depth_direction": settings.get("depth_direction", "white_near"),
               "painted": data.mask_batch(sparkle_mask, len(arr), *arr.shape[1:3]), "settings": settings, "saved_guides_json": guides_json,
               "revisions": {}}
    return session_payload(session, document=document, batch_mode="per_image", identities=[data.digest(im) for im in arr],
                           sam_available=sam is not None, sam_device=sam.device if sam else None,
                           sam3_available=sam3_model is not None, has_mask=mask is not None, params=settings,
                           legacy=records.get("legacy"), node_id=str(unique_id), saved_guides_json=guides_json, material_connected=material is not None)


class NFStockingTexture:
    """Unified manual/semantic workflow. No unprocessed failures in image outputs."""
    @classmethod
    def INPUT_TYPES(cls):
        render = NFStockingRender.INPUT_TYPES()
        required = dict(render["required"])
        required.pop("fields")
        required.update(guides_json=("STRING", {"default": "{}", "multiline": True}),
                        source_mode=(["semantic", "manual", "mask"], {"default": "semantic"}),
                        prompt=("STRING", {"default": "stockings"}),
                        threshold=("FLOAT", {"default": 0.4, "min": 0, "max": 1, "step": 0.01}),
                        auto_direction=("BOOLEAN", {"default": True}),
                        depth_direction=(["white_near", "black_near"],), auto_walls=("BOOLEAN", {"default": True}),
                        failure_mode=(["skip", "error"], {"default": "skip"}))
        return {"required": required, "optional": {"mask": ("MASK",), "depth": ("IMAGE",),
                "sparkle_mask": ("MASK",), "sam": ("NF_STOCKING_SAM",), "sam3_model": ("EASY_SAM3_MODEL",),
                "effects_json": ("STRING", {"default": "{}", "multiline": True}), **render_inputs(), "material": ("NF_STOCKING_MATERIAL",)},
                "hidden": {"unique_id": "UNIQUE_ID"}}

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "MASK", "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES = ("image", "stocking_layer", "layer_alpha", "regions_mask", "diagnostics", "source_images", "report")
    FUNCTION = "execute"
    CATEGORY = CATEGORY
    DESCRIPTION = "在一个窗口编辑部位、走向及纹理。SAM3 逐图语义识别；可选 ViT-B 点选修边。只输出成功图像；source_images 与成功输出一一对应。"

    def execute(self, images, guides_json="{}", source_mode="semantic", prompt="stockings", threshold=0.4,
                auto_direction=True, depth_direction="white_near", auto_walls=True, failure_mode="skip",
                mask=None, sam=None, sam3_model=None, depth=None, sparkle_mask=None, unique_id="", material=None, **params):
        from .unified import process_batch
        from .engine import tensor
        params=resolve_material(params,material)
        settings = dict(params, source_mode=source_mode, prompt=prompt, threshold=threshold,
                        auto_direction=auto_direction, depth_direction=depth_direction, auto_walls=auto_walls,
                        failure_mode=failure_mode)
        color = params.pop("color_exclude", True)
        seed = params.pop("seed", 20261005)
        arr = data.image_batch(images)
        result = process_batch(arr, guides_json, source_mode, params, mask, depth, sparkle_mask, sam3_model,
                               prompt, threshold, failure_mode, auto_direction, depth_direction, auto_walls, color, seed)
        # Output port order deliberately differs from process_batch's internal tuple.
        out, layer, alpha, diag, regions, sources, report = result
        payload = prepare_session(images, settings, guides_json, mask, sam, sam3_model, depth, sparkle_mask, unique_id, material)
        payload["report"] = report
        return {"ui": {"nf_stocking": [payload]}, "result": (tensor(out), tensor(layer), tensor(alpha), tensor(regions),
                tensor(diag), tensor(sources), json.dumps(report, ensure_ascii=False, allow_nan=False))}


# V3's dev-only schema hides the capture sink from ordinary node menus. It is used
# solely as the target of a partial execution that acquires upstream tensors/models.
try:
    from comfy_api.latest import io

    class NFStockingPrepare(io.ComfyNode):
        @classmethod
        def define_schema(cls):
            inputs = [io.Image.Input("images"), io.String.Input("settings_json", default="{}"),
                      io.String.Input("guides_json", default="{}"), io.Mask.Input("mask", optional=True),
                      io.Image.Input("depth", optional=True), io.Mask.Input("sparkle_mask", optional=True),
                      io.Custom("NF_STOCKING_SAM").Input("sam", optional=True),
                      io.Custom("EASY_SAM3_MODEL").Input("sam3_model", optional=True),
                      io.String.Input("effects_json", default="{}", optional=True),
                      io.Custom("NF_STOCKING_MATERIAL").Input("material", optional=True)]
            specs = dict(NFStockingTexture.INPUT_TYPES()["required"], **render_inputs())
            for name, spec in specs.items():
                if name in ("images", "guides_json"):
                    continue
                typ, options = spec[0], spec[1] if len(spec) > 1 else {}
                if isinstance(typ, list):
                    inputs.append(io.Combo.Input(name, options=typ, default=options.get("default", typ[0]), optional=True))
                else:
                    cls_type = {"STRING": io.String, "FLOAT": io.Float, "INT": io.Int, "BOOLEAN": io.Boolean}[typ]
                    inputs.append(cls_type.Input(name, default=options.get("default"), optional=True))
            return io.Schema(node_id="NFStockingPrepare", display_name="Stocking preview capture (internal)",
                category="_ToolBox/internal", is_dev_only=True, is_output_node=True,
                inputs=inputs, outputs=[])

        @classmethod
        def execute(cls, images, settings_json="{}", guides_json="{}", **kwargs):
            settings = json.loads(settings_json)
            if "effects_json" in kwargs:
                settings["effects_json"] = kwargs.pop("effects_json")
            for name in [*NFStockingTexture.INPUT_TYPES()["required"], *render_inputs()]:
                if name in kwargs:
                    settings[name] = kwargs.pop(name)
            payload = prepare_session(images, settings, guides_json, **kwargs)
            return io.NodeOutput(ui={"nf_stocking": [payload]})
except ImportError:
    class NFStockingPrepare:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"images": ("IMAGE",), "settings_json": ("STRING", {"default": "{}"}),
                    "guides_json": ("STRING", {"default": "{}"})}, "optional": NFStockingTexture.INPUT_TYPES()["optional"]}
        RETURN_TYPES = ()
        FUNCTION = "execute"
        CATEGORY = "_ToolBox/internal"
        OUTPUT_NODE = True
        def execute(self, images, settings_json="{}", guides_json="{}", **kwargs):
            settings = json.loads(settings_json)
            if "effects_json" in kwargs:
                settings["effects_json"] = kwargs.pop("effects_json")
            for name in render_inputs():
                if name in kwargs:
                    settings[name] = kwargs.pop(name)
            return {"ui": {"nf_stocking": [prepare_session(images, settings, guides_json, **kwargs)]}, "result": ()}

NODE_CLASS_MAPPINGS.update(NFStockingTexture=NFStockingTexture, NFStockingPrepare=NFStockingPrepare)
NODE_DISPLAY_NAME_MAPPINGS["NFStockingTexture"] = "tb-丝袜纹理 · 一体化编辑与批处理"

from .psd import NFStockingPSDLoad, NFStockingPSDSave
NODE_CLASS_MAPPINGS.update(NFStockingPSDLoad=NFStockingPSDLoad, NFStockingPSDSave=NFStockingPSDSave)
NODE_DISPLAY_NAME_MAPPINGS.update(NFStockingPSDLoad="tb-丝袜 PSD/PSB 导入", NFStockingPSDSave="tb-丝袜引导 PSD 导出")

from .material_nodes import NODE_CLASS_MAPPINGS as material_nodes, NODE_DISPLAY_NAME_MAPPINGS as material_names
NODE_CLASS_MAPPINGS.update(material_nodes)
NODE_DISPLAY_NAME_MAPPINGS.update(material_names)
