"""Deterministic, fail-closed narration casting for Qwen TTS.

This current-runtime resolver deliberately has no generic-pool target or
narrator fallback. It consumes validated snapshots and has no ORM/provider IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import unicodedata
from typing import Final, Iterable
from uuid import RFC_4122, UUID

from . import schemas as wire
from .contracts import issue_severity
from .fingerprints import canonical_json_bytes
from .script_contracts import (
    CastingDecision,
    CastingDecisionOrigin,
    CastingRuleAuthorityRecord,
    CastingTargetKind,
    CastingTargetRef,
    ScriptIssueContract,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
)

CASTING_RESOLVER_VERSION: Final = "narration-casting-resolver/2"
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class CastingInputError(ValueError):
    """Raised when server authority snapshots are internally inconsistent."""


class CastingScopeKind(str, Enum):
    NOVEL = "novel"
    VOLUME = "volume"
    CHAPTER = "chapter"


class CastingRuleAction(str, Enum):
    VOICE_VERSION = "voice_version"
    REQUIRE_REVIEW = "require_review"


class CastingResolutionSource(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"
    CHAPTER_NARRATOR = "chapter_narrator"
    VOLUME_NARRATOR = "volume_narrator"
    NOVEL_NARRATOR = "novel_narrator"
    EXPLICIT_RULE = "explicit_rule"
    CHARACTER_DEDICATED = "character_dedicated"
    CHARACTER_INHERITED = "character_inherited"
    ANONYMOUS_BINDING = "anonymous_binding"


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID or value.variant != RFC_4122 or value.version not in {4, 5}:
        raise CastingInputError(f"{field_name} must be a canonical UUIDv4/v5")
    return value


def _require_optional_uuid(value: object, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _require_uuid(value, field_name=field_name)


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise CastingInputError(f"{field_name} must be a positive integer")
    return value


def _require_bounded_int(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CastingInputError(f"{field_name} must be an integer in [{minimum}, {maximum}]")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CastingInputError(f"{field_name} must be lowercase SHA-256")
    return value


def _require_exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise CastingInputError(f"{field_name} must be an exact boolean")
    return value


def _normalized_tag(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        raise CastingInputError(f"{field_name} must be text")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if not normalized or len(normalized) > 80:
        raise CastingInputError(f"{field_name} must be bounded non-empty text")
    return normalized


def _normalized_tags(values: object, *, field_name: str) -> frozenset[str]:
    if type(values) not in {tuple, frozenset}:
        raise CastingInputError(f"{field_name} must be an immutable collection")
    normalized = frozenset(_normalized_tag(value, field_name=f"{field_name} item") for value in values)
    if len(normalized) != len(values) or len(normalized) > 32:
        raise CastingInputError(f"{field_name} must contain at most 32 unique tags")
    return normalized


@dataclass(frozen=True, slots=True)
class VoiceVersionSnapshot:
    profile_id: UUID
    version_id: UUID
    version_number: int
    fingerprint: str
    profile_novel_id: UUID | None
    profile_status: wire.VoiceProfileStatus
    source_type: wire.VoiceSourceType
    version_state: wire.VoiceVersionState
    quality_state: wire.VoiceQualityState
    activation_evidence_usable: bool
    rights_record_id: UUID | None
    rights_state: wire.VoiceRightsState | None
    voice_cloning_permitted: bool

    def __post_init__(self) -> None:
        _require_uuid(self.profile_id, field_name="voice profile_id")
        _require_uuid(self.version_id, field_name="voice version_id")
        _require_positive_int(self.version_number, field_name="voice version_number")
        _require_sha256(self.fingerprint, field_name="voice fingerprint")
        _require_optional_uuid(self.profile_novel_id, field_name="voice profile_novel_id")
        if type(self.profile_status) is not wire.VoiceProfileStatus:
            raise CastingInputError("voice profile_status is unsupported")
        if type(self.source_type) is not wire.VoiceSourceType:
            raise CastingInputError("voice source_type is unsupported")
        if type(self.version_state) is not wire.VoiceVersionState:
            raise CastingInputError("voice version_state is unsupported")
        if type(self.quality_state) is not wire.VoiceQualityState:
            raise CastingInputError("voice quality_state is unsupported")
        _require_exact_bool(self.activation_evidence_usable, field_name="activation_evidence_usable")
        _require_optional_uuid(self.rights_record_id, field_name="voice rights_record_id")
        if self.rights_state is not None and type(self.rights_state) is not wire.VoiceRightsState:
            raise CastingInputError("voice rights_state is unsupported")
        _require_exact_bool(self.voice_cloning_permitted, field_name="voice_cloning_permitted")

    def blocker_codes(self, *, novel_id: UUID) -> frozenset[str]:
        _require_uuid(novel_id, field_name="voice use novel_id")
        blockers: set[str] = set()
        if (
            self.profile_novel_id not in {None, novel_id}
            or self.profile_status is not wire.VoiceProfileStatus.ACTIVE
            or self.version_state is not wire.VoiceVersionState.LOCKED
            or not self.activation_evidence_usable
        ):
            blockers.add("B_VOICE_VERSION_UNAVAILABLE")
        if (
            self.rights_record_id is None
            or self.rights_state is not wire.VoiceRightsState.ACTIVE
            or (self.source_type is wire.VoiceSourceType.UPLOADED and not self.voice_cloning_permitted)
        ):
            blockers.add("B_VOICE_RIGHTS_UNAVAILABLE")
        return frozenset(blockers)


def _validate_voice_ref(owner: str, profile_id: UUID, version_id: UUID, voice: VoiceVersionSnapshot | None) -> None:
    _require_uuid(profile_id, field_name=f"{owner} profile_id")
    _require_uuid(version_id, field_name=f"{owner} version_id")
    if voice is not None:
        if type(voice) is not VoiceVersionSnapshot:
            raise CastingInputError(f"{owner} voice has an invalid type")
        if voice.profile_id != profile_id or voice.version_id != version_id:
            raise CastingInputError(f"{owner} profile/version relation is inconsistent")


@dataclass(frozen=True, slots=True)
class NarratorSelectionSnapshot:
    novel_id: UUID
    scope_kind: CastingScopeKind
    scope_id: UUID
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="narrator novel_id")
        if type(self.scope_kind) is not CastingScopeKind:
            raise CastingInputError("narrator scope_kind is unsupported")
        _require_uuid(self.scope_id, field_name="narrator scope_id")
        if self.scope_kind is CastingScopeKind.NOVEL and self.scope_id != self.novel_id:
            raise CastingInputError("novel narrator scope_id must equal novel_id")
        _validate_voice_ref("narrator", self.profile_id, self.version_id, self.voice)


@dataclass(frozen=True, slots=True)
class CharacterBindingSnapshot:
    novel_id: UUID
    binding_id: UUID
    character_id: UUID
    policy: wire.CharacterVoiceBindingPolicy
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="character binding novel_id")
        _require_uuid(self.binding_id, field_name="character binding_id")
        _require_uuid(self.character_id, field_name="character binding character_id")
        if type(self.policy) is not wire.CharacterVoiceBindingPolicy or self.policy not in {
            wire.CharacterVoiceBindingPolicy.DEDICATED,
            wire.CharacterVoiceBindingPolicy.INHERITED,
        }:
            raise CastingInputError("character binding must be dedicated or inherited")
        _validate_voice_ref("character binding", self.profile_id, self.version_id, self.voice)


@dataclass(frozen=True, slots=True)
class AnonymousBindingSnapshot:
    novel_id: UUID
    anonymous_speaker_id: UUID
    profile_id: UUID
    version_id: UUID
    voice: VoiceVersionSnapshot | None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="anonymous binding novel_id")
        _require_uuid(self.anonymous_speaker_id, field_name="anonymous binding speaker_id")
        _validate_voice_ref("anonymous binding", self.profile_id, self.version_id, self.voice)


@dataclass(frozen=True, slots=True)
class CastingAttributes:
    gender: wire.CastingGender = wire.CastingGender.UNKNOWN
    age_band: wire.CastingAgeBand = wire.CastingAgeBand.UNKNOWN
    context_kind: wire.CastingContextKind | None = None
    role_tags: frozenset[str] = frozenset()
    anonymous_stable_key: str | None = None

    def __post_init__(self) -> None:
        if type(self.gender) is not wire.CastingGender:
            raise CastingInputError("casting gender is unsupported")
        if type(self.age_band) is not wire.CastingAgeBand:
            raise CastingInputError("casting age_band is unsupported")
        if self.context_kind is not None and type(self.context_kind) is not wire.CastingContextKind:
            raise CastingInputError("casting context_kind is unsupported")
        if _normalized_tags(self.role_tags, field_name="casting role_tags") != self.role_tags:
            raise CastingInputError("casting role_tags must be normalized")
        if self.anonymous_stable_key is not None and (
            type(self.anonymous_stable_key) is not str
            or not self.anonymous_stable_key.strip()
            or len(self.anonymous_stable_key) > 160
            or unicodedata.normalize("NFC", self.anonymous_stable_key) != self.anonymous_stable_key
        ):
            raise CastingInputError("anonymous_stable_key must be bounded NFC text")


@dataclass(frozen=True, slots=True)
class CastingRuleSnapshot:
    novel_id: UUID
    rule_id: UUID
    version: int
    priority: int
    enabled: bool
    condition: wire.VoiceCastingCondition
    action: CastingRuleAction
    profile_id: UUID | None = None
    version_id: UUID | None = None
    voice: VoiceVersionSnapshot | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="casting rule novel_id")
        _require_uuid(self.rule_id, field_name="casting rule_id")
        _require_positive_int(self.version, field_name="casting rule version")
        _require_bounded_int(self.priority, field_name="casting rule priority", minimum=-10_000, maximum=10_000)
        _require_exact_bool(self.enabled, field_name="casting rule enabled")
        if type(self.condition) is not wire.VoiceCastingCondition:
            raise CastingInputError("casting rule condition has an invalid type")
        if type(self.action) is not CastingRuleAction:
            raise CastingInputError("casting rule action is unsupported")
        _require_optional_uuid(self.profile_id, field_name="casting rule profile_id")
        _require_optional_uuid(self.version_id, field_name="casting rule version_id")
        if (self.profile_id is None) != (self.version_id is None):
            raise CastingInputError("casting rule profile/version must be paired")
        if self.action is CastingRuleAction.VOICE_VERSION:
            if self.profile_id is None or self.version_id is None or self.voice is None:
                raise CastingInputError("voice-version rule has an invalid target")
            _validate_voice_ref("casting rule", self.profile_id, self.version_id, self.voice)
        elif any(value is not None for value in (self.profile_id, self.version_id, self.voice)):
            raise CastingInputError("require-review rule cannot carry a target")


@dataclass(frozen=True, slots=True)
class CastingRequest:
    novel_id: UUID
    segment_id: UUID
    source_local_hash: str
    segment_kind: SegmentKind
    speaker: SpeakerRef
    chapter_id: UUID
    volume_id: UUID | None
    scene_id: UUID | None
    attributes: CastingAttributes
    same_scene_voice_deduplication: bool
    used_voice_version_ids: frozenset[UUID] = frozenset()

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="casting request novel_id")
        _require_uuid(self.segment_id, field_name="casting request segment_id")
        _require_sha256(self.source_local_hash, field_name="casting request source_local_hash")
        if type(self.segment_kind) is not SegmentKind:
            raise CastingInputError("casting request segment_kind is unsupported")
        if type(self.speaker) is not SpeakerRef:
            raise CastingInputError("casting request speaker has an invalid type")
        _require_uuid(self.chapter_id, field_name="casting request chapter_id")
        _require_optional_uuid(self.volume_id, field_name="casting request volume_id")
        _require_optional_uuid(self.scene_id, field_name="casting request scene_id")
        if type(self.attributes) is not CastingAttributes:
            raise CastingInputError("casting request attributes have an invalid type")
        _require_exact_bool(self.same_scene_voice_deduplication, field_name="same_scene_voice_deduplication")
        if type(self.used_voice_version_ids) is not frozenset:
            raise CastingInputError("used_voice_version_ids must be a frozenset")
        for value in self.used_voice_version_ids:
            _require_uuid(value, field_name="used_voice_version_ids item")
        if self.segment_kind is SegmentKind.SYNTHETIC_PAUSE and self.speaker.kind is not SpeakerKind.NARRATOR:
            raise CastingInputError("synthetic pause must use narrator identity")


@dataclass(frozen=True, slots=True)
class CastingInventory:
    narrator_selections: tuple[NarratorSelectionSnapshot, ...] = ()
    character_bindings: tuple[CharacterBindingSnapshot, ...] = ()
    anonymous_bindings: tuple[AnonymousBindingSnapshot, ...] = ()
    rules: tuple[CastingRuleSnapshot, ...] = ()

    def __post_init__(self) -> None:
        groups = (
            (self.narrator_selections, NarratorSelectionSnapshot),
            (self.character_bindings, CharacterBindingSnapshot),
            (self.anonymous_bindings, AnonymousBindingSnapshot),
            (self.rules, CastingRuleSnapshot),
        )
        if any(type(items) is not tuple or any(type(item) is not expected for item in items) for items, expected in groups):
            raise CastingInputError("casting inventory contains an invalid snapshot")
        keys = (
            [(x.novel_id, x.scope_kind, x.scope_id) for x in self.narrator_selections],
            [(x.novel_id, x.character_id) for x in self.character_bindings],
            [(x.novel_id, x.anonymous_speaker_id) for x in self.anonymous_bindings],
            [x.rule_id for x in self.rules],
            [x.priority for x in self.rules],
        )
        if any(len(values) != len(set(values)) for values in keys):
            raise CastingInputError("casting inventory contains duplicate authority")


@dataclass(frozen=True, slots=True)
class ResolvedVoiceSnapshot:
    profile_id: UUID
    version_id: UUID
    version_number: int
    fingerprint: str

    def __post_init__(self) -> None:
        _require_uuid(self.profile_id, field_name="resolved voice profile_id")
        _require_uuid(self.version_id, field_name="resolved voice version_id")
        _require_positive_int(self.version_number, field_name="resolved voice version_number")
        _require_sha256(self.fingerprint, field_name="resolved voice fingerprint")


@dataclass(frozen=True, slots=True)
class CastingResolution:
    speaker: SpeakerRef
    segment_id: UUID
    source_local_hash: str
    decision: CastingDecision
    source: CastingResolutionSource
    resolved_voice: ResolvedVoiceSnapshot | None
    issues: tuple[ScriptIssueContract, ...]
    rule_authority: CastingRuleAuthorityRecord | None = None

    def __post_init__(self) -> None:
        if type(self.speaker) is not SpeakerRef:
            raise CastingInputError("casting resolution speaker has an invalid type")
        _require_uuid(self.segment_id, field_name="casting resolution segment_id")
        _require_sha256(self.source_local_hash, field_name="casting resolution source_local_hash")
        if type(self.decision) is not CastingDecision or type(self.source) is not CastingResolutionSource:
            raise CastingInputError("casting resolution contract is unsupported")
        if self.resolved_voice is not None and type(self.resolved_voice) is not ResolvedVoiceSnapshot:
            raise CastingInputError("casting resolved_voice has an invalid type")
        if type(self.issues) is not tuple or not all(type(issue) is ScriptIssueContract for issue in self.issues):
            raise CastingInputError("casting issues must be frozen script issues")
        if self.issues != tuple(sorted(self.issues, key=lambda issue: (issue.code, str(issue.segment_id) if issue.segment_id else "", issue.evidence_digest or ""))):
            raise CastingInputError("casting issues must use canonical order")
        if any(issue.segment_id != self.segment_id for issue in self.issues):
            raise CastingInputError("casting issue belongs to another segment")
        codes = {issue.code for issue in self.issues}
        if self.decision.origin is CastingDecisionOrigin.UNRESOLVED:
            if self.resolved_voice is not None or "B_CASTING_TARGET_UNRESOLVED" not in codes:
                raise CastingInputError("unresolved casting must have no voice and its frozen blocker")
        elif self.decision.origin is CastingDecisionOrigin.NOT_APPLICABLE:
            if self.resolved_voice is not None or self.issues:
                raise CastingInputError("not-applicable casting cannot carry voice/issues")
        elif self.resolved_voice is None:
            raise CastingInputError("resolved casting requires transient voice evidence")
        if self.decision.origin is CastingDecisionOrigin.CASTING_RULE:
            if self.rule_authority is None or self.rule_authority.decision != self.decision:
                raise CastingInputError("casting-rule decision requires its exact authority record")
            if (
                self.rule_authority.segment_id != self.segment_id
                or self.rule_authority.source_local_hash != self.source_local_hash
                or self.rule_authority.speaker_target_hash != speaker_target_hash(self.speaker, self.decision)
            ):
                raise CastingInputError("casting-rule authority differs from segment/source/speaker decision")
        elif self.rule_authority is not None:
            raise CastingInputError("only casting-rule decisions carry rule authority")
        target = self.decision.final_target
        if target is not None and target.kind is CastingTargetKind.PROFILE and self.resolved_voice is not None and target.profile_id != self.resolved_voice.profile_id:
            raise CastingInputError("profile target differs from resolved voice")

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity.value == "blocker")

    @property
    def warning_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity.value == "warning")


def _target_key(target: CastingTargetRef) -> bytes:
    return canonical_json_bytes({
        "kind": target.kind.value,
        "binding_id": str(target.binding_id) if target.binding_id else None,
        "character_id": str(target.character_id) if target.character_id else None,
        "anonymous_speaker_id": str(target.anonymous_speaker_id) if target.anonymous_speaker_id else None,
        "profile_id": str(target.profile_id) if target.profile_id else None,
    })


def _canonical_targets(targets: Iterable[CastingTargetRef]) -> tuple[CastingTargetRef, ...]:
    unique = {_target_key(target): target for target in targets}
    return tuple(unique[key] for key in sorted(unique))


def _issues(segment_id: UUID, codes: Iterable[str]) -> tuple[ScriptIssueContract, ...]:
    return tuple(sorted((ScriptIssueContract(code=code, severity=issue_severity(code), segment_id=segment_id) for code in set(codes)), key=lambda issue: (issue.code, str(issue.segment_id) if issue.segment_id else "", issue.evidence_digest or "")))


def _unresolved(request: CastingRequest, *, candidates: Iterable[CastingTargetRef] = (), codes: Iterable[str] = ()) -> CastingResolution:
    return CastingResolution(
        speaker=request.speaker,
        segment_id=request.segment_id,
        source_local_hash=request.source_local_hash,
        decision=CastingDecision(candidate_targets=_canonical_targets(candidates), final_target=None, origin=CastingDecisionOrigin.UNRESOLVED),
        source=CastingResolutionSource.UNRESOLVED,
        resolved_voice=None,
        issues=_issues(request.segment_id, {"B_CASTING_TARGET_UNRESOLVED", *codes}),
    )


def _voice_or_block(request: CastingRequest, *, target: CastingTargetRef, voice: VoiceVersionSnapshot | None, origin: CastingDecisionOrigin, source: CastingResolutionSource, rule: CastingRuleSnapshot | None = None) -> CastingResolution:
    if voice is None:
        return _unresolved(request, candidates=(target,), codes=("B_VOICE_VERSION_UNAVAILABLE",))
    blockers = voice.blocker_codes(novel_id=request.novel_id)
    # Explicit narrator, character, anonymous, and rule bindings are stable
    # author choices. Same-scene deduplication previously existed only to pick
    # among interchangeable generic-pool candidates; it must not invalidate a
    # direct binding now that the generic pool has been retired.
    if blockers:
        return _unresolved(request, candidates=(target,), codes=blockers)
    decision = CastingDecision(candidate_targets=(target,), final_target=target, origin=origin, rule_id=rule.rule_id if rule else None, rule_version=rule.version if rule else None)
    authority = CastingRuleAuthorityRecord(decision=decision, segment_id=request.segment_id, source_local_hash=request.source_local_hash, speaker_target_hash=speaker_target_hash(request.speaker, decision)) if rule else None
    return CastingResolution(
        speaker=request.speaker,
        segment_id=request.segment_id,
        source_local_hash=request.source_local_hash,
        decision=decision,
        source=source,
        resolved_voice=ResolvedVoiceSnapshot(profile_id=voice.profile_id, version_id=voice.version_id, version_number=voice.version_number, fingerprint=voice.fingerprint),
        issues=(),
        rule_authority=authority,
    )


def _rule_matches(rule: CastingRuleSnapshot, request: CastingRequest) -> bool:
    if not rule.enabled or request.speaker.kind not in {SpeakerKind.CHARACTER, SpeakerKind.ANONYMOUS, SpeakerKind.GROUP, SpeakerKind.UNKNOWN}:
        return False
    condition = rule.condition
    if condition.speaker_kinds and wire.CastingSpeakerKind(request.speaker.kind.value) not in condition.speaker_kinds:
        return False
    if condition.genders and request.attributes.gender not in condition.genders:
        return False
    if condition.age_bands and request.attributes.age_band not in condition.age_bands:
        return False
    if condition.context_kinds and (request.attributes.context_kind is None or request.attributes.context_kind not in condition.context_kinds):
        return False
    required_tags = {_normalized_tag(tag, field_name="casting rule role tag") for tag in condition.role_tags}
    return required_tags.issubset(request.attributes.role_tags)


def _matching_rules(request: CastingRequest, inventory: CastingInventory) -> tuple[CastingRuleSnapshot, ...]:
    return tuple(sorted((rule for rule in inventory.rules if rule.novel_id == request.novel_id and _rule_matches(rule, request)), key=lambda rule: (-rule.priority, str(rule.rule_id))))


def _resolve_explicit_rule(request: CastingRequest, rule: CastingRuleSnapshot) -> CastingResolution:
    if rule.action is CastingRuleAction.REQUIRE_REVIEW:
        return _unresolved(request)
    assert rule.profile_id is not None
    return _voice_or_block(request, target=CastingTargetRef(kind=CastingTargetKind.PROFILE, profile_id=rule.profile_id), voice=rule.voice, origin=CastingDecisionOrigin.CASTING_RULE, source=CastingResolutionSource.EXPLICIT_RULE, rule=rule)


def _resolve_narrator(request: CastingRequest, inventory: CastingInventory) -> CastingResolution:
    scope_ids = {CastingScopeKind.NOVEL: request.novel_id, CastingScopeKind.VOLUME: request.volume_id, CastingScopeKind.CHAPTER: request.chapter_id}
    priority = {CastingScopeKind.CHAPTER: 3, CastingScopeKind.VOLUME: 2, CastingScopeKind.NOVEL: 1}
    selections = sorted((item for item in inventory.narrator_selections if item.novel_id == request.novel_id and scope_ids[item.scope_kind] is not None and item.scope_id == scope_ids[item.scope_kind]), key=lambda item: -priority[item.scope_kind])
    if not selections:
        return _unresolved(request, codes=("B_VOICE_MISSING",))
    selection = selections[0]
    source = {CastingScopeKind.CHAPTER: CastingResolutionSource.CHAPTER_NARRATOR, CastingScopeKind.VOLUME: CastingResolutionSource.VOLUME_NARRATOR, CastingScopeKind.NOVEL: CastingResolutionSource.NOVEL_NARRATOR}[selection.scope_kind]
    return _voice_or_block(request, target=CastingTargetRef(kind=CastingTargetKind.PROFILE, profile_id=selection.profile_id), voice=selection.voice, origin=CastingDecisionOrigin.NARRATOR_SETTING, source=source)


def resolve_casting(request: CastingRequest, inventory: CastingInventory) -> CastingResolution:
    """Resolve one segment without a generic-pool or narrator fallback."""
    if type(request) is not CastingRequest or type(inventory) is not CastingInventory:
        raise CastingInputError("resolve_casting requires frozen request/inventory")
    if any(item.novel_id != request.novel_id for group in (inventory.narrator_selections, inventory.character_bindings, inventory.anonymous_bindings, inventory.rules) for item in group):
        raise CastingInputError("casting inventory contains another novel")
    if request.segment_kind is SegmentKind.SYNTHETIC_PAUSE:
        return CastingResolution(speaker=request.speaker, segment_id=request.segment_id, source_local_hash=request.source_local_hash, decision=CastingDecision(candidate_targets=(), final_target=None, origin=CastingDecisionOrigin.NOT_APPLICABLE), source=CastingResolutionSource.NOT_APPLICABLE, resolved_voice=None, issues=())
    if request.speaker.kind is SpeakerKind.NARRATOR:
        return _resolve_narrator(request, inventory)
    rules = _matching_rules(request, inventory)
    if rules:
        return _resolve_explicit_rule(request, rules[0])
    if request.speaker.kind is SpeakerKind.CHARACTER:
        binding = next((item for item in inventory.character_bindings if item.character_id == request.speaker.character_id), None)
        if binding is not None:
            source = CastingResolutionSource.CHARACTER_DEDICATED if binding.policy is wire.CharacterVoiceBindingPolicy.DEDICATED else CastingResolutionSource.CHARACTER_INHERITED
            target = CastingTargetRef(kind=CastingTargetKind.CHARACTER_BINDING, binding_id=binding.binding_id, character_id=request.speaker.character_id)
            return _voice_or_block(request, target=target, voice=binding.voice, origin=CastingDecisionOrigin.CHARACTER_BINDING, source=source)
    elif request.speaker.kind is SpeakerKind.ANONYMOUS:
        binding = next((item for item in inventory.anonymous_bindings if item.anonymous_speaker_id == request.speaker.anonymous_speaker_id), None)
        if binding is not None:
            target = CastingTargetRef(kind=CastingTargetKind.ANONYMOUS_BINDING, anonymous_speaker_id=request.speaker.anonymous_speaker_id)
            return _voice_or_block(request, target=target, voice=binding.voice, origin=CastingDecisionOrigin.ANONYMOUS_BINDING, source=CastingResolutionSource.ANONYMOUS_BINDING)
    if request.speaker.kind is SpeakerKind.UNKNOWN:
        return _unresolved(request, codes=("B_SPEAKER_UNKNOWN",))
    return _unresolved(request, codes=("B_VOICE_MISSING",))


__all__ = [
    "CASTING_RESOLVER_VERSION",
    "AnonymousBindingSnapshot",
    "CastingAttributes",
    "CastingInputError",
    "CastingInventory",
    "CastingRequest",
    "CastingResolution",
    "CastingResolutionSource",
    "CastingRuleAction",
    "CastingRuleSnapshot",
    "CastingScopeKind",
    "CharacterBindingSnapshot",
    "NarratorSelectionSnapshot",
    "ResolvedVoiceSnapshot",
    "VoiceVersionSnapshot",
    "resolve_casting",
]
