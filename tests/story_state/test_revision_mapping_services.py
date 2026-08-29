from __future__ import annotations

from hashlib import sha256
import json
from uuid import UUID

import pytest

from backend.creative_data_models import (
    CharacterInstanceRevision,
    RevisionTimelineMapping,
    RevisionTimelineMappingHead,
    RevisionTimelineMappingSegment,
    StoryTimeline,
)
from backend.models import Document, DocumentRevision, Novel
from backend.story_state.mappings import (
    MappingServiceError,
    MappingServiceErrorCode,
    TimelineMappingSegmentInput,
    get_revision_timeline_mapping,
    list_revision_timeline_mapping_history,
    save_revision_timeline_mapping,
)
from backend.story_state.revisions import (
    CharacterInstanceProfileV1,
    CharacterInstanceProfileV2,
    RevisionServiceError,
    RevisionServiceErrorCode,
    get_character_instance_profile,
    list_character_instance_profile_history,
    restore_character_instance_profile,
    save_character_instance_profile,
)

from .test_persistence_contract import (
    FakeSession,
    NOW,
    id_factory,
    instance,
    novel,
    timeline,
    uid,
)


def profile_revision(
    value: int,
    *,
    number: int,
    profile: dict[str, object],
    parent: int | None = None,
    restored_from: int | None = None,
    operation_key: str | None = None,
    profile_schema_version: int = 1,
) -> CharacterInstanceRevision:
    return CharacterInstanceRevision(
        id=uid(value),
        novel_id=uid(1),
        character_instance_id=uid(30),
        revision_number=number,
        parent_revision_id=uid(parent) if parent else None,
        restored_from_revision_id=uid(restored_from) if restored_from else None,
        source_kind="manual",
        operation_key=operation_key or f"profile-{number}",
        operation_hash=f"{number:064x}",
        profile_schema_version=profile_schema_version,
        profile_json=profile,
        change_set_json={"changed_fields": sorted(profile)},
        content_hash=sha256(repr(profile).encode()).hexdigest(),
        created_at=NOW,
    )


