# ToolBox/DanceMV：音乐与动作意图自动编排

## 节点

| 菜单名称 | 稳定节点ID | 作用 |
|---|---|---|
| tb-dance-audio-analysis | DanceMVAnalyzeAudio | Beat This!＋librosa分析拍点、首拍、重音和能量，选取15秒音乐。 |
| tb-dance-intent-planner | DanceMVIntentPlanner | 本地GGUF模型结合音乐数据和用户动作意图自动编排，输出H3提示词、动作表和JSON。 |
| tb-dance-save-wav | DanceMVSaveWav | 保存FLOAT WAV并透传音频，供音乐工作流使用。 |

位于 `ToolBox/DanceMV`。`DanceMVChoreography`和`DanceMVAfterVideo`保留原ID与端口，列为Legacy兼容节点；固定动作模板只用于历史工作流。

## 使用

1. 运行[音乐生成示例](../examples/dance_mv/README.md)，或准备自己的音频。
2. 第二张示例选择音乐、人物图，在 `user_actions` 输入“有力量的街舞，动作随重音增强，具体编排由系统决定”等动作意图。
3. 分析节点提供真实音乐数据；编排节点自动选择动作、重音处理和衔接，自动生成的提示词直接连接H3 Ref2VA。用户无需填写完整成品提示词。

现有端口顺序、参数和默认值保持兼容。示例为768×1344、360输出帧、24fps、15秒，Turbo4步＋VEDA。CreateVideo保持 `codec=none`，由SaveVideo单次编码。输入文件、H3模型及其外部节点需按示例中的名称准备。

## 依赖与模型

基础ToolBox照常安装；DanceMV专用库按需安装到ComfyUI的Python环境：

```bash
python -m pip install -r requirements-dance-mv.txt
```

编排使用已经可用的CUDA llama-cpp-python；本机沿用0.3.40。不要用通用CPU wheel替换现有CUDA构建。节点注册时不加载Beat This!、librosa或llama-cpp-python，执行对应功能时才使用。

模型位置：

- `ComfyUI/models/beat_this/final0.ckpt`：Beat This! final0。
- `ComfyUI/models/LLM/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf`：本机沿用的编排模型。
- Music3、H3主模型、编码器、VAE、Turbo LoRA和VEDA预测器：沿用既有工作流的相对模型路径。

迁移复用本地已有权重，模型不随ToolBox源码打包。Beat This!失败时不会静默退回librosa；显式选择librosa时会标明其无法可靠检测小节首拍。

## 输出与限制

默认输出到ComfyUI `output/videos/minimaxh3/dance_mv/dance`。分析与编排节点保存实测音乐数据、用户意图、原始本地模型输出、动作JSON、时间表和自动编译提示词。动作内容由模型生成，段落时间由测量数据填入。

音乐分析、动作计划和H3实际执行效果须分别判断。节点不保证逐拍精确运动；原有视频已展示动作增强，也存在大幅伸臂出画等限制。

## 从独立包迁移

停用 `ComfyUI-H3-DanceMV`，只保留ToolBox提供相同ID的节点，避免重复注册。旧工作流接线无需重建；本次更新的两张示例已经标记为ToolBox来源。

本机增量部署脚本为 `scripts/deploy_dance_mv.py`，只合并DanceMV模块、注册、本地化和文档，保留运行副本的其他修改。它会先备份，等待队列空闲，再移出独立包；传入 `--restart` 时重启服务。可选依赖和模型按上述说明单独准备。

本次按照用户要求直接迁移，未重新运行测试、音乐生成或视频生成。既有实测记录属于迁移前结果。
