from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.models import (
    BackgroundJob, BackgroundJobAttempt, MediaAsset, ModelRunRecord, Novel,
    NovelCharacter, VoiceDesignDraft, VoiceGeneratorCommand, VoiceGeneratorRunEvidence,
    VoiceProfile, VoiceProfileVersion, VoiceRightsEvent, VoiceRightsRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID, NanoDecodeParametersV2
from backend.narration.nano_experiments import production_nano_experiment_identity
from backend.narration.services import NarrationServiceError, SqlAlchemyNarrationStore, canonical_sha256
from backend.narration.voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS, EXPECTED_RUNTIME_FINGERPRINT, EXPECTED_RUNTIME_IDENTITY,
    HOST_PROTOCOL_VERSION, RUNTIME_TOPOLOGY,
)
from backend.narration.voice_version_media import resolve_voice_version_media
from backend.narration.voices import voice_profile_resource


NOW = datetime(2026, 9, 3, 8, tzinfo=UTC)
SCOPE = {"owner_id": LOCAL_OWNER_ID, "workspace_id": LOCAL_WORKSPACE_ID}


class MemoryStore:
    """Read-only lookup port; any accidental row lock or write fails the test."""

    def __init__(self, rows):
        self.rows = {(type(row), row.id): row for row in rows}

    def get(self, model, row_id, *, for_update=False):
        assert not for_update
        return self.rows.get((model, row_id))

    def find_all(self, model, *, order_by=(), for_update=False, **filters):
        assert not for_update
        rows = [row for (kind, _), row in self.rows.items() if kind is model
                and all(getattr(row, key) == value for key, value in filters.items())]
        return sorted(rows, key=lambda row: tuple(getattr(row, key) for key in order_by))

    def find_one(self, model, *, for_update=False, **filters):
        return next(iter(self.find_all(model, for_update=for_update, **filters)), None)

    def add(self, row):
        raise AssertionError("media authorization must not write")

    def flush(self):
        raise AssertionError("media authorization must not flush")

    def consume_render_publication_context(self, **kwargs):
        raise AssertionError("media authorization must not publish")


