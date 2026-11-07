import errno
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image, PngImagePlugin
from support import Library, LibraryError, metadata


def media_root(lib): return Path(lib.roots()[0]['path'])

def add(lib, name='中文素材.txt', content='测试提示词：海边的人物'):
    p = media_root(lib) / name
    p.parent.mkdir(exist_ok=True, parents=True)
    p.write_text(content)
    return p, lib.upsert(p)


def test_search_all_types_and_chinese(lib):
    for name in ('图像.bin', 'nested/声音.zip', '三维.ply', '内容.md'):
        add(lib, name)
    lib.scan()
    assert lib.files(q='海边')['total'] == 1  # Only text content is indexed; ZIP stays opaque.
    assert lib.files(q='nested')['total'] == 1
    assert lib.files(kind='other')['total'] == 2
    assert lib.files(limit=1)['total'] == 4
    assert len(lib.files(offset=2, limit=1)['items']) == 1
    assert lib.files(q='%')['total'] == 0


def test_all_types_no_import_copy(lib):
    for name in ['a.txt', 'b.zip', 'c.ply', 'd.mp4', 'e.wav', 'f.png']:
        p, fid = add(lib, name)
        before = sorted(media_root(lib).iterdir())
        item = lib.select(fid)
        assert item['path'] == str(p)
        assert sorted(media_root(lib).iterdir()) == before
    assert lib.files(recent=True)['total'] == 6


def test_recent_twenty_persist_and_deduplicate(lib):
    ids = [add(lib, f'{n}.txt')[1] for n in range(25)]
    for fid in ids: lib.select(fid)
    assert lib.files(recent=True)['total'] == 20
    lib.select(ids[10])
    assert lib.files(recent=True)['items'][0]['id'] == ids[10]
    again = Library(lib.data_dir)
    assert again.files(recent=True)['total'] == 20
    again.close()


def test_rename_move_stable_id_and_sidecar(lib):
    p, fid = add(lib)
    companion = Path(str(p) + '.json')
    companion.write_text('{"prompt":"海边"}')
    lib.select(fid)
    plan = lib.plan('rename', [fid], template='新名称')
    assert len(plan['entries'][0]['actions']) == 2
    result = lib.apply(plan['token'], True)
    assert result['results'][0]['ok']
    new = p.with_name('新名称.txt')
    assert lib.resolve(fid) == new
    assert Path(str(new) + '.json').is_file()
    assert lib.files(recent=True)['items'][0]['path'] == str(new)
    dest = media_root(lib) / '目标'
    dest.mkdir()
    result = lib.apply(lib.plan('move', [fid], destination=str(dest))['token'], True)
    assert result['results'][0]['ok']
    assert lib.resolve(fid) == dest / new.name
    assert lib.files(q='海边')['total'] == 1


def test_delete_requires_confirm_and_token_once(lib):
    p, fid = add(lib)
    lib.select(fid)
    plan = lib.plan('delete', [fid])
    with pytest.raises(LibraryError): lib.apply(plan['token'])
    assert p.exists()
    assert lib.apply(plan['token'], True)['results'][0]['ok']
    assert not p.exists()
    assert lib.files(recent=True)['items'][0]['missing']
    with pytest.raises(LibraryError): lib.resolve(fid)
    lib.prune_recents()
    assert lib.files(recent=True)['total'] == 0
    with pytest.raises(LibraryError): lib.apply(plan['token'], True)


def test_reused_path_does_not_resurrect_deleted_asset(lib):
    p, old = add(lib)
    lib.apply(lib.plan('delete', [old])['token'], True)
    p.write_text('其他文件')
    new = lib.upsert(p)
    assert old != new
    with pytest.raises(LibraryError): lib.resolve(old)


