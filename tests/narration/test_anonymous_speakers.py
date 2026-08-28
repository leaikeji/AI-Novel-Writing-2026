from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

import pytest

from backend.narration.anonymous_speakers import (
    ANONYMOUS_OPERATION_VERSION,
    AnonymousIdentityConflictError,
    AnonymousIdentitySeed,
    AnonymousInheritanceAmbiguityError,
    AnonymousLifecycleState,
    AnonymousOperationActor,
    AnonymousOperationHeader,
    AnonymousResolutionKind,
    AnonymousReuseBasis,
    AnonymousScopeAuthority,
    AnonymousSpeakerError,
    HistoricalAnonymousReference,
    MergeAnonymousSpeakers,
    PromoteAnonymousSpeaker,
    RegisterAnonymousSpeaker,
    SceneScopeBinding,
    SplitAnonymousSpeaker,
    SplitBranch,
    anonymous_operation_from_dict,
    anonymous_operation_to_dict,
    apply_anonymous_operation,
    empty_anonymous_registry,
    materialize_anonymous_identity,
    replay_anonymous_operations,
)
from backend.narration.contracts import ConfidenceLevel
from backend.narration.script_contracts import (
    ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
    AnonymousScopeKind,
    AnonymousSpeakerIdentity,
    ScriptContractError,
    derive_anonymous_speaker_id,
    derive_anonymous_stable_key,
)


NOVEL_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
CHAPTER_1 = UUID("33333333-3333-4333-8333-333333333331")
CHAPTER_2 = UUID("33333333-3333-4333-8333-333333333332")
SCENE_1 = UUID("44444444-4444-4444-8444-444444444441")
SCENE_2 = UUID("44444444-4444-4444-8444-444444444442")
SCENE_3 = UUID("44444444-4444-4444-8444-444444444443")
CHARACTER_1 = UUID("55555555-5555-4555-8555-555555555551")
CHARACTER_2 = UUID("55555555-5555-4555-8555-555555555552")
OWNER_ID = UUID("66666666-6666-4666-8666-666666666666")
REF_1 = UUID("77777777-7777-4777-8777-777777777771")
REF_2 = UUID("77777777-7777-4777-8777-777777777772")
REF_3 = UUID("77777777-7777-4777-8777-777777777773")
BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
ACTION_NAMESPACE = UUID("88888888-8888-4888-8888-888888888888")


def _evidence(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _authority(
    *,
    references: tuple[
        tuple[UUID, UUID, AnonymousScopeKind, UUID], ...
    ] = (),
    character_ids: frozenset[UUID] = frozenset({CHARACTER_1}),
) -> AnonymousScopeAuthority:
    return AnonymousScopeAuthority(
        novel_id=NOVEL_ID,
        chapter_ids=frozenset({CHAPTER_1, CHAPTER_2}),
        scene_bindings=frozenset(
            {
                SceneScopeBinding(SCENE_1, CHAPTER_1),
                SceneScopeBinding(SCENE_2, CHAPTER_1),
                SceneScopeBinding(SCENE_3, CHAPTER_2),
            }
        ),
        character_ids=character_ids,
        historical_references=frozenset(
            HistoricalAnonymousReference(
                speaker_id,
                reference_id,
                scope_kind,
                scope_id,
            )
            for speaker_id, reference_id, scope_kind, scope_id in references
        ),
    )


def _seed(
    authority: AnonymousScopeAuthority,
    label: str,
    *,
    scope_kind: AnonymousScopeKind = AnonymousScopeKind.SCENE,
    scope_id: UUID = SCENE_1,
    evidence: str | None = None,
    reuse_basis: AnonymousReuseBasis = AnonymousReuseBasis.LOCAL_CONTEXT,
    aliases: tuple[str, ...] = (),
) -> AnonymousIdentitySeed:
    return materialize_anonymous_identity(
        authority=authority,
        scope_kind=scope_kind,
        scope_id=scope_id,
        source_label=label,
        evidence_hash=_evidence(evidence or label),
        display_name=label,
        confidence=ConfidenceLevel.HIGH,
        reuse_basis=reuse_basis,
        explicit_aliases=aliases,
    )


def _header(
    ordinal: int,
    name: str,
    *,
    actor: AnonymousOperationActor = AnonymousOperationActor.OWNER,
    novel_id: UUID = NOVEL_ID,
    recorded_at: datetime | None = None,
) -> AnonymousOperationHeader:
    return AnonymousOperationHeader(
        action_id=uuid5(ACTION_NAMESPACE, name),
        novel_id=novel_id,
        ordinal=ordinal,
        actor=actor,
        actor_id=OWNER_ID if actor is AnonymousOperationActor.OWNER else None,
        recorded_at=recorded_at or BASE_TIME + timedelta(seconds=ordinal),
    )


def _register(
    seed: AnonymousIdentitySeed,
    ordinal: int,
    name: str,
    *,
    system: bool = False,
) -> RegisterAnonymousSpeaker:
    return RegisterAnonymousSpeaker(
        header=_header(
            ordinal,
            name,
            actor=(
                AnonymousOperationActor.SYSTEM
                if system
                else AnonymousOperationActor.OWNER
            ),
        ),
        seed=seed,
    )


def _sorted_branches(*branches: SplitBranch) -> tuple[SplitBranch, ...]:
    return tuple(
        sorted(
            branches,
            key=lambda branch: (
                branch.seed.identity.stable_key_algorithm,
                branch.seed.identity.stable_key,
                str(branch.seed.identity.anonymous_speaker_id),
            ),
        )
    )


def test_materialization_uses_frozen_stable_key_and_speaker_id() -> None:
    authority = _authority()
    seed = _seed(authority, "店小二")
    identity = seed.identity  # type: ignore[union-attr]

    expected_key = derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=SCENE_1,
        label="店小二",
        evidence_hash=_evidence("店小二"),
    )
    assert identity.stable_key_algorithm == ANONYMOUS_SPEAKER_STABLE_KEY_VERSION
    assert identity.stable_key == expected_key
    assert identity.anonymous_speaker_id == derive_anonymous_speaker_id(
        novel_id=NOVEL_ID,
        stable_key=expected_key,
    )


