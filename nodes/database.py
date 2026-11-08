"""Shared ToolBox SQLite location and connection policy."""
import sqlite3
import uuid
from pathlib import Path


DEFAULT_DB = Path(__file__).resolve().parents[1] / 'data' / 'prompts.sqlite3'
BUSY_TIMEOUT_MS = 5000


def open_connection(path=None, *, create=False, check_same_thread=True):
    path = Path(path if path is not None else DEFAULT_DB).resolve()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path.as_uri() + ('?mode=rwc' if create else '?mode=rw'), uri=True,
        timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=check_same_thread,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute(f'PRAGMA busy_timeout={BUSY_TIMEOUT_MS}')
        if create and conn.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
            conn.execute('PRAGMA journal_mode=WAL')
        # Prompts and Skill files are authoritative data, including after power loss.
        conn.execute('PRAGMA synchronous=FULL')
        return conn
    except BaseException:
        conn.close()
        raise


def initialize(conn):
    """Make a shared database usable regardless of which library creates it first."""
    from .prompt_schema import create_schema
    from .prompt_examples_schema import initialize_revision, revision_ready

    create_schema(conn)
    if not revision_ready(conn):
        initialize_revision(conn)


def initialize_revision(conn, domain, tables):
    """Track only writes to one library's tables, including writes by other tools."""
    revision_table = f'toolbox_{domain}_revision'
    conn.execute(f'''CREATE TABLE IF NOT EXISTS {revision_table} (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), epoch TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0
    )''')
    conn.execute(f'INSERT OR IGNORE INTO {revision_table}(singleton,epoch) VALUES(1,?)', (uuid.uuid4().hex,))
    for table in tables:
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS toolbox_{domain}_rev_{table}_{event.lower()}
                AFTER {event} ON {table} BEGIN
                UPDATE {revision_table} SET revision=revision+1 WHERE singleton=1;
                END''')
