"""Generate a public synthetic 2px-grid fixture and PreviewImage workflows."""

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "examples/degrid"
    (directory / "assets").mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:384, :512]
    base = 0.18 + 0.25 * x / 511 + 0.12 * y / 383
    image = np.stack([base, base * 0.85, base * 0.7], axis=-1)
    ellipse = ((x - 190) / 95) ** 2 + ((y - 192) / 130) ** 2 < 1
    image[ellipse] += [0.15, 0.20, 0.26]
    image[90:294, 340:344] = [0.9, 0.8, 0.65]
    grid = 0.008 * (1 - 2 * ((x + y) % 2)) + 0.002 * (1 - 2 * (x % 2))
    Image.fromarray(np.rint(np.clip(image + grid[..., None], 0, 1) * 255).astype(np.uint8)).save(directory / "assets/tb_degrid_demo.png")

    values = dict(enabled=True, mode="auto", limit=0.02, skip_when_clean=True,
                  grid_gain=10.0, grid_view="4x zoom")
    api = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "tb_degrid_demo.png"}},
        "2": {"class_type": "ToolBoxVAEDeGrid", "inputs": {"image": ["1", 0], **values}},
        "3": {"class_type": "PreviewImage", "inputs": {"images": ["1", 0]}},
        "4": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
        "5": {"class_type": "PreviewImage", "inputs": {"images": ["2", 1]}},
    }
    links = [[1, 1, 0, 2, 0, "IMAGE"], [2, 1, 0, 3, 0, "IMAGE"],
             [3, 2, 0, 4, 0, "IMAGE"], [4, 2, 1, 5, 0, "IMAGE"]]

    def node(identifier, kind, title, pos, size, inputs, outputs, widgets):
        return dict(id=identifier, type=kind, title=title, pos=pos, size=size,
                    flags={}, order=identifier - 1, mode=0, inputs=inputs, outputs=outputs,
                    properties={"Node name for S&R": kind}, widgets_values=widgets)

    nodes = [
        node(1, "LoadImage", "公开合成测试图 / Synthetic grid", [0, 40], [340, 390], [],
             [{"name": "IMAGE", "type": "IMAGE", "links": [1, 2]}, {"name": "MASK", "type": "MASK", "links": []}], ["tb_degrid_demo.png", "image"]),
        node(2, "ToolBoxVAEDeGrid", "VAE 解码后、缩放锐化前 / Before resize", [400, 40], [360, 350],
             [{"name": "image", "type": "IMAGE", "link": 1}],
             [{"name": "image", "type": "IMAGE", "links": [3]}, {"name": "removed_grid", "type": "IMAGE", "links": [4]}], list(values.values())),
    ]
    for identifier, title, position, link in [
        (3, "原图 / Original", [0, 510], 2),
        (4, "去网格 / Cleaned", [400, 510], 3),
        (5, "移除的网格 · 4倍预览 / Removed grid", [800, 510], 4),
    ]:
        nodes.append(node(identifier, "PreviewImage", title, position, [360, 350],
                          [{"name": "images", "type": "IMAGE", "link": link}], [], []))
    workflow = dict(last_node_id=5, last_link_id=4, nodes=nodes, links=links, groups=[],
                    config={}, extra={"ds": {"scale": 0.8, "offset": [80, 40]}}, version=0.4)
    for suffix, data in [(".json", workflow), (".api.json", api)]:
        (directory / ("01-去网格对比" + suffix)).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
