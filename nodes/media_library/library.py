"""Persistent catalog, recent selection and constrained file operations."""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .. import database
from . import metadata


class LibraryError(ValueError):
    pass


class Library:
    def __init__(self, db_path: Path, cache_dir: Path, defaults: dict[str, str] | None = None):
        self.db_path = Path(db_path).resolve()
        self.cache = Path(cache_dir).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.operations_lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.status = {'running': False, 'scanned': 0, 'errors': [], 'finished_at': None}
        self.plans = {}
        self.revision = 0
        self.db = database.open_connection(self.db_path, create=True, check_same_thread=False)
        try:
            self.initialize(defaults)
        except BaseException:
            self.db.close()
            raise

    def initialize(self, defaults):
        with self.transaction() as db:
            database.initialize(db)
            for statement in '''
          CREATE TABLE IF NOT EXISTS media_roots(id TEXT PRIMARY KEY, path TEXT UNIQUE, name TEXT, builtin INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS media_files(id TEXT PRIMARY KEY, path TEXT, root_id TEXT, name TEXT, kind TEXT,
            size INTEGER, mtime_ns INTEGER, signature TEXT, metadata TEXT DEFAULT '{}', search_text TEXT, missing INTEGER DEFAULT 0);
          CREATE UNIQUE INDEX IF NOT EXISTS media_files_active_path ON media_files(path) WHERE missing=0;
          CREATE INDEX IF NOT EXISTS media_files_root ON media_files(root_id,missing);
          CREATE INDEX IF NOT EXISTS media_files_sort ON media_files(mtime_ns);
          CREATE TABLE IF NOT EXISTS media_recents(file_id TEXT PRIMARY KEY, used_at INTEGER);
            '''.split(';'):
                if statement.strip():
                    db.execute(statement)
            seen_defaults = set()
            for name, path in (defaults or {}).items():
                resolved = str(Path(path).resolve())
                if resolved in seen_defaults: continue
                seen_defaults.add(resolved)
                # Refresh built-in roots when ComfyUI was started with different directory arguments.
                rid = 'builtin-' + name
                collision = db.execute('SELECT id FROM media_roots WHERE path=? AND id!=?', (resolved, rid)).fetchone()
                if collision:
                    db.execute('UPDATE media_files SET root_id=? WHERE root_id=?', (rid, collision['id']))
                    db.execute('DELETE FROM media_roots WHERE id=?', (collision['id'],))
                db.execute('INSERT INTO media_roots VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET path=excluded.path,name=excluded.name,builtin=1', (rid, resolved, name))

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.db.in_transaction:
                yield self.db
            else:
                with self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    yield self.db

    def roots(self):
        with self.lock: return [dict(r) for r in self.db.execute('SELECT * FROM media_roots ORDER BY builtin DESC,name')]

    def add_root(self, path: str, name: str = ''):
        p = Path(path).expanduser()
        if not p.is_absolute() or not p.is_dir(): raise LibraryError('请输入服务器上存在的绝对目录路径')
        p = p.resolve()
        if self.is_internal_path(p):
            raise LibraryError('素材目录不能是插件数据库或预览缓存')
        try:
            with self.transaction() as db:
                db.execute('INSERT INTO media_roots VALUES(?,?,?,0)', (uuid.uuid4().hex, str(p), name.strip() or p.name))
        except sqlite3.IntegrityError: raise LibraryError('该目录已经添加')
        self.revision += 1
        return self.roots()

    def remove_root(self, root_id):
        with self.operations_lock, self.transaction() as db:
            row = db.execute('SELECT * FROM media_roots WHERE id=?', (root_id,)).fetchone()
            if not row or row['builtin']: raise LibraryError('默认目录不能移除')
            db.execute('DELETE FROM media_roots WHERE id=?', (root_id,))
            db.execute('UPDATE media_files SET missing=1 WHERE root_id=?', (root_id,))
            self.revision += 1

    def is_internal_path(self, path):
        p = Path(path).resolve()
        return (p == self.cache or p.is_relative_to(self.cache) or
                p.parent == self.db_path.parent and
                p.name in {self.db_path.name + suffix for suffix in ('', '-wal', '-shm', '-journal')})

    def check_path(self, path, *, must_exist=True):
        p = Path(os.path.abspath(os.path.expanduser(str(path))))
        candidates = sorted((r for r in self.roots() if p.is_relative_to(Path(r['path']))), key=lambda r: len(r['path']), reverse=True)
        if not candidates: raise LibraryError('路径不在配置的素材目录内')
        root = candidates[0]
        base = Path(root['path'])
        cursor = p
        while cursor != base:
            if cursor.is_symlink(): raise LibraryError('不读取或操作符号链接，请将目标目录单独加入素材库')
            cursor = cursor.parent
        if not p.resolve().is_relative_to(base.resolve()): raise LibraryError('路径超出素材目录')
        if self.is_internal_path(p): raise LibraryError('不能访问插件数据库或预览缓存')
        if must_exist and not p.exists(): raise LibraryError('原文件已失效，请刷新素材库并重新选择')
        return p, root

    def row(self, file_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM media_files WHERE id=?', (file_id,)).fetchone()
        if not row: raise LibraryError('找不到该素材，请刷新素材库')
        return dict(row)

    def resolve(self, file_id='', path=''):
        if file_id:
            row = self.row(file_id)
            path = row['path']
            if row['missing']: raise LibraryError('原文件已失效，请重新选择：' + path)
        try:
            p, _ = self.check_path(path)
        except LibraryError:
            if file_id and not Path(path).is_file():
                with self.transaction() as db: db.execute('UPDATE media_files SET missing=1 WHERE id=?', (file_id,))
            raise
        if not p.is_file(): raise LibraryError('请选择一个文件')
        return p

    @staticmethod
    def search_text(path, info):
        return '\n'.join([str(path), json.dumps(info.get('summary', {}), ensure_ascii=False),
                          json.dumps(info.get('generation_nodes', []), ensure_ascii=False),
                          json.dumps(info.get('raw', {}), ensure_ascii=False), info.get('text', '')]).casefold()

    def upsert(self, path: Path, *, force=False):
        with self.operations_lock:
            p, root = self.check_path(path)
            if not p.is_file(): raise LibraryError('不是普通文件')
            stat = p.stat()
            sig = metadata.signature(p)
            with self.lock: existing = self.db.execute('SELECT * FROM media_files WHERE path=? AND missing=0', (str(p),)).fetchone()
            if existing and existing['signature'] == sig and not force:
                cached = json.loads(existing['metadata'])
                if cached.get('parser_version') != metadata.PARSER_VERSION:
                    # Upgrade summaries from the preserved JSON; do not re-probe media files.
                    cached = metadata.refresh_generation(cached)
                    with self.transaction() as db:
                        db.execute('UPDATE media_files SET metadata=?,search_text=? WHERE id=?', (json.dumps(cached, ensure_ascii=False), self.search_text(p,cached), existing['id']))
                    self.revision += 1
                if existing['root_id'] != root['id']:
                    with self.transaction() as db:
                        db.execute('UPDATE media_files SET root_id=? WHERE id=?', (root['id'], existing['id']))
                return existing['id']
        # Probing large or damaged media must not block other detail requests or management.
        info = metadata.inspect(p)
        searchable = self.search_text(p, info)
        with self.operations_lock:
            p, root = self.check_path(p)
            if metadata.signature(p) != sig: raise LibraryError('文件正在写入，稍后刷新即可')
            with self.transaction() as db:
                # Another request may have indexed this path during inspection.
                existing = db.execute('SELECT id FROM media_files WHERE path=? AND missing=0', (str(p),)).fetchone()
                file_id = existing['id'] if existing else uuid.uuid4().hex
                db.execute('''INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET
                    path=excluded.path,root_id=excluded.root_id,name=excluded.name,kind=excluded.kind,size=excluded.size,mtime_ns=excluded.mtime_ns,
                    signature=excluded.signature,metadata=excluded.metadata,search_text=excluded.search_text,missing=0''',
                    (file_id, str(p), root['id'], p.name, info['kind'], stat.st_size, stat.st_mtime_ns, sig, json.dumps(info, ensure_ascii=False), searchable))
            self.revision += 1
        return file_id

    def detail(self, file_id='', path=''):
        p = self.resolve(file_id, path)
        actual_id = self.upsert(p)
        with self.operations_lock:
            p = self.resolve(actual_id)
            row = self.row(actual_id)
            info = json.loads(row.pop('metadata'))
            row.pop('search_text', None)
            row.pop('signature', None)
            return {**row, **info, 'extension': p.suffix.lower(), 'mtime': row['mtime_ns'] / 1e9}

    def brief(self, row):
        data = dict(row)
        info = json.loads(data.pop('metadata', '{}'))
        data.pop('search_text', None)
        data.pop('signature', None)
        data['properties'] = info.get('properties', {})
        data['errors'] = info.get('errors', [])
        data['extension'] = Path(data['path']).suffix.lower()
        data['mtime'] = data['mtime_ns'] / 1e9
        return data

    def files(self, *, q='', kind='', root_id='', folder='', recursive=False, sort='time', direction='desc', offset=0, limit=80, recent=False, focus_id=''):
        offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
        where, args = ['1=1' if recent else 'f.missing=0'], []
        if q:
            escaped = q.casefold().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("f.search_text LIKE ? ESCAPE '\\'")
            args.append('%' + escaped + '%')
        if kind: where.append('f.kind=?'); args.append(kind)
        root = next((r for r in self.roots() if r['id'] == root_id), None) if root_id else None
        if root_id and not root: raise LibraryError('找不到所选素材目录')
        scope = folder or (root['path'] if root else '')
        if scope:
            p, _ = self.check_path(scope)
            if not p.is_dir(): raise LibraryError('不是目录')
            if root and not p.is_relative_to(Path(root['path'])): raise LibraryError('目录不在所选素材目录内')
            prefix = str(p) + os.sep
            escaped = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("f.path LIKE ? ESCAPE '\\'"); args.append(escaped + '%')
            if not recursive:
                where.append('instr(substr(f.path, ?), ?)=0')
                args.extend([len(prefix) + 1, os.sep])
            else:
                # Cached descendants of hidden directories must also stay out of flat views.
                where.append('NOT (substr(f.path, ?) GLOB ? OR substr(f.path, ?) GLOB ?)')
                args.extend([len(prefix) + 1, '.*' + os.sep + '*', len(prefix) + 1, '*' + os.sep + '.*' + os.sep + '*'])
        order = {'name': 'f.name COLLATE NOCASE', 'size': 'f.size', 'time': 'f.mtime_ns'}.get(sort, 'f.mtime_ns')
        order += ' ASC' if direction == 'asc' else ' DESC'
        table = 'media_files f JOIN media_recents r ON r.file_id=f.id' if recent else 'media_files f'
        if recent: order = 'r.used_at DESC'
        condition = ' AND '.join(where)
        focus = None
        with self.lock:
            total = self.db.execute(f'SELECT count(*) FROM {table} WHERE {condition}', args).fetchone()[0]
            if focus_id:
                position = self.db.execute(f'''SELECT position,previous_id,next_id FROM (
                    SELECT f.id, ROW_NUMBER() OVER (ORDER BY {order},f.id)-1 AS position,
                    LAG(f.id) OVER (ORDER BY {order},f.id) AS previous_id,
                    LEAD(f.id) OVER (ORDER BY {order},f.id) AS next_id
                    FROM {table} WHERE {condition}) WHERE id=?''', [*args, focus_id]).fetchone()
                if position is not None:
                    offset = (position['position'] // limit) * limit
                    focus = dict(position)
            rows = self.db.execute(f'SELECT f.* FROM {table} WHERE {condition} ORDER BY {order},f.id LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
        return {'items': [self.brief(row) for row in rows], 'total': total, 'offset': offset, 'limit': limit, 'focus': focus}

    def folders(self, path):
        p, _ = self.check_path(path)
        if not p.is_dir(): raise LibraryError('不是目录')
        return [{'name': child.name, 'path': str(child)} for child in sorted(p.iterdir(), key=lambda x: x.name.casefold()) if not child.name.startswith('.') and child.is_dir() and not child.is_symlink() and not self.is_internal_path(child)]

    @staticmethod
    def rename_directory_no_replace(source, target):
        """Claim the new directory name atomically without replacing even an empty target."""
        if os.name == 'nt':
            os.rename(source, target)  # Windows rename refuses existing destinations.
            return
        libc = ctypes.CDLL(None, use_errno=True)
        if hasattr(libc, 'renameat2'):
            rename = libc.renameat2
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)  # RENAME_NOREPLACE
        elif hasattr(libc, 'renamex_np'):
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            result = rename(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL on macOS.
        else:
            raise LibraryError('当前系统不支持不覆盖目标的目录重命名')
        if result:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))

    def rename_folder(self, path, name):
        if not isinstance(name, str): raise LibraryError('请输入目录名称')
        self.valid_name(name)
        with self.operations_lock:
            source, _ = self.check_path(path)
            if not source.is_dir(): raise LibraryError('请选择目录')
            roots = self.roots()
            if any(root['builtin'] and Path(root['path']).is_relative_to(source) for root in roots):
                raise LibraryError('不能重命名 ComfyUI 默认目录或包含默认目录的位置')
            if self.db_path.is_relative_to(source) or self.cache.is_relative_to(source):
                raise LibraryError('不能重命名包含插件数据库或预览缓存的目录')
            target = source.with_name(name)
            if target == source: raise LibraryError('新旧目录名称相同')
            if target.exists() or target.is_symlink(): raise LibraryError('目标目录或文件已经存在')
            if any(Path(root['path']) == target for root in roots): raise LibraryError('目标路径已经配置为素材目录')
            if self.is_internal_path(target): raise LibraryError('不能使用插件数据库或预览缓存路径')
            # A custom root may be renamed within its parent; other directories stay in scope.
            if not any(Path(root['path']) == source for root in roots):
                self.check_path(target, must_exist=False)
            moved = False
            try:
                with self.transaction() as db:
                    prefix = str(source) + os.sep
                    rows = [dict(row) for row in db.execute(
                        'SELECT * FROM media_files WHERE path=? OR substr(path,1,?)=?',
                        (str(source), len(prefix), prefix),
                    )]
                    for root in roots:
                        old = Path(root['path'])
                        if old.is_relative_to(source):
                            root['path'] = str(target / old.relative_to(source))
                            if old == source: root['name'] = name
                            db.execute('UPDATE media_roots SET path=?,name=? WHERE id=?', (root['path'], root['name'], root['id']))
                    for row in rows:
                        new_path = target / Path(row['path']).relative_to(source)
                        root = max((root for root in roots if new_path.is_relative_to(Path(root['path']))), key=lambda root: len(root['path']))
                        # Discard stale active entries for a target that no longer exists on disk.
                        if not row['missing']:
                            db.execute('UPDATE media_files SET missing=1 WHERE path=? AND id!=?', (str(new_path), row['id']))
                        db.execute('UPDATE media_files SET path=?,root_id=?,signature=NULL,search_text=? WHERE id=?',
                                   (str(new_path), root['id'], self.search_text(new_path, json.loads(row['metadata'])), row['id']))
                    self.rename_directory_no_replace(source, target)
                    moved = True
            except BaseException:
                if moved:
                    try: self.rename_directory_no_replace(target, source)
                    except OSError as exc:
                        raise LibraryError(f'目录已改名为 {target}，数据库保存失败且无法恢复原目录：{exc}') from exc
                raise
            self.plans.clear()
            self.revision += 1
            return {'path': str(target), 'previous_path': str(source), 'roots': self.roots(), 'updated_files': len(rows)}

    def select(self, file_id='', path=''):
        item = self.detail(file_id, path)
        with self.transaction() as db:
            db.execute('INSERT INTO media_recents VALUES(?,?) ON CONFLICT(file_id) DO UPDATE SET used_at=excluded.used_at', (item['id'], time.time_ns()))
            db.execute('DELETE FROM media_recents WHERE file_id NOT IN (SELECT file_id FROM media_recents ORDER BY used_at DESC LIMIT 20)')
        self.revision += 1
        return item

    def prune_recents(self):
        with self.transaction() as db:
            for row in db.execute('SELECT f.id,f.path,f.missing FROM media_files f JOIN media_recents r ON r.file_id=f.id').fetchall():
                try: self.resolve(row['id'])
                except LibraryError: db.execute('DELETE FROM media_recents WHERE file_id=?', (row['id'],))
        self.revision += 1

    def scan(self, folder='', recursive=False):
        if not self.scan_lock.acquire(blocking=False): return False
        self.status = {'running': True, 'scanned': 0, 'errors': [], 'finished_at': None}
        seen, successful_scopes = set(), []
        try:
            bases = [self.check_path(folder)[0]] if folder else [Path(root['path']) for root in self.roots()]
            for base in bases:
                errors = []
                if not base.is_dir():
                    self.status['errors'].append(str(base) + '：目录不存在或未挂载')
                    continue
                for directory, dirs, names in os.walk(base, followlinks=False, onerror=lambda e: errors.append(str(e))):
                    dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(directory) / d).is_symlink() and not self.is_internal_path(Path(directory) / d)] if recursive else []
                    for name in names:
                        p = Path(directory) / name
                        if p.is_symlink() or not p.is_file() or self.is_internal_path(p): continue
                        try:
                            file_id = self.upsert(p)
                            seen.add(file_id)
                            self.status['scanned'] += 1
                        except Exception as exc:
                            # Preserve existing IDs on transient parse/access failures.
                            errors.append(f'{p}：{exc}')
                        if len(errors) > 30: errors = errors[:30]
                if not errors: successful_scopes.append(base)
                self.status['errors'].extend(errors[:30])
            # Filesystem checks must not hold the shared database's write lock.
            with self.operations_lock:
                with self.lock:
                    rows = self.db.execute('SELECT id,path FROM media_files WHERE missing=0').fetchall()
                missing = []
                for row in rows:
                    path = Path(row['path'])
                    covered = any(path.is_relative_to(base) if recursive else path.parent == base for base in successful_scopes)
                    if covered and row['id'] not in seen and not path.is_file():
                        missing.append((row['id'], row['path']))
                if missing:
                    with self.transaction() as db:
                        db.executemany('UPDATE media_files SET missing=1 WHERE id=? AND path=?', missing)
        finally:
            self.status.update(running=False, finished_at=time.time())
            self.revision += 1
            try: self.clean_cache()
            finally: self.scan_lock.release()
        return True

    def fingerprint(self, p):
        s = p.stat()
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]

    @staticmethod
    def valid_name(name):
        if not name or name in ('.', '..') or any(c in name for c in '/\\\x00'):
            raise LibraryError('文件名不能为空，也不能包含路径分隔符')

    def plan(self, op, ids, *, destination='', template='{name}_{index}', start=1):
        if op not in ('rename', 'move', 'delete'): raise LibraryError('未知文件操作')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 1000: raise LibraryError('请选择 1 至 1000 个文件')
        ids = list(dict.fromkeys(ids))
        if op == 'move':
            dest, _ = self.check_path(destination)
            if not dest.is_dir(): raise LibraryError('移动目标必须是已有目录')
        entries, targets, claimed = [], set(), set()
        with self.operations_lock:
            # An explicitly selected companion is handled with its primary exactly once,
            # independent of checkbox ordering.
            associated = set()
            for file_id in ids:
                try: associated.update(str(p) for p in metadata.sidecars(self.resolve(file_id)))
                except (LibraryError, OSError): pass
            primary_ids = []
            for file_id in ids:
                try:
                    if self.row(file_id)['path'] in associated: continue
                except LibraryError: pass
                primary_ids.append(file_id)
            for index, file_id in enumerate(primary_ids, int(start)):
                try:
                    p = self.resolve(file_id)
                    if str(p) in claimed: continue
                    if op == 'rename':
                        try: name = template.format(name=p.stem, index=index) + p.suffix
                        except (ValueError, KeyError, IndexError, AttributeError) as exc: raise LibraryError('名称模板仅支持 {name} 和 {index}（可用 {index:03d}）') from exc
                        self.valid_name(name)
                        target = p.with_name(name)
                    elif op == 'move': target = dest / p.name
                    else: target = None
                    pairs = [(p, target)]
                    for sidecar in metadata.sidecars(p):
                        if target:
                            suffix = sidecar.name[len(p.name):] if sidecar.name.startswith(p.name + '.') else None
                            side_target = Path(str(target) + suffix) if suffix else target.with_suffix('.xmp')
                        else: side_target = None
                        pairs.append((sidecar, side_target))
                    actions = []
                    for source, target in pairs:
                        self.check_path(source)
                        if target:
                            self.check_path(target, must_exist=False)
                            if target == source: raise LibraryError('新旧路径相同，无需操作')
                            if target.exists() or target.is_symlink() or str(target) in targets: raise LibraryError('目标文件已存在或批量名称重复：' + str(target))
                        actions.append({'source': str(source), 'target': str(target) if target else None, 'fingerprint': self.fingerprint(source)})
                    for action in actions:
                        if action['target']: targets.add(action['target'])
                        claimed.add(action['source'])
                    entries.append({'id': file_id, 'actions': actions})
                except (LibraryError, OSError) as exc:
                    entries.append({'id': file_id, 'error': str(exc), 'actions': []})
            token = uuid.uuid4().hex
            plan = {'token': token, 'op': op, 'entries': entries, 'created_at': time.time()}
            # Bound abandoned previews and invalidate old confirmations.
            self.plans = {k:v for k,v in self.plans.items() if time.time() - v['created_at'] < 600}
            self.plans[token] = plan
            return plan

    @staticmethod
    def move_no_replace(source: Path, target: Path):
        """Atomic no-clobber destination claim. Cross-device moves verify SHA256."""
        try:
            os.link(source, target, follow_symlinks=False)
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP): raise
            before = source.stat()
            claimed = False
            try:
                with source.open('rb') as src, target.open('xb') as dst:
                    claimed = True
                    digest = hashlib.sha256()
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk); digest.update(chunk)
                    dst.flush(); os.fsync(dst.fileno())
                check = hashlib.sha256()
                with target.open('rb') as dst:
                    while chunk := dst.read(1024 * 1024): check.update(chunk)
                after = source.stat()
                if digest.digest() != check.digest() or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise LibraryError('复制校验失败或源文件已变化，保留原文件')
                shutil.copystat(source, target)
            except Exception:
                if claimed: target.unlink(missing_ok=True)
                raise
        try: source.unlink()
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def apply(self, token, confirmed=False):
        if confirmed is not True: raise LibraryError('必须确认预览清单后才能执行')
        with self.operations_lock:
            plan = self.plans.pop(token, None)
            if not plan or time.time() - plan['created_at'] >= 600: raise LibraryError('操作确认已过期，请重新打开操作窗口')
            results = []
            for entry in plan['entries']:
                if entry.get('error'):
                    results.append({**entry, 'ok': False}); continue
                completed = []
                try:
                    # Revalidate the whole companion group before changing any file.
                    for action in entry['actions']:
                        source, _ = self.check_path(action['source'])
                        if self.fingerprint(source) != action['fingerprint']: raise LibraryError('文件已发生变化，请关闭后重新操作')
                        if action['target']:
                            target, _ = self.check_path(action['target'], must_exist=False)
                            if target.exists() or target.is_symlink(): raise LibraryError('目标文件已经存在')
                    for action in entry['actions']:
                        source = Path(action['source'])
                        if action['target']: self.move_no_replace(source, Path(action['target']))
                        else: source.unlink()
                        completed.append(action)
                        with self.transaction() as db:
                            old = db.execute('SELECT id FROM media_files WHERE path=? AND missing=0', (str(source),)).fetchone()
                            if old:
                                if action['target']:
                                    target = Path(action['target'])
                                    _, root = self.check_path(target)
                                    db.execute('UPDATE media_files SET missing=1 WHERE path=? AND id!=?', (str(target), old['id']))
                                    # Search text must not keep the old filename/path.
                                    db.execute('UPDATE media_files SET path=?,name=?,root_id=?,signature=NULL,search_text=? WHERE id=?', (str(target), target.name, root['id'], str(target).casefold(), old['id']))
                                else: db.execute('UPDATE media_files SET missing=1 WHERE id=?', (old['id'],))
                    if plan['op'] != 'delete': self.upsert(Path(entry['actions'][0]['target']))
                    for cached in self.cache.glob(entry['id'] + '-*'):
                        cached.unlink(missing_ok=True)
                    results.append({'id': entry['id'], 'ok': True, 'completed': completed})
                except Exception as exc:
                    results.append({'id': entry['id'], 'ok': False, 'error': str(exc), 'completed': completed})
            self.clean_cache()
            self.revision += 1
            return {'results': results, 'op': plan['op']}

    def clean_cache(self, protected=None):
        # Retain up to seven days / 2 GiB of derived previews, never source media.
        self.cache.mkdir(parents=True, exist_ok=True)
        files = []
        for p in self.cache.iterdir():
            try:
                if p.is_file() and '.tmp.' not in p.name:
                    stat = p.stat()
                    files.append((stat.st_mtime, stat.st_size, p))
            except OSError: pass
        total = sum(s for _, s, _ in files)
        for mtime, size, p in sorted(files):
            if p == protected: continue
            if time.time() - mtime > 7 * 86400 or total > 2 * 1024**3:
                try: p.unlink(missing_ok=True); total -= size
                except OSError: pass

    def close(self):
        with self.lock: self.db.close()
