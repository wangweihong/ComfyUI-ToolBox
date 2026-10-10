# 丝袜纹理节点

节点位于 `南风节点/丝袜纹理`，由 ComfyUI-ToolBox 注册。五种样式依次为 `knit`（细线）、`loops`（针织）、
`lines`（斜单线）、`grain`（加濑风）、`oily`（油光，试验）。不需要扩散模型；手工流程无需 SAM 或深度模型。

## 安装和升级

将更新后的 ComfyUI-ToolBox 放入 `ComfyUI/custom_nodes/ComfyUI-ToolBox`，重启 ComfyUI 后刷新网页。
已有 Docker 持久化节点目录不会因更新镜像自动覆盖，请在实际挂载的 ToolBox 仓库更新。
新安装和升级使用同一份根目录节点映射；不需要修改 ComfyUI-Custom 的 Dockerfile。

核心依赖：NumPy、SciPy、OpenCV、contourpy、Pillow。若已有 ComfyUI 环境满足依赖，无需重装。

```bash
python -m pip install "numpy>=1.26" "scipy>=1.11" "opencv-python>=4.8" "contourpy>=1.2" "Pillow>=10"
# 可选点选/深度辅助；使用现有 ComfyUI 的 torch 和 torchvision
python -m pip install -r requirements-stocking-models.txt
```

ToolBox 原有 `requirements.txt` 的 Transformers 约束维持原状；本功能兼容 Transformers 4/5 的深度 API，
不要为了本功能单独替换已有 Torch/CUDA 或强行降级容器依赖。导入节点和模型节点执行均不会自动联网下载模型。

## 推荐：一体化编辑与批处理

`LoadImage → NFStockingTexture → PreviewImage / SaveImage`。点击主节点的「编辑与预览」即可准备当前底图，
无需先运行完整工作流。标准 LoadImage 可直接读取；其他上游结果只执行必要祖先和内部捕获节点，
不会执行后续比较或保存节点，也不会推进种子控制。未保存的草稿不参与正式队列执行。

窗口包含「部位／走向／纹理」三页：

1. 部位页可用画笔、橡皮，或连接原有 `NFStockingSAMLoader → sam` 点选。左键添加、右键减去，
   自动预览推荐候选，小／中／大切换，点击「应用选区」才修改草稿；取消不修改遮罩。左右拖动对比保留。
2. `Easy-Sam3 Model Loader` 的 image 模型接到 `sam3_model`，可按文本识别丝袜。
   默认 `stockings`、阈值 0.4；可尝试 `pantyhose`、`tights`。逐图识别，实例可选择、预览、应用，
   应用后仍可用原有点选和画笔修边。SAM3 与 ViT-B 为两个独立输入，未连接 SAM3 仍可手工编辑。
3. 没有有效手绘走向的连通区域，会按 PCA 主轴在 25/50/75% 位置生成横向基础引导，显示为虚线。
   手绘引导优先；折腿、遮挡或复杂弯曲建议修正走向和隔开线。基础走向是二维近似。
4. 纹理页显示真实渲染、原图分界对比，以及 100%/200% 细节。五种样式、强度和亮点在同一窗口调整。
   状态显示选区比例、实际变化像素比例、走向来源及未生效原因；选区高亮不等于纹理已生效。
5. 「保存并关闭」提交部位和参数；「取消」、×、Esc 放弃本次草稿。正式运行得到成品。

手工数据以图片内容指纹和尺寸绑定；换图自动恢复该图记录或开始空草稿，不拉伸或复用其他图的遮罩。
旧 v1 引导必须显式导入并确认属于当前图片。外部 MASK 可作部位底图，添加和擦除叠加保存。
上游连接控制的参数在编辑器内只读，预览使用底图准备时解析的值。

批量处理使用标准 IMAGE 批次，SAM3 对每张图独立识别；匹配的手工记录优先。
默认跳过无目标、无有效走向或没有变化的图片，报告保留所有输入索引；全批失败时报错。
只输出成功图像，`source_images` 是成功图片对应的原图，供图层重合成使用。
异尺寸图片需逐张排队，不自动缩放；不包含视频跟踪或时序稳定。

