"""Atomic, fail-closed readiness for TTS35 and VoiceGenerator features.

The provider deliberately performs no I/O and knows nothing about Alembic,
storage paths, Sidecar clients, workers, or HTTP.  Their owners publish one
strict dependency snapshot after completing their own probes.  This keeps one
process-local readiness authority usable by the settings overview, route
guards, and runtime health without duplicating probe logic.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
import re
from threading import Lock
from typing import Awaitable, Callable, Final, Iterable, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import schemas as wire


FEATURE_READINESS_SCHEMA_VERSION: Final = "narration-feature-readiness/1"

LifecycleStatus = Literal[
    "disabled",
    "starting",
    "ready",
    "degraded",
    "stopping",
]

TTS_FEATURE_DISABLED: Final = "TTS_FEATURE_DISABLED"
TTS_FEATURE_STARTING: Final = "TTS_FEATURE_STARTING"
TTS_DATABASE_SCHEMA_OUTDATED: Final = "TTS_DATABASE_SCHEMA_OUTDATED"
TTS_STORAGE_UNAVAILABLE: Final = "TTS_STORAGE_UNAVAILABLE"
TTS_DIGEST_KEYRING_UNAVAILABLE: Final = "TTS_DIGEST_KEYRING_UNAVAILABLE"
TTS_SIDECAR_UNAVAILABLE: Final = "TTS_SIDECAR_UNAVAILABLE"
TTS_PROCESSOR_UNAVAILABLE: Final = "TTS_PROCESSOR_UNAVAILABLE"
TTS_DELETION_RECONCILER_UNAVAILABLE: Final = (
    "TTS_DELETION_RECONCILER_UNAVAILABLE"
)
TTS_CHARACTER_WORKSPACE_UNAVAILABLE: Final = (
    "TTS_CHARACTER_WORKSPACE_UNAVAILABLE"
)
TTS_NOVEL_AGENT_UNAVAILABLE: Final = "TTS_NOVEL_AGENT_UNAVAILABLE"
TTS_VOICE_GENERATOR_HOST_UNAVAILABLE: Final = (
    "TTS_VOICE_GENERATOR_HOST_UNAVAILABLE"
)
TTS_VOICE_GENERATOR_IDENTITY_MISMATCH: Final = (
    "TTS_VOICE_GENERATOR_IDENTITY_MISMATCH"
)
TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE: Final = (
    "TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE"
)
TTS_FEATURE_STOPPING: Final = "TTS_FEATURE_STOPPING"
TTS_FEATURE_CRASHED: Final = "TTS_FEATURE_CRASHED"

STABLE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        TTS_FEATURE_DISABLED,
        TTS_FEATURE_STARTING,
        TTS_DATABASE_SCHEMA_OUTDATED,
        TTS_STORAGE_UNAVAILABLE,
        TTS_DIGEST_KEYRING_UNAVAILABLE,
        TTS_SIDECAR_UNAVAILABLE,
        TTS_PROCESSOR_UNAVAILABLE,
        TTS_DELETION_RECONCILER_UNAVAILABLE,
        TTS_CHARACTER_WORKSPACE_UNAVAILABLE,
        TTS_NOVEL_AGENT_UNAVAILABLE,
        TTS_VOICE_GENERATOR_HOST_UNAVAILABLE,
        TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
        TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE,
        TTS_FEATURE_STOPPING,
        TTS_FEATURE_CRASHED,
    }
)

MANAGED_CAPABILITY_KEYS: Final[tuple[wire.CapabilityKey, ...]] = (
    wire.CapabilityKey.CHARACTER_VOICE_MATCHING,
    wire.CapabilityKey.NANO_ADVANCED_TUNING,
    wire.CapabilityKey.PRIVATE_VOICE_DELETION,
    wire.CapabilityKey.VOICE_GENERATOR,
)

_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_ShutdownResult = TypeVar("_ShutdownResult")


class NarrationFeatureReadinessError(RuntimeError):
    """Base class for rejected provider transitions."""


class NarrationFeatureReadinessTransitionError(NarrationFeatureReadinessError):
    """Raised when a transition could reopen a stopped provider."""


class NarrationFeatureReadinessStaleUpdate(NarrationFeatureReadinessError):
    """Raised when an asynchronous probe publishes against an old generation."""


@dataclass(frozen=True, slots=True)
class NarrationFeatureDependencies:
    """Strict results supplied by the owners of the underlying dependencies.

    ``schema_ready`` represents the shared schema-readiness sentinel.  The
    provider never compares revision strings or walks the migration graph.
    Sidecar protocol and model identity stay separate so either probe can
    independently revoke advanced tuning.
    """

    schema_ready: bool = False
    voice_generator_schema_ready: bool = False
    character_workspace_ready: bool = False
    novel_agent_ready: bool = False
    official_preset_catalog_ready: bool = False
    official_casting_baseline_ready: bool = False
    official_binding_service_ready: bool = False
    storage_ready: bool = False
    digest_keyring_ready: bool = False
    sidecar_protocol_ready: bool = False
    sidecar_model_fingerprint_ready: bool = False
    nano_experiment_processor_ready: bool = False
    background_scheduler_ready: bool = False
    exact_asset_plan_service_ready: bool = False
    deletion_reconciler_ready: bool = False
    voice_generator_host_protocol_ready: bool = False
    voice_generator_model_identity_ready: bool = False
    voice_generator_codec_identity_ready: bool = False
    voice_generator_heavy_lock_ready: bool = False
    voice_generator_processor_ready: bool = False
    voice_generator_reconciler_ready: bool = False

    def __post_init__(self) -> None:
        for dependency in fields(self):
            if type(getattr(self, dependency.name)) is not bool:
                raise TypeError(f"{dependency.name} must be an exact boolean")

    @classmethod
    def fully_ready(cls) -> "NarrationFeatureDependencies":
        return cls(**{dependency.name: True for dependency in fields(cls)})

    def with_updates(self, **updates: bool) -> "NarrationFeatureDependencies":
        known = {dependency.name for dependency in fields(self)}
        unknown = set(updates) - known
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"unknown readiness dependencies: {names}")
        return replace(self, **updates)


class NarrationFeatureReadinessSnapshot(BaseModel):
    """One immutable provider publication.

    The provider returns a deep copy of this frozen envelope.  Although the
    shared ``FeatureCapability`` DTO predates frozen Pydantic models, callers
    therefore cannot mutate the provider's authoritative nested instances.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["narration-feature-readiness/1"] = (
        FEATURE_READINESS_SCHEMA_VERSION
    )
    lifecycle_status: LifecycleStatus
    generation: int = Field(ge=0)
    capabilities: tuple[wire.FeatureCapability, ...]
    reason_code: str | None = Field(default=None, max_length=96)
    updated_at: datetime

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, value: str | None) -> str | None:
        if value is not None and (
            value not in STABLE_REASON_CODES or _SAFE_REASON.fullmatch(value) is None
        ):
            raise ValueError("reason_code must be a frozen readiness reason")
        return value

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_snapshot_shape(self) -> "NarrationFeatureReadinessSnapshot":
        keys = tuple(item.key for item in self.capabilities)
        if keys != MANAGED_CAPABILITY_KEYS:
            raise ValueError(
                "readiness capabilities must contain every managed key in order"
            )
        enabled = tuple(
            item.state is wire.CapabilityState.ENABLED
            and item.visible
            and item.actionable
            for item in self.capabilities
        )
        if self.lifecycle_status == "ready":
            if not all(enabled) or self.reason_code is not None:
                raise ValueError("ready snapshot requires every capability enabled")
        else:
            if self.reason_code is None:
                raise ValueError("non-ready snapshot requires a stable reason")
            if self.lifecycle_status in {"disabled", "starting", "stopping"} and any(
                enabled
            ):
                raise ValueError(
                    "disabled, starting, and stopping snapshots must fail closed"
                )
        return self

    def item(self, key: wire.CapabilityKey) -> wire.FeatureCapability:
        if key not in MANAGED_CAPABILITY_KEYS:
            raise KeyError(key)
        item = next(item for item in self.capabilities if item.key is key)
        return item.model_copy(deep=True)

    def public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


