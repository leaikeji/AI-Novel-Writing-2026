from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.creative_services import list_foreshadows, list_storylines
from backend.models import (
    Document,
    DocumentRevision,
    Foreshadow,
    IntelligenceProposal,
    Novel,
    NovelCharacter,
    StoryFact,
    Storyline,
)
from backend.services import build_intelligence_prompt


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _ReadOnlySession:
    """Minimal statement fake that turns every attempted write into a failure."""

    def __init__(
        self,
        *,
        objects: list[Any],
        rows: dict[type[Any], list[Any]] | None = None,
    ) -> None:
        self._objects: dict[type[Any], dict[UUID, Any]] = {}
        for item in objects:
            self._objects.setdefault(type(item), {})[item.id] = item
        self._rows = rows or {}

    def get(self, model: type[Any], identifier: UUID) -> Any | None:
        return self._objects.get(model, {}).get(identifier)

    def scalars(self, statement: Any) -> _Rows:
        entity = statement.column_descriptions[0].get("entity")
        return _Rows(self._rows.get(entity, []))

    def add(self, _item: object) -> None:  # pragma: no cover - hard failure path
        raise AssertionError("creative read service must not add rows")

    def add_all(self, _items: object) -> None:  # pragma: no cover - hard failure path
        raise AssertionError("creative read service must not add rows")

    def delete(self, _item: object) -> None:  # pragma: no cover - hard failure path
        raise AssertionError("creative read service must not delete rows")

    def flush(self) -> None:  # pragma: no cover - hard failure path
        raise AssertionError("creative read service must not flush")

    def commit(self) -> None:  # pragma: no cover - hard failure path
        raise AssertionError("creative read service must not commit")


def _novel(novel_id: UUID) -> Novel:
    return Novel(id=novel_id, title="零写读取回归")


def test_list_storylines_is_read_only_and_does_not_reconcile_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    active = Storyline(
        id=uuid4(),
        novel_id=novel_id,
        storyline_type="main",
        title="主线",
        description="作者维护的主线",
        status="active",
        progress=25,
        position=1000,
        version=3,
    )
    archived = Storyline(
        id=uuid4(),
        novel_id=novel_id,
        storyline_type="support",
        title="已归档支线",
        description="",
        status="archived",
        progress=100,
        position=2000,
        version=2,
    )
    session = _ReadOnlySession(
        objects=[_novel(novel_id)],
        rows={Storyline: [active, archived]},
    )
    before = (active.status, active.progress, active.version, archived.status, archived.version)
    monkeypatch.setattr(
        "backend.creative_services.get_story_projection_payload",
        lambda *_args, **_kwargs: {
            "timeline_id": str(uuid4()),
            "narrative_cutoff": None,
            "visible_facts": [],
            "current_facts": [],
            "conflicts": [],
        },
    )

    result = list_storylines(session, novel_id)  # type: ignore[arg-type]

    assert [item["id"] for item in result] == [str(active.id)]
    assert (active.status, active.progress, active.version, archived.status, archived.version) == before


def test_list_foreshadows_is_read_only_and_does_not_reconcile_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    active = Foreshadow(
        id=uuid4(),
        novel_id=novel_id,
        title="未寄出的信",
        content="作者手工维护的伏笔",
        latest_progress="尚未回收",
        status="active",
        progress=30,
        position=1000,
        version=4,
    )
    dropped = Foreshadow(
        id=uuid4(),
        novel_id=novel_id,
        title="已放弃伏笔",
        content="",
        latest_progress="",
        status="dropped",
        progress=100,
        position=2000,
        version=2,
    )
    session = _ReadOnlySession(
        objects=[_novel(novel_id)],
        rows={Foreshadow: [active, dropped]},
    )
    before = (active.status, active.progress, active.version, dropped.status, dropped.version)
    monkeypatch.setattr(
        "backend.creative_services.get_story_projection_payload",
        lambda *_args, **_kwargs: {
            "timeline_id": str(uuid4()),
            "narrative_cutoff": None,
            "visible_facts": [],
            "current_facts": [],
            "conflicts": [],
        },
    )

    result = list_foreshadows(session, novel_id)  # type: ignore[arg-type]

    assert [item["id"] for item in result] == [str(active.id)]
    assert (active.status, active.progress, active.version, dropped.status, dropped.version) == before


