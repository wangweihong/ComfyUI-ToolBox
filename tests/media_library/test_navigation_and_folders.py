import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from support import LibraryError


def add(lib, name, text='content'):
    path = Path(lib.roots()[0]['path']) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path, lib.upsert(path)


def test_neighbors_cross_page_boundaries_in_filtered_sort_order(lib):
    ids = [add(lib, f'asset-{index:03d}.txt')[1] for index in range(83)]
    add(lib, 'not-in-filter.txt')
    add(lib, 'asset-other.zip')
    add(lib, 'child/asset-nested.txt')
    query = dict(root_id=lib.roots()[0]['id'], q='asset-', kind='text', sort='name', direction='asc')
    page = lib.files(**query, focus_id=ids[80])
    assert page['total'] == 83 and page['offset'] == 80
    assert page['focus'] == dict(position=80, previous_id=ids[79], next_id=ids[81])
    assert lib.files(**query, focus_id=ids[0], limit=1)['focus'] == dict(position=0, previous_id=None, next_id=ids[1])
    assert lib.files(**query, focus_id=ids[-1], limit=1)['focus'] == dict(position=82, previous_id=ids[-2], next_id=None)
    reverse = lib.files(**(query | {'direction': 'desc'}), focus_id=ids[80], limit=1)
    assert reverse['focus'] == dict(position=2, previous_id=ids[81], next_id=ids[79])
    assert lib.files(**query, focus_id='not-in-list')['focus'] is None


def test_neighbors_follow_recents_and_stable_ties(lib):
    ids = [add(lib, f'child-{index}/same.txt')[1] for index in range(3)]
    rows = lib.files(root_id=lib.roots()[0]['id'], recursive=True, sort='size', direction='asc')['items']
    ordered = [row['id'] for row in rows]
    assert ordered == sorted(ids)
    focus = lib.files(recursive=True, sort='size', direction='asc', focus_id=ordered[1])['focus']
    assert focus == dict(position=1, previous_id=ordered[0], next_id=ordered[2])
    for file_id in ids:
        lib.select(file_id)
    assert lib.files(recent=True, focus_id=ids[1])['focus'] == dict(position=1, previous_id=ids[2], next_id=ids[0])


def test_directory_rename_updates_nested_assets_recents_and_registered_roots(lib):
    first, first_id = add(lib, 'source/nested/one.txt', 'searchable prompt')
    second, second_id = add(lib, 'source/two.txt')
    unaffected, unaffected_id = add(lib, 'source-other/three.txt')
    lib.add_root(str(first.parent), 'Nested alias')
    lib.select(first_id)
    lib.select(second_id)
    source = second.parent
    result = lib.rename_folder(str(source), 'renamed_%目录')
    target = source.with_name('renamed_%目录')
    assert result['updated_files'] == 2
    assert lib.resolve(first_id) == target / 'nested' / 'one.txt'
    assert lib.resolve(second_id) == target / 'two.txt'
    assert lib.resolve(unaffected_id) == unaffected
    assert not source.exists() and lib.resolve(first_id).read_text() == 'searchable prompt'
    nested_root = next(root for root in lib.roots() if root['name'] == 'Nested alias')
    assert nested_root['path'] == str(target / 'nested')
    assert lib.row(first_id)['root_id'] == nested_root['id']
    assert {row['id'] for row in lib.files(recent=True)['items']} == {first_id, second_id}
    assert lib.files(q='searchable prompt')['total'] == 1
    assert lib.files(q='renamed_%目录')['total'] == 2


def test_custom_root_rename_keeps_id_and_updates_display_name(lib, tmp_path):
    source = tmp_path / 'custom'
    source.mkdir()
    path = source / 'source.txt'
    path.write_text('root file')
    root = next(root for root in lib.add_root(str(source), 'Custom alias') if root['path'] == str(source))
    file_id = lib.upsert(path)
    lib.rename_folder(str(source), 'new-root')
    updated = next(row for row in lib.roots() if row['id'] == root['id'])
    assert updated['name'] == 'new-root'
    assert updated['path'] == str(tmp_path / 'new-root')
    assert lib.resolve(file_id) == tmp_path / 'new-root' / 'source.txt'


