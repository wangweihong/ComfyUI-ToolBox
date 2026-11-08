"""Explicit prompt -> save/register wiring, without intercepting other savers."""
import json
from pathlib import Path, PurePosixPath

from . import prompt_examples as examples


def safe_prefix(prefix):
    if not isinstance(prefix, str) or not prefix.strip() or Path(prefix).is_absolute() or ".." in Path(prefix).parts or "\\" in prefix or "\0" in prefix:
        raise ValueError("filename_prefix 必须为 output 内的相对前缀")


def ui_paths(ui):
    if hasattr(ui, "as_dict"):
        ui = ui.as_dict()
    found = []
    def visit(value):
        if isinstance(value, dict):
            if "filename" in value:
                if value.get("type") != "output":
                    raise ValueError("只登记正式 output 文件，不接受 temp")
                filename = value["filename"]
                if not isinstance(filename, str) or PurePosixPath(filename).name != filename:
                    raise ValueError("保存结果 filename 无效")
                found.append(str(PurePosixPath(value.get("subfolder", "")) / filename))
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
    visit(ui)
    if not found:
        raise ValueError("保存节点未返回正式文件路径")
    return list(dict.fromkeys(found))


def finish(metadata, paths):
    prompt_id, digest = examples.parse_metadata(metadata)
    relative = [examples.normalize_path(path)[1] for path in paths]
    payload = {"prompt_id": prompt_id, "shasum": digest, "paths": relative, "source": "generated"}
    try:
        from comfy_execution.utils import get_executing_context
        context = get_executing_context()
        if context:
            payload.update(job_id=str(context.prompt_id), node_id=str(context.node_id))
    except ImportError:
        pass
    try:
        for offset in range(0, len(relative), 200):
            examples.register({**payload, "paths": relative[offset:offset+200]})
        payload.update(registration="registered", message=f"已保存并关联 {len(relative)} 个文件")
    except Exception as exc:
        # Saving is irreversible here: keep the files and expose an explicit retry.
        payload.update(registration="failed", message=f"保存成功，关联失败：{exc}")
    return payload


def image_saver():
    import nodes
    return nodes.SaveImage()


class ToolBoxPromptSaveImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "images/unspecified/prompt_examples/ComfyUI"})},
                "optional": {"prompt_metadata": ("STRING", {"forceInput": True})},
                "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "files")
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "eazy-toolbox/prompt"

    def save(self, images, prompt_metadata=None, filename_prefix="images/unspecified/prompt_examples/ComfyUI", prompt=None, extra_pnginfo=None):
        if prompt_metadata is not None:
            examples.validate_source(prompt_metadata)
        safe_prefix(filename_prefix)
        result = image_saver().save_images(images, filename_prefix, prompt, extra_pnginfo)
        paths = ui_paths(result["ui"])
        if prompt_metadata is not None:
            report = finish(prompt_metadata, paths)
        else:
            report = {"paths": paths, "registration": "skipped", "message": f"已保存 {len(paths)} 个文件，未连接 metadata，未建立关联"}
        return {"ui": {**result["ui"], "toolbox_prompt_media": [report]}, "result": (images, json.dumps(report, ensure_ascii=False))}


class ToolBoxPromptRecordMedia:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"prompt_metadata": ("STRING", {"forceInput": True})}, "optional": {
            "files": ("STRING", {"forceInput": True}), "vhs_filenames": ("VHS_FILENAMES",)}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("files",)
    FUNCTION = "record"
    OUTPUT_NODE = True
    CATEGORY = "eazy-toolbox/prompt"

    def record(self, prompt_metadata, files="", vhs_filenames=None):
        examples.validate_source(prompt_metadata)
        if bool(files) == (vhs_filenames is not None):
            raise ValueError("文件列表 JSON 和 VHS_FILENAMES 请选择一个输入")
        if vhs_filenames is not None:
            if not isinstance(vhs_filenames, (tuple, list)) or len(vhs_filenames) != 2 or not isinstance(vhs_filenames[0], bool):
                raise ValueError("Invalid VHS_FILENAMES")
            output, paths = vhs_filenames
            if not output:
                raise ValueError("VHS 请启用 save_output，不登记 temp")
            if not isinstance(paths, (tuple, list)):
                raise ValueError("Invalid VHS file list")
            # VHS appends workflow PNG, silent intermediates, then the final result.
            paths = [paths[-1]] if paths else []
        else:
            data = json.loads(files)
            paths = data.get("paths") if isinstance(data, dict) else data
        if not isinstance(paths, list) or len(paths) > 10000:
            raise ValueError("Invalid saved file list")
        if paths:
            report = finish(prompt_metadata, paths)
        else:
            prompt_id, digest = examples.parse_metadata(prompt_metadata)
            report = {"prompt_id":prompt_id, "shasum":digest, "paths":[], "registration":"pending", "message":"批次尚未产生最终输出，暂不登记"}
        return {"ui": {"toolbox_prompt_media": [report]}, "result": (json.dumps(report, ensure_ascii=False),)}


try:
    from comfy_api.latest import io
    from comfy_extras.nodes_video import SaveVideo as CoreSaveVideo
except ImportError:
    # Importable for unit tests outside ComfyUI; the real runtime uses V3 below.
    class ToolBoxPromptSaveVideo:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"video": ("VIDEO",), "prompt_metadata": ("STRING", {"forceInput":True})}}

        RETURN_TYPES = ("VIDEO", "STRING")
        RETURN_NAMES = ("video", "files")
        FUNCTION = "save"
        CATEGORY = "eazy-toolbox/prompt"
        OUTPUT_NODE = True

        def save(self, **kwargs):
            raise RuntimeError("此节点需要支持标准 SaveVideo 的 ComfyUI，请在 ComfyUI 内运行。")
else:
    class ToolBoxPromptSaveVideo(CoreSaveVideo):
        @classmethod
        def define_schema(cls):
            schema = super().define_schema()
            schema.node_id = "ToolBoxPromptSaveVideo"
            schema.display_name = "tb-prompt-save-video"
            schema.category = "eazy-toolbox/prompt"
            schema.inputs.insert(1, io.String.Input("prompt_metadata", force_input=True))
            schema.outputs.append(io.String.Output("files"))
            for field in schema.inputs:
                if field.id == "filename_prefix":
                    field.default = "videos/unspecified/prompt_examples/ComfyUI"
            return schema

        @classmethod
        def execute(cls, video, prompt_metadata, filename_prefix, format, codec=None):
            examples.validate_source(prompt_metadata)
            safe_prefix(filename_prefix)
            result = super().execute(video, filename_prefix, format, codec)
            native_ui = result.ui.as_dict() if hasattr(result.ui, "as_dict") else result.ui
            report = finish(prompt_metadata, ui_paths(native_ui))
            return io.NodeOutput(video, json.dumps(report, ensure_ascii=False), ui={**native_ui, "toolbox_prompt_media":[report]})


NODE_CLASS_MAPPINGS = {cls.__name__:cls for cls in (ToolBoxPromptSaveImage, ToolBoxPromptSaveVideo, ToolBoxPromptRecordMedia)}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxPromptSaveImage":"tb-prompt-save-image", "ToolBoxPromptSaveVideo":"tb-prompt-save-video", "ToolBoxPromptRecordMedia":"tb-prompt-record-media"}
