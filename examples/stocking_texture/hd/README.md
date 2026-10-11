# 原生方形高清多场景测试 / Native square HD scene tests

19 使用本地 Qwen Image 2.1 BF16、Qwen3-VL 8B 与 Qwen 2.1 VAE，Euler/simple、25 steps、CFG 1，直接生成 12 张 **2048×2048** 图片，无放大步骤。覆盖二次元插画/写实 × 站姿/跪姿/坐姿 × 连裤袜/大腿袜。采用单人、简洁背景和明确成年人物的日常服饰提示词。跪姿使用双膝并排、小腿自然向后折叠的姿势。

生成素材必须逐张检查手臂、腿、膝盖连接和脚部；明显多肢、错接或姿势不合理的图片换种子重生成。提示词不能保证人体结构正确。旧 2048×3072 语料及其截图已撤销为合格示例。

20 是 540 节点的大工作流。每张图片共用一个引导编辑器、深度节点与求解节点，再进入六种基础织物和三组组合效果（Coil＋蕾丝、油光＋豹纹/PARIS、爱心＋多文字＋摩尔纹＋损伤），共 108 个原生高清成品。512×512 缩图只用于比较总览，完整 2048×2048 输出保留。

固定输入：`ComfyUI/input/tb_stocking_square_*.png`；原始生成图：`output/ToolBoxStocking/Square-Qwen21/`；对比输出：`output/ToolBoxStocking/Square-compare/`。大图片不放入 Git。模型均为本地已有模型，无下载或远端生图服务。

先运行 19，并检查生成结果，再将合格图片以素材清单中的文件名放入 input、重新分割和编辑引导，最后运行 20。本地已准备的固定输入与保存引导相匹配；19 的生成结果只写入 output，不会覆盖固定 input。换图后不能继续沿用旧选区或走向。早期渲染预览会话可能被缓存回收，可重新单独执行该分支，或查看保存的完整 PNG。

详见 [素材清单](dataset_manifest.json) 和 [验收记录](../../../docs/testing/stocking_hd_2026-10-11.md)。

English: workflow 19 generates twelve native **2048×2048** images with the locally installed Qwen Image 2.1 models (Euler/simple, 25 steps, CFG 1). The corpus covers illustrated/photorealistic adult fashion, standing/kneeling/sitting and tights/thigh-high stockings. Every image is visually reviewed for extra limbs and incorrect joint connections before inclusion; prompts alone do not guarantee anatomy. The former 2048×3072 corpus is withdrawn. Workflow 20 shares masks, direction guides and depth per scene, rendering nine materials (108 native HD outputs). The 512×512 thumbnails are only for overview. Generated assets remain outside Git. Replacing input images requires new masks and guides. Re-running workflow 19 saves new outputs without replacing the curated fixed inputs.