def test_stable_identity_is_deterministic_but_scope_evidence_and_novel_separate() -> None:
    authority = _authority()
    same_a = _seed(authority, "老妇人")
    same_b = _seed(authority, "老妇人")
    evidence_changed = _seed(authority, "老妇人", evidence="第二次证据")
    scope_changed = _seed(
        authority,
        "老妇人",
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=SCENE_2,
    )
    other_authority = AnonymousScopeAuthority(novel_id=OTHER_NOVEL_ID)
    other_novel = _seed(
        other_authority,
        "老妇人",
        scope_kind=AnonymousScopeKind.NOVEL,
        scope_id=OTHER_NOVEL_ID,
        reuse_basis=AnonymousReuseBasis.OWNER_CONFIRMED,
    )

    assert same_a == same_b
    ids = {
        value.identity.anonymous_speaker_id  # type: ignore[union-attr]
        for value in (same_a, evidence_changed, scope_changed, other_novel)
    }
    assert len(ids) == 4


@pytest.mark.parametrize(
    ("scope_kind", "scope_id"),
    [
        (AnonymousScopeKind.SCENE, SCENE_1),
        (AnonymousScopeKind.CHAPTER, CHAPTER_1),
        (AnonymousScopeKind.NOVEL, NOVEL_ID),
    ],
)
def test_scene_chapter_and_novel_scopes_are_materialized(
    scope_kind: AnonymousScopeKind,
    scope_id: UUID,
) -> None:
    reuse_basis = (
        AnonymousReuseBasis.OWNER_CONFIRMED
        if scope_kind is AnonymousScopeKind.NOVEL
        else AnonymousReuseBasis.LOCAL_CONTEXT
    )
    seed = _seed(
        _authority(),
        f"{scope_kind.value}-人物",
        scope_kind=scope_kind,
        scope_id=scope_id,
        reuse_basis=reuse_basis,
    )

    assert seed.identity.scope_kind is scope_kind  # type: ignore[union-attr]
    assert seed.identity.scope_id == scope_id  # type: ignore[union-attr]


def test_scope_authority_rejects_cross_novel_or_unknown_scope_ids() -> None:
    authority = _authority()

    with pytest.raises(AnonymousSpeakerError, match="novel scope_id"):
        _seed(
            authority,
            "跨作品",
            scope_kind=AnonymousScopeKind.NOVEL,
            scope_id=OTHER_NOVEL_ID,
            reuse_basis=AnonymousReuseBasis.OWNER_CONFIRMED,
        )
    with pytest.raises(AnonymousSpeakerError, match="chapter scope"):
        _seed(
            authority,
            "未知章节",
            scope_kind=AnonymousScopeKind.CHAPTER,
            scope_id=uuid4(),
        )
    with pytest.raises(AnonymousSpeakerError, match="scene scope"):
        _seed(authority, "未知场景", scope_id=uuid4())


def test_future_resolution_rejects_reuse_outside_identity_scope() -> None:
    authority = _authority()
    scene_seed = _seed(authority, "只在第一场出现")
    chapter_seed = _seed(
        authority,
        "第一章人物",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_1,
    )
    registry = replay_anonymous_operations(
        authority,
        (
            _register(scene_seed, 0, "scope-scene"),
            _register(chapter_seed, 1, "scope-chapter"),
        ),
    )

    with pytest.raises(AnonymousSpeakerError, match="outside its authorized scope"):
        registry.resolve_for_new_script(
            scene_seed.identity.anonymous_speaker_id,
            usage_scope_kind=AnonymousScopeKind.SCENE,
            usage_scope_id=SCENE_2,
        )
    assert registry.resolve_for_new_script(
        chapter_seed.identity.anonymous_speaker_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_2,
    ).anonymous_speaker_id == chapter_seed.identity.anonymous_speaker_id


