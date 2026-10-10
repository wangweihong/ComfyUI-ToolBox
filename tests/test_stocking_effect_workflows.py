import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from generate_stocking_effect_workflows import graphs
from generate_stocking_function_workflows import workflow


def test_four_effect_recipes_are_public_self_contained_and_preview_only():
    items = graphs()
    assert len(items) == 4
    assert sum(n["class_type"]=="NFStockingTexture" for n in items[0][1].values()) == 8
    for title,prompt in items:
        assert prompt["1"]["inputs"]["image"] == "tb_stocking_demo.png"
        assert not any(n["class_type"] in ("SaveImage","easy sam3ModelLoader","NFStockingSAMLoader") for n in prompt.values())
        for n in prompt.values():
            if n["class_type"]=="NFStockingTexture":
                assert n["inputs"]["source_mode"]=="manual"
                assert len(json.loads(n["inputs"]["guides_json"])["records"])==1
    damage=json.loads(items[2][1]["2"]["inputs"]["guides_json"])
    assert all(r["damage_strokes"] for d in damage["records"].values() for r in d["frames"][0]["regions"])
