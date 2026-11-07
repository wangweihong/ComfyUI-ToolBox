# 接口与验证记录

验证日期：2026-11-05。

## 接口

| 路径 | 功能 |
| --- | --- |
| `GET /toolbox/media-library/gallery` | 独立图库；`mode=preview&id=…` 为节点简洁预览 |
| `GET/POST /toolbox/media-library/roots` | 查询目录和工具状态 / 添加服务器目录 |
| `DELETE /toolbox/media-library/roots/{id}` | 移除自定义目录；JSON 请求体 `{}` |
| `GET /toolbox/media-library/files` | 分页查询：q、kind、root_id、folder、recursive=1（明确递归，默认当前层）、sort=time/name/size、direction、offset、limit；recent=1 查询最近使用 |
| `GET /toolbox/media-library/folders?path=…` | 查询目录的直属子目录 |
| `GET /toolbox/media-library/detail?id=…` | 检查当前文件并返回原路径、属性、summary、raw、text、errors、truncated；也接受 path |
| `GET /toolbox/media-library/file?id=…` | 原始文件流，支持 Range；非媒体文件作为附件 |
| `GET /toolbox/media-library/thumb?id=…` | 懒生成的图片/视频封面 |
| `POST /toolbox/media-library/select` | `{id}` 或 `{path}`，验证并记录最近使用，返回详情 |
| `POST /toolbox/media-library/recents/prune` | `{}`，清除失效使用记录 |
| `GET /toolbox/media-library/status` | 后台扫描进度、读取错误及目录修订号 |
| `POST /toolbox/media-library/scan` | `{path,recursive?}`，扫描所选目录；recursive 默认为 false；已扫描文件按签名复用 |
| `POST /toolbox/media-library/preview` | `{id,retry?}`，按需生成兼容预览，返回 queued/running/ready/error 和播放 URL；可轮询 |
| `GET /toolbox/media-library/preview/file?id=…` | 兼容预览流，支持 Range |
| `POST /toolbox/media-library/operations/plan` | `{op,ids,destination?,template?,start?}`，返回服务器保存的 token 和完整操作清单 |
| `POST /toolbox/media-library/operations/apply` | `{token,confirmed:true}`，复查并执行，返回逐项结果及已完成动作 |

修改接口要求同来源 JSON；操作 token 一次性使用，有效 10 分钟。文件操作每批最多 1000 个主文件，不覆盖同名目标；结果可能部分成功，界面保留逐项清单。

节点公开类型：`ToolBoxMediaLibrary`。输入 `file_path: STRING`、可选内部 `asset_id: STRING`；唯一输出 `path: STRING`。工作流保存素材 ID 和路径，ID 解析在插件内移动后的当前绝对路径。节点执行不记录最近使用、不读取为 tensor、不自动入队。

## 自动化验证

通过：48 项 Python 测试、1 项 JavaScript 控件检查、11 项 Playwright 浏览器测试；TypeScript 类型检查与 Vite 构建通过。

- Python 后端测试覆盖目录边界、中文及文本搜索、最近 20 项持久化、重名冲突、删除确认、操作过期/变化复查、稳定 ID、侧车文件、跨盘校验、权限失败、损坏文件及截断标志。
- 10,001 个真实空文件验证首次索引、分页、第二次扫描不重复解析。文件全部位于临时目录。
- HTTP 测试覆盖 Range、未知文件附件类型、跨来源和非 JSON 操作拒绝、并发封面请求，以及 FFmpeg 生成的真实 MKV 的尺寸、帧率、时长、提示词和兼容播放文件。
- Python ComfyUI 接口夹具验证节点注册、STRING 输出、校验方法、移动后路径恢复和失效报错。
- JavaScript 检查验证传统画布与 Nodes 2.0 的 DOM 控件类型、序列化和消息来源限制。
- Playwright 使用 Chromium 验证真实 MP4 播放/暂停/拖动、元数据、路径、搜索、PLY/ZIP、删除确认、多节点回填隔离、保存后恢复、窄屏、点击弹窗与 Esc 关闭后保留状态。

`docs/gallery-overview.png` 与 `docs/gallery-video.png` 来自运行中的测试网页截图，非设计稿。

## 验证范围说明

2026-11-06 实机补充：除隔离测试外，已安装至本机实际运行的 `comfyui-test-cu130-megapak-pt211` Docker 容器：ComfyUI 0.43.0、前端 1.57.4、Python 3.13.12、aiohttp 3.13.4、Pillow 12.3.0，系统 FFmpeg/ffprobe 可用。

