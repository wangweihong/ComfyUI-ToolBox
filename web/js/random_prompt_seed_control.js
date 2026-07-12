import { app } from "../../../scripts/app.js";

const NODE_NAME = "ToolBoxRandomPrompt";
const CONTROL_WIDGET_NAME = "control_after_generate";
const PATCHED = Symbol("toolboxRandomPromptPartialExecutionPatched");

function allowPartialExecution(callback) {
    return function (options = {}) {
        if (options?.isPartialExecution) {
            return callback.call(this, { ...options, isPartialExecution: false });
        }
        return callback.call(this, options);
    };
}

function patchSeedControl(node) {
    const controlWidget = node.widgets?.find(
        (widget) => widget.name === CONTROL_WIDGET_NAME,
    );
    if (!controlWidget || controlWidget[PATCHED]) {
        return;
    }

    for (const callbackName of ["beforeQueued", "afterQueued"]) {
        const callback = controlWidget[callbackName];
        if (typeof callback === "function") {
            controlWidget[callbackName] = allowPartialExecution(callback);
        }
    }

    controlWidget[PATCHED] = true;
}

app.registerExtension({
    name: "eazy.toolbox.random_prompt_seed_control",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            patchSeedControl(this);
            return result;
        };
    },
});
