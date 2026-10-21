# MOSS 提示词增强示例

先安装ToolBox及兼容的CUDA llama-cpp-python，准备GGUF模型；增强后生图还需MOSS主模型、专用文本编码器、VAE及Turbo LoRA。模型不随项目分发，不会自动下载。

| 工作流 | 用途 |
|---|---|
| [01 仅增强提示词](01_MOSS_仅增强提示词_布局JSON预览.json) | 只增强、校验、显示并保存文字 |
| [02 布局增强生图](02_MOSS_布局增强_Turbo8步_完整生图.json) | 三物体布局，1024×1024 |
| [03 Caption增强生图](03_MOSS_Caption增强_Turbo8步_完整生图.json) | 自然语言增强，1024×1024 |
| [04 中文海报](04_MOSS_中文海报布局增强_Turbo8步.json) | 中文文字，1024×1536 |
| [05 海滩人物与狗](05_MOSS_海滩人物与狗_布局增强_Turbo8步.json) | 人物、动物和远景，1536×1024 |

同名API图位于api目录。示例默认GGUF为Gemma4-12B Q4_K_M，使用时应在增强器中选择自己已安装的模型。生图示例的本地文件名为 `moss/moss_image_sft_bf16.safetensors`、`moss/qwen3.5_9b_int8_convrot.safetensors`、`moss/flux2-vae.safetensors` 和 `moss/moss_sft_8step_dmd_2600.safetensors`；实际安装文件名不同时需在加载器中修改。

打开普通JSON，在增强器输入prompt和尺寸，RESPONSE连接文本编码器，WIDTH/HEIGHT连接latent。示例采用8步CFG1、Euler/sgm_uniform、Shift5，固定种子20261020；相同输入可能复用ComfyUI缓存。输出图片及文字保存在ComfyUI的 `output/moss_prompt_enhancer/`。

生成内容和框位置仍需人工检查。使用细节、参数及迁移兼容说明见 [完整文档](../../docs/moss_prompt_enhancer.md)。

English: select an existing local GGUF and prepare the MOSS components before running. Workflow 01 only enhances text; 02–05 also generate images. The node keeps the legacy type identifier. Clear old CLI flags in extra_args; this field now accepts optional Python initialization settings as JSON.
