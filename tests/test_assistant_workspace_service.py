from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.assistant_workspace_service import (
    WORKSPACE_CONTEXT_MAX_CHARS,
    WORKSPACE_CONTEXT_MIN_CHARS,
    WorkspaceOwnerScope,
    WorkspaceScopeError,
    get_assistant_workspace_context,
)
from backend.models import (
    CharacterRelationship,
    Document,
    DocumentWorkingCopy,
    Foreshadow,
    Novel,
    NovelCharacter,
    Storyline,
)
from backend.services import ValidationError


NOW = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _CountingSession:
    """Small SQLAlchemy statement fake; every read is counted as one query."""

    def __init__(
        self,
        *,
        objects: list[Any],
        rows: dict[type[Any], list[Any]],
        working_copies: dict[UUID, DocumentWorkingCopy],
    ) -> None:
        self._objects: dict[type[Any], dict[UUID, Any]] = {}
        for item in objects:
            self._objects.setdefault(type(item), {})[item.id] = item
        self._rows = rows
        self._working_copies = working_copies
        self.query_count = 0

    def get(self, model: type[Any], identifier: UUID) -> Any | None:
        self.query_count += 1
        return self._objects.get(model, {}).get(identifier)

    def scalars(self, statement: Any) -> _Rows:
        self.query_count += 1
        entity = statement.column_descriptions[0].get("entity")
        return _Rows(self._rows.get(entity, []))

    def execute(self, statement: Any) -> _Rows:
        self.query_count += 1
        params = statement.compile().params
        kind = next(value for key, value in params.items() if "kind" in key)
        novel_id = next(value for value in params.values() if isinstance(value, UUID))
        pairs = [
            (document, self._working_copies[document.id])
            for document in self._rows.get(Document, [])
            if document.novel_id == novel_id
            and document.kind == kind
            and document.id in self._working_copies
        ]
        return _Rows(pairs)

    def commit(self) -> None:  # pragma: no cover - a call is a hard test failure.
        raise AssertionError("read-only workspace service must not commit")

    def flush(self) -> None:  # pragma: no cover - a call is a hard test failure.
        raise AssertionError("read-only workspace service must not flush")

    def add(self, _item: object) -> None:  # pragma: no cover
        raise AssertionError("read-only workspace service must not add rows")


