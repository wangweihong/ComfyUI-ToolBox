"""Measured music + user movement intent -> local semantic choreography -> H3."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np


SYSTEM = '''You are a choreographer planning a dance to a measured music excerpt.
The user provides movement intent, NOT a finished video prompt. The music measurements provide the actual beat grid, downbeats, per-beat accents and changing energy. Infer a suitable choreography from BOTH inputs.
Return only the JSON object requested. Do not output H3 reference tags, camera instructions, a soundtrack description or invented timestamps. Those are compiled separately from measured times.
For every supplied musical phrase, choose a concrete physically possible main movement, an accent gesture, and a transition into the next phrase. Honor the user's requested style, amplitude, body parts, sequence and exclusions. If the user delegates the choreography, invent fitting movements yourself. Vary the movements across phrases instead of repeating a generic step-touch template.
Use strong accents for decisive visible body hits, foot plants or arm gestures when appropriate to the requested style. Use lower-energy music moments for a controlled transition or reduced motion, unless the user explicitly requests constant intensity. Keep enough time to execute each movement. Do not assume that faster BPM always means higher energy. Only use the supplied data when explaining the musical choice. If bars are uncertain, do not claim exact bar detection.
Write performance_directive_en as a concise English translation of ALL the user's global movement requirements and exclusions, so restrictions remain explicit in the final video prompt. Write concise visual movement instructions in English for action_en, accent_action_en and transition_en. Write the interpretation, action_zh and musical_reason_zh in Chinese. Do not supply stage lighting, appearance, captions or new characters. Return phrases in the same order with the provided phrase_id values.'''


def musical_phrases(data):
    beats=data['beats']
    starts=[float(t) for t in data.get('group_start_seconds',[]) if 0<=t<15]
    if not starts or starts[0]>.08:starts.insert(0,0.0)
    starts[0]=0.0
    # Two measured bars per phrase; a short trailing fragment joins its predecessor.
    boundaries=starts[::2]
    minimum=max(1.0,2*60/data['bpm_median'])
    if len(boundaries)>1 and 15-boundaries[-1]<minimum:boundaries.pop()
    boundaries.append(15.0)
    curve=data['energy_curve'];times=np.array([e['seconds'] for e in curve]);rms=np.array([e['rms'] for e in curve])
    baseline=max(float(np.median(rms)),1e-9)
    output=[]
    for i,(start,end) in enumerate(zip(boundaries,boundaries[1:]),1):
        local=[b for b in beats if start-1e-5<=b['seconds']<end]
        if not local:continue
        energies=rms[(times>=start)&(times<end)]
        relative=float(np.mean(energies)/baseline) if len(energies) else 1.0
        accents=sorted(sorted(local,key=lambda b:b['accent'],reverse=True)[:min(3,len(local))],key=lambda b:b['seconds'])
        output.append({'phrase_id':i,'start_seconds':start,'end_seconds':end,'beat_count':len(local),
                       'energy_relative_to_clip_median':round(relative,3),
                       'energy_variation':round(float(np.std(energies)/max(np.mean(energies),1e-9)),3) if len(energies) else 0,
                       'strong_accent_seconds':[b['seconds'] for b in accents],
                       'downbeat_seconds':[t for t in data.get('downbeat_seconds',[]) if start-1e-5<=t<end],
                       'beats':[{k:b[k] for k in ('seconds','accent','is_downbeat')} for b in local]})
    return output


def plan_schema(count):
    fields=['action_zh','action_en','accent_action_en','transition_en','musical_reason_zh']
    props={k:{'type':'string'} for k in fields};props['phrase_id']={'type':'integer'}
    return {'type':'object','properties':{
        'music_interpretation_zh':{'type':'string'},'intent_interpretation_zh':{'type':'string'},'performance_directive_en':{'type':'string'},
        'phrases':{'type':'array','minItems':count,'maxItems':count,'items':{'type':'object','properties':props,'required':['phrase_id']+fields,'additionalProperties':False}}},
        'required':['music_interpretation_zh','intent_interpretation_zh','performance_directive_en','phrases'],'additionalProperties':False}


def validate_plan(plan,phrases):
    if not isinstance(plan,dict) or not isinstance(plan.get('phrases'),list) or len(plan['phrases'])!=len(phrases):
        raise ValueError('本地模型没有为每个实测乐句提供动作。')
    if not isinstance(plan.get('performance_directive_en'),str) or len(plan['performance_directive_en'].strip())<5:
        raise ValueError('本地模型须完整翻译用户的整体动作要求和禁止事项。')
    for row,measured in zip(plan['phrases'],phrases):
        if row.get('phrase_id')!=measured['phrase_id']:raise ValueError('乐句ID必须按输入顺序匹配，不能自行改写时间。')
        for k in ('action_zh','action_en','accent_action_en','transition_en','musical_reason_zh'):
            if not isinstance(row.get(k),str) or len(row[k].strip())<3:raise ValueError(f'动作字段缺失：{k}')
        if any(k in row for k in ('start_seconds','end_seconds')):raise ValueError('乐句时间由音频测量决定，模型不能虚构时间。')
    return plan


def generate_plan(data,user_actions,model_path,seed=20261021):
    """Load an existing local GGUF, generate constrained JSON, then release VRAM."""
    if not user_actions.strip():raise ValueError('请填写用户想要的动作或舞蹈风格，无需输入成品提示词。')
    if not Path(model_path).is_file():raise RuntimeError(f'本地编排模型不存在：{model_path}')
    import comfy.model_management as mm
    import llama_cpp
    from llama_cpp import Llama,LlamaGrammar
    from llama_cpp.llama_chat_format import Jinja2ChatFormatter
    phrases=musical_phrases(data)
    payload={'user_movement_intent':user_actions,'music':{
        'duration_seconds':15,'measured_bpm':data['bpm_median'],
        'downbeats_detected':data['downbeats_detected'],'measurement_warnings':data['warnings'],
        'phrases':phrases},'required_output_schema':plan_schema(len(phrases))}
    mm.throw_exception_if_processing_interrupted();mm.unload_all_models();mm.soft_empty_cache()
    llm=Llama(model_path=str(model_path),n_ctx=12288,n_gpu_layers=99,seed=seed,verbose=False)
    started=time.monotonic();raw=''
    try:
        template=llm.metadata.get('tokenizer.chat_template')
        if not template:raise ValueError('GGUF缺少本地对话模板。')
        def tok(n):return llm.detokenize([n],special=True).decode('utf-8') if n>=0 else ''
        formatter=Jinja2ChatFormatter(template=template,bos_token=tok(llm.token_bos()),eos_token=tok(llm.token_eos()),stop_token_ids=[n for n in (llm.token_eos(),llm.token_eot()) if n>=0])
        grammar=LlamaGrammar.from_json_schema(json.dumps(plan_schema(len(phrases))),verbose=False)
        prompt=json.dumps(payload,ensure_ascii=False)
        for attempt in range(2):
            formatted=formatter(messages=[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}],enable_thinking=False)
            tokens=llm.tokenize(formatted.prompt.encode('utf-8'),add_bos=not formatted.added_special,special=True)
            chunks=[]
            for chunk in llm.create_completion(prompt=tokens,max_tokens=2400,temperature=.35,top_p=.9,top_k=40,repeat_penalty=1.05,seed=seed,
                    stop=formatted.stop,stopping_criteria=formatted.stopping_criteria,grammar=grammar,reasoning_budget=0,stream=True):
                mm.throw_exception_if_processing_interrupted();chunks.append(chunk['choices'][0].get('text',''))
            raw=''.join(chunks).strip()
            try:
                plan=validate_plan(json.loads(raw),phrases);break
            except (ValueError,TypeError) as exc:
                if attempt:raise RuntimeError(f'本地编排输出校验失败：{exc}') from exc
                prompt=json.dumps(payload,ensure_ascii=False)+'\nPrevious JSON failed validation: '+str(exc)+'. Return a corrected JSON object.'
        metadata={'model_path':str(model_path),'llama_cpp_version':llama_cpp.__version__,'seed':seed,'seconds':time.monotonic()-started,
                  'user_actions':user_actions,'music_source_sha256':data['clip_float32_sha256'],'music_measurements':payload['music'],
                  'raw_model_output':raw,'system_instruction':SYSTEM,'input_payload':payload}
        return plan,metadata
    finally:
        llm.close();mm.soft_empty_cache()


def compile_plan(data,user_actions,plan):
    phrases=musical_phrases(data);validate_plan(plan,phrases)
    # Deterministic formatting, not hand-authored choreography: every action comes from the local planner.
    lines=['subject_definitions:',
        '<Subject 1> is the adult woman in <Picture 1>, with a copper-red bob, teal sportswear, an orange waistband and white sneakers. Preserve her appearance and outfit while her pose changes throughout the dance.',
        '<Audio 1> is the exact supplied music and soundtrack.',
        'summary:', 'A continuous fifteen-second full-body dance by <Subject 1> synchronized to <Audio 1>.',
        'retention_analysis:', '<Subject 1>: Preserve identity and clothing from <Picture 1>; use a continuously changing dance pose.',
        '<Audio 1>: Preserve the original music and its timing.',
        'detailed_description:',
        '[Shot 1] A fixed wide full-body camera in a gray dance studio. The complete body and both shoes remain in frame, with room for lateral travel and raised arms. The music drives the dance throughout. One dancer, stable studio lighting and one continuous shot.',
        f'Follow the measured musical pulse, approximately {data["bpm_median"]:.1f} BPM.',
        'Performance requirements: '+plan['performance_directive_en']]
    timeline=[]
    table='| 音乐时间 | 自动选择的动作 | 强拍处理 | 音乐依据 |\n|---|---|---|---|\n'
    for measured,row in zip(phrases,plan['phrases']):
        hits=', '.join(f'{t:.2f}s' for t in measured['strong_accent_seconds'])
        lines.append(f'From {measured["start_seconds"]:.2f}s to {measured["end_seconds"]:.2f}s: {row["action_en"]} On musical accents around {hits}: {row["accent_action_en"]} Transition: {row["transition_en"]}')
        timeline.append({**measured,**row})
        table+=f'| {measured["start_seconds"]:.2f}–{measured["end_seconds"]:.2f}s | {row["action_zh"]} | {hits} | {row["musical_reason_zh"]} |\n'
    lines.extend(['overall_soundscape:','The original instrumental music, with no extra voices or sound effects.','non_diegetic_music:','Use <Audio 1> throughout without changing its timing.'])
    return '\n'.join(lines)+'\n',table,timeline
