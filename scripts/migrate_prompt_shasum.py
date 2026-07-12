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
    for index in conn.execute("PRAGMA index_list(prompts)").fetchall():
        if not index[2]:
            continue
        index_name = index[1]
        columns = [row[2] for row in conn.execute(f"PRAGMA index_info({index_name})").fetchall()]
        if columns == ["shasum"]:
            return True
    return False


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


def confirm_delete_duplicates(input_func=input, output=print):
    try:
        answer = input_func("Delete duplicate rows and merge their tags? [y/N] ")
    except (EOFError, OSError):
        output("No confirmation received; duplicate rows will not be deleted.")
        return False
    return answer.strip().lower() in {"y", "yes"}


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


def migrate_db(db_path, delete_duplicates=None, input_func=input, output=print):
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

        should_delete_duplicates = False
        if duplicate_groups:
            if delete_duplicates is None:
                should_delete_duplicates = confirm_delete_duplicates(input_func=input_func, output=output)
            else:
                should_delete_duplicates = bool(delete_duplicates)

        removed_duplicates = 0
        if should_delete_duplicates:
            removed_duplicates = delete_duplicate_prompt_groups(conn, duplicate_groups)
            duplicate_groups = []

        skip_ids = set()
        if duplicate_groups and has_unique_shasum_index(conn):
            skip_ids = {
                prompt_id
                for group in duplicate_groups
                for prompt_id in group["ids"]
            }
        updated_rows = backfill_shasum(conn, skip_ids=skip_ids)

        index_created = False
        if duplicate_groups:
            output("Unique shasum index skipped; resolve duplicate prompt rows first.")
        else:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prompts_shasum ON prompts(shasum)")
            index_created = True
        conn.commit()

    return {
        "added_column": added_column,
        "updated_rows": updated_rows,
        "duplicate_group_count": duplicate_group_count,
        "removed_duplicates": removed_duplicates,
        "index_created": index_created,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Add and backfill SHA-1 shasum values for the prompt database."
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
        help="Report duplicate prompt rows but never delete them.",
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
    index_status = "created or already present" if result["index_created"] else "skipped"
    print(
        f"shasum column: {added}; "
        f"updated rows: {result['updated_rows']}; "
        f"duplicate groups: {result['duplicate_group_count']}; "
        f"removed duplicate rows: {result['removed_duplicates']}; "
        f"unique index: {index_status}; "
        f"database: {args.db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
