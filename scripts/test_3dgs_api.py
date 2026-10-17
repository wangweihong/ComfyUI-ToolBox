#!/usr/bin/env python3
"""Explicit integration test against an isolated server, never starts containers."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

FEATURE=Path(__file__).resolve().parents[1]


def api_graph(workflow):
    links={link[0]:link for link in workflow['links']}
    graph={}
    for node in workflow['nodes']:
        if node['type'] in ('MarkdownNote','Note'):continue
        inputs={k:v for k,v in node.get('widgets_values_named',{}).items() if k not in ('control_after_generate','upload')}
        for socket in node.get('inputs',[]):
            if socket.get('link') is not None:
                link=links[socket['link']];inputs[socket['name']]=[str(link[1]),link[2]]
        if node['type']=='PreviewGaussianSplat':inputs['viewport_state']={}
        graph[str(node['id'])]=dict(class_type=node['type'],inputs=inputs,_meta={'title':node.get('title',node['type'])})
    return graph


def preview_file(output):
    if output.get('3d'):
        return output['3d'][0]
    # Older ComfyUI versions returned a display string instead of a descriptor.
    name=output['result'][0].split(' [',1)[0]
    return dict(filename=name,subfolder='',type='temp')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--url',default='http://127.0.0.1:8189')
    p.add_argument('--results',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=1800)
    args=p.parse_args();args.results.mkdir(parents=True,exist_ok=True)
    def request(route,data=None):
        body=json.dumps(data).encode() if data is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(args.url+route,data=body,headers={'Content-Type':'application/json'}),timeout=30) as r:return json.load(r)
        except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from e
    start=time.monotonic()
    while True:
        try:info=request('/object_info');break
        except (OSError,RuntimeError):
            if time.monotonic()-start>300:raise
            time.sleep(3)
    name='01_assets宇航员_环绕到3DGS'
    workflow=json.loads((FEATURE/'examples/3dgs/workflows'/(name+'.json')).read_text());graph=api_graph(workflow)
    required={n['class_type'] for n in graph.values()}
    required.update({'LocalCOLMAPDataset','LocalVideoFrames','LocalBrushTrain','LocalPLYFile'})
    assert required.issubset(info),sorted(required-set(info))
    (args.results/'node_schemas.json').write_text(json.dumps({k:info[k] for k in required},ensure_ascii=False,indent=2))
    queue=request('/queue');assert not queue['queue_running'] and not queue['queue_pending'],'Isolated test server queue is busy'
    response=request('/prompt',dict(prompt=graph,client_id=str(uuid.uuid4()),extra_data={'extra_pnginfo':{'workflow':workflow}}))
    assert not response.get('node_errors'),response
    pid=response['prompt_id'];print('Submitted isolated H3/COLMAP/Brush/PLY test:',pid,flush=True)
    (args.results/'submission.json').write_text(json.dumps(response,indent=2));(args.results/'actual_api.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2))
    start=time.monotonic();last=0
    while time.monotonic()-start<args.timeout:
        record=request('/history/'+pid).get(pid)
        if record:
            (args.results/'history.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
            assert record['status']['status_str']=='success',record['status']
            sfm=json.loads(record['outputs']['40']['text'][1]);train=json.loads(record['outputs']['41']['text'][0])
            assert sfm['registered_images']>=8 and sfm['camera_model']=='SIMPLE_PINHOLE'
            assert train['steps']==5000 and '42' in record['outputs']
            preview=preview_file(record['outputs']['42'])
            with urllib.request.urlopen(args.url+'/view?'+urllib.parse.urlencode(preview),timeout=30) as f:
                assert f.read(128).startswith(b'ply\n'),'Native preview did not serve a PLY'
            stamps={k:v.get('timestamp') for k,v in record['status']['messages']}
            result=dict(status='success',prompt_id=pid,server_seconds=(stamps['execution_success']-stamps['execution_start'])/1000,
                        sfm=sfm,training=train,preview=record['outputs']['42'])
            (args.results/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('SUCCESS',result['server_seconds'],'seconds',flush=True);return
        elapsed=time.monotonic()-start
        if elapsed-last>=30:print('Running',round(elapsed),'seconds',flush=True);last=elapsed
        time.sleep(3)
    raise RuntimeError('Timeout; test may still be running. No global interrupt was sent.')


if __name__=='__main__':main()
