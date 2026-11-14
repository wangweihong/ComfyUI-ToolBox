import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    TestClient = None

from nodes import prompt_library as library, prompt_nodes as prompts


@unittest.skipUnless(TestClient, "aiohttp is required for API integration tests")
class PromptRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from prompt_test_fixture import create_app
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prompts.sqlite3"
        self.database = patch.object(prompts.database, "DEFAULT_DB", self.path)
        self.database.start()
        prompts.ToolBoxPromptWriter().write_prompt(0, "synthetic", "zh", "image", "natural", False,
                                                   "plaintext", False, 1024, 768, "night")
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.database.stop()
        self.directory.cleanup()

    async def test_list_tags_detail_and_edit(self):
        response = await self.client.get("/toolbox/prompts?sensitivity_level=L2&tags=night")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual((await response.json())["total"], 1)
        self.assertEqual((await (await self.client.get("/toolbox/prompts/tags?q=night")).json())["items"], ["night"])
        row = await (await self.client.get("/toolbox/prompts/1")).json()
        payload = {key: row[key] for key in library.WRITE_NAMES}
        payload.update(tags="new, night", version=row["version"], prompt="saved", gore=True, sensitivity_level=4)
        saved = await self.client.patch("/toolbox/prompts/1", json=payload)
        self.assertEqual(saved.status, 200)
        self.assertEqual((await saved.json())["prompt"], "saved")
        self.assertEqual((await self.client.patch("/toolbox/prompts/1", json=payload)).status, 409)
        self.assertEqual(library.detail(1)["tags"], ["new", "night"])

    async def test_invalid_http_requests_and_missing_database(self):
        for url, status in (("/toolbox/prompts/999", 404), ("/toolbox/prompts/bad", 400),
                            ("/toolbox/prompts?page_size=999", 400), ("/toolbox/prompts?gore=bad", 400)):
            response = await self.client.get(url)
            self.assertEqual(response.status, status)
            self.assertIn("error", await response.json())
        self.assertEqual((await self.client.patch("/toolbox/prompts/1", data="x")).status, 415)
        self.assertEqual((await self.client.patch("/toolbox/prompts/1", data="{", headers={"Content-Type": "application/json"})).status, 400)
        self.assertEqual((await self.client.patch("/toolbox/prompts/1", json={})).status, 400)
        response = await self.client.patch("/toolbox/prompts/1", data=io.BytesIO(b"x" * 2_100_001),
                                           headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 413)
        with patch.object(prompts.database, "DEFAULT_DB", self.path.parent / "missing.sqlite3"):
            response=await self.client.get('/toolbox/prompts/tags')
            self.assertEqual(response.status,200)
            self.assertEqual((await response.json())['items'],[])
            self.assertEqual((await self.client.get("/toolbox/prompts")).status, 400)
            self.assertFalse(prompts.database.DEFAULT_DB.exists())

    async def test_exact_level_api_and_tag_catalog_metadata(self):
        prompts.ToolBoxPromptWriter().write_prompt(0, "synthetic higher level", "zh", "image", "natural", False,
                                                   "plaintext", False, 1024, 768, "night", sensitivity_level=3)
        response = await self.client.get("/toolbox/prompts?sensitivity_mode=exact&sensitivity_levels=L1,L3&sensitivity_level=L0")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["sensitivity_level"], 3)
        tags = await (await self.client.get("/toolbox/prompts/tags?page_size=500")).json()
        self.assertEqual(tags["counts"], {"night": 2})
        self.assertEqual(tags["total"], 1)
        self.assertFalse(tags["has_more"])
        self.assertEqual((await self.client.get("/toolbox/prompts?sensitivity_mode=exact&sensitivity_levels=L9")).status, 400)

    async def test_list_update_sort_and_invalid_sort(self):
        prompts.ToolBoxPromptWriter().write_prompt(0, "new synthetic", "zh", "image", "natural", False,
                                                   "plaintext", False, 1024, 768, "night")
        original = library.detail(1)
        payload = {key: original[key] for key in library.WRITE_NAMES}
        payload.update(version=original["version"], tags="night, updated")
        self.assertEqual((await self.client.patch("/toolbox/prompts/1",json=payload)).status,200)
        latest = await (await self.client.get("/toolbox/prompts?sort=updated_desc&page_size=1")).json()
        self.assertEqual(latest["items"][0]["id"], 1)
        self.assertIn("updated_at",latest["items"][0])
        earliest = await (await self.client.get("/toolbox/prompts?sort=updated_asc&page_size=1")).json()
        self.assertEqual(earliest["items"][0]["id"], 2)
        self.assertEqual((await self.client.get("/toolbox/prompts?sort=bad")).status,400)

    async def test_create_then_duplicate_update_returns_distinct_notices(self):
        original = library.detail(1)
        payload = {key: original[key] for key in library.WRITE_NAMES}
        payload.update(prompt="new synthetic prompt", tags="new-tag", width=864, height=1536)
        response = await self.client.post("/toolbox/prompts", json=payload)
        self.assertEqual(response.status, 201)
        created = await response.json()
        self.assertEqual(created["action"], "created")
        self.assertNotEqual(created["id"], 1)
        response = await self.client.post("/toolbox/prompts", json={**payload, "tags": "replaced", "sensitivity_level": 2})
        self.assertEqual(response.status, 200)
        updated = await response.json()
        self.assertEqual(updated["action"], "updated")
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["tags"], ["replaced"])
        self.assertEqual(library.list_prompts({})["total"], 2)
        self.assertEqual(library.detail(1)["prompt"], "synthetic")
        self.assertEqual((await self.client.post("/toolbox/prompts", json={**payload, "prompt": " "})).status, 400)
        self.assertEqual((await self.client.post("/toolbox/prompts", data="x")).status, 415)

    async def test_delete_prompt_and_tag_routes_validate_and_report_conflicts(self):
        row = library.detail(1)
        for path in ('/toolbox/prompts/1', '/toolbox/prompts/tags'):
            self.assertEqual((await self.client.delete(path, data='x')).status, 415)
            self.assertEqual((await self.client.delete(path, json={})).status, 400)
            self.assertEqual((await self.client.delete(path, data='{', headers={'Content-Type':'application/json'})).status, 400)
            self.assertEqual((await self.client.delete(path, data=b'x' * 16385, headers={'Content-Type':'application/json'})).status, 413)
        deleted = await self.client.delete('/toolbox/prompts/tags', json={'name':'night'})
        self.assertEqual(deleted.status, 200)
        self.assertEqual(await deleted.json(), {'deleted':['night'], 'affected_count':1})
        self.assertEqual((await self.client.delete('/toolbox/prompts/tags', json={'name':'night'})).status, 404)
        self.assertEqual((await self.client.delete('/toolbox/prompts/1', json={'version':row['version']})).status, 409)
        fresh = library.detail(1)
        self.assertEqual(fresh['tags'], [])
        response = await self.client.delete('/toolbox/prompts/1', json={'version':fresh['version']})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(await response.json(), {'deleted':[1]})
        self.assertEqual((await self.client.get('/toolbox/prompts/1')).status, 404)
        self.assertEqual((await self.client.delete('/toolbox/prompts/1', json={'version':fresh['version']})).status, 404)
        self.assertEqual((await self.client.delete('/toolbox/prompts/bad', json={'version':fresh['version']})).status, 400)
        with patch.object(library, 'delete_tag', side_effect=OSError('unavailable')):
            self.assertEqual((await self.client.delete('/toolbox/prompts/tags', json={'name':'x'})).status, 503)


if __name__ == "__main__":
    unittest.main()
