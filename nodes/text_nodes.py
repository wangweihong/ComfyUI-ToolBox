class AnyType(str):
    """A special type that can be connected to any other types."""

    def __ne__(self, __value: object) -> bool:
        return False

any_type = AnyType("*")

class ToolBoxText:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": '', "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)

def text_multiline(self, text):
    return (text,)

NODE_CLASS_MAPPINGS = {
    "ToolBoxText": ToolBoxText
}