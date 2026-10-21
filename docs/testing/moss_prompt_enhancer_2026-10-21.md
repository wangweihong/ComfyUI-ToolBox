# MOSS Prompt Enhancer迁移验收（2026-10-21）

测试环境为本地RTX 5090 D、现有CUDA llama-cpp-python 0.3.40及Gemma4-12B Q4_K_M。独立插件已移出运行目录，仅由ToolBox注册MOSSPromptEnhancer。以下为该环境的实际结果，不代表所有模型或平台。

## 注册与兼容

- 迁移前后5657个节点的注册集合相同；仅MOSSPromptEnhancer归属改为ToolBox，其他节点归属未变。
- 输入schema、控件顺序、输出名称与类型逐项相同；菜单为ToolBox/MOSS，显示名tb-moss-prompt-enhancer。
- 缺少llama库时可以导入模块和生成节点定义，执行增强才报依赖错误；旁路不需要该库。默认requirements未加入llama包。
- 编译器、增强指令及推理/资源关闭逻辑与已实测独立版相同；推理函数仅增加执行时的依赖导入。

## 测试结果

9项CPU测试通过：可选依赖、旧接口、旁路、官方编译与严格JSON、重试复用上下文、异常/取消/超时关闭、示例可移植性及文档链接。运行命令：

```bash
python3 -m unittest discover -s tests -p 'test_moss_prompt_enhancer.py' -v
```

| 完整工作流 | 尺寸 | 执行时间 | 原生生成速度 |
|---|---|---:|---:|
| 布局增强生图 | 1024×1024 | 55.901秒 | 121.2 tokens/s |
| Caption增强生图 | 1024×1024 | 35.105秒 | 122.0 tokens/s |
| 中文海报布局 | 1024×1536 | 44.363秒 | 121.0 tokens/s |

三次增强节点均实际执行。检查官方编译输出、边界转换、中文text、PNG尺寸、哈希和内嵌API；三物体关系正确，“春日茶会”四字正确且排为两行。完整耗时包含模型加载、卸载和切换，不含排队，不能直接与其他缓存状态下的耗时比较。

独立原生探测确认所有libllama/libggml来自现有site-packages/llama_cpp/lib，没有启动推理CLI。现有库导入时通过ctypes.find_library调用ldconfig/gcc/ld定位系统库，这些探测调用单列，不视为新的推理后端。真实超时与已加载上下文中的取消均抛出预期异常并关闭模型。

未重测参考图和reasoning on，未完整重建镜像。详细执行历史、原图、注册快照、备份及回滚清单保存于本地迁移验收归档。
