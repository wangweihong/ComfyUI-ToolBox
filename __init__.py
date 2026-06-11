import os
import importlib
from .node_mappings import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS


# 获取当前插件的根目录名称（例如 ComfyUI-ToolBox）
node_path = os.path.dirname(__file__)
node_import_path = os.path.basename(node_path)



# 必须声明，否则 web/js/zimage_main.js 不会被加载，下拉联动会失效
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]