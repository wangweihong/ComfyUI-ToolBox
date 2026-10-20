"""Standard VIDEO handles for eager file caches and deferred streaming."""
import copy
import gc
import os
import shutil
import threading
import time
from fractions import Fraction
from pathlib import Path

from comfy_api.latest import Input, Types
from comfy_api.input_impl import VideoFromFile

from . import cache
from .encoding import select_encoder, write_video
from .engine import decode_frames, iter_upscaled
from .resources import GIB, Resources, preflight
from .settings import ALGORITHM_VERSION,WEIGHTS,configuration, file_source, json_text


def interrupt():
    import comfy.model_management as mm
    mm.throw_exception_if_processing_interrupted()


def directory_for(plan):
    import folder_paths
    root = Path(plan['config']['cache_directory'] or (Path(folder_paths.get_temp_directory())/'toolbox_flashvsr'))
    directory=root.resolve()/plan['signature']
    cache.validate_existing(directory,plan['signature'])
    return directory


def initial_info(plan):
    return dict(schema_version=1,algorithm_version=ALGORITHM_VERSION,status='prepared',cache_mode=plan['config']['cache_mode'],
                signature=plan['signature'], source=dict(name=Path(plan['source']).name,dimensions=plan['source_size'],fps_rational=plan['source_fps'],start_seconds=plan['start_seconds'],has_audio=plan['has_audio']),
                output=dict(width=plan['width'],height=plan['height'],frames=plan['frames'],fps=float(Fraction(plan['fps'])),fps_rational=plan['fps'],duration_seconds=plan['duration_seconds']),
                processing=dict(preset=plan['config']['preset'],chunk_frames=plan['chunk_frames'],
                                tile_width_lq=plan['tile_width'],tile_height_lq=plan['tile_height'],
                                tile_x_positions_lq=plan['xs'],tile_y_positions_lq=plan['ys'],tile_storage=plan['config']['tile_storage'],
                                overlap_x_lq=plan['overlap_x'],overlap_y_lq=plan['overlap_y'],
                                fit_lq={k:plan[k] for k in ('fit_width','fit_height','fit_x','fit_y')},
                                output_crop_origin=[plan['crop_x'],plan['crop_y']],scale=4,temporal=4,color_fix=False,
                                seed=plan['config']['seed'],attention=plan['config']['attention'],models={k:plan['config'][k] for k in WEIGHTS}),
                resource_limits={k:plan['config'][k] for k in ('memory_budget_gib','memory_reserve_gib','disk_budget_gib','disk_reserve_gib')},
                cache_retention=plan['config']['cache_retention'],
                estimates=plan['estimates'], model_load_count=0,decoder_load_count=0,tile_calls=0,frames_produced=0,
                timings=dict(model_load_seconds=0.,prepare_seconds=0.,denoise_seconds=0.,decode_seconds=0.,quantize_seconds=0.,compose_and_sink_seconds=0.),
                warnings=['Resource checks are cooperative and cannot guarantee interception of an instantaneous allocation/OOM.'] +
                         (['Tested geometry comes from RTX 5090 D / 94 GiB host; historical performance is not a portability guarantee.'] if plan['config']['preset']=='tested' else []))


