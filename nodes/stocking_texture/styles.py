"""The same style registry is read by Python, browser UI and example builders."""
import json
from pathlib import Path

REGISTRY = json.loads((Path(__file__).parents[2] / "web/js/stocking_styles.json").read_text())
STYLES = tuple(item["id"] for item in REGISTRY)
PATTERNS = {item["id"]: item for item in REGISTRY if item["period"]}


def base_style(style):
    if style in PATTERNS:
        return "knit"
    if style == "p_oily":
        return "oily"
    if style not in STYLES:
        raise ValueError(f"未知样式：{style}")
    return style
