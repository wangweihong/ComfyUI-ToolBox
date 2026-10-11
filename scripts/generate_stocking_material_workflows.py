"""Four public recipes for layered materials and region inheritance."""
import copy
import json
from pathlib import Path
import urllib.request
from generate_stocking_upstream_workflows import graphs as upstream_graphs
from generate_stocking_function_workflows import workflow

ROOT=Path(__file__).resolve().parents[1]


def pattern(lid,name='lace',color='#332233'):
    return dict(id=lid,type='pattern',params=dict(pattern=name,enabled=True,mode='fabric',color=color,opacity=70,size=100,rotation=0))


def text(lid,content,color='#eeeeee'):
    return dict(id=lid,type='text',params=dict(enabled=True,content=content,mode='print',size=100,spacing_x=100,spacing_y=100,rotation=-10,color=color,opacity=70))


def graphs():
    def base():return copy.deepcopy(upstream_graphs()[0][1])
    result=[]
    p=base();p['2']['inputs']['effects_json']=json.dumps(dict(version=2,layers=[pattern('lace')]))
    result.append(('15-Coil与蕾丝组合',p))
    p=base();raw=json.loads(p['2']['inputs']['guides_json'])
    for doc in raw['records'].values():
        a,b=doc['frames'][0]['regions']
        a['material']=dict(params=dict(style='coil',strength_auto=False,strength=110),layers=[pattern('left','polka')])
        b['material']=dict(params=dict(style='oily'),layers=[pattern('right','leopard'),text('right-brand','PARIS')],damage=dict(enabled=True,mode='manual'))
    p['2']['inputs']['guides_json']=json.dumps(raw,ensure_ascii=False)
    result.append(('16-左右腿独立材质',p))
    p=base();p['2']['inputs']['effects_json']=json.dumps(dict(version=2,layers=[pattern('hearts','hearts'),text('paris','PARIS'),text('brand','BALENCIAGA','#bb5566')]))
    result.append(('17-有序多层文字',p))
    p=base()
    p['10']={'class_type':'NFStockingPatternLayer','inputs':dict(pattern='lace',mode='fabric',size=120,rotation=0,color='#332233',opacity=70,enabled=True)}
    p['11']={'class_type':'NFStockingTextLayer','inputs':dict(enabled=True,content='PARIS',mode='print',size=100,spacing_x=100,spacing_y=100,rotation=-10,color='#eeeeee',opacity=70)}
    p['12']={'class_type':'NFStockingLayerStack','inputs':dict(layer_1=['10',0],layer_2=['11',0])}
    p['13']={'class_type':'NFStockingDamageConfig','inputs':dict(enabled=True,mode='both',type='mixed',count=2,length=100,width=100,strength=60)}
    p['14']={'class_type':'NFStockingMaterial','inputs':dict(style='coil',density=100,tilt=32,strength=100,strength_auto=True,color_exclude=True,sparkle_depth=0,sparkle_bright=0,sparkle_painted=0,sparkle_even=0,sparkle_link=False,moire_on=False,moire=100,moire_area=100,layers=['12',0],damage=['13',0])}
    p['2']['inputs']['material']=['14',0]
    result.append(('18-材质配置节点连线',p))
    return result


def main():
    items=graphs();schemas={}
    for name in {n['class_type'] for _,p in items for n in p.values()}:
        schemas.update(json.load(urllib.request.urlopen('http://127.0.0.1:8188/object_info/'+name)))
    folder=ROOT/'examples/stocking_texture/materials';folder.mkdir(parents=True,exist_ok=True)
    for title,p in items:
        ui=workflow(p,schemas,0,title);ui['groups']=[]
        for i,n in enumerate(ui['nodes']):n['pos']=[i%4*420,160+i//4*450];n['size']=[360,320]
        (folder/(title+'.json')).write_text(json.dumps(ui,ensure_ascii=False,indent=2)+'\n')
        (folder/(title+'.api.json')).write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
