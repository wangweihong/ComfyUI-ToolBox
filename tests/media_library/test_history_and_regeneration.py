import asyncio
import copy
import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image,PngImagePlugin
from support import Library,LibraryError
from regeneration_fixture import FakeRuntime,graph

regeneration=importlib.import_module('nodes.media_library.regeneration')


def image(lib, prompt=None, name='source.png'):
    path=Path(lib.roots()[0]['path'])/name;path.parent.mkdir(parents=True,exist_ok=True)
    info=PngImagePlugin.PngInfo()
    if prompt is not None:info.add_text('prompt',json.dumps(prompt))
    info.add_text('workflow',json.dumps({'nodes':[{'id':1,'type':'original'}]}))
    Image.new('RGB',(32,32),'red').save(path,pnginfo=info)
    return path,lib.upsert(path)


def test_directory_history_records_visits_not_scans_or_detail(lib):
    path,asset=image(lib)
    lib.scan();lib.detail(asset);assert lib.folder_visits()==[]
    lib.visit_folder(str(path.parent));assert lib.folder_visits()[0]['path']==str(path.parent)
    (path.parent/'deep').mkdir();lib.visit_folder(str(path.parent/'deep'))
    lib.visit_folder(str(path.parent));assert len(lib.folder_visits())==2
    assert lib.folder_visits()[0]['path']==str(path.parent)
    reopened=Library(lib.db_path,lib.cache)
    try:assert [row['path'] for row in reopened.folder_visits()]==[row['path'] for row in lib.folder_visits()]
    finally:reopened.close()


def test_directory_history_limit_rename_and_missing_entries(lib):
    root=Path(lib.roots()[0]['path'])
    for index in range(23):
        path=root/f'folder-{index}';path.mkdir();lib.visit_folder(str(path))
    visits=lib.folder_visits();assert len(visits)==20
    assert visits[0]['path']==str(root/'folder-22')
    lib.rename_folder(str(root/'folder-22'),'renamed')
    assert lib.folder_visits()[0]['path']==str(root/'renamed')
    (root/'renamed').rmdir();assert lib.folder_visits()[0]['available'] is False
    assert len(lib.prune_folder_visits())==19
    assert all(row['available'] for row in lib.folder_visits())


def test_directory_history_rejects_outside_and_prunes_removed_roots(lib,tmp_path):
    root=tmp_path/'custom';root.mkdir()
    with pytest.raises(LibraryError):lib.visit_folder(str(root))
    added=next(row for row in lib.add_root(str(root)) if row['path']==str(root))
    lib.visit_folder(str(root),added['id']);lib.remove_root(added['id']);assert lib.folder_visits()==[]


def test_graph_parser_rejects_summary_ui_only_and_truncation():
    for item in [dict(kind='video'),dict(kind='image',raw={'workflow':'{"nodes":[]}'}),dict(kind='image',raw={'prompt':'broken'}),dict(kind='image',raw={'prompt':graph()},truncated=True)]:
        with pytest.raises(LibraryError):regeneration.recorded_graph(item)
    assert regeneration.recorded_graph(dict(kind='image',raw={'prompt':json.dumps(json.dumps(graph()))}))==graph()


def test_branch_selection_ignores_unrelated_outputs_and_preserves_shared_seed_links():
    prompt=graph();prompt['other']={'class_type':'UnknownNode','inputs':{}}
    branch=regeneration.branch_graph(prompt,'save');assert 'other' not in branch
    definitions=FakeRuntime('/tmp').definitions(branch)
    branch['sampler']={'class_type':'KSampler','inputs':{'seed':['seed',0]}}
    changes=regeneration.randomize_seeds(branch,definitions)
    assert len(changes)==1 and changes[0]['before']==123 and 0<=changes[0]['after']<=2**53-1
    assert changes[0]['after']!=123 and branch['sampler']['inputs']['seed']==['seed',0]
    assert prompt['seed']['inputs']['seed']==123


def test_seed_primitive_and_unknown_sources():
    prompt={'primitive':{'class_type':'PrimitiveInt','inputs':{'value':3}},'sampler':{'class_type':'KSampler','inputs':{'seed':['primitive',0]}}}
    changes=regeneration.randomize_seeds(prompt,FakeRuntime('/tmp').definitions(prompt));assert changes[0]['field']=='value'
    prompt['primitive']['class_type']='UnknownMath'
    definitions=FakeRuntime('/tmp').definitions(prompt);definitions['UnknownMath']={'required':{'value':('INT',{})}}
    with pytest.raises(LibraryError):regeneration.randomize_seeds(prompt,definitions)
    with pytest.raises(LibraryError):regeneration.randomize_seeds(graph()|{'seed':{'class_type':'Seed (rgthree)','inputs':{'seed':True}}},FakeRuntime('/tmp').definitions(graph()))


def test_seed_change_preview_preserves_large_original_integer_digits():
    prompt=graph();prompt['seed']['inputs']['seed']=2**64-1
    changes=regeneration.randomize_seeds(prompt,FakeRuntime('/tmp').definitions(prompt))
    assert changes[0]['before']=='18446744073709551615'
    assert isinstance(changes[0]['after'],int) and changes[0]['after']<=2**53-1


def test_native_validation_reports_unavailable_models_without_dumping_config():
    errors={'model':{'class_type':'UNETLoader','errors':[{'type':'value_not_in_list','extra_info':{'input_name':'unet_name','received_value':'missing.safetensors','input_config':['large private list']}}]}}
    message=regeneration.validation_error({'message':'failed'},errors,{})
    assert 'UNETLoader' in message and 'missing.safetensors' in message and 'large private list' not in message


