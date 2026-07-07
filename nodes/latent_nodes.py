# 核心预设数据：比例 -> 对应分辨率列表
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

CUSTOM_RATIO = "自定义尺寸"
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
    def INPUT_TYPES(s):
        # 预加载所有选项，JS 会根据 ratio 进行过滤
        all_res = []
        for res_list in RATIO_DATA.values():
            all_res.extend(res_list)
            
        return {
            "required": {
                "ratio": ([*RATIO_DATA.keys(), CUSTOM_RATIO], {"default": "1:1 方图"}),
                "resolution": (all_res, {"default": "1440 x 1440"}),
                "custom_width": ("INT", {"default": 1024, "min": 8, "max": 4096, "step": 8}),
                "custom_height": ("INT", {"default": 1024, "min": 8, "max": 4096, "step": 8}),
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

NODE_CLASS_MAPPINGS = {"ToolBoxLatentSize": ToolBoxLatentSize}
