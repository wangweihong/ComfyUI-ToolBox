# 显式导入 latent_nodes 模块
# 使用绝对路径导入，避免 RELATIVE_PYTHON_MODULE 属性错误
from .nodes.cinematic_nodes import NODE_CLASS_MAPPINGS as cinematic_nodes_mapping
from .nodes.latent_nodes import NODE_CLASS_MAPPINGS as latent_nodes_mapping
from .nodes.video_compare_node import NODE_CLASS_MAPPINGS as video_compare_nodes_mapping
from .nodes.text_nodes import NODE_CLASS_MAPPINGS as text_nodes_mapping
from .nodes.prompt_nodes import NODE_CLASS_MAPPINGS as prompt_nodes_mapping
from .nodes.stocking_texture.nodes import NODE_CLASS_MAPPINGS as stocking_nodes_mapping
from .nodes.stocking_texture.nodes import NODE_DISPLAY_NAME_MAPPINGS as stocking_display_mapping
from .nodes.stocking_texture import routes as _stocking_routes


NODE_CLASS_MAPPINGS = {
    **latent_nodes_mapping,
    **cinematic_nodes_mapping,
    **video_compare_nodes_mapping,
    **text_nodes_mapping,
    **prompt_nodes_mapping,
    **stocking_nodes_mapping,
}

# 这里定义节点在 UI 菜单中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    **stocking_display_mapping,
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
    # prompt
    "ToolBoxRandomPrompt": "tb-random-prompt",
    "ToolBoxPromptWriter": "tb-prompt-writer",
    "ToolBoxPromptNSFWDetector": "tb-prompt-nsfw-detector",
}
