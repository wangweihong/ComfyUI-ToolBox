"""Local audio measurements and deterministic H3 choreography (no language model)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def validate_audio(signal, sample_rate, minimum_seconds=19.0):
    signal = np.asarray(signal, dtype=np.float32)
    if signal.ndim == 1:
        signal = signal[:, None]
    if signal.ndim != 2 or not len(signal) or sample_rate <= 0:
        raise ValueError("音频须为非空 [samples, channels] 波形，采样率须为正数。")
    if not np.isfinite(signal).all():
        raise ValueError("音频包含 NaN 或无穷数。")
    if len(signal) / sample_rate < minimum_seconds:
        raise ValueError(f"音频过短：至少需要 {minimum_seconds:g} 秒，以便从第4秒之后选取15秒。")
    if np.max(np.abs(signal)) < 1e-5 or np.sqrt(np.mean(signal.astype(np.float64) ** 2)) < 1e-6:
        raise ValueError("音频为静音或音量过低，无法可靠分析节拍。")
    return signal


def select_start(beats, downbeats, total_seconds, times, energy, duration=15.0):
    """Choose a measured downbeat using tempo stability, energy and beat coverage."""
    candidates = downbeats[(downbeats >= 4) & (downbeats <= min(20, total_seconds-duration))]
    if not len(candidates):
        raise ValueError("第4–20秒内没有可用的小节首拍或后续不足15秒；请换音乐或手动使用librosa模式。")
    scores = []
    median_energy = max(float(np.median(energy)), 1e-9)
    for start in candidates:
        local = beats[(beats >= start-0.03) & (beats < start+duration)]
        if len(local) < 8:
            continue
        intervals = np.diff(local)
        cv = float(np.std(intervals) / max(np.mean(intervals), 1e-9))
        e = energy[(times >= start) & (times < start+duration)]
        coverage = float((local[-1]-local[0]) / duration)
        score = coverage - 3*cv + .1*min(float(np.mean(e))/median_energy, 2)
        scores.append((score, float(start), cv))
    if not scores:
        raise ValueError("候选片段内可用拍点不足8个，无法安排编舞。")
    best = max(scores, key=lambda x: (x[0], -x[1]))
    return best[1], [{"start_seconds": s, "score": v, "interval_cv": cv} for v,s,cv in scores]


def analyze(signal, sample_rate, backend="beat_this", checkpoint=None, supplied_beats=None):
    """Return original-rate crop, auditable measurements and click-overlay audio."""
    import librosa

    signal = validate_audio(signal, sample_rate)
    mono = signal.mean(axis=1)
    y = librosa.resample(mono, orig_sr=sample_rate, target_sr=22050)
    sr, hop = 22050, 220
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    spectrum = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    low = np.sqrt(np.mean(spectrum[librosa.fft_frequencies(sr=sr, n_fft=2048) < 180]**2, axis=0))
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    fallback_note = ""
    if supplied_beats is not None:
        beats, downbeats = supplied_beats
    elif backend == "beat_this":
        from beat_this.inference import Audio2Beats
        import torch
        if not checkpoint or not Path(checkpoint).is_file():
            raise RuntimeError("Beat This! final0权重缺失。请先安装权重；不会静默改用librosa。")
        try:
            with torch.inference_mode():
                tracker = Audio2Beats(checkpoint_path=str(checkpoint), device="cpu", dbn=False)
                beats, downbeats = tracker(y, sr)
            del tracker
        except Exception as exc:
            raise RuntimeError(f"Beat This! 本地分析失败，请检查依赖/权重，或手动选择librosa：{exc}") from exc
    elif backend == "librosa":
        _, beats = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset, hop_length=hop, units="time")
        # Phase is deliberately not presented as a detected bar/downbeat.
        downbeats = np.asarray(beats)[::4]
        fallback_note = "librosa后备模式：每4拍分组仅为编舞计数，未检测可靠的小节首拍。"
    else:
        raise ValueError(f"未知分析后端：{backend}")
    beats, downbeats = (np.asarray(v, dtype=float) for v in (beats, downbeats))
    if len(beats) < 8 or not np.isfinite(beats).all() or np.any(np.diff(beats) <= 0):
        raise ValueError("拍点过少、非有限或顺序错误。")
    if not len(downbeats) or not np.isfinite(downbeats).all() or np.any(np.diff(downbeats) <= 0):
        raise ValueError("缺少有效、递增的小节首拍/后备分组起点。")
    start, candidates = select_start(beats, downbeats, len(signal)/sample_rate, times, rms)
    offset = round(start*sample_rate)
    start = offset/sample_rate
    clip = signal[offset:offset+15*sample_rate].copy()
    if len(clip) != 15*sample_rate:
        raise ValueError("音频截取长度不足15秒。")
    local_beats = beats[(beats >= start-1/sample_rate) & (beats < start+15)]-start
    local_beats = np.maximum(local_beats, 0)
    local_down = downbeats[(downbeats >= start-1/sample_rate) & (downbeats < start+15)]-start
    local_down = np.maximum(local_down, 0)
    def norm(v):
        return v/max(float(np.percentile(v, 95)), 1e-9)
    onset_times = librosa.frames_to_time(np.arange(len(onset)), sr=sr, hop_length=hop)
    strengths = np.interp(local_beats+start, onset_times, norm(onset))
    bass = np.interp(local_beats+start, times[:len(low)], norm(low))
    weights = .6*strengths + .4*bass
    ibi = np.diff(local_beats)
    tempo = float(60/np.median(ibi))
    warning = [fallback_note] if fallback_note else []
    if not 90 <= tempo <= 150:
        warning.append("实测速度偏离目标120 BPM；请试听排查半速/倍速，未强制改写拍点。")
    if np.std(ibi)/np.mean(ibi) > .12:
        warning.append("拍间隔变化较大，时间表仅作为动作指导。")
    curve_indices = np.flatnonzero((times >= start) & (times < start+15))[::10]
    data = {
        "schema_version": 1, "backend": backend, "checkpoint": str(checkpoint) if backend=="beat_this" else None,
        "downbeats_detected": backend=="beat_this", "duration_seconds": 15.0,
        "source_duration_seconds": len(signal)/sample_rate, "source_sample_rate": int(sample_rate),
        "source_float32_sha256": hashlib.sha256(signal.astype('<f4').tobytes()).hexdigest(),
        "crop_start_seconds": start, "crop_start_sample": offset, "crop_samples": len(clip),
        "clip_float32_sha256": hashlib.sha256(clip.astype('<f4').tobytes()).hexdigest(),
        "bpm_median": tempo, "bpm_interval_range": [float(60/np.max(ibi)), float(60/np.min(ibi))],
        "beat_interval_cv": float(np.std(ibi)/np.mean(ibi)),
        "beats": [{"index": i+1, "seconds": round(float(t),6), "frame_24fps": min(359,round(float(t)*24)),
                   "accent": round(float(weights[i]),4), "is_downbeat": bool(np.any(np.abs(local_down-t)<.04)) and backend=="beat_this"}
                  for i,t in enumerate(local_beats)],
        "downbeat_seconds": [round(float(t),6) for t in local_down] if backend=="beat_this" else [],
        "group_start_seconds": [round(float(t),6) for t in local_down],
        "energy_curve": [{"seconds":round(float(times[i]-start),4),"rms":float(rms[i]),"bass":float(low[i])} for i in curve_indices],
        "selection_candidates": candidates, "warnings": warning,
        "measurement_note": "算法估计，非人工真值。提示词中的120 BPM未用于覆盖检测结果。",
    }
    click = np.zeros(len(clip), dtype=np.float32)
    for t in local_beats:
        is_down = np.any(np.abs(local_down-t)<.04)
        length = round(.045*sample_rate)
        x = np.arange(length)/sample_rate
        tone = np.sin(2*np.pi*(1200 if is_down else 800)*x)*np.exp(-x*90)
        pos = round(t*sample_rate)
        end = min(pos+length,len(click))
        click[pos:end] += tone[:end-pos]*(.35 if is_down else .22)
    click_mix = np.clip(clip*.7 + click[:,None], -1, 1)
    return clip, data, click_mix


COMMON = """subject_definitions:
<Subject 1> is the adult woman in <Picture 1>, with a short copper-red bob, teal sleeveless sportswear with an orange waistband, and white athletic shoes. Preserve her face, build, hairstyle and complete outfit.
<Audio 1> is the supplied instrumental music and the exact soundtrack for the entire clip.
summary:
[video generation + reference] One continuous fifteen-second photorealistic studio dance performance by <Subject 1>, synchronized to <Audio 1>.
retention_analysis:
<Subject 1>: fully_preserved - Use <Picture 1> for identity and clothing.
<Audio 1>: fully_preserved - Keep its timing, rhythm and music throughout.
detailed_description:
[Shot 1] A locked eye-level camera shows the dancer's full body, including both shoes and space above her head and beside her arms. Plain light gray studio floor and background, soft even lighting. She stays near the center with grounded foot contacts, naturally bent knees, relaxed shoulders and a confident friendly expression. No cuts, zooms, additional people, visible writing or wardrobe changes.
"""
ENDING = """
overall_soundscape:
Only the provided music soundtrack; no speech, singing or added sound effects.
non_diegetic_music:
Use <Audio 1> unchanged from the start to the end, with continuous synchronization.
"""


def choreography(data, override=""):
    beats = data["beats"]
    if len(beats) < 8:
        raise ValueError("至少需要8个有效拍点。")
    baseline = COMMON + "The woman dances naturally and dynamically to the beat of <Audio 1>, with a relaxed funk/pop street-dance groove and continuous fluent movement.\n" + ENDING
    patterns = [
        ("左右step-touch与轻柔弹动", "Perform alternating left and right step-touches with a soft knee bounce on each beat. Shift the body's weight onto each planted foot; let the arms swing naturally in opposition."),
        ("侧步配前臂摆动", "Continue into small side steps, alternating the weight left and right. Swing bent forearms across the torso on accented beats and reopen them smoothly between beats."),
        ("原地脚步配肩部律动", "Keep a grounded alternating two-step near the center. Add relaxed shoulder grooves and short forward hand pushes on accented beats, retracting the hands smoothly."),
        ("侧步回中与连贯收势", "Use two small lateral steps, return to the center with the same groove, and gradually reduce the arm range toward a balanced soft-knee finishing pose without abruptly freezing."),
    ]
    timeline = []
    for i, first in enumerate(range(0,len(beats),8)):
        group=beats[first:first+8]
        start=0.0 if first==0 else group[0]["seconds"]
        end=beats[first+8]["seconds"] if first+8<len(beats) else 15.0
        label, action=patterns[min(i,3)]
        accents=sorted(group,key=lambda b:b["accent"],reverse=True)[:2]
        accents=sorted(b["seconds"] for b in accents)
        timeline.append({"start_seconds":start,"end_seconds":end,"beat_start":first+1,"beat_end":first+len(group),
                         "action_zh":label,"instruction_en":action,"accent_seconds":accents})
    lines=[f"The measured musical pulse is approximately {data['bpm_median']:.1f} BPM. Follow the actual music, treating the times below as choreographic guidance. Maintain momentum through every transition."]
    for entry in timeline:
        hits=", ".join(f"{t:.2f}s" for t in entry["accent_seconds"])
        lines.append(f"From {entry['start_seconds']:.2f}s to {entry['end_seconds']:.2f}s (counts {entry['beat_start']}–{entry['beat_end']}): {entry['instruction_en']} Emphasize visible weight shifts or arm accents around {hits}, following the audible groove.")
    compiled=COMMON + "\n".join(lines) + ENDING
    if override.strip():
        compiled=override.strip()
    table="| 片段时间 | 拍数 | 动作 | 重音时间 |\n|---|---|---|---|\n"
    table+="\n".join(f"| {e['start_seconds']:.2f}–{e['end_seconds']:.2f}s | {e['beat_start']}–{e['beat_end']} | {e['action_zh']} | "+", ".join(f"{t:.2f}s" for t in e['accent_seconds'])+" |" for e in timeline)
    return baseline,compiled,table,timeline


def save_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
