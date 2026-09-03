from __future__ import annotations

from dataclasses import fields, replace
import hashlib
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from backend.narration import schemas as wire
from backend.narration.casting import (
    AnonymousBindingSnapshot,
    CastingAttributes,
    CastingInputError,
    CastingInventory,
    CastingRequest,
    CastingResolutionSource,
    CastingRuleAction,
    CastingRuleSnapshot,
    CastingScopeKind,
    CharacterBindingSnapshot,
    GenericPoolSnapshot,
    GenericSlotSnapshot,
    NarratorSelectionSnapshot,
    VoiceVersionSnapshot,
    resolve_casting,
)
from backend.narration.script_contracts import (
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetRef,
    CastingTargetKind,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
)


def uid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://example.invalid/t3-f/{label}")


NOVEL_ID = uid("novel")
OTHER_NOVEL_ID = uid("other-novel")
VOLUME_ID = uid("volume")
CHAPTER_ID = uid("chapter")
SCENE_ID = uid("scene")
CHARACTER_ID = uid("character")
ANONYMOUS_ID = uid("anonymous")
POOL_ID = uid("pool")
SOURCE_HASH = hashlib.sha256(b"source").hexdigest()


def voice(
    label: str,
    *,
    novel_id: UUID | None = NOVEL_ID,
    profile_status: wire.VoiceProfileStatus = wire.VoiceProfileStatus.ACTIVE,
    version_state: wire.VoiceVersionState = wire.VoiceVersionState.LOCKED,
    quality_state: wire.VoiceQualityState = wire.VoiceQualityState.ACCEPTED,
    rights_state: wire.VoiceRightsState | None = wire.VoiceRightsState.ACTIVE,
    rights_record: bool = True,
    source_type: wire.VoiceSourceType = wire.VoiceSourceType.PRESET,
    cloning: bool = True,
    activation_evidence_usable: bool | None = None,
) -> VoiceVersionSnapshot:
    if activation_evidence_usable is None:
        activation_evidence_usable = (
            version_state is wire.VoiceVersionState.LOCKED
            and quality_state is wire.VoiceQualityState.ACCEPTED
        )
    return VoiceVersionSnapshot(
        profile_id=uid(f"profile-{label}"),
        version_id=uid(f"version-{label}"),
        version_number=1,
        fingerprint=hashlib.sha256(f"voice:{label}".encode()).hexdigest(),
        profile_novel_id=novel_id,
        profile_status=profile_status,
        source_type=source_type,
        version_state=version_state,
        quality_state=quality_state,
        activation_evidence_usable=activation_evidence_usable,
        rights_record_id=uid(f"rights-{label}") if rights_record else None,
        rights_state=rights_state,
        voice_cloning_permitted=cloning,
    )


def condition(
    *,
    speaker: wire.CastingSpeakerKind = wire.CastingSpeakerKind.CHARACTER,
    genders: list[wire.CastingGender] | None = None,
    ages: list[wire.CastingAgeBand] | None = None,
    contexts: list[wire.CastingContextKind] | None = None,
    tags: list[str] | None = None,
) -> wire.VoiceCastingCondition:
    return wire.VoiceCastingCondition(
        speaker_kinds=[speaker],
        genders=genders or [],
        age_bands=ages or [],
        context_kinds=contexts or [],
        role_tags=tags or [],
    )


def generic_slot(
    index: int,
    *,
    pool_id: UUID = POOL_ID,
    genders: tuple[wire.CastingGender, ...] = (),
    ages: tuple[wire.CastingAgeBand, ...] = (),
    contexts: tuple[wire.CastingContextKind, ...] = (),
    tags: frozenset[str] = frozenset(),
    neutral: bool = True,
    slot_voice: VoiceVersionSnapshot | None = None,
) -> GenericSlotSnapshot:
    return GenericSlotSnapshot(
        pool_id=pool_id,
        slot_id=uid(f"slot-{index}"),
        slot_key=f"slot_{index:02d}",
        position=index,
        enabled=True,
        state=wire.GenericVoiceSlotState.READY,
        rights_approved=True,
        quality_approved=True,
        production_ready=True,
        voice=slot_voice or voice(f"slot-{index}"),
        speaker_kinds=(
            wire.CastingSpeakerKind.CHARACTER,
            wire.CastingSpeakerKind.ANONYMOUS,
            wire.CastingSpeakerKind.GROUP,
        ),
        genders=genders,
        age_bands=ages,
        context_kinds=contexts,
        role_tags=tags,
        neutral_fallback=neutral,
    )


