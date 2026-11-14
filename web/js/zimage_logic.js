import { app } from "../../../scripts/app.js";

const CUSTOM_RATIO = "自定义尺寸";
const HIDDEN_TYPE = "toolboxHidden";

function rememberWidget(widget) {
    if (!widget._toolboxOriginal) {
        widget._toolboxOriginal = {
            hidden: widget.hidden,
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
}

function setWidgetVisible(widget, visible) {
    if (!widget) {
        return;
    }

    rememberWidget(widget);

    if (visible) {
        widget.hidden = widget._toolboxOriginal.hidden ?? false;
        widget.type = widget._toolboxOriginal.type;
        widget.computeSize = widget._toolboxOriginal.computeSize;
    } else {
        widget.hidden = true;
        widget.type = HIDDEN_TYPE;
        widget.computeSize = () => [0, -4];
    }
}

function pixelSummary(width, height) {
    const pixels = width * height;
    if (!Number.isFinite(pixels) || width <= 0 || height <= 0) return "请选择有效尺寸";
    return `${width}×${height} · 约 ${(pixels / 10000).toFixed(1)} 万像素（${(pixels / 1000000).toFixed(2)} MP）`;
}

function addSizeStatus(node, height, initialText) {
    node.toolboxSizeInputWidgetCount = node.widgets.length;
    const text = document.createElement("textarea");
    text.readOnly = true;
    text.value = initialText;
    text.setAttribute("aria-label", "尺寸与像素数");
    Object.assign(text.style, {
        width: "100%", height: "100%", resize: "none", boxSizing: "border-box",
        fontSize: "12px", padding: "6px", color: "var(--input-text)",
        background: "var(--comfy-input-bg)", border: "none",
    });
    node.toolboxSizeStatus = text;
    const widget = node.addDOMWidget("size_status", "customtext", text, { serialize: false });
    widget.serialize = false;
    widget.serializeValue = () => undefined;
    widget.computeSize = () => [node.size[0], height];
}

// 注册节点js逻辑
app.registerExtension({
    name: "eazy.zimage.size_logic",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "ToolBoxLatentSize") {
            // Read the server's presets so Python and the dropdown cannot drift.
            const ratioData = nodeData.input.required.resolution[1].toolbox_ratio_data;
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = onNodeCreated?.apply(this, arguments);

                const ratioWidget = this.widgets.find(w => w.name === "ratio");
                const resWidget = this.widgets.find(w => w.name === "resolution");
                const customWidthWidget = this.widgets.find(w => w.name === "custom_width");
                const customHeightWidget = this.widgets.find(w => w.name === "custom_height");
                addSizeStatus(this, 50, "请选择比例与尺寸");

                const updateResolutionOptions = () => {
                    const selectedRatio = ratioData[ratioWidget.value] || ratioWidget.value === CUSTOM_RATIO
                        ? ratioWidget.value
                        : Object.keys(ratioData).find(name => name.split(" ")[0] === ratioWidget.value.split(" ")[0]);
                    const isCustom = selectedRatio === CUSTOM_RATIO;
                    const options = ratioData[selectedRatio] || [];
                    if (selectedRatio) ratioWidget.value = selectedRatio;

                    setWidgetVisible(resWidget, !isCustom);
                    setWidgetVisible(customWidthWidget, isCustom);
                    setWidgetVisible(customHeightWidget, isCustom);
                    
                    // 核心逻辑：动态修改分辨率 Widget 的可选项
                    if (!isCustom) resWidget.options.values = options;
                    
                    // 如果旧的值不属于新比例，则强制选中当前比例的第一个选项
                    if (!isCustom && options.length && !options.includes(resWidget.value)) {
                        resWidget.value = options[0];
                    }
                    const [width, height] = isCustom
                        ? [Number(customWidthWidget.value), Number(customHeightWidget.value)]
                        : String(resWidget.value).split(" x ").map(Number);
                    this.toolboxSizeStatus.value = pixelSummary(width, height);
                    this.setSize([this.size[0], this.computeSize()[1]]);
                    this.setDirtyCanvas(true, true);
                };

                // 尺寸改变时即时显示总像素；保留原有控件回调。
                for (const widget of [ratioWidget, resWidget, customWidthWidget, customHeightWidget]) {
                    const callback = widget.callback;
                    widget.callback = function () {
                        callback?.apply(this, arguments);
                        updateResolutionOptions();
                    };
                }

                this.toolboxUpdateSizeWidgets = updateResolutionOptions;
                // 节点创建时初始化一次
                setTimeout(updateResolutionOptions, 20);
                return result;
            };
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                const result = onConfigure?.apply(this, arguments);
                this.toolboxUpdateSizeWidgets?.();
                return result;
            };
        }
        if (nodeData.name === "ToolBoxLatentSizeAuto") {
            const created = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = created?.apply(this, arguments);
                const mode = this.widgets.find(widget => widget.name === "size_mode");
                const scale = this.widgets.find(widget => widget.name === "scale_by");
                const edge = this.widgets.find(widget => widget.name === "long_edge");
                const update = () => {
                    setWidgetVisible(scale, mode.value === "按倍数缩放");
                    setWidgetVisible(edge, mode.value === "指定长边");
                    this.setSize([this.size[0], this.computeSize()[1]]);
                    this.setDirtyCanvas(true, true);
                };
                const callback = mode.callback;
                mode.callback = function () {
                    callback?.apply(this, arguments);
                    update();
                };
                this.toolboxUpdateSizeWidgets = update;
                addSizeStatus(this, 145, "运行后显示原图比例、最近预设、实际输出尺寸和万像素数");
                update();
                return result;
            };
            const configure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                const result = configure?.apply(this, arguments);
                this.toolboxUpdateSizeWidgets?.();
                return result;
            };
            const executed = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const result = executed?.apply(this, arguments);
                if (message?.text?.length && this.toolboxSizeStatus) {
                    this.toolboxSizeStatus.value = message.text.join("\n");
                }
                return result;
            };
        }
        if (["ToolBoxLatentSize", "ToolBoxLatentSizeAuto"].includes(nodeData.name)) {
            const serialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function (info) {
                const result = serialize?.apply(this, arguments);
                if (Array.isArray(info.widgets_values)) {
                    info.widgets_values = info.widgets_values.slice(0, this.toolboxSizeInputWidgetCount);
                }
                return result;
            };
        }
    }
});
