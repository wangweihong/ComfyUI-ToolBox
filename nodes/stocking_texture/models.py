"""Local-only optional models; nothing is loaded or downloaded at node import."""
from pathlib import Path
import threading

import numpy as np

_model_lock = threading.RLock()
_sam_cache = None
_depth_cache = None


def model_root():
    import folder_paths
    return Path(folder_paths.models_dir)


def sam_choices():
    try:
        root = model_root()
        return sorted({str(p.relative_to(root)) for folder in (root / "sams", root / "sam", root / "stocking_texture")
                       if folder.exists() for p in folder.rglob("*vit_b*.pth")}) or ["sams/sam_vit_b_01ec64.pth"]
    except ImportError:
        return ["sams/sam_vit_b_01ec64.pth"]


def depth_choices():
    try:
        root = model_root()
        return sorted(str(p.parent.relative_to(root)) for p in (root / "stocking_texture").rglob("config.json")) or ["stocking_texture/Depth-Anything-V2-Small-hf"]
    except ImportError:
        return ["stocking_texture/Depth-Anything-V2-Small-hf"]


def resolve_local(relative):
    root = model_root().resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("模型必须位于 ComfyUI models 目录")
    if not path.exists():
        raise ValueError(f"缺少本地模型 {path}；请按 README 安装，节点不会自动下载")
    return path


def device_for(requested):
    import torch
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError("未知设备")
    if requested == "cpu" or not torch.cuda.is_available():
        return torch.device("cpu")
    import comfy.model_management as mm
    return mm.get_torch_device()


class SAMHandle:
    def __init__(self, checkpoint, device="auto"):
        self.checkpoint = checkpoint
        self.device = device

    def candidates(self, rgb, identity):
        import torch
        try:
            from segment_anything import SamPredictor, sam_model_registry
        except ImportError as exc:
            raise RuntimeError("SAM 点选缺少 segment-anything，请安装 requirements-stocking-models.txt") from exc
        global _sam_cache
        path = resolve_local(self.checkpoint)
        key = (str(path), path.stat().st_mtime_ns)
        with _model_lock:
            if _sam_cache is None or _sam_cache[0] != key:
                model = sam_model_registry["vit_b"](checkpoint=str(path)).eval()
                _sam_cache = (key, SamPredictor(model), None)
            predictor = _sam_cache[1]
            return predictor, torch, key

    def segment(self, rgb, identity, x, y):
        if not 0 <= x < rgb.shape[1] or not 0 <= y < rgb.shape[0]:
            raise ValueError("SAM 点击坐标超出图像范围")
        global _sam_cache
        with _model_lock:
            predictor, torch, key = self.candidates(rgb, identity)
            dev = device_for(self.device)
            predictor.model.to(dev)
            try:
                with torch.inference_mode():
                    if _sam_cache[2] != identity:
                        predictor.set_image(rgb)
                        _sam_cache = (key, predictor, identity)
                    else:
                        predictor.features = predictor.features.to(dev)
                    masks, scores, _ = predictor.predict(point_coords=np.array([[x, y]], np.float32),
                                                         point_labels=np.array([1]), multimask_output=True)
                order = np.argsort(masks.sum(axis=(1, 2)), kind="stable")
                return masks[order], scores[order]
            finally:
                predictor.model.to("cpu")
                if predictor.features is not None:
                    predictor.features = predictor.features.to("cpu")


def estimate_depth(images, relative, device="auto"):
    import torch
    try:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except ImportError as exc:
        raise RuntimeError("深度估算缺少 transformers，请安装 requirements-stocking-models.txt") from exc
    from .engine import interrupt
    from .data import rgb8
    path = resolve_local(relative)
    if not (path / "config.json").is_file():
        raise ValueError("深度模型需要完整的 Small-hf 本地目录（含 config、processor、weights）")
    import json
    config = json.loads((path / "config.json").read_text())
    backbone = config.get("backbone_config", {})
    if backbone.get("hidden_size") != 384:
        raise ValueError("内置深度节点仅支持 Depth Anything V2 Small-hf；其他模型请使用外部灰度深度输入")
    global _depth_cache
    key = (str(path), (path / "config.json").stat().st_mtime_ns)
    dev = device_for(device)
    with _model_lock:
        if _depth_cache is None or _depth_cache[0] != key:
            processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
            model = AutoModelForDepthEstimation.from_pretrained(str(path), local_files_only=True).eval()
            _depth_cache = (key, processor, model)
        _, processor, model = _depth_cache
        model.to(dev)
        outputs = []
        try:
            with torch.inference_mode():
                for image in images:
                    interrupt()
                    inp = processor(images=rgb8(image), return_tensors="pt", size={"height": 1036, "width": 1036},
                                    keep_aspect_ratio=True, ensure_multiple_of=14)
                    pred = model(**{k: v.to(dev) for k, v in inp.items()}).predicted_depth
                    pred = torch.nn.functional.interpolate(pred[:, None], size=image.shape[:2], mode="bicubic", align_corners=False)[0, 0]
                    lo, hi = pred.min(), pred.max()
                    pred = torch.zeros_like(pred) if (hi - lo).item() < 1e-6 else (pred - lo) / (hi - lo)
                    outputs.append(pred.clamp(0, 1).cpu().float().numpy())
        finally:
            model.to("cpu")
    return np.repeat(np.stack(outputs)[..., None], 3, axis=-1)
