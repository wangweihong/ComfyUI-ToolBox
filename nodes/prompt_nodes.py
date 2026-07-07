import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT_DB = ROOT_DIR / "data" / "prompts.sqlite3"

LANGUAGE_FILTERS = ["全部", "zh", "en"]
LANGUAGES = ["zh", "en"]
MEDIA_TYPE_FILTERS = ["全部", "image", "video", "audio", "music"]
MEDIA_TYPES = ["image", "video", "audio", "music"]
PROMPT_TYPE_FILTERS = ["全部", "natural", "danbooru"]
PROMPT_TYPES = ["natural", "danbooru"]
SAFETY_FILTERS = ["全部", "nsfw", "safe"]
CONTENT_FORMAT_FILTERS = ["全部", "plaintext", "json"]
CONTENT_FORMATS = ["plaintext", "json"]
DYNAMIC_FILTERS = ["全部", "dynamic", "static"]


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


def require_enum(name, value, allowed):
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")


def create_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    conn.execute("CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prompt_tags (
            prompt_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY(prompt_id, tag_id),
            FOREIGN KEY(prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)


def connect_db(create=False):
    if not DEFAULT_PROMPT_DB.exists() and not create:
        raise ValueError(f"Prompt database not found: {DEFAULT_PROMPT_DB}. Run: python3 scripts/import_prompts.py")

    DEFAULT_PROMPT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DEFAULT_PROMPT_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if create:
        create_schema(conn)
    return conn


def ensure_schema(conn):
    required_columns = {
        "id", "prompt", "language", "media_type", "prompt_type", "nsfw", "content_format",
        "dynamic", "suggested_width", "suggested_height", "created_at",
    }
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(prompts)").fetchall()}
    if not required_columns.issubset(columns):
        raise ValueError(f"Invalid prompt database schema: {DEFAULT_PROMPT_DB}. Run: python3 scripts/import_prompts.py")


def insert_tags(conn, prompt_id, tags):
    for tag in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO prompt_tags (prompt_id, tag_id) VALUES (?, ?)",
            (prompt_id, tag_id),
        )