def test_historical_reference_id_is_globally_single_owner() -> None:
    with pytest.raises(AnonymousSpeakerError, match="exactly one identity"):
        _authority(
            references=(
                (REF_1, REF_3, AnonymousScopeKind.SCENE, SCENE_1),
                (REF_2, REF_3, AnonymousScopeKind.SCENE, SCENE_1),
            )
        )


def test_replay_rejects_historical_reference_for_unregistered_identity() -> None:
    authority = _authority(
        references=(
            (REF_1, REF_2, AnonymousScopeKind.SCENE, SCENE_1),
        )
    )

    with pytest.raises(AnonymousSpeakerError, match="unregistered identity"):
        replay_anonymous_operations(authority, ())


def test_novel_scope_requires_alias_evidence_or_owner_confirmation() -> None:
    authority = _authority()
    local = _seed(
        authority,
        "侍卫",
        scope_kind=AnonymousScopeKind.NOVEL,
        scope_id=NOVEL_ID,
    )
    registry = empty_anonymous_registry(authority)

    with pytest.raises(AnonymousSpeakerError, match="novel-scope reuse"):
        apply_anonymous_operation(registry, _register(local, 0, "local-novel", system=True))

    alias_seed = _seed(
        authority,
        "侍卫长",
        scope_kind=AnonymousScopeKind.NOVEL,
        scope_id=NOVEL_ID,
        reuse_basis=AnonymousReuseBasis.EXPLICIT_ALIAS,
        aliases=("禁军统领",),
    )
    accepted = apply_anonymous_operation(
        registry,
        _register(alias_seed, 0, "alias-novel", system=True),
    )
    assert accepted.revision == 1


def test_owner_confirmed_novel_scope_rejects_system_actor() -> None:
    authority = _authority()
    seed = _seed(
        authority,
        "跨章掌柜",
        scope_kind=AnonymousScopeKind.NOVEL,
        scope_id=NOVEL_ID,
        reuse_basis=AnonymousReuseBasis.OWNER_CONFIRMED,
    )

    with pytest.raises(AnonymousSpeakerError, match="owner operation"):
        replay_anonymous_operations(
            authority,
            (_register(seed, 0, "owner-confirmed-system", system=True),),
        )


def test_aliases_are_nfc_normalized_unique_and_canonical() -> None:
    authority = _authority()
    seed = _seed(
        authority,
        "掌柜",
        reuse_basis=AnonymousReuseBasis.EXPLICIT_ALIAS,
        aliases=("A\u0301", "老板"),
    )
    assert seed.explicit_aliases == ("Á", "老板")  # type: ignore[union-attr]

    with pytest.raises(AnonymousSpeakerError, match="unique"):
        _seed(
            authority,
            "重复别名",
            reuse_basis=AnonymousReuseBasis.EXPLICIT_ALIAS,
            aliases=("Ａ", "a"),
        )


def test_unknown_stable_key_algorithm_and_tampered_derivation_fail_closed() -> None:
    seed = _seed(_authority(), "陌生女子")
    identity = seed.identity  # type: ignore[union-attr]

    with pytest.raises(ScriptContractError, match="unknown anonymous stable-key algorithm"):
        replace(identity, stable_key_algorithm="anonymous-speaker-stable-key/2")
    with pytest.raises(AnonymousSpeakerError, match="stable_key differs"):
        replace(seed, identity=replace(identity, stable_key="as1_" + "0" * 64))  # type: ignore[arg-type]


def test_operation_header_rejects_unknown_version_actor_shape_and_non_utc_time() -> None:
    with pytest.raises(AnonymousSpeakerError, match="schema version"):
        replace(_header(0, "version"), schema_version="anonymous-speaker-operation/2")
    with pytest.raises(AnonymousSpeakerError, match="owner actor_id"):
        AnonymousOperationHeader(
            action_id=uuid4(),
            novel_id=NOVEL_ID,
            ordinal=0,
            actor=AnonymousOperationActor.OWNER,
            actor_id=None,
            recorded_at=BASE_TIME,
        )
    with pytest.raises(AnonymousSpeakerError, match="UTC datetime"):
        replace(_header(0, "time"), recorded_at=datetime(2026, 8, 26, 12, 0))


def test_registration_replay_is_deterministic_and_snapshot_is_canonical() -> None:
    authority = _authority()
    first = _seed(authority, "老妇人", evidence="B")
    second = _seed(authority, "小男孩", evidence="A", scope_id=SCENE_2)
    operations = (
        _register(first, 0, "register-first", system=True),
        _register(second, 1, "register-second", system=True),
    )

    one = replay_anonymous_operations(authority, operations)
    two = replay_anonymous_operations(authority, operations)

    assert one == two
    snapshot = one.historical_script_snapshot(
        [
            second.identity.anonymous_speaker_id,  # type: ignore[union-attr]
            first.identity.anonymous_speaker_id,  # type: ignore[union-attr]
            second.identity.anonymous_speaker_id,  # type: ignore[union-attr]
        ]
    )
    assert snapshot == tuple(
        sorted(
            snapshot,
            key=lambda identity: (
                identity.stable_key_algorithm,
                identity.stable_key,
                str(identity.anonymous_speaker_id),
            ),
        )
    )
    assert all(type(value) is AnonymousSpeakerIdentity for value in snapshot)