def ready_pool(
    *,
    slots: tuple[GenericSlotSnapshot, ...] | None = None,
    novel_id: UUID = NOVEL_ID,
    pool_id: UUID = POOL_ID,
    version: int = 7,
) -> GenericPoolSnapshot:
    selected = slots or tuple(
        generic_slot(index, pool_id=pool_id) for index in range(24)
    )
    return GenericPoolSnapshot(
        novel_id=novel_id,
        pool_id=pool_id,
        version=version,
        state=wire.GenericVoicePoolState.READY,
        ready_slot_count=24,
        rights_approved_slot_count=24,
        quality_approved_slot_count=24,
        production_ready_slot_count=24,
        slots=selected,
    )


def missing_pool() -> GenericPoolSnapshot:
    return GenericPoolSnapshot(
        novel_id=NOVEL_ID,
        pool_id=None,
        version=0,
        state=wire.GenericVoicePoolState.MISSING,
        ready_slot_count=0,
        rights_approved_slot_count=0,
        quality_approved_slot_count=0,
        production_ready_slot_count=0,
        slots=(),
    )


def request(
    *,
    speaker: SpeakerRef | None = None,
    segment: str = "segment",
    kind: SegmentKind = SegmentKind.DIALOGUE,
    attributes: CastingAttributes | None = None,
    deduplicate: bool = True,
    used_voices: frozenset[UUID] = frozenset(),
    used_slots: frozenset[UUID] = frozenset(),
) -> CastingRequest:
    return CastingRequest(
        novel_id=NOVEL_ID,
        segment_id=uid(segment),
        source_local_hash=SOURCE_HASH,
        segment_kind=kind,
        speaker=speaker
        or SpeakerRef(kind=SpeakerKind.CHARACTER, character_id=CHARACTER_ID),
        chapter_id=CHAPTER_ID,
        volume_id=VOLUME_ID,
        scene_id=SCENE_ID,
        attributes=attributes
        or CastingAttributes(
            gender=wire.CastingGender.FEMALE,
            age_band=wire.CastingAgeBand.YOUNG_ADULT,
            context_kind=wire.CastingContextKind.DIALOGUE,
            role_tags=frozenset({"路人"}),
        ),
        same_scene_voice_deduplication=deduplicate,
        used_voice_version_ids=used_voices,
        used_slot_ids=used_slots,
    )


def narrator_selection(
    scope: CastingScopeKind,
    scope_id: UUID,
    label: str,
    *,
    selected_voice: VoiceVersionSnapshot | None = None,
) -> NarratorSelectionSnapshot:
    current = selected_voice or voice(label)
    return NarratorSelectionSnapshot(
        novel_id=NOVEL_ID,
        scope_kind=scope,
        scope_id=scope_id,
        profile_id=current.profile_id,
        version_id=current.version_id,
        voice=current,
    )


def binding(
    *,
    policy: wire.CharacterVoiceBindingPolicy = wire.CharacterVoiceBindingPolicy.DEDICATED,
    selected_voice: VoiceVersionSnapshot | None = None,
    include_snapshot: bool = True,
) -> CharacterBindingSnapshot:
    current = selected_voice or voice("character")
    return CharacterBindingSnapshot(
        novel_id=NOVEL_ID,
        binding_id=uid("binding"),
        character_id=CHARACTER_ID,
        policy=policy,
        profile_id=current.profile_id,
        version_id=current.version_id,
        voice=current if include_snapshot else None,
    )


def automatic_rule(
    *,
    speaker: wire.CastingSpeakerKind = wire.CastingSpeakerKind.CHARACTER,
    priority: int = -100,
    pool_id: UUID = POOL_ID,
    label: str = "automatic",
) -> CastingRuleSnapshot:
    return CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid(f"rule-{label}"),
        version=3,
        priority=priority,
        enabled=True,
        condition=condition(speaker=speaker),
        action=CastingRuleAction.AUTOMATIC_POOL,
        pool_id=pool_id,
    )


def test_narrator_scope_priority_is_chapter_then_volume_then_novel() -> None:
    chapter = narrator_selection(CastingScopeKind.CHAPTER, CHAPTER_ID, "chapter")
    volume = narrator_selection(CastingScopeKind.VOLUME, VOLUME_ID, "volume")
    novel = narrator_selection(CastingScopeKind.NOVEL, NOVEL_ID, "novel")
    result = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
            kind=SegmentKind.NARRATION,
        ),
        CastingInventory(narrator_selections=(novel, volume, chapter)),
    )

    assert result.source is CastingResolutionSource.CHAPTER_NARRATOR
    assert result.decision.origin is CastingDecisionOrigin.NARRATOR_SETTING
    assert result.decision.final_target is not None
    assert result.decision.final_target.profile_id == chapter.profile_id
    assert result.resolved_voice is not None
    assert result.resolved_voice.version_id == chapter.version_id


