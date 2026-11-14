import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_library as library, prompt_nodes as prompts
from nodes.prompt_examples_schema import initialize


class PromptManagementTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'prompts.sqlite3'
        database = patch.object(prompts.database, 'DEFAULT_DB', self.path)
        database.start(); self.addCleanup(database.stop)
        writer = prompts.ToolBoxPromptWriter()
        for text, tags in (('first', '摄影,shared'), ('second', 'shared')):
            writer.write_prompt(0, text, 'zh', 'image', 'natural', False, 'plaintext', False, 1024, 768, tags)

    def test_prompt_removes_all_versions_preserves_files_tags_and_other_libraries(self):
        file = Path(self.directory.name) / 'original.png'; file.write_bytes(b'original')
        with prompts.connect_db() as conn:
            initialize(conn)
            conn.execute('CREATE TABLE skill_tags(name TEXT)')
            conn.execute("INSERT INTO skill_tags VALUES ('摄影')")
            for prompt_id, shasum in ((1, 'old'), (1, 'current'), (2, 'other')):
                conn.execute('''INSERT INTO prompt_examples(prompt_id,prompt_shasum,relative_path,media_type,
                    source,created_at,updated_at,file_size,mtime_ns) VALUES(?,?,?,'image','test','now','now',8,0)''',
                             (prompt_id, shasum, str(file)))
        revision = prompts.prompt_data_revision()
        self.assertEqual(library.delete_prompt(1, {'version':library.detail(1)['version']}), {'deleted':[1]})
        self.assertNotEqual(revision, prompts.prompt_data_revision())
        with prompts.connect_db() as conn:
            self.assertEqual(conn.execute('SELECT prompt_id FROM prompt_examples').fetchall()[0][0], 2)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM prompt_tags WHERE prompt_id=1').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT name FROM skill_tags').fetchone()[0], '摄影')
        self.assertTrue(file.exists())
        self.assertEqual(library.detail(2)['prompt'], 'second')
        self.assertEqual(library.list_tags({})['counts']['摄影'], 0)
        with self.assertRaises(library.PromptNotFound):
            library.delete_prompt(1, {'version':'0' * 64})

    def test_delete_version_conflict_validation_and_transaction_rollback(self):
        stale = library.detail(1)['version']
        with prompts.connect_db() as conn:
            prompts.insert_tags(conn, 1, ['new'])
        with self.assertRaises(prompts.PromptConflict):
            library.delete_prompt(1, {'version':stale})
        for payload in (None, {}, {'version':1}, {'version':'bad'}, {'version':stale, 'extra':True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                library.delete_prompt(1, payload)
        with prompts.connect_db() as conn:
            conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON prompts BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            library.delete_prompt(1, {'version':library.detail(1)['version']})
        self.assertEqual(library.detail(1)['tags'], ['new', 'shared', '摄影'])

    def test_global_tag_delete_and_rollback_preserve_prompts_and_invalidate_versions(self):
        old = library.detail(1)['version']; revision = prompts.prompt_data_revision()
        self.assertEqual(library.delete_tag({'name':' SHARED '}), {'deleted':['shared'], 'affected_count':2})
        self.assertNotEqual(old, library.detail(1)['version'])
        self.assertNotEqual(revision, prompts.prompt_data_revision())
        self.assertEqual(library.list_prompts({})['total'], 2)
        self.assertEqual(library.detail(1)['tags'], ['摄影'])
        self.assertEqual(library.detail(2)['tags'], [])
        with self.assertRaises(library.PromptNotFound):
            library.delete_tag({'name':'shared'})
        with prompts.connect_db() as conn:
            conn.execute("INSERT INTO tags(name) VALUES ('unused')")
        self.assertEqual(library.delete_tag({'name':'unused'})['affected_count'], 0)
        with prompts.connect_db() as conn:
            conn.execute("CREATE TRIGGER fail_delete_tag BEFORE DELETE ON tags BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            library.delete_tag({'name':'摄影'})
        self.assertEqual(library.detail(1)['tags'], ['摄影'])
        for payload in (None, {}, {'name':''}, {'name':False}, {'name':'shared','extra':1}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                library.delete_tag(payload)


if __name__ == '__main__':
    unittest.main()
