# FLUX.2 Klein 增强与身份迁移

ToolBox 内置 Flux2Klein Enhancer 的全部 16 个节点，菜单分类统一为 `ToolBox/Flux2Klein`。原节点 ID、显示名称、输入输出、参数顺序、默认值和计算逻辑保留，已有工作流无需替换节点。

## 安装与升级

1. 更新 `ComfyUI/custom_nodes/ComfyUI-ToolBox`。
2. 若已安装独立的 `ComfyUI-Flux2Klein-Enhancer`，将其移出 `custom_nodes` 或通过管理器禁用，再重启 ComfyUI、刷新页面。两个插件使用同一组节点 ID，同时加载时实际采用的实现可能取决于加载顺序。
3. 在 `ToolBox/Flux2Klein` 中添加节点，或打开 [原始示例](../examples/flux2_klein/README.md)。

不需要单独克隆原仓库。运行依赖为 ComfyUI 及其提供的 PyTorch、tqdm；没有额外模型下载、安装脚本或网络请求。生成仍需自行配置匹配的 FLUX.2 Klein 模型、文本编码器、VAE 和输入图片。

本次只迁移 ToolBox。外部 ComfyUI-Custom 构建脚本若仍克隆已删除的仓库，或将 ToolBox 固定在迁移前的提交，仍需另行调整；离线缓存中的独立原插件也需在后续构建迁移时处理。

## 节点一览

以下为稳定节点 ID，括号中为菜单显示名称。

| 节点 ID | 显示名称 | 用途 |
| --- | --- | --- |
| `Flux2KleinEnhancer` | FLUX.2 Klein Enhancer | 活跃文本 token 缩放、白化、范数均衡和三段 Qwen3 层缩放 |
| `Flux2KleinTextEnhancer` | FLUX.2 Klein Text Enhancer | 文本 magnitude、contrast 与 normalize_strength 控制 |
| `Flux2KleinSectionedEncoder` | FLUX.2 Klein Sectioned Encoder | 分段编码 front/mid/end，附带 token 区间元数据 |
| `Flux2KleinDetailController` | FLUX.2 Klein Detail Controller | 按分段区间调整文本权重；缺少区间时使用原有比例切分 |
| `Flux2KleinRefLatentController` | FLUX.2 Klein Ref Latent Controller | 对指定参考图注册注意力 K/V 权重补丁，支持空间渐变 |
| `Flux2KleinTextRefBalance` | FLUX.2 Klein Text/Ref Balance | 调整文本与参考图注意力比例 |
| `Flux2KleinRefLatentWeight` | FLUX.2 Klein Ref Latent Weight | 对指定参考图注册注意力 K/V 权重补丁 |
| `Flux2KleinMultiReferenceLatent` | Multi ReferenceLatent | 将最多八个 latent 输入按顺序写入参考元数据，批次逐项展开 |
| `Flux2KleinMaskRefController` | FLUX.2 Klein Mask Ref Controller | 根据遮罩衰减指定参考 latent，支持反转和羽化 |
| `Flux2KleinColorAnchor` | FLUX.2 Klein Color Anchor | 通过采样回调向参考 latent 的通道均值校正 |
| `IdentityGuidance` | FLUX.2 Klein Identity Guidance | 采样预测校正，支持 adaptive、direct、channel_match |
| `IdentityFeatureTransfer` | FLUX.2 Klein Identity Feature Transfer | 基础身份特征迁移 |
| `IdentityFeatureTransferAdvanced` | FLUX.2 Klein Identity Feature Transfer Advanced | 参考选择与多种高级迁移模式 |
| `IdentityFeatureTransferV3` | FLUX.2 Klein Identity Feature Transfer V3 | 带预设、双流/单流块调度的迁移 |
| `IdentityFeatureTransferFinal` | Identity Feature Transfer Final | 多参考、主体遮罩及可选 SIGMAS 调度的迁移 |
| `Flux2KleinKSamplerExperimental` | Flux2Klein KSampler Experimental | 实验采样器，直接调用扩散模型 forward |

## 连接方式

- **文本增强**：`CLIPTextEncode → Flux2KleinEnhancer / Flux2KleinTextEnhancer → 采样器 positive`。
- **分段控制**：`Flux2KleinSectionedEncoder → Flux2KleinDetailController → 采样器 positive`。分段编码器生成的 `klein_sections` 元数据用于精确分段。
- **多参考**：各参考图经 VAE 编码后连接 `Flux2KleinMultiReferenceLatent` 的 `latent_1…latent_8`，同时连接文本 conditioning；输出连接采样器 positive。
- **遮罩与参考权重**：在含有 `reference_latents` 的 conditioning 链上连接相应节点。参考索引从 0 开始。
- **模型补丁**：参考控制、身份迁移和颜色锚定节点输出的 MODEL 必须连接到实际使用的采样器；有 CONDITIONING 输出时也应继续传递。

身份迁移各版本并存以兼容已有工作流，迁移未自动升级或替换旧版本。参数范围和中性值沿用备份代码，具体以节点面板为准。

实验采样器保留原实现及其名称。它直接调用扩散模型，不能据此假定与标准采样器具有相同的模型补丁、LoRA 或回调行为；需要身份迁移补丁的工作流优先沿用示例中的标准采样链。

## 来源与验证

来源为本地完整备份的提交 `1e3926bb9323289f5acce2cf8dfece6d2b70126c`。备份的项目元数据版本为 3.4.3，原包入口版本为 3.4.0；迁移以实际文件为准。功能模块和原始示例逐字节保留，来源与 SHA-256 校验值见 [迁移清单](../nodes/flux2_klein/provenance.json)。分类变更位于 ToolBox 包入口。

合成张量与模拟模型测试覆盖接口、文本增强、参考 latent、遮罩和模型补丁；这些测试不代表真实模型出图效果。执行记录见 [迁移验证](testing/flux2_klein_2026-10-19.md)。
