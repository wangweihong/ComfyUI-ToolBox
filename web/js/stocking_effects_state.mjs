import {SCHEMA, cleanEffects} from "./stocking_config.mjs?v=20261011-material6";
export const EFFECT_DEFAULTS=SCHEMA.legacy_defaults;
const LIMITS=Object.fromEntries(Object.values(SCHEMA.groups).flatMap(g=>Object.entries(g).filter(([,s])=>s.type==="number").map(([k,s])=>[k,[s.min,s.max]])));

// Earlier workflow exports included the non-input summary/button after required
// widgets. The new trailing optional input must not interpret that summary as JSON.
export function upgradeEffectsValue(raw) {
    if (raw == null || raw === "") return "{}";
    if (typeof raw === "string" && /^(SAM3 语义识别|手工 \/ 原有点选|外部 MASK|SAM3 semantic|Manual|External MASK).* · /.test(raw)) return "{}";
    return raw;
}

export function readEffects(raw="{}") {return cleanEffects(raw);}

export function effectPatch(raw, group, key, value) {
    const cfg = readEffects(raw);
    if (!cfg[group] || !(key in cfg[group])) return null;
    if (LIMITS[key]) {
        if (String(value).trim() === "" || !Number.isFinite(Number(value))) return null;
        value = Math.max(LIMITS[key][0], Math.min(LIMITS[key][1], Number(value)));
    }
    if (key === "content" && (value.length > 128 || /[^\x20-\x7e]/.test(value))) return null;
    cfg[group][key] = value;
    return JSON.stringify(cfg);
}

export function damageStroke(points, type, width) {
    if (!["snag", "ladder"].includes(type) || !points.length) throw new Error("损伤路径无效");
    return { type, points: points.map(p => [...p]), width: Math.max(1, Math.min(256, width)) };
}
