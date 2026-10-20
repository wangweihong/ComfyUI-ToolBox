import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { ComfyWidgets } from "/scripts/widgets.js";

app.registerExtension({
    name: "ToolBox.FlashVSR",
    async beforeRegisterNodeDef(nodeType, data) {
        if (!["ToolBoxFlashVSRUpscale", "ToolBoxVideoEncode"].includes(data.name)) return;
        const previous = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            previous?.apply(this, arguments);
            const text = message?.flashvsr_info?.[0];
            if (!text) return;
            this.flashvsrInfo = JSON.parse(text);
            let display = this.widgets?.find(w => w.name === "info_json_preview");
            if (!display) {
                display = ComfyWidgets.STRING(this, "info_json_preview", ["STRING", { multiline: true }], app).widget;
                display.inputEl.readOnly = true;
                display.serialize = false;
                display.options = { ...(display.options ?? {}), serialize: false };
                display.serializeValue = () => undefined;
            }
            display.value = JSON.stringify(this.flashvsrInfo, null, 2);
            if (data.name === "ToolBoxFlashVSRUpscale" && !this.widgets?.some(w => w.name === "清理此任务缓存")) {
                const button = this.addWidget("button", "清理此任务缓存", null, async () => {
                    const response = await api.fetchApi("/toolbox/flashvsr/cache/clear", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ signature: this.flashvsrInfo.signature }),
                    });
                    const result = await response.json();
                    display.value = JSON.stringify(result, null, 2);
                    this.setDirtyCanvas(true, true);
                });
                button.serialize = false;
                button.options = { ...(button.options ?? {}), serialize: false };
                button.serializeValue = () => undefined;
            }
            this.setDirtyCanvas(true, true);
        };
    },
});
