"""ComfyUI nodes for measured skin reference -> prompt -> check -> correction."""
import json
import uuid
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
import folder_paths

from . import core


def array(image):
    return image.detach().float().cpu().numpy()[...,:3]


def tensor(image):
    return torch.from_numpy(np.ascontiguousarray(image,dtype=np.float32))


def dumps(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)


def palette(sample):
    groups=sample['frames'][0]['groups'];im=Image.new('RGB',(720,170),'white');draw=ImageDraw.Draw(im)
    for i,kind in enumerate(['all','face','body']):
        item=groups.get(kind,groups['all']);x=i*240
        draw.rectangle((x+8,8,x+232,108),fill=tuple(int(np.floor(c+.5)) for c in item['rgb_median']))
        draw.text((x+8,113),f'{kind}: {item["hex"]}',fill='black')
        draw.text((x+8,134),str(item['rgb_median']),fill='black')
    return tensor(np.asarray(im,dtype=np.float32)[None]/255)


class H3SkinMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'layout':(['auto','single_person','character_sheet'],),
                'confidence':('FLOAT',{'default':.55,'min':.2,'max':.95,'step':.05}),
                'erode':('INT',{'default':2,'min':0,'max':8})},
                'optional':{'external_mask':('MASK',),'layout_report':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('H3_SKIN_MASK','MASK','IMAGE','STRING')
    RETURN_NAMES=('皮肤区域数据','皮肤遮罩','遮罩预览','分割报告')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,image,layout,confidence,erode,external_mask=None,layout_report=None):
        rgb=array(image)
        mask,packet,report=core.skin_masks(rgb,Path(folder_paths.models_dir)/'mediapipe'/core.MODEL_NAME,
                   layout,confidence,erode,None if external_mask is None else external_mask.detach().cpu().numpy(),
                   None if layout_report is None else json.loads(layout_report))
        preview=rgb.copy();preview=preview*.70+mask[...,None]*np.array([0.,.30,.12],dtype=np.float32)
        return packet,tensor(mask),tensor(np.clip(preview,0,1)),dumps({'method':packet['method'],'frames':report})


class H3SkinMeasure:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'skin_regions':('H3_SKIN_MASK',),
            'trim_low':('INT',{'default':20,'min':0,'max':45}),
            'trim_high':('INT',{'default':80,'min':55,'max':100}),
            'max_pixels':('INT',{'default':50000,'min':1000,'max':200000,'step':1000})}}
    RETURN_TYPES=('H3_SKIN_PROFILE','STRING','IMAGE')
    RETURN_NAMES=('肤色样本与统计','RGB与Lab取色报告','肤色色卡')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,image,skin_regions,trim_low,trim_high,max_pixels):
        sample=core.make_sample(array(image),skin_regions,trim_low,trim_high,max_pixels)
        return sample,dumps(core.public_sample(sample)),palette(sample)


class H3SkinPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'base_prompt':('STRING',{'forceInput':True}),'reference':('H3_SKIN_PROFILE',)}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('自动补充肤色后的提示词',)
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,base_prompt,reference):
        return (core.color_prompt(base_prompt,reference),)


class H3SkinCompare:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'reference':('H3_SKIN_PROFILE',),'target':('H3_SKIN_PROFILE',),
                            'threshold':('FLOAT',{'default':3.,'min':0.,'max':30.,'step':.5})}}
    RETURN_TYPES=('STRING','FLOAT','BOOLEAN')
    RETURN_NAMES=('生成肤色复测报告','区域中位ΔE76','需要局部校色')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,reference,target,threshold):
        records=core.distances(reference,target['frames']);summary=core.summarize(records)
        needed=any(r['delta_E76']>threshold for r in records)
        return dumps({'summary':summary,'regions':records,'threshold':threshold,'needs_correction':needed}),summary['median_delta_E76'],needed


class H3SkinCorrect:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'reference':('H3_SKIN_PROFILE',),'target':('H3_SKIN_PROFILE',),
            'needs_correction':('BOOLEAN',{'forceInput':True}),
            'mode':(['auto','off','always'],),
            'strength':('FLOAT',{'default':.75,'min':0.,'max':1.,'step':.05}),
            'threshold':('FLOAT',{'default':3.,'min':0.,'max':30.,'step':.5}),
            'max_L_shift':('FLOAT',{'default':18.,'min':0.,'max':30.,'step':1.}),
            'max_chroma_shift':('FLOAT',{'default':8.,'min':0.,'max':20.,'step':.5}),
            'feather':('FLOAT',{'default':6.,'min':0.,'max':32.,'step':1.})}}
    RETURN_TYPES=('IMAGE','MASK','STRING')
    RETURN_NAMES=('必要时局部校色的结果','实际校色区域','校色决策与前后数据')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,image,reference,target,needs_correction,mode,strength,threshold,max_L_shift,max_chroma_shift,feather):
        enabled=mode!='off' and (needs_correction or mode=='always')
        rgb,mask,report=core.correct_skin(array(image),reference,target,strength,
                           0. if mode=='always' else threshold,max_L_shift,max_chroma_shift,feather,enabled)
        return tensor(rgb),tensor(mask),dumps(report)


