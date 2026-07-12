#!/usr/bin/env python3
import argparse
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT_DIR / "prompts"
DEFAULT_DB = ROOT_DIR / "data" / "prompts.sqlite3"

RECORD_RE = re.compile(r"^\[(\d+)\].*?\|\s*提示词:\s*(.*)$")
LANGUAGES = ("zh", "en")
PROMPT_TYPES = ("natural", "danbooru")
CONTENT_FORMATS = ("plaintext", "json")
MEDIA_TYPES = ("image", "video", "audio", "music")


def normalize_prompt(lines):
    return re.sub(r"\s+", " ", " ".join(line.strip() for line in lines)).strip()


def prompt_shasum(prompt):
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()


def parse_prompt_file(path):
    records = []
    current_id = None
    current_lines = []

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.rstrip("\n")
            match = RECORD_RE.match(line)

            if match:
                if current_id is not None:
                    records.append((current_id, normalize_prompt(current_lines)))

                current_id = int(match.group(1))
                current_lines = [match.group(2)]
            elif current_id is not None:
                current_lines.append(line)

    if current_id is not None:
        records.append((current_id, normalize_prompt(current_lines)))

    return records


def parse_prompt_directory(path):
    records = []

    for file in sorted(path.glob("*.txt")):
        print(f"Reading {file}")
        records.extend(parse_prompt_file(file))

    return records


def parse_tags(tags):
    if not tags:
        return []

    seen = set()
    parsed = []
    for tag in tags.split(","):
        name = tag.strip().lower()
        if name and name not in seen:
            seen.add(name)
            parsed.append(name)
    return parsed


def validate_tag_options(tags, apply_tags_to_all):
    if tags and not apply_tags_to_all:
        raise ValueError(
            "--tags applies the listed tags to every imported prompt. "
            "Pass --apply-tags-to-all to confirm batch-wide tag assignment."
        )


def create_schema(conn):
    conn.execute("DROP TABLE IF EXISTS prompt_tags")
    conn.execute("DROP TABLE IF EXISTS tags")
    conn.execute("DROP TABLE IF EXISTS prompts")
    conn.execute("""
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shasum TEXT NOT NULL UNIQUE,
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
    conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    conn.execute("""
        CREATE TABLE prompt_tags (
            prompt_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY(prompt_id, tag_id),
            FOREIGN KEY(prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)


def insert_tags(conn, prompt_id, tags):
    for tag in tags:
        tag = tag.strip().lower()
        if not tag:
            continue

        row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
        if row is not None:
            tag_id = row[0]
        else:
            try:
                tag_id = conn.execute("INSERT INTO tags (name) VALUES (?)", (tag,)).lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
                if row is None:
                    raise
                tag_id = row[0]
        conn.execute(
            "INSERT OR IGNORE INTO prompt_tags (prompt_id, tag_id) VALUES (?, ?)",
            (prompt_id, tag_id),
        )


def import_records(records, db_path, metadata, apply_tags_to_all=False):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    unique_records = []
    seen_shasums = set()
    for prompt_id, prompt in records:
        shasum = prompt_shasum(prompt)
        if shasum in seen_shasums:
            continue
        seen_shasums.add(shasum)
        unique_records.append((prompt_id, shasum, prompt))

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)
        created_at = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            """
            INSERT INTO prompts (
                id, shasum, prompt, language, media_type, prompt_type, nsfw, content_format, dynamic,
                suggested_width, suggested_height, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    prompt_id,
                    shasum,
                    prompt,
                    metadata["language"],
                    metadata["media_type"],
                    metadata["prompt_type"],
                    metadata["nsfw"],
                    metadata["content_format"],
                    metadata["dynamic"],
                    metadata["suggested_width"],
                    metadata["suggested_height"],
                    created_at,
                )
                for prompt_id, shasum, prompt in unique_records
            ],
        )

        if apply_tags_to_all:
            for prompt_id, _, _ in unique_records:
                insert_tags(conn, prompt_id, metadata["tags"])

        conn.commit()

    return len(unique_records)


def main():
    parser = argparse.ArgumentParser(
        description="Import prompt records from prompts directory into SQLite database."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Prompt directory or single prompt file. Default: {DEFAULT_INPUT_DIR}"
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite database path. Default: {DEFAULT_DB}"
    )
    parser.add_argument("--language", choices=LANGUAGES, required=True, help="Prompt language metadata.")
    parser.add_argument("--media-type", choices=MEDIA_TYPES, required=True, help="Prompt media type metadata.")
    parser.add_argument("--prompt-type", choices=PROMPT_TYPES, required=True, help="Prompt style metadata.")
    parser.add_argument("--content-format", choices=CONTENT_FORMATS, default="plaintext", help="Prompt content format.")
    parser.add_argument("--tags", default="", help='Comma-separated tags, for example "landscape,night".')
    parser.add_argument(
        "--apply-tags-to-all",
        action="store_true",
        help="Confirm that --tags should be attached to every imported prompt.",
    )
    parser.add_argument("--width", type=int, default=1024, help="Suggested width metadata. Default: 1024")
    parser.add_argument("--height", type=int, default=768, help="Suggested height metadata. Default: 768")

    safety_group = parser.add_mutually_exclusive_group(required=True)
    safety_group.add_argument("--nsfw", action="store_true", help="Mark imported prompts as NSFW.")
    safety_group.add_argument("--safe", action="store_true", help="Mark imported prompts as safe/non-NSFW.")

    dynamic_group = parser.add_mutually_exclusive_group(required=True)
    dynamic_group.add_argument("--dynamic", action="store_true", help="Mark imported prompts as dynamic.")
    dynamic_group.add_argument("--static", action="store_true", help="Mark imported prompts as non-dynamic.")

    args = parser.parse_args()

    if args.width <= 0 or args.height <= 0:
        raise ValueError("--width and --height must be positive integers.")

    tags = parse_tags(args.tags)
    validate_tag_options(tags, args.apply_tags_to_all)

    if not args.input.exists():
        raise FileNotFoundError(f"Prompt path not found: {args.input}")

    if args.input.is_dir():
        records = parse_prompt_directory(args.input)
    else:
        records = parse_prompt_file(args.input)

    if not records:
        raise ValueError(f"No prompt records found in: {args.input}")

    metadata = {
        "language": args.language,
        "media_type": args.media_type,
        "prompt_type": args.prompt_type,
        "nsfw": 1 if args.nsfw else 0,
        "content_format": args.content_format,
        "dynamic": 1 if args.dynamic else 0,
        "tags": tags,
        "suggested_width": args.width,
        "suggested_height": args.height,
    }

    imported_count = import_records(records, args.db, metadata, apply_tags_to_all=args.apply_tags_to_all)

    print(f"Imported {imported_count} prompts into {args.db}")


if __name__ == "__main__":
    main()
