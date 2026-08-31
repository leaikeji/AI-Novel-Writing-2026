from __future__ import annotations

from uuid import uuid4

from backend.character_workspace.service import _chapter_references
from backend.models import ChapterBrief, Document


def test_character_reference_uses_non_empty_current_chapter_title() -> None:
    novel_id = uuid4()
    character_id = uuid4()
    instance_id = uuid4()
    timeline_id = uuid4()
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        kind="chapter",
        title="",
        position=9_000,
        status="draft",
        version=1,
    )
    brief = ChapterBrief(
        id=uuid4(),
        document_id=document.id,
        version=1,
        target_word_count=2_000,
        expectation_text="",
        outline_text="",
        forbidden_text="",
        role_constraints={
            "_v3": {
                "schema_version": "chapter-role-constraints/3",
                "timeline_id": str(timeline_id),
                "required_characters": [
                    {
                        "character_id": str(character_id),
                        "character_instance_id": str(instance_id),
                    }
                ],
            }
        },
    )

    references = _chapter_references(
        ((brief, document),),
        character_id=character_id,
        instance_id=instance_id,
        timeline_id=timeline_id,
        ordinals={document.id: 7},
    )

    assert references[0].document_title == "第7章"
    assert references[0].document_position == 9_000
