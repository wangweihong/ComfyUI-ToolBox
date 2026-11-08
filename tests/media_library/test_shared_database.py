"""Exercise real libraries against one disposable database, never production data."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from pathlib import Path
import threading

import pytest
from support import Library, LibraryError, metadata
from nodes import database, prompt_library, prompt_nodes, skill_library
from nodes.skill_nodes import ToolBoxSkillReader


def write_prompt(text='shared prompt'):
    return prompt_nodes.ToolBoxPromptWriter().write_prompt(
        0, text, 'zh', 'image', 'natural', False, 'plaintext', False, 64, 64, 'prompt-only',
    )[0]


def write_skill():
    return skill_library.create_entry(dict(
        name='shared skill', entry_type='skill', description='', content='skill body', tags='skill-only',
    ))


@pytest.fixture
def shared(lib, monkeypatch):
    monkeypatch.setattr(database, 'DEFAULT_DB', lib.db_path)
    return lib


def test_media_first_initializes_prompt_tables_without_examples(shared):
    assert prompt_library.list_prompts({})['total'] == 0
    assert skill_library.list_entries({})['total'] == 0
    assert prompt_nodes.prompt_data_revision() != prompt_nodes.database_revision()
    prompt_id = write_prompt()
    skill = write_skill()
    path = Path(shared.roots()[0]['path']) / 'source.txt'
    path.write_text('media body')
    item = shared.select(path=str(path))
    with closing(database.open_connection()) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'prompts', 'skill_entries', 'media_roots', 'media_files', 'media_recents'} <= tables
        assert not tables & {'roots', 'files', 'recents', 'prompt_examples'}
        assert conn.execute('SELECT path FROM media_files WHERE id=?', (item['id'],)).fetchone()[0] == str(path)
    assert prompt_library.detail(prompt_id)['prompt'] == 'shared prompt'
    assert skill_library.detail(skill['id'])['content'] == 'skill body'
    assert path.read_text() == 'media body'
    assert not list(shared.cache.parent.rglob('catalog.sqlite3'))


@pytest.mark.parametrize('first', ['prompt', 'skill'])
def test_opening_media_preserves_other_libraries(tmp_path, monkeypatch, first):
    db_path = tmp_path / 'data' / 'prompts.sqlite3'
    monkeypatch.setattr(database, 'DEFAULT_DB', db_path)
    prompt_id = write_prompt() if first == 'prompt' else None
    skill = write_skill() if first == 'skill' else None
    before = prompt_nodes.prompt_data_revision()
    media = Library(db_path, tmp_path / 'cache')
    try:
        assert media.db_path == database.DEFAULT_DB
        assert prompt_nodes.prompt_data_revision() == before
        if prompt_id:
            assert prompt_library.detail(prompt_id)['prompt'] == 'shared prompt'
        if skill:
            assert skill_library.detail(skill['id'])['content'] == 'skill body'
        assert prompt_library.list_prompts({})['total'] == (1 if prompt_id else 0)
    finally:
        media.close()


def test_media_writes_do_not_invalidate_prompt_or_skill_nodes(shared):
    write_prompt()
    prompt_revision = prompt_nodes.prompt_data_revision()
    skill = write_skill()
    assert prompt_nodes.prompt_data_revision() == prompt_revision
    skill_revision = ToolBoxSkillReader.IS_CHANGED(id=skill['id'])
    path = Path(shared.roots()[0]['path']) / 'version.txt'
    path.write_text('before')
    shared.scan()
    item = shared.select(path=str(path))
    shared.apply(shared.plan('rename', [item['id']], template='changed')['token'], True)
    assert prompt_nodes.prompt_data_revision() == prompt_revision
    assert ToolBoxSkillReader.IS_CHANGED(id=skill['id']) == skill_revision
    with closing(database.open_connection()) as conn, conn:
        conn.execute('UPDATE skill_entries SET content=? WHERE id=?', ('new body', skill['id']))
    assert ToolBoxSkillReader.IS_CHANGED(id=skill['id']) != skill_revision
    assert prompt_nodes.prompt_data_revision() == prompt_revision
    write_prompt('new prompt')
    assert prompt_nodes.prompt_data_revision() != prompt_revision


def test_database_and_cache_cannot_be_indexed_or_selected(tmp_path):
    store = Library(tmp_path / 'prompts.sqlite3', tmp_path / 'cache', {'input': str(tmp_path)})
    try:
        (tmp_path / 'visible.txt').write_text('visible')
        (store.cache / 'private.txt').write_text('private cache')
        store.scan(recursive=True)
        assert store.status['errors'] == []
        assert [row['name'] for row in store.files()['items']] == ['visible.txt']
        assert store.cache.name not in {row['name'] for row in store.folders(str(tmp_path))}
        for path in [store.db_path, *(Path(str(store.db_path) + suffix) for suffix in ('-wal', '-shm', '-journal')), store.cache / 'private.txt']:
            with pytest.raises(LibraryError, match='数据库或预览缓存'):
                store.select(path=str(path))
        # A rename target must not become a reserved SQLite sidecar, even if absent.
        internal_source = tmp_path / 'other.sqlite3-journal'
        internal_source.write_text('ordinary file')
        file_id = store.upsert(internal_source)
        plan = store.plan('rename', [file_id], template='prompts')
        assert '数据库或预览缓存' in plan['entries'][0]['error']
        assert internal_source.exists()
    finally:
        store.close()


def test_media_transaction_rolls_back_with_nested_calls(shared):
    with pytest.raises(RuntimeError):
        with shared.transaction() as conn:
            conn.execute("INSERT INTO media_roots VALUES('outer','/outer','outer',0)")
            with shared.transaction() as nested:
                nested.execute("INSERT INTO media_roots VALUES('inner','/inner','inner',0)")
            raise RuntimeError('rollback both')
    assert not {row['id'] for row in shared.roots()} & {'outer', 'inner'}


def test_media_write_waits_for_another_library_transaction(shared):
    path = Path(shared.roots()[0]['path']) / 'waiting.txt'
    path.write_text('waiting')
    started = threading.Event()

    def select():
        started.set()
        return shared.select(path=str(path))

    with closing(database.open_connection()) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.execute('BEGIN IMMEDIATE')
        pending = pool.submit(select)
        try:
            assert started.wait(2)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.05)
            # WAL permits a prompt read while the other writer holds its transaction.
            assert prompt_library.list_prompts({})['total'] == 0
        finally:
            writer.rollback()
        assert pending.result(timeout=3)['path'] == str(path)


def test_scan_and_prompt_skill_writes_can_overlap(shared):
    root = Path(shared.roots()[0]['path'])
    for index in range(12):
        (root / f'{index}.txt').write_text(f'file {index}')
    gate = threading.Barrier(3)

    def scan():
        gate.wait(timeout=5)
        shared.scan()

    def prompts():
        gate.wait(timeout=5)
        for index in range(12):
            write_prompt(f'prompt {index}')

    def skills():
        gate.wait(timeout=5)
        for _ in range(12):
            write_skill()

    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = [pool.submit(operation) for operation in (scan, prompts, skills)]
        for task in pending:
            task.result(timeout=20)
    assert shared.status['errors'] == []
    assert shared.files()['total'] == prompt_library.list_prompts({})['total'] == skill_library.list_entries({})['total'] == 12
    assert shared.db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_slow_media_probe_does_not_hold_shared_write_lock(shared, monkeypatch):
    path = Path(shared.roots()[0]['path']) / 'slow.txt'
    path.write_text('slow')
    entered, release = threading.Event(), threading.Event()
    inspect = metadata.inspect

    def slow_probe(path):
        entered.set()
        assert release.wait(5)
        return inspect(path)

    monkeypatch.setattr(metadata, 'inspect', slow_probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scanning = pool.submit(shared.scan)
        try:
            assert entered.wait(2)
            assert pool.submit(write_prompt).result(timeout=2) == 1
        finally:
            release.set()
        scanning.result(timeout=3)


def test_all_connections_use_shared_policy(shared):
    with prompt_nodes.connect_db() as prompt, skill_library.connect() as skill:
        for conn in (shared.db, prompt, skill):
            assert conn.execute('PRAGMA database_list').fetchone()['file'] == str(shared.db_path)
            for name, expected in [('journal_mode', 'wal'), ('foreign_keys', 1), ('synchronous', 2), ('busy_timeout', 5000)]:
                assert conn.execute(f'PRAGMA {name}').fetchone()[0] == expected


def test_prompt_reimport_restores_revision_without_examples(shared):
    from scripts import import_prompts

    write_prompt()
    skill = write_skill()
    before = prompt_nodes.prompt_data_revision()
    import_prompts.import_records([(1, 'reimported')], shared.db_path, dict(
        language='zh', media_type='image', prompt_type='natural', nsfw=False,
        content_format='plaintext', dynamic=False, suggested_width=64, suggested_height=64,
    ))
    assert prompt_library.detail(1)['prompt'] == 'reimported'
    assert prompt_nodes.prompt_data_revision() != before
    assert prompt_nodes.prompt_data_revision() != prompt_nodes.database_revision()
    assert skill_library.detail(skill['id'])['content'] == 'skill body'
    assert shared.roots()
