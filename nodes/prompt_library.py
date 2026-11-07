"""Database operations for the prompt browser; no ComfyUI dependency."""
import json

from . import prompt_nodes as prompts
from .prompt_schema import CATEGORY_FIELDS, LEVEL_DESCRIPTIONS

FILTER_NAMES = {
    "q", "language", "media_type", "prompt_type", "safety", "content_format", "dynamic",
    "match_size", "width", "height", "tags", "sensitivity_level",
    "sensitivity_mode", "sensitivity_levels", *CATEGORY_FIELDS,
}
WRITE_NAMES = {
    "prompt", "language", "media_type", "prompt_type", "nsfw", "content_format", "dynamic",
    "width", "height", "tags", "sensitivity_level", "extreme", "horror", "gore", "minor",
}


class PromptNotFound(ValueError):
    pass


def positive_int(value, name, maximum=2**63 - 1):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if str(number) != str(value) or not 1 <= number <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return number


def detail(prompt_id):
    with prompts.connect_db() as conn:
        prompts.ensure_schema(conn)
        conn.execute("BEGIN")
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,)).fetchone()
        if row is None:
            raise PromptNotFound(f"prompt id does not exist: {prompt_id}")
        return {**json.loads(prompts.metadata_json(conn, row)), "prompt": row["prompt"],
                "version": prompts.record_version(conn, row)}


def list_prompts(query):
    unknown = set(query) - FILTER_NAMES - {"page", "page_size"}
    if unknown:
        raise ValueError(f"Unknown filters: {', '.join(sorted(unknown))}")
    filters = {key: value for key, value in query.items() if key in FILTER_NAMES}
    page = positive_int(query.get("page", 1), "page", 10_000_000)
    size = positive_int(query.get("page_size", 50), "page_size", 100)
    if len(filters.get("q", "")) > 2000 or len(filters.get("tags", "")) > 10000:
        raise ValueError("Search or tags too long")
    if "match_size" in filters:
        if filters["match_size"] not in ("true", "false"):
            raise ValueError("match_size must be true or false")
        filters["match_size"] = filters["match_size"] == "true"
    for key in ("width", "height"):
        if key in filters:
            filters[key] = positive_int(filters[key], key, 16384)
    where, params = prompts.prompt_filter_sql(**filters)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with prompts.connect_db() as conn:
        prompts.ensure_schema(conn)
        # One snapshot for the count, page and tag associations.
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*) FROM prompts p" + clause, params).fetchone()[0]
        rows = conn.execute(
            "SELECT p.id, substr(p.prompt,1,320) AS preview,p.language,p.media_type,p.prompt_type,"
            "p.sensitivity_level,p.nsfw,p.extreme,p.horror,p.gore,p.minor,p.content_format,p.dynamic,"
            "p.suggested_width AS width,p.suggested_height AS height FROM prompts p" + clause +
            " ORDER BY p.id DESC LIMIT ? OFFSET ?", [*params, size, (page - 1) * size],
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["tags"] = []
        by_id = {item["id"]: item for item in items}
        if by_id:
            placeholders = ",".join("?" for _ in by_id)
            for row in conn.execute(
                f"SELECT pt.prompt_id,t.name FROM prompt_tags pt JOIN tags t ON t.id=pt.tag_id "
                f"WHERE pt.prompt_id IN ({placeholders}) ORDER BY t.name", list(by_id),
            ):
                by_id[row[0]]["tags"].append(row[1])
        return {"items": items, "total": total, "page": page, "page_size": size}


def list_tags(query):
    if set(query) - {"q", "page", "page_size"}:
        raise ValueError("Unknown tag filters")
    text = query.get("q", "").lower()
    if len(text) > 2000:
        raise ValueError("Tag search too long")
    page = positive_int(query.get("page", 1), "page", 10_000_000)
    size = positive_int(query.get("page_size", 100), "page_size", 500)
    with prompts.connect_db() as conn:
        prompts.ensure_schema(conn)
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*) FROM tags WHERE instr(lower(name),?)>0", (text,)).fetchone()[0]
        rows = conn.execute(
            "SELECT t.name,COUNT(pt.prompt_id) AS usage_count FROM tags t "
            "LEFT JOIN prompt_tags pt ON pt.tag_id=t.id WHERE instr(lower(t.name),?)>0 "
            "GROUP BY t.id,t.name ORDER BY t.name COLLATE NOCASE LIMIT ? OFFSET ?",
            (text, size, (page - 1) * size),
        ).fetchall()
        return {"items": [row[0] for row in rows], "counts": {row[0]: row[1] for row in rows},
                "total": total, "has_more": page * size < total, "page": page, "page_size": size}


def validate_editable(payload, *, existing):
    expected = WRITE_NAMES | ({"version"} if existing else set())
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Save requires all editable prompt fields" + (" and version" if existing else ""))
    if existing and (not isinstance(payload["version"], str) or len(payload["version"]) != 64):
        raise ValueError("Invalid record version")
    if not isinstance(payload["prompt"], str) or not isinstance(payload["tags"], str):
        raise ValueError("prompt and tags must be strings")
    for key in (*CATEGORY_FIELDS, "dynamic"):
        if not isinstance(payload[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key in ("width", "height"):
        positive_int(payload[key], key, 16384)
    return {key: payload[key] for key in WRITE_NAMES}


def create_prompt(payload):
    values = validate_editable(payload, existing=False)
    prompt_id, _, _, action = prompts.ToolBoxPromptWriter().write_prompt(0, **values, _return_action=True)
    return {**detail(prompt_id), "action": action}


def save_prompt(prompt_id, payload):
    values = validate_editable(payload, existing=True)
    detail(prompt_id)  # Fail without creating a missing database or record.
    prompts.ToolBoxPromptWriter().write_prompt(prompt_id, **values, expected_version=payload["version"])
    return detail(prompt_id)


def browser_options():
    return {
        "levels": LEVEL_DESCRIPTIONS,
        "language": prompts.LANGUAGE_FILTERS, "media_type": prompts.MEDIA_TYPE_FILTERS,
        "prompt_type": prompts.PROMPT_TYPE_FILTERS, "content_format": prompts.CONTENT_FORMAT_FILTERS,
        "dynamic": prompts.DYNAMIC_FILTERS,
    }
