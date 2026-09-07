from pathlib import Path

import pytest
from fastapi import FastAPI

from backend.writing_skills import button
from backend.writing_skills.button import current_catalog
from backend.writing_skills.catalog import published_skill_ids
from backend.writing_skills.primary import creative_primary_skill


@pytest.mark.parametrize(
    ("kind", "operation", "expected"),
    [
        ("novel_template", "", "novel-direction"),
        ("novel_naming", "", "novel-direction"),
        ("outline_background", "", "story-foundation"),
        ("outline_characters", "", "character-craft"),
        ("outline_plot", "", "story-foundation"),
        ("outline_highlight", "", "story-foundation"),
        ("chapter_storyline_recommendation", "", "chapter-outline"),
        ("chapter_outline", "", "chapter-outline"),
        ("character_profile_completion", "", "character-craft"),
        ("review", "", "style-review"),
        ("selection_edit", "polish", "prose-writing"),
        ("selection_edit", "review", "style-review"),
    ],
)
def test_creative_primary_skill_is_one_server_owned_task_contract(kind, operation, expected):
    assert creative_primary_skill(kind, operation=operation) == expected


@pytest.mark.parametrize(
    ("kind", "operation"),
    [
        ("novel_cover", ""),
        ("relationship_graph", ""),
        ("selection_edit", "unknown"),
        ("unknown", ""),
    ],
)
def test_primary_mapping_rejects_excluded_or_unknown_tasks(kind, operation):
    with pytest.raises(ValueError, match="excluded|no primary"):
        creative_primary_skill(kind, operation=operation)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("primary_skill", "expected_paths"),
    [
        (
            "novel-direction",
            [
                "SKILL.md",
                "references/premise-and-reader-promise.md",
            ],
        ),
        (
            "chapter-outline",
            [
                "SKILL.md",
                "references/chapter-architecture.md",
            ],
        ),
        (
            "prose-writing",
            [
                "SKILL.md",
                "references/narrative-craft.md",
                "references/genre-promises.md",
            ],
        ),
    ],
)
async def test_catalog_loads_exact_primary_bytes_for_each_task(primary_skill, expected_paths):
    app = FastAPI()

    @app.get("/api/skills")
    def skills():
        return [
            {
                "name": name,
                "source": "plugin:ai-novel-world-2026",
                "enabled": True,
            }
            for name in published_skill_ids(button.SKILLS_ROOT)
        ]

    _, blocks = await current_catalog(app, primary_skill=primary_skill)
    assert [block.path for block in blocks] == expected_paths
    assert all(
        block.text
        == (Path("skills") / primary_skill / block.path).read_text(encoding="utf-8")
        for block in blocks
    )


@pytest.mark.asyncio
async def test_catalog_fails_closed_when_selected_primary_is_disabled():
    app = FastAPI()

    @app.get("/api/skills")
    def skills():
        return [
            {
                "name": name,
                "source": "plugin:ai-novel-world-2026",
                "enabled": name != "style-review",
            }
            for name in published_skill_ids(button.SKILLS_ROOT)
        ]

    with pytest.raises(ValueError, match="primary Skill is disabled"):
        await current_catalog(app, primary_skill="style-review")
    with pytest.raises(ValueError, match="unsupported primary Skill"):
        await current_catalog(app, primary_skill="arbitrary-skill")
