"""Build five independent functional workflows for a local image and saved guides.

The image is referenced by filename, never embedded in a workflow. Query only the
ComfyUI node schemas; image upload/deployment and queue execution are explicit steps.
"""
import argparse
import json
from pathlib import Path
import urllib.request

from PIL import Image

SCALARS = {"STRING", "INT", "FLOAT", "BOOLEAN"}
STYLES = [("knit", "细线"), ("loops", "针织"), ("lines", "斜单线"), ("grain", "加濑风"), ("oily", "油光（试验）")]


def graphs(image_name, guides, prefix, density):
    load = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    edit = {"class_type": "NFStockingEditor", "inputs": {"images": ["1", 0], "guides_json": json.dumps(guides, ensure_ascii=False), "batch_mode": "shared"}}
    solve = {"class_type": "NFStockingSolve", "inputs": {"images": ["1", 0], "guides": ["2", 0], "depth_direction": "white_near", "auto_walls": True}}
    params = {"images": ["1", 0], "fields": ["3", 0], "style": "knit", "density": density, "tilt": 32,
              "strength": 100, "strength_auto": True, "color_exclude": True,
              "sparkle_depth": 0, "sparkle_bright": 0, "sparkle_painted": 0, "sparkle_even": 0, "seed": 20261005}
    def save(images, suffix):
        return {"class_type": "SaveImage", "inputs": {"images": images, "filename_prefix": prefix + "/" + suffix}}
    def preview(images):
        return {"class_type": "PreviewImage", "inputs": {"images": images}}
    def base():
        return json.loads(json.dumps({"1": load, "2": edit, "3": solve}))
    result = []
    p = base()
    p["4"] = save(["3", 1], "01-guides")
    p["5"] = {"class_type": "MaskToImage", "inputs": {"mask": ["2", 1]}}
    p["6"] = save(["5", 0], "01-mask")
    result.append(("01-手工选区与走向引导", p))
    p = base()
    p["4"] = {"class_type": "NFStockingSAMLoader", "inputs": {"checkpoint": "sams/sam_vit_b_01ec64.pth", "device": "auto"}}
    p["2"]["inputs"]["sam"] = ["4", 0]
    p["5"] = {"class_type": "MaskToImage", "inputs": {"mask": ["2", 1]}}
    p["6"] = save(["5", 0], "02-sam-mask")
    p["7"] = save(["3", 1], "02-sam-guides")
    result.append(("02-SAM点选与遮罩修边", p))
    p = base()
    p["4"] = {"class_type": "NFStockingDepth", "inputs": {"images": ["1", 0], "model": "stocking_texture/Depth-Anything-V2-Small-hf", "device": "auto"}}
    p["3"]["inputs"]["depth"] = ["4", 0]
    p["5"] = {"class_type": "NFStockingRender", "inputs": dict(params, sparkle_depth=35, sparkle_bright=20)}
    p["6"] = save(["4", 0], "03-depth")
    p["7"] = save(["5", 0], "03-depth-texture")
    p["8"] = save(["3", 1], "03-depth-guides")
    result.append(("03-深度辅助与贴体纹理", p))
    p = base()
    p["11"] = {"class_type": "NFStockingSAMLoader", "inputs": {"checkpoint": "sams/sam_vit_b_01ec64.pth", "device": "auto"}}
    p["2"]["inputs"]["sam"] = ["11", 0]
    for i, (style, _) in enumerate(STYLES, 4):
        p[str(i)] = {"class_type": "NFStockingRender", "inputs": dict(params, style=style)}
        p[str(i + 10)] = save([str(i), 0], "04-" + style)
    compare = {"image1": ["1", 0], "name1": "Original"}
    for i, (style, _) in enumerate(STYLES, 2):
        compare[f"image{i}"] = [str(i + 2), 0]
        compare[f"name{i}"] = {"knit": "Fine", "loops": "Loops", "lines": "Slant", "grain": "Grain", "oily": "Oily"}[style]
    p["9"] = {"class_type": "ParallelVideoComparison", "inputs": compare}
    p["10"] = save(["9", 0], "04-five-styles")
    result.append(("04-五种纹理并排对比", p))
    p = base()
    p["4"] = {"class_type": "NFStockingRender", "inputs": dict(params, style="loops")}
    p["5"] = {"class_type": "InvertMask", "inputs": {"mask": ["4", 2]}}
    p["6"] = {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["4", 1], "alpha": ["5", 0]}}
    p["7"] = save(["6", 0], "05-transparent-layer")
    p["8"] = {"class_type": "ImageCompositeMasked", "inputs": {"destination": ["1", 0], "source": ["4", 1], "mask": ["4", 2], "x": 0, "y": 0, "resize_source": False}}
    p["9"] = save(["8", 0], "05-recomposited")
    p["10"] = save(["4", 3], "05-diagnostics")
    p["11"] = save(["4", 0], "05-final")
    result.append(("05-透明图层合成与问题诊断", p))
    return result


def layout(index, prompt):
    common = {"1": [0, 160], "2": [400, 160], "3": [800, 160]}
    positions = dict(common)
    if index == 1:
        positions.update({"4": [1200, 160], "5": [800, 550], "6": [1200, 550]})
    elif index == 2:
        positions.update({"4": [0, 560], "5": [800, 540], "6": [1200, 540], "7": [1200, 160]})
    elif index == 3:
        positions.update({"4": [0, 600], "5": [1200, 160], "6": [400, 600], "7": [1600, 160], "8": [800, 600]})
    elif index == 4:
        for i in range(4, 9):
            positions[str(i)] = [1200, 160 + (i - 4) * 520]
            positions[str(i + 10)] = [1600, 160 + (i - 4) * 520]
        positions["9"] = [2000, 160]; positions["10"] = [2400, 160]; positions["11"] = [0, 600]
    else:
        positions.update({"4": [1200, 160], "5": [1200, 720], "6": [1600, 720], "7": [2000, 720],
                          "8": [1600, 160], "9": [2000, 160], "10": [1600, 1150], "11": [2000, 1150]})
    return positions


