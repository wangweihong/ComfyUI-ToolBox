import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from nodes import prompt_nodes as prompts, prompt_library, prompt_examples as library
from nodes import prompt_examples_schema as schema, prompt_media_nodes as media
from scripts import migrate_prompt_examples, migrate_prompt_shasum, import_prompts


class PromptExamplesTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
        self.db=self.root/'prompts.sqlite3';self.output=self.root/'output';self.output.mkdir()
        self.database=patch.object(prompts.database,'DEFAULT_DB',self.db);self.database.start()
        self.output_patch=patch.object(library,'OUTPUT_ROOT',self.output);self.output_patch.start()
        self.writer=prompts.ToolBoxPromptWriter()
        self.id=self.write('Synthetic prompt')[0];self.metadata=json.loads(prompts.ToolBoxPromptReader().read_prompt(self.id)[-1])

    def tearDown(self):
        self.output_patch.stop();self.database.stop();self.directory.cleanup()

    def write(self,text,prompt_id=0,tags='alpha'):
        return self.writer.write_prompt(prompt_id,text,'zh','image','natural',False,'plaintext',False,64,64,tags)

    def file(self,name='images/model/sample.png',data=b'synthetic'):
        path=self.output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path

    def payload(self,paths,**changes):
        return dict(prompt_id=self.id,shasum=self.metadata['shasum'],paths=[str(path) for path in paths],source='manual')|changes

    def test_mapping_batch_absolute_relative_duplicates_counts_and_raw_path(self):
        image=self.file();video=self.file('videos/model/movie.mp4',b'video')
        rows=library.register(self.payload([image,video]))['items']
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['relative_path'],'images/model/sample.png')
        self.assertIn('type=output',rows[0]['url']);self.assertNotIn('preview=',rows[0]['url'])
        self.assertEqual([r['media_type'] for r in rows],['image','video'])
        again=library.register(self.payload(['images/model/sample.png']))['items'][0]
        self.assertEqual(rows[0]['id'],again['id'])
        self.assertEqual(library.list_examples({},self.id)['total'],2)
        self.assertEqual(prompt_library.detail(self.id)['example_count'],2)
        self.assertEqual(prompt_library.list_prompts({})['items'][0]['example_count'],2)
        self.assertEqual(image.read_bytes(),b'synthetic')

    def test_parallel_branches_keep_their_own_source_and_execution_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        other=self.write('Other synthetic branch');other_metadata=json.loads(other[-1])
        first_path=self.file('branch-a.png');second_path=self.file('branch-b.png')
        payloads=[self.payload([first_path],source='generated',job_id='job-a',node_id='save-a'),
                  dict(prompt_id=other[0],shasum=other_metadata['shasum'],paths=[str(second_path)],source='generated',job_id='job-b',node_id='save-b')]
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(library.register,payloads))
        self.assertEqual([(result['items'][0]['prompt_id'],result['items'][0]['relative_path']) for result in results],[(self.id,'branch-a.png'),(other[0],'branch-b.png')])
        self.assertEqual(library.list_examples({},self.id)['items'][0]['node_id'],'save-a')
        self.assertEqual(library.list_examples({},other[0])['items'][0]['job_id'],'job-b')

    def test_invalid_and_outside_paths_do_not_initialize(self):
        outside=self.root/'outside.png';outside.write_bytes(b'x')
        self.file('unsupported.txt')
        (self.output/'alias.png').symlink_to(outside)
        for path in (outside,'../outside.png','http://example.com/image.png',self.output,'missing.png','unsupported.txt','alias.png'):
            with self.subTest(path=str(path)),self.assertRaises(ValueError):library.register(self.payload([path]))
        with prompts.connect_db() as conn:self.assertFalse(schema.table_exists(conn,'prompt_examples'))

    def test_no_scan_during_reads_and_manual_check_cleanup_restore(self):
        path=self.file();row=library.register(self.payload([path]))['items'][0]
        path.unlink()
        with patch.object(library,'probe',side_effect=AssertionError('Reading must not scan')):
            self.assertEqual(library.list_examples({},self.id)['items'][0]['status'],'available')
            self.assertEqual(prompt_library.list_prompts({})['items'][0]['example_count'],1)
        checked=library.check({'ids':[row['id']]})['items'][0];self.assertEqual(checked['status'],'missing')
        path.write_bytes(b'synthetic');os.utime(path,ns=(row['mtime_ns'],row['mtime_ns']))
        result=library.cleanup({'ids':[row['id']]})
        self.assertEqual(result['deleted'],[]);self.assertEqual(result['items'][0]['status'],'available')
        path.unlink();library.check({'ids':[row['id']]})
        self.assertEqual(library.cleanup({'ids':[row['id']]})['deleted'],[row['id']])
        self.assertEqual(library.list_examples({},self.id)['total'],0)

    def test_unavailable_root_permissions_and_changed_files_are_not_purged(self):
        path=self.file();row=library.register(self.payload([path]))['items'][0]
        with patch.object(Path,'open',side_effect=PermissionError('denied')):
            self.assertEqual(library.check({'ids':[row['id']]})['items'][0]['status'],'unavailable')
        path.write_bytes(b'overwritten data')
        self.assertEqual(library.check({'ids':[row['id']]})['items'][0]['status'],'changed')
        self.assertEqual(library.cleanup({'ids':[row['id']]})['deleted'],[])
        row=library.register(self.payload([path]))['items'][0]
        path.unlink();library.check({'ids':[row['id']]})
        self.output.rename(self.root/'offline')
        result=library.cleanup({'ids':[row['id']]})
        self.assertEqual(result['deleted'],[]);self.assertEqual(result['items'][0]['status'],'unavailable')

    def test_history_and_manual_concurrent_edit_conflict(self):
        path=self.file();library.register(self.payload([path]))
        version=prompt_library.detail(self.id)['version']
        self.write('Synthetic prompt',prompt_id=self.id,tags='new-label')
        with self.assertRaises(prompts.PromptConflict):library.register(self.payload([path],version=version))
        self.write('Changed prompt',prompt_id=self.id)
        self.assertEqual(library.list_examples({},self.id)['total'],0)
        self.assertEqual(library.list_examples({'shasum':'all'},self.id)['total'],1)
        with self.assertRaises(prompts.PromptConflict):library.register(self.payload([path]))
        library.register(self.payload([path],source='generated'))
        self.assertEqual(library.list_examples({'shasum':self.metadata['shasum']},self.id)['total'],1)
        self.assertEqual(prompt_library.detail(self.id)['example_count'],0)

    def test_unlink_keeps_file_and_pagination_validation(self):
        paths=[self.file(f'{i}.png') for i in range(5)];rows=library.register(self.payload(paths))['items']
        self.assertEqual(len(library.list_examples({'page_size':'2','page':'2'})['items']),2)
        self.assertEqual(library.remove(rows[0]['id'])['deleted'],[rows[0]['id']]);self.assertTrue(paths[0].exists())
        for query in ({'page_size':'101'},{'status':'bad'},{'shasum':'bad'},{'unknown':'x'}):
            with self.assertRaises(ValueError):library.list_examples(query)
        for payload in ({'ids':[]},{'ids':[True]},{'ids':list(range(201))}):
            with self.assertRaises(ValueError):library.check(payload)

    def test_revision_only_tracks_prompt_and_tags_and_ui_output_compatibility(self):
        migrate_prompt_examples.migrate_db(self.db);revision=prompts.prompt_data_revision();generic=prompts.database_revision()
        path=self.file();row=library.register(self.payload([path]))['items'][0]
        library.check({'ids':[row['id']]});library.remove(row['id'])
        self.assertEqual(prompts.prompt_data_revision(),revision);self.assertNotEqual(prompts.database_revision(),generic)
        with prompts.connect_db() as conn:conn.execute("UPDATE tags SET name='changed-tag'")
        self.assertNotEqual(prompts.prompt_data_revision(),revision)
        reader=prompts.ToolBoxPromptReader();result=reader.execute_prompt(self.id)
        self.assertEqual(result['result'],reader.read_prompt(self.id));self.assertEqual(result['ui']['toolbox_prompt'][0]['id'],self.id)
        filters=dict(seed=42,language='全部',media_type='全部',prompt_type='全部',safety='全部',content_format='全部',dynamic='全部',match_size=False,width=64,height=64,tags='')
        random=prompts.ToolBoxRandomPrompt();execution=random.execute_prompt(**filters)
        self.assertEqual(execution['result'],random.random_prompt(**filters));self.assertEqual(execution['ui']['toolbox_prompt'][0]['shasum'],self.metadata['shasum'])
        before=prompts.prompt_data_revision()
        with prompts.connect_db() as conn:conn.execute('DROP TRIGGER toolbox_prompt_rev_prompts_insert')
        self.assertEqual(prompts.prompt_data_revision(),prompts.database_revision())
        self.assertNotEqual(prompts.prompt_data_revision(),before)

    def test_migration_backup_idempotence_meta_and_rebuilt_tables(self):
        with prompts.connect_db() as conn:
            conn.execute('CREATE TABLE library_meta(key TEXT PRIMARY KEY,value TEXT)');conn.execute("INSERT INTO library_meta VALUES('revision','keep')")
        backup=migrate_prompt_examples.migrate_db(self.db);self.assertTrue(backup.is_file())
        self.assertIsNone(migrate_prompt_examples.migrate_db(self.db))
        row=library.register(self.payload([self.file()]))['items'][0]
        with prompts.connect_db() as conn:
            migrate_prompt_shasum.rebuild_prompts_without_unique(conn)
            self.assertTrue(schema.revision_ready(conn))
            self.assertEqual(conn.execute('SELECT value FROM library_meta').fetchone()[0],'keep')
        self.assertEqual(library.list_examples({},self.id)['items'][0]['id'],row['id'])
        metadata={'language':'zh','media_type':'image','prompt_type':'natural','nsfw':False,'content_format':'plaintext','dynamic':False,'suggested_width':64,'suggested_height':64,'tags':[]}
        import_prompts.import_records([(self.id,'Reimported')],self.db,metadata)
        with prompts.connect_db() as conn:self.assertTrue(schema.revision_ready(conn));self.assertEqual(conn.execute('SELECT COUNT(*) FROM prompt_examples').fetchone()[0],1)
        self.assertEqual(library.list_examples({},self.id)['total'],0)

    def test_image_save_without_metadata_skips_association(self):
        inputs=media.ToolBoxPromptSaveImage.INPUT_TYPES()
        self.assertNotIn('prompt_metadata',inputs['required'])
        self.assertEqual(inputs['optional']['prompt_metadata'],('STRING',{'forceInput':True}))
        tensor=object();prompt={'synthetic':True};extra={'workflow':{'nodes':[]}}
        native_ui={'images':[{'filename':'sample.png','subfolder':'images/model','type':'output'}]}
        with patch.object(media,'image_saver') as delegate,patch.object(library,'validate_source') as validate,patch.object(media,'finish') as finish:
            delegate.return_value.save_images.return_value={'ui':native_ui}
            for metadata in ({},{'prompt_metadata':None}):
                with self.subTest(metadata=metadata):
                    result=media.ToolBoxPromptSaveImage().save(tensor,filename_prefix='images/model/test',prompt=prompt,extra_pnginfo=extra,**metadata)
                    delegate.return_value.save_images.assert_called_with(tensor,'images/model/test',prompt,extra)
                    self.assertIs(result['result'][0],tensor)
                    self.assertEqual(result['ui']['images'],native_ui['images'])
                    report=json.loads(result['result'][1])
                    self.assertEqual(report['paths'],['images/model/sample.png'])
                    self.assertEqual(report['registration'],'skipped')
                    self.assertNotIn('prompt_id',report)
                    self.assertEqual(result['ui']['toolbox_prompt_media'],[report])
            validate.assert_not_called();finish.assert_not_called()
            with self.assertRaises(ValueError):media.ToolBoxPromptSaveImage().save(tensor,filename_prefix='../outside')
            self.assertEqual(delegate.return_value.save_images.call_count,2)
        with prompts.connect_db() as conn:self.assertFalse(schema.table_exists(conn,'prompt_examples'))

    def test_image_delegate_registration_failure_retry_and_vhs_final_only(self):
        image=self.file();video=self.file('final.mp4',b'video')
        class Saver:
            def save_images(self,images,prefix,prompt,extra):
                self.args=(images,prefix,prompt,extra);return {'ui':{'images':[{'filename':image.name,'subfolder':'images/model','type':'output'}]},'result':(images,)}
        saver=Saver();tensor=object();meta=json.dumps(self.metadata)
        with patch.object(media,'image_saver',return_value=saver):
            result=media.ToolBoxPromptSaveImage().save(tensor,meta,'images/model/test',prompt={'synthetic':True})
        self.assertIs(result['result'][0],tensor);self.assertEqual(json.loads(result['result'][1])['registration'],'registered')
        with patch.object(library,'register',side_effect=sqlite3.OperationalError('locked')),patch.object(media,'image_saver',return_value=saver):
            result=media.ToolBoxPromptSaveImage().save(tensor,meta,'test')
        failed=json.loads(result['result'][1]);self.assertEqual(failed['registration'],'failed');self.assertTrue(image.exists())
        result=media.ToolBoxPromptRecordMedia().record(meta,files=json.dumps(failed));self.assertEqual(json.loads(result['result'][0])['registration'],'registered')
        result=media.ToolBoxPromptRecordMedia().record(meta,vhs_filenames=(True,[str(image),str(video)]))
        self.assertEqual(json.loads(result['result'][0])['paths'],['final.mp4'])
        self.assertEqual(json.loads(media.ToolBoxPromptRecordMedia().record(meta,vhs_filenames=(True,[]))['result'][0])['registration'],'pending')
        with self.assertRaises(ValueError):media.ToolBoxPromptRecordMedia().record(meta,vhs_filenames=(False,[str(video)]))
        with self.assertRaises(ValueError):media.ToolBoxPromptRecordMedia().record(meta,files='[]',vhs_filenames=(True,[]))
        with patch.object(media,'image_saver') as delegate:
            with self.assertRaises(ValueError):media.ToolBoxPromptSaveImage().save(tensor,'{}','test')
            with self.assertRaises(ValueError):media.ToolBoxPromptSaveImage().save(tensor,meta,'../outside')
            delegate.assert_not_called()