_DEPENDENCY_MATRIX: Final[
    dict[wire.CapabilityKey, tuple[tuple[str, str], ...]]
] = {
    wire.CapabilityKey.CHARACTER_VOICE_MATCHING: (
        ("schema_ready", TTS_DATABASE_SCHEMA_OUTDATED),
        ("character_workspace_ready", TTS_CHARACTER_WORKSPACE_UNAVAILABLE),
        ("novel_agent_ready", TTS_NOVEL_AGENT_UNAVAILABLE),
        # The frozen C0 contract has no separate catalog/binding reason.  Both
        # are parts of the deterministic matching processor boundary.
        ("official_preset_catalog_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("official_casting_baseline_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("official_binding_service_ready", TTS_PROCESSOR_UNAVAILABLE),
    ),
    wire.CapabilityKey.NANO_ADVANCED_TUNING: (
        ("schema_ready", TTS_DATABASE_SCHEMA_OUTDATED),
        ("storage_ready", TTS_STORAGE_UNAVAILABLE),
        ("digest_keyring_ready", TTS_DIGEST_KEYRING_UNAVAILABLE),
        ("sidecar_protocol_ready", TTS_SIDECAR_UNAVAILABLE),
        ("sidecar_model_fingerprint_ready", TTS_SIDECAR_UNAVAILABLE),
        ("nano_experiment_processor_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("background_scheduler_ready", TTS_PROCESSOR_UNAVAILABLE),
    ),
    wire.CapabilityKey.PRIVATE_VOICE_DELETION: (
        ("schema_ready", TTS_DATABASE_SCHEMA_OUTDATED),
        ("storage_ready", TTS_STORAGE_UNAVAILABLE),
        ("digest_keyring_ready", TTS_DIGEST_KEYRING_UNAVAILABLE),
        ("exact_asset_plan_service_ready", TTS_PROCESSOR_UNAVAILABLE),
        (
            "deletion_reconciler_ready",
            TTS_DELETION_RECONCILER_UNAVAILABLE,
        ),
    ),
    wire.CapabilityKey.VOICE_GENERATOR: (
        ("voice_generator_schema_ready", TTS_DATABASE_SCHEMA_OUTDATED),
        ("character_workspace_ready", TTS_CHARACTER_WORKSPACE_UNAVAILABLE),
        ("novel_agent_ready", TTS_NOVEL_AGENT_UNAVAILABLE),
        ("storage_ready", TTS_STORAGE_UNAVAILABLE),
        ("digest_keyring_ready", TTS_DIGEST_KEYRING_UNAVAILABLE),
        ("sidecar_protocol_ready", TTS_SIDECAR_UNAVAILABLE),
        ("sidecar_model_fingerprint_ready", TTS_SIDECAR_UNAVAILABLE),
        ("nano_experiment_processor_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("background_scheduler_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("exact_asset_plan_service_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("deletion_reconciler_ready", TTS_DELETION_RECONCILER_UNAVAILABLE),
        (
            "voice_generator_host_protocol_ready",
            TTS_VOICE_GENERATOR_HOST_UNAVAILABLE,
        ),
        (
            "voice_generator_model_identity_ready",
            TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
        ),
        (
            "voice_generator_codec_identity_ready",
            TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
        ),
        ("voice_generator_heavy_lock_ready", TTS_PROCESSOR_UNAVAILABLE),
        ("voice_generator_processor_ready", TTS_PROCESSOR_UNAVAILABLE),
        (
            "voice_generator_reconciler_ready",
            TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE,
        ),
    ),
}


def _feature_capability(
    key: wire.CapabilityKey,
    *,
    reason_code: str | None,
    disabled: bool = False,
) -> wire.FeatureCapability:
    enabled = reason_code is None
    return wire.FeatureCapability(
        key=key,
        state=(
            wire.CapabilityState.ENABLED
            if enabled
            else (
                wire.CapabilityState.DISABLED
                if disabled
                else wire.CapabilityState.UNAVAILABLE
            )
        ),
        visible=True,
        actionable=enabled,
        reason_code=reason_code,
        required_gate=None,
    )


def _uniform_capabilities(
    reason_code: str,
    *,
    disabled: bool = False,
) -> tuple[wire.FeatureCapability, ...]:
    return tuple(
        _feature_capability(key, reason_code=reason_code, disabled=disabled)
        for key in MANAGED_CAPABILITY_KEYS
    )


def _capabilities_from_dependencies(
    dependencies: NarrationFeatureDependencies,
) -> tuple[wire.FeatureCapability, ...]:
    result: list[wire.FeatureCapability] = []
    for key in MANAGED_CAPABILITY_KEYS:
        reason = next(
            (
                reason_code
                for dependency_name, reason_code in _DEPENDENCY_MATRIX[key]
                if not getattr(dependencies, dependency_name)
            ),
            None,
        )
        result.append(_feature_capability(key, reason_code=reason))
    return tuple(result)


def _overall_reason(
    capabilities: tuple[wire.FeatureCapability, ...],
) -> str | None:
    return next(
        (item.reason_code for item in capabilities if item.reason_code is not None),
        None,
    )


class NarrationFeatureReadinessProvider:
    """The single atomic control plane for narration feature readiness.

    Lifecycle publications and dependency updates are serialized with one
    process lock.  Slow probes happen outside this class; ``expected_generation``
    prevents their stale results from reopening features after shutdown or a
    newer probe.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._snapshot = NarrationFeatureReadinessSnapshot(
            lifecycle_status="disabled",
            generation=0,
            capabilities=_uniform_capabilities(
                TTS_FEATURE_DISABLED,
                disabled=True,
            ),
            reason_code=TTS_FEATURE_DISABLED,
            updated_at=self._now(),
        )

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("readiness clock must return a timezone-aware datetime")
        return current.astimezone(timezone.utc)

    @staticmethod
    def _clone(
        snapshot: NarrationFeatureReadinessSnapshot,
    ) -> NarrationFeatureReadinessSnapshot:
        return snapshot.model_copy(deep=True)

    @staticmethod
    def _validate_expected_generation(
        expected_generation: int | None,
    ) -> None:
        if expected_generation is not None and (
            type(expected_generation) is not int or expected_generation < 0
        ):
            raise TypeError("expected_generation must be a non-negative exact integer")

    def _require_current_generation_locked(
        self,
        expected_generation: int | None,
    ) -> None:
        self._validate_expected_generation(expected_generation)
        if (
            expected_generation is not None
            and expected_generation != self._snapshot.generation
        ):
            raise NarrationFeatureReadinessStaleUpdate(
                "readiness update targets a stale generation"
            )

    def _publish_locked(
        self,
        *,
        lifecycle_status: LifecycleStatus,
        capabilities: tuple[wire.FeatureCapability, ...],
        reason_code: str | None,
    ) -> NarrationFeatureReadinessSnapshot:
        published = NarrationFeatureReadinessSnapshot(
            lifecycle_status=lifecycle_status,
            generation=self._snapshot.generation + 1,
            capabilities=capabilities,
            reason_code=reason_code,
            updated_at=self._now(),
        )
        # One pointer replacement is the atomic publication boundary.
        self._snapshot = published
        return self._clone(published)

    def snapshot(self) -> NarrationFeatureReadinessSnapshot:
        with self._lock:
            return self._clone(self._snapshot)

    def begin_startup(self) -> NarrationFeatureReadinessSnapshot:
        """Revoke all features before any startup probe or task creation."""

        with self._lock:
            if self._snapshot.lifecycle_status == "stopping":
                raise NarrationFeatureReadinessTransitionError(
                    "cannot start while readiness is stopping"
                )
            return self._publish_locked(
                lifecycle_status="starting",
                capabilities=_uniform_capabilities(TTS_FEATURE_STARTING),
                reason_code=TTS_FEATURE_STARTING,
            )

    def publish_dependencies(
        self,
        dependencies: NarrationFeatureDependencies,
        *,
        expected_generation: int | None = None,
    ) -> NarrationFeatureReadinessSnapshot:
        """Atomically replace all managed decisions from one probe result."""

        if not isinstance(dependencies, NarrationFeatureDependencies):
            raise TypeError("dependencies must be NarrationFeatureDependencies")
        with self._lock:
            self._require_current_generation_locked(expected_generation)
            if self._snapshot.lifecycle_status not in {
                "starting",
                "ready",
                "degraded",
            }:
                raise NarrationFeatureReadinessTransitionError(
                    "dependencies cannot reopen disabled or stopping readiness"
                )
            capabilities = _capabilities_from_dependencies(dependencies)
            reason_code = _overall_reason(capabilities)
            return self._publish_locked(
                lifecycle_status="ready" if reason_code is None else "degraded",
                capabilities=capabilities,
                reason_code=reason_code,
            )

    def mark_crashed(
        self,
        capabilities: Iterable[wire.CapabilityKey] | None = None,
        *,
        expected_generation: int | None = None,
    ) -> NarrationFeatureReadinessSnapshot:
        """Synchronously revoke affected features before crash cleanup runs."""

        affected = (
            frozenset(MANAGED_CAPABILITY_KEYS)
            if capabilities is None
            else frozenset(capabilities)
        )
        if (
            not affected
            or any(type(key) is not wire.CapabilityKey for key in affected)
            or not affected.issubset(MANAGED_CAPABILITY_KEYS)
        ):
            raise ValueError("crash capabilities must be non-empty managed keys")
        with self._lock:
            self._require_current_generation_locked(expected_generation)
            if self._snapshot.lifecycle_status not in {
                "starting",
                "ready",
                "degraded",
            }:
                raise NarrationFeatureReadinessTransitionError(
                    "a crash cannot reopen disabled or stopping readiness"
                )
            current = {item.key: item for item in self._snapshot.capabilities}
            revoked = tuple(
                _feature_capability(key, reason_code=TTS_FEATURE_CRASHED)
                if key in affected
                else current[key].model_copy(deep=True)
                for key in MANAGED_CAPABILITY_KEYS
            )
            return self._publish_locked(
                lifecycle_status="degraded",
                capabilities=revoked,
                reason_code=TTS_FEATURE_CRASHED,
            )

    def begin_shutdown(self) -> NarrationFeatureReadinessSnapshot:
        """Publish a fail-closed snapshot before any component is stopped."""

        with self._lock:
            return self._publish_locked(
                lifecycle_status="stopping",
                capabilities=_uniform_capabilities(TTS_FEATURE_STOPPING),
                reason_code=TTS_FEATURE_STOPPING,
            )

    def finish_shutdown(
        self,
        *,
        expected_generation: int | None = None,
    ) -> NarrationFeatureReadinessSnapshot:
        """Publish the stable disabled state after component shutdown finishes."""

        with self._lock:
            self._require_current_generation_locked(expected_generation)
            if self._snapshot.lifecycle_status != "stopping":
                raise NarrationFeatureReadinessTransitionError(
                    "shutdown can finish only after readiness is stopping"
                )
            return self._publish_locked(
                lifecycle_status="disabled",
                capabilities=_uniform_capabilities(
                    TTS_FEATURE_DISABLED,
                    disabled=True,
                ),
                reason_code=TTS_FEATURE_DISABLED,
            )

    async def revoke_then_stop(
        self,
        stop_components: Callable[[], Awaitable[_ShutdownResult]],
    ) -> _ShutdownResult:
        """Enforce revocation-before-stop for an injected async teardown."""

        if not callable(stop_components):
            raise TypeError("stop_components must be callable")
        stopping = self.begin_shutdown()
        try:
            result = await stop_components()
        except BaseException:
            with self._lock:
                if (
                    self._snapshot.lifecycle_status == "stopping"
                    and self._snapshot.generation == stopping.generation
                ):
                    self._publish_locked(
                        lifecycle_status="stopping",
                        capabilities=_uniform_capabilities(TTS_FEATURE_CRASHED),
                        reason_code=TTS_FEATURE_CRASHED,
                    )
            raise
        self.finish_shutdown(expected_generation=stopping.generation)
        return result


# Production integration imports this exact process-local instance.  Tests and
# isolated runtimes may construct explicitly injected providers without changing
# the application authority.
NARRATION_FEATURE_READINESS_PROVIDER: Final = NarrationFeatureReadinessProvider()


__all__ = [
    "FEATURE_READINESS_SCHEMA_VERSION",
    "MANAGED_CAPABILITY_KEYS",
    "NARRATION_FEATURE_READINESS_PROVIDER",
    "NarrationFeatureDependencies",
    "NarrationFeatureReadinessError",
    "NarrationFeatureReadinessProvider",
    "NarrationFeatureReadinessSnapshot",
    "NarrationFeatureReadinessStaleUpdate",
    "NarrationFeatureReadinessTransitionError",
    "STABLE_REASON_CODES",
    "TTS_CHARACTER_WORKSPACE_UNAVAILABLE",
    "TTS_DATABASE_SCHEMA_OUTDATED",
    "TTS_DELETION_RECONCILER_UNAVAILABLE",
    "TTS_DIGEST_KEYRING_UNAVAILABLE",
    "TTS_FEATURE_CRASHED",
    "TTS_FEATURE_DISABLED",
    "TTS_FEATURE_STARTING",
    "TTS_FEATURE_STOPPING",
    "TTS_NOVEL_AGENT_UNAVAILABLE",
    "TTS_PROCESSOR_UNAVAILABLE",
    "TTS_SIDECAR_UNAVAILABLE",
    "TTS_STORAGE_UNAVAILABLE",
]