def workflow(prompt, schemas, index, title):
    nodes, links = [], []
    positions = layout(index, prompt)
    labels = {"LoadImage": "参考图片（替换图片后需重建引导）", "NFStockingEditor": "部位与走向编辑 · 先运行再打开",
              "NFStockingSolve": "求解横纹与隔开", "NFStockingSAMLoader": "SAM 点选模型 · 编辑器内点击选区",
              "NFStockingDepth": "Small 深度 · 本地模型", "ImageCompositeMasked": "将丝袜图层叠回原图"}
    for key, entry in prompt.items():
        schema = schemas[entry["class_type"]]
        inputs, values = [], []
        for group in ("required", "optional"):
            for name in schema.get("input_order", {}).get(group, list(schema["input"].get(group, {}))):
                spec = schema["input"][group][name]; typ = spec[0]
                opts = spec[1] if len(spec) > 1 else {}
                is_widget = typ == "COMBO" or isinstance(typ, list) or (typ in SCALARS and not opts.get("forceInput"))
                if is_widget:
                    default = opts.get("default", typ[0] if isinstance(typ, list) and typ else opts.get("options", [""])[0])
                    values.append(entry["inputs"].get(name, default))
                    if name in ("seed", "noise_seed"): values.append("fixed")
                else:
                    inputs.append({"name": name, "type": typ, "link": None})
        if entry["class_type"] == "LoadImage": values.append("image")
        output_types = schema.get("output", [])
        output_names = schema.get("output_name", output_types)
        outputs = [{"name": name, "type": typ, "links": []} for name, typ in zip(output_names, output_types)]
        node_title = labels.get(entry["class_type"], schema.get("display_name", entry["class_type"]))
        if entry["class_type"] == "NFStockingRender": node_title = dict(STYLES)[entry["inputs"]["style"]] + " · 自动强度，独立亮点"
        if entry["class_type"] == "SaveImage": node_title = "保存 " + entry["inputs"]["filename_prefix"].split("/")[-1]
        nodes.append({"id": int(key), "type": entry["class_type"], "title": node_title, "pos": positions.get(key, [400 * (len(nodes) % 4), 160 + 500 * (len(nodes) // 4)]),
                      "size": [330, 460 if entry["class_type"] == "NFStockingRender" else 290], "flags": {},
                      "order": len(nodes), "mode": 0, "inputs": inputs, "outputs": outputs,
                      "properties": {"Node name for S&R": entry["class_type"]}, "widgets_values": values})
    lookup = {n["id"]: n for n in nodes}
    for key, entry in prompt.items():
        for name, val in entry["inputs"].items():
            if not isinstance(val, list): continue
            target = lookup[int(key)]; slot = next(i for i, inp in enumerate(target["inputs"]) if inp["name"] == name)
            origin = lookup[int(val[0])]; origin_slot = val[1]; typ = target["inputs"][slot]["type"]
            if origin["outputs"][origin_slot]["type"] != typ: raise ValueError(f"Invalid link type: {name}")
            lid = len(links) + 1; links.append([lid, origin["id"], origin_slot, target["id"], slot, typ])
            target["inputs"][slot]["link"] = lid; origin["outputs"][origin_slot]["links"].append(lid)
    right = max(n["pos"][0] + n["size"][0] for n in nodes)
    bottom = max(n["pos"][1] + n["size"][1] for n in nodes)
    return {"last_node_id": max(lookup), "last_link_id": len(links), "nodes": nodes, "links": links,
            "groups": [{"title": title + " · 首次运行获取底图，编辑后重新执行", "bounding": [-30, 90, right + 80, bottom - 40],
                        "color": "#38695d", "font_size": 24, "flags": {}}], "config": {},
            "extra": {"ds": {"scale": 0.7 if index < 4 else 0.65, "offset": [80, 230]}}, "version": 0.4}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True); parser.add_argument("--image-name")
    parser.add_argument("--guides", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--prefix", default="ToolBoxStocking/functions")
    parser.add_argument("--density", type=float, default=60)
    args = parser.parse_args()
    if not 40 <= args.density <= 200: parser.error("density must be 40..200")
    guides = json.loads(Path(args.guides).read_text())
    with Image.open(args.image) as im:
        if (guides.get("width"), guides.get("height")) != im.size: parser.error("guide dimensions differ from image")
    image_name = args.image_name or Path(args.image).name
    items = graphs(image_name, guides, args.prefix, args.density)
    classes = {n["class_type"] for _, p in items for n in p.values()}
    schemas = {}
    for name in sorted(classes):
        response = json.load(urllib.request.urlopen(args.url.rstrip("/") + "/object_info/" + name, timeout=15))
        if name not in response: parser.error(f"missing node {name}")
        schemas[name] = response[name]
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    for index, (title, prompt) in enumerate(items, 1):
        (output / (title + ".api.json")).write_text(json.dumps(prompt, ensure_ascii=False, indent=2))
        (output / (title + ".json")).write_text(json.dumps(workflow(prompt, schemas, index, title), ensure_ascii=False, indent=2))
        print(title, flush=True)


if __name__ == "__main__": main()
