import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import database
from .prompt_schema import ANNOTATION_DEFAULTS, CATEGORY_FIELDS, LEVEL_DESCRIPTIONS, add_missing_annotations, create_schema


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
LEVEL_FILTERS = ["全部", "L0", "L1", "L2", "L3", "L4"]
BOOLEAN_FILTERS = ["全部", "是", "否"]

NSFW_MODEL_ID = "uget/sexual_content_dection"
NSFW_MODEL_MAX_LENGTH = 128
_NSFW_MODEL_BUNDLE = None
_NSFW_MODEL_LOCK = threading.Lock()

# Exact Danbooru-style tags only. Natural-language semantics are handled by the
# classifier, which avoids substring false positives such as "breastplate".
NSFW_DANBOORU_TAGS = frozenset({
    "anal", "anal fingering", "anus", "areolae", "ass focus", "bdsm",
    "bikini aside", "bondage", "breast grab", "breast sucking", "breasts out",
    "bukkake", "cervix", "clothed sex", "cum", "cum in mouth", "cum on body",
    "cum on breasts", "cum on face", "cum on stomach", "cum pool", "deepthroat",
    "double penetration", "erection", "explicit", "fellatio", "female ejaculation",
    "fingering", "forced orgasm", "group sex", "handjob", "hentai", "implied sex",
    "lactation", "masturbation", "multiple insertions", "naked", "nipple piercing",
    "nipple slip", "nipples", "nude", "oral", "orgasm", "paizuri", "penis",
    "penis in mouth", "questionable", "sex", "sex from behind", "sex toy",
    "spread anus", "spread legs", "testicles", "topless", "uncensored",
    "vaginal", "vaginal penetration", "vibrator", "visible erection", "yaoi", "yuri",
})
NSFW_RATINGS = frozenset({"explicit", "questionable", "e", "q"})
_WEIGHT_SUFFIX_RE = re.compile(r":\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*$")
_SEXUAL_LABEL_RE = re.compile(r"(?:sexual|nsfw|adult|porn)", re.IGNORECASE)
_SAFE_LABEL_RE = re.compile(r"(?:none|safe|sfw|non.?sexual)", re.IGNORECASE)


def normalize_danbooru_tag(raw_tag):
    tag = raw_tag.strip().replace("\\(", "(").replace("\\)", ")")
    while len(tag) >= 2 and tag[0] == "(" and tag[-1] == ")":
        tag = tag[1:-1].strip()
    tag = _WEIGHT_SUFFIX_RE.sub("", tag).strip()
    while len(tag) >= 2 and tag[0] == "(" and tag[-1] == ")":
        tag = tag[1:-1].strip()
    tag = tag.casefold().replace("_", " ")
    return " ".join(tag.split())


def find_nsfw_danbooru_tags(prompt):
    matches = set()
    for raw_tag in re.split(r"[,\r\n]+", prompt):
        tag = normalize_danbooru_tag(raw_tag)
        if not tag:
            continue
        if tag in NSFW_DANBOORU_TAGS:
            matches.add(tag)
            continue
        rating = re.fullmatch(r"rating\s*:\s*(.+)", tag)
        if rating and rating.group(1).strip() in NSFW_RATINGS:
            matches.add(f"rating:{rating.group(1).strip()}")
    return sorted(matches)


def _resolve_sexual_label_index(model):
    id2label = getattr(model.config, "id2label", None) or {}
    labels = {int(index): str(label) for index, label in id2label.items()}
    sexual = [index for index, label in labels.items() if _SEXUAL_LABEL_RE.search(label)]
    safe = [index for index, label in labels.items() if _SAFE_LABEL_RE.search(label)]
    if len(sexual) == 1 and sexual[0] not in safe:
        return sexual[0]

    # This model omits id2label in config.json. Its published model card defines
    # class 0 as None and class 1 as Sexual, so keep the fallback model-specific.
    model_name = str(getattr(model.config, "_name_or_path", ""))
    if model_name == NSFW_MODEL_ID and int(getattr(model.config, "num_labels", 0)) == 2:
        return 1
    raise RuntimeError(
        "NSFW model labels are invalid: expected exactly one Sexual/NSFW/Adult label "
        "in config.id2label."
    )


