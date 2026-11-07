import importlib.util
import sys
import types
from pathlib import Path
from aiohttp import web
from support import ROOT


def test_comfy_registration_node_path_and_saved_id(lib,monkeypatch):
    folder=types.ModuleType('folder_paths')
    folder.get_user_directory=lambda:str(lib.data_dir.parent)
    folder.get_input_directory=folder.get_output_directory=folder.get_temp_directory=lambda:lib.roots()[0]['path']
    server=types.ModuleType('server')
    instance=types.SimpleNamespace(routes=web.RouteTableDef(),app=web.Application(),send_sync=lambda *args:None)
    server.PromptServer=types.SimpleNamespace(instance=instance)
    monkeypatch.setitem(sys.modules,'folder_paths',folder);monkeypatch.setitem(sys.modules,'server',server)
    name='actual_media_library_plugin'
    spec=importlib.util.spec_from_file_location(name,ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
    module=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,name,module);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'get_library',lambda:lib)
    cls=module.NODE_CLASS_MAPPINGS['ToolBoxMediaLibrary']
    assert cls.RETURN_TYPES==('STRING',)
    p=Path(lib.roots()[0]['path'])/'source.txt';p.write_text('prompt');fid=lib.upsert(p)
    assert cls().resolve_path(str(p),fid)==(str(p),)
    before=cls.IS_CHANGED(str(p),fid)
    plan=lib.plan('rename',[fid],template='renamed');assert lib.apply(plan['token'],True)['results'][0]['ok']
    assert cls().resolve_path(str(p),fid)==(str(p.with_name('renamed.txt')),)
    assert cls.VALIDATE_INPUTS(str(p),fid) is True
    assert cls.IS_CHANGED(str(p),fid)!=before
    lib.apply(lib.plan('delete',[fid])['token'],True)
    assert cls.VALIDATE_INPUTS(str(p),fid) is not True
    assert not hasattr(module, 'WEB_DIRECTORY')
    assert list(module.NODE_CLASS_MAPPINGS) == ['ToolBoxMediaLibrary']
    assert module.NODE_DISPLAY_NAME_MAPPINGS['ToolBoxMediaLibrary'] == 'tb-media-library'
    assert cls.CATEGORY == 'ToolBox/Media'
    assert list(instance.routes)
