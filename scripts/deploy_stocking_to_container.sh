#!/usr/bin/env bash
# Update only this feature in an existing persistent ToolBox installation.
set -euo pipefail
container_name="${1:-comfyui-test-cu130-megapak-pt211}"
plugin_root="/root/ComfyUI/custom_nodes/ComfyUI-ToolBox"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
stage_root="$(mktemp -d /tmp/toolbox-stocking.XXXXXX)"
trap 'rm -rf "$stage_root"' EXIT
mkdir -p "$stage_root/stocking_texture"
cp -a "$repo_root/nodes/stocking_texture/." "$stage_root/stocking_texture/"
find "$stage_root/stocking_texture" -type d -name __pycache__ -prune -exec rm -rf {} +
docker cp "$stage_root/stocking_texture/." "$container_name:$plugin_root/nodes/stocking_texture/"
docker cp "$repo_root/node_mappings.py" "$container_name:$plugin_root/node_mappings.py"
for file in "$repo_root"/web/js/stocking_*.js "$repo_root"/web/js/stocking_*.mjs "$repo_root"/web/js/stocking_*.json; do
    docker cp "$file" "$container_name:$plugin_root/web/js/"
done
# The new entry URL also invalidates stale browser module caches. Archive the
# former entry so ComfyUI cannot load two copies of the same extension.
if [ -f "$repo_root/web/js/stocking_texture_effects.js" ]; then
    docker exec "$container_name" bash -c 'for name in stocking_texture.js stocking_texture_editor.js; do if [ -f "$1/web/js/$name" ]; then mv "$1/web/js/$name" "$1/web/js/$name.legacy"; fi; done' bash "$plugin_root"
fi
docker cp "$repo_root/locales" "$container_name:$plugin_root/"
docker restart "$container_name"
printf 'Updated stocking nodes in %s; refresh the ComfyUI page.\n' "$container_name"
