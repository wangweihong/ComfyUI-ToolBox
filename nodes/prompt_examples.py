"""Path-only generation examples. All checks are explicitly requested."""
import json
import mimetypes
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

from . import database
from . import prompt_nodes as prompts
from .prompt_library import positive_int, PromptNotFound
from .prompt_examples_schema import initialize, table_exists

OUTPUT_ROOT = None  # Tests override this instead of using the real ComfyUI output.
STATUSES = ("available", "missing", "unavailable", "changed")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}


def now():
    return datetime.now(timezone.utc).isoformat()


def output_root():
    if OUTPUT_ROOT is not None:
        return Path(OUTPUT_ROOT).resolve()
    import folder_paths
    return Path(folder_paths.get_output_directory()).resolve()


def normalize_path(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("请输入 output 内的文件路径")
    # Saved paths are exact filesystem names; whitespace may be part of a directory.
    if "://" in value or "\\" in value or "\0" in value or any(ord(char) < 32 for char in value):
        raise ValueError("仅支持当前服务器的 output 路径，不支持 URL 或其他系统路径")
    root = output_root()
    candidate = Path(value)
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise ValueError("路径不能包含 ..")
        candidate = root / candidate
    target = candidate.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("示例文件必须位于当前 ComfyUI output 内")
    suffix = target.suffix.lower()
    if suffix not in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
        raise ValueError("只支持图像或视频文件")
    return target, target.relative_to(root).as_posix(), "image" if suffix in IMAGE_SUFFIXES else "video"


def probe(value, baseline=None):
    """Root errors are unavailable, not evidence that a file has been deleted."""
    try:
        root = output_root()
        if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
            return "unavailable", None, "output 目录不可访问"
        with os.scandir(root):
            pass
        target, relative, kind = normalize_path(value)
        info = target.stat()
        if not stat.S_ISREG(info.st_mode):
            return "unavailable", None, "路径不是普通文件"
        with target.open("rb"):
            pass
        data = {"relative_path": relative, "media_type": kind, "file_size": info.st_size, "mtime_ns": info.st_mtime_ns}
        if baseline and (info.st_size != baseline["file_size"] or info.st_mtime_ns != baseline["mtime_ns"]):
            return "changed", data, "文件大小或修改时间已变化，请确认后重新登记"
        return "available", data, ""
    except FileNotFoundError:
        return "missing", None, "文件不存在"
    except (PermissionError, OSError, ValueError) as exc:
        return "unavailable", None, str(exc)


def parse_metadata(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("prompt_metadata 必须为提示词节点输出的 metadata JSON")
    prompt_id = positive_int(value.get("id"), "prompt_id")
    digest = value.get("shasum")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", digest):
        raise ValueError("提示词 metadata 缺少有效 SHA-1")
    return prompt_id, digest.lower()


def validate_source(metadata):
    prompt_id, digest = parse_metadata(metadata)
    with prompts.connect_db() as conn:
        prompts.ensure_schema(conn)
        if conn.execute("SELECT 1 FROM prompts WHERE id=?", (prompt_id,)).fetchone() is None:
            raise PromptNotFound(f"prompt id does not exist: {prompt_id}")
    return prompt_id, digest


def notify(prompt_ids):
    try:
        from server import PromptServer
        server = getattr(PromptServer, "instance", None)
        if server is not None and hasattr(server, "send_sync"):
            server.send_sync("toolbox.prompt_examples_changed", {"prompt_ids": sorted(set(prompt_ids))})
    except (ImportError, RuntimeError):
        pass


def serialize(row):
    data = dict(row)
    path = PurePosixPath(data["relative_path"])
    safe = not path.is_absolute() and ".." not in path.parts and "\\" not in str(path)
    data["url"] = "/view?" + urlencode({"filename": path.name, "subfolder": "" if str(path.parent) == "." else str(path.parent), "type": "output"}) if safe else None
    data["mime_type"] = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return data


def register(payload):
    if not isinstance(payload, dict) or set(payload) - {"prompt_id", "shasum", "paths", "source", "job_id", "node_id", "version"}:
        raise ValueError("无效登记参数")
    prompt_id, digest = parse_metadata({"id": payload.get("prompt_id"), "shasum": payload.get("shasum")})
    paths, source = payload.get("paths"), payload.get("source", "manual")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 200 or source not in ("manual", "generated"):
        raise ValueError("每批登记 1–200 个文件，source 为 manual 或 generated")
    for key in ("job_id", "node_id"):
        if payload.get(key) is not None and (not isinstance(payload[key], str) or len(payload[key]) > 200):
            raise ValueError(f"Invalid {key}")
    if "version" in payload and (not isinstance(payload["version"], str) or len(payload["version"]) != 64):
        raise ValueError("Invalid record version")
    records = {}
    for value in paths:
        # Registration rejects outside paths before any schema/data writes.
        normalize_path(value)
        status, item, message = probe(value)
        if status != "available":
            raise ValueError(f"无法登记 {value}：{message}")
        records[item["relative_path"]] = item
    stamp = now()
    with prompts.connect_db() as conn:
        prompts.ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()
        if current is None:
            raise PromptNotFound(f"prompt id does not exist: {prompt_id}")
        if source == "manual" and (current["shasum"] != digest or ("version" in payload and prompts.record_version(conn,current) != payload["version"])):
            raise prompts.PromptConflict("提示词记录已被修改，请重新加载详情后添加示例。")
        initialize(conn)
        items = []
        for item in records.values():
            conn.execute("""INSERT INTO prompt_examples
                (prompt_id,prompt_shasum,relative_path,media_type,source,created_at,updated_at,job_id,node_id,file_size,mtime_ns,status,checked_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,'available',?)
                ON CONFLICT(prompt_id,prompt_shasum,relative_path) DO UPDATE SET
                media_type=excluded.media_type,source=excluded.source,updated_at=excluded.updated_at,
                job_id=excluded.job_id,node_id=excluded.node_id,file_size=excluded.file_size,mtime_ns=excluded.mtime_ns,
                status='available',checked_at=excluded.checked_at,message=''""",
                (prompt_id, digest, item["relative_path"], item["media_type"], source, stamp, stamp,
                 payload.get("job_id"), payload.get("node_id"), item["file_size"], item["mtime_ns"], stamp))
            row = conn.execute("SELECT * FROM prompt_examples WHERE prompt_id=? AND prompt_shasum=? AND relative_path=?",
                               (prompt_id, digest, item["relative_path"])).fetchone()
            items.append(serialize(row))
    notify([prompt_id])
    return {"items": items, "registered": len(items)}


def list_examples(query, prompt_id=None):
    if set(query) - {"page", "page_size", "prompt_id", "shasum", "status"}:
        raise ValueError("Unknown example filters")
    page = positive_int(query.get("page", 1), "page", 10_000_000)
    size = positive_int(query.get("page_size", 20), "page_size", 100)
    if prompt_id is not None or query.get("prompt_id"):
        prompt_id = positive_int(prompt_id if prompt_id is not None else query["prompt_id"], "prompt_id")
    digest, status = query.get("shasum"), query.get("status", "all")
    if digest not in (None, "all") and (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", digest)):
        raise ValueError("Invalid shasum")
    if status not in (*STATUSES, "all"):
        raise ValueError("Invalid status")
    result = {"items": [], "total": 0, "page": page, "page_size": size}
    if not database.DEFAULT_DB.exists():
        return result
    with prompts.connect_db() as conn:
        conn.execute("BEGIN")
        if prompt_id is not None:
            row = conn.execute("SELECT shasum FROM prompts WHERE id=?", (prompt_id,)).fetchone()
            if row is None:
                raise PromptNotFound(f"prompt id does not exist: {prompt_id}")
            if digest is None:
                digest = row[0]
        if not table_exists(conn, "prompt_examples"):
            return result
        clauses, params = [], []
        for column, value in (("prompt_id", prompt_id), ("prompt_shasum", digest if digest != "all" else None), ("status", status if status != "all" else None)):
            if value is not None:
                clauses.append(f"{column}=?"); params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        result["total"] = conn.execute("SELECT COUNT(*) FROM prompt_examples" + where, params).fetchone()[0]
        rows = conn.execute("SELECT * FROM prompt_examples" + where + " ORDER BY id DESC LIMIT ? OFFSET ?", [*params, size, (page-1)*size]).fetchall()
        result["items"] = [serialize(row) for row in rows]
    return result


def selected_ids(payload):
    if not isinstance(payload, dict) or set(payload) != {"ids"} or not isinstance(payload["ids"], list) or not 1 <= len(payload["ids"]) <= 200:
        raise ValueError("每批需提交 1–200 个记录 ID")
    return list(dict.fromkeys(positive_int(value, "id") for value in payload["ids"]))


def check(payload, *, cleanup=False):
    ids = selected_ids(payload)
    items, deleted, affected = [], [], []
    if not database.DEFAULT_DB.exists():
        return {"items": [], "deleted": []}
    with prompts.connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not table_exists(conn, "prompt_examples"):
            return {"items": [], "deleted": []}
        for item_id in ids:
            row = conn.execute("SELECT * FROM prompt_examples WHERE id=?", (item_id,)).fetchone()
            if row is None:
                continue
            if cleanup and row["status"] != "missing":
                continue
            status, _info, message = probe(row["relative_path"], row)
            affected.append(row["prompt_id"])
            if cleanup and status == "missing":
                conn.execute("DELETE FROM prompt_examples WHERE id=?", (item_id,)); deleted.append(item_id)
            else:
                conn.execute("UPDATE prompt_examples SET status=?,checked_at=?,message=? WHERE id=?", (status, now(), message, item_id))
                items.append(serialize(conn.execute("SELECT * FROM prompt_examples WHERE id=?", (item_id,)).fetchone()))
    notify(affected)
    return {"items": items, "deleted": deleted}


def cleanup(payload):
    return check(payload, cleanup=True)


def remove(item_id, payload=None):
    item_id = positive_int(item_id, "id")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict) or set(payload) - {"delete_file"} or not isinstance(payload.get("delete_file", False), bool):
        raise ValueError("delete_file 必须为布尔值")
    affected = []
    with prompts.connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if table_exists(conn, "prompt_examples"):
            row = conn.execute("SELECT prompt_id,relative_path FROM prompt_examples WHERE id=?", (item_id,)).fetchone()
            if row:
                if payload.get("delete_file", False):
                    try:
                        if not output_root().is_dir():
                            raise ValueError("output 目录不可访问")
                        target, relative, _kind = normalize_path(row["relative_path"])
                        if relative != row["relative_path"]:
                            raise ValueError("示例路径已指向其他文件，请重新登记后操作")
                        target.unlink(missing_ok=True)
                    except (OSError, ValueError) as exc:
                        raise ValueError(f"无法删除示例素材，关联已保留：{exc}") from exc
                affected.append(row["prompt_id"]); conn.execute("DELETE FROM prompt_examples WHERE id=?", (item_id,))
    notify(affected)
    return {"deleted": [item_id] if affected else []}