def test_narrator_inherits_volume_then_novel_when_narrower_scope_is_absent() -> None:
    volume = narrator_selection(CastingScopeKind.VOLUME, VOLUME_ID, "volume")
    novel = narrator_selection(CastingScopeKind.NOVEL, NOVEL_ID, "novel")
    narrator_request = request(
        speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
        kind=SegmentKind.NARRATION,
    )

    volume_result = resolve_casting(
        narrator_request,
        CastingInventory(narrator_selections=(novel, volume)),
    )
    novel_result = resolve_casting(
        narrator_request,
        CastingInventory(narrator_selections=(novel,)),
    )

    assert volume_result.source is CastingResolutionSource.VOLUME_NARRATOR
    assert novel_result.source is CastingResolutionSource.NOVEL_NARRATOR


def test_direct_official_voice_uses_activation_evidence_without_fake_quality_acceptance() -> None:
    direct_official = voice(
        "official-direct",
        quality_state=wire.VoiceQualityState.PENDING,
        activation_evidence_usable=True,
    )
    selected = narrator_selection(
        CastingScopeKind.NOVEL,
        NOVEL_ID,
        "official-direct",
        selected_voice=direct_official,
    )

    result = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
            kind=SegmentKind.NARRATION,
        ),
        CastingInventory(narrator_selections=(selected,)),
    )

    assert result.decision.origin is CastingDecisionOrigin.NARRATOR_SETTING
    assert result.blocker_codes == ()
    assert result.resolved_voice is not None
    assert result.resolved_voice.version_id == direct_official.version_id


def test_unusable_chapter_narrator_blocks_without_silent_volume_fallback() -> None:
    unavailable = voice(
        "bad-chapter", version_state=wire.VoiceVersionState.UNAVAILABLE
    )
    chapter = narrator_selection(
        CastingScopeKind.CHAPTER,
        CHAPTER_ID,
        "unused",
        selected_voice=unavailable,
    )
    volume = narrator_selection(CastingScopeKind.VOLUME, VOLUME_ID, "volume")

    result = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
            kind=SegmentKind.NARRATION,
        ),
        CastingInventory(narrator_selections=(volume, chapter)),
    )

    assert result.decision.origin is CastingDecisionOrigin.UNRESOLVED
    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_VERSION_UNAVAILABLE",
    }
    assert result.decision.candidate_targets[0].profile_id == chapter.profile_id


def test_missing_narrator_has_voice_missing_and_unresolved_blockers() -> None:
    result = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
            kind=SegmentKind.NARRATION,
        ),
        CastingInventory(),
    )

    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_MISSING",
    }


def test_explicit_work_rule_precedes_character_dedicated_binding() -> None:
    rule_voice = voice("rule")
    rule = CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid("rule-explicit"),
        version=4,
        priority=100,
        enabled=True,
        condition=condition(tags=["路人"]),
        action=CastingRuleAction.VOICE_VERSION,
        profile_id=rule_voice.profile_id,
        version_id=rule_voice.version_id,
        voice=rule_voice,
    )

    result = resolve_casting(
        request(), CastingInventory(character_bindings=(binding(),), rules=(rule,))
    )

    assert result.source is CastingResolutionSource.EXPLICIT_RULE
    assert result.decision.origin is CastingDecisionOrigin.CASTING_RULE
    assert result.resolved_voice is not None
    assert result.resolved_voice.version_id == rule_voice.version_id
    assert result.rule_authority is not None
    assert result.rule_authority.decision == result.decision
    assert result.rule_authority.speaker_target_hash == speaker_target_hash(
        result.speaker, result.decision
    )


def test_higher_priority_matching_explicit_rule_wins_deterministically() -> None:
    low_voice = voice("low-rule")
    high_voice = voice("high-rule")
    low = CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid("rule-low"),
        version=1,
        priority=1,
        enabled=True,
        condition=condition(),
        action=CastingRuleAction.VOICE_VERSION,
        profile_id=low_voice.profile_id,
        version_id=low_voice.version_id,
        voice=low_voice,
    )
    high = replace(
        low,
        rule_id=uid("rule-high"),
        version=9,
        priority=10,
        profile_id=high_voice.profile_id,
        version_id=high_voice.version_id,
        voice=high_voice,
    )

    result = resolve_casting(request(), CastingInventory(rules=(low, high)))

    assert result.resolved_voice is not None
    assert result.resolved_voice.version_id == high_voice.version_id
    assert result.decision.rule_id == high.rule_id
    assert result.decision.rule_version == 9


