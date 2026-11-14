import math


MAX_DIMENSION = 32768

# 保留已有预设及顺序，避免改变已保存工作流的分辨率。
RATIO_DATA = {
    "9:16 竖屏": ["1088 x 1920", "864 x 1536", "720 x 1280", "1296 x 2304", "1440 x 2560", "1728 x 3072", "2016 x 3584", "2304 x 4096"],
    "2:3 竖屏": ["1280 x 1920", "1120 x 1680", "960 x 1440", "832 x 1248", "1536 x 2304", "1704 x 2560", "2048 x 3072", "2392 x 3584", "2728 x 4096"],
    "3:4 竖屏": ["1440 x 1920", "1200 x 1600", "912 x 1216", "1728 x 2304", "1920 x 2560", "2304 x 3072", "2688 x 3584", "3072 x 4096"],
    "4:5 竖屏": ["1536 x 1920", "1152 x 1440", "832 x 1040", "1840 x 2304", "2048 x 2560", "2456 x 3072", "2864 x 3584", "3280 x 4096"],
    "1:1 方图": ["1680 x 1680", "1440 x 1440", "1040 x 1040", "2304 x 2304", "2560 x 2560", "3072 x 3072", "3584 x 3584", "4096 x 4096"],
    "16:9 横屏": ["1920 x 1088", "1536 x 864", "1280 x 720", "2304 x 1296", "2560 x 1440", "3072 x 1728", "3584 x 2016", "4096 x 2304"],
    "3:2 横屏": ["1920 x 1280", "1680 x 1120", "1440 x 960", "1248 x 832", "2304 x 1536", "2560 x 1704", "3072 x 2048", "3584 x 2392", "4096 x 2728"],
    "4:3 横屏": ["1920 x 1440", "1600 x 1200", "1216 x 912", "2304 x 1728", "2560 x 1920", "3072 x 2304", "3584 x 2688", "4096 x 3072"],
    "5:4 横屏": ["1920 x 1536", "1440 x 1152", "1040 x 832", "2304 x 1840", "2560 x 2048", "3072 x 2456", "3584 x 2864", "4096 x 3280"],
}


def ratio_pair(name):
    width, height = map(int, name.split()[0].split(":"))
    divisor = math.gcd(width, height)
    return width // divisor, height // divisor


def proportional_size(width, height, long_edge, alignment=1):
    """Round one common multiplier, never the width and height separately."""
    divisor = math.gcd(width, height)
    unit_width, unit_height = width // divisor, height // divisor
    step = math.lcm(
        alignment // math.gcd(unit_width, alignment),
        alignment // math.gcd(unit_height, alignment),
    )
    unit_long = max(unit_width, unit_height) * step
    count = max(1, math.floor(long_edge / unit_long + 0.5))
    return unit_width * step * count, unit_height * step * count