def _asset(novel_id, *, reference, command_id):
    identity = uuid4()
    digest = ("a" if reference else "b") * 64
    nano = production_nano_experiment_identity()
    return MediaAsset(
        id=identity, **SCOPE, novel_id=novel_id,
        kind="narration_voice_reference" if reference else "narration_voice_preview",
        asset_class="voice_reference" if reference else "preview", state="ready",
        retention_policy="private_voice_source" if reference else "private_voice_validation",
        storage_backend="local", storage_path=f"assets/{identity.hex[:2]}/{identity.hex}/{digest}.wav",
        mime_type="audio/wav", content_hash=digest, checksum_algorithm="sha256",
        byte_size=288044, duration_ms=3000, sample_rate=48000, channels=2,
        verified_at=NOW, expires_at=None,
        validation_json=(
            {"schema_version": "voice-generator-audio-validation/1", "metrics": {}}
            if reference else {"schema_version": "voice-generator-nano-validation/1",
                               "reference_sha256": "a" * 64, "model_fingerprint": nano.model_fingerprint_sha256}
        ),
        metadata_json=(
            {"schema_version": "voice-generator-reference/1", "command_id": str(command_id),
             "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT}
            if reference else {"schema_version": "voice-generator-validation/1", "command_id": str(command_id)}
        ),
    )


@pytest.fixture
def graph():
    """The publication shape mirrors VoiceGeneratorRepository.publish_success.

    No VoicePreview or character binding is present: neither is the authority
    for a completed dedicated voice's stored Nano validation output.
    """
    novel = Novel(id=uuid4(), **SCOPE)
    scope = {**SCOPE, "novel_id": novel.id}
    character = NovelCharacter(id=uuid4(), novel_id=novel.id)
    command_id = uuid4()
    reference = _asset(novel.id, reference=True, command_id=command_id)
    asset = _asset(novel.id, reference=False, command_id=command_id)
    draft = VoiceDesignDraft(
        id=uuid4(), **scope, character_id=character.id, fingerprint="c" * 64,
        runtime_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        parameters_json=EXPECTED_AUDIO_PARAMETERS.wire_payload(),
        parameters_digest=canonical_sha256(EXPECTED_AUDIO_PARAMETERS.wire_payload()),
        instruction_digest_key_id="tts-test", instruction_digest="e" * 64,
        language="zh-CN", seed=104729,
    )
    job = BackgroundJob(id=uuid4(), **scope, job_kind="narration.voice_generate",
                        state="succeeded", resource_class="moss-nano", input_hash=draft.fingerprint)
    attempt = BackgroundJobAttempt(id=uuid4(), job_id=job.id, attempt_number=1,
                                   completed_at=NOW, error_classification=None, error_code=None)
    generator = ModelRunRecord(
        id=uuid4(), attempt_id=attempt.id, requested_provider_id="local-native-host",
        actual_provider_id="local-native-host", requested_model_id="OpenMOSS-Team/MOSS-VoiceGenerator",
        actual_model_id="OpenMOSS-Team/MOSS-VoiceGenerator",
        requested_revision=EXPECTED_RUNTIME_IDENTITY.voice_generator_revision,
        actual_revision=EXPECTED_RUNTIME_IDENTITY.voice_generator_revision,
        model_fingerprint=EXPECTED_RUNTIME_FINGERPRINT, parameters_digest=draft.parameters_digest,
        input_digest_key_id=draft.instruction_digest_key_id, input_digest=draft.instruction_digest,
        output_digest=reference.content_hash, duration_ms=3000, result_classification="success",
    )
    identity = production_nano_experiment_identity()
    nano = ModelRunRecord(
        id=uuid4(), attempt_id=attempt.id, requested_provider_id=identity.requested_provider_id,
        actual_provider_id=identity.actual_provider_id, requested_model_id=identity.requested_model_id,
        actual_model_id=identity.actual_model_id, requested_revision=identity.requested_revision,
        actual_revision=identity.actual_revision, model_fingerprint=identity.model_fingerprint_sha256,
        parameters_digest=canonical_sha256({
            "schema_version": "voice-generator-nano-validation-parameters/1",
            "seed": draft.seed, "sample_mode": "full", "max_new_frames": 375,
            "decode_parameters": dict(NanoDecodeParametersV2().wire_payload()),
            "reference_sha256": reference.content_hash,
        }), input_digest_key_id="tts-test", input_digest="1" * 64,
        output_digest=asset.content_hash, duration_ms=3000, result_classification="success",
    )
    rights = VoiceRightsRecord(
        id=uuid4(), **scope, source_kind="voice_generator", purpose="private_novel_narration",
        source_identifier=f"local://voice-generator/{command_id}", notice_version="voice-generator-private-use/1",
        commercial_use=False, redistribution=False, voice_cloning=False, subject_consent_reference=None,
        confirmed_actor="local-owner", confirmed_at=NOW, expires_at=None, risk_flags_json=[],
    )
    event = VoiceRightsEvent(id=uuid4(), rights_record_id=rights.id, event_type="confirmed",
                             event_key="confirmed", actor="local-owner", occurred_at=NOW)
    profile = VoiceProfile(id=uuid4(), **scope, name="沈砚 · 专属音色", status="active", version=1,
                           created_at=NOW, updated_at=NOW)
    version = VoiceProfileVersion(
        id=uuid4(), **SCOPE, profile_id=profile.id, version_number=1, source_type="generated", state="locked",
        activation_basis="character_one_click_generation", validation_basis="machine_validated",
        quality_state="accepted", provider_id="local-native-host", model_id=generator.actual_model_id,
        model_revision=generator.actual_revision, preset_key=None, model_run_id=nano.id,
        reference_asset_id=reference.id, preview_asset_id=asset.id, rights_record_id=rights.id,
        description_digest_key_id=draft.instruction_digest_key_id, description_digest=draft.instruction_digest,
        language=draft.language, seed=draft.seed, locked_actor=None, locked_at=None, created_at=NOW,
        parameters_json={"schema_version": "voice-generator-version/1", "draft_fingerprint": draft.fingerprint,
                         "runtime_identity": draft.runtime_identity_json, "generator_parameters": draft.parameters_json,
                         "nano_parameters_digest": nano.parameters_digest},
        fingerprint=canonical_sha256({
            "schema_version": "voice-generator-version/1", "draft_fingerprint": draft.fingerprint,
            "generator_audio_sha256": reference.content_hash, "nano_audio_sha256": asset.content_hash,
            "generator_model_run_id": str(generator.id), "nano_model_run_id": str(nano.id),
            "runtime_fingerprint": EXPECTED_RUNTIME_FINGERPRINT, "nano_model_fingerprint": identity.model_fingerprint_sha256,
        }),
    )
    profile.current_version_id = version.id
    command = VoiceGeneratorCommand(
        id=command_id, **scope, character_id=character.id, state="ready_applied", completed_at=NOW,
        failure_code=None, draft_id=draft.id, background_job_id=job.id,
        generated_reference_asset_id=reference.id, nano_validation_asset_id=asset.id,
        generator_model_run_id=generator.id, nano_model_run_id=nano.id,
        voice_profile_id=profile.id, voice_version_id=version.id,
    )
    attempt.actual_result_digest = canonical_sha256({
        "schema_version": "voice-generator-result/1", "command_id": str(command.id),
        "voice_version_id": str(version.id), "generator_audio_sha256": reference.content_hash,
        "nano_audio_sha256": asset.content_hash,
    })
    evidence = VoiceGeneratorRunEvidence(
        id=uuid4(), command_id=command.id, model_run_id=generator.id, attempt_number=1,
        request_digest="2" * 64, protocol_version=HOST_PROTOCOL_VERSION, topology=RUNTIME_TOPOLOGY,
        runtime_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
        requested_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        actual_identity_json=EXPECTED_RUNTIME_IDENTITY.wire_payload(),
        instruction_digest=draft.instruction_digest, token_digest="3" * 64,
        audio_digest=reference.content_hash, result_classification="success", exit_reason_code="COMPLETED",
        started_at=NOW - timedelta(seconds=60), completed_at=NOW,
    )
    values = dict(novel=novel, character=character, reference=reference, asset=asset, draft=draft,
                  job=job, attempt=attempt, generator=generator, nano=nano, rights=rights, event=event,
                  profile=profile, version=version, command=command, evidence=evidence)
    return SimpleNamespace(store=MemoryStore(values.values()), **values)


@pytest.mark.parametrize("state", ["ready_applied", "ready_unapplied"])
def test_completed_generated_voice_resolves_without_binding_or_preview(graph, state):
    graph.command.state = state
    assert resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW) is graph.asset


