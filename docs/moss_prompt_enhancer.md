# MOSS 提示词增强

`tb-moss-prompt-enhancer` 位于 `ToolBox/MOSS`，节点类型保持 `MOSSPromptEnhancer`，旧版输入、控件顺序和六个输出不变。它将简短想法扩写为自然语言或带布局的JSON，使用官方MOSS编译逻辑校验并输出生图提示词。

## 安装和模型

随ComfyUI-ToolBox安装，无须独立的ComfyUI-MOSS-Prompt-Enhancer或LLM Text Processor插件，也不需要llama-cli。升级时停用独立增强器插件，避免重复注册同一个节点类型。

推理复用已有的CUDA版 `llama-cpp-python`；本地验证版本为JamePeng分支0.3.40。该库不加入ToolBox默认requirements、不自动安装或下载。缺少库或无法加载原生库时，本节点仍能注册，只在执行增强时报告依赖错误；旁路不加载该依赖。构建镜像时复用原有匹配Python、CUDA版本的wheel安装步骤。

- GGUF放在 `ComfyUI/models/LLM/`，递归发现；不包含mmproj的文件显示在model列表。
- 纯文本选择 `mmproj=none`；连接参考图时需要与模型匹配的mmproj。
- 可选附加系统预设为 `models/LLM/prompts/` 中顶层TXT文件。
- 五套示例见 [示例与准备](../examples/moss_prompt_enhancer/README.md)。模型和MOSS生图组件需要预先准备，节点不下载权重。

## 使用

在prompt输入想法，设置width/height为16的倍数，然后运行。`Structured Layout`产生绝对像素XYXY草稿，再编译成MOSS使用的中心原点YXYX。`Caption`输出详细自然语言。JSON校验只检查结构、坐标和尺寸，不能保证语义标签、物体位置和文字完全正确。

| 输出 | 用途 |
|---|---|
| RESPONSE | 编译后的提示词，连接MOSS文本编码器 |
| DRAFT_JSON | 可编辑草稿；手改后必须重新编译，不能直接作为MOSS布局条件 |
| REASONING | 模型输出的推理内容，可能为空 |
| PERF | 已有库版本及原生token性能指标 |
| WIDTH / HEIGHT | 连接latent宽高，保持画布与布局一致 |

`extra_args`默认留空，接收Python初始化参数JSON，例如 `{"n_threads":8,"n_batch":512}`。支持n_threads、n_threads_batch、n_batch、n_ubatch、flash_attn_type、type_k、type_v。旧CLI参数如 `--simple-io` 应清空。

每次增强创建自己的模型上下文，不共享其他节点的模型实例。加载前调用ComfyUI已有卸载入口及已注册的llama清理钩子；JSON重试复用同一个上下文，完成或异常后关闭模型，给MOSS生图腾出显存。超时包含加载时间，但加载本身需等待返回后检查；解码阶段通过原生回调与逐token检查响应超时/取消。

## 兼容与验证

迁移只改变节点归属、菜单名称和分类。已有JSON/PNG中的 `MOSSPromptEnhancer` 及连线继续有效；较早CLI版工作流需清空extra_args。重启ComfyUI并刷新页面后重新打开磁盘JSON，避免浏览器未保存的旧参数。

本地验收覆盖依赖缺失注册、旁路、官方编译结果、重试及模型关闭，并实跑布局、Caption和中文海报生图。参考图输入和reasoning on不属于这次迁移的GPU验收范围。

[2026-10-21验收记录](testing/moss_prompt_enhancer_2026-10-21.md)。

English: the node retains the legacy `MOSSPromptEnhancer` identifier and all six outputs. It uses the existing CUDA llama-cpp-python package only at execution time; missing optional dependencies do not prevent registration. Disable the standalone enhancer plugin to avoid duplicate registration. No CLI backend, automatic package installation or model download is added. See the [examples](../examples/moss_prompt_enhancer/README.md) and [upstream attribution](../nodes/moss_prompt_enhancer/UPSTREAM.md).
