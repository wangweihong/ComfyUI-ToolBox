# MOSS 提示词增强

`tb-moss-prompt-enhancer` 位于 `ToolBox/MOSS`，节点类型保持 `MOSSPromptEnhancer`，旧输入名称、控件顺序和六个输出保留；output_mode新增Tagged Caption选项。它将简短想法扩写为自然语言或带布局的JSON，使用官方MOSS编译逻辑校验并输出生图提示词。

## 安装和模型

随ComfyUI-ToolBox安装，无须独立的ComfyUI-MOSS-Prompt-Enhancer或LLM Text Processor插件，也不需要llama-cli。升级时停用独立增强器插件，避免重复注册同一个节点类型。

推理复用已有的CUDA版 `llama-cpp-python`；本地验证版本为JamePeng分支0.3.40。该库不加入ToolBox默认requirements、不自动安装或下载。缺少库或无法加载原生库时，本节点仍能注册，只在执行增强时报告依赖错误；旁路不加载该依赖。构建镜像时复用原有匹配Python、CUDA版本的wheel安装步骤。

- GGUF放在 `ComfyUI/models/LLM/`，递归发现；不包含mmproj的文件显示在model列表。
- 纯文本选择 `mmproj=none`；连接参考图时需要与模型匹配的mmproj。
- 附加系统预设包括 `models/LLM/prompts/` 中顶层TXT及节点自带presets目录；用户目录同名文件优先。
- 示例见 [示例与准备](../examples/moss_prompt_enhancer/README.md)。模型和MOSS生图组件需要预先准备，节点不下载权重。

## 使用

在prompt输入想法，设置width/height为16的倍数，然后运行。`Structured Layout`产生绝对像素XYXY草稿，再编译成MOSS使用的中心原点YXYX。`Caption`输出详细自然语言。`Tagged Caption`把模型生成的sections数组编译成统一标签段落。JSON校验只检查结构、坐标和尺寸，不能保证语义标签、物体位置和文字完全正确。

| 输出 | 用途 |
|---|---|
| RESPONSE | 编译后的提示词，连接MOSS文本编码器 |
| DRAFT_JSON | 可编辑草稿；手改后必须重新编译，不能直接作为MOSS布局条件 |
| REASONING | 模型输出的推理内容，可能为空 |
| PERF | 已有库版本及原生token性能指标 |
| WIDTH / HEIGHT | 连接latent宽高，保持画布与布局一致 |

`extra_args`默认留空，接收Python初始化参数JSON，例如 `{"n_threads":8,"n_batch":512}`。支持n_threads、n_threads_batch、n_batch、n_ubatch、flash_attn_type、type_k、type_v。旧CLI参数如 `--simple-io` 应清空。

每次增强创建自己的模型上下文，不共享其他节点的模型实例。加载前调用ComfyUI已有卸载入口及已注册的llama清理钩子；JSON重试复用同一个上下文，完成或异常后关闭模型，给MOSS生图腾出显存。超时包含加载时间，但加载本身需等待返回后检查；解码阶段通过原生回调与逐token检查响应超时/取消。

`reasoning=on/off`分别向文本模板和受支持的MTMD视觉模板传入 `enable_thinking=True/False`；`auto`保留模板默认设置。视觉处理器需要支持extra_template_arguments，无法传递时on会明确报错。Gemma4使用原生thought通道，其他模板默认使用think标签，推理内容从最终JSON中分离后输出到REASONING。若推理未闭合，节点报错而不把推理草稿交给MOSS。模型本身需要支持思考模板；开关不会给非推理模型增加这种能力。

推理和最终JSON共同使用max_tokens预算。开启推理可将max_tokens设为8192、ctx_size设为32768，并适当增加timeout_seconds；这些是容量上限，不保证正文变长。增加篇幅需要同时调整系统预设中的长度和细节要求。

## 参考图反推：中文分块提示词

新增 [06参考图反推工作流](../examples/moss_prompt_enhancer/06_参考图_llama-cpp中文分块反推_MOSS_Turbo8步.json)：上传图片后，保持比例缩放至约1MP并对齐16像素，宽高自动连接增强器和MOSS画布。默认选择已有Gemma4-12B GGUF与匹配的mmproj，Tagged Caption模式，内置预设 `image_prompt_reverse_zh.txt`。

反推结果采用以下形式，分区名称根据图片内容变化：

```text
<|镜头与全局比例|>「画幅、视角和主体大致占比。」<|/镜头与全局比例|><|主体外观与动作|>「可见外观、姿态与道具关系。」<|/主体外观与动作|>
```

这是分块标签式、场景重建用途的中文自然语言提示词，标签是自定义文本分段，不是MOSS专用token，也不是bbox布局JSON。模型输出 `{"sections":[{"name":"分区名","description":"正文"}]}`；程序校验字段并添加标签、闭合标记和「」引号，再通过官方Caption编译路径输出。DRAFT_JSON保留sections数组，RESPONSE和保存的TXT只包含规范化正文，直接送入MOSS文本编码器。

组织方式参考 [image-prompt skill](https://github.com/veryCoolTimo/imagegen-skills/blob/main/skills/image-prompt/SKILL.md) 的命名分区、主体细节与文字组织思路。该skill默认面向gpt-image-2且没有MOSS适配，本例按用户指定的标签格式独立编写中文反推预设，使用MOSS自然语言条件；不照搬其外部API参数、品牌补全或强制字体/色号规则。

图片只输入视觉语言模型，MOSS仍从空latent生成，因此属于“图像反推辅助文生图”，没有身份、姿态或逐像素一致性约束。可在prompt补充已知信息或明确改动；模糊文字、精确比例及不可见细节仍需核对。示例图需从examples中的assets目录复制到ComfyUI/input，或直接上传自己的图。

## 兼容与验证

迁移只改变节点归属、菜单名称和分类。已有JSON/PNG中的 `MOSSPromptEnhancer` 及连线继续有效；较早CLI版工作流需清空extra_args。重启ComfyUI并刷新页面后重新打开磁盘JSON，避免浏览器未保存的旧参数。

迁移验收覆盖依赖缺失注册、旁路、官方编译结果、重试及模型关闭，并实跑布局、Caption和中文海报生图。参考图功能已通过两张图片的Tagged Caption反推和06完整生图，见[参考图集成验收记录](testing/moss_image_prompt_reverse_2026-10-22.md)。视觉on/off/auto及纯文本on已做真实模型测试，见[推理开关验证记录](testing/moss_reasoning_2026-10-22.md)。

[2026-10-21验收记录](testing/moss_prompt_enhancer_2026-10-21.md)。

English: the node retains the legacy `MOSSPromptEnhancer` identifier and all six outputs. It uses the existing CUDA llama-cpp-python package only at execution time; missing optional dependencies do not prevent registration. Disable the standalone enhancer plugin to avoid duplicate registration. No CLI backend, automatic package installation or model download is added. See the [examples](../examples/moss_prompt_enhancer/README.md) and [upstream attribution](../nodes/moss_prompt_enhancer/UPSTREAM.md).
