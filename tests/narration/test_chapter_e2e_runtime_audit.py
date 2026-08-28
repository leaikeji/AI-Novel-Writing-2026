from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from scripts.tts.chapter_e2e_executor import (
    ChainAuditEvidence,
    RuntimePreflightEvidence,
    TechnicalProbeContext,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    BoundProbeReportCache,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
    ProbeExpectation,
)
from scripts.tts.chapter_e2e_runtime_audit import (
    ReportBackedRuntimeAuditProbe,
    SqlAlchemyRuntimeAuditReader,
)
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    ChapterCase,
    ChapterFixture,
    RunnerConfig,
    RunnerError,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTO_REQUEST = UUID("44444444-4444-4444-8444-444444444444")
AUTO_EDITION = UUID("55555555-5555-4555-8555-555555555555")
AUTO_SCRIPT = UUID("66666666-6666-4666-8666-666666666666")
MANUAL_REQUEST = UUID("77777777-7777-4777-8777-777777777777")
MANUAL_EDITION = UUID("88888888-8888-4888-8888-888888888888")
MANUAL_SCRIPT = UUID("99999999-9999-4999-8999-999999999999")
MODEL = hashlib.sha256(b"moss-nano").hexdigest()
AUTO_EDITION_FINGERPRINT = hashlib.sha256(b"automatic-edition").hexdigest()
MANUAL_EDITION_FINGERPRINT = hashlib.sha256(b"manual-edition").hexdigest()
OUTPUT_HASHES = ("a" * 64, "b" * 64)


def _config(tmp_path: Path) -> RunnerConfig:
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=tmp_path / "private",
        output_dir=tmp_path / "output",
        duration_minutes=30.0,
        listening_record=None,
        resume=False,
        expected_formal_speakers=("林晚", "沈川"),
    )


def _context() -> TechnicalProbeContext:
    return TechnicalProbeContext(
        automatic_request_id=AUTO_REQUEST,
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        automatic_manifest_revision=2,
        manual_request_id=MANUAL_REQUEST,
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        manual_manifest_revision=2,
        request_to_ready_seconds=(10.0, 20.0),
        observed_http_first_audio_ms=(500, 700),
        chapter_audio_duration_seconds=90.0,
        range_status_codes=(200, 206, 304, 416),
        listening_output_hashes=OUTPUT_HASHES,
    )


def _fixture() -> ChapterFixture:
    automatic = ChapterCase(
        case_id="automatic",
        mode="automatic_zero_blockers",
        source_text="automatic",
        source_sha256="c" * 64,
        review_policy="blockers_only",
        expected_initial_blocker_codes=(),
        corrections=(),
    )
    manual = ChapterCase(
        case_id="manual",
        mode="manual_blocker_resolution",
        source_text="manual",
        source_sha256="d" * 64,
        review_policy="blockers_only",
        expected_initial_blocker_codes=("B_SPEAKER_UNKNOWN",),
        corrections=(),
    )
    return ChapterFixture(
        fixture_id="fixture-v2",
        manifest_sha256="e" * 64,
        authorization_reference="authorized",
        voice_scope="isolated_test_only",
        production_eligible=False,
        commercial_distribution_status="not_evaluated",
        minimum_character_speakers=2,
        minimum_distinct_voice_versions=3,
        expected_formal_speakers=("林晚", "沈川"),
        require_uncached_nano_model_run=True,
        restoration_policy="dedicated_append_only_author_visible",
        automatic=automatic,
        manual=manual,
        required_viewports=ALLOWED_VIEWPORTS,
    )


