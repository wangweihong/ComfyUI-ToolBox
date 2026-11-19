"""Run inside an installed ComfyUI: python this_file.py /path/to/image_compare_node.py.

Uses an isolated executor, CPU-only synthetic images and a temporary preview directory.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace


async def main():
    source = sys.argv[1]
    sys.argv = [sys.argv[0], "--cpu"]
    sys.path.insert(0, "/root/ComfyUI")
    import execution
    import folder_paths
    import nodes
    from comfy_execution.graph import get_input_info

    package = types.ModuleType("toolbox_compare_test")
    package.__path__ = ["/root/ComfyUI/custom_nodes/ComfyUI-ToolBox/nodes"]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location("toolbox_compare_test.image_compare_node", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    nodes.NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    cls = module.ToolBoxImageCompare
    assert get_input_info(cls, "image_200")[:2] == ("IMAGE", "optional")
    params = {"width": 120, "height": 80, "layout": "{}"}
    prompt = {
        "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 2, "color": 16711680}},
        "2": {"class_type": "EmptyImage", "inputs": {"width": 128, "height": 64, "batch_size": 1, "color": 255}},
        "5": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 128, "batch_size": 1, "color": 65280}},
        "3": {"class_type": "ToolBoxImageCompare", "inputs": {**params, "image_1": ["1", 0], "image_2": ["5", 0], "image_200": ["2", 0]}},
        "4": {"class_type": "PreviewImage", "inputs": {"images": ["3", 0]}},
    }
    valid = await execution.validate_prompt("image-compare-test", prompt, None)
    assert valid[0], valid
    test_server = SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
    executor = execution.PromptExecutor(test_server, cache_args={"ram": 0, "ram_inactive": 0, "lru": 0})
    with tempfile.TemporaryDirectory(prefix="toolbox-image-compare-") as directory:
        folder_paths.set_temp_directory(directory)
        await executor.execute_async(prompt, "image-compare-test", execute_outputs=valid[2])
        assert executor.success, executor.status_messages
        ui = executor.history_result["outputs"]["3"]["toolbox_image_compare"]
        assert [group["input"] for group in ui] == ["image_1", "image_2", "image_200"], ui
        assert [len(group["images"]) for group in ui] == [2, 1, 1], ui
        from PIL import Image
        composite = executor.history_result["outputs"]["4"]["images"][0]
        with Image.open(Path(directory) / composite["subfolder"] / composite["filename"]) as picture:
            assert picture.size == (120, 80)
            assert picture.getpixel((0, 40)) == (255, 0, 0)
            assert picture.getpixel((50, 40)) == (0, 255, 0)
            assert picture.getpixel((119, 40)) == (0, 0, 255)
        # Only the explicit downstream PreviewImage writes a file.
        assert len(list(Path(directory).rglob("*.png"))) == 1
        assert all(set(image) == {"width", "height"} for group in ui for image in group["images"])
        # Empty sockets must not prevent a standalone comparison node from executing.
        empty = {"3": {"class_type": "ToolBoxImageCompare", "inputs": params.copy()}}
        empty_valid = await execution.validate_prompt("empty", empty, None)
        assert empty_valid[0], empty_valid
        await executor.execute_async(empty, "empty", execute_outputs=empty_valid[2])
        assert executor.success
        assert executor.history_result["outputs"]["3"]["toolbox_image_compare"] == []
    mismatch = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
        "3": {"class_type": "ToolBoxImageCompare", "inputs": {**params, "image_200": ["1", 0]}},
    }
    # Legacy dynamic sockets are type checked by the adapter at execution time.
    with tempfile.TemporaryDirectory(prefix="toolbox-image-compare-invalid-") as directory:
        folder_paths.set_temp_directory(directory)
        await executor.execute_async(mismatch, "mismatch", execute_outputs=["3"])
        assert not executor.success
        errors = [data for event, data in executor.status_messages if event == "execution_error"]
        assert errors and "image_200: expected" in errors[0]["exception_message"], errors
        assert not list(Path(directory).rglob("*.png"))
    print(json.dumps({"ok": True, "dynamic_input": "image_200", "frames": 3, "source_previews": 0, "image_output": "verified pixels via PreviewImage",
                      "empty_node": "passed", "wrong_type": "runtime rejected"}))


asyncio.run(main())
