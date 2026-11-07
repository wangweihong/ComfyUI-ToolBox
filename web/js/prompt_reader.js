import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { attachPromptReader } from "./prompt_browser.mjs";

app.registerExtension({
    name: "eazy.toolbox.prompt_reader",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "ToolBoxPromptReader") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            attachPromptReader(this, app, api);
            return result;
        };
    },
});
