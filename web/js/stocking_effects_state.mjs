export const EFFECT_DEFAULTS = {
    version: 1,
    pattern: { mode: "fabric", size: 100, rotation: 0, color: "#000000", opacity: 70 },
    text: { enabled: false, content: "BALENCIAGA", size: 100, spacing_x: 100, spacing_y: 100, rotation: 0, color: "#000000", opacity: 70 },
    damage: { enabled: false, mode: "random", type: "mixed", count: 5, length: 100, width: 100, strength: 60 },
};
const LIMITS = { size: [25, 400], rotation: [-180, 180], opacity: [0, 100], spacing_x: [25, 400], spacing_y: [25, 400], count: [0, 50], length: [25, 400], width: [25, 400], strength: [0, 100] };

// Earlier workflow exports included the non-input summary/button after required
// widgets. The new trailing optional input must not interpret that summary as JSON.
export function upgradeEffectsValue(raw) {
    if (raw == null || raw === "") return "{}";
    if (typeof raw === "string" && /^(SAM3 语义识别|手工 \/ 原有点选|外部 MASK|SAM3 semantic|Manual|External MASK).* · /.test(raw)) return "{}";
    return raw;
}

export function readEffects(raw = "{}") {
    const parsed = typeof raw === "string" ? JSON.parse(raw || "{}") : raw;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || (parsed.version ?? 1) !== 1) throw new Error("不支持此效果配置版本");
    const result = structuredClone(EFFECT_DEFAULTS);
    for (const group of ["pattern", "text", "damage"]) {
        if (parsed[group] !== undefined && (!parsed[group] || typeof parsed[group] !== "object" || Array.isArray(parsed[group]))) throw new Error("效果配置必须为对象");
        for (const key of Object.keys(result[group])) if (parsed[group]?.[key] !== undefined) result[group][key] = parsed[group][key];
    }
    return result;
}

export function effectPatch(raw, group, key, value) {
    const cfg = readEffects(raw);
    if (!(key in cfg[group])) return null;
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
