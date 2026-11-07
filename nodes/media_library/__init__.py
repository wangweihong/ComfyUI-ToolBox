"""ComfyUI media library: select a server file without copying it."""
from pathlib import Path
import threading
import folder_paths
from server import PromptServer
from .library import Library
from .routes import register_routes

_library = None
_init_lock = threading.Lock()


def get_library():
    global _library
    with _init_lock:
        if _library is None:
            _library = Library(Path(folder_paths.get_user_directory()) / 'tb_media_library', {
                'input': folder_paths.get_input_directory(),
                'output': folder_paths.get_output_directory(),
                'temp': folder_paths.get_temp_directory(),
            })
    return _library


class ToolBoxMediaLibrary:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'file_path': ('STRING', {'default': '', 'multiline': False, 'tooltip': '原文件的绝对路径；点击浏览素材库选择，不会复制到 input。'})},
                'optional': {'asset_id': ('STRING', {'default': '', 'multiline': False, 'tooltip': '素材稳定 ID，由图库自动维护；手动修改路径会清除此 ID。'})}}

    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('path',)
    FUNCTION = 'resolve_path'
    CATEGORY = 'ToolBox/Media'
    DESCRIPTION = '浏览、管理服务器上的素材，按类型预览，并输出原文件绝对路径。'

    @classmethod
    def VALIDATE_INPUTS(cls, file_path, asset_id=''):
        try: get_library().resolve(asset_id, file_path)
        except ValueError as exc: return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, file_path, asset_id=''):
        try:
            p = get_library().resolve(asset_id, file_path)
            s = p.stat()
            return f'{p}:{s.st_size}:{s.st_mtime_ns}'
        except (ValueError, OSError): return float('nan')

    def resolve_path(self, file_path, asset_id=''):
        return (str(get_library().resolve(asset_id, file_path)),)


register_routes(PromptServer.instance.routes, get_library, lambda: PromptServer.instance.send_sync('tb-media-library-changed', {}))

# Initialize when the ComfyUI HTTP app starts, including before any gallery tab is opened.
async def _startup(app):
    get_library()

if hasattr(PromptServer.instance, 'app'):
    PromptServer.instance.app.on_startup.append(_startup)

NODE_CLASS_MAPPINGS = {'ToolBoxMediaLibrary': ToolBoxMediaLibrary}
NODE_DISPLAY_NAME_MAPPINGS = {'ToolBoxMediaLibrary': 'tb-media-library'}
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