def _write_probe(path: Path, config: RunnerConfig) -> None:
    context = _context()
    expectation = ProbeExpectation.from_runner(
        config,
        automatic_edition_id=context.automatic_edition_id,
        automatic_edition_fingerprint=(
            context.automatic_edition_fingerprint
        ),
        manual_edition_id=context.manual_edition_id,
        manual_edition_fingerprint=context.manual_edition_fingerprint,
        listening_output_hashes=context.listening_output_hashes,
    )
    collected_at = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "binding": expectation.report_binding(collected_at=collected_at),
        "browser": {
            "observer_report_sha256": "8" * 64,
            "captures": [
                {
                    "width": width,
                    "height": height,
                    "assistant_mode": mode,
                    "console_error_count": 0,
                    "overlap_count": 0,
                }
                for width, height in ALLOWED_VIEWPORTS
                for mode in ALLOWED_ASSISTANT_MODES
            ],
            "range_status_codes": [200, 206, 304, 416],
            "time_to_first_audio_ms": 700,
            "seam_pairs_checked": 4,
            "seek_latest_wins": True,
            "pending_gap_not_skipped": True,
            "edit_actions_created_tts_writes": 0,
        },
        "runtime": {
            "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
            "stability_elapsed_seconds": 1800.0,
            "chapter_audio_duration_seconds": 90.0,
            "request_to_ready_seconds": 20.0,
            "peak_memory_bytes": 2_000_000_000,
            "sidecar_restart_count": 0,
            "health_failure_count": 0,
            "host_paging_observed": False,
            "pageout_delta": 0,
            "swapout_delta": 0,
            "memory_baseline_median_bytes": 1_800_000_000,
            "memory_tail_median_bytes": 1_900_000_000,
            "memory_growth_bytes": 100_000_000,
            "memory_growth_limit_bytes": 134_217_728,
            "sidecar_memory_growth_observed": False,
            "qwenpaw_slowdown_observed": False,
        },
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    def preflight(self, config: RunnerConfig) -> RuntimePreflightEvidence:
        assert config.novel_id == NOVEL_ID
        return RuntimePreflightEvidence(
            production_ready=True,
            sidecar_ready=True,
            product_visible=False,
            model_fingerprint=MODEL,
        )

    def audit_chain(
        self,
        config: RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> ChainAuditEvidence:
        assert config.document_id == DOCUMENT_ID
        assert job_ids and segment_ids
        self.calls.append(request_id)
        return ChainAuditEvidence(
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_version_id,
            edition_fingerprint=(
                AUTO_EDITION_FINGERPRINT
                if edition_id == AUTO_EDITION
                else MANUAL_EDITION_FINGERPRINT
            ),
            distinct_voice_version_count=3,
            uncached_nano_job_count=len(job_ids),
            model_run_fingerprints=(MODEL,),
        )


def test_report_backed_runtime_probe_requires_both_audited_chains(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    report = tmp_path / "probe.json"
    _write_probe(report, config)
    reader = FakeReader()
    probe = ReportBackedRuntimeAuditProbe(
        config,
        reader=reader,
        cache=BoundProbeReportCache(report),
    )
    context = _context()

    assert probe.preflight(config).model_fingerprint == MODEL
    auto = probe.audit_chain(
        config,
        request_id=AUTO_REQUEST,
        edition_id=AUTO_EDITION,
        script_version_id=AUTO_SCRIPT,
        job_ids=(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),),
        segment_ids=(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),),
    )
    manual = probe.audit_chain(
        config,
        request_id=MANUAL_REQUEST,
        edition_id=MANUAL_EDITION,
        script_version_id=MANUAL_SCRIPT,
        job_ids=(UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),),
        segment_ids=(UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),),
    )
    technical = probe.collect_technical(config, _fixture(), context)

    assert auto.model_run_fingerprints == (MODEL,)
    assert auto.edition_fingerprint == AUTO_EDITION_FINGERPRINT
    assert manual.distinct_voice_version_count == 3
    assert manual.edition_fingerprint == MANUAL_EDITION_FINGERPRINT
    assert reader.calls == [AUTO_REQUEST, MANUAL_REQUEST]
    assert technical.stability_elapsed_seconds == 1800.0
    assert technical.peak_memory_bytes == 2_000_000_000
    assert technical.seam_pairs_checked == 4
    assert technical.sidecar_restart_count == 0
    assert technical.health_failure_count == 0
    assert technical.host_paging_observed is False
    assert technical.pageout_delta == 0
    assert technical.swapout_delta == 0
    assert technical.memory_baseline_median_bytes == 1_800_000_000
    assert technical.memory_tail_median_bytes == 1_900_000_000
    assert technical.memory_growth_bytes == 100_000_000
    assert technical.memory_growth_limit_bytes == 134_217_728
    assert technical.sidecar_memory_growth_observed is False
    assert technical.qwenpaw_slowdown_observed is False


def test_runtime_probe_fails_closed_on_sequence_replay(tmp_path: Path) -> None:
    config = _config(tmp_path)
    probe = ReportBackedRuntimeAuditProbe(
        config,
        reader=FakeReader(),
        cache=BoundProbeReportCache(tmp_path / "missing.json"),
    )

    with pytest.raises(RunnerError, match="RUNTIME_AUDIT_SEQUENCE_INVALID"):
        probe.audit_chain(
            config,
            request_id=AUTO_REQUEST,
            edition_id=AUTO_EDITION,
            script_version_id=AUTO_SCRIPT,
            job_ids=(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),),
            segment_ids=(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),),
        )

    probe.preflight(config)
    with pytest.raises(RunnerError, match="RUNTIME_AUDIT_SEQUENCE_INVALID"):
        probe.preflight(config)


