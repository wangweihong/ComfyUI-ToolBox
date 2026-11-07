import {app} from "../../../scripts/app.js";
import {api} from "../../../scripts/api.js";
import {attachNodeTags} from "./tag_picker.mjs";

app.registerExtension({
    name:"eazy.toolbox.prompt_tags",
    async beforeRegisterNodeDef(nodeType,nodeData){
        if(!["ToolBoxPromptWriter","ToolBoxRandomPrompt"].includes(nodeData.name))return;
        const created=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);
            attachNodeTags(this,app,api,{allowCreate:nodeData.name==="ToolBoxPromptWriter"});return result;};
    },
});
