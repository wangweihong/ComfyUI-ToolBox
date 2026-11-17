# 开关与基础值节点

这四个节点由 Crystools 对应节点迁入，独立实现于 `nodes/control_nodes.py`，不导入 Crystools，不扫描文件目录，不需要额外依赖。

| 原节点类型 | ToolBox 节点类型 | 显示名称 |
| --- | --- | --- |
| `Switch any [Crystools]` | `ToolBoxSwitchAny` | `tb-switch-any` |
| `Primitive integer [Crystools]` | `ToolBoxPrimitiveInteger` | `tb-primitive-integer` |
| `Primitive string multiline [Crystools]` | `ToolBoxPrimitiveStringMultiline` | `tb-primitive-string-multiline` |
| `Switch image [Crystools]` | `ToolBoxSwitchImage` | `tb-switch-image` |

开关位于 `ToolBox/Control`，基础值位于 `ToolBox/Primitive`。

开关保留 `on_true`、`on_false`、`boolean` 的名称和顺序，布尔值默认为真；只请求选中分支的输入，未选中分支不执行。任意类型开关直接透传原对象；图片开关输出 `IMAGE`，不复制、不转换图像。

整数节点保留 `int` 输入和输出，默认值 1、步长 1，范围为 `-sys.maxsize` 到 `sys.maxsize`。多行文本节点保留 `string` 输入和输出，默认空字符串，不改变换行或空白字符。

## 已有工作流

安装后重启 ComfyUI 并刷新页面，可以搜索上述 `tb-` 名称。此变更不自动修改已有工作流、不修改 `comfy.settings.json`、不禁用 Crystools，也不注册旧的 Crystools 类型别名，避免与原插件冲突。

需要迁移已有工作流时，将节点的 `type`（API 格式为 `class_type`）按表替换；保留节点 ID、连接、端口顺序及控件值，并同步来源属性中的插件信息。嵌套子图内的节点也需检查。迁移并验证后，再决定是否停用原插件。

普通 `tb-text` 的端口名为 `text`；此处单独提供多行文本节点，以保留 Crystools 的 `string` 端口，方便迁移。

## 来源

根据 [ComfyUI-Crystools](https://github.com/crystian/ComfyUI-Crystools) 的 `nodes/switch.py`、`nodes/primitive.py` 和 `core/types.py` 适配。保留其 MIT 许可，见 `licenses/Crystools-MIT.txt`。
