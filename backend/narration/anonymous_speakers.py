"""Immutable anonymous-speaker identity and lineage operations for T3-E.

The module is deliberately free of ORM, HTTP, and model calls.  It consumes the
frozen T3-A identity derivation, then models registration, merge, split, and
promotion as replayable operations.  Historical script identities never change;
lineage is consulted only when a later script is materialized.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final, Mapping, Sequence, TypeAlias
from uuid import RFC_4122, UUID

from .contracts import ConfidenceLevel
from .script_contracts import (
    ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
    AnonymousScopeKind,
    AnonymousSpeakerIdentity,
    ScriptContractError,
    derive_anonymous_speaker_id,
    derive_anonymous_stable_key,
    normalize_identity_label,
)


ANONYMOUS_OPERATION_VERSION: Final = "anonymous-speaker-operation/1"
_SHA256: Final = re.compile(r"^[a-f0-9]{64}$")


class AnonymousSpeakerError(ScriptContractError):
    """Base error for anonymous-speaker identity and lineage violations."""


class AnonymousIdentityConflictError(AnonymousSpeakerError):
    """Raised when an identity or operation would have two meanings."""


class AnonymousInheritanceAmbiguityError(AnonymousSpeakerError):
    """Raised when a split parent is reused without an exact reference route."""


class AnonymousOperationActor(str, Enum):
    SYSTEM = "system"
    OWNER = "owner"


class AnonymousReuseBasis(str, Enum):
    LOCAL_CONTEXT = "local_context"
    EXPLICIT_ALIAS = "explicit_alias"
    OWNER_CONFIRMED = "owner_confirmed"


class AnonymousLifecycleState(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"
    SPLIT = "split"
    PROMOTED = "promoted"


class AnonymousResolutionKind(str, Enum):
    ANONYMOUS = "anonymous"
    CHARACTER = "character"


def _require_uuid(value: object, *, field_name: str) -> UUID:
    if (
        type(value) is not UUID
        or value.variant != RFC_4122
        or value.version not in {1, 2, 3, 4, 5}
    ):
        raise AnonymousSpeakerError(f"{field_name} must be an RFC-4122 UUID v1-v5")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise AnonymousSpeakerError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_text(value: object, *, field_name: str, maximum: int = 160) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise AnonymousSpeakerError(
            f"{field_name} must be a non-empty string up to {maximum} characters"
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise AnonymousSpeakerError(
            f"{field_name} contains an unpaired Unicode surrogate"
        ) from error
    return value


def _require_utc(value: object, *, field_name: str) -> datetime:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise AnonymousSpeakerError(f"{field_name} must be a UTC datetime")
    return value


def _canonical_uuid_tuple(
    values: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[UUID, ...]:
    if type(values) is not tuple or len(values) < minimum:
        raise AnonymousSpeakerError(
            f"{field_name} must be a tuple with at least {minimum} item(s)"
        )
    for value in values:
        _require_uuid(value, field_name=f"{field_name} item")
    if len(set(values)) != len(values):
        raise AnonymousSpeakerError(f"{field_name} must not contain duplicates")
    if values != tuple(sorted(values, key=str)):
        raise AnonymousSpeakerError(f"{field_name} must use canonical UUID order")
    return values


@dataclass(frozen=True, slots=True)
class SceneScopeBinding:
    scene_id: UUID
    chapter_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.scene_id, field_name="scene scope scene_id")
        _require_uuid(self.chapter_id, field_name="scene scope chapter_id")


@dataclass(frozen=True, slots=True)
class HistoricalAnonymousReference:
    anonymous_speaker_id: UUID
    reference_id: UUID
    scope_kind: AnonymousScopeKind
    scope_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(
            self.anonymous_speaker_id,
            field_name="historical anonymous_speaker_id",
        )
        _require_uuid(self.reference_id, field_name="historical reference_id")
        if type(self.scope_kind) is not AnonymousScopeKind:
            raise AnonymousSpeakerError(
                "historical reference scope_kind must use AnonymousScopeKind"
            )
        _require_uuid(self.scope_id, field_name="historical reference scope_id")


@dataclass(frozen=True, slots=True)
class AnonymousScopeAuthority:
    """Server-owned same-novel scope and historical-reference authority."""

    novel_id: UUID
    chapter_ids: frozenset[UUID] = frozenset()
    scene_bindings: frozenset[SceneScopeBinding] = frozenset()
    character_ids: frozenset[UUID] = frozenset()
    historical_references: frozenset[HistoricalAnonymousReference] = frozenset()

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="authority novel_id")
        for field_name in ("chapter_ids", "character_ids"):
            values = getattr(self, field_name)
            if type(values) is not frozenset:
                raise AnonymousSpeakerError(f"authority {field_name} must be a frozenset")
            for value in values:
                _require_uuid(value, field_name=f"authority {field_name} item")
        if type(self.scene_bindings) is not frozenset or not all(
            type(value) is SceneScopeBinding for value in self.scene_bindings
        ):
            raise AnonymousSpeakerError(
                "authority scene_bindings must be a frozenset of SceneScopeBinding"
            )
        if type(self.historical_references) is not frozenset or not all(
            type(value) is HistoricalAnonymousReference
            for value in self.historical_references
        ):
            raise AnonymousSpeakerError(
                "authority historical_references must be a frozenset of "
                "HistoricalAnonymousReference"
            )
        scene_ids = {binding.scene_id for binding in self.scene_bindings}
        if len(scene_ids) != len(self.scene_bindings):
            raise AnonymousSpeakerError("authority scene ids must be unique")
        if any(
            binding.chapter_id not in self.chapter_ids
            for binding in self.scene_bindings
        ):
            raise AnonymousSpeakerError(
                "authority scene binding references an unknown chapter"
            )
        reference_pairs = {
            (value.anonymous_speaker_id, value.reference_id)
            for value in self.historical_references
        }
        if len(reference_pairs) != len(self.historical_references):
            raise AnonymousSpeakerError("authority historical references must be unique")
        reference_ids = {
            value.reference_id for value in self.historical_references
        }
        if len(reference_ids) != len(self.historical_references):
            raise AnonymousSpeakerError(
                "each historical reference_id must name exactly one identity"
            )
        for reference in self.historical_references:
            self.validate_scope(reference.scope_kind, reference.scope_id)

    def validate_scope(self, scope_kind: AnonymousScopeKind, scope_id: UUID) -> None:
        if type(scope_kind) is not AnonymousScopeKind:
            raise AnonymousSpeakerError("scope_kind must use AnonymousScopeKind")
        _require_uuid(scope_id, field_name="scope_id")
        if scope_kind is AnonymousScopeKind.NOVEL:
            if scope_id != self.novel_id:
                raise AnonymousSpeakerError("novel scope_id must equal novel_id")
            return
        if scope_kind is AnonymousScopeKind.CHAPTER:
            if scope_id not in self.chapter_ids:
                raise AnonymousSpeakerError("chapter scope is outside novel authority")
            return
        if scope_id not in {value.scene_id for value in self.scene_bindings}:
            raise AnonymousSpeakerError("scene scope is outside novel authority")

    def contains_scope(
        self,
        container_kind: AnonymousScopeKind,
        container_id: UUID,
        member_kind: AnonymousScopeKind,
        member_id: UUID,
    ) -> bool:
        self.validate_scope(container_kind, container_id)
        self.validate_scope(member_kind, member_id)
        if container_kind is AnonymousScopeKind.NOVEL:
            return True
        if container_kind is AnonymousScopeKind.SCENE:
            return (
                member_kind is AnonymousScopeKind.SCENE
                and member_id == container_id
            )
        if member_kind is AnonymousScopeKind.NOVEL:
            return False
        if member_kind is AnonymousScopeKind.CHAPTER:
            return member_id == container_id
        scene_to_chapter = {
            value.scene_id: value.chapter_id for value in self.scene_bindings
        }
        return scene_to_chapter[member_id] == container_id


@dataclass(frozen=True, slots=True)
class AnonymousIdentitySeed:
    novel_id: UUID
    identity: AnonymousSpeakerIdentity
    source_label: str
    evidence_hash: str
    reuse_basis: AnonymousReuseBasis
    explicit_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_uuid(self.novel_id, field_name="identity seed novel_id")
        if type(self.identity) is not AnonymousSpeakerIdentity:
            raise AnonymousSpeakerError(
                "identity seed identity must be AnonymousSpeakerIdentity"
            )
        _require_text(self.source_label, field_name="identity seed source_label")
        _require_sha256(self.evidence_hash, field_name="identity seed evidence_hash")
        if type(self.reuse_basis) is not AnonymousReuseBasis:
            raise AnonymousSpeakerError("reuse_basis must use AnonymousReuseBasis")
        if type(self.explicit_aliases) is not tuple:
            raise AnonymousSpeakerError("explicit_aliases must be a tuple")
        normalized_aliases: list[str] = []
        for alias in self.explicit_aliases:
            _require_text(alias, field_name="explicit alias")
            if alias != unicodedata.normalize("NFC", alias):
                raise AnonymousSpeakerError("explicit aliases must use Unicode NFC")
            normalized_aliases.append(normalize_identity_label(alias))
        if len(set(normalized_aliases)) != len(normalized_aliases):
            raise AnonymousSpeakerError("explicit aliases must be unique after normalization")
        if normalized_aliases != sorted(normalized_aliases):
            raise AnonymousSpeakerError("explicit aliases must use canonical normalized order")
        if (
            self.reuse_basis is AnonymousReuseBasis.EXPLICIT_ALIAS
            and not self.explicit_aliases
        ):
            raise AnonymousSpeakerError(
                "explicit_alias reuse requires at least one explicit alias"
            )
        expected_key = derive_anonymous_stable_key(
            novel_id=self.novel_id,
            scope_kind=self.identity.scope_kind,
            scope_id=self.identity.scope_id,
            label=self.source_label,
            evidence_hash=self.evidence_hash,
        )
        if self.identity.stable_key_algorithm != ANONYMOUS_SPEAKER_STABLE_KEY_VERSION:
            raise AnonymousSpeakerError("unknown anonymous stable-key algorithm")
        if self.identity.stable_key != expected_key:
            raise AnonymousSpeakerError("identity stable_key differs from frozen derivation")
        if self.identity.anonymous_speaker_id != derive_anonymous_speaker_id(
            novel_id=self.novel_id,
            stable_key=expected_key,
        ):
            raise AnonymousSpeakerError(
                "anonymous_speaker_id differs from frozen derivation"
            )


def materialize_anonymous_identity(
    *,
    authority: AnonymousScopeAuthority,
    scope_kind: AnonymousScopeKind,
    scope_id: UUID,
    source_label: str,
    evidence_hash: str,
    display_name: str,
    confidence: ConfidenceLevel,
    reuse_basis: AnonymousReuseBasis = AnonymousReuseBasis.LOCAL_CONTEXT,
    explicit_aliases: Sequence[str] = (),
) -> AnonymousIdentitySeed:
    """Create one identity using only the frozen T3-A key and ID algorithms."""

    if type(authority) is not AnonymousScopeAuthority:
        raise AnonymousSpeakerError("authority must be AnonymousScopeAuthority")
    authority.validate_scope(scope_kind, scope_id)
    if type(confidence) is not ConfidenceLevel:
        raise AnonymousSpeakerError("confidence must use ConfidenceLevel")
    _require_text(display_name, field_name="display_name")
    if display_name != unicodedata.normalize("NFC", display_name):
        raise AnonymousSpeakerError("display_name must use Unicode NFC")
    if type(explicit_aliases) not in {tuple, list}:
        raise AnonymousSpeakerError("explicit_aliases must be a tuple or list")
    for alias in explicit_aliases:
        _require_text(alias, field_name="explicit alias")
    aliases = tuple(
        sorted(
            (unicodedata.normalize("NFC", value) for value in explicit_aliases),
            key=normalize_identity_label,
        )
    )
    stable_key = derive_anonymous_stable_key(
        novel_id=authority.novel_id,
        scope_kind=scope_kind,
        scope_id=scope_id,
        label=source_label,
        evidence_hash=evidence_hash,
    )
    identity = AnonymousSpeakerIdentity(
        anonymous_speaker_id=derive_anonymous_speaker_id(
            novel_id=authority.novel_id,
            stable_key=stable_key,
        ),
        stable_key_algorithm=ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
        stable_key=stable_key,
        display_name=display_name,
        scope_kind=scope_kind,
        scope_id=scope_id,
        confidence=confidence,
    )
    return AnonymousIdentitySeed(
        novel_id=authority.novel_id,
        identity=identity,
        source_label=source_label,
        evidence_hash=evidence_hash,
        reuse_basis=reuse_basis,
        explicit_aliases=aliases,
    )


@dataclass(frozen=True, slots=True)
class AnonymousOperationHeader:
    action_id: UUID
    novel_id: UUID
    ordinal: int
    actor: AnonymousOperationActor
    actor_id: UUID | None
    recorded_at: datetime
    schema_version: str = ANONYMOUS_OPERATION_VERSION

    def __post_init__(self) -> None:
        _require_uuid(self.action_id, field_name="operation action_id")
        _require_uuid(self.novel_id, field_name="operation novel_id")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise AnonymousSpeakerError("operation ordinal must be an integer >= 0")
        if type(self.actor) is not AnonymousOperationActor:
            raise AnonymousSpeakerError("operation actor must use AnonymousOperationActor")
        if self.actor is AnonymousOperationActor.OWNER:
            _require_uuid(self.actor_id, field_name="owner actor_id")
        elif self.actor_id is not None:
            raise AnonymousSpeakerError("system operation must not claim an owner actor_id")
        _require_utc(self.recorded_at, field_name="operation recorded_at")
        if self.schema_version != ANONYMOUS_OPERATION_VERSION:
            raise AnonymousSpeakerError("unknown anonymous operation schema version")


@dataclass(frozen=True, slots=True)
class RegisterAnonymousSpeaker:
    header: AnonymousOperationHeader
    seed: AnonymousIdentitySeed

    def __post_init__(self) -> None:
        if type(self.header) is not AnonymousOperationHeader:
            raise AnonymousSpeakerError("register header is invalid")
        if type(self.seed) is not AnonymousIdentitySeed:
            raise AnonymousSpeakerError("register seed is invalid")


@dataclass(frozen=True, slots=True)
class MergeAnonymousSpeakers:
    header: AnonymousOperationHeader
    source_ids: tuple[UUID, ...]
    target_id: UUID

    def __post_init__(self) -> None:
        if type(self.header) is not AnonymousOperationHeader:
            raise AnonymousSpeakerError("merge header is invalid")
        _canonical_uuid_tuple(self.source_ids, field_name="merge source_ids", minimum=1)
        _require_uuid(self.target_id, field_name="merge target_id")
        if self.target_id in self.source_ids:
            raise AnonymousSpeakerError("merge target cannot also be a source")


@dataclass(frozen=True, slots=True)
class SplitBranch:
    seed: AnonymousIdentitySeed
    historical_reference_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if type(self.seed) is not AnonymousIdentitySeed:
            raise AnonymousSpeakerError("split branch seed is invalid")
        _canonical_uuid_tuple(
            self.historical_reference_ids,
            field_name="split historical_reference_ids",
            minimum=1,
        )


@dataclass(frozen=True, slots=True)
class SplitAnonymousSpeaker:
    header: AnonymousOperationHeader
    parent_id: UUID
    branches: tuple[SplitBranch, ...]

    def __post_init__(self) -> None:
        if type(self.header) is not AnonymousOperationHeader:
            raise AnonymousSpeakerError("split header is invalid")
        _require_uuid(self.parent_id, field_name="split parent_id")
        if type(self.branches) is not tuple or len(self.branches) < 2 or not all(
            type(branch) is SplitBranch for branch in self.branches
        ):
            raise AnonymousSpeakerError("split requires at least two SplitBranch values")
        branch_ids = [branch.seed.identity.anonymous_speaker_id for branch in self.branches]
        if len(set(branch_ids)) != len(branch_ids):
            raise AnonymousSpeakerError("split branch identities must be unique")
        if self.branches != tuple(
            sorted(
                self.branches,
                key=lambda branch: (
                    branch.seed.identity.stable_key_algorithm,
                    branch.seed.identity.stable_key,
                    str(branch.seed.identity.anonymous_speaker_id),
                ),
            )
        ):
            raise AnonymousSpeakerError("split branches must use canonical identity order")
        references = [
            reference_id
            for branch in self.branches
            for reference_id in branch.historical_reference_ids
        ]
        if len(set(references)) != len(references):
            raise AnonymousSpeakerError("split reference assignments must be disjoint")


@dataclass(frozen=True, slots=True)
class PromoteAnonymousSpeaker:
    header: AnonymousOperationHeader
    anonymous_speaker_id: UUID
    character_id: UUID

    def __post_init__(self) -> None:
        if type(self.header) is not AnonymousOperationHeader:
            raise AnonymousSpeakerError("promotion header is invalid")
        _require_uuid(
            self.anonymous_speaker_id,
            field_name="promotion anonymous_speaker_id",
        )
        _require_uuid(self.character_id, field_name="promotion character_id")


AnonymousOperation: TypeAlias = (
    RegisterAnonymousSpeaker
    | MergeAnonymousSpeakers
    | SplitAnonymousSpeaker
    | PromoteAnonymousSpeaker
)


@dataclass(frozen=True, slots=True)
class AnonymousSplitRoute:
    parent_id: UUID
    reference_id: UUID
    child_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.parent_id, field_name="split route parent_id")
        _require_uuid(self.reference_id, field_name="split route reference_id")
        _require_uuid(self.child_id, field_name="split route child_id")


@dataclass(frozen=True, slots=True)
class AnonymousSpeakerResolution:
    kind: AnonymousResolutionKind
    anonymous_speaker_id: UUID | None = None
    character_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not AnonymousResolutionKind:
            raise AnonymousSpeakerError("resolution kind is invalid")
        if self.anonymous_speaker_id is not None:
            _require_uuid(
                self.anonymous_speaker_id,
                field_name="resolution anonymous_speaker_id",
            )
        if self.character_id is not None:
            _require_uuid(self.character_id, field_name="resolution character_id")
        if self.kind is AnonymousResolutionKind.ANONYMOUS:
            valid = self.anonymous_speaker_id is not None and self.character_id is None
        else:
            valid = self.character_id is not None and self.anonymous_speaker_id is None
        if not valid:
            raise AnonymousSpeakerError("resolution target shape is invalid")


@dataclass(frozen=True, slots=True)
class AnonymousSpeakerRegistry:
    authority: AnonymousScopeAuthority
    operations: tuple[AnonymousOperation, ...]
    identities: tuple[AnonymousIdentitySeed, ...]
    merged_into: tuple[tuple[UUID, UUID], ...]
    split_routes: tuple[AnonymousSplitRoute, ...]
    promotions: tuple[tuple[UUID, UUID], ...]

    def __post_init__(self) -> None:
        if type(self.authority) is not AnonymousScopeAuthority:
            raise AnonymousSpeakerError("registry authority is invalid")
        if type(self.operations) is not tuple or not all(
            type(value)
            in {
                RegisterAnonymousSpeaker,
                MergeAnonymousSpeakers,
                SplitAnonymousSpeaker,
                PromoteAnonymousSpeaker,
            }
            for value in self.operations
        ):
            raise AnonymousSpeakerError("registry operations are invalid")
        if type(self.identities) is not tuple or not all(
            type(value) is AnonymousIdentitySeed for value in self.identities
        ):
            raise AnonymousSpeakerError("registry identities are invalid")
        expected_identities = tuple(
            sorted(
                self.identities,
                key=lambda seed: (
                    seed.identity.stable_key_algorithm,
                    seed.identity.stable_key,
                    str(seed.identity.anonymous_speaker_id),
                ),
            )
        )
        if self.identities != expected_identities:
            raise AnonymousSpeakerError("registry identities are not canonical")
        identity_ids = {
            seed.identity.anonymous_speaker_id for seed in self.identities
        }
        if len(identity_ids) != len(self.identities):
            raise AnonymousSpeakerError("registry identity ids are not unique")
        if type(self.merged_into) is not tuple:
            raise AnonymousSpeakerError("registry merge projection is invalid")
        if type(self.split_routes) is not tuple or not all(
            type(value) is AnonymousSplitRoute for value in self.split_routes
        ):
            raise AnonymousSpeakerError("registry split routes are invalid")
        if type(self.promotions) is not tuple:
            raise AnonymousSpeakerError("registry promotion projection is invalid")
        for field_name, pairs in (
            ("merge", self.merged_into),
            ("promotion", self.promotions),
        ):
            keys: set[UUID] = set()
            for pair in pairs:
                if type(pair) is not tuple or len(pair) != 2:
                    raise AnonymousSpeakerError(f"registry {field_name} pair is invalid")
                _require_uuid(pair[0], field_name=f"registry {field_name} source")
                _require_uuid(pair[1], field_name=f"registry {field_name} target")
                if pair[0] in keys:
                    raise AnonymousSpeakerError(
                        f"registry {field_name} sources are not unique"
                    )
                keys.add(pair[0])
            if pairs != tuple(sorted(pairs, key=lambda item: str(item[0]))):
                raise AnonymousSpeakerError(
                    f"registry {field_name} projection is not canonical"
                )
        expected_routes = tuple(
            sorted(
                self.split_routes,
                key=lambda route: (
                    str(route.parent_id),
                    str(route.reference_id),
                    str(route.child_id),
                ),
            )
        )
        if self.split_routes != expected_routes:
            raise AnonymousSpeakerError("registry split routes are not canonical")
        route_keys = {
            (route.parent_id, route.reference_id) for route in self.split_routes
        }
        if len(route_keys) != len(self.split_routes):
            raise AnonymousSpeakerError("registry split routes are ambiguous")

    @property
    def revision(self) -> int:
        return len(self.operations)

    def historical_identity(self, anonymous_speaker_id: UUID) -> AnonymousSpeakerIdentity:
        _require_uuid(anonymous_speaker_id, field_name="anonymous_speaker_id")
        for seed in self.identities:
            if seed.identity.anonymous_speaker_id == anonymous_speaker_id:
                return seed.identity
        raise AnonymousSpeakerError("anonymous speaker identity is unknown")

    def lifecycle(self, anonymous_speaker_id: UUID) -> AnonymousLifecycleState:
        self.historical_identity(anonymous_speaker_id)
        if anonymous_speaker_id in dict(self.merged_into):
            return AnonymousLifecycleState.MERGED
        if anonymous_speaker_id in {route.parent_id for route in self.split_routes}:
            return AnonymousLifecycleState.SPLIT
        if anonymous_speaker_id in dict(self.promotions):
            return AnonymousLifecycleState.PROMOTED
        return AnonymousLifecycleState.ACTIVE

    def resolve_for_new_script(
        self,
        anonymous_speaker_id: UUID,
        *,
        usage_scope_kind: AnonymousScopeKind,
        usage_scope_id: UUID,
        historical_reference_id: UUID | None = None,
    ) -> AnonymousSpeakerResolution:
        initial_identity = self.historical_identity(anonymous_speaker_id)
        self.authority.validate_scope(usage_scope_kind, usage_scope_id)
        if not self.authority.contains_scope(
            initial_identity.scope_kind,
            initial_identity.scope_id,
            usage_scope_kind,
            usage_scope_id,
        ):
            raise AnonymousSpeakerError(
                "anonymous identity cannot be reused outside its authorized scope"
            )
        if historical_reference_id is not None:
            _require_uuid(
                historical_reference_id,
                field_name="historical_reference_id",
            )
        merges = dict(self.merged_into)
        promotions = dict(self.promotions)
        routes = {
            (route.parent_id, route.reference_id): route.child_id
            for route in self.split_routes
        }
        split_parents = {route.parent_id for route in self.split_routes}
        current = anonymous_speaker_id
        visited: set[UUID] = set()
        while True:
            if current in visited:
                raise AnonymousIdentityConflictError("anonymous lineage contains a cycle")
            visited.add(current)
            if current in merges:
                current = merges[current]
                continue
            if current in split_parents:
                if historical_reference_id is None:
                    raise AnonymousInheritanceAmbiguityError(
                        "split anonymous identity requires an exact historical reference"
                    )
                child = routes.get((current, historical_reference_id))
                if child is None:
                    raise AnonymousInheritanceAmbiguityError(
                        "historical reference has no authorized split branch"
                    )
                current = child
                continue
            character_id = promotions.get(current)
            if character_id is not None:
                return AnonymousSpeakerResolution(
                    kind=AnonymousResolutionKind.CHARACTER,
                    character_id=character_id,
                )
            final_identity = self.historical_identity(current)
            if not self.authority.contains_scope(
                final_identity.scope_kind,
                final_identity.scope_id,
                usage_scope_kind,
                usage_scope_id,
            ):
                raise AnonymousSpeakerError(
                    "resolved anonymous identity does not cover the usage scope"
                )
            return AnonymousSpeakerResolution(
                kind=AnonymousResolutionKind.ANONYMOUS,
                anonymous_speaker_id=current,
            )

    def historical_script_snapshot(
        self,
        anonymous_speaker_ids: Sequence[UUID],
    ) -> tuple[AnonymousSpeakerIdentity, ...]:
        identities = {
            self.historical_identity(value) for value in anonymous_speaker_ids
        }
        return tuple(
            sorted(
                identities,
                key=lambda identity: (
                    identity.stable_key_algorithm,
                    identity.stable_key,
                    str(identity.anonymous_speaker_id),
                ),
            )
        )


def _operation_header(operation: AnonymousOperation) -> AnonymousOperationHeader:
    if type(operation) not in {
        RegisterAnonymousSpeaker,
        MergeAnonymousSpeakers,
        SplitAnonymousSpeaker,
        PromoteAnonymousSpeaker,
    }:
        raise AnonymousSpeakerError("unknown anonymous operation type")
    return operation.header


def _require_owner_operation(operation: AnonymousOperation) -> None:
    if _operation_header(operation).actor is not AnonymousOperationActor.OWNER:
        raise AnonymousSpeakerError("merge, split, and promotion require owner authority")


def _seed_scope_is_allowed(
    authority: AnonymousScopeAuthority,
    seed: AnonymousIdentitySeed,
    *,
    actor: AnonymousOperationActor,
) -> None:
    if seed.novel_id != authority.novel_id:
        raise AnonymousSpeakerError("anonymous identity belongs to another novel")
    authority.validate_scope(seed.identity.scope_kind, seed.identity.scope_id)
    if seed.identity.scope_kind is AnonymousScopeKind.NOVEL:
        if seed.reuse_basis is AnonymousReuseBasis.LOCAL_CONTEXT:
            raise AnonymousSpeakerError(
                "novel-scope reuse requires an explicit alias or owner confirmation"
            )
        if (
            seed.reuse_basis is AnonymousReuseBasis.OWNER_CONFIRMED
            and actor is not AnonymousOperationActor.OWNER
        ):
            raise AnonymousSpeakerError(
                "owner-confirmed novel scope requires an owner operation"
            )


def _resolve_historical_reference_owner(
    anonymous_speaker_id: UUID,
    reference_id: UUID,
    *,
    merges: Mapping[UUID, UUID],
    split_routes: Mapping[tuple[UUID, UUID], UUID],
) -> UUID:
    """Resolve one historical reference through every prior lineage operation."""

    current = anonymous_speaker_id
    visited: set[UUID] = set()
    while True:
        if current in visited:
            raise AnonymousIdentityConflictError(
                "anonymous historical lineage contains a cycle"
            )
        visited.add(current)
        merged_target = merges.get(current)
        if merged_target is not None:
            current = merged_target
            continue
        split_target = split_routes.get((current, reference_id))
        if split_target is not None:
            current = split_target
            continue
        return current


def _direct_lifecycle(
    anonymous_speaker_id: UUID,
    *,
    merges: Mapping[UUID, UUID],
    split_parents: set[UUID],
    promotions: Mapping[UUID, UUID],
) -> AnonymousLifecycleState:
    if anonymous_speaker_id in merges:
        return AnonymousLifecycleState.MERGED
    if anonymous_speaker_id in split_parents:
        return AnonymousLifecycleState.SPLIT
    if anonymous_speaker_id in promotions:
        return AnonymousLifecycleState.PROMOTED
    return AnonymousLifecycleState.ACTIVE


def replay_anonymous_operations(
    authority: AnonymousScopeAuthority,
    operations: Sequence[AnonymousOperation],
) -> AnonymousSpeakerRegistry:
    """Replay the exact operation log; missing, duplicated, or reordered data fails."""

    if type(authority) is not AnonymousScopeAuthority:
        raise AnonymousSpeakerError("authority must be AnonymousScopeAuthority")
    if type(operations) not in {tuple, list}:
        raise AnonymousSpeakerError("operations must be a tuple or list")
    identities: dict[UUID, AnonymousIdentitySeed] = {}
    stable_keys: set[tuple[str, str]] = set()
    merges: dict[UUID, UUID] = {}
    split_routes: dict[tuple[UUID, UUID], UUID] = {}
    split_parents: set[UUID] = set()
    promotions: dict[UUID, UUID] = {}
    action_ids: set[UUID] = set()
    accepted: list[AnonymousOperation] = []
    previous_recorded_at: datetime | None = None

    for expected_ordinal, operation in enumerate(operations):
        header = _operation_header(operation)
        if header.novel_id != authority.novel_id:
            raise AnonymousSpeakerError("operation belongs to another novel")
        if header.ordinal != expected_ordinal:
            raise AnonymousSpeakerError("operation ordinals must be contiguous from zero")
        if header.action_id in action_ids:
            raise AnonymousIdentityConflictError("duplicate action_id in operation log")
        if previous_recorded_at is not None and header.recorded_at < previous_recorded_at:
            raise AnonymousSpeakerError("operation recorded_at values must not move backwards")
        action_ids.add(header.action_id)
        previous_recorded_at = header.recorded_at

        if type(operation) is RegisterAnonymousSpeaker:
            seed = operation.seed
            _seed_scope_is_allowed(authority, seed, actor=header.actor)
            identity_id = seed.identity.anonymous_speaker_id
            stable_identity = (
                seed.identity.stable_key_algorithm,
                seed.identity.stable_key,
            )
            if identity_id in identities or stable_identity in stable_keys:
                raise AnonymousIdentityConflictError(
                    "anonymous stable identity is already registered"
                )
            identities[identity_id] = seed
            stable_keys.add(stable_identity)

        elif type(operation) is MergeAnonymousSpeakers:
            _require_owner_operation(operation)
            if operation.target_id not in identities:
                raise AnonymousSpeakerError("merge target identity is unknown")
            if _direct_lifecycle(
                operation.target_id,
                merges=merges,
                split_parents=split_parents,
                promotions=promotions,
            ) is not AnonymousLifecycleState.ACTIVE:
                raise AnonymousIdentityConflictError("merge target is not active")
            target = identities[operation.target_id].identity
            for source_id in operation.source_ids:
                if source_id not in identities:
                    raise AnonymousSpeakerError("merge source identity is unknown")
                if _direct_lifecycle(
                    source_id,
                    merges=merges,
                    split_parents=split_parents,
                    promotions=promotions,
                ) is not AnonymousLifecycleState.ACTIVE:
                    raise AnonymousIdentityConflictError("merge source is not active")
                source = identities[source_id].identity
                if not authority.contains_scope(
                    target.scope_kind,
                    target.scope_id,
                    source.scope_kind,
                    source.scope_id,
                ):
                    raise AnonymousIdentityConflictError(
                        "merge target scope does not contain every source scope"
                    )
                merges[source_id] = operation.target_id

        elif type(operation) is SplitAnonymousSpeaker:
            _require_owner_operation(operation)
            if operation.parent_id not in identities:
                raise AnonymousSpeakerError("split parent identity is unknown")
            if _direct_lifecycle(
                operation.parent_id,
                merges=merges,
                split_parents=split_parents,
                promotions=promotions,
            ) is not AnonymousLifecycleState.ACTIVE:
                raise AnonymousIdentityConflictError("split parent is not active")
            parent = identities[operation.parent_id].identity
            expected_references = {
                value.reference_id
                for value in authority.historical_references
                if _resolve_historical_reference_owner(
                    value.anonymous_speaker_id,
                    value.reference_id,
                    merges=merges,
                    split_routes=split_routes,
                )
                == operation.parent_id
            }
            assigned_references = {
                reference_id
                for branch in operation.branches
                for reference_id in branch.historical_reference_ids
            }
            if not expected_references:
                raise AnonymousIdentityConflictError(
                    "split requires authoritative historical references"
                )
            if assigned_references != expected_references:
                raise AnonymousIdentityConflictError(
                    "split branches must exactly partition authoritative references"
                )
            references_by_id = {
                value.reference_id: value
                for value in authority.historical_references
                if value.reference_id in expected_references
            }
            for reference in references_by_id.values():
                source_identity = identities[reference.anonymous_speaker_id].identity
                if not authority.contains_scope(
                    source_identity.scope_kind,
                    source_identity.scope_id,
                    reference.scope_kind,
                    reference.scope_id,
                ):
                    raise AnonymousIdentityConflictError(
                        "historical reference is outside its source identity scope"
                    )
            for branch in operation.branches:
                seed = branch.seed
                _seed_scope_is_allowed(authority, seed, actor=header.actor)
                child = seed.identity
                if not authority.contains_scope(
                    parent.scope_kind,
                    parent.scope_id,
                    child.scope_kind,
                    child.scope_id,
                ):
                    raise AnonymousIdentityConflictError(
                        "split branch scope must stay within its parent scope"
                    )
                child_id = child.anonymous_speaker_id
                stable_identity = (child.stable_key_algorithm, child.stable_key)
                if child_id in identities or stable_identity in stable_keys:
                    raise AnonymousIdentityConflictError(
                        "split branch identity already exists"
                    )
                for reference_id in branch.historical_reference_ids:
                    reference = references_by_id[reference_id]
                    if not authority.contains_scope(
                        child.scope_kind,
                        child.scope_id,
                        reference.scope_kind,
                        reference.scope_id,
                    ):
                        raise AnonymousIdentityConflictError(
                            "split branch scope does not cover its historical reference"
                        )
                identities[child_id] = seed
                stable_keys.add(stable_identity)
                for reference_id in branch.historical_reference_ids:
                    split_routes[(operation.parent_id, reference_id)] = child_id
            split_parents.add(operation.parent_id)

        else:
            _require_owner_operation(operation)
            if operation.anonymous_speaker_id not in identities:
                raise AnonymousSpeakerError("promotion identity is unknown")
            if _direct_lifecycle(
                operation.anonymous_speaker_id,
                merges=merges,
                split_parents=split_parents,
                promotions=promotions,
            ) is not AnonymousLifecycleState.ACTIVE:
                raise AnonymousIdentityConflictError(
                    "only an active unambiguous identity may be promoted"
                )
            if operation.character_id not in authority.character_ids:
                raise AnonymousSpeakerError(
                    "promotion character is outside same-novel authority"
                )
            promotions[operation.anonymous_speaker_id] = operation.character_id

        accepted.append(operation)

    for reference in authority.historical_references:
        seed = identities.get(reference.anonymous_speaker_id)
        if seed is None:
            raise AnonymousSpeakerError(
                "historical reference authority names an unregistered identity"
            )
        if not authority.contains_scope(
            seed.identity.scope_kind,
            seed.identity.scope_id,
            reference.scope_kind,
            reference.scope_id,
        ):
            raise AnonymousIdentityConflictError(
                "historical reference is outside its source identity scope"
            )

    ordered_identities = tuple(
        sorted(
            identities.values(),
            key=lambda seed: (
                seed.identity.stable_key_algorithm,
                seed.identity.stable_key,
                str(seed.identity.anonymous_speaker_id),
            ),
        )
    )
    routes = tuple(
        AnonymousSplitRoute(parent_id, reference_id, child_id)
        for (parent_id, reference_id), child_id in sorted(
            split_routes.items(),
            key=lambda item: (str(item[0][0]), str(item[0][1]), str(item[1])),
        )
    )
    return AnonymousSpeakerRegistry(
        authority=authority,
        operations=tuple(accepted),
        identities=ordered_identities,
        merged_into=tuple(sorted(merges.items(), key=lambda item: str(item[0]))),
        split_routes=routes,
        promotions=tuple(sorted(promotions.items(), key=lambda item: str(item[0]))),
    )


def apply_anonymous_operation(
    registry: AnonymousSpeakerRegistry,
    operation: AnonymousOperation,
) -> AnonymousSpeakerRegistry:
    """Apply once; an exact action retry returns the unchanged registry."""

    if type(registry) is not AnonymousSpeakerRegistry:
        raise AnonymousSpeakerError("registry must be AnonymousSpeakerRegistry")
    header = _operation_header(operation)
    for existing in registry.operations:
        if _operation_header(existing).action_id != header.action_id:
            continue
        if existing == operation:
            return registry
        raise AnonymousIdentityConflictError(
            "action_id was already used with a different operation payload"
        )
    if header.ordinal != registry.revision:
        raise AnonymousSpeakerError("new operation ordinal must equal registry revision")
    return replay_anonymous_operations(
        registry.authority,
        (*registry.operations, operation),
    )


def empty_anonymous_registry(
    authority: AnonymousScopeAuthority,
) -> AnonymousSpeakerRegistry:
    return replay_anonymous_operations(authority, ())


def _header_payload(header: AnonymousOperationHeader) -> dict[str, object]:
    return {
        "schema_version": header.schema_version,
        "action_id": str(header.action_id),
        "novel_id": str(header.novel_id),
        "ordinal": header.ordinal,
        "actor": header.actor.value,
        "actor_id": str(header.actor_id) if header.actor_id else None,
        "recorded_at": header.recorded_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
    }


def _seed_payload(seed: AnonymousIdentitySeed) -> dict[str, object]:
    identity = seed.identity
    return {
        "novel_id": str(seed.novel_id),
        "anonymous_speaker_id": str(identity.anonymous_speaker_id),
        "stable_key_algorithm": identity.stable_key_algorithm,
        "stable_key": identity.stable_key,
        "display_name": identity.display_name,
        "scope_kind": identity.scope_kind.value,
        "scope_id": str(identity.scope_id),
        "confidence": identity.confidence.value,
        "source_label": seed.source_label,
        "evidence_hash": seed.evidence_hash,
        "reuse_basis": seed.reuse_basis.value,
        "explicit_aliases": list(seed.explicit_aliases),
    }


def anonymous_operation_to_dict(operation: AnonymousOperation) -> dict[str, object]:
    """Return the versioned JSON-safe operation payload used for replay."""

    header = _operation_header(operation)
    payload: dict[str, object] = {"header": _header_payload(header)}
    if type(operation) is RegisterAnonymousSpeaker:
        payload.update({"kind": "register", "seed": _seed_payload(operation.seed)})
    elif type(operation) is MergeAnonymousSpeakers:
        payload.update(
            {
                "kind": "merge",
                "source_ids": [str(value) for value in operation.source_ids],
                "target_id": str(operation.target_id),
            }
        )
    elif type(operation) is SplitAnonymousSpeaker:
        payload.update(
            {
                "kind": "split",
                "parent_id": str(operation.parent_id),
                "branches": [
                    {
                        "seed": _seed_payload(branch.seed),
                        "historical_reference_ids": [
                            str(value) for value in branch.historical_reference_ids
                        ],
                    }
                    for branch in operation.branches
                ],
            }
        )
    else:
        payload.update(
            {
                "kind": "promote",
                "anonymous_speaker_id": str(operation.anonymous_speaker_id),
                "character_id": str(operation.character_id),
            }
        )
    return payload


def _expect_object(value: object, *, field_name: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise AnonymousSpeakerError(f"{field_name} must be a JSON object")
    return value


def _expect_keys(
    value: Mapping[str, object],
    *,
    keys: set[str],
    field_name: str,
) -> None:
    if set(value) != keys:
        raise AnonymousSpeakerError(f"{field_name} has invalid keys")


def _parse_uuid(value: object, *, field_name: str) -> UUID:
    if type(value) is not str:
        raise AnonymousSpeakerError(f"{field_name} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise AnonymousSpeakerError(f"{field_name} must be a UUID string") from error
    if str(parsed) != value:
        raise AnonymousSpeakerError(f"{field_name} must use canonical UUID form")
    return _require_uuid(parsed, field_name=field_name)


def _parse_header(value: object) -> AnonymousOperationHeader:
    payload = _expect_object(value, field_name="operation header")
    _expect_keys(
        payload,
        keys={
            "schema_version",
            "action_id",
            "novel_id",
            "ordinal",
            "actor",
            "actor_id",
            "recorded_at",
        },
        field_name="operation header",
    )
    actor_value = payload["actor"]
    if type(actor_value) is not str:
        raise AnonymousSpeakerError("operation actor must be a string")
    try:
        actor = AnonymousOperationActor(actor_value)
    except ValueError as error:
        raise AnonymousSpeakerError("unknown operation actor") from error
    actor_id_value = payload["actor_id"]
    actor_id = (
        None
        if actor_id_value is None
        else _parse_uuid(actor_id_value, field_name="operation actor_id")
    )
    recorded_value = payload["recorded_at"]
    if type(recorded_value) is not str or not recorded_value.endswith("Z"):
        raise AnonymousSpeakerError("recorded_at must be canonical UTC text")
    try:
        recorded_at = datetime.fromisoformat(recorded_value[:-1] + "+00:00")
    except ValueError as error:
        raise AnonymousSpeakerError("recorded_at must be canonical UTC text") from error
    canonical_time = recorded_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    if canonical_time != recorded_value:
        raise AnonymousSpeakerError("recorded_at must use canonical microsecond UTC text")
    return AnonymousOperationHeader(
        action_id=_parse_uuid(payload["action_id"], field_name="operation action_id"),
        novel_id=_parse_uuid(payload["novel_id"], field_name="operation novel_id"),
        ordinal=payload["ordinal"],  # type: ignore[arg-type]
        actor=actor,
        actor_id=actor_id,
        recorded_at=recorded_at,
        schema_version=payload["schema_version"],  # type: ignore[arg-type]
    )


def _parse_seed(value: object) -> AnonymousIdentitySeed:
    payload = _expect_object(value, field_name="identity seed")
    _expect_keys(
        payload,
        keys={
            "novel_id",
            "anonymous_speaker_id",
            "stable_key_algorithm",
            "stable_key",
            "display_name",
            "scope_kind",
            "scope_id",
            "confidence",
            "source_label",
            "evidence_hash",
            "reuse_basis",
            "explicit_aliases",
        },
        field_name="identity seed",
    )
    try:
        scope_kind = AnonymousScopeKind(payload["scope_kind"])
        confidence = ConfidenceLevel(payload["confidence"])
        reuse_basis = AnonymousReuseBasis(payload["reuse_basis"])
    except (TypeError, ValueError) as error:
        raise AnonymousSpeakerError("identity seed contains an unknown enum") from error
    aliases = payload["explicit_aliases"]
    if type(aliases) is not list or not all(type(value) is str for value in aliases):
        raise AnonymousSpeakerError("explicit_aliases must be a JSON string array")
    identity = AnonymousSpeakerIdentity(
        anonymous_speaker_id=_parse_uuid(
            payload["anonymous_speaker_id"],
            field_name="anonymous_speaker_id",
        ),
        stable_key_algorithm=payload["stable_key_algorithm"],  # type: ignore[arg-type]
        stable_key=payload["stable_key"],  # type: ignore[arg-type]
        display_name=payload["display_name"],  # type: ignore[arg-type]
        scope_kind=scope_kind,
        scope_id=_parse_uuid(payload["scope_id"], field_name="scope_id"),
        confidence=confidence,
    )
    return AnonymousIdentitySeed(
        novel_id=_parse_uuid(payload["novel_id"], field_name="seed novel_id"),
        identity=identity,
        source_label=payload["source_label"],  # type: ignore[arg-type]
        evidence_hash=payload["evidence_hash"],  # type: ignore[arg-type]
        reuse_basis=reuse_basis,
        explicit_aliases=tuple(aliases),
    )


def anonymous_operation_from_dict(value: object) -> AnonymousOperation:
    """Strict reverse loader; unknown versions, kinds, and fields fail closed."""

    payload = _expect_object(value, field_name="anonymous operation")
    kind = payload.get("kind")
    if type(kind) is not str:
        raise AnonymousSpeakerError("anonymous operation kind must be a string")
    expected_keys = {
        "register": {"header", "kind", "seed"},
        "merge": {"header", "kind", "source_ids", "target_id"},
        "split": {"header", "kind", "parent_id", "branches"},
        "promote": {
            "header",
            "kind",
            "anonymous_speaker_id",
            "character_id",
        },
    }.get(kind)
    if expected_keys is None:
        raise AnonymousSpeakerError("unknown anonymous operation kind")
    _expect_keys(payload, keys=expected_keys, field_name="anonymous operation")
    header = _parse_header(payload["header"])
    if kind == "register":
        return RegisterAnonymousSpeaker(header=header, seed=_parse_seed(payload["seed"]))
    if kind == "merge":
        sources = payload["source_ids"]
        if type(sources) is not list:
            raise AnonymousSpeakerError("merge source_ids must be a JSON array")
        return MergeAnonymousSpeakers(
            header=header,
            source_ids=tuple(
                _parse_uuid(value, field_name="merge source_id") for value in sources
            ),
            target_id=_parse_uuid(payload["target_id"], field_name="merge target_id"),
        )
    if kind == "split":
        branches_value = payload["branches"]
        if type(branches_value) is not list:
            raise AnonymousSpeakerError("split branches must be a JSON array")
        branches: list[SplitBranch] = []
        for item in branches_value:
            branch = _expect_object(item, field_name="split branch")
            _expect_keys(
                branch,
                keys={"seed", "historical_reference_ids"},
                field_name="split branch",
            )
            references = branch["historical_reference_ids"]
            if type(references) is not list:
                raise AnonymousSpeakerError(
                    "historical_reference_ids must be a JSON array"
                )
            branches.append(
                SplitBranch(
                    seed=_parse_seed(branch["seed"]),
                    historical_reference_ids=tuple(
                        _parse_uuid(value, field_name="historical reference_id")
                        for value in references
                    ),
                )
            )
        return SplitAnonymousSpeaker(
            header=header,
            parent_id=_parse_uuid(payload["parent_id"], field_name="split parent_id"),
            branches=tuple(branches),
        )
    return PromoteAnonymousSpeaker(
        header=header,
        anonymous_speaker_id=_parse_uuid(
            payload["anonymous_speaker_id"],
            field_name="promotion anonymous_speaker_id",
        ),
        character_id=_parse_uuid(
            payload["character_id"],
            field_name="promotion character_id",
        ),
    )


__all__ = [
    "ANONYMOUS_OPERATION_VERSION",
    "AnonymousIdentityConflictError",
    "AnonymousIdentitySeed",
    "AnonymousInheritanceAmbiguityError",
    "AnonymousLifecycleState",
    "AnonymousOperation",
    "AnonymousOperationActor",
    "AnonymousOperationHeader",
    "AnonymousResolutionKind",
    "AnonymousReuseBasis",
    "AnonymousScopeAuthority",
    "AnonymousSpeakerError",
    "AnonymousSpeakerRegistry",
    "AnonymousSpeakerResolution",
    "AnonymousSplitRoute",
    "HistoricalAnonymousReference",
    "MergeAnonymousSpeakers",
    "PromoteAnonymousSpeaker",
    "RegisterAnonymousSpeaker",
    "SceneScopeBinding",
    "SplitAnonymousSpeaker",
    "SplitBranch",
    "anonymous_operation_from_dict",
    "anonymous_operation_to_dict",
    "apply_anonymous_operation",
    "empty_anonymous_registry",
    "materialize_anonymous_identity",
    "replay_anonymous_operations",
]
