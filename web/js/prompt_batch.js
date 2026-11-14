import {app} from '../../../scripts/app.js';
import {attachPromptBatchPreview} from './prompt_batch.mjs?v=20261114-prompt-library-management';

app.registerExtension({
    name:'eazy.toolbox.prompt_batch',
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== 'ToolBoxPromptsByTag') return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            const result = created?.apply(this, arguments);
            attachPromptBatchPreview(this);
            return result;
        };
    },
});
