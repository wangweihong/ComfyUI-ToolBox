import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { attachSkillReader } from "./skill_browser.mjs?v=20261114-skill-library-management";
import { createSkillLibraryToolbar } from "./skill_toolbar.mjs?v=20261114-skill-library-management";
import {SKILLS_EVENT} from './prompt_actions.mjs?v=20261114-skill-library-management';

app.registerExtension({
    name:"eazy.toolbox.skill_reader",
    setup(){api.addEventListener('toolbox.skills_changed',event=>window.dispatchEvent(new CustomEvent(SKILLS_EVENT,{detail:event.detail})));},
    actionBarButtons: [createSkillLibraryToolbar({ app, api })],
    async beforeRegisterNodeDef(nodeType,nodeData) {
        if (nodeData.name !== "ToolBoxSkillReader") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this,arguments); attachSkillReader(this,app,api); return result;
        };
    },
});
