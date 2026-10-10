"""Recommended examples preserve point selection and batch/composite contracts."""
import importlib.util
import sys
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_stocking_unified_workflows import graphs


class UnifiedWorkflows(unittest.TestCase):
    def test_five_recommended_workflows_preserve_points_and_never_save_untreated_images(self):
        items = graphs("demo.png")
        self.assertEqual(len(items), 5)
        for index, (title, prompt) in enumerate(items):
            main = [n for n in prompt.values() if n["class_type"] == "NFStockingTexture"]
            self.assertTrue(main, title)
            self.assertEqual(prompt["3"]["class_type"], "NFStockingSAMLoader")
            if index == 0:
                self.assertTrue(all("sam" not in n["inputs"] for n in main))
            else:
                self.assertTrue(all(n["inputs"].get("sam") == ["3", 0] for n in main))
            self.assertFalse(any(n["class_type"] == "SaveImage" for n in prompt.values()))

    def test_batch_is_real_image_batch_and_layer_composite_uses_filtered_sources(self):
        items = graphs("demo.png")
        batch = items[2][1]
        self.assertEqual(batch["8"]["class_type"], "ImageBatch")
        self.assertEqual(batch["2"]["inputs"]["images"], ["8", 0])
        self.assertEqual(batch["6"]["inputs"]["images"], ["8", 0])
        composite = items[4][1]["6"]["inputs"]
        self.assertEqual(composite["destination"], ["2", 5])
        self.assertEqual(composite["source"], ["2", 1])
        self.assertEqual(composite["mask"], ["2", 2])


if __name__ == "__main__":
    unittest.main()
