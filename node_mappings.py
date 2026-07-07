# 显式导入 latent_nodes 模块
# 使用绝对路径导入，避免 RELATIVE_PYTHON_MODULE 属性错误
from .nodes.cinematic_nodes import NODE_CLASS_MAPPINGS as cinematic_nodes_mapping
from .nodes.latent_nodes import NODE_CLASS_MAPPINGS as latent_nodes_mapping
from .nodes.video_compare_node import NODE_CLASS_MAPPINGS as video_compare_nodes_mapping
from .nodes.text_nodes import NODE_CLASS_MAPPINGS as text_nodes_mapping


NODE_CLASS_MAPPINGS = {
    **latent_nodes_mapping,
    **cinematic_nodes_mapping,
    **video_compare_nodes_mapping,
    **text_nodes_mapping,
}

# 这里定义节点在 UI 菜单中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    # latent size
    "ToolBoxLatentSize": "tb-latent-size",
    # cinematic prompt
    "CinematicPromptNode": "tb-prompt-builder",
    "CinematicLoaderNode": "tb-prompt-loader",
    "CinematicPromptNodeCN": "tb-prompt-builder-cn",
    "CinematicLoaderNodeCN": "tb-prompt-loader-cn",
    # video compare
    "ParallelVideoComparison": "tb-video-comparison",
    # text
    "ToolBoxText": "tb-text",
    "ToolBoxSubjectConceptReplacer": "tb-subject-concept-replacer",
}
