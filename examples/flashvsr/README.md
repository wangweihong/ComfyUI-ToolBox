# FlashVSR 示例

01–07视频示例使用LoadVideo、Config、Upscale、Encode显式连接，缓存模式均保留“请选择”，使用者需先选择。默认低内存配置、原片帧率和比例；目标分辨率与片段见文件名及Config。

08为上游原生图像分块超分，1440×2560参考图放大到4320×7680，不依赖ToolBox视频节点。尺寸/接口已验证，但本图出现过强的皮肤和织物纹理，作为可复现试验保留，不代表画质验收通过。换图需同步修改合成尺寸。生成脚本：scripts/build_flashvsr_image_example.py。

[使用说明与依赖](../../docs/flashvsr.md) · [视频实测及对比截图](../../docs/testing/flashvsr_2026-10-19.md) · [图像试验与画质诊断](../../docs/testing/flashvsr_image_2026-10-19.md)。示例不包含原图、视频或模型。
