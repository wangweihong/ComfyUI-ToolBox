import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_nodes, skill_library as library
from nodes.skill_nodes import ToolBoxSkillReader


def payload(**changes):
    return dict(name="Synthetic skill", entry_type="skill", description="A summary",
                content="# Heading\r\n\r\n    indented {{variable}}\r\n", tags="alpha, beta") | changes


class SkillLibraryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prompts.sqlite3"
        self.database = patch.object(prompt_nodes.database, "DEFAULT_DB", self.path)
        self.database.start()

    def tearDown(self):
        self.database.stop()
        self.directory.cleanup()

    def edit(self, row, **changes):
        values = {key: row[key] for key in library.EDITABLE_FIELDS}
        values.update(tags=", ".join(row["tags"]), version=row["version"])
        return library.save_entry(row["id"], values | changes)

    def test_empty_reads_and_invalid_saves_do_not_initialize(self):
        self.assertEqual(library.list_entries({})["total"], 0)
        self.assertEqual(library.list_tags({})["items"], [])
        with self.assertRaises(library.SkillNotFound):
            library.detail(1)
        for invalid in ({}, payload(name=" "), payload(content="\n"), payload(entry_type="other")):
            with self.assertRaises(ValueError):
                library.create_entry(invalid)
        self.assertFalse(self.path.exists())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE library_meta(key TEXT PRIMARY KEY,value TEXT)")
            conn.execute("INSERT INTO library_meta VALUES('revision','preserve')")
        before = self.path.read_bytes()
        self.assertEqual(library.list_entries({})["items"], [])
        self.assertEqual(library.list_tags({})["total"], 0)
        self.assertEqual(self.path.read_bytes(), before)
        row = library.create_entry(payload())
        self.assertEqual(row["action"], "created")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT * FROM library_meta").fetchall(), [("revision", "preserve")])

    def test_raw_markdown_node_outputs_and_cache_revision(self):
        source = " \t# Heading\r\n\r\n    keep  spaces\r\n{{variable}} <script>literal</script>\r\n "
        row = library.create_entry(payload(content=source))
        self.assertEqual(row["content"], source)
        self.assertEqual(row["shasum"], hashlib.sha1(source.strip().encode()).hexdigest())
        node = ToolBoxSkillReader()
        result = node.read_skill(row["id"])
        self.assertEqual(result[:4], (row["id"], row["name"], "skill", source))
        metadata = json.loads(result[4])
        for key in ("description", "tags", "created_at", "updated_at", "shasum"):
            self.assertEqual(metadata[key], row[key])
        self.assertNotIn("content", metadata)
        revision = node.IS_CHANGED(id=row["id"])
        updated = self.edit(row, name="Changed", tags="new")
        self.assertNotEqual(node.IS_CHANGED(id=row["id"]), revision)
        self.assertEqual(updated["content"], source)
        self.assertEqual(node.RETURN_NAMES, ("id", "name", "entry_type", "content", "metadata"))
        self.assertEqual(list(node.INPUT_TYPES()["required"]), ["id"])

    def test_duplicate_content_always_creates_and_edits_target_only(self):
        first = library.create_entry(payload(content=" body "))
        duplicate = library.create_entry(payload(content="body", name="Replaced", tags="gamma"))
        self.assertEqual(duplicate["action"], "created")
        self.assertNotEqual(duplicate["id"], first["id"])
        self.assertEqual(duplicate["tags"], ["gamma"])
        template = library.create_entry(payload(content="body", entry_type="prompt_template"))
        self.assertNotEqual(template["id"], first["id"])
        third = library.create_entry(payload(content="different"))
        third = self.edit(third, content="body")
        self.assertEqual(library.list_entries({})["total"], 4)
        updated = library.create_entry(payload(content="\nbody\t", name="Lowest"))
        self.assertEqual(updated["action"], "created")
        self.assertEqual(library.list_entries({})["total"], 5)
        self.assertEqual(library.detail(first["id"])["content"], " body ")
        self.assertEqual(library.detail(third["id"])["name"], third["name"])
        self.assertEqual(library.detail(template["id"])["name"], template["name"])

    def test_conflicts_include_tag_only_changes_and_preserve_data(self):
        row = library.create_entry(payload())
        current = self.edit(row, description="Changed", tags="new")
        with self.assertRaises(library.SkillConflict):
            self.edit(row, content="stale")
        self.assertEqual(library.detail(row["id"]), {key:value for key,value in current.items() if key != "action"})
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM skill_entry_tags WHERE entry_id=?", (row["id"],))
        with self.assertRaises(library.SkillConflict):
            self.edit(current, name="stale tags")
        self.assertEqual(library.detail(row["id"])["tags"], [])

    def test_search_type_tag_intersection_and_pagination(self):
        library.create_entry(payload(name="Name needle", content="one", tags="alpha,beta"))
        library.create_entry(payload(name="two", description="Summary needle", content="two", tags="alpha"))
        library.create_entry(payload(name="three", content="Body needle 100%", tags="alpha,beta", entry_type="prompt_template"))
        self.assertEqual(library.list_entries({"q":"NEEDLE"})["total"], 3)
        self.assertEqual(library.list_entries({"q":"%"})["total"], 1)
        self.assertEqual(library.list_entries({"tags":"ALPHA,beta"})["total"], 2)
        self.assertEqual(library.list_entries({"tags":"alpha,beta", "entry_type":"skill"})["total"], 1)
        self.assertEqual(library.list_entries({"tags":"missing"})["items"], [])
        first = library.list_entries({"page_size":"2"})
        second = library.list_entries({"page_size":"2", "page":"2"})
        self.assertEqual([r["id"] for r in first["items"] + second["items"]], [3,2,1])
        self.assertNotIn("content", first["items"][0])
        tags = library.list_tags({"page_size":"1"})
        self.assertTrue(tags["has_more"])
        self.assertEqual(tags["counts"], {"alpha":3})
        self.assertEqual(library.list_tags({"page":"2","page_size":"1"})["items"], ["beta"])

    def test_prompt_tables_and_tags_remain_untouched(self):
        prompt_nodes.ToolBoxPromptWriter().write_prompt(0, "Synthetic prompt", "zh", "image", "natural", False,
                                                       "plaintext", False, 1024, 768, "prompt-only")
        def snapshot():
            with closing(sqlite3.connect(self.path)) as conn, conn:
                return [conn.execute(f"SELECT * FROM {table}").fetchall() for table in ("prompts", "tags", "prompt_tags")]
        before = snapshot()
        row = library.create_entry(payload(tags="skill-only"))
        self.edit(row, tags="replacement")
        self.assertEqual(snapshot(), before)
        self.assertNotIn("prompt-only", library.list_tags({})["items"])
        self.assertEqual(library.detail(row["id"])["tags"], ["replacement"])

    def test_validation_and_missing_ids(self):
        for query in ({"page":"0"}, {"page_size":"101"}, {"entry_type":"other"}, {"unexpected":"x"}):
            with self.assertRaises(ValueError):
                library.list_entries(query)
        for query in ({"page_size":"501"}, {"unknown":"x"}):
            with self.assertRaises(ValueError):
                library.list_tags(query)
        row = library.create_entry(payload())
        with self.assertRaises(library.SkillNotFound):
            library.save_entry(999, payload(version=row["version"]))
        with self.assertRaises(ValueError):
            library.save_entry(row["id"], payload())
        with self.assertRaises(ValueError):
            library.detail("1 OR 1=1")


if __name__ == "__main__":
    unittest.main()
