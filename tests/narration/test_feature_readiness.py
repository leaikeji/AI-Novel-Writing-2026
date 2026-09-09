from __future__ import annotations

import asyncio

import pytest

from backend.narration import schemas as wire
from backend.narration.feature_readiness import (
    MANAGED_CAPABILITY_KEYS,
    NarrationFeatureDependencies,
    NarrationFeatureReadinessProvider,
    NarrationFeatureReadinessStaleUpdate,
    NarrationFeatureReadinessTransitionError,
    TTS_DATABASE_SCHEMA_OUTDATED,
    TTS_FEATURE_CRASHED,
)


PRIVATE_DELETION = wire.CapabilityKey.PRIVATE_VOICE_DELETION


def test_readiness_only_manages_retained_private_voice_deletion() -> None:
    assert MANAGED_CAPABILITY_KEYS == (PRIVATE_DELETION,)
    provider = NarrationFeatureReadinessProvider()

    disabled = provider.snapshot()
    assert disabled.lifecycle_status == "disabled"
    assert disabled.item(PRIVATE_DELETION).state is wire.CapabilityState.DISABLED

    starting = provider.begin_startup()
    degraded = provider.publish_dependencies(
        NarrationFeatureDependencies(),
        expected_generation=starting.generation,
    )
    assert degraded.lifecycle_status == "degraded"
    assert degraded.reason_code == TTS_DATABASE_SCHEMA_OUTDATED

    ready = provider.publish_dependencies(
        NarrationFeatureDependencies.fully_ready(),
        expected_generation=degraded.generation,
    )
    assert ready.lifecycle_status == "ready"
    assert ready.item(PRIVATE_DELETION).actionable is True


def test_crash_and_shutdown_revoke_before_cleanup() -> None:
    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    ready = provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())

    crashed = provider.mark_crashed(
        [PRIVATE_DELETION],
        expected_generation=ready.generation,
    )
    assert crashed.lifecycle_status == "degraded"
    assert crashed.item(PRIVATE_DELETION).reason_code == TTS_FEATURE_CRASHED

    stopping = provider.begin_shutdown()
    stopped = provider.finish_shutdown(expected_generation=stopping.generation)
    assert stopped.lifecycle_status == "disabled"


def test_stale_and_invalid_transitions_fail_closed() -> None:
    provider = NarrationFeatureReadinessProvider()
    starting = provider.begin_startup()
    provider.publish_dependencies(
        NarrationFeatureDependencies.fully_ready(),
        expected_generation=starting.generation,
    )

    with pytest.raises(NarrationFeatureReadinessStaleUpdate):
        provider.publish_dependencies(
            NarrationFeatureDependencies.fully_ready(),
            expected_generation=starting.generation,
        )

    stopping = provider.begin_shutdown()
    with pytest.raises(NarrationFeatureReadinessTransitionError):
        provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    provider.finish_shutdown(expected_generation=stopping.generation)


def test_dependency_shape_is_strict() -> None:
    with pytest.raises(TypeError):
        NarrationFeatureDependencies(schema_ready=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        NarrationFeatureDependencies().with_updates(legacy_mode_ready=True)


def test_revoke_then_stop_orders_revocation_before_async_cleanup() -> None:
    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    observed: list[str] = []

    async def stop_components() -> str:
        observed.append(provider.snapshot().lifecycle_status)
        await asyncio.sleep(0)
        return "stopped"

    assert asyncio.run(provider.revoke_then_stop(stop_components)) == "stopped"
    assert observed == ["stopping"]
    assert provider.snapshot().lifecycle_status == "disabled"
