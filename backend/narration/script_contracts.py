"""Frozen T3 narration script, source-range, identity, and state contracts.

This module is deliberately free of ORM, HTTP, model, worker, and media I/O.
It is the serial T3-A input consumed by segmentation, speaker attribution,
anonymous identity, casting, confidence, and script-review work packages.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Sequence
from uuid import RFC_4122, UUID, uuid5

from .contracts import (
    BLOCKER_CODES,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    WARNING_CODES,
    ConfidenceLevel,
    ReviewIssueSeverity,
    issue_severity,
)
from .fingerprints import canonical_json_bytes

NARRATION_SCRIPT_CONTRACT_VERSION: Final = "narration-script/1"
NARRATION_SCRIPT_ID_CONTRACT_VERSION: Final = "narration-script-id/1"
NARRATION_SOURCE_BLOCK_KEY_VERSION: Final = "narration-source-block/1"
ANONYMOUS_SPEAKER_STABLE_KEY_VERSION: Final = "anonymous-speaker-stable-key/1"
GROUP_SPEAKER_KEY_VERSION: Final = "group-speaker-key/1"
SPEAKER_TARGET_HASH_VERSION: Final = "narration-speaker-target/1"
OVERRIDE_PROVENANCE_VERSION: Final = "narration-override-provenance/1"
NARRATION_CASTING_DECISION_VERSION: Final = "narration-casting-decision/1"
NARRATION_SEGMENT_EVIDENCE_VERSION: Final = "narration-segment-evidence/1"
UTF16_OFFSET_UNIT: Final = "utf16_code_unit"
SOURCE_RANGE_SEMANTICS: Final = "half_open"

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_BLOCK_KEY = re.compile(r"^sb1_[a-f0-9]{64}$")
_ANONYMOUS_KEY = re.compile(r"^as1_[a-f0-9]{64}$")
_GROUP_KEY = re.compile(r"^grp1_[a-f0-9]{64}$")
_RULE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_DIGEST_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


class ScriptContractError(ValueError):
    """Raised when a narration script violates the frozen v1 contract."""


class ScriptVersionState(str, Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    FAILED = "failed"


class ScriptReviewPolicy(str, Enum):
    BLOCKERS_ONLY = "blockers_only"
    ALWAYS_REVIEW = "always_review"


class ScriptApprovalKind(str, Enum):
    AUTO_NO_BLOCKERS = "auto_no_blockers"
    MANUAL_AFTER_REVIEW = "manual_after_review"


class ApprovalActorType(str, Enum):
    OWNER = "owner"
    SYSTEM = "system"
    SERVICE = "service"


class SegmentKind(str, Enum):
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    MESSAGE = "message"
    LETTER = "letter"
    BROADCAST = "broadcast"
    PHONE = "phone"
    CHAPTER_TITLE = "chapter_title"
    SYNTHETIC_PAUSE = "synthetic_pause"


class SourceBlockKind(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    MESSAGE = "message"
    LETTER = "letter"
    BROADCAST = "broadcast"
    PHONE = "phone"
    SYNTHETIC = "synthetic"


class SpeakerKind(str, Enum):
    NARRATOR = "narrator"
    CHARACTER = "character"
    ANONYMOUS = "anonymous"
    GROUP = "group"
    UNKNOWN = "unknown"


class CastingTargetKind(str, Enum):
    CHARACTER_BINDING = "character_binding"
    ANONYMOUS_BINDING = "anonymous_binding"
    GENERIC_SLOT = "generic_slot"
    PROFILE = "profile"


class CastingDecisionOrigin(str, Enum):
    NARRATOR_SETTING = "narrator_setting"
    CHARACTER_BINDING = "character_binding"
    ANONYMOUS_BINDING = "anonymous_binding"
    CASTING_RULE = "casting_rule"
    MANUAL_OVERRIDE = "manual_override"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class OverrideKind(str, Enum):
    MANUAL_CURRENT = "manual_current"
    INHERITED = "inherited"


class AnonymousScopeKind(str, Enum):
    SCENE = "scene"
    CHAPTER = "chapter"
    NOVEL = "novel"


class AttributionOrigin(str, Enum):
    LOCAL_RULE = "local_rule"
    CLOUD_ASSISTED = "cloud_assisted"
    MANUAL_OVERRIDE = "manual_override"
    INHERITED_OVERRIDE = "inherited_override"


class Emotion(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    FEARFUL = "fearful"
    TENSE = "tense"


class Delivery(str, Enum):
    NORMAL = "normal"
    WHISPER = "whisper"
    SHOUT = "shout"
    INNER_MONOLOGUE = "inner_monologue"


class SceneBoundarySource(str, Enum):
    DOCUMENT_START = "document_start"
    MARKDOWN_HEADING = "markdown_heading"
    SCENE_SEPARATOR = "scene_separator"
    PARAGRAPH_RULE = "paragraph_rule"
    MANUAL = "manual"


SCRIPT_STATE_TRANSITIONS: Final[Mapping[ScriptVersionState, frozenset[ScriptVersionState]]] = (
    MappingProxyType(
        {
            ScriptVersionState.DRAFT: frozenset(
                {ScriptVersionState.ANALYZING, ScriptVersionState.FAILED}
            ),
            ScriptVersionState.ANALYZING: frozenset(
                {
                    ScriptVersionState.ANALYZED,
                    ScriptVersionState.REVIEW_REQUIRED,
                    ScriptVersionState.FAILED,
                }
            ),
            ScriptVersionState.ANALYZED: frozenset(
                {
                    ScriptVersionState.REVIEW_REQUIRED,
                    ScriptVersionState.APPROVED,
                    ScriptVersionState.FAILED,
                }
            ),
            ScriptVersionState.REVIEW_REQUIRED: frozenset(
                {ScriptVersionState.APPROVED, ScriptVersionState.FAILED}
            ),
            ScriptVersionState.APPROVED: frozenset(),
            ScriptVersionState.FAILED: frozenset(),
        }
    )
)

SOURCE_BOUND_SEGMENT_KINDS: Final[frozenset[SegmentKind]] = frozenset(
    {
        SegmentKind.NARRATION,
        SegmentKind.DIALOGUE,
        SegmentKind.INNER_MONOLOGUE,
        SegmentKind.MESSAGE,
        SegmentKind.LETTER,
        SegmentKind.BROADCAST,
        SegmentKind.PHONE,
    }
)
SYNTHETIC_SEGMENT_KINDS: Final[frozenset[SegmentKind]] = frozenset(
    {SegmentKind.CHAPTER_TITLE, SegmentKind.SYNTHETIC_PAUSE}
)


def _require_exact_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ScriptContractError(f"{field_name} must be an integer >= {minimum}")
    return value


def _require_exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ScriptContractError(f"{field_name} must be a boolean")
    return value


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not UUID:
        raise ScriptContractError(f"{field_name} must be a UUID")
    if value.variant != RFC_4122 or value.version not in {1, 2, 3, 4, 5}:
        raise ScriptContractError(
            f"{field_name} must be an RFC-4122 variant UUID v1-v5"
        )
    return value


def _require_enum(value: object, enum_type: type[Enum], *, field_name: str) -> Enum:
    if type(value) is not enum_type:
        raise ScriptContractError(f"{field_name} must be a {enum_type.__name__}")
    return value


def _require_text(
    value: object,
    *,
    field_name: str,
    minimum: int = 1,
    maximum: int | None = None,
    nfc: bool = False,
) -> str:
    if type(value) is not str or len(value) < minimum:
        raise ScriptContractError(f"{field_name} must be a string of length >= {minimum}")
    if maximum is not None and len(value) > maximum:
        raise ScriptContractError(f"{field_name} exceeds maximum length {maximum}")
    if nfc and value != unicodedata.normalize("NFC", value):
        raise ScriptContractError(f"{field_name} must be Unicode NFC")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ScriptContractError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


def _require_optional_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    nfc: bool = False,
) -> str | None:
    if value is None:
        return None
    return _require_text(
        value,
        field_name=field_name,
        maximum=maximum,
        nfc=nfc,
    )


def _require_utc_datetime(value: object, *, field_name: str) -> datetime:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ScriptContractError(f"{field_name} must be a UTC datetime")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ScriptContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field_name=field_name)


def _hash_payload(version: str, payload: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes({"schema_version": version, "payload": payload})
    ).hexdigest()


def text_sha256(text: str) -> str:
    _require_text(text, field_name="text", minimum=0)
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ScriptContractError("text contains an unpaired Unicode surrogate") from error
    return hashlib.sha256(encoded).hexdigest()


def utf16_length(text: str) -> int:
    _require_text(text, field_name="text", minimum=0)
    try:
        return len(text.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError as error:
        raise ScriptContractError("text contains an unpaired Unicode surrogate") from error


def _utf16_boundary_to_python_index(text: str, offset: int) -> int:
    _require_exact_int(offset, field_name="UTF-16 offset")
    units = 0
    for index, character in enumerate(text):
        if units == offset:
            return index
        width = 2 if ord(character) > 0xFFFF else 1
        if units < offset < units + width:
            raise ScriptContractError("UTF-16 offset splits a surrogate pair")
        units += width
    if units == offset:
        return len(text)
    raise ScriptContractError("UTF-16 offset is outside the source text")


@dataclass(frozen=True, slots=True)
class Utf16Range:
    start: int
    end_exclusive: int

    def __post_init__(self) -> None:
        _require_exact_int(self.start, field_name="UTF-16 range start")
        _require_exact_int(
            self.end_exclusive,
            field_name="UTF-16 range end_exclusive",
            minimum=self.start + 1,
        )

    @property
    def length(self) -> int:
        return self.end_exclusive - self.start


def utf16_slice(text: str, source_range: Utf16Range) -> str:
    if type(source_range) is not Utf16Range:
        raise ScriptContractError("source_range must be Utf16Range")
    utf16_length(text)
    start = _utf16_boundary_to_python_index(text, source_range.start)
    end = _utf16_boundary_to_python_index(text, source_range.end_exclusive)
    return text[start:end]


def normalize_identity_label(value: str) -> str:
    _require_text(value, field_name="identity label", maximum=160)
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized:
        raise ScriptContractError("identity label cannot normalize to empty")
    return normalized


def derive_source_block_key(
    *,
    script_version_id: UUID,
    block_kind: SourceBlockKind,
    paragraph_ordinal: int | None,
    block_hash: str,
    anchor_before_hash: str | None,
    anchor_after_hash: str | None,
) -> str:
    _require_uuid(script_version_id, field_name="script_version_id")
    _require_enum(block_kind, SourceBlockKind, field_name="block_kind")
    if paragraph_ordinal is not None:
        _require_exact_int(paragraph_ordinal, field_name="paragraph_ordinal")
    _require_sha256(block_hash, field_name="block_hash")
    _require_optional_sha256(anchor_before_hash, field_name="anchor_before_hash")
    _require_optional_sha256(anchor_after_hash, field_name="anchor_after_hash")
    digest = _hash_payload(
        NARRATION_SOURCE_BLOCK_KEY_VERSION,
        {
            "script_version_id": str(script_version_id),
            "block_kind": block_kind.value,
            "paragraph_ordinal": paragraph_ordinal,
            "block_hash": block_hash,
            "anchor_before_hash": anchor_before_hash,
            "anchor_after_hash": anchor_after_hash,
        },
    )
    return f"sb1_{digest}"


def derive_scene_id(
    *,
    script_version_id: UUID,
    ordinal: int,
    source_range: Utf16Range | None,
    local_hash: str,
) -> UUID:
    _require_uuid(script_version_id, field_name="script_version_id")
    _require_exact_int(ordinal, field_name="scene ordinal")
    if source_range is not None and type(source_range) is not Utf16Range:
        raise ScriptContractError("scene source_range must be Utf16Range or None")
    _require_sha256(local_hash, field_name="scene local_hash")
    name = canonical_json_bytes(
        {
            "schema_version": NARRATION_SCRIPT_ID_CONTRACT_VERSION,
            "kind": "scene",
            "ordinal": ordinal,
            "source_range": _range_payload(source_range),
            "local_hash": local_hash,
        }
    ).decode("utf-8")
    return uuid5(script_version_id, name)


def derive_segment_id(
    *,
    script_version_id: UUID,
    ordinal: int,
    source_block_key: str,
    segment_ordinal_in_block: int,
    local_hash: str,
) -> UUID:
    _require_uuid(script_version_id, field_name="script_version_id")
    _require_exact_int(ordinal, field_name="segment ordinal")
    if type(source_block_key) is not str or _SOURCE_BLOCK_KEY.fullmatch(source_block_key) is None:
        raise ScriptContractError("source_block_key does not match narration-source-block/1")
    _require_exact_int(
        segment_ordinal_in_block, field_name="segment_ordinal_in_block"
    )
    _require_sha256(local_hash, field_name="segment local_hash")
    name = canonical_json_bytes(
        {
            "schema_version": NARRATION_SCRIPT_ID_CONTRACT_VERSION,
            "kind": "segment",
            "ordinal": ordinal,
            "source_block_key": source_block_key,
            "segment_ordinal_in_block": segment_ordinal_in_block,
            "local_hash": local_hash,
        }
    ).decode("utf-8")
    return uuid5(script_version_id, name)


def derive_anonymous_stable_key(
    *,
    novel_id: UUID,
    scope_kind: AnonymousScopeKind,
    scope_id: UUID,
    label: str,
    evidence_hash: str,
) -> str:
    _require_uuid(novel_id, field_name="novel_id")
    _require_enum(scope_kind, AnonymousScopeKind, field_name="scope_kind")
    _require_uuid(scope_id, field_name="scope_id")
    _require_sha256(evidence_hash, field_name="evidence_hash")
    digest = _hash_payload(
        ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
        {
            "novel_id": str(novel_id),
            "scope_kind": scope_kind.value,
            "scope_id": str(scope_id),
            "normalized_label": normalize_identity_label(label),
            "evidence_hash": evidence_hash,
        },
    )
    return f"as1_{digest}"


def derive_anonymous_speaker_id(*, novel_id: UUID, stable_key: str) -> UUID:
    _require_uuid(novel_id, field_name="novel_id")
    if type(stable_key) is not str or _ANONYMOUS_KEY.fullmatch(stable_key) is None:
        raise ScriptContractError("stable_key does not match anonymous-speaker-stable-key/1")
    return uuid5(novel_id, f"{ANONYMOUS_SPEAKER_STABLE_KEY_VERSION}:{stable_key}")


def derive_group_key(
    *, novel_id: UUID, scene_id: UUID | None, label: str, evidence_hash: str
) -> str:
    _require_uuid(novel_id, field_name="novel_id")
    if scene_id is not None:
        _require_uuid(scene_id, field_name="scene_id")
    _require_sha256(evidence_hash, field_name="evidence_hash")
    digest = _hash_payload(
        GROUP_SPEAKER_KEY_VERSION,
        {
            "novel_id": str(novel_id),
            "scene_id": str(scene_id) if scene_id else None,
            "normalized_label": normalize_identity_label(label),
            "evidence_hash": evidence_hash,
        },
    )
    return f"grp1_{digest}"


@dataclass(frozen=True, slots=True)
class SpeakerRef:
    kind: SpeakerKind
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None
    group_key: str | None = None

    def __post_init__(self) -> None:
        _require_enum(self.kind, SpeakerKind, field_name="speaker kind")
        if self.character_id is not None:
            _require_uuid(self.character_id, field_name="character_id")
        if self.anonymous_speaker_id is not None:
            _require_uuid(
                self.anonymous_speaker_id, field_name="anonymous_speaker_id"
            )
        if self.group_key is not None and (
            type(self.group_key) is not str
            or _GROUP_KEY.fullmatch(self.group_key) is None
        ):
            raise ScriptContractError("group_key does not match group-speaker-key/1")
        shape = (
            self.character_id is not None,
            self.anonymous_speaker_id is not None,
            self.group_key is not None,
        )
        expected = {
            SpeakerKind.NARRATOR: (False, False, False),
            SpeakerKind.CHARACTER: (True, False, False),
            SpeakerKind.ANONYMOUS: (False, True, False),
            SpeakerKind.GROUP: (False, False, True),
            SpeakerKind.UNKNOWN: (False, False, False),
        }[self.kind]
        if shape != expected:
            raise ScriptContractError(
                f"speaker reference fields do not match kind {self.kind.value}"
            )


@dataclass(frozen=True, slots=True)
class CastingTargetRef:
    kind: CastingTargetKind
    binding_id: UUID | None = None
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None
    pool_id: UUID | None = None
    slot_id: UUID | None = None
    profile_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_enum(self.kind, CastingTargetKind, field_name="casting target kind")
        for field_name, value in (
            ("casting binding_id", self.binding_id),
            ("casting character_id", self.character_id),
            ("casting anonymous_speaker_id", self.anonymous_speaker_id),
            ("casting pool_id", self.pool_id),
            ("casting slot_id", self.slot_id),
            ("casting profile_id", self.profile_id),
        ):
            if value is not None:
                _require_uuid(value, field_name=field_name)
        shape = (
            self.binding_id is not None,
            self.character_id is not None,
            self.anonymous_speaker_id is not None,
            self.pool_id is not None,
            self.slot_id is not None,
            self.profile_id is not None,
        )
        expected = {
            CastingTargetKind.CHARACTER_BINDING: (
                True,
                True,
                False,
                False,
                False,
                False,
            ),
            CastingTargetKind.ANONYMOUS_BINDING: (
                False,
                False,
                True,
                False,
                False,
                False,
            ),
            CastingTargetKind.GENERIC_SLOT: (
                False,
                False,
                False,
                True,
                True,
                False,
            ),
            CastingTargetKind.PROFILE: (
                False,
                False,
                False,
                False,
                False,
                True,
            ),
        }[self.kind]
        if shape != expected:
            raise ScriptContractError(
                f"casting fields do not match target kind {self.kind.value}"
            )


def _casting_target_payload(target: CastingTargetRef) -> dict[str, object]:
    return {
        "kind": target.kind.value,
        "binding_id": str(target.binding_id) if target.binding_id else None,
        "character_id": str(target.character_id) if target.character_id else None,
        "anonymous_speaker_id": (
            str(target.anonymous_speaker_id)
            if target.anonymous_speaker_id
            else None
        ),
        "pool_id": str(target.pool_id) if target.pool_id else None,
        "slot_id": str(target.slot_id) if target.slot_id else None,
        "profile_id": str(target.profile_id) if target.profile_id else None,
    }


@dataclass(frozen=True, slots=True)
class CastingDecision:
    candidate_targets: tuple[CastingTargetRef, ...]
    final_target: CastingTargetRef | None
    origin: CastingDecisionOrigin
    rule_id: UUID | None = None
    rule_version: int | None = None

    def __post_init__(self) -> None:
        if type(self.candidate_targets) is not tuple or not all(
            type(item) is CastingTargetRef for item in self.candidate_targets
        ):
            raise ScriptContractError(
                "casting candidate_targets must be a tuple of CastingTargetRef"
            )
        if len(self.candidate_targets) > 32:
            raise ScriptContractError("casting candidate_targets exceeds 32")
        candidate_payloads = [
            canonical_json_bytes(_casting_target_payload(item))
            for item in self.candidate_targets
        ]
        if len(candidate_payloads) != len(set(candidate_payloads)):
            raise ScriptContractError("casting candidate_targets must be unique")
        if candidate_payloads != sorted(candidate_payloads):
            raise ScriptContractError(
                "casting candidate_targets must use canonical order"
            )
        if self.final_target is not None and type(
            self.final_target
        ) is not CastingTargetRef:
            raise ScriptContractError(
                "casting final_target must be CastingTargetRef or None"
            )
        _require_enum(
            self.origin, CastingDecisionOrigin, field_name="casting decision origin"
        )
        unresolved = self.origin in {
            CastingDecisionOrigin.UNRESOLVED,
            CastingDecisionOrigin.NOT_APPLICABLE,
        }
        if unresolved != (self.final_target is None):
            raise ScriptContractError(
                "casting final_target shape differs from its decision origin"
            )
        if self.final_target is not None and self.final_target not in (
            self.candidate_targets
        ):
            raise ScriptContractError(
                "casting final_target must be one of candidate_targets"
            )
        if (
            self.origin is CastingDecisionOrigin.NOT_APPLICABLE
            and self.candidate_targets
        ):
            raise ScriptContractError(
                "not_applicable casting cannot carry candidate targets"
            )
        if self.rule_id is not None:
            _require_uuid(self.rule_id, field_name="casting rule_id")
        if self.rule_version is not None:
            _require_exact_int(
                self.rule_version, field_name="casting rule_version", minimum=1
            )
        if self.origin is CastingDecisionOrigin.CASTING_RULE:
            if self.rule_id is None or self.rule_version is None:
                raise ScriptContractError(
                    "casting_rule origin requires rule_id and rule_version"
                )
        elif self.rule_id is not None or self.rule_version is not None:
            raise ScriptContractError(
                "only casting_rule origin may carry rule identity"
            )
        expected_target_kind = {
            CastingDecisionOrigin.NARRATOR_SETTING: CastingTargetKind.PROFILE,
            CastingDecisionOrigin.CHARACTER_BINDING: (
                CastingTargetKind.CHARACTER_BINDING
            ),
            CastingDecisionOrigin.ANONYMOUS_BINDING: (
                CastingTargetKind.ANONYMOUS_BINDING
            ),
        }.get(self.origin)
        if (
            expected_target_kind is not None
            and self.final_target is not None
            and self.final_target.kind is not expected_target_kind
        ):
            raise ScriptContractError(
                "casting final target kind differs from its decision origin"
            )


def speaker_target_hash(speaker: SpeakerRef, casting: CastingDecision) -> str:
    if type(speaker) is not SpeakerRef or type(casting) is not CastingDecision:
        raise ScriptContractError(
            "speaker_target_hash requires SpeakerRef and CastingDecision"
        )
    return _hash_payload(
        SPEAKER_TARGET_HASH_VERSION,
        {
            "speaker": {
                "kind": speaker.kind.value,
                "character_id": (
                    str(speaker.character_id) if speaker.character_id else None
                ),
                "anonymous_speaker_id": (
                    str(speaker.anonymous_speaker_id)
                    if speaker.anonymous_speaker_id
                    else None
                ),
                "group_key": speaker.group_key,
            },
            "final_target": (
                _casting_target_payload(casting.final_target)
                if casting.final_target
                else None
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class OverrideProvenance:
    kind: OverrideKind
    action_id: UUID
    owner_actor_id: str
    recorded_at: datetime
    source_local_hash: str
    source_anchor_before_hash: str | None
    source_anchor_after_hash: str | None
    speaker_target_hash: str
    source_script_version_id: UUID | None = None
    source_segment_id: UUID | None = None
    source_immutable_hash: str | None = None
    contract_version: str = OVERRIDE_PROVENANCE_VERSION

    def __post_init__(self) -> None:
        _require_enum(self.kind, OverrideKind, field_name="override kind")
        _require_uuid(self.action_id, field_name="override action_id")
        _require_text(
            self.owner_actor_id,
            field_name="override owner_actor_id",
            maximum=120,
            nfc=True,
        )
        _require_utc_datetime(
            self.recorded_at, field_name="override recorded_at"
        )
        _require_sha256(
            self.source_local_hash, field_name="override source_local_hash"
        )
        _require_optional_sha256(
            self.source_anchor_before_hash,
            field_name="override source_anchor_before_hash",
        )
        _require_optional_sha256(
            self.source_anchor_after_hash,
            field_name="override source_anchor_after_hash",
        )
        _require_sha256(
            self.speaker_target_hash,
            field_name="override speaker_target_hash",
        )
        for field_name, value in (
            ("override source_script_version_id", self.source_script_version_id),
            ("override source_segment_id", self.source_segment_id),
        ):
            if value is not None:
                _require_uuid(value, field_name=field_name)
        _require_optional_sha256(
            self.source_immutable_hash,
            field_name="override source_immutable_hash",
        )
        inherited_shape = all(
            value is not None
            for value in (
                self.source_script_version_id,
                self.source_segment_id,
                self.source_immutable_hash,
            )
        )
        if self.kind is OverrideKind.INHERITED and not inherited_shape:
            raise ScriptContractError(
                "inherited override requires source version, segment, and immutable hash"
            )
        if self.kind is OverrideKind.MANUAL_CURRENT and any(
            value is not None
            for value in (
                self.source_script_version_id,
                self.source_segment_id,
                self.source_immutable_hash,
            )
        ):
            raise ScriptContractError(
                "manual_current override cannot carry inherited source identity"
            )
        if self.contract_version != OVERRIDE_PROVENANCE_VERSION:
            raise ScriptContractError("unknown override provenance version")


@dataclass(frozen=True, slots=True)
class AttributionEvidence:
    origin: AttributionOrigin
    rule_codes: tuple[str, ...] = ()
    candidate_character_ids: tuple[UUID, ...] = ()
    consent_id: UUID | None = None
    model_run_id: UUID | None = None
    input_digest_key_id: str | None = None
    input_digest: str | None = None
    output_digest: str | None = None
    override_provenance: OverrideProvenance | None = None

    def __post_init__(self) -> None:
        _require_enum(self.origin, AttributionOrigin, field_name="attribution origin")
        if type(self.rule_codes) is not tuple:
            raise ScriptContractError("rule_codes must be a tuple")
        if len(self.rule_codes) > 16 or len(set(self.rule_codes)) != len(self.rule_codes):
            raise ScriptContractError("rule_codes must contain at most 16 unique values")
        if self.rule_codes != tuple(sorted(self.rule_codes)):
            raise ScriptContractError("rule_codes must use canonical order")
        for code in self.rule_codes:
            if type(code) is not str or _RULE_CODE.fullmatch(code) is None:
                raise ScriptContractError("rule_codes contain an invalid value")
        if type(self.candidate_character_ids) is not tuple:
            raise ScriptContractError("candidate_character_ids must be a tuple")
        if len(self.candidate_character_ids) > 32 or len(
            set(self.candidate_character_ids)
        ) != len(self.candidate_character_ids):
            raise ScriptContractError(
                "candidate_character_ids must contain at most 32 unique values"
            )
        if self.candidate_character_ids != tuple(
            sorted(self.candidate_character_ids, key=lambda value: str(value))
        ):
            raise ScriptContractError(
                "candidate_character_ids must use canonical order"
            )
        for character_id in self.candidate_character_ids:
            _require_uuid(character_id, field_name="candidate_character_id")
        if self.consent_id is not None:
            _require_uuid(self.consent_id, field_name="consent_id")
        if self.model_run_id is not None:
            _require_uuid(self.model_run_id, field_name="model_run_id")
        if self.input_digest_key_id is not None and (
            type(self.input_digest_key_id) is not str
            or _DIGEST_KEY_ID.fullmatch(self.input_digest_key_id) is None
        ):
            raise ScriptContractError("input_digest_key_id is not a stable key id")
        _require_optional_sha256(self.input_digest, field_name="input_digest")
        _require_optional_sha256(self.output_digest, field_name="output_digest")
        if self.override_provenance is not None and type(
            self.override_provenance
        ) is not OverrideProvenance:
            raise ScriptContractError(
                "override_provenance must be OverrideProvenance or None"
            )
        if self.origin is AttributionOrigin.LOCAL_RULE and not self.rule_codes:
            raise ScriptContractError("local_rule attribution requires rule_codes")
        if self.origin is AttributionOrigin.CLOUD_ASSISTED:
            if any(
                value is None
                for value in (
                    self.consent_id,
                    self.model_run_id,
                    self.input_digest_key_id,
                    self.input_digest,
                    self.output_digest,
                )
            ):
                raise ScriptContractError(
                    "cloud_assisted attribution requires consent, model run, "
                    "and keyed input/output digest evidence"
                )
        elif any(
            value is not None
            for value in (
                self.consent_id,
                self.model_run_id,
                self.input_digest_key_id,
                self.input_digest,
                self.output_digest,
            )
        ):
            raise ScriptContractError(
                "only cloud_assisted attribution may carry cloud call evidence"
            )
        override_origin = self.origin in {
            AttributionOrigin.MANUAL_OVERRIDE,
            AttributionOrigin.INHERITED_OVERRIDE,
        }
        if override_origin != (self.override_provenance is not None):
            raise ScriptContractError(
                "manual/inherited attribution requires override_provenance"
            )


@dataclass(frozen=True, slots=True)
class CloudAuthorityRecord:
    """Server-verified cloud evidence bound to one exact segment decision."""

    attribution: AttributionEvidence
    model_fingerprint: str
    segment_id: UUID
    source_local_hash: str
    speaker_target_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.attribution) is not AttributionEvidence
            or self.attribution.origin is not AttributionOrigin.CLOUD_ASSISTED
        ):
            raise ScriptContractError(
                "cloud authority requires cloud_assisted attribution evidence"
            )
        _require_sha256(
            self.model_fingerprint,
            field_name="cloud authority model_fingerprint",
        )
        _require_uuid(self.segment_id, field_name="cloud authority segment_id")
        _require_sha256(
            self.source_local_hash,
            field_name="cloud authority source_local_hash",
        )
        _require_sha256(
            self.speaker_target_hash,
            field_name="cloud authority speaker_target_hash",
        )


@dataclass(frozen=True, slots=True)
class CastingRuleAuthorityRecord:
    """Server-owned rule outcome bound to one exact segment decision."""

    decision: CastingDecision
    segment_id: UUID
    source_local_hash: str
    speaker_target_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.decision) is not CastingDecision
            or self.decision.origin is not CastingDecisionOrigin.CASTING_RULE
        ):
            raise ScriptContractError(
                "casting rule authority requires a casting_rule decision"
            )
        _require_uuid(
            self.segment_id,
            field_name="casting rule authority segment_id",
        )
        _require_sha256(
            self.source_local_hash,
            field_name="casting rule authority source_local_hash",
        )
        _require_sha256(
            self.speaker_target_hash,
            field_name="casting rule authority speaker_target_hash",
        )


@dataclass(frozen=True, slots=True)
class AnonymousSpeakerIdentity:
    anonymous_speaker_id: UUID
    stable_key_algorithm: str
    stable_key: str
    display_name: str
    scope_kind: AnonymousScopeKind
    scope_id: UUID
    confidence: ConfidenceLevel

    def __post_init__(self) -> None:
        _require_uuid(
            self.anonymous_speaker_id, field_name="anonymous_speaker_id"
        )
        if self.stable_key_algorithm != ANONYMOUS_SPEAKER_STABLE_KEY_VERSION:
            raise ScriptContractError("unknown anonymous stable-key algorithm")
        if type(self.stable_key) is not str or _ANONYMOUS_KEY.fullmatch(
            self.stable_key
        ) is None:
            raise ScriptContractError(
                "stable_key does not match anonymous-speaker-stable-key/1"
            )
        _require_text(
            self.display_name,
            field_name="anonymous display_name",
            maximum=160,
            nfc=True,
        )
        _require_enum(self.scope_kind, AnonymousScopeKind, field_name="scope_kind")
        _require_uuid(self.scope_id, field_name="anonymous scope_id")
        _require_enum(self.confidence, ConfidenceLevel, field_name="confidence")


@dataclass(frozen=True, slots=True)
class SceneContract:
    scene_id: UUID
    ordinal: int
    source_range_utf16: Utf16Range | None
    boundary_source: SceneBoundarySource
    local_hash: str
    title: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.scene_id, field_name="scene_id")
        _require_exact_int(self.ordinal, field_name="scene ordinal")
        if self.source_range_utf16 is not None and type(
            self.source_range_utf16
        ) is not Utf16Range:
            raise ScriptContractError(
                "scene source_range_utf16 must be Utf16Range or None"
            )
        _require_enum(
            self.boundary_source,
            SceneBoundarySource,
            field_name="scene boundary_source",
        )
        _require_sha256(self.local_hash, field_name="scene local_hash")
        _require_optional_text(
            self.title, field_name="scene title", maximum=240, nfc=True
        )


@dataclass(frozen=True, slots=True)
class SegmentContract:
    segment_id: UUID
    ordinal: int
    scene_id: UUID | None
    segment_kind: SegmentKind
    source_block_kind: SourceBlockKind
    paragraph_ordinal: int | None
    segment_ordinal_in_block: int
    source_block_key: str
    source_block_hash: str
    source_range_utf16: Utf16Range | None
    source_text: str
    spoken_text: str
    local_hash: str
    anchor_before_hash: str | None
    anchor_after_hash: str | None
    inheritance_anchor_before_hash: str | None
    inheritance_anchor_after_hash: str | None
    speaker: SpeakerRef
    casting: CastingDecision
    confidence: ConfidenceLevel
    emotion: Emotion
    emotion_confidence: ConfidenceLevel
    delivery: Delivery
    attribution: AttributionEvidence
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    manual_override: bool = False

    def __post_init__(self) -> None:
        _require_uuid(self.segment_id, field_name="segment_id")
        _require_exact_int(self.ordinal, field_name="segment ordinal")
        if self.scene_id is not None:
            _require_uuid(self.scene_id, field_name="scene_id")
        _require_enum(self.segment_kind, SegmentKind, field_name="segment_kind")
        _require_enum(
            self.source_block_kind, SourceBlockKind, field_name="source_block_kind"
        )
        if self.paragraph_ordinal is not None:
            _require_exact_int(
                self.paragraph_ordinal, field_name="paragraph_ordinal"
            )
        _require_exact_int(
            self.segment_ordinal_in_block,
            field_name="segment_ordinal_in_block",
        )
        if type(self.source_block_key) is not str or _SOURCE_BLOCK_KEY.fullmatch(
            self.source_block_key
        ) is None:
            raise ScriptContractError(
                "source_block_key does not match narration-source-block/1"
            )
        _require_sha256(self.source_block_hash, field_name="source_block_hash")
        if self.source_range_utf16 is not None and type(
            self.source_range_utf16
        ) is not Utf16Range:
            raise ScriptContractError(
                "segment source_range_utf16 must be Utf16Range or None"
            )
        _require_text(self.source_text, field_name="source_text", minimum=0)
        _require_text(
            self.spoken_text,
            field_name="spoken_text",
            minimum=0,
            nfc=True,
        )
        _require_sha256(self.local_hash, field_name="segment local_hash")
        if self.local_hash != text_sha256(self.source_text):
            raise ScriptContractError("segment local_hash does not match source_text")
        _require_optional_sha256(
            self.anchor_before_hash, field_name="anchor_before_hash"
        )
        _require_optional_sha256(
            self.anchor_after_hash, field_name="anchor_after_hash"
        )
        _require_optional_sha256(
            self.inheritance_anchor_before_hash,
            field_name="inheritance_anchor_before_hash",
        )
        _require_optional_sha256(
            self.inheritance_anchor_after_hash,
            field_name="inheritance_anchor_after_hash",
        )
        if type(self.speaker) is not SpeakerRef:
            raise ScriptContractError("speaker must be SpeakerRef")
        if type(self.casting) is not CastingDecision:
            raise ScriptContractError("casting must be CastingDecision")
        _require_enum(self.confidence, ConfidenceLevel, field_name="confidence")
        _require_enum(self.emotion, Emotion, field_name="emotion")
        _require_enum(
            self.emotion_confidence,
            ConfidenceLevel,
            field_name="emotion_confidence",
        )
        _require_enum(self.delivery, Delivery, field_name="delivery")
        if type(self.attribution) is not AttributionEvidence:
            raise ScriptContractError("attribution must be AttributionEvidence")
        _require_exact_int(self.pause_before_ms, field_name="pause_before_ms")
        _require_exact_int(self.pause_after_ms, field_name="pause_after_ms")
        _require_exact_bool(self.manual_override, field_name="manual_override")

        if self.segment_kind in SOURCE_BOUND_SEGMENT_KINDS:
            if self.source_block_kind is SourceBlockKind.SYNTHETIC:
                raise ScriptContractError(
                    "source-bound segment cannot use source_block_kind=synthetic"
                )
            if self.source_range_utf16 is None or not self.source_text:
                raise ScriptContractError(
                    "source-bound segment requires a non-empty UTF-16 source range"
                )
            if utf16_length(self.source_text) != self.source_range_utf16.length:
                raise ScriptContractError(
                    "source_text UTF-16 length differs from source range"
                )
            if not self.spoken_text:
                raise ScriptContractError("source-bound segment requires spoken_text")
            if self.paragraph_ordinal is None:
                raise ScriptContractError(
                    "source-bound segment requires paragraph_ordinal"
                )
        elif self.segment_kind in SYNTHETIC_SEGMENT_KINDS:
            if self.source_range_utf16 is not None:
                raise ScriptContractError(
                    "synthetic segment must not fabricate a source range"
                )
            if self.source_block_kind is not SourceBlockKind.SYNTHETIC:
                raise ScriptContractError(
                    "synthetic segment requires source_block_kind=synthetic"
                )
            if self.segment_kind is SegmentKind.CHAPTER_TITLE:
                if not self.source_text or not self.spoken_text:
                    raise ScriptContractError(
                        "chapter_title requires source_text and spoken_text"
                    )
            elif self.source_text or self.spoken_text or self.pause_after_ms <= 0:
                raise ScriptContractError(
                    "synthetic_pause requires empty text and pause_after_ms > 0"
                )

        if self.segment_kind in {
            SegmentKind.CHAPTER_TITLE,
            SegmentKind.SYNTHETIC_PAUSE,
        } and self.speaker.kind is not SpeakerKind.NARRATOR:
            raise ScriptContractError("synthetic/title segments use narrator identity")
        if self.segment_kind is SegmentKind.SYNTHETIC_PAUSE:
            if self.casting.origin is not CastingDecisionOrigin.NOT_APPLICABLE:
                raise ScriptContractError(
                    "synthetic_pause casting must be not_applicable"
                )
        elif self.casting.origin is CastingDecisionOrigin.NOT_APPLICABLE:
            raise ScriptContractError(
                "only synthetic_pause casting may be not_applicable"
            )
        if (
            self.speaker.kind is SpeakerKind.UNKNOWN
            and self.casting.origin is not CastingDecisionOrigin.UNRESOLVED
        ):
            raise ScriptContractError("unknown speaker casting must be unresolved")
        expected_speaker_kind = {
            CastingDecisionOrigin.NARRATOR_SETTING: SpeakerKind.NARRATOR,
            CastingDecisionOrigin.CHARACTER_BINDING: SpeakerKind.CHARACTER,
            CastingDecisionOrigin.ANONYMOUS_BINDING: SpeakerKind.ANONYMOUS,
        }.get(self.casting.origin)
        if (
            expected_speaker_kind is not None
            and self.speaker.kind is not expected_speaker_kind
        ):
            raise ScriptContractError(
                "casting decision origin differs from speaker identity"
            )
        final_target = self.casting.final_target
        if final_target is not None:
            if (
                final_target.kind is CastingTargetKind.CHARACTER_BINDING
                and (
                    self.speaker.kind is not SpeakerKind.CHARACTER
                    or final_target.character_id != self.speaker.character_id
                )
            ):
                raise ScriptContractError(
                    "character binding target differs from speaker identity"
                )
            if (
                final_target.kind is CastingTargetKind.ANONYMOUS_BINDING
                and (
                    self.speaker.kind is not SpeakerKind.ANONYMOUS
                    or final_target.anonymous_speaker_id
                    != self.speaker.anonymous_speaker_id
                )
            ):
                raise ScriptContractError(
                    "anonymous binding target differs from speaker identity"
                )
        manual_origin = self.attribution.origin in {
            AttributionOrigin.MANUAL_OVERRIDE,
            AttributionOrigin.INHERITED_OVERRIDE,
        }
        if (
            self.casting.origin is CastingDecisionOrigin.MANUAL_OVERRIDE
            and not manual_origin
        ):
            raise ScriptContractError(
                "manual casting requires manual/inherited attribution provenance"
            )
        if self.manual_override is not manual_origin:
            raise ScriptContractError(
                "manual_override must match manual/inherited attribution origin"
            )
        provenance = self.attribution.override_provenance
        if provenance is not None:
            expected_kind = (
                OverrideKind.MANUAL_CURRENT
                if self.attribution.origin is AttributionOrigin.MANUAL_OVERRIDE
                else OverrideKind.INHERITED
            )
            if provenance.kind is not expected_kind:
                raise ScriptContractError(
                    "override provenance kind differs from attribution origin"
                )
            if provenance.source_local_hash != self.local_hash:
                raise ScriptContractError(
                    "override source local hash differs from current segment"
                )
            if (
                provenance.source_anchor_before_hash
                != self.inheritance_anchor_before_hash
                or provenance.source_anchor_after_hash
                != self.inheritance_anchor_after_hash
            ):
                raise ScriptContractError(
                    "override unique anchors differ from current segment"
                )
            if provenance.speaker_target_hash != speaker_target_hash(
                self.speaker, self.casting
            ):
                raise ScriptContractError(
                    "override speaker/casting target digest differs"
                )


@dataclass(frozen=True, slots=True)
class ScriptIssueContract:
    code: str
    severity: ReviewIssueSeverity
    segment_id: UUID | None = None
    evidence_summary: str | None = None
    evidence_digest: str | None = None
    taxonomy_version: str = NARRATION_REVIEW_TAXONOMY_VERSION

    def __post_init__(self) -> None:
        expected = issue_severity(self.code)
        if type(self.severity) is not ReviewIssueSeverity or self.severity is not expected:
            raise ScriptContractError(
                f"severity for {self.code} is server-owned and must be {expected.value}"
            )
        if self.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
            raise ScriptContractError("unknown narration review taxonomy version")
        if self.segment_id is not None:
            _require_uuid(self.segment_id, field_name="issue segment_id")
        _require_optional_text(
            self.evidence_summary,
            field_name="issue evidence_summary",
            maximum=500,
            nfc=True,
        )
        _require_optional_sha256(
            self.evidence_digest, field_name="issue evidence_digest"
        )
        if self.evidence_summary is not None and self.evidence_digest is None:
            raise ScriptContractError(
                "issue evidence_summary requires its keyed evidence_digest"
            )


@dataclass(frozen=True, slots=True)
class ScriptApproval:
    kind: ScriptApprovalKind
    request_id: UUID
    actor_type: ApprovalActorType
    actor_id: str
    approved_at: datetime

    def __post_init__(self) -> None:
        _require_enum(self.kind, ScriptApprovalKind, field_name="approval kind")
        _require_uuid(self.request_id, field_name="approval request_id")
        _require_enum(
            self.actor_type, ApprovalActorType, field_name="approval actor_type"
        )
        _require_text(
            self.actor_id,
            field_name="approval actor_id",
            maximum=120,
            nfc=True,
        )
        _require_utc_datetime(self.approved_at, field_name="approved_at")
        if self.kind is ScriptApprovalKind.AUTO_NO_BLOCKERS and self.actor_type not in {
            ApprovalActorType.SYSTEM,
            ApprovalActorType.SERVICE,
        }:
            raise ScriptContractError(
                "auto_no_blockers requires a system or service actor"
            )
        if (
            self.kind is ScriptApprovalKind.MANUAL_AFTER_REVIEW
            and self.actor_type is not ApprovalActorType.OWNER
        ):
            raise ScriptContractError("manual_after_review requires the owner actor")


@dataclass(frozen=True, slots=True)
class ScriptAuthorityContext:
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    script_id: UUID
    script_version_id: UUID
    version_number: int
    state: ScriptVersionState
    effective_policy: ScriptReviewPolicy
    analyzer_fingerprint: str
    rules_fingerprint: str
    settings_fingerprint: str
    requested_model_fingerprint: str | None
    actual_model_fingerprint: str | None
    approval: ScriptApproval | None
    parent_version_ids: frozenset[UUID] = frozenset()
    manual_review_parent_ids: frozenset[UUID] = frozenset()
    non_review_parent_ids: frozenset[UUID] = frozenset()
    character_ids: frozenset[UUID] = frozenset()
    anonymous_speakers: frozenset[AnonymousSpeakerIdentity] = frozenset()
    verified_historical_anonymous_ids: frozenset[UUID] = frozenset()
    group_keys: frozenset[str] = frozenset()
    casting_targets: frozenset[CastingTargetRef] = frozenset()
    casting_rule_records: frozenset[CastingRuleAuthorityRecord] = frozenset()
    cloud_records: frozenset[CloudAuthorityRecord] = frozenset()
    override_provenances: frozenset[OverrideProvenance] = frozenset()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("authority novel_id", self.novel_id),
            ("authority document_id", self.document_id),
            ("authority revision_id", self.revision_id),
            ("authority script_id", self.script_id),
            ("authority script_version_id", self.script_version_id),
        ):
            _require_uuid(value, field_name=field_name)
        _require_exact_int(
            self.version_number,
            field_name="authority version_number",
            minimum=1,
        )
        _require_enum(self.state, ScriptVersionState, field_name="authority state")
        _require_enum(
            self.effective_policy,
            ScriptReviewPolicy,
            field_name="authority effective_policy",
        )
        for field_name, value in (
            ("authority analyzer_fingerprint", self.analyzer_fingerprint),
            ("authority rules_fingerprint", self.rules_fingerprint),
            ("authority settings_fingerprint", self.settings_fingerprint),
        ):
            _require_sha256(value, field_name=field_name)
        _require_optional_sha256(
            self.requested_model_fingerprint,
            field_name="authority requested_model_fingerprint",
        )
        _require_optional_sha256(
            self.actual_model_fingerprint,
            field_name="authority actual_model_fingerprint",
        )
        if (self.requested_model_fingerprint is None) != (
            self.actual_model_fingerprint is None
        ) or (
            self.requested_model_fingerprint is not None
            and self.requested_model_fingerprint
            != self.actual_model_fingerprint
        ):
            raise ScriptContractError(
                "authority requested/actual model fingerprints must match"
            )
        if self.approval is not None and type(self.approval) is not ScriptApproval:
            raise ScriptContractError(
                "authority approval must be ScriptApproval or None"
            )
        if (self.state is ScriptVersionState.APPROVED) != (
            self.approval is not None
        ):
            raise ScriptContractError(
                "authority approval presence must match approved state"
            )
        uuid_sets = (
            "parent_version_ids",
            "manual_review_parent_ids",
            "non_review_parent_ids",
            "character_ids",
            "verified_historical_anonymous_ids",
        )
        for field_name in uuid_sets:
            values = getattr(self, field_name)
            if type(values) is not frozenset:
                raise ScriptContractError(
                    f"authority {field_name} must be a frozenset"
                )
            for value in values:
                _require_uuid(value, field_name=f"authority {field_name} item")
        if self.manual_review_parent_ids & self.non_review_parent_ids:
            raise ScriptContractError(
                "authority parent review classifications must be disjoint"
            )
        if (
            self.manual_review_parent_ids | self.non_review_parent_ids
            != self.parent_version_ids
        ):
            raise ScriptContractError(
                "authority must classify every parent as manual-review or "
                "verified non-review"
            )
        typed_sets = (
            ("anonymous_speakers", AnonymousSpeakerIdentity),
            ("casting_targets", CastingTargetRef),
            ("casting_rule_records", CastingRuleAuthorityRecord),
            ("cloud_records", CloudAuthorityRecord),
            ("override_provenances", OverrideProvenance),
        )
        for field_name, expected_type in typed_sets:
            values = getattr(self, field_name)
            if type(values) is not frozenset or not all(
                type(value) is expected_type for value in values
            ):
                raise ScriptContractError(
                    f"authority {field_name} must be a frozenset of "
                    f"{expected_type.__name__}"
                )
        anonymous_ids = {
            identity.anonymous_speaker_id
            for identity in self.anonymous_speakers
        }
        if len(anonymous_ids) != len(self.anonymous_speakers):
            raise ScriptContractError(
                "authority anonymous speaker ids must be unique"
            )
        if not self.verified_historical_anonymous_ids.issubset(anonymous_ids):
            raise ScriptContractError(
                "authority verified historical anonymous ids must name an "
                "authorized identity snapshot"
            )
        for target in self.casting_targets:
            if (
                target.character_id is not None
                and target.character_id not in self.character_ids
            ):
                raise ScriptContractError(
                    "authority casting target references an unauthorized character"
                )
            if (
                target.anonymous_speaker_id is not None
                and target.anonymous_speaker_id not in anonymous_ids
            ):
                raise ScriptContractError(
                    "authority casting target references an unauthorized "
                    "anonymous speaker"
                )
        for record in self.cloud_records:
            if (
                self.actual_model_fingerprint is None
                or record.model_fingerprint != self.actual_model_fingerprint
            ):
                raise ScriptContractError(
                    "authority cloud evidence must match the actual model fingerprint"
                )
        if type(self.group_keys) is not frozenset or any(
            type(value) is not str or _GROUP_KEY.fullmatch(value) is None
            for value in self.group_keys
        ):
            raise ScriptContractError(
                "authority group_keys must be a frozenset of frozen group keys"
            )


@dataclass(frozen=True, slots=True)
class NarrationScriptContract:
    script_id: UUID
    script_version_id: UUID
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    source_content_hash: str
    source_length_utf16: int
    version_number: int
    parent_version_id: UUID | None
    state: ScriptVersionState
    effective_policy: ScriptReviewPolicy
    analyzer_fingerprint: str
    rules_fingerprint: str
    settings_fingerprint: str
    requested_model_fingerprint: str | None
    actual_model_fingerprint: str | None
    anonymous_speakers: tuple[AnonymousSpeakerIdentity, ...]
    scenes: tuple[SceneContract, ...]
    segments: tuple[SegmentContract, ...]
    issues: tuple[ScriptIssueContract, ...]
    warning_count: int
    blocker_count: int
    immutable_hash: str
    approval: ScriptApproval | None = None
    schema_version: str = NARRATION_SCRIPT_CONTRACT_VERSION
    taxonomy_version: str = NARRATION_REVIEW_TAXONOMY_VERSION

    def __post_init__(self) -> None:
        for field_name, value in (
            ("script_id", self.script_id),
            ("script_version_id", self.script_version_id),
            ("novel_id", self.novel_id),
            ("document_id", self.document_id),
            ("revision_id", self.revision_id),
        ):
            _require_uuid(value, field_name=field_name)
        _require_sha256(self.source_content_hash, field_name="source_content_hash")
        _require_exact_int(
            self.source_length_utf16, field_name="source_length_utf16"
        )
        _require_exact_int(
            self.version_number, field_name="version_number", minimum=1
        )
        if self.parent_version_id is not None:
            _require_uuid(self.parent_version_id, field_name="parent_version_id")
            if self.parent_version_id == self.script_version_id:
                raise ScriptContractError("script version cannot parent itself")
        _require_enum(self.state, ScriptVersionState, field_name="script state")
        _require_enum(
            self.effective_policy,
            ScriptReviewPolicy,
            field_name="effective_policy",
        )
        for field_name, value in (
            ("analyzer_fingerprint", self.analyzer_fingerprint),
            ("rules_fingerprint", self.rules_fingerprint),
            ("settings_fingerprint", self.settings_fingerprint),
        ):
            _require_sha256(value, field_name=field_name)
        _require_optional_sha256(
            self.requested_model_fingerprint,
            field_name="requested_model_fingerprint",
        )
        _require_optional_sha256(
            self.actual_model_fingerprint, field_name="actual_model_fingerprint"
        )
        if type(self.anonymous_speakers) is not tuple or not all(
            type(item) is AnonymousSpeakerIdentity
            for item in self.anonymous_speakers
        ):
            raise ScriptContractError(
                "anonymous_speakers must be a tuple of AnonymousSpeakerIdentity"
            )
        if self.anonymous_speakers != tuple(
            sorted(
                self.anonymous_speakers,
                key=lambda item: (
                    item.stable_key_algorithm,
                    item.stable_key,
                    str(item.anonymous_speaker_id),
                ),
            )
        ):
            raise ScriptContractError(
                "anonymous_speakers must use canonical stable-key order"
            )
        if type(self.scenes) is not tuple or not all(
            type(item) is SceneContract for item in self.scenes
        ):
            raise ScriptContractError("scenes must be a tuple of SceneContract")
        if type(self.segments) is not tuple or not all(
            type(item) is SegmentContract for item in self.segments
        ):
            raise ScriptContractError("segments must be a tuple of SegmentContract")
        if type(self.issues) is not tuple or not all(
            type(item) is ScriptIssueContract for item in self.issues
        ):
            raise ScriptContractError("issues must be a tuple of ScriptIssueContract")
        if self.issues != tuple(
            sorted(
                self.issues,
                key=lambda item: (
                    item.code,
                    str(item.segment_id) if item.segment_id else "",
                    item.evidence_digest or "",
                ),
            )
        ):
            raise ScriptContractError("issues must use canonical order")
        _require_exact_int(self.warning_count, field_name="warning_count")
        _require_exact_int(self.blocker_count, field_name="blocker_count")
        _require_sha256(self.immutable_hash, field_name="immutable_hash")
        if self.approval is not None and type(self.approval) is not ScriptApproval:
            raise ScriptContractError("approval must be ScriptApproval or None")
        if self.schema_version != NARRATION_SCRIPT_CONTRACT_VERSION:
            raise ScriptContractError("unknown narration script contract version")
        if self.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
            raise ScriptContractError("unknown narration review taxonomy version")

        self._validate_collections()
        self._validate_state()
        if self.immutable_hash != script_immutable_hash(self):
            raise ScriptContractError(
                "immutable_hash does not match the frozen script payload"
            )

    def _validate_collections(self) -> None:
        if [scene.ordinal for scene in self.scenes] != list(range(len(self.scenes))):
            raise ScriptContractError("scene ordinals must be contiguous from zero")
        if [segment.ordinal for segment in self.segments] != list(
            range(len(self.segments))
        ):
            raise ScriptContractError("segment ordinals must be contiguous from zero")
        scene_ids = {scene.scene_id for scene in self.scenes}
        if len(scene_ids) != len(self.scenes):
            raise ScriptContractError("scene ids must be unique")
        segment_ids = {segment.segment_id for segment in self.segments}
        if len(segment_ids) != len(self.segments):
            raise ScriptContractError("segment ids must be unique")

        previous_scene_end = 0
        for scene in self.scenes:
            expected_id = derive_scene_id(
                script_version_id=self.script_version_id,
                ordinal=scene.ordinal,
                source_range=scene.source_range_utf16,
                local_hash=scene.local_hash,
            )
            if scene.scene_id != expected_id:
                raise ScriptContractError("scene_id is not the frozen version-scoped ID")
            if scene.source_range_utf16 is not None:
                if scene.source_range_utf16.end_exclusive > self.source_length_utf16:
                    raise ScriptContractError("scene range exceeds source_length_utf16")
                if scene.source_range_utf16.start < previous_scene_end:
                    raise ScriptContractError("scene ranges overlap or move backwards")
                previous_scene_end = scene.source_range_utf16.end_exclusive

        block_members: dict[str, list[SegmentContract]] = {}
        previous_segment_end = 0
        for segment in self.segments:
            expected_id = derive_segment_id(
                script_version_id=self.script_version_id,
                ordinal=segment.ordinal,
                source_block_key=segment.source_block_key,
                segment_ordinal_in_block=segment.segment_ordinal_in_block,
                local_hash=segment.local_hash,
            )
            if segment.segment_id != expected_id:
                raise ScriptContractError(
                    "segment_id is not the frozen version-scoped ID"
                )
            expected_block_key = derive_source_block_key(
                script_version_id=self.script_version_id,
                block_kind=segment.source_block_kind,
                paragraph_ordinal=segment.paragraph_ordinal,
                block_hash=segment.source_block_hash,
                anchor_before_hash=segment.anchor_before_hash,
                anchor_after_hash=segment.anchor_after_hash,
            )
            if segment.source_block_key != expected_block_key:
                raise ScriptContractError(
                    "source_block_key is not the frozen version-scoped key"
                )
            if segment.scene_id is not None and segment.scene_id not in scene_ids:
                raise ScriptContractError("segment references an unknown scene")
            if segment.source_range_utf16 is not None:
                if segment.source_range_utf16.end_exclusive > self.source_length_utf16:
                    raise ScriptContractError("segment range exceeds source_length_utf16")
                if segment.source_range_utf16.start < previous_segment_end:
                    raise ScriptContractError(
                        "source-bound segment ranges overlap or move backwards"
                    )
                previous_segment_end = segment.source_range_utf16.end_exclusive
                if segment.scene_id is not None:
                    scene = next(
                        item for item in self.scenes if item.scene_id == segment.scene_id
                    )
                    if scene.source_range_utf16 is None:
                        raise ScriptContractError(
                            "source-bound segment cannot reference a synthetic scene"
                        )
                    if not (
                        scene.source_range_utf16.start
                        <= segment.source_range_utf16.start
                        < segment.source_range_utf16.end_exclusive
                        <= scene.source_range_utf16.end_exclusive
                    ):
                        raise ScriptContractError(
                            "segment source range is outside its scene range"
                        )
            block_members.setdefault(segment.source_block_key, []).append(segment)

        for members in block_members.values():
            first = members[0]
            signature = (
                first.source_block_kind,
                first.paragraph_ordinal,
                first.source_block_hash,
                first.anchor_before_hash,
                first.anchor_after_hash,
            )
            if any(
                (
                    item.source_block_kind,
                    item.paragraph_ordinal,
                    item.source_block_hash,
                    item.anchor_before_hash,
                    item.anchor_after_hash,
                )
                != signature
                for item in members
            ):
                raise ScriptContractError("source block metadata drifted within one key")
            if [item.segment_ordinal_in_block for item in members] != list(
                range(len(members))
            ):
                raise ScriptContractError(
                    "segment_ordinal_in_block must be contiguous within each block"
                )

        anonymous_by_id = {
            item.anonymous_speaker_id: item for item in self.anonymous_speakers
        }
        if len(anonymous_by_id) != len(self.anonymous_speakers):
            raise ScriptContractError("anonymous speaker ids must be unique")
        stable_identities = {
            (item.stable_key_algorithm, item.stable_key)
            for item in self.anonymous_speakers
        }
        if len(stable_identities) != len(self.anonymous_speakers):
            raise ScriptContractError("anonymous stable identities must be unique")
        for identity in self.anonymous_speakers:
            if identity.anonymous_speaker_id != derive_anonymous_speaker_id(
                novel_id=self.novel_id, stable_key=identity.stable_key
            ):
                raise ScriptContractError(
                    "anonymous_speaker_id does not match its stable key"
                )
            if identity.scope_kind is AnonymousScopeKind.CHAPTER and (
                identity.scope_id != self.document_id
            ):
                raise ScriptContractError(
                    "chapter-scoped anonymous speaker must use document_id"
                )
            if identity.scope_kind is AnonymousScopeKind.NOVEL and (
                identity.scope_id != self.novel_id
            ):
                raise ScriptContractError(
                    "novel-scoped anonymous speaker must use novel_id"
                )
        for segment in self.segments:
            if segment.speaker.kind is SpeakerKind.ANONYMOUS and (
                segment.speaker.anonymous_speaker_id not in anonymous_by_id
            ):
                raise ScriptContractError(
                    "segment references an unknown anonymous speaker identity"
                )
        referenced_anonymous_ids = {
            segment.speaker.anonymous_speaker_id
            for segment in self.segments
            if segment.speaker.kind is SpeakerKind.ANONYMOUS
        }
        if referenced_anonymous_ids != set(anonymous_by_id):
            raise ScriptContractError(
                "anonymous_speakers must exactly match referenced identities"
            )

        issue_keys = [
            (issue.code, issue.segment_id, issue.evidence_digest)
            for issue in self.issues
        ]
        if len(set(issue_keys)) != len(issue_keys):
            raise ScriptContractError("duplicate script issue")
        if any(
            issue.segment_id is not None and issue.segment_id not in segment_ids
            for issue in self.issues
        ):
            raise ScriptContractError("script issue references an unknown segment")
        warning_count = sum(
            issue.severity is ReviewIssueSeverity.WARNING for issue in self.issues
        )
        blocker_count = sum(
            issue.severity is ReviewIssueSeverity.BLOCKER for issue in self.issues
        )
        if (warning_count, blocker_count) != (
            self.warning_count,
            self.blocker_count,
        ):
            raise ScriptContractError(
                "warning_count/blocker_count must be recomputed from issue rows"
            )

        issues_by_segment = {
            segment.segment_id: {
                issue.code
                for issue in self.issues
                if issue.segment_id == segment.segment_id
            }
            for segment in self.segments
        }
        for segment in self.segments:
            codes = issues_by_segment[segment.segment_id]
            if (
                segment.speaker.kind is SpeakerKind.CHARACTER
                and segment.speaker.character_id
                not in segment.attribution.candidate_character_ids
            ):
                raise ScriptContractError(
                    "character speaker must belong to its attribution candidates"
                )
            if (
                segment.confidence is ConfidenceLevel.MEDIUM
                and "W_SPEAKER_MEDIUM_CONFIDENCE" not in codes
            ):
                raise ScriptContractError(
                    "medium speaker confidence requires its server warning"
                )
            if segment.confidence in {
                ConfidenceLevel.LOW,
                ConfidenceLevel.UNKNOWN,
            } and "B_SPEAKER_LOW_CONFIDENCE" not in codes:
                raise ScriptContractError(
                    "low/unknown speaker confidence requires its server blocker"
                )
            if (
                segment.speaker.kind is SpeakerKind.UNKNOWN
                and "B_SPEAKER_UNKNOWN" not in codes
            ):
                raise ScriptContractError(
                    "unknown speaker requires B_SPEAKER_UNKNOWN"
                )
            if (
                segment.casting.origin is CastingDecisionOrigin.UNRESOLVED
                and "B_CASTING_TARGET_UNRESOLVED" not in codes
            ):
                raise ScriptContractError(
                    "unresolved casting requires B_CASTING_TARGET_UNRESOLVED"
                )
            if (
                segment.casting.final_target is None
                and segment.casting.origin
                is not CastingDecisionOrigin.NOT_APPLICABLE
                and "B_CASTING_TARGET_UNRESOLVED" not in codes
            ):
                raise ScriptContractError(
                    "missing final casting target requires its server blocker"
                )
            if segment.attribution.origin is AttributionOrigin.INHERITED_OVERRIDE:
                provenance = segment.attribution.override_provenance
                if provenance is None or (
                    provenance.source_script_version_id == self.script_version_id
                ):
                    raise ScriptContractError(
                        "inherited override must reference another script version"
                    )
                if "W_MANUAL_OVERRIDE_INHERITED" not in codes:
                    raise ScriptContractError(
                        "inherited override requires its server warning"
                    )
            if (
                segment.attribution.origin is AttributionOrigin.CLOUD_ASSISTED
                and "W_CLOUD_ASSISTED_USED" not in codes
            ):
                raise ScriptContractError(
                    "cloud-assisted attribution requires its server warning"
                )
        uses_cloud = any(
            segment.attribution.origin is AttributionOrigin.CLOUD_ASSISTED
            for segment in self.segments
        )
        if (self.requested_model_fingerprint is None) != (
            self.actual_model_fingerprint is None
        ):
            raise ScriptContractError(
                "requested and actual model fingerprints must be both present or absent"
            )
        if (
            self.requested_model_fingerprint is not None
            and self.requested_model_fingerprint
            != self.actual_model_fingerprint
        ):
            raise ScriptContractError(
                "requested and actual model fingerprints must match"
            )
        if uses_cloud:
            if (
                self.requested_model_fingerprint is None
                or self.actual_model_fingerprint is None
            ):
                raise ScriptContractError(
                    "cloud-assisted script requires requested and actual model fingerprints"
                )

    def _validate_state(self) -> None:
        materialized = self.state in {
            ScriptVersionState.ANALYZED,
            ScriptVersionState.REVIEW_REQUIRED,
            ScriptVersionState.APPROVED,
        }
        if materialized and not self.segments:
            raise ScriptContractError(
                "materialized script state requires at least one segment"
            )
        if self.state is ScriptVersionState.ANALYZED and (
            self.effective_policy is not ScriptReviewPolicy.BLOCKERS_ONLY
            or self.blocker_count != 0
        ):
            raise ScriptContractError(
                "analyzed state requires blockers_only and zero blockers"
            )
        if self.state is ScriptVersionState.REVIEW_REQUIRED and not (
            self.effective_policy is ScriptReviewPolicy.ALWAYS_REVIEW
            or self.blocker_count > 0
            or self.parent_version_id is not None
        ):
            raise ScriptContractError(
                "review_required needs always_review, at least one blocker, "
                "or a corrected child version"
            )
        if self.state is ScriptVersionState.APPROVED:
            if self.blocker_count != 0 or self.approval is None:
                raise ScriptContractError(
                    "approved script requires zero blockers and approval audit"
                )
            if (
                self.approval.kind is ScriptApprovalKind.AUTO_NO_BLOCKERS
                and self.effective_policy is not ScriptReviewPolicy.BLOCKERS_ONLY
            ):
                raise ScriptContractError(
                    "auto approval is only valid for blockers_only"
                )
            if (
                self.approval.kind is ScriptApprovalKind.MANUAL_AFTER_REVIEW
                and self.effective_policy is ScriptReviewPolicy.BLOCKERS_ONLY
                and self.parent_version_id is None
            ):
                raise ScriptContractError(
                    "manual approval under blockers_only requires a corrected "
                    "child version"
                )
        elif self.approval is not None:
            raise ScriptContractError("only approved state may contain approval audit")


def validate_authorized_references(
    script: NarrationScriptContract, authority: ScriptAuthorityContext
) -> None:
    """Reject every value or relation not authorized by server-owned scope."""

    if type(script) is not NarrationScriptContract:
        raise ScriptContractError("script must be NarrationScriptContract")
    if type(authority) is not ScriptAuthorityContext:
        raise ScriptContractError("authority must be ScriptAuthorityContext")
    expected_roots = (
        ("novel_id", script.novel_id, authority.novel_id),
        ("document_id", script.document_id, authority.document_id),
        ("revision_id", script.revision_id, authority.revision_id),
        ("script_id", script.script_id, authority.script_id),
        (
            "script_version_id",
            script.script_version_id,
            authority.script_version_id,
        ),
        ("version_number", script.version_number, authority.version_number),
        ("state", script.state, authority.state),
        (
            "effective_policy",
            script.effective_policy,
            authority.effective_policy,
        ),
        (
            "analyzer_fingerprint",
            script.analyzer_fingerprint,
            authority.analyzer_fingerprint,
        ),
        (
            "rules_fingerprint",
            script.rules_fingerprint,
            authority.rules_fingerprint,
        ),
        (
            "settings_fingerprint",
            script.settings_fingerprint,
            authority.settings_fingerprint,
        ),
        (
            "requested_model_fingerprint",
            script.requested_model_fingerprint,
            authority.requested_model_fingerprint,
        ),
        (
            "actual_model_fingerprint",
            script.actual_model_fingerprint,
            authority.actual_model_fingerprint,
        ),
        ("approval", script.approval, authority.approval),
    )
    for field_name, actual, expected in expected_roots:
        if actual != expected:
            raise ScriptContractError(f"{field_name} is outside server authority")
    if (
        script.parent_version_id is not None
        and script.parent_version_id not in authority.parent_version_ids
    ):
        raise ScriptContractError("parent_version_id is outside server authority")

    current_scene_ids = {scene.scene_id for scene in script.scenes}
    authorized_anonymous_ids = {
        identity.anonymous_speaker_id for identity in authority.anonymous_speakers
    }
    for identity in script.anonymous_speakers:
        if identity not in authority.anonymous_speakers:
            raise ScriptContractError(
                "anonymous speaker snapshot is outside server authority"
            )
        if (
            identity.scope_kind is AnonymousScopeKind.SCENE
            and identity.scope_id not in current_scene_ids
            and identity.anonymous_speaker_id
            not in authority.verified_historical_anonymous_ids
        ):
            raise ScriptContractError(
                "historical scene anonymous reuse lacks verified unique authority"
            )
    for segment in script.segments:
        speaker = segment.speaker
        if (
            speaker.character_id is not None
            and speaker.character_id not in authority.character_ids
        ):
            raise ScriptContractError("character_id is outside server authority")
        if (
            speaker.anonymous_speaker_id is not None
            and speaker.anonymous_speaker_id
            not in authorized_anonymous_ids
        ):
            raise ScriptContractError(
                "anonymous_speaker_id is outside server authority"
            )
        if speaker.group_key is not None and speaker.group_key not in authority.group_keys:
            raise ScriptContractError("group_key is outside server authority")
        if not set(segment.attribution.candidate_character_ids).issubset(
            authority.character_ids
        ):
            raise ScriptContractError(
                "candidate_character_ids are outside server authority"
            )
        attribution = segment.attribution
        if attribution.origin is AttributionOrigin.CLOUD_ASSISTED:
            model_fingerprint = script.actual_model_fingerprint
            if model_fingerprint is None or CloudAuthorityRecord(
                attribution=attribution,
                model_fingerprint=model_fingerprint,
                segment_id=segment.segment_id,
                source_local_hash=segment.local_hash,
                speaker_target_hash=speaker_target_hash(
                    segment.speaker,
                    segment.casting,
                ),
            ) not in authority.cloud_records:
                raise ScriptContractError(
                    "cloud attribution is outside verified server authority"
                )
        provenance = attribution.override_provenance
        if (
            provenance is not None
            and provenance not in authority.override_provenances
        ):
            raise ScriptContractError(
                "override provenance is outside verified server authority"
            )
        for target in segment.casting.candidate_targets:
            if target not in authority.casting_targets:
                raise ScriptContractError(
                    "casting target relation is outside server authority"
                )
        if segment.casting.origin is CastingDecisionOrigin.CASTING_RULE:
            if CastingRuleAuthorityRecord(
                decision=segment.casting,
                segment_id=segment.segment_id,
                source_local_hash=segment.local_hash,
                speaker_target_hash=speaker_target_hash(
                    segment.speaker,
                    segment.casting,
                ),
            ) not in authority.casting_rule_records:
                raise ScriptContractError(
                    "casting rule decision relation is outside server authority"
                )

    manual_review_parent = (
        script.parent_version_id is not None
        and script.parent_version_id in authority.manual_review_parent_ids
    )
    if (
        script.state is ScriptVersionState.REVIEW_REQUIRED
        and script.effective_policy is ScriptReviewPolicy.BLOCKERS_ONLY
        and script.blocker_count == 0
        and not manual_review_parent
    ):
        raise ScriptContractError(
            "zero-blocker review requires a verified manual-review parent"
        )
    if manual_review_parent and script.state is ScriptVersionState.ANALYZED:
        raise ScriptContractError(
            "verified blocker correction cannot bypass manual review"
        )
    if script.state is ScriptVersionState.APPROVED:
        approval = script.approval
        if approval is None:
            raise ScriptContractError(
                "approved script lacks its server-authorized approval audit"
            )
        if manual_review_parent and (
            approval.kind is not ScriptApprovalKind.MANUAL_AFTER_REVIEW
        ):
            raise ScriptContractError(
                "verified blocker correction requires manual_after_review"
            )
        if (
            approval.kind is ScriptApprovalKind.MANUAL_AFTER_REVIEW
            and script.effective_policy is ScriptReviewPolicy.BLOCKERS_ONLY
            and not manual_review_parent
        ):
            raise ScriptContractError(
                "blockers_only manual approval lacks a verified review parent"
            )


def initial_materialized_state(
    policy: ScriptReviewPolicy, *, blocker_count: int
) -> ScriptVersionState:
    _require_enum(policy, ScriptReviewPolicy, field_name="policy")
    _require_exact_int(blocker_count, field_name="blocker_count")
    if policy is ScriptReviewPolicy.ALWAYS_REVIEW or blocker_count > 0:
        return ScriptVersionState.REVIEW_REQUIRED
    return ScriptVersionState.ANALYZED


def ensure_script_transition(
    current: ScriptVersionState, target: ScriptVersionState
) -> None:
    _require_enum(current, ScriptVersionState, field_name="current state")
    _require_enum(target, ScriptVersionState, field_name="target state")
    if target not in SCRIPT_STATE_TRANSITIONS[current]:
        raise ScriptContractError(
            f"illegal script state transition: {current.value} -> {target.value}"
        )


def _range_payload(source_range: Utf16Range | None) -> dict[str, int] | None:
    if source_range is None:
        return None
    return {
        "start": source_range.start,
        "end_exclusive": source_range.end_exclusive,
    }


def _speaker_payload(speaker: SpeakerRef) -> dict[str, object]:
    return {
        "kind": speaker.kind.value,
        "character_id": str(speaker.character_id) if speaker.character_id else None,
        "anonymous_speaker_id": (
            str(speaker.anonymous_speaker_id)
            if speaker.anonymous_speaker_id
            else None
        ),
        "group_key": speaker.group_key,
    }


def _attribution_payload(attribution: AttributionEvidence) -> dict[str, object]:
    provenance = attribution.override_provenance
    return {
        "origin": attribution.origin.value,
        "rule_codes": sorted(attribution.rule_codes),
        "candidate_character_ids": [
            str(item)
            for item in sorted(
                attribution.candidate_character_ids, key=lambda value: str(value)
            )
        ],
        "consent_id": (
            str(attribution.consent_id) if attribution.consent_id else None
        ),
        "model_run_id": (
            str(attribution.model_run_id) if attribution.model_run_id else None
        ),
        "input_digest_key_id": attribution.input_digest_key_id,
        "input_digest": attribution.input_digest,
        "output_digest": attribution.output_digest,
        "override_provenance": (
            {
                "contract_version": provenance.contract_version,
                "kind": provenance.kind.value,
                "action_id": str(provenance.action_id),
                "owner_actor_id": provenance.owner_actor_id,
                "recorded_at": provenance.recorded_at.isoformat(),
                "source_script_version_id": (
                    str(provenance.source_script_version_id)
                    if provenance.source_script_version_id
                    else None
                ),
                "source_segment_id": (
                    str(provenance.source_segment_id)
                    if provenance.source_segment_id
                    else None
                ),
                "source_immutable_hash": provenance.source_immutable_hash,
                "source_local_hash": provenance.source_local_hash,
                "source_anchor_before_hash": (
                    provenance.source_anchor_before_hash
                ),
                "source_anchor_after_hash": provenance.source_anchor_after_hash,
                "speaker_target_hash": provenance.speaker_target_hash,
            }
            if provenance
            else None
        ),
    }


def _casting_decision_payload(casting: CastingDecision) -> dict[str, object]:
    candidates = sorted(
        (_casting_target_payload(item) for item in casting.candidate_targets),
        key=canonical_json_bytes,
    )
    return {
        "contract_version": NARRATION_CASTING_DECISION_VERSION,
        "candidate_targets": candidates,
        "final_target": (
            _casting_target_payload(casting.final_target)
            if casting.final_target
            else None
        ),
        "origin": casting.origin.value,
        "rule_id": str(casting.rule_id) if casting.rule_id else None,
        "rule_version": casting.rule_version,
    }


def _anonymous_payload(identity: AnonymousSpeakerIdentity) -> dict[str, object]:
    return {
        "anonymous_speaker_id": str(identity.anonymous_speaker_id),
        "stable_key_algorithm": identity.stable_key_algorithm,
        "stable_key": identity.stable_key,
        "display_name": identity.display_name,
        "scope_kind": identity.scope_kind.value,
        "scope_id": str(identity.scope_id),
        "confidence": identity.confidence.value,
    }


def _scene_payload(scene: SceneContract) -> dict[str, object]:
    return {
        "scene_id": str(scene.scene_id),
        "ordinal": scene.ordinal,
        "source_range_utf16": _range_payload(scene.source_range_utf16),
        "boundary_source": scene.boundary_source.value,
        "local_hash": scene.local_hash,
        "title": scene.title,
    }


def _segment_payload(segment: SegmentContract) -> dict[str, object]:
    return {
        "segment_id": str(segment.segment_id),
        "ordinal": segment.ordinal,
        "scene_id": str(segment.scene_id) if segment.scene_id else None,
        "segment_kind": segment.segment_kind.value,
        "source_block_kind": segment.source_block_kind.value,
        "paragraph_ordinal": segment.paragraph_ordinal,
        "segment_ordinal_in_block": segment.segment_ordinal_in_block,
        "source_block_key": segment.source_block_key,
        "source_block_hash": segment.source_block_hash,
        "source_range_utf16": _range_payload(segment.source_range_utf16),
        "source_text": segment.source_text,
        "spoken_text": segment.spoken_text,
        "local_hash": segment.local_hash,
        "anchor_before_hash": segment.anchor_before_hash,
        "anchor_after_hash": segment.anchor_after_hash,
        "inheritance_anchor_before_hash": segment.inheritance_anchor_before_hash,
        "inheritance_anchor_after_hash": segment.inheritance_anchor_after_hash,
        "speaker": _speaker_payload(segment.speaker),
        "casting": _casting_decision_payload(segment.casting),
        "confidence": segment.confidence.value,
        "emotion": segment.emotion.value,
        "emotion_confidence": segment.emotion_confidence.value,
        "delivery": segment.delivery.value,
        "attribution": _attribution_payload(segment.attribution),
        "pause_before_ms": segment.pause_before_ms,
        "pause_after_ms": segment.pause_after_ms,
        "manual_override": segment.manual_override,
    }


def _issue_payload(issue: ScriptIssueContract) -> dict[str, object]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "segment_id": str(issue.segment_id) if issue.segment_id else None,
        "evidence_summary": issue.evidence_summary,
        "evidence_digest": issue.evidence_digest,
        "taxonomy_version": issue.taxonomy_version,
    }


def _scene_persistence_payload(scene: SceneContract) -> dict[str, object]:
    source_range = scene.source_range_utf16
    return {
        "scene_id": str(scene.scene_id),
        "ordinal": scene.ordinal,
        "source_start": source_range.start if source_range else None,
        "source_end": source_range.end_exclusive if source_range else None,
        "boundary_source": scene.boundary_source.value,
        "local_hash": scene.local_hash,
        "title": scene.title,
    }


def _anonymous_identity_hash_snapshot(
    identity: AnonymousSpeakerIdentity,
) -> dict[str, object]:
    return {
        "anonymous_speaker_id": str(identity.anonymous_speaker_id),
        "stable_key_algorithm": identity.stable_key_algorithm,
        "stable_key": identity.stable_key,
        "scope_kind": identity.scope_kind.value,
        "scope_id": str(identity.scope_id),
    }


def _segment_persistence_payload(
    segment: SegmentContract,
    *,
    anonymous_by_id: Mapping[UUID, AnonymousSpeakerIdentity],
) -> dict[str, object]:
    source_range = segment.source_range_utf16
    anonymous_identity = None
    if segment.speaker.anonymous_speaker_id is not None:
        anonymous_identity = _anonymous_identity_hash_snapshot(
            anonymous_by_id[segment.speaker.anonymous_speaker_id]
        )
    return {
        "segment_id": str(segment.segment_id),
        "scene_id": str(segment.scene_id) if segment.scene_id else None,
        "ordinal": segment.ordinal,
        "segment_kind": segment.segment_kind.value,
        "paragraph_ordinal": segment.paragraph_ordinal,
        "source_block_key": segment.source_block_key,
        "source_start_utf16": source_range.start if source_range else None,
        "source_end_utf16": source_range.end_exclusive if source_range else None,
        "source_text": segment.source_text,
        "spoken_text": segment.spoken_text,
        "local_hash": segment.local_hash,
        "anchor_before_hash": segment.anchor_before_hash,
        "anchor_after_hash": segment.anchor_after_hash,
        "speaker_kind": segment.speaker.kind.value,
        "character_id": (
            str(segment.speaker.character_id)
            if segment.speaker.character_id
            else None
        ),
        "anonymous_speaker_id": (
            str(segment.speaker.anonymous_speaker_id)
            if segment.speaker.anonymous_speaker_id
            else None
        ),
        "casting": _casting_decision_payload(segment.casting),
        "evidence": {
            "contract_version": NARRATION_SEGMENT_EVIDENCE_VERSION,
            "source_block_kind": segment.source_block_kind.value,
            "source_block_hash": segment.source_block_hash,
            "segment_ordinal_in_block": segment.segment_ordinal_in_block,
            "inheritance_anchor_before_hash": (
                segment.inheritance_anchor_before_hash
            ),
            "inheritance_anchor_after_hash": (
                segment.inheritance_anchor_after_hash
            ),
            "group_key": segment.speaker.group_key,
            "attribution": _attribution_payload(segment.attribution),
            "anonymous_identity": anonymous_identity,
            "emotion_confidence": segment.emotion_confidence.value,
        },
        "confidence": segment.confidence.value,
        "emotion": segment.emotion.value,
        "expression": segment.delivery.value,
        "pause_before_ms": segment.pause_before_ms,
        "pause_after_ms": segment.pause_after_ms,
        "manual_override": segment.manual_override,
    }


def _issue_persistence_payload(issue: ScriptIssueContract) -> dict[str, object]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "segment_id": str(issue.segment_id) if issue.segment_id else None,
        "evidence_digest": issue.evidence_digest,
    }


def script_immutable_payload(script: NarrationScriptContract) -> dict[str, object]:
    anonymous_by_id = {
        item.anonymous_speaker_id: item for item in script.anonymous_speakers
    }
    issue_payloads = sorted(
        (_issue_persistence_payload(item) for item in script.issues),
        key=lambda item: (
            str(item["code"]),
            str(item["segment_id"] or ""),
            str(item["evidence_digest"] or ""),
        ),
    )
    return {
        "script_id": str(script.script_id),
        "parent_version_id": (
            str(script.parent_version_id) if script.parent_version_id else None
        ),
        "source_content_hash": script.source_content_hash,
        "settings_fingerprint": script.settings_fingerprint,
        "analyzer_fingerprint": script.analyzer_fingerprint,
        "rules_fingerprint": script.rules_fingerprint,
        "requested_model_fingerprint": script.requested_model_fingerprint,
        "actual_model_fingerprint": script.actual_model_fingerprint,
        "effective_policy": script.effective_policy.value,
        "taxonomy_version": script.taxonomy_version,
        "scenes": [_scene_persistence_payload(item) for item in script.scenes],
        "segments": [
            _segment_persistence_payload(item, anonymous_by_id=anonymous_by_id)
            for item in script.segments
        ],
        "issues": issue_payloads,
    }


def script_immutable_hash(script: NarrationScriptContract) -> str:
    return hashlib.sha256(
        canonical_json_bytes(script_immutable_payload(script))
    ).hexdigest()


def script_contract_to_dict(script: NarrationScriptContract) -> dict[str, object]:
    approval = None
    if script.approval is not None:
        approval = {
            "kind": script.approval.kind.value,
            "request_id": str(script.approval.request_id),
            "actor_type": script.approval.actor_type.value,
            "actor_id": script.approval.actor_id,
            "approved_at": script.approval.approved_at.isoformat(),
        }
    return {
        "schema_version": script.schema_version,
        "taxonomy_version": script.taxonomy_version,
        "script_id": str(script.script_id),
        "script_version_id": str(script.script_version_id),
        "novel_id": str(script.novel_id),
        "document_id": str(script.document_id),
        "revision_id": str(script.revision_id),
        "source_content_hash": script.source_content_hash,
        "source_length_utf16": script.source_length_utf16,
        "version_number": script.version_number,
        "parent_version_id": (
            str(script.parent_version_id) if script.parent_version_id else None
        ),
        "state": script.state.value,
        "effective_policy": script.effective_policy.value,
        "analyzer_fingerprint": script.analyzer_fingerprint,
        "rules_fingerprint": script.rules_fingerprint,
        "settings_fingerprint": script.settings_fingerprint,
        "requested_model_fingerprint": script.requested_model_fingerprint,
        "actual_model_fingerprint": script.actual_model_fingerprint,
        "anonymous_speakers": [
            _anonymous_payload(item) for item in script.anonymous_speakers
        ],
        "scenes": [_scene_payload(item) for item in script.scenes],
        "segments": [_segment_payload(item) for item in script.segments],
        "issues": [_issue_payload(item) for item in script.issues],
        "warning_count": script.warning_count,
        "blocker_count": script.blocker_count,
        "immutable_hash": script.immutable_hash,
        "approval": approval,
    }


def validate_source_mapping(
    source_text: str, script: NarrationScriptContract
) -> None:
    if utf16_length(source_text) != script.source_length_utf16:
        raise ScriptContractError(
            "source text UTF-16 length differs from frozen script source length"
        )
    if text_sha256(source_text) != script.source_content_hash:
        raise ScriptContractError("source text hash differs from frozen revision")
    for scene in script.scenes:
        if scene.source_range_utf16 is None:
            continue
        scene_text = utf16_slice(source_text, scene.source_range_utf16)
        if text_sha256(scene_text) != scene.local_hash:
            raise ScriptContractError(
                f"scene {scene.scene_id} local_hash differs from its UTF-16 slice"
            )

    source_bound = [
        segment
        for segment in script.segments
        if segment.source_range_utf16 is not None
    ]
    if source_text and not source_bound:
        raise ScriptContractError(
            "non-empty source requires at least one source-bound segment"
        )
    coverage_cursor = 0
    active_block_key: str | None = None
    closed_block_keys: set[str] = set()
    paragraph_ordinals: list[int] = []
    for segment in source_bound:
        source_range = segment.source_range_utf16
        if source_range is None:
            raise ScriptContractError(
                "source-bound collection contains a segment without a source range"
            )
        if source_range.start != coverage_cursor:
            raise ScriptContractError(
                "source-bound segment ranges must completely partition the source"
            )
        if utf16_slice(source_text, source_range) != segment.source_text:
            raise ScriptContractError(
                f"segment {segment.segment_id} source_text differs from UTF-16 slice"
            )
        coverage_cursor = source_range.end_exclusive
        if segment.source_block_key != active_block_key:
            if segment.source_block_key in closed_block_keys:
                raise ScriptContractError(
                    "source block members must form one contiguous source sequence"
                )
            if active_block_key is not None:
                closed_block_keys.add(active_block_key)
            active_block_key = segment.source_block_key
            paragraph_ordinal = segment.paragraph_ordinal
            if paragraph_ordinal is None:
                raise ScriptContractError(
                    "source-bound block lacks its paragraph ordinal"
                )
            paragraph_ordinals.append(paragraph_ordinal)
    if coverage_cursor != script.source_length_utf16:
        raise ScriptContractError(
            "source-bound segment ranges must completely partition the source"
        )
    if paragraph_ordinals != list(range(len(paragraph_ordinals))):
        raise ScriptContractError(
            "source block paragraph ordinals must be unique and contiguous in source order"
        )

    ordered_blocks: list[tuple[int, int, str, str | None, str | None]] = []
    for block_key in dict.fromkeys(
        segment.source_block_key for segment in source_bound
    ):
        members = [
            segment
            for segment in source_bound
            if segment.source_block_key == block_key
        ]
        starts = [
            segment.source_range_utf16.start
            for segment in members
            if segment.source_range_utf16 is not None
        ]
        ends = [
            segment.source_range_utf16.end_exclusive
            for segment in members
            if segment.source_range_utf16 is not None
        ]
        start = min(starts)
        end = max(ends)
        block_text = utf16_slice(source_text, Utf16Range(start, end))
        expected_hash = members[0].source_block_hash
        if text_sha256(block_text) != expected_hash:
            raise ScriptContractError(
                f"source block {block_key} hash differs from its UTF-16 span"
            )
        ordered_blocks.append(
            (
                start,
                end,
                expected_hash,
                members[0].anchor_before_hash,
                members[0].anchor_after_hash,
            )
        )

    ordered_blocks.sort(key=lambda item: (item[0], item[1]))
    previous_block_end = 0
    for index, (_, _, block_hash, before_hash, after_hash) in enumerate(
        ordered_blocks
    ):
        block_start, block_end = ordered_blocks[index][0:2]
        if block_start != previous_block_end or block_end <= block_start:
            raise ScriptContractError(
                "source block spans must be contiguous and non-overlapping"
            )
        previous_block_end = block_end
        expected_before = ordered_blocks[index - 1][2] if index else None
        expected_after = (
            ordered_blocks[index + 1][2]
            if index + 1 < len(ordered_blocks)
            else None
        )
        if before_hash != expected_before or after_hash != expected_after:
            raise ScriptContractError(
                f"source block {block_hash} neighbor anchors differ from source order"
            )
    if previous_block_end != script.source_length_utf16:
        raise ScriptContractError(
            "source block spans must completely partition the source"
        )


def _expect_object(value: object, *, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise ScriptContractError(f"{field_name} must be a JSON object")
    return value


def _expect_list(value: object, *, field_name: str) -> list[object]:
    if type(value) is not list:
        raise ScriptContractError(f"{field_name} must be a JSON array")
    return value


def _expect_keys(
    payload: Mapping[str, object],
    *,
    required: Sequence[str],
    field_name: str,
) -> None:
    expected = set(required)
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ScriptContractError(
            f"{field_name} has invalid keys; missing={missing}, extra={extra}"
        )


def _parse_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not str:
        raise ScriptContractError(f"{field_name} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ScriptContractError(f"{field_name} must be a UUID string") from error
    if str(parsed) != value:
        raise ScriptContractError(f"{field_name} must use canonical lowercase UUID form")
    return _require_uuid(parsed, field_name=field_name)


def _parse_optional_uuid(value: object, *, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _parse_uuid(value, field_name=field_name)


def _parse_enum(value: object, enum_type: type[Enum], *, field_name: str) -> Enum:
    if type(value) is not str:
        raise ScriptContractError(f"{field_name} must be a string enum")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ScriptContractError(f"{field_name} has an unknown value") from error


def _parse_range(value: object, *, field_name: str) -> Utf16Range | None:
    if value is None:
        return None
    payload = _expect_object(value, field_name=field_name)
    _expect_keys(
        payload,
        required=("start", "end_exclusive"),
        field_name=field_name,
    )
    return Utf16Range(
        start=_require_exact_int(payload["start"], field_name=f"{field_name}.start"),
        end_exclusive=_require_exact_int(
            payload["end_exclusive"],
            field_name=f"{field_name}.end_exclusive",
        ),
    )


def _parse_string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_text(item, field_name=f"{field_name} item", maximum=96)
        for item in _expect_list(value, field_name=field_name)
    )


def _parse_uuid_tuple(value: object, *, field_name: str) -> tuple[UUID, ...]:
    return tuple(
        _parse_uuid(item, field_name=f"{field_name} item")
        for item in _expect_list(value, field_name=field_name)
    )


def _parse_speaker(value: object) -> SpeakerRef:
    payload = _expect_object(value, field_name="speaker")
    keys = ("kind", "character_id", "anonymous_speaker_id", "group_key")
    _expect_keys(payload, required=keys, field_name="speaker")
    return SpeakerRef(
        kind=_parse_enum(
            payload["kind"], SpeakerKind, field_name="speaker.kind"
        ),  # type: ignore[arg-type]
        character_id=_parse_optional_uuid(
            payload["character_id"], field_name="speaker.character_id"
        ),
        anonymous_speaker_id=_parse_optional_uuid(
            payload["anonymous_speaker_id"],
            field_name="speaker.anonymous_speaker_id",
        ),
        group_key=(
            None
            if payload["group_key"] is None
            else _require_text(
                payload["group_key"], field_name="speaker.group_key", maximum=80
            )
        ),
    )


def _parse_casting_target(value: object) -> CastingTargetRef:
    payload = _expect_object(value, field_name="casting target")
    keys = (
        "kind",
        "binding_id",
        "character_id",
        "anonymous_speaker_id",
        "pool_id",
        "slot_id",
        "profile_id",
    )
    _expect_keys(payload, required=keys, field_name="casting target")
    return CastingTargetRef(
        kind=_parse_enum(
            payload["kind"], CastingTargetKind, field_name="casting target kind"
        ),  # type: ignore[arg-type]
        binding_id=_parse_optional_uuid(
            payload["binding_id"], field_name="casting binding_id"
        ),
        character_id=_parse_optional_uuid(
            payload["character_id"], field_name="casting character_id"
        ),
        anonymous_speaker_id=_parse_optional_uuid(
            payload["anonymous_speaker_id"],
            field_name="casting anonymous_speaker_id",
        ),
        pool_id=_parse_optional_uuid(
            payload["pool_id"], field_name="casting pool_id"
        ),
        slot_id=_parse_optional_uuid(
            payload["slot_id"], field_name="casting slot_id"
        ),
        profile_id=_parse_optional_uuid(
            payload["profile_id"], field_name="casting profile_id"
        ),
    )


def _parse_casting_decision(value: object) -> CastingDecision:
    payload = _expect_object(value, field_name="casting")
    keys = (
        "contract_version",
        "candidate_targets",
        "final_target",
        "origin",
        "rule_id",
        "rule_version",
    )
    _expect_keys(payload, required=keys, field_name="casting")
    if payload["contract_version"] != NARRATION_CASTING_DECISION_VERSION:
        raise ScriptContractError("unknown casting decision contract version")
    final_target = payload["final_target"]
    rule_version = payload["rule_version"]
    return CastingDecision(
        candidate_targets=tuple(
            _parse_casting_target(item)
            for item in _expect_list(
                payload["candidate_targets"],
                field_name="casting candidate_targets",
            )
        ),
        final_target=(
            None if final_target is None else _parse_casting_target(final_target)
        ),
        origin=_parse_enum(
            payload["origin"],
            CastingDecisionOrigin,
            field_name="casting origin",
        ),  # type: ignore[arg-type]
        rule_id=_parse_optional_uuid(
            payload["rule_id"], field_name="casting rule_id"
        ),
        rule_version=(
            None
            if rule_version is None
            else _require_exact_int(
                rule_version, field_name="casting rule_version", minimum=1
            )
        ),
    )


def _parse_override_provenance(value: object) -> OverrideProvenance | None:
    if value is None:
        return None
    payload = _expect_object(value, field_name="override_provenance")
    keys = (
        "contract_version",
        "kind",
        "action_id",
        "owner_actor_id",
        "recorded_at",
        "source_script_version_id",
        "source_segment_id",
        "source_immutable_hash",
        "source_local_hash",
        "source_anchor_before_hash",
        "source_anchor_after_hash",
        "speaker_target_hash",
    )
    _expect_keys(payload, required=keys, field_name="override_provenance")
    recorded_at = _require_text(
        payload["recorded_at"], field_name="override recorded_at", maximum=64
    )
    try:
        parsed_at = datetime.fromisoformat(recorded_at)
    except ValueError as error:
        raise ScriptContractError(
            "override recorded_at must be ISO-8601"
        ) from error
    return OverrideProvenance(
        contract_version=_require_text(
            payload["contract_version"],
            field_name="override contract_version",
            maximum=120,
        ),
        kind=_parse_enum(
            payload["kind"], OverrideKind, field_name="override kind"
        ),  # type: ignore[arg-type]
        action_id=_parse_uuid(
            payload["action_id"], field_name="override action_id"
        ),
        owner_actor_id=_require_text(
            payload["owner_actor_id"],
            field_name="override owner_actor_id",
            maximum=120,
        ),
        recorded_at=parsed_at,
        source_script_version_id=_parse_optional_uuid(
            payload["source_script_version_id"],
            field_name="override source_script_version_id",
        ),
        source_segment_id=_parse_optional_uuid(
            payload["source_segment_id"],
            field_name="override source_segment_id",
        ),
        source_immutable_hash=_require_optional_sha256(
            payload["source_immutable_hash"],
            field_name="override source_immutable_hash",
        ),
        source_local_hash=_require_sha256(
            payload["source_local_hash"],
            field_name="override source_local_hash",
        ),
        source_anchor_before_hash=_require_optional_sha256(
            payload["source_anchor_before_hash"],
            field_name="override source_anchor_before_hash",
        ),
        source_anchor_after_hash=_require_optional_sha256(
            payload["source_anchor_after_hash"],
            field_name="override source_anchor_after_hash",
        ),
        speaker_target_hash=_require_sha256(
            payload["speaker_target_hash"],
            field_name="override speaker_target_hash",
        ),
    )


def _parse_attribution(value: object) -> AttributionEvidence:
    payload = _expect_object(value, field_name="attribution")
    keys = (
        "origin",
        "rule_codes",
        "candidate_character_ids",
        "consent_id",
        "model_run_id",
        "input_digest_key_id",
        "input_digest",
        "output_digest",
        "override_provenance",
    )
    _expect_keys(payload, required=keys, field_name="attribution")
    return AttributionEvidence(
        origin=_parse_enum(
            payload["origin"], AttributionOrigin, field_name="attribution.origin"
        ),  # type: ignore[arg-type]
        rule_codes=_parse_string_tuple(
            payload["rule_codes"], field_name="attribution.rule_codes"
        ),
        candidate_character_ids=_parse_uuid_tuple(
            payload["candidate_character_ids"],
            field_name="attribution.candidate_character_ids",
        ),
        consent_id=_parse_optional_uuid(
            payload["consent_id"], field_name="attribution.consent_id"
        ),
        model_run_id=_parse_optional_uuid(
            payload["model_run_id"], field_name="attribution.model_run_id"
        ),
        input_digest_key_id=(
            None
            if payload["input_digest_key_id"] is None
            else _require_text(
                payload["input_digest_key_id"],
                field_name="attribution.input_digest_key_id",
                maximum=80,
            )
        ),
        input_digest=_require_optional_sha256(
            payload["input_digest"], field_name="attribution.input_digest"
        ),
        output_digest=_require_optional_sha256(
            payload["output_digest"], field_name="attribution.output_digest"
        ),
        override_provenance=_parse_override_provenance(
            payload["override_provenance"]
        ),
    )


def _parse_anonymous(value: object) -> AnonymousSpeakerIdentity:
    payload = _expect_object(value, field_name="anonymous_speaker")
    keys = (
        "anonymous_speaker_id",
        "stable_key_algorithm",
        "stable_key",
        "display_name",
        "scope_kind",
        "scope_id",
        "confidence",
    )
    _expect_keys(payload, required=keys, field_name="anonymous_speaker")
    return AnonymousSpeakerIdentity(
        anonymous_speaker_id=_parse_uuid(
            payload["anonymous_speaker_id"], field_name="anonymous_speaker_id"
        ),
        stable_key_algorithm=_require_text(
            payload["stable_key_algorithm"],
            field_name="stable_key_algorithm",
            maximum=120,
        ),
        stable_key=_require_text(
            payload["stable_key"], field_name="stable_key", maximum=160
        ),
        display_name=_require_text(
            payload["display_name"],
            field_name="display_name",
            maximum=160,
        ),
        scope_kind=_parse_enum(
            payload["scope_kind"],
            AnonymousScopeKind,
            field_name="anonymous scope_kind",
        ),  # type: ignore[arg-type]
        scope_id=_parse_uuid(payload["scope_id"], field_name="anonymous scope_id"),
        confidence=_parse_enum(
            payload["confidence"], ConfidenceLevel, field_name="confidence"
        ),  # type: ignore[arg-type]
    )


def _parse_scene(value: object) -> SceneContract:
    payload = _expect_object(value, field_name="scene")
    keys = (
        "scene_id",
        "ordinal",
        "source_range_utf16",
        "boundary_source",
        "local_hash",
        "title",
    )
    _expect_keys(payload, required=keys, field_name="scene")
    return SceneContract(
        scene_id=_parse_uuid(payload["scene_id"], field_name="scene_id"),
        ordinal=_require_exact_int(payload["ordinal"], field_name="scene ordinal"),
        source_range_utf16=_parse_range(
            payload["source_range_utf16"], field_name="scene source_range_utf16"
        ),
        boundary_source=_parse_enum(
            payload["boundary_source"],
            SceneBoundarySource,
            field_name="scene boundary_source",
        ),  # type: ignore[arg-type]
        local_hash=_require_sha256(
            payload["local_hash"], field_name="scene local_hash"
        ),
        title=_require_optional_text(
            payload["title"], field_name="scene title", maximum=240
        ),
    )


def _parse_segment(value: object) -> SegmentContract:
    payload = _expect_object(value, field_name="segment")
    keys = (
        "segment_id",
        "ordinal",
        "scene_id",
        "segment_kind",
        "source_block_kind",
        "paragraph_ordinal",
        "segment_ordinal_in_block",
        "source_block_key",
        "source_block_hash",
        "source_range_utf16",
        "source_text",
        "spoken_text",
        "local_hash",
        "anchor_before_hash",
        "anchor_after_hash",
        "inheritance_anchor_before_hash",
        "inheritance_anchor_after_hash",
        "speaker",
        "casting",
        "confidence",
        "emotion",
        "emotion_confidence",
        "delivery",
        "attribution",
        "pause_before_ms",
        "pause_after_ms",
        "manual_override",
    )
    _expect_keys(payload, required=keys, field_name="segment")
    paragraph_ordinal = payload["paragraph_ordinal"]
    return SegmentContract(
        segment_id=_parse_uuid(payload["segment_id"], field_name="segment_id"),
        ordinal=_require_exact_int(payload["ordinal"], field_name="segment ordinal"),
        scene_id=_parse_optional_uuid(payload["scene_id"], field_name="scene_id"),
        segment_kind=_parse_enum(
            payload["segment_kind"], SegmentKind, field_name="segment_kind"
        ),  # type: ignore[arg-type]
        source_block_kind=_parse_enum(
            payload["source_block_kind"],
            SourceBlockKind,
            field_name="source_block_kind",
        ),  # type: ignore[arg-type]
        paragraph_ordinal=(
            None
            if paragraph_ordinal is None
            else _require_exact_int(
                paragraph_ordinal, field_name="paragraph_ordinal"
            )
        ),
        segment_ordinal_in_block=_require_exact_int(
            payload["segment_ordinal_in_block"],
            field_name="segment_ordinal_in_block",
        ),
        source_block_key=_require_text(
            payload["source_block_key"],
            field_name="source_block_key",
            maximum=160,
        ),
        source_block_hash=_require_sha256(
            payload["source_block_hash"], field_name="source_block_hash"
        ),
        source_range_utf16=_parse_range(
            payload["source_range_utf16"],
            field_name="segment source_range_utf16",
        ),
        source_text=_require_text(
            payload["source_text"], field_name="source_text", minimum=0
        ),
        spoken_text=_require_text(
            payload["spoken_text"], field_name="spoken_text", minimum=0
        ),
        local_hash=_require_sha256(
            payload["local_hash"], field_name="segment local_hash"
        ),
        anchor_before_hash=_require_optional_sha256(
            payload["anchor_before_hash"], field_name="anchor_before_hash"
        ),
        anchor_after_hash=_require_optional_sha256(
            payload["anchor_after_hash"], field_name="anchor_after_hash"
        ),
        inheritance_anchor_before_hash=_require_optional_sha256(
            payload["inheritance_anchor_before_hash"],
            field_name="inheritance_anchor_before_hash",
        ),
        inheritance_anchor_after_hash=_require_optional_sha256(
            payload["inheritance_anchor_after_hash"],
            field_name="inheritance_anchor_after_hash",
        ),
        speaker=_parse_speaker(payload["speaker"]),
        casting=_parse_casting_decision(payload["casting"]),
        confidence=_parse_enum(
            payload["confidence"], ConfidenceLevel, field_name="confidence"
        ),  # type: ignore[arg-type]
        emotion=_parse_enum(
            payload["emotion"], Emotion, field_name="emotion"
        ),  # type: ignore[arg-type]
        emotion_confidence=_parse_enum(
            payload["emotion_confidence"],
            ConfidenceLevel,
            field_name="emotion_confidence",
        ),  # type: ignore[arg-type]
        delivery=_parse_enum(
            payload["delivery"], Delivery, field_name="delivery"
        ),  # type: ignore[arg-type]
        attribution=_parse_attribution(payload["attribution"]),
        pause_before_ms=_require_exact_int(
            payload["pause_before_ms"], field_name="pause_before_ms"
        ),
        pause_after_ms=_require_exact_int(
            payload["pause_after_ms"], field_name="pause_after_ms"
        ),
        manual_override=_require_exact_bool(
            payload["manual_override"], field_name="manual_override"
        ),
    )


def _parse_issue(value: object) -> ScriptIssueContract:
    payload = _expect_object(value, field_name="issue")
    keys = (
        "code",
        "severity",
        "segment_id",
        "evidence_summary",
        "evidence_digest",
        "taxonomy_version",
    )
    _expect_keys(payload, required=keys, field_name="issue")
    return ScriptIssueContract(
        code=_require_text(payload["code"], field_name="issue code", maximum=96),
        severity=_parse_enum(
            payload["severity"],
            ReviewIssueSeverity,
            field_name="issue severity",
        ),  # type: ignore[arg-type]
        segment_id=_parse_optional_uuid(
            payload["segment_id"], field_name="issue segment_id"
        ),
        evidence_summary=_require_optional_text(
            payload["evidence_summary"],
            field_name="issue evidence_summary",
            maximum=500,
        ),
        evidence_digest=_require_optional_sha256(
            payload["evidence_digest"], field_name="issue evidence_digest"
        ),
        taxonomy_version=_require_text(
            payload["taxonomy_version"],
            field_name="issue taxonomy_version",
            maximum=120,
        ),
    )


def _parse_approval(value: object) -> ScriptApproval | None:
    if value is None:
        return None
    payload = _expect_object(value, field_name="approval")
    keys = ("kind", "request_id", "actor_type", "actor_id", "approved_at")
    _expect_keys(payload, required=keys, field_name="approval")
    approved_at = _require_text(
        payload["approved_at"], field_name="approved_at", maximum=64
    )
    try:
        parsed_at = datetime.fromisoformat(approved_at)
    except ValueError as error:
        raise ScriptContractError("approved_at must be ISO-8601") from error
    return ScriptApproval(
        kind=_parse_enum(
            payload["kind"], ScriptApprovalKind, field_name="approval kind"
        ),  # type: ignore[arg-type]
        request_id=_parse_uuid(
            payload["request_id"], field_name="approval request_id"
        ),
        actor_type=_parse_enum(
            payload["actor_type"],
            ApprovalActorType,
            field_name="approval actor_type",
        ),  # type: ignore[arg-type]
        actor_id=_require_text(
            payload["actor_id"], field_name="approval actor_id", maximum=120
        ),
        approved_at=parsed_at,
    )


def script_contract_from_dict(
    value: object,
    *,
    authority: ScriptAuthorityContext,
    source_text: str,
) -> NarrationScriptContract:
    payload = _expect_object(value, field_name="script contract")
    keys = (
        "schema_version",
        "taxonomy_version",
        "script_id",
        "script_version_id",
        "novel_id",
        "document_id",
        "revision_id",
        "source_content_hash",
        "source_length_utf16",
        "version_number",
        "parent_version_id",
        "state",
        "effective_policy",
        "analyzer_fingerprint",
        "rules_fingerprint",
        "settings_fingerprint",
        "requested_model_fingerprint",
        "actual_model_fingerprint",
        "anonymous_speakers",
        "scenes",
        "segments",
        "issues",
        "warning_count",
        "blocker_count",
        "immutable_hash",
        "approval",
    )
    _expect_keys(payload, required=keys, field_name="script contract")
    requested_model = payload["requested_model_fingerprint"]
    actual_model = payload["actual_model_fingerprint"]
    script = NarrationScriptContract(
        schema_version=_require_text(
            payload["schema_version"], field_name="schema_version", maximum=120
        ),
        taxonomy_version=_require_text(
            payload["taxonomy_version"],
            field_name="taxonomy_version",
            maximum=120,
        ),
        script_id=_parse_uuid(payload["script_id"], field_name="script_id"),
        script_version_id=_parse_uuid(
            payload["script_version_id"], field_name="script_version_id"
        ),
        novel_id=_parse_uuid(payload["novel_id"], field_name="novel_id"),
        document_id=_parse_uuid(
            payload["document_id"], field_name="document_id"
        ),
        revision_id=_parse_uuid(
            payload["revision_id"], field_name="revision_id"
        ),
        source_content_hash=_require_sha256(
            payload["source_content_hash"], field_name="source_content_hash"
        ),
        source_length_utf16=_require_exact_int(
            payload["source_length_utf16"], field_name="source_length_utf16"
        ),
        version_number=_require_exact_int(
            payload["version_number"], field_name="version_number", minimum=1
        ),
        parent_version_id=_parse_optional_uuid(
            payload["parent_version_id"], field_name="parent_version_id"
        ),
        state=_parse_enum(
            payload["state"], ScriptVersionState, field_name="state"
        ),  # type: ignore[arg-type]
        effective_policy=_parse_enum(
            payload["effective_policy"],
            ScriptReviewPolicy,
            field_name="effective_policy",
        ),  # type: ignore[arg-type]
        analyzer_fingerprint=_require_sha256(
            payload["analyzer_fingerprint"], field_name="analyzer_fingerprint"
        ),
        rules_fingerprint=_require_sha256(
            payload["rules_fingerprint"], field_name="rules_fingerprint"
        ),
        settings_fingerprint=_require_sha256(
            payload["settings_fingerprint"], field_name="settings_fingerprint"
        ),
        requested_model_fingerprint=(
            None
            if requested_model is None
            else _require_sha256(
                requested_model, field_name="requested_model_fingerprint"
            )
        ),
        actual_model_fingerprint=(
            None
            if actual_model is None
            else _require_sha256(
                actual_model, field_name="actual_model_fingerprint"
            )
        ),
        anonymous_speakers=tuple(
            _parse_anonymous(item)
            for item in _expect_list(
                payload["anonymous_speakers"], field_name="anonymous_speakers"
            )
        ),
        scenes=tuple(
            _parse_scene(item)
            for item in _expect_list(payload["scenes"], field_name="scenes")
        ),
        segments=tuple(
            _parse_segment(item)
            for item in _expect_list(payload["segments"], field_name="segments")
        ),
        issues=tuple(
            _parse_issue(item)
            for item in _expect_list(payload["issues"], field_name="issues")
        ),
        warning_count=_require_exact_int(
            payload["warning_count"], field_name="warning_count"
        ),
        blocker_count=_require_exact_int(
            payload["blocker_count"], field_name="blocker_count"
        ),
        immutable_hash=_require_sha256(
            payload["immutable_hash"], field_name="immutable_hash"
        ),
        approval=_parse_approval(payload["approval"]),
    )
    validate_authorized_references(script, authority)
    validate_source_mapping(source_text, script)
    return script


__all__ = [
    "ANONYMOUS_SPEAKER_STABLE_KEY_VERSION",
    "GROUP_SPEAKER_KEY_VERSION",
    "NARRATION_CASTING_DECISION_VERSION",
    "NARRATION_SCRIPT_CONTRACT_VERSION",
    "NARRATION_SCRIPT_ID_CONTRACT_VERSION",
    "NARRATION_SEGMENT_EVIDENCE_VERSION",
    "NARRATION_SOURCE_BLOCK_KEY_VERSION",
    "OVERRIDE_PROVENANCE_VERSION",
    "SOURCE_BOUND_SEGMENT_KINDS",
    "SOURCE_RANGE_SEMANTICS",
    "SCRIPT_STATE_TRANSITIONS",
    "SPEAKER_TARGET_HASH_VERSION",
    "SYNTHETIC_SEGMENT_KINDS",
    "UTF16_OFFSET_UNIT",
    "AnonymousScopeKind",
    "AnonymousSpeakerIdentity",
    "ApprovalActorType",
    "AttributionEvidence",
    "AttributionOrigin",
    "CastingDecision",
    "CastingDecisionOrigin",
    "CastingRuleAuthorityRecord",
    "CastingTargetKind",
    "CastingTargetRef",
    "CloudAuthorityRecord",
    "Delivery",
    "Emotion",
    "NarrationScriptContract",
    "OverrideKind",
    "OverrideProvenance",
    "SceneBoundarySource",
    "SceneContract",
    "ScriptApproval",
    "ScriptApprovalKind",
    "ScriptAuthorityContext",
    "ScriptContractError",
    "ScriptIssueContract",
    "ScriptReviewPolicy",
    "ScriptVersionState",
    "SegmentContract",
    "SegmentKind",
    "SourceBlockKind",
    "SpeakerKind",
    "SpeakerRef",
    "Utf16Range",
    "derive_anonymous_speaker_id",
    "derive_anonymous_stable_key",
    "derive_group_key",
    "derive_scene_id",
    "derive_segment_id",
    "derive_source_block_key",
    "ensure_script_transition",
    "initial_materialized_state",
    "normalize_identity_label",
    "script_contract_from_dict",
    "script_contract_to_dict",
    "script_immutable_hash",
    "script_immutable_payload",
    "speaker_target_hash",
    "text_sha256",
    "utf16_length",
    "utf16_slice",
    "validate_authorized_references",
    "validate_source_mapping",
]
