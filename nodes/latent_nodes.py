# 核心预设数据：比例 -> 对应分辨率列表
RATIO_DATA = {
    "9:16 tall": ["1088 x 1920", "864 x 1536", "720 x 1280"],
    "2:3 tall": ["1280 x 1920", "1120 x 1680", "960 x 1440", "832 x 1248"],
    "3:4 tall": ["1440 x 1920", "1200 x 1600", "912 x 1216"],
    "4:5 tall": ["1536 x 1920", "1152 x 1440", "832 x 1040"],
    "1:1 square": ["1680 x 1680", "1440 x 1440", "1040 x 1040"],
    "16:9 wide": ["1920 x 1088", "1536 x 864", "1280 x 720"],
    "3:2 wide": ["1920 x 1280", "1680 x 1120", "1440 x 960", "1248 x 832"],
    "4:3 wide": ["1920 x 1440", "1600 x 1200", "1216 x 912"],
    "5:4 wide": ["1920 x 1536", "1440 x 1152", "1040 x 832"]
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
                "ratio": (list(RATIO_DATA.keys()), {"default": "1:1 square"}),
                "resolution": (all_res, {"default": "1440 x 1440"}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "execute"
    CATEGORY = "eazy-toolbox"

    def execute(self, ratio, resolution):
        try:
            # 格式化解析 "1088 x 1920"
            w_str, h_str = resolution.split(" x ")
            return (int(w_str), int(h_str))
        except:
            # 回退机制，防止因 JS 未加载导致的数据错误
            return (1024, 1024)

NODE_CLASS_MAPPINGS = {"ToolBoxLatentSize": ToolBoxLatentSize}
NODE_DISPLAY_NAME_MAPPINGS = {"ToolBoxLatentSize": "toolbox-latent-size"}