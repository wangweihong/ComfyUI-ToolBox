# 显式导入 latent_nodes 模块
from importlib import import_module

_gaussian_nodes = import_module('.nodes.3dgs', __package__)
gaussian_nodes_mapping = _gaussian_nodes.NODE_CLASS_MAPPINGS
gaussian_display_mapping = _gaussian_nodes.NODE_DISPLAY_NAME_MAPPINGS
# 使用绝对路径导入，避免 RELATIVE_PYTHON_MODULE 属性错误
from .nodes.cinematic_nodes import NODE_CLASS_MAPPINGS as cinematic_nodes_mapping
from .nodes.latent_nodes import NODE_CLASS_MAPPINGS as latent_nodes_mapping
from .nodes.video_compare_node import NODE_CLASS_MAPPINGS as video_compare_nodes_mapping
from .nodes.text_nodes import NODE_CLASS_MAPPINGS as text_nodes_mapping
from .nodes.prompt_nodes import NODE_CLASS_MAPPINGS as prompt_nodes_mapping
from .nodes.moss_prompt_enhancer import NODE_CLASS_MAPPINGS as moss_nodes_mapping
from .nodes.moss_prompt_enhancer import NODE_DISPLAY_NAME_MAPPINGS as moss_display_mapping
from .nodes.degrid import NODE_CLASS_MAPPINGS as degrid_nodes_mapping
from .nodes.degrid import NODE_DISPLAY_NAME_MAPPINGS as degrid_display_mapping
from .nodes.flux2_klein import NODE_CLASS_MAPPINGS as flux2_klein_nodes_mapping
from .nodes.flux2_klein import NODE_DISPLAY_NAME_MAPPINGS as flux2_klein_display_mapping
from .nodes.flashvsr import NODE_CLASS_MAPPINGS as flashvsr_nodes_mapping
from .nodes.flashvsr import NODE_DISPLAY_NAME_MAPPINGS as flashvsr_display_mapping
from .nodes.stocking_texture.nodes import NODE_CLASS_MAPPINGS as stocking_nodes_mapping
from .nodes.stocking_texture.nodes import NODE_DISPLAY_NAME_MAPPINGS as stocking_display_mapping
from .nodes.stocking_texture import routes as _stocking_routes


from .nodes.skin_color_pipeline import NODE_CLASS_MAPPINGS as skin_color_nodes_mapping
from .nodes.skin_color_pipeline import NODE_DISPLAY_NAME_MAPPINGS as skin_color_display_mapping

from .nodes.dance_mv import NODE_CLASS_MAPPINGS as dance_mv_nodes_mapping
from .nodes.dance_mv import NODE_DISPLAY_NAME_MAPPINGS as dance_mv_display_mapping

NODE_CLASS_MAPPINGS = {
    **dance_mv_nodes_mapping,
    **gaussian_nodes_mapping,
    **skin_color_nodes_mapping,
    **latent_nodes_mapping,
    **cinematic_nodes_mapping,
    **video_compare_nodes_mapping,
    **text_nodes_mapping,
    **prompt_nodes_mapping,
    **moss_nodes_mapping,
    **degrid_nodes_mapping,
    **stocking_nodes_mapping,
    **flux2_klein_nodes_mapping,
    **flashvsr_nodes_mapping,
}

# 这里定义节点在 UI 菜单中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    **dance_mv_display_mapping,
    **gaussian_display_mapping,
    **moss_display_mapping,
    **skin_color_display_mapping,
    **degrid_display_mapping,
    **stocking_display_mapping,
    **flux2_klein_display_mapping,
    **flashvsr_display_mapping,
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
