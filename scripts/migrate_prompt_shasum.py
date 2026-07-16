#!/usr/bin/env python3
import argparse
import hashlib
import shlex
import shutil
import sqlite3
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT_DIR / "data" / "prompts.sqlite3"


def prompt_shasum(prompt):
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()


def recovery_hint(db_path):
    recovered_path = db_path.with_name(f"{db_path.stem}.recovered{db_path.suffix}")
    sqlite3_prefix = ""
    if shutil.which("sqlite3") is None:
        sqlite3_prefix = "Install the sqlite3 command-line tool first, then run:\n"
    return (
        "The database file appears to be corrupted, so migration was not attempted.\n"
        "Restore this database from a known-good backup, or recover what SQLite can read with:\n"
        f"{sqlite3_prefix}"
        f"  sqlite3 {shlex.quote(str(db_path))} \".recover\" | sqlite3 {shlex.quote(str(recovered_path))}\n"
        f"Then rerun this script against: {recovered_path}"
    )


def check_database_integrity(conn, db_path):
    try:
        rows = [row[0] for row in conn.execute("PRAGMA quick_check(20)").fetchall()]
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"{recovery_hint(db_path)}\nSQLite error: {exc}") from exc

    if rows != ["ok"]:
        details = "\n".join(f"  - {row}" for row in rows[:20])
        raise ValueError(f"{recovery_hint(db_path)}\nIntegrity check failed:\n{details}")


def table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def has_unique_shasum_index(conn):
    return bool(unique_shasum_indexes(conn))


def unique_shasum_indexes(conn):
    indexes = []
    for index in conn.execute("PRAGMA index_list(prompts)").fetchall():
        if not index[2]:
            continue
        index_name = index[1]
        quoted_name = index_name.replace('"', '""')
        columns = [
            row[2]
            for row in conn.execute(f'PRAGMA index_info("{quoted_name}")').fetchall()
        ]
        if columns == ["shasum"]:
            indexes.append({"name": index_name, "origin": index[3]})
    return indexes


def ensure_shasum_column(conn):
    columns = table_columns(conn, "prompts")
    if not columns:
        raise ValueError("prompts table does not exist.")
    if "prompt" not in columns:
        raise ValueError("prompts table does not contain a prompt column.")
    if "shasum" not in columns:
        conn.execute("ALTER TABLE prompts ADD COLUMN shasum TEXT")
        return True
    return False


def backfill_shasum(conn, skip_ids=None):
    skip_ids = set(skip_ids or [])
    updated = 0
    rows = conn.execute("SELECT id, prompt, shasum FROM prompts").fetchall()
    for prompt_id, prompt, current_shasum in rows:
        if prompt_id in skip_ids:
            continue
        shasum = prompt_shasum(prompt)
        if current_shasum == shasum:
            continue
        conn.execute("UPDATE prompts SET shasum = ? WHERE id = ?", (shasum, prompt_id))
        updated += 1
    return updated


def create_prompts_table(conn, table_name):
    quoted_name = table_name.replace('"', '""')
    conn.execute(f"""
        CREATE TABLE "{quoted_name}" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shasum TEXT NOT NULL,
            prompt TEXT NOT NULL,
            language TEXT NOT NULL,
            media_type TEXT NOT NULL,
            prompt_type TEXT NOT NULL,
            nsfw INTEGER NOT NULL,
            content_format TEXT NOT NULL,
            dynamic INTEGER NOT NULL,
            suggested_width INTEGER NOT NULL DEFAULT 1024,
            suggested_height INTEGER NOT NULL DEFAULT 768,
            created_at TEXT NOT NULL
        )
    """)


def rebuild_prompts_without_unique(conn):
    columns = [
        "id", "shasum", "prompt", "language", "media_type", "prompt_type", "nsfw",
        "content_format", "dynamic", "suggested_width", "suggested_height", "created_at",
    ]
    missing_columns = sorted(set(columns) - table_columns(conn, "prompts"))
    if missing_columns:
        raise ValueError(
            f"Cannot rebuild prompts table; missing columns: {', '.join(missing_columns)}"
        )

    sequence_row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'prompts'"
    ).fetchone()
    previous_sequence = sequence_row[0] if sequence_row is not None else 0
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM prompts ORDER BY id").fetchall()
    updated_rows = 0
    migrated_rows = []
    for row in rows:
        values = list(row)
        shasum = prompt_shasum(values[2])
        if values[1] != shasum:
            values[1] = shasum
            updated_rows += 1
        migrated_rows.append(values)

    conn.execute("DROP TABLE IF EXISTS prompts_migrated")
    create_prompts_table(conn, "prompts_migrated")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO prompts_migrated ({', '.join(columns)}) VALUES ({placeholders})",
        migrated_rows,
    )
    conn.execute("DROP TABLE prompts")
    conn.execute("ALTER TABLE prompts_migrated RENAME TO prompts")

    maximum_id = max((row[0] for row in migrated_rows), default=0)
    sequence = max(previous_sequence, maximum_id)
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('prompts', 'prompts_migrated')")
    if sequence:
        conn.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES ('prompts', ?)",
            (sequence,),
        )
    return updated_rows


