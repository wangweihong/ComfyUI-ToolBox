import json
from pathlib import Path
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from support import Library, metadata


def graph():
    return {'1':{'class_type':'Drama3Loader','inputs':{'model_name':'speech.safetensors'}},
            '2':{'class_type':'Drama3Generate','inputs':{'model':['1',0],'text':'你好，海岸','seed':0,'temperature':0.7,'top_p':0.9}}}


def extract(raw):
    return metadata.refresh_generation({'raw':raw})


def fields(info):
    return {f['name']:f['value'] for n in info['generation_nodes'] for f in n['fields']}


def test_unknown_generator_exposes_literal_text_and_seed_without_sampler():
    info=extract({'prompt':json.dumps(graph())})
    assert info['has_workflow']
    assert fields(info)['text']=='你好，海岸'
    assert fields(info)['seed']=='0'
    assert fields(info)['model_name']=='speech.safetensors'
    assert 'model' not in fields(info)  # A linked model is not a model filename.
    assert 'positive' not in info['summary']


def test_custom_text_nodes_are_not_guessed_to_be_positive_or_negative():
    info=extract({'prompt':json.dumps({'1':{'class_type':'CustomText','inputs':{'text':'negative only'}}})})
    assert fields(info)['text']=='negative only'
    assert not info['summary']


def test_nested_json_comment_envelope_and_flat_explicit_fields():
    info=extract({'comment':json.dumps({'metadata':{'prompt':graph()}})})
    assert fields(info)['seed']=='0'
    info=extract({'description':json.dumps({'generation':{'positive_prompt':'日出','negative_prompt':'模糊','seed':42}})})
    assert fields(info)['positive_prompt']=='日出'
    assert fields(info)['seed']=='42'


def test_ui_workflow_only_preserves_widget_values_without_guessing_names():
    workflow={'nodes':[{'id':9,'type':'CustomVoice','title':'语音生成','widgets_values':['你好',123,False]}]}
    info=extract({'workflow':json.dumps(workflow)})
    assert info['has_workflow'] and not info['summary']
    assert fields(info)=={'控件 1':'你好','控件 2':'123','控件 3':'false'}


def test_ui_workflow_does_not_mask_existing_parameters():
    info=extract({'workflow':json.dumps({'nodes':[{'id':1,'type':'CustomGenerator','widgets_values':[]}]}),
                  'parameters':'sunrise\nNegative prompt: blurry\nSteps: 12, Sampler: Euler, CFG scale: 3, Seed: 12'})
    assert info['summary']['positive']=='sunrise'
    assert info['summary']['seed']=='12'


def test_cache_upgrade_reads_saved_json_without_reopening_media(lib):
    root=Path(lib.roots()[0]['path']);path=root/'generated.png'
    extra=PngImagePlugin.PngInfo();extra.add_text('prompt',json.dumps(graph()))
    Image.new('RGB',(32,24),'blue').save(path,pnginfo=extra)
    fid=lib.upsert(path);before=path.read_bytes()
    row=lib.row(fid);old=json.loads(row['metadata'])
    for key in ('generation_nodes','parser_version','has_workflow','generation_truncated'):old.pop(key,None)
    old['summary']={}
    with lib.transaction() as db:db.execute('UPDATE media_files SET metadata=?,search_text=? WHERE id=?',(json.dumps(old),str(path),fid))
    with patch.object(metadata,'inspect',side_effect=AssertionError('must reuse cached metadata')):
        detail=lib.detail(fid)
    assert fields(detail)['text']=='你好，海岸'
    assert lib.files(q='你好')['total']==1
    assert path.read_bytes()==before


def test_plain_technical_metadata_is_not_generation_parameters():
    info=extract({'ffprobe':{'streams':[{'codec_name':'h264'}]},'encoder':'Lavf'})
    assert not info['generation_nodes'] and not info['summary'] and not info['has_workflow']


def test_standard_sampler_roles_remain_correct():
    g={'1':{'class_type':'CLIPTextEncode','inputs':{'text':'positive'}},
       '2':{'class_type':'CLIPTextEncode','inputs':{'text':'negative'}},
       '3':{'class_type':'KSampler','inputs':{'positive':['1',0],'negative':['2',0],'seed':42,'steps':12,'cfg':3}}}
    info=extract({'prompt':json.dumps(g)})
    assert info['summary']['positive']=='positive'
    assert info['summary']['negative']=='negative'
    assert info['summary']['seed']=='42'


def test_graph_json_with_no_literal_parameters_is_not_labeled_as_prompt_text():
    g={'1':{'class_type':'Custom','inputs':{'source':['2',0]}},'2':{'class_type':'Custom','inputs':{'source':['1',0]}}}
    info=extract({'prompt':json.dumps(g)})
    assert info['has_workflow'] and not info['generation_nodes']
