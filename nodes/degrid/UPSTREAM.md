# DeGrid provenance and license scope

`degrid_core.py` is copied without changes from
[lunaaispace-eng/ComfyUI-DeGrid](https://github.com/lunaaispace-eng/ComfyUI-DeGrid),
commit [`8082f8b04e0b4a79220e493d5647a0c32e1ff855`](https://github.com/lunaaispace-eng/ComfyUI-DeGrid/commit/8082f8b04e0b4a79220e493d5647a0c32e1ff855).
The upstream Apache-2.0 license is retained in the adjacent `LICENSE` file.
Upstream supplies no NOTICE file or additional copyright header.

The Apache-2.0 notice applies to this third-party DeGrid component, not to
ToolBox as a whole or to its other modules. Existing module licenses remain
unchanged. No root license is added or replaced.

`nodes.py` adapts the upstream node schema and status formatting to ToolBox's
legacy node interface. The adapter uses a distinct `ToolBoxVAEDeGrid` ID,
restores skipped frames directly from the original tensor for exact passthrough,
and returns structured execution status for the ToolBox frontend. It is marked
as a UI output node so cached executions can replay the status after a page reload;
this does not save images or force the filter to recompute. The frontend,
localization, examples and tests are ToolBox integration code. The core filter,
lattice detector, auto-calibration and preview routines are unchanged.