try:
    from aiohttp.test_utils import TestClient,TestServer
except ImportError:TestClient=None


@unittest.skipUnless(TestClient,'aiohttp required')
class PromptExampleRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from prompt_test_fixture import create_app
        self.base=PromptExamplesTest();self.base.setUp();self.client=TestClient(TestServer(create_app()));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close();self.base.tearDown()

    async def test_manual_register_check_cleanup_unlink_and_conflict(self):
        path=self.base.file();payload=self.base.payload([path])
        response=await self.client.post('/toolbox/prompt-examples/register',json=payload);self.assertEqual(response.status,200)
        row=(await response.json())['items'][0]
        data=await (await self.client.get(f'/toolbox/prompts/{self.base.id}/examples')).json();self.assertEqual(data['total'],1)
        self.base.write('changed',prompt_id=self.base.id)
        self.assertEqual((await self.client.post('/toolbox/prompt-examples/register',json=payload)).status,409)
        path.unlink();self.assertEqual((await self.client.post('/toolbox/prompt-examples/check',json={'ids':[row['id']]})).status,200)
        response=await self.client.delete('/toolbox/prompt-examples/invalid',json={'ids':[row['id']]});self.assertEqual((await response.json())['deleted'],[row['id']])
        self.assertEqual((await self.client.delete(f'/toolbox/prompt-examples/{row["id"]}')).status,200)

    async def test_errors_and_empty_reads_do_not_initialize(self):
        self.assertEqual((await (await self.client.get('/toolbox/prompt-examples')).json())['total'],0)
        with prompts.connect_db() as conn:self.assertFalse(schema.table_exists(conn,'prompt_examples'))
        for url in ('/toolbox/prompt-examples?page=0','/toolbox/prompt-examples?status=bad','/toolbox/prompts/999/examples'):
            self.assertIn((await self.client.get(url)).status,(400,404))
        self.assertEqual((await self.client.post('/toolbox/prompt-examples/check',data='x')).status,415)
        self.assertEqual((await self.client.post('/toolbox/prompt-examples/register',json={})).status,400)
        response=await self.client.post('/toolbox/prompt-examples/check',data=io.BytesIO(b'x'*1_100_001),headers={'Content-Type':'application/json'})
        self.assertEqual(response.status,413)


if __name__=='__main__':unittest.main()
