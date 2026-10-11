"""Independent sampling and damage caches within the existing 128 MiB effect budget."""
from types import SimpleNamespace
import numpy as np
from . import data
from .cache import ByteLRU
from .core import tiles
from .styles import PATTERNS
from .surface import context

SAMPLE_CACHE=ByteLRU(64*1024**2,64)
DAMAGE_CACHE=ByteLRU(32*1024**2,8)


def _slice(rect):return (slice(None),slice(None)) if rect is None else (slice(rect[1],rect[3]),slice(rect[0],rect[2]))


def pattern_source(ctx,p):
    from .effects import pattern_tile
    period=max(1,PATTERNS[p['pattern']]['period']*ctx.scale*p['size']/100)
    return pattern_tile(p['pattern']),period,period


def text_source(ctx,p):
    from .effects import text_tile
    rip,(w,h)=text_tile(p);ratio=.5*ctx.scale*p['size']/100
    return rip,max(w*ratio,1),max(h*ratio,1)


LAYER_HANDLERS={'pattern':pattern_source,'text':text_source}


def sampled(scene,ctx,layer,rect,stats,sampling):
    p=layer['params'];sl=_slice(rect)
    geometry={k:v for k,v in p.items() if k not in ('color','opacity','mode','enabled')}
    key=data.digest('sample-v2',ctx.signature,scene.__class__.__module__,layer['type'],geometry,rect,sampling)
    hit=SAMPLE_CACHE.get(key)
    if hit is not None:stats['sample_hits']+=1;return hit
    stats['sample_misses']+=1
    rip,px,py=LAYER_HANDLERS[layer['type']](ctx,p)
    angle=np.deg2rad(p['rotation']);c,s=np.cos(angle),np.sin(angle)
    # Values and global derivatives use the same arithmetic as V1 sampling.
    u=(ctx.horizontal[sl]*c+ctx.vertical[sl]*s)/px;v=(-ctx.horizontal[sl]*s+ctx.vertical[sl]*c)/py
    if min(scene.R.shape)<2:mask=np.zeros(u.shape,np.float32)
    else:
        if sampling=='v1':
            uy,ux=np.gradient((ctx.horizontal*c+ctx.vertical*s)/px)
            vy,vx=np.gradient((-ctx.horizontal*s+ctx.vertical*c)/py)
            ux,uy,vx,vy=ux[sl],uy[sl],vx[sl],vy[sl]
        else:
            ux=(ctx.hx[sl]*c+ctx.vx[sl]*s)/px;uy=(ctx.hy[sl]*c+ctx.vy[sl]*s)/px
            vx=(-ctx.hx[sl]*s+ctx.vx[sl]*c)/py;vy=(-ctx.hy[sl]*s+ctx.vy[sl]*c)/py
        fu=np.where(ctx.valid[sl],np.hypot(ux,uy),1).astype(np.float32)
        fv=np.where(ctx.valid[sl],np.hypot(vx,vy),1).astype(np.float32)
        mask=tiles.sample(rip,u,v,fu,fv)
    SAMPLE_CACHE.put(key,mask)
    return mask


def damage(scene,field,cfg,stats):
    from .effects import damage_maps
    p=dict(cfg,strength=100)
    if not p['enabled'] or cfg['strength']==0:
        return None
    key=data.digest('damage-v2',scene._nf_signature,scene.seed,field['signature'],p,field.get('damage_strokes',[]))
    hit=DAMAGE_CACHE.get(key)
    if hit is None:
        stats['damage_misses']+=1
        import copy
        raw_scene=copy.copy(scene);raw_scene.alpha=np.ones(scene.R.shape,np.float32)
        hit=damage_maps(raw_scene,field,p,float(np.sqrt(scene.w*scene.h/(1280*1920))))
        DAMAGE_CACHE.put(key,hit)
    else:stats['damage_hits']+=1
    loss,yarn,count=hit
    return loss*(cfg['strength']/100)*scene.alpha,yarn*(cfg['strength']/100)*scene.alpha,count


def render(scene,field,base,cfg,rect=None):
    from .effects import _blend
    stats=dict(sample_hits=0,sample_misses=0,damage_hits=0,damage_misses=0)
    ctx,hit=context(scene,field);stats['surface_hit']=hit
    sl=_slice(rect)
    view=SimpleNamespace(src=scene.src[sl],alpha=scene.alpha[sl],R=scene.R[sl])
    out=base.astype(np.float32)
    for layer in cfg['layers']:
        p=layer['params']
        if not p['enabled'] or p['opacity']==0 or layer['type']=='text' and not p['content'].strip():continue
        mask=sampled(scene,ctx,layer,rect,stats,cfg.get("sampling","field"))
        out=_blend(out,view,mask,p,p['mode']=='fabric')
    maps=damage(scene,field,cfg['damage'],stats)
    count=0
    if maps is not None:
        loss,yarn,count=maps
        if count:
            loss=loss[sl]
            # Roll at image boundaries, never at the cropped preview boundary.
            shadow=(np.roll(yarn,1,axis=1)*.22*(np.roll(scene.R,1,axis=1)==scene.R))[sl]
            out=out*(1-loss[...,None])+view.src*loss[...,None]
            out=out*(1-shadow[...,None])
            out+=(255-out)*yarn[sl][...,None]*.42
    inside=(view.R>0)&(view.alpha>0);out[~inside]=view.src[~inside]
    info=dict(effects_version=2,layer_count=len(cfg['layers']),damage_count=count,
              text_enabled=any(x['type']=='text' and x['params']['enabled'] for x in cfg['layers']),effect_cache=stats)
    return np.round(np.clip(out,0,255)).astype(np.uint8),info
