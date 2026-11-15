import {app} from '../../../scripts/app.js';
import {api} from '../../../scripts/api.js';
import {attachRandomPromptCount} from './random_prompt_count.mjs?v=20261115';

app.registerExtension({
    name:'eazy.toolbox.random_prompt_count',
    async beforeRegisterNodeDef(nodeType,nodeData) {
        if(nodeData.name!=='ToolBoxRandomPrompt')return;
        const created=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function() {
            const result=created?.apply(this,arguments);
            attachRandomPromptCount(this,api);
            return result;
        };
    },
});
