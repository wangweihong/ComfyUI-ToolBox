# Origin and compatibility

Migrated from the local ComfyUI-H3-DanceMV package into ComfyUI-ToolBox on 2026-10-21.

The existing class IDs, socket order, parameters, defaults and inference logic are preserved. The three current nodes are exposed under ToolBox/DanceMV. DanceMVChoreography and DanceMVAfterVideo remain deprecated compatibility entries for historical workflows. Stop loading the standalone package after migration to avoid duplicate class IDs.

The local planner still receives measured music data and user movement intent; no manual final prompt is required. Migration did not rerun tests or music/video generation, as requested.