def test_apply_exact_action_retry_is_idempotent_but_payload_reuse_is_rejected() -> None:
    authority = _authority()
    first = _seed(authority, "路人甲")
    second = _seed(authority, "路人乙", evidence="other")
    operation = _register(first, 0, "retry", system=True)
    registry = apply_anonymous_operation(empty_anonymous_registry(authority), operation)

    assert apply_anonymous_operation(registry, operation) is registry
    conflicting = RegisterAnonymousSpeaker(header=operation.header, seed=second)  # type: ignore[arg-type]
    with pytest.raises(AnonymousIdentityConflictError, match="different operation payload"):
        apply_anonymous_operation(registry, conflicting)


def test_operation_replay_rejects_duplicate_action_gaps_and_backward_time() -> None:
    authority = _authority()
    first = _register(_seed(authority, "甲"), 0, "dup", system=True)
    duplicate = replace(first, header=replace(first.header, ordinal=1))
    with pytest.raises(AnonymousIdentityConflictError, match="duplicate action_id"):
        replay_anonymous_operations(authority, (first, duplicate))

    gap = _register(_seed(authority, "乙", evidence="gap"), 2, "gap", system=True)
    with pytest.raises(AnonymousSpeakerError, match="contiguous"):
        replay_anonymous_operations(authority, (first, gap))

    backward = _register(
        _seed(authority, "丙", evidence="back"),
        1,
        "back",
        system=True,
    )
    backward = replace(
        backward,
        header=replace(backward.header, recorded_at=BASE_TIME - timedelta(seconds=1)),
    )
    with pytest.raises(AnonymousSpeakerError, match="move backwards"):
        replay_anonymous_operations(authority, (first, backward))


def test_duplicate_stable_identity_requires_explicit_conflict_resolution() -> None:
    authority = _authority()
    seed = _seed(authority, "守门人")

    with pytest.raises(AnonymousIdentityConflictError, match="already registered"):
        replay_anonymous_operations(
            authority,
            (
                _register(seed, 0, "duplicate-1", system=True),
                _register(seed, 1, "duplicate-2", system=True),
            ),
        )


def test_merge_resolves_future_scripts_but_keeps_historical_identity() -> None:
    authority = _authority()
    target = _seed(
        authority,
        "店员",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_1,
    )
    source = _seed(authority, "店小二", scope_id=SCENE_1)
    target_id = target.identity.anonymous_speaker_id  # type: ignore[union-attr]
    source_id = source.identity.anonymous_speaker_id  # type: ignore[union-attr]
    operations = (
        _register(target, 0, "merge-target"),
        _register(source, 1, "merge-source"),
        MergeAnonymousSpeakers(
            header=_header(2, "merge"),
            source_ids=(source_id,),
            target_id=target_id,
        ),
    )
    registry = replay_anonymous_operations(authority, operations)

    assert registry.lifecycle(source_id) is AnonymousLifecycleState.MERGED
    assert registry.lifecycle(target_id) is AnonymousLifecycleState.ACTIVE
    assert registry.resolve_for_new_script(
        source_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
    ).anonymous_speaker_id == target_id
    assert registry.historical_identity(source_id) == source.identity  # type: ignore[union-attr]


def test_merge_target_scope_must_contain_every_source_scope() -> None:
    authority = _authority()
    target = _seed(
        authority,
        "第一章路人",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_1,
    )
    source = _seed(authority, "第二章路人", scope_id=SCENE_3)
    target_id = target.identity.anonymous_speaker_id  # type: ignore[union-attr]
    source_id = source.identity.anonymous_speaker_id  # type: ignore[union-attr]

    with pytest.raises(AnonymousIdentityConflictError, match="does not contain"):
        replay_anonymous_operations(
            authority,
            (
                _register(target, 0, "scope-target"),
                _register(source, 1, "scope-source"),
                MergeAnonymousSpeakers(
                    header=_header(2, "scope-merge"),
                    source_ids=(source_id,),
                    target_id=target_id,
                ),
            ),
        )


def test_merge_requires_owner_and_rejects_merged_source_reuse() -> None:
    authority = _authority()
    target = _seed(authority, "目标", evidence="target")
    source = _seed(authority, "来源", evidence="source")
    other = _seed(authority, "其他", evidence="other")
    target_id = target.identity.anonymous_speaker_id  # type: ignore[union-attr]
    source_id = source.identity.anonymous_speaker_id  # type: ignore[union-attr]
    other_id = other.identity.anonymous_speaker_id  # type: ignore[union-attr]
    base = (
        _register(target, 0, "owner-target"),
        _register(source, 1, "owner-source"),
        _register(other, 2, "owner-other"),
    )
    system_merge = MergeAnonymousSpeakers(
        header=_header(3, "system-merge", actor=AnonymousOperationActor.SYSTEM),
        source_ids=(source_id,),
        target_id=target_id,
    )
    with pytest.raises(AnonymousSpeakerError, match="owner authority"):
        replay_anonymous_operations(authority, (*base, system_merge))

    first_merge = replace(system_merge, header=_header(3, "first-merge"))
    second_merge = MergeAnonymousSpeakers(
        header=_header(4, "second-merge"),
        source_ids=(source_id,),
        target_id=other_id,
    )
    with pytest.raises(AnonymousIdentityConflictError, match="source is not active"):
        replay_anonymous_operations(
            authority,
            (*base, first_merge, second_merge),
        )


