"""Actual layered-material queue, preview, exchange and restart acceptance."""
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
from generate_stocking_material_workflows import graphs


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8188');parser.add_argument('--output',type=Path,default=Path('data/stocking_material_validation'));parser.add_argument('--restore',action='store_true');a=parser.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    def request(path,body=None,binary=False):
        req=urllib.request.Request(a.url+path,None if body is None else json.dumps(body).encode(),{'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=180) as r:return r.read() if binary else json.load(r)
    def png(encoded):return np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded))))
    def queue(p):
        p=copy.deepcopy(p);offset=time.monotonic_ns()%1000000000;ids={k:str(offset+i) for i,k in enumerate(p)}
        for node in p.values():
            for k,v in node['inputs'].items():
                if isinstance(v,list) and len(v)==2 and v[0] in ids:node['inputs'][k]=[ids[v[0]],v[1]]
        pid=request('/prompt',{'prompt':{ids[k]:v for k,v in p.items()}})['prompt_id'];deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            e=request('/history/'+pid).get(pid)
            if e:
                assert e['status']['status_str']=='success',e['status'];return {k:e['outputs'].get(v) for k,v in ids.items()}
            time.sleep(.3)
        raise TimeoutError(pid)
    key=dict(editor_id='__material_acceptance__')
    if a.restore:
        key.update(json.loads((a.output/'draft-key.json').read_text()))
        d=request('/toolbox/stocking/feature/draft',dict(key,action='load'))['draft'];assert d
        body=dict(session=d['payload']['session'],index=0,client='restore-material',revision=1,guides_json=json.dumps(d['state']['doc']),settings=d['state']['settings'])
        assert np.array_equal(png(request('/toolbox/stocking/preview',body)['png']),np.asarray(Image.open(a.output/'draft-reference.png')))
        request('/toolbox/stocking/feature/draft',dict(key,action='delete'));(a.output/'restart-result.json').write_text(json.dumps(dict(v2_material_restored_after_restart=True,preview_identical=True)));print('Restart draft: passed');return
    reports=[];gallery=[]
    for title,p in graphs():
        p['900']={'class_type':'PreviewImage','inputs':dict(images=['2',0])};e=queue(p);payload=e['2']['nf_stocking'][0]
        raw=request('/view?'+urllib.parse.urlencode(e['900']['images'][0]),binary=True);out=np.asarray(Image.open(io.BytesIO(raw)));Image.fromarray(out).save(a.output/(title+'.png'));gallery.append((title,Image.fromarray(out)))
        body=dict(session=payload['session'],index=0,client='material-acceptance',revision=1,guides_json=json.dumps(payload['document']),settings=payload['params'])
        full=request('/toolbox/stocking/preview',body);assert np.array_equal(png(full['png']),out)
        crop=request('/toolbox/stocking/preview',dict(body,revision=2,rect=[80,100,400,600]));assert np.array_equal(png(crop['png']),out[100:600,80:400])
        rgba=np.asarray(Image.open(io.BytesIO(request('/toolbox/stocking/feature/export',dict(body,kind='cutout',batch_mode='per_image'),True))))
        original=np.asarray(Image.open(Path(__file__).resolve().parents[1]/'examples/stocking_texture/assets/tb_stocking_demo.png'));alpha=rgba[...,3:4]/255
        error=int(np.max(np.abs(np.round(rgba[...,:3]*alpha+original*(1-alpha))-out)));assert error<=1
        report=dict(workflow=title,queue_matches_preview=True,crop_identical=True,png_composition_max_error=error)
        if title.startswith('18'):
            assert payload['material_connected'];fake=dict(payload['params'],style='oily',effects_json='{}')
            changed=request('/toolbox/stocking/preview',dict(body,revision=3,settings=fake));assert np.array_equal(png(changed['png']),out);report['linked_material_authoritative']=True
        if title.startswith('16'):
            assert all(r.get('material') for r in payload['document']['frames'][0]['regions']);report['region_materials_preserved']=True
        reports.append(report);print(title+': passed',flush=True)
    root=Path(__file__).resolve().parents[1]
    advanced=json.loads((root/'examples/stocking_texture/manual.api.json').read_text())
    for node in advanced.values():
        if node['class_type']=='SaveImage':node['class_type']='PreviewImage';node['inputs'].pop('filename_prefix',None)
    connected=graphs()[-1][1]
    advanced.update({k:copy.deepcopy(v) for k,v in connected.items() if k in ('10','11','12','13','14')})
    advanced['4']['inputs'].update(material=['14',0],renderer_version='upstream_f74c8ac',layer_mode='soft')
    entry=queue(advanced);payload=entry['4']['nf_stocking'][0];assert payload['material_connected']
    preview=request('/toolbox/stocking/preview',dict(session=payload['session'],index=0,client='advanced-v2',revision=1,rect=[80,100,400,600]))
    image=np.asarray(Image.open(io.BytesIO(request('/view?'+urllib.parse.urlencode(entry['5']['images'][0]),binary=True))))
    assert np.array_equal(png(preview['png']),image[100:600,80:400]);reports.append(dict(advanced_material_connected=True,crop_identical=True))
    # Refresh the session after the bounded preview pool has handled the matrix.
    p=graphs()[2][1];e=queue(p);payload=e['2']['nf_stocking'][0];key['identity']=payload['identity']
    state=dict(doc=payload['document'],mode='per_image',index=0,selected=0,settings=payload['params'])
    request('/toolbox/stocking/feature/draft',dict(key,action='save',session=payload['session'],state=state));assert request('/toolbox/stocking/feature/draft',dict(key,action='load'))['draft']
    preview=request('/toolbox/stocking/preview',dict(session=payload['session'],index=0,client='draft-material',revision=4,guides_json=json.dumps(state['doc']),settings=state['settings']))
    Image.fromarray(png(preview['png'])).save(a.output/'draft-reference.png');(a.output/'draft-key.json').write_text(json.dumps(key))
    preset='__materials_acceptance__';saved=request('/toolbox/stocking/feature/presets',dict(action='save',name=preset,params=payload['params']))
    assert any(x['name']==preset and json.loads(x['params']['effects_json'])['version']==2 for x in saved['presets']);request('/toolbox/stocking/feature/presets',dict(action='delete',name=preset))
    reports.append(dict(v2_draft_saved=True,v2_preset_roundtrip=True));(a.output/'api-results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
    sheet=Image.new('RGB',(4*256,420),(22,26,34));draw=ImageDraw.Draw(sheet)
    for i,(title,im) in enumerate(gallery):sheet.paste(im.resize((256,384)),(i*256,0));draw.text((i*256+12,397),title[:2]+' / V2 material',fill='white')
    sheet.save(a.output/'materials-comparison.png')


if __name__=='__main__':main()
