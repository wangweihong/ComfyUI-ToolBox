// An editor draft is independent of the serialized ComfyUI node inputs.
export class GuideDraft {
    constructor(raw, mode, fallback) {
        const parsed = JSON.parse(raw || "{}");
        this.doc = structuredClone(parsed.version ? parsed : fallback);
        this.mode = mode;
        this.initial = this.state();
    }

    state() { return JSON.stringify({ doc: this.doc, mode: this.mode }); }
    get dirty() { return this.state() !== this.initial; }
    save(writeInput) {
        writeInput("guides_json", JSON.stringify(this.doc));
        writeInput("batch_mode", this.mode);
        this.initial = this.state();
    }
}

export function samHint(available, connected = false, device = "auto") {
    if (available) return `点选已就绪，当前会话设备选项 ${device}：首次点击加载本地 SAM；左键添加，右键减去，自动预览推荐范围；选小/中/大后点击“应用选区”。修改模型或设备后需重新执行工作流。`;
    if (connected) return "点选尚未就绪：SAM 已连接，请先重新执行工作流取得模型句柄。";
    return "点选不可用：未连接 SAM 模型。请把「tb-丝袜 SAM 点选模型」连接到本节点的 sam 输入，再运行一次工作流。";
}

// SAM depends on the base image and target region, not the isoline preview revision.
export class SAMRequests {
    begin(index, region) { return this.current = { index, region }; }
    invalidate() { this.current = null; }
    matches(token, closed, index, region) {
        return !closed && this.current === token && token.index === index && token.region === region;
    }
}