def test_require_review_rule_stops_lower_binding_and_pool() -> None:
    rule = CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid("rule-review"),
        version=1,
        priority=10,
        enabled=True,
        condition=condition(),
        action=CastingRuleAction.REQUIRE_REVIEW,
    )

    result = resolve_casting(
        request(),
        CastingInventory(
            character_bindings=(binding(),),
            rules=(rule, automatic_rule()),
            generic_pool=ready_pool(),
        ),
    )

    assert result.decision.origin is CastingDecisionOrigin.UNRESOLVED
    assert result.blocker_codes == ("B_CASTING_TARGET_UNRESOLVED",)
    assert result.rule_authority is None


def test_character_dedicated_binding_has_exact_binding_character_relation() -> None:
    selected = binding()
    result = resolve_casting(
        request(),
        CastingInventory(
            character_bindings=(selected,),
            rules=(automatic_rule(),),
            generic_pool=ready_pool(),
        ),
    )

    assert result.source is CastingResolutionSource.CHARACTER_DEDICATED
    assert result.decision.origin is CastingDecisionOrigin.CHARACTER_BINDING
    assert result.decision.final_target is not None
    assert result.decision.final_target.kind is CastingTargetKind.CHARACTER_BINDING
    assert result.decision.final_target.binding_id == selected.binding_id
    assert result.decision.final_target.character_id == CHARACTER_ID
    assert result.warning_codes == ()


def test_character_inherited_binding_is_explicit_and_precedes_generic() -> None:
    inherited = binding(policy=wire.CharacterVoiceBindingPolicy.INHERITED)
    result = resolve_casting(
        request(),
        CastingInventory(
            character_bindings=(inherited,),
            rules=(automatic_rule(),),
            generic_pool=ready_pool(),
        ),
    )

    assert result.source is CastingResolutionSource.CHARACTER_INHERITED
    assert result.warning_codes == ()


def test_missing_character_binding_version_blocks_instead_of_using_pool() -> None:
    missing = binding(include_snapshot=False)
    result = resolve_casting(
        request(),
        CastingInventory(
            character_bindings=(missing,),
            rules=(automatic_rule(),),
            generic_pool=ready_pool(),
        ),
    )

    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_VERSION_UNAVAILABLE",
    }
    assert result.decision.candidate_targets[0].binding_id == missing.binding_id


@pytest.mark.parametrize(
    ("selected_voice", "expected"),
    [
        (
            voice("wrong-scope", novel_id=OTHER_NOVEL_ID),
            {"B_CASTING_TARGET_UNRESOLVED", "B_VOICE_VERSION_UNAVAILABLE"},
        ),
        (
            voice("revoked", rights_state=wire.VoiceRightsState.REVOKED),
            {"B_CASTING_TARGET_UNRESOLVED", "B_VOICE_RIGHTS_UNAVAILABLE"},
        ),
        (
            voice(
                "both-bad",
                version_state=wire.VoiceVersionState.UNAVAILABLE,
                rights_state=wire.VoiceRightsState.REVIEW_BLOCKED,
            ),
            {
                "B_CASTING_TARGET_UNRESOLVED",
                "B_VOICE_VERSION_UNAVAILABLE",
                "B_VOICE_RIGHTS_UNAVAILABLE",
            },
        ),
        (
            voice(
                "upload-no-clone",
                source_type=wire.VoiceSourceType.UPLOADED,
                cloning=False,
            ),
            {"B_CASTING_TARGET_UNRESOLVED", "B_VOICE_RIGHTS_UNAVAILABLE"},
        ),
    ],
)
def test_version_scope_and_rights_failures_use_distinct_frozen_blockers(
    selected_voice: VoiceVersionSnapshot, expected: set[str]
) -> None:
    result = resolve_casting(
        request(),
        CastingInventory(
            character_bindings=(binding(selected_voice=selected_voice),)
        ),
    )

    assert set(result.blocker_codes) == expected


