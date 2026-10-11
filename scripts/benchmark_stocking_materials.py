"""Renderer-only benchmarks on public artwork; geometry preparation is reported separately."""
import argparse
import copy
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]


def worker(w,h):
    sys.path.insert(0,str(ROOT/'tests'));import test_stocking_texture
    from tb_stocking_test import data,engine,effects
    from tb_stocking_test.cache import REGION_CACHE,SCENE_CACHE
    from tb_stocking_test.layer_renderer import SAMPLE_CACHE,DAMAGE_CACHE
    from tb_stocking_test.config import normalize_effects
    image=np.asarray(Image.open(ROOT/'examples/stocking_texture/assets/tb_stocking_demo.png').resize((w,h)),np.float32)/255
    doc=json.loads((ROOT/'examples/stocking_texture/assets/guides.json').read_text());ow,oh=doc['width'],doc['height']
    for r in doc['frames'][0]['regions']:
        mask=data.decode_mask(r['mask'],oh,ow)
        r['mask']=data.encode_mask(np.asarray(Image.fromarray(data.rgb8(mask)).resize((w,h)),np.float32)/255)
        for key in ('strokes','walls'):
            r[key]=[(np.asarray(p)*[w/ow,h/oh]).tolist() for p in r[key]]
    doc.update(width=w,height=h)
    start=time.perf_counter();guides,_=engine.build_guides(image[None],data.dump_guides(doc));f=engine.solve_batch(image[None],guides)['frames'][0];solve=time.perf_counter()-start
    cfg=dict(pattern=dict(mode='fabric'),text=dict(enabled=True,content='PARIS'))
    base,v2=normalize_effects('lace',cfg);v2['sampling']='field'
    common=dict(style=base,strength_auto=True,renderer_version='upstream_f74c8ac',sparkle_depth=0,sparkle_bright=0,sparkle_painted=0,sparkle_even=0)
    result={'resolution':[w,h],'geometry_seconds':solve,'scenarios':{}}
    for version in ('v1','v2'):
        for cache in (SCENE_CACHE,effects.EFFECT_CACHE,SAMPLE_CACHE,DAMAGE_CACHE):cache.clear()
        p=dict(common,style='lace' if version=='v1' else base,effects_json=json.dumps(cfg if version=='v1' else v2))
        scenarios={'cold':[(p,None)]*5,'repeat':[(p,None)]*5,'layer_color':[], 'quarter_roi':[(p,[w//4,h//4,3*w//4,3*h//4])]*5}
        for c in ('#112233','#223344','#334455','#445566','#556677'):
            config=copy.deepcopy(cfg if version=='v1' else v2)
            if version=='v1':config['text']['color']=c
            else:config['layers'][-1]['params']['color']=c
            scenarios['layer_color'].append((dict(p,effects_json=json.dumps(config)),None))
        records={}
        for name,runs in scenarios.items():
            times=[];last=None;hits=misses=0;final_hits=0
            for params,rect in runs:
                if name=='cold':
                    for cache in (SCENE_CACHE,effects.EFFECT_CACHE,SAMPLE_CACHE,DAMAGE_CACHE):cache.clear()
                start=time.perf_counter();last=engine.render_one(image,f,params,rect=rect)[4];times.append((time.perf_counter()-start)*1000)
                cache=last.get('effect_cache',{});hits+=cache.get('sample_hits',0);misses+=cache.get('sample_misses',0);final_hits+=int(cache.get('final_hit',False))
            records[name]=dict(samples=len(times),sampling_hit_rate=hits/(hits+misses) if hits+misses else None,final_hit_rate=final_hits/len(times) if version=='v2' else None,median_ms=float(np.median(times)),p95_ms=float(np.percentile(times,95)),peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,cache=last.get('effect_cache',{}))
        result['scenarios'][version]=records
    result['cache_bytes']=dict(scene=SCENE_CACHE.bytes,effects=effects.EFFECT_CACHE.bytes+SAMPLE_CACHE.bytes+DAMAGE_CACHE.bytes)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',nargs=2,type=int);parser.add_argument('--output',type=Path,default=ROOT/'data/stocking_material_validation/benchmark.json');a=parser.parse_args()
    if a.worker:print(json.dumps(worker(*a.worker)));return
    a.output.parent.mkdir(parents=True,exist_ok=True);results=[]
    for size in ((1920,1080),(2560,1440),(3840,2160)):
        raw=subprocess.check_output([sys.executable,__file__,'--worker',*map(str,size)])
        results.append(json.loads(raw));a.output.write_text(json.dumps(results,indent=2));print('Measured',size,flush=True)


if __name__=='__main__':main()
