import {app} from "../../../scripts/app.js";
import {api} from "../../../scripts/api.js";
import {attachNodeTags} from "./tag_picker.mjs";
import {PROMPTS_EVENT} from "./prompt_actions.mjs";

app.registerExtension({
    name:"eazy.toolbox.prompt_tags",
    setup(){api.addEventListener('toolbox.prompts_changed',event=>window.dispatchEvent(new CustomEvent(PROMPTS_EVENT,{detail:event.detail})));},
    async beforeRegisterNodeDef(nodeType,nodeData){
        if(!["ToolBoxPromptWriter","ToolBoxRandomPrompt","ToolBoxPromptsByTag"].includes(nodeData.name))return;
        const created=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);
            attachNodeTags(this,app,api,{allowCreate:nodeData.name==="ToolBoxPromptWriter"});return result;};
    },
});
