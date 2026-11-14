import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_nodes, skill_files, skill_library as library
from nodes.skill_nodes import ToolBoxSkillReader
from test_skill_library import payload


class SkillManagementTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'prompts.sqlite3'
        database = patch.object(prompt_nodes.database, 'DEFAULT_DB', self.path)
        database.start(); self.addCleanup(database.stop)

    def package(self, **changes):
        return library.create_entry(payload(storage_mode='files',content='',primary_path='SKILL.md',
            files=[skill_files.file_item('SKILL.md', b'# Synthetic body'),
                   skill_files.file_item('assets/data.bin', b'\x00\xff')], **changes))

    def test_text_and_package_deletion_release_capacity_preserve_source_and_prompt_library(self):
        prompt_id = prompt_nodes.ToolBoxPromptWriter().write_prompt(0,'prompt sentinel','zh','image','natural',
            False,'plaintext',False,32,32,'alpha')[0]
        prompt_revision = prompt_nodes.prompt_data_revision()
        source = Path(self.directory.name) / 'original.md'; source.write_text('original source')
        text = library.create_entry(payload(entry_type='prompt_template'))
        package = self.package()
        revision = ToolBoxSkillReader.IS_CHANGED()
        result = library.delete_entry(package['id'], {'version':package['version']})
        self.assertEqual(result['deleted'], [package['id']])
        self.assertEqual(result['storage']['used_bytes'], len(text['content'].encode()))
        self.assertEqual(result['storage']['entry_count'], 1)
        self.assertNotEqual(revision, ToolBoxSkillReader.IS_CHANGED())
        with library.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM skill_files').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM skill_entry_tags WHERE entry_id=?',(package['id'],)).fetchone()[0], 0)
        self.assertEqual(source.read_text(), 'original source')
        self.assertEqual(prompt_nodes.ToolBoxPromptReader().read_prompt(prompt_id)[1], 'prompt sentinel')
        self.assertEqual(prompt_revision, prompt_nodes.prompt_data_revision())
        self.assertEqual(library.delete_entry(text['id'], {'version':text['version']})['storage']['used_bytes'], 0)
        self.assertEqual(library.list_tags({})['counts'], {'alpha':0,'beta':0})
        with self.assertRaises(library.SkillNotFound): library.detail(package['id'])
        with self.assertRaises(library.SkillNotFound): library.delete_entry(package['id'], {'version':package['version']})

    def test_file_changes_conflict_and_failed_delete_rolls_back_files_tags_and_revision(self):
        row = self.package()
        with library.connect(write=True) as conn:
            conn.execute('UPDATE skill_files SET data=? WHERE entry_id=? AND path=?',(b'changed',row['id'],'assets/data.bin'))
        with self.assertRaises(library.SkillConflict): library.delete_entry(row['id'], {'version':row['version']})
        fresh = library.detail(row['id']); revision = library.data_revision()
        with library.connect(write=True) as conn:
            conn.execute("CREATE TRIGGER fail_skill_delete BEFORE DELETE ON skill_entries BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): library.delete_entry(row['id'], {'version':fresh['version']})
        self.assertEqual(library.detail(row['id']), fresh)
        self.assertEqual(library.data_revision(), revision)

    def test_global_tag_delete_spans_both_types_preserves_files_and_prompt_tags(self):
        prompt_nodes.ToolBoxPromptWriter().write_prompt(0,'prompt sentinel','zh','image','natural',False,
            'plaintext',False,32,32,'alpha')
        first = self.package(tags='alpha')
        second = library.create_entry(payload(entry_type='prompt_template', tags='alpha,beta'))
        revision = prompt_nodes.prompt_data_revision(); usage = library.storage()
        result = library.delete_tag({'name':' ALPHA '})
        self.assertEqual(result, {'deleted':['alpha'],'affected_count':2})
        fresh = library.detail(first['id'])
        self.assertEqual(fresh['tags'], [])
        self.assertEqual(fresh['files'], first['files'])
        self.assertNotEqual(fresh['version'], first['version'])
        self.assertEqual(library.detail(second['id'])['tags'], ['beta'])
        self.assertEqual(usage, library.storage())
        self.assertEqual(prompt_nodes.prompt_data_revision(), revision)
        self.assertEqual(prompt_nodes.ToolBoxPromptReader().read_prompt(1)[1], 'prompt sentinel')
        with self.assertRaises(library.SkillConflict): library.delete_entry(first['id'], {'version':first['version']})
        with library.connect(write=True) as conn:
            conn.execute("INSERT INTO skill_tags(name) VALUES('unused')")
        self.assertEqual(library.delete_tag({'name':'unused'})['affected_count'], 0)

    def test_tag_delete_failure_rolls_back_and_notifies_only_after_commit(self):
        row = library.create_entry(payload())
        with library.connect(write=True) as conn:
            conn.execute("CREATE TRIGGER fail_skill_tag BEFORE DELETE ON skill_tags BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with patch.object(library, 'notify_changed') as notify:
            with self.assertRaises(sqlite3.IntegrityError): library.delete_tag({'name':'alpha'})
            notify.assert_not_called()
        self.assertEqual(library.detail(row['id']), {key:value for key,value in row.items() if key!='action'})
        with library.connect(write=True) as conn: conn.execute('DROP TRIGGER fail_skill_tag')
        with patch.object(library, 'notify_changed') as notify:
            library.delete_tag({'name':'alpha'})
            notify.assert_called_once_with({'deleted_tags':['alpha']})

    def test_invalid_and_missing_deletions_do_not_create_a_database(self):
        for invalid in (None,{}, {'version':3},{'version':'bad'},{'version':'a'*64,'extra':True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): library.delete_entry(1,invalid)
        for invalid in (None,{}, {'name':''},{'name':False},{'name':'x','extra':True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): library.delete_tag(invalid)
        with self.assertRaises(library.SkillNotFound): library.delete_entry(1,{'version':'a'*64})
        with self.assertRaises(library.SkillNotFound): library.delete_tag({'name':'unknown'})
        self.assertFalse(self.path.exists())


if __name__ == '__main__': unittest.main()
