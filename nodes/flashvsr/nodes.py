"""ToolBox node schemas. No FlashVSR/Triton/model imports at registration."""
from pathlib import Path
from .settings import CACHE_MODES, PRESETS, WEIGHTS, configuration, json_text, make_plan


class ToolBoxFlashVSRConfig:
    RETURN_TYPES=('TOOLBOX_FLASHVSR_CONFIG',)
    RETURN_NAMES=('config',)
    FUNCTION='configure'
    CATEGORY='ToolBox/FlashVSR'
    DESCRIPTION='选择缓存方式和资源参数；未选择缓存方式不会加载模型。帧率0保留原片，时长0处理到片尾。空间参数单位为LQ像素。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'cache_mode':(CACHE_MODES,{'default':'请选择','tooltip':'raw：完整RGB8缓存，速度/重编码方便但磁盘较大；lossless：FFV1无损压缩，空间随内容变化且增加编解码；stream：低磁盘，推理在编码节点执行，重编码需重推理。10秒8K24fps原始帧约22.3GiB，另有分块暂存。'}),
            'preset':(PRESETS,{'default':'low_memory','tooltip':'low_memory=8帧/256×256/重叠32；balanced=32帧/384×384/重叠64；tested仅复用本机已测几何；custom使用下方高级数值。不自动试探缩块。'}),
            'resolution':(['2K','4K','8K'],{'default':'4K'}),
            'orientation':(['auto','portrait','landscape'],{'default':'auto','tooltip':'auto按原片画幅选择目标方向；保持比例，必要时灰边适配，不居中裁掉主体。'}),
            'fps':('FLOAT',{'default':0.,'min':0.,'max':240.,'step':.01,'tooltip':'0保留原片平均帧率；非零显式重采样为指定恒定帧率。'}),
            'start_seconds':('FLOAT',{'default':0.,'min':0.,'max':86400.,'step':.01}),
            'duration_seconds':('FLOAT',{'default':0.,'min':0.,'max':86400.,'step':.01,'tooltip':'0处理到片尾，保持尾段帧数。'}),
            'seed':('INT',{'default':20261018,'min':0,'max':2147483647,'control_after_generate':True}),
            'tile_storage':(['disk','ram'],{'default':'disk','tooltip':'每段空间块的暂存方式，与整段缓存模式独立。disk降低分块累计内存；ram更依赖可用RAM。'}),
            'cache_retention':(['cleanup_after_encode','keep'],{'default':'cleanup_after_encode','tooltip':'磁盘缓存：编码成功后清理或保留供重编码。失败不删除完整缓存；stream无需整段缓存。'}),
        },'optional':{
            'chunk_frames':('INT',{'default':8,'min':1,'max':240,'tooltip':'custom预设生效。减小可降低内存，但增加分段边界/开销。'}),
            'tile_width':('INT',{'default':256,'min':128,'max':2048,'step':32,'tooltip':'custom：LQ空间块宽，要求32对齐，输出块宽为4倍。'}),
            'tile_height':('INT',{'default':256,'min':128,'max':2048,'step':32}),
            'overlap_x':('INT',{'default':32,'min':0,'max':2047,'tooltip':'custom：LQ横向重叠，小于块宽。'}),
            'overlap_y':('INT',{'default':32,'min':0,'max':2047}),
            'memory_budget_gib':('FLOAT',{'default':0.,'min':0.,'max':1024.,'step':.5,'tooltip':'ComfyUI整个进程树RSS上限，包含已有节点/共享映射。0不设此上限，仍检查可用内存余量。不是显存预算。'}),
            'memory_reserve_gib':('FLOAT',{'default':2.,'min':.25,'max':128.,'step':.25,'tooltip':'保留的主机可用RAM。协作式检查不能保证拦截瞬时OOM。'}),
            'disk_budget_gib':('FLOAT',{'default':0.,'min':0.,'max':100000.,'step':1.,'tooltip':'本任务临时缓存额度，0不设额度；FFV1实际大小依画面而定。'}),
            'disk_reserve_gib':('FLOAT',{'default':1.,'min':.25,'max':1024.,'step':.25}),
            'cache_directory':('STRING',{'default':'','tooltip':'留空使用ComfyUI临时目录。每个任务使用独立受管缓存子目录。'}),
            'attention':(['triton_block_sparse','sdpa'],{'default':'triton_block_sparse'}),
            **{k:('STRING',{'default':v,'tooltip':'models/FlashVSR下的文件名，不会自动下载模型。'}) for k,v in WEIGHTS.items()},
            'custom_width':('INT',{'default':0,'min':0,'max':8192,'step':4,'tooltip':'两个自定义尺寸均非零时覆盖分辨率预设，要求4对齐。0保留预设。'}),
            'custom_height':('INT',{'default':0,'min':0,'max':8192,'step':4}),
        }}

    def configure(self,**kwargs):
        return (configuration(**kwargs),)


