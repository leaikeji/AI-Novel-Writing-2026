from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event

import pytest

from backend.narration import schemas as wire
from backend.narration.feature_readiness import (
    FEATURE_READINESS_SCHEMA_VERSION,
    MANAGED_CAPABILITY_KEYS,
    NarrationFeatureDependencies,
    NarrationFeatureReadinessProvider,
    NarrationFeatureReadinessSnapshot,
    NarrationFeatureReadinessStaleUpdate,
    NarrationFeatureReadinessTransitionError,
    TTS_CHARACTER_WORKSPACE_UNAVAILABLE,
    TTS_DATABASE_SCHEMA_OUTDATED,
    TTS_DELETION_RECONCILER_UNAVAILABLE,
    TTS_DIGEST_KEYRING_UNAVAILABLE,
    TTS_FEATURE_CRASHED,
    TTS_FEATURE_DISABLED,
    TTS_FEATURE_STARTING,
    TTS_FEATURE_STOPPING,
    TTS_NOVEL_AGENT_UNAVAILABLE,
    TTS_PROCESSOR_UNAVAILABLE,
    TTS_SIDECAR_UNAVAILABLE,
    TTS_STORAGE_UNAVAILABLE,
    TTS_VOICE_GENERATOR_HOST_UNAVAILABLE,
    TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
    TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE,
)


ALL_FEATURES = frozenset(MANAGED_CAPABILITY_KEYS)
CHARACTER_MATCHING = wire.CapabilityKey.CHARACTER_VOICE_MATCHING
ADVANCED_TUNING = wire.CapabilityKey.NANO_ADVANCED_TUNING
PRIVATE_DELETION = wire.CapabilityKey.PRIVATE_VOICE_DELETION
VOICE_GENERATOR = wire.CapabilityKey.VOICE_GENERATOR


def _assert_all_unavailable(
    snapshot: NarrationFeatureReadinessSnapshot,
    reason_code: str,
) -> None:
    assert tuple(item.key for item in snapshot.capabilities) == MANAGED_CAPABILITY_KEYS
    assert all(item.actionable is False for item in snapshot.capabilities)
    assert all(item.visible is True for item in snapshot.capabilities)
    assert all(item.reason_code == reason_code for item in snapshot.capabilities)


def test_initial_and_starting_snapshots_are_strict_fail_closed_copies() -> None:
    provider = NarrationFeatureReadinessProvider(
        clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    )

    initial = provider.snapshot()
    assert initial.schema_version == FEATURE_READINESS_SCHEMA_VERSION
    assert initial.lifecycle_status == "disabled"
    assert initial.generation == 0
    assert initial.reason_code == TTS_FEATURE_DISABLED
    assert initial.updated_at == datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    assert all(
        item.state is wire.CapabilityState.DISABLED
        for item in initial.capabilities
    )
    _assert_all_unavailable(initial, TTS_FEATURE_DISABLED)

    starting = provider.begin_startup()
    assert starting.lifecycle_status == "starting"
    assert starting.generation == 1
    assert starting.reason_code == TTS_FEATURE_STARTING
    assert all(
        item.state is wire.CapabilityState.UNAVAILABLE
        for item in starting.capabilities
    )
    _assert_all_unavailable(starting, TTS_FEATURE_STARTING)

    # Shared FeatureCapability is mutable, so the provider must never expose its
    # authoritative nested objects to overview, routes, or health consumers.
    starting.capabilities[0].reason_code = TTS_FEATURE_CRASHED
    assert provider.snapshot().capabilities[0].reason_code == TTS_FEATURE_STARTING
    assert initial.lifecycle_status == "disabled"
    assert initial.generation == 0

    public = provider.snapshot().public_dict()
    assert public["schema_version"] == "narration-feature-readiness/1"
    assert public["lifecycle_status"] == "starting"
    assert public["generation"] == 1
    assert public["capabilities"][0]["key"] == "character_voice_matching"
    assert public["updated_at"] == "2026-08-29T12:00:00Z"