def _novel(novel_id: UUID, title: str) -> Novel:
    return Novel(
        id=novel_id,
        title=title,
        author_name="作者",
        description="正式简介",
        writing_type="long",
        audience="female",
        genre="悬疑",
        subgenre="成长",
        idea="寻找旧城真相",
        template_key="growth",
        template_name="成长型长篇",
        template_data={"tone": "克制"},
        outline_target_chapters=120,
        highlight="伏笔回收",
        background="海港旧城",
        main_plot="主角追查失踪档案",
        story_ledger_version=3,
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _document(
    novel_id: UUID,
    *,
    kind: str,
    title: str,
    position: int,
) -> tuple[Document, DocumentWorkingCopy]:
    document = Document(
        id=uuid4(),
        novel_id=novel_id,
        volume_id=None,
        kind=kind,
        title=title,
        position=position,
        status="draft",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    content = {
        "chapter": "SECRET CHAPTER BODY — 不得进入正式资料聚合",
        "outline": "# 正式总体大纲\n第一幕从旧电台开始。",
        "setting": "# 港城设定\n终年多雾，潮汐影响交通。",
    }[kind]
    working = DocumentWorkingCopy(
        document_id=document.id,
        base_revision_id=None,
        draft_version=2,
        content_markdown=content,
        content_hash=(kind[0] * 64),
        updated_at=NOW,
    )
    return document, working


def _character(
    novel_id: UUID,
    position: int,
    *,
    description: str = "",
) -> NovelCharacter:
    return NovelCharacter(
        id=uuid4(),
        novel_id=novel_id,
        role_type="main" if position == 1 else "supporting",
        name=f"角色{position}",
        description=description or f"角色{position}的正式小传",
        details={"identity": f"身份{position}"},
        lifecycle_state="active",
        archived_at=None,
        position=position * 1000,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _relationship(
    novel_id: UUID,
    source: NovelCharacter,
    target: NovelCharacter,
    position: int,
) -> CharacterRelationship:
    return CharacterRelationship(
        id=uuid4(),
        novel_id=novel_id,
        source_character_id=source.id,
        target_character_id=target.id,
        directionality="directed",
        relation_kind="ally",
        label="盟友",
        normalized_label="盟友",
        relation_pair_key=f"{source.id}:{target.id}",
        description=f"第{position}组合作关系",
        status="active",
        created_by="manual",
        manual_override=True,
        confidence=None,
        evidence_json=[],
        source_generation_job_id=None,
        source_chapter_revision_id=None,
        proposal_item_id=None,
        current_revision_id=None,
        archived_at=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _storyline(novel_id: UUID) -> Storyline:
    return Storyline(
        id=uuid4(),
        novel_id=novel_id,
        storyline_type="main",
        title="旧电台真相线",
        description="追查失踪档案与深夜广播的关联。",
        status="active",
        progress=35,
        position=1000,
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _foreshadow(novel_id: UUID) -> Foreshadow:
    return Foreshadow(
        id=uuid4(),
        novel_id=novel_id,
        title="停摆的钟",
        content="钟停在失踪当夜。",
        latest_progress="第二章确认钟被人为调整。",
        status="active",
        progress=40,
        position=1000,
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace_session(
    *,
    character_count: int = 2,
    character_description: str = "",
) -> tuple[_CountingSession, dict[str, Any]]:
    novel_id = uuid4()
    other_novel_id = uuid4()
    novel = _novel(novel_id, "雾港来信")
    other_novel = _novel(other_novel_id, "另一部书")
    chapter, chapter_working = _document(
        novel_id, kind="chapter", title="第一章", position=1000
    )
    sibling_chapter, sibling_chapter_working = _document(
        novel_id, kind="chapter", title="第二章", position=1500
    )
    outline, outline_working = _document(
        novel_id, kind="outline", title="总体大纲", position=2000
    )
    setting, setting_working = _document(
        novel_id, kind="setting", title="港城设定", position=3000
    )
    other_document, other_working = _document(
        other_novel_id, kind="chapter", title="越权章节", position=1000
    )
    characters = [
        _character(
            novel_id,
            index,
            description=character_description,
        )
        for index in range(1, max(2, character_count) + 1)
    ]
    other_character = _character(other_novel_id, 1)
    relationships = [
        _relationship(novel_id, characters[index - 1], characters[index], index)
        for index in range(1, len(characters))
    ]
    storyline = _storyline(novel_id)
    foreshadow = _foreshadow(novel_id)
    documents = [chapter, sibling_chapter, outline, setting, other_document]
    working_copies = {
        item.document_id: item
        for item in (
            chapter_working,
            sibling_chapter_working,
            outline_working,
            setting_working,
            other_working,
        )
    }
    objects: list[Any] = [
        novel,
        other_novel,
        *documents,
        *characters,
        other_character,
        *relationships,
        storyline,
        foreshadow,
    ]
    session = _CountingSession(
        objects=objects,
        rows={
            Document: documents,
            NovelCharacter: characters,
            CharacterRelationship: relationships,
            Storyline: [storyline],
            Foreshadow: [foreshadow],
        },
        working_copies=working_copies,
    )
    return session, {
        "novel": novel,
        "other_novel": other_novel,
        "chapter": chapter,
        "sibling_chapter": sibling_chapter,
        "other_document": other_document,
        "characters": characters,
        "other_character": other_character,
        "relationships": relationships,
        "storyline": storyline,
        "foreshadow": foreshadow,
    }


def _scope(novel: Novel) -> WorkspaceOwnerScope:
    return WorkspaceOwnerScope.from_novel_ids("local-owner", [novel.id])


def test_aggregates_all_formal_sections_with_provenance_and_no_chapter_body() -> None:
    session, fixture = _workspace_session()
    novel = fixture["novel"]

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="chapters",
        max_chars=WORKSPACE_CONTEXT_MAX_CHARS,
        clock=lambda: NOW,
    )

    assert payload["schema_version"] == 2
    assert payload["as_of"] == "2026-08-25T04:00:00Z"
    assert payload["novel_id"] == str(novel.id)
    assert list(payload["data"]) == [
        "outline",
        "characters",
        "relationships",
        "storylines",
        "foreshadows",
        "settings",
    ]
    assert "SECRET CHAPTER BODY" not in json.dumps(payload, ensure_ascii=False)
    assert payload["data"]["outline"]["documents"][0]["content_markdown"].startswith(
        "# 正式总体大纲"
    )
    assert payload["data"]["relationships"][0]["source_character_name"] == "角色1"
    assert payload["provenance"]["outline"] == [
        {"source_type": "database_table", "table": "novels", "record_count": 1},
        {
            "source_type": "working_copy",
            "table": "document_working_copies",
            "record_count": 1,
        },
    ]
    assert payload["truncated"] is False
    assert payload["omitted_sections"] == []
    assert payload["warnings"] == []
    assert session.query_count == 7


def test_explicit_chapter_naming_returns_current_body_and_book_title_index() -> None:
    session, fixture = _workspace_session()
    novel = fixture["novel"]

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="chapters",
        document_id=fixture["chapter"].id,
        include=["chapter_naming"],
        max_chars=WORKSPACE_CONTEXT_MAX_CHARS,
        clock=lambda: NOW,
    )

    naming = payload["data"]["chapter_naming"]
    assert naming["current_chapter"]["id"] == str(fixture["chapter"].id)
    assert naming["current_chapter"]["content_markdown"].startswith(
        "SECRET CHAPTER BODY"
    )
    assert naming["current_chapter"]["content_truncated"] is False
    assert naming["current_chapter"]["title"] == "第1章"
    assert naming["chapter_titles_in_book_order"] == ["第1章", "第2章"]
    assert naming["title_index_truncated"] is False
    assert payload["provenance"]["chapter_naming"] == [
        {"source_type": "database_table", "table": "documents", "record_count": 2},
        {
            "source_type": "working_copy",
            "table": "document_working_copies",
            "record_count": 1,
        },
    ]
    assert payload["truncated"] is False
    assert payload["warnings"] == []
    assert session.query_count == 4


def test_empty_semantic_chapter_names_never_enter_assistant_context() -> None:
    session, fixture = _workspace_session()
    fixture["chapter"].title = ""
    fixture["sibling_chapter"].title = "第十二章 · 潮声"
    novel = fixture["novel"]

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="chapters",
        document_id=fixture["chapter"].id,
        include=["chapter_naming"],
        max_chars=WORKSPACE_CONTEXT_MAX_CHARS,
        clock=lambda: NOW,
    )

    assert payload["document"]["title"] == "第1章"
    assert payload["data"]["chapter_naming"]["chapter_titles_in_book_order"] == [
        "第1章",
        "第2章 潮声",
    ]


def test_rejects_novel_outside_server_resolved_owner_without_querying() -> None:
    session, fixture = _workspace_session()

    with pytest.raises(WorkspaceScopeError, match="current owner scope"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(fixture["other_novel"]),
            novel_id=fixture["novel"].id,
            section="chapters",
            include=[],
        )

    assert session.query_count == 0


def test_rejects_cross_novel_document_and_entity() -> None:
    session, fixture = _workspace_session()
    novel = fixture["novel"]

    with pytest.raises(WorkspaceScopeError):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="chapters",
            document_id=fixture["other_document"].id,
            include=[],
        )
    assert session.query_count == 2

    session, fixture = _workspace_session()
    novel = fixture["novel"]
    with pytest.raises(WorkspaceScopeError):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            entity_type="character",
            entity_id=fixture["other_character"].id,
            include=[],
        )
    assert session.query_count == 2


def test_rejects_relationship_whose_endpoint_is_outside_the_novel() -> None:
    session, fixture = _workspace_session()
    novel = fixture["novel"]
    invalid = _relationship(
        novel.id,
        fixture["characters"][0],
        fixture["other_character"],
        99,
    )
    session._objects.setdefault(CharacterRelationship, {})[invalid.id] = invalid

    with pytest.raises(WorkspaceScopeError):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            entity_type="relationship",
            entity_id=invalid.id,
            include=[],
        )

    assert session.query_count == 4


