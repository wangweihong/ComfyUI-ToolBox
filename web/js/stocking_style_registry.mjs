import registry from "./stocking_styles.json?v=20261010-effects2" with { type: "json" };

export const STYLE_REGISTRY = registry;
export const STYLE_LABELS = Object.fromEntries(registry.map(s => [s.id, s.label]));
export const STYLE_HINTS = Object.fromEntries(registry.map(s => [s.id, s.hint]));
export const PATTERN_STYLES = new Set(registry.filter(s => s.period).map(s => s.id));
