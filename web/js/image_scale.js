import { app } from "../../../scripts/app.js";
import { attachScalePreview } from "./image_scale_view.mjs";

app.registerExtension({
    name: "eazy.toolbox.imageScale",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ToolBoxImageScale") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            this.toolboxScalePreview = attachScalePreview(this, {
                chinese: (app.extensionManager?.setting?.get("Comfy.Locale") || "en").startsWith("zh"),
            });
            return result;
        };
    },
});
