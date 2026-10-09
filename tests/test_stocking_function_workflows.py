"""Offline graph contracts against sanitized ComfyUI 0.39 node schemas."""
import json
from pathlib import Path
import unittest

from scripts.generate_stocking_function_workflows import graphs, workflow


class FunctionalWorkflowsTest(unittest.TestCase):
    def setUp(self):
        self.guides = {"version": 1, "width": 540, "height": 960, "frames": [{"regions": []}]}
        self.graphs = graphs("reference.png", self.guides, "test", 60)
        self.schemas = json.loads((Path(__file__).parent / "fixtures/stocking_node_schemas.json").read_text())

    def test_five_independent_functions(self):
        self.assertEqual(len(self.graphs), 5)
        kinds = [{n["class_type"] for n in p.values()} for _, p in self.graphs]
        self.assertNotIn("NFStockingSAMLoader", kinds[0])
        self.assertNotIn("NFStockingRender", kinds[0])
        self.assertIn("NFStockingSAMLoader", kinds[1])
        self.assertNotIn("NFStockingDepth", kinds[1])
        self.assertIn("NFStockingDepth", kinds[2])
        self.assertIn("ParallelVideoComparison", kinds[3])
        self.assertIn("ImageCompositeMasked", kinds[4])

    def test_ui_links_are_typed_and_match_api_links(self):
        for index, (title, prompt) in enumerate(self.graphs, 1):
            with self.subTest(title=title):
                doc = workflow(prompt, self.schemas, index, title)
                lookup = {n["id"]: n for n in doc["nodes"]}
                expected = sum(isinstance(v, list) for p in prompt.values() for v in p["inputs"].values())
                self.assertEqual(len(doc["links"]), expected)
                for lid, source, out_slot, target, in_slot, kind in doc["links"]:
                    source_slot, target_slot = lookup[source]["outputs"][out_slot], lookup[target]["inputs"][in_slot]
                    self.assertEqual(source_slot["type"], kind)
                    self.assertEqual(target_slot["type"], kind)
                    self.assertEqual(target_slot["link"], lid)
                    self.assertIn(lid, source_slot["links"])
                    self.assertEqual(prompt[str(target)]["inputs"][target_slot["name"]], [str(source), out_slot])
                editor = next(n for n in doc["nodes"] if n["type"] == "NFStockingEditor")
                self.assertEqual(json.loads(editor["widgets_values"][0]), self.guides)

    def test_style_comparison_shares_geometry_and_all_other_parameters(self):
        prompt = self.graphs[3][1]
        renderers = [p["inputs"] for p in prompt.values() if p["class_type"] == "NFStockingRender"]
        self.assertEqual({p["style"] for p in renderers}, {"knit", "loops", "lines", "grain", "oily"})
        baseline = {k: v for k, v in renderers[0].items() if k != "style"}
        for p in renderers:
            self.assertEqual({k: v for k, v in p.items() if k != "style"}, baseline)
        self.assertEqual(sum(p["class_type"] == "NFStockingSolve" for p in prompt.values()), 1)

    def test_layer_workflow_uses_opacity_for_composition_and_inverts_png_mask(self):
        prompt = self.graphs[4][1]
        self.assertEqual(prompt["8"]["inputs"]["mask"], ["4", 2])
        self.assertEqual(prompt["8"]["inputs"]["source"], ["4", 1])
        self.assertEqual(prompt["8"]["inputs"]["destination"], ["1", 0])
        self.assertEqual(prompt["5"]["inputs"]["mask"], ["4", 2])
        self.assertEqual(prompt["6"]["inputs"]["alpha"], ["5", 0])


if __name__ == "__main__": unittest.main()