def chapter_document() -> Document:
    return Document(
        id=uid(50),
        novel_id=uid(1),
        kind="chapter",
        title="第一章",
        position=1,
        status="final",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def chapter_revision(text: str = "甲乙丙丁") -> DocumentRevision:
    return DocumentRevision(
        id=uid(51),
        document_id=uid(50),
        revision_number=1,
        parent_revision_id=None,
        restored_from_revision_id=None,
        content_markdown=text,
        content_text=text,
        content_hash=sha256(text.encode()).hexdigest(),
        source="manual",
        created_at=NOW,
    )


def mapping_revision(
    value: int,
    *,
    version: int,
    digest: str | None = None,
) -> RevisionTimelineMapping:
    return RevisionTimelineMapping(
        id=uid(value),
        novel_id=uid(1),
        document_id=uid(50),
        revision_id=uid(51),
        source_content_hash=chapter_revision().content_hash,
        mapping_version=version,
        source_kind="manual",
        operation_key=f"map-{version}",
        operation_hash=f"{version:064x}",
        mapping_digest=digest or f"{version + 10:064x}",
        created_at=NOW,
    )


def mapping_segment(
    value: int,
    *,
    mapping_id: int,
    timeline_id: int,
    ordinal: int,
    start: int,
    end: int,
) -> RevisionTimelineMappingSegment:
    return RevisionTimelineMappingSegment(
        id=uid(value),
        mapping_revision_id=uid(mapping_id),
        novel_id=uid(1),
        timeline_id=uid(timeline_id),
        ordinal=ordinal,
        source_start=start,
        source_end=end,
        story_sequence=None,
        story_time_json={"schema_version": "story-time/1", "precision": "unknown"},
    )


def test_profile_save_appends_immutable_revision_and_advances_both_cas_values() -> None:
    novel_row = novel(version=4)
    instance_row = instance(30, current_revision_id=60, version=3)
    old = profile_revision(60, number=1, profile={"public_identity": "学徒"})
    session = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[old]]},
    )

    result = save_character_instance_profile(
        session,
        uid(1),
        uid(30),
        expected_story_ledger_version=4,
        expected_instance_version=3,
        operation_key="profile.save.2",
        profile=CharacterInstanceProfileV1(
            public_identity="巡查员",
            true_identity="失踪王女",
            birth_year=998,
            growth_direction="从逃避责任到主动承担",
        ),
        id_factory=id_factory(1000),
        clock=lambda: NOW,
    )

    created = next(
        item for item in session.added if isinstance(item, CharacterInstanceRevision)
    )
    assert created.parent_revision_id == old.id
    assert created.revision_number == 2
    assert created.restored_from_revision_id is None
    assert created.profile_json["true_identity"] == "失踪王女"
    canonical = json.dumps(
        created.profile_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert created.content_hash == sha256(canonical.encode()).hexdigest()
    assert old.profile_json == {"public_identity": "学徒"}
    assert instance_row.current_revision_id == created.id
    assert instance_row.version == 4
    assert novel_row.story_ledger_version == 5
    assert result["replayed"] is False
    assert session.flush_count == 1
    assert session.commit_count == 0


def test_profile_v2_note_is_persisted_as_text_and_never_becomes_computed_age() -> None:
    novel_row = novel(version=4)
    instance_row = instance(30, version=3)
    session = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[]]},
    )
    profile = CharacterInstanceProfileV2(
        public_identity="巡查员",
        age_at_story_start_note="故事开篇约十八岁，月份尚未确定",
    )

    result = save_character_instance_profile(
        session,
        uid(1),
        uid(30),
        expected_story_ledger_version=4,
        expected_instance_version=3,
        operation_key="profile.v2.save.1",
        profile=profile,
        id_factory=id_factory(1050),
        clock=lambda: NOW,
    )

    created = next(
        item for item in session.added if isinstance(item, CharacterInstanceRevision)
    )
    assert created.profile_schema_version == 2
    assert created.profile_json["schema_version"] == "character-instance-profile/2"
    assert created.profile_json["age_at_story_start_note"] == profile.age_at_story_start_note
    assert created.profile_json.get("birth_year") is None
    assert "age_at_story_start" not in created.profile_json
    assert result["story_ledger_version"] == 5
    assert instance_row.version == 4


def test_profile_v1_remains_the_default_for_payloads_without_schema_version() -> None:
    from backend.story_state import api

    request = api.CharacterInstanceProfileSaveRequest(
        expected_story_ledger_version=2,
        expected_instance_version=1,
        operation_key="profile.v1.compat.1",
        profile={"public_identity": "学徒"},
    )

    assert type(request.profile) is CharacterInstanceProfileV1
    assert request.profile.schema_version == "character-instance-profile/1"


def test_profile_restore_creates_new_revision_without_rewriting_target() -> None:
    novel_row = novel(version=7)
    instance_row = instance(30, current_revision_id=61, version=5)
    target = profile_revision(60, number=1, profile={"public_identity": "学徒"})
    current = profile_revision(
        61,
        number=2,
        parent=60,
        profile={"public_identity": "巡查员"},
    )
    session = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[target, current]]},
    )

    result = restore_character_instance_profile(
        session,
        uid(1),
        uid(30),
        target.id,
        expected_story_ledger_version=7,
        expected_instance_version=5,
        operation_key="profile.restore.1",
        id_factory=id_factory(1100),
        clock=lambda: NOW,
    )

    created = next(
        item for item in session.added if isinstance(item, CharacterInstanceRevision)
    )
    assert created.revision_number == 3
    assert created.parent_revision_id == current.id
    assert created.restored_from_revision_id == target.id
    assert created.profile_json == target.profile_json
    assert result["revision"]["source_kind"] == "restore"
    assert current.parent_revision_id == target.id
    assert target.restored_from_revision_id is None


