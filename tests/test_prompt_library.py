import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_library as library, prompt_nodes as prompts
from scripts import import_prompts, migrate_prompt_annotations, migrate_prompt_shasum
from test_prompt_writer import create_old_schema


class PromptLibraryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "prompts.sqlite3"
        self.database = patch.object(prompts, "DEFAULT_PROMPT_DB", self.path)
        self.database.start()

    def tearDown(self):
        self.database.stop()
        self.directory.cleanup()

    def write(self, text="synthetic test", prompt_id=0, **changes):
        values = dict(language="zh", media_type="image", prompt_type="natural", nsfw=False,
                      content_format="plaintext", dynamic=False, width=1024, height=768, tags="")
        values.update(changes)
        return prompts.ToolBoxPromptWriter().write_prompt(prompt_id, text, **values)

    def random(self, **changes):
        values = dict(seed=0, language="全部", media_type="全部", prompt_type="全部", safety="全部",
                      content_format="全部", dynamic="全部", match_size=False, width=1024, height=768, tags="")
        values.update(changes)
        return prompts.ToolBoxRandomPrompt().random_prompt(**values)

    def payload(self, prompt_id):
        row = library.detail(prompt_id)
        result = {key: row[key] for key in library.WRITE_NAMES}
        result["tags"] = ", ".join(result["tags"])
        result["version"] = row["version"]
        return result

    def test_annotations_are_independent_and_old_writer_preserves_them(self):
        prompt_id, _, metadata = self.write(sensitivity_level="L4", minor=False, nsfw=False,
                                           extreme=True, horror=True, gore=True)
        self.assertEqual(json.loads(metadata)["sensitivity_level"], 4)
        self.assertFalse(json.loads(metadata)["minor"])
        self.write(prompt_id=prompt_id)
        data = library.detail(prompt_id)
        self.assertEqual(data["sensitivity_level"], 4)
        self.assertTrue(all(data[key] for key in ("extreme", "horror", "gore")))
        self.assertFalse(data["nsfw"])
        self.assertEqual(library.detail(self.write("new default")[0])["sensitivity_level"], 0)

    def test_reader_output_order_and_missing_id(self):
        prompt_id = self.write("reader", width=900, height=1200, sensitivity_level=2)[0]
        result = prompts.ToolBoxPromptReader().read_prompt(prompt_id)
        self.assertEqual(result[:4], (prompt_id, "reader", 900, 1200))
        self.assertEqual(json.loads(result[4])["sensitivity_level"], 2)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            prompts.ToolBoxPromptReader().read_prompt(999)

    def test_upper_levels_and_all_five_categories(self):
        ids = [self.write(f"synthetic {level}", sensitivity_level=level,
                          **{key: level % 2 == 1 for key in prompts.CATEGORY_FIELDS})[0]
               for level in range(5)]
        self.assertEqual(library.list_prompts({"sensitivity_level": "L2"})["total"], 3)
        self.assertEqual(library.list_prompts({"sensitivity_level": "L0"})["total"], 1)
        self.assertEqual(library.list_prompts({})["total"], 5)
        self.assertEqual(self.random(seed=2, sensitivity_level="L2")[0], ids[2])
        self.assertEqual(self.random(seed=2**64 - 1)[0], ids[(2**64 - 1) % 5])
        for key in prompts.CATEGORY_FIELDS:
            for choice, count in (("是", 2), ("否", 3), ("全部", 5)):
                self.assertEqual(library.list_prompts({key: choice})["total"], count)
                self.assertEqual(self.random(**{key: choice}), self.random(**{key: choice}))
        with self.assertRaisesRegex(ValueError, "No prompts match"):
            self.random(sensitivity_level="L0", gore="是")
        self.assertEqual(library.list_prompts({"sensitivity_level": "L0", "gore": "是"})["items"], [])

    def test_exact_levels_and_maximum_are_separate_modes(self):
        ids = [self.write(f"level {level}", sensitivity_level=level)[0] for level in range(5)]
        exact = dict(sensitivity_mode="exact", sensitivity_levels="L1,L3,L1", sensitivity_level="L0")
        rows = library.list_prompts(exact)["items"]
        self.assertEqual({row["sensitivity_level"] for row in rows}, {1, 3})
        self.assertEqual(self.random(**exact, seed=0)[0], ids[1])
        self.assertEqual(self.random(**exact, seed=1)[0], ids[3])
        self.assertEqual(self.random(**exact, seed=2)[0], ids[1])
        self.assertEqual(library.list_prompts({"sensitivity_mode": "max", "sensitivity_level": "L2",
                                             "sensitivity_levels": "L4"})["total"], 3)
        self.assertEqual(library.list_prompts({"sensitivity_mode": "exact", "sensitivity_levels": "0, 2，4"})["total"], 3)
        self.assertEqual(library.list_prompts({"sensitivity_mode": "exact", "sensitivity_levels": ""})["total"], 0)
        with self.assertRaisesRegex(ValueError, "No prompts match"):
            self.random(sensitivity_mode="exact", sensitivity_levels="")
        for query in ({"sensitivity_mode": "bad"}, {"sensitivity_mode": "exact", "sensitivity_levels": "L5"},
                      {"sensitivity_mode": "exact", "sensitivity_levels": "1 OR 1=1"}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                library.list_prompts(query)

    def test_all_tag_pages_counts_and_mixed_case_matching(self):
        first = self.write("first", tags="landscape")[0]
        self.write("second", tags="landscape,night")
        with sqlite3.connect(self.path) as conn:
            prompts.insert_tags(conn, first, ["3d"])
            conn.execute("UPDATE tags SET name='3D' WHERE name='3d'")
            conn.executemany("INSERT INTO tags(name) VALUES (?)", ((f"unused-{i:03}",) for i in range(520)))
        first_page = library.list_tags({"page_size": "500"})
        second_page = library.list_tags({"page": "2", "page_size": "500"})
        self.assertTrue(first_page["has_more"])
        self.assertFalse(second_page["has_more"])
        self.assertEqual(first_page["total"], 523)
        self.assertEqual(len(first_page["items"]) + len(second_page["items"]), 523)
        self.assertEqual(first_page["counts"]["landscape"], 2)
        self.assertEqual(first_page["counts"]["unused-000"], 0)
        self.assertEqual(library.list_tags({"q": "3d"})["items"], ["3D"])
        self.assertEqual(library.list_prompts({"tags": "3D, landscape"})["total"], 1)
        self.assertEqual(self.random(tags="3D, landscape")[0], first)

    def test_search_tags_size_and_paging_match_random(self):
        self.write("first 100%_LITERAL", tags="Portrait,Night,night", width=900, height=1200,
                   language="en", media_type="video", prompt_type="danbooru", dynamic=True)
        self.write("second 100XXLITERAL", tags="portrait")
        self.assertEqual(library.list_prompts({"q": "%_literal"})["total"], 1)
        query = dict(tags="Portrait, NIGHT", match_size="true", width="900", height="1200",
                     language="en", media_type="video", prompt_type="danbooru", dynamic="dynamic")
        row = library.list_prompts(query)["items"][0]
        self.assertEqual(row["id"], self.random(**{**query, "match_size": True})[0])
        self.assertEqual(row["tags"], ["night", "portrait"])
        self.assertEqual(library.list_tags({"q": "NIGHT"})["items"], ["night"])
        self.assertEqual(library.list_prompts({"page": "2", "page_size": "1"})["items"][0]["id"], row["id"])
        self.assertEqual(library.list_prompts({"q": "' OR 1=1 --"})["total"], 0)

    def test_save_detects_stale_body_and_stale_tags_without_overwrite(self):
        prompt_id = self.write(tags="old")[0]
        stale = self.payload(prompt_id)
        fresh = library.save_prompt(prompt_id, {**stale, "prompt": "new", "sensitivity_level": 4, "minor": True})
        self.assertNotEqual(stale["version"], fresh["version"])
        with self.assertRaises(prompts.PromptConflict):
            library.save_prompt(prompt_id, {**stale, "prompt": "lost update"})
        self.assertEqual(library.detail(prompt_id)["prompt"], "new")
        stale = self.payload(prompt_id)
        with sqlite3.connect(self.path) as conn:
            prompts.insert_tags(conn, prompt_id, ["external-edit"])
        with self.assertRaises(prompts.PromptConflict):
            library.save_prompt(prompt_id, stale)
        self.assertIn("external-edit", library.detail(prompt_id)["tags"])

    def test_create_upserts_lowest_shasum_id_and_reports_action(self):
        first = self.write("same", tags="old", sensitivity_level=3)[0]
        other = self.write("other", tags="other")[0]
        self.write("same", prompt_id=other, tags="other")
        payload = self.payload(first)
        payload.pop("version")
        payload.update(prompt="  same  ", tags="new", sensitivity_level=2)
        result = library.create_prompt(payload)
        self.assertEqual(result["id"], first)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["tags"], ["new"])
        self.assertEqual(result["sensitivity_level"], 2)
        self.assertEqual(library.detail(other)["tags"], ["other"])
        self.assertEqual(library.list_prompts({})["total"], 2)
        created = library.create_prompt({**payload, "prompt": "brand new"})
        self.assertEqual(created["action"], "created")
        self.assertGreater(created["id"], other)
        self.assertEqual(library.list_prompts({})["total"], 3)

    def test_create_validates_without_writing_and_can_initialize_new_database(self):
        existing = self.write()[0]
        payload = self.payload(existing)
        payload.pop("version")
        for changes in ({"prompt": " "}, {"minor": "true"}, {"width": 0}, {"id": 1}, {"version": "x"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                library.create_prompt({**payload, **changes})
        self.assertEqual(library.list_prompts({})["total"], 1)
        with patch.object(prompts, "DEFAULT_PROMPT_DB", self.path.with_name("fresh.sqlite3")):
            result = library.create_prompt(payload)
            self.assertEqual(result["id"], 1)
            self.assertEqual(result["action"], "created")

    def test_invalid_inputs_do_not_write(self):
        prompt_id = self.write()[0]
        data = self.payload(prompt_id)
        for changes in ({"sensitivity_level": 5}, {"gore": "false"}, {"width": 0},
                        {"height": 16385}, {"language": "xx"}, {"prompt": " "}, {"version": "wrong"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                library.save_prompt(prompt_id, {**data, **changes})
        self.assertEqual(self.payload(prompt_id), data)
        for query in ({"page": "0"}, {"page_size": "101"}, {"nsfw": "invalid"},
                      {"sensitivity_level": "L5"}, {"unknown": "x"}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                library.list_prompts(query)

    def test_revision_changes_after_writer_and_wal_edit(self):
        prompt_id = self.write()[0]
        old = prompts.ToolBoxPromptReader.IS_CHANGED(id=prompt_id)
        self.write("changed", prompt_id=prompt_id)
        self.assertNotEqual(old, prompts.ToolBoxRandomPrompt.IS_CHANGED(seed=0))
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            old = prompts.database_revision()
            conn.execute("UPDATE prompts SET gore=1")
            conn.commit()
            self.assertNotEqual(old, prompts.database_revision())

    def test_annotation_migration_backs_up_and_preserves_data(self):
        with sqlite3.connect(self.path) as conn:
            create_old_schema(conn)
            conn.execute("INSERT INTO prompts VALUES (7,'hash','legacy','zh','image','natural',1,'plaintext',0,900,1200,'old')")
            conn.execute("INSERT INTO tags VALUES (1,'kept')")
            conn.execute("INSERT INTO prompt_tags VALUES (7,1)")
            before = conn.execute("SELECT * FROM prompts").fetchall()
        result = migrate_prompt_annotations.migrate_db(self.path)
        self.assertEqual(set(result["added_columns"]), set(prompts.ANNOTATION_DEFAULTS))
        with sqlite3.connect(result["backup"]) as conn:
            self.assertEqual(conn.execute("SELECT * FROM prompts").fetchall(), before)
        self.assertEqual(library.detail(7)["sensitivity_level"], 0)
        self.assertEqual(library.detail(7)["tags"], ["kept"])
        self.assertEqual(migrate_prompt_annotations.migrate_db(self.path), {"added_columns": [], "backup": None})
        migrate_prompt_shasum.migrate_db(self.path, output=lambda _: None)
        self.assertEqual(library.detail(7)["tags"], ["kept"])

    def test_sha_rebuild_keeps_annotations_extra_columns_and_sequence(self):
        with sqlite3.connect(self.path) as conn:
            create_old_schema(conn)
            prompts.add_missing_annotations(conn)
            conn.execute("ALTER TABLE prompts ADD COLUMN custom_note TEXT DEFAULT 'kept'")
            conn.execute("INSERT INTO prompts (id,shasum,prompt,language,media_type,prompt_type,nsfw,content_format,dynamic,created_at,sensitivity_level,extreme,gore,horror,minor) VALUES (12,'hash','synthetic','en','image','natural',0,'plaintext',0,'old',4,1,1,1,1)")
            conn.execute("INSERT INTO tags VALUES (1,'kept')")
            conn.execute("INSERT INTO prompt_tags VALUES (12,1)")
            conn.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='prompts'")
        migrate_prompt_shasum.migrate_db(self.path, output=lambda _: None)
        data = library.detail(12)
        self.assertEqual(data["sensitivity_level"], 4)
        self.assertTrue(all(data[key] for key in ("extreme", "gore", "horror", "minor")))
        self.assertEqual(data["tags"], ["kept"])
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT custom_note FROM prompts").fetchone()[0], "kept")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.write("after migration")[0], 101)

    def test_partial_migration_keeps_manual_level_and_existing_flags(self):
        with sqlite3.connect(self.path) as conn:
            create_old_schema(conn)
            conn.execute("ALTER TABLE prompts ADD COLUMN sensitivity_level INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE prompts ADD COLUMN extreme INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT INTO prompts (id,shasum,prompt,language,media_type,prompt_type,nsfw,content_format,dynamic,created_at,sensitivity_level,extreme) VALUES (1,'hash','synthetic','zh','image','natural',0,'plaintext',0,'old',4,1)")
        result = migrate_prompt_annotations.migrate_db(self.path)
        self.assertEqual(set(result["added_columns"]), {"horror", "gore", "minor"})
        data = library.detail(1)
        self.assertEqual(data["sensitivity_level"], 4)
        self.assertTrue(data["extreme"])
        self.assertFalse(data["gore"])

    def test_old_widget_order_and_outputs_are_unchanged(self):
        self.assertEqual(list(prompts.ToolBoxPromptWriter.INPUT_TYPES()["required"]),
                         ["id", "prompt", "language", "media_type", "prompt_type", "nsfw", "content_format", "dynamic", "width", "height", "tags"])
        self.assertEqual(list(prompts.ToolBoxRandomPrompt.INPUT_TYPES()["required"]),
                         ["seed", "language", "media_type", "prompt_type", "safety", "content_format", "dynamic", "match_size", "width", "height", "tags"])
        self.assertEqual(prompts.ToolBoxPromptWriter.RETURN_NAMES, ("id", "prompt", "metadata"))
        self.assertEqual(prompts.ToolBoxPromptReader.RETURN_NAMES, prompts.ToolBoxRandomPrompt.RETURN_NAMES)
        self.assertIn("ToolBoxPromptReader", prompts.NODE_CLASS_MAPPINGS)

    def test_import_annotations_and_missing_fields_defaults(self):
        metadata = dict(language="zh", media_type="image", prompt_type="natural", nsfw=0,
                        content_format="plaintext", dynamic=0, suggested_width=1024,
                        suggested_height=768, tags=[], sensitivity_level=3, gore=1)
        import_prompts.import_records([(1, "synthetic")], self.path, metadata)
        data = library.detail(1)
        self.assertEqual(data["sensitivity_level"], 3)
        self.assertTrue(data["gore"])
        self.assertFalse(data["extreme"])

    def test_120k_records_page_payload_and_combined_filters(self):
        self.write("initial")
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                "INSERT INTO prompts (shasum,prompt,language,media_type,prompt_type,nsfw,content_format,dynamic,created_at,sensitivity_level,gore) VALUES (?,?, 'zh','image','natural',0,'plaintext',0,'test',?,?)",
                ((str(i), f"synthetic {i} " + "x" * 500, i % 5, i % 2) for i in range(120000)),
            )
        started = time.monotonic()
        data = library.list_prompts({"sensitivity_level": "L2", "gore": "是", "page_size": "50"})
        elapsed = time.monotonic() - started
        self.assertEqual(data["total"], 36000)
        self.assertEqual(len(data["items"]), 50)
        self.assertTrue(all(len(row["preview"]) <= 320 for row in data["items"]))
        self.assertLess(len(json.dumps(data)), 100_000)
        self.assertLess(elapsed, 10, "Paged query should complete within a generous CI time budget")
        print(f"\n120k prompt page query: {elapsed:.3f}s, {len(json.dumps(data))} response bytes")


if __name__ == "__main__":
    unittest.main()
