# FlashVSR：配置、超分与编码

节点分类：`ToolBox/FlashVSR`。这是本地编排代码迁移，底层模型推理仍来自独立的 [ComfyUI_FlashVSR](https://github.com/smthemex/ComfyUI_FlashVSR)。来源、固定版本与历史本地文件哈希见 [provenance.json](../nodes/flashvsr/provenance.json)。

## 连接与输出

`LoadVideo → FlashVSR Upscale → Video Encode`，另将 `FlashVSR Config.config` 连接到 Upscale。示例在 [examples/flashvsr](../examples/flashvsr)。输入要求本地文件支持的标准 VIDEO；不会偷偷把整段 IMAGE 批次编码到内存。

| 节点 | 输出 | 执行时机 |
|---|---|---|
| FlashVSR Config | config | 校验参数，不加载模型 |
| FlashVSR Upscale | video、info_json | 磁盘模式完成推理；stream只返回准备好的任务 |
| Video Encode | video、info_json | 独立选择编码器/质量/容器/保存目录；stream在此执行推理 |

`video` 是标准 ComfyUI VIDEO 对象。`info_json` 是合法 JSON **文本**，可以连接显示、JSON解析、文本保存节点，由使用者决定如何处理；不是运行报告文件路径，也不自动导出用户报告。节点同时提供只读信息预览。

stream 在 Upscale 的状态为 `prepared`，Encode 完成后才返回 `completed` 和实际耗时。磁盘模式 Upscale 返回 `upscaled`；换编码参数可复用完整缓存。JSON还包含实际分块、seed、帧率、模型加载次数、资源计量口径、缓存预估与编码回退原因。

## 缓存方式必须由使用者选择

默认 `请选择`，未选择时在加载模型前停止。没有自动替你选择的缓存模式。

| cache_mode | 行为 | 代价 |
|---|---|---|
| raw | RGB8/NUT整段缓存，之后独立编码 | 约`宽×高×帧数×3`字节，可重复编码；音频与分块暂存另计 |
| lossless | RGB8→FFV1/bgr0无损MKV缓存 | 大小依内容变化，增加中间编码和解码耗时 |
| stream | 逐段计算，直接送最终编码器 | 没有整段帧缓存；再次编码需要重新推理 |

10秒8K（4320×7680、24fps）原始帧约 **22.25 GiB**；18.2167秒4K（2160×3840、60fps、1093帧）约 **25.33 GiB**。这是磁盘缓存估计，**不是**内存/显存需求；临时分块、音频及文件封装另计。预检显示磁盘余量与原始缓存估计，FFV1实际写入额度由运行监控检查，不承诺固定压缩比。

`tile_storage` 控制每段空间块暂存，独立于整段缓存模式：`disk` 为可回收的临时RGB映射；`ram` 将分块累计保留在RAM。`cache_directory` 留空使用 ComfyUI temp；可指定有足够空间的磁盘目录，每个任务使用独立受管子目录。

`cache_retention=cleanup_after_encode` 在**编码成功后**清理本任务缓存；`keep` 保留供重编码。编码失败保留完整缓存，取消/失败清理未完成文件。Upscale信息预览下的“清理此任务缓存”只清理当前受管任务；清理会更新缓存代数，使下一次队列正确重新执行超分。缓存清单仅用于恢复/失效管理，不是强制报告导出。

需要多个下游读取原始帧缓存时选择keep。本模块Encode的video输出是已保存文件引用，清理后仍可继续处理；标准SaveVideo返回原输入对象，若其上游缓存已按策略清理，应重新运行Upscale或使用keep。

最终视频应保存到受管帧缓存目录之外，本模块会拒绝冲突路径，避免“编码成功后清理”连同最终视频一起删除。

## 分块与资源

默认保持原片平均帧率（fps=0）和比例，方向auto，适配目标2K/4K/8K画布并补灰边。时长0处理到片尾；指定fps时显式转为恒定帧率。支持竖屏，尾段按实际帧数处理。空间块尺寸以 **LQ像素** 计，模型输出为其4倍；块宽高至少128且32对齐，重叠必须小于块尺寸。

| preset | 每段帧数 | LQ块 / 重叠 |
|---|---:|---|
| low_memory（默认） | 8 | 256×256 / 32×32 |
| balanced | 32 | 384×384 / 64×64 |
| tested | 120 | 按分辨率/方向复用本机已测几何，见JSON实际位置 |
| custom | 可调 | chunk_frames、tile_width/height、overlap_x/y全部可调 |

块尺寸会限制到对齐后的整幅LQ尺寸，边缘补齐后裁回目标；实际重叠权重归一化，处理非整除及多重重叠。减小时间/空间块可能改变速度、时序边界或接缝，不会静默降低输出分辨率/帧率。tested来自32GB RTX5090D、94GiB主机，不能作为小机器可运行保证。

- `memory_budget_gib`：当前**整个ComfyUI进程树RSS**上限，包含已有节点和共享映射；0不设此上限。
- `memory_reserve_gib`：主机可用RAM保留量，默认2GiB。
- `disk_budget_gib`：当前任务缓存写入额度，0不设额度；最终保存视频不属于该缓存额度。
- `disk_reserve_gib`：缓存/输出文件系统空闲保留量，默认1GiB。

预检只是图像缓冲估计，模型/驱动开销仍可变。运行时约0.2秒采样，在块/帧之间协作检查取消和预算；**无法保证拦截一次瞬时CUDA/主机OOM**。不足时明确报错并建议减小参数，不自动换模式或缩块。CUDA调用中的取消需等下一安全检查点。

VIDEO的尺寸、时长和帧数查询不会物化全片。`GetVideoComponents`之类操作需要整段float32 IMAGE，会先估算内存，超预算时拒绝；stream不提供隐式整片IMAGE物化，应先编码或显式选择磁盘模式。

## 编码与保存

提供 `auto / libx264 / libx265 / h264_nvenc / hevc_nvenc`。auto是使用者可明确选择的策略：2K/4K先探测H.264 NVENC，8K先探测HEVC NVENC，失败则CPU H.264并在JSON记录原因。手动指定不可用编码器则报错；探测使用实际尺寸/帧率，在正式编码前完成。stream模式也在推理前探测；磁盘模式的超分已经由上游独立完成，编码探测失败时保留完整缓存，便于换编码器重试。

CPU质量参数是CRF、NVENC是CQ，数值不表示相同质量。preset=auto对应CPU fast或NVENC p5；手动预设必须匹配编码器。保存可选temp或output，默认temp；返回已编码的标准VIDEO和JSON，可继续接其他节点。支持标准SaveVideo的H.264保存接口；HDR/10bit及AV1不作隐式转换。

## 安装与迁移

ComfyUI自身已有Torch；可按需安装 [requirements-flashvsr.txt](../requirements-flashvsr.txt)，不要为本模块自动升级Torch/CUDA。FFmpeg和ffprobe必须在PATH中。

外部插件固定提交：`153cf03343a116c85aee40d291125921cc33935a`。模型固定 [ruchangyao/FlashVSR_plus](https://huggingface.co/ruchangyao/FlashVSR_plus) revision `46b79520946ac67dec94d1566490690953c7debc`，四个文件放在 `ComfyUI/models/FlashVSR/`：

`turbo_dit_plus.safetensors`、`lq_proj_in_plus_turbo.safetensors`、`TCDecoder_plus.ckpt`、`posi_prompt_plus.pth`。Config可选择文件名，模型不自动下载。Triton后端需上游附带flashvsr-attn算子；也可显式选sdpa，性能/显存不同。

模型推理仍需受支持的NVIDIA CUDA环境，CPU编码不等于CPU推理。NVENC为可选编码能力；普通容器用 `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` 注入匹配驱动库。本机兼容适配器可读取已有隐藏runtime的NVENC库清单，驱动版本不符时仅相应NVENC探测失败，不阻止显式CPU编码。驱动二进制不进入仓库。

当前推理配置为FlashVSR+ Turbo、BF16、temporal=4，模型文件选项用于选择兼容的Turbo权重，图像流程为RGB8 SDR/sRGB。缓存复用时，upscale_resources和超分阶段耗时属于原缓存生成记录；当前保存耗时/资源单独在encode字段中，不能相加冒充本次队列总耗时。

原本地编排迁入ToolBox，仅注册三个新ID；旧 `LocalFlashVSRVideo` 和 `LocalFlashVSR8KOptimizedCore` 不提供兼容别名。本地正式01–07工作流更新为显式连线，旧测试目录不恢复。旧图和独立插件停用前备份在仓库外；保持外部FlashVSR依赖与模型。

历史数据、截图及本次迁移验证见 [测试记录](testing/flashvsr_2026-10-19.md)。仓库只保存统计/文档和对比截图，不包含测试视频、模型或缓存。

在现有ComfyUI Python环境验证编排（测试使用真实VIDEO/FFmpeg和合成推理适配器，不下载模型）：

```bash
COMFY_ROOT=/root/ComfyUI OMP_NUM_THREADS=4 python3.13 -m pytest --confcutdir=tests tests/test_flashvsr.py -q
```

真实模型短片接口检查另由 `scripts/validate_flashvsr_live.py` 执行，依赖本机已有输入视频和模型；生成媒体位于仓库外并在验证后清理。`scripts/build_flashvsr_history.py` 仅整理旧数据和提取截图，不重新超分。部署使用 `scripts/deploy_flashvsr_local.py`，仅增量复制FlashVSR模块/注册项，不覆盖整个已安装ToolBox或其他未提交工作。

## 图像放大：直接使用上游原生节点

[08图像8K示例（效果一般）](../examples/flashvsr/08_FlashVSR_图像8K_4320x7680_原生分块_效果一般.json) 使用 `LoadImage → SplitImageToTileList → FlashVSR_SM_KSampler → FlashVSR_SM_Decoder → ImageMergeTileList → SaveImage`，另接共享的 `FlashVSR_SM_Model` 和 `FlashVSR_SM_Vae`。切块和合成节点来自本机ComfyUI内置 `comfy_extras.nodes_images`，无需新增ToolBox节点或分块插件；旧版本ComfyUI可能尚无这两个内置节点。

本例针对1440×2560竖图：原图块512×640、重叠128，共20块；每块scale=3、输出1536×1920，按384重叠融合为4320×7680。没有先缩小原图，也没有裁剪主体。KSampler宽高与切块相同，块尺寸乘scale必须128对齐；否则上游会中心裁剪。更换输入尺寸时，必须同步设置合成宽高为实际输入宽高乘scale。

必须保留**IMAGE列表**语义，使每块独立作为单图推理；不能将不同空间块合并为视频帧批次。此流程会在RAM中缓存各块latent/IMAGE，不具备视频三节点的预算保护及磁盘暂存策略。模型节点共享，offload可由使用者调整；不保证其他显存/内存环境运行。

本例实测尺寸、节点连接和PNG输出通过，**画质未验收通过**：对该参考图，模型加入明显的皮肤颗粒和布料短线纹理，不能将“像素更多”当成“更忠实”。图像试验、控制变量对照和可选处理策略见[图像测试记录](testing/flashvsr_image_2026-10-19.md)。更改策略前由使用者选择；不默认替换模型或套用混合比例。
