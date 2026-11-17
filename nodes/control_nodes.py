"""Standalone switches and primitives adapted from Crystools.

Copyright (c) 2023 Crystian. MIT license: ../licenses/Crystools-MIT.txt.
Port names and widget order deliberately match the original four nodes.
"""

import sys


class _AnyType(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


_ANY = _AnyType("*")


class ToolBoxSwitchAny:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "on_true": (_ANY, {"lazy": True}),
            "on_false": (_ANY, {"lazy": True}),
            "boolean": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = (_ANY,)
    FUNCTION = "execute"
    CATEGORY = "ToolBox/Control"
    DESCRIPTION = "Select one input without executing the unselected branch. Works with any data type."

    def check_lazy_status(self, on_true=None, on_false=None, boolean=True):
        return ["on_true" if boolean else "on_false"]

    def execute(self, on_true=None, on_false=None, boolean=True):
        return (on_true if boolean else on_false,)


class ToolBoxSwitchImage(ToolBoxSwitchAny):
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "on_true": ("IMAGE", {"lazy": True}),
            "on_false": ("IMAGE", {"lazy": True}),
            "boolean": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    DESCRIPTION = "Select one image input without executing the unselected branch."


class ToolBoxPrimitiveInteger:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "int": ("INT", {"default": 1, "min": -sys.maxsize, "max": sys.maxsize, "step": 1}),
        }}

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("int",)
    FUNCTION = "execute"
    CATEGORY = "ToolBox/Primitive"
    DESCRIPTION = "Provide an integer value to connected nodes."

    def execute(self, int=1):
        return (int,)


class ToolBoxPrimitiveStringMultiline:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"string": ("STRING", {"multiline": True, "default": ""})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("string",)
    FUNCTION = "execute"
    CATEGORY = "ToolBox/Primitive"
    DESCRIPTION = "Provide multiline text unchanged to connected nodes."

    def execute(self, string=""):
        return (string,)


NODE_CLASS_MAPPINGS = {
    "ToolBoxSwitchAny": ToolBoxSwitchAny,
    "ToolBoxPrimitiveInteger": ToolBoxPrimitiveInteger,
    "ToolBoxPrimitiveStringMultiline": ToolBoxPrimitiveStringMultiline,
    "ToolBoxSwitchImage": ToolBoxSwitchImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ToolBoxSwitchAny": "tb-switch-any",
    "ToolBoxPrimitiveInteger": "tb-primitive-integer",
    "ToolBoxPrimitiveStringMultiline": "tb-primitive-string-multiline",
    "ToolBoxSwitchImage": "tb-switch-image",
}
