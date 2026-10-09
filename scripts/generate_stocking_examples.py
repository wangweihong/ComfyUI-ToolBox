"""Generate redistributable synthetic artwork and ComfyUI UI/API example workflows."""
from pathlib import Path
import base64
import io
import json

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def encoded(mask):
    stream = io.BytesIO(); Image.fromarray((mask * 255).astype(np.uint8)).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode()


def artwork(h=768, w=512):
    y, x = np.mgrid[:h, :w]
    image = np.zeros((h, w, 3), np.float32); image[:] = [0.12, 0.15, 0.20]
    masks, regions = [], []
    depth = np.zeros((h, w), np.float32)
    for idx, (cx, rgb) in enumerate([(w * 0.30, [0.77, 0.73, 0.75]), (w * 0.72, [0.23, 0.22, 0.26])]):
        cy = h * 0.49
        m = ((x - cx) / (w * 0.15)) ** 2 + ((y - cy) / (h * 0.45)) ** 2 < 1
        shade = 0.52 + 0.48 * np.maximum(0, 1 - ((x - cx) / (w * 0.16)) ** 2)
        tint = np.array(rgb)[None, None, :] * shade[..., None]
        light = np.exp(-((x - cx + w * 0.032) / (w * 0.035)) ** 2) * np.exp(-((y - h * 0.45) / (h * 0.4)) ** 2)
        tint = np.minimum(1, tint + light[..., None] * 0.10)
        image[m] = tint[m]
        depth[m] = (0.35 + 0.5 * np.maximum(0, 1 - ((x[m] - cx) / (w * 0.16)) ** 2))
        m[(y > h * 0.30) & (y < h * 0.34) & (x > cx - w * 0.025) & (x < cx + w * 0.11)] = False
        # A foreground strap and warm trim exercise occlusion and colour rejection.
        occluder = (y > h * 0.30) & (y < h * 0.34) & (x > cx - w * 0.025) & (x < cx + w * 0.11)
        image[occluder] = [0.19, 0.25, 0.29]
        trim = m & (y > h * 0.15) & (y < h * 0.16)
        image[trim] = [0.85, 0.61, 0.18]
        masks.append(m)
        strokes = []
        for cyg in (h * 0.24, h * 0.52, h * 0.75):
            xx = np.linspace(cx - w * 0.105, cx + w * 0.105, 35)
            yy = cyg - h * 0.022 * (1 - ((xx - cx) / (w * 0.105)) ** 2)
            strokes.append(np.stack([xx, yy], 1).round(3).tolist())
        regions.append({"id": f"leg-{idx}", "name": "左腿" if idx == 0 else "右腿", "external": False,
                        "mask": encoded(m), "erase": "", "strokes": strokes, "walls": []})
    doc = {"version": 1, "width": w, "height": h, "frames": [{"regions": regions}]}
    return np.round(image * 255).astype(np.uint8), np.logical_or.reduce(masks).astype(np.uint8) * 255, np.round(depth * 255).astype(np.uint8), doc


RENDER = dict(style="knit", density=100, tilt=32, strength=100, strength_auto=True, color_exclude=True,
              sparkle_depth=100, sparkle_bright=100, sparkle_painted=0, sparkle_even=0, seed=20261005)


def prompt(doc, variant):
    p = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "tb_stocking_demo.png"}},
        "2": {"class_type": "NFStockingEditor", "inputs": {"images": ["1", 0], "guides_json": json.dumps(doc, ensure_ascii=False), "batch_mode": "shared"}},
        "3": {"class_type": "NFStockingSolve", "inputs": {"images": ["1", 0], "guides": ["2", 0], "depth_direction": "white_near", "auto_walls": True}},
        "4": {"class_type": "NFStockingRender", "inputs": {"images": ["1", 0], "fields": ["3", 0], **RENDER}},
        "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": f"ToolBoxStocking/{variant}"}},
        "6": {"class_type": "PreviewImage", "inputs": {"images": ["4", 3]}},
        "7": {"class_type": "InvertMask", "inputs": {"mask": ["4", 2]}},
        "8": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["4", 1], "alpha": ["7", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": f"ToolBoxStocking/{variant}-layer"}},
    }
    if variant == "external-depth":
        p["10"] = {"class_type": "LoadImage", "inputs": {"image": "tb_stocking_demo_depth.png"}}
        p["3"]["inputs"]["depth"] = ["10", 0]
    if variant == "sam":
        p["10"] = {"class_type": "NFStockingSAMLoader", "inputs": {"checkpoint": "sams/sam_vit_b_01ec64.pth", "device": "auto"}}
        p["2"]["inputs"]["sam"] = ["10", 0]
    if variant == "batch":
        p["10"] = {"class_type": "RepeatImageBatch", "inputs": {"image": ["1", 0], "amount": 4}}
        for n in ("2", "3", "4"): p[n]["inputs"]["images"] = ["10", 0]
    return p