def test_rename_to_previous_deleted_path(lib):
    p, old = add(lib, 'target.txt')
    lib.apply(lib.plan('delete', [old])['token'], True)
    source, new = add(lib, 'source.txt')
    result = lib.apply(lib.plan('rename', [new], template='target')['token'], True)
    assert result['results'][0]['ok']
    assert lib.resolve(new) == p
    with pytest.raises(LibraryError): lib.resolve(old)


def test_conflicts_never_overwrite_and_partial_results(lib):
    p, first = add(lib, 'a.txt', 'A')
    _, second = add(lib, 'b.txt', 'B')
    plan = lib.plan('rename', [first, second], template='same')
    result = lib.apply(plan['token'], True)
    assert [r['ok'] for r in result['results']] == [True, False]
    assert (media_root(lib) / 'same.txt').read_text() == 'A'
    assert lib.resolve(second).read_text() == 'B'


def test_file_change_invalidates_preview(lib):
    p, fid = add(lib)
    plan = lib.plan('delete', [fid])
    p.write_text('内容已改变')
    result = lib.apply(plan['token'], True)
    assert not result['results'][0]['ok']
    assert p.exists()


def test_destination_created_after_plan_is_not_overwritten(lib):
    p, fid = add(lib)
    plan = lib.plan('rename', [fid], template='占用')
    target = p.with_name('占用.txt'); target.write_text('保留')
    result = lib.apply(plan['token'], True)
    assert not result['results'][0]['ok']
    assert target.read_text() == '保留' and p.exists()


def test_paths_and_symlinks_constrained(lib, tmp_path):
    p, fid = add(lib)
    outside = tmp_path / 'private.txt'; outside.write_text('秘密')
    link = media_root(lib) / 'link.txt'; link.symlink_to(outside)
    for path in (outside, link, media_root(lib)/'..'/'private.txt'):
        with pytest.raises(LibraryError): lib.resolve(path=str(path))
    lib.scan()
    assert lib.files()['total'] == 1
    plan = lib.plan('rename', [fid], template='../越界')
    assert plan['entries'][0]['error']


def test_root_config_persist_and_removal_preserves_file(lib, tmp_path):
    custom = tmp_path / 'custom';custom.mkdir()
    p = custom / 'test.zip';p.write_bytes(b'ZIP')
    roots = lib.add_root(str(custom), '额外目录')
    rid = next(r['id'] for r in roots if r['path'] == str(custom))
    lib.scan();fid = lib.files(root_id=rid)['items'][0]['id']
    lib.remove_root(rid)
    assert p.exists()
    with pytest.raises(LibraryError): lib.resolve(fid)
    with pytest.raises(LibraryError): lib.add_root(str(tmp_path))


def test_external_delete_marks_missing_and_prunes(lib):
    p, fid = add(lib);lib.select(fid);p.unlink();lib.scan()
    assert lib.files()['total'] == 0
    assert lib.files(recent=True)['items'][0]['missing']


def test_cross_device_move_checks_content(lib):
    p, fid = add(lib, content='跨盘内容'*1000)
    target = p.with_name('cross.txt')
    with patch('os.link', side_effect=OSError(errno.EXDEV, 'cross device')):
        lib.move_no_replace(p, target)
    assert not p.exists() and target.read_text() == '跨盘内容'*1000


def test_cross_device_failure_keeps_source(lib):
    p, fid = add(lib)
    target = p.with_name('cross.txt')
    with patch('os.link', side_effect=OSError(errno.EXDEV, 'cross device')), patch('os.fsync', side_effect=OSError('disk full')):
        with pytest.raises(OSError): lib.move_no_replace(p, target)
    assert p.exists() and not target.exists()


def test_cross_device_no_clobber(lib):
    p, fid = add(lib);target=p.with_name('cross.txt');target.write_text('保留')
    with patch('os.link', side_effect=OSError(errno.EXDEV, 'cross device')):
        with pytest.raises(FileExistsError): lib.move_no_replace(p, target)
    assert target.read_text()=='保留' and p.exists()


