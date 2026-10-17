# ToolBox 3DGS

ToolBox提供四个节点：LocalCOLMAPDataset、LocalVideoFrames、LocalBrushTrain、LocalPLYFile，分类为ToolBox/3DGS。节点类型和输入输出保持兼容旧工作流。节点始终注册，导入ToolBox时不导入PyCOLMAP、不启动Brush、不安装或下载依赖。

## 三个项目的职责

- ComfyUI-ToolBox维护节点、examples/3dgs中的四套工作流及两张图片，以及本目录文档。
- Wheels-Containerfiles的[3dgs-v1 Release](https://github.com/wangweihong/Wheels-Containerfiles/releases/tag/3dgs-v1)提供官方PyCOLMAP4.2.1 CPU wheel、Brush0.3.0程序归档和Rocky Linux10通用Vulkan Loader RPM，包含SHA256和来源清单。
- ComfyUI-Custom在Dockerfile中通过wget下载、校验和安装这些文件；INSTALL_3DGS默认false，只控制运行依赖。节点、工作流和文档两种变体均保留。

在ComfyUI-Custom根目录运行`make build-cu130-megapak-pt211 INSTALL_3DGS=true`构建包含依赖的-3dgs镜像。`OFFLINE_MODE=true`从该组件offline-cache/3dgs读取同一批发行文件。首次支持Linux amd64、Python3.13、Rocky Linux10镜像组合；不在源码中编译wheel，也不改变基础PyTorch/CUDA。

普通ToolBox安装仍可使用抽帧和PLY加载；执行重建或训练时若缺少PyCOLMAP或Brush，会提示安装运行依赖，不影响其他ToolBox节点。Brush固定安装到`/opt/3dgs/bin/brush_app`。RPM只适用于匹配的发行版，其他Linux环境应自行安装其发行版的通用Vulkan Loader。

## 工作流与模型

四套示例位于ToolBox的examples/3dgs/workflows。原生H3及KJNodes提供视频生成所需节点。将examples/3dgs/assets的两张图片复制到ComfyUI/input；Custom镜像在构建时已经预置图片和工作流。

H3模型不打包，沿用用户模型挂载。加载器下拉值如下：

| 加载器 | 模型 |
| --- | --- |
| UNETLoader | minmaxh3/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors |
| CLIPLoader / minimax | text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors |
| VAELoader | vae/minimax_h3_video_vae_int8_convrot.safetensors |
| LoraLoaderModelOnly | minimaxh3/minimax_h3_flf2v_lora_v1.safetensors |

01/02完成从单图到高斯场景的全流程。03选择已有COLMAP dataset重新训练；04选择已有PLY预览。03/04默认路径为空，路径须指向当前ComfyUI output内的实际输出。

## 升级与设备条件

旧版独立插件ComfyUI-Local-3DGS与ToolBox使用相同节点类型名。更新ToolBox前，应由用户移除或停用旧独立插件，防止重复注册。这里不自动清理旧节点、同步已有卷或修改正在运行的服务。

PyCOLMAP运行CPU；Brush需要实际环境提供可用Vulkan设备及驱动。通用Loader不能替代设备驱动。节点继承外部环境，不设置驱动品牌、版本、本机ICD或驱动库目录。H3仍需满足基础ComfyUI环境的设备条件。

- [功能原理与完整操作流程](功能原理与完整流程.md)
- [技术分析](技术分析.md)
- [安装位置与依赖说明](Linux安装与路径说明.md)
- [历史样例及质量边界](本地测试报告.md)
- [优化建议](优化建议.md)

单图生成视角可能存在几何矛盾、漂浮高斯和截断伪影；流程成功不代表几何质量合格。完整GPU测试通过`scripts/test_3dgs_api.py --url http://127.0.0.1:8189 --results <独立测试输出目录>`显式提交，勿对正在使用的服务运行测试。
