# 显式导入 latent_nodes 模块
from importlib import import_module

_gaussian_nodes = import_module('.nodes.3dgs', __package__)
gaussian_nodes_mapping = _gaussian_nodes.NODE_CLASS_MAPPINGS
gaussian_display_mapping = _gaussian_nodes.NODE_DISPLAY_NAME_MAPPINGS
# 使用绝对路径导入，避免 RELATIVE_PYTHON_MODULE 属性错误
from .nodes.latent_nodes import NODE_CLASS_MAPPINGS as latent_nodes_mapping
from .nodes.video_compare_node import NODE_CLASS_MAPPINGS as video_compare_nodes_mapping
from .nodes.text_nodes import NODE_CLASS_MAPPINGS as text_nodes_mapping
from .nodes.image_metadata_nodes import NODE_CLASS_MAPPINGS as image_metadata_mapping
from .nodes.prompt_nodes import NODE_CLASS_MAPPINGS as prompt_nodes_mapping
from .nodes import prompt_routes as _prompt_routes
from .nodes.prompt_media_nodes import NODE_CLASS_MAPPINGS as prompt_media_mapping, NODE_DISPLAY_NAME_MAPPINGS as prompt_media_display
from .nodes.skill_nodes import NODE_CLASS_MAPPINGS as skill_nodes_mapping
from .nodes import skill_routes as _skill_routes
from .nodes.moss_prompt_enhancer import NODE_CLASS_MAPPINGS as moss_nodes_mapping
from .nodes.moss_prompt_enhancer import NODE_DISPLAY_NAME_MAPPINGS as moss_display_mapping
from .nodes.degrid import NODE_CLASS_MAPPINGS as degrid_nodes_mapping
from .nodes.degrid import NODE_DISPLAY_NAME_MAPPINGS as degrid_display_mapping
from .nodes.flux2_klein import NODE_CLASS_MAPPINGS as flux2_klein_nodes_mapping
from .nodes.flux2_klein import NODE_DISPLAY_NAME_MAPPINGS as flux2_klein_display_mapping
from .nodes.flashvsr import NODE_CLASS_MAPPINGS as flashvsr_nodes_mapping
from .nodes.flashvsr import NODE_DISPLAY_NAME_MAPPINGS as flashvsr_display_mapping


from .nodes.media_library import NODE_CLASS_MAPPINGS as media_library_mapping, NODE_DISPLAY_NAME_MAPPINGS as media_library_display

from .nodes.skin_color_pipeline import NODE_CLASS_MAPPINGS as skin_color_nodes_mapping
from .nodes.skin_color_pipeline import NODE_DISPLAY_NAME_MAPPINGS as skin_color_display_mapping

from .nodes.dance_mv import NODE_CLASS_MAPPINGS as dance_mv_nodes_mapping
from .nodes.dance_mv import NODE_DISPLAY_NAME_MAPPINGS as dance_mv_display_mapping

NODE_CLASS_MAPPINGS = {
    **media_library_mapping,
    **dance_mv_nodes_mapping,
    **gaussian_nodes_mapping,
    **skin_color_nodes_mapping,
    **latent_nodes_mapping,
    **video_compare_nodes_mapping,
    **text_nodes_mapping,
    **image_metadata_mapping,
    **prompt_nodes_mapping,
    **prompt_media_mapping,
    **skill_nodes_mapping,
    **moss_nodes_mapping,
    **degrid_nodes_mapping,
    **flux2_klein_nodes_mapping,
    **flashvsr_nodes_mapping,
}

# 这里定义节点在 UI 菜单中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    **media_library_display,
    **dance_mv_display_mapping,
    **gaussian_display_mapping,
    **prompt_media_display,
    **moss_display_mapping,
    **skin_color_display_mapping,
    **degrid_display_mapping,
    **flux2_klein_display_mapping,
    **flashvsr_display_mapping,
    # latent size
    "ToolBoxLatentSize": "tb-latent-size",
    # video compare
    "ParallelVideoComparison": "tb-video-comparison",
    # text
    "ToolBoxText": "tb-text",
    "ToolBoxImageMetadataReader": "tb-image-metadata-reader",
    "ToolBoxSubjectConceptReplacer": "tb-subject-concept-replacer",
    # prompt
    "ToolBoxRandomPrompt": "tb-random-prompt",
    "ToolBoxPromptWriter": "tb-prompt-writer",
    "ToolBoxPromptReader": "tb-prompt-reader",
    "ToolBoxPromptsByTag": "tb-prompts-by-tag",
    "ToolBoxSkillReader": "tb-skill-reader",
    "ToolBoxPromptNSFWDetector": "tb-prompt-nsfw-detector",
}