def test_sqlalchemy_reader_rejects_non_postgresql_before_queries() -> None:
    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    reader = SqlAlchemyRuntimeAuditReader(FakeSession)  # type: ignore[arg-type]

    with pytest.raises(RunnerError, match="RUNTIME_AUDIT_POSTGRES_REQUIRED"):
        with reader._read_session():  # noqa: SLF001 - explicit safety unit test
            raise AssertionError("unreachable")


class _ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _VoiceAuthoritySession:
    def __init__(self, outputs: list[list[object]]) -> None:
        self._outputs = outputs

    def scalars(self, _statement: object) -> _ScalarRows:
        if not self._outputs:
            raise AssertionError("unexpected authority query")
        return _ScalarRows(self._outputs.pop(0))


def _voice_authority_rows(
    *,
    confirmed: bool = True,
    bad_provenance: bool = False,
) -> tuple[_VoiceAuthoritySession, dict[UUID, UUID]]:
    now = datetime.now(timezone.utc)
    preset_names = ("Lingyu", "Yuewen", "Junhao")
    versions: list[object] = []
    profiles: list[object] = []
    rights_rows: list[object] = []
    expected: dict[UUID, UUID] = {}
    rights_ids: list[UUID] = []
    for index, name in enumerate(preset_names, start=1):
        profile_id = UUID(f"aaaaaaaa-aaaa-4aaa-8aaa-{index:012d}")
        version_id = UUID(f"bbbbbbbb-bbbb-4bbb-8bbb-{index:012d}")
        rights_id = UUID(f"cccccccc-cccc-4ccc-8ccc-{index:012d}")
        unsigned = {
            "schema_version": "moss-tts-official-preset-provenance/1.0",
            "repository": "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
            "revision": "f52645cb467506d8e18e746ddd59482685b74e58",
            "manifest_path": "browser_poc_manifest.json",
            "manifest_sha256": "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee",
            "preset_id": f"onnx.{name}",
            "manifest_voice": name,
            "prompt_codes_sha256": str(index) * 64,
            "prompt_frame_count": 90 + index,
            "prompt_quantizer_count": 16,
            "model_fingerprint_sha256": "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d",
        }
        provenance = {
            **unsigned,
            "provenance_fingerprint_sha256": hashlib.sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        if bad_provenance and index == 1:
            provenance["manifest_sha256"] = "0" * 64
        versions.append(
            SimpleNamespace(
                id=version_id,
                profile_id=profile_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                source_type="preset",
                state="locked",
                quality_state="accepted",
                locked_actor="test-author",
                locked_at=now,
                fingerprint="f" * 64,
                rights_record_id=rights_id,
                reference_asset_id=None,
                preset_key=f"onnx.{name}",
                parameters_json={"official_preset": provenance},
            )
        )
        profiles.append(
            SimpleNamespace(
                id=profile_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=NOVEL_ID,
                status="active",
                current_version_id=version_id,
            )
        )
        rights_rows.append(
            SimpleNamespace(
                id=rights_id,
                owner_id=LOCAL_OWNER_ID,
                workspace_id=LOCAL_WORKSPACE_ID,
                novel_id=NOVEL_ID,
                source_kind="official_preset",
                purpose="private_novel_narration",
                commercial_use=False,
                redistribution=False,
                voice_cloning=False,
                subject_consent_reference=None,
                confirmed_actor="test-author",
                confirmed_at=now,
                expires_at=None,
            )
        )
        expected[version_id] = profile_id
        rights_ids.append(rights_id)
    confirmed_rows: list[object] = rights_ids if confirmed else []
    session = _VoiceAuthoritySession(
        [
            versions,
            profiles,
            rights_rows,
            [],
            confirmed_rows,
            [],
        ]
    )
    return session, expected


def test_voice_authority_requires_confirmed_event_and_canonical_provenance() -> None:
    session, expected = _voice_authority_rows()

    SqlAlchemyRuntimeAuditReader._validate_voice_versions(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        novel_id=NOVEL_ID,
        expected_profiles=expected,
    )

    assert session._outputs == []  # noqa: SLF001


@pytest.mark.parametrize(
    ("confirmed", "bad_provenance"),
    ((False, False), (True, True)),
)
def test_voice_authority_fails_closed_on_missing_confirmation_or_bad_provenance(
    confirmed: bool,
    bad_provenance: bool,
) -> None:
    session, expected = _voice_authority_rows(
        confirmed=confirmed,
        bad_provenance=bad_provenance,
    )

    with pytest.raises(RunnerError, match="RUNTIME_AUDIT_VOICE_INVALID"):
        SqlAlchemyRuntimeAuditReader._validate_voice_versions(  # noqa: SLF001
            session,  # type: ignore[arg-type]
            novel_id=NOVEL_ID,
            expected_profiles=expected,
        )


def _formal_voice_rows() -> tuple[
    list[SimpleNamespace],
    list[SimpleNamespace],
    tuple[UUID, UUID],
    dict[UUID, tuple[UUID, UUID]],
    dict[UUID, UUID],
]:
    narrator_voice = (
        UUID("10000000-0000-4000-8000-000000000001"),
        UUID("20000000-0000-4000-8000-000000000001"),
    )
    lin_wan = UUID("30000000-0000-4000-8000-000000000001")
    shen_chuan = UUID("30000000-0000-4000-8000-000000000002")
    character_voices = {
        lin_wan: (
            UUID("10000000-0000-4000-8000-000000000002"),
            UUID("20000000-0000-4000-8000-000000000002"),
        ),
        shen_chuan: (
            UUID("10000000-0000-4000-8000-000000000003"),
            UUID("20000000-0000-4000-8000-000000000003"),
        ),
    }
    script_rows = [
        SimpleNamespace(speaker_kind="narrator", character_id=None),
        SimpleNamespace(speaker_kind="character", character_id=lin_wan),
        SimpleNamespace(speaker_kind="character", character_id=shen_chuan),
    ]
    edition_rows = [
        SimpleNamespace(
            voice_version_id=narrator_voice[0],
            profile_id=narrator_voice[1],
        ),
        SimpleNamespace(
            voice_version_id=character_voices[lin_wan][0],
            profile_id=character_voices[lin_wan][1],
        ),
        SimpleNamespace(
            voice_version_id=character_voices[shen_chuan][0],
            profile_id=character_voices[shen_chuan][1],
        ),
    ]
    expected_profiles = {
        narrator_voice[0]: narrator_voice[1],
        **{
            voice_version_id: profile_id
            for voice_version_id, profile_id in character_voices.values()
        },
    }
    return (
        script_rows,
        edition_rows,
        narrator_voice,
        character_voices,
        expected_profiles,
    )


def test_segment_voice_mapping_proves_narrator_and_both_formal_speakers() -> None:
    script_rows, edition_rows, narrator, characters, profiles = (
        _formal_voice_rows()
    )

    SqlAlchemyRuntimeAuditReader._validate_segment_voice_mapping(  # noqa: SLF001
        script_rows,  # type: ignore[arg-type]
        edition_rows,  # type: ignore[arg-type]
        narrator_voice=narrator,
        character_voices_by_id=characters,
        expected_profiles=profiles,
    )


@pytest.mark.parametrize("failure", ("swapped", "missing", "anonymous"))
def test_segment_voice_mapping_fails_closed_on_semantic_mismatch(
    failure: str,
) -> None:
    script_rows, edition_rows, narrator, characters, profiles = (
        _formal_voice_rows()
    )
    if failure == "swapped":
        edition_rows[1], edition_rows[2] = edition_rows[2], edition_rows[1]
    elif failure == "missing":
        script_rows[2] = SimpleNamespace(
            speaker_kind="narrator",
            character_id=None,
        )
        edition_rows[2] = SimpleNamespace(
            voice_version_id=narrator[0],
            profile_id=narrator[1],
        )
    else:
        script_rows[2] = SimpleNamespace(
            speaker_kind="anonymous",
            character_id=None,
        )

    with pytest.raises(RunnerError, match="RUNTIME_AUDIT_CHAIN_INVALID"):
        SqlAlchemyRuntimeAuditReader._validate_segment_voice_mapping(  # noqa: SLF001
            script_rows,  # type: ignore[arg-type]
            edition_rows,  # type: ignore[arg-type]
            narrator_voice=narrator,
            character_voices_by_id=characters,
            expected_profiles=profiles,
        )
