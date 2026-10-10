// Mask operations shared by temporary SAM previews and explicit application.
export function applyCandidate(paint, erase, candidate, subtract) {
    if (paint.length !== erase.length || paint.length !== candidate.length) throw new Error("SAM 遮罩尺寸不一致");
    for (let i = 0; i < candidate.length; i += 4) {
        if (candidate[i] <= 127) continue;
        const p = subtract ? 0 : 255, e = subtract ? 255 : 0;
        paint[i] = paint[i + 1] = paint[i + 2] = p;
        erase[i] = erase[i + 1] = erase[i + 2] = e;
    }
}

export function selectionCoverage(paint, erase, external = null, candidate = null, subtract = false) {
    const out = new Uint8Array(paint.length / 4);
    for (let i = 0, j = 0; i < paint.length; i += 4, j++) {
        const hit = candidate && candidate[i] > 127;
        const p = hit ? (subtract ? 0 : 255) : paint[i];
        const e = hit ? (subtract ? 255 : 0) : erase[i];
        out[j] = Math.round(Math.max(p, external?.[i] || 0) * (1 - e / 255));
    }
    return out;
}

// Boundary segments remain in image coordinates; stroke width is set in CSS pixels.
export function* maskBoundarySegments(mask, width, height) {
    const inside = (x, y) => x >= 0 && y >= 0 && x < width && y < height && mask[y * width + x] > 127;
    for (let y = 0; y <= height; y++) {
        let start = -1;
        for (let x = 0; x <= width; x++) {
            const edge = x < width && inside(x, y) !== inside(x, y - 1);
            if (edge && start < 0) start = x;
            if (!edge && start >= 0) { yield [start, y, x, y]; start = -1; }
        }
    }
    for (let x = 0; x <= width; x++) {
        let start = -1;
        for (let y = 0; y <= height; y++) {
            const edge = y < height && inside(x, y) !== inside(x - 1, y);
            if (edge && start < 0) start = y;
            if (!edge && start >= 0) { yield [x, start, x, y]; start = -1; }
        }
    }
}

export function splitRatio(clientX, rect) {
    return Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
}

export function canvasMetrics(cssWidth, cssHeight, dpr) {
    const w = Math.max(1, cssWidth), h = Math.max(1, cssHeight);
    const width = Math.max(1, Math.round(w * dpr)), height = Math.max(1, Math.round(h * dpr));
    return { width, height, scaleX: width / w, scaleY: height / h };
}

export function compareKey(ratio, key) {
    if (key === "Home") return 0;
    if (key === "End") return 1;
    if (key === "ArrowLeft") return Math.max(0, ratio - 0.01);
    if (key === "ArrowRight") return Math.min(1, ratio + 0.01);
    return null;
}
