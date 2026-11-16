import { app } from "../../../scripts/app.js";

const CUSTOM_RATIO = "自定义尺寸";
const HIDDEN_TYPE = "toolboxHidden";
const PREVIEW_HEIGHT = 150;
const PREVIEW_PADDING = 8;
const PREVIEW_LABEL_SPACE = 24;

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
        // Restore type first: modern ComfyUI reapplies options.hidden in its type setter.
        widget.type = widget._toolboxOriginal.type;
        widget.computeSize = widget._toolboxOriginal.computeSize;
        widget.hidden = widget._toolboxOriginal.hidden ?? false;
    } else {
        widget.hidden = true;
        widget.type = HIDDEN_TYPE;
        widget.computeSize = () => [0, -4];
    }
}

function pixelSummary(width, height) {
    const pixels = width * height;
    if (!Number.isFinite(pixels) || width <= 0 || height <= 0) return "请选择有效尺寸";
    return `${width}×${height} px · 约 ${(pixels / 10000).toFixed(1)} 万像素（${(pixels / 1000000).toFixed(2)} MP）`;
}

function addSizeStatus(node, height, initialText, withPreview = false) {
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
    let element = text;
    const options = { serialize: false };
    if (withPreview) {
        element = document.createElement("div");
        Object.assign(element.style, {
            width: "100%", height: "100%", minWidth: "0", display: "flex",
            flexDirection: "column", color: "var(--input-text)",
            background: "var(--comfy-input-bg)", overflow: "hidden",
        });
        const stage = document.createElement("div");
        Object.assign(stage.style, {
            height: `${PREVIEW_HEIGHT}px`, flex: `0 0 ${PREVIEW_HEIGHT}px`,
            padding: `${PREVIEW_LABEL_SPACE}px ${PREVIEW_LABEL_SPACE + PREVIEW_PADDING}px ${PREVIEW_PADDING}px ${PREVIEW_PADDING}px`, boxSizing: "border-box",
            display: "flex", alignItems: "center", justifyContent: "center",
        });
        const frame = document.createElement("div");
        frame.hidden = true;
        frame.setAttribute("aria-hidden", "true");
        Object.assign(frame.style, {
            position: "relative", boxSizing: "border-box", flexShrink: "0", border: "1px solid currentColor",
            background: "rgba(128, 128, 128, 0.15)",
        });
        const widthLabel = document.createElement("span");
        const heightLabel = document.createElement("span");
        for (const edgeLabel of [widthLabel, heightLabel]) {
            Object.assign(edgeLabel.style, {
                position: "absolute", fontSize: "11px", lineHeight: "16px", whiteSpace: "nowrap",
            });
        }
        Object.assign(widthLabel.style, {
            bottom: "calc(100% + 4px)", left: "50%", transform: "translateX(-50%)",
        });
        Object.assign(heightLabel.style, {
            top: "50%", left: "calc(100% + 14px)", transform: "translate(-50%, -50%) rotate(90deg)",
        });
        frame.append(widthLabel, heightLabel);
        const label = document.createElement("div");
        Object.assign(label.style, {
            flex: "0 0 20px", fontSize: "12px", lineHeight: "20px",
            textAlign: "center", padding: "0 6px", overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
        });
        Object.assign(text.style, { flex: "1 1 0", minHeight: "0", height: "auto" });
        stage.append(frame);
        element.append(stage, label, text);
        node.toolboxSizePreview = { frame, label, widthLabel, heightLabel };
        options.getMinHeight = () => height;
        options.getMaxHeight = () => height;
    }
    const widget = node.addDOMWidget("size_status", "customtext", element, options);
    widget.serialize = false;
    widget.serializeValue = () => undefined;
    widget.computeSize = () => [node.size[0], height];
}

