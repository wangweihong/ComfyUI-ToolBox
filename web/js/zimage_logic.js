import { app } from "../../../scripts/app.js";

const RATIO_DATA = {
    "9:16 tall": ["1088 x 1920", "864 x 1536", "720 x 1280"],
    "2:3 tall": ["1280 x 1920", "1120 x 1680", "960 x 1440", "832 x 1248"],
    "3:4 tall": ["1440 x 1920", "1200 x 1600", "912 x 1216"],
    "4:5 tall": ["1536 x 1920", "1152 x 1440", "832 x 1040"],
    "1:1 square": ["1680 x 1680", "1440 x 1440", "1040 x 1040"],
    "16:9 wide": ["1920 x 1088", "1536 x 864", "1280 x 720"],
    "3:2 wide": ["1920 x 1280", "1680 x 1120", "1440 x 960", "1248 x 832"],
    "4:3 wide": ["1920 x 1440", "1600 x 1200", "1216 x 912"],
    "5:4 wide": ["1920 x 1536", "1440 x 1152", "1040 x 832"]
};

app.registerExtension({
    name: "eazy.zimage.size_logic",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "ToolBoxLatentSize") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                onNodeCreated?.apply(this, arguments);

                const ratioWidget = this.widgets.find(w => w.name === "ratio");
                const resWidget = this.widgets.find(w => w.name === "resolution");

                const updateResolutionOptions = () => {
                    const selectedRatio = ratioWidget.value;
                    const options = RATIO_DATA[selectedRatio] || [];
                    
                    // 核心逻辑：动态修改分辨率 Widget 的可选项
                    resWidget.options.values = options;
                    
                    // 如果旧的值不属于新比例，则强制选中当前比例的第一个选项
                    if (!options.includes(resWidget.value)) {
                        resWidget.value = options[0];
                    }
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