def test_profile_restore_accepts_v2_and_preserves_note_without_reinterpreting_it() -> None:
    novel_row = novel(version=7)
    instance_row = instance(30, current_revision_id=61, version=5)
    target_profile = {
        "schema_version": "character-instance-profile/2",
        "public_identity": "学徒",
        "age_at_story_start_note": "大约十八岁",
    }
    target = profile_revision(
        60,
        number=1,
        profile=target_profile,
        profile_schema_version=2,
    )
    current = profile_revision(
        61,
        number=2,
        parent=60,
        profile={"schema_version": "character-instance-profile/1", "public_identity": "巡查员"},
    )
    session = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[target, current]]},
    )

    restore_character_instance_profile(
        session,
        uid(1),
        uid(30),
        target.id,
        expected_story_ledger_version=7,
        expected_instance_version=5,
        operation_key="profile.v2.restore.1",
        id_factory=id_factory(1120),
        clock=lambda: NOW,
    )

    created = next(
        item for item in session.added if isinstance(item, CharacterInstanceRevision)
    )
    assert created.profile_schema_version == 2
    assert created.profile_json == target_profile
    assert "birth_year" not in created.profile_json


def test_profile_restore_rejects_schema_column_payload_mismatch_without_cas_change() -> None:
    novel_row = novel(version=7)
    instance_row = instance(30, current_revision_id=61, version=5)
    target = profile_revision(
        60,
        number=1,
        profile={
            "schema_version": "character-instance-profile/2",
            "age_at_story_start_note": "十八岁",
        },
        profile_schema_version=1,
    )
    current = profile_revision(
        61, number=2, parent=60, profile={"public_identity": "巡查员"}
    )
    session = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[target, current]]},
    )

    with pytest.raises(RevisionServiceError) as caught:
        restore_character_instance_profile(
            session,
            uid(1),
            uid(30),
            target.id,
            expected_story_ledger_version=7,
            expected_instance_version=5,
            operation_key="profile.invalid.restore.1",
        )

    assert caught.value.code is RevisionServiceErrorCode.INVALID_PROFILE_SCHEMA
    assert session.added == []
    assert session.flush_count == 0
    assert instance_row.current_revision_id == current.id
    assert instance_row.version == 5
    assert novel_row.story_ledger_version == 7


def test_profile_save_idempotent_retry_precedes_stale_cas_checks() -> None:
    novel_row = novel(version=2)
    instance_row = instance(30, version=1)
    profile = CharacterInstanceProfileV1(public_identity="巡查员")
    first = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[]]},
    )
    save_character_instance_profile(
        first,
        uid(1),
        uid(30),
        expected_story_ledger_version=2,
        expected_instance_version=1,
        operation_key="profile.retry.1",
        profile=profile,
        id_factory=id_factory(1150),
        clock=lambda: NOW,
    )
    created = next(
        item for item in first.added if isinstance(item, CharacterInstanceRevision)
    )
    assert novel_row.story_ledger_version == 3
    assert instance_row.version == 2

    retry = FakeSession(
        scalar_results={Novel: [novel_row], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[created]]},
    )
    result = save_character_instance_profile(
        retry,
        uid(1),
        uid(30),
        expected_story_ledger_version=2,
        expected_instance_version=1,
        operation_key="profile.retry.1",
        profile=profile,
    )
    assert result["replayed"] is True
    assert result["revision"]["id"] == str(created.id)
    assert retry.added == []
    assert retry.flush_count == 0


def test_profile_history_and_current_reads_are_novel_scoped_and_write_free() -> None:
    instance_row = instance(30, current_revision_id=61, version=3)
    old = profile_revision(60, number=1, profile={"public_identity": "学徒"})
    current = profile_revision(
        61,
        number=2,
        parent=60,
        profile={"public_identity": "巡查员"},
    )
    history_session = FakeSession(
        scalar_results={type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[old, current]]},
    )
    history = list_character_instance_profile_history(
        history_session, uid(1), uid(30)
    )
    assert [item["revision_number"] for item in history] == [2, 1]
    assert history[0]["is_current"] is True
    assert history_session.added == []
    assert history_session.flush_count == 0

    read_session = FakeSession(
        scalar_results={type(instance_row): [instance_row], CharacterInstanceRevision: [current]}
    )
    payload = get_character_instance_profile(read_session, uid(1), uid(30))
    assert payload["revision"]["id"] == str(current.id)
    assert read_session.added == []
    assert all("novel_id" in statement for statement in read_session.statements)