@pytest.mark.parametrize("row,field,value", [
    ("profile", "status", "unavailable"), ("profile", "status", "archived"),
    ("version", "state", "deleted"), ("version", "source_type", "uploaded"),
    ("version", "activation_basis", "generic_voice_pack_generation"),
    ("version", "activation_basis", "experimental_machine_validated"),
    ("version", "quality_state", "pending"), ("version", "model_revision", "other"),
    ("command", "state", "failed"), ("command", "completed_at", None),
    ("command", "nano_validation_asset_id", uuid4()), ("command", "generator_model_run_id", uuid4()),
    ("job", "state", "running"), ("job", "job_kind", "narration.render"),
    ("job", "input_hash", "0" * 64), ("attempt", "completed_at", None),
    ("attempt", "job_id", uuid4()), ("attempt", "actual_result_digest", "0" * 64),
    ("nano", "attempt_id", uuid4()), ("nano", "result_classification", "retryable_failure"),
    ("nano", "actual_model_id", "another-model"), ("nano", "requested_revision", "other"),
    ("nano", "model_fingerprint", "0" * 64), ("nano", "output_digest", "0" * 64),
    ("nano", "input_digest_key_id", None), ("nano", "input_digest", "invalid"),
    ("generator", "actual_provider_id", "another-provider"),
    ("generator", "result_classification", "security_failure"),
    ("generator", "input_digest", "0" * 64), ("generator", "parameters_digest", "0" * 64),
    ("evidence", "actual_identity_json", {}), ("evidence", "runtime_fingerprint", "0" * 64),
    ("evidence", "result_classification", "cancelled"), ("evidence", "token_digest", None),
    ("evidence", "attempt_number", 2), ("evidence", "instruction_digest", "0" * 64),
    ("draft", "runtime_identity_json", {}), ("draft", "parameters_json", {}),
    ("version", "fingerprint", "0" * 64), ("version", "parameters_json", {}),
    ("asset", "state", "deleting"), ("asset", "state", "deleted"),
    ("asset", "metadata_json", {}), ("asset", "validation_json", {}),
    ("asset", "storage_path", "other.wav"), ("asset", "retention_policy", "temporary_preview"),
    ("asset", "verified_at", None), ("asset", "expires_at", NOW + timedelta(days=1)),
    ("reference", "state", "deleted"), ("reference", "metadata_json", {}),
    ("rights", "source_identifier", "local://unrelated"), ("rights", "expires_at", NOW),
    ("rights", "risk_flags_json", ["review"]),
])
def test_rejects_unusable_or_mismatched_publication(graph, row, field, value):
    setattr(getattr(graph, row), field, value)
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)


