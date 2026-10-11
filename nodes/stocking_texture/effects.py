"""Surface-space prints and fabric damage, outside the unchanged upstream core."""
import copy
import json
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import data
from .cache import ByteLRU
from .core import look, tiles
from .styles import PATTERNS

TILE_CACHE = ByteLRU(16 * 1024**2, 32)
EFFECT_CACHE = ByteLRU(32 * 1024**2, 8)
from .config import LEGACY_DEFAULTS as DEFAULTS, clean_effects
FONT = Path(__file__).with_name("fonts") / "DejaVuSans-Bold.ttf"


def _line(value, width):
    distance = np.abs((value + .5) % 1 - .5)
    return np.clip((width - distance) * 256 + .5, 0, 1)


def pattern_tile(style):
    key = ("pattern", style)
    cached = TILE_CACHE.get(key)
    if cached is not None:
        return cached
    n = 256
    v, u = (np.mgrid[:n, :n] + .5) / n
    if style == "polka":
        mask = np.zeros((n, n))
        for x, y in ((.25, .25), (.75, .75)):
            mask = np.maximum(mask, np.clip((.11 - np.hypot(u - x, v - y)) * n + .5, 0, 1))
    elif style == "hearts":
        mask = np.zeros((n, n))
        for x, y in ((.25, .25), (.75, .75)):
            a, b = (u - x) / .12, -(v - y) / .12
            mask = np.maximum(mask, np.clip(-((a*a + b*b - 1)**3 - a*a*b**3) * 4, 0, 1))
    elif style in ("diamonds", "fishnet_small", "fishnet_large"):
        width = {"diamonds": .023, "fishnet_small": .055, "fishnet_large": .027}[style]
        mask = np.maximum(_line(u + v, width), _line(u - v, width))
        if style == "diamonds":
            mask = np.maximum(mask, .45 * np.maximum(_line(u + v + .10, .008), _line(u - v + .10, .008)))
    elif style in ("floral", "lace"):
        mask = np.zeros((n, n))
        for x, y, r in ((.27, .27, .17), (.73, .73, .15)):
            dx, dy = u - x, v - y
            radius, theta = np.hypot(dx, dy), np.arctan2(dy, dx)
            edge = r * (.72 + .28 * np.cos(theta * 5))
            if style == "floral":
                petals = np.clip((edge - radius) * n, 0, 1)
                center = np.clip((.034 - radius) * n, 0, 1)
                mask = np.maximum(mask, petals * (1 - .6 * center))
            else:
                mask = np.maximum(mask, np.clip((.013 - np.abs(edge - radius)) * n, 0, 1))
                mask = np.maximum(mask, .75 * np.clip((.022 - radius) * n, 0, 1))
        vine = np.abs(u - (.5 + .16 * np.sin(v * 2 * np.pi)))
        mask = np.maximum(mask, np.clip((.012 - vine) * n, 0, 1))
        for x, y in ((.53, .42), (.46, .88)):
            dx, dy = u-x, v-y
            leaf = (dx/.09)**2 + ((dy + dx*.6)/.035)**2
            mask = np.maximum(mask, np.clip((1-leaf) * 8, 0, 1))
        if style == "lace":
            mesh = np.maximum(_line((u+v)*4, .026), _line((u-v)*4, .026))
            mask = np.maximum(mask, mesh * .35)
    elif style == "leopard":
        mask = np.zeros((n, n))
        for x, y, r, phase in ((.25,.23,.13,1),(.72,.68,.16,3),(.77,.17,.07,2),(.2,.76,.075,4)):
            dx, dy = u-x, (v-y)*1.1
            theta = np.arctan2(dy, dx)
            edge = r*(1 + .15*np.cos(3*theta+phase) + .08*np.sin(5*theta))
            ring = np.clip((.027 - np.abs(np.hypot(dx,dy)-edge))*n,0,1)
            ring *= (np.sin(theta*2+phase) > -.65)
            mask = np.maximum(mask, ring)
        for x,y in ((.48,.48),(.48,.9),(.95,.4)):
            mask = np.maximum(mask,np.clip((.025-np.hypot(u-x,v-y))*n,0,1))
    else:
        raise ValueError(f"未知花纹：{style}")
    rip = tiles.ripmap(mask.astype(np.float32))
    TILE_CACHE.put(key, rip)
    return rip


