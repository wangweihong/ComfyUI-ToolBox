"""One schema for Python, browser controls and composable material nodes."""
import copy
import json
from pathlib import Path
import re
import numpy as np
from .styles import PATTERNS, base_style

SCHEMA = json.loads((Path(__file__).parents[2] / 'web/js/stocking_effect_schema.json').read_text())
LEGACY_DEFAULTS = SCHEMA['legacy_defaults']
MAX_LAYERS = SCHEMA['max_layers']
APPEARANCE = SCHEMA['appearance']
LAYER_TYPES = tuple(k for k,v in SCHEMA['types'].items() if v.get('layer'))


def decode(raw):
    if isinstance(raw, str):
        if len(raw.encode()) > 64 * 1024:
            raise ValueError('效果配置超过 64 KiB')
        try:
            raw = json.loads(raw or '{}')
        except (ValueError, RecursionError) as exc:
            raise ValueError('效果 JSON 格式错误') from exc
    if not isinstance(raw, dict):
        raise ValueError('效果配置必须为对象')
    return raw


def fields(raw, specs, partial=False, strict=True):
    if not isinstance(raw, dict):
        raise ValueError('配置必须为对象')
    if strict and set(raw) - set(specs):
        raise ValueError('不支持此配置参数：' + ', '.join(sorted(set(raw)-set(specs))))
    out = {}
    for k, spec in specs.items():
        if partial and k not in raw:
            continue
        v = raw.get(k, spec['default']); typ = spec['type']
        if typ == 'boolean' and not isinstance(v, bool):
            raise ValueError(f'{k} 必须为布尔值')
        if typ == 'number':
            if isinstance(v, bool) or not isinstance(v, (int,float)) or not np.isfinite(v):
                raise ValueError(f'{k} 必须为有限数值')
            v = float(np.clip(v, spec['min'], spec['max']))
        if typ == 'enum' and v not in spec['options']:
            raise ValueError(f'未知 {k}：{v}')
        if typ == 'color':
            if not isinstance(v, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v):
                raise ValueError('颜色必须为 #RRGGBB')
            v = v.lower()
        if typ == 'string':
            if not isinstance(v, str) or len(v)>spec.get('maxLength',4096) or spec.get('ascii') and any(not 32<=ord(c)<=126 for c in v):
                raise ValueError('文字最多 128 字符，仅支持英文、数字、空格和常见标点')
        out[k] = v
    return out


def clean_v1(raw):
    raw=decode(raw)
    if raw.get('version',1)!=1:
        raise ValueError('不支持此效果配置版本')
    out={'version':1}
    for kind in ('pattern','text','damage'):
        specs={k:dict(SCHEMA['groups'][kind][k],default=v) for k,v in LEGACY_DEFAULTS[kind].items()}
        out[kind]=fields(raw.get(kind,{}),specs,strict=False)
    return out


def clean_layer(layer):
    if not isinstance(layer,dict) or set(layer)-{'id','type','params'} or layer.get('type') not in LAYER_TYPES:
        raise ValueError('不支持此效果图层类型或参数')
    lid=layer.get('id')
    if not isinstance(lid,str) or not lid or len(lid)>128:
        raise ValueError('图层 id 必须为非空字符串')
    return dict(id=lid,type=layer['type'],params=fields(layer.get('params',{}),SCHEMA['groups'][layer['type']]))


def clean_v2(raw):
    raw=decode(raw)
    if raw.get('version')!=2 or set(raw)-{'version','layers','damage','sampling'}:
        raise ValueError('不支持此效果配置版本或参数')
    layers=raw.get('layers',[])
    if not isinstance(layers,list) or len(layers)>MAX_LAYERS:
        raise ValueError('每套材质最多 16 个图层')
    layers=[clean_layer(x) for x in layers]
    if len({x['id'] for x in layers})!=len(layers):
        raise ValueError('图层 id 必须唯一')
    sampling=raw.get('sampling','field')
    if sampling not in ('field','v1'):raise ValueError('未知采样版本')
    return dict(version=2,layers=layers,damage=fields(raw.get('damage',{}),SCHEMA['groups']['damage']),sampling=sampling)


def clean_effects(raw='{}'):
    obj=decode(raw)
    return clean_v1(obj) if obj.get('version',1)==1 else clean_v2(obj)


def normalize_effects(style, raw='{}'):
    cfg=clean_effects(raw)
    if cfg['version']==2:
        if style in PATTERNS:
            # A V2 caller explicitly chooses a base; old pattern IDs remain compatible aliases.
            cfg=copy.deepcopy(cfg)
            cfg['layers'].insert(0,clean_layer(dict(id='legacy-style',type='pattern',params=dict(pattern=style))))
            cfg=clean_v2(cfg)
        return base_style(style),cfg
    layers=[]
    if style in PATTERNS:
        layers.append(clean_layer(dict(id='legacy-pattern',type='pattern',params=dict(cfg['pattern'],pattern=style,enabled=True))))
    layers.append(clean_layer(dict(id='legacy-text',type='text',params=dict(cfg['text'],mode=cfg['pattern']['mode']))))
    return base_style(style),dict(version=2,layers=layers,damage=cfg['damage'],sampling='v1')


def clean_override(raw):
    if not isinstance(raw,dict) or set(raw)-{'params','layers','damage'}:
        raise ValueError('部位材质包含不支持的参数')
    out={'params':fields(raw.get('params',{}),APPEARANCE,partial=True)}
    if 'layers' in raw:
        out['layers']=clean_v2(dict(version=2,layers=raw['layers']))['layers']
    if 'damage' in raw:
        out['damage']=fields(raw['damage'],SCHEMA['groups']['damage'],partial=True)
    return out


def resolve_material(params, material=None):
    out=dict(params)
    if material is not None:
        if not isinstance(material,dict) or set(material)-{'version','params','effects'} or material.get('version')!=2:
            raise ValueError('不支持此材质版本或参数')
        out.update(fields(material.get('params',{}),APPEARANCE))
        out['effects_json']=json.dumps(clean_v2(material.get('effects',{'version':2})),ensure_ascii=False)
    return out