输出顺序：`image / stocking_layer / layer_alpha / regions_mask / diagnostics / source_images / report`。
所有图像和遮罩输出有相同成功批次数 B'。普通图层合成使用 `source_images` 为 destination。

高级分步节点 `NFStockingEditor / Solve / Render` 保留原接口；渲染节点直接设置参数。
推荐工作流使用一体化窗口，避免多个参数编辑入口。编辑快捷键：B 画笔、E 橡皮、P 走向、W 隔开、S 点选，
Ctrl/Cmd+Z 撤销，Shift+Ctrl/Cmd+Z 重做；滚轮缩放、中键或空格平移。

### 纹理参数

推荐节点在统一窗口的「纹理」页调整全部参数；高级 `NFStockingRender` 保留相同参数。04 工作流五个一体化节点分别对应五种样式。

| 控制 | 范围与行为 |
| --- | --- |
| 样式 | 细线、针织、斜单线、加濑风、油光（试验） |
| 密度 | 40–200%，控制横纹疏密；报告显示实际周期及密度限制 |
| 纹理强度 | 0–250%；默认自动，按丝袜深浅决定实际强度；拖动滑杆切换为手动，可勾选恢复自动 |
| 斜度 | 0–75°；仅在斜单线样式显示并生效 |
| 亮点 | 深度、画面亮部、输入遮罩、均匀分布四种来源，各为 0–300%，可混用；与纹理强度独立 |
| 颜色排除 | 默认开；透肤膝盖被误排除时可关 |
| 随机种子 | 保证重复预览和执行的亮点点位一致 |

深度亮点需将灰度深度图连接到一体化节点（高级流程连接求解节点）；遮罩亮点需连接 `sparkle_mask`。均匀亮点和画面亮部无需模型。
上游“亮点”指纱线反光的分布量，没有单独的全图曝光/亮度滑杆。油光依赖原画已有高光，适合纯色深色丝袜。

滑杆拖动约 300ms 防抖更新草稿预览，保存并关闭后写入节点；正式执行读取已保存参数。
整体视图为缩略图，左原图、右效果；点击图像定位细节，拖分界线或下方滑杆对比。右侧细节与正式导出使用同一渲染函数和种子，
100%/200% 关闭插值，不缩小原像素。参数改变时一次全图渲染同时产生整体和细节；走向缓存按部位复用；样式和强度变化不重新求解。

`IMAGE` 为 `[B,H,W,C]` RGB 浮点 [0,1]；`MASK` 为 `[B,H,W]`，1 表示应用纹理。
外部 MASK、深度和亮点遮罩数量为 1 或 B；遮罩尺寸必须与图像一致。
共享引导要求批次图像构图一致；逐图模式为每张图保存完整部位与折线。不包含视频跟踪或时序稳定。

透明图层输出是“已处理 RGB + layer_alpha（1 表示不透明）”，不是纹理差值。
用 `ImageCompositeMasked` 以原图作 destination、图层作 source、layer_alpha 作 mask，可重建成品。
标准 `JoinImageWithAlpha` 把 MASK 理解为透明度，因此保存透明 PNG 前需 `InvertMask(layer_alpha)`；
示例工作流已经连接好了。遮罩外的原始浮点像素严格保留。

## 可选模型

- SAM3：复用已安装的 ComfyUI-Easy-Sam3 的 `easy sam3ModelLoader`，选择 image，使用本地 `sam3.pt`。
  ToolBox 不捆绑 SAM3 框架或下载权重，不更换 Torch/CUDA。模型推理后回到 CPU，分割遮罩缓存上限 64MiB。
  正式队列忙时语义预览等待，已有遮罩的 CPU 纹理预览可继续。
  当前验收为 SAM3 静态图像；不声明 SAM3.1 视频权重可直接用于图像加载器。
  CPU 推理已验证；当前 Easy-Sam3 版本的加载器初始化仍有 CUDA 依赖，纯 CPU 机器需要支持 CPU 初始化的版本。

