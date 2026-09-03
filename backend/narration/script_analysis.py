"""T3-GATE orchestration for deterministic local narration-script analysis.

This module joins the already-frozen T3 segmentation, scene, speaker,
expression, casting, review, and typed-persistence components.  It deliberately
contains no model, network, media, Edition, or render work and does not
reimplement any of those components' decision rules.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from types import SimpleNamespace
import unicodedata
from uuid import UUID

from pydantic import ValidationError

from ..models import (
    AnonymousSpeaker,
    CharacterAlias,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    GenericVoicePackVersion,
    GenericVoicePackVersionSlot,
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationRequest,
    NarrationRequestSource,
    NarrationSettingsSnapshot,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
    NarrationScriptVersion,
)

from . import schemas as wire
from .aliases import (
    AliasSource,
    CharacterAliasRecord,
    build_character_alias_index,
    normalize_character_alias,
)
from .casting import (
    AnonymousBindingSnapshot,
    CastingAttributes,
    CastingInventory,
    CastingRequest,
    CastingRuleAction,
    CastingRuleSnapshot,
    CastingScopeKind,
    CharacterBindingSnapshot,
    GenericPoolSnapshot,
    GenericSlotSnapshot,
    NarratorSelectionSnapshot,
    VoiceVersionSnapshot,
    automatic_generic_casting_rule_id,
    resolve_casting,
)
from .anonymous_speakers import (
    AnonymousReuseBasis,
    AnonymousScopeAuthority,
    materialize_anonymous_identity,
)
from .contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    SPEAKER_CORRECTION_ISSUE_CODES,
    ConfidenceLevel,
    ReviewIssueSeverity,
)
from .confidence import (
    InheritanceAuditStamp,
    OverrideInheritanceAuthority,
    OverrideInheritanceTarget,
    decide_override_inheritance,
    manual_override_source,
    segment_anchor_uniqueness,
    segment_inheritance_anchors,
)
from .expression import (
    ExpressionContext,
    classify_expression,
)
from .requests import RequestSource, advance_request_state, source_set_hash
from .scenes import (
    build_scene_contracts,
    scene_ids_for_source_ranges,
)
from .script_contracts import (
    NARRATION_SCRIPT_CONTRACT_VERSION,
    AttributionEvidence,
    AttributionOrigin,
    AnonymousSpeakerIdentity,
    CastingDecisionOrigin,
    NarrationScriptContract,
    OverrideProvenance,
    ScriptIssueContract,
    ScriptReviewPolicy,
    ScriptVersionState,
    SegmentContract,
    SegmentKind,
    AnonymousScopeKind,
    SpeakerKind,
    SpeakerRef,
    derive_group_key,
    initial_materialized_state,
    script_immutable_payload,
)
from .script_versions import (
    SCRIPT_ANALYZER_FINGERPRINT,
    SCRIPT_ANALYZER_VERSION,
    SCRIPT_RULES_FINGERPRINT,
    ReserveScriptIdentity,
    ScriptVersionAllocation,
    freeze_script_version,
    load_script_contract,
    persist_script_contract,
    reserve_script_identity,
)
from .review_actions import (
    inherited_analysis_action_identity,
    persist_inherited_analysis_result,
)
from .segmentation import SourceFormat, segment_source
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    StaleNarrationInput,
    canonical_sha256,
    canonical_payload,
    require_local_novel,
    require_nonempty,
    require_row,
    require_same_novel,
    require_sha256,
    utc_now,
    voice_activation_evidence_is_usable,
)
from .snapshots import SETTINGS_SNAPSHOT_SCHEMA_VERSION
from .speaker_rules import (
    ResolvedSpeakerLabel,
    SpeakerRuleContext,
    attribute_speaker_local,
    build_resolved_speaker_index,
)
from .voice_pool import load_voice_pool_catalog
from .voices import _rights_state


_GENERIC_CASTING_EVIDENCE_VERSION = "generic-casting-evidence/1"


def _generic_slot_shape(
    *, slot_key: str, category: str
) -> tuple[
    tuple[wire.CastingSpeakerKind, ...],
    tuple[wire.CastingGender, ...],
    tuple[wire.CastingAgeBand, ...],
    tuple[wire.CastingContextKind, ...],
    bool,
]:
    """Derive casting metadata from the one frozen taxonomy category.

    Keeping this mechanical avoids introducing a second age/gender catalog.
    Unknown or malformed categories fail closed instead of guessing.
    """

    if category.startswith("female_"):
        genders = (wire.CastingGender.FEMALE,)
    elif category.startswith("male_"):
        genders = (wire.CastingGender.MALE,)
    elif category.startswith("neutral_"):
        genders = (wire.CastingGender.NEUTRAL,)
    else:
        raise InvalidNarrationState("generic voice category has an unknown gender")

    age_bands: tuple[wire.CastingAgeBand, ...]
    if category.endswith("_child"):
        age_bands = (wire.CastingAgeBand.CHILD,)
    elif category.endswith("_teen"):
        age_bands = (wire.CastingAgeBand.TEEN,)
    elif category.endswith("_young_adult"):
        age_bands = (wire.CastingAgeBand.YOUNG_ADULT,)
    elif category.endswith("_middle_aged"):
        age_bands = (wire.CastingAgeBand.MIDDLE_AGED,)
    elif category.endswith("_elderly"):
        age_bands = (wire.CastingAgeBand.ELDERLY,)
    elif category.endswith(("_announcer", "_group")):
        age_bands = ()
    else:
        raise InvalidNarrationState("generic voice category has an unknown age band")

    if category.endswith("_group"):
        speaker_kinds = (
            wire.CastingSpeakerKind.GROUP,
            wire.CastingSpeakerKind.UNKNOWN,
        )
        context_kinds = (wire.CastingContextKind.GROUP,)
    elif category.endswith("_announcer"):
        speaker_kinds = (
            wire.CastingSpeakerKind.CHARACTER,
            wire.CastingSpeakerKind.ANONYMOUS,
            wire.CastingSpeakerKind.UNKNOWN,
        )
        context_kinds = (wire.CastingContextKind.BROADCAST,)
    else:
        speaker_kinds = (
            wire.CastingSpeakerKind.CHARACTER,
            wire.CastingSpeakerKind.ANONYMOUS,
            wire.CastingSpeakerKind.UNKNOWN,
        )
        context_kinds = ()
    return (
        speaker_kinds,
        genders,
        age_bands,
        context_kinds,
        slot_key == "neutral_young",
    )


def _generic_pool_snapshot(
    store: NarrationStore, *, novel_id: UUID
) -> GenericPoolSnapshot | None:
    pools = store.find_all(
        GenericVoicePool,
        novel_id=novel_id,
        status="active",
        order_by=("version_number",),
    )
    if not pools:
        return None
    if len(pools) != 1:
        raise InvalidNarrationState("multiple active generic voice pools exist")
    pool = pools[0]
    if pool.language != "zh-CN" or pool.source_pack_version_id is None:
        return None
    pack = store.get(GenericVoicePackVersion, pool.source_pack_version_id)
    if (
        pack is None
        or pack.workspace_id != LOCAL_WORKSPACE_ID
        or pack.language != "zh-CN"
        or pack.state != "active"
        or pack.validated_slot_count != 24
    ):
        return None
    catalog = load_voice_pool_catalog()
    catalog_by_key = {item.slot_key: item for item in catalog.slots}
    pool_slots = store.find_all(
        GenericVoiceSlot,
        pool_id=pool.id,
        order_by=("position",),
    )
    pack_slots = store.find_all(
        GenericVoicePackVersionSlot,
        pack_version_id=pack.id,
        order_by=("position",),
    )
    if (
        len(pool_slots) != 24
        or len(pack_slots) != 24
        or [row.position for row in pool_slots] != list(range(24))
        or [row.position for row in pack_slots] != list(range(24))
        or {row.slot_key for row in pool_slots} != set(catalog_by_key)
        or {row.slot_key for row in pack_slots} != set(catalog_by_key)
    ):
        return None
    source_by_key = {row.slot_key: row for row in pack_slots}
    snapshots: list[GenericSlotSnapshot] = []
    for row in pool_slots:
        source = source_by_key[row.slot_key]
        if (
            not row.enabled
            or source.voice_version_id != row.voice_version_id
            or source.state not in {"validated", "reused"}
            or not source.rights_approved
            or not source.quality_approved
        ):
            return None
        version = require_row(
            store.get(VoiceProfileVersion, row.voice_version_id),
            label="generic voice version",
        )
        voice = _voice_snapshot(
            store,
            novel_id=novel_id,
            profile_id=version.profile_id,
            version_id=row.voice_version_id,
        )
        if voice is None or voice.blocker_codes(novel_id=novel_id):
            return None
        catalog_slot = catalog_by_key[row.slot_key]
        speaker_kinds, genders, ages, contexts, neutral = _generic_slot_shape(
            slot_key=row.slot_key,
            category=catalog_slot.category,
        )
        snapshots.append(
            GenericSlotSnapshot(
                pool_id=pool.id,
                slot_id=row.id,
                slot_key=row.slot_key,
                position=row.position,
                enabled=True,
                state=wire.GenericVoiceSlotState.READY,
                rights_approved=True,
                quality_approved=True,
                production_ready=True,
                voice=voice,
                speaker_kinds=speaker_kinds,
                genders=genders,
                age_bands=ages,
                context_kinds=contexts,
                neutral_fallback=neutral,
            )
        )
    return GenericPoolSnapshot(
        novel_id=novel_id,
        pool_id=pool.id,
        version=pool.version_number,
        state=wire.GenericVoicePoolState.READY,
        ready_slot_count=24,
        rights_approved_slot_count=24,
        quality_approved_slot_count=24,
        production_ready_slot_count=24,
        slots=tuple(snapshots),
    )


def _automatic_generic_rule(
    *, novel_id: UUID, pool: GenericPoolSnapshot
) -> CastingRuleSnapshot:
    assert pool.pool_id is not None
    return CastingRuleSnapshot(
        novel_id=novel_id,
        rule_id=automatic_generic_casting_rule_id(
            novel_id=novel_id,
            pool_id=pool.pool_id,
            pool_version=pool.version,
        ),
        version=1,
        priority=-10_000,
        enabled=True,
        condition=wire.VoiceCastingCondition(
            speaker_kinds=[
                wire.CastingSpeakerKind.CHARACTER,
                wire.CastingSpeakerKind.ANONYMOUS,
                wire.CastingSpeakerKind.GROUP,
            ],
            genders=[],
            age_bands=[],
            context_kinds=[],
            role_tags=[],
        ),
        action=CastingRuleAction.AUTOMATIC_POOL,
        pool_id=pool.pool_id,
    )


def _anonymous_identity(row: AnonymousSpeaker) -> AnonymousSpeakerIdentity:
    try:
        return AnonymousSpeakerIdentity(
            anonymous_speaker_id=row.id,
            stable_key_algorithm=row.stable_key_algorithm,
            stable_key=row.stable_key,
            display_name=row.display_name,
            scope_kind=AnonymousScopeKind(row.scope_kind),
            scope_id=row.scope_id,
            confidence=ConfidenceLevel(row.confidence),
        )
    except (TypeError, ValueError) as error:
        raise InvalidNarrationState(
            "anonymous speaker identity contains unknown persisted values"
        ) from error


def _explicit_casting_attributes(
    *,
    label: str | None,
    segment_kind: SegmentKind,
    speaker_kind: SpeakerKind,
    anonymous_stable_key: str | None = None,
) -> CastingAttributes:
    value = unicodedata.normalize("NFKC", label or "").casefold()
    female = any(
        marker in value
        for marker in ("女童", "女孩", "少女", "女人", "女子", "女性", "妇人", "老妇", "老妪", "老太太", "姑娘", "女声")
    )
    male = any(
        marker in value
        for marker in ("男童", "男孩", "少年", "男人", "男子", "男性", "老汉", "老翁", "男声")
    )
    if female == male:
        gender = (
            wire.CastingGender.NEUTRAL
            if "中性" in value and not female
            else wire.CastingGender.UNKNOWN
        )
    else:
        gender = wire.CastingGender.FEMALE if female else wire.CastingGender.MALE

    age_matches = [
        (wire.CastingAgeBand.CHILD, ("男童", "女童", "小男孩", "小女孩", "孩子")),
        (wire.CastingAgeBand.TEEN, ("少年", "少女")),
        (wire.CastingAgeBand.YOUNG_ADULT, ("青年", "年轻")),
        (wire.CastingAgeBand.MIDDLE_AGED, ("中年",)),
        (wire.CastingAgeBand.ELDERLY, ("老年", "老人", "老者", "老妇", "老妪", "老太太", "老汉", "老翁")),
    ]
    matched_ages = {
        age for age, markers in age_matches if any(marker in value for marker in markers)
    }
    age_band = (
        next(iter(matched_ages))
        if len(matched_ages) == 1
        else wire.CastingAgeBand.UNKNOWN
    )
    context_by_kind = {
        SegmentKind.DIALOGUE: wire.CastingContextKind.DIALOGUE,
        SegmentKind.INNER_MONOLOGUE: wire.CastingContextKind.INNER_MONOLOGUE,
        SegmentKind.LETTER: wire.CastingContextKind.LETTER,
        SegmentKind.PHONE: wire.CastingContextKind.TELEPHONE,
        SegmentKind.BROADCAST: wire.CastingContextKind.BROADCAST,
    }
    context_kind = (
        wire.CastingContextKind.GROUP
        if speaker_kind is SpeakerKind.GROUP
        else context_by_kind.get(segment_kind)
    )
    return CastingAttributes(
        gender=gender,
        age_band=age_band,
        context_kind=context_kind,
        anonymous_stable_key=anonymous_stable_key,
    )


@dataclass(frozen=True, slots=True)
class AnalyzeNarrationScript:
    """Server-scoped input for one document/revision analysis action."""

    request_id: UUID
    document_id: UUID
    revision_id: UUID
    content_hash: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _AnalysisContext:
    request: NarrationRequest
    document: Document
    revision: DocumentRevision
    settings: wire.NarrationSettingsValues


def _stored_request_sources(
    store: NarrationStore,
    request: NarrationRequest,
) -> tuple[RequestSource, ...]:
    return tuple(
        RequestSource(
            document_id=row.document_id,
            revision_id=row.revision_id,
            content_hash=row.content_hash,
            position=row.position,
        )
        for row in store.find_all(
            NarrationRequestSource,
            request_id=request.id,
            order_by=("position",),
            for_update=True,
        )
    )


def _snapshot_settings(
    store: NarrationStore,
    *,
    request: NarrationRequest,
) -> wire.NarrationSettingsValues:
    snapshot = require_row(
        store.find_one(
            NarrationSettingsSnapshot,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            fingerprint=request.settings_fingerprint,
        ),
        label="narration settings snapshot",
    )
    if (
        snapshot.novel_id != request.novel_id
        or snapshot.schema_version != SETTINGS_SNAPSHOT_SCHEMA_VERSION
        or snapshot.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION
        or canonical_sha256(snapshot.snapshot_json) != snapshot.fingerprint
    ):
        raise StaleNarrationInput("narration settings snapshot changed")
    payload = snapshot.snapshot_json
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "taxonomy_version",
        "novel_id",
        "settings_version",
        "resolved_settings",
    }:
        raise InvalidNarrationState("narration settings snapshot has an unknown shape")
    resolved = payload["resolved_settings"]
    if type(resolved) is not dict or set(resolved) != {
        "script_review_policy",
        "analysis_mode",
        "narrator_profile_id",
        "narrator_version_id",
        "settings",
        "scope_overrides",
    }:
        raise InvalidNarrationState("resolved narration settings have an unknown shape")
    if resolved["analysis_mode"] != wire.AnalysisMode.LOCAL_RULES_ONLY.value:
        raise InvalidNarrationState(
            "cloud-assisted script analysis remains HOLD at T3-GATE"
        )
    if resolved["scope_overrides"]:
        raise InvalidNarrationState(
            "volume/chapter narration overrides remain HOLD at T3-GATE"
        )
    stored = resolved["settings"]
    if type(stored) is not dict:
        raise InvalidNarrationState("narration settings payload must be an object")
    settings_payload = dict(stored)
    playback = settings_payload.get("playback")
    if type(playback) is not dict or set(playback) != {"playback_rate", "volume"}:
        raise InvalidNarrationState("narration playback snapshot is malformed")
    try:
        settings_payload["playback"] = {
            "playback_rate": float(playback["playback_rate"]),
            "volume": float(playback["volume"]),
        }
    except (TypeError, ValueError) as error:
        raise InvalidNarrationState(
            "narration playback snapshot is malformed"
        ) from error
    narrator_profile_id = resolved["narrator_profile_id"]
    narrator_version_id = resolved["narrator_version_id"]
    if (narrator_profile_id is None) != (narrator_version_id is None):
        raise InvalidNarrationState("narrator snapshot identity is incomplete")
    settings_payload.update(
        {
            "narrator": (
                None
                if narrator_profile_id is None
                else {
                    "profile_id": narrator_profile_id,
                    "version_id": narrator_version_id,
                }
            ),
            "script_review_policy": resolved["script_review_policy"],
            "analysis_mode": resolved["analysis_mode"],
        }
    )
    try:
        values = wire.NarrationSettingsValues.model_validate(settings_payload)
    except ValidationError as error:
        raise InvalidNarrationState(
            "narration settings snapshot violates the frozen wire contract"
        ) from error
    if values.script_review_policy.value != request.effective_policy:
        raise StaleNarrationInput("request review policy differs from settings snapshot")
    if (
        not values.text_rules.read_chapter_title
        or values.text_rules.read_author_notes
        or values.text_rules.read_section_breaks
        or values.text_rules.first_person_mode is not wire.FirstPersonVoiceMode.NARRATOR
        or values.text_rules.first_person_character_id is not None
        or values.text_rules.inner_monologue_mode
        is not wire.InnerMonologueVoiceMode.CHARACTER
        or values.casting.unknown_speaker_action
        is not wire.UnknownSpeakerAction.BLOCK
    ):
        raise InvalidNarrationState(
            "configured advanced narration text rules remain HOLD at T3-GATE"
        )
    return values


def _require_analysis_context(
    store: NarrationStore,
    command: AnalyzeNarrationScript,
) -> _AnalysisContext:
    if type(command) is not AnalyzeNarrationScript:
        raise NarrationServiceError("command must be AnalyzeNarrationScript")
    require_sha256(command.content_hash, field="content_hash")
    require_nonempty(command.idempotency_key, field="idempotency_key")
    request = require_row(
        store.get(NarrationRequest, command.request_id, for_update=True),
        label="narration request",
    )
    if (
        request.owner_id != LOCAL_OWNER_ID
        or request.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch("narration request is outside fixed local scope")
    require_local_novel(store, request.novel_id)
    document = require_row(
        store.get(Document, command.document_id, for_update=True),
        label="document",
    )
    require_same_novel(document.novel_id, request.novel_id, label="document")
    revision = require_row(
        store.get(DocumentRevision, command.revision_id), label="revision"
    )
    if (
        revision.document_id != document.id
        or revision.content_hash != command.content_hash
    ):
        raise StaleNarrationInput("analysis source differs from immutable revision")

    sources = _stored_request_sources(store, request)
    if (
        request.sources_sealed_at is None
        or request.source_count != len(sources)
        or request.source_set_hash != source_set_hash(sources)
    ):
        raise IdempotencyConflict("narration request source manifest changed")
    direct_match = (
        request.document_id == command.document_id
        and request.source_revision_id == command.revision_id
        and request.source_content_hash == command.content_hash
    )
    child_match = any(
        item.document_id == command.document_id
        and item.revision_id == command.revision_id
        and item.content_hash == command.content_hash
        for item in sources
    )
    if not (direct_match or child_match):
        raise NarrationScopeMismatch(
            "narration request does not authorize this immutable source"
        )
    if request.state not in {"created", "analyzing", "analyzed", "review_required"}:
        raise InvalidNarrationState("narration request is not analyzable")
    settings = _snapshot_settings(store, request=request)
    return _AnalysisContext(
        request=request,
        document=document,
        revision=revision,
        settings=settings,
    )


def _voice_snapshot(
    store: NarrationStore,
    *,
    novel_id: UUID,
    profile_id: UUID,
    version_id: UUID,
) -> VoiceVersionSnapshot | None:
    profile = store.get(VoiceProfile, profile_id)
    version = store.get(VoiceProfileVersion, version_id)
    if profile is None or version is None:
        return None
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or profile.novel_id not in {None, novel_id}
        or version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
        or version.profile_id != profile.id
    ):
        raise NarrationScopeMismatch("voice snapshot is outside fixed local scope")
    rights = store.get(VoiceRightsRecord, version.rights_record_id)
    rights_state = None
    voice_cloning_permitted = False
    activation_evidence_usable = False
    rights_record_id = version.rights_record_id
    if rights is not None:
        if (
            rights.owner_id != LOCAL_OWNER_ID
            or rights.workspace_id != LOCAL_WORKSPACE_ID
            or rights.novel_id not in {None, novel_id}
        ):
            raise NarrationScopeMismatch("voice rights are outside fixed local scope")
        rights_state = _rights_state(store, rights, at=utc_now())
        voice_cloning_permitted = bool(rights.voice_cloning)
        activation_evidence_usable = voice_activation_evidence_is_usable(
            version,
            rights,
        )
    try:
        return VoiceVersionSnapshot(
            profile_id=profile.id,
            version_id=version.id,
            version_number=version.version_number,
            fingerprint=version.fingerprint,
            profile_novel_id=profile.novel_id,
            profile_status=wire.VoiceProfileStatus(profile.status),
            source_type=wire.VoiceSourceType(version.source_type),
            version_state=wire.VoiceVersionState(version.state),
            quality_state=wire.VoiceQualityState(version.quality_state),
            activation_evidence_usable=activation_evidence_usable,
            rights_record_id=rights_record_id,
            rights_state=rights_state,
            voice_cloning_permitted=voice_cloning_permitted,
        )
    except ValueError as error:
        raise InvalidNarrationState("voice snapshot contains an unknown state") from error


def _casting_inventory(
    store: NarrationStore,
    *,
    novel_id: UUID,
    settings: wire.NarrationSettingsValues,
) -> CastingInventory:
    narrator_selections: tuple[NarratorSelectionSnapshot, ...] = ()
    if settings.narrator is not None:
        narrator_selections = (
            NarratorSelectionSnapshot(
                novel_id=novel_id,
                scope_kind=CastingScopeKind.NOVEL,
                scope_id=novel_id,
                profile_id=settings.narrator.profile_id,
                version_id=settings.narrator.version_id,
                voice=_voice_snapshot(
                    store,
                    novel_id=novel_id,
                    profile_id=settings.narrator.profile_id,
                    version_id=settings.narrator.version_id,
                ),
            ),
        )
    bindings: list[CharacterBindingSnapshot] = []
    for row in store.find_all(
        CharacterVoiceBinding,
        novel_id=novel_id,
        order_by=("character_id",),
    ):
        if row.binding_policy not in {"dedicated", "inherited"}:
            continue
        if row.profile_id is None or row.voice_version_id is None:
            raise InvalidNarrationState("character voice binding is incomplete")
        bindings.append(
            CharacterBindingSnapshot(
                novel_id=novel_id,
                binding_id=row.id,
                character_id=row.character_id,
                policy=wire.CharacterVoiceBindingPolicy(row.binding_policy),
                profile_id=row.profile_id,
                version_id=row.voice_version_id,
                voice=_voice_snapshot(
                    store,
                    novel_id=novel_id,
                    profile_id=row.profile_id,
                    version_id=row.voice_version_id,
                ),
            )
        )
    generic_pool = _generic_pool_snapshot(store, novel_id=novel_id)
    anonymous_bindings: list[AnonymousBindingSnapshot] = []
    for row in store.find_all(
        AnonymousSpeaker,
        novel_id=novel_id,
        lifecycle_state="active",
        order_by=("id",),
    ):
        if row.promoted_character_id is not None or row.voice_version_id is None:
            continue
        version = store.get(VoiceProfileVersion, row.voice_version_id)
        if version is None:
            continue
        voice = _voice_snapshot(
            store,
            novel_id=novel_id,
            profile_id=version.profile_id,
            version_id=version.id,
        )
        slot = None
        pool_version = None
        pool_active = None
        if row.slot_id is not None:
            if generic_pool is None:
                continue
            slot = generic_pool.slot(row.slot_id)
            if slot is None or slot.voice is None or slot.voice.version_id != version.id:
                continue
            pool_version = generic_pool.version
            pool_active = True
        anonymous_bindings.append(
            AnonymousBindingSnapshot(
                novel_id=novel_id,
                anonymous_speaker_id=row.id,
                profile_id=version.profile_id,
                version_id=version.id,
                voice=voice,
                slot=slot,
                pool_version=pool_version,
                pool_active=pool_active,
            )
        )
    rules = (
        (_automatic_generic_rule(novel_id=novel_id, pool=generic_pool),)
        if generic_pool is not None
        else ()
    )
    return CastingInventory(
        narrator_selections=narrator_selections,
        character_bindings=tuple(bindings),
        anonymous_bindings=tuple(anonymous_bindings),
        rules=rules,
        generic_pool=generic_pool,
    )


def _alias_index(
    store: NarrationStore,
    *,
    novel_id: UUID,
):
    characters = store.find_all(
        NovelCharacter,
        novel_id=novel_id,
        order_by=("position",),
    )
    active = tuple(row for row in characters if row.lifecycle_state == "active")
    allowed_ids = frozenset(row.id for row in active)
    records: list[CharacterAliasRecord] = []
    seen: set[tuple[UUID, str, AliasSource, bool]] = set()

    def append_record(record: CharacterAliasRecord) -> None:
        key = (record.character_id, record.alias, record.source, record.active)
        if key not in seen:
            seen.add(key)
            records.append(record)

    for character in active:
        if 0 < len(character.name) <= 80:
            append_record(
                CharacterAliasRecord(
                    character_id=character.id,
                    alias=character.name,
                    source=AliasSource.CANONICAL_NAME,
                )
            )
    for row in store.find_all(
        CharacterAlias,
        novel_id=novel_id,
        order_by=("normalized_alias", "character_id"),
    ):
        if row.character_id not in allowed_ids or not (0 < len(row.alias) <= 80):
            continue
        try:
            source = AliasSource(row.source)
        except ValueError as error:
            raise InvalidNarrationState("character alias source is unknown") from error
        if row.normalized_alias != normalize_character_alias(row.alias):
            raise StaleNarrationInput("character alias normalization changed")
        append_record(
            CharacterAliasRecord(
                character_id=row.character_id,
                alias=row.alias,
                source=source,
                active=row.lifecycle_state in {"active", "conflicted"},
            )
        )
    return build_character_alias_index(records, allowed_character_ids=allowed_ids)


def _canonical_issues(
    issues: list[ScriptIssueContract],
) -> tuple[ScriptIssueContract, ...]:
    by_key: dict[tuple[object, ...], ScriptIssueContract] = {}
    for issue in issues:
        key = (issue.code, issue.segment_id, issue.evidence_digest)
        previous = by_key.get(key)
        if previous is not None and previous != issue:
            raise InvalidNarrationState(
                "duplicate review issue key contains conflicting evidence"
            )
        by_key[key] = issue
    return tuple(
        sorted(
            by_key.values(),
            key=lambda issue: (
                issue.code,
                str(issue.segment_id) if issue.segment_id else "",
                issue.evidence_digest or "",
            ),
        )
    )


def _latest_approved_manual_contract(
    store: NarrationStore,
    *,
    script_id: UUID,
    actor_id: str,
) -> NarrationScriptContract | None:
    approved = store.find_all(
        NarrationScriptVersion,
        script_id=script_id,
        state="approved",
        order_by=("version_number",),
    )
    if not approved:
        return None
    candidate = load_script_contract(store, approved[-1].id)
    manual_segments = tuple(
        segment
        for segment in candidate.segments
        if segment.manual_override
        and segment.attribution.override_provenance is not None
    )
    if not manual_segments or any(
        segment.attribution.override_provenance.owner_actor_id != actor_id
        for segment in manual_segments
        if segment.attribution.override_provenance is not None
    ):
        return None
    return candidate


def _inherit_manual_overrides(
    store: NarrationStore,
    *,
    context: _AnalysisContext,
    allocation: ScriptVersionAllocation,
    contract: NarrationScriptContract,
    source: NarrationScriptContract,
    action_id: UUID,
    actor_id: str,
) -> tuple[NarrationScriptContract, frozenset[OverrideProvenance]] | None:
    """Apply only v1-authorized exact overrides to a fresh local analysis."""

    recorded_at = utc_now()
    audit = InheritanceAuditStamp(
        action_id=action_id,
        owner_actor_id=actor_id,
        recorded_at=recorded_at,
    )
    source_segments = tuple(
        segment
        for segment in source.segments
        if segment.manual_override
        and segment.attribution.override_provenance is not None
    )
    source_snapshots = tuple(
        manual_override_source(source, segment) for segment in source_segments
    )
    authority = OverrideInheritanceAuthority(
        novel_id=context.request.novel_id,
        owner_actor_id=actor_id,
        authorized_sources=frozenset(source_snapshots),
    )
    source_by_ordinal = {
        segment.ordinal: (segment, snapshot)
        for segment, snapshot in zip(
            source_segments,
            source_snapshots,
            strict=True,
        )
    }
    inventory = _casting_inventory(
        store,
        novel_id=context.request.novel_id,
        settings=context.settings,
    )
    segments = list(contract.segments)
    issues = list(contract.issues)
    provenances = set()
    for target_index, target_segment in enumerate(contract.segments):
        source_pair = source_by_ordinal.get(target_segment.ordinal)
        if source_pair is None:
            continue
        source_segment, source_snapshot = source_pair
        if (
            source_segment.local_hash != target_segment.local_hash
            or source_segment.source_text != target_segment.source_text
            or source_segment.speaker.kind
            not in {SpeakerKind.NARRATOR, SpeakerKind.CHARACTER}
            or source_segment.casting.origin
            not in {
                CastingDecisionOrigin.NARRATOR_SETTING,
                CastingDecisionOrigin.CHARACTER_BINDING,
            }
        ):
            continue
        resolution = resolve_casting(
            CastingRequest(
                novel_id=context.request.novel_id,
                segment_id=target_segment.segment_id,
                source_local_hash=target_segment.local_hash,
                segment_kind=target_segment.segment_kind,
                speaker=source_segment.speaker,
                chapter_id=context.document.id,
                volume_id=context.document.volume_id,
                scene_id=target_segment.scene_id,
                attributes=CastingAttributes(),
                same_scene_voice_deduplication=(
                    context.settings.casting.same_scene_voice_deduplication
                ),
                used_voice_version_ids=frozenset(),
                used_slot_ids=frozenset(),
            ),
            inventory,
        )
        if resolution.blocker_codes or resolution.decision.final_target is None:
            continue
        before_hash, after_hash = segment_inheritance_anchors(
            contract.segments,
            target_index,
        )
        decision = decide_override_inheritance(
            source=source_snapshot,
            target=OverrideInheritanceTarget(
                novel_id=context.request.novel_id,
                script_version_id=contract.script_version_id,
                segment_id=target_segment.segment_id,
                local_hash=target_segment.local_hash,
                anchor_before_hash=before_hash,
                anchor_after_hash=after_hash,
                speaker=source_segment.speaker,
                casting=resolution.decision,
                uniqueness=segment_anchor_uniqueness(
                    contract.segments,
                    target_index,
                ),
            ),
            authority=authority,
            audit=audit,
        )
        if not decision.eligible or decision.provenance is None:
            continue
        attribution = AttributionEvidence(
            origin=AttributionOrigin.INHERITED_OVERRIDE,
            candidate_character_ids=(
                source_segment.attribution.candidate_character_ids
            ),
            override_provenance=decision.provenance,
        )
        segments[target_index] = replace(
            target_segment,
            spoken_text=source_segment.spoken_text,
            inheritance_anchor_before_hash=before_hash,
            inheritance_anchor_after_hash=after_hash,
            speaker=source_segment.speaker,
            casting=resolution.decision,
            confidence=ConfidenceLevel.HIGH,
            attribution=attribution,
            manual_override=True,
        )
        issues = [
            issue
            for issue in issues
            if not (
                issue.segment_id == target_segment.segment_id
                and issue.code in SPEAKER_CORRECTION_ISSUE_CODES
            )
        ]
        issues.extend(
            decision.to_script_issues(segment_id=target_segment.segment_id)
        )
        provenances.add(decision.provenance)

    if not provenances:
        return None
    canonical_issues = _canonical_issues(issues)
    values = {
        field.name: getattr(contract, field.name)
        for field in fields(NarrationScriptContract)
    }
    values.update(
        {
            "parent_version_id": source.script_version_id,
            "state": ScriptVersionState.REVIEW_REQUIRED,
            "segments": tuple(segments),
            "issues": canonical_issues,
            "warning_count": sum(
                issue.severity is ReviewIssueSeverity.WARNING
                for issue in canonical_issues
            ),
            "blocker_count": sum(
                issue.severity is ReviewIssueSeverity.BLOCKER
                for issue in canonical_issues
            ),
            "approval": None,
        }
    )
    values["immutable_hash"] = canonical_sha256(
        script_immutable_payload(SimpleNamespace(**values))
    )
    inherited = NarrationScriptContract(**values)
    if inherited.script_version_id != allocation.script_version_id:
        raise InvalidNarrationState(
            "inherited script identity differs from its allocation"
        )
    return inherited, frozenset(provenances)


def _resolved_non_character_records(
    store: NarrationStore,
    *,
    novel_id: UUID,
    chapter_id: UUID,
    scene_id: UUID,
    extra: tuple[ResolvedSpeakerLabel, ...] = (),
) -> tuple[ResolvedSpeakerLabel, ...]:
    records = list(extra)
    for row in store.find_all(
        AnonymousSpeaker,
        novel_id=novel_id,
        lifecycle_state="active",
        order_by=("id",),
    ):
        if row.promoted_character_id is not None:
            continue
        if row.scope_kind == "novel" and row.scope_id == novel_id:
            pass
        elif row.scope_kind == "chapter" and row.scope_id == chapter_id:
            pass
        elif row.scope_kind == "scene" and row.scope_id == scene_id:
            pass
        else:
            continue
        records.append(
            ResolvedSpeakerLabel(
                row.display_name,
                SpeakerRef(
                    SpeakerKind.ANONYMOUS,
                    anonymous_speaker_id=row.id,
                ),
            )
        )
    return tuple(records)


def _materialize_explicit_anonymous_speaker(
    store: NarrationStore,
    *,
    novel_id: UUID,
    chapter_id: UUID,
    label: str,
    attributes: CastingAttributes,
) -> AnonymousSpeaker:
    normalized = normalize_character_alias(label)
    for row in store.find_all(
        AnonymousSpeaker,
        novel_id=novel_id,
        lifecycle_state="active",
        order_by=("id",),
    ):
        if (
            row.promoted_character_id is None
            and row.scope_kind == "chapter"
            and row.scope_id == chapter_id
            and normalize_character_alias(row.display_name) == normalized
        ):
            return row
    evidence_hash = canonical_sha256(
        {
            "schema_version": _GENERIC_CASTING_EVIDENCE_VERSION,
            "novel_id": str(novel_id),
            "chapter_id": str(chapter_id),
            "normalized_label": normalized,
        }
    )
    seed = materialize_anonymous_identity(
        authority=AnonymousScopeAuthority(
            novel_id=novel_id,
            chapter_ids=frozenset({chapter_id}),
        ),
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=chapter_id,
        source_label=label,
        evidence_hash=evidence_hash,
        display_name=unicodedata.normalize("NFC", label),
        confidence=ConfidenceLevel.HIGH,
        reuse_basis=AnonymousReuseBasis.EXPLICIT_ALIAS,
        explicit_aliases=(label,),
    )
    existing = store.get(AnonymousSpeaker, seed.identity.anonymous_speaker_id)
    if existing is not None:
        if _anonymous_identity(existing) != seed.identity:
            raise NarrationScopeMismatch(
                "derived anonymous speaker identity collides with persisted authority"
            )
        return existing
    row = AnonymousSpeaker(
        id=seed.identity.anonymous_speaker_id,
        novel_id=novel_id,
        stable_key_algorithm=seed.identity.stable_key_algorithm,
        stable_key=seed.identity.stable_key,
        display_name=seed.identity.display_name,
        scope_kind=seed.identity.scope_kind.value,
        scope_id=seed.identity.scope_id,
        inferred_json={
            "schema_version": _GENERIC_CASTING_EVIDENCE_VERSION,
            "source": "explicit_dialogue_cue",
            "source_label": label,
            "evidence_hash": evidence_hash,
            "gender": attributes.gender.value,
            "age_band": attributes.age_band.value,
            "context_kind": (
                attributes.context_kind.value if attributes.context_kind else None
            ),
        },
        confidence=seed.identity.confidence.value,
        slot_id=None,
        voice_version_id=None,
        lifecycle_state="active",
    )
    store.add(row)
    store.flush()
    return row


def _materialize_contract(
    store: NarrationStore,
    *,
    context: _AnalysisContext,
    allocation: object,
) -> NarrationScriptContract:
    segmentation = segment_source(
        script_version_id=allocation.script_version_id,
        source_text=context.revision.content_markdown,
        source_format=SourceFormat.MARKDOWN,
    )
    if segmentation.source_content_hash != context.revision.content_hash:
        raise StaleNarrationInput("revision content differs from its content hash")
    if not segmentation.segments:
        raise InvalidNarrationState("empty source cannot materialize a narration script")
    scenes = build_scene_contracts(
        script_version_id=allocation.script_version_id,
        source_text=context.revision.content_markdown,
        source_segment_ranges_utf16=tuple(
            segment.source_range_utf16 for segment in segmentation.segments
        ),
    )
    scene_ids = scene_ids_for_source_ranges(
        scenes=scenes,
        source_ranges_utf16=tuple(
            segment.source_range_utf16 for segment in segmentation.segments
        ),
    )
    aliases = _alias_index(store, novel_id=context.request.novel_id)
    inventory = _casting_inventory(
        store,
        novel_id=context.request.novel_id,
        settings=context.settings,
    )
    scene_characters: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    previous_speaker = None
    previous_paragraph: int | None = None
    used_voice_ids: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    used_slot_ids: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    assigned_by_speaker: dict[UUID, dict[tuple[str, str], tuple[UUID, UUID | None]]] = {
        scene.scene_id: {} for scene in scenes
    }
    group_records: dict[UUID, list[ResolvedSpeakerLabel]] = {
        scene.scene_id: [] for scene in scenes
    }
    anonymous_identities: dict[UUID, AnonymousSpeakerIdentity] = {}
    segments: list[SegmentContract] = []
    issues: list[ScriptIssueContract] = []
    materialized = segmentation.segments

    for index, source_segment in enumerate(materialized):
        scene_id = scene_ids[index]
        same_scene_as_previous = bool(
            index and scene_ids[index - 1] == scene_id
        )
        same_paragraph_as_previous = bool(
            same_scene_as_previous
            and materialized[index - 1].paragraph_ordinal
            == source_segment.paragraph_ordinal
        )
        before = (
            materialized[index - 1].source_text[-1000:]
            if same_paragraph_as_previous
            else ""
        )
        same_paragraph_as_next = bool(
            index + 1 < len(materialized)
            and scene_ids[index + 1] == scene_id
            and materialized[index + 1].paragraph_ordinal
            == source_segment.paragraph_ordinal
        )
        after = (
            materialized[index + 1].source_text[:1000]
            if same_paragraph_as_next
            else ""
        )
        if not same_scene_as_previous:
            previous_speaker = None
            previous_paragraph = None
        same_paragraph = (
            previous_paragraph is not None
            and previous_paragraph == source_segment.paragraph_ordinal
        )
        rule_context = SpeakerRuleContext(
            segment_kind=source_segment.segment_kind,
            source_text=source_segment.source_text,
            cue_before=before,
            cue_after=after,
            scene_character_ids=frozenset(scene_characters[scene_id]),
            previous_speaker=previous_speaker,
            same_paragraph_continuation=same_paragraph,
        )
        resolved_records = _resolved_non_character_records(
            store,
            novel_id=context.request.novel_id,
            chapter_id=context.document.id,
            scene_id=scene_id,
            extra=tuple(group_records[scene_id]),
        )
        resolved_index = build_resolved_speaker_index(
            resolved_records,
            allowed_speakers=frozenset(record.speaker for record in resolved_records),
        )
        speaker = attribute_speaker_local(
            rule_context,
            aliases=aliases,
            resolved_speakers=resolved_index,
        )
        speaker_label: str | None = None
        if (
            inventory.generic_pool is not None
            and speaker.speaker.kind is SpeakerKind.UNKNOWN
            and speaker.unresolved_label is not None
            and speaker.unresolved_kind in {SpeakerKind.ANONYMOUS, SpeakerKind.GROUP}
        ):
            speaker_label = speaker.unresolved_label
            preliminary = _explicit_casting_attributes(
                label=speaker_label,
                segment_kind=source_segment.segment_kind,
                speaker_kind=speaker.unresolved_kind,
            )
            if speaker.unresolved_kind is SpeakerKind.ANONYMOUS:
                anonymous = _materialize_explicit_anonymous_speaker(
                    store,
                    novel_id=context.request.novel_id,
                    chapter_id=context.document.id,
                    label=speaker_label,
                    attributes=preliminary,
                )
                anonymous_identities[anonymous.id] = _anonymous_identity(anonymous)
            else:
                evidence_hash = canonical_sha256(
                    {
                        "schema_version": _GENERIC_CASTING_EVIDENCE_VERSION,
                        "scene_id": str(scene_id),
                        "label": normalize_character_alias(speaker_label),
                    }
                )
                group_ref = SpeakerRef(
                    SpeakerKind.GROUP,
                    group_key=derive_group_key(
                        novel_id=context.request.novel_id,
                        scene_id=scene_id,
                        label=speaker_label,
                        evidence_hash=evidence_hash,
                    ),
                )
                record = ResolvedSpeakerLabel(speaker_label, group_ref)
                if record not in group_records[scene_id]:
                    group_records[scene_id].append(record)
            resolved_records = _resolved_non_character_records(
                store,
                novel_id=context.request.novel_id,
                chapter_id=context.document.id,
                scene_id=scene_id,
                extra=tuple(group_records[scene_id]),
            )
            resolved_index = build_resolved_speaker_index(
                resolved_records,
                allowed_speakers=frozenset(
                    record.speaker for record in resolved_records
                ),
            )
            speaker = attribute_speaker_local(
                rule_context,
                aliases=aliases,
                resolved_speakers=resolved_index,
            )
        if speaker.speaker.character_id is not None:
            scene_characters[scene_id].add(speaker.speaker.character_id)
        anonymous_row = None
        anonymous_stable_key = None
        if speaker.speaker.kind is SpeakerKind.ANONYMOUS:
            anonymous_row = require_row(
                store.get(
                    AnonymousSpeaker,
                    speaker.speaker.anonymous_speaker_id,
                    for_update=True,
                ),
                label="anonymous speaker",
            )
            anonymous_identities[anonymous_row.id] = _anonymous_identity(anonymous_row)
            speaker_label = anonymous_row.display_name
            anonymous_stable_key = anonymous_row.stable_key
        attributes = _explicit_casting_attributes(
            label=speaker_label,
            segment_kind=source_segment.segment_kind,
            speaker_kind=speaker.speaker.kind,
            anonymous_stable_key=anonymous_stable_key,
        )
        identity_value = (
            speaker.speaker.character_id
            or speaker.speaker.anonymous_speaker_id
            or speaker.speaker.group_key
            or source_segment.local_hash
        )
        speaker_key = (speaker.speaker.kind.value, str(identity_value))
        used_voices = set(used_voice_ids[scene_id])
        used_slots = set(used_slot_ids[scene_id])
        previous_assignment = assigned_by_speaker[scene_id].get(speaker_key)
        if previous_assignment is not None:
            used_voices.discard(previous_assignment[0])
            if previous_assignment[1] is not None:
                used_slots.discard(previous_assignment[1])
        casting = resolve_casting(
            CastingRequest(
                novel_id=context.request.novel_id,
                segment_id=source_segment.segment_id,
                source_local_hash=source_segment.local_hash,
                segment_kind=source_segment.segment_kind,
                speaker=speaker.speaker,
                chapter_id=context.document.id,
                volume_id=context.document.volume_id,
                scene_id=scene_id,
                attributes=attributes,
                same_scene_voice_deduplication=(
                    context.settings.casting.same_scene_voice_deduplication
                ),
                used_voice_version_ids=frozenset(used_voices),
                used_slot_ids=frozenset(used_slots),
            ),
            inventory,
        )
        if casting.resolved_voice is not None:
            used_voice_ids[scene_id].add(casting.resolved_voice.version_id)
            if casting.resolved_voice.slot_id is not None:
                used_slot_ids[scene_id].add(casting.resolved_voice.slot_id)
            assigned_by_speaker[scene_id][speaker_key] = (
                casting.resolved_voice.version_id,
                casting.resolved_voice.slot_id,
            )
            if (
                anonymous_row is not None
                and casting.resolved_voice.slot_id is not None
                and anonymous_row.voice_version_id is None
                and inventory.generic_pool is not None
            ):
                slot = inventory.generic_pool.slot(casting.resolved_voice.slot_id)
                if slot is None or slot.voice is None:
                    raise InvalidNarrationState(
                        "resolved anonymous generic slot disappeared"
                    )
                anonymous_row.slot_id = slot.slot_id
                anonymous_row.voice_version_id = slot.voice.version_id
                binding = AnonymousBindingSnapshot(
                    novel_id=context.request.novel_id,
                    anonymous_speaker_id=anonymous_row.id,
                    profile_id=slot.voice.profile_id,
                    version_id=slot.voice.version_id,
                    voice=slot.voice,
                    slot=slot,
                    pool_version=inventory.generic_pool.version,
                    pool_active=True,
                )
                inventory = replace(
                    inventory,
                    anonymous_bindings=tuple(
                        item
                        for item in inventory.anonymous_bindings
                        if item.anonymous_speaker_id != anonymous_row.id
                    )
                    + (binding,),
                )
        expression = classify_expression(
            ExpressionContext(
                segment_kind=source_segment.segment_kind,
                source_text=source_segment.source_text,
                spoken_text=source_segment.spoken_text,
                cue_before=before,
                cue_after=after,
            )
        )
        next_segment = materialized[index + 1] if index + 1 < len(materialized) else None
        if next_segment is None:
            pause_after_ms = 0
        elif next_segment.paragraph_ordinal == source_segment.paragraph_ordinal:
            pause_after_ms = context.settings.timing.sentence_gap_ms
        elif scene_ids[index + 1] != scene_id:
            pause_after_ms = context.settings.timing.section_gap_ms
        else:
            pause_after_ms = context.settings.timing.paragraph_gap_ms
        segments.append(
            SegmentContract(
                segment_id=source_segment.segment_id,
                ordinal=source_segment.ordinal,
                scene_id=scene_id,
                segment_kind=source_segment.segment_kind,
                source_block_kind=source_segment.source_block_kind,
                paragraph_ordinal=source_segment.paragraph_ordinal,
                segment_ordinal_in_block=source_segment.segment_ordinal_in_block,
                source_block_key=source_segment.source_block_key,
                source_block_hash=source_segment.source_block_hash,
                source_range_utf16=source_segment.source_range_utf16,
                source_text=source_segment.source_text,
                spoken_text=source_segment.spoken_text,
                local_hash=source_segment.local_hash,
                anchor_before_hash=source_segment.anchor_before_hash,
                anchor_after_hash=source_segment.anchor_after_hash,
                inheritance_anchor_before_hash=None,
                inheritance_anchor_after_hash=None,
                speaker=speaker.speaker,
                casting=casting.decision,
                confidence=speaker.confidence,
                emotion=expression.emotion,
                emotion_confidence=expression.emotion_confidence,
                delivery=expression.delivery,
                attribution=speaker.attribution,
                pause_before_ms=0,
                pause_after_ms=pause_after_ms,
                manual_override=False,
            )
        )
        issues.extend(speaker.to_script_issues(segment_id=source_segment.segment_id))
        issues.extend(casting.issues)
        previous_speaker = speaker.speaker
        previous_paragraph = source_segment.paragraph_ordinal

    canonical_issues = _canonical_issues(issues)
    warning_count = sum(
        issue.severity is ReviewIssueSeverity.WARNING for issue in canonical_issues
    )
    blocker_count = sum(
        issue.severity is ReviewIssueSeverity.BLOCKER for issue in canonical_issues
    )
    policy = ScriptReviewPolicy(context.request.effective_policy)
    base = {
        "script_id": allocation.script_id,
        "script_version_id": allocation.script_version_id,
        "novel_id": context.request.novel_id,
        "document_id": context.document.id,
        "revision_id": context.revision.id,
        "source_content_hash": context.revision.content_hash,
        "source_length_utf16": segmentation.source_length_utf16,
        "version_number": allocation.version_number,
        "parent_version_id": allocation.parent_version_id,
        "state": initial_materialized_state(policy, blocker_count=blocker_count),
        "effective_policy": policy,
        "analyzer_fingerprint": SCRIPT_ANALYZER_FINGERPRINT,
        "rules_fingerprint": SCRIPT_RULES_FINGERPRINT,
        "settings_fingerprint": context.request.settings_fingerprint,
        "requested_model_fingerprint": None,
        "actual_model_fingerprint": None,
        "anonymous_speakers": tuple(
            sorted(
                anonymous_identities.values(),
                key=lambda item: (
                    item.stable_key_algorithm,
                    item.stable_key,
                    str(item.anonymous_speaker_id),
                ),
            )
        ),
        "scenes": scenes,
        "segments": tuple(segments),
        "issues": canonical_issues,
        "warning_count": warning_count,
        "blocker_count": blocker_count,
        "approval": None,
        "schema_version": NARRATION_SCRIPT_CONTRACT_VERSION,
        "taxonomy_version": NARRATION_REVIEW_TAXONOMY_VERSION,
    }
    immutable_hash = canonical_sha256(
        script_immutable_payload(SimpleNamespace(**base))
    )
    return NarrationScriptContract(**base, immutable_hash=immutable_hash)


def _analysis_version_key(command: AnalyzeNarrationScript) -> str:
    return "analysis-" + canonical_sha256(
        {
            "request_id": str(command.request_id),
            "idempotency_key": command.idempotency_key,
        }
    )


def _finish_request(
    store: NarrationStore,
    *,
    request: NarrationRequest,
    contract: NarrationScriptContract,
) -> None:
    if request.state != "analyzing":
        return
    new_state = (
        "review_required"
        if contract.state.value == "review_required"
        else "analyzed"
    )
    advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state=new_state,
        novel_id=request.novel_id,
        actor="narration-script-analyzer",
    )


def _bind_request_review_pointer(
    store: NarrationStore,
    *,
    request: NarrationRequest,
    contract: NarrationScriptContract,
) -> None:
    """Bind the server-owned candidate without guessing for completed legacy rows."""

    if request.document_id != contract.document_id:
        raise NarrationScopeMismatch(
            "narration request review candidate belongs to another document"
        )
    if (
        request.review_script_id is None
        and request.current_review_version_id is None
    ):
        if request.state not in {"created", "analyzing"}:
            raise InvalidNarrationState(
                "completed legacy narration request has no review candidate pointer"
            )
        request.review_script_id = contract.script_id
        request.current_review_version_id = contract.script_version_id
        request.version += 1
        request.updated_at = utc_now()
        store.flush()
        return
    if (
        request.review_script_id != contract.script_id
        or request.current_review_version_id != contract.script_version_id
    ):
        raise IdempotencyConflict(
            "narration request already points at another review candidate"
        )


def analyze_narration_script(
    store: NarrationStore,
    command: AnalyzeNarrationScript,
) -> NarrationScriptContract:
    """Analyze, persist, reload, and (only when legal) auto-freeze one script.

    The caller owns one authoritative transaction.  No Edition or media row is
    created here.  HTTP manual corrections/approval/reanalysis remain HOLD in
    the adapter until their action-key persistence contract exists.
    """

    context = _require_analysis_context(store, command)
    if context.request.state == "created":
        context = _AnalysisContext(
            request=advance_request_state(
                store,
                context.request.id,
                expected_version=context.request.version,
                new_state="analyzing",
                novel_id=context.request.novel_id,
                actor="narration-script-analyzer",
            ),
            document=context.document,
            revision=context.revision,
            settings=context.settings,
        )
    elif context.request.state not in {"analyzing", "analyzed", "review_required"}:
        raise InvalidNarrationState("narration request is not analyzable")

    allocation = reserve_script_identity(
        store,
        ReserveScriptIdentity(
            novel_id=context.request.novel_id,
            document_id=context.document.id,
            revision_id=context.revision.id,
            content_hash=context.revision.content_hash,
            idempotency_key=_analysis_version_key(command),
        ),
    )
    if allocation.existing:
        if (
            context.request.review_script_id == allocation.script_id
            and context.request.current_review_version_id is not None
        ):
            contract = load_script_contract(
                store,
                context.request.current_review_version_id,
            )
        else:
            contract = load_script_contract(store, allocation.script_version_id)
        _bind_request_review_pointer(
            store,
            request=context.request,
            contract=contract,
        )
        _finish_request(store, request=context.request, contract=contract)
        return contract
    if context.request.state in {"analyzed", "review_required"}:
        raise InvalidNarrationState(
            "a completed narration request may only replay its original analysis"
        )

    contract = _materialize_contract(
        store,
        context=context,
        allocation=allocation,
    )
    actor_id = context.request.explicit_generation_actor
    if context.request.intent != "analyze_only" and actor_id is not None:
        source = _latest_approved_manual_contract(
            store,
            script_id=allocation.script_id,
            actor_id=actor_id,
        )
        if source is not None:
            action_key, action_id = inherited_analysis_action_identity(
                request_id=context.request.id,
                analysis_idempotency_key=command.idempotency_key,
            )
            inherited_result = _inherit_manual_overrides(
                store,
                context=context,
                allocation=allocation,
                contract=contract,
                source=source,
                action_id=action_id,
                actor_id=actor_id,
            )
            if inherited_result is not None:
                contract, pending_provenances = inherited_result
                allocation = replace(
                    allocation,
                    parent_version_id=source.script_version_id,
                )
                persist_inherited_analysis_result(
                    store,
                    request=context.request,
                    allocation=allocation,
                    contract=contract,
                    source_version_id=source.script_version_id,
                    action_key=action_key,
                    actor_id=actor_id,
                    pending_provenances=pending_provenances,
                )
                contract = load_script_contract(
                    store,
                    contract.script_version_id,
                )
                _finish_request(
                    store,
                    request=context.request,
                    contract=contract,
                )
                return contract
    persisted = persist_script_contract(store, allocation, contract)
    if (
        context.request.intent != "analyze_only"
        and contract.state.value == "analyzed"
        and contract.blocker_count == 0
        and contract.effective_policy is ScriptReviewPolicy.BLOCKERS_ONLY
    ):
        freeze_script_version(
            store,
            persisted.id,
            request_id=context.request.id,
            actor_type="service",
            actor_id="narration-script-analyzer",
        )
        contract = load_script_contract(store, persisted.id)
    _bind_request_review_pointer(
        store,
        request=context.request,
        contract=contract,
    )
    _finish_request(store, request=context.request, contract=contract)
    return contract


__all__ = [
    "SCRIPT_ANALYZER_FINGERPRINT",
    "SCRIPT_ANALYZER_VERSION",
    "SCRIPT_RULES_FINGERPRINT",
    "AnalyzeNarrationScript",
    "analyze_narration_script",
]
