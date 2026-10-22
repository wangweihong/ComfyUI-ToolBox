# MOSS 提示词增强示例

先安装ToolBox及兼容的CUDA llama-cpp-python，准备GGUF模型；增强后生图还需MOSS主模型、专用文本编码器、VAE及Turbo LoRA。模型不随项目分发，不会自动下载。

| 工作流 | 用途 |
|---|---|
| [01 仅增强提示词](01_MOSS_仅增强提示词_布局JSON预览.json) | 只增强、校验、显示并保存文字 |
| [02 布局增强生图](02_MOSS_布局增强_Turbo8步_完整生图.json) | 三物体布局，1024×1024 |
| [03 Caption增强生图](03_MOSS_Caption增强_Turbo8步_完整生图.json) | 自然语言增强，1024×1024 |
| [04 中文海报](04_MOSS_中文海报布局增强_Turbo8步.json) | 中文文字，1024×1536 |
| [05 海滩人物与狗](05_MOSS_海滩人物与狗_布局增强_Turbo8步.json) | 人物、动物和远景，1536×1024 |
| [06 参考图中文分块反推](06_参考图_llama-cpp中文分块反推_MOSS_Turbo8步.json) | 上传图片 → llama-cpp视觉反推 → 分块中文提示词 → MOSS；自动跟随比例 |

同名API图位于api目录。示例默认GGUF为Gemma4-12B Q4_K_M，使用时应在增强器中选择自己已安装的模型。生图示例的本地文件名为 `moss/moss_image_sft_bf16.safetensors`、`moss/qwen3.5_9b_int8_convrot.safetensors`、`moss/flux2-vae.safetensors` 和 `moss/moss_sft_8step_dmd_2600.safetensors`；实际安装文件名不同时需在加载器中修改。

打开普通JSON，在增强器输入prompt和尺寸，RESPONSE连接文本编码器，WIDTH/HEIGHT连接latent。示例采用8步CFG1、Euler/sgm_uniform、Shift5，01–05固定种子20261020，06为20261021；相同输入可能复用ComfyUI缓存。输出图片及文字保存在ComfyUI的 `output/moss_prompt_enhancer/`。

生成内容和框位置仍需人工检查。使用细节、参数及迁移兼容说明见 [完整文档](../../docs/moss_prompt_enhancer.md)。

06使用视觉模型，需要配对的 `mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf`，以及随ToolBox分发的 `image_prompt_reverse_zh.txt` 系统预设，output_mode选择 `Tagged Caption`。将 [示例图](assets/tb_moss_reverse_cafe.jpg) 复制到ComfyUI/input，或在LoadImage上传自己的图片。该图来自此前本机生成的咖啡馆人物样本，JPEG不包含原PNG的工作流元数据。反推分区根据当前图片产生，不固定人物、镜子或场景。

反推正文在预览和TXT中呈现为 `<|分区名|>「描述」<|/分区名|>`；模型填写sections分区JSON，程序统一添加闭合标签及「」引号；分区JSON供校验和归档。MOSS采用普通文生图条件，参考图不会直接进入MOSS的VAE或图像参考分支。更换图片后检查文字，再决定是否调整prompt和重新生成。

English: select an existing local GGUF and prepare the MOSS components before running. Workflow 01 only enhances text; 02–05 also generate images. The node keeps the legacy type identifier. Clear old CLI flags in extra_args; this field now accepts optional Python initialization settings as JSON.

Workflow 06 accepts an image and a matching vision projector, generates Chinese prompts divided into named tagged sections, then sends the caption text to MOSS. The reference image guides the caption only; it is not an image-edit or identity-conditioning input to MOSS.
