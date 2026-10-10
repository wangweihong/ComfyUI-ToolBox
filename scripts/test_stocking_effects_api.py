"""Queue public effect workflows, verify exact preview/layer contracts, save comparison evidence."""
import argparse
import base64
import copy
import io
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

from generate_stocking_effect_workflows import graphs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="http://127.0.0.1:8188")
    parser.add_argument("--output",type=Path,default=Path("data/stocking_effects_validation"))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    def request(path,body=None):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(args.url+path,data,{"Content-Type":"application/json"})
        return json.load(urllib.request.urlopen(req,timeout=180))
    def queue(prompt):
        pid=request("/prompt",{"prompt":prompt})["prompt_id"]
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            entry=request("/history/"+pid).get(pid)
            if entry:
                if entry["status"]["status_str"]!="success":
                    raise RuntimeError(entry["status"])
                return pid,entry
            time.sleep(.3)
        raise TimeoutError(pid)
    def pixels(item):
        raw=urllib.request.urlopen(args.url+"/view?"+urllib.parse.urlencode(item)).read()
        return np.asarray(Image.open(io.BytesIO(raw)))
    reports=[];items=graphs();gallery=[]
    for title,prompt in items:
        pid,entry=queue(prompt)
        record={"workflow":title,"prompt_id":pid,"nodes":[]}
        for nid,node in prompt.items():
            if node["class_type"]!="NFStockingTexture":continue
            payload=entry["outputs"][nid]["nf_stocking"][0]
            report=payload["report"]
            assert all(r["changed_pixels"]>0 for r in report)
            out_nid=next(key for key,n in prompt.items() if n["class_type"]=="PreviewImage" and n["inputs"]["images"]==[nid,0])
            out=pixels(entry["outputs"][out_nid]["images"][0])
            revision=int(nid)+100
            preview=request("/toolbox/stocking/preview",{"session":payload["session"],"index":0,"client":"effect-api-acceptance","revision":revision,
                 "guides_json":json.dumps(payload["document"]),"settings":payload["params"],"rect":[80,100,400,600]})
            crop=np.asarray(Image.open(io.BytesIO(base64.b64decode(preview["png"]))))
            assert np.array_equal(crop,out[100:600,80:400])
            record["nodes"].append({"style":node["inputs"]["style"],"preview_matches_queue":True,"report":report})
            if title.startswith("06"):
                gallery.append((node["inputs"]["style"],Image.fromarray(out)))
            else:Image.fromarray(out).save(args.output/(title+".png"))
        reports.append(record);print(title+": passed",flush=True)
        (args.output/"api-results.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    # Extra outputs exercise exact composition and RGBA export with combined effects.
    p=copy.deepcopy(items[-1][1])
    p["6"]={"class_type":"ImageCompositeMasked","inputs":{"destination":["2",5],"source":["2",1],"mask":["2",2],"x":0,"y":0,"resize_source":False}}
    p["7"]={"class_type":"PreviewImage","inputs":{"images":["6",0]}}
    p["8"]={"class_type":"InvertMask","inputs":{"mask":["2",2]}}
    p["9"]={"class_type":"JoinImageWithAlpha","inputs":{"image":["2",1],"alpha":["8",0]}}
    p["10"]={"class_type":"PreviewImage","inputs":{"images":["9",0]}}
    pid,entry=queue(p)
    assert np.array_equal(pixels(entry["outputs"]["5"]["images"][0]),pixels(entry["outputs"]["7"]["images"][0]))
    layer=pixels(entry["outputs"]["10"]["images"][0]);assert layer.shape[-1]==4 and layer[...,3].min()==0 and layer[...,3].max()==255
    reports.append({"workflow":"combined-layer-contract","prompt_id":pid,"composition_exact":True,"rgba_valid":True})
    # The older split Editor -> Solve -> Render recipes accept the new effects too.
    root=Path(__file__).resolve().parents[1]
    advanced=json.loads((root/"examples/stocking_texture/manual.api.json").read_text())
    for node in advanced.values():
        if node["class_type"]=="SaveImage":
            node["class_type"]="PreviewImage";node["inputs"].pop("filename_prefix",None)
    advanced["4"]["inputs"].update(style="lace",effects_json=json.dumps({"text":{"enabled":True,"content":"PARIS"},"damage":{"enabled":True,"mode":"random","count":3}}))
    pid,entry=queue(advanced)
    payload=entry["outputs"]["4"]["nf_stocking"][0]
    preview=request("/toolbox/stocking/preview",{"session":payload["session"],"index":0,"client":"effect-advanced-acceptance","revision":1,"rect":[80,100,400,600]})
    crop=np.asarray(Image.open(io.BytesIO(base64.b64decode(preview["png"]))))
    output=pixels(entry["outputs"]["5"]["images"][0])
    assert np.array_equal(crop,output[100:600,80:400])
    reports.append({"workflow":"advanced-renderer-effects","prompt_id":pid,"preview_matches_queue":True,"report":preview["info"]})
    (args.output/"api-results.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    gallery_image=Image.new("RGB",(4*256,2*414),(22,26,34));draw=ImageDraw.Draw(gallery_image)
    for i,(name,im) in enumerate(gallery):
        im=im.resize((256,384),Image.Resampling.LANCZOS)
        x,y=(i%4)*256,(i//4)*414;gallery_image.paste(im,(x,y));draw.text((x+10,y+390),name,fill="white")
    gallery_image.save(args.output/"patterns-overview.png")
    print("Combined layer exactly equals final; RGBA transparency valid",flush=True)


if __name__=="__main__":main()
