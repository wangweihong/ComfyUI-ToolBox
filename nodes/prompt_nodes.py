import json
import re
import sqlite3
import threading
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
    "ToolBoxPromptNSFWDetector": ToolBoxPromptNSFWDetector,
}
