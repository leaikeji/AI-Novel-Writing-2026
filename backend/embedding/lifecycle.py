"""Pure embedding consent and generation state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Literal
from uuid import UUID


class EmbeddingLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConsentSnapshot:
    consent_id: UUID
    novel_id: UUID
    active: bool
    notice_version: str
    corpora: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NovelBuildState:
    novel_id: UUID
    consent_id: UUID
    state: Literal["pending", "building", "ready", "failed", "cancelled", "stale"]
    index_fingerprint: str


@dataclass(frozen=True, slots=True)
class GenerationState:
    generation_id: UUID
    state: Literal["draft", "building", "ready", "active", "failed", "cancelled", "stale", "retired"]
    index_fingerprint: str
    dimension: int
    novels: tuple[NovelBuildState, ...]


def consent_cohort_hash(consents: tuple[ConsentSnapshot, ...]) -> str:
    active = sorted(
        (
            str(item.novel_id),
            str(item.consent_id),
            item.notice_version,
            ",".join(sorted(item.corpora)),
        )
        for item in consents
        if item.active
    )
    return sha256(repr(active).encode("utf-8")).hexdigest()


def derive_generation_state(generation: GenerationState) -> GenerationState:
    if generation.state in {"active", "retired", "cancelled"}:
        return generation
    states = {item.state for item in generation.novels}
    if not generation.novels:
        target = "ready"
    elif states == {"ready"}:
        target = "ready"
    elif "failed" in states:
        target = "failed"
    elif states <= {"cancelled"}:
        target = "cancelled"
    elif states & {"building"}:
        target = "building"
    else:
        target = "draft"
    return replace(generation, state=target)


def activate_candidate(
    *,
    candidate: GenerationState,
    active_consents: tuple[ConsentSnapshot, ...],
    expected_dimension: int,
    expected_fingerprint: str,
) -> GenerationState:
    derived = derive_generation_state(candidate)
    if derived.state != "ready":
        raise EmbeddingLifecycleError("candidate_not_ready", "candidate generation is not ready")
    if candidate.dimension != expected_dimension or candidate.index_fingerprint != expected_fingerprint:
        raise EmbeddingLifecycleError("candidate_fingerprint_mismatch", "candidate profile changed")
    required = {item.novel_id: item.consent_id for item in active_consents if item.active}
    actual = {item.novel_id: item for item in candidate.novels}
    if set(actual) != set(required):
        raise EmbeddingLifecycleError("candidate_cohort_changed", "authorized novel cohort changed")
    for novel_id, consent_id in required.items():
        item = actual[novel_id]
        if item.consent_id != consent_id or item.state != "ready":
            raise EmbeddingLifecycleError("candidate_not_ready", "an authorized novel is not ready")
        if item.index_fingerprint != candidate.index_fingerprint:
            raise EmbeddingLifecycleError("candidate_fingerprint_mismatch", "novel index fingerprint differs")
    return replace(candidate, state="active")


def revoke_consent(
    builds: tuple[NovelBuildState, ...], *, novel_id: UUID
) -> tuple[NovelBuildState, ...]:
    """Stop future work while preserving local derived vectors."""

    return tuple(
        replace(item, state="cancelled")
        if item.novel_id == novel_id and item.state in {"pending", "building"}
        else item
        for item in builds
    )