def test_merge_rejects_cross_novel_operation_and_noncanonical_sources() -> None:
    with pytest.raises(AnonymousSpeakerError, match="canonical UUID order"):
        MergeAnonymousSpeakers(
            header=_header(0, "order"),
            source_ids=tuple(sorted((REF_1, REF_2), key=str, reverse=True)),
            target_id=REF_3,
        )
    with pytest.raises(AnonymousSpeakerError, match="target cannot"):
        MergeAnonymousSpeakers(
            header=_header(0, "target-source"),
            source_ids=(REF_1,),
            target_id=REF_1,
        )

    authority = _authority()
    seed = _seed(authority, "跨作品操作")
    cross = RegisterAnonymousSpeaker(
        header=_header(0, "cross", novel_id=OTHER_NOVEL_ID),
        seed=seed,  # type: ignore[arg-type]
    )
    with pytest.raises(AnonymousSpeakerError, match="another novel"):
        replay_anonymous_operations(authority, (cross,))


def _split_fixture():
    base_authority = _authority()
    parent = _seed(
        base_authority,
        "侍卫",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_1,
    )
    child_a = _seed(base_authority, "东门侍卫", scope_id=SCENE_1)
    child_b = _seed(base_authority, "西门侍卫", scope_id=SCENE_2)
    parent_id = parent.identity.anonymous_speaker_id  # type: ignore[union-attr]
    authority = _authority(
        references=(
            (parent_id, REF_1, AnonymousScopeKind.SCENE, SCENE_1),
            (parent_id, REF_2, AnonymousScopeKind.SCENE, SCENE_1),
            (parent_id, REF_3, AnonymousScopeKind.SCENE, SCENE_2),
        )
    )
    branches = _sorted_branches(
        SplitBranch(child_a, (REF_1, REF_2)),  # type: ignore[arg-type]
        SplitBranch(child_b, (REF_3,)),  # type: ignore[arg-type]
    )
    split = SplitAnonymousSpeaker(
        header=_header(1, "split"),
        parent_id=parent_id,
        branches=branches,
    )
    return authority, parent, child_a, child_b, split


def test_split_exact_partition_routes_reanalysis_without_rewriting_history() -> None:
    authority, parent, child_a, child_b, split = _split_fixture()
    parent_id = parent.identity.anonymous_speaker_id  # type: ignore[union-attr]
    registry = replay_anonymous_operations(
        authority,
        (_register(parent, 0, "split-parent"), split),
    )

    assert registry.lifecycle(parent_id) is AnonymousLifecycleState.SPLIT
    assert registry.historical_identity(parent_id) == parent.identity  # type: ignore[union-attr]
    with pytest.raises(AnonymousInheritanceAmbiguityError, match="exact historical reference"):
        registry.resolve_for_new_script(
            parent_id,
            usage_scope_kind=AnonymousScopeKind.SCENE,
            usage_scope_id=SCENE_1,
        )

    routes = {
        REF_1: registry.resolve_for_new_script(
            parent_id,
            usage_scope_kind=AnonymousScopeKind.SCENE,
            usage_scope_id=SCENE_1,
            historical_reference_id=REF_1,
        ).anonymous_speaker_id,
        REF_2: registry.resolve_for_new_script(
            parent_id,
            usage_scope_kind=AnonymousScopeKind.SCENE,
            usage_scope_id=SCENE_1,
            historical_reference_id=REF_2,
        ).anonymous_speaker_id,
        REF_3: registry.resolve_for_new_script(
            parent_id,
            usage_scope_kind=AnonymousScopeKind.SCENE,
            usage_scope_id=SCENE_2,
            historical_reference_id=REF_3,
        ).anonymous_speaker_id,
    }
    assert routes[REF_1] == routes[REF_2] == child_a.identity.anonymous_speaker_id  # type: ignore[union-attr]
    assert routes[REF_3] == child_b.identity.anonymous_speaker_id  # type: ignore[union-attr]


