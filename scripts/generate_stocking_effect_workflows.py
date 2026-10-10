"""Four public, model-free recipes for patterns, lettering and snags."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image

from generate_stocking_function_workflows import workflow

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "web/js/stocking_styles.json").read_text())


def records(damage=False):
    image = np.asarray(Image.open(ROOT / "examples/stocking_texture/assets/tb_stocking_demo.png").convert("RGB"), dtype=np.float32) / np.float32(255)
    h = hashlib.blake2b(digest_size=16)
    h.update(str((image.shape, image.dtype)).encode()); h.update(image.tobytes())
    doc = json.loads((ROOT / "examples/stocking_texture/assets/guides.json").read_text())
    if damage:
        for region in doc["frames"][0]["regions"]:
            # A short hand-placed snag and a point that grows into a local ladder run.
            stroke = region["strokes"][1]
            x,y = stroke[len(stroke)//2]
            region["damage_strokes"] = [
                {"type":"snag","points":[[x-12,y-45],[x-8,y],[x+4,y+45]],"width":3},
                {"type":"ladder","points":[[x+16,y+60]],"width":4}]
    return json.dumps({"version":2,"records":{h.hexdigest():doc}},ensure_ascii=False)


def graphs():
    common = {"images":["1",0],"guides_json":records(),"source_mode":"manual","prompt":"stockings","threshold":.4,
              "auto_direction":True,"depth_direction":"white_near","auto_walls":True,"failure_mode":"skip",
              "style":"knit","density":100,"tilt":32,"strength":100,"strength_auto":True,"color_exclude":True,
              "sparkle_depth":0,"sparkle_bright":0,"sparkle_painted":0,"sparkle_even":0,"seed":20261005,"effects_json":"{}"}
    def base():
        return {"1":{"class_type":"LoadImage","inputs":{"image":"tb_stocking_demo.png"}},
                "2":{"class_type":"NFStockingTexture","inputs":copy.deepcopy(common)},
                "5":{"class_type":"PreviewImage","inputs":{"images":["2",0]}}}
    items=[]
    p=base()
    for index,style in enumerate(s for s in REGISTRY if s["period"]):
        nid=str(2+index*10)
        p[nid]={"class_type":"NFStockingTexture","inputs":dict(common,style=style["id"],effects_json=json.dumps({"pattern":{"mode":"print"}}))}
        p[str(5+index*10)]={"class_type":"PreviewImage","inputs":{"images":[nid,0]}}
    items.append(("06-八种花纹总览",p))
    p=base();p["2"]["inputs"]["effects_json"]=json.dumps({"pattern":{"mode":"print"},"text":{"enabled":True,"content":"BALENCIAGA","size":100,"rotation":-12}})
    items.append(("07-英文错行印花",p))
    p=base();p["2"]["inputs"].update(guides_json=records(True),effects_json=json.dumps({"damage":{"enabled":True,"mode":"both","type":"mixed","count":5,"strength":85}}))
    items.append(("08-钩丝与梯状抽丝",p))
    p=base();p["2"]["inputs"].update(style="hearts",guides_json=records(True),effects_json=json.dumps({"pattern":{"mode":"fabric","size":130,"color":"#442233"},"text":{"enabled":True,"content":"PARIS","size":100,"rotation":-15,"color":"#dddddd"},"damage":{"enabled":True,"mode":"both","type":"mixed","strength":80}}))
    items.append(("09-花纹文字损伤组合",p))
    return items


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="http://127.0.0.1:8188")
    parser.add_argument("--output",type=Path,default=ROOT/"examples/stocking_texture/effects")
    args=parser.parse_args(); items=graphs(); schemas={}
    for name in {n["class_type"] for _,p in items for n in p.values()}:
        schemas.update(json.load(urllib.request.urlopen(args.url+"/object_info/"+urllib.parse.quote(name))))
    args.output.mkdir(parents=True,exist_ok=True)
    for title,prompt in items:
        ui=workflow(prompt,schemas,4,title)
        for i,n in enumerate(ui["nodes"]):
            n["pos"]=[(i%4)*420,(i//4)*420+160];n["size"]=[360,280]
            if n["type"]=="NFStockingTexture":
                n["title"]=next(s["label"] for s in REGISTRY if s["id"]==prompt[str(n["id"])]["inputs"]["style"])
        ui["groups"]=[]
        (args.output/(title+".api.json")).write_text(json.dumps(prompt,ensure_ascii=False,indent=2)+"\n")
        (args.output/(title+".json")).write_text(json.dumps(ui,ensure_ascii=False,indent=2)+"\n")
        print(title)


if __name__=="__main__":
    main()
