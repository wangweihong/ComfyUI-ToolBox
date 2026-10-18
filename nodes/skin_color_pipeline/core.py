"""Skin-only measurement and bounded Lab correction; no image-wide matching."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

MODEL_NAME = 'selfie_multiclass_256x256.tflite'
MODEL_SHA256 = 'c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0'
_LOCK = threading.Lock()
_SEGMENTER = None
_MODEL_PATH = None
XYZ = np.array([[.4124564,.3575761,.1804375], [.2126729,.7151522,.0721750],
                [.0193339,.1191920,.9503041]], dtype=np.float32)
XYZ_INV = np.linalg.inv(XYZ).astype(np.float32)
WHITE = np.array([.95047,1.,1.08883], dtype=np.float32)


def rgb_to_lab(rgb):
    c = np.asarray(rgb, dtype=np.float32)
    linear = np.where(c <= .04045, c/12.92, ((c+.055)/1.055)**2.4)
    v = (linear @ XYZ.T)/WHITE
    delta = 6/29
    f = np.where(v > delta**3, np.cbrt(v), v/(3*delta**2)+4/29)
    return np.stack([116*f[...,1]-16, 500*(f[...,0]-f[...,1]),
                     200*(f[...,1]-f[...,2])], axis=-1)


def lab_to_rgb(lab):
    lab = np.asarray(lab, dtype=np.float32)
    fy=(lab[...,0]+16)/116
    f=np.stack([fy+lab[...,1]/500,fy,fy-lab[...,2]/200],axis=-1)
    delta=6/29
    xyz=np.where(f>delta, f**3, 3*delta**2*(f-4/29))*WHITE
    linear=xyz @ XYZ_INV.T
    return np.clip(np.where(linear<=.0031308, linear*12.92,
                           1.055*np.maximum(linear,0)**(1/2.4)-.055),0,1)


def color_guard(rgb):
    r,g,b=rgb[...,0],rgb[...,1],rgb[...,2]
    mx=rgb.max(axis=-1);mn=rgb.min(axis=-1)
    sat=(mx-mn)/np.maximum(mx,1e-5)
    # White backgrounds/socks, purple cloth/irises, saturated lips and yellow
    # metal are excluded. This gate refines semantic masks, never replaces them.
    lab=rgb_to_lab(rgb)
    return ((r-g>.008)&(r-b>.008)&(sat>.035)&(sat<.55)&
            (lab[...,0]>35)&(lab[...,0]<96)&(lab[...,1]>1)&
            (lab[...,1]<25)&(lab[...,2]>-8)&(lab[...,2]<28))


def _segmenter(path):
    global _SEGMENTER,_MODEL_PATH
    path=Path(path)
    if not path.is_file():
        raise RuntimeError(f'缺少已缓存的皮肤分割模型：{path}。不会自动下载。')
    with _LOCK:
        if _SEGMENTER is not None and str(path)==_MODEL_PATH:
            return _SEGMENTER
        if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA256:
            raise RuntimeError('皮肤分割模型校验失败；请使用指定的selfie_multiclass模型。')
        import mediapipe as mp
        options=mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            output_confidence_masks=True,output_category_mask=False)
        if _SEGMENTER is not None:_SEGMENTER.close()
        _SEGMENTER=mp.tasks.vision.ImageSegmenter.create_from_options(options)
        _MODEL_PATH=str(path)
        return _SEGMENTER


def _resize_probability(value,w,h):
    return np.asarray(Image.fromarray(np.asarray(value,dtype=np.float32).squeeze()).resize(
        (w,h),Image.Resampling.BILINEAR),dtype=np.float32)


def layout_tiles(width,height,mode,geometry=None):
    if mode=='auto': mode='character_sheet' if width/height>1.4 else 'single_person'
    if mode=='single_person':return [(0,0,width,height,'reference')]
    split=round(width*.60)
    top=int(geometry['detail_y']) if geometry else round(height*.096)
    grid_h=int(geometry['detail_height']) if geometry else round(height*.808)
    if top<0 or grid_h<=0 or top+grid_h>height:raise ValueError('细节网格区域超出画布。')
    tiles=[]
    for col in range(3):
        tiles.append((round(split*col/3),0,round(split*(col+1)/3),height,f'view_{col+1}'))
    for row in range(4):
        for col in range(3):
            tiles.append((split+round((width-split)*col/3),top+round(grid_h*row/4),
                          split+round((width-split)*(col+1)/3),top+round(grid_h*(row+1)/4),
                          f'detail_{row*3+col+1}'))
    return tiles


def skin_masks(images,model_path,mode='auto',confidence=.55,erode=2,external=None,geometries=None):
    import mediapipe as mp
    from scipy.ndimage import label as connected_labels
    segmenter=_segmenter(model_path)
    frames=[];unions=[];summaries=[]
    for fi,rgb in enumerate(images):
        h,w=rgb.shape[:2];union=np.zeros((h,w),dtype=np.float32);tiles=[]
        geometry=None if geometries is None else geometries[min(fi,len(geometries)-1)]
        for x0,y0,x1,y1,label in layout_tiles(w,h,mode,geometry):
            patch=np.ascontiguousarray(rgb[y0:y1,x0:x1,:3])
            pixels=np.clip(np.rint(patch*255),0,255).astype(np.uint8)
            with _LOCK:
                result=segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=pixels))
            probs=result.confidence_masks
            if len(probs)<4:raise RuntimeError('皮肤语义模型未返回身体/面部类别。')
            body=_resize_probability(probs[2].numpy_view(),x1-x0,y1-y0)
            face=_resize_probability(probs[3].numpy_view(),x1-x0,y1-y0)
            valid=color_guard(patch)
            # Outdoors, skin-colored bark can touch a leg through a few pixels.
            # Keep reference growth inside the semantic foreground confidence.
            is_reference=(mode=='single_person' or (mode=='auto' and w/h<=1.4))
            if is_reference:valid &= np.maximum(face,body)>=max(.15,confidence*.35)
            ext=None if external is None else external[min(fi,len(external)-1),y0:y1,x0:x1]
            if ext is not None:valid &= ext>.5
            maps={k:np.zeros(valid.shape,dtype=np.float32) for k in ('face','body')}
            components,ncomponents=connected_labels(valid)
            face_seed=(face>=confidence)&(face>=body)&valid
            body_seed=(body>=confidence)&(body>face)&valid
            # Fill only color-compatible components with semantic skin evidence.
            # This prevents coarse semantic holes turning into painted islands.
            for component in range(1,ncomponents+1):
                region=components==component;size=int(region.sum())
                nf=int((face_seed&region).sum());nb=int((body_seed&region).sum())
                if nf+nb>=max(8,round(size*.02)):
                    maps['face' if nf>=nb else 'body'][region]=1
            # The ordered sheet's tenth panel is explicitly a bare knee/calf crop.
            # A selfie segmenter often misses such headless close-ups. Color-only
            # fallback is limited to this named tile with >70% compatible pixels.
            detail_fallback=label=='detail_10' and valid.mean()>.70 and not np.any(maps['body'])
            if detail_fallback:maps['body'][valid]=1
            for kind,p,other in [('face',face,body),('body',body,face)]:
                binary=maps[kind]>.5
                if erode>0:
                    binary=np.asarray(Image.fromarray(binary.astype(np.uint8)*255).filter(
                        ImageFilter.MinFilter(erode*2+1)))>127
                maps[kind]=binary.astype(np.float32)
            if np.any(maps['face']) or np.any(maps['body']):
                tiles.append({'box':[x0,y0,x1,y1],'label':label,
                              'anatomical_detail_fallback':detail_fallback,**maps})
                union[y0:y1,x0:x1]=np.maximum(maps['face'],maps['body'])
        count=int((union>.5).sum())
        if count<100:raise RuntimeError('皮肤遮罩不足100像素；请查看参考图、降低置信度或提供外部遮罩。')
        frames.append({'tiles':tiles,'shape':[h,w]});unions.append(union)
        summaries.append({'frame':fi,'skin_pixels':count,'coverage':count/(h*w),
                          'tiles':[{'label':t['label'],'face_pixels':int(t['face'].sum()),
                                    'body_pixels':int(t['body'].sum())} for t in tiles]})
    return np.stack(unions),{'frames':frames,'method':'MediaPipe face/body skin + RGB/Lab guard'},summaries


def _stats(pixels):
    # Quantize to exported PNG precision for repeatable RGB/Lab reporting.
    rgb=np.clip(np.floor(pixels*255),0,255)/255
    labs=rgb_to_lab(rgb)
    med=np.median(rgb,axis=0)*255
    lab=np.median(labs,axis=0)
    return {'rgb_median':np.round(med,3).tolist(),
            'hex':'#'+''.join(f'{int(np.floor(v+.5)):02X}' for v in med),
            'lab_median':np.round(lab,4).tolist(),'pixels':len(rgb),
            'L_p10_p90':np.percentile(labs[:,0],[10,90]).round(4).tolist()}


def make_sample(images,packet,low=20,high=80,max_pixels=50000):
    selections=[];frames=[]
    for fi,frame in enumerate(packet['frames']):
        entries=[];by_kind={'face':[],'body':[]};tile_stats=[]
        for ti,tile in enumerate(frame['tiles']):
            x0,y0,x1,y1=tile['box'];flat=images[fi,y0:y1,x0:x1,:3].reshape(-1,3)
            for kind in ('face','body'):
                ids=np.flatnonzero(tile[kind].reshape(-1)>.5)
                if len(ids)<32:continue
                if len(ids)>max_pixels:ids=ids[np.linspace(0,len(ids)-1,max_pixels).astype(int)]
                L=rgb_to_lab(flat[ids])[:,0];lo,hi=np.percentile(L,[low,high])
                ids=ids[(L>=lo)&(L<=hi)]
                if len(ids)<16:continue
                values=flat[ids]
                entries.append({'tile':ti,'kind':kind,'ids':ids})
                by_kind[kind].append(values)
                tile_stats.append({'tile':ti,'label':tile['label'],'kind':kind,'stats':_stats(values)})
        stats={k:_stats(np.concatenate(v)) for k,v in by_kind.items() if v}
        if not stats:raise RuntimeError('没有可用的皮肤中间调取样。')
        stats['all']=_stats(np.concatenate([x for v in by_kind.values() for x in v]))
        frames.append({'groups':stats,'tiles':tile_stats});selections.append(entries)
    return {'frames':frames,'selections':selections,'packet':packet,
            'trim_percentiles':[low,high],'color_space':'sRGB/D65 assumed; rendered skin midtones, not PBR albedo'}


def resample_fixed(images,sample):
    """Reuse BEFORE indices: no after-color resegmentation or percentile selection."""
    frames=[]
    for fi,entries in enumerate(sample['selections']):
        values={'face':[],'body':[]};tiles=[]
        for entry in entries:
            tile=sample['packet']['frames'][fi]['tiles'][entry['tile']]
            x0,y0,x1,y1=tile['box'];px=images[fi,y0:y1,x0:x1,:3].reshape(-1,3)[entry['ids']]
            values[entry['kind']].append(px)
            tiles.append({'tile':entry['tile'],'label':tile['label'],'kind':entry['kind'],'stats':_stats(px)})
        groups={k:_stats(np.concatenate(v)) for k,v in values.items() if v}
        groups['all']=_stats(np.concatenate([x for v in values.values() for x in v]))
        frames.append({'groups':groups,'tiles':tiles})
    return frames


def public_sample(sample):
    return {k:v for k,v in sample.items() if k not in ('selections','packet')}


def color_prompt(base,sample):
    groups=sample['frames'][0]['groups'];terms=[]
    for kind,label in [('face','face'),('body','neck, arms and legs')]:
        stats=groups.get(kind,groups['all']);rgb=', '.join(str(int(np.floor(x+.5))) for x in stats['rgb_median'])
        terms.append(f'{label}: approximate rendered midtone sRGB ({rgb}), hex {stats["hex"]}')
    block=('\n\nMEASURED REFERENCE SKIN COLOR FOR <Subject 1>\n'
           'Preserve the pale neutral-pink skin appearance from <Picture 1>. '
           +' ; '.join(terms)+'. '
           'These measured image colors are midtone references, not flat paint or PBR base-color values. '
           'Use neutral white-balanced studio lighting, broad soft fill and shallow skin shadows. '
           'Preserve natural shading and skin texture without tanning, bronzing or a yellow/brown skin shift. '
           'Keep the same skin material across the turnaround and detail panels. '
           'Do not print any RGB numbers, color codes, swatches or text on the board.')
    return base.rstrip()+block


def distances(reference,frames):
    ref=reference['frames'][0]['groups'];records=[]
    for fi,frame in enumerate(frames):
        for tile in frame['tiles']:
            anchor=ref.get(tile['kind'],ref['all'])
            delta=np.array(tile['stats']['lab_median'])-anchor['lab_median']
            records.append({'frame':fi,'label':tile['label'],'kind':tile['kind'],
                            'delta_lab':delta.round(4).tolist(),
                            'delta_E76':float(np.linalg.norm(delta)),
                            'chroma_error':float(np.linalg.norm(delta[1:]))})
    return records


def summarize(records):
    if not records:return {'median_delta_E76':None,'median_chroma_error':None}
    return {'median_delta_E76':float(np.median([r['delta_E76'] for r in records])),
            'median_chroma_error':float(np.median([r['chroma_error'] for r in records])),
            'regions':len(records)}


def matched_baseline_comparison(baseline,before,after):
    def mapping(records):return {(r['frame'],r['label'],r['kind']):r for r in records}
    old,new,corrected=map(mapping,[baseline,before,after])
    common=sorted(old.keys()&new.keys()&corrected.keys())
    if len(common)<3:
        return {'common_regions':len(common),'improved':None,
                'reason':'Fewer than three matching region/type pairs; no prompt-effect conclusion.'}
    medians=[float(np.median([source[k]['delta_E76'] for k in common]))
             for source in [old,new,corrected]]
    reduction=medians[0]-medians[1]
    return {'common_regions':len(common),'baseline_median_delta_E76':medians[0],
            'rgb_prompt_median_delta_E76':medians[1],'calibrated_median_delta_E76':medians[2],
            'improved':reduction>0,'delta_E_reduction':reduction,'small_effect':abs(reduction)<1.,
            'regions':[{'label':k[1],'kind':k[2],'baseline':old[k]['delta_E76'],
                        'rgb_prompt':new[k]['delta_E76'],'calibrated':corrected[k]['delta_E76']} for k in common],
            'method':'Same region labels/types across baseline, RGB prompt and correction; different poses are not pixel-registered. A single run is not evidence of stable prompt improvement.'}


def correct_skin(images,reference,target,strength=.75,threshold=3.,max_L=18.,max_chroma=8.,feather=6.,enabled=True):
    from scipy.ndimage import distance_transform_edt
    output=images.copy();used=np.zeros(images.shape[:3],dtype=np.float32);decisions=[]
    anchors=reference['frames'][0]['groups']
    for fi,frame in enumerate(target['frames']):
        for measured in frame['tiles']:
            tile=target['packet']['frames'][fi]['tiles'][measured['tile']]
            x0,y0,x1,y1=tile['box'];kind=measured['kind'];src=images[fi,y0:y1,x0:x1,:3]
            anchor=anchors.get(kind,anchors['all']);a=np.array(anchor['lab_median'],dtype=np.float32)
            b=np.array(measured['stats']['lab_median'],dtype=np.float32);raw=a-b
            before=float(np.linalg.norm(raw));delta=raw.copy()
            # Separate luminance from chroma and cap both, retaining local gradients.
            delta[0]=np.clip(delta[0],-max_L,max_L)
            c=float(np.linalg.norm(delta[1:]))
            if c>max_chroma:delta[1:]*=max_chroma/c
            decision={'frame':fi,'label':tile['label'],'kind':kind,'before_delta_E76':before,
                      'requested_delta_lab':raw.tolist(),'bounded_delta_lab':delta.tolist(),
                      'applied_strength':0.,'reason':'below_threshold'}
            if not enabled:decision['reason']='disabled'
            elif strength==0:decision['reason']='zero_strength'
            elif before>threshold:
                hard=tile[kind]>.5
                # A smooth inward distance ramp reaches zero at the boundary;
                # multiplying a blurred binary mask by hard edges does not.
                if feather>0:
                    t=np.clip((distance_transform_edt(hard)-1)/feather,0,1).astype(np.float32)
                    soft=t*t*(3-2*t)
                else:soft=hard.astype(np.float32)
                lab=rgb_to_lab(src)
                light_weight=np.clip((98-lab[...,0])/12,0,1)
                weights=soft*light_weight
                active=hard&(weights>0)
                entries=[e for e in target['selections'][fi] if e['tile']==measured['tile'] and e['kind']==kind]
                ids=entries[0]['ids']
                for fraction in (strength,strength*.5,strength*.25):
                    candidate=lab_to_rgb(lab+weights[...,None]*delta*fraction)
                    changed=src.copy();changed[active]=candidate[active]
                    after_stats=_stats(changed.reshape(-1,3)[ids])
                    after=float(np.linalg.norm(np.array(after_stats['lab_median'])-a))
                    if after+1e-3<before:
                        roi=output[fi,y0:y1,x0:x1,:3];roi[active]=changed[active]
                        used[fi,y0:y1,x0:x1]=np.maximum(used[fi,y0:y1,x0:x1],weights*fraction)
                        decision.update(applied_strength=fraction,reason='improved',candidate_delta_E76=after)
                        break
                else:decision['reason']='candidate_did_not_improve'
            decisions.append(decision)
    before_records=distances(reference,target['frames'])
    after_frames=resample_fixed(output,target);after_records=distances(reference,after_frames)
    before_summary=summarize(before_records);after_summary=summarize(after_records)
    report={'reference':public_sample(reference),'before':public_sample(target),
            'after':{'frames':after_frames,'sampling':'exactly the same indices as before'},
            'before_errors':before_records,'after_errors':after_records,
            'before_summary':before_summary,'after_summary':after_summary,'decisions':decisions,
            'improved':after_summary['median_delta_E76']<before_summary['median_delta_E76'],
            'max_rgb_change_outside_skin':float(np.max(np.abs(output-images)[used<=0])) if np.any(used<=0) else 0.,
            'correction_triggered':any(d['applied_strength']>0 for d in decisions),
            'settings':{'enabled':enabled,'strength':strength,'threshold':threshold,'max_L_shift':max_L,
                        'max_chroma_shift':max_chroma,'feather':feather},
            'limitations':'Rendered image statistics; segmentation and unseen designs require visual review. No guarantee of physical skin albedo or pixel-identical color.'}
    return output,used,report


def reflow_board(image,source_split=.5):
    """Find white-background figure spans and vertical grid lines, preserve aspect."""
    from scipy.ndimage import binary_closing, label
    h,w=image.shape[:2];gray=image.mean(axis=-1);neutral=(image.max(axis=-1)-image.min(axis=-1))<.08
    scores=((gray<.3)&neutral).mean(axis=0)
    candidates=np.flatnonzero((scores>.80)&(np.arange(w)>w*.35)&(np.arange(w)<w*.75))
    split=int(candidates[0]) if len(candidates) else round(w*source_split)
    foreground=image[:,:split].min(axis=-1)<.94
    occupied=foreground.sum(axis=0)>h*.008
    occupied=binary_closing(occupied,iterations=max(2,round(w/512)))
    labels,n=label(occupied);spans=[]
    for group in range(1,n+1):
        xs=np.flatnonzero(labels==group)
        if len(xs)>w*.025:spans.append((int(xs[0]),int(xs[-1])+1,int(foreground[:,xs].sum())))
    spans=sorted(sorted(spans,key=lambda p:p[2],reverse=True)[:3])
    if len(spans)!=3:
        raise RuntimeError(f'未找到三个完整角色区域（检测到{len(spans)}）；请检查原始排版和source_split。')
    result=np.ones_like(image);left=round(w*.60);margin=max(8,round(h*.008));placements=[]
    for col,(x0,x1,area) in enumerate(spans):
        x0=max(0,x0-margin);x1=min(split,x1+margin)
        ys=np.flatnonzero(foreground[:,x0:x1].any(axis=1))
        y0=max(0,int(ys[0])-margin);y1=min(h,int(ys[-1])+1+margin)
        cw,ch=x1-x0,y1-y0;cell_left=round(left*col/3);cell_right=round(left*(col+1)/3)
        scale=min((cell_right-cell_left-2*margin)/cw,(h-2*margin)/ch)
        nw,nh=max(1,round(cw*scale)),max(1,round(ch*scale))
        patch=np.asarray(Image.fromarray(np.clip(image[y0:y1,x0:x1]*255,0,255).astype(np.uint8)).resize((nw,nh),Image.Resampling.LANCZOS),dtype=np.float32)/255
        x=cell_left+(cell_right-cell_left-nw)//2;y=h-margin-nh
        result[y:y+nh,x:x+nw]=patch
        placements.append({'source_box':[x0,y0,x1,y1],'destination_box':[x,y,x+nw,y+nh]})
    gw=w-split;tw=w-left;th=round(h*tw/gw)
    if th>h:raise RuntimeError('细节网格高度超出画布，请检查源图区域。')
    grid=np.asarray(Image.fromarray(np.clip(image[:,split:]*255,0,255).astype(np.uint8)).resize((tw,th),Image.Resampling.LANCZOS),dtype=np.float32)/255
    top=(h-th)//2;result[top:top+th,left:]=grid
    return result,{'source_grid_left':split,'grid_detected':bool(len(candidates)),
                   'left_width':left,'right_width':tw,'detail_y':top,'detail_height':th,
                   'figures':placements}
