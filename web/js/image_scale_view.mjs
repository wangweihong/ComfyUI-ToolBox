// Keep dimension predictions consistent with the native Python resize functions.
export function roundEven(value) {
    const floor = Math.floor(value);
    return value - floor === 0.5 ? floor + (floor % 2) : Math.round(value);
}

function alignSize([width, height], multiple) {
    const w = Math.floor(width / multiple) * multiple;
    const h = Math.floor(height / multiple) * multiple;
    return multiple <= 1 || !w || !h ? [width, height] : [w, h];
}

export function predictSize(source, params, multiple = 1, match = null) {
    if (!source) return null;
    let [w, h] = source;
    switch (params.resize_type) {
        case "scale dimensions":
            if (params.width || params.height) {
                w = params.width || Math.max(1, roundEven(source[0] * params.height / source[1]));
                h = params.height || Math.max(1, roundEven(source[1] * params.width / source[0]));
            }
            break;
        case "scale by multiplier": w = roundEven(w * params.multiplier); h = roundEven(h * params.multiplier); break;
        case "scale longer dimension": {
            const edge = params.longer_size;
            [w, h] = h > w ? [roundEven((w / h) * edge), edge] : [edge, roundEven((h / w) * edge)];
            break;
        }
        case "scale shorter dimension": {
            const edge = params.shorter_size;
            [w, h] = h < w ? [roundEven((w / h) * edge), edge] : [edge, roundEven((h / w) * edge)];
            break;
        }
        case "scale width":
            if (params.width) { h = Math.max(1, roundEven(h * params.width / w)); w = params.width; }
            break;
        case "scale height":
            if (params.height) { w = Math.max(1, roundEven(w * params.height / h)); h = params.height; }
            break;
        case "scale total pixels": {
            const factor = Math.sqrt(Math.trunc(params.megapixels * 1024 * 1024) / (w * h));
            w = roundEven(w * factor); h = roundEven(h * factor); break;
        }
        case "match size": if (!match) return null; [w, h] = match; break;
        case "scale to multiple": [w, h] = alignSize([w, h], params.multiple); break;
        default: return null;
    }
    if (![w, h, multiple].every(value => Number.isFinite(value) && value > 0)) return null;
    return { resized: [w, h], output: alignSize([w, h], multiple) };
}

const modeFields = {
    "scale dimensions": ["width", "height", "crop"],
    "scale by multiplier": ["multiplier"],
    "scale longer dimension": ["longer_size"],
    "scale shorter dimension": ["shorter_size"],
    "scale width": ["width"], "scale height": ["height"],
    "scale total pixels": ["megapixels"], "match size": ["crop"],
    "scale to multiple": ["multiple"],
};

function settings(node) {
    const get = name => node.widgets?.find(widget => widget.name === name || widget.name === `resize_type.${name}`)?.value;
    const mode = get("resize_type");
    const parameters = { resize_type: mode };
    for (const key of modeFields[mode] || []) parameters[key] = get(key);
    return { parameters, multiple_of: get("multiple_of"), scale_method: get("scale_method") };
}

function settingsKey(node, value) {
    const linked = name => node.inputs?.some(input => input.name === name && input.link != null && input.widget);
    const mode = value.parameters.resize_type;
    const values = [["resize_type", mode]];
    for (const key of modeFields[mode] || []) values.push([key, linked(`resize_type.${key}`) ? "linked" : value.parameters[key]]);
    values.push(["multiple_of", linked("multiple_of") ? "linked" : value.multiple_of]);
    values.push(["scale_method", linked("scale_method") ? "linked" : value.scale_method]);
    return JSON.stringify(values);
}

function upstreamState(node, seen = new Set()) {
    if (seen.has(node.id)) return null;
    seen.add(node.id);
    return (node.inputs || []).filter(input => input.link != null).map(input => {
        const link = node.graph?.links[input.link];
        const origin = link && node.graph.getNodeById(link.origin_id);
        return [input.name, input.link, origin && [origin.id,
            origin.widgets?.filter(w => w.options?.serialize !== false && w.serialize !== false).map(w => [w.name, w.value]),
            upstreamState(origin, seen)]];
    });
}

