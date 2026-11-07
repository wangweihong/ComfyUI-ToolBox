import json

from . import skill_library, skill_files
from .prompt_nodes import database_revision


class ToolBoxSkillReader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"id": ("INT", {"default": 1, "min": 1, "max": 2**63 - 1})}}

    RETURN_TYPES = ("INT", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("id", "name", "entry_type", "content", "metadata")
    FUNCTION = "read_skill"
    CATEGORY = "eazy-toolbox/skill"
    IS_CHANGED = staticmethod(database_revision)

    def read_skill(self, id):
        data = skill_library.detail(id)
        metadata = {key: value for key, value in data.items() if key not in ("content", "version")}
        metadata["files"] = skill_files.manifest(data["files"])
        metadata["download_url"] = f'/toolbox/skills/{data["id"]}/download'
        return data["id"], data["name"], data["entry_type"], data["content"], json.dumps(metadata, ensure_ascii=False)


NODE_CLASS_MAPPINGS = {"ToolBoxSkillReader": ToolBoxSkillReader}
