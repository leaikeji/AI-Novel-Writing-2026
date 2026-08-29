from __future__ import annotations

import ast
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.context_v3 import (
    CONTEXT_SECTION_ORDER,
    AuthorSecretConstraintV1,
    BoundPrivateAssetRecordV1,
    ChapterRoleConstraintsV3,
    CharacterContextRecordV2,
    CharacterRefV2,
    ContextAssemblyError,
    ContextAssemblyErrorCode,
    ContextAuthority,
    NovelContextAssemblySnapshotV3,
    OmissionCode,
    PerspectiveKind,
    PerspectiveV1,
    PlanningKind,
    PrivateAssetPolicy,
    SemanticCorpus,
    SemanticEvidenceRecordV1,
    StoryPositionV2,
    FormalPlanningRecordV1,
    assemble_novel_context,
)
from backend.story_state import (
    CharacterStateDetailsV1,
    GeneralFactDetailsV1,
    StoryFactType,
    StoryFactV2,
    StoryStateError,
    StoryStateErrorCode,
    StoryTimeV1,
    StoryTimelineRecord,
    StoryVisibilityV1,
    TimelineKind,
)
from backend.story_state.contracts import VisibilityScope


NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _timeline(
    novel_id: UUID,
    *,
    key: str,
    kind: TimelineKind,
    parent_id: UUID | None = None,
    fork_sequence: int | None = None,
    primary: bool = False,
) -> StoryTimelineRecord:
    return StoryTimelineRecord(
        id=uuid4(),
        novel_id=novel_id,
        timeline_key=key,
        name=key,
        normalized_name=key,
        timeline_kind=kind,
        is_primary=primary,
        parent_timeline_id=parent_id,
        fork_story_sequence=fork_sequence,
        created_at=NOW,
        updated_at=NOW,
    )


def _visibility(
    scope: VisibilityScope,
    *,
    instance_ids: tuple[UUID, ...] = (),
    revealed_at: int | None = None,
) -> StoryVisibilityV1:
    return StoryVisibilityV1(
        scope=scope,
        character_instance_ids=instance_ids,
        revealed_at_sequence=revealed_at,
    )


def _fact(
    novel_id: UUID,
    timeline_id: UUID,
    *,
    subject: str,
    sequence: int,
    visibility: StoryVisibilityV1,
    source_revision_id: UUID,
    character_ref: CharacterRefV2 | None = None,
) -> StoryFactV2:
    fact_id = uuid4()
    if character_ref is None:
        fact_type = StoryFactType.GENERAL_FACT
        details = GeneralFactDetailsV1(value=subject)
        character_id = None
        instance_id = None
    else:
        fact_type = StoryFactType.CHARACTER_STATE
        details = CharacterStateDetailsV1(value=subject)
        character_id = character_ref.character_id
        instance_id = character_ref.character_instance_id
    return StoryFactV2(
        id=fact_id,
        novel_id=novel_id,
        fact_type=fact_type,
        subject=subject,
        predicate="state",
        object_text=subject,
        details=details,
        source_revision_id=source_revision_id,
        source_document_id=uuid4(),
        timeline_id=timeline_id,
        character_id=character_id,
        character_instance_id=instance_id,
        dimension=subject,
        event_kind="confirmed",
        story_sequence=sequence,
        visibility_json=visibility,
        event_fingerprint=_hash(str(fact_id)),
        created_at=NOW,
    )


def _character_record(
    novel_id: UUID,
    ref: CharacterRefV2,
    timeline_ids: tuple[UUID, ...],
    *,
    secret_text: str = "",
) -> CharacterContextRecordV2:
    secrets = ()
    if secret_text:
        secrets = (
            AuthorSecretConstraintV1(
                constraint_id=uuid4(),
                instruction=secret_text,
                source_revision_id=uuid4(),
                character_ref=ref,
            ),
        )
    return CharacterContextRecordV2(
        novel_id=novel_id,
        ref=ref,
        root_revision_id=uuid4(),
        instance_revision_id=uuid4(),
        present_on_timeline_ids=timeline_ids,
        public_profile="public character profile",
        author_secret_constraints=secrets,
    )