def preset_resolution(name, long_edge):
    width, height = ratio_pair(name)
    multiplier = max(1, long_edge // (max(width, height) * 8)) * 8
    return f"{width * multiplier} x {height * multiplier}"


for _ratio in ("9:21 竖屏", "9:32 竖屏", "21:9 横屏", "32:9 横屏"):
    RATIO_DATA[_ratio] = [
        preset_resolution(_ratio, edge)
        for edge in (1920, 1536, 1280, 2304, 2560, 3072, 3584, 4096)
    ]

for _ratio, _resolutions in RATIO_DATA.items():
    for _edge in (5120, 6144, 7680, 8192):
        _resolution = preset_resolution(_ratio, _edge)
        if _resolution not in _resolutions:
            _resolutions.append(_resolution)

CUSTOM_RATIO = "自定义尺寸"
KEEP_RATIO = "保持原图比例"
NEAREST_RATIO = "自动匹配最近预设"
SCALE_MODE = "按倍数缩放"
LONG_EDGE_MODE = "指定长边"
LEGACY_RATIO_NAMES = {
    "9:16 tall": "9:16 竖屏",
    "2:3 tall": "2:3 竖屏",
    "3:4 tall": "3:4 竖屏",
    "4:5 tall": "4:5 竖屏",
    "1:1 square": "1:1 方图",
    "16:9 wide": "16:9 横屏",
    "3:2 wide": "3:2 横屏",
    "4:3 wide": "4:3 横屏",
    "5:4 wide": "5:4 横屏",
}


class ToolBoxLatentSize:
    @classmethod
    def INPUT_TYPES(cls):
        # 预加载所有选项，JS 会根据 ratio 进行过滤
        all_res = []
        for res_list in RATIO_DATA.values():
            all_res.extend(res_list)

        return {
            "required": {
                "ratio": ([*RATIO_DATA.keys(), CUSTOM_RATIO], {"default": "1:1 方图"}),
                "resolution": (all_res, {"default": "1440 x 1440", "toolbox_ratio_data": RATIO_DATA}),
                "custom_width": ("INT", {"default": 1024, "min": 8, "max": MAX_DIMENSION, "step": 8}),
                "custom_height": ("INT", {"default": 1024, "min": 8, "max": MAX_DIMENSION, "step": 8}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "execute"
    CATEGORY = "eazy-toolbox"

    def execute(self, ratio, resolution, custom_width=1024, custom_height=1024):
        if ratio == CUSTOM_RATIO:
            return (int(custom_width), int(custom_height))

        ratio = LEGACY_RATIO_NAMES.get(ratio, ratio)

        try:
            # 格式化解析 "1088 x 1920"
            w_str, h_str = resolution.split(" x ")
            return (int(w_str), int(h_str))
        except:
            # 回退机制，防止因 JS 未加载导致的数据错误
            return (1024, 1024)


def positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_DIMENSION:
        raise ValueError(f"{name} 必须是 1–{MAX_DIMENSION} 的整数。")
    return value


def nearest_ratio(width, height):
    source_ratio = width / height

    def distance(name):
        ratio_width, ratio_height = ratio_pair(name)
        # Log distance treats reciprocal portrait/landscape errors equally.
        return abs(math.log(source_ratio / (ratio_width / ratio_height)))

    return min(RATIO_DATA, key=distance)


class ToolBoxLatentSizeAuto:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_width": ("INT", {"default": 1024, "min": 1, "max": MAX_DIMENSION,
                                         "tooltip": "未连接 image 时使用，可连接其他节点的宽度输出。"}),
                "source_height": ("INT", {"default": 1024, "min": 1, "max": MAX_DIMENSION,
                                          "tooltip": "未连接 image 时使用，可连接其他节点的高度输出。"}),
                "ratio": ([KEEP_RATIO, NEAREST_RATIO, *RATIO_DATA], {
                    "default": KEEP_RATIO,
                    "tooltip": "默认严格保持原图比例；自动匹配或手动选择预设会改变比例。无论哪种模式都会报告最近预设。",
                }),
                "size_mode": ([SCALE_MODE, LONG_EDGE_MODE], {"default": SCALE_MODE}),
                "scale_by": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 64.0, "step": 0.01,
                                       "tooltip": "宽、高各自的缩放倍数：4 表示宽高各乘 4，面积乘 16。仅按倍数缩放时生效。"}),
                "long_edge": ("INT", {"default": 2048, "min": 1, "max": MAX_DIMENSION,
                                       "tooltip": "指定长边模式的目标像素值；按比例和对齐要求取最近可实现尺寸。"}),
                "alignment": (["1", "8", "16", "32", "64"], {
                    "default": "1",
                    "tooltip": "1 为整数像素。其他值要求宽高同时对齐，并严格保持所选比例；特殊原图比例可能使实际尺寸明显偏离目标，运行后查看结果。",
                }),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "连接后自动读取图像宽高，优先于 source_width/source_height；仅计算尺寸，不缩放图片。"}),
            },
        }

    RETURN_TYPES = ("INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("width", "height", "matched_ratio", "info")
    FUNCTION = "execute"
    CATEGORY = "eazy-toolbox"
    DESCRIPTION = "识别图像比例、匹配最近预设并计算缩放尺寸。默认严格保持原图比例，仅输出尺寸，不分配 latent 或缩放图像。"

    def execute(self, source_width, source_height, ratio=KEEP_RATIO, size_mode=SCALE_MODE,
                scale_by=1.0, long_edge=2048, alignment="1", image=None):
        if image is not None:
            shape = getattr(image, "shape", ())
            if len(shape) != 4 or any(int(value) <= 0 for value in shape):
                raise ValueError("image 必须是非空的 ComfyUI IMAGE（批次、高、宽、通道）。")
            source_width, source_height = int(shape[2]), int(shape[1])
        width = positive_integer(source_width, "source_width")
        height = positive_integer(source_height, "source_height")
        if alignment not in ("1", "8", "16", "32", "64"):
            raise ValueError("alignment 必须为 1、8、16、32 或 64。")
        matched = nearest_ratio(width, height)
        if ratio == KEEP_RATIO:
            ratio_width, ratio_height = width, height
        elif ratio == NEAREST_RATIO or ratio in RATIO_DATA:
            ratio_width, ratio_height = ratio_pair(matched if ratio == NEAREST_RATIO else ratio)
        else:
            raise ValueError("请选择有效的比例模式或预设比例。")

        if size_mode == SCALE_MODE:
            if (isinstance(scale_by, bool) or not isinstance(scale_by, (int, float))
                    or not math.isfinite(scale_by) or not 0.01 <= scale_by <= 64):
                raise ValueError("scale_by 必须是 0.01–64 的有限数值。")
            target_long = max(width, height) * scale_by
        elif size_mode == LONG_EDGE_MODE:
            target_long = positive_integer(long_edge, "long_edge")
        else:
            raise ValueError("请选择有效的尺寸调整模式。")
        result_width, result_height = proportional_size(ratio_width, ratio_height, target_long, int(alignment))
        if max(result_width, result_height) > MAX_DIMENSION:
            raise ValueError(f"按所选比例及对齐要求得到 {result_width}×{result_height}，超过 {MAX_DIMENSION}；请减小目标尺寸或对齐值。")

        divisor = math.gcd(width, height)
        output_divisor = math.gcd(result_width, result_height)
        selected = KEEP_RATIO if ratio == KEEP_RATIO else (matched if ratio == NEAREST_RATIO else ratio)
        info = (
            f"原图 {width}×{height}（{width // divisor}:{height // divisor}）\n"
            f"最近预设：{matched}；使用：{selected}\n"
            f"目标长边 {target_long:g} px；输出 {result_width}×{result_height}"
            f"（{result_width // output_divisor}:{result_height // output_divisor}，{alignment} 像素对齐）\n"
            f"约 {result_width * result_height / 10000:.1f} 万像素"
            f"（{result_width * result_height / 1000000:.2f} MP）\n"
            f"实际宽度 ×{result_width / width:.6g}，高度 ×{result_height / height:.6g}"
        )
        if max(result_width, result_height) != target_long:
            info += "\n为严格保持比例和像素对齐，已取最近可实现尺寸。"
        return {"ui": {"text": [info]}, "result": (result_width, result_height, matched, info)}


NODE_CLASS_MAPPINGS = {
    "ToolBoxLatentSize": ToolBoxLatentSize,
    "ToolBoxLatentSizeAuto": ToolBoxLatentSizeAuto,
}
