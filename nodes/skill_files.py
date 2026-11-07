"""Skill packages stay in SQLite; uploads are never extracted or executed."""
import base64
import binascii
import hashlib
import io
import json
import mimetypes
import stat
import zipfile

MAX_FILES = 200
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_LIBRARY_BYTES = 200 * 1024 * 1024
MAX_UPLOAD_BYTES = MAX_TOTAL_BYTES + 1024 * 1024
MAX_JSON_BYTES = 40 * 1024 * 1024


class SkillCapacityError(ValueError):
    pass


def safe_path(path):
    if not isinstance(path, str) or not path or len(path) > 500:
        raise ValueError("文件路径不能为空，且不能超过 500 个字符")
    if path.startswith(("/", "\\")) or "\\" in path or ":" in path or any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError(f"无效相对路径：{path!r}")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"无效相对路径：{path!r}")
    return path


def file_item(path, data):
    safe_path(path)
    if len(data) > MAX_FILE_BYTES:
        raise SkillCapacityError(f"单文件最多 5 MiB：{path}")
    return {"path": path, "data": base64.b64encode(data).decode("ascii"), "size": len(data),
            "media_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
            "shasum": hashlib.sha256(data).hexdigest()}


def validate_files(items):
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise ValueError("最多保存 200 个文件")
    result, paths, total = [], set(), 0
    for item in items:
        if not isinstance(item, dict) or not {"path", "data"} <= set(item) or set(item) - {"path", "data", "size", "media_type", "shasum"}:
            raise ValueError("文件需包含 path 与 Base64 data")
        path = safe_path(item["path"])
        if path in paths:
            raise ValueError(f"文件路径重复：{path}")
        paths.add(path)
        data = item["data"]
        if not isinstance(data, str) or len(data) > ((MAX_FILE_BYTES + 2) // 3) * 4:
            raise SkillCapacityError(f"文件内容过大或无效：{path}")
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"无效 Base64：{path}") from exc
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise SkillCapacityError("文件总大小最多 20 MiB")
        result.append(file_item(path, raw))
    for path in paths:
        if any("/".join(path.split("/")[:index]) in paths for index in range(1, len(path.split("/")))):
            raise ValueError(f"文件和目录路径冲突：{path}")
    return sorted(result, key=lambda item: item["path"])


def manifest(items):
    return [{key: item[key] for key in ("path", "size", "media_type", "shasum")} for item in items]


def package_hash(items, primary_path):
    if not items:
        return ""
    return hashlib.sha256(json.dumps([primary_path, manifest(items)], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def import_uploads(uploads):
    """Normalize individual files and ZIP entries without touching the filesystem."""
    items, expanded_size = [], 0
    for path, raw in uploads:
        safe_path(path)
        if not path.lower().endswith(".zip"):
            items.append(file_item(path, raw))
            expanded_size += len(raw)
        else:
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    if len(archive.infolist()) > MAX_FILES * 2:
                        raise ValueError("ZIP 中的条目过多")
                    for info in archive.infolist():
                        safe_path(info.filename.rstrip("/") if info.is_dir() else info.filename)
                        mode = info.external_attr >> 16
                        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                            raise ValueError("ZIP 不支持链接或特殊文件")
                        if info.flag_bits & 1:
                            raise ValueError("不支持加密 ZIP")
                        if info.is_dir():
                            continue
                        if len(items) >= MAX_FILES or info.file_size > MAX_FILE_BYTES:
                            raise SkillCapacityError("最多 200 个文件，单文件最多 5 MiB")
                        expanded_size += info.file_size
                        if expanded_size > MAX_TOTAL_BYTES:
                            raise SkillCapacityError("解压后总大小最多 20 MiB")
                        with archive.open(info) as member:
                            data = member.read(MAX_FILE_BYTES + 1)
                        items.append(file_item(info.filename, data))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise ValueError(f"无法读取 ZIP：{path}") from exc
        if len(items) > MAX_FILES or expanded_size > MAX_TOTAL_BYTES:
            raise SkillCapacityError("最多 200 个文件，总大小最多 20 MiB")
    files = validate_files(items)
    candidates = [item for item in files if item["path"].split("/")[-1].lower() == "skill.md"]
    if not candidates:
        candidates = [item for item in files if item["path"].lower().endswith((".md", ".txt"))]
    primary, content = "", ""
    for item in sorted(candidates, key=lambda item: (item["path"].count("/"), item["path"])):
        try:
            text = base64.b64decode(item["data"]).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "\0" not in text:
            primary, content = item["path"], text
            break
    return {"files": files, "primary_path": primary, "content": content}


def archive_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            archive.writestr(item["path"], base64.b64decode(item["data"]))
    return output.getvalue()
