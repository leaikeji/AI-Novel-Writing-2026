from __future__ import annotations

from array import array
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import sys
import wave

import pytest

from backend.narration.character_voice_matching import (
    ACOUSTIC_EXTRACTOR_SPEC_SHA256,
    BASELINE_SCHEMA_VERSION,
    CHARACTER_VOICE_BASELINE_INVALID,
    CHARACTER_VOICE_BRIEF_INVALID,
    CHARACTER_VOICE_NO_CANDIDATE,
    EXTRACTOR_SCHEMA_VERSION,
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoiceMatchingError,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
    OfficialVoiceAcousticProfile,
    OfficialVoiceCastingBaseline,
    load_official_voice_casting_baseline,
    match_official_voice,
    parse_character_voice_brief,
    score_official_voice_candidates,
)
from backend.narration.official_presets import (
    OFFICIAL_PRESET_MANIFEST_PATH,
    OFFICIAL_PRESET_MANIFEST_SHA256,
    OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
    OFFICIAL_PRESET_REPOSITORY,
    OFFICIAL_PRESET_REVISION,
    OFFICIAL_PRESETS,
)
from scripts.tts.build_official_voice_casting_baseline import (
    BaselineBuildError,
    build_baseline,
)


def _valid_brief_payload() -> dict[str, object]:
    return {
        "schema_version": "character-voice-brief/1",
        "language": "zh-CN",
        "presentation": "feminine",
        "pitch": 1,
        "pace": None,
        "energy": -1,
        "texture": "warm",
        "evidence_fields": [
            "language:selected_instance.profile.voice.language",
            "presentation:character.details.voice.presentation",
            "pitch:selected_instance.profile.voice.pitch",
            "energy:projected_state.current_facts[0].details.voice_energy",
            "texture:character.description.voice_texture",
        ],
    }


def _profile(
    preset_id: str,
    *,
    language: CharacterVoiceLanguage = CharacterVoiceLanguage.ZH_CN,
    presentation: CharacterVoicePresentation = CharacterVoicePresentation.MASCULINE,
    pitch: int = 0,
    pace: int = 0,
    energy: int = 0,
    texture: CharacterVoiceTexture = CharacterVoiceTexture.CLEAR,
) -> OfficialVoiceAcousticProfile:
    return OfficialVoiceAcousticProfile(
        preset_id=preset_id,
        language=language,
        presentation=presentation,
        pitch=pitch,
        pace=pace,
        energy=energy,
        texture=texture,
    )


def _baseline(
    items: tuple[OfficialVoiceAcousticProfile, ...] = (),
) -> OfficialVoiceCastingBaseline:
    overrides = {item.preset_id: item for item in items}
    assert len(overrides) == len(items)
    return OfficialVoiceCastingBaseline(
        source_path=Path("fixture.json"),
        file_sha256="a" * 64,
        source={},
        items=tuple(
            overrides.get(
                preset.preset_id,
                _profile(
                    preset.preset_id,
                    language=CharacterVoiceLanguage(preset.language),
                    presentation=(
                        CharacterVoicePresentation.MASCULINE
                        if preset.group.endswith("Male")
                        else CharacterVoicePresentation.FEMININE
                    ),
                ),
            )
            for preset in OFFICIAL_PRESETS
        ),
    )


def _source_manifest(audio_hashes: list[str]) -> dict[str, object]:
    prompts = {
        "zh-CN": {"text_sha256": "1" * 64, "codepoint_count": 18},
        "en": {"text_sha256": "2" * 64, "codepoint_count": 48},
        "ja-JP": {"text_sha256": "3" * 64, "codepoint_count": 26},
    }
    return {
        "schema_version": "official-voice-casting-source/1",
        "official_manifest": {
            "repository": OFFICIAL_PRESET_REPOSITORY,
            "revision": OFFICIAL_PRESET_REVISION,
            "path": OFFICIAL_PRESET_MANIFEST_PATH,
            "sha256": OFFICIAL_PRESET_MANIFEST_SHA256,
        },
        "source": {
            "model_fingerprint_sha256": OFFICIAL_PRESET_MODEL_FINGERPRINT_SHA256,
            "model_revision": OFFICIAL_PRESET_REVISION,
            "sidecar_protocol_version": "moss-tts-sidecar/1.1",
            "sample_mode": "fixed",
            "max_new_frames": 375,
            "seed": 1234,
        },
        "prompts": prompts,
        "items": [
            {
                "preset_id": preset.preset_id,
                "audio_path": f"{index:02d}.wav",
                "audio_sha256": audio_hashes[index],
            }
            for index, preset in enumerate(OFFICIAL_PRESETS)
        ],
    }