def _load_nsfw_model():
    global _NSFW_MODEL_BUNDLE
    if _NSFW_MODEL_BUNDLE is not None:
        return _NSFW_MODEL_BUNDLE
    with _NSFW_MODEL_LOCK:
        if _NSFW_MODEL_BUNDLE is not None:
            return _NSFW_MODEL_BUNDLE
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Prompt NSFW Detector requires 'transformers'. Install this plugin's "
                "requirements.txt, then restart ComfyUI."
            ) from exc
        try:
            tokenizer = AutoTokenizer.from_pretrained(NSFW_MODEL_ID)
            model = AutoModelForSequenceClassification.from_pretrained(NSFW_MODEL_ID)
            model.to("cpu")
            model.eval()
            sexual_index = _resolve_sexual_label_index(model)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to load NSFW model '{NSFW_MODEL_ID}'. Connect to the internet for "
                "the first download or ensure it exists in the Hugging Face cache. "
                f"Original error: {exc}"
            ) from exc
        _NSFW_MODEL_BUNDLE = (tokenizer, model, sexual_index)
        return _NSFW_MODEL_BUNDLE


def predict_nsfw_score(prompt):
    import torch

    tokenizer, model, sexual_index = _load_nsfw_model()
    encoded = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=NSFW_MODEL_MAX_LENGTH,
    )
    encoded = {name: tensor.to("cpu") for name, tensor in encoded.items()}
    with torch.inference_mode():
        logits = model(**encoded).logits
        probabilities = torch.softmax(logits, dim=-1)
    if sexual_index < 0 or sexual_index >= probabilities.shape[-1]:
        raise RuntimeError("NSFW model Sexual label index is outside the logits shape.")
    return float(probabilities[0, sexual_index].item())


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


def prompt_shasum(prompt):
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()


def require_enum(name, value, allowed):
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")


@contextmanager
def connect_db(create=False):
    if not database.DEFAULT_DB.exists() and not create:
        raise ValueError(f"Prompt database not found: {database.DEFAULT_DB}. Run: python3 scripts/import_prompts.py")

    conn = database.open_connection(create=create)
    try:
        if create:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                database.initialize(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def required_prompt_columns():
    return {
        "id", "shasum", "prompt", "language", "media_type", "prompt_type", "nsfw", "content_format",
        "dynamic", "suggested_width", "suggested_height", "created_at",
        *ANNOTATION_DEFAULTS,
    }


def migration_command():
    return f"python3 scripts/migrate_prompt_annotations.py --db {database.DEFAULT_DB}"


def ensure_schema(conn):
    required_columns = required_prompt_columns()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(prompts)").fetchall()}
    missing_columns = sorted(required_columns - columns)
    if missing_columns:
        commands = []
        if set(missing_columns) - ANNOTATION_DEFAULTS.keys():
            commands.append(f"python3 scripts/migrate_prompt_shasum.py --db {database.DEFAULT_DB}")
        if set(missing_columns) & ANNOTATION_DEFAULTS.keys():
            commands.append(migration_command())
        raise ValueError(
            f"Invalid prompt database schema: {database.DEFAULT_DB}. "
            f"Missing columns: {', '.join(missing_columns)}. "
            f"Run: {'; then '.join(commands)}"
        )


def has_unique_shasum_index(conn):
    for index in conn.execute("PRAGMA index_list(prompts)").fetchall():
        if not index["unique"]:
            continue
        index_name = index["name"].replace('"', '""')
        columns = [
            row["name"]
            for row in conn.execute(f'PRAGMA index_info("{index_name}")').fetchall()
        ]
        if columns == ["shasum"]:
            return True
    return False


def ensure_writer_schema(conn):
    if has_unique_shasum_index(conn):
        raise ValueError(
            f"Invalid prompt database schema: {database.DEFAULT_DB}. "
            "The shasum column must allow duplicates. "
            f"Run: python3 scripts/migrate_prompt_shasum.py --db {database.DEFAULT_DB}"
        )
    ensure_schema(conn)


def insert_tags(conn, prompt_id, tags):
    for tag in tags:
        tag = tag.strip().lower()
        if not tag:
            continue

        row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
        if row is not None:
            tag_id = row["id"]
        else:
            try:
                tag_id = conn.execute("INSERT INTO tags (name) VALUES (?)", (tag,)).lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag,)).fetchone()
                if row is None:
                    raise
                tag_id = row["id"]
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
        "shasum": row["shasum"],
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
    metadata.update({key: row[key] if key == "sensitivity_level" else bool(row[key])
                     for key in ANNOTATION_DEFAULTS})
    return json.dumps(metadata, ensure_ascii=False)


