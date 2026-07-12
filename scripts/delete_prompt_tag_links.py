#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT_DIR / "data" / "prompts.sqlite3"
TARGET_TAG_IDS = (1, 2)


def validate_prompt_tags_table(conn):
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(prompt_tags)").fetchall()
    }
    missing = {"prompt_id", "tag_id"} - columns
    if missing:
        raise ValueError(
            "prompt_tags table is missing or invalid; missing columns: "
            f"{', '.join(sorted(missing))}"
        )


def association_counts(conn):
    counts = {}
    for tag_id in TARGET_TAG_IDS:
        row = conn.execute(
            """
            SELECT COUNT(*),
                   (SELECT name FROM tags WHERE id = ?)
            FROM prompt_tags
            WHERE tag_id = ?
            """,
            (tag_id, tag_id),
        ).fetchone()
        counts[tag_id] = {"count": row[0], "name": row[1]}
    return counts


def confirm_delete(input_func=input, output=print):
    try:
        answer = input_func("Delete these prompt_tags rows? [y/N] ")
    except (EOFError, OSError):
        output("No confirmation received; no rows were deleted.")
        return False
    return answer.strip().lower() in {"y", "yes"}


def delete_prompt_tag_links(db_path, confirmed=None, input_func=input, output=print):
    if not db_path.exists():
        raise FileNotFoundError(f"Prompt database not found: {db_path}")

    with sqlite3.connect(db_path) as conn:
        validate_prompt_tags_table(conn)
        counts = association_counts(conn)
        total = sum(item["count"] for item in counts.values())

        for tag_id, item in counts.items():
            name = f" ({item['name']})" if item["name"] is not None else ""
            output(f"tag_id={tag_id}{name}: {item['count']} association(s)")
        output(f"Total matching associations: {total}")

        if total == 0:
            return {"matched_rows": 0, "deleted_rows": 0}

        should_delete = confirmed if confirmed is not None else confirm_delete(input_func, output)
        if not should_delete:
            output("No rows were deleted.")
            return {"matched_rows": total, "deleted_rows": 0}

        placeholders = ", ".join("?" for _ in TARGET_TAG_IDS)
        cursor = conn.execute(
            f"DELETE FROM prompt_tags WHERE tag_id IN ({placeholders})",
            TARGET_TAG_IDS,
        )
        conn.commit()
        output(f"Deleted {cursor.rowcount} prompt_tags row(s).")
        return {"matched_rows": total, "deleted_rows": cursor.rowcount}


def main():
    parser = argparse.ArgumentParser(
        description="Delete all prompt_tags associations for tag_id 1 and 2."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite database path. Default: {DEFAULT_DB}",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete matching associations without asking for confirmation.",
    )
    args = parser.parse_args()

    try:
        delete_prompt_tag_links(args.db, confirmed=True if args.yes else None)
    except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