def test_known_anonymous_binding_reuses_exact_identity_and_slot() -> None:
    anonymous_voice = voice("anonymous")
    slot = generic_slot(4, slot_voice=anonymous_voice)
    known = AnonymousBindingSnapshot(
        novel_id=NOVEL_ID,
        anonymous_speaker_id=ANONYMOUS_ID,
        profile_id=anonymous_voice.profile_id,
        version_id=anonymous_voice.version_id,
        voice=anonymous_voice,
        slot=slot,
        pool_version=7,
        pool_active=True,
    )
    anonymous_request = request(
        speaker=SpeakerRef(
            kind=SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=ANONYMOUS_ID,
        ),
        attributes=CastingAttributes(
            context_kind=wire.CastingContextKind.DIALOGUE,
            anonymous_stable_key="as1_" + "a" * 64,
        ),
    )

    result = resolve_casting(
        anonymous_request,
        CastingInventory(
            anonymous_bindings=(known,),
            rules=(
                automatic_rule(speaker=wire.CastingSpeakerKind.ANONYMOUS),
            ),
            generic_pool=ready_pool(),
        ),
    )

    assert result.source is CastingResolutionSource.ANONYMOUS_BINDING
    assert result.decision.origin is CastingDecisionOrigin.ANONYMOUS_BINDING
    assert result.decision.final_target is not None
    assert result.decision.final_target.anonymous_speaker_id == ANONYMOUS_ID
    assert result.resolved_voice is not None
    assert result.resolved_voice.slot_id == slot.slot_id
    assert result.resolved_voice.pool_version == 7
    assert result.warning_codes == ()

    inactive_result = resolve_casting(
        anonymous_request,
        CastingInventory(
            anonymous_bindings=(replace(known, pool_active=False),),
            rules=(
                automatic_rule(speaker=wire.CastingSpeakerKind.ANONYMOUS),
            ),
            generic_pool=ready_pool(),
        ),
    )
    assert set(inactive_result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_VERSION_UNAVAILABLE",
    }
    assert inactive_result.decision.candidate_targets[0].kind is CastingTargetKind.ANONYMOUS_BINDING


def test_anonymous_binding_rejects_inconsistent_slot_voice_or_missing_pool_version() -> None:
    first = voice("anonymous-first")
    second = voice("anonymous-second")
    slot = generic_slot(0, slot_voice=second)

    with pytest.raises(CastingInputError, match="slot/voice relation"):
        AnonymousBindingSnapshot(
            novel_id=NOVEL_ID,
            anonymous_speaker_id=ANONYMOUS_ID,
            profile_id=first.profile_id,
            version_id=first.version_id,
            voice=first,
            slot=slot,
            pool_version=1,
            pool_active=True,
        )
    with pytest.raises(CastingInputError, match="pool version"):
        AnonymousBindingSnapshot(
            novel_id=NOVEL_ID,
            anonymous_speaker_id=ANONYMOUS_ID,
            profile_id=second.profile_id,
            version_id=second.version_id,
            voice=second,
            slot=slot,
        )


def test_unusable_anonymous_binding_blocks_without_automatic_reassignment() -> None:
    revoked = voice("anonymous-revoked", rights_state=wire.VoiceRightsState.REVOKED)
    known = AnonymousBindingSnapshot(
        novel_id=NOVEL_ID,
        anonymous_speaker_id=ANONYMOUS_ID,
        profile_id=revoked.profile_id,
        version_id=revoked.version_id,
        voice=revoked,
    )
    anonymous_request = request(
        speaker=SpeakerRef(
            kind=SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=ANONYMOUS_ID,
        ),
        attributes=CastingAttributes(
            context_kind=wire.CastingContextKind.DIALOGUE,
            anonymous_stable_key="as1_" + "d" * 64,
        ),
    )

    result = resolve_casting(
        anonymous_request,
        CastingInventory(
            anonymous_bindings=(known,),
            rules=(
                automatic_rule(speaker=wire.CastingSpeakerKind.ANONYMOUS),
            ),
            generic_pool=ready_pool(),
        ),
    )

    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_RIGHTS_UNAVAILABLE",
    }
    assert result.decision.candidate_targets[0].kind is CastingTargetKind.ANONYMOUS_BINDING


def test_unknown_speaker_and_synthetic_pause_have_frozen_shapes() -> None:
    unknown = resolve_casting(
        request(speaker=SpeakerRef(kind=SpeakerKind.UNKNOWN)), CastingInventory()
    )
    pause = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.NARRATOR),
            kind=SegmentKind.SYNTHETIC_PAUSE,
        ),
        CastingInventory(),
    )

    assert set(unknown.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_SPEAKER_UNKNOWN",
    }
    assert pause.decision.origin is CastingDecisionOrigin.NOT_APPLICABLE
    assert pause.source is CastingResolutionSource.NOT_APPLICABLE
    assert pause.issues == ()


