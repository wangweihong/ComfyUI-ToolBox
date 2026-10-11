# 🧰 ComfyUI-ToolBox

这是一个为 ComfyUI 设计的综合工具盒，旨在通过预设化、模块化的节点提升工作流的效率。

## 丝袜纹理与引导编辑

为图片中的丝袜添加沿腿部弧度贴合的织物纹理、花纹、英文印花和钩丝效果。推荐使用 `NFStockingTexture` 一体化节点，在同一窗口完成部位选区、走向编辑和纹理预览。

### 开源来源与致谢

**本功能的核心算法来源于开源项目 [silvermoong/stocking-texture-tool](https://github.com/silvermoong/stocking-texture-tool)**，包括走向求解、织物纹理渲染和抗摩尔纹处理。感谢原作者 Silvermoong 的开源贡献；原项目采用 MIT 许可证，本仓库保留了原作者版权声明及完整许可，详见 [来源与移植说明](nodes/stocking_texture/UPSTREAM.md) 和 [上游 MIT 许可证](nodes/stocking_texture/LICENSE)。

本项目在该核心算法基础上实现了 ComfyUI 节点、编辑器、预览接口、模型适配及示例工作流，并扩展了八种花纹、英文印花和钩丝/抽丝效果。

### 功能介绍

| 功能 | 说明 |
| --- | --- |
| 一体化编辑 | 「部位／走向／纹理」三页完成编辑；打开窗口只准备必要上游，无需先运行完整工作流 |
| 选区与修边 | 支持画笔、橡皮、外部 MASK，以及可选 SAM ViT-B 点选；候选范围可预览、应用或取消 |
| SAM3 语义识别 | 可选连接 Easy-Sam3 image 模型加载器，按 `stockings` 等文本逐图识别部位，再手工修边 |
| 走向与深度 | 手绘横向引导控制纹理弧度；缺少手绘引导时可生成基础走向，可选灰度深度辅助贴合与隔开 |
| 14 种样式 | 原有细线、针织、斜单线、加濑风、油光（试验）；新版增加透肤自适应 Coil 线圈，以及波点、爱心、菱格、小渔网、大渔网、蕾丝、花卉、豹纹 |
| 上游新版渲染 | 显式切换至 f74c8ac，使用 Coil、深度摩尔纹及新版连续油光；旧工作流默认保持原输出 |
| 部位编辑与镜像 | 手画切开、自动贴线分割、合并、清空、走向镜像、指针删除和横／纵引导显示 |
| 材质预设与恢复 | 按用户保存材质预设；独立自动恢复草稿，仍需保存并关闭才写入节点 |
| PSD 互通 | 可选 psd-tools 支持 PSD/PSB 导入、引导 PSD 导出，以及成品和柔和透明 PNG |
| 花纹表现 | 新花纹支持「织物／印花」切换，大小、旋转、颜色和不透明度独立可调 |
| 英文印花 | 提供 BALENCIAGA、PARIS 预设及自由输入，支持最多 128 个可打印 ASCII 字符；字号、行列间距、方向、颜色和不透明度可调 |
| 钩丝与抽丝 | 支持随机、手工或混合生成钩丝和梯状抽丝，可调整数量、长度、宽度和强度；手工路径支持删除、撤销和重做 |
| 实时预览与保存 | 支持整体、100%/200% 细节及原图分界对比；统一窗口「保存并关闭」写入工作流，「取消」放弃草稿 |
| 图片绑定与批处理 | 手工选区和损伤按图片内容绑定，避免换图误用；批次只输出成功图像，保留输入/输出索引报告 |
| 图层与诊断 | 输出成品、丝袜图层、alpha、部位遮罩、诊断及报告；图层可精确叠回对应原图，遮罩外原始像素保留 |

手工选区与纹理渲染无需扩散模型、SAM 或深度模型；SAM/SAM3 和深度辅助按需连接。英文印花与损伤默认关闭，油光为试验样式。渔网、蕾丝及抽丝效果基于原图渲染，不生成新的裸肤底图。

保留 `NFStockingEditor → NFStockingSolve → NFStockingRender` 高级分步流程，兼容原有工作流。安装依赖、模型准备、参数及输出说明见 [完整使用文档](docs/stocking_texture.md)。

### 快速上手

1. 将插件放入 `ComfyUI/custom_nodes/ComfyUI-ToolBox`，按 [安装说明](docs/stocking_texture.md#安装和升级) 安装依赖，然后重启 ComfyUI 并刷新页面。
2. 将 [公开示例素材](examples/stocking_texture/assets) 中的 `tb_stocking_demo*.png` 复制到 `ComfyUI/input/`。PSD 示例另需复制 `tb_stocking_guides.psd`，并安装 `requirements-stocking-psd.txt`。
3. 把下表中的普通 `.json` 工作流拖入 ComfyUI。初次体验建议选择 **06-八种花纹总览**，已有合成图选区，无需准备识别或深度模型。
4. 点击主节点的「编辑与预览」，选择样式、调整参数或绘制损伤；「保存并关闭」后运行工作流生成结果。替换为自己的图片后，需重新建立该图片的选区。

自行搭建最简流程：`LoadImage → NFStockingTexture → PreviewImage / SaveImage`。图层合成时，一体化节点的 `source_images` 输出与成功处理的图片一一对应，可用作原图输入。

### 示例工作流

以下链接为可直接加载的 ComfyUI `.json` 工作流；同目录中的同名 `.api.json` 用于 API 队列调用。示例使用项目生成的公开合成图片，推荐的一体化与效果示例默认通过 PreviewImage 预览，不自动保存成品文件。

| 工作流 | 用途与准备 |
| --- | --- |
| [01-手工点选与统一编辑](examples/stocking_texture/unified/01-手工点选与统一编辑.json) | 画笔选区、走向与统一纹理编辑；默认选区为空，需要先编辑选区 |
| [02-SAM3语义识别与点选修边](examples/stocking_texture/unified/02-SAM3语义识别与点选修边.json) | SAM3 文本识别，再用 SAM ViT-B 点选修边；需准备对应本地模型 |
| [03-深度辅助与逐图批处理](examples/stocking_texture/unified/03-深度辅助与逐图批处理.json) | 两张图片组成真实批次，逐图识别并使用 Small 深度辅助；需 SAM3、SAM ViT-B 和 Small 深度模型 |
| [04-五种纹理并排对比](examples/stocking_texture/unified/04-五种纹理并排对比.json) | 比较原有五种织物纹理，共用图片与识别来源；需对应识别模型 |
| [05-图层合成与效果诊断](examples/stocking_texture/unified/05-图层合成与效果诊断.json) | 对应原图合成、透明图层及诊断预览；需对应识别模型 |
| [06-八种花纹总览](examples/stocking_texture/effects/06-八种花纹总览.json) | 并行预览八种新增花纹，内置合成图选区，无需识别/深度模型 |
| [07-英文错行印花](examples/stocking_texture/effects/07-英文错行印花.json) | BALENCIAGA 英文重复印花，可修改文本和排列参数；无需识别/深度模型 |
| [08-钩丝与梯状抽丝](examples/stocking_texture/effects/08-钩丝与梯状抽丝.json) | 随机损伤与预设手工路径组合，可继续编辑；无需识别/深度模型 |
| [09-花纹文字损伤组合](examples/stocking_texture/effects/09-花纹文字损伤组合.json) | 爱心花纹、PARIS 字样和损伤叠加；无需识别/深度模型 |

新增上游能力示例（无需识别模型）：

| 工作流 | 用途 |
| --- | --- |
| [10-Coil透肤线圈](examples/stocking_texture/upstream/10-Coil透肤线圈.json) | 新版线圈与柔和图层 |
| [11-深度摩尔纹](examples/stocking_texture/upstream/11-深度摩尔纹.json) | 使用公开合成深度图调整强度与面积 |
| [12-新旧油光对比](examples/stocking_texture/upstream/12-新旧油光对比.json) | 原图、兼容版油光与新版油光 |
| [13-柔和图层与组合效果](examples/stocking_texture/upstream/13-柔和图层与组合效果.json) | 蕾丝、PARIS、损伤、透明 PNG 和重合成 |
| [14-PSD引导导入导出](examples/stocking_texture/upstream/14-PSD引导导入导出.json) | 读入引导并在 output 保存新的引导 PSD |
| [04-六种纹理并排对比](examples/stocking_texture/unified/04-六种纹理并排对比.json) | 原图与六种基础样式；需对应识别模型，旧五样式示例保留 |

高级分步例子：[手工引导](examples/stocking_texture/manual.json)、[外部遮罩与深度](examples/stocking_texture/external-depth.json)、[SAM 点选](examples/stocking_texture/sam.json)、[批次渲染](examples/stocking_texture/batch.json)。这些高级例子包含 SaveImage 节点，执行前可调整保存位置。

### 效果预览与验证

下图为八种新增花纹在公开合成图片上的实际渲染结果：

![八种丝袜花纹对比](docs/images/stocking_patterns_overview.png)

![上游新版丝袜效果对比](docs/images/stocking_upstream_comparison.png)

验证记录：[上游能力验收](docs/testing/stocking_upstream_2026-10-11.md)、[一体化编辑与模型验收](docs/testing/stocking_unified_2026-10-10.md)、[花纹、英文印花与钩丝验收](docs/testing/stocking_effects_2026-10-10.md)。

### 有序图层与部位材质

基础织物与花纹可独立组合，每套材质最多 16 个有序花纹/英文文字层，支持复制、启停和排序，损伤最后处理。左右腿可继承全局或覆盖不同材质；连接 `NFStockingMaterial` 后全局参数显示解析值并只读，部位仍可编辑。V1 工作流、预设和十四个旧样式入口兼容，读取不改写，显式保存迁移至 V2；取消放弃编辑。详见 [V2 使用说明](docs/stocking_texture.md#有序材质图层与部位覆盖v2)。

| 新公开工作流 | 展示内容 |
| --- | --- |
| [15-Coil与蕾丝组合](examples/stocking_texture/materials/15-Coil与蕾丝组合.json) | 基础织物＋独立花纹层 |
| [16-左右腿独立材质](examples/stocking_texture/materials/16-左右腿独立材质.json) | Coil＋波点与油光＋豹纹/PARIS |
| [17-有序多层文字](examples/stocking_texture/materials/17-有序多层文字.json) | 爱心＋PARIS＋BALENCIAGA |
| [18-材质配置节点连线](examples/stocking_texture/materials/18-材质配置节点连线.json) | 五个新配置节点与只读全局材质 |

English: six base fabrics can be combined with up to 16 ordered procedural pattern/text layers and final damage. Regions inherit or override the global material. The five composable configuration nodes connect through the optional material input; linked global settings are read-only while region overrides remain editable. V1 pixels and workflow ports remain compatible. See [V2 usage](docs/stocking_texture.md#有序材质图层与部位覆盖v2) and [acceptance/performance results](docs/testing/stocking_materials_2026-10-11.md).

![有序材质图层对比](docs/images/stocking_materials_comparison.png)

## 🚀 核心功能：尺寸管理 (Size Management)
### tb-latent-size (ToolBoxLatentSize)

该节点解决了在不同宽高比（Aspect Ratio）之间切换时，手动计算像素值的繁琐过程。它内置了竖屏、方图和横屏等常用比例的多档分辨率预设；具体尺寸需根据所用模型和显存选择，部分预设比例会因像素对齐而略有偏差。

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
python3 scripts/import_prompts.py --language zh --media-type image --prompt-type natural --nsfw --content-format plaintext --static
```

默认会读取插件根目录下的 `prompts/` 目录，并生成 `data/prompts.sqlite3`。导入脚本会提取记录 id 和提示词内容；如果提示词跨多行，会拼接成同一行写入数据库。可使用 `--input prompt.txt` 指定单个文件。`--tags` 是批量标签，会绑定到本次导入的每一条提示词；如确实需要批量标签，需同时传入 `--apply-tags-to-all`。

### 节点参数说明
| 参数名 | 类型 | 描述 |
|--------|------|------|
| seed | INT | 可复现随机种子；`fixed` 保持相同结果。生成后控制设为 `randomize` 时，无论完整执行还是点击节点局部运行，都会自动更新 seed 并重新抽取；由于随机取样允许重复，仍可能低概率连续得到同一提示词 |
| language | Combo | `全部`、`zh`、`en` |
| media_type | Combo | `全部`、`image`、`video`、`audio`、`music` |
| prompt_type | Combo | `全部`、`natural`、`danbooru` |
| safety | Combo | `全部`、`nsfw`、`safe` |
| content_format | Combo | `全部`、`plaintext`、`json` |
| dynamic | Combo | `全部`、`dynamic`、`static` |
| tags | STRING | 可选，逗号分隔；多个标签需要全部匹配 |
| match_size | BOOLEAN | 是否按数据库记录中的建议宽高过滤；不会搜索真实图片文件 |
| width / height | INT | 仅在启用 match_size 时用于匹配数据库记录的建议宽高，默认 1024×768；输出宽高来自抽中的记录 |

### tb-prompt-writer (ToolBoxPromptWriter)

该节点可在 ComfyUI 页面中将一条提示词及其元数据写入本地数据库，并输出 `id`、`prompt`、`metadata`。写入时会根据去除首尾空白后的 `prompt` 计算 SHA-1 `shasum`：`id=0` 时更新相同 `shasum` 中 ID 最小的记录，不存在时创建新记录；指定 ID 时只更新该记录，即使其他记录已有相同 `shasum`。指定不存在的 ID 会报错。旧数据库需先运行 `python3 scripts/migrate_prompt_shasum.py --db data/prompts.sqlite3` 移除 `shasum` 唯一约束。

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
