export const RENDER_DEFAULTS = {renderer_version:"legacy", layer_mode:"replacement", moire_on:false, moire:100, moire_area:100, sparkle_link:false};
export const MATERIAL_DEFAULTS = {style:"knit",density:100,tilt:32,strength:100,strength_auto:true,color_exclude:true,
    sparkle_depth:100,sparkle_bright:100,sparkle_painted:0,sparkle_even:0,seed:20261005,effects_json:"{}",...RENDER_DEFAULTS};

export function linkedSparklePatch(patch, linked, depth) {
    if (patch.sparkle_link === true) return {...patch,sparkle_bright:depth};
    const value=patch.sparkle_depth ?? patch.sparkle_bright;
    return linked && value!==undefined ? {...patch,sparkle_depth:value,sparkle_bright:value} : patch;
}

export function nearestPath(paths, point, tolerance) {
    let best = -1, distance = tolerance;
    for (let i=0;i<paths.length;i++) {
        const pts = paths[i].points || paths[i];
        for (let j=0;j<pts.length;j++) {
            const a=pts[j], b=pts[Math.min(j+1,pts.length-1)], dx=b[0]-a[0],dy=b[1]-a[1];
            const t=Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy||1)));
            const d=Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy);
            if (d<=distance) {best=i;distance=d;}
        }
    }
    return best;
}

// Remove new painted pixels from other regions, including their external base mask.
export function claimPixels(maskRGBA, eraseRGBA, coverage) {
    for(let i=0;i<coverage.length;i++) if(coverage[i]>127) {
        const k=i*4; maskRGBA[k]=maskRGBA[k+1]=maskRGBA[k+2]=0;
        eraseRGBA[k]=eraseRGBA[k+1]=eraseRGBA[k+2]=255;
    }
}

export function nearestPoint(path, point) {
    let best=path[0],distance=Infinity;
    for(let j=0;j<path.length;j++) {
        const a=path[j],b=path[Math.min(j+1,path.length-1)],dx=b[0]-a[0],dy=b[1]-a[1];
        const t=Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy||1)));
        const p=[a[0]+t*dx,a[1]+t*dy],d=Math.hypot(p[0]-point[0],p[1]-point[1]);
        if(d<distance){best=p;distance=d;}
    }
    return best;
}