def test_nested_split_replays_reference_ownership_through_prior_split() -> None:
    authority, parent, child_a, _, first_split = _split_fixture()
    child_a_id = child_a.identity.anonymous_speaker_id  # type: ignore[union-attr]
    grandchild_a = _seed(
        authority,
        "东门侍卫甲",
        evidence="nested-a",
        scope_id=SCENE_1,
    )
    grandchild_b = _seed(
        authority,
        "东门侍卫乙",
        evidence="nested-b",
        scope_id=SCENE_1,
    )
    second_split = SplitAnonymousSpeaker(
        header=_header(2, "nested-split"),
        parent_id=child_a_id,
        branches=_sorted_branches(
            SplitBranch(grandchild_a, (REF_1,)),
            SplitBranch(grandchild_b, (REF_2,)),
        ),
    )
    parent_id = parent.identity.anonymous_speaker_id  # type: ignore[union-attr]
    registry = replay_anonymous_operations(
        authority,
        (
            _register(parent, 0, "split-parent"),
            first_split,
            second_split,
        ),
    )

    assert registry.resolve_for_new_script(
        parent_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
        historical_reference_id=REF_1,
    ).anonymous_speaker_id == grandchild_a.identity.anonymous_speaker_id  # type: ignore[union-attr]
    assert registry.resolve_for_new_script(
        child_a_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
        historical_reference_id=REF_2,
    ).anonymous_speaker_id == grandchild_b.identity.anonymous_speaker_id  # type: ignore[union-attr]
    assert registry.historical_identity(parent_id) == parent.identity  # type: ignore[union-attr]