# UI slot/widget descriptions for standard ComfyUI and our five nodes.
SCHEMAS = {
    "LoadImage": ([], [("IMAGE", "IMAGE"), ("MASK", "MASK")], ["image", "upload"]),
    "NFStockingEditor": ([("images", "IMAGE"), ("mask", "MASK"), ("sam", "NF_STOCKING_SAM")], [("guides", "NF_STOCKING_GUIDES"), ("regions_mask", "MASK"), ("guides_preview", "IMAGE")], ["guides_json", "batch_mode"]),
    "NFStockingSolve": ([("images", "IMAGE"), ("guides", "NF_STOCKING_GUIDES"), ("depth", "IMAGE")], [("fields", "NF_STOCKING_FIELDS"), ("isolines_preview", "IMAGE")], ["depth_direction", "auto_walls"]),
    "NFStockingRender": ([("images", "IMAGE"), ("fields", "NF_STOCKING_FIELDS"), ("sparkle_mask", "MASK")], [("image", "IMAGE"), ("stocking_layer", "IMAGE"), ("layer_alpha", "MASK"), ("diagnostics", "IMAGE"), ("report", "STRING")], [*RENDER.keys(), "control_after_generate"]),
    "SaveImage": ([("images", "IMAGE")], [], ["filename_prefix"]),
    "PreviewImage": ([("images", "IMAGE")], [], []),
    "InvertMask": ([("mask", "MASK")], [("MASK", "MASK")], []),
    "JoinImageWithAlpha": ([("image", "IMAGE"), ("alpha", "MASK")], [("IMAGE", "IMAGE")], []),
    "RepeatImageBatch": ([("image", "IMAGE")], [("IMAGE", "IMAGE")], ["amount"]),
    "NFStockingSAMLoader": ([], [("NF_STOCKING_SAM", "NF_STOCKING_SAM")], ["checkpoint", "device"]),
}


def ui_workflow(p):
    nodes, links = [], []
    positions = {1: (0, 0), 2: (380, 0), 3: (740, 0), 4: (1100, 0), 5: (1480, 0), 6: (1480, 450),
                 7: (1100, 720), 8: (1480, 720), 9: (1850, 720), 10: (0, 520)}
    for key, entry in p.items():
        inputs, outputs, widgets = SCHEMAS[entry["class_type"]]
        n = {"id": int(key), "type": entry["class_type"], "pos": list(positions[int(key)]), "size": [320, 460 if key == "4" else 250],
             "flags": {}, "order": int(key), "mode": 0, "properties": {"Node name for S&R": entry["class_type"]},
             "inputs": [{"name": name, "type": typ, "link": None} for name, typ in inputs],
             "outputs": [{"name": name, "type": typ, "links": []} for name, typ in outputs],
             "widgets_values": [entry["inputs"].get(name, "fixed" if name == "control_after_generate" else "image") for name in widgets]}
        nodes.append(n)
    lookup = {n["id"]: n for n in nodes}
    for key, entry in p.items():
        for name, val in entry["inputs"].items():
            if not isinstance(val, list): continue
            target = lookup[int(key)]; slot = next(i for i, inp in enumerate(target["inputs"]) if inp["name"] == name)
            origin, origin_slot = int(val[0]), val[1]; lid = len(links) + 1
            typ = target["inputs"][slot]["type"]
            links.append([lid, origin, origin_slot, int(key), slot, typ]); target["inputs"][slot]["link"] = lid
            lookup[origin]["outputs"][origin_slot]["links"].append(lid)
    return {"last_node_id": max(lookup), "last_link_id": len(links), "nodes": nodes, "links": links, "groups": [], "config": {},
            "extra": {"ds": {"scale": 0.7, "offset": [80, 100]}}, "version": 0.4}


def main():
    root = ROOT / "examples/stocking_texture"; (root / "assets").mkdir(parents=True, exist_ok=True)
    art, mask, depth, doc = artwork()
    for name, pixels in [("tb_stocking_demo.png", art), ("tb_stocking_demo_mask.png", mask), ("tb_stocking_demo_depth.png", depth)]:
        Image.fromarray(pixels).save(root / "assets" / name)
    (root / "assets/guides.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    for variant in ["manual", "external-depth", "sam", "batch"]:
        p = prompt(doc, variant)
        (root / f"{variant}.api.json").write_text(json.dumps(p, ensure_ascii=False, indent=2))
        (root / f"{variant}.json").write_text(json.dumps(ui_workflow(p), ensure_ascii=False, indent=2))
    print(root)


if __name__ == "__main__":
    main()