def test_permission_failure_reported(lib):
    p, fid = add(lib)
    with patch.object(Path, 'unlink', side_effect=PermissionError('permission denied')):
        result = lib.apply(lib.plan('delete', [fid])['token'], True)
    assert not result['results'][0]['ok'] and p.exists()


def test_image_metadata_prompt_and_dimensions(lib):
    p = media_root(lib) / 'image.png'
    extra = PngImagePlugin.PngInfo();extra.add_text('parameters', '海边的人物\nNegative prompt: 模糊\nSteps: 20, Sampler: Euler, CFG scale: 7, Seed: 42, Model: test')
    Image.new('RGB', (640, 360)).save(p, pnginfo=extra)
    item = lib.detail(path=str(p))
    assert item['properties']['aspect_ratio'] == '16:9'
    assert item['summary']['positive'] == '海边的人物'
    assert item['summary']['negative'] == '模糊'
    assert item['summary']['seed'] == '42'
    assert item['raw']['parameters']
    assert lib.files(q='海边')['total'] == 1


def test_ply_and_zip_information_only(lib):
    p, fid = add(lib, 'cloud.ply', 'ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nelement face 1\nend_header\n0 0 0\n')
    item = lib.detail(fid)
    assert item['properties']['vertices'] == 3
    assert item['properties']['faces'] == 1
    p, fid = add(lib, 'archive.zip', 'not actually a zip')
    item = lib.detail(fid)
    assert item['kind'] == 'other' and not item['raw'] and not item['errors']


def test_truncated_text_and_corrupt_media(lib):
    p, fid = add(lib, 'large.txt', '中'*(metadata.TEXT_LIMIT//3+10))
    assert lib.detail(fid)['truncated']
    p, fid = add(lib, 'bad.png', 'corrupt')
    assert lib.detail(fid)['errors']
    assert lib.files()['total'] == 2


def test_many_files_paging_and_unchanged_scan(lib):
    root=media_root(lib)
    for n in range(10001): (root/f'{n:05}.zip').touch()
    lib.scan()
    assert lib.files()['total'] == 10001
    assert len(lib.files(offset=9990,limit=20)['items']) == 11
    with patch.object(metadata, 'inspect', side_effect=AssertionError('unchanged file was inspected')):
        lib.scan()
    assert lib.status['errors'] == []


def test_companions_selected_before_primary_are_operated_once(lib):
    p, fid = add(lib)
    side = Path(str(p)+'.json');side.write_text('{"prompt":"text"}');sideid=lib.upsert(side)
    plan=lib.plan('rename',[sideid,fid],template='new')
    assert len(plan['entries'])==1 and len(plan['entries'][0]['actions'])==2
    result=lib.apply(plan['token'],True)
    assert result['results'][0]['ok']
    assert lib.resolve(sideid).name=='new.txt.json'


def test_missing_ffprobe_reports_error_without_hiding_file(lib):
    p, fid=add(lib,'movie.mp4')
    with patch.object(metadata.shutil,'which',return_value=None):
        item=lib.detail(fid)
    assert 'ffprobe' in item['errors'][0] and item['kind']=='video'


def test_audio_info_and_rotation_ratio(lib):
    import subprocess
    p=media_root(lib)/'tone.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',str(p)],check=True)
    item=lib.detail(path=str(p))
    assert item['properties']['channels']==1
    assert item['properties']['sample_rate']=='44100'
    assert .9 < item['properties']['duration'] < 1.1



def test_same_default_directories_are_deduplicated(tmp_path):
    root=tmp_path/'shared';root.mkdir()
    lib=Library(tmp_path/'data',{'input':str(root),'output':str(root),'temp':str(root)})
    assert len(lib.roots())==1
    lib.close()


def test_typescript_text_is_not_treated_as_transport_stream(lib):
    p,fid=add(lib,'example.ts','const prompt = "海岸";')
    assert lib.detail(fid)['kind']=='text'
    assert lib.files(q='海岸')['total']==1