class PromptConflict(ValueError):
    pass


def parse_level(value):
    if isinstance(value, str) and value in LEVEL_FILTERS[1:]:
        return int(value[1])
    if type(value) is int and 0 <= value <= 4:
        return value
    raise ValueError("sensitivity_level must be L0–L4 or an integer from 0 to 4")


def parse_levels(value):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("sensitivity_levels must be a comma-separated list such as L1,L3")
    levels = []
    for part in value.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        level = parse_level(part.upper() if part[:1].lower() == "l" else f"L{part}")
        if level not in levels:
            levels.append(level)
    return sorted(levels)


def prompt_filter_sql(*, q="", language="全部", media_type="全部", prompt_type="全部",
                      safety="全部", content_format="全部", dynamic="全部", match_size=False,
                      width=1024, height=768, tags="", sensitivity_level="全部",
                      sensitivity_mode="max", sensitivity_levels="", **categories):
    where, params = [], []
    for key, value, allowed in (
        ("language", language, LANGUAGE_FILTERS), ("media_type", media_type, MEDIA_TYPE_FILTERS),
        ("prompt_type", prompt_type, PROMPT_TYPE_FILTERS), ("content_format", content_format, CONTENT_FORMAT_FILTERS),
    ):
        require_enum(key, value, allowed)
        if value != "全部":
            where.append(f"p.{key} = ?")
            params.append(value)
    require_enum("safety", safety, SAFETY_FILTERS)
    require_enum("dynamic", dynamic, DYNAMIC_FILTERS)
    if safety != "全部":
        where.append("p.nsfw = ?")
        params.append(int(safety == "nsfw"))
    if dynamic != "全部":
        where.append("p.dynamic = ?")
        params.append(int(dynamic == "dynamic"))
    require_enum("sensitivity_mode", sensitivity_mode, ["max", "exact"])
    if sensitivity_mode == "exact":
        levels = parse_levels(sensitivity_levels)
        if levels:
            where.append(f"p.sensitivity_level IN ({','.join('?' for _ in levels)})")
            params.extend(levels)
        else:
            where.append("0")
    elif sensitivity_level != "全部":
        where.append("p.sensitivity_level <= ?")
        params.append(parse_level(sensitivity_level))
    for key, value in categories.items():
        if key not in CATEGORY_FIELDS:
            raise ValueError(f"Unknown filter: {key}")
        require_enum(key, value, BOOLEAN_FILTERS)
        if value != "全部":
            where.append(f"p.{key} = ?")
            params.append(int(value == "是"))
    if match_size:
        where.extend(["p.suggested_width = ?", "p.suggested_height = ?"])
        params.extend([int(width), int(height)])
    if q:
        # Literal substring search, including literal percent and underscore.
        where.append("instr(lower(p.prompt), lower(?)) > 0")
        params.append(q)
    for tag in parse_tags(tags):
        where.append("EXISTS (SELECT 1 FROM prompt_tags pt JOIN tags t ON t.id = pt.tag_id "
                     "WHERE pt.prompt_id = p.id AND t.name = ? COLLATE NOCASE)")
        params.append(tag)
    return where, params


def record_version(conn, row):
    payload = [dict(row), row_tags(conn, row["id"])]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def database_revision(**_kwargs):
    paths = [database.DEFAULT_DB, Path(str(database.DEFAULT_DB) + "-wal")]
    revision = []
    for path in paths:
        try:
            stat = path.stat()
            revision.append((str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_size))
        except FileNotFoundError:
            revision.append((str(path), None))
    return tuple(revision)


