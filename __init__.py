import os
import importlib


# 显式导入 latent_nodes 模块
# 使用绝对路径导入，避免 RELATIVE_PYTHON_MODULE 属性错误
from .nodes.cinematic_nodes import NODE_CLASS_MAPPINGS as cinematic_nodes_mapping
from .nodes.latent_nodes import NODE_CLASS_MAPPINGS as latent_nodes_mapping
# 获取当前插件的根目录名称（例如 ComfyUI-ToolBox）
node_path = os.path.dirname(__file__)
node_import_path = os.path.basename(node_path)

NODE_CLASS_MAPPINGS = {
    **latent_nodes_mapping,
    **cinematic_nodes_mapping,
    # **util_nodes,
}

# 这里定义节点在 UI 菜单中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    "ToolBoxLatentSize": "toolbox-latent-size",

    "CinematicPromptNode": "toolbox-prompt-builder",
    "CinematicLoaderNode": "toolbox-prompt-loader",

    "CinematicPromptNodeCN": "toolbox-prompt-builder-cn",
    "CinematicLoaderNodeCN": "toolbox-prompt-loader-cn"
}

# 必须声明，否则 web/js/zimage_main.js 不会被加载，下拉联动会失效
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]