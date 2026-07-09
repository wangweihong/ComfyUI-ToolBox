import re


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
    FUNCTION = "text_multiline"
    CATEGORY = "eazy-toolbox/text"

    def text_multiline(self, text):
        return (text,)


class ToolBoxSubjectConceptReplacer:
    MAX_PAIRS = 8

    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "pair_count": ("INT", {"default": 1, "min": 1, "max": cls.MAX_PAIRS, "step": 1}),
            "text": ("STRING", {"default": "", "multiline": True, "forceInput": False}),
        }

        for i in range(1, cls.MAX_PAIRS + 1):
            inputs[f"subject_{i}"] = ("STRING", {"default": "", "multiline": False})
            inputs[f"concept_{i}"] = ("STRING", {"default": "", "multiline": True})

        return {"required": inputs}

    RETURN_TYPES = ("STRING",) * (1 + MAX_PAIRS * 2)
    RETURN_NAMES = (
        "text",
        "subject_1", "concept_1",
        "subject_2", "concept_2",
        "subject_3", "concept_3",
        "subject_4", "concept_4",
        "subject_5", "concept_5",
        "subject_6", "concept_6",
        "subject_7", "concept_7",
        "subject_8", "concept_8",
    )
    FUNCTION = "replace_subjects"
    CATEGORY = "eazy-toolbox/text"

    def replace_subjects(self, pair_count, text, **kwargs):
        pair_count = max(1, min(self.MAX_PAIRS, int(pair_count)))
        pairs = []
        seen_subjects = set()

        for i in range(1, pair_count + 1):
            subject = kwargs.get(f"subject_{i}", "").strip()
            concept = kwargs.get(f"concept_{i}", "").strip()

            if not subject:
                raise ValueError(f"subject_{i} cannot be empty.")
            if not concept:
                raise ValueError(f"concept_{i} cannot be empty.")
            if subject in seen_subjects:
                raise ValueError(f"Duplicate subject name: {subject}")

            seen_subjects.add(subject)
            pairs.append((subject, concept))

        replaced_text = self._replace_text(text, pairs)

        outputs = [replaced_text]
        for i in range(1, self.MAX_PAIRS + 1):
            if i <= pair_count:
                subject, concept = pairs[i - 1]
                outputs.extend([subject, concept])
            else:
                outputs.extend(["", ""])

        return tuple(outputs)

    def _replace_text(self, text, pairs):
        if not pairs:
            return text

        replacements = dict(pairs)
        subjects = sorted(replacements, key=len, reverse=True)
        pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(subject) for subject in subjects) + r")(?!\w)")

        return pattern.sub(lambda match: replacements[match.group(0)], text)


NODE_CLASS_MAPPINGS = {
    "ToolBoxText": ToolBoxText,
    "ToolBoxSubjectConceptReplacer": ToolBoxSubjectConceptReplacer,
}
