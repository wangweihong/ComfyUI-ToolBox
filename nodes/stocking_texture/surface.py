"""Read-only image-wide sampling context; ROI views retain global derivatives."""
from dataclasses import dataclass
import numpy as np
from .core import look
from . import data


@dataclass(frozen=True)
class SurfaceContext:
    original: np.ndarray
    region_mask: np.ndarray
    coverage: np.ndarray
    occlusion_boundary: np.ndarray
    reference_size: tuple
    horizontal: np.ndarray
    vertical: np.ndarray
    hx: np.ndarray
    hy: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    valid: np.ndarray
    signature: str
    scale: float


def context(scene, field):
    cached=getattr(scene,'_nf_surface',None)
    if cached is not None:
        return cached,True
    horizontal,vertical=scene.A.copy(),scene.V.copy()
    if min(scene.R.shape)>=2:
        ay,ax=np.gradient(horizontal);vy,vx=np.gradient(vertical)
        for rid in np.unique(scene.R[scene.R>0]):
            inside=scene.R==rid
            if np.median(ax[inside])<0:horizontal[inside]*=-1
            if np.median(vy[inside])<0:vertical[inside]*=-1
        hy,hx=np.gradient(horizontal);vy,vx=np.gradient(vertical)
    else:
        hx=hy=vx=vy=np.zeros_like(horizontal)
    same=scene.R>0
    for shift in ((0,1),(0,-1),(1,0),(-1,0)):
        same &= np.roll(scene.R,shift,(0,1))==scene.R
    if scene.cut is not None:same &= ~scene.cut
    for a in (horizontal,vertical,hx,hy,vx,vy,same):a.setflags(write=False)
    original,regions,coverage,boundary=scene.src.view(),scene.R.view(),scene.alpha.view(),field['cut'].view()
    for a in (original,regions,coverage,boundary):a.setflags(write=False)
    cached=SurfaceContext(original,regions,coverage,boundary,(scene.w,scene.h),horizontal,vertical,hx,hy,vx,vy,same,data.digest(field['signature'],scene.R),float(np.sqrt(scene.w*scene.h/look.REF_AREA)))
    scene._nf_surface=cached
    return cached,False
