"""ToolBox adapter for ComfyUI-DeGrid; see UPSTREAM.md for provenance."""

import torch

from .degrid_core import NEGLIGIBLE_AMP, degrid


def status_line(mode, stats):
    s = stats[0]
    amp = s["amp_255"]
    if amp < NEGLIGIBLE_AMP * 255:
        state = "passed through untouched" if s["skipped"] else "filtered anyway"
        verdict = f"grid {amp:.2f}/255 — none detected, {state}"
    else:
        parts = (("checker", s["checker_255"]), ("V-stripe", s["vstripe_255"]), ("H-stripe", s["hstripe_255"]))
        kind = max(parts, key=lambda p: p[1])[0]
        verdict = f"grid {amp:.2f}/255 ({kind}) — filtered (limit {s['limit']:.3f} {mode})"
    line = f"{verdict} · edges protected: {s['clipped_pct']:.1f}%"
    if len(stats) > 1:
        line += f" · batch of {len(stats)} (first shown)"
    return line


class ToolBoxVAEDeGrid:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "image": ("IMAGE", {"tooltip": "Connect directly after VAE Decode, before resize, sharpening or upscaling."}),
            "enabled": ("BOOLEAN", {"default": True, "tooltip": "Off passes the original image through untouched for A/B comparison."}),
            "mode": (["auto", "manual"], {"default": "auto", "tooltip": "Auto calibrates each image; manual uses limit."}),
            "limit": ("FLOAT", {"default": 0.02, "min": 0.0, "max": 0.10, "step": 0.001, "tooltip": "Manual only. Maximum per-pixel correction on the 0–1 scale. Too high may soften fine texture."}),
            "skip_when_clean": ("BOOLEAN", {"default": True, "tooltip": "Preserve original pixels when no phase-locked 2px grid is detected. Off forces filtering."}),
            "grid_gain": ("FLOAT", {"default": 10.0, "min": 1.0, "max": 50.0, "step": 1.0, "tooltip": "Amplification of removed_grid only; never changes the cleaned image."}),
            "grid_view": (["full frame", "4x zoom", "8x zoom"], {"default": "4x zoom", "tooltip": "Removed-grid preview framing only. Zoom magnifies a center crop using nearest-neighbor sampling."}),
        }}

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("image", "removed_grid")
    FUNCTION = "process"
    CATEGORY = "eazy-toolbox/image"
    # Schedule the status even when downstream previews are already cached.
    OUTPUT_NODE = True
    DESCRIPTION = "Remove the 2px VAE grid from Qwen Image / Qwen Image 2.1 / Wan 2.1 decodes. Place before resize, sharpening, upscaling or restoration. Auto detects and calibrates each image; clean images pass through unchanged. removed_grid is a diagnostic preview centered on gray."

    def process(self, image, enabled=True, mode="auto", limit=0.02,
                skip_when_clean=True, grid_gain=10.0, grid_view="4x zoom"):
        if image.ndim != 4 or any(size == 0 for size in image.shape) or not image.is_floating_point():
            raise ValueError("DeGrid requires a non-empty floating-point IMAGE batch [B, H, W, C].")
        if not enabled:
            return {"ui": {"degrid": [{"enabled": False, "mode": mode, "stats": [], "text": "bypassed (enabled = off)"}]},
                    "result": (image, torch.full_like(image, 0.5))}

        cleaned, vis, stats = degrid(image, mode=mode, limit=limit,
                                   skip_when_clean=skip_when_clean,
                                   grid_gain=grid_gain, grid_view=grid_view)
        # The core computes in float32. Restore skipped frames from the input,
        # including values whose original precision exceeds float32.
        skipped = [i for i, s in enumerate(stats) if s["skipped"]]
        if len(skipped) == len(stats):
            cleaned = image
        elif skipped:
            cleaned[skipped] = image[skipped]
        return {"ui": {"degrid": [{"enabled": True, "mode": mode, "stats": stats, "text": status_line(mode, stats)}]},
                "result": (cleaned, vis)}


NODE_CLASS_MAPPINGS = {"ToolBoxVAEDeGrid": ToolBoxVAEDeGrid}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxVAEDeGrid": "tb-vae-degrid"}
