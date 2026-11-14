import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    TestClient = None

from nodes import prompt_nodes
from test_skill_library import payload
from nodes import skill_files


@unittest.skipUnless(TestClient, "aiohttp required")
class SkillRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from skill_test_fixture import create_app
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prompts.sqlite3"
        self.database = patch.object(prompt_nodes.database, "DEFAULT_DB", self.path)
        self.database.start()
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.database.stop()
        self.directory.cleanup()

    async def test_empty_create_duplicates_edit_conflict_and_filters(self):
        response = await self.client.get("/toolbox/skills")
        self.assertEqual((response.status, (await response.json())["total"]), (200,0))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual((await (await self.client.get("/toolbox/skills/tags")).json())["items"], [])
        self.assertEqual((await self.client.get("/toolbox/skills/1")).status, 404)
        self.assertEqual((await self.client.post("/toolbox/skills", json={})).status, 400)
        self.assertFalse(self.path.exists())
        response = await self.client.post("/toolbox/skills", json=payload())
        row = await response.json()
        self.assertEqual((response.status, row["action"]), (201,"created"))
        response = await self.client.post("/toolbox/skills", json=payload(name="Replacement"))
        current = await response.json()
        self.assertEqual((response.status,current["action"]), (201,"created"))
        self.assertNotEqual(current["id"],row["id"])
        response = await self.client.post("/toolbox/skills", json=payload(entry_type="prompt_template"))
        self.assertEqual(response.status, 201)
        values = payload(name="Edited", version=row["version"], tags="new")
        response = await self.client.patch(f'/toolbox/skills/{row["id"]}', json=values)
        saved = await response.json()
        self.assertEqual((response.status,saved["name"],saved["tags"]), (200,"Edited",["new"]))
        self.assertEqual((await self.client.patch(f'/toolbox/skills/{row["id"]}', json=values)).status, 409)
        result = await (await self.client.get("/toolbox/skills?q=Edited&entry_type=skill&tags=new")).json()
        self.assertEqual(result["total"], 1)
        self.assertEqual((await (await self.client.get(f'/toolbox/skills/{row["id"]}')).json())["content"], payload()["content"])

    async def test_http_errors(self):
        for url in ("/toolbox/skills?page=0", "/toolbox/skills?entry_type=bad", "/toolbox/skills/bad", "/toolbox/skills/tags?page_size=999"):
            self.assertEqual((await self.client.get(url)).status, 400)
        self.assertEqual((await self.client.post("/toolbox/skills", data="x")).status, 415)
        self.assertEqual((await self.client.post("/toolbox/skills", data="{", headers={"Content-Type":"application/json"})).status, 400)
        with patch('nodes.skill_files.MAX_JSON_BYTES', 2_100_000):
            response = await self.client.post("/toolbox/skills", data=io.BytesIO(b"x"*2_100_001), headers={"Content-Type":"application/json"})
            self.assertEqual(response.status, 413)
        self.assertFalse(self.path.exists())

    async def test_upload_preview_package_save_and_download(self):
        import json
        import zipfile
        from aiohttp import FormData
        from test_skill_files import zip_bytes
        original={'folder/SKILL.md':b'# Uploaded\r\n\r\n    {{raw}}\r\n','folder/assets/data.bin':b'\0\xff\x01'}
        form=FormData()
        form.add_field('paths',json.dumps(['bundle.zip']))
        form.add_field('file',zip_bytes(original.items()),filename='bundle.zip')
        response=await self.client.post('/toolbox/skills/upload',data=form)
        self.assertEqual(response.status,200)
        imported=await response.json()
        self.assertEqual(imported['primary_path'],'folder/SKILL.md')
        self.assertFalse(self.path.exists())
        response=await self.client.post('/toolbox/skills',json=payload(**imported))
        self.assertEqual(response.status,201)
        row=await response.json()
        again=await self.client.post('/toolbox/skills',json=payload(**imported))
        self.assertEqual(again.status,201)
        self.assertNotEqual((await again.json())['id'],row['id'])
        response=await self.client.get(f'/toolbox/skills/{row["id"]}/files',params={'path':'folder/assets/data.bin'})
        self.assertEqual(response.status,200)
        self.assertEqual(await response.read(),original['folder/assets/data.bin'])
        self.assertIn('attachment;',response.headers['Content-Disposition'])
        response=await self.client.get(f'/toolbox/skills/{row["id"]}/download')
        self.assertEqual(response.content_type,'application/zip')
        with zipfile.ZipFile(io.BytesIO(await response.read())) as archive:
            self.assertEqual({path:archive.read(path) for path in archive.namelist()},original)
        self.assertEqual((await self.client.get(f'/toolbox/skills/{row["id"]}/files',params={'path':'missing'})).status,404)
        self.assertEqual((await self.client.get(f'/toolbox/skills/{row["id"]}/files',params={'path':'../bad'})).status,400)
        values=payload(version=row['version'],files=[],primary_path='')
        response=await self.client.patch(f'/toolbox/skills/{row["id"]}',json=values)
        self.assertEqual((await response.json())['files'],[])
        self.assertEqual((await self.client.patch(f'/toolbox/skills/{row["id"]}',json=values)).status,409)

    async def test_upload_invalid_paths_count_and_format(self):
        import json
        from aiohttp import FormData
        self.assertEqual((await self.client.post('/toolbox/skills/upload',json={})).status,415)
        for paths in (['../bad'],['a','b'],['a','a'],['bad.zip']):
            form=FormData()
            form.add_field('paths',json.dumps(paths))
            for index in range(1 if len(paths)==1 or paths==['a','b'] else 2):
                form.add_field('file',b'raw',filename='data')
            response=await self.client.post('/toolbox/skills/upload',data=form)
            self.assertEqual(response.status,400)
        self.assertFalse(self.path.exists())

    async def test_text_only_download_includes_main_content(self):
        import zipfile
        row=await (await self.client.post('/toolbox/skills',json=payload())).json()
        response=await self.client.get(f'/toolbox/skills/{row["id"]}/download')
        with zipfile.ZipFile(io.BytesIO(await response.read())) as archive:
            self.assertEqual(archive.read('SKILL.md').decode(),payload()['content'])

    async def test_capacity_http_status_and_stats(self):
        with patch.object(skill_files,'MAX_LIBRARY_BYTES',5):
            response=await self.client.post('/toolbox/skills',json=payload(content='12345'))
            row=await response.json()
            self.assertEqual(response.status,201)
            self.assertEqual((await self.client.post('/toolbox/skills',json=payload(content='x'))).status,413)
            stats=await (await self.client.get('/toolbox/skills/storage')).json()
            self.assertEqual((stats['used_bytes'],stats['max_library_bytes']),(5,5))
            self.assertEqual((await self.client.patch(f'/toolbox/skills/{row["id"]}',json=payload(content='123456',version=row['version']))).status,413)
            self.assertEqual((await (await self.client.get(f'/toolbox/skills/{row["id"]}')).json())['content'],'12345')

    async def test_explicit_file_mode_without_body_and_reject_mixed_sources(self):
        values=payload(storage_mode='files',content='',files=[skill_files.file_item('data.bin',b'\0\xff')])
        response=await self.client.post('/toolbox/skills',json=values)
        row=await response.json()
        self.assertEqual(response.status,201)
        self.assertEqual((row['storage_mode'],row['content']),('files',''))
        self.assertEqual((await self.client.post('/toolbox/skills',json={**values,'storage_mode':'text','content':'body'})).status,400)
        self.assertEqual((await self.client.post('/toolbox/skills',json={**values,'content':'body'})).status,400)

    async def test_delete_routes_conflict_download_capacity_and_validation(self):
        row=await (await self.client.post('/toolbox/skills',json=payload())).json()
        for route in (f'/toolbox/skills/{row["id"]}','/toolbox/skills/tags'):
            self.assertEqual((await self.client.delete(route,data='x')).status,415)
            self.assertEqual((await self.client.delete(route,json={})).status,400)
            self.assertEqual((await self.client.delete(route,data='{',headers={'Content-Type':'application/json'})).status,400)
            self.assertEqual((await self.client.delete(route,data=b'x'*65537,headers={'Content-Type':'application/json'})).status,413)
        response=await self.client.delete('/toolbox/skills/tags',json={'name':'alpha'})
        self.assertEqual(response.status,200)
        self.assertEqual(await response.json(),{'deleted':['alpha'],'affected_count':1})
        self.assertEqual((await self.client.delete('/toolbox/skills/tags',json={'name':'unknown'})).status,404)
        self.assertEqual((await self.client.delete(f'/toolbox/skills/{row["id"]}',json={'version':row['version']})).status,409)
        current=await (await self.client.get(f'/toolbox/skills/{row["id"]}')).json()
        response=await self.client.delete(f'/toolbox/skills/{row["id"]}',json={'version':current['version']})
        self.assertEqual(response.status,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual((await response.json())['storage']['used_bytes'],0)
        self.assertEqual((await self.client.get(f'/toolbox/skills/{row["id"]}/download')).status,404)
        self.assertEqual((await self.client.get(f'/toolbox/skills/{row["id"]}/files?path=SKILL.md')).status,404)
        self.assertEqual((await self.client.delete('/toolbox/skills/999',json={'version':current['version']})).status,404)
        self.assertEqual((await self.client.delete('/toolbox/skills/bad',json={'version':current['version']})).status,400)


if __name__ == "__main__":
    unittest.main()
