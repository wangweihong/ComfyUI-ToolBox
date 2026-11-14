import math
import types
import unittest

from nodes.latent_nodes import (
    CUSTOM_RATIO,
    KEEP_RATIO,
    LEGACY_RATIO_NAMES,
    LONG_EDGE_MODE,
    MAX_DIMENSION,
    NEAREST_RATIO,
    NODE_CLASS_MAPPINGS,
    RATIO_DATA,
    ToolBoxLatentSize,
    ToolBoxLatentSizeAuto,
    nearest_ratio,
    ratio_pair,
)


class LatentSizeTest(unittest.TestCase):
    def test_expanded_presets_remain_aligned_and_available_to_frontend(self):
        required = ToolBoxLatentSize.INPUT_TYPES()["required"]
        self.assertEqual(required["resolution"][1]["toolbox_ratio_data"], RATIO_DATA)
        for name, resolutions in RATIO_DATA.items():
            dimensions = [tuple(map(int, value.split(" x "))) for value in resolutions]
            self.assertEqual(len(dimensions), len(set(dimensions)))
            self.assertTrue(all(w % 8 == h % 8 == 0 for w, h in dimensions), name)
            self.assertTrue(any(max(pair) >= 7680 for pair in dimensions), name)
            self.assertTrue(all(max(pair) <= 8192 for pair in dimensions), name)
            self.assertTrue(all(value in required["resolution"][0] for value in resolutions))
        for name in ("21:9 横屏", "32:9 横屏", "9:21 竖屏", "9:32 竖屏"):
            x, y = ratio_pair(name)
            for resolution in RATIO_DATA[name]:
                w, h = map(int, resolution.split(" x "))
                self.assertEqual(w * y, h * x)
        self.assertIn("7680 x 4320", RATIO_DATA["16:9 横屏"])
        self.assertIn("8192 x 4608", RATIO_DATA["16:9 横屏"])

    def test_existing_resolutions_legacy_names_and_custom_sizes(self):
        node = ToolBoxLatentSize()
        for legacy, name in LEGACY_RATIO_NAMES.items():
            resolution = RATIO_DATA[name][0]
            expected = tuple(map(int, resolution.split(" x ")))
            self.assertEqual(node.execute(legacy, resolution), expected)
            self.assertEqual(node.execute(name, resolution), expected)
        self.assertEqual(node.execute(CUSTOM_RATIO, "1440 x 1440", 16384, 8192), (16384, 8192))
        self.assertEqual(node.execute("1:1 方图", "invalid"), (1024, 1024))

    def test_integer_scaling_keeps_exact_original_ratio_for_arbitrary_images(self):
        node = ToolBoxLatentSizeAuto()
        for width, height in ((1001, 777), (1024, 769), (777, 1001), (1, 4096), (1920, 1080)):
            with self.subTest(width=width, height=height):
                result = node.execute(width, height, scale_by=4)
                w, h, matched, info = result["result"]
                self.assertEqual((w, h), (width * 4, height * 4))
                self.assertEqual(w * height, h * width)
                self.assertEqual(matched, nearest_ratio(width, height))
                self.assertEqual(result["ui"]["text"], [info])
                self.assertIn("实际宽度 ×4，高度 ×4", info)
                self.assertIn(f"约 {w * h / 10000:.1f} 万像素（{w * h / 1000000:.2f} MP）", info)

    def test_image_dimensions_override_manual_inputs_without_allocating_or_modifying_image(self):
        image = types.SimpleNamespace(shape=(2, 777, 1001, 3))
        result = ToolBoxLatentSizeAuto().execute(0, 0, image=image, scale_by=4)["result"]
        self.assertEqual(result[:2], (4004, 3108))
        self.assertEqual(image.shape, (2, 777, 1001, 3))

    def test_nearest_matching_is_symmetric_and_recognizes_wide_presets(self):
        for width, height, expected in (
            (1919, 1080, "16:9 横屏"), (1080, 1919, "9:16 竖屏"),
            (2500, 1080, "21:9 横屏"), (1080, 2500, "9:21 竖屏"),
            (3800, 1080, "32:9 横屏"), (1080, 3800, "9:32 竖屏"),
            (1000, 1000, "1:1 方图"),
        ):
            self.assertEqual(nearest_ratio(width, height), expected)
        result = ToolBoxLatentSizeAuto().execute(1919, 1080, ratio=NEAREST_RATIO, scale_by=4)["result"]
        self.assertEqual(result[:3], (7680, 4320, "16:9 横屏"))

    def test_manual_ratio_override_retains_target_long_edge(self):
        result = ToolBoxLatentSizeAuto().execute(1000, 500, ratio="1:1 方图", scale_by=4)["result"]
        self.assertEqual(result[:2], (4000, 4000))
        self.assertIn("使用：1:1 方图", result[3])

    def test_long_edge_and_fractional_scaling_use_nearest_exact_ratio(self):
        node = ToolBoxLatentSizeAuto()
        self.assertEqual(node.execute(1920, 1080, size_mode=LONG_EDGE_MODE, long_edge=3840)["result"][:2], (3840, 2160))
        self.assertEqual(node.execute(1920, 1080, scale_by=1.5)["result"][:2], (2880, 1620))
        # Coprime source dimensions admit only integer multiples when ratio is exact.
        result = node.execute(1001, 1000, scale_by=1.4)["result"]
        self.assertEqual(result[:2], (1001, 1000))
        self.assertIn("最近可实现尺寸", result[3])
        result = node.execute(1001, 1000, size_mode=LONG_EDGE_MODE, long_edge=1800)["result"]
        self.assertEqual(result[:2], (2002, 2000))

    def test_alignment_preserves_ratio_and_uses_closest_feasible_dimensions(self):
        node = ToolBoxLatentSizeAuto()
        for width, height in ((1001, 777), (1920, 1080), (123, 456)):
            divisor = math.gcd(width, height)
            for alignment in (1, 8, 16, 32):
                w, h = node.execute(width, height, scale_by=4, alignment=str(alignment))["result"][:2]
                self.assertEqual(w * height, h * width)
                self.assertEqual((w % alignment, h % alignment), (0, 0))
                unit_w, unit_h = width // divisor, height // divisor
                step = math.lcm(alignment // math.gcd(unit_w, alignment), alignment // math.gcd(unit_h, alignment))
                stride = max(unit_w, unit_h) * step
                target = max(width, height) * 4
                error = abs(max(w, h) - target)
                for neighbor in (max(w, h) - stride, max(w, h) + stride):
                    if neighbor > 0:
                        self.assertLessEqual(error, abs(neighbor - target))
        self.assertEqual(node.execute(1920, 1080, scale_by=4, alignment="8")["result"][:2], (7680, 4320))

    def test_size_limit_is_checked_instead_of_clamping_and_distorting(self):
        node = ToolBoxLatentSizeAuto()
        self.assertEqual(node.execute(8192, 4096, scale_by=4)["result"][:2], (MAX_DIMENSION, 16384))
        with self.assertRaisesRegex(ValueError, "超过"):
            node.execute(8192, 8192, scale_by=5)
        with self.assertRaisesRegex(ValueError, "超过"):
            node.execute(1001, 1000, alignment="64")

    def test_invalid_inputs_fail_with_actionable_errors(self):
        node = ToolBoxLatentSizeAuto()
        for overrides in (
            {"source_width": 0}, {"source_height": -1}, {"source_width": 1024.5},
            {"scale_by": float("nan")}, {"scale_by": float("inf")}, {"scale_by": 0},
            {"scale_by": 65}, {"scale_by": True}, {"ratio": "unknown"},
            {"size_mode": "unknown"}, {"alignment": "3"},
            {"size_mode": LONG_EDGE_MODE, "long_edge": 0},
            {"image": types.SimpleNamespace(shape=(10, 20, 3))},
            {"image": types.SimpleNamespace(shape=(0, 10, 20, 3))},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                node.execute(**{"source_width": 1024, "source_height": 768, **overrides})

    def test_auto_node_is_registered_and_defaults_to_original_ratio(self):
        self.assertIs(NODE_CLASS_MAPPINGS["ToolBoxLatentSizeAuto"], ToolBoxLatentSizeAuto)
        inputs = ToolBoxLatentSizeAuto.INPUT_TYPES()
        self.assertEqual(inputs["required"]["ratio"][1]["default"], KEEP_RATIO)
        self.assertEqual(inputs["required"]["alignment"][1]["default"], "1")
        self.assertEqual(inputs["optional"]["image"][0], "IMAGE")


if __name__ == "__main__":
    unittest.main()