- SAM：将 Meta ViT-B 权重 `sam_vit_b_01ec64.pth` 放到 `ComfyUI/models/sams/`，
  `NFStockingSAMLoader → NFStockingTexture.sam`（高级编辑器同样支持）。第一次点击加载模型并计算 embedding；小、中、大候选按面积排序。
  左键预览添加、右键预览减去，返回后自动高亮推荐范围；小／中／大只切换预览，点击“应用选区”才修改草稿。
  点选预览会自动打开主画布的左右对比：左侧原图，右侧选区效果；绿色表示添加，红色表示将减去的范围。
  拖动竖直手柄或底部滑杆调整分界，“对比居中”恢复 50%；手柄支持方向键及 Home/End。
  取消本次点选不会修改选区；应用可撤销，保存并关闭后持久化遮罩，重开工作流无需重新点选。
  候选和分界位置只属于当前编辑窗口，不写入工作流；应用时保留候选等待期间的画笔修改。
  当前会话的设备选项显示在编辑器中；修改加载节点的设备后重新打开编辑器准备底图。
  SAM 使用独立的等待状态和请求标识，走向预览或继续绘制不会丢弃候选；返回后显示实际设备、耗时和 embedding 是否复用。
  可取消等待；超过 120 秒会停止前端等待并提示检查容器日志（后台已开始的推理可能仍在完成）。
- 深度：将 [Depth-Anything-V2-Small-hf](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf)
  的完整目录（config、processor、weights）放到 `ComfyUI/models/stocking_texture/Depth-Anything-V2-Small-hf/`。
  `NFStockingDepth → NFStockingSolve.depth`；输出白色更近。
- 可以直接连接现有 Depth Anything 等节点的灰度 IMAGE。选择白色/黑色更近；伪彩色图会报错。
  深度图可缩放到原图尺寸，常量深度等同无有效深度。

模型按需加载，推理后回到 CPU；一次只缓存一个 SAM 和一个深度模型。无 CUDA 时使用 CPU。
因此点击期间 GPU 运算和显存增加可能很短暂；以完成提示的实际设备和容器 `[ToolBox SAM]` 日志判断，不能只靠监控刷新时的瞬时读数。
显式 cuda 在 CUDA 可用时使用 CUDA；auto 遵循 ComfyUI 的计算设备设置。
无深度时，手绘隔开线有效，深度亮点和自动隔开跳过并写入报告。油光依赖原画已有高光，效果有局限。

## 引导格式与 API

一体化节点使用 `{"version":2,"records":{"<图片内容指纹>":<v1 单帧引导>}}`。
空 JSON 可用于逐图语义或外部 MASK 自动流程；内容指纹使用适配层 `data.digest(image)`，
其中 image 是 RGB float32 的 HWC 数组。临时候选、会话 token、对比分界位置不持久化。

以下 v1 格式供高级分步节点使用；一体化编辑器可显式导入。

`guides_json` 是自包含 JSON，包含版本、原图尺寸、frames、部位 id/name、external、mask/erase 和 strokes/walls。
遮罩为同尺寸灰度 PNG 的 base64，无损保存；折线为原图坐标 `[x,y]`。
MASK 合成规则为 `max(输入底图, 手绘添加) * (1 - 擦除)`，求解域阈值为 0.5。
批次模式为 shared 或 per_image，后者 frames 数量必须等于 B。
导出的工作流和 API 提示不引用临时预览文件；无需浏览器连接即可执行。

```json
{"version":1,"width":512,"height":768,"frames":[{"regions":[
  {"id":"left","name":"左腿","external":true,"mask":"","erase":"",
   "strokes":[[[100,350],[150,330],[200,350]]],"walls":[]}
]}]}
```

默认参数保持上游调校：密度 100%、斜度 32°、自动纹理强度、颜色排除开启、深度/高光亮点各 100%。
各亮点来源独立控制；纹理强度不控制亮点。默认种子 20261005，批次逐张处理保持相同种子的随机点位规则。
报告为 JSON 数组，每张图包含实际周期、密度上限、衰减比例、实际强度、耗时、缓存命中和跳过原因。

