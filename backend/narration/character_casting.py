"""Pure deterministic whole-book official-voice casting.

The module has no ORM, HTTP, model-runtime, or transaction concerns.  Callers
provide already validated briefs and current binding projections, persist model
evidence separately, then apply the returned assignments through the atomic
official-selection service.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Iterable, Sequence

from .character_voice_matching import (
    CHARACTER_VOICE_NO_CANDIDATE,
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoiceMatchingError,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
    OfficialVoiceAcousticProfile,
    OfficialVoiceCandidateScore,
    OfficialVoiceCastingBaseline,
    load_official_voice_casting_baseline,
    official_voice_acoustic_distance_milli,
    score_official_voice_candidates,
)
from .narrator_voice_brief import NarratorVoiceBrief
from .official_presets import OFFICIAL_PRESETS


CHARACTER_CAST_INVALID_INPUT: Final = "CHARACTER_CAST_INVALID_INPUT"
CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS: Final = (
    "CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS"
)
CHARACTER_CAST_LANGUAGE_UNKNOWN: Final = "CHARACTER_CAST_LANGUAGE_UNKNOWN"
CHARACTER_CAST_NO_LANGUAGE_CANDIDATE: Final = "CHARACTER_CAST_NO_LANGUAGE_CANDIDATE"
CHARACTER_CAST_BRIEF_MISSING: Final = "CHARACTER_CAST_BRIEF_MISSING"
CHARACTER_CAST_PROTECTED_NON_OFFICIAL_PRESERVED: Final = (
    "CHARACTER_CAST_PROTECTED_NON_OFFICIAL_PRESERVED"
)
CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED: Final = (
    "CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED"
)
CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED: Final = (
    "CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED"
)
CHARACTER_CAST_OFFICIAL_COLLISION_REASSIGNED: Final = (
    "CHARACTER_CAST_OFFICIAL_COLLISION_REASSIGNED"
)
CHARACTER_CAST_OFFICIAL_ASSIGNED: Final = "CHARACTER_CAST_OFFICIAL_ASSIGNED"
CHARACTER_CAST_PROTECTED_VOICE_SHARED: Final = (
    "CHARACTER_CAST_PROTECTED_VOICE_SHARED"
)
CHARACTER_CAST_OFFICIAL_POOL_REUSED: Final = "CHARACTER_CAST_OFFICIAL_POOL_REUSED"
CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED: Final = (
    "CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED"
)


class CharacterCastError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CastTargetKind(str, Enum):
    NARRATOR = "narrator"
    CHARACTER = "character"


class CastRole(str, Enum):
    NARRATOR = "narrator"
    MAIN = "main"
    SUPPORTING = "supporting"


class CastVoiceSource(str, Enum):
    OFFICIAL = "official_preset"
    PRIVATE = "private"
    UPLOADED = "uploaded"
    GENERATED = "generated"


class CastDecisionStatus(str, Enum):
    PRESERVED = "preserved"
    ASSIGNED = "assigned"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CurrentCastVoice:
    """Minimal current-binding projection required by the solver."""

    source: CastVoiceSource
    identity_key: str
    preset_id: str | None = None
    available: bool = True

    def __post_init__(self) -> None:
        if type(self.source) is not CastVoiceSource:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "current voice source is invalid"
            )
        if type(self.identity_key) is not str or not self.identity_key.strip():
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "current voice identity is required"
            )
        if type(self.available) is not bool:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "current voice availability is invalid"
            )
        if self.source is CastVoiceSource.OFFICIAL:
            if type(self.preset_id) is not str or not self.preset_id:
                raise CharacterCastError(
                    CHARACTER_CAST_INVALID_INPUT,
                    "official current voice requires a preset ID",
                )
        elif self.preset_id is not None:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT,
                "protected private voice cannot masquerade as an official preset",
            )


@dataclass(frozen=True, slots=True)
class CastTarget:
    """One narrator or character in the authoritative server-side roster."""

    target_key: str
    stable_id: str
    kind: CastTargetKind
    role: CastRole
    brief: CharacterVoiceBrief | NarratorVoiceBrief | None
    fallback_language: CharacterVoiceLanguage | None
    current_voice: CurrentCastVoice | None = None

    def __post_init__(self) -> None:
        if type(self.target_key) is not str or not self.target_key.strip():
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "cast target key is required"
            )
        if type(self.stable_id) is not str or not self.stable_id.strip():
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "cast target stable ID is required"
            )
        if type(self.kind) is not CastTargetKind or type(self.role) is not CastRole:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "cast target kind or role is invalid"
            )
        if self.kind is CastTargetKind.NARRATOR:
            if self.role is not CastRole.NARRATOR or (
                self.brief is not None and type(self.brief) is not NarratorVoiceBrief
            ):
                raise CharacterCastError(
                    CHARACTER_CAST_INVALID_INPUT,
                    "narrator target requires narrator role and narrator brief",
                )
        elif self.role is CastRole.NARRATOR or (
            self.brief is not None and type(self.brief) is not CharacterVoiceBrief
        ):
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT,
                "character target requires main/supporting role and character brief",
            )
        if self.fallback_language is not None and type(
            self.fallback_language
        ) is not CharacterVoiceLanguage:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT,
                "fallback language must use the frozen enum",
            )
        if self.current_voice is not None and type(
            self.current_voice
        ) is not CurrentCastVoice:
            raise CharacterCastError(
                CHARACTER_CAST_INVALID_INPUT, "current voice projection is invalid"
            )


@dataclass(frozen=True, slots=True)
class CastDecision:
    target_key: str
    status: CastDecisionStatus
    reason_code: str
    preset_id: str | None
    language: CharacterVoiceLanguage | None
    score_milli: int | None = None
    compared_dimensions: tuple[str, ...] = ()
    reused: bool = False
    replaces_existing: bool = False


@dataclass(frozen=True, slots=True)
class CastWarning:
    code: str
    target_keys: tuple[str, ...]
    voice_identity: str | None = None


@dataclass(frozen=True, slots=True)
class CharacterCastSolution:
    baseline_sha256: str
    decisions: tuple[CastDecision, ...]
    warnings: tuple[CastWarning, ...]

    @property
    def assignments(self) -> tuple[CastDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is CastDecisionStatus.ASSIGNED
        )

    @property
    def preserved(self) -> tuple[CastDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is CastDecisionStatus.PRESERVED
        )

    @property
    def blocked(self) -> tuple[CastDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is CastDecisionStatus.BLOCKED
        )


_ROLE_ORDER: Final = {
    CastRole.NARRATOR: 0,
    CastRole.MAIN: 1,
    CastRole.SUPPORTING: 2,
}


def _target_sort_key(target: CastTarget) -> tuple[int, str, str]:
    return (_ROLE_ORDER[target.role], target.stable_id, target.target_key)


def _invalid(message: str) -> CharacterCastError:
    return CharacterCastError(CHARACTER_CAST_INVALID_INPUT, message)


def _effective_language(target: CastTarget) -> CharacterVoiceLanguage | None:
    if target.brief is not None and target.brief.language is not None:
        return target.brief.language
    return target.fallback_language


def _profile_maps(
    baseline: OfficialVoiceCastingBaseline,
) -> tuple[
    dict[str, OfficialVoiceAcousticProfile],
    dict[str, int],
]:
    expected_ids = tuple(preset.preset_id for preset in OFFICIAL_PRESETS)
    if type(baseline) is not OfficialVoiceCastingBaseline or tuple(
        profile.preset_id for profile in baseline.items
    ) != expected_ids:
        raise _invalid("casting baseline must retain all 18 manifest rows")
    for preset, profile in zip(OFFICIAL_PRESETS, baseline.items, strict=True):
        if (
            type(profile) is not OfficialVoiceAcousticProfile
            or type(profile.language) is not CharacterVoiceLanguage
            or profile.language.value != preset.language
            or type(profile.presentation) is not CharacterVoicePresentation
            or type(profile.texture) is not CharacterVoiceTexture
            or any(
                type(value) is not int or value not in {-2, -1, 0, 1, 2}
                for value in (profile.pitch, profile.pace, profile.energy)
            )
        ):
            raise _invalid("casting baseline acoustic rows are invalid")
    if (
        type(baseline.file_sha256) is not str
        or len(baseline.file_sha256) != 64
        or any(character not in "0123456789abcdef" for character in baseline.file_sha256)
    ):
        raise _invalid("casting baseline identity is invalid")
    return (
        {profile.preset_id: profile for profile in baseline.items},
        {preset_id: index for index, preset_id in enumerate(expected_ids)},
    )


def _role_totals(
    assignment: tuple[int, ...],
    targets: tuple[CastTarget, ...],
    candidates: tuple[str, ...],
    scores: dict[str, dict[str, OfficialVoiceCandidateScore]],
) -> tuple[int, int, int]:
    totals = [0, 0, 0]
    for target, candidate_index in zip(targets, assignment, strict=True):
        totals[_ROLE_ORDER[target.role]] += scores[target.target_key][
            candidates[candidate_index]
        ].score_milli
    return tuple(totals)  # type: ignore[return-value]


def _assign_distinct(
    targets: tuple[CastTarget, ...],
    candidate_ids: tuple[str, ...],
    scores: dict[str, dict[str, OfficialVoiceCandidateScore]],
) -> dict[str, str]:
    """Maximize narrator/main/supporting totals, then manifest/stable order."""

    if not targets:
        return {}
    if len(targets) > len(candidate_ids):
        raise _invalid("distinct assignment exceeds the available voice pool")

    # mask -> candidate-index tuple in target priority/stable-ID order
    states: dict[int, tuple[int, ...]] = {0: ()}
    for target_index, target in enumerate(targets):
        next_states: dict[int, tuple[int, ...]] = {}
        for mask, assignment in states.items():
            for candidate_index, preset_id in enumerate(candidate_ids):
                bit = 1 << candidate_index
                if mask & bit or preset_id not in scores[target.target_key]:
                    continue
                next_mask = mask | bit
                proposed = (*assignment, candidate_index)
                existing = next_states.get(next_mask)
                if existing is None:
                    next_states[next_mask] = proposed
                    continue
                proposed_totals = _role_totals(
                    proposed,
                    targets[: target_index + 1],
                    candidate_ids,
                    scores,
                )
                existing_totals = _role_totals(
                    existing,
                    targets[: target_index + 1],
                    candidate_ids,
                    scores,
                )
                if proposed_totals > existing_totals or (
                    proposed_totals == existing_totals and proposed < existing
                ):
                    next_states[next_mask] = proposed
        states = next_states
        if not states:
            raise _invalid("no complete distinct official-voice assignment exists")

    best: tuple[int, ...] | None = None
    best_totals = (-1, -1, -1)
    for assignment in states.values():
        totals = _role_totals(assignment, targets, candidate_ids, scores)
        if best is None or totals > best_totals or (
            totals == best_totals and assignment < best
        ):
            best = assignment
            best_totals = totals
    if best is None:
        raise _invalid("no distinct official-voice assignment was selected")
    return {
        target.target_key: candidate_ids[candidate_index]
        for target, candidate_index in zip(targets, best, strict=True)
    }


def _distance_or_max(
    candidate: OfficialVoiceAcousticProfile,
    references: Iterable[OfficialVoiceAcousticProfile],
) -> int:
    distances = tuple(
        official_voice_acoustic_distance_milli(candidate, reference)
        for reference in references
    )
    return min(distances) if distances else 1000


def _reuse_choice(
    target: CastTarget,
    *,
    candidate_ids: tuple[str, ...],
    profiles: dict[str, OfficialVoiceAcousticProfile],
    manifest_order: dict[str, int],
    score_map: dict[str, OfficialVoiceCandidateScore],
    usage_count: dict[str, int],
    prior: tuple[tuple[CastTarget, str], ...],
) -> str:
    narrator_profiles = tuple(
        profiles[preset_id]
        for prior_target, preset_id in prior
        if prior_target.role is CastRole.NARRATOR
    )
    main_profiles = tuple(
        profiles[preset_id]
        for prior_target, preset_id in prior
        if prior_target.role is CastRole.MAIN
    )
    adjacent_profile = profiles[prior[-1][1]] if prior else None

    def key(preset_id: str) -> tuple[int, int, int, int, int, int]:
        profile = profiles[preset_id]
        return (
            _distance_or_max(profile, narrator_profiles),
            _distance_or_max(profile, main_profiles),
            (
                official_voice_acoustic_distance_milli(profile, adjacent_profile)
                if adjacent_profile is not None
                else 1000
            ),
            score_map[preset_id].score_milli,
            -usage_count.get(preset_id, 0),
            -manifest_order[preset_id],
        )

    return max(candidate_ids, key=key)


def solve_character_cast(
    targets: Sequence[CastTarget],
    *,
    baseline: OfficialVoiceCastingBaseline | None = None,
) -> CharacterCastSolution:
    """Plan all official-voice changes without mutating any binding.

    Protected private/uploaded/generated voices are always preserved.  Valid
    unique official voices are preserved, while lower-priority participants in
    an official collision enter deterministic reassignment.  Assignment is
    grouped by language and never introduces a cross-language preset.
    """

    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise _invalid("cast targets must be a finite sequence")
    ordered = tuple(targets)
    if any(type(target) is not CastTarget for target in ordered):
        raise _invalid("cast targets must be validated CastTarget values")
    target_keys = tuple(target.target_key for target in ordered)
    if len(set(target_keys)) != len(target_keys):
        raise _invalid("cast target keys must be unique")
    stable_scopes = tuple((target.kind, target.stable_id) for target in ordered)
    if len(set(stable_scopes)) != len(stable_scopes):
        raise _invalid("cast target stable scopes must be unique")

    catalog = baseline or load_official_voice_casting_baseline()
    profiles, manifest_order = _profile_maps(catalog)
    priority_targets = tuple(sorted(ordered, key=_target_sort_key))
    decisions: dict[str, CastDecision] = {}
    warnings: list[CastWarning] = []
    assignment_pool: list[CastTarget] = []

    protected_by_identity: dict[tuple[CastVoiceSource, str], list[str]] = {}
    official_users: dict[str, list[CastTarget]] = {}
    for target in priority_targets:
        current = target.current_voice
        if current is None:
            assignment_pool.append(target)
            continue
        if current.source is not CastVoiceSource.OFFICIAL:
            decisions[target.target_key] = CastDecision(
                target_key=target.target_key,
                status=CastDecisionStatus.PRESERVED,
                reason_code=CHARACTER_CAST_PROTECTED_NON_OFFICIAL_PRESERVED,
                preset_id=None,
                language=_effective_language(target),
            )
            protected_by_identity.setdefault(
                (current.source, current.identity_key), []
            ).append(target.target_key)
            continue
        if (
            not current.available
            or current.preset_id is None
            or current.preset_id not in profiles
        ):
            assignment_pool.append(target)
            continue
        official_users.setdefault(current.preset_id, []).append(target)

    for (source, identity), users in sorted(
        protected_by_identity.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        if len(users) > 1:
            warnings.append(
                CastWarning(
                    code=CHARACTER_CAST_PROTECTED_VOICE_SHARED,
                    target_keys=tuple(users),
                    voice_identity=f"{source.value}:{identity}",
                )
            )

    preserved_official: dict[str, tuple[CastTarget, str]] = {}
    collision_losers: set[str] = set()
    for preset_id in sorted(official_users, key=manifest_order.__getitem__):
        users = tuple(sorted(official_users[preset_id], key=_target_sort_key))
        winner = users[0]
        preserved_official[winner.target_key] = (winner, preset_id)
        decisions[winner.target_key] = CastDecision(
            target_key=winner.target_key,
            status=CastDecisionStatus.PRESERVED,
            reason_code=(
                CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED
                if len(users) > 1
                else CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED
            ),
            preset_id=preset_id,
            language=profiles[preset_id].language,
        )
        for loser in users[1:]:
            collision_losers.add(loser.target_key)
            assignment_pool.append(loser)

    score_maps: dict[str, dict[str, OfficialVoiceCandidateScore]] = {}
    assignable_by_language: dict[CharacterVoiceLanguage, list[CastTarget]] = {}
    for target in sorted(assignment_pool, key=_target_sort_key):
        language = _effective_language(target)
        if target.brief is None:
            decisions[target.target_key] = CastDecision(
                target_key=target.target_key,
                status=CastDecisionStatus.BLOCKED,
                reason_code=CHARACTER_CAST_BRIEF_MISSING,
                preset_id=None,
                language=language,
                replaces_existing=target.current_voice is not None,
            )
            continue
        if language is None:
            decisions[target.target_key] = CastDecision(
                target_key=target.target_key,
                status=CastDecisionStatus.BLOCKED,
                reason_code=CHARACTER_CAST_LANGUAGE_UNKNOWN,
                preset_id=None,
                language=None,
                replaces_existing=target.current_voice is not None,
            )
            continue
        if all(
            getattr(target.brief, field_name) is None
            for field_name in ("presentation", "pitch", "pace", "energy", "texture")
        ):
            decisions[target.target_key] = CastDecision(
                target_key=target.target_key,
                status=CastDecisionStatus.BLOCKED,
                reason_code=CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS,
                preset_id=None,
                language=language,
                replaces_existing=target.current_voice is not None,
            )
            continue
        try:
            scores = score_official_voice_candidates(
                target.brief,
                effective_language=language,
                baseline=catalog,
            )
        except CharacterVoiceMatchingError as error:
            if error.code != CHARACTER_VOICE_NO_CANDIDATE:
                raise
            decisions[target.target_key] = CastDecision(
                target_key=target.target_key,
                status=CastDecisionStatus.BLOCKED,
                reason_code=CHARACTER_CAST_NO_LANGUAGE_CANDIDATE,
                preset_id=None,
                language=language,
                replaces_existing=target.current_voice is not None,
            )
            continue
        score_maps[target.target_key] = {
            score.preset_id: score for score in scores
        }
        assignable_by_language.setdefault(language, []).append(target)

    assigned_by_target: dict[str, str] = {}
    for language in CharacterVoiceLanguage:
        group = tuple(
            sorted(assignable_by_language.get(language, ()), key=_target_sort_key)
        )
        if not group:
            continue
        language_ids = tuple(
            profile.preset_id
            for profile in catalog.items
            if profile.language is language
        )
        preserved_for_language = tuple(
            (target, preset_id)
            for target, preset_id in preserved_official.values()
            if profiles[preset_id].language is language
        )
        used_ids = {preset_id for _, preset_id in preserved_for_language}
        free_ids = tuple(
            preset_id for preset_id in language_ids if preset_id not in used_ids
        )
        distinct_targets = group[: min(len(group), len(free_ids))]
        distinct = _assign_distinct(distinct_targets, free_ids, score_maps)
        assigned_by_target.update(distinct)

        usage_count = {preset_id: 0 for preset_id in language_ids}
        prior: list[tuple[CastTarget, str]] = list(
            sorted(preserved_for_language, key=lambda item: _target_sort_key(item[0]))
        )
        for _, preset_id in prior:
            usage_count[preset_id] += 1
        for target in distinct_targets:
            preset_id = distinct[target.target_key]
            usage_count[preset_id] += 1
            prior.append((target, preset_id))

        reuse_targets = group[len(distinct_targets) :]
        for target in reuse_targets:
            preset_id = _reuse_choice(
                target,
                candidate_ids=language_ids,
                profiles=profiles,
                manifest_order=manifest_order,
                score_map=score_maps[target.target_key],
                usage_count=usage_count,
                prior=tuple(
                    sorted(
                        (
                            item
                            for item in prior
                            if _target_sort_key(item[0]) < _target_sort_key(target)
                        ),
                        key=lambda item: _target_sort_key(item[0]),
                    )
                ),
            )
            assigned_by_target[target.target_key] = preset_id
            usage_count[preset_id] += 1
            prior.append((target, preset_id))

        if reuse_targets:
            warnings.append(
                CastWarning(
                    code=CHARACTER_CAST_OFFICIAL_POOL_REUSED,
                    target_keys=tuple(target.target_key for target in reuse_targets),
                    voice_identity=language.value,
                )
            )

    targets_by_key = {target.target_key: target for target in priority_targets}
    for target in sorted(assignment_pool, key=_target_sort_key):
        preset_id = assigned_by_target.get(target.target_key)
        if preset_id is None:
            if target.target_key in collision_losers:
                warnings.append(
                    CastWarning(
                        code=CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED,
                        target_keys=(target.target_key,),
                        voice_identity=(
                            target.current_voice.preset_id
                            if target.current_voice is not None
                            else None
                        ),
                    )
                )
            continue
        score = score_maps[target.target_key][preset_id]
        language = profiles[preset_id].language
        used_before = preset_id in {
            preserved_id
            for _, preserved_id in preserved_official.values()
            if profiles[preserved_id].language is language
        } or sum(
            1
            for other_key, other_id in assigned_by_target.items()
            if other_id == preset_id
            and _target_sort_key(targets_by_key[other_key]) < _target_sort_key(target)
        ) > 0
        decisions[target.target_key] = CastDecision(
            target_key=target.target_key,
            status=CastDecisionStatus.ASSIGNED,
            reason_code=(
                CHARACTER_CAST_OFFICIAL_COLLISION_REASSIGNED
                if target.target_key in collision_losers
                else CHARACTER_CAST_OFFICIAL_ASSIGNED
            ),
            preset_id=preset_id,
            language=language,
            score_milli=score.score_milli,
            compared_dimensions=score.compared_dimensions,
            reused=used_before,
            replaces_existing=target.current_voice is not None,
        )

    final_decisions = tuple(decisions[target.target_key] for target in priority_targets)
    return CharacterCastSolution(
        baseline_sha256=catalog.file_sha256,
        decisions=final_decisions,
        warnings=tuple(warnings),
    )


__all__ = [
    "CHARACTER_CAST_BRIEF_MISSING",
    "CHARACTER_CAST_INVALID_INPUT",
    "CHARACTER_CAST_LANGUAGE_UNKNOWN",
    "CHARACTER_CAST_NO_LANGUAGE_CANDIDATE",
    "CHARACTER_CAST_NO_SCOREABLE_DIMENSIONS",
    "CHARACTER_CAST_EXISTING_OFFICIAL_PRESERVED",
    "CHARACTER_CAST_OFFICIAL_ASSIGNED",
    "CHARACTER_CAST_OFFICIAL_COLLISION_PRIORITY_PRESERVED",
    "CHARACTER_CAST_OFFICIAL_COLLISION_REASSIGNED",
    "CHARACTER_CAST_OFFICIAL_COLLISION_UNRESOLVED",
    "CHARACTER_CAST_OFFICIAL_POOL_REUSED",
    "CHARACTER_CAST_PROTECTED_NON_OFFICIAL_PRESERVED",
    "CHARACTER_CAST_PROTECTED_VOICE_SHARED",
    "CastDecision",
    "CastDecisionStatus",
    "CastRole",
    "CastTarget",
    "CastTargetKind",
    "CastVoiceSource",
    "CastWarning",
    "CharacterCastError",
    "CharacterCastSolution",
    "CurrentCastVoice",
    "solve_character_cast",
]
