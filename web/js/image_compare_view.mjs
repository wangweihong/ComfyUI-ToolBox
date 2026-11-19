const INPUT = /^image_[1-9]\d*$/;
const STATE = 'toolbox_image_compare';
const CUSTOM_RATIO = '自定义尺寸';
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
const inputMetadata = groups => groups.map(group => ({input: group.input,
    images: (group.images || []).map(image => ({width: image.width, height: image.height}))}));

export function frameRect(rect = {}, index = 0) {
    const number = (key, fallback) => Number.isFinite(rect?.[key]) ? rect[key] : fallback;
    const w = clamp(number('w', .28), 1e-9, 1), h = clamp(number('h', .32), 1e-9, 1);
    return {x: clamp(number('x', .04 + index % 3 * .31), 0, 1 - w),
        y: clamp(number('y', .08 + Math.floor(index / 3) % 3 * .3), 0, 1 - h), w, h,
        z: clamp(number('z', index + 1), 1, 1000000)};
}

export function freeLayout(keys, data = {}) {
    let frames = data.frames || {};
    if (data.version === 2) {
        const weights = keys.map(key => Number.isFinite(data.weights?.[key]) && data.weights[key] > 0 ? data.weights[key] : 1);
        const total = weights.reduce((sum, weight) => sum + weight, 0);
        let position = 0; frames = {};
        keys.forEach((key, i) => {
            const end = i === keys.length - 1 ? 1 : position + weights[i] / total;
            // Inset old full-height strips so they can immediately move in both axes.
            frames[key] = data.axis === 'y' ? {x: .15, y: position + (end - position) * .15, w: .7, h: (end - position) * .7, z: i + 1}
                : {x: position + (end - position) * .15, y: .15, w: (end - position) * .7, h: .7, z: i + 1};
            position = end;
        });
    }
    return {version: 3, keys: [...keys], frames: Object.fromEntries(keys.map((key, i) => [key, frameRect(frames[key], i)])),
        indices: {...(data.indices || {})}, filled: data.filled === true,
        names_version: 2, names: Object.fromEntries(keys.map(key => {
            const name = typeof data.names?.[key] === 'string' ? data.names[key].replace(/\s+/g, ' ').trim().slice(0, 120) : '';
            return [key, !name || data.names_version !== 2 && name === `image ${key.slice(6)}` ? key : name];
        }))};
}

// Recursively split the canvas at the clearest separation between frame centres.
// Original frame areas control relative output areas; every leaf fills its rectangle.
export function fillLayout(layout) {
    const current = freeLayout(layout.keys, layout), original = current.frames, frames = {};
    function split(keys, box) {
        if (!keys.length) return;
        if (keys.length === 1) {frames[keys[0]] = {...box, z: original[keys[0]].z}; return;}
        let best;
        for (const axis of ['x', 'y']) {
            const centre = key => original[key][axis] + original[key][axis === 'x' ? 'w' : 'h'] / 2;
            const ordered = [...keys].sort((a, b) => centre(a) - centre(b) || keys.indexOf(a) - keys.indexOf(b));
            const span = Math.max(.2, centre(ordered.at(-1)) - centre(ordered[0]));
            for (let i = 1; i < ordered.length; i++) {
                const gap = centre(ordered[i]) - centre(ordered[i - 1]), score = gap / span;
                if (!best || score > best.score + 1e-9 || Math.abs(score - best.score) < 1e-9 && gap > best.gap + 1e-9) best = {axis, ordered, i, score, gap};
            }
        }
        const left = best.ordered.slice(0, best.i), right = best.ordered.slice(best.i);
        const area = group => group.reduce((sum, key) => sum + original[key].w * original[key].h, 0);
        const fraction = area(left) / (area(left) + area(right));
        if (best.axis === 'x') {
            const width = box.w * fraction;
            split(left, {...box, w: width}); split(right, {...box, x: box.x + width, w: box.w - width});
        } else {
            const height = box.h * fraction;
            split(left, {...box, h: height}); split(right, {...box, y: box.y + height, h: box.h - height});
        }
    }
    split(current.keys, {x: 0, y: 0, w: 1, h: 1});
    return {...current, frames, filled: true};
}

