import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from nodes import prompt_nodes
from scripts import migrate_prompt_shasum


class PromptWriterTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "prompts.sqlite3"
        self.original_database_path = prompt_nodes.DEFAULT_PROMPT_DB
        prompt_nodes.DEFAULT_PROMPT_DB = self.database_path
        self.writer = prompt_nodes.ToolBoxPromptWriter()

    def tearDown(self):
        prompt_nodes.DEFAULT_PROMPT_DB = self.original_database_path
        self.temporary_directory.cleanup()

    def write(self, prompt_id, prompt, **overrides):
        values = {
            "language": "zh",
            "media_type": "image",
            "prompt_type": "natural",
            "nsfw": False,
            "content_format": "plaintext",
            "dynamic": False,
            "width": 1024,
            "height": 768,
            "tags": "",
        }
        values.update(overrides)
        return self.writer.write_prompt(prompt_id, prompt, **values)

    def rows(self):
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM prompts ORDER BY id").fetchall()

    def tags(self, prompt_id):
        with sqlite3.connect(self.database_path) as conn:
            return [
                row[0]
                for row in conn.execute(
                    """
                    SELECT t.name
                    FROM tags t
                    JOIN prompt_tags pt ON pt.tag_id = t.id
                    WHERE pt.prompt_id = ?
                    ORDER BY t.name
                    """,
                    (prompt_id,),
                ).fetchall()
            ]

    def test_zero_id_inserts_prompt_with_shasum(self):
        prompt_id, prompt, metadata = self.write(0, "  a new prompt  ", tags="Portrait")

        self.assertEqual(prompt_id, 1)
        self.assertEqual(prompt, "a new prompt")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(json.loads(metadata)["shasum"], prompt_nodes.prompt_shasum(prompt))
        self.assertEqual(self.tags(prompt_id), ["portrait"])

    def test_zero_id_updates_existing_prompt_and_replaces_tags(self):
        prompt_id, _, _ = self.write(0, "same prompt", tags="old")

        returned_id, _, metadata = self.write(
            0,
            "same prompt",
            language="en",
            media_type="video",
            width=1920,
            height=1080,
            tags="new, replacement",
        )

        self.assertEqual(returned_id, prompt_id)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(json.loads(metadata)["language"], "en")
        self.assertEqual(json.loads(metadata)["media_type"], "video")
        self.assertEqual(self.tags(prompt_id), ["new", "replacement"])

    def test_zero_id_updates_lowest_id_when_shasum_is_duplicated(self):
        lowest_id, _, _ = self.write(0, "duplicate")
        other_id, _, _ = self.write(0, "other", language="en")
        self.write(other_id, "duplicate", language="en", tags="other-row")

        returned_id, _, _ = self.write(0, "duplicate", media_type="video", tags="lowest-row")

        self.assertEqual(returned_id, lowest_id)
        rows = {row["id"]: row for row in self.rows()}
        self.assertEqual(rows[lowest_id]["media_type"], "video")
        self.assertEqual(rows[other_id]["language"], "en")
        self.assertEqual(self.tags(lowest_id), ["lowest-row"])
        self.assertEqual(self.tags(other_id), ["other-row"])

    def test_explicit_id_updates_target_despite_duplicate_shasum(self):
        first_id, _, _ = self.write(0, "first", tags="first-row")
        target_id, _, _ = self.write(0, "target", tags="old-target")

        returned_id, _, metadata = self.write(
            target_id,
            "first",
            language="en",
            tags="updated-target",
        )

        self.assertEqual(returned_id, target_id)
        rows = {row["id"]: row for row in self.rows()}
        self.assertEqual(rows[first_id]["shasum"], rows[target_id]["shasum"])
        self.assertEqual(rows[target_id]["language"], "en")
        self.assertEqual(json.loads(metadata)["id"], target_id)
        self.assertEqual(self.tags(first_id), ["first-row"])
        self.assertEqual(self.tags(target_id), ["updated-target"])

    def test_missing_explicit_id_raises_without_writing(self):
        existing_id, _, _ = self.write(0, "existing")
        before = [tuple(row) for row in self.rows()]

        with self.assertRaisesRegex(ValueError, "prompt id does not exist: 999"):
            self.write(999, "missing")

        self.assertEqual(existing_id, 1)
        self.assertEqual([tuple(row) for row in self.rows()], before)

    def test_writer_rejects_old_unique_shasum_schema(self):
        with sqlite3.connect(self.database_path) as conn:
            create_old_schema(conn)

        with self.assertRaisesRegex(ValueError, "shasum column must allow duplicates"):
            self.write(0, "blocked")


class PromptShasumMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "prompts.sqlite3"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_migration_removes_inline_unique_constraint_and_preserves_data(self):
        with sqlite3.connect(self.database_path) as conn:
            create_old_schema(conn)
            conn.execute(
                """
                INSERT INTO prompts (
                    id, shasum, prompt, language, media_type, prompt_type, nsfw,
                    content_format, dynamic, suggested_width, suggested_height, created_at
                ) VALUES (5, 'legacy-one', 'duplicate', 'zh', 'image', 'natural', 0,
                          'plaintext', 0, 1024, 768, 'old')
                """
            )
            conn.execute(
                """
                INSERT INTO prompts (
                    id, shasum, prompt, language, media_type, prompt_type, nsfw,
                    content_format, dynamic, suggested_width, suggested_height, created_at
                ) VALUES (10, 'legacy-two', 'duplicate', 'en', 'video', 'natural', 0,
                          'plaintext', 0, 1920, 1080, 'old')
                """
            )
            conn.execute("INSERT INTO tags (id, name) VALUES (1, 'kept-tag')")
            conn.execute("INSERT INTO prompt_tags (prompt_id, tag_id) VALUES (5, 1)")
            conn.execute("DELETE FROM prompts WHERE id = 10")
            conn.execute(
                """
                INSERT INTO prompts (
                    id, shasum, prompt, language, media_type, prompt_type, nsfw,
                    content_format, dynamic, suggested_width, suggested_height, created_at
                ) VALUES (6, 'legacy-two', 'duplicate', 'en', 'video', 'natural', 0,
                          'plaintext', 0, 1920, 1080, 'old')
                """
            )
            conn.commit()

        result = migrate_prompt_shasum.migrate_db(
            self.database_path,
            output=lambda _message: None,
        )

        self.assertTrue(result["unique_constraint_removed"])
        self.assertEqual(result["removed_duplicates"], 0)
        with sqlite3.connect(self.database_path) as conn:
            self.assertFalse(migrate_prompt_shasum.has_unique_shasum_index(conn))
            rows = conn.execute("SELECT id, shasum FROM prompts ORDER BY id").fetchall()
            expected_shasum = migrate_prompt_shasum.prompt_shasum("duplicate")
            self.assertEqual(rows, [(5, expected_shasum), (6, expected_shasum)])
            self.assertEqual(
                conn.execute("SELECT prompt_id, tag_id FROM prompt_tags").fetchall(),
                [(5, 1)],
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            cursor = conn.execute(
                """
                INSERT INTO prompts (
                    shasum, prompt, language, media_type, prompt_type, nsfw,
                    content_format, dynamic, suggested_width, suggested_height, created_at
                ) VALUES ('new', 'new', 'zh', 'image', 'natural', 0,
                          'plaintext', 0, 1024, 768, 'new')
                """
            )
            self.assertEqual(cursor.lastrowid, 11)

        second_result = migrate_prompt_shasum.migrate_db(
            self.database_path,
            output=lambda _message: None,
        )
        self.assertFalse(second_result["unique_constraint_removed"])

    def test_migration_drops_explicit_unique_shasum_index(self):
        with sqlite3.connect(self.database_path) as conn:
            prompt_nodes.create_schema(conn)
            conn.execute("CREATE UNIQUE INDEX idx_prompts_shasum ON prompts(shasum)")
            conn.commit()

        result = migrate_prompt_shasum.migrate_db(
            self.database_path,
            output=lambda _message: None,
        )

        self.assertTrue(result["unique_constraint_removed"])
        with sqlite3.connect(self.database_path) as conn:
            self.assertFalse(migrate_prompt_shasum.has_unique_shasum_index(conn))


def create_old_schema(conn):
    conn.execute(
        """
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shasum TEXT NOT NULL UNIQUE,
            prompt TEXT NOT NULL,
            language TEXT NOT NULL,
            media_type TEXT NOT NULL,
            prompt_type TEXT NOT NULL,
            nsfw INTEGER NOT NULL,
            content_format TEXT NOT NULL,
            dynamic INTEGER NOT NULL,
            suggested_width INTEGER NOT NULL DEFAULT 1024,
            suggested_height INTEGER NOT NULL DEFAULT 768,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)"
    )
    conn.execute(
        """
        CREATE TABLE prompt_tags (
            prompt_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY(prompt_id, tag_id),
            FOREIGN KEY(prompt_id) REFERENCES prompts(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
        """
    )


if __name__ == "__main__":
    unittest.main()
