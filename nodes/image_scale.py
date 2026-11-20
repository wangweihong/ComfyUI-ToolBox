"""Native image/mask resizing with dimension metadata for the scale diagram."""

from comfy_api.latest import io
from comfy_extras.nodes_post_processing import ResizeImageMaskNode, scale_to_multiple_cover


def dimensions(value):
    return [int(value.shape[-2]), int(value.shape[-3])] if value.ndim == 4 else [int(value.shape[-1]), int(value.shape[-2])]


class ToolBoxImageScale(ResizeImageMaskNode):
    @classmethod
    def define_schema(cls):
        schema = super().define_schema()
        schema.node_id = "ToolBoxImageScale"
        schema.display_name = "tb-image-scale"
        schema.category = "eazy-toolbox"
        schema.description = "缩放图像或掩码，并用同一比例的框体显示输入与输出尺寸。运行一次后调参可即时预估，执行后显示实际结果。"
        schema.is_output_node = True
        schema.search_aliases = ["scale", "resize", "缩放", "尺寸对比"]
        schema.inputs.append(io.Int.Input(
            "multiple_of", default=1, min=1, max=16384, step=1,
            tooltip="最终宽高对齐倍数。1 不额外调整；32 等效于缩放后再接 scale to multiple=32，可能少量居中裁剪。小于倍数的边保持原生节点行为，不强制对齐。",
        ))
        schema.outputs.extend([io.Int.Output("width"), io.Int.Output("height"), io.String.Output("info")])
        return schema

    @classmethod
    def execute(cls, input, scale_method, resize_type, multiple_of=1):
        resized = super().execute(input, scale_method, resize_type)[0]
        output = scale_to_multiple_cover(resized, multiple_of, scale_method)
        source_size, resized_size, output_size = dimensions(input), dimensions(resized), dimensions(output)
        width, height = output_size
        source_width, source_height = source_size
        info = (
            f"输入 {source_width}×{source_height} px → 输出 {width}×{height} px\n"
            f"宽 ×{width / source_width:.6g}；高 ×{height / source_height:.6g}；"
            f"像素量 ×{width * height / (source_width * source_height):.6g}\n"
            f"输出约 {width * height / 10000:.1f} 万像素（{width * height / 1000000:.2f} MP）"
        )
        if multiple_of > 1:
            info += f"\n最终对齐 {multiple_of}：{resized_size[0]}×{resized_size[1]} → {width}×{height}"
            if width % multiple_of or height % multiple_of:
                info += "（尺寸小于对齐倍数，按原生规则保留，未对齐）"
        parameters = {key: value for key, value in resize_type.items() if key != "match"}
        report = {
            "source": source_size, "resized": resized_size, "output": output_size,
            "match": dimensions(resize_type["match"]) if "match" in resize_type else None,
            "parameters": parameters, "scale_method": scale_method, "multiple_of": multiple_of,
        }
        return io.NodeOutput(output, width, height, info, ui={"toolbox_scale": [report], "text": [info]})


NODE_CLASS_MAPPINGS = {"ToolBoxImageScale": ToolBoxImageScale}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxImageScale": "tb-image-scale"}
