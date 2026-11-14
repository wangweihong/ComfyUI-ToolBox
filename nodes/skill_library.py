"""Raw skill/template storage, isolated from the prompt tables in the same DB."""
import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import database
from . import prompt_nodes
from .prompt_library import positive_int
from . import skill_files

ENTRY_TYPES = ("skill", "prompt_template")
EDITABLE_FIELDS = {"name", "entry_type", "description", "content", "tags"}


class SkillNotFound(ValueError):
    pass


class SkillConflict(ValueError):
    pass


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, entry_type TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', content TEXT NOT NULL,
        shasum TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    conn.execute("CREATE TABLE IF NOT EXISTS skill_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)")
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_entry_tags (
        entry_id INTEGER NOT NULL REFERENCES skill_entries(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES skill_tags(id) ON DELETE CASCADE,
        PRIMARY KEY(entry_id, tag_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_entries_shasum ON skill_entries(entry_type,shasum,id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_entry_tags_tag ON skill_entry_tags(tag_id,entry_id)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(skill_entries)")}
    for name in ("primary_path", "bundle_shasum"):
        if name not in columns:
            conn.execute(f"ALTER TABLE skill_entries ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_files (
        entry_id INTEGER NOT NULL REFERENCES skill_entries(id) ON DELETE CASCADE,
        path TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(entry_id,path)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_entries_bundle ON skill_entries(entry_type,shasum,bundle_shasum,id)")
    database.initialize_revision(conn, "skill", ("skill_entries", "skill_tags", "skill_entry_tags", "skill_files"))


@contextmanager
def connect(*, write=False, create=False):
    path = database.DEFAULT_DB
    if not path.is_file() and not create:
        if write:
            raise SkillNotFound("Skill/模板记录不存在，请先新增。")
        yield None
        return
    conn = database.open_connection(create=create)
    try:
        conn.execute("BEGIN IMMEDIATE" if write or create else "BEGIN")
        if create:
            database.initialize(conn)
            initialize(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialized(conn):
    return conn is not None and conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_entries'"
    ).fetchone() is not None


def data_revision(**_kwargs):
    try:
        with connect() as conn:
            if not initialized(conn):
                return None
            row = conn.execute('SELECT epoch,revision FROM toolbox_skill_revision WHERE singleton=1').fetchone()
            info = database.DEFAULT_DB.stat()
            return (str(database.DEFAULT_DB.resolve()), info.st_dev, info.st_ino, row[0], row[1])
    except (ValueError, OSError, sqlite3.Error):
        return float('nan')


def storage_usage(conn, exclude_id=None):
    used, count = 0, 0
    if initialized(conn):
        where, params = (" WHERE id<>?", (exclude_id,)) if exclude_id is not None else ("", ())
        has_files = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_files'").fetchone()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(skill_entries)")}
        # A linked file's content is a read/output cache, not a second user input.
        body_size = "length(CAST(content AS BLOB))"
        if has_files and "primary_path" in columns:
            body_size = "CASE WHEN EXISTS (SELECT 1 FROM skill_files f WHERE f.entry_id=skill_entries.id AND f.path=skill_entries.primary_path) THEN 0 ELSE length(CAST(content AS BLOB)) END"
        used, count = conn.execute(f"SELECT COALESCE(SUM({body_size}),0),COUNT(*) FROM skill_entries" + where, params).fetchone()
        if has_files:
            where = " WHERE entry_id<>?" if exclude_id is not None else ""
            used += conn.execute("SELECT COALESCE(SUM(length(data)),0) FROM skill_files" + where, params).fetchone()[0]
    return {"used_bytes":used, "entry_count":count, "max_library_bytes":skill_files.MAX_LIBRARY_BYTES,
            "max_entry_bytes":skill_files.MAX_TOTAL_BYTES, "max_file_bytes":skill_files.MAX_FILE_BYTES,
            "max_files":skill_files.MAX_FILES}


def storage():
    with connect() as conn:
        return storage_usage(conn)


def row_tags(conn, entry_id):
    return [row[0] for row in conn.execute(
        "SELECT t.name FROM skill_tags t JOIN skill_entry_tags st ON st.tag_id=t.id "
        "WHERE st.entry_id=? ORDER BY t.name", (entry_id,),
    )]


def record(conn, entry_id):
    row = conn.execute("SELECT * FROM skill_entries WHERE id=?", (entry_id,)).fetchone() if initialized(conn) else None
    if row is None:
        raise SkillNotFound(f"Skill/模板记录不存在：{entry_id}")
    data = {"primary_path":"", "bundle_shasum":"", **dict(row), "tags": row_tags(conn, entry_id)}
    has_files = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_files'").fetchone()
    data["files"] = [skill_files.file_item(row["path"], row["data"]) for row in conn.execute(
        "SELECT path,data FROM skill_files WHERE entry_id=? ORDER BY path", (entry_id,),
    )] if has_files else []
    data["storage_mode"] = "files" if data["files"] else "text"
    version_data = {**data, "files":skill_files.manifest(data["files"])}
    data["version"] = hashlib.sha256(json.dumps(version_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return data


def detail(entry_id):
    entry_id = positive_int(entry_id, "id")
    with connect() as conn:
        return record(conn, entry_id)


def list_entries(query):
    if set(query) - {"q", "entry_type", "tags", "page", "page_size"}:
        raise ValueError("Unknown skill filters")
    page = positive_int(query.get("page", 1), "page", 10_000_000)
    size = positive_int(query.get("page_size", 50), "page_size", 100)
    q, kind, tags = query.get("q", ""), query.get("entry_type", "全部"), query.get("tags", "")
    if not isinstance(q, str) or len(q) > 2000 or not isinstance(tags, str) or len(tags) > 10000:
        raise ValueError("Invalid search or tags")
    if kind not in ("全部", *ENTRY_TYPES):
        raise ValueError("entry_type must be skill, prompt_template or 全部")
    clauses, params = [], []
    if q:
        clauses.append("(instr(lower(s.name),lower(?))>0 OR instr(lower(s.description),lower(?))>0 OR instr(lower(s.content),lower(?))>0)")
        params.extend([q, q, q])
    if kind != "全部":
        clauses.append("s.entry_type=?")
        params.append(kind)
    for tag in prompt_nodes.parse_tags(tags):
        clauses.append("EXISTS (SELECT 1 FROM skill_entry_tags st JOIN skill_tags t ON t.id=st.tag_id "
                       "WHERE st.entry_id=s.id AND t.name=? COLLATE NOCASE)")
        params.append(tag)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    result = {"items": [], "total": 0, "page": page, "page_size": size}
    with connect() as conn:
        result["storage"] = storage_usage(conn)
        if not initialized(conn):
            return result
        result["total"] = conn.execute("SELECT COUNT(*) FROM skill_entries s" + where, params).fetchone()[0]
        rows = conn.execute(
            "SELECT s.id,s.name,s.entry_type,substr(s.description,1,240) AS description,"
            "substr(s.content,1,320) AS preview,s.updated_at FROM skill_entries s" + where +
            " ORDER BY s.id DESC LIMIT ? OFFSET ?", [*params, size, (page - 1) * size],
        ).fetchall()
        has_files = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_files'").fetchone()
        result["items"] = [{**dict(row), "tags": row_tags(conn, row["id"]), "file_count": conn.execute(
            "SELECT COUNT(*) FROM skill_files WHERE entry_id=?", (row["id"],),
        ).fetchone()[0] if has_files else 0} for row in rows]
        return result


def list_tags(query):
    if set(query) - {"q", "page", "page_size"}:
        raise ValueError("Unknown tag filters")
    q = query.get("q", "")
    if not isinstance(q, str) or len(q) > 2000:
        raise ValueError("Invalid tag search")
    page = positive_int(query.get("page", 1), "page", 10_000_000)
    size = positive_int(query.get("page_size", 500), "page_size", 500)
    result = {"items": [], "counts": {}, "total": 0, "has_more": False, "page": page, "page_size": size}
    with connect() as conn:
        if not initialized(conn):
            return result
        result["total"] = conn.execute("SELECT COUNT(*) FROM skill_tags WHERE instr(lower(name),lower(?))>0", (q,)).fetchone()[0]
        rows = conn.execute(
            "SELECT t.name,COUNT(st.entry_id) AS uses FROM skill_tags t LEFT JOIN skill_entry_tags st ON st.tag_id=t.id "
            "WHERE instr(lower(t.name),lower(?))>0 GROUP BY t.id,t.name ORDER BY t.name COLLATE NOCASE LIMIT ? OFFSET ?",
            (q, size, (page - 1) * size),
        ).fetchall()
        result.update(items=[row[0] for row in rows], counts={row[0]: row[1] for row in rows}, has_more=page * size < result["total"])
        return result


def validate(payload, *, existing):
    required = EDITABLE_FIELDS | ({"version"} if existing else set())
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {"files", "primary_path", "storage_mode"}:
        raise ValueError("请提交名称、类型、简述、正文、标签" + ("及记录版本" if existing else ""))
    for key, limit in (("name", 200), ("description", 20000), ("content", 2_000_000), ("tags", 10000)):
        if not isinstance(payload[key], str) or len(payload[key]) > limit:
            raise ValueError(f"Invalid {key}")
    if not payload["name"].strip():
        raise ValueError("名称不能为空")
    if payload["entry_type"] not in ENTRY_TYPES:
        raise ValueError("entry_type must be skill or prompt_template")
    if existing and (not isinstance(payload["version"], str) or len(payload["version"]) != 64):
        raise ValueError("Invalid record version")
    values = {key: payload[key] for key in EDITABLE_FIELDS}
    if "storage_mode" in payload:
        if payload["storage_mode"] not in ("text", "files"):
            raise ValueError("storage_mode 必须为 text 或 files")
        values["storage_mode"] = payload["storage_mode"]
    if "files" in payload:
        values["files"] = skill_files.validate_files(payload["files"])
    if "primary_path" in payload:
        if not isinstance(payload["primary_path"], str):
            raise ValueError("primary_path 必须为字符串")
        values["primary_path"] = skill_files.safe_path(payload["primary_path"]) if payload["primary_path"] else ""
    if not existing and values.get("primary_path") and "files" not in values:
        raise ValueError("关联正文的文件不存在")
    if "files" in values and values.get("primary_path") and values["primary_path"] not in {item["path"] for item in values["files"]}:
        raise ValueError("关联正文的文件不存在")
    if values.get("storage_mode") == "text" and (values.get("files") or values.get("primary_path")):
        raise ValueError("正文与文件包只能选择一种")
    if not existing:
        mode = values.get("storage_mode", "files" if values.get("files") else "text")
        if mode == "files" and not values.get("files"):
            raise ValueError("文件包模式请至少上传一个文件")
        if mode == "text" and not values["content"].strip():
            raise ValueError("正文不能为空")
        if mode == "files" and "storage_mode" in values:
            primary = values.get("primary_path", "")
            if primary:
                main = next(item for item in values["files"] if item["path"] == primary)
                try:
                    text = base64.b64decode(main["data"]).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("输出正文的文件必须为 UTF-8 文本") from exc
                if "\0" in text:
                    raise ValueError("输出正文的文件必须为 UTF-8 文本")
                if values["content"] and values["content"] != text:
                    raise ValueError("文件包模式的正文只能来自所选文件")
            elif values["content"]:
                raise ValueError("文件包模式不能另填独立正文")
    return values


def store(payload, entry_id=None):
    values = validate(payload, existing=entry_id is not None)
    if entry_id is not None:
        entry_id = positive_int(entry_id, "id")
    with connect(write=True, create=entry_id is None) as conn:
        now = datetime.now(timezone.utc).isoformat()
        if entry_id is not None:
            current = record(conn, entry_id)
            if current["version"] != payload["version"]:
                raise SkillConflict("记录已被修改，请重新加载详情后再保存。")
            initialize(conn)
        else:
            current = {}
        files = values.get("files", current.get("files", []))
        primary = values.get("primary_path", current.get("primary_path", ""))
        mode = values.get("storage_mode", "files" if files else "text")
        if mode == "text":
            files, primary = [], ""
            if not values["content"].strip():
                raise ValueError("正文不能为空")
        elif not files:
            raise ValueError("文件包模式请至少上传一个文件")
        elif "storage_mode" not in values and not primary and values["content"]:
            # Preserve older mixed records/clients as a file, never discard their body.
            paths = {item["path"] for item in files}
            primary = "content.md"
            while primary in paths:
                primary = "_" + primary
            files = [*files, skill_files.file_item(primary, values["content"].encode("utf-8"))]
        if mode == "files" and primary:
            if primary not in {item["path"] for item in files}:
                raise ValueError("关联正文的文件不存在")
            if "storage_mode" not in values:
                files = [skill_files.file_item(item["path"], values["content"].encode("utf-8")) if item["path"] == primary else item for item in files]
            files = skill_files.validate_files(files)
            main = next(item for item in files if item["path"] == primary)
            try:
                content = base64.b64decode(main["data"]).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("输出正文的文件必须为 UTF-8 文本") from exc
            if "\0" in content:
                raise ValueError("输出正文的文件必须为 UTF-8 文本")
            if "storage_mode" in values and values["content"] and values["content"] != content:
                raise ValueError("文件包模式的正文只能来自所选文件")
            values["content"] = content
        elif mode == "files":
            if "storage_mode" in values and values["content"]:
                raise ValueError("文件包模式不能另填独立正文")
            values["content"] = ""
        digest = hashlib.sha1(values["content"].strip().encode("utf-8")).hexdigest()
        bundle = skill_files.package_hash(files, primary)
        required_bytes = sum(item["size"] for item in files) if mode == "files" else len(values["content"].encode("utf-8"))
        if required_bytes > skill_files.MAX_TOTAL_BYTES:
            raise skill_files.SkillCapacityError("每条正文或文件包最多 20 MiB")
        used = storage_usage(conn, exclude_id=entry_id)["used_bytes"]
        if used + required_bytes > skill_files.MAX_LIBRARY_BYTES:
            raise skill_files.SkillCapacityError("Skill／模板库已达到 200 MiB 容量上限，请移除部分附件或缩短正文后重试。")
        action = "updated" if entry_id is not None else "created"
        columns = (values["name"].strip(), values["entry_type"], values["description"], values["content"], digest, now)
        if entry_id is None:
            entry_id = conn.execute(
                "INSERT INTO skill_entries(name,entry_type,description,content,shasum,updated_at,created_at) VALUES(?,?,?,?,?,?,?)",
                (*columns, now),
            ).lastrowid
        else:
            conn.execute("UPDATE skill_entries SET name=?,entry_type=?,description=?,content=?,shasum=?,updated_at=? WHERE id=?",
                         (*columns, entry_id))
            conn.execute("DELETE FROM skill_entry_tags WHERE entry_id=?", (entry_id,))
        for tag in prompt_nodes.parse_tags(values["tags"]):
            conn.execute("INSERT OR IGNORE INTO skill_tags(name) VALUES(?)", (tag,))
            tag_id = conn.execute("SELECT id FROM skill_tags WHERE name=?", (tag,)).fetchone()[0]
            conn.execute("INSERT INTO skill_entry_tags VALUES(?,?)", (entry_id, tag_id))
        conn.execute("UPDATE skill_entries SET primary_path=?,bundle_shasum=? WHERE id=?", (primary, bundle, entry_id))
        conn.execute("DELETE FROM skill_files WHERE entry_id=?", (entry_id,))
        conn.executemany("INSERT INTO skill_files(entry_id,path,data) VALUES(?,?,?)",
                         [(entry_id, item["path"], base64.b64decode(item["data"])) for item in files])
        return {**record(conn, entry_id), "action": action}


def create_entry(payload):
    return store(payload)


def save_entry(entry_id, payload):
    return store(payload, entry_id)


def delete_entry(entry_id, payload):
    entry_id = positive_int(entry_id, "id")
    if (not isinstance(payload, dict) or set(payload) != {"version"}
            or not isinstance(payload["version"], str) or len(payload["version"]) != 64):
        raise ValueError("删除需要当前记录的 version")
    with connect(write=True) as conn:
        current = record(conn, entry_id)
        if current["version"] != payload["version"]:
            raise SkillConflict("记录已被修改，请重新加载详情后再删除。")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_files'").fetchone():
            conn.execute("DELETE FROM skill_files WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM skill_entry_tags WHERE entry_id=?", (entry_id,))
        conn.execute("DELETE FROM skill_entries WHERE id=?", (entry_id,))
        usage = storage_usage(conn)
    notify_changed({"deleted_entry_ids": [entry_id]})
    return {"deleted": [entry_id], "storage": usage}


def delete_tag(payload):
    if (not isinstance(payload, dict) or set(payload) != {"name"}
            or not isinstance(payload["name"], str) or not payload["name"].strip()
            or len(payload["name"]) > 10000):
        raise ValueError("删除需要标签名称 name")
    name = payload["name"].strip()
    with connect(write=True) as conn:
        row = conn.execute("SELECT id,name FROM skill_tags WHERE name=? COLLATE NOCASE ORDER BY name=? DESC,id LIMIT 1",
                           (name, name)).fetchone() if initialized(conn) else None
        if row is None:
            raise SkillNotFound(f"Skill/模板标签不存在：{name}")
        count = conn.execute("SELECT COUNT(*) FROM skill_entry_tags WHERE tag_id=?", (row[0],)).fetchone()[0]
        conn.execute("DELETE FROM skill_entry_tags WHERE tag_id=?", (row[0],))
        conn.execute("DELETE FROM skill_tags WHERE id=?", (row[0],))
    notify_changed({"deleted_tags": [row[1]]})
    return {"deleted": [row[1]], "affected_count": count}


def notify_changed(detail):
    try:
        from server import PromptServer
        server = getattr(PromptServer, "instance", None)
        if server is not None and hasattr(server, "send_sync"):
            server.send_sync("toolbox.skills_changed", detail)
    except (ImportError, RuntimeError):
        pass