def test_age_projection_uses_story_time_bounds_and_never_server_time() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id, key="main", kind=TimelineKind.MAIN, primary=True)
    ref = CharacterRefV2(
        character_id=uuid4(), character_instance_id=uuid4(), display_label="A"
    )
    record = CharacterContextRecordV2(
        novel_id=novel_id,
        ref=ref,
        root_revision_id=uuid4(),
        instance_revision_id=uuid4(),
        present_on_timeline_ids=(main.id,),
        birth_year=1989,
        birth_calendar_id="gregorian",
        public_profile="profile",
    )
    envelope = assemble_novel_context(
        NovelContextAssemblySnapshotV3(
            novel_id=novel_id,
            position=StoryPositionV2(
                narrative_sequence=1,
                story_time=StoryTimeV1(
                    label="2017",
                    calendar_id="gregorian",
                    lower_bound=2017,
                    upper_bound=2017,
                    precision="exact",
                ),
            ),
            perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
            chapter_requirements=ChapterRoleConstraintsV3(required_characters=(ref,)),
            timelines=(main,),
            character_records=(record,),
        )
    )

    age = envelope.character_state[0].age_projection
    assert (age.minimum_age, age.maximum_age, age.precision) == (27, 28, "range")
    assert age.reason == "year_only_birth"

    unknown = assemble_novel_context(
        NovelContextAssemblySnapshotV3(
            novel_id=novel_id,
            position=StoryPositionV2(narrative_sequence=1),
            perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
            chapter_requirements=ChapterRoleConstraintsV3(required_characters=(ref,)),
            timelines=(main,),
            character_records=(record,),
        )
    ).character_state[0].age_projection
    assert unknown.precision == "unknown"
    assert unknown.reason == "missing_story_time_bounds"
    assert unknown.minimum_age is None


def _semantic(
    novel_id: UUID,
    *,
    content: str,
    timeline_id: UUID | None,
    sequence: int | None,
    visibility: StoryVisibilityV1,
    revision_id: UUID | None = None,
    current: bool = True,
) -> SemanticEvidenceRecordV1:
    return SemanticEvidenceRecordV1(
        evidence_id=uuid4(),
        novel_id=novel_id,
        corpus=SemanticCorpus.STORY_EVENT,
        source_id=uuid4(),
        source_revision_id=revision_id,
        chunk_id=uuid4(),
        content=content,
        score=0.9,
        timeline_id=timeline_id,
        story_sequence=sequence,
        visibility=visibility,
        is_current_source=current,
    )


def test_fixed_order_sources_and_author_secrets_are_separate_from_story_state() -> None:
    novel_id = uuid4()
    main = _timeline(
        novel_id, key="main", kind=TimelineKind.MAIN, primary=True
    )
    ref = CharacterRefV2(
        character_id=uuid4(), character_instance_id=uuid4(), display_label="A"
    )
    profile = _character_record(
        novel_id, ref, (main.id,), secret_text="Do not reveal the hidden identity."
    )
    public_revision = uuid4()
    secret_revision = uuid4()
    public_state = _fact(
        novel_id,
        main.id,
        subject="public-state",
        sequence=2,
        visibility=_visibility(VisibilityScope.ALL),
        source_revision_id=public_revision,
        character_ref=ref,
    )
    author_secret_fact = _fact(
        novel_id,
        main.id,
        subject="secret-canon",
        sequence=2,
        visibility=_visibility(VisibilityScope.AUTHOR),
        source_revision_id=secret_revision,
    )
    semantic_revision = uuid4()
    semantic = _semantic(
        novel_id,
        content="vector-only suggestion contradicting the ledger",
        timeline_id=main.id,
        sequence=2,
        visibility=_visibility(VisibilityScope.ALL),
        revision_id=semantic_revision,
    )
    outline_content = "formal outline"
    asset_content = "fixed private material"
    snapshot = NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=StoryPositionV2(narrative_sequence=3),
        perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        chapter_requirements=ChapterRoleConstraintsV3(
            required_characters=(ref,),
            point_of_view=ref,
            public_requirements=("keep the scene focused",),
        ),
        timelines=(main,),
        character_records=(profile,),
        facts=(public_state, author_secret_fact),
        source_revision_validity={
            public_revision: True,
            secret_revision: True,
            semantic_revision: True,
        },
        formal_planning=(
            FormalPlanningRecordV1(
                novel_id=novel_id,
                planning_kind=PlanningKind.OUTLINE,
                source_id=uuid4(),
                revision_id=uuid4(),
                title="outline",
                content=outline_content,
                content_hash=_hash(outline_content),
            ),
        ),
        private_assets=(
            BoundPrivateAssetRecordV1(
                novel_id=novel_id,
                binding_id=uuid4(),
                asset_id=uuid4(),
                asset_version_id=uuid4(),
                title="asset",
                content=asset_content,
                content_hash=_hash(asset_content),
                policy=PrivateAssetPolicy.REQUIRED,
            ),
        ),
        semantic_evidence=(semantic,),
    )

    envelope = assemble_novel_context(snapshot)

    assert envelope.section_order == CONTEXT_SECTION_ORDER
    assert tuple(name for name, _ in envelope.ordered_sections()) == CONTEXT_SECTION_ORDER
    assert envelope.chapter_timeline.timeline_id == main.id
    assert envelope.character_state[0].current_state_facts == (public_state,)
    assert envelope.story_state.current_facts == ()
    assert envelope.chapter_requirements.author_secret_facts == (author_secret_fact,)
    assert envelope.chapter_requirements.author_secret_constraints == (
        profile.author_secret_constraints[0],
    )
    assert envelope.semantic_evidence[0].content.startswith("vector-only")
    assert envelope.semantic_evidence[0].authority is ContextAuthority.SUPPLEMENTAL
    assert any(
        item.source_id == public_state.id
        and item.authority is ContextAuthority.DETERMINISTIC
        for item in envelope.diagnostics.sources
    )
    assert any(
        item.source_id == semantic.source_id
        and item.authority is ContextAuthority.SUPPLEMENTAL
        for item in envelope.diagnostics.sources
    )
    assert public_state.object_text != envelope.semantic_evidence[0].content


