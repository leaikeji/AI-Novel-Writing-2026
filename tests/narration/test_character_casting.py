from __future__ import annotations

from pathlib import Path

import pytest

from backend.narration.character_casting import (
    CHARACTER_CAST_INVALID_INPUT,
    CHARACTER_CAST_LANGUAGE_UNKNOWN,
    CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS,
    CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED,
    CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED,
    CHARACTER_CAST_OFFICIAL_POOL_REUSED,
    CHARACTER_CAST_PROTECTED_VOICE_SHARED,
    CastDecisionStatus,
    CastRole,
    CastTarget,
    CastTargetKind,
    CastVoiceSource,
    CharacterCastError,
    CurrentCastVoice,
    solve_character_cast,
)
from backend.narration.character_voice_matching import (
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
    OfficialVoiceAcousticProfile,
    OfficialVoiceCastingBaseline,
)
from backend.narration.narrator_voice_brief import NarratorVoiceBrief
from backend.narration.official_presets import OFFICIAL_PRESETS


def _baseline(*, flatten: bool = False) -> OfficialVoiceCastingBaseline:
    profiles = []
    for index, preset in enumerate(OFFICIAL_PRESETS):
        presentation = (
            CharacterVoicePresentation.MASCULINE
            if preset.group.endswith("Male")
            else CharacterVoicePresentation.FEMININE
        )
        profiles.append(
            OfficialVoiceAcousticProfile(
                preset_id=preset.preset_id,
                language=CharacterVoiceLanguage(preset.language),
                presentation=(
                    CharacterVoicePresentation.MASCULINE
                    if flatten
                    else presentation
                ),
                pitch=0 if flatten else (index % 5) - 2,
                pace=0 if flatten else ((index + 1) % 5) - 2,
                energy=0 if flatten else ((index + 2) % 5) - 2,
                texture=(
                    CharacterVoiceTexture.CLEAR
                    if flatten
                    else tuple(CharacterVoiceTexture)[
                        index % len(CharacterVoiceTexture)
                    ]
                ),
            )
        )
    return OfficialVoiceCastingBaseline(
        source_path=Path("fixture.json"),
        file_sha256="a" * 64,
        source={},
        items=tuple(profiles),
    )


def _distance_priority_baseline() -> OfficialVoiceCastingBaseline:
    base = _baseline(flatten=True)
    return OfficialVoiceCastingBaseline(
        source_path=base.source_path,
        file_sha256=base.file_sha256,
        source=base.source,
        items=tuple(
            (
                OfficialVoiceAcousticProfile(
                    preset_id=profile.preset_id,
                    language=profile.language,
                    presentation=CharacterVoicePresentation.FEMININE,
                    pitch=2,
                    pace=2,
                    energy=2,
                    texture=CharacterVoiceTexture.DARK,
                )
                if profile.preset_id == "onnx.Yuewen"
                else profile
            )
            for profile in base.items
        ),
    )


def _character_brief(
    *,
    language: CharacterVoiceLanguage | None = CharacterVoiceLanguage.ZH_CN,
    presentation: CharacterVoicePresentation | None = CharacterVoicePresentation.MASCULINE,
    pitch: int | None = 0,
    pace: int | None = 0,
    energy: int | None = 0,
    texture: CharacterVoiceTexture | None = CharacterVoiceTexture.CLEAR,
) -> CharacterVoiceBrief:
    values = {
        "language": language,
        "presentation": presentation,
        "pitch": pitch,
        "pace": pace,
        "energy": energy,
        "texture": texture,
    }
    evidence = tuple(
        f"{field_name}:character.details.voice.{field_name}"
        for field_name, value in values.items()
        if value is not None
    )
    return CharacterVoiceBrief(evidence_fields=evidence, **values)


def _narrator_brief(
    *,
    language: CharacterVoiceLanguage | None = CharacterVoiceLanguage.ZH_CN,
    presentation: CharacterVoicePresentation | None = CharacterVoicePresentation.ANDROGYNOUS,
    pitch: int | None = 0,
    pace: int | None = 0,
    energy: int | None = 0,
    texture: CharacterVoiceTexture | None = CharacterVoiceTexture.DARK,
) -> NarratorVoiceBrief:
    values = {
        "language": language,
        "presentation": presentation,
        "pitch": pitch,
        "pace": pace,
        "energy": energy,
        "texture": texture,
    }
    evidence = tuple(
        (
            "language:narration_settings.language"
            if field_name == "language"
            else f"{field_name}:novel.description"
        )
        for field_name, value in values.items()
        if value is not None
    )
    return NarratorVoiceBrief(evidence_fields=evidence, **values)


def _character(
    stable_id: str,
    *,
    role: CastRole = CastRole.SUPPORTING,
    brief: CharacterVoiceBrief | None = None,
    current: CurrentCastVoice | None = None,
    fallback: CharacterVoiceLanguage | None = CharacterVoiceLanguage.ZH_CN,
) -> CastTarget:
    return CastTarget(
        target_key=f"character:{stable_id}",
        stable_id=stable_id,
        kind=CastTargetKind.CHARACTER,
        role=role,
        brief=brief if brief is not None else _character_brief(),
        fallback_language=fallback,
        current_voice=current,
    )


