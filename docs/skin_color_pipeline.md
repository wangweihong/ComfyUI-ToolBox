# 参考取色与肤色复测局部校色

把参考皮肤取色、提示词自动补充、生成结果复测、必要时局部Lab校准、校准后固定取样点复测串为ComfyUI节点。模块位于 `nodes/skin_color_pipeline/`，节点菜单位于 `ToolBox/SkinColor`。保留原来的8个H3Skin节点标识，已有工作流及PNG元数据继续兼容。

## 节点

- `H3SkinMask`：本地MediaPipe面部/身体皮肤类别与RGB/Lab颜色筛选共同取遮罩。角色表逐角色、逐细节格处理。可接外部遮罩收紧区域。
- `H3SkinMeasure`：剔除亮度下20%和上20%，分别统计脸部/身体的RGB与Lab中位数，并保留之后复测使用的具体像素索引。
- `H3SkinPrompt`：把实测RGB、HEX与自然语言肤色约束自动追加到基础提示词。明确数值是渲染中间调参考，不是PBR Base Color。
- `H3SkinCompare`：按区域给出参考与生成图的ΔE76、亮度/色度偏差以及是否需要校色。
- `H3SkinCorrect`：仅处理皮肤；改变量有上限，边缘向内羽化，保护高光。不改善该区域统计的候选校准会被拒绝；低于阈值时跳过。
- `H3SkinRecheck`：对校色前的同一批像素复测，避免校色后重新选择更好的样本而虚报改善。
- `H3SkinBoardLayout`：白色背景下检测三个人物与网格分界，自动完成60/40排版，避免沿用旧图的固定人物裁切坐标。
- `H3SkinSaveReport`：保存参考、生成、局部校色前后及可选无RGB基线的独立结果。

## 依赖与恢复

使用ComfyUI现有Torch、NumPy、Pillow、SciPy，以及已安装MediaPipe。代码不进行pip安装或模型下载。

模型位置：`ComfyUI/models/mediapipe/selfie_multiclass_256x256.tflite`。

SHA256：`c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0`。缺少模型或校验失败会明确报错，不能默默把整图当皮肤。

工作流位于 `examples/skin_color/`，GUI JSON可导入ComfyUI；API JSON供后端提交。加载 `h3_character_design_reference.png` 与可选基线 `h3_skin_baseline_without_rgb.png` 时，请放入ComfyUI input目录或自行重新选择图片。MiniMax H3模型与Fizgig H3 Still节点需事先可用。MediaPipe是本模块的可选运行依赖，按需使用 `requirements-skin-color.txt`，不会在执行节点时自动安装。

## 默认校色策略

`mode=auto`，区域ΔE76阈值3，强度0.75，最大L*调整18，最大色度向量调整8，羽化6像素。`off`为完全跳过，`always`尝试所有有偏差区域。阈值3是可调工作流参数，不是通用感知合格标准。

脸部与身体各自对照参考；颜色假设为sRGB/D65，衡量的是最终图像表现，不是光照无关的物理肤色。白色背景、白袜、紫色衣服、明显金饰、暗发及饱和唇色由颜色筛选排除；自动语义分割仍会有遗漏或误判，运行前后应检查遮罩与叠加预览。

为减少碎片边界，语义种子可在颜色兼容连通区域内扩展。参考图额外限制在低阈值语义前景中，防止扩展到树林/树皮。角色表指定的第10格应为膝盖/小腿：如果语义模型漏检且该格超过70%像素符合肤色，会使用该格的颜色回退；必须确认该格实际内容正确。

对照图是同一角色、同一基础提示词、seed及采样设置的已有无RGB输出。换角色/种子/设计后必须替换对照图或断开保存报告节点的baseline_report，不能继续使用旧人物计算提示词效果。

## 验证

`tests/test_skin_color_pipeline.py`检查标准Lab锚点、逆转换、条件跳过、局部校准改善和遮罩外像素精确保留。实际ComfyUI API复测使用既有4K成图检查分割、校色和报告链路，无需重新采样H3。

参考接口：[MediaPipe Image Segmenter](https://developers.google.com/edge/mediapipe/solutions/vision/image_segmenter/python)。Lab采用标准sRGB/D65矩阵，ΔE使用CIE1976欧氏距离。
