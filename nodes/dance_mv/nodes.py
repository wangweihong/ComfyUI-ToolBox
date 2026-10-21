"""ToolBox DanceMV nodes; legacy workflow IDs and sockets are preserved."""
from pathlib import Path
import json

from .dance_core import analyze, choreography, save_json


def output_dir(prefix):
    import folder_paths
    base=Path(folder_paths.get_output_directory()).resolve()
    target=(base/prefix).resolve()
    if not target.is_relative_to(base):
        raise ValueError("输出前缀必须位于ComfyUI output目录内。")
    target.mkdir(parents=True,exist_ok=True)
    return target


def array_audio(value):
    import torch
    if not isinstance(value.get("waveform"),torch.Tensor) or value["waveform"].ndim!=3 or value["waveform"].shape[0]!=1:
        raise ValueError("需要单条AUDIO，waveform形状为[1, channels, samples]。")
    return value["waveform"][0].detach().float().cpu().T.numpy(),int(value["sample_rate"])


def audio_value(array,sr):
    import torch
    return {"waveform":torch.from_numpy(array.T.copy()).unsqueeze(0),"sample_rate":sr}


class DanceMVAnalyzeAudio:
    CATEGORY="ToolBox/DanceMV"
    RETURN_TYPES=("AUDIO","STRING","STRING","AUDIO")
    RETURN_NAMES=("音乐15秒","分析JSON","测量摘要","节拍点击试听")
    FUNCTION="run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"audio":("AUDIO",),"backend":(["beat_this","librosa"],),
                "output_prefix":("STRING",{"default":"videos/minimaxh3/dance_mv/dance/analysis"})}}

    def run(self,audio,backend,output_prefix):
        import folder_paths
        import soundfile as sf
        signal,sr=array_audio(audio)
        checkpoint=Path(folder_paths.models_dir)/"beat_this/final0.ckpt"
        clip,data,click=analyze(signal,sr,backend,checkpoint)
        dest=output_dir(output_prefix)
        sf.write(dest/"music_clip_15s.wav",clip,sr,subtype="FLOAT")
        sf.write(dest/"beat_click_preview.wav",click,sr,subtype="FLOAT")
        save_json(dest/"beat_analysis.json",data)
        summary=f"{backend} | 实测 {data['bpm_median']:.2f} BPM | {len(data['beats'])}拍 | 原曲 {data['crop_start_seconds']:.6f}–{data['crop_start_seconds']+15:.6f}s\n"+"\n".join(data["warnings"])
        return audio_value(clip,sr),json.dumps(data,ensure_ascii=False),summary,audio_value(click,sr)


class DanceMVChoreography:
    CATEGORY="ToolBox/DanceMV/Legacy"
    DEPRECATED=True
    RETURN_TYPES=("STRING","STRING","STRING")
    RETURN_NAMES=("A基线提示词","B编舞提示词","中文动作表")
    FUNCTION="run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"analysis_json":("STRING",{"forceInput":True}),
                "manual_override":("STRING",{"multiline":True,"default":""}),
                "output_prefix":("STRING",{"default":"videos/minimaxh3/dance_mv/dance/analysis"})}}

    def run(self,analysis_json,manual_override,output_prefix):
        baseline,compiled,table,timeline=choreography(json.loads(analysis_json),manual_override)
        dest=output_dir(output_prefix)
        (dest/"prompt_A_baseline.txt").write_text(baseline,encoding="utf-8")
        (dest/"prompt_B_choreography.txt").write_text(compiled,encoding="utf-8")
        (dest/"动作时间表.md").write_text(table+"\n",encoding="utf-8")
        save_json(dest/"choreography.json",{"timeline":timeline,"manual_override_used":bool(manual_override.strip())})
        return baseline,compiled,table


class DanceMVSaveWav:
    CATEGORY="ToolBox/DanceMV"
    RETURN_TYPES=("AUDIO","STRING")
    RETURN_NAMES=("audio","wav_path")
    FUNCTION="run"
    OUTPUT_NODE=True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"audio":("AUDIO",),"output_prefix":("STRING",{"default":"videos/minimaxh3/dance_mv/dance/music"}),
                "filename":("STRING",{"default":"music3_funk_120bpm_40s.wav"})}}

    def run(self,audio,output_prefix,filename):
        import soundfile as sf
        import folder_paths
        if Path(filename).name!=filename or not filename.endswith('.wav'):
            raise ValueError("文件名必须为不带路径的.wav名称。")
        signal,sr=array_audio(audio)
        dest=output_dir(output_prefix)/filename
        sf.write(dest,signal,sr,subtype="FLOAT")
        relative=dest.relative_to(Path(folder_paths.get_output_directory()).resolve())
        return {"ui":{"audio":[{"filename":relative.name,"subfolder":str(relative.parent),"type":"output"}]},"result":(audio,str(dest))}


class DanceMVAfterVideo:
    """Make B's conditioning wait for A's fully decoded/encoded video."""
    CATEGORY="ToolBox/DanceMV/Legacy"
    DEPRECATED=True
    RETURN_TYPES=("CONDITIONING",)
    FUNCTION="run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"prior_video":("VIDEO",),"conditioning":("CONDITIONING",)}}

    def run(self,prior_video,conditioning):
        return (conditioning,)


class DanceMVIntentPlanner:
    CATEGORY="ToolBox/DanceMV"
    RETURN_TYPES=("STRING","STRING","STRING")
    RETURN_NAMES=("自动H3提示词","音乐与动作时间表","本地编排JSON")
    FUNCTION="run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":{"analysis_json":("STRING",{"forceInput":True}),
            "user_actions":("STRING",{"multiline":True,"default":"有力量的街舞，动作随重音增强，具体编排由系统决定"}),
            "model":(["Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf"],),
            "seed":("INT",{"default":20261021,"min":0,"max":2**32-1,"control_after_generate":True}),
            "output_prefix":("STRING",{"default":"videos/minimaxh3/dance_mv/dance/intent"})}}

    def run(self,analysis_json,user_actions,model,seed,output_prefix):
        import folder_paths
        from .intent_planner import generate_plan,compile_plan
        data=json.loads(analysis_json)
        plan,metadata=generate_plan(data,user_actions,Path(folder_paths.models_dir)/'LLM'/model,seed)
        prompt,table,timeline=compile_plan(data,user_actions,plan)
        dest=output_dir(output_prefix)
        save_json(dest/'planner_input_and_inference.json',metadata)
        save_json(dest/'local_action_plan.json',plan)
        save_json(dest/'measured_action_timeline.json',timeline)
        (dest/'user_actions.txt').write_text(user_actions+'\n',encoding='utf-8')
        (dest/'generated_h3_prompt.txt').write_text(prompt,encoding='utf-8')
        (dest/'音乐与动作时间表.md').write_text(table,encoding='utf-8')
        return prompt,table,json.dumps(plan,ensure_ascii=False,indent=2)


NODE_CLASS_MAPPINGS={c.__name__:c for c in (DanceMVAnalyzeAudio,DanceMVChoreography,DanceMVSaveWav,DanceMVAfterVideo,DanceMVIntentPlanner)}
NODE_DISPLAY_NAME_MAPPINGS={
    "DanceMVAnalyzeAudio":"tb-dance-audio-analysis",
    "DanceMVIntentPlanner":"tb-dance-intent-planner",
    "DanceMVSaveWav":"tb-dance-save-wav",
    "DanceMVChoreography":"tb-dance-template-legacy",
    "DanceMVAfterVideo":"tb-dance-after-video-legacy",
}