def row_tags(conn, prompt_id):
    rows = conn.execute(
        """
        SELECT t.name
        FROM tags t
        JOIN prompt_tags pt ON pt.tag_id = t.id
        WHERE pt.prompt_id = ?
        ORDER BY t.name
        """,
        (prompt_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def metadata_json(conn, row):
    metadata = {
        "id": row["id"],
        "language": row["language"],
        "media_type": row["media_type"],
        "prompt_type": row["prompt_type"],
        "nsfw": bool(row["nsfw"]),
        "content_format": row["content_format"],
        "dynamic": bool(row["dynamic"]),
        "width": row["suggested_width"],
        "height": row["suggested_height"],
        "suggested_width": row["suggested_width"],
        "suggested_height": row["suggested_height"],
        "created_at": row["created_at"],
        "tags": row_tags(conn, row["id"]),
    }
    return json.dumps(metadata, ensure_ascii=False)


class ToolBoxRandomPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "language": (LANGUAGE_FILTERS, {"default": "全部"}),
                "media_type": (MEDIA_TYPE_FILTERS, {"default": "全部"}),
                "prompt_type": (PROMPT_TYPE_FILTERS, {"default": "全部"}),
                "safety": (SAFETY_FILTERS, {"default": "全部"}),
                "content_format": (CONTENT_FORMAT_FILTERS, {"default": "全部"}),
                "dynamic": (DYNAMIC_FILTERS, {"default": "全部"}),
                "match_size": ("BOOLEAN", {"default": False}),
                "width": ("INT", {"default": 1024, "min": 1, "max": 16384, "step": 1}),
                "height": ("INT", {"default": 768, "min": 1, "max": 16384, "step": 1}),
                "tags": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("INT", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("id", "prompt", "width", "height", "metadata")
    FUNCTION = "random_prompt"
    CATEGORY = "eazy-toolbox/prompt"

    def random_prompt(
        self, seed, language, media_type, prompt_type, safety, content_format, dynamic,
        match_size, width, height, tags,
    ):
        with connect_db() as conn:
            ensure_schema(conn)
            where = []
            params = []

            if language != "全部":
                where.append("p.language = ?")
                params.append(language)
            if media_type != "全部":
                where.append("p.media_type = ?")
                params.append(media_type)
            if prompt_type != "全部":
                where.append("p.prompt_type = ?")
                params.append(prompt_type)
            if safety != "全部":
                where.append("p.nsfw = ?")
                params.append(1 if safety == "nsfw" else 0)
            if content_format != "全部":
                where.append("p.content_format = ?")
                params.append(content_format)
            if dynamic != "全部":
                where.append("p.dynamic = ?")
                params.append(1 if dynamic == "dynamic" else 0)
            if match_size:
                where.append("p.suggested_width = ?")
                where.append("p.suggested_height = ?")
                params.extend([int(width), int(height)])

            for tag in parse_tags(tags):
                where.append("""
                    EXISTS (
                        SELECT 1
                        FROM prompt_tags pt
                        JOIN tags t ON t.id = pt.tag_id
                        WHERE pt.prompt_id = p.id AND t.name = ?
                    )
                """)
                params.append(tag)

            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            count = conn.execute(f"SELECT COUNT(*) AS count FROM prompts p {where_sql}", params).fetchone()["count"]
            if count <= 0:
                raise ValueError("No prompts match the selected filters.")

            offset = int(seed) % count
            row = conn.execute(
                f"SELECT p.* FROM prompts p {where_sql} ORDER BY p.id LIMIT 1 OFFSET ?",
                [*params, offset],
            ).fetchone()

            if row is None:
                raise ValueError("No prompt found for the selected filters.")

            return (row["id"], row["prompt"], row["suggested_width"], row["suggested_height"], metadata_json(conn, row))


class ToolBoxPromptWriter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "id": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "language": (LANGUAGES, {"default": "zh"}),
                "media_type": (MEDIA_TYPES, {"default": "image"}),
                "prompt_type": (PROMPT_TYPES, {"default": "natural"}),
                "nsfw": ("BOOLEAN", {"default": False}),
                "content_format": (CONTENT_FORMATS, {"default": "plaintext"}),
                "dynamic": ("BOOLEAN", {"default": False}),
                "width": ("INT", {"default": 1024, "min": 1, "max": 16384, "step": 1}),
                "height": ("INT", {"default": 768, "min": 1, "max": 16384, "step": 1}),
                "tags": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("id", "prompt", "metadata")
    FUNCTION = "write_prompt"
    CATEGORY = "eazy-toolbox/prompt"

    def write_prompt(
        self, id, prompt, language, media_type, prompt_type, nsfw, content_format, dynamic,
        width, height, tags,
    ):
        prompt_id = int(id)
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt cannot be empty.")
        require_enum("language", language, LANGUAGES)
        require_enum("media_type", media_type, MEDIA_TYPES)
        require_enum("prompt_type", prompt_type, PROMPT_TYPES)
        require_enum("content_format", content_format, CONTENT_FORMATS)

        width = int(width or 1024)
        height = int(height or 768)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive integers.")

        with connect_db(create=True) as conn:
            created_at = datetime.now(timezone.utc).isoformat()
            if prompt_id > 0:
                exists = conn.execute("SELECT 1 FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
                if exists is None:
                    raise ValueError(f"prompt id does not exist: {prompt_id}")

                conn.execute(
                    """
                    UPDATE prompts
                    SET prompt = ?,
                        language = ?,
                        media_type = ?,
                        prompt_type = ?,
                        nsfw = ?,
                        content_format = ?,
                        dynamic = ?,
                        suggested_width = ?,
                        suggested_height = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    (
                        prompt,
                        language,
                        media_type,
                        prompt_type,
                        1 if nsfw else 0,
                        content_format,
                        1 if dynamic else 0,
                        width,
                        height,
                        created_at,
                        prompt_id,
                    ),
                )
                conn.execute("DELETE FROM prompt_tags WHERE prompt_id = ?", (prompt_id,))
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO prompts (
                        prompt, language, media_type, prompt_type, nsfw, content_format, dynamic,
                        suggested_width, suggested_height, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prompt,
                        language,
                        media_type,
                        prompt_type,
                        1 if nsfw else 0,
                        content_format,
                        1 if dynamic else 0,
                        width,
                        height,
                        created_at,
                    ),
                )
                prompt_id = cursor.lastrowid

            insert_tags(conn, prompt_id, parse_tags(tags))
            conn.commit()

            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
            return (row["id"], row["prompt"], metadata_json(conn, row))


NODE_CLASS_MAPPINGS = {
    "ToolBoxRandomPrompt": ToolBoxRandomPrompt,
    "ToolBoxPromptWriter": ToolBoxPromptWriter,
}
