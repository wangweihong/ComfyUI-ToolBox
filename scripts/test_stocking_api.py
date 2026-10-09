"""End-to-end ComfyUI queue/PNG/preview verification on generated public fixtures."""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
import uuid

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--include-sam", action="store_true")
    parser.add_argument("--output", default="/tmp/stocking-api-tests.json")
    args = parser.parse_args(); base = args.url.rstrip("/")
    def get(path):
        return json.load(urllib.request.urlopen(base + path, timeout=30))
    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=60))
    assets = ROOT / "examples/stocking_texture/assets"
    for path in assets.glob("tb_stocking_demo*.png"):
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(base + "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        uploaded = json.load(urllib.request.urlopen(req, timeout=30))
        if uploaded["name"] != path.name:
            raise RuntimeError("Fixture filename already contains different data; use an isolated input directory")
    art = np.array(Image.open(assets / "tb_stocking_demo.png").convert("RGB"))
    reports = []
    for variant in ["manual", "external-depth", "batch"] + (["sam"] if args.include_sam else []):
        prompt = json.loads((ROOT / f"examples/stocking_texture/{variant}.api.json").read_text())
        result = post("/prompt", {"prompt": prompt, "client_id": "toolbox-stocking-api-tests"})
        pid = result["prompt_id"]; deadline = time.monotonic() + 180
        history = None
        while time.monotonic() < deadline:
            history = get("/history/" + pid).get(pid)
            if history: break
            time.sleep(0.5)
        if not history or history["status"]["status_str"] != "success":
            raise RuntimeError(f"{variant} failed: {history['status'] if history else 'timeout'}")
        outputs = history["outputs"]
        def pixels(item):
            raw = urllib.request.urlopen(base + "/view?" + urllib.parse.urlencode(item), timeout=30).read()
            return np.array(Image.open(io.BytesIO(raw)))
        images = outputs["5"]["images"]; layers = outputs["9"]["images"]
        assert len(images) == (4 if variant == "batch" else 1)
        for image, layer in zip(images, layers):
            out, rgba = pixels(image), pixels(layer)
            alpha = rgba[..., 3:4] / 255
            composite = np.round(rgba[..., :3] * alpha + art * (1 - alpha)).astype(np.uint8)
            assert np.array_equal(out, composite), "Layer composite differs from final image"
        token = outputs["4"]["nf_stocking"][0]["session"]
        p = {"session": token, "client": uuid.uuid4().hex, "index": 0, "rect": [80, 100, 400, 600], "revision": 10}
        preview = post("/toolbox/stocking/preview", p)
        crop = np.array(Image.open(io.BytesIO(base64.b64decode(preview["png"]))))
        assert np.array_equal(crop, pixels(images[0])[100:600, 80:400])
        assert post("/toolbox/stocking/preview", dict(p, revision=9))["stale"]
        record = {"variant": variant, "images": len(images), "status": "success", "layer_composite_exact": True,
                  "crop_equals_saved_image": True, "stale_request_rejected": True}
        if variant == "sam":
            sam_token = outputs["2"]["nf_stocking"][0]["session"]
            candidate = post("/toolbox/stocking/sam", {"session": sam_token, "index": 0, "x": 154, "y": 390})
            masks = [np.array(Image.open(io.BytesIO(base64.b64decode(m)))) > 127 for m in candidate["masks"]]
            areas = [int(m.sum()) for m in masks]
            assert len(masks) == 3 and areas == sorted(areas)
            record["sam_areas"] = areas
        reports.append(record); print(json.dumps(record), flush=True)
        Path(args.output).write_text(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