def test_rename_preserves_tombstones_without_hiding_the_current_asset(lib):
    path, old_id = add(lib, 'source/reused.txt')
    lib.apply(lib.plan('delete', [old_id])['token'], True)
    path.write_text('new content')
    new_id = lib.upsert(path)
    lib.rename_folder(str(path.parent), 'renamed')
    assert lib.row(old_id)['missing'] == 1
    assert lib.row(new_id)['missing'] == 0
    assert lib.resolve(new_id).read_text() == 'new content'


def test_stale_destination_index_is_not_reused(lib):
    stale, stale_id = add(lib, 'target/same.txt')
    stale.unlink()
    stale.parent.rmdir()
    source, source_id = add(lib, 'source/same.txt', 'source content')
    lib.rename_folder(str(source.parent), 'target')
    assert lib.row(stale_id)['missing'] == 1
    assert lib.resolve(source_id) == stale
    assert lib.files()['total'] == 1


@pytest.mark.parametrize('name', ['', '.', '..', '../escape', '/absolute', 'nested/name', 'nested\\name', 'null\0name', None])
def test_invalid_directory_names_leave_files_untouched(lib, name):
    source, file_id = add(lib, 'source/file.txt')
    with pytest.raises(LibraryError):
        lib.rename_folder(str(source.parent), name)
    assert lib.resolve(file_id) == source


def test_default_roots_symlinks_internal_data_and_outside_paths_are_protected(lib, tmp_path):
    path, _ = add(lib, 'source/file.txt')
    outside = tmp_path / 'outside'
    outside.mkdir()
    alias = path.parent.parent / 'alias'
    alias.symlink_to(outside, target_is_directory=True)
    lib.add_root(str(tmp_path))
    for source in [path.parent.parent, tmp_path, alias, lib.db_path.parent, lib.cache]:
        with pytest.raises(LibraryError):
            lib.rename_folder(str(source), 'new-name')
    with pytest.raises(LibraryError):
        lib.rename_folder(str(tmp_path.parent), 'outside-scope')
    with pytest.raises(LibraryError):
        lib.rename_folder(str(path), 'file-is-not-a-directory')
    with pytest.raises(LibraryError):
        lib.rename_folder(str(path.parent), 'source')
    assert path.exists()


@pytest.mark.parametrize('kind', ['empty-directory', 'file', 'symlink'])
def test_directory_rename_refuses_existing_targets(lib, kind):
    source, file_id = add(lib, 'source/file.txt')
    target = source.parent.with_name('occupied')
    if kind == 'empty-directory': target.mkdir()
    elif kind == 'file': target.write_text('keep')
    else: target.symlink_to(target.with_name('missing'), target_is_directory=True)
    with pytest.raises(LibraryError, match='已经存在'):
        lib.rename_folder(str(source.parent), 'occupied')
    assert lib.resolve(file_id) == source
    assert target.exists() or target.is_symlink()


def test_directory_target_created_during_rename_is_never_overwritten(lib):
    source, file_id = add(lib, 'source/file.txt')
    rename = lib.rename_directory_no_replace

    def race(old, new):
        new.mkdir()
        return rename(old, new)

    with patch.object(lib, 'rename_directory_no_replace', side_effect=race), pytest.raises(FileExistsError):
        lib.rename_folder(str(source.parent), 'occupied')
    assert lib.resolve(file_id) == source
    assert source.parent.with_name('occupied').is_dir()


def test_database_failure_after_filesystem_rename_restores_directory(lib):
    source, file_id = add(lib, 'source/file.txt')
    transaction = lib.transaction

    @contextmanager
    def fail_commit():
        with transaction() as db:
            yield db
            raise sqlite3.OperationalError('simulated commit failure')

    with patch.object(lib, 'transaction', fail_commit), pytest.raises(sqlite3.OperationalError):
        lib.rename_folder(str(source.parent), 'renamed')
    assert lib.resolve(file_id) == source
    assert not source.parent.with_name('renamed').exists()


def test_directory_rename_invalidates_pending_file_operations(lib):
    source, file_id = add(lib, 'source/file.txt')
    plan = lib.plan('delete', [file_id])
    lib.rename_folder(str(source.parent), 'renamed')
    with pytest.raises(LibraryError, match='过期'):
        lib.apply(plan['token'], True)
    assert lib.resolve(file_id).exists()