def test_validates_include_schema_and_returns_current_document_entity() -> None:
    session, fixture = _workspace_session()
    novel = fixture["novel"]

    with pytest.raises(ValidationError, match="unsupported workspace include"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            include=["characters", "chapter_bodies"],
        )
    with pytest.raises(ValidationError, match="schema version"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            schema_version=1,
        )
    with pytest.raises(ValidationError, match="schema version"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            schema_version=2.0,  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="only approved section names"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=novel.id,
            section="roles",
            include=["characters", 1],  # type: ignore[list-item]
        )
    with pytest.raises(ValidationError, match="novel_id must be a UUID"):
        get_assistant_workspace_context(
            session,
            owner_scope=_scope(novel),
            novel_id=str(novel.id),  # type: ignore[arg-type]
            section="roles",
            include=[],
        )
    assert session.query_count == 0

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="roles",
        document_id=fixture["chapter"].id,
        entity_type="character",
        entity_id=fixture["characters"][0].id,
        include=["characters"],
        clock=lambda: NOW,
    )
    assert list(payload["data"]) == ["characters"]
    assert payload["document"]["id"] == str(fixture["chapter"].id)
    assert "content_markdown" not in payload["document"]
    assert payload["entity"] == {
        "type": "character",
        "id": str(fixture["characters"][0].id),
        "title": "角色1",
        "lifecycle_state": "active",
        "version": 1,
        "provenance": {
            "source_type": "database_table",
            "table": "novel_characters",
            "record_count": 1,
        },
    }


