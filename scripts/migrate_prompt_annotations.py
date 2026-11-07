#!/usr/bin/env python3
"""Back up a prompt database and add missing manual annotation columns."""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nodes.prompt_schema import ANNOTATION_DEFAULTS, add_missing_annotations
from scripts.migrate_prompt_shasum import check_database_integrity

DEFAULT_DB = ROOT_DIR / "data" / "prompts.sqlite3"


def migrate_db(db_path):
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"Prompt database not found: {db_path}")
    backup_path = None
    with sqlite3.connect(db_path.as_uri() + "?mode=rw", uri=True) as conn:
        check_database_integrity(conn, db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
        if not columns:
            raise ValueError("prompts table does not exist")
        if set(ANNOTATION_DEFAULTS) <= columns:
            return {"added_columns": [], "backup": None}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = db_path.with_name(f"{db_path.name}.{stamp}.bak")
        with sqlite3.connect(backup_path) as backup:
            conn.backup(backup)
        conn.execute("BEGIN IMMEDIATE")
        added = add_missing_annotations(conn)
        conn.commit()
    return {"added_columns": added, "backup": str(backup_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        result = migrate_db(args.db)
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Added columns: {', '.join(result['added_columns']) or 'none'}")
    if result["backup"]:
        print(f"Backup: {result['backup']}")


if __name__ == "__main__":
    main()
