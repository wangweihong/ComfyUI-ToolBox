"""Port compatibility and native executor checks for the migrated controls."""

import importlib.util
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("toolbox_control_test", ROOT / "nodes/control_nodes.py")
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


def test_primitive_values_preserve_large_integers_and_text():
    integer = controls.ToolBoxPrimitiveInteger()
    for value in [-sys.maxsize, -1, 0, 1, sys.maxsize]:
        assert integer.execute(int=value) == (value,)
    assert type(integer.execute()[0]) is int
    text = "中文\n  indented\r\n\tlast line  "
    assert controls.ToolBoxPrimitiveStringMultiline().execute(string=text) == (text,)


@pytest.mark.parametrize("node", [controls.ToolBoxSwitchAny, controls.ToolBoxSwitchImage])
@pytest.mark.parametrize("boolean", [True, False])
def test_lazy_request_and_identity(node, boolean):
    selected = object()
    inputs = {"on_true" if boolean else "on_false": selected, "boolean": boolean}
    assert node().check_lazy_status(**inputs) == ["on_true" if boolean else "on_false"]
    assert node().execute(**inputs)[0] is selected


def test_ports_locales_and_registration():
    expected = {
        "ToolBoxSwitchAny": ["on_true", "on_false", "boolean"],
        "ToolBoxSwitchImage": ["on_true", "on_false", "boolean"],
        "ToolBoxPrimitiveInteger": ["int"],
        "ToolBoxPrimitiveStringMultiline": ["string"],
    }
    for node_id, ports in expected.items():
        node = controls.NODE_CLASS_MAPPINGS[node_id]
        assert list(node.INPUT_TYPES()["required"]) == ports
        assert controls.NODE_DISPLAY_NAME_MAPPINGS[node_id].startswith("tb-")
        for language in ["en", "zh"]:
            entry = json.loads((ROOT / f"locales/{language}/nodeDefs.json").read_text())[node_id]
            assert entry["display_name"] == controls.NODE_DISPLAY_NAME_MAPPINGS[node_id]
            assert set(entry["inputs"]) == set(ports)


@pytest.mark.parametrize("node_id", ["ToolBoxSwitchAny", "ToolBoxSwitchImage"])
@pytest.mark.parametrize("boolean", [True, False])
def test_native_executor_skips_unselected_branch(monkeypatch, node_id, boolean):
    comfy = Path("/root/ComfyUI")
    try:
        available = (comfy / "execution.py").is_file()
    except OSError:
        available = False
    if not available:
        pytest.skip("Requires the existing ComfyUI Python environment")
    monkeypatch.syspath_prepend(str(comfy))
    import comfy.cli_args
    comfy.cli_args.args.cpu = True
    import execution
    import nodes
    import torch

    selected = torch.zeros((1, 2, 3, 3)) if node_id == "ToolBoxSwitchImage" else {"value": "unchanged"}
    data_type = "IMAGE" if node_id == "ToolBoxSwitchImage" else "*"
    seen = []

    class Source:
        RETURN_TYPES = (data_type,)
        FUNCTION = "execute"

        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}

        def execute(self):
            return (selected,)

    class Unselected(Source):
        def execute(self):
            raise AssertionError("The unselected branch must not execute")

    class Sink:
        RETURN_TYPES = ()
        FUNCTION = "execute"
        OUTPUT_NODE = True

        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"value": (data_type,)}}

        def execute(self, value):
            seen.append(value)
            return ()

    class Server:
        client_id = None
        last_node_id = None

        def send_sync(self, *args, **kwargs):
            pass

    for key, node in {**controls.NODE_CLASS_MAPPINGS, "TBTestSource": Source,
                      "TBTestUnselected": Unselected, "TBTestSink": Sink}.items():
        monkeypatch.setitem(nodes.NODE_CLASS_MAPPINGS, key, node)
    prompt = {
        "1": {"class_type": "TBTestSource", "inputs": {}},
        "2": {"class_type": "TBTestUnselected", "inputs": {}},
        "3": {"class_type": node_id, "inputs": {
            "on_true": ["1" if boolean else "2", 0],
            "on_false": ["2" if boolean else "1", 0], "boolean": boolean}},
        "4": {"class_type": "TBTestSink", "inputs": {"value": ["3", 0]}},
    }
    valid = asyncio.run(execution.validate_inputs("tb-control-validation", prompt, "4", {}))
    assert valid[0], valid[1]
    executor = execution.PromptExecutor(Server(), cache_args={"ram": 0, "ram_inactive": 0})
    executor.execute(prompt, f"tb-control-{node_id}-{boolean}", execute_outputs=["4"])
    assert executor.success, executor.status_messages
    assert len(seen) == 1
    assert seen[0] is selected
