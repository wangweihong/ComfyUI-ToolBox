import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { attachSkillReader } from "./skill_browser.mjs";

app.registerExtension({
    name:"eazy.toolbox.skill_reader",
    async beforeRegisterNodeDef(nodeType,nodeData) {
        if (nodeData.name !== "ToolBoxSkillReader") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this,arguments); attachSkillReader(this,app,api); return result;
        };
    },
});
