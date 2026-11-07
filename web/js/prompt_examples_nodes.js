import {app} from '../../../scripts/app.js';
import {api} from '../../../scripts/api.js';
import {openPromptBrowser} from './prompt_browser.mjs';
import {EXAMPLES_EVENT,attachExampleCounter,attachMediaStatus} from './prompt_examples.mjs';

app.registerExtension({name:'eazy.toolbox.prompt_examples',
    setup(){api.addEventListener('toolbox.prompt_examples_changed',event=>window.dispatchEvent(new CustomEvent(EXAMPLES_EVENT,{detail:event.detail})));},
    async beforeRegisterNodeDef(nodeType,nodeData){
        const reader=nodeData.name==='ToolBoxPromptReader',random=nodeData.name==='ToolBoxRandomPrompt';
        const saver=['ToolBoxPromptSaveImage','ToolBoxPromptSaveVideo','ToolBoxPromptRecordMedia'].includes(nodeData.name);
        if(!reader&&!random&&!saver)return;const created=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function(){const result=created?.apply(this,arguments);
            if(saver)attachMediaStatus(this,api);else attachExampleCounter(this,app,api,{reader,openBrowser:openPromptBrowser});return result;};
    },
});
