"""Deterministic v1 emotion and delivery classification for narration scripts.

This module deliberately performs no model, network, database, or persistence
work.  It emits only fields that the T3-GATE assembler can place into the
frozen :class:`~backend.narration.script_contracts.SegmentContract`.

The returned confidence is a rule tier, not a probability.  A conflicting
result is therefore preserved explicitly instead of being hidden behind a
made-up numeric score.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .contracts import ConfidenceLevel
from .script_contracts import Delivery, Emotion, SegmentKind

EXPRESSION_RULESET_VERSION: Final = "narration-expression-rules/1"


class ExpressionRuleError(ValueError):
    """Raised when an expression-classification input is not contract-shaped."""


# Marker tables are intentionally short, frozen, and auditable.  Matching is
# Unicode-NFC substring matching; no tokeniser or language model is implied.
_EMOTION_MARKERS: Final[Mapping[Emotion, tuple[str, ...]]] = MappingProxyType(
    {
        Emotion.HAPPY: (
            "喜悦",
            "欢喜",
            "开心",
            "欣喜",
            "兴奋",
            "笑道",
            "笑了",
            "微笑",
        ),
        Emotion.SAD: (
            "悲伤",
            "难过",
            "失落",
            "哽咽",
            "抽泣",
            "泪水",
            "含泪",
            "哭道",
        ),
        Emotion.ANGRY: (
            "愤怒",
            "怒道",
            "恼怒",
            "盛怒",
            "怒吼",
            "咆哮",
            "厉声",
            "喝道",
        ),
        Emotion.FEARFUL: (
            "害怕",
            "恐惧",
            "惊恐",
            "惊惧",
            "惧怕",
            "发抖",
            "颤声",
            "颤抖",
        ),
        Emotion.TENSE: (
            "紧张",
            "绷紧",
            "屏住呼吸",
            "呼吸急促",
            "急促",
            "警惕",
            "戒备",
            "剑拔弩张",
        ),
    }
)

_WHISPER_MARKERS: Final[tuple[str, ...]] = (
    "低声",
    "轻声",
    "耳语",
    "呢喃",
    "压低声音",
    "小声",
)
_SHOUT_MARKERS: Final[tuple[str, ...]] = (
    "大声",
    "高声",
    "喊道",
    "怒吼",
    "咆哮",
    "厉声",
    "喝道",
)


def _require_text(value: object, *, field_name: str, maximum: int) -> str:
    if type(value) is not str:
        raise ExpressionRuleError(f"{field_name} must be a string")
    if len(value) > maximum:
        raise ExpressionRuleError(f"{field_name} exceeds maximum length {maximum}")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ExpressionRuleError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


@dataclass(frozen=True, slots=True)
class ExpressionContext:
    """Bounded local evidence for one already-segmented source range."""

    segment_kind: SegmentKind
    source_text: str
    spoken_text: str
    cue_before: str = ""
    cue_after: str = ""
    ruleset_version: str = EXPRESSION_RULESET_VERSION

    def __post_init__(self) -> None:
        if type(self.segment_kind) is not SegmentKind:
            raise ExpressionRuleError("segment_kind must be SegmentKind")
        for field_name, maximum in (
            ("source_text", 20_000),
            ("spoken_text", 20_000),
            ("cue_before", 2_000),
            ("cue_after", 2_000),
        ):
            _require_text(
                getattr(self, field_name), field_name=field_name, maximum=maximum
            )
        if self.ruleset_version != EXPRESSION_RULESET_VERSION:
            raise ExpressionRuleError("unknown expression ruleset version")


@dataclass(frozen=True, slots=True)
class ExpressionDecision:
    """T3-A-compatible expression fields plus auditable local evidence."""

    emotion: Emotion
    emotion_confidence: ConfidenceLevel
    delivery: Delivery
    emotion_rule_codes: tuple[str, ...]
    delivery_rule_codes: tuple[str, ...]
    conflict_codes: tuple[str, ...] = ()
    ruleset_version: str = EXPRESSION_RULESET_VERSION

    def __post_init__(self) -> None:
        if type(self.emotion) is not Emotion:
            raise ExpressionRuleError("emotion must be Emotion")
        if type(self.emotion_confidence) is not ConfidenceLevel:
            raise ExpressionRuleError("emotion_confidence must be ConfidenceLevel")
        if type(self.delivery) is not Delivery:
            raise ExpressionRuleError("delivery must be Delivery")
        for field_name in (
            "emotion_rule_codes",
            "delivery_rule_codes",
            "conflict_codes",
        ):
            values = getattr(self, field_name)
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise ExpressionRuleError(
                    f"{field_name} must be a unique canonically sorted tuple"
                )
        if not self.emotion_rule_codes or not self.delivery_rule_codes:
            raise ExpressionRuleError("expression decision must retain rule evidence")
        if self.ruleset_version != EXPRESSION_RULESET_VERSION:
            raise ExpressionRuleError("unknown expression ruleset version")

    @property
    def rule_codes(self) -> tuple[str, ...]:
        """Return the bounded canonical evidence union for persistence/debugging."""

        return tuple(
            sorted(
                set(self.emotion_rule_codes)
                | set(self.delivery_rule_codes)
                | set(self.conflict_codes)
            )
        )

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflict_codes)


def _matched_markers(text: str, markers: Sequence[str]) -> tuple[str, ...]:
    found = tuple(marker for marker in markers if marker in text)
    # A long phrase and its substring are one lexical observation, not two
    # independent corroborating signals (for example "呼吸急促"/"急促").
    return tuple(
        marker
        for marker in found
        if not any(marker != other and marker in other for other in found)
    )


def _classify_emotion(text: str) -> tuple[
    Emotion,
    ConfidenceLevel,
    tuple[str, ...],
    tuple[str, ...],
]:
    matches = {
        emotion: _matched_markers(text, markers)
        for emotion, markers in _EMOTION_MARKERS.items()
    }
    active = {emotion: found for emotion, found in matches.items() if found}
    if not active:
        return (
            Emotion.NEUTRAL,
            ConfidenceLevel.HIGH,
            ("expression.emotion.default_neutral",),
            (),
        )

    ranked = sorted(
        active.items(),
        key=lambda item: (-len(item[1]), item[0].value),
    )
    top_emotion, top_markers = ranked[0]
    evidence = tuple(
        sorted(f"expression.emotion.signal.{emotion.value}" for emotion in active)
    )
    if len(active) == 1:
        confidence = (
            ConfidenceLevel.HIGH
            if len(top_markers) >= 2
            else ConfidenceLevel.MEDIUM
        )
        tier = "corroborated" if confidence is ConfidenceLevel.HIGH else "single"
        return (
            top_emotion,
            confidence,
            tuple(sorted((*evidence, f"expression.emotion.{tier}"))),
            (),
        )

    runner_count = len(ranked[1][1])
    if len(top_markers) == runner_count:
        return (
            Emotion.NEUTRAL,
            ConfidenceLevel.UNKNOWN,
            evidence,
            ("expression.conflict.emotion_tie",),
        )
    return (
        top_emotion,
        ConfidenceLevel.LOW,
        evidence,
        ("expression.conflict.emotion_competing",),
    )


def _classify_delivery(
    *, segment_kind: SegmentKind, text: str
) -> tuple[Delivery, tuple[str, ...], tuple[str, ...]]:
    if segment_kind is SegmentKind.INNER_MONOLOGUE:
        return (
            Delivery.INNER_MONOLOGUE,
            ("expression.delivery.segment_inner_monologue",),
            (),
        )

    whisper = _matched_markers(text, _WHISPER_MARKERS)
    shout = _matched_markers(text, _SHOUT_MARKERS)
    if whisper and shout:
        return (
            Delivery.NORMAL,
            (
                "expression.delivery.signal.shout",
                "expression.delivery.signal.whisper",
            ),
            ("expression.conflict.delivery_competing",),
        )
    if whisper:
        return Delivery.WHISPER, ("expression.delivery.signal.whisper",), ()
    if shout:
        return Delivery.SHOUT, ("expression.delivery.signal.shout",), ()
    return Delivery.NORMAL, ("expression.delivery.default_normal",), ()


def classify_expression(context: ExpressionContext) -> ExpressionDecision:
    """Classify one segment with a frozen, local-only, fail-closed ruleset.

    ``cue_before`` and ``cue_after`` are bounded by the caller and are treated as
    evidence only; the function never changes source or spoken text.  Structural
    ``inner_monologue`` wins over lexical delivery cues.  Competing lexical cues
    collapse to the safe default and remain visible in ``conflict_codes``.
    """

    if type(context) is not ExpressionContext:
        raise ExpressionRuleError("context must be ExpressionContext")
    evidence_text = unicodedata.normalize(
        "NFC",
        "\n".join(
            (
                context.cue_before,
                context.source_text,
                context.spoken_text,
                context.cue_after,
            )
        ),
    )
    emotion, emotion_confidence, emotion_codes, emotion_conflicts = (
        _classify_emotion(evidence_text)
    )
    delivery, delivery_codes, delivery_conflicts = _classify_delivery(
        segment_kind=context.segment_kind,
        text=evidence_text,
    )
    return ExpressionDecision(
        emotion=emotion,
        emotion_confidence=emotion_confidence,
        delivery=delivery,
        emotion_rule_codes=emotion_codes,
        delivery_rule_codes=delivery_codes,
        conflict_codes=tuple(sorted((*emotion_conflicts, *delivery_conflicts))),
    )


__all__ = [
    "EXPRESSION_RULESET_VERSION",
    "ExpressionContext",
    "ExpressionDecision",
    "ExpressionRuleError",
    "classify_expression",
]
