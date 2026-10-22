# 参考图反推工作流部署与集成验收（2026-10-22）

## 部署

部署至当前运行的ComfyUI环境，新增ToolBox内的moss_prompt_enhancer模块和必要注册项、单独合并中英文节点说明，安装06工作流、中文预设及示例图。保留运行环境中其他ToolBox模块。部署前备份注册文件、语言文件、已有工作流和用户同名预设。

队列空闲后重启ComfyUI，确认 `MOSSPromptEnhancer` 的python_module为 `custom_nodes.ComfyUI-ToolBox`，分类为 `ToolBox/MOSS`，output_mode包含 `Tagged Caption`。注册节点由5663增至5664，新增项只有MOSSPromptEnhancer，没有原有节点消失。

工作流在ComfyUI侧栏的 `003text2image/MOSS-Image/Prompt-Enhancer/06_参考图_llama-cpp中文分块反推_MOSS_Turbo8步.json`。安装文件与项目示例字节一致。示例JPEG放入input，配对Gemma4模型与mmproj、MOSS生图模型均使用已有文件；复用已安装CUDA llama-cpp-python 0.3.40，没有新增推理依赖。进程检查未发现llama-cli或llama-server。

## 实测

| 测试 | 结果 | 服务端耗时 |
|---|---|---|
| 咖啡馆参考图 → Tagged Caption | 8个中文分区，740字符，sections与编译正文一致 | 16.946秒 |
| 三物体参考图 → Tagged Caption | 7个中文分区，658字符，识别红方块、绿玻璃球和蓝茶壶 | 8.451秒 |
| 06完整工作流 | 重新执行识图、编译并生成1024×1024图片 | 39.588秒 |

三次历史记录均成功，均未命中节点缓存。检查分区JSON、严格匹配的开闭标签与「」引号、保存的TXT/JSON、执行历史及图片内嵌工作流/API图。完整测试的提示词来自实际视觉推理，没有离线替换增强器输出。

完整生图保留短发人物、浅色衬衫、蓝杯、手表、左窗光及咖啡馆背景；视线转向画面左侧、手势和人物面容发生变化。参考图仅辅助视觉语言模型生成文字，MOSS从空latent生成，未加入身份或姿态图像条件。

CPU测试14项通过，`git diff --check`通过。此前自由标签生成的失败尝试和阶段性渲染仍保留在[10月21日记录](moss_image_prompt_reverse_2026-10-21.md)，本次已补齐最终模式的集成验收。

本地备份和原始记录：工作目录下 `results/moss_prompt_enhancer/image_prompt_reverse/20261022_180319/`，包括backup、deployment.json、registration_check.json、process_check.json，以及cafe_caption、objects_caption、cafe_full各测试的API图、UI图、历史、输出图和validation.json。完整生图prompt_id为 `ed464b23-498c-4799-93fa-e2953c35be1d`。