def test_character_perspective_filters_future_sibling_hidden_and_invalid_sources() -> None:
    novel_id = uuid4()
    other_novel_id = uuid4()
    main = _timeline(novel_id, key="main", kind=TimelineKind.MAIN, primary=True)
    branch = _timeline(
        novel_id,
        key="branch",
        kind=TimelineKind.BRANCH,
        parent_id=main.id,
        fork_sequence=5,
    )
    sibling = _timeline(
        novel_id,
        key="sibling",
        kind=TimelineKind.BRANCH,
        parent_id=main.id,
        fork_sequence=5,
    )
    observer = CharacterRefV2(
        character_id=uuid4(), character_instance_id=uuid4(), display_label="observer"
    )
    other_instance_id = uuid4()
    profile = _character_record(
        novel_id,
        observer,
        (branch.id,),
        secret_text="withheld-profile-secret",
    )
    fact_specs = (
        ("main-before-fork", main.id, 4, _visibility(VisibilityScope.ALL)),
        ("main-after-fork", main.id, 6, _visibility(VisibilityScope.ALL)),
        ("branch-current", branch.id, 6, _visibility(VisibilityScope.ALL)),
        ("sibling-leak", sibling.id, 6, _visibility(VisibilityScope.ALL)),
        ("branch-future", branch.id, 8, _visibility(VisibilityScope.ALL)),
        (
            "other-character-secret",
            branch.id,
            7,
            _visibility(
                VisibilityScope.CHARACTER_INSTANCES,
                instance_ids=(other_instance_id,),
            ),
        ),
        ("author-only-secret", branch.id, 7, _visibility(VisibilityScope.AUTHOR)),
    )
    revisions: dict[str, UUID] = {name: uuid4() for name, *_ in fact_specs}
    facts = tuple(
        _fact(
            novel_id,
            timeline_id,
            subject=name,
            sequence=sequence,
            visibility=visibility,
            source_revision_id=revisions[name],
        )
        for name, timeline_id, sequence, visibility in fact_specs
    )
    cross_novel_revision = uuid4()
    cross_novel_fact = _fact(
        other_novel_id,
        main.id,
        subject="cross-novel-leak",
        sequence=1,
        visibility=_visibility(VisibilityScope.ALL),
        source_revision_id=cross_novel_revision,
    )
    invalid_revision = uuid4()
    invalid_fact = _fact(
        novel_id,
        branch.id,
        subject="invalid-source-leak",
        sequence=6,
        visibility=_visibility(VisibilityScope.ALL),
        source_revision_id=invalid_revision,
    )
    semantic_valid_main_revision = uuid4()
    semantic_valid_branch_revision = uuid4()
    semantic_records = (
        _semantic(
            novel_id,
            content="semantic-main-before",
            timeline_id=main.id,
            sequence=4,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=semantic_valid_main_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-main-after-leak",
            timeline_id=main.id,
            sequence=6,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=semantic_valid_main_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-branch-current",
            timeline_id=branch.id,
            sequence=6,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=semantic_valid_branch_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-sibling-leak",
            timeline_id=sibling.id,
            sequence=6,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=semantic_valid_branch_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-future-leak",
            timeline_id=branch.id,
            sequence=8,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=semantic_valid_branch_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-hidden-leak",
            timeline_id=branch.id,
            sequence=6,
            visibility=_visibility(VisibilityScope.AUTHOR),
            revision_id=semantic_valid_branch_revision,
        ),
        _semantic(
            novel_id,
            content="semantic-invalid-leak",
            timeline_id=branch.id,
            sequence=6,
            visibility=_visibility(VisibilityScope.ALL),
            revision_id=uuid4(),
        ),
        _semantic(
            other_novel_id,
            content="semantic-cross-novel-leak",
            timeline_id=branch.id,
            sequence=1,
            visibility=_visibility(VisibilityScope.ALL),
        ),
    )
    planning_secret = "formal-planning-author-leak"
    private_secret = "fixed-private-author-leak"
    source_validity = {revision_id: True for revision_id in revisions.values()}
    source_validity.update(
        {
            cross_novel_revision: True,
            invalid_revision: False,
            semantic_valid_main_revision: True,
            semantic_valid_branch_revision: True,
        }
    )
    snapshot = NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=StoryPositionV2(
            timeline_id=branch.id,
            narrative_sequence=7,
        ),
        perspective=PerspectiveV1(
            kind=PerspectiveKind.CHARACTER,
            observer_character_instance_id=observer.character_instance_id,
        ),
        chapter_requirements=ChapterRoleConstraintsV3(
            required_characters=(observer,), point_of_view=observer
        ),
        timelines=(main, branch, sibling),
        character_records=(profile,),
        facts=(*facts, cross_novel_fact, invalid_fact),
        source_revision_validity=source_validity,
        formal_planning=(
            FormalPlanningRecordV1(
                novel_id=novel_id,
                planning_kind=PlanningKind.OUTLINE,
                source_id=uuid4(),
                revision_id=uuid4(),
                title="author planning",
                content=planning_secret,
                content_hash=_hash(planning_secret),
            ),
        ),
        private_assets=(
            BoundPrivateAssetRecordV1(
                novel_id=novel_id,
                binding_id=uuid4(),
                asset_id=uuid4(),
                asset_version_id=uuid4(),
                title="author private asset",
                content=private_secret,
                content_hash=_hash(private_secret),
                policy=PrivateAssetPolicy.REQUIRED,
            ),
        ),
        semantic_evidence=semantic_records,
    )

    envelope = assemble_novel_context(snapshot)
    serialized = envelope.model_dump_json()

    assert "main-before-fork" in serialized
    assert "branch-current" in serialized
    for forbidden in (
        "main-after-fork",
        "sibling-leak",
        "branch-future",
        "other-character-secret",
        "author-only-secret",
        "cross-novel-leak",
        "invalid-source-leak",
        "semantic-main-after-leak",
        "semantic-sibling-leak",
        "semantic-future-leak",
        "semantic-hidden-leak",
        "semantic-invalid-leak",
        "semantic-cross-novel-leak",
        "withheld-profile-secret",
        planning_secret,
        private_secret,
    ):
        assert forbidden not in serialized
    assert {item.content for item in envelope.semantic_evidence} == {
        "semantic-main-before",
        "semantic-branch-current",
    }
    omission_codes = {item.code for item in envelope.diagnostics.omissions}
    assert {
        OmissionCode.AFTER_CUTOFF,
        OmissionCode.OUTSIDE_TIMELINE,
        OmissionCode.NOT_VISIBLE,
        OmissionCode.SOURCE_INVALID,
        OmissionCode.CROSS_NOVEL,
        OmissionCode.AUTHOR_SECRET_WITHHELD,
    } <= omission_codes


