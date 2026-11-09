import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { attachPromptReader } from "./prompt_browser.mjs?v=20261109-example-delete";
import { createPromptLibraryToolbar } from "./prompt_toolbar.mjs?v=20261109-example-delete";

app.registerExtension({
    name: "eazy.toolbox.prompt_reader",
    actionBarButtons: [createPromptLibraryToolbar({ app, api })],
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