function styles() {
    if (document.getElementById('tb-image-compare-style')) return;
    const style = document.createElement('style'); style.id = 'tb-image-compare-style';
    style.textContent = `
    .tbic {display:flex;flex-direction:column;min-width:0;width:100%;color:#eee;background:#17191d;font:12px system-ui;overflow:hidden;border:1px solid #41454e;border-radius:7px;box-sizing:border-box}
    .tbic * {box-sizing:border-box}
    .tbic-toolbar {display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:7px;background:#252830;min-height:40px}
    .tbic button,.tbic select {font:inherit;color:#eee;background:#353a45;border:1px solid #565e6b;border-radius:4px;padding:4px 7px;cursor:pointer}
    .tbic button:focus-visible,.tbic select:focus-visible {outline:2px solid #84b9ff;outline-offset:-2px}
    .tbic-count {margin-left:auto;color:#c7d2e3}
    .tbic-board {position:relative;width:100%;flex:none;overflow:hidden;isolation:isolate;background:#08090b;touch-action:none}
    .tbic-empty {padding:24px;text-align:center;color:#b6becb}
    .tbic-frame {position:absolute;overflow:hidden;background:hsl(var(--region-hue) 25% 16%);border:2px solid hsl(var(--region-hue) 45% 55%);color:hsl(var(--region-hue) 65% 83%);cursor:move;touch-action:none;box-shadow:0 3px 10px #0005}
    .tbic-frame:focus-visible {outline:2px solid #fff;outline-offset:-3px}
    .tbic-resize {position:absolute;z-index:2;right:0;bottom:0;width:20px;height:20px;padding:0!important;border:0!important;cursor:nwse-resize!important;touch-action:none;background:linear-gradient(135deg,transparent 40%,hsl(var(--region-hue) 65% 83%) 42%,hsl(var(--region-hue) 65% 83%) 53%,transparent 55%)!important}
    .tbic-label {position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;padding:8px;text-align:center;pointer-events:none;user-select:none;overflow:hidden}
    .tbic-name {font:600 clamp(16px,2.3vw,28px) system-ui;text-align:center;width:100%;min-width:0;color:inherit;background:transparent;border:0;border-bottom:1px dashed currentColor;padding:3px 0;outline:none;pointer-events:auto;text-overflow:ellipsis}
    .tbic-name:focus {background:#ffffff12;border-bottom-style:solid}
    .tbic-proportion,.tbic-pixels {font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}
    .tbic-pixels {opacity:.75}
    .tbic-header {position:absolute;z-index:1;top:5px;left:5px;right:5px;display:flex;align-items:center;justify-content:flex-end;pointer-events:none}
    .tbic-header select {max-width:80px;padding:1px 2px;pointer-events:auto;background:#1a2639dd}
    .tbic-hint {padding:6px 8px;color:#bac4d4;font-size:11px;background:#20232a;min-height:28px}
    `;
    document.head.append(style);
}

