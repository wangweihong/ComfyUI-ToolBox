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

## 使用

1. `LoadImage → NFStockingEditor`，先执行一次，让编辑器取得上游底图。生成图同样需要先运行上游。
2. 点击“编辑丝袜引导”，涂出部位；走向线沿一条横纹横穿部位，通常每个部位 1–3 条。
3. 折叠表面串线时，用隔开线沿交界绘制。窗口自动显示求解等值线；编辑期间保留草稿，点击“保存并关闭”才写入 `guides_json`。
4. 将图像与引导连到 `NFStockingSolve`，再将图像和字段连到 `NFStockingRender`。
5. 在 **渲染节点** 点击“选样式 / 调参数 / 预览”。左侧选样式、拖动滑杆，中间整体拖分界线对比，右侧细节查看 100%/200% 原像素。预览使用最近一次队列执行的求解结果；修改引导后重新执行工作流。
6. 成品接 `SaveImage`；诊断图可接 `PreviewImage`。红色为密度衰减、蓝色为颜色排除、黄色为缺少走向引导。

编辑快捷键：B 画笔、E 橡皮、P 走向、W 隔开、S 点选；Ctrl/Cmd+Z 撤销，Shift+Ctrl/Cmd+Z 重做。
滚轮缩放，中键或空格拖动平移。100%/200% 查看原像素；右键或工具栏按钮删除当前部位最后一条线。
“取消”或 Esc 直接关闭并放弃本次草稿，已有保存内容保留。正式运行工作流前先保存草稿。
未连接 SAM 时，点选按钮被禁用，工具栏下方会说明需要连接模型并重新运行；连接后同一区域显示使用提示。
部位列表靠后的遮罩优先。外部 MASK 连接后可作为部位底图，手绘添加与擦除独立保存。
尺寸改变时点击节点的“清空引导”按钮，再执行并重新绘制；不会自动拉伸旧坐标。

### 纹理参数

部位与走向编辑器负责选区和引导；样式与亮点在 `NFStockingRender` 中调整。04 工作流的五个渲染节点可以各自调整参数，彼此独立。

| 控制 | 范围与行为 |
| --- | --- |
| 样式 | 细线、针织、斜单线、加濑风、油光（试验） |
| 密度 | 40–200%，控制横纹疏密；报告显示实际周期及密度限制 |
| 纹理强度 | 0–250%；默认自动，按丝袜深浅决定实际强度；拖动滑杆切换为手动，可勾选恢复自动 |
| 斜度 | 0–75°；仅在斜单线样式显示并生效 |
| 亮点 | 深度、画面亮部、输入遮罩、均匀分布四种来源，各为 0–300%，可混用；与纹理强度独立 |
| 颜色排除 | 默认开；透肤膝盖被误排除时可关 |
| 随机种子 | 保证重复预览和执行的亮点点位一致 |

深度亮点需将灰度深度图连接到求解节点；遮罩亮点需将 MASK 接到渲染节点的 `sparkle_mask`。均匀亮点和画面亮部无需模型。
上游“亮点”指纱线反光的分布量，没有单独的全图曝光/亮度滑杆。油光依赖原画已有高光，适合纯色深色丝袜。

滑杆拖动时采用约 300ms 防抖更新，参数直接写入当前渲染节点，随工作流保存。关闭窗口后重新运行工作流才更新正式输出。
整体视图为缩略图，左原图、右效果；点击图像定位细节，拖分界线或下方滑杆对比。右侧细节与正式导出使用同一渲染函数和种子，
100%/200% 关闭插值，不缩小原像素。参数改变时一次全图渲染同时产生整体和细节；仅平移时只渲染局部，不重复求解。

`IMAGE` 为 `[B,H,W,C]` RGB 浮点 [0,1]；`MASK` 为 `[B,H,W]`，1 表示应用纹理。
外部 MASK、深度和亮点遮罩数量为 1 或 B；遮罩尺寸必须与图像一致。
共享引导要求批次图像构图一致；逐图模式为每张图保存完整部位与折线。不包含视频跟踪或时序稳定。

透明图层输出是“已处理 RGB + layer_alpha（1 表示不透明）”，不是纹理差值。
用 `ImageCompositeMasked` 以原图作 destination、图层作 source、layer_alpha 作 mask，可重建成品。
标准 `JoinImageWithAlpha` 把 MASK 理解为透明度，因此保存透明 PNG 前需 `InvertMask(layer_alpha)`；
示例工作流已经连接好了。遮罩外的原始浮点像素严格保留。

## 可选模型

- SAM：将 Meta ViT-B 权重 `sam_vit_b_01ec64.pth` 放到 `ComfyUI/models/sams/`，
  `NFStockingSAMLoader → NFStockingEditor.sam`。第一次点击加载模型并计算 embedding；小、中、大候选按面积排序。
  左键预览添加、右键预览减去，返回后自动高亮推荐范围；小／中／大只切换预览，点击“应用选区”才修改草稿。
  点选预览会自动打开主画布的左右对比：左侧原图，右侧选区效果；绿色表示添加，红色表示将减去的范围。
  拖动竖直手柄或底部滑杆调整分界，“对比居中”恢复 50%；手柄支持方向键及 Home/End。
  取消本次点选不会修改选区；应用可撤销，保存并关闭后持久化遮罩，重开工作流无需重新点选。
  候选和分界位置只属于当前编辑窗口，不写入工作流；应用时保留候选等待期间的画笔修改。
  当前会话的设备选项显示在编辑器中；修改加载节点的设备后需要重新执行工作流。
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

预览路由 `/toolbox/stocking/image`、`/preview`、`/sam` 只处理节点最近一次执行产生的会话。
预览请求按 client/revision 拒绝旧版本，限两条工作线程并在前端 300ms 防抖；正式执行仅以已保存节点参数为准。
缓存有字节和条目上限（部位 256MiB、场景 1GiB/4条、底图会话 512MiB/8条），淘汰后需重跑节点。
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