def remove_unique_shasum_constraint(conn):
    indexes = unique_shasum_indexes(conn)
    if not indexes:
        return False, 0

    requires_rebuild = any(index["origin"] != "c" for index in indexes)
    if requires_rebuild:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with conn:
                updated_rows = rebuild_prompts_without_unique(conn)
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise ValueError(
                        "Foreign key check failed after rebuilding prompts table: "
                        f"{violations[:10]}"
                    )
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
        return True, updated_rows

    for index in indexes:
        quoted_name = index["name"].replace('"', '""')
        conn.execute(f'DROP INDEX "{quoted_name}"')
    return True, 0


def find_duplicate_prompt_groups(conn):
    groups = {}
    for prompt_id, prompt in conn.execute("SELECT id, prompt FROM prompts ORDER BY id").fetchall():
        shasum = prompt_shasum(prompt)
        group = groups.setdefault(shasum, {"shasum": shasum, "prompt": prompt, "ids": []})
        group["ids"].append(prompt_id)
    return [group for group in groups.values() if len(group["ids"]) > 1]


def prompt_preview(prompt, limit=120):
    normalized = " ".join(prompt.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit - 3]}..."


def print_duplicate_summary(duplicate_groups, output=print):
    if not duplicate_groups:
        return

    output(f"Found {len(duplicate_groups)} duplicate prompt group(s):")
    for index, group in enumerate(duplicate_groups, start=1):
        output(f"[{index}] shasum: {group['shasum']}")
        output(f"    count: {len(group['ids'])}")
        output(f"    ids: {', '.join(str(prompt_id) for prompt_id in group['ids'])}")
        output(f"    prompt: {prompt_preview(group['prompt'])}")


def delete_duplicate_prompt_groups(conn, duplicate_groups):
    removed = 0
    has_prompt_tags = table_exists(conn, "prompt_tags")
    for group in duplicate_groups:
        prompt_ids = group["ids"]
        keep_id = prompt_ids[0]
        for duplicate_id in prompt_ids[1:]:
            if has_prompt_tags:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO prompt_tags (prompt_id, tag_id)
                    SELECT ?, tag_id
                    FROM prompt_tags
                    WHERE prompt_id = ?
                    """,
                    (keep_id, duplicate_id),
                )
            conn.execute("DELETE FROM prompts WHERE id = ?", (duplicate_id,))
            removed += 1
    return removed


def migrate_db(db_path, delete_duplicates=None, output=print):
    if not db_path.exists():
        raise FileNotFoundError(f"Prompt database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        check_database_integrity(conn, db_path)
        added_column = ensure_shasum_column(conn)
        duplicate_groups = find_duplicate_prompt_groups(conn)
        duplicate_group_count = len(duplicate_groups)
        if duplicate_groups:
            print_duplicate_summary(duplicate_groups, output=output)

        should_delete_duplicates = bool(delete_duplicates)
        removed_duplicates = 0
        if should_delete_duplicates:
            removed_duplicates = delete_duplicate_prompt_groups(conn, duplicate_groups)

        unique_constraint_removed, rebuilt_rows = remove_unique_shasum_constraint(conn)
        updated_rows = rebuilt_rows + backfill_shasum(conn)
        conn.commit()

    return {
        "added_column": added_column,
        "updated_rows": updated_rows,
        "duplicate_group_count": duplicate_group_count,
        "removed_duplicates": removed_duplicates,
        "unique_constraint_removed": unique_constraint_removed,
        "index_created": False,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Add and backfill SHA-1 shasum values, and allow duplicate shasums in the "
            "prompt database."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite database path. Default: {DEFAULT_DB}",
    )
    duplicate_group = parser.add_mutually_exclusive_group()
    duplicate_group.add_argument(
        "--yes",
        action="store_true",
        help="Delete duplicate prompt rows without asking, keeping the lowest id in each group.",
    )
    duplicate_group.add_argument(
        "--no-delete",
        action="store_true",
        help="Preserve duplicate prompt rows (the default; retained for compatibility).",
    )
    args = parser.parse_args()

    delete_duplicates = None
    if args.yes:
        delete_duplicates = True
    elif args.no_delete:
        delete_duplicates = False

    try:
        result = migrate_db(args.db, delete_duplicates=delete_duplicates)
    except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    added = "added" if result["added_column"] else "already present"
    constraint_status = "removed" if result["unique_constraint_removed"] else "already absent"
    print(
        f"shasum column: {added}; "
        f"updated rows: {result['updated_rows']}; "
        f"duplicate groups: {result['duplicate_group_count']}; "
        f"removed duplicate rows: {result['removed_duplicates']}; "
        f"unique shasum constraint: {constraint_status}; "
        f"database: {args.db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
