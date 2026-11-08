# 素材库开发与验证

后端位于 `nodes/media_library`，图库源码位于 `frontend/media_library`，节点扩展及共用弹窗位于 `web/js/media_library*`。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-media-library-dev.txt
npm ci
npm run typecheck
npm run build
.venv/bin/python -m pytest tests/media_library -q
PROMPT_TEST_PYTHON=.venv/bin/python npm test
MEDIA_LIBRARY_TEST_PYTHON=.venv/bin/python npm run test:e2e
```

首次运行浏览器测试前执行 `npx playwright install chromium`。FFmpeg、ffprobe 用于临时音视频测试素材和兼容预览。

`npm run build` 将网页写入 `nodes/media_library/web/dist`，请将构建产物随源码提交。不要把图库 bundle 放进根目录 `web`：该目录的 JavaScript 会由 ComfyUI 自动加载。

浏览器测试独立启动 8919 端口临时素材服务器，退出后清理素材；截图位于忽略的 `test-results`。通过 `.venv/bin/python tests/media_library/serve_fixture.py --port 8919` 可手动打开该隔离环境。

运行时数据库为插件目录下的 `data/prompts.sqlite3`，由 `nodes/database.py` 统一路径、WAL、5 秒锁等待、外键和 FULL 同步配置。素材表使用 `media_*` 前缀，缓存仍位于实际 ComfyUI 用户目录的 `tb_media_library/cache`。不使用旧插件或旧 `catalog.sqlite3` 的目录配置、索引或最近记录，不进行自动迁移。提示词和 Skill 使用各自的表变更版本，素材扫描不会触发其节点缓存失效。图库 API 为 `/toolbox/media-library`，文件上传继续调用 ComfyUI 的 `/upload/image`。嵌入消息及文件变更事件统一使用 `tb-media-library-` 前缀。

当前测试容器的拆分部署使用 `python3 scripts/deploy_media_library_split.py`；脚本先检查队列为空，在用户目录备份插件代码，再部署、重启和检查节点/API。启动检查失败自动恢复代码。备份不包含或移动用户素材和数据库。
