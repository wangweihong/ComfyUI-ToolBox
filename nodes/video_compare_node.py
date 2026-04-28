import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

class ParallelVideoComparison:
    @classmethod
    def INPUT_TYPES(s):
        # 预设 6 个槽位，不连线则不处理
        optional_inputs = {}
        for i in range(1, 7):
            optional_inputs[f"image{i}"] = ("IMAGE",)
            optional_inputs[f"name{i}"] = ("STRING", {"default": f"Video {i}"})
            
        return {
            "required": {},
            "optional": optional_inputs
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "combine_videos"
    CATEGORY = "Video Helpers"

    def combine_videos(self, **kwargs):
        active_data = []

        # 1. 自动检测连线：过滤出所有连入了 image 信号的槽位
        for i in range(1, 7):
            img_key = f"image{i}"
            if img_key in kwargs and kwargs[img_key] is not None:
                active_data.append({
                    "tensor": kwargs[img_key],
                    "name": kwargs.get(f"name{i}", "")
                })

        if not active_data:
            # 防错处理：若无输入则返回一个黑色空帧
            return (torch.zeros((1, 512, 512, 3)),)

        # 2. 确定对齐基准（以第一路输入的宽高和帧数为准）
        base_tensor = active_data[0]["tensor"]
        max_batch = min(d["tensor"].shape[0] for d in active_data)
        target_h = base_tensor.shape[1]
        target_w = base_tensor.shape[2]

        # 3. 动态字体与布局计算
        # 字体大小设为视频高度的 10%，保证在预览图中清晰可见
        font_size = max(32, target_h // 10)
        # 底部留白区高度设为字体的 1.8 倍
        padding_height = int(font_size * 1.8) 

        processed_batches = []
        font = self.get_font(font_size)
        
        # 4. 逐帧合成
        for b in range(max_batch):
            row_frames = []
            for item in active_data:
                # 获取当前帧 [H, W, C]
                frame = item["tensor"][b]
                frame_np = (frame.cpu().numpy() * 255).astype(np.uint8)
                pil_img = Image.fromarray(frame_np)
                
                # 强制缩放至基准分辨率，确保拼接整齐
                if pil_img.height != target_h or pil_img.width != target_w:
                    pil_img = pil_img.resize((target_w, target_h), Image.LANCZOS)

                # 创建带底栏的画布
                canvas_h = target_h + padding_height
                # 使用接近纯黑的背景 (15, 15, 15)
                canvas = Image.new("RGB", (target_w, canvas_h), (15, 15, 15))
                canvas.paste(pil_img, (0, 0))
                
                draw = ImageDraw.Draw(canvas)
                
                # 计算文字居中位置
                text = item["name"]
                if hasattr(draw, 'textlength'):
                    text_w = draw.textlength(text, font=font)
                else:
                    # 兼容旧版本 Pillow
                    text_w = font.getsize(text)[0]
                
                # X: 水平居中 | Y: 底部留白区域垂直居中
                text_x = (target_w - text_w) // 2
                text_y = target_h + (padding_height - font_size) // 2 - (font_size // 10)
                
                # 渲染文字
                draw.text((text_x, text_y), text, fill=(255, 255, 255), font=font)
                
                # 转回 tensor 格式 [0.0, 1.0]
                row_frames.append(torch.from_numpy(np.array(canvas).astype(np.float32) / 255.0))
            
            # 将所有视频帧在宽度方向（dim=1）拼接
            combined_frame = torch.cat(row_frames, dim=1) 
            processed_batches.append(combined_frame)

        # 5. 重新打包成 [B, H, W, C]
        result = torch.stack(processed_batches, dim=0)
        return (result,)

    def get_font(self, size):
        """ 智能获取系统内可用的粗体中文字体 """
        font_paths = [
            # Windows: 微软雅黑粗体 / Arial Bold
            "C:\\Windows\\Fonts\\msyhbd.ttc", 
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\simhei.ttf",
            # Linux: 文泉驿微米黑 / 常用粗体
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except:
                    continue
        return ImageFont.load_default()
    
NODE_CLASS_MAPPINGS = {
    "ParallelVideoComparison": ParallelVideoComparison
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ParallelVideoComparison": "🎬 Parallel Video Comparison "
}