def test_stable_character_ids_are_required_and_names_are_never_resolved() -> None:
    with pytest.raises(ValidationError):
        CharacterRefV2.model_validate({"display_label": "same name"})

    novel_id = uuid4()
    main = _timeline(novel_id, key="main", kind=TimelineKind.MAIN, primary=True)
    actual_ref = CharacterRefV2(
        character_id=uuid4(),
        character_instance_id=uuid4(),
        display_label="same name",
    )
    wrong_ref = CharacterRefV2(
        character_id=actual_ref.character_id,
        character_instance_id=uuid4(),
        display_label="same name",
    )
    snapshot = NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=StoryPositionV2(),
        perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        chapter_requirements=ChapterRoleConstraintsV3(
            required_characters=(wrong_ref,)
        ),
        timelines=(main,),
        character_records=(
            _character_record(novel_id, actual_ref, (main.id,)),
        ),
    )

    with pytest.raises(ContextAssemblyError) as error:
        assemble_novel_context(snapshot)
    assert error.value.code is ContextAssemblyErrorCode.REQUIRED_CHARACTER_UNAVAILABLE
    assert error.value.details["character_instance_id"] == str(
        wrong_ref.character_instance_id
    )


def test_conflicts_keep_both_deterministic_sources_and_select_no_winner() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id, key="main", kind=TimelineKind.MAIN, primary=True)
    first_revision = uuid4()
    second_revision = uuid4()
    first = _fact(
        novel_id,
        main.id,
        subject="same-key",
        sequence=3,
        visibility=_visibility(VisibilityScope.ALL),
        source_revision_id=first_revision,
    )
    second_id = uuid4()
    second = first.model_copy(
        update={
            "id": second_id,
            "object_text": "different-value",
            "details": GeneralFactDetailsV1(value="different-value"),
            "source_revision_id": second_revision,
            "source_document_id": uuid4(),
            "event_fingerprint": _hash(str(second_id)),
        }
    )
    snapshot = NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=StoryPositionV2(narrative_sequence=3),
        perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        chapter_requirements=ChapterRoleConstraintsV3(),
        timelines=(main,),
        facts=(first, second),
        source_revision_validity={first_revision: True, second_revision: True},
    )

    envelope = assemble_novel_context(snapshot)

    assert envelope.story_state.current_facts == ()
    assert len(envelope.diagnostics.conflicts) == 1
    assert set(envelope.diagnostics.conflicts[0].fact_ids) == {first.id, second.id}
    deterministic_source_ids = {
        item.source_id
        for item in envelope.diagnostics.sources
        if item.authority is ContextAuthority.DETERMINISTIC
    }
    assert {first.id, second.id} <= deterministic_source_ids


