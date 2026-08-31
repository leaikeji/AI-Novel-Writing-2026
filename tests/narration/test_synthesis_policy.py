from __future__ import annotations

from dataclasses import replace

import pytest

from backend.narration.synthesis_policy import (
    SHORT_ATTRIBUTION_POLICY_VERSION,
    SynthesisPolicyError,
    resolve_effective_synthesis_policy,
)


def _resolve(text: str, **changes: object):
    values: dict[str, object] = {
        "spoken_text": text,
        "segment_kind": "narration",
        "speaker_kind": "narrator",
        "language": "zh-CN",
        "preset_key": "onnx.Zhiming",
        "base_seed": 0,
        "base_sample_mode": "fixed",
        "base_max_new_frames": 375,
        "strategy": "fixed_seed_1",
    }
    values.update(changes)
    return resolve_effective_synthesis_policy(**values)  # type: ignore[arg-type]


def test_product_default_keeps_official_preset_parameters() -> None:
    resolved = resolve_effective_synthesis_policy(
        spoken_text="林晚说道：",
        segment_kind="narration",
        speaker_kind="narrator",
        language="zh-CN",
        preset_key="onnx.Zhiming",
        base_seed=1234,
        base_sample_mode="fixed",
        base_max_new_frames=375,
    )

    assert resolved.applied is False
    assert (resolved.effective_sample_mode, resolved.effective_seed) == (
        "fixed",
        1234,
    )
    assert resolved.evidence_payload() is None


@pytest.mark.parametrize("text", ["林晚说道：", "沈川说道："])
def test_confirmed_bad_attributions_select_fixed_seed_one(text: str) -> None:
    resolved = _resolve(text)

    assert resolved.applied is True
    assert (resolved.effective_sample_mode, resolved.effective_seed) == ("fixed", 1)
    assert resolved.evidence_payload() == {
        "schema_version": SHORT_ATTRIBUTION_POLICY_VERSION,
        "trigger_kind": "zh_narrator_said_colon",
        "strategy": "fixed_seed_1",
        "sample_mode": "fixed",
        "seed": 1,
        "max_new_frames": 375,
        "duration_gate_version": "nano-short-chinese-duration/2",
    }


@pytest.mark.parametrize("text", ["林晚说道。", "沈川说道。"])
def test_confirmed_period_variant_selects_fixed_seed_one(text: str) -> None:
    resolved = _resolve(text)

    assert resolved.applied is True
    assert (resolved.effective_sample_mode, resolved.effective_seed) == ("fixed", 1)
    assert resolved.evidence_payload() == {
        "schema_version": SHORT_ATTRIBUTION_POLICY_VERSION,
        "trigger_kind": "zh_narrator_said_period",
        "strategy": "fixed_seed_1",
        "sample_mode": "fixed",
        "seed": 1,
        "max_new_frames": 375,
        "duration_gate_version": "nano-short-chinese-duration/2",
    }


@pytest.mark.parametrize(
    ("text", "changes"),
    [
        ("站台上的灯忽然闪了一次，四周仍然没有人影。", {}),
        ("林晚说。", {}),
        ("林晚说道.", {}),
        ("第2章：", {}),
        ("Lin说道：", {}),
        ("林🌙说道：", {}),
        ("林晚说道：", {"segment_kind": "dialogue"}),
        ("林晚说道：", {"speaker_kind": "character"}),
        ("林晚说道：", {"language": "en"}),
        ("林晚说道：", {"preset_key": "onnx.Junhao"}),
        ("林晚说道：", {"strategy": "disabled"}),
    ],
)
def test_policy_is_narrow_and_keeps_base_parameters(
    text: str,
    changes: dict[str, object],
) -> None:
    resolved = _resolve(text, **changes)

    assert resolved.applied is False
    assert (resolved.effective_sample_mode, resolved.effective_seed) == ("fixed", 0)
    assert resolved.evidence_payload() is None


def test_policy_or_parameters_change_the_policy_fingerprint() -> None:
    base = _resolve("林晚说道：")

    assert base.fingerprint() != _resolve(
        "林晚说道：", strategy="disabled"
    ).fingerprint()
    assert base.fingerprint() != replace(
        base, effective_max_new_frames=374
    ).fingerprint()


@pytest.mark.parametrize(
    "changes",
    [
        {"base_seed": -1},
        {"base_seed": 2**63},
        {"base_seed": True},
        {"base_sample_mode": "random"},
        {"base_max_new_frames": 376},
        {"strategy": "greedy"},
        {"strategy": "unknown"},
    ],
)
def test_invalid_persisted_policy_inputs_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(SynthesisPolicyError):
        _resolve("林晚说道：", **changes)