export function attachImageCompare(node, {chinese = true, ratioData = {}, legacyRatioData = {}} = {}) {
    if (node.__toolboxImageCompare) return node.__toolboxImageCompare;
    styles();
    const tr = (zh, en) => chinese ? zh : en;
    const el = (tag, cls) => {const element = document.createElement(tag); if (cls) element.className = cls; return element;};
    const root = el('div', 'tbic'); root.setAttribute('aria-label', tr('图像空间布局', 'Image spatial layout'));
    const toolbar = el('div', 'tbic-toolbar'), fill = el('button'), undo = el('button');
    fill.type = undo.type = 'button'; fill.textContent = tr('铺满画布', 'Fill canvas');
    undo.textContent = tr('撤销铺满', 'Undo fill'); undo.hidden = true;
    const count = el('span', 'tbic-count'), board = el('div', 'tbic-board'), hint = el('div', 'tbic-hint');
    toolbar.append(fill, undo, count); root.append(toolbar, board, hint);
    const cards = new Map();
    let removed = false, syncing = false, activeGesture, executedLayout, beforeFill;
    const inputWidget = name => node.widgets?.find(widget => widget.name === name);
    if (inputWidget('ratio') && inputWidget('resolution')) {
        const ordered = ['ratio', 'resolution', 'width', 'height', 'layout'].map(inputWidget).filter(Boolean);
        node.widgets.splice(0, node.widgets.length, ...ordered, ...node.widgets.filter(widget => !ordered.includes(widget)));
    }
    const keys = () => (node.inputs || []).filter(input => INPUT.test(input.name) && input.link != null).map(input => input.name);
    const dimensions = () => {
        if (inputWidget('ratio') && inputWidget('ratio').value !== CUSTOM_RATIO) {
            const [width, height] = String(inputWidget('resolution')?.value).split(' x ').map(Number);
            if (width > 0 && height > 0) return {width, height};
        }
        return {width: Math.max(1, Number(inputWidget('width')?.value) || 1024), height: Math.max(1, Number(inputWidget('height')?.value) || 768)};
    };
    const visibility = new Map();
    const allResolutions = [...new Set([...Object.values(ratioData).flat(), ...Object.values(legacyRatioData).flat()])];
    let restoredLegacyResolution;
    function showWidget(widget, visible) {
        if (!widget) return;
        if (!visibility.has(widget)) visibility.set(widget, {type: widget.type, computeSize: widget.computeSize});
        if (visible) {
            const original = visibility.get(widget); widget.type = original.type; widget.computeSize = original.computeSize; widget.hidden = false;
        } else {widget.hidden = true; widget.type = 'toolboxHidden'; widget.computeSize = () => [0, -4];}
    }
    function syncSizeControls(restore = false) {
        const ratio = inputWidget('ratio'), resolution = inputWidget('resolution');
        if (!ratio || !resolution) return;
        const selected = ratioData[ratio.value] || ratio.value === CUSTOM_RATIO ? ratio.value
            : Object.keys(ratioData).find(name => name.split(' ')[0] === String(ratio.value).split(' ')[0]);
        if (selected) ratio.value = selected;
        const custom = ratio.value === CUSTOM_RATIO;
        if (restore) restoredLegacyResolution = resolution.value;
        const preserveLegacy = restoredLegacyResolution === resolution.value && (legacyRatioData[ratio.value] || []).includes(resolution.value);
        if (!preserveLegacy) restoredLegacyResolution = undefined;
        const presets = ratioData[ratio.value] || [];
        resolution.options ||= {};
        if (!custom) {
            const options = preserveLegacy ? presets.concat(resolution.value) : presets;
            resolution.options.values = options;
            if (options.length && !options.includes(resolution.value)) resolution.value = options[0];
        } else {
            resolution.options.values = allResolutions;
            if (!allResolutions.includes(resolution.value)) resolution.value = allResolutions[0] || '1440 x 1440';
        }
        showWidget(resolution, !custom); showWidget(inputWidget('width'), custom); showWidget(inputWidget('height'), custom);
    }
    function state() {
        node.properties ||= {};
        if (!node.properties[STATE] || typeof node.properties[STATE] !== 'object') node.properties[STATE] = {};
        const current = node.properties[STATE];
        if (!Array.isArray(current.previews)) current.previews = [];
        current.layout = freeLayout(keys(), current.layout);
        return current;
    }
    function writeLayout() {const value = JSON.stringify(state().layout); const widget = inputWidget('layout'); if (widget) widget.value = value; return value;}
    function updateStatus() {
        const size = dimensions(), current = JSON.stringify({layout: state().layout, ...size});
        hint.textContent = executedLayout === current
            ? tr(`输出 ${size.width}×${size.height} · 自由移动框体，摆好后点击“铺满画布”`, `Output ${size.width}×${size.height} · Move frames freely, then Fill canvas`)
            : tr(`自由拖动 · 右下角缩放 · 铺满后运行更新 IMAGE 输出（${size.width}×${size.height}）`, `Drag frames · Resize at corner · Fill canvas, then run for IMAGE (${size.width}×${size.height})`);
    }
    function changed() {writeLayout(); updateStatus(); node.graph?.change?.(); node.setDirtyCanvas?.(true, true);}
    function restore(info) {
        beforeFill = null; undo.hidden = true;
        const values = info?.widgets_values;
        if (inputWidget('ratio') && Array.isArray(values) && Number.isFinite(values[0]) && Number.isFinite(values[1])) {
            inputWidget('ratio').value = CUSTOM_RATIO;
            inputWidget('width').value = values[0]; inputWidget('height').value = values[1];
            if (typeof values[2] === 'string') inputWidget('layout').value = values[2];
        }
        syncSizeControls(true);
        state().previews = inputMetadata(state().previews);
        const widget = inputWidget('layout');
        if (widget) {
            widget.hidden = true; widget.type = 'toolboxHidden'; widget.computeSize = () => [0, -4];
            try {const saved = JSON.parse(widget.value); if ([2, 3].includes(saved?.version)) state().layout = saved;} catch { /* Older workflows use the default split. */ }
        }
        render();
    }
    for (const event of ['pointerdown', 'pointermove', 'pointerup', 'dblclick', 'wheel', 'keydown']) root.addEventListener(event, e => e.stopPropagation());
    fill.addEventListener('click', () => {
        // ComfyUI wraps saved properties in reactive proxies; copy their JSON values.
        activeGesture?.(); beforeFill = JSON.parse(JSON.stringify(state().layout));
        state().layout = fillLayout(state().layout); undo.hidden = false; render(); changed();
    });
    undo.addEventListener('click', () => {
        if (!beforeFill) return;
        activeGesture?.(); state().layout = freeLayout(keys(), beforeFill); beforeFill = null;
        undo.hidden = true; render(); changed();
    });
    function raise(key) {
        const layout = state().layout;
        [...layout.keys].sort((a, b) => layout.frames[a].z - layout.frames[b].z).filter(name => name !== key).concat(key)
            .forEach((name, i) => {layout.frames[name].z = i + 1;});
    }
    function gesture(event, key, resize = false) {
        if (event.button !== 0 || event.target.closest('select,input') || !resize && event.target.closest('.tbic-resize')) return;
        event.preventDefault(); event.stopPropagation(); activeGesture?.(); raise(key);
        const target = event.currentTarget, initial = {...state().layout.frames[key]}, bounds = board.getBoundingClientRect();
        if (!bounds.width || !bounds.height) return;
        target.setPointerCapture(event.pointerId);
        const startX = event.clientX, startY = event.clientY;
        const move = e => {
            if (e.pointerId !== event.pointerId) return;
            const dx = (e.clientX - startX) / bounds.width, dy = (e.clientY - startY) / bounds.height;
            state().layout.frames[key] = frameRect(resize
                ? {...initial, w: clamp(initial.w + dx, Math.min(.06, 1 - initial.x), 1 - initial.x), h: clamp(initial.h + dy, Math.min(.06, 1 - initial.y), 1 - initial.y)}
                : {...initial, x: initial.x + dx, y: initial.y + dy});
            state().layout.filled = false; positionCards(); changed();
        };
        const finish = () => {
            for (const [name, handler] of [['pointermove', move], ['pointerup', finish], ['pointercancel', finish], ['lostpointercapture', finish]]) target.removeEventListener(name, handler);
            if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId);
            activeGesture = null; changed();
        };
        for (const [name, handler] of [['pointermove', move], ['pointerup', finish], ['pointercancel', finish], ['lostpointercapture', finish]]) target.addEventListener(name, handler);
        activeGesture = finish; positionCards();
    }
    function positionCards() {
        const layout = state().layout, rects = layout.frames, size = dimensions();
        for (const [key, card] of cards) {
            const rect = rects[key]; if (!rect) continue;
            Object.assign(card.element.style, {left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.w * 100}%`, height: `${rect.h * 100}%`, zIndex: rect.z});
            card.proportion.textContent = `${(rect.w * 100).toFixed(1)}% × ${(rect.h * 100).toFixed(1)}%`;
            const width = Math.round((rect.x + rect.w) * size.width) - Math.round(rect.x * size.width);
            const height = Math.round((rect.y + rect.h) * size.height) - Math.round(rect.y * size.height);
            card.pixels.textContent = `${width} × ${height} px`;
            card.element.title = `${layout.names[key]} · X ${(rect.x * 100).toFixed(1)}% · Y ${(rect.y * 100).toFixed(1)}% · ${card.pixels.textContent}`;
        }
    }
    function makeCard(key) {
        const element = el('section', 'tbic-frame'); element.dataset.input = key; element.setAttribute('aria-label', key); element.tabIndex = 0;
        element.style.setProperty('--region-hue', String((205 + Number(key.slice(6)) * 57) % 360));
        const label = el('div', 'tbic-label'), name = el('input', 'tbic-name'), proportion = el('span', 'tbic-proportion'), pixels = el('span', 'tbic-pixels');
        name.type = 'text'; name.maxLength = 120; name.setAttribute('aria-label', tr(`${key} 名称`, `${key} name`));
        name.title = tr('点击修改名称，名称也会显示在输出图片上', 'Edit name; also shown on the output image');
        label.append(name, proportion, pixels);
        const header = el('div', 'tbic-header'), select = el('select');
        select.setAttribute('aria-label', tr(`${key} 批次图片`, `${key} batch image`));
        const resize = el('button', 'tbic-resize'); resize.type = 'button';
        resize.setAttribute('aria-label', tr(`调整 ${key} 大小`, `Resize ${key}`));
        header.append(select); element.append(label, header, resize);
        element.addEventListener('pointerdown', e => gesture(e, key));
        resize.addEventListener('pointerdown', e => gesture(e, key, true));
        for (const [control, sizing] of [[element, false], [resize, true]]) control.addEventListener('keydown', e => {
            if (e.target !== control || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
            e.preventDefault(); e.stopPropagation(); raise(key);
            const rect = state().layout.frames[key], step = e.shiftKey ? .05 : .01;
            const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
            const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
            state().layout.frames[key] = frameRect(sizing
                ? {...rect, w: clamp(rect.w + dx, Math.min(.06, 1 - rect.x), 1 - rect.x), h: clamp(rect.h + dy, Math.min(.06, 1 - rect.y), 1 - rect.y)}
                : {...rect, x: rect.x + dx, y: rect.y + dy});
            state().layout.filled = false; positionCards(); changed();
        });
        select.addEventListener('change', () => {state().layout.indices[key] = Number(select.value); render(); changed();});
        name.addEventListener('input', () => {state().layout.names[key] = name.value; changed();});
        name.addEventListener('blur', () => {render(); changed();});
        name.addEventListener('keydown', event => {if (event.key === 'Enter') {event.preventDefault(); name.blur();}});
        return {element, name, proportion, pixels, select};
    }
    function render() {
        if (removed) return;
        const current = state(), connected = keys(), size = dimensions();
        board.style.aspectRatio = `${size.width} / ${size.height}`;
        count.textContent = tr(`${connected.length} 个区域 · ${size.width}×${size.height}`, `${connected.length} regions · ${size.width}×${size.height}`);
        for (const [key, card] of cards) if (!connected.includes(key)) {card.element.remove(); cards.delete(key);}
        board.querySelector('.tbic-empty')?.remove();
        if (!connected.length) {const empty = el('div', 'tbic-empty'); empty.textContent = tr('连接图片后自由摆放编号框体，再点击“铺满画布”', 'Connect images, position the frames freely, then Fill canvas.'); board.append(empty);}
        for (const key of connected) {
            if (!cards.has(key)) {const card = makeCard(key); cards.set(key, card); board.append(card.element);}
            const card = cards.get(key), images = current.previews.find(group => group.input === key)?.images || [], saved = current.layout.indices[key];
            const index = clamp(Number.isFinite(saved) ? Math.floor(saved) : 0, 0, Math.max(0, images.length - 1)); current.layout.indices[key] = index;
            card.select.replaceChildren(); card.select.hidden = images.length < 2;
            images.forEach((_, i) => {const option = el('option'); option.value = String(i); option.textContent = `${i + 1}/${images.length}`; card.select.append(option);});
            card.select.value = String(index);
            if (document.activeElement !== card.name) card.name.value = current.layout.names[key];
            const input = node.inputs?.find(input => input.name === key); if (input) input.label = key;
        }
        positionCards(); writeLayout(); updateStatus();
    }
    function syncInputs() {
        if (removed || syncing) return;
        syncing = true;
        try {
            if (!node.outputs?.length) node.addOutput?.('comparison', 'IMAGE');
            const inputs = node.inputs || [], empty = inputs.filter(input => INPUT.test(input.name) && input.link == null);
            for (let i = inputs.length - 1; i >= 0; i--) if (empty.includes(inputs[i])) node.removeInput(i);
            const maximum = Math.max(0, ...(node.inputs || []).filter(input => INPUT.test(input.name)).map(input => Number(input.name.slice(6))));
            node.addInput(`image_${maximum + 1}`, 'IMAGE'); state().previews = state().previews.filter(group => keys().includes(group.input)); render();
        } finally {syncing = false;}
    }
    const previewHeight = (width = node.size?.[0] || 640) => {const size = dimensions(); return Math.ceil((width - 22) * size.height / size.width) + 100;};
    const widget = node.addDOMWidget('image_compare', 'toolbox_image_compare', root, {serialize: false, hideOnZoom: false, getMinHeight: () => previewHeight(), getMaxHeight: () => previewHeight()});
    if (widget) {widget.serialize = false; widget.serializeValue = () => undefined; widget.computeSize = width => [width, previewHeight(width)];}
    const executed = node.onExecuted;
    node.onExecuted = function (message) {
        const result = executed?.apply(this, arguments);
        if (Array.isArray(message?.toolbox_image_compare)) {
            state().previews = inputMetadata(message.toolbox_image_compare); const output = message.toolbox_image_compare_result?.[0];
            executedLayout = output ? JSON.stringify({layout: output.layout, width: output.width, height: output.height}) : undefined; render();
        }
        return result;
    };
    let queued = false;
    const scheduleSync = () => {if (!syncing && !queued && !removed) {queued = true; queueMicrotask(() => {queued = false; syncInputs();});}};
    const configured = node.onConfigure; node.onConfigure = function (info) {const result = configured?.apply(this, arguments); restore(info); scheduleSync(); return result;};
    const connections = node.onConnectionsChange; node.onConnectionsChange = function () {const result = connections?.apply(this, arguments); scheduleSync(); return result;};
    const widgetChanged = node.onWidgetChanged; node.onWidgetChanged = function () {const result = widgetChanged?.apply(this, arguments); syncSizeControls(); render(); return result;};
    for (const name of ['ratio', 'resolution', 'width', 'height']) {
        const widget = inputWidget(name); if (!widget) continue;
        const callback = widget.callback;
        widget.callback = function () {const result = callback?.apply(this, arguments); syncSizeControls(); render(); node.setSize?.([node.size[0], node.computeSize?.()[1] || node.size[1]]); changed(); return result;};
    }
    const onRemoved = node.onRemoved; node.onRemoved = function () {removed = true; activeGesture?.(); cards.clear(); return onRemoved?.apply(this, arguments);};
    const controller = {root, render, syncInputs}; node.__toolboxImageCompare = controller; restore();
    const width = Math.max(node.size?.[0] || 0, 640);
    node.setSize?.([width, Math.max(node.size?.[1] || 0, previewHeight(width) + 160)]);
    return controller;
}
