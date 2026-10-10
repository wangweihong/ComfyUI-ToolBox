# 丝袜纹理节点

节点位于 `南风节点/丝袜纹理`，由 ComfyUI-ToolBox 注册。原有五种样式依次为 `knit`（细线）、`loops`（针织）、
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
## 花纹、英文印花和钩丝

样式下拉框保留细线、针织、斜单线、加濑风、油光，并新增波点、爱心、菱格、小渔网、大渔网、蕾丝、花卉、豹纹。
在统一编辑器的「纹理」页调整「基础样式」「花纹」「英文印花」「损伤」。新花纹有织物和印花两种表现：织物结合原图明暗，印花保留指定颜色与清晰轮廓；都会沿腿部弧度变形。

花纹大小与原有织纹密度独立。100% 对应 1280×1920 参考尺寸，随图像面积缩放，支持 25–400%；旋转、颜色与不透明度可单独设置。英文印花默认关闭，内置 BALENCIAGA / PARIS 预设，也可输入最多 128 个英文、数字、空格和常见标点，保留大小写。文字错行重复，字号、行列间距、方向、颜色和不透明度独立可调，字母不会随左右腿镜像。

损伤默认关闭。启用后可选择随机、手工或随机＋手工，以及钩丝、梯状抽丝或混合类型。随机数量按每个部位计算，由现有随机种子和图片身份共同确定。手工定位工具可点击生成一段局部损伤，或拖动画出路径；选择目标部位后再绘制，右键/「删除最后损伤」删除最后一条，支持撤销重做。上游高级引导编辑器也提供「钩丝 D」工具，可选择钩丝或梯状抽丝，保存后重新运行求解与渲染节点。

统一窗口「保存并关闭」保存参数及图片绑定的损伤；取消或 Esc 放弃草稿。高级渲染节点在执行后可点击「预览纹理」，参数按原有方式直接写入节点。当前图像渲染不会生成裸肤底图；渔网、蕾丝和抽丝表现基于原图，不是替换服装或生成破洞。

一体化与高级渲染节点新增末尾可选 `effects_json` 输入，旧工作流省略它即可。格式示例：

```json
{
  "version": 1,
  "pattern": {"mode": "fabric", "size": 100, "rotation": 0, "color": "#000000", "opacity": 70},
  "text": {"enabled": true, "content": "BALENCIAGA", "size": 100, "spacing_x": 100, "spacing_y": 100, "rotation": -12, "color": "#000000", "opacity": 70},
  "damage": {"enabled": true, "mode": "both", "type": "mixed", "count": 5, "length": 100, "width": 100, "strength": 60}
}
```

引导的每个部位可增加 `damage_strokes`，例如 `[{"type":"ladder","points":[[100,200],[105,260]],"width":3}]`；单点会沿部位走向延伸，坐标为原图像素。缺省为空。修改损伤不会重算几何，效果缓存按参数与路径隔离，最多 128 MiB；花纹/字体图集缓存最多 16 MiB。预览和队列共用渲染，遮罩外原图与透明图层合成约定保持一致。

公开例子位于 `examples/stocking_texture/effects/`：06 花纹总览、07 英文印花、08 钩丝抽丝、09 组合效果。先把 `examples/stocking_texture/assets/tb_stocking_demo.png` 复制到 `ComfyUI/input/`，再加载示例。均使用项目合成图片，不需要 SAM3 或深度模型，不默认保存输出文件。

English: choose one of fourteen styles, then adjust Fabric/Print appearance, English lettering and Snags/Ladder runs in the texture panel. Lettering and damage are disabled by default. Text supports up to 128 printable ASCII characters; BALENCIAGA and PARIS are editable presets. Manual damage follows the selected region and image; Save and close commits the unified draft, while Cancel discards it. All effects preserve pixels outside the mask. The optional version-1 `effects_json` input and `damage_strokes` guide field are backward compatible. A bundled DejaVu Sans Bold font keeps offline lettering reproducible; its license is included with the font.

## 上游新版能力（f74c8ac）

原有十三种样式保持原 ID 与顺序，末尾新增 `coil`（线圈）。选「上游新版 f74c8ac」后，可使用透肤自适应 Coil、摩尔纹，以及新版油光的连续柔光带、黑色暗边与弱高光补偿。遮挡补全只连接高光，遮挡物不被涂上纹理。

一体化与高级渲染节点在原有可选输入后追加如下参数；原必填控件和输出端口顺序不变：

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `renderer_version` | `legacy` | `legacy` 保持旧结果；`upstream_f74c8ac` 使用新版 |
| `layer_mode` | `replacement` | 旧精确替换图层；`soft` 输出柔和丝袜图层 |
| `moire_on` | `false` | 开启主动摩尔纹，需新版和有效灰度深度图 |
| `moire` / `moire_area` | 100 / 100 | 强度与面积，均为 0–100 |
| `sparkle_link` | `false` | 关联深度和画面亮部亮点 |