def test_cycles_dangling_links_and_no_seed_are_rejected():
    prompt=graph();prompt['image']['inputs']['color']=['missing',0]
    with pytest.raises(LibraryError):regeneration.branch_graph(prompt,'save')
    prompt=graph();prompt['seed']['inputs']['seed']=['image',0]
    with pytest.raises(LibraryError):regeneration.branch_graph(prompt,'save')
    with pytest.raises(LibraryError):regeneration.randomize_seeds({'node':{'class_type':'EmptyImage','inputs':{'color':123}}},FakeRuntime('/tmp').definitions(graph()))


@pytest.fixture
async def service(lib):
    runtime=FakeRuntime(Path(lib.roots()[0]['path']))
    manager=regeneration.Regenerator(lambda:lib,runtime)
    yield manager,runtime
    await manager.close()


async def test_prepare_then_submit_is_idempotent_and_indexes_every_result(lib,service):
    manager,runtime=service;path,asset=image(lib,graph());before=path.read_bytes()
    plan=await manager.prepare(asset,'save')
    assert runtime.submissions==[] and plan['batches']==[{'node_id':'image','batch_size':2}]
    assert plan['seed_changes'][0]['before']==123
    first,second=await asyncio.gather(manager.submit(plan['token']),manager.submit(plan['token']))
    assert first['id']==second['id'] and len(runtime.submissions)==1
    job=await manager.status(first['id']);assert job['status']=='complete' and len(job['outputs'])==2
    assert all(Path(row['path']).parent==path.parent for row in job['outputs'])
    assert path.read_bytes()==before
    assert runtime.submissions[0]['prompt']['save']['class_type']=='SaveImage'
    assert 'workflow' not in runtime.submissions[0]['extra_data']['extra_pnginfo']
    for output in job['outputs']:
        detail=lib.detail(output['id']);new_graph=json.loads(detail['raw']['prompt'])
        assert new_graph['seed']['inputs']['seed']==plan['seed_changes'][0]['after']
        provenance=json.loads(detail['raw']['tb_media_regeneration']);assert provenance['source_id']==asset
    assert manager.jobs(asset)[0]['id']==job['id']


async def test_custom_save_node_is_converted_and_unrelated_branch_is_not_run(lib,service):
    manager,runtime=service;prompt=graph();prompt['save']['class_type']='ToolBoxPromptSaveImage';prompt['save']['inputs']['prompt_metadata']='stale metadata'
    prompt['unused']={'class_type':'UnknownNode','inputs':{}}
    _,asset=image(lib,prompt);plan=await manager.prepare(asset,'save');await manager.submit(plan['token'])
    submitted=runtime.submissions[0]['prompt'];assert 'unused' not in submitted
    assert 'prompt_metadata' not in submitted['save']['inputs']


async def test_changed_source_and_expired_plan_never_enqueue(lib,service):
    manager,runtime=service;path,asset=image(lib,graph());plan=await manager.prepare(asset,'save')
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(LibraryError,match='变化'):await manager.submit(plan['token'])
    manager.prepared[plan['token']]['created']-=601
    with pytest.raises(LibraryError,match='过期'):await manager.submit(plan['token'])
    assert runtime.submissions==[]


async def test_failed_validation_no_job_and_failed_submit_no_duplicate(lib,service):
    manager,runtime=service;_,asset=image(lib,graph());runtime.validation_error=LibraryError('missing model')
    with pytest.raises(LibraryError,match='missing model'):await manager.prepare(asset,'save')
    assert manager.jobs(asset)==[]
    runtime.validation_error=None;plan=await manager.prepare(asset,'save');runtime.submit_error=LibraryError('rejected')
    first=await manager.submit(plan['token']);assert first['status']=='failed'
    assert (await manager.submit(plan['token']))['id']==first['id']


async def test_uncertain_submission_is_not_retried(lib,service):
    manager,runtime=service;_,asset=image(lib,graph());plan=await manager.prepare(asset,'save');runtime.submit_error=TimeoutError('lost response')
    first=await manager.submit(plan['token']);assert first['status']=='unknown'
    runtime.submit_error=None;await manager.submit(plan['token']);assert runtime.submissions==[]


async def test_input_source_falls_back_to_model_regenerated_directory(lib,service,tmp_path):
    manager,runtime=service;_,asset=image(lib,graph());runtime.root=tmp_path/'separate-output';runtime.root.mkdir()
    plan=await manager.prepare(asset,'save');assert plan['prefix'].startswith('images/unspecified/regenerated/')


async def test_status_rejects_outputs_outside_output_and_keeps_saved_files(lib,service):
    manager,runtime=service;_,asset=image(lib,graph());plan=await manager.prepare(asset,'save');job=await manager.submit(plan['token'])
    runtime.states[job['id']]['images']=[{'filename':'secret.png','subfolder':'../outside','type':'output'},'malformed']
    result=await manager.status(job['id']);assert result['status']=='complete' and result['outputs']==[] and result['error']


async def test_cancelled_preflight_is_released_but_submitted_token_stays_idempotent(lib,service):
    manager,runtime=service;_,asset=image(lib,graph());plan=await manager.prepare(asset,'save')
    await manager.release(plan['token']);assert plan['token'] not in manager.prepared
    with pytest.raises(LibraryError,match='过期'):await manager.submit(plan['token'])
    plan=await manager.prepare(asset,'save');first=await manager.submit(plan['token']);await manager.release(plan['token'])
    assert 'payload' not in manager.prepared[plan['token']]
    assert (await manager.submit(plan['token']))['id']==first['id'] and len(runtime.submissions)==1
