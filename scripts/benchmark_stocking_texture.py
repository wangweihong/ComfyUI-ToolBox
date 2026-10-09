"""Measure the public synthetic fixture on the actual ComfyUI Python runtime."""
import argparse
import importlib.util
import json
from pathlib import Path
import resource
import statistics
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tb_stocking_bench", ROOT / "nodes/stocking_texture/__init__.py", submodule_search_locations=[str(ROOT / "nodes/stocking_texture")])
PACKAGE = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = PACKAGE; SPEC.loader.exec_module(PACKAGE)
from tb_stocking_bench import engine, data
from tb_stocking_bench.cache import REGION_CACHE, SCENE_CACHE
from tb_stocking_bench.core import look, guide_fields as gf
from generate_stocking_examples import artwork


def clock(fn):
    start = time.perf_counter(); result = fn(); return result, time.perf_counter() - start


def measure(height, width, batch, styles):
    art, _, _, doc = artwork(height, width)
    image = art.astype(np.float32) / 255
    images = np.repeat(image[None], batch, axis=0)
    guides, _ = engine.build_guides(images, data.dump_guides(doc))
    REGION_CACHE.clear(); SCENE_CACHE.clear()
    fields, solve_seconds = clock(lambda: engine.solve_batch(images, guides))
    _, solve_cached = clock(lambda: engine.solve_batch(images, guides))
    results = []
    for style in styles:
        params = dict(style=style, sparkle_depth=0, sparkle_bright=0, sparkle_even=100)
        _, full = clock(lambda: engine.render_batch(images, fields, params))
        x, y = max(0, width // 2 - 256), max(0, height // 2 - 256)
        rect = [x, y, min(width, x + 512), min(height, y + 512)]
        warm = []
        for _ in range(3):
            _, seconds = clock(lambda: engine.render_one(image, fields["frames"][0], params, rect=rect))
            warm.append(seconds)
        results.append({"style": style, "full_batch_seconds": full, "warm_512_crop_median_seconds": statistics.median(warm),
                        "scene_cache": SCENE_CACHE.stats()})
    return {"height": height, "width": width, "batch": batch, "cold_solve_seconds": solve_seconds,
            "cached_solve_seconds": solve_cached, "renders": results,
            "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "region_cache": REGION_CACHE.stats()}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default="/tmp/stocking-benchmark.json")
    parser.add_argument("--quick", action="store_true"); args = parser.parse_args()
    import torch
    specs = [(1216, 832), (1920, 1280), (2160, 3840)] if not args.quick else [(768, 512)]
    report = {"python": sys.version, "torch": torch.__version__, "cuda": torch.cuda.is_available(),
              "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
              "note": "Synthetic artwork; solver and renderer are CPU. RSS is cumulative process peak, not per-stage allocation.", "cases": []}
    if torch.cuda.is_available(): torch.cuda.reset_peak_memory_stats()
    for height, width in specs:
        for batch in [1, 4]:
            result = measure(height, width, batch, look.STYLES)
            report["cases"].append(result); print(json.dumps(result, ensure_ascii=False), flush=True)
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report["peak_cuda_allocated_mib"] = torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else 0
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
