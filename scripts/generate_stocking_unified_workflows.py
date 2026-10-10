"""Five recommended unified workflows. Existing split-node recipes stay available."""
import argparse
import json
from pathlib import Path
import urllib.request

from generate_stocking_function_workflows import workflow, STYLES


def graphs(image_name, records="{}", density=100):
    load = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    sam = {"class_type": "NFStockingSAMLoader", "inputs": {"checkpoint": "sams/sam_vit_b_01ec64.pth", "device": "cuda"}}
    sam3 = {"class_type": "easy sam3ModelLoader", "inputs": {"model": "sam3.pt", "segmentor": "image", "device": "cuda", "precision": "fp32"}}
    params = {"images": ["1", 0], "guides_json": records, "source_mode": "manual", "prompt": "stockings", "threshold": 0.4,
              "auto_direction": True, "depth_direction": "white_near", "auto_walls": True, "failure_mode": "skip",
              "style": "knit", "density": density, "tilt": 32, "strength": 100, "strength_auto": True,
              "color_exclude": True, "sparkle_depth": 100, "sparkle_bright": 100, "sparkle_painted": 0,
              "sparkle_even": 0, "seed": 20261005, "sam": ["3", 0]}
    def preview(link):
        return {"class_type": "PreviewImage", "inputs": {"images": link}}
    def base(semantic=False):
        p = {"1": load, "2": {"class_type": "NFStockingTexture", "inputs": dict(params)}, "3": sam}
        if semantic:
            p["4"] = sam3
            p["2"]["inputs"].update(source_mode="semantic", sam3_model=["4", 0])
        return p
    items = []
    p = base(); p["2"]["inputs"].pop("sam")
    p["5"] = preview(["2", 0]); items.append(("01-手工点选与统一编辑", p))
    p = base(True); p["5"] = preview(["2", 0]); items.append(("02-SAM3语义识别与点选修边", p))
    p = base(True)
    p["6"] = {"class_type": "NFStockingDepth", "inputs": {"images": ["1", 0], "model": "stocking_texture/Depth-Anything-V2-Small-hf", "device": "auto"}}
    p["7"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    p["8"] = {"class_type": "ImageBatch", "inputs": {"image1": ["1", 0], "image2": ["7", 0]}}
    p["2"]["inputs"].update(images=["8", 0], depth=["6", 0])
    p["6"]["inputs"]["images"] = ["8", 0]
    p["5"] = preview(["2", 0])
    items.append(("03-深度辅助与逐图批处理", p))
    p = base(True)
    compare = {"image1": ["2", 5], "name1": "Original"}
    for index, (style, label) in enumerate(STYLES):
        nid = "2" if index == 0 else str(index + 6)
        p[nid] = {"class_type": "NFStockingTexture", "inputs": dict(p["2"]["inputs"], style=style)}
        compare[f"image{index + 2}"] = [nid, 0]
        compare[f"name{index + 2}"] = dict(knit="Fine", loops="Loops", lines="Slant", grain="Grain", oily="Oily")[style]
    p["11"] = {"class_type": "ParallelVideoComparison", "inputs": compare}
    p["5"] = preview(["11", 0]); items.append(("04-五种纹理并排对比", p))
    p = base(True)
    p["6"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": ["2", 5], "source": ["2", 1], "mask": ["2", 2], "x": 0, "y": 0, "resize_source": False}}
    p["5"] = preview(["6", 0]); p["7"] = preview(["2", 4])
    p["8"] = {"class_type": "InvertMask", "inputs": {"mask": ["2", 2]}}
    p["9"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["2", 1], "alpha": ["8", 0]}}
    p["10"] = preview(["9", 0]); items.append(("05-图层合成与效果诊断", p))
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-name", default="tb_stocking_demo.png")
    parser.add_argument("--records", type=Path)
    parser.add_argument("--output", type=Path, default=Path("examples/stocking_texture/unified"))
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    args = parser.parse_args()
    items = graphs(args.image_name, args.records.read_text() if args.records else "{}")
    schemas = {}
    for name in {n["class_type"] for _, p in items for n in p.values()}:
        schemas.update(json.load(urllib.request.urlopen(args.url + "/object_info/" + name.replace(" ", "%20"))))
    args.output.mkdir(parents=True, exist_ok=True)
    for index, (title, prompt) in enumerate(items, 1):
        # Reuse the project's Comfy schema serializer; lay out the new simpler graphs.
        ui = workflow(prompt, schemas, 4, title)
        for i, n in enumerate(ui["nodes"]):
            n["pos"] = [(i % 4) * 420, (i // 4) * 350 + 160]
            n["size"] = [360, 280]
            if n["type"].startswith("NFStocking"): n.pop("title", None)
            if n["type"] == "LoadImage": n["title"] = "图片 · 替换后直接打开编辑器"
        ui["groups"] = []
        (args.output / (title + ".json")).write_text(json.dumps(ui, ensure_ascii=False, indent=2))
        (args.output / (title + ".api.json")).write_text(json.dumps(prompt, ensure_ascii=False, indent=2))
        print(title)

if __name__ == "__main__":
    main()
