import { app } from "../../../scripts/app.js";

const NODE_NAME = "ToolBoxSubjectConceptReplacer";
const MAX_PAIRS = 8;
const HIDDEN_TYPE = "toolboxHidden";
const CONCEPT_WIDGET_HEIGHT = 56;

function rememberWidget(widget) {
    if (!widget._toolboxOriginal) {
        widget._toolboxOriginal = {
            hidden: widget.hidden,
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
}

function setWidgetVisible(widget, visible, options = {}) {
    if (!widget) {
        return;
    }

    rememberWidget(widget);

    if (visible) {
        widget.hidden = widget._toolboxOriginal.hidden ?? false;
        widget.type = widget._toolboxOriginal.type;
        widget.computeSize = options.compact ? () => [0, CONCEPT_WIDGET_HEIGHT] : widget._toolboxOriginal.computeSize;
    } else {
        widget.hidden = true;
        widget.type = HIDDEN_TYPE;
        widget.computeSize = () => [0, -4];
    }

    widget.linkedWidgets?.forEach((linkedWidget) => setWidgetVisible(linkedWidget, visible, options));
}

function clampPairCount(value) {
    const count = Number.parseInt(value, 10);
    if (Number.isNaN(count)) {
        return 1;
    }
    return Math.max(1, Math.min(MAX_PAIRS, count));
}

function updateWidgets(node, pairCount) {
    for (let i = 1; i <= MAX_PAIRS; i++) {
        const visible = i <= pairCount;
        setWidgetVisible(node.widgets?.find((widget) => widget.name === `subject_${i}`), visible);
        setWidgetVisible(node.widgets?.find((widget) => widget.name === `concept_${i}`), visible, { compact: true });
    }
}

function updateOutputs(node, pairCount) {
    const targetOutputCount = 1 + pairCount * 2;

    while ((node.outputs?.length ?? 0) > targetOutputCount) {
        node.removeOutput(node.outputs.length - 1);
    }

    if (!node.outputs) {
        node.outputs = [];
    }

    if (node.outputs.length === 0) {
        node.addOutput("text", "STRING");
    }

    while (node.outputs.length < targetOutputCount) {
        const pairIndex = Math.floor((node.outputs.length - 1) / 2) + 1;
        const isSubject = (node.outputs.length - 1) % 2 === 0;
        node.addOutput(`${isSubject ? "subject" : "concept"}_${pairIndex}`, "STRING");
    }

    node.outputs[0].name = "text";
    node.outputs[0].type = "STRING";

    for (let i = 1; i <= pairCount; i++) {
        const subjectSlot = 1 + (i - 1) * 2;
        const conceptSlot = subjectSlot + 1;

        node.outputs[subjectSlot].name = `subject_${i}`;
        node.outputs[subjectSlot].type = "STRING";
        node.outputs[conceptSlot].name = `concept_${i}`;
        node.outputs[conceptSlot].type = "STRING";
    }
}

function autofillConcept(node, index) {
    const subjectWidget = node.widgets?.find((widget) => widget.name === `subject_${index}`);
    const conceptWidget = node.widgets?.find((widget) => widget.name === `concept_${index}`);

    if (!subjectWidget || !conceptWidget) {
        return;
    }

    const subject = subjectWidget.value ?? "";
    const concept = conceptWidget.value ?? "";

    if (subject.trim() && !concept.trim()) {
        conceptWidget.value = subject;
        node.setDirtyCanvas(true, true);
    }
}

function bindSubjectAutofill(node) {
    for (let i = 1; i <= MAX_PAIRS; i++) {
        const subjectWidget = node.widgets?.find((widget) => widget.name === `subject_${i}`);

        if (!subjectWidget || subjectWidget._toolboxAutofillBound) {
            continue;
        }

        const originalCallback = subjectWidget.callback;
        subjectWidget.callback = (...args) => {
            const callbackResult = originalCallback?.apply(subjectWidget, args);
            autofillConcept(node, i);
            return callbackResult;
        };
        subjectWidget._toolboxAutofillBound = true;
    }
}

function updateNode(node) {
    const pairCountWidget = node.widgets?.find((widget) => widget.name === "pair_count");
    const pairCount = clampPairCount(pairCountWidget?.value);

    if (pairCountWidget && pairCountWidget.value !== pairCount) {
        pairCountWidget.value = pairCount;
    }

    updateWidgets(node, pairCount);
    updateOutputs(node, pairCount);
    bindSubjectAutofill(node);
    node.setSize([node.size[0], node.computeSize()[1]]);
    node.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "eazy.toolbox.subject_concept_replacer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) {
            return;
        }

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const pairCountWidget = this.widgets?.find((widget) => widget.name === "pair_count");

            if (pairCountWidget) {
                const originalCallback = pairCountWidget.callback;
                pairCountWidget.callback = (...args) => {
                    const callbackResult = originalCallback?.apply(pairCountWidget, args);
                    updateNode(this);
                    return callbackResult;
                };
            }

            setTimeout(() => updateNode(this), 20);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            setTimeout(() => updateNode(this), 20);
            return result;
        };
    },
});
