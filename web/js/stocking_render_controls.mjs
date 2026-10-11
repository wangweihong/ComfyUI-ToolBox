export { STYLE_LABELS, STYLE_HINTS } from "./stocking_style_registry.mjs?v=20261010-upstream1";
export const PARAM_KEYS = ["style", "density", "tilt", "strength", "strength_auto", "sparkle_depth", "sparkle_bright", "sparkle_painted", "sparkle_even", "effects_json", "renderer_version", "layer_mode", "moire_on", "moire", "moire_area", "sparkle_link"];
import {SCHEMA} from './stocking_config.mjs?v=20261011-material6';
export const SLIDERS = ['moire','moire_area','density','strength','tilt','sparkle_depth','sparkle_bright','sparkle_painted','sparkle_even'].map(key=>({key,...SCHEMA.appearance[key]}));

// Invalid partial number input must not replace a working node value.
export function parameterPatch(key, raw) {
    const spec = SLIDERS.find(s => s.key === key);
    if (!spec) return { [key]: raw };
    if (String(raw).trim() === "" || !Number.isFinite(Number(raw))) return null;
    const val = Math.max(spec.min, Math.min(spec.max, Number(raw)));
    return key === "strength" ? { strength: val, strength_auto: false } : { [key]: val };
}
