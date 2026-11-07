export const MEDIA_LIBRARY_API = '/toolbox/media-library';

export function openMediaLibrary({api, currentId = '', currentPath = '', onSelect, onChanged, onClose}) {
    const dialog = document.createElement('dialog');
    dialog.style.cssText = 'width:96vw;height:94vh;max-width:1900px;max-height:96vh;padding:0;border:1px solid #54627a;border-radius:12px;background:#191c22;color:#dce5f4';
    const header = document.createElement('div');
    header.style.cssText = 'height:40px;display:flex;align-items:center;justify-content:space-between;padding:0 16px';
    const label = document.createElement('span');
    label.textContent = '素材库 · 选中文件后点击使用';
    label.setAttribute('role', 'status');
    const done = document.createElement('button');
    done.textContent = '关闭';
    done.style.cssText = 'cursor:pointer;color:inherit;background:#2b3547;border:0;border-radius:5px;padding:5px 14px';
    const frame = document.createElement('iframe');
    frame.title = '素材库';
    frame.src = api.apiURL(`${MEDIA_LIBRARY_API}/gallery?` + new URLSearchParams({current_id: String(currentId), current_path: String(currentPath)}));
    frame.style.cssText = 'width:100%;height:calc(100% - 40px);border:0';
    let closed = false, selecting = false;
    const close = () => {
        if (closed) return;
        closed = true;
        window.removeEventListener('message', receive);
        frame.src = 'about:blank';
        dialog.remove();
        onClose?.();
    };
    const receive = async event => {
        if (closed || event.origin !== location.origin || event.source !== frame.contentWindow) return;
        if (event.data?.type === 'tb-media-library-ready') {
            frame.contentWindow.postMessage({type: 'tb-media-library-current', id: currentId, path: currentPath}, location.origin);
        }
        if (event.data?.type === 'tb-media-library-changed') onChanged?.();
        if (event.data?.type !== 'tb-media-library-select' || selecting) return;
        const {id, path} = event.data;
        if (typeof id !== 'string' || !id || typeof path !== 'string' || !path) return;
        selecting = true;
        try {
            await onSelect({id, path});
            close();
        } catch (error) {
            label.textContent = error.message || '无法使用所选素材，请重试。';
        } finally {
            selecting = false;
        }
    };
    done.onclick = close;
    header.append(label, done);
    dialog.append(header, frame);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    document.body.append(dialog);
    window.addEventListener('message', receive);
    try { dialog.showModal(); }
    catch (error) { close(); throw error; }
    return {close};
}
