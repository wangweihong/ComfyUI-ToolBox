// Pure image/view transforms, also exercised by the headless frontend tests.
export function fitView(width, height, viewportWidth, viewportHeight) {
    const scale = Math.min(viewportWidth / width, viewportHeight / height) * 0.94;
    return { scale, x: (viewportWidth - width * scale) / 2, y: (viewportHeight - height * scale) / 2 };
}

export function imagePoint(clientX, clientY, rect, view, width, height) {
    return [Math.max(0, Math.min(width - 0.001, (clientX - rect.left - view.x) / view.scale)),
        Math.max(0, Math.min(height - 0.001, (clientY - rect.top - view.y) / view.scale))];
}

export function zoomAt(view, x, y, factor) {
    const scale = Math.max(0.02, Math.min(16, view.scale * factor));
    return { scale, x: x - (x - view.x) * scale / view.scale, y: y - (y - view.y) * scale / view.scale };
}

export function isCurrent(revision, latest, closed, index, currentIndex) {
    return !closed && revision === latest && index === currentIndex;
}
