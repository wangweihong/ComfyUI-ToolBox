"""Compile model-generated sections into the user's tagged natural-language format."""

SYSTEM_PROMPT = """Write concrete image-generation descriptions in named spatial sections.
If images are provided, describe visible evidence and preserve subjects, composition,
materials and readable text. Do not invent hidden details or identities.
Return exactly one JSON object: {"sections":[{"name":"section name","description":"visible description"}]}.
Descriptions are plain text, without tags, markup, explanations or model parameters.
The application adds section delimiters after validation. Use the user's requested language."""


def compile_tagged_caption(draft):
    if not isinstance(draft, dict) or set(draft) != {"sections"}:
        raise ValueError('Tagged Caption requires exactly one root field: sections')
    sections = draft["sections"]
    if not isinstance(sections, list) or not sections:
        raise ValueError('sections must be a nonempty array')
    parts = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict) or set(section) != {"name", "description"}:
            raise ValueError(f'sections[{index}] requires name and description only')
        name, description = section["name"], section["description"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'sections[{index}].name must be nonempty text')
        if any(c in name for c in '<>|/\r\n'):
            raise ValueError(f'sections[{index}].name contains reserved tag characters')
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f'sections[{index}].description must be nonempty text')
        if '<|' in description:
            raise ValueError(f'sections[{index}].description must be plain text without section tags')
        name, description = name.strip(), description.strip()
        parts.append(f'<|{name}|>「{description}」<|/{name}|>')
    return ''.join(parts)