def _sine_wav(*, frequency: int, amplitude: int, duration_ms: int = 360) -> bytes:
    sample_rate = 8_000
    samples = array(
        "h",
        (
            round(amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
            for index in range(sample_rate * duration_ms // 1000)
        ),
    )
    if sys.byteorder != "little":
        samples.byteswap()
    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(samples.tobytes())
    return output.getvalue()


def test_brief_parser_is_exact_and_preserves_unknown_dimensions() -> None:
    brief = parse_character_voice_brief(_valid_brief_payload())

    assert brief.language is CharacterVoiceLanguage.ZH_CN
    assert brief.presentation is CharacterVoicePresentation.FEMININE
    assert brief.pitch == 1
    assert brief.pace is None
    assert brief.texture is CharacterVoiceTexture.WARM
    assert brief.to_payload() == _valid_brief_payload()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"preset_id": "onnx.Xiaoyu"}),
        lambda value: value.update({"pitch": True}),
        lambda value: value.update({"texture": "seductive"}),
        lambda value: value.update({"evidence_fields": value["evidence_fields"][:-1]}),
        lambda value: value.update(
            {
                "evidence_fields": [
                    *value["evidence_fields"],
                    "pace:character.description.voice_pace",
                ]
            }
        ),
        lambda value: value.update(
            {
                "evidence_fields": [
                    "language:selected_instance.profile.voice.language",
                    "presentation:character.name",
                    *value["evidence_fields"][2:],
                ]
            }
        ),
    ],
)
def test_brief_parser_rejects_coercion_extra_output_and_unsupported_evidence(
    mutate,
) -> None:
    payload = _valid_brief_payload()
    mutate(payload)

    with pytest.raises(CharacterVoiceMatchingError) as caught:
        parse_character_voice_brief(payload)

    assert caught.value.code == CHARACTER_VOICE_BRIEF_INVALID


def test_checked_in_baseline_authenticates_all_18_verified_recordings() -> None:
    baseline = load_official_voice_casting_baseline()

    assert tuple(item.preset_id for item in baseline.items) == tuple(
        preset.preset_id for preset in OFFICIAL_PRESETS
    )
    assert baseline.file_sha256 == (
        "ab64cbdbb0f7fc63171a15a4ab1e136c606e882cfe3748fedf44c13d37cf1888"
    )
    assert baseline.source["kind"] == "nano_fixed_short_sentence"


def test_match_filters_language_renormalizes_known_axes_and_uses_weights() -> None:
    brief = CharacterVoiceBrief(
        language=CharacterVoiceLanguage.ZH_CN,
        presentation=CharacterVoicePresentation.FEMININE,
        pitch=2,
        pace=None,
        energy=1,
        texture=CharacterVoiceTexture.WARM,
        evidence_fields=(
            "language:selected_instance.profile.voice.language",
            "presentation:character.details.voice.presentation",
            "pitch:selected_instance.profile.voice.pitch",
            "energy:character.details.voice.energy",
            "texture:character.details.voice.texture",
        ),
    )
    catalog = _baseline(
        (
            _profile("onnx.Junhao", pitch=2, energy=1, texture=CharacterVoiceTexture.WARM),
            _profile(
                "onnx.Xiaoyu",
                presentation=CharacterVoicePresentation.FEMININE,
                pitch=2,
                energy=1,
                texture=CharacterVoiceTexture.WARM,
            ),
            _profile(
                "onnx.Ava",
                language=CharacterVoiceLanguage.EN,
                presentation=CharacterVoicePresentation.FEMININE,
                pitch=2,
                energy=1,
                texture=CharacterVoiceTexture.WARM,
            ),
        )
    )

    result = match_official_voice(brief, baseline=catalog)

    assert result.selected_preset_id == "onnx.Xiaoyu"
    assert result.score_milli == 1000
    assert result.compared_dimensions == (
        "presentation",
        "pitch",
        "energy",
        "texture",
    )


def test_match_unknown_language_covers_all_and_ties_use_supplied_manifest_order() -> None:
    brief = CharacterVoiceBrief(
        language=None,
        presentation=None,
        pitch=None,
        pace=None,
        energy=0,
        texture=None,
        evidence_fields=("energy:character.details.voice.energy",),
    )
    catalog = _baseline(
        (
            _profile("onnx.Junhao", energy=0),
            _profile(
                "onnx.Ava", language=CharacterVoiceLanguage.EN, energy=0
            ),
        )
    )

    result = match_official_voice(brief, baseline=catalog)

    assert result.selected_preset_id == "onnx.Junhao"
    assert result.score_milli == 1000