def test_slow_background_probe_does_not_block_detail(lib):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    fast, fid=add(lib,'fast.txt')
    slow=media_root(lib)/'slow.txt';slow.write_text('slow')
    entered,release=threading.Event(),threading.Event()
    inspect=metadata.inspect
    def probe(path):
        if path==slow:
            entered.set();release.wait(5)
        return inspect(path)
    with patch.object(metadata,'inspect',side_effect=probe),ThreadPoolExecutor(max_workers=2) as pool:
        scanner=pool.submit(lib.scan)
        assert entered.wait(2)
        try:
            result=pool.submit(lib.detail,fid).result(timeout=1)
            assert result['path']==str(fast)
        finally:release.set()
        scanner.result(timeout=3)


def test_move_during_inspection_cannot_resurrect_old_path(lib):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    p,fid=add(lib,'changing.txt')
    entered,release=threading.Event(),threading.Event()
    inspect=metadata.inspect
    def probe(path):
        if threading.current_thread().name.startswith('ThreadPool'):
            entered.set();release.wait(5)
        return inspect(path)
    with patch.object(metadata,'inspect',side_effect=probe),ThreadPoolExecutor(max_workers=1) as pool:
        scanner=pool.submit(lib.upsert,p,force=True);assert entered.wait(2)
        try:
            result=lib.apply(lib.plan('rename',[fid],template='moved')['token'],True)
            assert result['results'][0]['ok']
        finally:release.set()
        with pytest.raises((LibraryError,OSError)):scanner.result(timeout=3)
    assert lib.resolve(fid).name=='moved.txt'
    assert lib.files()['total']==1


def test_scoped_listing_defaults_to_direct_children(lib):
    root=media_root(lib)
    direct,a=add(lib,'top.txt')
    child,b=add(lib,'子目录/child.txt')
    deep,c=add(lib,'子目录/更深层/deep.txt')
    rid=lib.roots()[0]['id']
    assert [r['id'] for r in lib.files(root_id=rid)['items']]==[a]
    assert {r['id'] for r in lib.files(root_id=rid,recursive=True)['items']}=={a,b,c}
    assert [r['id'] for r in lib.files(folder=str(child.parent))['items']]==[b]
    assert {r['id'] for r in lib.files(folder=str(child.parent),recursive=True)['items']}=={b,c}
    assert lib.files(root_id=rid,q='deep')['total']==0
    assert lib.files(root_id=rid,q='deep',recursive=True)['total']==1


def test_scanning_only_enters_subdirectories_when_explicitly_requested(lib):
    root=media_root(lib);(root/'sub').mkdir()
    (root/'top.txt').write_text('top')
    (root/'sub'/'child.txt').write_text('child')
    lib.scan()
    assert lib.files()['total']==1
    lib.scan(str(root/'sub'))
    assert lib.files()['total']==2
    (root/'sub'/'deep').mkdir();deep=root/'sub'/'deep'/'deeper.txt';deep.write_text('deep')
    lib.scan(str(root))
    assert lib.files()['total']==2
    lib.scan(str(root),recursive=True)
    assert lib.files()['total']==3
    deep.unlink();lib.scan(str(root))
    # A shallow refresh must not treat unseen descendants as deleted.
    assert not lib.row(next(r['id'] for r in lib.files()['items'] if r['name']=='deeper.txt'))['missing']
    lib.scan(str(root/'sub'),recursive=True)
    assert lib.files()['total']==2


def test_directory_names_with_sql_wildcards_stay_scoped(lib):
    p,first=add(lib,'a_%/one.txt')
    _,second=add(lib,'a_%/nested/two.txt')
    add(lib,'a_other/three.txt')
    assert lib.files(folder=str(p.parent))['total']==1
    assert lib.files(folder=str(p.parent),recursive=True)['total']==2