def test_storyline_and_foreshadow_lists_overlay_typed_projection_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid4()
    timeline_id = uuid4()
    storyline = Storyline(
        id=uuid4(), novel_id=novel_id, storyline_type="main", title="主线",
        description="规划根", status="active", progress=10, position=1, version=1,
    )
    foreshadow = Foreshadow(
        id=uuid4(), novel_id=novel_id, title="伏笔", content="规划根",
        latest_progress="作者规划", status="planned", progress=0, position=1, version=1,
    )
    storyline_fact = {
        "id": str(uuid4()), "fact_type": "storyline_event",
        "storyline_id": str(storyline.id), "story_sequence": 3,
        "event_kind": "advance", "predicate": "推进", "object_text": "取得关键证据",
        "details": {"schema_version": "storyline-event/1", "event": "证据确认", "status": "completed", "progress": 80},
    }
    foreshadow_fact = {
        "id": str(uuid4()), "fact_type": "foreshadow_event",
        "foreshadow_id": str(foreshadow.id), "story_sequence": 3,
        "event_kind": "resolve", "predicate": "回收", "object_text": "用途已经确认",
        "details": {"schema_version": "foreshadow-event/1", "event": "resolve", "note": "完成"},
    }
    projection = {
        "timeline_id": str(timeline_id), "narrative_cutoff": 3,
        "visible_facts": [storyline_fact, foreshadow_fact],
        "current_facts": [storyline_fact, foreshadow_fact], "conflicts": [],
    }
    monkeypatch.setattr(
        "backend.creative_services.get_story_projection_payload",
        lambda *_args, **_kwargs: projection,
    )
    session = _ReadOnlySession(
        objects=[_novel(novel_id)], rows={Storyline: [storyline], Foreshadow: [foreshadow]}
    )

    storyline_payload = list_storylines(session, novel_id)[0]  # type: ignore[arg-type]
    foreshadow_payload = list_foreshadows(session, novel_id)[0]  # type: ignore[arg-type]

    assert (storyline_payload["status"], storyline_payload["progress"]) == ("completed", 80)
    assert storyline_payload["planning_progress"] == 10
    assert storyline_payload["latest_progress"] == "取得关键证据"
    assert foreshadow_payload["status"] == "resolved"
    assert foreshadow_payload["progress"] == 100
    assert foreshadow_payload["planning_status"] == "planned"
    assert foreshadow_payload["latest_progress"] == "用途已经确认"


def test_production_backend_contains_no_sample_novel_tokens() -> None:
    backend_root = Path(__file__).resolve().parents[1] / "backend"
    forbidden_tokens = (
        "匿名举报",
        "灯塔承包权",
        "会议记录",
        "旧档案",
        "家书",
        "旧木盒",
        "铁盒",
        "唐知渔",
        "何漫",
        "周柚",
        "鹤嘴岬",
        "磁带里的秘密",
        "阿舟",
    )
    hits: list[str] = []
    for path in sorted(backend_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                hits.append(f"{path.relative_to(backend_root)}: {token}")

    assert hits == []


def test_intelligence_prompt_explicitly_allows_empty_items() -> None:
    novel_id = uuid4()
    document_id = uuid4()
    revision_id = uuid4()
    proposal_id = uuid4()
    proposal = IntelligenceProposal(
        id=proposal_id,
        novel_id=novel_id,
        document_id=document_id,
        chapter_revision_id=revision_id,
        input_hash="a" * 64,
        attempt=1,
        state="running",
    )
    document = Document(
        id=document_id,
        novel_id=novel_id,
        kind="chapter",
        title="无新事发生的一章",
        position=1000,
        status="draft",
        version=1,
    )
    revision = DocumentRevision(
        id=revision_id,
        document_id=document_id,
        revision_number=1,
        content_markdown="雨一直在下，他照常关上了窗。",
        content_text="雨一直在下，他照常关上了窗。",
        content_hash="b" * 64,
        source="manual",
    )
    session = _ReadOnlySession(
        objects=[proposal, document, revision],
        rows={StoryFact: [], NovelCharacter: []},
    )

    prompt = build_intelligence_prompt(session, proposal_id)  # type: ignore[arg-type]

    assert "正文没有新增或变化事实时，必须返回空 items" in prompt
    assert "正文不为空时至少返回 1 条情报" not in prompt