def test_explicit_unknown_can_use_a_server_authorized_generic_pool_rule() -> None:
    slots = tuple(
        replace(
            generic_slot(index),
            speaker_kinds=(),
            neutral_fallback=index == 0,
        )
        for index in range(24)
    )
    pool = ready_pool(slots=slots)
    generic_unknown = resolve_casting(
        request(
            speaker=SpeakerRef(kind=SpeakerKind.UNKNOWN),
            attributes=CastingAttributes(
                context_kind=wire.CastingContextKind.DIALOGUE,
            ),
        ),
        CastingInventory(
            rules=(
                automatic_rule(speaker=wire.CastingSpeakerKind.UNKNOWN),
            ),
            generic_pool=pool,
        ),
    )

    assert generic_unknown.source is CastingResolutionSource.GENERIC_RULE
    assert generic_unknown.blocker_codes == ()
    assert generic_unknown.resolved_voice is not None
    assert generic_unknown.resolved_voice.slot_id == slots[0].slot_id


def test_automatic_generic_casting_requires_complete_ready_24_slot_pool() -> None:
    result = resolve_casting(
        request(),
        CastingInventory(rules=(automatic_rule(),), generic_pool=missing_pool()),
    )

    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_MISSING",
    }
    with pytest.raises(CastingInputError, match="count|24-slot"):
        ready_pool(slots=tuple(generic_slot(index) for index in range(23)))


def test_ready_pool_rejects_aggregate_count_not_backed_by_exact_slots() -> None:
    slots = tuple(generic_slot(index) for index in range(24))
    with pytest.raises(CastingInputError, match="rights-approved count"):
        GenericPoolSnapshot(
            novel_id=NOVEL_ID,
            pool_id=POOL_ID,
            version=1,
            state=wire.GenericVoicePoolState.READY,
            ready_slot_count=24,
            rights_approved_slot_count=23,
            quality_approved_slot_count=24,
            production_ready_slot_count=24,
            slots=slots,
        )


def test_one_revoked_pool_voice_disables_all_automatic_generic_casting() -> None:
    slots = [generic_slot(index) for index in range(24)]
    revoked = voice("pool-revoked", rights_state=wire.VoiceRightsState.REVOKED)
    slots[5] = generic_slot(5, slot_voice=revoked)
    pool = ready_pool(slots=tuple(slots))

    result = resolve_casting(
        request(),
        CastingInventory(rules=(automatic_rule(),), generic_pool=pool),
    )

    assert set(result.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_RIGHTS_UNAVAILABLE",
    }
    assert result.resolved_voice is None


def test_generic_assignment_is_repeatable_and_binds_exact_rule_decision_evidence() -> None:
    pool = ready_pool()
    rule = automatic_rule()
    current_request = request(deduplicate=False)
    inventory = CastingInventory(rules=(rule,), generic_pool=pool)

    first = resolve_casting(current_request, inventory)
    second = resolve_casting(current_request, inventory)

    assert first == second
    assert first.source is CastingResolutionSource.GENERIC_RULE
    assert first.decision.origin is CastingDecisionOrigin.CASTING_RULE
    assert len(first.decision.candidate_targets) == 24
    assert first.decision.rule_id == rule.rule_id
    assert first.decision.rule_version == rule.version
    assert first.warning_codes == ("W_GENERIC_VOICE_FALLBACK",)
    assert first.rule_authority is not None
    assert first.rule_authority.segment_id == current_request.segment_id
    assert first.rule_authority.source_local_hash == SOURCE_HASH
    assert first.rule_authority.speaker_target_hash == speaker_target_hash(
        first.speaker, first.decision
    )
    with pytest.raises(CastingInputError, match="segment/source/speaker"):
        replace(
            first,
            rule_authority=replace(
                first.rule_authority,
                segment_id=uid("rebound-segment"),
            ),
        )


def test_same_scene_deduplication_selects_next_stable_voice_without_changing_candidates() -> None:
    pool = ready_pool()
    inventory = CastingInventory(rules=(automatic_rule(),), generic_pool=pool)
    baseline = resolve_casting(request(deduplicate=True), inventory)
    assert baseline.resolved_voice is not None
    assert baseline.resolved_voice.slot_id is not None

    deduplicated = resolve_casting(
        request(
            deduplicate=True,
            used_voices=frozenset({baseline.resolved_voice.version_id}),
            used_slots=frozenset({baseline.resolved_voice.slot_id}),
        ),
        inventory,
    )

    assert deduplicated.resolved_voice is not None
    assert deduplicated.resolved_voice.version_id != baseline.resolved_voice.version_id
    assert deduplicated.decision.candidate_targets == baseline.decision.candidate_targets


