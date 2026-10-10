// Image-specific edits never become a shared mask for an unrelated batch frame.
export const SETTING_KEYS = ["style", "density", "tilt", "strength", "strength_auto", "color_exclude", "sparkle_depth", "sparkle_bright", "sparkle_painted", "sparkle_even", "seed", "source_mode", "prompt", "threshold", "auto_direction", "depth_direction", "auto_walls", "failure_mode", "effects_json", "renderer_version", "layer_mode", "moire_on", "moire", "moire_area", "sparkle_link"];

export function recordsForSave(raw, document, identities, initial = null) {
    const parsed = JSON.parse(raw || "{}");
    const records = parsed.version === 2 ? structuredClone(parsed.records) : {};
    for (let i = 0; i < identities.length; i++) {
        if (initial && JSON.stringify(document.frames[i]) === JSON.stringify(initial.frames[i])) continue;
        records[identities[i]] = { version: 1, width: document.width, height: document.height, frames: [structuredClone(document.frames[i])] };
    }
    return JSON.stringify({ version: 2, records });
}

export function capturePrompt(prompt, inputs, captureId) {
    const result = {};
    const visit = id => {
        if (result[id]) return;
        if (!prompt[id]) throw new Error(`Missing upstream node ${id}`);
        result[id] = structuredClone(prompt[id]);
        for (const val of Object.values(prompt[id].inputs || {})) if (Array.isArray(val) && val.length === 2 && typeof val[0] === "string") visit(val[0]);
    };
    for (const val of Object.values(inputs)) if (Array.isArray(val) && val.length === 2 && typeof val[0] === "string") visit(val[0]);
    result[captureId] = { class_type: "NFStockingPrepare", inputs: structuredClone(inputs) };
    return result;
}
