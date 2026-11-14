import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_nodes as prompts
from nodes.prompt_schema import CATEGORY_FIELDS


class PromptBatchTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'prompts.sqlite3'
        database = patch.object(prompts.database, 'DEFAULT_DB', self.path)
        database.start(); self.addCleanup(database.stop)
        self.batch = prompts.ToolBoxPromptsByTag()

    def write(self, text, **changes):
        values = dict(id=0, prompt=text, language='zh', media_type='image', prompt_type='natural',
                      nsfw=False, content_format='plaintext', dynamic=False, width=1024, height=768, tags='摄影')
        values.update(changes)
        return prompts.ToolBoxPromptWriter().write_prompt(**values)[0]

    def test_offset_limit_alignment_duplicates_and_empty_results(self):
        ids = [self.write(f'Synthetic photo {i}', width=100 + i, height=200 + i) for i in range(205)]
        first = self.batch.execute_prompt(tags='摄影')
        self.assertEqual(first['result'][0], ids[:100])
        self.assertEqual(first['result'][-1], 205)
        second = self.batch.execute_prompt(tags='摄影', start_index=100, limit=100)
        self.assertEqual(second['result'][0], ids[100:200])
        tail = self.batch.execute_prompt(tags='摄影', start_index=200, limit=100)
        self.assertEqual(tail['result'][0], ids[200:])
        self.assertEqual(tail['ui']['toolbox_prompt_batch'][0]['count'], 5)
        for result in (first['result'], second['result'], tail['result']):
            self.assertEqual(len({len(values) for values in result[:5]}), 1)
            for prompt_id, text, width, height, metadata in zip(*result[:5]):
                data = json.loads(metadata)
                self.assertEqual((data['id'], data['width'], data['height']), (prompt_id, width, height))
                self.assertEqual(data['shasum'], prompts.prompt_shasum(text))
        one = self.batch.execute_prompt(start_index=204, limit=1)['result']
        self.assertEqual(one[0], [ids[-1]])
        self.write('Synthetic photo 0', id=ids[1])
        duplicate = self.batch.execute_prompt(limit=2)['result']
        self.assertEqual(duplicate[0], ids[:2])
        self.assertEqual(duplicate[1][0], duplicate[1][1])
        for query, total in ((dict(tags='unknown'), 0), (dict(start_index=205), 205)):
            empty = self.batch.execute_prompt(**query)
            self.assertEqual(empty['result'], ([], [], [], [], [], total))
            self.assertEqual(empty['ui']['toolbox_prompt_batch'][0]['count'], 0)

    def test_filters_and_safe_defaults_with_explicit_overrides(self):
        safe = self.write('Safe photo', tags='摄影, landscape', sensitivity_level='L2')
        for name in CATEGORY_FIELDS:
            self.write(f'Flagged {name}', **{name: True})
        self.assertEqual(self.batch.execute_prompt()['result'][0], [safe])
        random = prompts.ToolBoxRandomPrompt()
        filters = dict(seed=0, language='全部', media_type='全部', prompt_type='全部', safety='全部',
                       content_format='全部', dynamic='全部', match_size=False, width=1024, height=768, tags='')
        self.assertEqual(random.random_prompt(**filters)[0], safe)
        for name in CATEGORY_FIELDS:
            self.assertEqual(len(self.batch.execute_prompt(**{name: '全部'})['result'][0]), 2)
            selected = self.batch.execute_prompt(**{name: '是'})['result'][0]
            self.assertEqual(len(selected), 1)
            self.assertEqual(random.random_prompt(**filters, **{name: '是'})[0], selected[0])
        query = dict(tags=' 摄影, LANDSCAPE,摄影 ', language='zh', media_type='image', prompt_type='natural',
                     content_format='plaintext', dynamic='static', safety='safe', match_size=True,
                     width=1024, height=768, sensitivity_mode='exact', sensitivity_levels='L2')
        self.assertEqual(self.batch.execute_prompt(**query)['result'][0], [safe])
        for changes in (dict(tags='摄影,missing'), dict(language='en'), dict(media_type='video'),
                        dict(prompt_type='danbooru'), dict(content_format='json'), dict(dynamic='dynamic'),
                        dict(width=999), dict(sensitivity_levels='L0'), dict(sensitivity_levels='')):
            self.assertEqual(self.batch.execute_prompt(**{**query, **changes})['result'][0], [])
        self.assertEqual(self.batch.execute_prompt(tags='landscape', sensitivity_level='L1')['result'][0], [])
        for cls in (prompts.ToolBoxPromptsByTag, prompts.ToolBoxRandomPrompt):
            for name in CATEGORY_FIELDS:
                self.assertEqual(cls.INPUT_TYPES()['optional'][name][1]['default'], '否')
        self.assertNotIn('seed', self.batch.INPUT_TYPES()['required'])
        self.assertEqual(self.batch.OUTPUT_IS_LIST, (True, True, True, True, True, False))
        self.assertEqual(prompts.NODE_CLASS_MAPPINGS['ToolBoxPromptsByTag'], type(self.batch))

    def test_invalid_inputs_database_errors_and_revision(self):
        for query in (dict(start_index=-1), dict(start_index=True), dict(start_index=1.5),
                      dict(start_index=2**63), dict(limit=0), dict(limit=101), dict(limit=True),
                      dict(limit='1'), dict(gore='false'), dict(language='invalid')):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.batch.execute_prompt(**query)
        with self.assertRaisesRegex(ValueError, 'database not found'):
            self.batch.execute_prompt()
        self.assertFalse(self.path.exists())
        self.write('one')
        revision = self.batch.IS_CHANGED()
        self.write('two')
        self.assertNotEqual(revision, self.batch.IS_CHANGED())
        with prompts.connect_db() as conn:
            conn.execute('ALTER TABLE prompts DROP COLUMN gore')
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.batch.execute_prompt()

    def test_metadata_and_count_share_snapshot_during_external_write(self):
        self.write('first'); second = self.write('second')
        original = prompts.metadata_json
        calls = []
        def serialize(conn, row):
            if not calls:
                calls.append(True)
                self.write('second', id=second, tags='changed')
            return original(conn, row)
        with patch.object(prompts, 'metadata_json', side_effect=serialize):
            result = self.batch.execute_prompt(tags='摄影')['result']
        self.assertEqual(result[-1], 2)
        self.assertEqual([json.loads(value)['tags'] for value in result[4]], [['摄影'], ['摄影']])
        self.assertEqual(self.batch.execute_prompt(tags='摄影')['result'][-1], 1)


if __name__ == '__main__':
    unittest.main()