实际传统画布和 Nodes 2.0 均通过打开详情、视频播放和拖动、元数据、路径回填、多节点隔离、保存工作流再加载的检查；浏览器测试没有屏蔽其他扩展，本插件没有产生浏览器错误，测试结束后已恢复原来的渲染器设置。真实后端执行 `ToolBoxMediaLibrary → PreviewAny` 成功，重命名/移动后使用旧路径与稳定 ID 再次执行，得到新绝对路径。输入目录未出现测试素材副本。最终再次重启后，目录配置、最近使用、节点注册均保留，队列为空，渲染器设置恢复为原值。

另外只读抽查了已有 output 素材：一张 448×448 PNG 无元数据，正确显示为无元数据；一个 1152×640、24 fps、9.417 秒的 H.264/AAC 视频正确识别 ComfyUI 的 prompt/workflow，并提取 positive、model、seed、sampler、scheduler。记录只保留字段名及技术属性，未保存用户提示词内容。

测试使用独立的“本地安装测试素材”目录。测试产生的 25 个最近使用文件已通过批量操作删除，其余六类样例保留，方便打开图库复查。已保存 `ComfyUI/user/default/workflows/MediaLibrary_本地验证.json`，连接素材路径节点与原生文本预览节点，可直接运行。只操作本次创建的文件。实机记录见 [API 报告](local-api-report.json)、[浏览器报告](local-browser-report.json) 和截图 `local-classic-video.png`、`local-nodes2-node.png`。

实机发现并修复：首次扫描大目录时，长时间媒体探测不能持有文件操作锁。现在只在检查及提交索引时短暂加锁；慢速元数据读取与浏览详情并行。新增慢扫描并行详情、扫描期间重命名两项回归测试。修复后，扫描过程中六类样例详情请求约 2–105 毫秒。

首次索引未完成时，搜索只覆盖已处理文件；外部新增和修改需要刷新索引。外部跨路径移动不自动推断文件身份。视频元数据缺失时无法还原提示词；未能识别的生成图保留在原始数据中。大文本与元数据受读取上限保护，截断状态随“复制全部信息”返回。


## 2026-11-06 目录层级回归

0.1.1 首页仅列配置的目录，不发送文件列表、封面或扫描请求。默认目录查询和扫描均只包含当前层，递归平铺需要显式设置 recursive。切换目录重置开关，保留子目录导航和“上一级”。全库已有索引保留，但不会因此自动展开或加载后代文件。

新增回归覆盖：嵌套目录直接子项过滤、显式递归、浅层刷新不将未访问后代误标为删除、目录名中的 SQL 通配符、HTTP 默认空范围，以及浏览器请求数与目录进出/递归开关。

实机 0.1.1 补充：重启后状态为 running=false、scanned=0；打开首页没有文件/封面/扫描请求。测试目录当前层为 5 个文件和 1 个子目录，子目录文件默认不混入；手动递归后为 6 个文件。进入子目录与返回上级均重置平铺开关。传统画布和 Nodes 2.0 的视频选择、播放、元数据及工作流恢复再次通过，原渲染器设置已恢复。见 [目录实机报告](local-directory-report.json) 与 [启动报告](directory-startup-report.json)。


## 2026-11-06 卡片展示修复

0.1.2 将目录独立分组并统一紧凑高度，使用 SVG 文件夹图标，包括侧栏。桌面及 620px 窄屏检查确认，多行目录、超长名称和混合媒体时目录卡片高度一致，不被媒体卡片撑高。素材卡片移除路径行与路径悬停文字；详情仍能显示并复制原文件完整路径。8 项浏览器测试、类型检查及构建通过。


## 2026-11-06 JSON 参数与操作流程

0.1.3 增加独立的结构化生成参数读取器：优先保留已知采样器摘要，同时按来源节点展示其他 API 输入字段。UI-only 工作流仅保留原始控件序号，不猜测参数位置。未知采样器工作流不会遮盖已有 A1111 参数。旧 SQLite 缓存从已保存 JSON 升级，并补齐可搜索的解码文本，不触碰源文件。

删除弹窗自动显示待删除文件，一次确认，无额外预览按钮或勾选框；移动弹窗按目录列表进入和返回，`..` 表示上一级，直接执行到选定位置。服务器内部仍保留操作快照、边界检查和冲突保护。宽高合并显示在比例上一行。新增解析、缓存升级、确认删除/取消、移动目录导航、尺寸顺序的回归场景。

生成信息改为点击后打开独立弹窗：表格左列为标题、右列为数据，按节点分组并保留单项/全部复制，原始元数据可在同一弹窗展开。浏览器验证从详情打开/关闭该弹窗不会关闭文件预览，且自定义节点的文本、种子均以两列展示。
