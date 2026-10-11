# 原生高清多场景测试 / Native HD scene tests

19 复用本地已有 `qwen2.1 t2i 人物` 工作流的 UNET、CLIP、VAE、Euler / simple、25 steps、CFG 1，生成 12 张原生 2048×3072 图：二次元/写实 × 站姿/跪姿/坐姿 × 连裤袜/大腿袜。使用明确成年人物的日常服饰场景，包含深浅颜色、不同厚度、弯曲、遮挡与光照。

20 是 540 节点的大工作流。每张图片共用一个引导编辑器、深度节点与求解节点，再进入六种基础织物和三组组合效果（Coil＋蕾丝、油光＋豹纹/PARIS、爱心＋多文字＋摩尔纹＋损伤），共 108 个高清成品分支。全分辨率输出保留；512×768 缩图只用于比较总览。材质配置节点由所有场景共享，可集中调整。

固定测试图位于本地 `ComfyUI/input/ToolBoxStockingHD/20261011/`，原始生成图在 `output/ToolBoxStocking/HD-Qwen21/`，测试输出在 `output/ToolBoxStocking/HD-compare/`。这些大图片不放入 Git 仓库。工作流中的选区与引导对应这批固定图片；换图后应重新分割与编辑引导。

先生成并导入测试图片，再运行 20。已有本地测试环境已完成这一步；模型仍为本地已有模型，无额外下载。19 的重新生成图保存到 output，若要用新图做测试，需导入 input 并重建引导。高级节点预览受会话缓存上限约束，检查较早分支时可重新单独执行该分支，也可直接查看保存的高清 PNG。

English: workflow 19 reuses the existing local Qwen Image 2.1 portrait graph and settings to generate twelve native 2048×3072 adult fashion images. Workflow 20 shares masks, direction guides and depth per scene, testing six base fabrics and three layered combinations across twelve scenes (108 full-resolution results). Overview thumbnails do not replace the HD outputs. The fixed generated corpus is kept outside Git in ComfyUI input/output. Replacing an image requires new masks/guides. Models are already installed locally; there are no downloads. Re-execute an earlier render branch to refresh its bounded preview session, or inspect its saved HD PNG.
