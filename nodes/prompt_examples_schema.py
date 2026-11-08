"""Additive example mapping and prompt-only cache revision. No filesystem workers."""
import uuid

TABLES = ("prompts", "tags", "prompt_tags")
TRIGGERS = {f"toolbox_prompt_rev_{table}_{event.lower()}" for table in TABLES for event in ("INSERT", "UPDATE", "DELETE")}


def table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def revision_ready(conn):
    if not table_exists(conn, "toolbox_prompt_revision"):
        return False
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    return TRIGGERS <= names


def initialize(conn):
    if not all(table_exists(conn, name) for name in TABLES):
        raise ValueError("请先初始化提示词库，再启用生成示例。")
    conn.execute("""CREATE TABLE IF NOT EXISTS prompt_examples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_id INTEGER NOT NULL, prompt_shasum TEXT NOT NULL, relative_path TEXT NOT NULL,
        media_type TEXT NOT NULL, source TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        job_id TEXT, node_id TEXT, file_size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'available', checked_at TEXT, message TEXT NOT NULL DEFAULT '',
        UNIQUE(prompt_id,prompt_shasum,relative_path)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_examples_version ON prompt_examples(prompt_id,prompt_shasum,id DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_examples_status ON prompt_examples(status,id)")
    initialize_revision(conn)


def initialize_revision(conn):
    ready = revision_ready(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS toolbox_prompt_revision (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), epoch TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("INSERT OR IGNORE INTO toolbox_prompt_revision(singleton,epoch) VALUES(1,?)", (uuid.uuid4().hex,))
    if not ready:
        conn.execute("UPDATE toolbox_prompt_revision SET epoch=?,revision=revision+1 WHERE singleton=1", (uuid.uuid4().hex,))
    for table in TABLES:
        for event in ("INSERT", "UPDATE", "DELETE"):
            name = f"toolbox_prompt_rev_{table}_{event.lower()}"
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {name} AFTER {event} ON {table}
                BEGIN UPDATE toolbox_prompt_revision SET revision=revision+1 WHERE singleton=1; END""")


def restore_if_initialized(conn):
    if table_exists(conn, "prompt_examples"):
        initialize(conn)
    elif table_exists(conn, "toolbox_prompt_revision"):
        initialize_revision(conn)
