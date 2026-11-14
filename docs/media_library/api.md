# 接口说明

所有接口共用 ComfyUI 端口，前缀为 `/toolbox/media-library/`。

| 方法与路径 | 功能 |
| --- | --- |
| `GET /gallery` | 独立图库；`mode=preview&id=…` 显示节点简洁预览；`current_id` / `current_path` 定位已有素材所在目录 |
| `GET /roots` | 素材目录与 FFmpeg/ffprobe 状态 |
| `POST /roots` | `{path,name?}` 添加服务器绝对目录 |
| `DELETE /roots/{id}` | 移除自定义目录，保留原文件；JSON 请求体 `{}` |
| `GET /files` | 分页文件列表；参数 root_id、folder、q、kind、sort、direction、offset、limit、focus_id |
| `GET /folders?path=…` | 当前层可浏览的非隐藏子目录 |
| `POST /folders/rename` | `{path,name}` 重命名目录，返回 path、previous_path、roots 和 updated_files；更新已索引子素材和嵌套自定义目录的路径 |
| `GET /folder-visits` | 最近访问的 20 个目录，含 path、root_id、visited_at、available 和失效原因 |
| `POST /folder-visits` | `{path,root_id?}` 记录成功访问的目录，去重置顶 |
| `POST /folder-visits/prune` | `{}` 清除失效目录记录 |
| `DELETE /folder-visits` | `{}` 清空目录访问历史 |
| `GET /regenerations/options?id=…` | 重新生成可用性、图片保存分支与不可用原因 |
| `POST /regenerations/prepare` | `{id,output_node}` 服务端恢复指定分支、换种子并预检，返回确认 token、保存前缀、种子变更、模型和批次 |
| `POST /regenerations/submit` | `{token}` 再次校验后幂等提交同一任务，返回任务 id、status、details、outputs、error |
| `GET /regenerations?source_id=…` | 此素材最近 10 次重新生成任务 |
| `GET /regenerations/{id}` | 刷新指定任务状态，完成后索引其保存节点返回的全部图片 |
| `GET /detail?id=…` | 文件信息、媒体属性、摘要、生成节点参数与原始元数据；也接受 path |
| `GET /file?id=…` | 原文件流，支持 HTTP Range；非媒体文件作为附件 |
| `GET /thumb?id=…` | 按需生成图片或视频封面 |
| `POST /select` | `{id}` 或 `{path}`，校验文件并记录最近使用 |
| `POST /recents/prune` | `{}`，移除失效的最近使用记录 |
| `GET /status` | 目录扫描状态与修订号 |
| `POST /scan` | `{path,recursive?}`，扫描所选目录，默认不进入子目录 |
| `POST /preview` | `{id,retry?}`，请求兼容预览，返回 queued/running/ready/error 与播放 URL |
| `GET /preview/file?id=…` | 兼容预览流，支持 HTTP Range |
| `POST /operations/plan` | `{op,ids,destination?,template?,start?}`，生成服务端操作快照 |
| `POST /operations/apply` | `{token,confirmed:true}`，复查并执行快照，返回逐项结果 |

`/files` 默认只显示当前层；显式使用 `recursive=1` 才平铺子目录，`recent=1` 保留原有文件使用查询，图库的新历史入口使用 `/folder-visits`。未指定目录且不是最近使用时返回空文件列表。

`focus_id` 存在于当前查询结果时，服务端计算并返回该文件所在页，响应 `offset` 为实际分页位置；不需要客户端依次加载前面的分页。

`/files` 同时返回 `focus: {position,previous_id,next_id}`，位置从 0 开始，前后 ID 遵循同一目录、筛选、排序与最近使用范围，支持跨页。首项的 previous_id、末项的 next_id 为 null；未提供或找不到 focus_id 时 focus 为 null。详情切换使用 `limit=1` 获取相邻 ID，无需加载全部文件。

目录重命名拒绝覆盖已有目标、越界路径和符号链接；ComfyUI 默认 input/output/temp 目录及包含默认目录、共享数据库或预览缓存的位置不能改名。自定义根目录可在其父目录内改名。数据库更新失败时回滚目录名称；素材 ID 与最近使用关联保持不变，之前的文件操作快照失效。

上传直接调用 ComfyUI 自带的 `POST /upload/image`，不属于 `/toolbox/media-library/` 路由。请求为 multipart 表单：`image` 为文件、`type=input`、`subfolder` 为 input 下的相对目录，不设置 overwrite。遵循响应中的实际 `name` / `subfolder` / `type` 解析路径，再通过 `/detail?path=…` 加入索引。上传本身不产生最近使用记录，也不自动选择素材。

修改接口要求同来源的 JSON 请求。文件操作限于配置目录，拒绝覆盖同名目标；服务端快照只可使用一次，有效 10 分钟。每批最多 1000 个主文件，关联的明确元数据附件包含在操作清单中。批量操作可能部分成功，响应保留已完成动作与错误。

界面中的删除仅需一次确认；移动通过文件夹列表选择目标。服务端快照为内部一致性检查，不要求用户额外执行预览步骤。

`ToolBoxMediaLibrary` 输入为可见的 `file_path: STRING` 与内部保存的 `asset_id: STRING`，唯一输出为 `path: STRING`。素材在插件内移动、重命名后保持 ID；执行时解析当前路径。文件失效时明确报错，不改用其他文件。

原始元数据保留在 detail 响应中，便于“复制所有信息”和 JSON 树查看器使用；常规生成信息弹窗只展示关键参数。不重写源文件的生成信息。

目录历史和重新生成任务存入同一 prompts.sqlite3，不触发提示词或 Skill 缓存版本变化。目录重命名原子更新访问历史，移除自定义根目录时清除其访问记录。

预检快照保留 10 分钟，任务记录持久化；同一 token 的并发或重复提交返回同一任务。向本实例固定的本地 `/prompt` 端点提交预检后的图，使用原生校验和队列；不接受浏览器上传的任意执行图。按任务 ID 读取队列/历史，不传输整个队列。无法确认网络提交结果或服务重启后的任务状态时返回 unknown，不自动重试。