@pytest.mark.parametrize("row", ["novel", "profile", "version", "command", "draft", "job", "rights", "asset", "reference"])
def test_rejects_foreign_owner_scope(graph, row):
    getattr(graph, row).owner_id = uuid4()
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)


@pytest.mark.parametrize("row", ["character", "command", "draft", "job", "rights", "asset", "reference"])
def test_rejects_cross_novel_links(graph, row):
    getattr(graph, row).novel_id = uuid4()
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)


@pytest.mark.parametrize("row", ["novel", "character", "profile", "version", "rights", "event", "command",
                                 "draft", "job", "attempt", "generator", "nano", "evidence", "reference", "asset"])
def test_incomplete_graph_cannot_authorize_media(graph, row):
    value = getattr(graph, row)
    del graph.store.rows[(type(value), value.id)]
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)


def test_reference_audio_is_not_the_listening_asset(graph):
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.reference.id, at=NOW)


@pytest.mark.parametrize("model", ["generator", "nano"])
def test_matching_parameter_labels_do_not_replace_parameter_digest_validation(graph, model):
    if model == "generator":
        graph.generator.parameters_digest = graph.draft.parameters_digest = "0" * 64
    else:
        graph.nano.parameters_digest = "0" * 64
        graph.version.parameters_json["nano_parameters_digest"] = "0" * 64
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)


@pytest.mark.parametrize("event_type", ["revoked", "expired", "review_blocked"])
def test_negative_rights_event_removes_public_projection_without_hiding_profile(graph, event_type):
    before = voice_profile_resource(graph.store, graph.profile, at=NOW)
    assert before.versions[0].preview_asset.asset_id == graph.asset.id
    event = VoiceRightsEvent(id=uuid4(), rights_record_id=graph.rights.id, event_key="revocation",
                            event_type=event_type, actor="local-owner", occurred_at=NOW)
    graph.store.rows[(VoiceRightsEvent, event.id)] = event
    with pytest.raises(NarrationServiceError):
        resolve_voice_version_media(graph.store, graph.version.id, graph.asset.id, at=NOW)
    after = voice_profile_resource(graph.store, graph.profile, at=NOW)
    assert after.profile_id == before.profile_id
    assert after.versions[0].preview_asset is None