function updateSizePreview(node, selectedRatio, width, height) {
    const { frame, label, widthLabel, heightLabel } = node.toolboxSizePreview;
    const isCustom = selectedRatio === CUSTOM_RATIO;
    const [ratioWidth, ratioHeight] = isCustom
        ? [width, height]
        : String(selectedRatio).split(" ")[0].split(":").map(Number);
    const valid = [width, height, ratioWidth, ratioHeight].every(value => Number.isFinite(value) && value > 0);
    frame.hidden = !valid;
    widthLabel.textContent = valid ? `${width} px` : "";
    heightLabel.textContent = valid ? `${height} px` : "";
    label.textContent = valid ? (isCustom ? "自定义比例" : `${selectedRatio} · 比例示意`) : "请选择有效尺寸";
    label.title = valid && !isCustom ? "按所选比例示意，实际输出尺寸以像素标注为准。" : "";
    if (valid) {
        frame.style.aspectRatio = `${ratioWidth} / ${ratioHeight}`;
        frame.style.width = `min(100%, ${(PREVIEW_HEIGHT - PREVIEW_PADDING - PREVIEW_LABEL_SPACE) * ratioWidth / ratioHeight}px)`;
    }
}

// 注册节点js逻辑
app.registerExtension({
    name: "eazy.zimage.size_logic",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "ToolBoxLatentSize") {
            // Read the server's presets so Python and the dropdown cannot drift.
            const ratioData = nodeData.input.required.resolution[1].toolbox_ratio_data;
            const legacyRatioData = nodeData.input.required.resolution[1].toolbox_legacy_ratio_data || {};
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = onNodeCreated?.apply(this, arguments);

                const ratioWidget = this.widgets.find(w => w.name === "ratio");
                const resWidget = this.widgets.find(w => w.name === "resolution");
                const customWidthWidget = this.widgets.find(w => w.name === "custom_width");
                const customHeightWidget = this.widgets.find(w => w.name === "custom_height");
                addSizeStatus(this, 234, "请选择比例与尺寸", true);

                let restoredLegacyResolution;
                const updateResolutionOptions = (restoreLegacy = false) => {
                    const selectedRatio = ratioData[ratioWidget.value] || ratioWidget.value === CUSTOM_RATIO
                        ? ratioWidget.value
                        : Object.keys(ratioData).find(name => name.split(" ")[0] === ratioWidget.value.split(" ")[0]);
                    const isCustom = selectedRatio === CUSTOM_RATIO;
                    if (restoreLegacy) restoredLegacyResolution = resWidget.value;
                    const preserveLegacy = resWidget.value === restoredLegacyResolution
                        && (legacyRatioData[selectedRatio] || []).includes(resWidget.value);
                    const presets = ratioData[selectedRatio] || [];
                    const options = preserveLegacy ? presets.concat(resWidget.value) : presets;
                    if (!preserveLegacy) restoredLegacyResolution = undefined;
                    if (selectedRatio) ratioWidget.value = selectedRatio;

                    setWidgetVisible(resWidget, !isCustom);
                    setWidgetVisible(customWidthWidget, isCustom);
                    setWidgetVisible(customHeightWidget, isCustom);
                    
                    // 核心逻辑：动态修改分辨率 Widget 的可选项
                    if (!isCustom) resWidget.options.values = options;
                    
                    // 切换比例时选择首个精确预设，恢复旧工作流则保留显式保存的尺寸。
                    if (!isCustom && options.length && !options.includes(resWidget.value)) {
                        resWidget.value = options[0];
                    }
                    const [width, height] = isCustom
                        ? [Number(customWidthWidget.value), Number(customHeightWidget.value)]
                        : String(resWidget.value).split(" x ").map(Number);
                    this.toolboxSizeStatus.value = pixelSummary(width, height);
                    updateSizePreview(this, selectedRatio, width, height);
                    if (preserveLegacy) {
                        this.toolboxSizePreview.label.textContent += " · 旧版尺寸";
                        this.toolboxSizePreview.label.title = "已保留工作流中的旧版尺寸；重新选择分辨率可使用精确比例预设。";
                    }
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
                this.toolboxUpdateSizeWidgets?.(true);
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
