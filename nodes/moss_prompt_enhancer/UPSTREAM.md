# 来源与迁移

- 节点及增强规则来自 [xb1n0ry/ComfyUI-MOSS-Prompt-Enhancer](https://github.com/xb1n0ry/ComfyUI-MOSS-Prompt-Enhancer)，原始版本 `db438f7483cbcb1128efd583b6e93e839ed49ece`。
- `compile_prompt`来自作者节点所内嵌的 [OpenMOSS官方编译器](https://github.com/OpenMOSS/MOSS-Image/blob/main/skills/moss-image-prompt-enhancer/scripts/compile_prompt.py)。迁移保留其字段检查、画布约束和坐标转换逻辑。
- 原项目通过LLM Text Processor调用CLI。此版本移除了该调用链，直接复用已经安装的CUDA llama-cpp-python。模型发现、推理生命周期、性能输出及超时处理由python_backend.py实现。
- 迁入ToolBox时仅将可选库延迟至执行时导入，接入ToolBox注册和本地化；节点类型、输入顺序和六个输出不变。

感谢原作者及OpenMOSS。上游代码和模型的许可条款应以对应原仓库为准；此说明不替代上游许可。不将LLM Text Processor作为运行依赖，也不包含其二进制。

使用说明见 [MOSS提示词增强](../../docs/moss_prompt_enhancer.md)。
