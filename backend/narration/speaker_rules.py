"""Auditable local-first speaker attribution rules for T3-C.

This module never calls a model, persists an identity, or creates a formal
character.  Exact alias conflicts and unresolved labels become frozen review
blockers instead of being guessed from scene membership.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Mapping, Sequence
from uuid import UUID

from .aliases import (
    AliasContractError,
    AliasResolutionKind,
    CharacterAliasIndex,
    normalize_character_alias,
)
from .contracts import (
    BLOCKER_CODES,
    WARNING_CODES,
    ConfidenceLevel,
    issue_severity,
)
from .script_contracts import (
    AttributionEvidence,
    AttributionOrigin,
    SegmentKind,
    SpeakerKind,
    SpeakerRef,
    ScriptIssueContract,
)


LOCAL_SPEAKER_RULESET_VERSION: Final = "local-speaker-rules/2"

_SPEECH_VERBS = (
    "开口说道",
    "开口说",
    "喃喃道",
    "回答道",
    "回应道",
    "说道",
    "问道",
    "喊道",
    "答道",
    "叫道",
    "嚷道",
    "吼道",
    "喝道",
    "回答",
    "回应",
    "低语",
    "耳语",
    "嘀咕",
    "暗道",
    "说",
    "问",
    "喊",
    "答",
    "叫",
    "嚷",
    "吼",
    "道",
)
_DELIVERY_MODIFIERS = (
    "压低声音",
    "提高声音",
    "轻声",
    "低声",
    "沉声",
    "高声",
    "大声",
    "小声",
    "厉声",
    "柔声",
    "冷声",
    "笑着",
    "哭着",
    "喃喃",
    "缓缓",
    "齐声",
)
_ACTION_VERBS = (
    "笑了一下",
    "皱眉",
    "点头",
    "摇头",
    "抬眼",
    "转身",
    "冷笑",
    "叹气",
    "挥手",
    "闭眼",
    "看向",
    "看着",
    "望向",
    "笑了",
    "把",
)

_LABEL = r"(?P<label>[^\r\n，。！？!?；;：:“”「」『』\"'（）()<>《》]{1,32}?)"
_MODIFIER = "(?:" + "|".join(map(re.escape, _DELIVERY_MODIFIERS)) + ")?"
_VERB = "(?:" + "|".join(map(re.escape, _SPEECH_VERBS)) + ")"
_ACTION = "(?:" + "|".join(map(re.escape, _ACTION_VERBS)) + ")"
_PREFIX_CUE = re.compile(
    rf"^\s*{_LABEL}\s*{_MODIFIER}\s*地?\s*{_VERB}\s*[：:,，]?"
)
_SUFFIX_CUE = re.compile(
    rf"[”」』\"']\s*[，,。.!?！？]?\s*{_LABEL}\s*{_MODIFIER}\s*地?\s*{_VERB}\s*[。.!?！？]?\s*$"
)
_ACTION_BEFORE_DIALOGUE = re.compile(
    rf"^\s*{_LABEL}\s*{_ACTION}[^\n。！？：:]{{0,24}}[。！？：:]\s*[“「『\"']"
)

_ANONYMOUS_MARKERS = (
    "一个",
    "一名",
    "一位",
    "年轻女人",
    "年轻男人",
    "中年女人",
    "中年男人",
    "老妇人",
    "老人",
    "老者",
    "妇人",
    "男人",
    "女人",
    "男孩",
    "女孩",
    "小男孩",
    "小女孩",
    "男童",
    "女童",
    "少年",
    "少女",
    "青年男性",
    "青年女性",
    "中年男性",
    "中年女性",
    "老年男性",
    "老年女性",
    "中性声音",
    "掌柜",
    "侍卫",
    "医生",
    "店小二",
)
_GROUP_MARKERS = (
    "众人",
    "大家",
    "人群",
    "齐声",
    "众弟子",
    "侍卫们",
    "孩子们",
    "人们",
    "男人们",
    "女人们",
    "男孩们",
    "女孩们",
    "男声群体",
    "女声群体",
)


class SpeakerRuleError(ValueError):
    """Raised for invalid rule input, never for an ordinary unknown speaker."""


def _require_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if type(value) is not str or (not allow_empty and not value) or len(value) > maximum:
        raise SpeakerRuleError(
            f"{field_name} must be a string of at most {maximum} characters"
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SpeakerRuleError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


def _speaker_sort_key(speaker: SpeakerRef) -> tuple[str, str, str, str]:
    return (
        speaker.kind.value,
        str(speaker.character_id or ""),
        str(speaker.anonymous_speaker_id or ""),
        speaker.group_key or "",
    )


@dataclass(frozen=True, slots=True)
class ResolvedSpeakerLabel:
    """A server-authorized anonymous/group label supplied by another owner."""

    label: str
    speaker: SpeakerRef
    active: bool = True

    def __post_init__(self) -> None:
        _require_text(
            self.label,
            field_name="resolved speaker label",
            maximum=80,
            allow_empty=False,
        )
        if type(self.speaker) is not SpeakerRef or self.speaker.kind not in {
            SpeakerKind.ANONYMOUS,
            SpeakerKind.GROUP,
        }:
            raise SpeakerRuleError(
                "resolved labels may only name typed anonymous/group speakers"
            )
        if type(self.active) is not bool:
            raise SpeakerRuleError("resolved speaker active must be an exact boolean")

    @property
    def normalized_label(self) -> str:
        try:
            return normalize_character_alias(self.label)
        except AliasContractError as error:
            raise SpeakerRuleError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ResolvedSpeakerIndex:
    allowed_speakers: frozenset[SpeakerRef]
    records: tuple[ResolvedSpeakerLabel, ...]
    _speakers_by_label: Mapping[str, tuple[SpeakerRef, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.allowed_speakers) is not frozenset or not all(
            type(speaker) is SpeakerRef
            and speaker.kind in {SpeakerKind.ANONYMOUS, SpeakerKind.GROUP}
            for speaker in self.allowed_speakers
        ):
            raise SpeakerRuleError(
                "allowed_speakers must be a frozenset of anonymous/group SpeakerRef"
            )
        if type(self.records) is not tuple or not all(
            type(record) is ResolvedSpeakerLabel for record in self.records
        ):
            raise SpeakerRuleError(
                "records must be a tuple of ResolvedSpeakerLabel"
            )
        canonical = tuple(
            sorted(
                self.records,
                key=lambda record: (
                    record.normalized_label,
                    _speaker_sort_key(record.speaker),
                    record.label,
                    not record.active,
                ),
            )
        )
        if self.records != canonical:
            raise SpeakerRuleError("resolved speaker records must use canonical order")
        if any(
            record.speaker not in self.allowed_speakers for record in self.records
        ):
            raise SpeakerRuleError(
                "resolved speaker record is outside server authority"
            )

        active: dict[str, set[SpeakerRef]] = {}
        for record in self.records:
            if record.active:
                active.setdefault(record.normalized_label, set()).add(record.speaker)
        object.__setattr__(
            self,
            "_speakers_by_label",
            MappingProxyType(
                {
                    label: tuple(sorted(speakers, key=_speaker_sort_key))
                    for label, speakers in sorted(active.items())
                }
            ),
        )

    def resolve(self, label: str) -> tuple[SpeakerRef, ...]:
        try:
            normalized = normalize_character_alias(label)
        except AliasContractError as error:
            raise SpeakerRuleError(str(error)) from error
        return self._speakers_by_label.get(normalized, ())


def build_resolved_speaker_index(
    records: Sequence[ResolvedSpeakerLabel],
    *,
    allowed_speakers: frozenset[SpeakerRef],
) -> ResolvedSpeakerIndex:
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise SpeakerRuleError("resolved speaker records must be a sequence")
    if not all(type(record) is ResolvedSpeakerLabel for record in records):
        raise SpeakerRuleError(
            "resolved speaker records contain an invalid value"
        )
    canonical = tuple(
        sorted(
            records,
            key=lambda record: (
                record.normalized_label,
                _speaker_sort_key(record.speaker),
                record.label,
                not record.active,
            ),
        )
    )
    return ResolvedSpeakerIndex(
        allowed_speakers=allowed_speakers,
        records=canonical,
    )


@dataclass(frozen=True, slots=True)
class SpeakerRuleContext:
    segment_kind: SegmentKind
    source_text: str
    cue_before: str = ""
    cue_after: str = ""
    scene_character_ids: frozenset[UUID] = frozenset()
    previous_speaker: SpeakerRef | None = None
    same_paragraph_continuation: bool = False
    explicit_speaker: SpeakerRef | None = None
    ruleset_version: str = LOCAL_SPEAKER_RULESET_VERSION

    def __post_init__(self) -> None:
        if type(self.segment_kind) is not SegmentKind:
            raise SpeakerRuleError("segment_kind must be SegmentKind")
        _require_text(
            self.source_text,
            field_name="source_text",
            maximum=20_000,
            allow_empty=True,
        )
        _require_text(
            self.cue_before,
            field_name="cue_before",
            maximum=2_000,
            allow_empty=True,
        )
        _require_text(
            self.cue_after,
            field_name="cue_after",
            maximum=2_000,
            allow_empty=True,
        )
        if type(self.scene_character_ids) is not frozenset or not all(
            type(character_id) is UUID for character_id in self.scene_character_ids
        ):
            raise SpeakerRuleError("scene_character_ids must be a frozenset of UUID")
        if self.previous_speaker is not None and type(
            self.previous_speaker
        ) is not SpeakerRef:
            raise SpeakerRuleError("previous_speaker must be SpeakerRef or None")
        if type(self.same_paragraph_continuation) is not bool:
            raise SpeakerRuleError(
                "same_paragraph_continuation must be an exact boolean"
            )
        if self.explicit_speaker is not None and type(
            self.explicit_speaker
        ) is not SpeakerRef:
            raise SpeakerRuleError("explicit_speaker must be SpeakerRef or None")
        if self.ruleset_version != LOCAL_SPEAKER_RULESET_VERSION:
            raise SpeakerRuleError("unknown local speaker ruleset version")


@dataclass(frozen=True, slots=True)
class SpeakerRuleDecision:
    speaker: SpeakerRef
    confidence: ConfidenceLevel
    attribution: AttributionEvidence
    issue_codes: tuple[str, ...]
    unresolved_label: str | None = None
    unresolved_kind: SpeakerKind | None = None
    ruleset_version: str = LOCAL_SPEAKER_RULESET_VERSION

    def __post_init__(self) -> None:
        if type(self.speaker) is not SpeakerRef:
            raise SpeakerRuleError("speaker must be SpeakerRef")
        if type(self.confidence) is not ConfidenceLevel:
            raise SpeakerRuleError("confidence must be ConfidenceLevel")
        if (
            type(self.attribution) is not AttributionEvidence
            or self.attribution.origin is not AttributionOrigin.LOCAL_RULE
        ):
            raise SpeakerRuleError(
                "local speaker decision requires local_rule AttributionEvidence"
            )
        if type(self.issue_codes) is not tuple or self.issue_codes != tuple(
            sorted(set(self.issue_codes))
        ):
            raise SpeakerRuleError("issue_codes must be unique and canonically sorted")
        allowed_codes = set(BLOCKER_CODES) | set(WARNING_CODES)
        if any(code not in allowed_codes for code in self.issue_codes):
            raise SpeakerRuleError("decision contains an unknown review issue code")
        if self.unresolved_label is not None:
            _require_text(
                self.unresolved_label,
                field_name="unresolved_label",
                maximum=80,
                allow_empty=False,
            )
        if self.unresolved_kind is not None and (
            type(self.unresolved_kind) is not SpeakerKind
            or self.unresolved_kind
            not in {SpeakerKind.ANONYMOUS, SpeakerKind.GROUP, SpeakerKind.UNKNOWN}
        ):
            raise SpeakerRuleError(
                "unresolved_kind must be anonymous, group, unknown, or None"
            )
        if self.speaker.kind is SpeakerKind.UNKNOWN:
            required = {"B_SPEAKER_LOW_CONFIDENCE", "B_SPEAKER_UNKNOWN"}
            if not required.issubset(self.issue_codes):
                raise SpeakerRuleError(
                    "unknown speaker decision lacks frozen confidence/unknown blockers"
                )
        elif self.unresolved_label is not None or self.unresolved_kind is not None:
            raise SpeakerRuleError(
                "resolved speaker decision cannot carry unresolved label metadata"
            )
        if (
            self.confidence is ConfidenceLevel.MEDIUM
            and "W_SPEAKER_MEDIUM_CONFIDENCE" not in self.issue_codes
        ):
            raise SpeakerRuleError("medium confidence lacks its frozen warning")
        if self.ruleset_version != LOCAL_SPEAKER_RULESET_VERSION:
            raise SpeakerRuleError("unknown local speaker ruleset version")

    def to_script_issues(self, *, segment_id: UUID) -> tuple[ScriptIssueContract, ...]:
        """Materialize exact T3-A issue rows for one already-derived segment ID."""

        if type(segment_id) is not UUID:
            raise SpeakerRuleError("segment_id must be UUID")
        return tuple(
            ScriptIssueContract(
                code=code,
                severity=issue_severity(code),
                segment_id=segment_id,
            )
            for code in self.issue_codes
        )


@dataclass(frozen=True, slots=True)
class _Cue:
    label: str
    rule_code: str


def _cue_from_match(match: re.Match[str] | None, rule_code: str) -> _Cue | None:
    if match is None:
        return None
    label = unicodedata.normalize("NFC", match.group("label").strip())
    if not label:
        return None
    return _Cue(label=label, rule_code=rule_code)


def _extract_cues(context: SpeakerRuleContext) -> tuple[_Cue, ...]:
    found: dict[tuple[str, str], _Cue] = {}

    def collect(
        text: str,
        *,
        window_code: str,
        patterns: Sequence[tuple[re.Pattern[str], str]],
    ) -> None:
        if not text:
            return
        for pattern, shape in patterns:
            cue = _cue_from_match(
                pattern.search(text),
                f"speaker.{shape}.{window_code}",
            )
            if cue is None:
                continue
            try:
                normalized = normalize_character_alias(cue.label)
            except AliasContractError:
                continue
            found[(normalized, cue.rule_code)] = cue

    collect(
        context.source_text,
        window_code="source",
        patterns=(
            (_PREFIX_CUE, "prefix"),
            (_SUFFIX_CUE, "suffix"),
            (_ACTION_BEFORE_DIALOGUE, "action_before_dialogue"),
        ),
    )
    collect(
        context.cue_before[-160:] + context.source_text,
        window_code="context_before",
        patterns=(
            (_PREFIX_CUE, "prefix"),
            (_ACTION_BEFORE_DIALOGUE, "action_before_dialogue"),
        ),
    )
    collect(
        context.source_text + context.cue_after[:160],
        window_code="context_after",
        patterns=((_SUFFIX_CUE, "suffix"),),
    )
    collect(
        context.cue_after[:160],
        window_code="cue_after",
        patterns=((_PREFIX_CUE, "prefix"),),
    )
    return tuple(
        sorted(found.values(), key=lambda cue: (normalize_character_alias(cue.label), cue.rule_code))
    )


def _unknown_kind_for_label(label: str | None) -> SpeakerKind:
    if label is None:
        return SpeakerKind.UNKNOWN
    normalized = unicodedata.normalize("NFKC", label).casefold()
    if any(marker in normalized for marker in _GROUP_MARKERS):
        return SpeakerKind.GROUP
    if any(marker in normalized for marker in _ANONYMOUS_MARKERS):
        return SpeakerKind.ANONYMOUS
    return SpeakerKind.UNKNOWN


def _decision(
    *,
    speaker: SpeakerRef,
    confidence: ConfidenceLevel,
    rule_codes: Sequence[str],
    candidate_character_ids: Sequence[UUID] = (),
    extra_issue_codes: Sequence[str] = (),
    unresolved_label: str | None = None,
    unresolved_kind: SpeakerKind | None = None,
) -> SpeakerRuleDecision:
    rules = tuple(sorted(set(rule_codes)))
    candidates = tuple(sorted(set(candidate_character_ids), key=str))
    if len(rules) > 16:
        raise SpeakerRuleError("local rule evidence exceeds the T3-A limit of 16")
    if len(candidates) > 32:
        raise SpeakerRuleError(
            "speaker candidates exceed the T3-A limit of 32"
        )
    issues = set(extra_issue_codes)
    if confidence is ConfidenceLevel.MEDIUM:
        issues.add("W_SPEAKER_MEDIUM_CONFIDENCE")
    if confidence in {ConfidenceLevel.LOW, ConfidenceLevel.UNKNOWN}:
        issues.add("B_SPEAKER_LOW_CONFIDENCE")
    if speaker.kind is SpeakerKind.UNKNOWN:
        issues.add("B_SPEAKER_UNKNOWN")
    return SpeakerRuleDecision(
        speaker=speaker,
        confidence=confidence,
        attribution=AttributionEvidence(
            origin=AttributionOrigin.LOCAL_RULE,
            rule_codes=rules,
            candidate_character_ids=candidates,
        ),
        issue_codes=tuple(sorted(issues)),
        unresolved_label=unresolved_label,
        unresolved_kind=unresolved_kind,
    )


def _validate_authorized_context(
    context: SpeakerRuleContext,
    aliases: CharacterAliasIndex,
) -> None:
    if not context.scene_character_ids.issubset(aliases.allowed_character_ids):
        raise SpeakerRuleError(
            "scene_character_ids contain a character outside server authority"
        )


def _explicit_decision(
    speaker: SpeakerRef,
    *,
    aliases: CharacterAliasIndex,
    resolved_speakers: ResolvedSpeakerIndex,
) -> SpeakerRuleDecision:
    if speaker.kind is SpeakerKind.CHARACTER:
        if speaker.character_id not in aliases.allowed_character_ids:
            return _decision(
                speaker=SpeakerRef(SpeakerKind.UNKNOWN),
                confidence=ConfidenceLevel.UNKNOWN,
                rule_codes=("speaker.explicit.invalid_character",),
                extra_issue_codes=("B_CHARACTER_REFERENCE_INVALID",),
                unresolved_kind=SpeakerKind.UNKNOWN,
            )
        return _decision(
            speaker=speaker,
            confidence=ConfidenceLevel.HIGH,
            rule_codes=("speaker.explicit.character",),
            candidate_character_ids=(speaker.character_id,),
        )
    if speaker.kind in {SpeakerKind.ANONYMOUS, SpeakerKind.GROUP}:
        if speaker not in resolved_speakers.allowed_speakers:
            return _decision(
                speaker=SpeakerRef(SpeakerKind.UNKNOWN),
                confidence=ConfidenceLevel.UNKNOWN,
                rule_codes=("speaker.explicit.invalid_non_character",),
                extra_issue_codes=("B_ANONYMOUS_IDENTITY_CONFLICT",),
                unresolved_kind=speaker.kind,
            )
        return _decision(
            speaker=speaker,
            confidence=ConfidenceLevel.HIGH,
            rule_codes=("speaker.explicit.non_character",),
        )
    if speaker.kind is SpeakerKind.NARRATOR:
        return _decision(
            speaker=speaker,
            confidence=ConfidenceLevel.HIGH,
            rule_codes=("speaker.explicit.narrator",),
        )
    return _decision(
        speaker=SpeakerRef(SpeakerKind.UNKNOWN),
        confidence=ConfidenceLevel.UNKNOWN,
        rule_codes=("speaker.explicit.unknown",),
        unresolved_kind=SpeakerKind.UNKNOWN,
    )


def attribute_speaker_local(
    context: SpeakerRuleContext,
    *,
    aliases: CharacterAliasIndex,
    resolved_speakers: ResolvedSpeakerIndex | None = None,
) -> SpeakerRuleDecision:
    """Attribute one segment using only deterministic, explainable inputs."""

    if type(context) is not SpeakerRuleContext:
        raise SpeakerRuleError("context must be SpeakerRuleContext")
    if type(aliases) is not CharacterAliasIndex:
        raise SpeakerRuleError("aliases must be CharacterAliasIndex")
    if resolved_speakers is None:
        resolved_speakers = build_resolved_speaker_index(
            (),
            allowed_speakers=frozenset(),
        )
    if type(resolved_speakers) is not ResolvedSpeakerIndex:
        raise SpeakerRuleError("resolved_speakers must be ResolvedSpeakerIndex")
    _validate_authorized_context(context, aliases)

    if context.segment_kind in {
        SegmentKind.NARRATION,
        SegmentKind.CHAPTER_TITLE,
        SegmentKind.SYNTHETIC_PAUSE,
    }:
        return _decision(
            speaker=SpeakerRef(SpeakerKind.NARRATOR),
            confidence=ConfidenceLevel.HIGH,
            rule_codes=("speaker.segment_kind.narrator",),
        )

    if context.explicit_speaker is not None:
        if context.segment_kind not in {
            SegmentKind.INNER_MONOLOGUE,
            SegmentKind.MESSAGE,
            SegmentKind.LETTER,
            SegmentKind.BROADCAST,
            SegmentKind.PHONE,
        }:
            raise SpeakerRuleError(
                "explicit_speaker is only valid for configured non-dialogue forms"
            )
        return _explicit_decision(
            context.explicit_speaker,
            aliases=aliases,
            resolved_speakers=resolved_speakers,
        )

    cues = _extract_cues(context)
    if cues:
        by_label: dict[str, list[_Cue]] = {}
        for cue in cues:
            normalized = normalize_character_alias(cue.label)
            by_label.setdefault(normalized, []).append(cue)

        resolved_by_label: dict[str, SpeakerRef] = {}
        unresolved_labels: dict[str, str] = {}
        candidate_ids: set[UUID] = set()
        extra_issues: set[str] = set()
        rule_codes = {cue.rule_code for cue in cues}

        for normalized, label_cues in sorted(by_label.items()):
            label = label_cues[0].label
            alias_resolution = aliases.resolve(label)
            non_character_matches = resolved_speakers.resolve(label)
            candidate_ids.update(alias_resolution.character_ids)

            if alias_resolution.kind is AliasResolutionKind.CONFLICT:
                extra_issues.add("B_CHARACTER_ALIAS_CONFLICT")
                rule_codes.add("speaker.alias.conflict")
                continue
            if (
                alias_resolution.kind is AliasResolutionKind.UNIQUE
                and non_character_matches
            ):
                extra_issues.add("B_CHARACTER_ALIAS_CONFLICT")
                rule_codes.add("speaker.alias.cross_kind_conflict")
                continue
            if alias_resolution.kind is AliasResolutionKind.UNIQUE:
                character_id = alias_resolution.character_id
                if character_id is None:
                    raise SpeakerRuleError("unique alias resolution lost character_id")
                resolved_by_label[normalized] = SpeakerRef(
                    SpeakerKind.CHARACTER,
                    character_id=character_id,
                )
                rule_codes.add("speaker.alias.exact")
                if (
                    context.scene_character_ids
                    and character_id not in context.scene_character_ids
                ):
                    rule_codes.add("speaker.scene.explicit_new_entry")
                continue
            if len(non_character_matches) > 1:
                extra_issues.add("B_ANONYMOUS_IDENTITY_CONFLICT")
                rule_codes.add("speaker.non_character.conflict")
                continue
            if len(non_character_matches) == 1:
                resolved_by_label[normalized] = non_character_matches[0]
                rule_codes.add("speaker.non_character.exact")
                continue
            unresolved_labels[normalized] = label
            rule_codes.add("speaker.cue.unresolved")

        resolved_values = set(resolved_by_label.values())
        has_conflict = bool(extra_issues)
        if (
            not has_conflict
            and not unresolved_labels
            and len(resolved_values) == 1
        ):
            speaker = next(iter(resolved_values))
            return _decision(
                speaker=speaker,
                confidence=ConfidenceLevel.HIGH,
                rule_codes=rule_codes,
                candidate_character_ids=(
                    (speaker.character_id,)
                    if speaker.kind is SpeakerKind.CHARACTER
                    and speaker.character_id is not None
                    else ()
                ),
            )

        if len(by_label) > 1 or len(resolved_values) > 1:
            rule_codes.add("speaker.cue.multiple_targets")
        unresolved_label = (
            next(iter(unresolved_labels.values()))
            if len(unresolved_labels) == 1 and not resolved_values
            else None
        )
        unresolved_kind = _unknown_kind_for_label(unresolved_label)
        if unresolved_kind is SpeakerKind.ANONYMOUS:
            extra_issues.add("W_NEW_ANONYMOUS_SPEAKER")
        return _decision(
            speaker=SpeakerRef(SpeakerKind.UNKNOWN),
            confidence=ConfidenceLevel.UNKNOWN,
            rule_codes=rule_codes,
            candidate_character_ids=candidate_ids,
            extra_issue_codes=extra_issues,
            unresolved_label=unresolved_label,
            unresolved_kind=unresolved_kind,
        )

    if context.same_paragraph_continuation and context.previous_speaker is not None:
        previous = context.previous_speaker
        if (
            previous.kind is SpeakerKind.CHARACTER
            and previous.character_id not in aliases.allowed_character_ids
        ):
            return _decision(
                speaker=SpeakerRef(SpeakerKind.UNKNOWN),
                confidence=ConfidenceLevel.UNKNOWN,
                rule_codes=("speaker.continuation.invalid_character",),
                extra_issue_codes=("B_CHARACTER_REFERENCE_INVALID",),
                unresolved_kind=SpeakerKind.UNKNOWN,
            )
        if previous.kind in {SpeakerKind.ANONYMOUS, SpeakerKind.GROUP} and (
            previous not in resolved_speakers.allowed_speakers
        ):
            return _decision(
                speaker=SpeakerRef(SpeakerKind.UNKNOWN),
                confidence=ConfidenceLevel.UNKNOWN,
                rule_codes=("speaker.continuation.invalid_non_character",),
                extra_issue_codes=("B_ANONYMOUS_IDENTITY_CONFLICT",),
                unresolved_kind=previous.kind,
            )
        if previous.kind in {
            SpeakerKind.CHARACTER,
            SpeakerKind.ANONYMOUS,
            SpeakerKind.GROUP,
        }:
            return _decision(
                speaker=previous,
                confidence=ConfidenceLevel.MEDIUM,
                rule_codes=("speaker.continuation.same_paragraph",),
                candidate_character_ids=(
                    (previous.character_id,)
                    if previous.kind is SpeakerKind.CHARACTER
                    and previous.character_id is not None
                    else ()
                ),
            )

    return _decision(
        speaker=SpeakerRef(SpeakerKind.UNKNOWN),
        confidence=ConfidenceLevel.UNKNOWN,
        rule_codes=("speaker.no_deterministic_match",),
        unresolved_kind=SpeakerKind.UNKNOWN,
    )


__all__ = [
    "LOCAL_SPEAKER_RULESET_VERSION",
    "ResolvedSpeakerIndex",
    "ResolvedSpeakerLabel",
    "SpeakerRuleContext",
    "SpeakerRuleDecision",
    "SpeakerRuleError",
    "attribute_speaker_local",
    "build_resolved_speaker_index",
]
