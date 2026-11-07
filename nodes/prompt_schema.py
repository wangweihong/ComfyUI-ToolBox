"""Manual prompt annotations shared by nodes and offline migration tools."""

ANNOTATION_DEFAULTS = {
    "sensitivity_level": 0,
    "extreme": 0,
    "horror": 0,
    "gore": 0,
    "minor": 0,
}
CATEGORY_FIELDS = ("nsfw", "extreme", "horror", "gore", "minor")
LEVEL_DESCRIPTIONS = [
    "L0 安全",
    "L1 轻度性化：丝袜/腿部特写/恋物/紧身/短裙/透视；轻微恐怖氛围",
    "L2 性意味着装：内衣/内裤/比基尼/泳装；重口味（束缚捆绑未裸露）；中度血腥",
    "L3 裸露/性器官/性行为；触手/异种；肢解虐杀级血腥",
    "L4 未成年 + 任意性化内容",
]


def add_missing_annotations(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
    if not columns:
        raise ValueError("prompts table does not exist")
    added = []
    for name, default in ANNOTATION_DEFAULTS.items():
        if name not in columns:
            maximum = 4 if name == "sensitivity_level" else 1
            conn.execute(
                f"ALTER TABLE prompts ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default} "
                f"CHECK ({name} BETWEEN 0 AND {maximum})"
            )
            added.append(name)
    return added
