class AnyType(str):
    """A special type that can be connected to any other types. Credit to pythongosssss"""

    def __ne__(self, __value: object) -> bool:
        return False

any_type = AnyType("*")

class CR_Text:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": '', "multiline": True}),
            }
        }

    RETURN_TYPES = (any_type, "STRING", )
    RETURN_NAMES = ("text" )
    FUNCTION = "text_multiline"

    def text_multiline(self, text):
        return (text,)
    
NODE_CLASS_MAPPINGS = {
    "CR_Text": CR_Text
}
