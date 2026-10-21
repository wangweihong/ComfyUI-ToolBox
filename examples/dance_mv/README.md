# DanceMV示例

先运行01生成音乐，再运行02读取音乐、人物图和用户动作意图，自动分析音乐、编排动作并生成H3视频。

- `01_Music3_120BPM街舞纯音乐_40秒.json`：独立Music3音乐生成与ToolBox WAV保存。
- `02_音乐节奏反推_用户动作意图_自动H3_15秒1MP.json`：音乐＋动作意图→自动编排→H3。
- `api/`：对应API图；这里只提供文件，不会自动提交执行。

把参考人物图放入ComfyUI input，或在LoadImage重新选择。默认人物文件为 `h3_bfs_original_teal_character_20261014.png`，默认音频为 `h3dance_music3_funk_40s.wav`；也可加载自己生成的WAV。模型使用示例中已有的相对路径。

参数、依赖和迁移说明见[DanceMV文档](../../docs/dance_mv.md)。保留原DanceMV节点ID，现由ToolBox注册；请停用旧独立包。