def _narrator(
    *,
    brief: NarratorVoiceBrief | None = None,
    current: CurrentCastVoice | None = None,
) -> CastTarget:
    return CastTarget(
        target_key="narrator",
        stable_id="narrator",
        kind=CastTargetKind.NARRATOR,
        role=CastRole.NARRATOR,
        brief=brief if brief is not None else _narrator_brief(),
        fallback_language=CharacterVoiceLanguage.ZH_CN,
        current_voice=current,
    )


def _official(preset_id: str, *, available: bool = True) -> CurrentCastVoice:
    return CurrentCastVoice(
        source=CastVoiceSource.OFFICIAL,
        identity_key=preset_id,
        preset_id=preset_id,
        available=available,
    )


def test_official_collision_preserves_narrator_and_reassigns_main() -> None:
    solution = solve_character_cast(
        (
            _character("main-a", role=CastRole.MAIN, current=_official("onnx.Junhao")),
            _narrator(current=_official("onnx.Junhao")),
        ),
        baseline=_baseline(),
    )
    decisions = {decision.target_key: decision for decision in solution.decisions}

    assert decisions["narrator"].status is CastDecisionStatus.PRESERVED
    assert (
        decisions["narrator"].reason_code
        == CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED
    )
    assert decisions["character:main-a"].status is CastDecisionStatus.ASSIGNED
    assert decisions["character:main-a"].preset_id != "onnx.Junhao"
    assert decisions["character:main-a"].replaces_existing is True


def test_official_collision_preserves_main_before_supporting_then_stable_id() -> None:
    solution = solve_character_cast(
        (
            _character(
                "support-a",
                role=CastRole.SUPPORTING,
                current=_official("onnx.Junhao"),
            ),
            _character(
                "main-b", role=CastRole.MAIN, current=_official("onnx.Junhao")
            ),
            _character(
                "main-a", role=CastRole.MAIN, current=_official("onnx.Junhao")
            ),
        ),
        baseline=_baseline(),
    )
    decisions = {decision.target_key: decision for decision in solution.decisions}

    assert decisions["character:main-a"].status is CastDecisionStatus.PRESERVED
    assert decisions["character:main-b"].status is CastDecisionStatus.ASSIGNED
    assert decisions["character:support-a"].status is CastDecisionStatus.ASSIGNED


def test_private_uploaded_and_generated_voices_are_never_replaced() -> None:
    protected = (
        _character(
            "a",
            current=CurrentCastVoice(
                source=CastVoiceSource.GENERATED,
                identity_key="version-1",
            ),
        ),
        _character(
            "b",
            current=CurrentCastVoice(
                source=CastVoiceSource.GENERATED,
                identity_key="version-1",
            ),
        ),
        _character(
            "c",
            current=CurrentCastVoice(
                source=CastVoiceSource.UPLOADED,
                identity_key="version-2",
                available=False,
            ),
        ),
    )

    solution = solve_character_cast(protected, baseline=_baseline())

    assert not solution.assignments
    assert len(solution.preserved) == 3
    assert len(solution.warnings) == 1
    assert solution.warnings[0].code == CHARACTER_CAST_PROTECTED_VOICE_SHARED
    assert solution.warnings[0].target_keys == ("character:a", "character:b")


def test_available_pool_is_unique_and_input_order_does_not_change_solution() -> None:
    targets = (
        _character("support-b", role=CastRole.SUPPORTING),
        _character("main-b", role=CastRole.MAIN),
        _narrator(),
        _character("main-a", role=CastRole.MAIN),
    )

    first = solve_character_cast(targets, baseline=_baseline())
    second = solve_character_cast(tuple(reversed(targets)), baseline=_baseline())

    first_map = {item.target_key: item.preset_id for item in first.assignments}
    second_map = {item.target_key: item.preset_id for item in second.assignments}
    assert first_map == second_map
    assert len(set(first_map.values())) == len(first_map)


def test_ties_use_stable_target_id_then_manifest_order() -> None:
    solution = solve_character_cast(
        (
            _character("b", role=CastRole.MAIN),
            _character("a", role=CastRole.MAIN),
        ),
        baseline=_baseline(flatten=True),
    )
    decisions = {decision.target_key: decision for decision in solution.assignments}

    assert decisions["character:a"].preset_id == "onnx.Junhao"
    assert decisions["character:b"].preset_id == "onnx.Zhiming"


