"""User-requested, verified snapshots of the entire shared ToolBox database."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from . import database

NAME_PATTERN = re.compile(r'prompts-\d{8}T\d{12}Z-[0-9a-f]{8}\.sqlite3')
BACKUP_TIMEOUT_SECONDS = 600
_operation_lock = threading.Lock()
_state_lock = threading.Lock()
_active = None
_cleanup_plans = {}
CLEANUP_PLAN_SECONDS = 600


class BackupInProgress(ValueError):
    pass


class BackupNotFound(ValueError):
    pass


class BackupPlanChanged(ValueError):
    pass


def backup_directory():
    try:
        import folder_paths
    except ImportError:
        return database.DEFAULT_DB.resolve().parent / 'backups'
    return Path(folder_paths.get_user_directory()).resolve() / 'toolbox-database-backups'


def _set_active(value):
    global _active
    with _state_lock:
        _active = value


def _record(path):
    stat = path.stat()
    return {'filename': path.name, 'size_bytes': stat.st_size, 'path': str(path),
            'created_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            'version': _version([path.name, *_fingerprint(stat)])}


def _fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _version(identity):
    return hashlib.sha256(repr(identity).encode()).hexdigest()


def _backup_paths():
    directory = backup_directory()
    paths = [p for p in directory.iterdir() if NAME_PATTERN.fullmatch(p.name) and not p.is_symlink() and p.is_file()] if directory.is_dir() else []
    paths.sort(key=lambda p: p.name, reverse=True)
    return paths


def list_backups():
    directory = backup_directory()
    paths = _backup_paths()
    with _state_lock:
        active = dict(_active) if _active else None
    return {'directory': str(directory), 'source_path': str(database.DEFAULT_DB.resolve()),
            'items': [_record(p) for p in paths[:100]], 'total': len(paths), 'active': active}


def download_path(filename):
    if not NAME_PATTERN.fullmatch(filename):
        raise BackupNotFound('备份不存在。')
    path = backup_directory() / filename
    if path.is_symlink() or not path.is_file():
        raise BackupNotFound('备份不存在。')
    return path


def _identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise BackupPlanChanged('备份列表已改变，请重新预览。') from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise BackupPlanChanged('备份文件已改变或包含链接，请重新预览。')
    if any(path.with_name(path.name + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise BackupPlanChanged('备份文件正在被其他工具使用，请关闭后重新预览。')
    if path.resolve() == database.DEFAULT_DB.resolve():
        raise BackupPlanChanged('不能清理当前数据库。')
    return [path.name, *_fingerprint(info)]


def delete_backup(filename, version, confirmed):
    if confirmed is not True or not isinstance(version, str) or not re.fullmatch('[0-9a-f]{64}', version):
        raise ValueError('请先选择备份并确认删除。')
    if not _operation_lock.acquire(blocking=False):
        raise BackupInProgress('数据库备份、清理或删除正在进行，请等待完成。')
    try:
        path = download_path(filename)
        identity = _identity(path)
        if _version(identity) != version:
            raise BackupPlanChanged('备份文件已改变，请刷新列表后重新选择。')
        _set_active({'phase': 'deleting', 'percent': 0})
        path.unlink()
        return {'deleted': filename, 'size_bytes': identity[3], 'remaining_count': len(_backup_paths())}
    finally:
        _set_active(None)
        _operation_lock.release()


def preview_cleanup(keep_latest):
    if type(keep_latest) is not int or not 1 <= keep_latest <= 1000:
        raise ValueError('保留数量必须为 1–1000 的整数，至少保留最新一份备份。')
    if not _operation_lock.acquire(blocking=False):
        raise BackupInProgress('数据库备份、清理或删除正在进行，请等待完成。')
    try:
        now = time.monotonic()
        for token in list(_cleanup_plans):
            if _cleanup_plans[token]['expires'] <= now:
                del _cleanup_plans[token]
        if len(_cleanup_plans) >= 128:
            del _cleanup_plans[next(iter(_cleanup_plans))]
        paths = _backup_paths()
        snapshot = [_identity(path) for path in paths]
        items = [_record(path) for path in paths[keep_latest:]]
        token = uuid.uuid4().hex
        _cleanup_plans[token] = {'expires': now + CLEANUP_PLAN_SECONDS, 'snapshot': snapshot,
            'directory': str(backup_directory().resolve()), 'source': str(database.DEFAULT_DB.resolve()),
            'keep_latest': keep_latest}
        return {'token': token, 'keep_latest': keep_latest, 'items': items, 'count': len(items),
                'size_bytes': sum(item['size_bytes'] for item in items), 'retained_count': min(len(paths), keep_latest)}
    finally:
        _operation_lock.release()


def cleanup_backups(token, confirmed):
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token) or confirmed is not True:
        raise ValueError('请先预览并确认清理。')
    if not _operation_lock.acquire(blocking=False):
        raise BackupInProgress('数据库备份、清理或删除正在进行，请等待完成。')
    try:
        plan = _cleanup_plans.pop(token, None)
        if plan is None or plan['expires'] <= time.monotonic():
            raise BackupPlanChanged('清理预览已过期，请重新预览。')
        paths = _backup_paths()
        if (plan['directory'] != str(backup_directory().resolve()) or
                plan['source'] != str(database.DEFAULT_DB.resolve()) or
                plan['snapshot'] != [_identity(path) for path in paths]):
            raise BackupPlanChanged('备份列表已改变，请重新预览后确认。')
        _set_active({'phase': 'cleaning', 'percent': 0})
        deleted, errors, freed = [], [], 0
        for path in paths[plan['keep_latest']:]:
            try:
                info = path.stat()
                path.unlink()
                deleted.append(path.name)
                freed += info.st_size
            except OSError as exc:
                errors.append({'filename': path.name, 'error': str(exc)})
                break
        return {'deleted_count': len(deleted), 'deleted': deleted, 'size_bytes': freed,
                'errors': errors, 'retained_count': len(paths) - len(deleted)}
    finally:
        _set_active(None)
        _operation_lock.release()


def create_backup():
    if not _operation_lock.acquire(blocking=False):
        raise BackupInProgress('数据库备份、清理或删除正在进行，请等待完成。')
    temporary = None
    try:
        _set_active({'phase': 'copying', 'percent': 0})
        source_path = database.DEFAULT_DB.resolve()
        if not source_path.is_file():
            raise ValueError('数据库不存在，无法备份。')
        directory = backup_directory()
        directory.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + BACKUP_TIMEOUT_SECONDS

        def progress(_status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('备份超时，请在数据库写入较少时重试。')
            _set_active({'phase': 'copying', 'percent': int(100 * (total - remaining) / total) if total else 0})

        # Open the same runtime path as every ToolBox library, including its WAL.
        with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True, timeout=5)) as source:
            source.execute('PRAGMA query_only=ON')
            if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompts'").fetchone():
                raise ValueError('数据库尚未初始化，无法备份。')
            estimated = source.execute('PRAGMA page_count').fetchone()[0] * source.execute('PRAGMA page_size').fetchone()[0]
            if shutil.disk_usage(directory).free < estimated + 16 * 1024 * 1024:
                raise OSError('备份目录的剩余空间不足。')
            descriptor, name = tempfile.mkstemp(prefix='.prompts-backup-', suffix='.partial', dir=directory)
            os.close(descriptor)
            temporary = Path(name)
            with closing(sqlite3.connect(temporary)) as destination:
                destination.execute('PRAGMA synchronous=FULL')
                source.backup(destination, pages=256, progress=progress, sleep=0.05)
                # Produce one standalone file; never require the live database's sidecars.
                destination.execute('PRAGMA journal_mode=DELETE')
                _set_active({'phase': 'verifying', 'percent': 100})
                destination.set_progress_handler(lambda: int(time.monotonic() > deadline), 100000)
                result = destination.execute('PRAGMA integrity_check(20)').fetchall()
                if result != [('ok',)]:
                    raise ValueError('备份完整性检查失败，未保存此副本。')
        with temporary.open('rb') as handle:
            os.fsync(handle.fileno())
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        final = directory / f'prompts-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3'
        os.replace(temporary, final)
        temporary = None
        if os.name == 'posix':
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return {**_record(final), 'integrity': 'ok'}
    finally:
        try:
            if temporary is not None:
                for suffix in ('', '-journal', '-wal', '-shm'):
                    temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
        finally:
            _set_active(None)
            _operation_lock.release()
