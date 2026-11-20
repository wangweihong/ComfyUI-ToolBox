"""Run with ComfyUI's Python: this_script.py /path/to/nodes/image_scale.py.

CPU-only native parity and executor checks; no models or persistent images.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


async def main():
    source = sys.argv[1]
    sys.argv = [sys.argv[0], "--cpu"]
    sys.path.insert(0, "/root/ComfyUI")
    import torch
    import execution
    import folder_paths
    import nodes
    from comfy_extras.nodes_post_processing import ResizeImageMaskNode, scale_to_multiple_cover

    spec = importlib.util.spec_from_file_location("toolbox_scale_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = module.ToolBoxImageScale
    schema = cls.define_schema()
    assert schema.node_id == "ToolBoxImageScale"
    assert len(schema.outputs) == 4
    cases = []
    for width, height in [(63, 41), (41, 63), (31, 17), (64, 64)]:
        for is_mask in (False, True):
            tensor = torch.rand((2, height, width) if is_mask else (2, height, width, 4))
            original = tensor.clone()
            match = torch.rand((1, 35, 51))
            modes = [
                {"resize_type": "scale dimensions", "width": 32, "height": 24, "crop": "disabled"},
                {"resize_type": "scale dimensions", "width": 32, "height": 24, "crop": "center"},
                {"resize_type": "scale dimensions", "width": 0, "height": 24, "crop": "center"},
                {"resize_type": "scale dimensions", "width": 0, "height": 0, "crop": "center"},
                {"resize_type": "scale by multiplier", "multiplier": 0.5},
                {"resize_type": "scale longer dimension", "longer_size": 70},
                {"resize_type": "scale shorter dimension", "shorter_size": 22},
                {"resize_type": "scale width", "width": 42},
                {"resize_type": "scale width", "width": 0},
                {"resize_type": "scale height", "height": 18},
                {"resize_type": "scale height", "height": 0},
                {"resize_type": "scale total pixels", "megapixels": 0.01},
                {"resize_type": "match size", "match": match, "crop": "center"},
                {"resize_type": "scale to multiple", "multiple": 16},
                {"resize_type": "scale to multiple", "multiple": 128},
            ]
            for params in modes:
                for multiple in (1, 8, 32, 128):
                    for method in ("area", "bicubic"):
                        result = cls.execute(tensor, method, params, multiple)
                        native = ResizeImageMaskNode.execute(tensor, method, params)[0]
                        expected = scale_to_multiple_cover(native, multiple, method)
                        assert torch.equal(result[0], expected), (params, method, multiple)
                        assert torch.equal(tensor, original)
                        assert result[0].dtype == tensor.dtype and result[0].shape[0] == 2
                        if not is_mask:
                            assert result[0].shape[-1] == 4
                        report = result.ui["toolbox_scale"][0]
                        assert report["source"] == [width, height]
                        assert report["output"] == list(result.result[1:3])
                        assert report["resized"] == module.dimensions(native)
                        assert result.ui["text"] == [result[3]]
                        json.dumps(report)
                        if not is_mask and method == "area":
                            cases.append(report)
    nodes.NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    prompt = {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 128, "height": 64, "batch_size": 1, "color": 255}},
        "2": {"class_type": "ToolBoxImageScale", "inputs": {"input": ["1", 0], "resize_type": "scale by multiplier",
              "resize_type.multiplier": 0.5, "scale_method": "area", "multiple_of": 32}},
    }
    valid = await execution.validate_prompt("scale-test", prompt, None)
    assert valid[0], valid
    server = SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
    executor = execution.PromptExecutor(server, cache_args={"ram": 0, "ram_inactive": 0, "lru": 0})
    with tempfile.TemporaryDirectory(prefix="toolbox-scale-") as directory:
        folder_paths.set_temp_directory(directory)
        await executor.execute_async(prompt, "scale-test", execute_outputs=valid[2])
        assert executor.success, executor.status_messages
        report = executor.history_result["outputs"]["2"]["toolbox_scale"][0]
        assert report["output"] == [64, 32], report
        assert not list(Path(directory).rglob("*")), "Scale node must not save previews"
    print(json.dumps({"ok": True, "native_parity": 960, "executor": "passed", "cases": cases}))


asyncio.run(main())