@pytest.mark.parametrize(
    ("missing_dependency", "affected", "reason_code"),
    (
        (
            "schema_ready",
            frozenset({CHARACTER_MATCHING, ADVANCED_TUNING, PRIVATE_DELETION}),
            TTS_DATABASE_SCHEMA_OUTDATED,
        ),
        (
            "voice_generator_schema_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_DATABASE_SCHEMA_OUTDATED,
        ),
        (
            "character_workspace_ready",
            frozenset({CHARACTER_MATCHING, VOICE_GENERATOR}),
            TTS_CHARACTER_WORKSPACE_UNAVAILABLE,
        ),
        (
            "novel_agent_ready",
            frozenset({CHARACTER_MATCHING, VOICE_GENERATOR}),
            TTS_NOVEL_AGENT_UNAVAILABLE,
        ),
        (
            "official_preset_catalog_ready",
            frozenset({CHARACTER_MATCHING}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "official_casting_baseline_ready",
            frozenset({CHARACTER_MATCHING}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "official_binding_service_ready",
            frozenset({CHARACTER_MATCHING}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "storage_ready",
            frozenset({ADVANCED_TUNING, PRIVATE_DELETION, VOICE_GENERATOR}),
            TTS_STORAGE_UNAVAILABLE,
        ),
        (
            "digest_keyring_ready",
            frozenset({ADVANCED_TUNING, PRIVATE_DELETION, VOICE_GENERATOR}),
            TTS_DIGEST_KEYRING_UNAVAILABLE,
        ),
        (
            "sidecar_protocol_ready",
            frozenset({ADVANCED_TUNING, VOICE_GENERATOR}),
            TTS_SIDECAR_UNAVAILABLE,
        ),
        (
            "sidecar_model_fingerprint_ready",
            frozenset({ADVANCED_TUNING, VOICE_GENERATOR}),
            TTS_SIDECAR_UNAVAILABLE,
        ),
        (
            "nano_experiment_processor_ready",
            frozenset({ADVANCED_TUNING, VOICE_GENERATOR}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "background_scheduler_ready",
            frozenset({ADVANCED_TUNING, VOICE_GENERATOR}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "exact_asset_plan_service_ready",
            frozenset({PRIVATE_DELETION, VOICE_GENERATOR}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "deletion_reconciler_ready",
            frozenset({PRIVATE_DELETION, VOICE_GENERATOR}),
            TTS_DELETION_RECONCILER_UNAVAILABLE,
        ),
        (
            "voice_generator_host_protocol_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_VOICE_GENERATOR_HOST_UNAVAILABLE,
        ),
        (
            "voice_generator_model_identity_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
        ),
        (
            "voice_generator_codec_identity_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_VOICE_GENERATOR_IDENTITY_MISMATCH,
        ),
        (
            "voice_generator_heavy_lock_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "voice_generator_processor_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_PROCESSOR_UNAVAILABLE,
        ),
        (
            "voice_generator_reconciler_ready",
            frozenset({VOICE_GENERATOR}),
            TTS_VOICE_GENERATOR_RECONCILER_UNAVAILABLE,
        ),
    ),
)
def test_each_dependency_revokes_exactly_its_capabilities(
    missing_dependency: str,
    affected: frozenset[wire.CapabilityKey],
    reason_code: str,
) -> None:
    provider = NarrationFeatureReadinessProvider()
    starting = provider.begin_startup()
    dependencies = NarrationFeatureDependencies.fully_ready().with_updates(
        **{missing_dependency: False}
    )

    snapshot = provider.publish_dependencies(
        dependencies,
        expected_generation=starting.generation,
    )

    assert snapshot.lifecycle_status == "degraded"
    assert snapshot.reason_code == reason_code
    for item in snapshot.capabilities:
        if item.key in affected:
            assert item.state is wire.CapabilityState.UNAVAILABLE
            assert item.visible is True
            assert item.actionable is False
            assert item.reason_code == reason_code
        else:
            assert item.state is wire.CapabilityState.ENABLED
            assert item.visible is True
            assert item.actionable is True
            assert item.reason_code is None


def test_all_dependencies_ready_enables_exactly_the_four_frozen_features() -> None:
    provider = NarrationFeatureReadinessProvider()
    starting = provider.begin_startup()

    ready = provider.publish_dependencies(
        NarrationFeatureDependencies.fully_ready(),
        expected_generation=starting.generation,
    )

    assert ready.lifecycle_status == "ready"
    assert ready.reason_code is None
    assert tuple(item.key for item in ready.capabilities) == MANAGED_CAPABILITY_KEYS
    assert all(
        item.state is wire.CapabilityState.ENABLED
        for item in ready.capabilities
    )
    assert all(item.visible and item.actionable for item in ready.capabilities)
    assert ready.item(ADVANCED_TUNING).key is ADVANCED_TUNING
    assert ready.item(VOICE_GENERATOR).key is VOICE_GENERATOR


def test_dependencies_are_exact_typed_and_reject_unknown_updates() -> None:
    with pytest.raises(TypeError, match="schema_ready"):
        NarrationFeatureDependencies(schema_ready=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unknown readiness dependencies"):
        NarrationFeatureDependencies().with_updates(unknown_ready=True)

    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    with pytest.raises(TypeError, match="NarrationFeatureDependencies"):
        provider.publish_dependencies({"schema_ready": True})  # type: ignore[arg-type]


def test_dependency_publications_are_atomic_under_concurrent_readers() -> None:
    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    release = Event()

    ready_pattern = (
        "ready",
        ("enabled", "enabled", "enabled", "enabled"),
        (None, None, None, None),
    )
    schema_down_pattern = (
        "degraded",
        ("unavailable", "unavailable", "unavailable", "enabled"),
        (
            TTS_DATABASE_SCHEMA_OUTDATED,
            TTS_DATABASE_SCHEMA_OUTDATED,
            TTS_DATABASE_SCHEMA_OUTDATED,
            None,
        ),
    )

    def writer() -> None:
        release.wait()
        ready = NarrationFeatureDependencies.fully_ready()
        for index in range(300):
            provider.publish_dependencies(
                ready if index % 2 else ready.with_updates(schema_ready=False)
            )

    def reader() -> tuple[list[tuple[object, ...]], list[int]]:
        release.wait()
        patterns: list[tuple[object, ...]] = []
        generations: list[int] = []
        for _index in range(300):
            snapshot = provider.snapshot()
            patterns.append(
                (
                    snapshot.lifecycle_status,
                    tuple(item.state.value for item in snapshot.capabilities),
                    tuple(item.reason_code for item in snapshot.capabilities),
                )
            )
            generations.append(snapshot.generation)
        return patterns, generations

    with ThreadPoolExecutor(max_workers=7) as executor:
        writer_future = executor.submit(writer)
        reader_futures = [executor.submit(reader) for _index in range(6)]
        release.set()
        writer_future.result()
        results = [future.result() for future in reader_futures]

    for patterns, generations in results:
        assert set(patterns).issubset({ready_pattern, schema_down_pattern})
        assert generations == sorted(generations)


def test_crash_revokes_only_affected_feature_and_explicit_probe_can_recover() -> None:
    provider = NarrationFeatureReadinessProvider()
    start = provider.begin_startup()
    ready = provider.publish_dependencies(
        NarrationFeatureDependencies.fully_ready(),
        expected_generation=start.generation,
    )

    crashed = provider.mark_crashed(
        [ADVANCED_TUNING],
        expected_generation=ready.generation,
    )

    assert crashed.lifecycle_status == "degraded"
    assert crashed.reason_code == TTS_FEATURE_CRASHED
    assert crashed.item(ADVANCED_TUNING).state is wire.CapabilityState.UNAVAILABLE
    assert crashed.item(ADVANCED_TUNING).reason_code == TTS_FEATURE_CRASHED
    assert crashed.item(CHARACTER_MATCHING).state is wire.CapabilityState.ENABLED
    assert crashed.item(PRIVATE_DELETION).state is wire.CapabilityState.ENABLED

    recovered = provider.publish_dependencies(
        NarrationFeatureDependencies.fully_ready(),
        expected_generation=crashed.generation,
    )
    assert recovered.lifecycle_status == "ready"
    assert recovered.reason_code is None

    all_crashed = provider.mark_crashed(expected_generation=recovered.generation)
    assert all_crashed.lifecycle_status == "degraded"
    _assert_all_unavailable(all_crashed, TTS_FEATURE_CRASHED)


def test_generation_is_strictly_increasing_for_every_accepted_publication() -> None:
    provider = NarrationFeatureReadinessProvider()
    snapshots = [provider.snapshot()]
    snapshots.append(provider.begin_startup())
    snapshots.append(
        provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    )
    snapshots.append(
        provider.publish_dependencies(
            NarrationFeatureDependencies.fully_ready().with_updates(
                deletion_reconciler_ready=False
            )
        )
    )
    snapshots.append(provider.mark_crashed([CHARACTER_MATCHING]))
    snapshots.append(provider.begin_shutdown())
    snapshots.append(
        provider.finish_shutdown(
            expected_generation=snapshots[-1].generation,
        )
    )

    generations = [snapshot.generation for snapshot in snapshots]
    assert generations == list(range(len(snapshots)))


def test_stale_or_late_probe_cannot_reopen_shutdown() -> None:
    provider = NarrationFeatureReadinessProvider()
    starting = provider.begin_startup()
    stopping = provider.begin_shutdown()

    with pytest.raises(NarrationFeatureReadinessStaleUpdate):
        provider.publish_dependencies(
            NarrationFeatureDependencies.fully_ready(),
            expected_generation=starting.generation,
        )
    with pytest.raises(NarrationFeatureReadinessTransitionError):
        provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())

    unchanged = provider.snapshot()
    assert unchanged.generation == stopping.generation
    assert unchanged.lifecycle_status == "stopping"
    _assert_all_unavailable(unchanged, TTS_FEATURE_STOPPING)


@pytest.mark.asyncio
async def test_revoke_then_stop_publishes_stopping_before_injected_teardown() -> None:
    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    ready = provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    observed: list[tuple[str, int]] = []

    async def stop_components() -> str:
        snapshot = provider.snapshot()
        observed.append((snapshot.lifecycle_status, snapshot.generation))
        _assert_all_unavailable(snapshot, TTS_FEATURE_STOPPING)
        return "stopped"

    result = await provider.revoke_then_stop(stop_components)

    disabled = provider.snapshot()
    assert result == "stopped"
    assert observed == [("stopping", ready.generation + 1)]
    assert disabled.lifecycle_status == "disabled"
    assert disabled.generation == ready.generation + 2
    _assert_all_unavailable(disabled, TTS_FEATURE_DISABLED)


@pytest.mark.asyncio
async def test_shutdown_failure_remains_revoked_and_reports_crash() -> None:
    provider = NarrationFeatureReadinessProvider()
    provider.begin_startup()
    ready = provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())

    async def fail_to_stop() -> None:
        _assert_all_unavailable(provider.snapshot(), TTS_FEATURE_STOPPING)
        raise RuntimeError("worker did not stop")

    with pytest.raises(RuntimeError, match="worker did not stop"):
        await provider.revoke_then_stop(fail_to_stop)

    failed = provider.snapshot()
    assert failed.lifecycle_status == "stopping"
    assert failed.generation == ready.generation + 2
    assert failed.reason_code == TTS_FEATURE_CRASHED
    _assert_all_unavailable(failed, TTS_FEATURE_CRASHED)
    with pytest.raises(NarrationFeatureReadinessTransitionError):
        provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())


def test_illegal_transitions_and_generation_types_fail_without_publication() -> None:
    provider = NarrationFeatureReadinessProvider()
    initial = provider.snapshot()

    with pytest.raises(NarrationFeatureReadinessTransitionError):
        provider.publish_dependencies(NarrationFeatureDependencies.fully_ready())
    with pytest.raises(NarrationFeatureReadinessTransitionError):
        provider.finish_shutdown()
    with pytest.raises(TypeError, match="expected_generation"):
        provider.mark_crashed(expected_generation=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="managed keys"):
        provider.mark_crashed([wire.CapabilityKey.NARRATION_PRODUCT])
    with pytest.raises(ValueError, match="managed keys"):
        provider.mark_crashed(["nano_advanced_tuning"])  # type: ignore[list-item]

    assert provider.snapshot() == initial


def test_clock_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NarrationFeatureReadinessProvider(
            clock=lambda: datetime(2026, 8, 29, 12, 0)
        )
