"""Server-owned primary task Skill mapping and exact reference allowlist."""

PRIMARY_REFERENCES_BY_SKILL: dict[str, tuple[str, ...]] = {
    "novel-direction": ("references/premise-and-reader-promise.md",),
    "story-foundation": ("references/story-architecture.md",),
    "character-craft": ("references/character-dynamics.md",),
    "chapter-outline": ("references/chapter-architecture.md",),
    "style-review": ("references/revision-passes.md",),
    "prose-writing": (
        "references/narrative-craft.md",
        "references/genre-promises.md",
    ),
}

CREATIVE_PRIMARY_BY_KIND: dict[str, str] = {
    "novel_template": "novel-direction",
    "novel_naming": "novel-direction",
    "outline_background": "story-foundation",
    "outline_characters": "character-craft",
    "outline_plot": "story-foundation",
    "outline_highlight": "story-foundation",
    "chapter_storyline_recommendation": "chapter-outline",
    "chapter_outline": "chapter-outline",
    "character_profile_completion": "character-craft",
    "review": "style-review",
}

SELECTION_PRIMARY_BY_OPERATION: dict[str, str] = {
    "polish": "prose-writing",
    "rewrite": "prose-writing",
    "expand": "prose-writing",
    "shorten": "prose-writing",
    "dialogue": "prose-writing",
    "review": "style-review",
    "custom": "prose-writing",
}


def creative_primary_skill(kind: str, *, operation: str = "") -> str:
    """Return the one task Skill whose output contract remains authoritative."""

    if kind in {"novel_cover", "relationship_graph"}:
        raise ValueError("creative kind is excluded from writing methods")
    if kind == "selection_edit":
        primary = SELECTION_PRIMARY_BY_OPERATION.get(operation)
        if primary is None:
            raise ValueError("selection operation has no primary Skill")
        return primary
    primary = CREATIVE_PRIMARY_BY_KIND.get(kind)
    if primary is None:
        raise ValueError("creative kind has no primary Skill")
    return primary
