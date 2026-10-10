"""Public model-free examples for the upstream renderer and PSD exchange."""
import argparse
import copy
import json
from pathlib import Path
import urllib.parse
import urllib.request
from generate_stocking_effect_workflows import graphs as effect_graphs
from generate_stocking_function_workflows import workflow

ROOT = Path(__file__).resolve().parents[1]


def graphs():
    template = effect_graphs()[-1][1]
    def base():
        p=copy.deepcopy(template)
        p['2']['inputs'].update(style='coil',renderer_version='upstream_f74c8ac',effects_json='{}',layer_mode='soft')
        return p
    result=[]
    p=base();result.append(('10-Coil透肤线圈',p))
    p=base();p['3']={'class_type':'LoadImage','inputs':{'image':'tb_stocking_demo_depth.png'}}
    p['2']['inputs'].update(depth=['3',0],moire_on=True,moire=85,moire_area=70)
    result.append(('11-深度摩尔纹',p))
    p=base();p['2']['inputs'].update(style='oily',renderer_version='legacy')
    p['3']={'class_type':'NFStockingTexture','inputs':dict(p['2']['inputs'],renderer_version='upstream_f74c8ac')}
    p['4']={'class_type':'ParallelVideoComparison','inputs':{'image1':['1',0],'name1':'Original','image2':['2',0],'name2':'Legacy glossy','image3':['3',0],'name3':'New glossy'}}
    p['5']['inputs']['images']=['4',0];result.append(('12-新旧油光对比',p))
    p=base();p['2']['inputs'].update(style='lace',effects_json=json.dumps({'text':{'enabled':True,'content':'PARIS'},'damage':{'enabled':True,'mode':'both'}}))
    p['3']={'class_type':'ImageCompositeMasked','inputs':{'destination':['2',5],'source':['2',1],'mask':['2',2],'x':0,'y':0,'resize_source':False}}
    p['4']={'class_type':'InvertMask','inputs':{'mask':['2',2]}}
    p['6']={'class_type':'JoinImageWithAlpha','inputs':{'image':['2',1],'alpha':['4',0]}}
    p['7']={'class_type':'PreviewImage','inputs':{'images':['3',0]}}
    p['8']={'class_type':'PreviewImage','inputs':{'images':['6',0]}}
    result.append(('13-柔和图层与组合效果',p))
    p=base();p['1']={'class_type':'NFStockingPSDLoad','inputs':{'psd_file':'tb_stocking_guides.psd'}}
    p['2']['inputs'].update(guides_json=['1',1],sparkle_mask=['1',3],sparkle_painted=60)
    p['3']={'class_type':'NFStockingEditor','inputs':{'images':['1',0],'guides_json':['1',2],'batch_mode':'shared'}}
    p['4']={'class_type':'NFStockingPSDSave','inputs':{'images':['1',0],'guides':['3',0],'filename_prefix':'ToolBoxStocking/upstream/guides-roundtrip','sparkle_mask':['1',3]}}
    result.append(('14-PSD引导导入导出',p))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8188');parser.add_argument('--output',type=Path,default=ROOT/'examples/stocking_texture/upstream')
    args=parser.parse_args();items=graphs();schemas={}
    for name in {n['class_type'] for _,p in items for n in p.values()}:
        schemas.update(json.load(urllib.request.urlopen(args.url+'/object_info/'+urllib.parse.quote(name))))
    args.output.mkdir(parents=True,exist_ok=True)
    for title,prompt in items:
        ui=workflow(prompt,schemas,0,title)
        for i,n in enumerate(ui['nodes']):
            n['pos']=[(i%4)*420,160+(i//4)*360]
            if n['type']=='NFStockingTexture':n['size']=[360,280]
        ui['groups']=[]
        (args.output/(title+'.api.json')).write_text(json.dumps(prompt,ensure_ascii=False,indent=2)+'\n')
        (args.output/(title+'.json')).write_text(json.dumps(ui,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
