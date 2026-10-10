export { STYLE_LABELS, STYLE_HINTS } from "./stocking_style_registry.mjs?v=20261010-effects2";
export const PARAM_KEYS = ["style", "density", "tilt", "strength", "strength_auto", "sparkle_depth", "sparkle_bright", "sparkle_painted", "sparkle_even", "effects_json"];
export const SLIDERS = [
    { key: "density", label: "密度", min: 40, max: 200, unit: "%", hint: "横纹疏密；接近像素大小时会自动限制并衰减。" },
    { key: "strength", label: "纹理强度", min: 0, max: 250, unit: "%", hint: "拖动即切换为手动强度，不影响亮点。" },
    { key: "tilt", label: "斜度", min: 0, max: 75, unit: "°", hint: "斜单线的倾斜角度。" },
    { key: "sparkle_depth", label: "按深度亮点", min: 0, max: 300, unit: "%", hint: "按深度分布在鼓起处；需给求解节点连接有效灰度深度图。" },
    { key: "sparkle_bright", label: "按画面亮部亮点", min: 0, max: 300, unit: "%", hint: "沿原画已有高光分布。" },
    { key: "sparkle_painted", label: "按遮罩亮点", min: 0, max: 300, unit: "%", hint: "按渲染节点 sparkle_mask 输入分布；未连接时此来源无效。" },
    { key: "sparkle_even", label: "均匀分布亮点", min: 0, max: 300, unit: "%", hint: "整个应用区域均匀分布，适合亮片效果。" },
];

// Invalid partial number input must not replace a working node value.
export function parameterPatch(key, raw) {
    const spec = SLIDERS.find(s => s.key === key);
    if (!spec) return { [key]: raw };
    if (String(raw).trim() === "" || !Number.isFinite(Number(raw))) return null;
    const val = Math.max(spec.min, Math.min(spec.max, Number(raw)));
    return key === "strength" ? { strength: val, strength_auto: false } : { [key]: val };
}
