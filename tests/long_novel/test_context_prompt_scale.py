from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from backend.context_v4 import RetrievalPurpose
from backend.context_v4_loader import (
    MAX_ADJACENT_CHAPTERS,
    _hydrate_manuscript_blocks,
    _select_adjacent_chapter_refs,
)
from backend.models import DocumentRevision


def uid(value: int) -> UUID:
    return UUID(int=value)


class _ScaleSession:
    def __init__(self, chapter_count: int) -> None:
        self.chapter_count = chapter_count
        self.execute_statements: list[Any] = []
        self.scalar_statements: list[Any] = []
        self.revisions: list[DocumentRevision] = []

    def execute(self, statement: Any) -> list[Any]:
        self.execute_statements.append(statement)
        if len(self.execute_statements) == 1:
            return [
                SimpleNamespace(
                    document_id=uid(100_000 + self.chapter_count),
                    narrative_sequence=self.chapter_count,
                )
            ]
        limit = statement._limit_clause.value
        return [
            SimpleNamespace(
                document_id=uid(100_000 + sequence),
                title=f"第 {sequence} 章",
                narrative_sequence=sequence,
                revision_id=uid(200_000 + sequence),
                content_hash=sha256(f"body-{sequence}".encode()).hexdigest(),
                markdown_character_count=2_010,
                text_character_count=2_010,
            )
            for sequence in range(
                self.chapter_count - 1,
                max(0, self.chapter_count - limit - 1),
                -1,
            )
        ][:limit]

    def scalars(self, statement: Any) -> list[Any]:
        self.scalar_statements.append(statement)
        return self.revisions


@pytest.mark.parametrize(
    ("chapter_count", "nominal_visible_characters"),
    ((500, 1_000_000), (2_500, 5_000_000)),
)
def test_long_novel_context_hydrates_only_eight_selected_chapter_bodies(
    chapter_count: int,
    nominal_visible_characters: int,
) -> None:
    session = _ScaleSession(chapter_count)
    target_document_id = uid(100_000 + chapter_count)
    refs = _select_adjacent_chapter_refs(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        target_document_id=target_document_id,
        target_narrative_sequence=chapter_count,
        purpose=RetrievalPurpose.CHAPTER_BODY,
    )
    session.revisions = [
        DocumentRevision(
            id=ref.revision_id,
            document_id=ref.document_id,
            revision_number=1,
            content_markdown=f"合成正文 {ref.narrative_sequence}" + "字" * 2_000,
            content_text=f"合成正文 {ref.narrative_sequence}" + "字" * 2_000,
            content_hash=ref.content_hash,
            source="synthetic",
        )
        for ref in refs
    ]

    blocks = _hydrate_manuscript_blocks(
        session,  # type: ignore[arg-type]
        novel_id=uid(1),
        timeline_id=uid(2),
        timelines=(SimpleNamespace(novel_id=uid(1)),),
        scope=SimpleNamespace(story_limits={uid(2): chapter_count}),  # type: ignore[arg-type]
        refs=refs,
    )

    assert nominal_visible_characters in {1_000_000, 5_000_000}
    assert len(refs) == MAX_ADJACENT_CHAPTERS
    assert len(blocks) == MAX_ADJACENT_CHAPTERS
    assert session.execute_statements[1]._limit_clause.value == MAX_ADJACENT_CHAPTERS + 1
    assert len(session.scalar_statements) == 1
    bound_values = [
        value
        for value in session.scalar_statements[0].compile().params.values()
        if isinstance(value, (list, tuple))
    ]
    assert any(len(value) == MAX_ADJACENT_CHAPTERS for value in bound_values)
