"""CPU orchestration tests use real VIDEO/FFmpeg and a synthetic inference adapter.

No model downloads; actual GPU checks are recorded separately in docs/testing.
Run inside an existing ComfyUI Python environment (see docs/flashvsr.md).
"""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import torch

COMFY = Path(os.environ.get('COMFY_ROOT','/root/ComfyUI'))
if not (COMFY/'folder_paths.py').is_file():
    pytest.skip('Requires the existing ComfyUI Python environment',allow_module_level=True)
sys.path.append(str(COMFY))
import comfy.cli_args
comfy.cli_args.args.cpu = True

PACKAGE = Path(os.environ.get('TOOLBOX_FLASHVSR_DIR',str(Path(__file__).resolve().parents[1]/'nodes/flashvsr')))
spec=importlib.util.spec_from_file_location('toolbox_flashvsr_test',PACKAGE/'__init__.py',submodule_search_locations=[str(PACKAGE)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from toolbox_flashvsr_test import cache,engine,encoding,resources,settings
from toolbox_flashvsr_test.nodes import ToolBoxFlashVSRConfig,ToolBoxFlashVSRUpscale
from toolbox_flashvsr_test.video import FlashVideo
from comfy_api.input_impl import VideoFromFile


@pytest.fixture(scope='module')
def source(tmp_path_factory):
    path=tmp_path_factory.mktemp('flashvsr')/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-filter_threads','2','-f','lavfi','-i','testsrc2=s=160x96:r=24:d=0.5',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.5','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(path)],check=True)
    return VideoFromFile(str(path))


@pytest.fixture
def fake_backend(monkeypatch):
    calls=[]
    @contextlib.contextmanager
    def backend(plan,info,guard):
        calls.append(plan['signature'])
        info['model_load_count']=info['decoder_load_count']=1
        def infer(image):
            guard.check()
            return torch.nn.functional.interpolate(image.movedim(-1,1),scale_factor=4,mode='nearest').movedim(1,-1)
        yield infer
    monkeypatch.setattr(engine,'load_backend',backend)
    return calls


def config(tmp_path,mode='stream',**extra):
    cfg=settings.configuration(cache_mode=mode,preset='custom',custom_width=768,custom_height=512,
                               chunk_frames=4,tile_width=128,tile_height=128,overlap_x=32,overlap_y=32,
                               duration_seconds=.375,cache_directory=str(tmp_path),cache_retention='keep')
    cfg.update(extra)
    return cfg


def test_three_nodes_only_and_no_upstream_import_at_registration():
    assert set(module.NODE_CLASS_MAPPINGS)=={'ToolBoxFlashVSRConfig','ToolBoxFlashVSRUpscale','ToolBoxVideoEncode'}
    assert all(c.CATEGORY=='ToolBox/FlashVSR' for c in module.NODE_CLASS_MAPPINGS.values())
    assert not any(k.startswith('custom_nodes.ComfyUI_FlashVSR') for k in sys.modules)
    assert ToolBoxFlashVSRConfig.INPUT_TYPES()['required']['cache_mode'][1]['default']=='请选择'
    assert ToolBoxFlashVSRUpscale.RETURN_TYPES==('VIDEO','STRING')
    assert ToolBoxFlashVSRUpscale.RETURN_NAMES==('video','info_json')


def test_unselected_mode_stops_before_model(source,tmp_path,fake_backend):
    with pytest.raises(ValueError,match='选择缓存模式'):
        settings.make_plan(source,config(tmp_path,mode='请选择'))
    assert fake_backend==[]


@pytest.mark.parametrize('key,value',[('tile_width',130),('tile_height',127),('overlap_x',128),('chunk_frames',0)])
def test_invalid_custom_geometry_is_not_silently_rounded(source,tmp_path,key,value):
    cfg=config(tmp_path);cfg[key]=value
    with pytest.raises(ValueError):settings.make_plan(source,cfg)


def test_presets_and_native_rate(source,tmp_path):
    p=settings.make_plan(source,config(tmp_path,preset='low_memory'))
    assert (p['chunk_frames'],p['tile_width'])==(8,192)  # bounded to padded whole LQ width
    assert p['fps']=='24' and p['frames']==9
    b=settings.make_plan(source,config(tmp_path,preset='balanced'))
    assert b['chunk_frames']==32
    t=settings.make_plan(source,settings.configuration(cache_mode='stream',preset='tested',resolution='4K',orientation='portrait',duration_seconds=.1))
    assert (t['tile_width'],t['tile_height'],t['xs'],t['ys'])==(320,960,[0,220],[0])


def test_actual_overlap_normalization_for_nondivisible_and_triple_coverage():
    xs=settings.positions(500,256,64)
    assert xs==[0,192,244]
    coverage=np.zeros(2000,np.float32);acc=np.zeros(2000,np.float32)
    for i,x in enumerate(xs):
        w=engine.axis_weight(256,xs,i);coverage[x*4:x*4+1024]+=w;acc[x*4:x*4+1024]+=w*127
    assert np.all(coverage>0)
    assert np.rint(acc/coverage).astype(np.uint8).min()==127
    assert np.rint(acc/coverage).astype(np.uint8).max()==127


def test_stream_preparation_is_metadata_only(source,tmp_path,fake_backend):
    result=ToolBoxFlashVSRUpscale().upscale(source,config(tmp_path))
    video,text=result['result'];info=json.loads(text)
    assert info['status']=='prepared' and info['model_load_count']==0 and fake_backend==[]
    assert not video.file.exists()


def test_three_modes_have_identical_preencode_pixels_and_preserve_tail_audio(source,tmp_path,fake_backend):
    hashes=[]
    for mode in ['raw','lossless','stream']:
        video=FlashVideo(settings.make_plan(source,config(tmp_path/mode,mode)))
        video.build_cache()
        assert video.info['status']==('prepared' if mode=='stream' else 'upscaled')
        dest=tmp_path/(mode+'.mp4');info=video.encode(dest,encoder='libx264',preset='ultrafast')
        hashes.append(info['preencode_rgb_sha256'])
        meta=settings.probe(dest);v=next(x for x in meta['streams'] if x['codec_type']=='video')
        assert (v['width'],v['height'],int(v['nb_frames']))==(768,512,9)
        assert v['avg_frame_rate']=='24/1'
        assert any(x['codec_type']=='audio' for x in meta['streams'])
        assert info['tile_calls']==6 and info['frames_produced']==9
        assert json.loads(settings.json_text(info))['status']=='completed'
        assert not list(video.directory.rglob('*.rgb'))
    assert len(set(hashes))==1 and len(fake_backend)==3


def test_cached_reencoding_reuse_cleanup_and_generation_invalidation(source,tmp_path,fake_backend):
    cfg=config(tmp_path,'raw');p=settings.make_plan(source,cfg)
    a=FlashVideo(p);a.build_cache();before=ToolBoxFlashVSRUpscale.IS_CHANGED(source,cfg)
    a.encode(tmp_path/'one.mp4','libx264',preset='ultrafast')
    b=FlashVideo(p);b.build_cache();b.encode(tmp_path/'two.mp4','libx264',quality=24,preset='ultrafast')
    assert b.info['cache_reused'] and len(fake_backend)==1
    b.clear_cache()
    assert ToolBoxFlashVSRUpscale.IS_CHANGED(source,cfg)!=before
    a=FlashVideo(p);a.build_cache();assert len(fake_backend)==2
    cfg2=dict(cfg,cache_retention='cleanup_after_encode')
    assert settings.make_plan(source,cfg2)['signature']==p['signature']
    a.plan['config']['cache_retention']='cleanup_after_encode'
    a.encode(tmp_path/'three.mp4','libx264',preset='ultrafast')
    assert not a.file.exists() and not cache.read_manifest(a.directory)['complete']


@pytest.mark.parametrize('extra',[{'disk_budget_gib':.000001},{'memory_budget_gib':.01}])
def test_budget_preflight_stops_before_inference(source,tmp_path,fake_backend,extra):
    video=FlashVideo(settings.make_plan(source,config(tmp_path,'raw',**extra)))
    with pytest.raises(RuntimeError,match='budget'):
        video.build_cache()
    assert fake_backend==[]


def test_simulated_low_available_ram(source,tmp_path,monkeypatch,fake_backend):
    import psutil
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(available=128*1024**2))
    a=FlashVideo(settings.make_plan(source,config(tmp_path)))
    with pytest.raises(RuntimeError,match='RAM'):
        a.build_cache()
    assert fake_backend==[]


def test_auto_fallback_is_reported_but_explicit_encoder_does_not_fallback(monkeypatch):
    requested=[]
    monkeypatch.setattr(encoding,'nvenc_env',lambda:os.environ.copy())
    def run(cmd,**kwargs):
        codec=cmd[cmd.index('-c:v')+1];requested.append(codec)
        return SimpleNamespace(returncode=1 if codec.endswith('nvenc') else 0,stderr=b'not available')
    monkeypatch.setattr(encoding.subprocess,'run',run)
    plan=dict(width=7680,height=4320,fps='24')
    selected,_,reasons=encoding.select_encoder('auto',plan)
    assert selected=='libx264' and reasons and requested==['hevc_nvenc','libx264']
    requested.clear()
    with pytest.raises(RuntimeError,match='preflight'):
        encoding.select_encoder('hevc_nvenc',plan)
    assert requested==['hevc_nvenc']
    with pytest.raises(ValueError,match='preset'):encoding.codec_options('libx264',18,'p5')


def test_encode_failure_keeps_complete_cache(source,tmp_path,fake_backend,monkeypatch):
    a=FlashVideo(settings.make_plan(source,config(tmp_path,'raw',cache_retention='cleanup_after_encode')));a.build_cache()
    monkeypatch.setattr(encoding,'nvenc_env',lambda:(_ for _ in ()).throw(RuntimeError('no driver')))
    with pytest.raises(RuntimeError,match='preflight'):a.encode(tmp_path/'bad.mp4','hevc_nvenc')
    assert a.file.exists() and cache.read_manifest(a.directory)['complete']


def test_inference_cancellation_removes_partial_files(source,tmp_path,monkeypatch,fake_backend):
    import toolbox_flashvsr_test.video as video_module
    count=[0]
    def cancel():
        count[0]+=1
        if count[0]>12:raise RuntimeError('cancelled')
    monkeypatch.setattr(video_module,'interrupt',cancel)
    a=FlashVideo(settings.make_plan(source,config(tmp_path,'raw')))
    with pytest.raises(RuntimeError,match='cancelled'):a.build_cache()
    assert not a.file.exists() and not list(a.directory.rglob('*.rgb')) and not list(a.directory.glob('*.part*'))


def test_standard_video_save_to_and_materialization_guard(source,tmp_path,fake_backend):
    a=FlashVideo(settings.make_plan(source,config(tmp_path,'stream')));a.build_cache()
    dest=tmp_path/'standard.mp4';a.save_to(dest,codec='h264',crf=22,preset='ultrafast')
    assert settings.probe(dest)['streams'][0]['width']==768
    b=FlashVideo(settings.make_plan(source,config(tmp_path,'raw')));b.build_cache()
    b.plan['config']['memory_budget_gib']=.001
    with pytest.raises(RuntimeError,match='materializes'):b.get_components()


def test_file_paths_do_not_allow_escape(source,tmp_path):
    from toolbox_flashvsr_test.nodes import ToolBoxVideoEncode
    with pytest.raises(ValueError,match='relative'):ToolBoxVideoEncode().encode(source,filename_prefix='../escape')
    with pytest.raises(ValueError,match='filenames'):settings.configuration(dit='../weights.safetensors')


def test_simulated_full_disk_stops_during_stream_preparation(source,tmp_path,monkeypatch,fake_backend):
    monkeypatch.setattr(resources.shutil,'disk_usage',lambda path:SimpleNamespace(free=64*1024**2))
    a=FlashVideo(settings.make_plan(source,config(tmp_path)))
    with pytest.raises(RuntimeError,match='free'):a.build_cache()
    assert fake_backend==[]


def test_rotation_metadata_is_not_silently_reshaped(source,tmp_path):
    rotated=tmp_path/'rotated.mp4'
    result=subprocess.run(['ffmpeg','-v','error','-display_rotation:v:0','90','-i',source.get_stream_source(),'-c','copy',str(rotated)],capture_output=True)
    if result.returncode:
        subprocess.run(['ffmpeg','-v','error','-y','-i',source.get_stream_source(),'-c','copy','-metadata:s:v:0','rotate=90',str(rotated)],check=True)
    assert any(x.get('rotation') for s in settings.probe(rotated)['streams'] for x in s.get('side_data_list',[]))
    with pytest.raises(ValueError,match='rotation'):settings.make_plan(VideoFromFile(str(rotated)),config(tmp_path))


def test_cleanup_refuses_foreign_directories_and_symlinks(source,tmp_path):
    p=settings.make_plan(source,config(tmp_path,'raw'));target=tmp_path/p['signature'];target.mkdir()
    foreign=target/'foreign.txt';foreign.write_text('keep me')
    with pytest.raises(ValueError,match='non-owned'):FlashVideo(p)
    assert foreign.read_text()=='keep me'
    target.rename(tmp_path/'foreign');target.symlink_to(tmp_path/'foreign',target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):FlashVideo(p)
    assert (tmp_path/'foreign/foreign.txt').read_text()=='keep me'


def test_final_writer_budget_check_precedes_atomic_publish(source,tmp_path):
    class Guard:
        samples=0
        def sample(self):self.samples+=1
        def check(self):
            if self.samples>1:raise RuntimeError('final cache quota exceeded')
    p=dict(source=source.get_stream_source(),width=128,height=128,fps='24',frames=2,start_seconds=0,duration_seconds=2/24)
    path=tmp_path/'existing.mp4';path.write_bytes(b'previous file is preserved')
    with pytest.raises(RuntimeError,match='quota'):
        encoding.write_video([np.zeros((128,128,3),np.uint8)]*2,p,path,'libx264',preset='ultrafast',guard=Guard())
    assert path.read_bytes()==b'previous file is preserved'
    assert not list(tmp_path.glob('*.part*'))


def test_final_video_cannot_collide_with_its_managed_cache(source,tmp_path,fake_backend):
    a=FlashVideo(settings.make_plan(source,config(tmp_path,'raw')));a.build_cache()
    with pytest.raises(ValueError,match='outside'):
        a.encode(a.directory/'result.mp4','libx264')
    assert a.file.exists() and cache.read_manifest(a.directory)['complete']
