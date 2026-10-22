# 参考图反推工作流验证（2026-10-21）

## 实现与环境

工作流06使用已有Gemma4-12B Q4_K_M及配对BF16 mmproj，经已安装的CUDA llama-cpp-python 0.3.40识图。MOSS仍使用SFT BF16、官方INT8文本编码器、Turbo2600 LoRA，8步、CFG1、Euler/sgm_uniform、Shift5。没有安装第二套推理库或启动llama-cli。

模型生成sections数组，Tagged Caption模式的Python编译器统一输出 `<|分区名|>「正文」<|/分区名|>`。参考图保持比例缩放至约1MP、对齐16像素，宽高自动传给MOSS空latent。示例包含普通UI图、API图、中文系统预设和去除工作流元数据的示例JPEG。

## 已完成验证

- `python3 -m unittest discover -s tests -p test_moss_prompt_enhancer.py -v`：14项通过。覆盖旧接口、可选依赖、关闭与超时、原编译路径、新分区编译及输入校验、预设路径顺序和工作流连线；`git diff --check`通过。
- 实际视觉输入分别使用咖啡馆人物和三物体图片，保持通用反推指令。模型分别描述出短发人物/蓝杯/窗边环境，以及红方块/绿玻璃球/蓝茶壶，说明描述随输入图变化。
- 上述视觉预验证采用旧Caption模式直接生成标签。服务端推理成功，耗时19.586秒和8.223秒；严格格式校验未通过：存在缺少「」或闭合斜线的问题。因此最终实现改为模型输出分区JSON、程序统一格式化。
- 将实际咖啡馆识图结果恢复为分区JSON、经新编译器格式化后，单独验证MOSS渲染：成功生成1024×1024图片，耗时7.417秒。保留短发、浅色衬衫、蓝杯、左窗和咖啡馆背景；脸部、视线和持杯手势发生变化。这符合仅通过文字重建、没有图像身份条件的工作方式。

## 当日待完成的集成验收

以下为10月21日状态。最终部署及三项集成测试已于10月22日完成，见[完整验收记录](moss_image_prompt_reverse_2026-10-22.md)。

最终Tagged Caption模式尚未在常驻ComfyUI进程中加载。部署文件已备份和同步，但现有生成队列仍在运行，尚未重启。因此以上阶段验证不等于工作流06的最终整图执行通过。

重启并刷新页面后，需要确认output_mode包含Tagged Caption，再依次跑咖啡馆反推、三物体反推和06完整生图。核对sections JSON、规范标签、文本文件、图片及历史记录；确认旧节点注册没有减少。参考图仅传入视觉语言模型，不能将人脸、姿态或像素一致性作为验收标准。

本地原始证据保存在工作目录的 `results/moss_prompt_enhancer/image_prompt_reverse/20261021_171017/`：sources和source_manifest记录研究来源，attempts/freeform_tags保留格式不合格的真实识图记录，format_preview_from_caption记录离线格式化结果，staged_moss_render记录独立渲染图和执行历史，backup保存部署前文件。这些机器相关文件不随项目分发。