class FlashVideo(Input.Video):
    def __init__(self, plan):
        self.plan = copy.deepcopy(plan)
        self.directory = directory_for(plan)
        self.info = initial_info(plan)
        self.busy = False
        self.lock = threading.Lock()
        cache.register(self)

    @property
    def file(self):
        name = 'frames.nut' if self.plan['config']['cache_mode']=='raw' else 'frames.mkv'
        return self.directory/name

    def _manifest(self, **extra):
        m = cache.read_manifest(self.directory)
        m.update(owner='toolbox_flashvsr',signature=self.plan['signature'],**extra)
        cache.write_manifest(self.directory,m)

    def build_cache(self):
        m=cache.ensure_owned(self.directory,self.plan['signature'])
        if self.plan['config']['cache_mode']=='stream':
            # Metadata only: never even import the model adapter here.
            self.directory.mkdir(parents=True,exist_ok=True)
            self._manifest(complete=False)
            self.info['preflight']=preflight(self.plan,self.directory)
            return
        if m.get('owner')=='toolbox_flashvsr' and m.get('complete') and self.file.is_file():
            self.info = copy.deepcopy(m['info']); self.info['cache_reused'] = True
            self.info['resource_limits']={k:self.plan['config'][k] for k in ('memory_budget_gib','memory_reserve_gib','disk_budget_gib','disk_reserve_gib')}
            self.info['cache_retention']=self.plan['config']['cache_retention']
            self.info['current_disk_free_bytes']=shutil.disk_usage(self.directory).free
            return
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('This FlashVSR cache is busy.')
        self.busy=True
        try:
            # Recover only our own incomplete leftovers after a killed process.
            for p in self.directory.glob('*.part.*'):
                p.unlink()
            if (self.directory/'tiles').exists():
                shutil.rmtree(self.directory/'tiles')
            self.info=initial_info(self.plan)
            self.info['preflight']=preflight(self.plan,self.directory)
            self._manifest(complete=False)
            started=time.monotonic()
            with Resources(self.plan['config'],self.directory,interrupt) as guard:
                write_video(iter_upscaled(self.plan,self.directory,self.info,guard),self.plan,self.file,
                            self.plan['config']['cache_mode'],guard=guard)
                guard.check()
            self.info.update(status='upscaled',upscale_resources=guard.info())
            self.info['timings']['upscale_with_cache_seconds']=time.monotonic()-started
            self.info['cache']=dict(valid=True,bytes=self.file.stat().st_size,format=self.file.suffix[1:])
            self._manifest(complete=True,file=self.file.name,info=self.info)
        except BaseException:
            self.file.unlink(missing_ok=True)
            self._manifest(complete=False)
            raise
        finally:
            self.busy=False;self.lock.release()

    def clear_cache(self):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Cannot clear an executing task.')
        try:
            cache.clear(self.directory,self.plan['signature'])
            self.info['cache']=dict(valid=False)
        finally:
            self.lock.release()

    def get_dimensions(self):
        return self.plan['width'],self.plan['height']

    def get_frame_count(self):
        return self.plan['frames']

    def get_frame_rate(self):
        return Fraction(self.plan['fps'])

    def get_duration(self):
        return self.plan['duration_seconds']

    def get_color_space(self):
        return 'sRGB'

    def get_container_format(self):
        return 'rawvideo' if self.plan['config']['cache_mode']=='stream' else self.file.suffix[1:]

    def get_stream_source(self):
        if self.plan['config']['cache_mode']=='stream':
            raise ValueError('Deferred FlashVSR VIDEO has no file yet. Connect it to ToolBox Video Encode or standard SaveVideo.')
        if not self.file.is_file():
            raise ValueError('Frame cache was cleared. Queue the Upscale node again before re-encoding.')
        return str(self.file)

    def get_components(self):
        import psutil
        required=self.plan['width']*self.plan['height']*self.plan['frames']*3*4
        cfg=self.plan['config']; available=psutil.virtual_memory().available-cfg['memory_reserve_gib']*GIB
        if cfg['memory_budget_gib']:
            available=min(available,cfg['memory_budget_gib']*GIB-psutil.Process().memory_info().rss)
        # Copies made by downstream IMAGE consumers need additional headroom.
        if required*2 > available:
            raise RuntimeError('This downstream operation materializes the whole VIDEO as float32 IMAGE frames and exceeds the RAM budget. Use streaming Video Encode/SaveVideo instead.')
        if self.plan['config']['cache_mode']=='stream':
            raise ValueError('Deferred stream cannot materialize IMAGE frames. Encode it first, or explicitly select a disk cache mode.')
        return VideoFromFile(self.get_stream_source()).get_components()

    def as_trimmed(self,*args,**kwargs):
        return VideoFromFile(self.get_stream_source()).as_trimmed(*args,**kwargs)

    def as_cropped(self,*args,**kwargs):
        return VideoFromFile(self.get_stream_source()).as_cropped(*args,**kwargs)

    def frames(self,guard):
        if self.plan['config']['cache_mode']=='stream':
            yield from iter_upscaled(self.plan,self.directory,self.info,guard)
        else:
            yield from decode_frames(self.get_stream_source(),self.plan['width'],self.plan['height'],self.plan['fps'],self.plan['frames'])

    def encode(self,path,encoder='auto',quality=18,preset='auto',metadata=None):
        if Path(path).resolve().is_relative_to(self.directory.resolve()):
            raise ValueError('Save the final video outside this managed frame-cache directory so cache cleanup cannot delete it.')
        if self.busy or not self.lock.acquire(blocking=False):
            raise RuntimeError('This FlashVSR video is already executing.')
        self.busy=True
        try:
            if self.plan['config']['cache_mode']=='stream':
                self.info=initial_info(self.plan)
                self.info['preflight']=preflight(self.plan,self.directory)
            else:
                self.get_stream_source()  # Fail before creating a final file if cleared.
            selected,env,reasons=select_encoder(encoder,self.plan,quality,preset)
            started=time.monotonic()
            with Resources(self.plan['config'],self.directory,interrupt) as guard:
                write_video(self.frames(guard),self.plan,path,selected,quality=quality,preset=preset,env=env,guard=guard,metadata=metadata)
                guard.check()
            self.info.update(status='completed',encoder=dict(requested=encoder,selected=selected,quality=quality,preset=preset,actual_preset=('p5' if selected.endswith('_nvenc') else 'fast') if preset=='auto' else preset,fallback_reasons=reasons),
                             encode_resources=guard.info(),video_file=str(path))
            key='stream_upscale_and_encode_seconds' if self.plan['config']['cache_mode']=='stream' else 'encode_seconds'
            self.info['timings'][key]=time.monotonic()-started
            if self.plan['config']['cache_mode']!='stream' and self.plan['config']['cache_retention']=='cleanup_after_encode':
                cache.clear(self.directory,self.plan['signature'])
                self.info['cache']=dict(valid=False,cleanup='after_successful_encode')
            return copy.deepcopy(self.info)
        finally:
            self.busy=False;self.lock.release();gc.collect()

    def save_to(self,path,format=Types.VideoContainer.AUTO,codec=Types.VideoCodec.AUTO,metadata=None,
                bit_depth=None,crf=None,color_space=None,preset=None):
        if not isinstance(path,(str,os.PathLike)):
            raise ValueError('Use a file destination; implicit encoded BytesIO buffering is disabled.')
        value=getattr(codec,'value',codec)
        mapping={'auto':'auto','h264':'libx264','hevc':'libx265','h265':'libx265'}
        if value not in mapping:
            raise ValueError('This FlashVSR VIDEO supports H.264/HEVC. Use ToolBox Video Encode for NVENC selection.')
        if bit_depth not in (None,8) or color_space not in (None,'auto','sRGB'):
            raise ValueError('FlashVSR output is RGB8 SDR/sRGB; HDR/10-bit conversion is not implicit.')
        self.encode(path,mapping[value],18 if crf is None else crf,preset or 'auto',metadata)


def encode_existing(video,path,encoder,quality,preset):
    """Also accept ordinary file-backed VIDEO objects; never call get_components."""
    source,meta,trim=file_source(video)
    s=next(s for s in meta['streams'] if s['codec_type']=='video')
    rate=video.get_frame_rate(); duration=video.get_duration()
    cfg=configuration(cache_mode='stream')
    plan=dict(source=str(source),source_size=[s['width'],s['height']],width=s['width'],height=s['height'],fps=str(rate),
              frames=int(float(rate)*duration+1e-4),start_seconds=trim[0],duration_seconds=duration,config=cfg)
    selected,env,reasons=select_encoder(encoder,plan,quality,preset)
    directory=Path(path).parent
    with Resources(cfg,directory,interrupt) as guard:
        write_video(decode_frames(source,plan['width'],plan['height'],plan['fps'],plan['frames'],plan['start_seconds']),
                    plan,path,selected,quality=quality,preset=preset,env=env,guard=guard)
        guard.check()
    return dict(schema_version=1,status='completed',video_file=str(path),output={k:plan[k] for k in ('width','height','frames','fps','duration_seconds')},
                encoder=dict(requested=encoder,selected=selected,fallback_reasons=reasons),encode_resources=guard.info())
