"""Actual queue, preview, exchange and restart-recovery acceptance checks."""
import argparse
import base64
import copy
import io
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw
from generate_stocking_upstream_workflows import graphs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8188')
    parser.add_argument('--output',type=Path,default=Path('data/stocking_upstream_validation'))
    parser.add_argument('--restore',action='store_true');args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    def request(path,body=None,binary=False):
        raw=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(args.url+path,raw,{'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180) as response:
            return response.read() if binary else json.load(response)
    def queue(prompt):
        # Each acceptance run has its own UI token, while keeping the image/seed unchanged.
        offset=(time.monotonic_ns()//1000)%1000000000
        ids={k:str(offset+i) for i,k in enumerate(prompt)}
        submitted={ids[k]:copy.deepcopy(v) for k,v in prompt.items()}
        for node in submitted.values():
            for k,v in node['inputs'].items():
                if isinstance(v,list) and len(v)==2 and v[0] in ids:
                    node['inputs'][k]=[ids[v[0]],v[1]]
        pid=request('/prompt',{'prompt':submitted})['prompt_id'];deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            entry=request('/history/'+pid).get(pid)
            if entry:
                assert entry['status']['status_str']=='success',entry['status']
                reverse={v:k for k,v in ids.items()};entry['outputs']={reverse.get(k,k):v for k,v in entry['outputs'].items()}
                return pid,entry
            time.sleep(.3)
        raise TimeoutError(pid)
    def pixels(item):
        return np.asarray(Image.open(io.BytesIO(request('/view?'+urllib.parse.urlencode(item),binary=True))))
    if args.restore:
        saved=json.loads((args.output/'draft-key.json').read_text())
        recovered=request('/toolbox/stocking/feature/draft',dict(saved,action='load'))['draft']
        assert recovered and recovered['state']['settings']['style']=='coil'
        payload=recovered['payload']
        preview=request('/toolbox/stocking/preview',dict(session=payload['session'],index=0,client='restart-acceptance',revision=1,
                        guides_json=json.dumps(recovered['state']['doc']),settings=recovered['state']['settings']))
        image=np.asarray(Image.open(io.BytesIO(base64.b64decode(preview['png']))))
        assert np.array_equal(image,np.asarray(Image.open(args.output/'draft-reference.png')))
        request('/toolbox/stocking/feature/draft',dict(saved,action='delete'))
        (args.output/'restart-result.json').write_text(json.dumps({'restored_after_restart':True,'preview_matches_before_restart':True}))
        print('Restart recovery: passed',flush=True);return
    reports=[];gallery=[];draft_payload=None
    for title,prompt in graphs():
        pid,entry=queue(prompt);record=dict(workflow=title,prompt_id=pid,preview_matches_queue=True)
        for key,node in prompt.items():
            if node['class_type']!='NFStockingTexture':continue
            payload=entry['outputs'][key]['nf_stocking'][0]
            p=copy.deepcopy(prompt);p['900']={'class_type':'PreviewImage','inputs':{'images':[key,0]}}
            _,full_entry=queue(p);out=pixels(full_entry['outputs']['900']['images'][0])
            body=dict(session=payload['session'],index=0,client='upstream-acceptance',revision=int(key)+100,
                guides_json=json.dumps(payload['document']),settings=payload['params'],rect=[80,100,400,600])
            crop=request('/toolbox/stocking/preview',body)
            cropped=np.asarray(Image.open(io.BytesIO(base64.b64decode(crop['png']))))
            assert np.array_equal(cropped,out[100:600,80:400])
            if title.startswith('11'):
                flipped=dict(payload['params'],depth_direction='black_near')
                preview=request('/toolbox/stocking/preview',dict(session=payload['session'],index=0,client='depth-export-acceptance',revision=1000,
                                guides_json=json.dumps(payload['document']),settings=flipped))
                exported=request('/toolbox/stocking/feature/export',dict(session=payload['session'],index=0,kind='png',batch_mode='per_image',
                                 guides_json=json.dumps(payload['document']),settings=flipped),True)
                assert np.array_equal(np.asarray(Image.open(io.BytesIO(exported))),np.asarray(Image.open(io.BytesIO(base64.b64decode(preview['png'])))))
                record['flipped_depth_export_matches_preview']=True
            if title.startswith('10'):
                draft_payload=payload;Image.fromarray(out).save(args.output/'draft-reference.png')
            Image.fromarray(out).save(args.output/(title+'-'+key+'.png'))
            gallery.append((title+' '+key,Image.fromarray(out)))
        if title.startswith('13'):
            final=pixels(entry['outputs']['5']['images'][0]);composite=pixels(entry['outputs']['7']['images'][0])
            assert np.max(np.abs(final.astype(int)-composite.astype(int)))<=1
            rgba=pixels(entry['outputs']['8']['images'][0]);assert rgba.shape[-1]==4 and rgba[...,3].min()==0
            record['soft_composition_max_error']=int(np.max(np.abs(final.astype(int)-composite.astype(int))))
        if title.startswith('14'):
            assert entry['outputs']['4']['stocking_psd'];record['psd_export']=True
        reports.append(record);print(title+': passed',flush=True)
    # All editor exports use the same final rendering path.
    # Acquire a fresh editor token after the matrix; the bounded cache can evict early rows.
    _, fresh = queue(graphs()[0][1])
    p=fresh['outputs']['2']['nf_stocking'][0];body=dict(session=p['session'],index=0,guides_json=json.dumps(p['document']),batch_mode='per_image',settings=p['params'])
    exports={}
    for kind in ('png','cutout','guides'):
        raw=request('/toolbox/stocking/feature/export',dict(body,kind=kind),True)
        (args.output/('export-'+kind+('.psd' if kind=='guides' else '.png'))).write_bytes(raw);exports[kind]=len(raw)
    finished=np.asarray(Image.open(args.output/'export-png.png'));rgba=np.asarray(Image.open(args.output/'export-cutout.png'))
    original=np.asarray(Image.open(Path(__file__).resolve().parents[1]/'examples/stocking_texture/assets/tb_stocking_demo.png'))
    alpha=rgba[...,3:4]/255.;combined=np.round(rgba[...,:3]*alpha+original*(1-alpha))
    assert np.max(np.abs(combined-finished))<=1
    # Import exported guide PSD into the same editor image.
    boundary='tb-stocking-acceptance';parts=[]
    for key,value in dict(session=p['session'],index='0').items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="guides.psd"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(),
              (args.output/'export-guides.psd').read_bytes(),f'\r\n--{boundary}--\r\n'.encode()]
    req=urllib.request.Request(args.url+'/toolbox/stocking/psd/import',b''.join(parts),{'Content-Type':f'multipart/form-data; boundary={boundary}'})
    imported=json.load(urllib.request.urlopen(req));assert len(imported['document']['frames'][0]['regions'])==2
    edited=request('/toolbox/stocking/feature/edit',dict(body,operation='split',source=p['document']['frames'][0]['regions'][0]['id']))
    assert len(edited['frame']['regions'])==3
    preset_name='__upstream_acceptance__'
    presets=request('/toolbox/stocking/feature/presets',dict(action='save',name=preset_name,params=p['params']))
    assert any(x['name']==preset_name and x['params']['style']=='coil' for x in presets['presets'])
    request('/toolbox/stocking/feature/presets',dict(action='delete',name=preset_name))
    key=dict(editor_id='__upstream_acceptance__',identity=p['identity'])
    state=dict(doc=p['document'],mode='per_image',index=0,selected=0,settings=p['params'])
    request('/toolbox/stocking/feature/draft',dict(key,action='save',session=p['session'],state=state))
    assert request('/toolbox/stocking/feature/draft',dict(key,action='load'))['draft']
    (args.output/'draft-key.json').write_text(json.dumps(key))
    reports.append(dict(exports=exports,psd_import=True,split=True,presets=True,draft_saved=True,soft_png_max_error=int(np.max(np.abs(combined-finished)))))
    (args.output/'api-results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    sheet=Image.new('RGB',(3*256,2*414),(22,26,34));draw=ImageDraw.Draw(sheet)
    for i,(title,im) in enumerate(gallery[:6]):
        x,y=(i%3)*256,(i//3)*414;sheet.paste(im.resize((256,384)),(x,y));draw.text((x+8,y+390),title[:2]+' / '+title.rsplit(' ',1)[-1],fill='white')
    sheet.save(args.output/'upstream-comparison.png')
    print('Exports, split, presets and draft save: passed',flush=True)


if __name__=='__main__':main()
