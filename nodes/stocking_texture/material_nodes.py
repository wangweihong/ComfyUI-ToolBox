"""Schema-driven, serializable materials. Renderer/seed/output remain global."""
import json
from .config import SCHEMA, fields, clean_layer, clean_v2, resolve_material

CATEGORY='南风节点/丝袜纹理/材质配置'


def inputs(specs):
    result={}
    for k,s in specs.items():
        options={'default':s['default'],'tooltip':s.get('hint',s.get('label',k))}
        if s['type']=='number':options.update(min=s['min'],max=s['max'],step=1)
        typ=s['options'] if s['type']=='enum' else 'BOOLEAN' if s['type']=='boolean' else 'FLOAT' if s['type']=='number' else 'STRING'
        result[k]=(typ,options)
    return result


class NFStockingPatternLayer:
    kind='pattern'
    @classmethod
    def INPUT_TYPES(cls):return {'required':inputs(SCHEMA['groups'][cls.kind]),'hidden':{'unique_id':'UNIQUE_ID'}}
    RETURN_TYPES=('NF_STOCKING_LAYER',)
    RETURN_NAMES=('layer',)
    FUNCTION='build'
    CATEGORY=CATEGORY
    def build(self,unique_id='',**params):return (clean_layer(dict(id=str(unique_id or self.kind),type=self.kind,params=params)),)


class NFStockingTextLayer(NFStockingPatternLayer):kind='text'


class NFStockingLayerStack:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{},'optional':{'layers':('NF_STOCKING_LAYERS',),**{f'layer_{i}':('NF_STOCKING_LAYER',) for i in range(1,17)}}}
    RETURN_TYPES=('NF_STOCKING_LAYERS',)
    RETURN_NAMES=('layers',)
    FUNCTION='build'
    CATEGORY=CATEGORY
    def build(self,layers=None,**kwargs):
        import copy
        result=copy.deepcopy(layers or [])
        for i in range(1,17):
            if kwargs.get(f'layer_{i}') is not None:
                result.append(copy.deepcopy(kwargs[f'layer_{i}']))
        used=set()
        for layer in result:
            original=layer['id'];n=1
            while layer['id'] in used:
                layer['id']=f'{original}:{n}';n+=1
            used.add(layer['id'])
        return (clean_v2(dict(version=2,layers=result))['layers'],)


class NFStockingDamageConfig:
    @classmethod
    def INPUT_TYPES(cls):return {'required':inputs(SCHEMA['groups']['damage'])}
    RETURN_TYPES=('NF_STOCKING_DAMAGE',)
    RETURN_NAMES=('damage',)
    FUNCTION='build'
    CATEGORY=CATEGORY
    def build(self,**params):return (fields(params,SCHEMA['groups']['damage']),)


class NFStockingMaterial:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':inputs(SCHEMA['appearance']),'optional':{'layers':('NF_STOCKING_LAYERS',),'damage':('NF_STOCKING_DAMAGE',)}}
    RETURN_TYPES=('NF_STOCKING_MATERIAL',)
    RETURN_NAMES=('material',)
    FUNCTION='build'
    CATEGORY=CATEGORY
    def build(self,layers=None,damage=None,**params):
        effects=clean_v2(dict(version=2,layers=layers or [],damage=damage or {}))
        return (dict(version=2,params=fields(params,SCHEMA['appearance']),effects=effects),)


NODE_CLASS_MAPPINGS={c.__name__:c for c in (NFStockingPatternLayer,NFStockingTextLayer,NFStockingLayerStack,NFStockingDamageConfig,NFStockingMaterial)}
NODE_DISPLAY_NAME_MAPPINGS=dict(NFStockingPatternLayer='tb-丝袜花纹层',NFStockingTextLayer='tb-丝袜文字层',NFStockingLayerStack='tb-丝袜图层组合',NFStockingDamageConfig='tb-丝袜损伤配置',NFStockingMaterial='tb-丝袜基础材质')