class ToolBoxFlashVSRUpscale:
    RETURN_TYPES=('VIDEO','STRING')
    RETURN_NAMES=('video','info_json')
    FUNCTION='upscale'
    CATEGORY='ToolBox/FlashVSR'
    DESCRIPTION='raw/lossless模式在此完成超分；stream模式只准备任务，info_json.status=prepared，实际计算在保存/编码阶段发生。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'video':('VIDEO',),'config':('TOOLBOX_FLASHVSR_CONFIG',)}}

    @classmethod
    def IS_CHANGED(cls,video,config):
        from .cache import generation
        from .video import directory_for
        p=make_plan(video,config)
        return p['signature']+':'+str(generation(directory_for(p)))

    def upscale(self,video,config):
        from .video import FlashVideo
        result=FlashVideo(make_plan(video,config));result.build_cache()
        return {'ui':{'flashvsr_info':[json_text(result.info)]},'result':(result,json_text(result.info))}


class ToolBoxVideoEncode:
    RETURN_TYPES=('VIDEO','STRING')
    RETURN_NAMES=('video','info_json')
    FUNCTION='encode'
    CATEGORY='ToolBox/FlashVSR'
    OUTPUT_NODE=True
    DESCRIPTION='明确选择编码器、质量、容器及保存位置。自动模式记录实际编码器及回退原因；显式选择失败时报错，不强制NVENC。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'video':('VIDEO',),
            'encoder':(['auto','libx264','libx265','h264_nvenc','hevc_nvenc'],{'default':'auto','tooltip':'auto会按实际输出尺寸探测硬编码，不可用时回退CPU H.264并记录原因；指定编码器不可用则报错。CPU编码不等于CPU超分。'}),
            'quality':('INT',{'default':18,'min':0,'max':51,'tooltip':'CPU使用CRF，NVENC使用CQ；二者数值不代表完全相同的质量。'}),
            'preset':(['auto','ultrafast','veryfast','fast','medium','slow','p1','p2','p3','p4','p5','p6','p7'],{'default':'auto','tooltip':'auto=CPU fast或NVENC p5。请选择与编码器匹配的预设。'}),
            'container':(['mp4','mkv'],{'default':'mp4'}),
            'save_to':(['temp','output'],{'default':'temp'}),
            'filename_prefix':('STRING',{'default':'FlashVSR/video'}),
        }}

    def encode(self,video,encoder='auto',quality=18,preset='auto',container='mp4',save_to='temp',filename_prefix='FlashVSR/video'):
        import folder_paths
        from comfy_api.latest import ui,io
        from comfy_api.input_impl import VideoFromFile
        from .video import FlashVideo,encode_existing
        if not filename_prefix or Path(filename_prefix).is_absolute() or '..' in Path(filename_prefix).parts or '\\' in filename_prefix:
            raise ValueError('filename_prefix must be a relative path inside the selected ComfyUI destination.')
        if container not in ('mp4','mkv') or save_to not in ('temp','output'):
            raise ValueError('Invalid container/destination.')
        root=Path(folder_paths.get_output_directory() if save_to=='output' else folder_paths.get_temp_directory()).resolve()
        w,h=video.get_dimensions()
        full,name,counter,subfolder,_=folder_paths.get_save_image_path(filename_prefix,str(root),w,h)
        path=Path(full)/f'{name}_{counter:05}_.{container}'
        if not path.resolve().is_relative_to(root):
            raise ValueError('Output path escaped the selected destination.')
        info=video.encode(path,encoder,quality,preset) if isinstance(video,FlashVideo) else encode_existing(video,path,encoder,quality,preset)
        preview=ui.PreviewVideo([ui.SavedResult(path.name,subfolder,io.FolderType.output if save_to=='output' else io.FolderType.temp)])
        return {'ui':{**preview.as_dict(),'flashvsr_info':[json_text(info)]},'result':(VideoFromFile(str(path)),json_text(info))}


NODE_CLASS_MAPPINGS={c.__name__:c for c in (ToolBoxFlashVSRConfig,ToolBoxFlashVSRUpscale,ToolBoxVideoEncode)}
NODE_DISPLAY_NAME_MAPPINGS={'ToolBoxFlashVSRConfig':'FlashVSR Config · ToolBox','ToolBoxFlashVSRUpscale':'FlashVSR Upscale · ToolBox','ToolBoxVideoEncode':'Video Encode · ToolBox'}