class H3SkinRecheck:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'reference':('H3_SKIN_PROFILE',),'before':('H3_SKIN_PROFILE',)}}
    RETURN_TYPES=('STRING','FLOAT','BOOLEAN')
    RETURN_NAMES=('固定取样点的校色后复测','校色后区域中位ΔE76','校色后确有改善')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,image,reference,before):
        after_frames=core.resample_fixed(array(image),before)
        old=core.summarize(core.distances(reference,before['frames']))
        new=core.summarize(core.distances(reference,after_frames))
        report={'before_summary':old,'after_summary':new,
                'improved':new['median_delta_E76']<old['median_delta_E76'],
                'sampling':'Before/after use exactly the same coordinates, masks and selected indices',
                'after_frames':after_frames}
        return dumps(report),new['median_delta_E76'],report['improved']


class H3SkinBoardLayout:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'image':('IMAGE',),'source_split':('FLOAT',{'default':.5,'min':.35,'max':.65,'step':.01})}}
    RETURN_TYPES=('IMAGE','STRING');RETURN_NAMES=('自动60/40排版展示板','排版检测报告')
    FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,image,source_split):
        outputs=[];reports=[]
        for im in array(image):
            board,report=core.reflow_board(im,source_split);outputs.append(board);reports.append(report)
        return tensor(np.stack(outputs)),dumps(reports)


class H3SkinSaveReport:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'reference_report':('STRING',{'forceInput':True}),
            'before_report':('STRING',{'forceInput':True}),'correction_report':('STRING',{'forceInput':True}),
            'after_report':('STRING',{'forceInput':True}),'augmented_prompt':('STRING',{'forceInput':True}),
            'layout_report':('STRING',{'forceInput':True}),
            'filename_prefix':('STRING',{'default':'h3_fizgig/skin_pipeline/measurement'})},
            'optional':{'baseline_report':('STRING',{'forceInput':True})}}
    RETURN_TYPES=('STRING',);RETURN_NAMES=('报告文件路径',)
    OUTPUT_NODE=True;FUNCTION='run';CATEGORY='ToolBox/SkinColor'
    def run(self,reference_report,before_report,correction_report,after_report,augmented_prompt,layout_report,filename_prefix,baseline_report=None):
        reference=json.loads(reference_report);before=json.loads(before_report)
        after=json.loads(after_report);correction=json.loads(correction_report)
        report={'reference':reference,'before':before,'correction':correction,'after':after,
                'prompt':augmented_prompt,'layout':json.loads(layout_report)}
        if baseline_report:
            baseline=json.loads(baseline_report);report['without_rgb_prompt_baseline']=baseline
            matched=core.matched_baseline_comparison(baseline['regions'],before['regions'],correction['after_errors'])
            report['matched_baseline_comparison']=matched
            report['rgb_prompt_only_improved']=matched['improved']
            report['rgb_prompt_only_delta_E_reduction']=matched.get('delta_E_reduction')
            report['rgb_prompt_only_small_effect']=matched.get('small_effect')
        root=Path(folder_paths.get_output_directory()).resolve()
        target=(root/filename_prefix).resolve()
        if not target.is_relative_to(root):raise ValueError('报告路径必须位于ComfyUI output目录内。')
        target.parent.mkdir(parents=True,exist_ok=True)
        path=target.parent/(target.name+'_'+uuid.uuid4().hex[:12]+'.json')
        path.write_text(dumps(report)+'\n',encoding='utf-8')
        summary={'before_delta_E76':before['summary']['median_delta_E76'],
                 'after_delta_E76':after['after_summary']['median_delta_E76'],
                 'improved':after['improved'],'report':str(path)}
        if baseline_report:summary['rgb_prompt_only_improved']=report['rgb_prompt_only_improved']
        return {'ui':{'text':[dumps(summary)]},'result':(str(path),)}


NODE_CLASS_MAPPINGS={cls.__name__:cls for cls in [H3SkinMask,H3SkinMeasure,H3SkinPrompt,H3SkinCompare,
    H3SkinCorrect,H3SkinRecheck,H3SkinBoardLayout,H3SkinSaveReport]}
NODE_DISPLAY_NAME_MAPPINGS={'H3SkinMask': '识别皮肤区域 · H3SkinMask', 'H3SkinMeasure': '提取RGB与Lab肤色 · H3SkinMeasure', 'H3SkinPrompt': '自动补充肤色提示词 · H3SkinPrompt', 'H3SkinCompare': '量化肤色偏差 · H3SkinCompare', 'H3SkinCorrect': '条件触发局部校色 · H3SkinCorrect', 'H3SkinRecheck': '固定取样点复测 · H3SkinRecheck', 'H3SkinBoardLayout': '三视图与细节60/40排版 · H3SkinBoardLayout', 'H3SkinSaveReport': '保存肤色闭环报告 · H3SkinSaveReport'}
