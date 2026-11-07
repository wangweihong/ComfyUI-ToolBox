import base64
import hashlib
import io
import json
import sqlite3
import stat
import unittest
import zipfile
from contextlib import closing
from unittest.mock import patch

from nodes import skill_files as files, skill_library as library
from nodes.skill_nodes import ToolBoxSkillReader
import test_skill_library as base
payload = base.payload


def package(**changes):
    return payload(content="# Main\r\n\r\n    {{raw}}\r\n", files=[
        files.file_item("example/SKILL.md", b"# Main\r\n\r\n    {{raw}}\r\n"),
        files.file_item("example/scripts/main.py", b"print('not executed')\n"),
        files.file_item("example/assets/icon.bin", b"\x00\xff\x01\x02"),
    ], primary_path="example/SKILL.md") | changes


def zip_bytes(items):
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,data in items:
            archive.writestr(name,data)
    return output.getvalue()


class SkillFilesTest(unittest.TestCase):
    setUp = base.SkillLibraryTest.setUp
    tearDown = base.SkillLibraryTest.tearDown
    edit = base.SkillLibraryTest.edit

    def test_package_raw_bytes_manifest_and_duplicate_creation(self):
        values=package()
        row=library.create_entry(values)
        duplicate=library.create_entry(values)
        self.assertNotEqual(row["id"],duplicate["id"])
        self.assertEqual(duplicate["action"],"created")
        self.assertEqual(row["files"], sorted(values["files"],key=lambda item:item["path"]))
        self.assertEqual(row["primary_path"],values["primary_path"])
        self.assertEqual(library.list_entries({})["items"][0]["file_count"],3)
        result=ToolBoxSkillReader().read_skill(row["id"])
        self.assertEqual(result[3],values["content"])
        metadata=json.loads(result[4])
        self.assertEqual(len(metadata["files"]),3)
        self.assertNotIn("data", metadata["files"][0])
        self.assertTrue(metadata["download_url"].endswith(f'/{row["id"]}/download'))
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT data FROM skill_files WHERE entry_id=? AND path=?",(row["id"],"example/assets/icon.bin")).fetchone()[0],b"\x00\xff\x01\x02")

    def test_main_sync_attachment_preservation_and_conflict(self):
        row=library.create_entry(package())
        current=self.edit(row,name="Renamed without files payload")
        self.assertEqual(current["files"],row["files"])
        edited=self.edit(current,content="# Edited\r\n")
        main=next(item for item in edited["files"] if item["path"]==edited["primary_path"])
        self.assertEqual(base64.b64decode(main["data"]),b"# Edited\r\n")
        self.assertNotEqual(current["bundle_shasum"],edited["bundle_shasum"])
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE skill_files SET data=? WHERE entry_id=? AND path=?",(b"external",row["id"],"example/scripts/main.py"))
        with self.assertRaises(library.SkillConflict):
            self.edit(edited,name="Stale")
        latest=library.detail(row["id"])
        removed=self.edit(latest,files=[],primary_path="")
        self.assertEqual(removed["files"],[])
        self.assertEqual(removed["content"],"# Edited\r\n")

    def test_zip_and_directory_roundtrip(self):
        items=[("nested/SKILL.md", b"\xef\xbb\xbf# Raw\r\n"),("nested/scripts/run.py",b"    raw\n"),("nested/assets/data.bin",b"\0\xff")]
        for uploads in ([('bundle.zip',zip_bytes(items))],items):
            imported=files.import_uploads(uploads)
            self.assertEqual(imported["primary_path"],"nested/SKILL.md")
            self.assertEqual(imported["content"],"\ufeff# Raw\r\n")
            with zipfile.ZipFile(io.BytesIO(files.archive_bytes(imported["files"]))) as archive:
                self.assertEqual({name:archive.read(name) for name in archive.namelist()},dict(items))

    def test_invalid_paths_duplicates_symlinks_and_zip_limits(self):
        for path in ("../outside", "/absolute", "C:/file", "folder\\file", "a/./b", "a//b", "a\nfile"):
            with self.assertRaises(ValueError):
                files.import_uploads([(path,b"data")])
        for items in ([('a',b'x'),('a',b'y')], [('a',b'x'),('a/b',b'y')]):
            with self.assertRaises(ValueError):
                files.import_uploads(items)
        with self.assertRaises(ValueError):
            files.import_uploads([('bad.zip',b'not zip')])
        link=zipfile.ZipInfo("link");link.create_system=3;link.external_attr=(stat.S_IFLNK|0o777)<<16
        with self.assertRaises(ValueError):
            files.import_uploads([('link.zip',zip_bytes([(link,b'target')]))])
        with self.assertRaises(ValueError):
            files.import_uploads([('bad.zip',zip_bytes([('../outside',b'x')]))])
        with patch.object(files,'MAX_FILE_BYTES',4):
            with self.assertRaises(ValueError):
                files.import_uploads([('big.zip',zip_bytes([('a',b'12345')]))])
        with patch.object(files,'MAX_TOTAL_BYTES',5):
            with self.assertRaises(ValueError):
                files.import_uploads([('big.zip',zip_bytes([('a',b'123'),('b',b'456')]))])
        self.assertFalse(self.path.exists())

    def test_invalid_package_saves_do_not_initialize(self):
        for changes in ({'files':[{'path':'../x','data':'eA=='}]}, {'files':[{'path':'x','data':'!'}]},
                        {'files':[], 'primary_path':'missing.md'}, {'primary_path':'missing.md'}, {'primary_path':False}):
            with self.assertRaises(ValueError):
                library.create_entry(payload(**changes))
            self.assertFalse(self.path.exists())

    def test_old_skill_schema_reads_without_migration_then_edit_adds_files(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.executescript("""CREATE TABLE skill_entries(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,
                entry_type TEXT NOT NULL,description TEXT NOT NULL,content TEXT NOT NULL,shasum TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE skill_tags(id INTEGER PRIMARY KEY,name TEXT UNIQUE);
                CREATE TABLE skill_entry_tags(entry_id INTEGER,tag_id INTEGER,PRIMARY KEY(entry_id,tag_id));
                CREATE TABLE library_meta(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO library_meta VALUES('revision','unchanged');
                INSERT INTO skill_tags VALUES(1,'existing');
                INSERT INTO skill_entry_tags VALUES(9,1);""")
            conn.execute("INSERT INTO skill_entries VALUES(9,?,?,?,?,?,?,?)",('Old','skill','Summary','  raw\r\n',hashlib.sha1(b'raw').hexdigest(),'before','before'))
        before=self.path.read_bytes()
        old=library.detail(9)
        self.assertEqual(old['files'],[])
        self.assertEqual(library.list_entries({})['items'][0]['file_count'],0)
        self.assertEqual(self.path.read_bytes(),before)
        updated=self.edit(old,files=package()['files'])
        self.assertEqual(updated['id'],9)
        self.assertEqual(updated['content'],'  raw\r\n')
        self.assertEqual(updated['tags'],['existing'])
        self.assertEqual(updated['created_at'],'before')
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM library_meta').fetchall(),[('revision','unchanged')])

    def test_capacity_counts_utf8_and_files_and_allows_replacing_existing(self):
        self.assertEqual(library.storage()['used_bytes'],0)
        self.assertFalse(self.path.exists())
        row=library.create_entry(payload(content='中中',files=[files.file_item('data.bin',b'1234')]))
        self.assertEqual(library.storage()['used_bytes'],10)
        with patch.object(files,'MAX_LIBRARY_BYTES',15):
            with self.assertRaises(files.SkillCapacityError):
                library.create_entry(payload(content='123456'))
            self.assertEqual(library.list_entries({})['total'],1)
            updated=self.edit(row,content='中')
            self.assertEqual(library.storage()['used_bytes'],7)
            library.create_entry(payload(content='12345678'))
            self.assertEqual(library.storage()['used_bytes'],15)
            with self.assertRaises(files.SkillCapacityError):
                self.edit(updated,content='中中')
            self.assertEqual(library.detail(row['id'])['content'],'中')
        with patch.object(files,'MAX_TOTAL_BYTES',5):
            with self.assertRaises(files.SkillCapacityError):
                library.create_entry(payload(content='abc',files=[files.file_item('x',b'123')]))

    def test_concurrent_saves_cannot_exceed_library_capacity(self):
        from concurrent.futures import ThreadPoolExecutor
        def save(_index):
            try:
                return library.create_entry(payload(content='1234567'))['id']
            except files.SkillCapacityError:
                return None
        with patch.object(files,'MAX_LIBRARY_BYTES',10),ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(save,range(2)))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(library.storage()['used_bytes'],7)

    def test_explicit_modes_are_exclusive_and_files_can_have_no_text(self):
        invalids=[payload(storage_mode='text',files=package()['files']),
                  payload(storage_mode='files',files=[]),payload(storage_mode='text',content=''),
                  payload(storage_mode='files',files=[files.file_item('data.bin',b'\0\xff')]),
                  payload(storage_mode='files',content='different',files=[files.file_item('SKILL.md',b'body')],primary_path='SKILL.md')]
        for values in invalids:
            with self.assertRaises(ValueError):
                library.create_entry(values)
            self.assertFalse(self.path.exists())
        row=library.create_entry(payload(storage_mode='files',content='',files=[files.file_item('data.bin',b'\0\xff')]))
        self.assertEqual((row['storage_mode'],row['content'],row['primary_path']),('files','',''))
        result=ToolBoxSkillReader().read_skill(row['id'])
        self.assertEqual(result[3],'')
        converted=self.edit(row,storage_mode='text',files=[],primary_path='',content='Text mode')
        self.assertEqual((converted['storage_mode'],converted['files'],converted['content']),('text',[],'Text mode'))

    def test_file_output_is_derived_and_capacity_does_not_double_count(self):
        with patch.object(files,'MAX_TOTAL_BYTES',4),patch.object(files,'MAX_LIBRARY_BYTES',4):
            row=library.create_entry(payload(storage_mode='files',content='',files=[files.file_item('SKILL.md',b'main')],primary_path='SKILL.md'))
            self.assertEqual(row['content'],'main')
            self.assertEqual(library.storage()['used_bytes'],4)
            updated=self.edit(row,storage_mode='files',content='',files=[files.file_item('SKILL.md',b'edit')])
            self.assertEqual(updated['content'],'edit')
            with self.assertRaises(ValueError):
                self.edit(updated,storage_mode='files',content='independent')
            self.assertEqual(library.detail(row['id'])['content'],'edit')


if __name__ == '__main__':
    unittest.main()