未添加这些参数的旧工作流继续使用旧渲染和旧图层。Coil 或摩尔纹在兼容模式下会提示切换版本。启用摩尔纹但缺少有效深度时，预览提示问题，队列按失败处理选项报告，不能静默跳过。材质调整复用几何求解，版本切换只更换渲染场景缓存。

柔和图层使用覆盖率透明度，并提高必要位置的透明度以使 RGB 保持有效范围；浮点重合成误差不超过 `1e-6`，8 位 PNG 重合成每通道误差不超过一个灰阶。`layer_alpha` 仍为不透明度，连接标准 `JoinImageWithAlpha` 前仍需先反转 MASK。透明区域 RGB 为零。

### 部位编辑与预设

「切开 K」拖动切线，默认贴合附近线稿；也可自动分割。合并和镜像先选择目标部位：合并保留目标名称和颜色，镜像只替换目标走向线，并显示轮廓拟合误差。分割合并维护走向、隔开和手工损伤归属，一次操作可完整撤销。清空选区保留部位；新绘制和 SAM 添加范围从其他部位取得像素归属，加载旧遮罩时不改写原数据。

走向、隔开和损伤工具右键删除指针附近的线；自动隔开以虚线显示，其删除记录保存到每帧 `wall_erasures`，重开和重新求解后继续生效。横向、纵向引导和自动隔开可独立显示。部位可保存 `color`，每帧可保存亮点遮罩 `sparkle`；旧引导缺少字段时使用空值。

材质预设支持保存、覆盖、加载、删除、恢复默认及撤销。预设保存材质、种子、渲染选项与花纹文字损伤配置，不保存选区、图片、模型或手工损伤路径；自动强度在每张图重新计算。已连接的参数输入不会被预设覆盖。未来版本或损坏的预设标记为不可读取，读取不会重写文件。

### PSD 与自动恢复草稿

可选依赖：`python -m pip install -r requirements-stocking-psd.txt`。未安装时其他功能仍可使用。

- `NFStockingPSDLoad` 从 ComfyUI input 目录读取 PSD/PSB，输出底图、一体化 JSON、高级 JSON、亮点 MASK 和报告。识别中英文引导层，排除引导及旧纹理层以取得底图。
- `NFStockingPSDSave` 从高级引导对象或 JSON 按批次导出新的引导 PSD；不会覆盖原 PSD。导出含原图、部位颜色/遮罩、走向、亮点和手工隔开线。
- 编辑器支持导入同底图 PSD 引导，以及导出成品 PNG、柔和透明 PNG、引导 PSD。底图不匹配时请通过 PSD 加载节点导入。实验性叠底／减淡纹理 PSD 不开放。
- PSD 是上游引导交换格式，不保存 ToolBox 的文字、损伤、材质参数或自动隔开删除记录；继续编辑这些内容请保存 ComfyUI 工作流。
- 编辑 PSD 加载节点连接的引导后，保存修改会将引导转为编辑节点内保存，以便后续队列使用新引导。其他参数连接保持不变。

预设和草稿存入当前 ComfyUI 用户目录的 `toolbox_stocking/`。草稿在停止编辑一秒后独立保存源图、辅助数组、部位和参数，不写入节点；刷新或重启后重开可选择恢复或丢弃。「保存并关闭」、取消和丢弃会清除该草稿。恢复不保存撤销历史或模型对象；SAM 操作需要重新连接并获取模型。每用户最多八份草稿、共 512 MiB，超限按最近使用时间回收；写入失败不阻止正常保存节点。

新增公开工作流在 `examples/stocking_texture/upstream/`：10 Coil、11 摩尔纹、12 新旧油光、13 柔和图层组合、14 PSD 往返。均无需识别模型，11 使用公开合成深度图；14 还需复制 `assets/tb_stocking_guides.psd` 到 input，并会在 output 中保存新引导 PSD。

English: keep `renderer_version=legacy` for unchanged old output, or explicitly select `upstream_f74c8ac` for Coil, moiré and revised glossy shading. Moiré requires valid grayscale depth. Choose `layer_mode=soft` for a transparent stocking layer; floating composition matches within 1e-6 and PNG composition within one level. The editor supports region splitting/merging, snapped cuts, outline-fitted direction mirroring, targeted path deletion, persistent detected-wall deletion and course/wale overlays. Material presets are user-scoped and skip connected inputs. PSD/PSB load and guide PSD save require the optional psd-tools dependency; original files are never overwritten. Drafts are saved separately after one second, with Recover/Discard on reopening; Save and close commits the node, while Cancel removes the draft. Model objects and undo history are not persisted. The PSD interchange format does not carry ToolBox lettering, damage or material settings; save your ComfyUI workflow for those.