def text_tile(cfg):
    key = ("text", cfg["content"], cfg["spacing_x"], cfg["spacing_y"])
    cached = TILE_CACHE.get(key)
    if cached is not None:
        return cached
    font = ImageFont.truetype(str(FONT), 64)
    bounds = font.getbbox(cfg["content"])
    width, height = max(bounds[2] - bounds[0], 1), max(bounds[3] - bounds[1], 1)
    cell_w = max(width + 8, round(width + 48 * cfg["spacing_x"] / 100))
    cell_h = max(height + 8, round(height + 64 * cfg["spacing_y"] / 100))
    tile = Image.new("L", (cell_w, cell_h * 2))
    draw = ImageDraw.Draw(tile)
    for row in range(2):
        for col in (-1, 0, 1):
            draw.text((col*cell_w + (cell_w//2 if row else 0) + 4 - bounds[0],
                       row*cell_h + 4 - bounds[1]), cfg["content"], font=font, fill=255)
    # Bound the atlas even for a long phrase; surface aspect ratio retains its layout.
    aspect = tile.size
    tile.thumbnail((2048, 512), Image.Resampling.LANCZOS)
    value = (tiles.ripmap(np.asarray(tile, np.float32) / 255), aspect)
    TILE_CACHE.put(key, value)
    return value


def surface_coordinates(scene):
    """Orient text to screen-right/down on each region, without left/right mirroring."""
    horizontal, vertical = scene.A.copy(), scene.V.copy()
    if min(scene.R.shape) < 2:
        return horizontal, vertical
    ay, ax = np.gradient(horizontal)
    vy, vx = np.gradient(vertical)
    for rid in np.unique(scene.R[scene.R > 0]):
        inside = scene.R == rid
        if np.median(ax[inside]) < 0:
            horizontal[inside] *= -1
        if np.median(vy[inside]) < 0:
            vertical[inside] *= -1
    return horizontal, vertical


def sample_surface(rip, horizontal, vertical, period_x, period_y, rotation, scene):
    angle = np.deg2rad(rotation)
    u = (horizontal*np.cos(angle) + vertical*np.sin(angle)) / period_x
    v = (-horizontal*np.sin(angle) + vertical*np.cos(angle)) / period_y
    if min(u.shape) < 2:
        return np.zeros(u.shape, np.float32)
    uy, ux = np.gradient(u)
    vy, vx = np.gradient(v)
    same = scene.R > 0
    for shift in ((0,1),(0,-1),(1,0),(-1,0)):
        same &= np.roll(scene.R, shift, (0,1)) == scene.R
    if scene.cut is not None:
        same &= ~scene.cut
    # Borders have no meaningful coordinate derivatives: use the coarsest level there.
    fu = np.where(same, np.hypot(ux, uy), 1).astype(np.float32)
    fv = np.where(same, np.hypot(vx, vy), 1).astype(np.float32)
    return tiles.sample(rip, u, v, fu, fv)


def _blend(out, scene, mask, cfg, fabric=False):
    alpha = np.clip(mask * scene.alpha * (scene.R > 0) * cfg["opacity"] / 100, 0, 1)[..., None]
    color = np.array([int(cfg["color"][i:i+2],16) for i in (5,3,1)],np.float32)
    if fabric:
        # Preserve local light and translucent background, including white yarn on dark fabric.
        light = scene.src.max(axis=2).astype(np.float32) / 255
        target = color[None,None,:] * (.35 + .65*light[...,None])
        alpha *= .72
    else:
        target = color
    return out * (1-alpha) + target * alpha


def _follow(scene, field, x, y, length):
    points = [[float(x), float(y)]]
    steps = max(2, min(128, int(np.ceil(length / 3))))
    step = length / steps
    for _ in range(steps):
        px, py = points[-1]
        ix, iy = int(np.clip(px,0,scene.w-1)), int(np.clip(py,0,scene.h-1))
        dx, dy = field["NX"][iy,ix], field["NY"][iy,ix]
        norm = np.hypot(dx,dy)
        if norm < .01:
            dx,dy = 0,1
        else:
            dx,dy = dx/norm,dy/norm
            if dy < 0:
                dx,dy = -dx,-dy
        nx,ny = px+dx*step,py+dy*step
        if not (0<=nx<scene.w and 0<=ny<scene.h) or scene.R[int(ny),int(nx)] != scene.R[int(y),int(x)]:
            break
        points.append([nx,ny])
    return points


def damage_maps(scene, field, cfg, scale):
    loss = np.zeros(scene.R.shape, np.float32)
    yarn = np.zeros_like(loss)
    if not cfg["enabled"] or cfg["strength"] == 0:
        return loss,yarn,0
    entries = []
    if cfg["mode"] in ("manual","both"):
        for rid, strokes in enumerate(field.get("damage_strokes",[]),1):
            entries.extend((rid, s) for s in strokes)
    if cfg["mode"] in ("random","both"):
        rng = np.random.default_rng(int(data.digest(scene.src,scene.seed),16) % 2**64)
        for rid in np.unique(scene.R[scene.R>0]):
            ys,xs = np.nonzero(scene.R==rid)
            count = int(round(cfg["count"]))
            if not len(xs) or not count:
                continue
            for i in rng.integers(0,len(xs),size=count):
                kind = cfg["type"] if cfg["type"] != "mixed" else ("ladder" if rng.random()<.5 else "snag")
                path = _follow(scene,field,xs[i],ys[i],160*scale*cfg["length"]/100)
                entries.append((int(rid),{"type":kind,"points":path,"width":max(1,4*scale*cfg["width"]/100)}))
    rendered = 0
    for rid, stroke in entries:
        path = stroke["points"]
        if len(path)==1:
            path = _follow(scene,field,*path[0],160*scale*cfg["length"]/100)
        if len(path)<2:
            continue
        width = max(1,stroke["width"] * (2 if stroke["type"]=="ladder" else .55))
        pts = np.round(np.asarray(path)*16).astype(np.int32).reshape(-1,1,2)
        ribbon = np.zeros(scene.R.shape,np.uint8)
        cv2.polylines(ribbon,[pts],False,255,max(1,round(width)),cv2.LINE_AA,4)
        fill = ribbon.astype(np.float32)/255 * (scene.R==rid)
        edge = cv2.dilate(ribbon,np.ones((3,3),np.uint8)).astype(np.float32)/255 - ribbon.astype(np.float32)/255
        if stroke["type"]=="ladder":
            rungs = (.5+.5*np.cos(scene.V*2*np.pi/max(6*scale,2)))**12
            woven = fill*rungs
            loss = np.maximum(loss,fill*(1-rungs*.65))
            yarn = np.maximum(yarn,(woven*.5+edge*.55)*(scene.R==rid))
        else:
            loss = np.maximum(loss,fill*.45)
            yarn = np.maximum(yarn,(edge*.55+fill*.15)*(scene.R==rid))
        rendered += 1
    strength = cfg["strength"]/100
    return loss*strength*scene.alpha, yarn*strength*scene.alpha, rendered


def render_effects(scene, field, base, style, cfg, params, rect=None):
    if cfg["version"] == 2:
        from .layer_renderer import render
        key=data.digest('compose-v2',scene._nf_signature,params,cfg,field.get('damage_strokes',[]),rect)
        hit=EFFECT_CACHE.get(key)
        if hit is not None:
            info=dict(hit[1],effect_cache=dict(sample_hits=0,sample_misses=0,damage_hits=0,damage_misses=0,surface_hit=True,final_hit=True))
            return hit[0],info
        result=render(scene,field,base,cfg,rect)
        EFFECT_CACHE.put(key,result)
        return result
    damage = field.get("damage_strokes", [])
    key = data.digest("effects-v1",scene.__class__.__module__,scene.src,field["signature"],scene.seed,style,cfg,params,damage)
    hit = EFFECT_CACHE.get(key)
    if hit is not None:
        return hit
    horizontal,vertical = surface_coordinates(scene)
    scale = float(np.sqrt(scene.w*scene.h/look.REF_AREA))
    out = base.astype(np.float32)
    if style in PATTERNS:
        pattern = cfg["pattern"]
        period = PATTERNS[style]["period"] * scale * pattern["size"]/100
        mask = sample_surface(pattern_tile(style),horizontal,vertical,max(period,1),max(period,1),pattern["rotation"],scene)
        out = _blend(out,scene,mask,pattern,pattern["mode"]=="fabric")
    text = cfg["text"]
    if text["enabled"] and text["content"].strip() and text["opacity"]>0:
        rip, (width,height) = text_tile(text)
        ratio = .5 * scale * text["size"]/100
        mask = sample_surface(rip,horizontal,vertical,max(width*ratio,1),max(height*ratio,1),text["rotation"],scene)
        out = _blend(out,scene,mask,text,cfg["pattern"]["mode"]=="fabric")
    loss,yarn,count = damage_maps(scene,field,cfg["damage"],scale)
    if count:
        out = out*(1-loss[...,None]) + scene.src*loss[...,None]
        # A pulled thread has a pale ridge and a dark edge, rather than a flat white scratch.
        shadow = np.roll(yarn,1,axis=1) * .22 * (np.roll(scene.R,1,axis=1)==scene.R)
        out = out*(1-shadow[...,None])
        out += (255-out)*yarn[...,None]*.42
    inside = (scene.R>0)&(scene.alpha>0)
    out[~inside] = scene.src[~inside]
    value = (np.round(np.clip(out,0,255)).astype(np.uint8),{"pattern_mode":cfg["pattern"]["mode"],
             "text_enabled":text["enabled"],"damage_count":count,"effects_version":1})
    EFFECT_CACHE.put(key,value)
    return value