def test_clamps_budget_and_reports_omitted_sections_without_partial_records() -> None:
    session, fixture = _workspace_session(character_description="大" * 3_000)
    novel = fixture["novel"]

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="roles",
        include=["characters", "storylines"],
        max_chars=1,
        clock=lambda: NOW,
    )

    assert payload["budget"]["max_chars"] == WORKSPACE_CONTEXT_MIN_CHARS
    assert payload["budget"]["used_chars"] <= WORKSPACE_CONTEXT_MIN_CHARS
    assert "characters" not in payload["data"]
    assert payload["data"]["storylines"][0]["title"] == "旧电台真相线"
    assert payload["truncated"] is True
    assert payload["omitted_sections"] == ["characters"]
    assert payload["warnings"] == ["characters omitted by max_chars budget"]
    assert list(payload["provenance"]) == ["storylines"]


def test_returns_explicit_empty_sections_without_claiming_truncation() -> None:
    session, fixture = _workspace_session()
    session._rows[NovelCharacter] = []
    session._rows[CharacterRelationship] = []
    session._rows[Storyline] = []
    session._rows[Foreshadow] = []
    novel = fixture["novel"]

    payload = get_assistant_workspace_context(
        session,
        owner_scope=_scope(novel),
        novel_id=novel.id,
        section="clues",
        include=["characters", "relationships", "storylines", "foreshadows"],
        clock=lambda: NOW,
    )

    assert payload["data"] == {
        "foreshadows": [],
        "storylines": [],
        "relationships": [],
        "characters": [],
    }
    assert payload["truncated"] is False
    assert payload["omitted_sections"] == []
    assert payload["warnings"] == []
    assert all(
        entry[0]["record_count"] == 0
        for entry in payload["provenance"].values()
    )


def test_query_count_is_constant_as_relationship_graph_grows() -> None:
    small_session, small_fixture = _workspace_session(character_count=2)
    large_session, large_fixture = _workspace_session(character_count=200)

    small = get_assistant_workspace_context(
        small_session,
        owner_scope=_scope(small_fixture["novel"]),
        novel_id=small_fixture["novel"].id,
        section="chapters",
        max_chars=WORKSPACE_CONTEXT_MAX_CHARS,
        clock=lambda: NOW,
    )
    large = get_assistant_workspace_context(
        large_session,
        owner_scope=_scope(large_fixture["novel"]),
        novel_id=large_fixture["novel"].id,
        section="chapters",
        max_chars=999_999,
        clock=lambda: NOW,
    )

    assert small_session.query_count == 7
    assert large_session.query_count == 7
    assert len(small_fixture["relationships"]) == 1
    assert len(large_fixture["relationships"]) == 199
    assert large["budget"]["max_chars"] == WORKSPACE_CONTEXT_MAX_CHARS
    assert small["schema_version"] == large["schema_version"] == 2
