# 🧰 ComfyUI-ZImage-Toolbox

这是一个为 ComfyUI 设计的综合工具盒，旨在通过预设化、模块化的节点提升工作流的效率。
## 🚀 核心功能：尺寸管理 (Size Management)
### 1. zimage-latent-size (ToolBoxLatentSize)

该节点解决了在不同宽高比（Aspect Ratio）之间切换时，手动计算像素值的繁琐过程。它内置了符合主流 AI 模型（如 SDXL, SD1.5）训练分布的分辨率预设。

- **动态联动**：选择比例（如 9:16）后，分辨率选项会自动更新为该比例下的推荐像素值。
- **自定义尺寸**：选择“自定义尺寸”后，可直接输入宽度和高度。
- **8像素对齐**：所有预设均严格遵循 8×8 像素对齐要求。
- **纯数值输出**：仅输出 width 和 height 整数值，可自由连接至 Empty Latent 或 Upscale 节点。

### 节点参数说明
| 参数名     | 类型           | 描述                                         |
|------------|----------------|----------------------------------------------|
| ratio      | Combo (下拉框) | 预设比例（9:16 竖屏、1:1 方图、16:9 横屏等）或自定义尺寸 |
| resolution | Combo (下拉框) | 基于选定比例的具体分辨率选项，最高扩展到 4096 档 |
| custom_width | INT | 自定义尺寸模式下输出的宽度，范围 8-4096 |
| custom_height | INT | 自定义尺寸模式下输出的高度，范围 8-4096 |

## 🎲 随机提示词 (Random Prompt)
### tb-random-prompt (ToolBoxRandomPrompt)

该节点从本地 SQLite 数据库中按 seed 稳定抽取一条提示词，可按语言、媒体类型、提示词类型、NSFW、格式、动态性、标签和宽高过滤，输出 `id`、`prompt`、`width`、`height` 和 `metadata`。

首次使用前运行导入脚本：

```bash
python3 scripts/import_prompts.py --language zh --media-type image --prompt-type natural --nsfw --content-format plaintext --static --tags "portrait,indoor"
```

默认会读取插件根目录下的 `prompts/` 目录，并生成 `data/prompts.sqlite3`。导入脚本会提取记录 id 和提示词内容；如果提示词跨多行，会拼接成同一行写入数据库。可使用 `--input prompt.txt` 指定单个文件。

### 节点参数说明
| 参数名 | 类型 | 描述 |
|--------|------|------|
| seed | INT | 可复现随机种子；同一数据库和同一 seed 输出同一条提示词 |
| language | Combo | `全部`、`zh`、`en` |
| media_type | Combo | `全部`、`image`、`video`、`audio`、`music` |
| prompt_type | Combo | `全部`、`natural`、`danbooru` |
| safety | Combo | `全部`、`nsfw`、`safe` |
| content_format | Combo | `全部`、`plaintext`、`json` |
| dynamic | Combo | `全部`、`dynamic`、`static` |
| tags | STRING | 可选，逗号分隔；多个标签需要全部匹配 |
| match_size | BOOLEAN | 是否按数据库记录中的建议宽高过滤；不会搜索真实图片文件 |
| width / height | INT | 用于尺寸过滤或写入的宽高，默认 1024×768 |

### tb-prompt-writer (ToolBoxPromptWriter)

该节点可在 ComfyUI 页面中将一条提示词及其元数据写入本地数据库，并输出 `id`、`prompt`、`metadata`。`id=0` 时自动创建新记录；指定已存在的 `id` 时更新该记录；指定不存在的 `id` 会报错。

## 🔞 Prompt NSFW 检测

### tb-prompt-nsfw-detector (ToolBoxPromptNSFWDetector)

该节点使用本地文本分类模型和精确 Danbooru 成人标签词典，检测中文、英文自然语言及 Danbooru 标签式 prompt 中的成人性内容。它只返回检测结果，不会修改或拦截原 prompt。

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

首次执行会从 Hugging Face 下载 `uget/sexual_content_dection`，之后使用本地缓存离线推理。推理文本不会发送给远程 API；首次模型下载失败或缺少依赖时，节点会明确报错而不会静默退化。

| 参数/输出 | 类型 | 描述 |
|-----------|------|------|
| prompt | STRING | 待检测的自然语言或 Danbooru prompt；空文本按安全处理 |
| threshold | FLOAT | 模型判定阈值，默认 `0.5`；不影响显式 Danbooru 标签命中 |
| is_nsfw | BOOLEAN | 模型或标签词典任一命中时为 `true` |
| score | FLOAT | `0–1` 风险分数；显式词典命中时为 `1.0` |
| details | STRING | JSON 详情，包含模型分数、阈值、命中标签和判定来源 |

该检测仅覆盖成人性内容，不是暴力、仇恨或违法内容的完整安全审核。自动分类可能误报或漏报，不应作为高风险场景中的唯一审核措施。