预览路由 `/toolbox/stocking/prepare`、`/image`、`/preview`、`/sam`、`/semantic` 处理受限预览会话；底图准备不读取旧引导遮罩。
预览请求按 client/revision 拒绝旧版本，限两条工作线程并在前端 300ms 防抖；正式执行仅以已保存节点参数为准。
缓存有字节和条目上限（部位 256MiB、场景 1GiB/4条、底图会话 512MiB/8条），淘汰后重新打开编辑器准备底图。
超过单个预览缓存预算的大批次仍可队列渲染，应分批执行以获得交互预览；单图最多 16,777,216 像素。

## 示例和测试

`examples/stocking_texture/` 包含 manual、external-depth、sam、batch 四份可加载工作流，及对应 `.api.json`。
把 assets 中三个 `tb_stocking_demo*.png` 复制到 ComfyUI/input 后，加载示例。样图由项目脚本生成，可重新生成：

```bash
python scripts/generate_stocking_examples.py
python -m pytest --confcutdir=tests tests/test_stocking_texture.py -q
node --test tests/stocking_geometry.test.mjs
node --test tests/stocking_editor_state.test.mjs
node --test tests/stocking_render_controls.test.mjs
node --test tests/stocking_selection.test.mjs
python scripts/test_stocking_api.py --url http://127.0.0.1:8188 --include-sam
python scripts/benchmark_stocking_texture.py --output /tmp/stocking-benchmark.json
```

基础测试不需要私有样图、网络或模型。真实插画的视觉验收、SAM/深度模型推理及性能测量单独记录，
不能用缺少公开样图的跳过结果代替核心测试。源码来源、改动和 MIT 许可见 `nodes/stocking_texture/UPSTREAM.md`。

本次结果与截图见 [2026-10-09 验收记录](testing/stocking_validation_2026-10-09.md)。
SAM 候选自动预览、左右对比及容器更新验证见 [2026-10-10 选区预览验收](testing/stocking_selection_2026-10-10.md)。

### 按功能拆成五份工作流

推荐示例位于 `examples/stocking_texture/unified/`：01 手工与原有点选、02 SAM3 与点选修边、
03 深度与逐图批处理、04 五样式对比、05 图层合成与诊断。默认使用 PreviewImage，不自动保存未经处理的原图。
01 默认不连接模型，先打开编辑器选区再运行；连接旁边的 ViT-B 加载器可启用原有点选。
02–05 要求本地 Easy-Sam3 image 模型，03 另外需要深度模型。03 的两张图片须同尺寸，否则分开排队。
示例库使用公开合成图，容器工作流引用用户当前图片。
公开合成图适合手工/外部 MASK 验证；02–05 的语义流程请先换成包含丝袜的实际图片。

```bash
python scripts/generate_stocking_unified_workflows.py --image-name your_image.png --output /path/to/workflows
```

以下脚本仍用于生成高级分步示例：

可使用现有图片和引导文件生成五份独立工作流：手工选区与走向引导、SAM 点选与遮罩修边、深度辅助与贴体纹理、
五种纹理并排对比、透明图层合成与问题诊断。图片仅按 ComfyUI input 文件名引用，不嵌入工作流。

```bash
python scripts/generate_stocking_function_workflows.py \
  --image /path/to/reference.png --image-name reference.png \
  --guides /path/to/guides.json --output /path/to/workflows \
  --density 60 --url http://127.0.0.1:8188
python -m unittest discover -s tests -p test_stocking_function_workflows.py
```

每份生成一个可在界面打开的 `.json` 和一个队列/API 用的 `.api.json`。
03 要求本地 Small 模型；02 首次运行只加载 SAM 句柄，需在编辑器中点击选区。
04 已连接 SAM 句柄以支持编辑器点选，五种样式仍共用同一求解结果和其余参数，便于公平比较；05 同时导出透明图层、重合成结果和诊断图。

本次一体化节点的队列、批次及界面验收见 [2026-10-10 一体化验收](testing/stocking_unified_2026-10-10.md)。
