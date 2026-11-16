from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from nodes import database, database_backups as backups


class DatabaseBackupsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'live' / 'prompts.sqlite3'
        self.output = self.root / 'snapshots'
        self.patches = [patch.object(database, 'DEFAULT_DB', self.source),
                        patch.object(backups, 'backup_directory', return_value=self.output)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def initialize(self):
        conn = database.open_connection(create=True)
        conn.execute('PRAGMA wal_autocheckpoint=0')
        for name in ('prompts', 'skill_files', 'media_files'):
            conn.execute(f'CREATE TABLE {name}(id INTEGER PRIMARY KEY, data BLOB)')
            conn.execute(f'INSERT INTO {name} VALUES(1,?)', (b'committed synthetic data',))
        conn.commit()
        return conn

    def test_snapshot_contains_live_wal_all_tables_and_is_standalone(self):
        with closing(self.initialize()) as source:
            wal = Path(str(self.source) + '-wal')
            self.assertGreater(wal.stat().st_size, 0)
            before = wal.read_bytes()
            record = backups.create_backup()
            saved = Path(record['path'])
            self.assertEqual(record['integrity'], 'ok')
            self.assertEqual(wal.read_bytes(), before)
            self.assertEqual(source.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertFalse(Path(str(saved) + '-wal').exists())
            with closing(sqlite3.connect(saved.as_uri() + '?mode=ro&immutable=1', uri=True)) as copy:
                self.assertEqual(copy.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
                self.assertEqual(copy.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
                for name in ('prompts', 'skill_files', 'media_files'):
                    self.assertEqual(copy.execute(f'SELECT data FROM {name}').fetchone()[0], b'committed synthetic data')
            self.assertEqual(backups.list_backups()['total'], 1)
            self.assertEqual(backups.download_path(record['filename']), saved)
            self.assertIsNone(backups.list_backups()['active'])

    def test_multiple_backups_do_not_overwrite_previous_snapshots(self):
        with closing(self.initialize()) as conn:
            first = backups.create_backup()
            conn.execute("INSERT INTO prompts VALUES(2,'later')")
            conn.commit()
            second = backups.create_backup()
        self.assertNotEqual(first['filename'], second['filename'])
        for record, expected in ((first, 1), (second, 2)):
            with closing(sqlite3.connect(record['path'])) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM prompts').fetchone()[0], expected)

    def test_missing_source_listing_is_read_only_and_create_does_not_create_database(self):
        self.assertEqual(backups.list_backups()['items'], [])
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError, '不存在'):
            backups.create_backup()
        self.assertFalse(self.source.exists())
        self.assertFalse(self.output.exists())

    def test_corrupt_source_does_not_publish_backup(self):
        self.source.parent.mkdir()
        self.source.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            backups.create_backup()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'not a database')

    def test_timeout_and_sync_failure_clean_up_and_release_lock(self):
        with closing(self.initialize()):
            with patch.object(backups, 'BACKUP_TIMEOUT_SECONDS', -1):
                with self.assertRaises(TimeoutError):
                    backups.create_backup()
            self.assertEqual(list(self.output.iterdir()), [])
            with patch.object(backups.os, 'fsync', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError):
                    backups.create_backup()
            self.assertEqual(list(self.output.iterdir()), [])
            self.assertEqual(backups.create_backup()['integrity'], 'ok')

    def test_busy_and_disk_full_reject_without_partial_files(self):
        with backups._operation_lock:
            with self.assertRaises(backups.BackupInProgress):
                backups.create_backup()
        with closing(self.initialize()), patch.object(backups.shutil, 'disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaisesRegex(OSError, '空间不足'):
                backups.create_backup()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_download_rejects_traversal_partial_files_and_symlinks(self):
        with closing(self.initialize()):
            record = backups.create_backup()
        for name in ('../prompts.sqlite3', 'prompts.sqlite3', '.prompts-backup-test.partial', '/etc/passwd'):
            with self.assertRaises(backups.BackupNotFound):
                backups.download_path(name)
        link = self.output / (record['filename'].rsplit('-', 1)[0] + '-deadbeef.sqlite3')
        link.symlink_to(self.source)
        self.assertIsNotNone(backups.NAME_PATTERN.fullmatch(link.name))
        self.assertEqual(backups.list_backups()['total'], 1)
        with self.assertRaises(backups.BackupNotFound):
            backups.download_path(link.name)

    def test_cleanup_preview_is_read_only_and_confirmation_retains_latest(self):
        with closing(self.initialize()) as source:
            records = [backups.create_backup() for _ in range(5)]
            (self.output / 'notes.txt').write_text('unrelated')
            (self.output / '.prompts-backup-test.partial').write_text('incomplete')
            plan = backups.preview_cleanup(2)
            self.assertEqual(plan['count'], 3)
            self.assertEqual(plan['size_bytes'], sum(item['size_bytes'] for item in records[:3]))
            self.assertEqual(backups.list_backups()['total'], 5)
            with self.assertRaises(ValueError):
                backups.cleanup_backups(plan['token'], False)
            result = backups.cleanup_backups(plan['token'], True)
            self.assertEqual(result['deleted_count'], 3)
            self.assertEqual(result['errors'], [])
            self.assertEqual({item['filename'] for item in backups.list_backups()['items']}, {item['filename'] for item in records[-2:]})
            self.assertEqual(source.execute('SELECT count(*) FROM prompts').fetchone()[0], 1)
            self.assertTrue((self.output / 'notes.txt').exists())
            self.assertTrue((self.output / '.prompts-backup-test.partial').exists())
            with self.assertRaises(backups.BackupPlanChanged):
                backups.cleanup_backups(plan['token'], True)

    def test_cleanup_rejects_zero_retention_busy_expiry_and_changed_files(self):
        for value in (0, -1, 1001, True, '1', 1.5):
            with self.assertRaises(ValueError):
                backups.preview_cleanup(value)
        with backups._operation_lock:
            with self.assertRaises(backups.BackupInProgress):
                backups.preview_cleanup(1)
        with closing(self.initialize()):
            first, second = backups.create_backup(), backups.create_backup()
            plan = backups.preview_cleanup(1)
            third = backups.create_backup()
            with self.assertRaises(backups.BackupPlanChanged):
                backups.cleanup_backups(plan['token'], True)
            self.assertEqual(backups.list_backups()['total'], 3)
            plan = backups.preview_cleanup(1)
            Path(first['path']).write_bytes(b'changed externally')
            with self.assertRaises(backups.BackupPlanChanged):
                backups.cleanup_backups(plan['token'], True)
            self.assertTrue(Path(second['path']).exists())
            self.assertTrue(Path(third['path']).exists())
            plan = backups.preview_cleanup(1)
            backups._cleanup_plans[plan['token']]['expires'] = 0
            with self.assertRaises(backups.BackupPlanChanged):
                backups.cleanup_backups(plan['token'], True)

    def test_cleanup_protects_links_and_open_backup_sidecars(self):
        with closing(self.initialize()):
            record = backups.create_backup()
            sidecar = Path(record['path'] + '-wal')
            sidecar.write_bytes(b'active journal')
            with self.assertRaises(backups.BackupPlanChanged):
                backups.preview_cleanup(1)
            sidecar.unlink()
            import os
            hardlink = self.output / (record['filename'].rsplit('-', 1)[0] + '-deadbeef.sqlite3')
            os.link(self.source, hardlink)
            with self.assertRaises(backups.BackupPlanChanged):
                backups.preview_cleanup(1)
            self.assertTrue(self.source.is_file())

    def test_cleanup_reports_partial_deletion_failures(self):
        with closing(self.initialize()):
            records = [backups.create_backup() for _ in range(3)]
            plan = backups.preview_cleanup(1)
            unlink = Path.unlink
            def guarded(path, *args, **kwargs):
                if path.name == records[0]['filename']:
                    raise PermissionError('synthetic permission denied')
                return unlink(path, *args, **kwargs)
            with patch.object(Path, 'unlink', guarded):
                result = backups.cleanup_backups(plan['token'], True)
            self.assertEqual(result['deleted_count'], 1)
            self.assertEqual(len(result['errors']), 1)
            self.assertEqual(backups.list_backups()['total'], 2)
            self.assertTrue(Path(records[-1]['path']).is_file())

    def test_single_delete_only_removes_selected_snapshot_and_allows_last_after_confirmation(self):
        with closing(self.initialize()) as source:
            first, selected, last = [backups.create_backup() for _ in range(3)]
            with self.assertRaises(ValueError):
                backups.delete_backup(selected['filename'], selected['version'], False)
            result = backups.delete_backup(selected['filename'], selected['version'], True)
            self.assertEqual(result['deleted'], selected['filename'])
            self.assertEqual(result['size_bytes'], selected['size_bytes'])
            self.assertEqual(result['remaining_count'], 2)
            self.assertTrue(Path(first['path']).is_file())
            self.assertTrue(Path(last['path']).is_file())
            self.assertFalse(Path(selected['path']).exists())
            backups.delete_backup(first['filename'], first['version'], True)
            self.assertEqual(backups.delete_backup(last['filename'], last['version'], True)['remaining_count'], 0)
            self.assertEqual(source.execute('SELECT count(*) FROM prompts').fetchone()[0], 1)

    def test_single_delete_rejects_changed_files_busy_operations_and_unmanaged_paths(self):
        with closing(self.initialize()):
            record = backups.create_backup()
            with backups._operation_lock:
                with self.assertRaises(backups.BackupInProgress):
                    backups.delete_backup(record['filename'], record['version'], True)
            for filename in ('../prompts.sqlite3', 'prompts.sqlite3', '.prompts-backup-test.partial'):
                with self.assertRaises(backups.BackupNotFound):
                    backups.delete_backup(filename, record['version'], True)
            saved = Path(record['path'])
            saved.write_bytes(b'changed externally')
            with self.assertRaises(backups.BackupPlanChanged):
                backups.delete_backup(record['filename'], record['version'], True)
            self.assertTrue(saved.exists())
            saved.unlink()
            saved.symlink_to(self.source)
            with self.assertRaises(backups.BackupNotFound):
                backups.delete_backup(record['filename'], record['version'], True)
            saved.unlink()
            import os
            os.link(self.source, saved)
            with self.assertRaises(backups.BackupPlanChanged):
                backups.delete_backup(record['filename'], record['version'], True)
            self.assertTrue(self.source.is_file())

    def test_single_delete_failure_preserves_file_and_releases_lock(self):
        with closing(self.initialize()):
            record = backups.create_backup()
            with patch.object(Path, 'unlink', side_effect=PermissionError('synthetic permission denied')):
                with self.assertRaises(PermissionError):
                    backups.delete_backup(record['filename'], record['version'], True)
            self.assertTrue(Path(record['path']).is_file())
            self.assertIsNone(backups.list_backups()['active'])
            self.assertEqual(backups.delete_backup(record['filename'], record['version'], True)['remaining_count'], 0)


if __name__ == '__main__':
    unittest.main()
