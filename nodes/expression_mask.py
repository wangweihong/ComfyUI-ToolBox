"""ToolBox expression mask node.

Builds a face-region edit mask from MediaPipe landmarks and the expression card
region. All geometry is expressed as ratios of the interocular distance, so the
mask follows image scale, face size and head roll instead of relying on a
per-image hand-drawn mask.
"""
import json

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFilter


def _first_face(payload):
    frames = payload.get("frames") or [[]]
    faces = frames[0]
    if len(faces) != 1:
        raise ValueError(f"Expected one face, found {len(faces)}")
    return faces[0]


def _capsule(draw, cx, cy, width, height):
    radius = min(width, height) * 0.35
    draw.rounded_rectangle(
        (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2),
        radius=radius,
        fill=255,
    )


class ExpressionMask1024:
    """Brows/eyes + mouth mask in the card's crop frame.

    The nose, cheeks and jaw sides stay untouched by default so identity lives in
    the original pixels. The jaw is extended only for expressions that open the
    mouth (SU/HA/AF), and the nose wings only for disgust (DI).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_landmarks": ("FACE_LANDMARKS",),
                "region": ("EXPRESSION_REGION",),
                "label": ("STRING", {"forceInput": True}),
                "feather": ("INT", {"default": 16, "min": 0, "max": 64}),
                "jaw_from_label": ("BOOLEAN", {"default": True}),
                "include_nose": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("MASK", "STRING")
    RETURN_NAMES = ("mask", "diagnostics")
    FUNCTION = "build"
    CATEGORY = "eazy-toolbox/expression"

    def build(self, target_landmarks, region, label, feather, jaw_from_label, include_nose):
        face = _first_face(target_landmarks)
        points = np.asarray(face["landmarks_xy"], dtype=float)
        x, y, w, h = region["box"]
        size = int(region["size"])
        q = (points - [x, y]) * (size / float(w))

        eye = (q[33] + q[263]) / 2
        iod = float(np.linalg.norm(q[263] - q[33]))
        if iod < 1e-3:
            raise ValueError("Degenerate eye landmarks: cannot scale expression mask.")
        mouth = q[[61, 291, 13, 14]].mean(axis=0)

        code = label.split(" / ")[1] if " / " in label else ""
        jaw = bool(jaw_from_label and code in {"SU", "HA", "AF"})
        nose = bool(include_nose or code == "DI")

        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        # Brows + eyelids, shifted slightly up to keep the brow band inside.
        _capsule(draw, eye[0], eye[1] - 0.07 * iod, 1.28 * iod, 0.62 * iod)
        # Lips + chin for closed and moderately open mouths.
        _capsule(draw, mouth[0], mouth[1] + 0.02 * iod, 1.00 * iod, 0.58 * iod)
        if jaw:
            _capsule(draw, mouth[0], mouth[1] + 0.32 * iod, 0.86 * iod, 0.60 * iod)
        if nose:
            tip = q[1]
            _capsule(draw, tip[0], tip[1] + 0.02 * iod, 0.58 * iod, 0.42 * iod)

        if feather:
            mask = mask.filter(ImageFilter.GaussianBlur(feather))

        array = np.asarray(mask, dtype=np.float32) / 255.0
        diagnostics = {
            "schema": 1,
            "code": code,
            "iod_px": round(iod, 1),
            "feather": feather,
            "jaw": jaw,
            "nose": nose,
            "coverage": round(float(array.mean()), 4),
            "region": [int(x), int(y), int(w), int(h)],
            "size": size,
            "note": "Ratios of interocular distance; nose and cheeks excluded by default.",
        }
        return torch.from_numpy(array).unsqueeze(0), json.dumps(diagnostics, ensure_ascii=False)


NODE_CLASS_MAPPINGS = {"ExpressionMask1024": ExpressionMask1024}
NODE_DISPLAY_NAME_MAPPINGS = {"ExpressionMask1024": "tb-expression-mask-1024"}
