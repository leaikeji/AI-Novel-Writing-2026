"""Pure, versioned selection of effective Nano synthesis parameters.

The policy is intentionally narrower than the generic short-Chinese duration
gate.  It only covers the exact narrator attribution shape that failed real
human listening, and it performs no database, filesystem, network, or model
I/O.  Render identity and worker execution must call this same resolver.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Final, Literal
import unicodedata

from .audio_pipeline import SHORT_CHINESE_DURATION_POLICY_VERSION
from .contracts import (
    PRODUCTION_NANO_MAX_NEW_FRAMES,
    PRODUCTION_NANO_MAX_SEED,
    PRODUCTION_NANO_SAMPLE_MODES,
)


SHORT_ATTRIBUTION_POLICY_VERSION: Final = "nano-zh-attribution-sampling/2"
SHORT_ATTRIBUTION_COLON_TRIGGER_KIND: Final = "zh_narrator_said_colon"
SHORT_ATTRIBUTION_PERIOD_TRIGGER_KIND: Final = "zh_narrator_said_period"
ShortAttributionStrategy = Literal["disabled", "fixed_seed_1"]

# The author made a later, superseding product decision on 2026-08-28: every
# official preset must use the pinned official manifest/runtime defaults.  The
# fixed-seed-1 branch remains readable only for historical diagnostic evidence
# and must not be selected for new product renders.
ACTIVE_SHORT_ATTRIBUTION_STRATEGY: Final[ShortAttributionStrategy] = (
    "disabled"
)

_ATTRIBUTION = re.compile(
    r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{1,8}说道(?P<end>[：:。])$"
)


class SynthesisPolicyError(ValueError):
    """The persisted synthesis inputs cannot produce an authoritative policy."""


@dataclass(frozen=True, slots=True)
class EffectiveSynthesisPolicy:
    base_seed: int
    base_sample_mode: str
    base_max_new_frames: int
    effective_seed: int
    effective_sample_mode: str
    effective_max_new_frames: int
    strategy: ShortAttributionStrategy
    trigger_kind: str | None

    @property
    def applied(self) -> bool:
        return self.trigger_kind is not None

    def evidence_payload(self) -> dict[str, object] | None:
        if not self.applied:
            return None
        return {
            "schema_version": SHORT_ATTRIBUTION_POLICY_VERSION,
            "trigger_kind": self.trigger_kind,
            "strategy": self.strategy,
            "sample_mode": self.effective_sample_mode,
            "seed": self.effective_seed,
            "max_new_frames": self.effective_max_new_frames,
            "duration_gate_version": SHORT_CHINESE_DURATION_POLICY_VERSION,
        }

    def fingerprint(self) -> str:
        payload = {
            "schema_version": SHORT_ATTRIBUTION_POLICY_VERSION,
            "resolved": asdict(self),
            "duration_gate_version": SHORT_CHINESE_DURATION_POLICY_VERSION,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()


def resolve_effective_synthesis_policy(
    *,
    spoken_text: str,
    segment_kind: str,
    speaker_kind: str,
    language: str,
    preset_key: str | None,
    base_seed: int,
    base_sample_mode: str,
    base_max_new_frames: int,
    strategy: ShortAttributionStrategy | None = None,
) -> EffectiveSynthesisPolicy:
    """Resolve the exact per-segment parameters used by Nano.

    Only the pinned Zhiming narrator attribution form is eligible.  Normal
    narration and every other voice retain their immutable version defaults.
    """

    if type(spoken_text) is not str or not spoken_text:
        raise SynthesisPolicyError("spoken_text must be a non-empty string")
    if unicodedata.normalize("NFC", spoken_text) != spoken_text:
        raise SynthesisPolicyError("spoken_text must be NFC")
    if type(base_seed) is not int or not 0 <= base_seed <= PRODUCTION_NANO_MAX_SEED:
        raise SynthesisPolicyError("base seed is outside the Nano bound")
    if (
        type(base_sample_mode) is not str
        or base_sample_mode not in PRODUCTION_NANO_SAMPLE_MODES
    ):
        raise SynthesisPolicyError("base sample mode is invalid")
    if (
        type(base_max_new_frames) is not int
        or not 1 <= base_max_new_frames <= PRODUCTION_NANO_MAX_NEW_FRAMES
    ):
        raise SynthesisPolicyError("base frame bound is invalid")
    if strategy is None:
        strategy = ACTIVE_SHORT_ATTRIBUTION_STRATEGY
    if strategy not in {"disabled", "fixed_seed_1"}:
        raise SynthesisPolicyError("short attribution strategy is invalid")
    for value, label in (
        (segment_kind, "segment_kind"),
        (speaker_kind, "speaker_kind"),
        (language, "language"),
    ):
        if type(value) is not str or not value:
            raise SynthesisPolicyError(f"{label} is invalid")
    if preset_key is not None and (type(preset_key) is not str or not preset_key):
        raise SynthesisPolicyError("preset_key is invalid")

    attribution = _ATTRIBUTION.fullmatch(spoken_text)
    applies = (
        strategy != "disabled"
        and segment_kind == "narration"
        and speaker_kind == "narrator"
        and language == "zh-CN"
        and preset_key == "onnx.Zhiming"
        and attribution is not None
    )
    effective_seed = base_seed
    effective_mode = base_sample_mode
    trigger_kind: str | None = None
    if applies:
        assert attribution is not None
        trigger_kind = (
            SHORT_ATTRIBUTION_PERIOD_TRIGGER_KIND
            if attribution.group("end") == "。"
            else SHORT_ATTRIBUTION_COLON_TRIGGER_KIND
        )
        if strategy == "fixed_seed_1":
            effective_seed = 1
            effective_mode = "fixed"
    return EffectiveSynthesisPolicy(
        base_seed=base_seed,
        base_sample_mode=base_sample_mode,
        base_max_new_frames=base_max_new_frames,
        effective_seed=effective_seed,
        effective_sample_mode=effective_mode,
        effective_max_new_frames=base_max_new_frames,
        strategy=strategy,
        trigger_kind=trigger_kind,
    )


__all__ = [
    "ACTIVE_SHORT_ATTRIBUTION_STRATEGY",
    "EffectiveSynthesisPolicy",
    "SHORT_ATTRIBUTION_POLICY_VERSION",
    "SHORT_ATTRIBUTION_COLON_TRIGGER_KIND",
    "SHORT_ATTRIBUTION_PERIOD_TRIGGER_KIND",
    "ShortAttributionStrategy",
    "SynthesisPolicyError",
    "resolve_effective_synthesis_policy",
]
