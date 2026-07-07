import { app } from "../../../scripts/app.js";

const RATIO_DATA = {
    "9:16 竖屏": ["1088 x 1920", "864 x 1536", "720 x 1280", "1296 x 2304", "1440 x 2560", "1728 x 3072", "2016 x 3584", "2304 x 4096"],
    "2:3 竖屏": ["1280 x 1920", "1120 x 1680", "960 x 1440", "832 x 1248", "1536 x 2304", "1704 x 2560", "2048 x 3072", "2392 x 3584", "2728 x 4096"],
    "3:4 竖屏": ["1440 x 1920", "1200 x 1600", "912 x 1216", "1728 x 2304", "1920 x 2560", "2304 x 3072", "2688 x 3584", "3072 x 4096"],
    "4:5 竖屏": ["1536 x 1920", "1152 x 1440", "832 x 1040", "1840 x 2304", "2048 x 2560", "2456 x 3072", "2864 x 3584", "3280 x 4096"],
    "1:1 方图": ["1680 x 1680", "1440 x 1440", "1040 x 1040", "2304 x 2304", "2560 x 2560", "3072 x 3072", "3584 x 3584", "4096 x 4096"],
    "16:9 横屏": ["1920 x 1088", "1536 x 864", "1280 x 720", "2304 x 1296", "2560 x 1440", "3072 x 1728", "3584 x 2016", "4096 x 2304"],
    "3:2 横屏": ["1920 x 1280", "1680 x 1120", "1440 x 960", "1248 x 832", "2304 x 1536", "2560 x 1704", "3072 x 2048", "3584 x 2392", "4096 x 2728"],
    "4:3 横屏": ["1920 x 1440", "1600 x 1200", "1216 x 912", "2304 x 1728", "2560 x 1920", "3072 x 2304", "3584 x 2688", "4096 x 3072"],
    "5:4 横屏": ["1920 x 1536", "1440 x 1152", "1040 x 832", "2304 x 1840", "2560 x 2048", "3072 x 2456", "3584 x 2864", "4096 x 3280"],
};

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

// 注册节点js逻辑
app.registerExtension({
    name: "eazy.zimage.size_logic",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "ToolBoxLatentSize") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);

                const ratioWidget = this.widgets.find(w => w.name === "ratio");
                const resWidget = this.widgets.find(w => w.name === "resolution");
                const customWidthWidget = this.widgets.find(w => w.name === "custom_width");
                const customHeightWidget = this.widgets.find(w => w.name === "custom_height");

                const updateResolutionOptions = () => {
                    const selectedRatio = ratioWidget.value;
                    const isCustom = selectedRatio === CUSTOM_RATIO;
                    const options = RATIO_DATA[selectedRatio] || [];

                    setWidgetVisible(resWidget, !isCustom);
                    setWidgetVisible(customWidthWidget, isCustom);
                    setWidgetVisible(customHeightWidget, isCustom);
                    
                    // 核心逻辑：动态修改分辨率 Widget 的可选项
                    resWidget.options.values = options;
                    
                    // 如果旧的值不属于新比例，则强制选中当前比例的第一个选项
                    if (!isCustom && !options.includes(resWidget.value)) {
                        resWidget.value = options[0];
                    }
                    this.setSize([this.size[0], this.computeSize()[1]]);
                    this.setDirtyCanvas(true, true);
                };

                // 当 Ratio 下拉框值改变时触发
                ratioWidget.callback = () => {
                    updateResolutionOptions();
                };

                // 节点创建时初始化一次
                setTimeout(updateResolutionOptions, 20);
            };
        }
    }
});
