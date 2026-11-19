import { app } from "../../../scripts/app.js";
import { attachImageCompare } from "./image_compare_view.mjs?v=6-independent-names";

app.registerExtension({
    name: "eazy.toolbox.imageCompare",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ToolBoxImageCompare") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            attachImageCompare(this, {
                ratioData: nodeData.input.optional.resolution[1].toolbox_ratio_data,
                legacyRatioData: nodeData.input.optional.resolution[1].toolbox_legacy_ratio_data,
                chinese: (app.extensionManager?.setting?.get("Comfy.Locale") || "en").startsWith("zh"),
            });
            return result;
        };
    },
});
