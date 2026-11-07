# Third-party notices

`vendor/image_meta.py` is copied verbatim from [laurigates/comfyui-gallery-loader](https://github.com/laurigates/comfyui-gallery-loader), commit `bda772adc2bac4dca1e53b86e339011147c5dfbc` (MIT). The original copyright and license are preserved in `vendor/gallery-loader-LICENSE`; source provenance is recorded in `vendor/UPSTREAM.txt`.

The HTTP, catalog, file-management and UI implementations in this plugin are new. The same-origin selection bridge and custom DOM-widget approach reference the local [wangweihong/comfyui-pose-gallery](https://github.com/wangweihong/comfyui-pose-gallery) design. No gallery images, datasets or upstream build bundles are included.

The browser-test illustrations are deterministic generated geometry, and video/audio samples are generated with FFmpeg for temporary test runs only.

## ToolBox integration

Integrated from wangweihong/comfyui-media-library, local source revision `8631e27eb3cf673a2903ad2b29ad25ae1c0122b7`. ToolBox uses a new node ID, isolated API namespace, event names and data directory. The original MIT license is retained in LICENSE.