def prompt_data_revision(**_kwargs):
    from .prompt_examples_schema import revision_ready
    try:
        with connect_db() as conn:
            conn.execute("BEGIN")
            if revision_ready(conn):
                row = conn.execute("SELECT epoch,revision FROM toolbox_prompt_revision WHERE singleton=1").fetchone()
                if row:
                    info = database.DEFAULT_DB.stat()
                    return (str(database.DEFAULT_DB.resolve()), info.st_dev, info.st_ino, row[0], row[1])
    except (ValueError, OSError, sqlite3.Error):
        pass
    return database_revision()


def prompt_execution_ui(result):
    metadata = json.loads(result[-1])
    return {"ui": {"toolbox_prompt": [{"id": result[0], "shasum": metadata["shasum"]}]}, "result": result}


class ToolBoxRandomPrompt:
    IS_CHANGED = staticmethod(prompt_data_revision)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xffffffffffffffff,
                        "control_after_generate": True,
                    },
                ),
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
            },
            "optional": {
                "sensitivity_level": (LEVEL_FILTERS, {"default": "全部", "tooltip": "最高敏感等级，L2 包含 L0–L2"}),
                **{key: (BOOLEAN_FILTERS, {"default": "全部"}) for key in CATEGORY_FIELDS},
                "sensitivity_mode": (["max", "exact"], {"default": "max", "tooltip": "max：等级及以下；exact：只匹配 sensitivity_levels 中指定的级别"}),
                "sensitivity_levels": ("STRING", {"default": "", "tooltip": "exact 模式使用，逗号分隔，如 L1,L3；留空表示不匹配任何级别"}),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("id", "prompt", "width", "height", "metadata")
    FUNCTION = "execute_prompt"
    CATEGORY = "eazy-toolbox/prompt"

    def execute_prompt(self, **kwargs):
        return prompt_execution_ui(self.random_prompt(**kwargs))

    def random_prompt(
        self, seed, language, media_type, prompt_type, safety, content_format, dynamic,
        match_size, width, height, tags, sensitivity_level="全部", nsfw="全部",
        extreme="全部", horror="全部", gore="全部", minor="全部",
        sensitivity_mode="max", sensitivity_levels="",
    ):
        with connect_db() as conn:
            ensure_schema(conn)
            conn.execute("BEGIN")
            where, params = prompt_filter_sql(
                language=language, media_type=media_type, prompt_type=prompt_type,
                safety=safety, content_format=content_format, dynamic=dynamic,
                match_size=match_size, width=width, height=height, tags=tags,
                sensitivity_level=sensitivity_level, nsfw=nsfw, extreme=extreme,
                horror=horror, gore=gore, minor=minor,
                sensitivity_mode=sensitivity_mode, sensitivity_levels=sensitivity_levels,
            )

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


class ToolBoxPromptReader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"id": ("INT", {"default": 1, "min": 1, "max": 2**63 - 1})}}

    RETURN_TYPES = ("INT", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("id", "prompt", "width", "height", "metadata")
    FUNCTION = "execute_prompt"
    CATEGORY = "eazy-toolbox/prompt"
    IS_CHANGED = staticmethod(prompt_data_revision)

    def execute_prompt(self, id):
        return prompt_execution_ui(self.read_prompt(id))

    def read_prompt(self, id):
        with connect_db() as conn:
            ensure_schema(conn)
            conn.execute("BEGIN")
            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (int(id),)).fetchone()
            if row is None:
                raise ValueError(f"prompt id does not exist: {id}")
            return row["id"], row["prompt"], row["suggested_width"], row["suggested_height"], metadata_json(conn, row)


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
            },
            "optional": {
                "sensitivity_level": (["L0", "L1", "L2", "L3", "L4"], {"default": "L0", "tooltip": "\n".join(LEVEL_DESCRIPTIONS)}),
                **{key: ("BOOLEAN", {"default": False}) for key in ANNOTATION_DEFAULTS if key != "sensitivity_level"},
            }
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("id", "prompt", "metadata")
    FUNCTION = "write_prompt"
    CATEGORY = "eazy-toolbox/prompt"

    def write_prompt(
        self, id, prompt, language, media_type, prompt_type, nsfw, content_format, dynamic,
        width, height, tags, sensitivity_level=None, extreme=None, horror=None, gore=None, minor=None,
        *, expected_version=None, _return_action=False,
    ):
        prompt_id = int(id)
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt cannot be empty.")
        require_enum("language", language, LANGUAGES)
        require_enum("media_type", media_type, MEDIA_TYPES)
        require_enum("prompt_type", prompt_type, PROMPT_TYPES)
        require_enum("content_format", content_format, CONTENT_FORMATS)

        if sensitivity_level is not None:
            sensitivity_level = parse_level(sensitivity_level)
        annotations = {"sensitivity_level": sensitivity_level, "extreme": extreme,
                       "horror": horror, "gore": gore, "minor": minor}
        for key, value in annotations.items():
            if key != "sensitivity_level" and value is not None and not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        width = int(width or 1024)
        height = int(height or 768)
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive integers.")

        with connect_db(create=True) as conn:
            ensure_writer_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            created_at = datetime.now(timezone.utc).isoformat()
            shasum = prompt_shasum(prompt)
            update_existing = False

            if prompt_id > 0:
                existing = conn.execute(
                    "SELECT 1 FROM prompts WHERE id = ?",
                    (prompt_id,),
                ).fetchone()
                if existing is None:
                    raise ValueError(f"prompt id does not exist: {prompt_id}")
                update_existing = True
            else:
                existing = conn.execute(
                    "SELECT id FROM prompts WHERE shasum = ? ORDER BY id LIMIT 1",
                    (shasum,),
                ).fetchone()
                if existing is not None:
                    prompt_id = existing["id"]
                    update_existing = True

            if expected_version is not None:
                existing_row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
                if existing_row is None or record_version(conn, existing_row) != expected_version:
                    raise PromptConflict("记录已被修改，请重新加载详情后再保存。")

            if update_existing:
                conn.execute(
                    """
                    UPDATE prompts
                    SET shasum = ?,
                        prompt = ?,
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
                        shasum,
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
                        shasum, prompt, language, media_type, prompt_type, nsfw, content_format, dynamic,
                        suggested_width, suggested_height, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        shasum,
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

            # An old workflow omits these optional arguments: preserve annotations
            # when updating; new records receive the database defaults.
            updates = {key: int(value) for key, value in annotations.items() if value is not None}
            if updates:
                conn.execute(
                    f"UPDATE prompts SET {', '.join(key + ' = ?' for key in updates)} WHERE id = ?",
                    [*updates.values(), prompt_id],
                )
            insert_tags(conn, prompt_id, parse_tags(tags))
            conn.commit()

            row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
            result = (row["id"], row["prompt"], metadata_json(conn, row))
            # The browser needs the action chosen under the same write lock.
            # Normal ComfyUI execution retains its original three outputs.
            if _return_action:
                return (*result, "updated" if update_existing else "created")
            return result


class ToolBoxPromptNSFWDetector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "FLOAT", "STRING")
    RETURN_NAMES = ("is_nsfw", "score", "details")
    FUNCTION = "detect_nsfw"
    CATEGORY = "eazy-toolbox/prompt"

    def detect_nsfw(self, prompt, threshold):
        prompt = str(prompt or "").strip()
        threshold = float(threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1.")

        matched_tags = find_nsfw_danbooru_tags(prompt)
        model_score = predict_nsfw_score(prompt) if prompt else 0.0
        model_matched = model_score >= threshold
        tag_matched = bool(matched_tags)
        is_nsfw = model_matched or tag_matched
        score = 1.0 if tag_matched else model_score

        if tag_matched and model_matched:
            source = "model+danbooru"
        elif tag_matched:
            source = "danbooru"
        elif model_matched:
            source = "model"
        else:
            source = "none"
        details = {
            "is_nsfw": is_nsfw,
            "score": score,
            "model_score": model_score,
            "threshold": threshold,
            "model": NSFW_MODEL_ID,
            "matched_danbooru_tags": matched_tags,
            "source": source,
        }
        return (is_nsfw, score, json.dumps(details, ensure_ascii=False, sort_keys=True))


NODE_CLASS_MAPPINGS = {
    "ToolBoxRandomPrompt": ToolBoxRandomPrompt,
    "ToolBoxPromptWriter": ToolBoxPromptWriter,
    "ToolBoxPromptReader": ToolBoxPromptReader,
    "ToolBoxPromptNSFWDetector": ToolBoxPromptNSFWDetector,
}