def test_profile_save_rejects_stale_instance_version_without_flush() -> None:
    instance_row = instance(30, version=3)
    session = FakeSession(
        scalar_results={Novel: [novel(version=4)], type(instance_row): [instance_row]},
        scalars_results={CharacterInstanceRevision: [[]]},
    )
    with pytest.raises(RevisionServiceError) as caught:
        save_character_instance_profile(
            session,
            uid(1),
            uid(30),
            expected_story_ledger_version=4,
            expected_instance_version=2,
            operation_key="profile.save.stale",
            profile=CharacterInstanceProfileV1(public_identity="学徒"),
        )
    assert caught.value.code is RevisionServiceErrorCode.VERSION_CONFLICT
    assert session.added == []
    assert session.flush_count == 0


def test_single_timeline_mapping_omission_auto_maps_complete_unicode_text() -> None:
    document = chapter_document()
    revision = chapter_revision("甲😀\n丙")
    only_line = timeline(10, primary=True)
    session = FakeSession(
        scalar_results={
            Document: [document],
            DocumentRevision: [revision],
            RevisionTimelineMappingHead: [None],
        },
        scalars_results={StoryTimeline: [[only_line]], RevisionTimelineMapping: [[]]},
    )

    result = save_revision_timeline_mapping(
        session,
        uid(1),
        document.id,
        revision.id,
        expected_head_version=0,
        operation_key="mapping.auto.1",
        id_factory=id_factory(1200),
        clock=lambda: NOW,
    )

    mapping = next(
        item for item in session.added if isinstance(item, RevisionTimelineMapping)
    )
    segment = next(
        item for item in session.added if isinstance(item, RevisionTimelineMappingSegment)
    )
    head = next(
        item for item in session.added if isinstance(item, RevisionTimelineMappingHead)
    )
    assert mapping.source_kind == "auto_single"
    assert mapping.source_content_hash == revision.content_hash
    assert (segment.source_start, segment.source_end) == (0, len(revision.content_text))
    assert segment.source_end == 4  # Unicode code points, not UTF-16 code units.
    assert segment.timeline_id == only_line.id
    assert head.current_mapping_revision_id == mapping.id
    assert head.version == 1
    assert result["mapping"]["head_version"] == 1
    assert session.flush_count == 1
    assert session.commit_count == 0


def test_multi_timeline_mapping_requires_explicit_segments() -> None:
    document = chapter_document()
    revision = chapter_revision()
    session = FakeSession(
        scalar_results={Document: [document], DocumentRevision: [revision]},
        scalars_results={StoryTimeline: [[timeline(10), timeline(11, parent=10, anchor=2)]]},
    )

    with pytest.raises(MappingServiceError) as caught:
        save_revision_timeline_mapping(
            session,
            uid(1),
            document.id,
            revision.id,
            expected_head_version=0,
            operation_key="mapping.missing",
        )
    assert caught.value.code is MappingServiceErrorCode.TIMELINE_REQUIRED
    assert session.added == []
    assert session.flush_count == 0


def test_explicit_mapping_requires_exact_gapless_character_ranges() -> None:
    document = chapter_document()
    revision = chapter_revision()
    lines = [timeline(10), timeline(11, parent=10, anchor=2)]
    session = FakeSession(
        scalar_results={Document: [document], DocumentRevision: [revision]},
        scalars_results={StoryTimeline: [lines]},
    )
    with pytest.raises(MappingServiceError) as caught:
        save_revision_timeline_mapping(
            session,
            uid(1),
            document.id,
            revision.id,
            expected_head_version=0,
            operation_key="mapping.gap",
            segments=[
                TimelineMappingSegmentInput(
                    timeline_id=uid(10), source_start=0, source_end=1
                ),
                TimelineMappingSegmentInput(
                    timeline_id=uid(11), source_start=2, source_end=4
                ),
            ],
        )
    assert caught.value.code is MappingServiceErrorCode.INVALID_SEGMENTS
    assert session.added == []