def test_same_scene_deduplication_exhaustion_blocks_instead_of_reusing() -> None:
    pool = ready_pool()
    result = resolve_casting(
        request(
            used_voices=frozenset(
                slot.voice.version_id for slot in pool.slots if slot.voice is not None
            )
        ),
        CastingInventory(rules=(automatic_rule(),), generic_pool=pool),
    )

    assert result.blocker_codes == ("B_CASTING_TARGET_UNRESOLVED",)
    assert result.resolved_voice is None
    assert len(result.decision.candidate_targets) == 24


def test_generic_matching_uses_description_then_demographics_then_neutral() -> None:
    slots: list[GenericSlotSnapshot] = []
    for index in range(24):
        if index == 0:
            slots.append(
                generic_slot(
                    index,
                    tags=frozenset({"侍卫"}),
                    genders=(wire.CastingGender.MALE,),
                    neutral=False,
                )
            )
        elif index == 1:
            slots.append(
                generic_slot(
                    index,
                    genders=(wire.CastingGender.FEMALE,),
                    ages=(wire.CastingAgeBand.YOUNG_ADULT,),
                    neutral=False,
                )
            )
        elif index == 2:
            slots.append(generic_slot(index, neutral=True))
        else:
            slots.append(
                generic_slot(
                    index,
                    genders=(wire.CastingGender.MALE,),
                    neutral=False,
                )
            )
    pool = ready_pool(slots=tuple(slots))
    inventory = CastingInventory(rules=(automatic_rule(),), generic_pool=pool)

    described = resolve_casting(
        request(
            attributes=CastingAttributes(
                gender=wire.CastingGender.MALE,
                age_band=wire.CastingAgeBand.UNKNOWN,
                context_kind=wire.CastingContextKind.DIALOGUE,
                role_tags=frozenset({"侍卫"}),
            )
        ),
        inventory,
    )
    demographic = resolve_casting(request(), inventory)
    neutral = resolve_casting(
        request(
            attributes=CastingAttributes(
                gender=wire.CastingGender.UNKNOWN,
                age_band=wire.CastingAgeBand.UNKNOWN,
                context_kind=wire.CastingContextKind.DIALOGUE,
            )
        ),
        inventory,
    )

    assert described.resolved_voice is not None
    assert described.resolved_voice.slot_id == slots[0].slot_id
    assert demographic.resolved_voice is not None
    assert demographic.resolved_voice.slot_id == slots[1].slot_id
    assert neutral.resolved_voice is not None
    assert neutral.resolved_voice.slot_id == slots[2].slot_id


def test_group_and_anonymous_automatic_assignments_use_stable_identity() -> None:
    pool = ready_pool()
    group_rule = automatic_rule(
        speaker=wire.CastingSpeakerKind.GROUP, label="group"
    )
    anonymous_rule = automatic_rule(
        speaker=wire.CastingSpeakerKind.ANONYMOUS,
        priority=-101,
        label="anonymous",
    )
    inventory = CastingInventory(
        rules=(group_rule, anonymous_rule), generic_pool=pool
    )
    group_request = request(
        speaker=SpeakerRef(kind=SpeakerKind.GROUP, group_key="grp1_" + "b" * 64),
        attributes=CastingAttributes(
            context_kind=wire.CastingContextKind.GROUP,
        ),
    )
    anonymous_request = request(
        speaker=SpeakerRef(
            kind=SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=ANONYMOUS_ID,
        ),
        attributes=CastingAttributes(
            context_kind=wire.CastingContextKind.DIALOGUE,
            anonymous_stable_key="as1_" + "c" * 64,
        ),
    )

    assert resolve_casting(group_request, inventory).resolved_voice is not None
    assert resolve_casting(anonymous_request, inventory).resolved_voice is not None


def test_anonymous_automatic_casting_refuses_to_invent_t3_e_stable_identity() -> None:
    anonymous_request = request(
        speaker=SpeakerRef(
            kind=SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=ANONYMOUS_ID,
        ),
        attributes=CastingAttributes(
            context_kind=wire.CastingContextKind.DIALOGUE,
        ),
    )

    with pytest.raises(CastingInputError, match="T3-E stable key"):
        resolve_casting(
            anonymous_request,
            CastingInventory(
                rules=(
                    automatic_rule(speaker=wire.CastingSpeakerKind.ANONYMOUS),
                ),
                generic_pool=ready_pool(),
            ),
        )