def test_candidate_scoring_exposes_manifest_order_for_global_solver() -> None:
    brief = CharacterVoiceBrief(
        language=None,
        presentation=None,
        pitch=None,
        pace=None,
        energy=0,
        texture=None,
        evidence_fields=("energy:character.details.voice.energy",),
    )

    scores = score_official_voice_candidates(
        brief,
        effective_language=CharacterVoiceLanguage.EN,
        baseline=_baseline(),
    )

    assert tuple(score.preset_id for score in scores) == tuple(
        preset.preset_id for preset in OFFICIAL_PRESETS if preset.language == "en"
    )
    assert all(score.compared_dimensions == ("energy",) for score in scores)


def test_match_rejects_a_brief_with_no_scoreable_dimension() -> None:
    brief = CharacterVoiceBrief(
        language=CharacterVoiceLanguage.JA_JP,
        presentation=None,
        pitch=None,
        pace=None,
        energy=None,
        texture=None,
        evidence_fields=("language:selected_instance.profile.voice.language",),
    )

    with pytest.raises(CharacterVoiceMatchingError) as caught:
        match_official_voice(
            brief,
            baseline=_baseline(
                (
                    _profile(
                        "onnx.Soyo", language=CharacterVoiceLanguage.JA_JP
                    ),
                )
            ),
        )

    assert caught.value.code == CHARACTER_VOICE_NO_CANDIDATE


def test_objective_builder_requires_all_18_hash_closed_wavs_and_is_loadable(
    tmp_path: Path,
) -> None:
    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    audio_hashes: list[str] = []
    for index, _preset in enumerate(OFFICIAL_PRESETS):
        audio = _sine_wav(
            frequency=90 + index * 9,
            amplitude=5_000 + index * 500,
            duration_ms=320 + index * 5,
        )
        (audio_root / f"{index:02d}.wav").write_bytes(audio)
        audio_hashes.append(hashlib.sha256(audio).hexdigest())
    manifest_path = tmp_path / "source.json"
    manifest_path.write_text(
        json.dumps(_source_manifest(audio_hashes), sort_keys=True), encoding="utf-8"
    )
    implementation = Path(
        "scripts/tts/build_official_voice_casting_baseline.py"
    ).resolve()

    first = build_baseline(
        input_manifest_path=manifest_path,
        audio_root=audio_root,
        implementation_path=implementation,
    )
    second = build_baseline(
        input_manifest_path=manifest_path,
        audio_root=audio_root,
        implementation_path=implementation,
    )

    assert first == second
    assert first["schema_version"] == BASELINE_SCHEMA_VERSION
    assert first["extractor"]["schema_version"] == EXTRACTOR_SCHEMA_VERSION
    assert first["extractor"]["spec_sha256"] == ACOUSTIC_EXTRACTOR_SPEC_SHA256
    assert len(first["items"]) == 18
    assert {row["presentation"] for row in first["items"]} == {
        "masculine",
        "feminine",
    }
    assert len({row["pitch_hz_milli"] for row in first["items"]}) > 1
    output_path = tmp_path / "baseline.json"
    output_path.write_text(json.dumps(first, sort_keys=True), encoding="utf-8")
    loaded = load_official_voice_casting_baseline(output_path)
    assert tuple(item.preset_id for item in loaded.items) == tuple(
        preset.preset_id for preset in OFFICIAL_PRESETS
    )

    tampered = json.loads(json.dumps(first))
    tampered["source"]["aggregate_audio_sha256"] = "0" * 64
    output_path.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
    with pytest.raises(CharacterVoiceMatchingError) as caught:
        load_official_voice_casting_baseline(output_path)
    assert caught.value.code == CHARACTER_VOICE_BASELINE_INVALID


def test_objective_builder_rejects_audio_hash_drift(tmp_path: Path) -> None:
    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    audio_hashes: list[str] = []
    for index, _preset in enumerate(OFFICIAL_PRESETS):
        audio = _sine_wav(frequency=100 + index, amplitude=8_000)
        (audio_root / f"{index:02d}.wav").write_bytes(audio)
        audio_hashes.append(hashlib.sha256(audio).hexdigest())
    audio_hashes[-1] = "0" * 64
    manifest_path = tmp_path / "source.json"
    manifest_path.write_text(
        json.dumps(_source_manifest(audio_hashes), sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(BaselineBuildError, match="SHA-256 changed"):
        build_baseline(
            input_manifest_path=manifest_path,
            audio_root=audio_root,
            implementation_path=Path(
                "scripts/tts/build_official_voice_casting_baseline.py"
            ).resolve(),
        )