def test_explicit_mapping_saves_ordered_ranges_and_enforces_head_cas() -> None:
    document = chapter_document()
    revision = chapter_revision()
    lines = [timeline(10), timeline(11, parent=10, anchor=2)]
    session = FakeSession(
        scalar_results={
            Document: [document],
            DocumentRevision: [revision],
            RevisionTimelineMappingHead: [None],
        },
        scalars_results={StoryTimeline: [lines], RevisionTimelineMapping: [[]]},
    )
    save_revision_timeline_mapping(
        session,
        uid(1),
        document.id,
        revision.id,
        expected_head_version=0,
        operation_key="mapping.manual.1",
        segments=[
            TimelineMappingSegmentInput(
                timeline_id=uid(11), source_start=2, source_end=4, story_sequence=20
            ),
            TimelineMappingSegmentInput(
                timeline_id=uid(10), source_start=0, source_end=2, story_sequence=10
            ),
        ],
        id_factory=id_factory(1300),
        clock=lambda: NOW,
    )
    created_segments = [
        item for item in session.added if isinstance(item, RevisionTimelineMappingSegment)
    ]
    assert [(item.ordinal, item.source_start, item.source_end) for item in created_segments] == [
        (0, 0, 2),
        (1, 2, 4),
    ]

    current_mapping = mapping_revision(70, version=1)
    head = RevisionTimelineMappingHead(
        revision_id=revision.id,
        document_id=document.id,
        novel_id=uid(1),
        source_content_hash=revision.content_hash,
        current_mapping_revision_id=current_mapping.id,
        version=2,
        updated_at=NOW,
    )
    stale = FakeSession(
        scalar_results={
            Document: [document],
            DocumentRevision: [revision],
            RevisionTimelineMappingHead: [head],
        },
        scalars_results={StoryTimeline: [lines], RevisionTimelineMapping: [[current_mapping]]},
    )
    with pytest.raises(MappingServiceError) as caught:
        save_revision_timeline_mapping(
            stale,
            uid(1),
            document.id,
            revision.id,
            expected_head_version=1,
            operation_key="mapping.manual.stale",
            segments=[
                TimelineMappingSegmentInput(
                    timeline_id=uid(10), source_start=0, source_end=4
                )
            ],
        )
    assert caught.value.code is MappingServiceErrorCode.VERSION_CONFLICT
    assert stale.added == []
    assert stale.flush_count == 0


def test_mapping_current_and_history_are_read_only_and_preserve_source_evidence() -> None:
    document = chapter_document()
    revision = chapter_revision()
    old = mapping_revision(70, version=1)
    current = mapping_revision(71, version=2)
    head = RevisionTimelineMappingHead(
        revision_id=revision.id,
        document_id=document.id,
        novel_id=uid(1),
        source_content_hash=revision.content_hash,
        current_mapping_revision_id=current.id,
        version=2,
        updated_at=NOW,
    )
    old_segment = mapping_segment(
        80, mapping_id=70, timeline_id=10, ordinal=0, start=0, end=4
    )
    current_segment = mapping_segment(
        81, mapping_id=71, timeline_id=11, ordinal=0, start=0, end=4
    )
    read_session = FakeSession(
        scalar_results={
            Document: [document],
            DocumentRevision: [revision],
            RevisionTimelineMappingHead: [head],
            RevisionTimelineMapping: [current],
        },
        scalars_results={RevisionTimelineMappingSegment: [[current_segment]]},
    )
    payload = get_revision_timeline_mapping(
        read_session, uid(1), document.id, revision.id
    )
    assert payload["id"] == str(current.id)
    assert payload["source_content_hash"] == revision.content_hash
    assert payload["segments"][0]["timeline_id"] == str(uid(11))
    assert read_session.added == []
    assert read_session.flush_count == 0

    history_session = FakeSession(
        scalar_results={
            Document: [document],
            DocumentRevision: [revision],
            RevisionTimelineMappingHead: [head],
        },
        scalars_results={
            RevisionTimelineMapping: [[current, old]],
            RevisionTimelineMappingSegment: [[current_segment, old_segment]],
        },
    )
    history = list_revision_timeline_mapping_history(
        history_session, uid(1), document.id, revision.id
    )
    assert [item["mapping_version"] for item in history] == [2, 1]
    assert [item["is_current"] for item in history] == [True, False]
    assert history_session.added == []
    assert history_session.flush_count == 0