# Reuse the existing isolated database guard and real publication transaction;
# model adapters below are deterministic fakes and never load/download a model.
from tests.narration.test_voice_generator_postgres import vg_pg_runtime  # noqa: E402, F401


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_binding", [False, True])
async def test_processor_publication_is_compatible_with_version_preview(vg_pg_runtime, tmp_path, changed_binding):
    from time import perf_counter
    from sqlalchemy import event
    from backend.narration import schemas as wire
    from backend.narration.official_presets import OFFICIAL_PRESETS
    from backend.narration.official_voice_selection import OfficialVoiceSelectionService
    from backend.narration.playback_api import SqlAlchemyPlaybackApiBackend
    from backend.narration.storage import NarrationStorage
    from backend.narration.voice_generator_processor import SqlAlchemyVoiceGeneratorRepository, VoiceGeneratorProcessor
    from tests.narration.digest_fixtures import TEST_DIGEST_KEYRING
    from tests.narration.test_voice_generator_postgres import _Host, _Nano, _claim, _reserve_and_analyze, _seed

    connection, factory = vg_pg_runtime
    novel_id, character_id = _seed(factory)
    _, command_id, job_id = _reserve_and_analyze(factory, novel_id, character_id)
    lease = _claim(factory, job_id)
    if changed_binding:
        OfficialVoiceSelectionService(factory).select_official_voice(
            novel_id=novel_id,
            request=wire.OfficialVoiceSelectionRequest(
                preset_id=OFFICIAL_PRESETS[0].preset_id, target_kind="character",
                character_id=character_id, expected_settings_version=0, expected_binding_version=0,
            ),
            idempotency_key=f"version-preview-drift:{uuid4()}",
        )
    models_root, media_root = tmp_path / "models", tmp_path / "media"
    models_root.mkdir(mode=0o700)
    media_root.mkdir(mode=0o700)
    await VoiceGeneratorProcessor(
        repository=SqlAlchemyVoiceGeneratorRepository(factory, digest_keyring=TEST_DIGEST_KEYRING),
        host=_Host(), nano_adapter=_Nano(),
        storage=NarrationStorage(models_root=models_root, media_root=media_root),
        digest_keyring=TEST_DIGEST_KEYRING, poll_seconds=0.01,
    ).process(lease)
    with factory() as session:
        command = session.get(VoiceGeneratorCommand, command_id)
        assert command.state == ("ready_unapplied" if changed_binding else "ready_applied"), command.failure_code
        store = SqlAlchemyNarrationStore(session)
        resolved = resolve_voice_version_media(store, command.voice_version_id, command.nano_validation_asset_id)
        assert resolved.id == command.nano_validation_asset_id
        profile = session.get(VoiceProfile, command.voice_profile_id)
        statements = []
        def track_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(connection, "before_cursor_execute", track_statement)
        started = perf_counter()
        try:
            assert voice_profile_resource(store, profile).versions[0].preview_asset.asset_id == resolved.id
        finally:
            elapsed = perf_counter() - started
            event.remove(connection, "before_cursor_execute", track_statement)
        assert not any("FOR UPDATE" in statement.upper() for statement in statements)
        print(f"dedicated preview profile projection: {len(statements)} statements, {elapsed * 1000:.2f} ms")
        with pytest.raises(NarrationServiceError):
            resolve_voice_version_media(store, command.voice_version_id, command.generated_reference_asset_id)
        backend = SqlAlchemyPlaybackApiBackend(
            session,
            NarrationStorage(models_root=models_root, media_root=media_root),
            resolve_voice_version_media=lambda active_session, version_id, asset_id: resolve_voice_version_media(
                SqlAlchemyNarrationStore(active_session), version_id, asset_id,
            ),
        )
        for method in ("GET", "HEAD"):
            result = backend.read_media(
                asset_id=command.nano_validation_asset_id,
                edition_id=None, manifest_revision=None, voice_preview_id=None,
                generic_voice_slot_id=None, voice_version_id=command.voice_version_id,
                method=method, range_header="bytes=0-15", if_range=None, if_none_match=None,
            )
            assert result.decision.status == 206
            assert result.decision.headers["Content-Length"] == "16"
            body = b"".join(result.body)
            assert body.startswith(b"RIFF") if method == "GET" else body == b""
            assert not session.in_transaction()
        version = session.get(VoiceProfileVersion, command.voice_version_id)
        session.add(VoiceRightsEvent(
            id=uuid4(), rights_record_id=version.rights_record_id, event_key="preview-revocation",
            event_type="revoked", actor="local-owner", occurred_at=NOW,
        ))
        session.flush()
        with pytest.raises(NarrationServiceError):
            resolve_voice_version_media(store, command.voice_version_id, command.nano_validation_asset_id)
        assert voice_profile_resource(store, profile).versions[0].preview_asset is None
