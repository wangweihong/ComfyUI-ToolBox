from pathlib import Path
from unittest.mock import patch

import pytest
from support import LibraryError


def test_create_folder_checks_scope_names_and_conflicts(lib, tmp_path):
    root = Path(lib.roots()[0]['path'])
    result = lib.create_folder(str(root), '新目录')
    assert Path(result['path']).is_dir()
    assert lib.folders(str(root)) == [{'name': '新目录', 'path': result['path']}]
    for name in ('新目录', '../escape', '', '.', '..'):
        with pytest.raises(LibraryError):
            lib.create_folder(str(root), name)
    (root / 'file.txt').write_text('keep')
    with pytest.raises(LibraryError, match='已经存在'):
        lib.create_folder(str(root), 'file.txt')
    with pytest.raises(LibraryError):
        lib.create_folder(str(tmp_path), 'outside')
    (root / 'link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(LibraryError, match='符号链接'):
        lib.create_folder(str(root / 'link'), 'outside')
    with pytest.raises(LibraryError):
        lib.create_folder(str(root), ['not a name'])


@pytest.mark.parametrize('content', ['file', 'hidden', 'folder', 'link'])
def test_delete_rejects_every_kind_of_nonempty_directory(lib, content):
    folder = Path(lib.create_folder(lib.roots()[0]['path'], 'nonempty')['path'])
    if content == 'folder': (folder / 'empty-child').mkdir()
    elif content == 'link': (folder / 'link').symlink_to(folder / 'missing')
    else: (folder / ('.hidden' if content == 'hidden' else 'file.txt')).write_text('keep')
    with pytest.raises(LibraryError, match='只能删除空目录'):
        lib.plan_folder_delete(str(folder))
    assert folder.is_dir() and len(list(folder.iterdir())) == 1


def test_empty_folder_delete_requires_confirmation_and_cleans_history(lib):
    root = Path(lib.roots()[0]['path'])
    folder = root / 'empty'; folder.mkdir()
    old = folder / 'old.txt'; old.write_text('old'); asset = lib.upsert(old); lib.select(asset); old.unlink()
    lib.visit_folder(str(folder))
    # Prefix matching must not remove a sibling with a similar name.
    sibling = root / 'empty-other'; sibling.mkdir(); lib.visit_folder(str(sibling))
    plan = lib.plan_folder_delete(str(folder))
    with pytest.raises(LibraryError, match='确认'):
        lib.delete_folder(plan['token'])
    assert folder.exists()
    lib.delete_folder(plan['token'], True)
    assert not folder.exists() and sibling.exists()
    assert lib.row(asset)['missing'] == 1
    assert lib.files(recent=True)['items'] == []
    assert [item['path'] for item in lib.folder_visits()] == [str(sibling)]
    with pytest.raises(LibraryError, match='过期'):
        lib.delete_folder(plan['token'], True)


def test_delete_checks_new_contents_again_and_rmdir_never_recurses(lib):
    folder = Path(lib.create_folder(lib.roots()[0]['path'], 'empty')['path'])
    plan = lib.plan_folder_delete(str(folder))
    (folder / 'new.txt').write_text('keep')
    with pytest.raises(LibraryError, match='只能删除空目录'):
        lib.delete_folder(plan['token'], True)
    assert (folder / 'new.txt').read_text() == 'keep'
    (folder / 'new.txt').unlink()
    plan = lib.plan_folder_delete(str(folder))
    original = Path.rmdir
    def new_arrival(path):
        (path / 'arrived.txt').write_text('keep')
        original(path)
    with patch.object(Path, 'rmdir', new_arrival), pytest.raises(LibraryError, match='只能删除空目录'):
        lib.delete_folder(plan['token'], True)
    assert (folder / 'arrived.txt').read_text() == 'keep'


def test_delete_protects_roots_symlinks_internal_paths_and_expired_plans(lib):
    root = Path(lib.roots()[0]['path'])
    with pytest.raises(LibraryError, match='根目录'):
        lib.plan_folder_delete(str(root))
    custom = root / 'custom'; custom.mkdir(); lib.add_root(str(custom))
    with pytest.raises(LibraryError, match='根目录'):
        lib.plan_folder_delete(str(custom))
    (root / 'link').symlink_to(custom, target_is_directory=True)
    with pytest.raises(LibraryError, match='符号链接'):
        lib.plan_folder_delete(str(root / 'link'))
    with pytest.raises(LibraryError):
        lib.create_folder(str(lib.cache), 'no')
    folder = root / 'empty'; folder.mkdir()
    plan = lib.plan_folder_delete(str(folder)); lib.plans[plan['token']]['created_at'] -= 601
    with pytest.raises(LibraryError, match='过期'):
        lib.delete_folder(plan['token'], True)
    plan = lib.plan_folder_delete(str(folder))
    # Replacing an empty directory must invalidate the confirmation too.
    folder.rename(root / 'old-empty'); folder.mkdir()
    with pytest.raises(LibraryError, match='变化'):
        lib.delete_folder(plan['token'], True)
    assert folder.exists()