def test_generic_slot_rule_requires_exact_pool_slot_relation_and_ready_pack() -> None:
    pool = ready_pool()
    slot = pool.slots[3]
    rule = CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid("rule-slot"),
        version=2,
        priority=30,
        enabled=True,
        condition=condition(),
        action=CastingRuleAction.GENERIC_SLOT,
        pool_id=pool.pool_id,
        slot_id=slot.slot_id,
    )
    success = resolve_casting(
        request(deduplicate=False),
        CastingInventory(rules=(rule,), generic_pool=pool),
    )
    wrong_pool_rule = replace(rule, rule_id=uid("rule-wrong-pool"), pool_id=uid("wrong-pool"))
    blocked = resolve_casting(
        request(deduplicate=False),
        CastingInventory(rules=(wrong_pool_rule,), generic_pool=pool),
    )

    assert success.decision.final_target is not None
    assert success.decision.final_target.pool_id == pool.pool_id
    assert success.decision.final_target.slot_id == slot.slot_id
    assert success.resolved_voice is not None
    assert success.resolved_voice.slot_id == slot.slot_id
    assert set(blocked.blocker_codes) == {
        "B_CASTING_TARGET_UNRESOLVED",
        "B_VOICE_MISSING",
    }
    assert blocked.decision.candidate_targets[0].pool_id == uid("wrong-pool")


def test_generic_slot_rule_deduplication_blocks_without_falling_to_binding() -> None:
    pool = ready_pool()
    slot = pool.slots[0]
    assert slot.voice is not None
    rule = CastingRuleSnapshot(
        novel_id=NOVEL_ID,
        rule_id=uid("rule-dedup-slot"),
        version=1,
        priority=20,
        enabled=True,
        condition=condition(),
        action=CastingRuleAction.GENERIC_SLOT,
        pool_id=pool.pool_id,
        slot_id=slot.slot_id,
    )

    result = resolve_casting(
        request(used_voices=frozenset({slot.voice.version_id})),
        CastingInventory(
            character_bindings=(binding(),), rules=(rule,), generic_pool=pool
        ),
    )

    assert result.blocker_codes == ("B_CASTING_TARGET_UNRESOLVED",)
    assert result.decision.candidate_targets[0].slot_id == slot.slot_id


def test_inventory_rejects_duplicate_bindings_rules_and_cross_novel_scope() -> None:
    duplicate_binding = binding()
    with pytest.raises(CastingInputError, match="duplicate identities"):
        CastingInventory(
            character_bindings=(duplicate_binding, duplicate_binding)
        )
    first_rule = automatic_rule(priority=1)
    second_rule = replace(
        first_rule,
        rule_id=uid("another-rule"),
        priority=1,
    )
    with pytest.raises(CastingInputError, match="duplicate priorities"):
        CastingInventory(rules=(first_rule, second_rule))

    foreign = replace(duplicate_binding, novel_id=OTHER_NOVEL_ID)
    with pytest.raises(CastingInputError, match="another novel"):
        resolve_casting(
            request(), CastingInventory(character_bindings=(foreign,))
        )


def test_exact_binding_and_rule_constructors_reject_mismatched_relations() -> None:
    first = voice("first")
    second = voice("second")
    with pytest.raises(CastingInputError, match="relation is inconsistent"):
        CharacterBindingSnapshot(
            novel_id=NOVEL_ID,
            binding_id=uid("bad-binding"),
            character_id=CHARACTER_ID,
            policy=wire.CharacterVoiceBindingPolicy.DEDICATED,
            profile_id=first.profile_id,
            version_id=first.version_id,
            voice=second,
        )
    with pytest.raises(CastingInputError, match="rule relation"):
        CastingRuleSnapshot(
            novel_id=NOVEL_ID,
            rule_id=uid("bad-rule"),
            version=1,
            priority=1,
            enabled=True,
            condition=condition(),
            action=CastingRuleAction.VOICE_VERSION,
            profile_id=first.profile_id,
            version_id=first.version_id,
            voice=second,
        )


def test_casting_issues_and_candidate_targets_are_t3_a_canonical() -> None:
    pool = ready_pool()
    result = resolve_casting(
        request(deduplicate=False),
        CastingInventory(rules=(automatic_rule(),), generic_pool=pool),
    )

    target_ids = [str(target.slot_id) for target in result.decision.candidate_targets]
    assert target_ids == sorted(target_ids)
    assert tuple(issue.code for issue in result.issues) == tuple(
        sorted(issue.code for issue in result.issues)
    )


def test_voice_version_evidence_is_transient_and_absent_from_t3_a_casting() -> None:
    result = resolve_casting(
        request(), CastingInventory(character_bindings=(binding(),))
    )

    assert "voice_version_id" not in {field.name for field in fields(CastingDecision)}
    assert "voice_version_id" not in {field.name for field in fields(CastingTargetRef)}
    assert result.resolved_voice is not None
    assert result.resolved_voice.version_id == binding().version_id
