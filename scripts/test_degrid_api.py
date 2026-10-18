"""Validate real ComfyUI previews against the local tensor implementation.

Run with ComfyUI's Python dependencies, from the ToolBox checkout.
"""

import argparse
import io
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nodes.degrid.degrid_core import extract_grid, lattice_amp
from nodes.degrid.nodes import ToolBoxVAEDeGrid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--image", action="append", help="Input filename; repeat for multiple images.")
    parser.add_argument("--output", type=Path, default=ROOT / "data/degrid_validation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)

    def request(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(args.url + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def pixels(reference):
        query = urllib.parse.urlencode(reference)
        with urllib.request.urlopen(args.url + "/view?" + query, timeout=30) as response:
            return np.array(Image.open(io.BytesIO(response.read())).convert("RGB"))

    def amplitude(tensor):
        return lattice_amp(extract_grid(tensor.permute(0, 3, 1, 2).contiguous()))[0][0].item() * 255

    def execute(prompt):
        prompt_id = request("/prompt", {"prompt": prompt})["prompt_id"]
        deadline = time.monotonic() + 180
        while True:
            history = request("/history/" + prompt_id).get(prompt_id)
            if history:
                assert history["status"]["status_str"] == "success", history["status"]
                return prompt_id, history
            if time.monotonic() > deadline:
                raise TimeoutError(f"DeGrid queue timed out: {prompt_id}")
            time.sleep(0.5)

    schema = request("/object_info/ToolBoxVAEDeGrid")["ToolBoxVAEDeGrid"]
    assert schema["output"] == ["IMAGE", "IMAGE"]
    assert schema["category"] == "eazy-toolbox/image"
    assert schema["output_node"] is True
    rows = []
    images = args.image or ["tb_degrid_demo.png"]
    for index, filename in enumerate(images):
        prompt = json.loads((ROOT / "examples/degrid/01-去网格对比.api.json").read_text())
        prompt["1"]["inputs"]["image"] = filename
        started = time.monotonic()
        prompt_id, history = execute(prompt)
        outputs = history["outputs"]
        original = pixels(outputs["3"]["images"][0])
        cleaned = pixels(outputs["4"]["images"][0])
        preview = pixels(outputs["5"]["images"][0])
        tensor = torch.from_numpy(original.astype(np.float32) / 255)[None]
        expected = ToolBoxVAEDeGrid().process(tensor)["result"][0]
        expected8 = (expected[0].numpy() * 255).clip(0, 255).astype(np.uint8)
        error = np.abs(cleaned.astype(int) - expected8.astype(int)).max()
        assert original.shape == cleaned.shape and error <= 1
        stats = outputs["2"]["degrid"][0]
        delta = np.abs(cleaned.astype(int) - original.astype(int))
        row = dict(image=filename, prompt_id=prompt_id, status="success", shape=list(cleaned.shape),
                   queue_and_validation_seconds=round(time.monotonic() - started, 3),
                   input_grid_255=amplitude(tensor),
                   output_grid_255=amplitude(torch.from_numpy(cleaned.astype(np.float32) / 255)[None]),
                   mean_change_255=float(delta.mean()), max_change_255=int(delta.max()),
                   reference_max_error_255=int(error), node_status=stats)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if index in [0, len(images) - 1]:
            panels = []
            for rgb in [original, cleaned, preview]:
                h, w = rgb.shape[:2]
                crop = Image.fromarray(rgb).crop((w // 2 - 64, h // 2 - 64, w // 2 + 64, h // 2 + 64))
                panels.append(crop.resize((512, 512), Image.Resampling.NEAREST))
            comparison = Image.new("RGB", (1536, 548), "#202020")
            draw = ImageDraw.Draw(comparison)
            for column, (panel, title) in enumerate(zip(panels, ["Original (4x native pixels)", "Cleaned (4x native pixels)", "Removed grid (preview crop)"])):
                comparison.paste(panel, (column * 512, 36))
                draw.text((column * 512 + 12, 10), title, fill="white")
            comparison.save(args.output / f"comparison_{index + 1:02}.png")
    cached_id, cached = execute(prompt)
    cached_nodes = next(message[1]["nodes"] for message in cached["status"]["messages"] if message[0] == "execution_cached")
    assert "2" in cached_nodes
    assert cached["outputs"]["2"]["degrid"][0] == rows[-1]["node_status"]
    rows[-1]["cached_prompt_id"] = cached_id
    rows[-1]["cached_status_replayed"] = True
    print("Cached DeGrid status replayed:", cached_id, flush=True)
    (args.output / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