def test_split_rejects_missing_extra_overlapping_or_unknown_reference_routes() -> None:
    authority, parent, child_a, child_b, split = _split_fixture()
    parent_op = _register(parent, 0, "split-parent")
    missing = replace(
        split,
        branches=_sorted_branches(
            SplitBranch(child_a, (REF_1,)),  # type: ignore[arg-type]
            SplitBranch(child_b, (REF_3,)),  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(AnonymousIdentityConflictError, match="exactly partition"):
        replay_anonymous_operations(authority, (parent_op, missing))

    extra = replace(
        split,
        branches=_sorted_branches(
            SplitBranch(child_a, (REF_1, REF_2)),  # type: ignore[arg-type]
            SplitBranch(
                child_b,
                tuple(sorted((REF_3, uuid4()), key=str)),
            ),  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(AnonymousIdentityConflictError, match="exactly partition"):
        replay_anonymous_operations(authority, (parent_op, extra))

    with pytest.raises(AnonymousSpeakerError, match="disjoint"):
        SplitAnonymousSpeaker(
            header=_header(1, "overlap"),
            parent_id=parent.identity.anonymous_speaker_id,  # type: ignore[union-attr]
            branches=_sorted_branches(
                SplitBranch(child_a, (REF_1, REF_2)),  # type: ignore[arg-type]
                SplitBranch(child_b, (REF_2, REF_3)),  # type: ignore[arg-type]
            ),
        )


def test_split_requires_authoritative_references_and_narrower_same_novel_scope() -> None:
    authority, parent, child_a, child_b, split = _split_fixture()
    no_refs = _authority()
    with pytest.raises(AnonymousIdentityConflictError, match="authoritative historical"):
        replay_anonymous_operations(
            no_refs,
            (_register(parent, 0, "split-parent"), split),
        )

    wrong_child = _seed(
        authority,
        "第二章侍卫",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_2,
    )
    wrong_scope = replace(
        split,
        branches=_sorted_branches(
            SplitBranch(child_a, (REF_1, REF_2)),  # type: ignore[arg-type]
            SplitBranch(wrong_child, (REF_3,)),  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(AnonymousIdentityConflictError, match="within its parent scope"):
        replay_anonymous_operations(
            authority,
            (_register(parent, 0, "split-parent"), wrong_scope),
        )


def test_split_branch_must_cover_each_assigned_reference_scope() -> None:
    authority, parent, child_a, child_b, split = _split_fixture()
    swapped = replace(
        split,
        branches=_sorted_branches(
            SplitBranch(child_a, (REF_3,)),
            SplitBranch(child_b, (REF_1, REF_2)),
        ),
    )

    with pytest.raises(AnonymousIdentityConflictError, match="does not cover"):
        replay_anonymous_operations(
            authority,
            (_register(parent, 0, "split-parent"), swapped),
        )


def test_split_rejects_reference_outside_original_identity_scope() -> None:
    base = _authority()
    parent = _seed(base, "第一场路人", scope_id=SCENE_1)
    child_a = _seed(base, "第一场路人甲", evidence="a", scope_id=SCENE_1)
    child_b = _seed(base, "第一场路人乙", evidence="b", scope_id=SCENE_1)
    parent_id = parent.identity.anonymous_speaker_id
    authority = _authority(
        references=(
            (parent_id, REF_1, AnonymousScopeKind.SCENE, SCENE_1),
            (parent_id, REF_2, AnonymousScopeKind.SCENE, SCENE_2),
        )
    )
    split = SplitAnonymousSpeaker(
        header=_header(1, "bad-source-scope"),
        parent_id=parent_id,
        branches=_sorted_branches(
            SplitBranch(child_a, (REF_1,)),
            SplitBranch(child_b, (REF_2,)),
        ),
    )

    with pytest.raises(AnonymousIdentityConflictError, match="source identity scope"):
        replay_anonymous_operations(
            authority,
            (_register(parent, 0, "bad-source-parent"), split),
        )


def test_split_includes_references_from_every_merged_lineage_identity() -> None:
    base = _authority()
    target = _seed(
        base,
        "统称侍卫",
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=CHAPTER_1,
    )
    source = _seed(base, "东门侍卫旧称", scope_id=SCENE_1)
    child_a = _seed(base, "东门侍卫", evidence="child-a", scope_id=SCENE_1)
    child_b = _seed(base, "另一名东门侍卫", evidence="child-b", scope_id=SCENE_1)
    target_id = target.identity.anonymous_speaker_id  # type: ignore[union-attr]
    source_id = source.identity.anonymous_speaker_id  # type: ignore[union-attr]
    authority = _authority(
        references=(
            (target_id, REF_1, AnonymousScopeKind.SCENE, SCENE_1),
            (source_id, REF_2, AnonymousScopeKind.SCENE, SCENE_1),
        )
    )
    operations = (
        _register(target, 0, "lineage-target"),
        _register(source, 1, "lineage-source"),
        MergeAnonymousSpeakers(
            header=_header(2, "lineage-merge"),
            source_ids=(source_id,),
            target_id=target_id,
        ),
        SplitAnonymousSpeaker(
            header=_header(3, "lineage-split"),
            parent_id=target_id,
            branches=_sorted_branches(
                SplitBranch(child_a, (REF_1,)),  # type: ignore[arg-type]
                SplitBranch(child_b, (REF_2,)),  # type: ignore[arg-type]
            ),
        ),
    )
    registry = replay_anonymous_operations(authority, operations)

    assert registry.resolve_for_new_script(
        source_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
        historical_reference_id=REF_2,
    ).anonymous_speaker_id == child_b.identity.anonymous_speaker_id  # type: ignore[union-attr]


def test_promotion_changes_future_resolution_only_and_preserves_historical_script() -> None:
    authority = _authority()
    seed = _seed(authority, "反复出现的掌柜")
    speaker_id = seed.identity.anonymous_speaker_id  # type: ignore[union-attr]
    operations = (
        _register(seed, 0, "promotion-seed"),
        PromoteAnonymousSpeaker(
            header=_header(1, "promotion"),
            anonymous_speaker_id=speaker_id,
            character_id=CHARACTER_1,
        ),
    )
    registry = replay_anonymous_operations(authority, operations)

    resolution = registry.resolve_for_new_script(
        speaker_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
    )
    assert registry.lifecycle(speaker_id) is AnonymousLifecycleState.PROMOTED
    assert resolution.kind is AnonymousResolutionKind.CHARACTER
    assert resolution.character_id == CHARACTER_1
    assert resolution.anonymous_speaker_id is None
    assert registry.historical_identity(speaker_id) == seed.identity  # type: ignore[union-attr]
    assert registry.historical_script_snapshot((speaker_id,)) == (seed.identity,)  # type: ignore[union-attr]


def test_promotion_requires_owner_same_novel_character_and_unambiguous_identity() -> None:
    authority = _authority()
    seed = _seed(authority, "升级候选")
    speaker_id = seed.identity.anonymous_speaker_id  # type: ignore[union-attr]
    registered = _register(seed, 0, "promotion-seed")
    system = PromoteAnonymousSpeaker(
        header=_header(1, "system-promotion", actor=AnonymousOperationActor.SYSTEM),
        anonymous_speaker_id=speaker_id,
        character_id=CHARACTER_1,
    )
    with pytest.raises(AnonymousSpeakerError, match="owner authority"):
        replay_anonymous_operations(authority, (registered, system))

    unauthorized = replace(
        system,
        header=_header(1, "unauthorized-promotion"),
        character_id=CHARACTER_2,
    )
    with pytest.raises(AnonymousSpeakerError, match="same-novel authority"):
        replay_anonymous_operations(authority, (registered, unauthorized))

    split_authority, parent, _, _, split = _split_fixture()
    parent_id = parent.identity.anonymous_speaker_id  # type: ignore[union-attr]
    promote_split_parent = PromoteAnonymousSpeaker(
        header=_header(2, "promote-split-parent"),
        anonymous_speaker_id=parent_id,
        character_id=CHARACTER_1,
    )
    with pytest.raises(AnonymousIdentityConflictError, match="active unambiguous"):
        replay_anonymous_operations(
            split_authority,
            (
                _register(parent, 0, "split-parent"),
                split,
                promote_split_parent,
            ),
        )


def test_merge_chain_followed_by_promotion_has_one_future_resolution() -> None:
    authority = _authority()
    first = _seed(authority, "别名甲", evidence="first")
    second = _seed(authority, "别名乙", evidence="second")
    third = _seed(authority, "正式前称呼", evidence="third")
    first_id = first.identity.anonymous_speaker_id  # type: ignore[union-attr]
    second_id = second.identity.anonymous_speaker_id  # type: ignore[union-attr]
    third_id = third.identity.anonymous_speaker_id  # type: ignore[union-attr]
    registry = replay_anonymous_operations(
        authority,
        (
            _register(first, 0, "chain-first"),
            _register(second, 1, "chain-second"),
            _register(third, 2, "chain-third"),
            MergeAnonymousSpeakers(_header(3, "chain-merge-1"), (first_id,), second_id),
            MergeAnonymousSpeakers(_header(4, "chain-merge-2"), (second_id,), third_id),
            PromoteAnonymousSpeaker(_header(5, "chain-promotion"), third_id, CHARACTER_1),
        ),
    )

    assert registry.resolve_for_new_script(
        first_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
    ).character_id == CHARACTER_1
    assert registry.resolve_for_new_script(
        second_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
    ).character_id == CHARACTER_1
    assert registry.resolve_for_new_script(
        third_id,
        usage_scope_kind=AnonymousScopeKind.SCENE,
        usage_scope_id=SCENE_1,
    ).character_id == CHARACTER_1
    assert registry.historical_identity(first_id) == first.identity  # type: ignore[union-attr]


def test_operation_wire_round_trip_is_json_safe_and_replay_identical() -> None:
    authority, parent, child_a, child_b, split = _split_fixture()
    operations = (
        _register(parent, 0, "split-parent"),
        split,
        PromoteAnonymousSpeaker(
            header=_header(2, "child-promotion"),
            anonymous_speaker_id=child_a.identity.anonymous_speaker_id,  # type: ignore[union-attr]
            character_id=CHARACTER_1,
        ),
    )
    payloads = [anonymous_operation_to_dict(value) for value in operations]
    json.dumps(payloads, ensure_ascii=False)
    loaded = tuple(anonymous_operation_from_dict(value) for value in payloads)

    assert loaded == operations
    assert replay_anonymous_operations(authority, loaded) == replay_anonymous_operations(
        authority,
        operations,
    )


def test_merge_operation_wire_round_trip_is_json_safe_and_replay_identical() -> None:
    authority = _authority()
    source = _seed(authority, "wire-merge-source", evidence="wire-source")
    target = _seed(authority, "wire-merge-target", evidence="wire-target")
    source_id = source.identity.anonymous_speaker_id  # type: ignore[union-attr]
    target_id = target.identity.anonymous_speaker_id  # type: ignore[union-attr]
    operations = (
        _register(source, 0, "wire-merge-source"),
        _register(target, 1, "wire-merge-target"),
        MergeAnonymousSpeakers(
            header=_header(2, "wire-merge"),
            source_ids=(source_id,),
            target_id=target_id,
        ),
    )
    payloads = [anonymous_operation_to_dict(value) for value in operations]
    json.dumps(payloads, ensure_ascii=False)
    loaded = tuple(anonymous_operation_from_dict(value) for value in payloads)

    assert loaded == operations
    assert replay_anonymous_operations(authority, loaded) == replay_anonymous_operations(
        authority,
        operations,
    )


def test_operation_reverse_loader_rejects_unknown_version_kind_extra_and_time() -> None:
    operation = _register(_seed(_authority(), "wire"), 0, "wire", system=True)
    payload = anonymous_operation_to_dict(operation)

    unknown_version = deepcopy(payload)
    unknown_version["header"]["schema_version"] = "anonymous-speaker-operation/2"  # type: ignore[index]
    with pytest.raises(AnonymousSpeakerError, match="schema version"):
        anonymous_operation_from_dict(unknown_version)

    unknown_kind = deepcopy(payload)
    unknown_kind["kind"] = "rename"
    with pytest.raises(AnonymousSpeakerError, match="unknown anonymous operation kind"):
        anonymous_operation_from_dict(unknown_kind)

    extra = deepcopy(payload)
    extra["unexpected"] = True
    with pytest.raises(AnonymousSpeakerError, match="invalid keys"):
        anonymous_operation_from_dict(extra)

    noncanonical_time = deepcopy(payload)
    noncanonical_time["header"]["recorded_at"] = "2026-08-26T12:00:00Z"  # type: ignore[index]
    with pytest.raises(AnonymousSpeakerError, match="canonical microsecond"):
        anonymous_operation_from_dict(noncanonical_time)


def test_operation_wire_rejects_tampered_seed_scope_and_stable_key() -> None:
    operation = _register(_seed(_authority(), "篡改测试"), 0, "tamper", system=True)
    payload = anonymous_operation_to_dict(operation)

    bad_scope = deepcopy(payload)
    bad_scope["seed"]["scope_id"] = str(SCENE_3)  # type: ignore[index]
    with pytest.raises(AnonymousSpeakerError, match="stable_key differs"):
        anonymous_operation_from_dict(bad_scope)

    bad_key = deepcopy(payload)
    bad_key["seed"]["stable_key"] = "as1_" + "0" * 64  # type: ignore[index]
    with pytest.raises(AnonymousSpeakerError, match="stable_key differs"):
        anonymous_operation_from_dict(bad_key)


def test_operation_version_constant_and_wire_header_are_frozen() -> None:
    operation = _register(_seed(_authority(), "版本"), 0, "version-wire", system=True)
    payload = anonymous_operation_to_dict(operation)

    assert ANONYMOUS_OPERATION_VERSION == "anonymous-speaker-operation/1"
    assert payload["header"]["schema_version"] == ANONYMOUS_OPERATION_VERSION  # type: ignore[index]
    assert payload["header"]["recorded_at"] == "2026-08-26T12:00:00.000000Z"  # type: ignore[index]