def test_language_fallback_is_used_but_unknown_language_is_blocked() -> None:
    unknown_language_brief = _character_brief(language=None)
    solution = solve_character_cast(
        (
            _character("fallback", brief=unknown_language_brief),
            _character(
                "unknown",
                brief=unknown_language_brief,
                fallback=None,
            ),
        ),
        baseline=_baseline(),
    )
    decisions = {decision.target_key: decision for decision in solution.decisions}

    assert decisions["character:fallback"].status is CastDecisionStatus.ASSIGNED
    assert decisions["character:fallback"].language is CharacterVoiceLanguage.ZH_CN
    assert decisions["character:unknown"].status is CastDecisionStatus.BLOCKED
    assert decisions["character:unknown"].reason_code == CHARACTER_CAST_LANGUAGE_UNKNOWN


def test_no_scoreable_dimension_is_blocked_without_uuid_hash_fallback() -> None:
    language_only = _character_brief(
        presentation=None,
        pitch=None,
        pace=None,
        energy=None,
        texture=None,
    )

    solution = solve_character_cast(
        (_character("no-axes", brief=language_only),), baseline=_baseline()
    )

    assert solution.blocked[0].reason_code == CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS
    assert solution.blocked[0].preset_id is None


def test_manual_cross_language_official_voice_is_preserved() -> None:
    target = _character(
        "cross-language",
        current=_official("onnx.Ava"),
        fallback=CharacterVoiceLanguage.ZH_CN,
    )

    solution = solve_character_cast((target,), baseline=_baseline())

    assert solution.preserved[0].preset_id == "onnx.Ava"
    assert solution.preserved[0].language is CharacterVoiceLanguage.EN


def test_unique_available_official_voice_is_preserved_without_a_brief() -> None:
    target = CastTarget(
        target_key="character:saved",
        stable_id="saved",
        kind=CastTargetKind.CHARACTER,
        role=CastRole.SUPPORTING,
        brief=None,
        fallback_language=CharacterVoiceLanguage.ZH_CN,
        current_voice=_official("onnx.Zhiming"),
    )

    solution = solve_character_cast((target,), baseline=_baseline())

    assert solution.preserved[0].preset_id == "onnx.Zhiming"
    assert not solution.blocked


def test_unresolved_collision_with_no_brief_is_explicitly_blocked() -> None:
    loser = CastTarget(
        target_key="character:no-brief",
        stable_id="no-brief",
        kind=CastTargetKind.CHARACTER,
        role=CastRole.SUPPORTING,
        brief=None,
        fallback_language=CharacterVoiceLanguage.ZH_CN,
        current_voice=_official("onnx.Junhao"),
    )

    solution = solve_character_cast(
        (_narrator(current=_official("onnx.Junhao")), loser),
        baseline=_baseline(),
    )

    assert solution.blocked[0].target_key == "character:no-brief"
    assert any(
        warning.code == CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED
        and warning.target_keys == ("character:no-brief",)
        for warning in solution.warnings
    )


def test_unavailable_official_voice_enters_reassignment() -> None:
    target = _character(
        "stale",
        current=_official("onnx.Junhao", available=False),
    )

    solution = solve_character_cast((target,), baseline=_baseline())

    assert solution.assignments[0].replaces_existing is True
    assert solution.assignments[0].preset_id is not None


def test_pool_exhaustion_reuses_only_after_every_chinese_voice_is_used() -> None:
    targets = (
        _narrator(),
        _character("main-a", role=CastRole.MAIN),
        _character("main-b", role=CastRole.MAIN),
        _character("support-a"),
        _character("support-b"),
        _character("support-c"),
        _character("support-d"),
    )

    solution = solve_character_cast(targets, baseline=_baseline())

    assert len(solution.assignments) == 7
    assert len({item.preset_id for item in solution.assignments[:6]}) == 6
    assert solution.assignments[6].reused is True
    assert any(
        warning.code == CHARACTER_CAST_OFFICIAL_POOL_REUSED
        for warning in solution.warnings
    )


def test_reuse_prioritizes_acoustic_distance_from_narrator() -> None:
    targets = (
        _narrator(current=_official("onnx.Junhao")),
        _character("a", role=CastRole.MAIN, current=_official("onnx.Zhiming")),
        _character("b", current=_official("onnx.Weiguo")),
        _character("c", current=_official("onnx.Xiaoyu")),
        _character("d", current=_official("onnx.Yuewen")),
        _character("e", current=_official("onnx.Lingyu")),
        _character(
            "z",
            brief=_character_brief(
                presentation=CharacterVoicePresentation.MASCULINE,
                pitch=0,
                pace=0,
                energy=0,
                texture=CharacterVoiceTexture.CLEAR,
            ),
        ),
    )

    solution = solve_character_cast(targets, baseline=_distance_priority_baseline())
    decisions = {decision.target_key: decision for decision in solution.decisions}

    # Yuewen is intentionally a poor match but the only profile acoustically
    # far from the narrator in this fixture.  Reuse separation therefore wins.
    assert decisions["character:z"].preset_id == "onnx.Yuewen"
    assert decisions["character:z"].reused is True


def test_duplicate_target_scope_is_rejected() -> None:
    target = _character("same")

    with pytest.raises(CharacterCastError) as caught:
        solve_character_cast((target, target), baseline=_baseline())

    assert caught.value.code == CHARACTER_CAST_INVALID_INPUT
