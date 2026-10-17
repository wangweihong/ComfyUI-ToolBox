"""Run COLMAP in a child process, keeping native crashes out of the UI server."""
import json
from pathlib import Path
import sys
import time

import numpy as np
import pycolmap as p


def main():
    root = Path(sys.argv[1])
    root.chmod(0o755)
    cfg = json.loads((root / 'config.json').read_text())
    p.logging.minloglevel = 1
    start = time.monotonic()
    db, images, sparse = root / 'database.db', root / 'images', root / 'sparse'
    sparse.mkdir(exist_ok=True)
    ext = p.FeatureExtractionOptions()
    ext.num_threads = 12
    ext.use_gpu = False
    ext.sift.max_num_features = cfg['max_features']
    print('Extract SIFT · CPU · SIMPLE_PINHOLE · shared intrinsics', flush=True)
    reader = p.ImageReaderOptions()
    reader.camera_model = 'SIMPLE_PINHOLE'
    p.extract_features(db, images, camera_mode=p.CameraMode.SINGLE, reader_options=reader,
                       extraction_options=ext, device=p.Device.cpu)
    extracted = time.monotonic()
    match = p.FeatureMatchingOptions()
    match.num_threads = 12
    match.use_gpu = False
    if cfg['matcher'] == 'exhaustive':
        p.match_exhaustive(db, matching_options=match, device=p.Device.cpu)
    else:
        pairing = p.SequentialPairingOptions()
        pairing.overlap = 10
        p.match_sequential(db, matching_options=match, pairing_options=pairing, device=p.Device.cpu)
    matched = time.monotonic()
    print('Mapping', cfg['mapper'], flush=True)
    if cfg['mapper'] == 'global':
        opts = p.GlobalPipelineOptions()
        opts.num_threads = 12
        opts.random_seed = 20261016
        opts.mapper.num_threads = 12
        opts.mapper.random_seed = 20261016
        opts.mapper.global_positioning.use_gpu = False
        opts.mapper.bundle_adjustment.ceres.use_gpu = False
        opts.mapper.bundle_adjustment.ceres.solver_options.num_threads = 12
        models = p.global_mapping(db, images, sparse, opts)
    else:
        opts = p.IncrementalPipelineOptions()
        opts.num_threads = 12
        opts.random_seed = 20261016
        opts.ba_use_gpu = False
        models = p.incremental_mapping(db, images, sparse, opts)
    if not models:
        raise RuntimeError('COLMAP could not reconstruct a model. See sfm.log; do not invent camera poses.')
    key, model = max(models.items(), key=lambda kv: kv[1].num_reg_images())
    best = sparse / '0'
    best.mkdir(exist_ok=True)
    model.write(best)
    model.write_text(best)
    model.export_PLY(root / 'sparse_points.ply')
    registered = sorted(im.name for im in model.images.values() if im.has_pose)
    errors = [pt.error for pt in model.points3D.values()]
    report = dict(pycolmap_version=p.__version__, has_cuda=p.has_cuda, mapper=cfg['mapper'], matcher=cfg['matcher'],
                  camera_model='SIMPLE_PINHOLE', input_images=len(list(images.glob('*.png'))),
                  registered_images=model.num_reg_images(), points3D=model.num_points3D(), models=len(models),
                  selected_model=int(key), registered_names=registered,
                  mean_reprojection_error=float(np.mean(errors)) if errors else None,
                  extraction_seconds=round(extracted-start,3), matching_seconds=round(matched-extracted,3),
                  mapping_seconds=round(time.monotonic()-matched,3), total_seconds=round(time.monotonic()-start,3),
                  cameras=[{'id':int(k),'model':c.model_name,'width':c.width,'height':c.height,'params':c.params.tolist()} for k,c in model.cameras.items()],
                  summary=model.summary())
    (root / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
