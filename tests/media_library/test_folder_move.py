import errno
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from support import LibraryError


def setup_move(lib, tmp_path):
    root = Path(lib.roots()[0]['path'])
    source = root / '待移动_%目录'
    (source / 'nested').mkdir(parents=True)
    path = source / 'nested' / 'asset.txt'
    path.write_text('preserved content')
    (source / '.hidden').write_text('hidden content')
    destination = tmp_path / 'destination'
    destination.mkdir()
    lib.add_root(str(destination))
    return source, path, lib.upsert(path), destination


def test_move_between_roots_updates_ids_history_search_and_nested_roots(lib, tmp_path):
    source, path, fid, destination = setup_move(lib, tmp_path)
    lib.add_root(str(path.parent), 'Nested alias')
    lib.visit_folder(str(source)); lib.visit_folder(str(path.parent)); lib.select(fid)
    plan = lib.plan('delete', [fid])
    result = lib.move_folder(str(source), str(destination))
    target = destination / source.name
    assert result['path'] == str(target) and result['previous_path'] == str(source)
    assert not source.exists() and (target / '.hidden').read_text() == 'hidden content'
    assert lib.resolve(fid) == target / 'nested' / path.name
    assert lib.resolve(fid).read_text() == 'preserved content'
    roots = {root['id']: root for root in lib.roots()}
    nested = next(root for root in roots.values() if root['name'] == 'Nested alias')
    assert nested['path'] == str(target / 'nested')
    assert lib.row(fid)['root_id'] == nested['id']
    for visit in lib.folder_visits():
        assert visit['available'] and Path(visit['path']).is_relative_to(Path(roots[visit['root_id']]['path']))
    assert lib.files(recent=True)['items'][0]['id'] == fid
    assert lib.files(q=str(target))['total'] == 1
    with pytest.raises(LibraryError, match='过期'): lib.apply(plan['token'], True)


def test_move_custom_root_preserves_root_id_and_alias(lib, tmp_path):
    source, path, fid, destination = setup_move(lib, tmp_path)
    custom = next(root for root in lib.add_root(str(source), 'My alias') if root['path'] == str(source))
    lib.move_folder(str(source), str(destination))
    root = next(root for root in lib.roots() if root['id'] == custom['id'])
    assert root['path'] == str(destination / source.name) and root['name'] == 'My alias'
    assert lib.row(fid)['root_id'] == custom['id']


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink'])
def test_move_never_replaces_existing_target(lib, tmp_path, kind):
    source, path, fid, destination = setup_move(lib, tmp_path)
    target = destination / source.name
    if kind == 'directory': target.mkdir()
    elif kind == 'file': target.write_text('keep')
    else: target.symlink_to(destination / 'missing')
    with pytest.raises(LibraryError, match='已经存在|符号链接'): lib.move_folder(str(source), str(destination))
    assert lib.resolve(fid) == path and (target.exists() or target.is_symlink())


def test_move_rejects_self_descendants_outside_symlinks_and_builtin(lib, tmp_path):
    source, path, fid, destination = setup_move(lib, tmp_path)
    root = source.parent
    outside = tmp_path / 'outside'; outside.mkdir()
    alias = root / 'alias'; alias.symlink_to(destination)
    for target in [source, path.parent, root, outside, alias, path]:
        with pytest.raises(LibraryError): lib.move_folder(str(source), str(target))
    for protected in [root, lib.cache, lib.db_path.parent]:
        with pytest.raises(LibraryError): lib.move_folder(str(protected), str(destination))
    assert lib.resolve(fid) == path


def test_move_rolls_back_database_on_cross_device_and_destination_race(lib, tmp_path):
    source, path, fid, destination = setup_move(lib, tmp_path)
    lib.visit_folder(str(source))
    visits = lib.folder_visits()
    with patch.object(lib, 'rename_directory_no_replace', side_effect=OSError(errno.EXDEV, 'cross device')):
        with pytest.raises(LibraryError, match='跨文件系统'): lib.move_folder(str(source), str(destination))
    assert lib.resolve(fid) == path and lib.folder_visits() == visits
    rename = lib.rename_directory_no_replace
    def race(old, new):
        new.mkdir()
        rename(old, new)
    with patch.object(lib, 'rename_directory_no_replace', side_effect=race):
        with pytest.raises(FileExistsError): lib.move_folder(str(source), str(destination))
    assert lib.resolve(fid) == path and (destination / source.name).is_dir()


def test_move_restores_filesystem_on_database_commit_failure(lib, tmp_path):
    source, path, fid, destination = setup_move(lib, tmp_path)
    transaction = lib.transaction
    @contextmanager
    def fail_commit():
        with transaction() as db:
            yield db
            raise sqlite3.OperationalError('simulated failure')
    with patch.object(lib, 'transaction', fail_commit):
        with pytest.raises(sqlite3.OperationalError): lib.move_folder(str(source), str(destination))
    assert lib.resolve(fid) == path and not (destination / source.name).exists()