export function attachScalePreview(node, { chinese = true } = {}) {
    const t = (zh, en) => chinese ? zh : en;
    const root = document.createElement("div");
    root.className = "tb-scale-preview";
    Object.assign(root.style, {
        width: "100%", height: "100%", boxSizing: "border-box", padding: "10px",
        background: "var(--comfy-input-bg, #20232a)", color: "var(--input-text, #eee)",
        font: "12px sans-serif", display: "flex", flexDirection: "column", gap: "8px", overflow: "hidden",
    });
    const legend = document.createElement("div");
    legend.textContent = t("┄ 原尺寸（橙）　━ 目标尺寸（蓝）", "┄ Source (orange)　━ Target (blue)");
    legend.style.textAlign = "center";
    const stage = document.createElement("div");
    Object.assign(stage.style, { position: "relative", height: "154px", flex: "0 0 154px", overflow: "hidden" });
    const bounds = document.createElement("div");
    Object.assign(bounds.style, { position: "absolute", inset: "20px 40px 12px 8px" });
    const sourceFrame = document.createElement("div");
    const outputFrame = document.createElement("div");
    sourceFrame.dataset.frame = "source";
    outputFrame.dataset.frame = "output";
    for (const [frame, color, line] of [[sourceFrame, "#f5b56b", "dashed"], [outputFrame, "#69baff", "solid"]]) {
        Object.assign(frame.style, { position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)",
            boxSizing: "border-box", border: `2px ${line} ${color}`, background: `${color}12`, pointerEvents: "none" });
        frame.hidden = true;
        bounds.append(frame);
    }
    const widthLabel = document.createElement("span"), heightLabel = document.createElement("span");
    Object.assign(widthLabel.style, { position: "absolute", bottom: "calc(100% + 3px)", left: "50%", transform: "translateX(-50%)", whiteSpace: "nowrap", color: "#69baff" });
    Object.assign(heightLabel.style, { position: "absolute", left: "calc(100% + 12px)", top: "50%", transform: "translate(-50%, -50%) rotate(90deg)", whiteSpace: "nowrap", color: "#69baff" });
    outputFrame.append(widthLabel, heightLabel);
    stage.append(bounds);
    const status = document.createElement("div");
    status.setAttribute("role", "status");
    Object.assign(status.style, { textAlign: "center", color: "var(--descrip-text, #bfc5cf)", minHeight: "16px" });
    const details = document.createElement("div");
    Object.assign(details.style, { whiteSpace: "pre-wrap", lineHeight: "1.6", overflow: "auto", flex: "1", minHeight: "0" });
    root.append(legend, stage, status, details);
    const height = 340;
    const widget = node.addDOMWidget("scale_preview", "customtext", root, {
        serialize: false, getMinHeight: () => height, getMaxHeight: () => height,
    });
    widget.serialize = false;
    widget.serializeValue = () => undefined;
    widget.computeSize = () => [node.size[0], height];
    let report, executedSettings, executedUpstream, lastSignature;
    const snapshot = () => JSON.stringify([settings(node), upstreamState(node)]);
    const update = () => {
        let current = settings(node);
        const upstream = JSON.stringify(upstreamState(node));
        const signature = snapshot();
        if (lastSignature === signature) return;
        lastSignature = signature;
        let predicted = null;
        const sameSource = report && upstream === executedUpstream;
        const linked = node.inputs?.some(input => input.link != null && input.widget);
        const actual = sameSource && settingsKey(node, current) === executedSettings;
        if (actual) { predicted = report; current = report; }
        else if (sameSource && !linked) predicted = predictSize(report.source, current.parameters, current.multiple_of, report.match);
        sourceFrame.hidden = outputFrame.hidden = !predicted;
        if (!predicted) {
            widthLabel.textContent = heightLabel.textContent = "";
            status.textContent = t("等待运行读取尺寸", "Run to read dimensions");
            details.textContent = t("连接图像或掩码并运行一次。之后修改缩放参数即可即时预估；更换输入或连接参数后需重新运行。", "Connect an image or mask and run once. Parameter edits then update the estimate immediately. Run again after changing inputs or linked parameters.");
            return;
        }
        const [sw, sh] = report.source, [w, h] = predicted.output;
        const maxW = Math.max(sw, w), maxH = Math.max(sh, h);
        // A shared containing rectangle keeps both frames at exactly the same display scale.
        bounds.style.width = `min(calc(100% - 48px), ${122 * maxW / maxH}px)`;
        bounds.style.height = "auto";
        bounds.style.aspectRatio = `${maxW} / ${maxH}`;
        bounds.style.bottom = "auto";
        bounds.style.left = "calc(50% - 16px)";
        bounds.style.transform = "translateX(-50%)";
        for (const [frame, fw, fh] of [[sourceFrame, sw, sh], [outputFrame, w, h]]) {
            frame.style.width = `${100 * fw / maxW}%`;
            frame.style.height = `${100 * fh / maxH}%`;
        }
        widthLabel.textContent = `${w} px`;
        heightLabel.textContent = `${h} px`;
        status.textContent = actual ? t("实际输出 · 同一比例叠加", "Actual output · shared scale") : t("预估 · 基于上次输入，运行确认", "Estimate · based on last input; run to confirm");
        const count = value => `${(value / 1000000).toFixed(2)} MP`;
        const factor = value => Number(value.toPrecision(5));
        details.textContent = t(`输入 ${sw}×${sh} px · ${count(sw * sh)}\n目标 ${w}×${h} px · ${count(w * h)}\n宽 ×${factor(w / sw)}　高 ×${factor(h / sh)}　像素量 ×${factor(w * h / (sw * sh))}`,
            `Source ${sw}×${sh} px · ${count(sw * sh)}\nTarget ${w}×${h} px · ${count(w * h)}\nWidth ×${factor(w / sw)}　Height ×${factor(h / sh)}　Pixels ×${factor(w * h / (sw * sh))}`);
        if (current.parameters.resize_type === "scale total pixels") details.textContent += t("\n总像素参数按 1024² 计算；上方 MP 按 100 万计算。", "\nPixel target uses 1024²; displayed MP uses 1,000,000.");
        if (current.multiple_of > 1) {
            details.textContent += t(`\n最终对齐 ${current.multiple_of}：${predicted.resized.join("×")} → ${w}×${h}`, `\nAlign to ${current.multiple_of}: ${predicted.resized.join("×")} → ${w}×${h}`);
            if (w % current.multiple_of || h % current.multiple_of) details.textContent += t("（边长小于倍数，未对齐）", " (edge below multiple; unaligned)");
        }
        if (current.parameters.resize_type === "scale to multiple" || current.multiple_of > 1 || current.parameters.crop === "center") {
            details.textContent += t("\n按需等比缩放并居中裁剪；框体表示尺寸，不表示裁剪位置。", "\nMay resize proportionally and center crop; frames show dimensions, not crop positions.");
        } else if (current.parameters.crop === "disabled" && sw * h !== sh * w) {
            details.textContent += t("\n直接拉伸到目标尺寸，画面比例会改变。", "\nStretches to the target; content proportions change.");
        }
    };
    const executed = node.onExecuted;
    node.onExecuted = function (message) {
        const result = executed?.apply(this, arguments);
        if (message?.toolbox_scale?.[0]) {
            report = message.toolbox_scale[0];
            executedSettings = settingsKey(node, report);
            executedUpstream = JSON.stringify(upstreamState(node));
            lastSignature = null;
            update();
        }
        return result;
    };
    // DynamicCombo replaces its child widgets when the mode changes. Reading at draw
    // time also catches converted input sockets without patching those native widgets.
    const draw = node.onDrawBackground;
    node.onDrawBackground = function () {
        const result = draw?.apply(this, arguments);
        update();
        return result;
    };
    const configure = node.onConfigure;
    node.onConfigure = function () {
        const result = configure?.apply(this, arguments);
        report = null; lastSignature = null; update();
        return result;
    };
    const resize = node.onResize;
    node.onResize = function (size) {
        size[0] = Math.max(size[0], 360);
        return resize?.apply(this, arguments);
    };
    node.setSize([Math.max(node.size[0], 360), node.computeSize()[1]]);
    update();
    return { root, sourceFrame, outputFrame, widthLabel, heightLabel, status, details, update };
}