def test_implicit_timeline_only_works_for_a_single_active_timeline() -> None:
    novel_id = uuid4()
    main = _timeline(novel_id, key="main", kind=TimelineKind.MAIN, primary=True)
    branch = _timeline(
        novel_id,
        key="branch",
        kind=TimelineKind.BRANCH,
        parent_id=main.id,
        fork_sequence=1,
    )
    snapshot = NovelContextAssemblySnapshotV3(
        novel_id=novel_id,
        position=StoryPositionV2(),
        perspective=PerspectiveV1(kind=PerspectiveKind.AUTHOR),
        chapter_requirements=ChapterRoleConstraintsV3(),
        timelines=(main, branch),
    )

    with pytest.raises(StoryStateError) as error:
        assemble_novel_context(snapshot)
    assert error.value.code is StoryStateErrorCode.TIMELINE_REQUIRED


def test_context_package_exposes_no_write_capability() -> None:
    package_dir = Path(__file__).parents[2] / "backend" / "context_v3"
    forbidden_methods = {"add", "commit", "delete", "execute", "flush", "merge"}
    violations: list[str] = []
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.startswith("sqlalchemy") for alias in node.names):
                    violations.append(f"{path.name}:sqlalchemy import")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("sqlalchemy"):
                    violations.append(f"{path.name}:sqlalchemy import")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_methods
            ):
                violations.append(f"{path.name}:{node.func.attr}")
    assert violations == []
