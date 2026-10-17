# H3单图转3DGS（ToolBox节点）

ToolBox始终提供四个节点、四份工作流和两张示例输入。ComfyUI-Custom通过INSTALL_3DGS=true额外安装PyCOLMAP、Brush和通用Vulkan Loader。H3大模型由用户挂载，不包含在功能包里。

| 工作流 | 操作 |
| --- | --- |
| 01_assets宇航员_环绕到3DGS | 默认宇航员图，生成环绕视频、COLMAP重建、Brush训练、原生预览 |
| 02_assets提灯_环绕到3DGS | 默认提灯图，完整场景对照；历史样例几何质量不合格 |
| 03_复用COLMAP数据集_仅训练3DGS | 选择已有dataset目录，不重新生成或重建 |
| 04_原生高斯PLY预览_无需重新训练 | 选择已有PLY，只预览 |

01/02点击运行前准备以下模型，模型名对应ComfyUI加载器下拉值：

| 加载器 | 文件名 |
| --- | --- |
| UNETLoader | minmaxh3/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors |
| CLIPLoader（type=minimax） | text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors |
| VAELoader | vae/minimax_h3_video_vae_int8_convrot.safetensors |
| LoraLoaderModelOnly | minimaxh3/minimax_h3_flf2v_lora_v1.safetensors |

沿用已有模型挂载和基础环境的ComfyUI原生H3、Kitchen注意力及KJNodes的MiniMaxChunkFeedForward。镜像中不自动下载权重。

输出为ComfyUI output/h3_gaussian_splat下的独立dataset和brush目录。03/04默认路径为空，先运行01/02，再选择对应数据集或PLY。不要填写宿主机目录来代替容器内的output路径。

- [功能原理与完整流程](../../docs/3dgs/功能原理与完整流程.md)
- [技术分析](../../docs/3dgs/技术分析.md)
- [依赖安装位置与设备条件](../../docs/3dgs/Linux安装与路径说明.md)
- [历史测试及质量边界](../../docs/3dgs/本地测试报告.md)
- [优化建议（尚未完成对照）](../../docs/3dgs/优化建议.md)

PyCOLMAP使用CPU；Brush训练使用Vulkan，需要实际环境提供兼容设备和驱动。镜像不捆绑宿主机驱动，不锁定驱动品牌、版本或ICD路径。完整执行成功不保证场景质量合格。
