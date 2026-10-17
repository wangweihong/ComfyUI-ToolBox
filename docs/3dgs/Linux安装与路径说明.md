# 镜像内依赖与设备条件

启用INSTALL_3DGS=true的镜像在构建时安装PyCOLMAP4.2.1 CPU wheel、Brush0.3.0以及发行版通用Vulkan Loader。本功能不增加启动安装、自动下载大模型或驱动版本检查。

- Brush程序：`/opt/3dgs/bin/brush_app`。
- 版本与构建依赖记录：`/opt/3dgs/manifest.json`。
- PyCOLMAP：当前Python3.13的site-packages。用`python3.13 -c 'import pycolmap; print(pycolmap.__version__, pycolmap.__file__, pycolmap.has_cuda)'`查看。
- 节点预装目录：`/default-comfyui-bundle/ComfyUI/custom_nodes/ComfyUI-ToolBox/nodes/3dgs`。
- 工作流和文档：预装ComfyUI的`user/default/workflows/006视频生成/minimaxh3/单图转3DGS_COLMAP_Brush`。
- 示例输入：预装ComfyUI的`input/`。

沿用项目既有初始化机制。这里不增加已有卷同步、节点替换或启动开关；已有持久化目录的管理仍按原项目说明处理。

PyCOLMAP特征提取、匹配和SfM使用CPU；H3依赖基础镜像已有的PyTorch/CUDA环境；Brush训练需要实际环境提供可用的Vulkan设备及相应驱动。通用Loader不会代替显卡驱动，安装包存在也不保证任何硬件均能训练。节点继承用户环境，不覆盖VK_ICD_FILENAMES或LD_LIBRARY_PATH，不指定厂商和驱动版本。

ToolBox的examples/3dgs/README列出模型文件。03填写已有COLMAP dataset目录，04填写已有高斯PLY路径；路径都应位于当前ComfyUI output内。默认空路径会提示先运行01/02或选择已有输出。

[PyCOLMAP官方安装说明](https://colmap.github.io/pycolmap/index.html) · [Vulkan Loader](https://github.com/KhronosGroup/Vulkan-Loader)
