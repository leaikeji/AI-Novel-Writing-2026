from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
import stat
from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.models import CharacterVoiceBinding, NovelCharacter
from backend.narration.segmentation import SourceFormat, segment_source
from backend.narration.script_analysis import analyze_narration_script
from scripts.tts import validate_chapter_e2e as runner
from tests.narration.test_script_analysis import _seed, _voice


NOVEL_ID = "11111111-1111-4111-8111-111111111111"
DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_DOCUMENT_ID = "33333333-3333-4333-8333-333333333333"
REQUEST_AUTO = UUID("44444444-4444-4444-8444-444444444444")
SCRIPT_AUTO = UUID("55555555-5555-4555-8555-555555555555")
EDITION_AUTO = UUID("66666666-6666-4666-8666-666666666666")
REQUEST_MANUAL = UUID("77777777-7777-4777-8777-777777777777")
SCRIPT_MANUAL = UUID("88888888-8888-4888-8888-888888888888")
EDITION_MANUAL = UUID("99999999-9999-4999-8999-999999999999")
BASE_REVISION = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BASELINE_EDITION = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
BASELINE_SCRIPT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
AUTO_TEXT = "\n".join(
    f"这是项目自有的自动链测试文本第{index:02d}段。" for index in range(40)
)
MANUAL_SEGMENT_TEXT = "他说：“这是需要人工确认的句段。”"
MANUAL_TEXT = "\n".join(
    [MANUAL_SEGMENT_TEXT]
    + [f"这是项目自有的人工链后续测试文本第{index:02d}段。" for index in range(40)]
)
BASELINE_TEXT = "恢复时只能保存在仓库外的私有基线正文。"
REPOSITORY_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "narration"
    / "chapter-e2e-v2.json"
)
REPOSITORY_FIXTURE_SHA256 = (
    "e970e4f837d2f96b2675e8922e43bb5dfcffc352e86f0f96b84e34db1065380b"
)
REPOSITORY_FIXTURE_V3 = REPOSITORY_FIXTURE.with_name("chapter-e2e-v3.json")
REPOSITORY_FIXTURE_V3_SHA256 = (
    "3cfb094c3a3374eb233ccff5c08963adaba5cac55e5ec056ff5257d32e421913"
)
_ORIGINAL_RUNNER_MAIN = runner.main


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _listening_claim_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "listening-claims"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    monkeypatch.setattr(
        runner,
        "LISTENING_CLAIM_REGISTRY_DIRECTORY",
        directory,
    )

    def guarded_main(
        argv: list[str] | None = None,
        **kwargs: object,
    ) -> int:
        arguments = list(argv or [])
        if "--mode" in arguments and arguments[
            arguments.index("--mode") + 1
        ] == "real":
            private = Path(
                arguments[arguments.index("--private-work-dir") + 1]
            )
            if not private.exists():
                private.mkdir(mode=0o700)
            identity = runner._directory_identity(private.stat())
            path_digest, identity_digest = (
                runner.recovery_private_directory_binding(private, identity)
            )
            binding = runner.RecoveryClaimBinding(
                claim_identity_sha256="d" * 64,
                envelope_fingerprint_sha256="e" * 64,
                private_work_dir_canonical_sha256=path_digest,
                private_work_dir_identity_sha256=identity_digest,
            )
            recovery_path = private / "recovery.json"
            if (
                recovery_path.exists()
                and not recovery_path.is_symlink()
                and stat.S_ISREG(recovery_path.lstat().st_mode)
            ):
                payload = json.loads(recovery_path.read_text("utf-8"))
                recovery_state = payload["state"]
                state = runner._claim_state_for_recovery_state(recovery_state)
                generation = payload["generation"]
                digest = runner._recovery_record_sha256(payload)
            else:
                state = "PREPARED"
                generation = 0
                digest = None

            def observe(
                state_value: str,
                next_generation: int,
                next_digest: str,
            ) -> None:
                nonlocal state, generation, digest
                state = state_value
                generation = next_generation
                digest = next_digest

            def snapshot() -> runner.RecoveryClaimSnapshot:
                return runner.RecoveryClaimSnapshot(
                    state=state,
                    recovery_generation=generation,
                    latest_recovery_sha256=digest,
                )

            kwargs.setdefault("recovery_claim_binding", binding)
            kwargs.setdefault("recovery_state_observer", observe)
            kwargs.setdefault("recovery_claim_state_reader", snapshot)
        return _ORIGINAL_RUNNER_MAIN(arguments, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "main", guarded_main)


def test_repository_v2_fixture_is_frozen_and_correction_is_source_bound() -> None:
    fixture = runner.load_fixture(
        REPOSITORY_FIXTURE,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )

    assert fixture.manifest_sha256 == REPOSITORY_FIXTURE_SHA256
    assert len(fixture.automatic.source_text) == 1110
    assert len(fixture.manual.source_text) == 1172
    assert fixture.required_viewports == ((1920, 1080), (2560, 1440))
    correction = fixture.manual.corrections[0]
    segmented = segment_source(
        script_version_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        source_text=fixture.manual.source_text,
        source_format=SourceFormat.MARKDOWN,
    )
    target = segmented.segments[correction.segment_ordinal]
    assert target.source_range_utf16.start == correction.expected_source_start_utf16
    assert (
        target.source_range_utf16.end_exclusive
        == correction.expected_source_end_utf16
    )
    assert target.local_hash == correction.expected_source_local_hash
    assert target.source_text == "“先别开门。”\n\n"


def test_repository_v2_fixture_has_exact_automatic_and_manual_domain_states() -> None:
    fixture = runner.load_fixture(
        REPOSITORY_FIXTURE,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )

    outcomes: list[tuple[object, object]] = []
    for case in (fixture.automatic, fixture.manual):
        store, novel, _document, _revision, _lin, _request, command = _seed(
            case.source_text,
            intent="create",
        )
        shen = NovelCharacter(
            id=uuid4(),
            novel_id=novel.id,
            role_type="supporting",
            name="沈川",
            description="",
            details={},
            lifecycle_state="active",
            position=1,
            version=1,
        )
        store.add(shen)
        profile, version = _voice(store, novel.id, name="character-shen")
        store.add(
            CharacterVoiceBinding(
                id=uuid4(),
                novel_id=novel.id,
                character_id=shen.id,
                profile_id=profile.id,
                voice_version_id=version.id,
                binding_policy="dedicated",
                language="zh-CN",
                parameters_json={},
                version=1,
            )
        )
        outcomes.append((case, analyze_narration_script(store, command)))

    automatic_case, automatic = outcomes[0]
    assert automatic.state.value == "approved"
    assert automatic.blocker_count == 0
    assert automatic_case.expected_initial_blocker_codes == ()
    assert len(
        {
            segment.speaker.character_id
            for segment in automatic.segments
            if segment.speaker.kind.value == "character"
        }
    ) == 2

    manual_case, manual = outcomes[1]
    blocker_codes = tuple(
        sorted(
            {
                issue.code
                for issue in manual.issues
                if issue.severity.value == "blocker"
            }
        )
    )
    assert manual.state.value == "review_required"
    assert manual.blocker_count == 3
    assert blocker_codes == manual_case.expected_initial_blocker_codes
    correction = manual_case.corrections[0]
    target = manual.segments[correction.segment_ordinal]
    assert target.speaker.kind.value == "unknown"
    assert target.local_hash == correction.expected_source_local_hash


def test_repository_v3_fixture_is_append_only_and_source_bound() -> None:
    fixture = runner.load_fixture(
        REPOSITORY_FIXTURE_V3,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )

    assert fixture.manifest_sha256 == REPOSITORY_FIXTURE_V3_SHA256
    assert fixture.fixture_id == "t4-k-project-owned-chapter-v3"
    assert fixture.authorization_reference == "project-original-t4-k-v3"
    assert len(fixture.automatic.source_text) == 1110
    assert _sha256(fixture.automatic.source_text) == (
        "22b77e45447fc7c6145f22b4b50b55436c971f86d9359ec87e06dd695267635f"
    )
    assert len(fixture.manual.source_text) == 1170
    assert _sha256(fixture.manual.source_text) == (
        "564985d38cbafefff4abf500857f5dd4e18ad0cffe2107f77331309fc8fbe922"
    )
    assert fixture.required_viewports == ((1920, 1080), (2560, 1440))
    assert REPOSITORY_FIXTURE.read_bytes() != REPOSITORY_FIXTURE_V3.read_bytes()

    correction = fixture.manual.corrections[0]
    segmented = segment_source(
        script_version_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        source_text=fixture.manual.source_text,
        source_format=SourceFormat.MARKDOWN,
    )
    target = segmented.segments[correction.segment_ordinal]
    assert correction.segment_ordinal == 0
    assert target.source_range_utf16.start == correction.expected_source_start_utf16
    assert (
        target.source_range_utf16.end_exclusive
        == correction.expected_source_end_utf16
    )
    assert target.local_hash == correction.expected_source_local_hash
    assert target.source_text == "“先别开门。”\n\n"
    assert segmented.segments[4].source_text == (
        "“箱子没有破损，我先核对编号和旧批次记录。”\n\n"
    )


def test_repository_v3_fixture_preserves_exact_domain_states() -> None:
    fixture = runner.load_fixture(
        REPOSITORY_FIXTURE_V3,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )

    outcomes: list[tuple[object, object]] = []
    for case in (fixture.automatic, fixture.manual):
        store, novel, _document, _revision, _lin, _request, command = _seed(
            case.source_text,
            intent="create",
        )
        shen = NovelCharacter(
            id=uuid4(),
            novel_id=novel.id,
            role_type="supporting",
            name="沈川",
            description="",
            details={},
            lifecycle_state="active",
            position=1,
            version=1,
        )
        store.add(shen)
        profile, version = _voice(store, novel.id, name="character-shen")
        store.add(
            CharacterVoiceBinding(
                id=uuid4(),
                novel_id=novel.id,
                character_id=shen.id,
                profile_id=profile.id,
                voice_version_id=version.id,
                binding_policy="dedicated",
                language="zh-CN",
                parameters_json={},
                version=1,
            )
        )
        outcomes.append((case, analyze_narration_script(store, command)))

    automatic_case, automatic = outcomes[0]
    assert automatic.state.value == "approved"
    assert automatic.blocker_count == 0
    assert automatic_case.expected_initial_blocker_codes == ()
    assert len(
        {
            segment.speaker.character_id
            for segment in automatic.segments
            if segment.speaker.kind.value == "character"
        }
    ) == 2

    manual_case, manual = outcomes[1]
    blocker_codes = tuple(
        sorted(
            {
                issue.code
                for issue in manual.issues
                if issue.severity.value == "blocker"
            }
        )
    )
    assert manual.state.value == "review_required"
    assert manual.blocker_count == 3
    assert blocker_codes == manual_case.expected_initial_blocker_codes
    correction = manual_case.corrections[0]
    target = manual.segments[correction.segment_ordinal]
    assert target.speaker.kind.value == "unknown"
    assert target.local_hash == correction.expected_source_local_hash


def _fixture_payload() -> dict[str, Any]:
    return {
        "schema_version": runner.FIXTURE_SCHEMA,
        "fixture_id": "t4-k-authorized-chapter-v2",
        "authorization": {
            "text_owner": "project_owned",
            "authorization_reference": "project-fixture-license-v1",
            "authorized_for_tts": True,
            "contains_private_reference_audio": False,
        },
        "voice_scope": "local_personal_use",
        "production_eligible": True,
        "commercial_distribution_status": "not_evaluated",
        "minimum_character_speakers": 2,
        "minimum_distinct_voice_versions": 3,
        "expected_formal_speakers": ["林晚", "沈川"],
        "require_uncached_nano_model_run": True,
        "restoration_policy": "dedicated_append_only_author_visible",
        "minimum_duration_minutes": 30,
        "required_viewports": [
            {"width": 1920, "height": 1080},
            {"width": 2560, "height": 1440},
        ],
        "chapter_cases": [
            {
                "id": "chapter-auto-zero-blockers",
                "mode": "automatic_zero_blockers",
                "source_text": AUTO_TEXT,
                "source_sha256": _sha256(AUTO_TEXT),
                "review_policy": "blockers_only",
                "expected_initial_blocker_codes": [],
                "corrections": [],
            },
            {
                "id": "chapter-real-blocker",
                "mode": "manual_blocker_resolution",
                "source_text": MANUAL_TEXT,
                "source_sha256": _sha256(MANUAL_TEXT),
                "review_policy": "blockers_only",
                "expected_initial_blocker_codes": ["B_SPEAKER_UNKNOWN"],
                "corrections": [
                    {
                        "segment_ordinal": 0,
                        "expected_source_local_hash": _sha256(
                            MANUAL_SEGMENT_TEXT
                        ),
                        "expected_source_start_utf16": 0,
                        "expected_source_end_utf16": len(
                            MANUAL_SEGMENT_TEXT.encode("utf-16-le")
                        )
                        // 2,
                        "speaker_kind": "narrator",
                        "speaker_label": "旁白",
                        "spoken_text": MANUAL_SEGMENT_TEXT,
                        "reason": "项目自有 fixture 的确定性修正。",
                    }
                ],
            },
        ],
    }


def _write_fixture(path: Path, payload: dict[str, Any] | None = None) -> Path:
    path.write_text(
        json.dumps(payload or _fixture_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _arguments(
    tmp_path: Path,
    fixture: Path,
    *,
    mode: str = "validate-only",
    api_base: str = "http://127.0.0.1:18088/api/ai-novel-world-2026",
    confirmation: str = DOCUMENT_ID,
    novel_confirmation: str = NOVEL_ID,
    duration_minutes: str = "30",
    private_work_dir: Path | None = None,
    output_dir: Path | None = None,
    include_real_confirmations: bool = False,
    listening_record: Path | None = None,
    resume: bool = False,
    run_id: str | None = None,
) -> list[str]:
    private = private_work_dir or (tmp_path / "private-work")
    output = output_dir or (tmp_path / "evidence")
    argv = [
        "--mode",
        mode,
        "--fixture-manifest",
        str(fixture),
        "--api-base",
        api_base,
        "--novel-id",
        NOVEL_ID,
        "--document-id",
        DOCUMENT_ID,
        "--automatic-case-id",
        "chapter-auto-zero-blockers",
        "--manual-case-id",
        "chapter-real-blocker",
        "--private-work-dir",
        str(private),
        "--confirm-dedicated-test-document",
        confirmation,
        "--confirm-dedicated-test-novel",
        novel_confirmation,
        "--duration-minutes",
        duration_minutes,
        "--output-dir",
        str(output),
    ]
    if include_real_confirmations:
        argv.extend(
            [
                "--confirm-real-run",
                runner.REAL_RUN_CONFIRMATION,
                "--confirm-baseline-restore",
                runner.RESTORE_CONFIRMATION,
                "--confirm-private-work-dir-local-non-synced",
                runner.PRIVATE_WORK_DIR_CONFIRMATION,
            ]
        )
    if listening_record is not None:
        argv.extend(["--listening-record", str(listening_record)])
    if resume:
        argv.append("--resume")
    if run_id is not None:
        argv.extend(["--run-id", run_id])
    return argv


def _result(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "evidence" / "result.json").read_text("utf-8"))


class FakeExecutor:
    def __init__(
        self,
        *,
        automatic_error: BaseException | None = None,
        restore_error: BaseException | None = None,
    ) -> None:
        self.automatic_error = automatic_error
        self.restore_error = restore_error
        self.calls: list[str] = []
        self.automatic_case: runner.ChapterCase | None = None
        self.manual_case: runner.ChapterCase | None = None
        self.technical_fixture: runner.ChapterFixture | None = None
        self.checkpoint: (
            Any
        ) = None
        self.fence = runner.RecoveryFence(
            draft_version=7,
            content_hash=_sha256(BASELINE_TEXT),
            current_edition_id=BASELINE_EDITION,
            current_script_version_id=BASELINE_SCRIPT,
            pointer_version=4,
        )

    def set_recovery_checkpoint(self, checkpoint: Any) -> None:
        self.checkpoint = checkpoint

    def capture_baseline(self, config: runner.RunnerConfig) -> runner.BaselineSnapshot:
        del config
        self.calls.append("capture")
        return runner.BaselineSnapshot(
            draft_version=7,
            content_hash=_sha256(BASELINE_TEXT),
            content_markdown=BASELINE_TEXT,
            base_revision_id=BASE_REVISION,
            pointer_version=4,
            current_edition_id=BASELINE_EDITION,
            current_script_version_id=BASELINE_SCRIPT,
            edition_history_count=1,
        )

    def run_automatic(
        self,
        config: runner.RunnerConfig,
        case: runner.ChapterCase,
    ) -> runner.ChainOutcome:
        del config
        self.automatic_case = case
        self.calls.append("automatic")
        if self.automatic_error is not None:
            raise self.automatic_error
        self.fence = runner.RecoveryFence(
            draft_version=8,
            content_hash="1" * 64,
            current_edition_id=EDITION_AUTO,
            current_script_version_id=SCRIPT_AUTO,
            pointer_version=5,
        )
        return runner.ChainOutcome(
            request_id=REQUEST_AUTO,
            script_version_id=SCRIPT_AUTO,
            edition_id=EDITION_AUTO,
            edition_fingerprint="8" * 64,
            approval_kind="auto_no_blockers",
            initial_blocker_count=0,
            final_blocker_count=0,
            edition_count_for_request=1,
            manifest_revision=2,
            narrator_segment_count=2,
            character_segment_count=4,
            distinct_character_count=2,
            distinct_voice_version_count=3,
            uncached_nano_job_count=6,
            model_run_fingerprints=("a" * 64,),
        )

    def run_manual(
        self,
        config: runner.RunnerConfig,
        case: runner.ChapterCase,
    ) -> runner.ChainOutcome:
        del config
        self.manual_case = case
        self.calls.append("manual")
        self.fence = runner.RecoveryFence(
            draft_version=9,
            content_hash="2" * 64,
            current_edition_id=EDITION_MANUAL,
            current_script_version_id=SCRIPT_MANUAL,
            pointer_version=6,
        )
        return runner.ChainOutcome(
            request_id=REQUEST_MANUAL,
            script_version_id=SCRIPT_MANUAL,
            edition_id=EDITION_MANUAL,
            edition_fingerprint="9" * 64,
            approval_kind="manual_after_review",
            initial_blocker_count=1,
            final_blocker_count=0,
            edition_count_for_request=1,
            manifest_revision=3,
            narrator_segment_count=2,
            character_segment_count=4,
            distinct_character_count=2,
            distinct_voice_version_count=3,
            uncached_nano_job_count=6,
            model_run_fingerprints=("c" * 64,),
        )

    def run_technical_checks(
        self,
        config: runner.RunnerConfig,
        fixture: runner.ChapterFixture,
    ) -> runner.TechnicalOutcome:
        self.technical_fixture = fixture
        self.calls.append("technical")
        return _valid_technical_outcome(
            stability_elapsed_seconds=config.duration_minutes * 60,
        )

    def capture_recovery_fence(
        self,
        config: runner.RunnerConfig,
    ) -> runner.RecoveryFence:
        del config
        return self.fence

    def restore_baseline(
        self,
        config: runner.RunnerConfig,
        baseline: runner.BaselineSnapshot,
        fence: runner.RecoveryFence,
        write_intent: runner.RecoveryWriteIntent | None,
    ) -> runner.RecoveryOutcome:
        del config, baseline, fence, write_intent
        self.calls.append("restore")
        if self.restore_error is not None:
            raise self.restore_error
        return runner.RecoveryOutcome(
            restored_draft_version=10,
            restored_content_hash=_sha256(BASELINE_TEXT),
            restored_current_edition_id=BASELINE_EDITION,
            restored_current_script_version_id=BASELINE_SCRIPT,
            pointer_version_after_restore=5,
            append_only_history_retained=True,
            new_authoritative_record_count=12,
        )


def _valid_technical_outcome(
    **changes: object,
) -> runner.TechnicalOutcome:
    outcome = runner.TechnicalOutcome(
        stability_elapsed_seconds=1800.0,
        chapter_audio_duration_seconds=100.0,
        request_to_ready_seconds=42.0,
        time_to_first_audio_ms=1200,
        peak_memory_bytes=2_000_000_000,
        range_status_codes=(200, 206, 304, 416),
        seam_pairs_checked=3,
        seek_latest_wins=True,
        pending_gap_not_skipped=True,
        edit_actions_created_tts_writes=0,
        browser_viewports=runner.ALLOWED_VIEWPORTS,
        browser_assistant_modes=("collapsed", "expanded"),
        browser_console_error_count=0,
        browser_overlap_count=0,
        sidecar_restart_count=0,
        health_failure_count=0,
        listening_output_hashes=("b" * 64,),
        collector_collected_at="2026-08-27T12:00:00Z",
        progressive_playback_gate_passed=None,
        host_paging_observed=False,
        pageout_delta=0,
        swapout_delta=0,
        memory_baseline_median_bytes=1_800_000_000,
        memory_tail_median_bytes=1_900_000_000,
        memory_growth_bytes=100_000_000,
        memory_growth_limit_bytes=134_217_728,
        sidecar_memory_growth_observed=False,
        qwenpaw_slowdown_observed=False,
        evidence_class="local_operator_observation",
        evidence_root_sha256="d" * 64,
    )
    return replace(outcome, **changes)


def test_validate_only_is_default_network_free_and_writes_redacted_0600_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    factory_called = False

    def forbidden_factory(config: runner.RunnerConfig) -> FakeExecutor:
        nonlocal factory_called
        del config
        factory_called = True
        raise AssertionError("validate-only must not create an executor")

    exit_code = runner.main(
        _arguments(tmp_path, fixture), executor_factory=forbidden_factory
    )

    assert exit_code == 0
    assert factory_called is False
    result = _result(tmp_path)
    assert result["status"] == "VALIDATED_ONLY"
    assert result["automatic_chain"] == {"state": "NOT_RUN"}
    assert result["manual_chain"] == {"state": "NOT_RUN"}
    assert result["human_listening"] == {"state": "PENDING"}
    assert "run_id" not in result
    assert len(result["run_fingerprint_sha256"]) == 64
    assert not (tmp_path / "private-work" / "recovery.json").exists()
    assert stat.S_IMODE((tmp_path / "private-work").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "evidence").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "evidence" / "result.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(
        (tmp_path / "evidence" / "listening-template.md").stat().st_mode
    ) == 0o600
    evidence = (tmp_path / "evidence" / "result.json").read_text("utf-8")
    template = (tmp_path / "evidence" / "listening-template.md").read_text("utf-8")
    console = capsys.readouterr().out
    for forbidden in (AUTO_TEXT, MANUAL_TEXT, BASELINE_TEXT, str(tmp_path)):
        assert forbidden not in evidence
        assert forbidden not in template
        assert forbidden not in console


def test_dedicated_document_confirmation_must_exactly_match_before_executor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    called = False

    def factory(config: runner.RunnerConfig) -> FakeExecutor:
        nonlocal called
        del config
        called = True
        return FakeExecutor()

    exit_code = runner.main(
        _arguments(tmp_path, fixture, confirmation=OTHER_DOCUMENT_ID),
        executor_factory=factory,
    )

    assert exit_code == 2
    assert called is False
    assert "DEDICATED_DOCUMENT_CONFIRMATION_MISMATCH" in capsys.readouterr().out
    assert not (tmp_path / "evidence").exists()


def test_dedicated_novel_confirmation_must_exactly_match_before_executor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    exit_code = runner.main(
        _arguments(
            tmp_path,
            fixture,
            novel_confirmation="33333333-3333-4333-8333-333333333333",
        )
    )

    assert exit_code == 2
    assert "DEDICATED_NOVEL_CONFIRMATION_MISMATCH" in capsys.readouterr().out
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize(
    "api_base",
    [
        "https://127.0.0.1:18088/api/ai-novel-world-2026",
        "http://0.0.0.0:18088/api/ai-novel-world-2026",
        "http://example.test:18088/api/ai-novel-world-2026",
        "http://user:secret@127.0.0.1:18088/api/ai-novel-world-2026",
        "http://127.0.0.1:18088/api/ai-novel-world-2026?token=secret",
    ],
)
def test_api_base_is_strict_loopback_without_credentials_or_query(
    tmp_path: Path,
    api_base: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    assert runner.main(_arguments(tmp_path, fixture, api_base=api_base)) == 2
    output = capsys.readouterr().out
    assert "API_BASE_NOT_LOOPBACK" in output
    assert "secret" not in output


def test_private_work_dir_must_be_absolute_external_and_disjoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    monkeypatch.chdir(tmp_path)
    relative_args = _arguments(
        tmp_path,
        fixture,
        private_work_dir=Path("relative-private"),
    )
    assert runner.main(relative_args) == 2

    inside_repository = runner.REPOSITORY_ROOT / "not-created-t4k-private"
    assert runner.main(
        _arguments(tmp_path, fixture, private_work_dir=inside_repository)
    ) == 2

    private = tmp_path / "same"
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            private_work_dir=private,
            output_dir=private / "evidence",
        )
    ) == 2


def test_formal_cli_rejects_stability_duration_below_thirty_minutes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    assert runner.main(_arguments(tmp_path, fixture, duration_minutes="29.999")) == 2
    assert "STABILITY_DURATION_TOO_SHORT" in capsys.readouterr().out


def test_fixture_rejects_any_viewport_other_than_the_two_approved_desktops(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _fixture_payload()
    payload["required_viewports"] = [
        {"width": 1280, "height": 720},
        {"width": 1920, "height": 1080},
        {"width": 2560, "height": 1440},
    ]
    fixture = _write_fixture(tmp_path / "fixture.json", payload)

    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_VIEWPORTS_INVALID" in capsys.readouterr().out


def test_fixture_v2_rejects_runtime_source_block_keys_and_bad_stable_locator(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _fixture_payload()
    correction = payload["chapter_cases"][1]["corrections"][0]
    correction["source_block_key"] = f"sb1_{'a' * 64}"
    fixture = _write_fixture(tmp_path / "runtime-key.json", payload)
    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_CORRECTION_INVALID" in capsys.readouterr().out

    payload = _fixture_payload()
    payload["chapter_cases"][1]["corrections"][0][
        "expected_source_local_hash"
    ] = "a" * 64
    fixture = _write_fixture(tmp_path / "bad-locator.json", payload)
    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_CORRECTION_SOURCE_MISMATCH" in capsys.readouterr().out


def test_fixture_v2_requires_two_characters_three_voices_and_uncached_nano(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _fixture_payload()
    payload["minimum_character_speakers"] = 1
    payload["minimum_distinct_voice_versions"] = 2
    payload["require_uncached_nano_model_run"] = False
    fixture = _write_fixture(tmp_path / "weak-real-chain.json", payload)

    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_REAL_CHAIN_REQUIREMENTS_INVALID" in capsys.readouterr().out


def test_fixture_v2_rejects_unit_sized_text_masquerading_as_a_chapter(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _fixture_payload()
    payload["chapter_cases"][0]["source_text"] = "过短章节。"
    payload["chapter_cases"][0]["source_sha256"] = _sha256("过短章节。")
    fixture = _write_fixture(tmp_path / "short.json", payload)

    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_CHAPTER_TOO_SHORT" in capsys.readouterr().out


def test_fixture_rejects_unknown_taxonomy_and_false_product_eligibility(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _fixture_payload()
    payload["chapter_cases"][1]["expected_initial_blocker_codes"] = [
        "UNKNOWN_SPEAKER"
    ]
    fixture = _write_fixture(tmp_path / "unknown.json", payload)
    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_CASE_INVALID" in capsys.readouterr().out

    payload = _fixture_payload()
    payload["voice_scope"] = "production_approved"
    payload["production_eligible"] = False
    fixture = _write_fixture(tmp_path / "scope.json", payload)
    assert runner.main(_arguments(tmp_path, fixture)) == 2
    assert "FIXTURE_VOICE_SCOPE_INVALID" in capsys.readouterr().out


def test_real_mode_requires_both_fixed_confirmations_before_executor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    called = False

    def factory(config: runner.RunnerConfig) -> FakeExecutor:
        nonlocal called
        del config
        called = True
        return FakeExecutor()

    assert runner.main(
        _arguments(tmp_path, fixture, mode="real"), executor_factory=factory
    ) == 2
    assert called is False
    assert "REAL_MODE_CONFIRMATION_REQUIRED" in capsys.readouterr().out


def test_cli_real_mode_has_no_builtin_write_executor(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        )
    ) == 2
    result = _result(tmp_path)
    assert result["status"] == "FAILED"
    assert result["error_codes"] == ["REAL_EXECUTOR_UNAVAILABLE"]
    assert result["recovery"]["record_created"] is False


def test_real_executor_is_wrapped_in_recovery_and_cannot_pass_without_listening(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    executor = FakeExecutor()

    exit_code = runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            duration_minutes="0.01",
            include_real_confirmations=True,
        ),
        executor_factory=lambda config: executor,
        minimum_duration_minutes=0.01,
    )

    assert exit_code == 3
    assert executor.calls == [
        "capture",
        "automatic",
        "manual",
        "technical",
        "restore",
    ]
    assert executor.automatic_case is not None
    assert executor.manual_case is not None
    assert executor.technical_fixture is not None
    assert executor.automatic_case.source_text.startswith(AUTO_TEXT)
    assert executor.manual_case.source_text.startswith(MANUAL_TEXT)
    assert executor.automatic_case.source_text != AUTO_TEXT
    assert executor.manual_case.source_text != MANUAL_TEXT
    assert executor.automatic_case.source_sha256 == _sha256(
        executor.automatic_case.source_text
    )
    assert executor.manual_case.source_sha256 == _sha256(
        executor.manual_case.source_text
    )
    assert executor.technical_fixture.automatic == executor.automatic_case
    assert executor.technical_fixture.manual == executor.manual_case
    assert executor.manual_case.corrections == runner.load_fixture(
        fixture,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    ).manual.corrections
    result = _result(tmp_path)
    assert result["schema_version"] == "moss-tts-chapter-e2e-result/2.3"
    assert result["status"] == "HUMAN_LISTENING_PENDING"
    assert result["automatic_chain"]["approval_kind"] == "auto_no_blockers"
    assert result["manual_chain"]["approval_kind"] == "manual_after_review"
    assert result["automatic_chain"]["edition_id_sha256"] == _sha256(
        str(EDITION_AUTO)
    )
    assert result["automatic_chain"]["edition_fingerprint_sha256"] == "8" * 64
    assert result["manual_chain"]["edition_id_sha256"] == _sha256(
        str(EDITION_MANUAL)
    )
    assert result["manual_chain"]["edition_fingerprint_sha256"] == "9" * 64
    assert result["automatic_chain"]["edition_id_sha256"] != (
        result["automatic_chain"]["edition_fingerprint_sha256"]
    )
    assert result["technical_checks"]["range_status_codes"] == [200, 206, 304, 416]
    assert result["technical_checks"]["edit_actions_created_tts_writes"] == 0
    assert result["technical_checks"]["performance_gate"] == {
        "black_box_rtf_limit": 1.0,
        "black_box_rtf_passed": True,
        "progressive_playback_alternative": (
            "not_eligible_without_strict_ready_window_evidence"
        ),
        "host_paging_observed": False,
        "host_paging_interpretation": "whole_host_telemetry_only",
        "pageout_delta": 0,
        "swapout_delta": 0,
        "memory_baseline_median_bytes": 1_800_000_000,
        "memory_tail_median_bytes": 1_900_000_000,
        "memory_growth_bytes": 100_000_000,
        "memory_growth_limit_bytes": 134_217_728,
        "sidecar_memory_growth_observed": False,
        "qwenpaw_slowdown_observed": False,
        "sidecar_peak_memory_limit_bytes": (
            runner.SIDECAR_PEAK_MEMORY_LIMIT_BYTES
        ),
        "memory_safety_passed": True,
    }
    assert result["recovery"] == {
        "record_created": True,
        "working_copy_content_restored": True,
        "author_visible_edition_restored": True,
        "append_only_history_retained": True,
        "new_authoritative_record_count": 12,
        "recovery_required": False,
    }
    recovery_record = json.loads(
        (tmp_path / "private-work" / "recovery.json").read_text("utf-8")
    )
    assert recovery_record["schema_version"] == runner.RECOVERY_SCHEMA
    assert recovery_record["state"] == "LISTENING_PENDING"
    assert recovery_record["sealed_technical_result"]["result"][
        "result_schema_version"
    ] == runner.RESULT_SCHEMA
    assert recovery_record["restoration_evidence"] == {
        "working_copy_content_restored": True,
        "author_visible_edition_restored": True,
        "append_only_history_retained": True,
        "new_authoritative_record_count": 12,
    }
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        AUTO_TEXT,
        MANUAL_TEXT,
        BASELINE_TEXT,
        str(tmp_path),
        NOVEL_ID,
        DOCUMENT_ID,
        str(REQUEST_AUTO),
        str(EDITION_AUTO),
    ):
        assert forbidden not in serialized


def test_same_run_failed_listening_preserves_exact_restoration_evidence(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    run_id = str(REQUEST_AUTO)
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            run_id=run_id,
        ),
        executor_factory=lambda _config: FakeExecutor(),
        minimum_duration_minutes=0.01,
    ) == 3
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
        verdict="fail",
    )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            resume=True,
            run_id=run_id,
        ),
        recovery_executor_factory=lambda _config: (_ for _ in ()).throw(
            AssertionError("listening resume must not restore baseline twice")
        ),
        minimum_duration_minutes=0.01,
    ) == 2

    result = _result(tmp_path)
    assert result["status"] == "FAILED"
    assert result["error_codes"] == ["HUMAN_LISTENING_FAILED"]
    assert result["recovery"] == {
        "record_created": True,
        "working_copy_content_restored": True,
        "author_visible_edition_restored": True,
        "append_only_history_retained": True,
        "new_authoritative_record_count": 12,
        "recovery_required": False,
        "recovered_run_fingerprint_sha256": _sha256(run_id),
    }
    assert not (tmp_path / "private-work" / "recovery.json").exists()


def test_legacy_3_0_listening_resume_does_not_invent_restoration_evidence(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    run_id = str(REQUEST_AUTO)
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            run_id=run_id,
        ),
        executor_factory=lambda _config: FakeExecutor(),
        minimum_duration_minutes=0.01,
    ) == 3
    recovery_path = tmp_path / "private-work" / "recovery.json"
    legacy = json.loads(recovery_path.read_text("utf-8"))
    legacy["schema_version"] = runner.LEGACY_RECOVERY_SCHEMA
    legacy.pop("restoration_evidence")
    sealed = legacy["sealed_technical_result"]
    assert isinstance(sealed, dict)
    sealed_result = sealed["result"]
    assert isinstance(sealed_result, dict)
    sealed_result.pop("result_schema_version")
    sealed["self_sha256"] = hashlib.sha256(
        json.dumps(
            sealed_result,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _rewrite_recovery_payload(recovery_path, legacy)
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
        verdict="fail",
    )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            resume=True,
            run_id=run_id,
        ),
        recovery_executor_factory=lambda _config: (_ for _ in ()).throw(
            AssertionError("legacy listening resume must not restore twice")
        ),
        minimum_duration_minutes=0.01,
    ) == 2

    resumed = _result(tmp_path)
    assert resumed["error_codes"] == ["RECOVERY_EVIDENCE_SCHEMA_STALE"]
    recovery = resumed["recovery"]
    assert recovery["working_copy_content_restored"] is False
    assert recovery["author_visible_edition_restored"] is False
    assert recovery["append_only_history_retained"] is False
    assert recovery["new_authoritative_record_count"] == 0


def test_technical_gate_accepts_exact_black_box_rtf_boundary() -> None:
    outcome = _valid_technical_outcome(
        chapter_audio_duration_seconds=100.0,
        request_to_ready_seconds=100.0,
    )

    assert runner._validate_technical(outcome, required_seconds=1800.0) is outcome
    evidence = runner._technical_evidence(outcome)
    assert evidence["black_box_rtf"] == 1.0
    assert evidence["performance_gate"]["black_box_rtf_passed"] is True


@pytest.mark.parametrize(
    "progressive_claim",
    (None, False, True),
)
def test_technical_gate_rejects_rtf_above_one_without_boolean_waiver(
    progressive_claim: bool | None,
) -> None:
    outcome = _valid_technical_outcome(
        chapter_audio_duration_seconds=100.0,
        request_to_ready_seconds=100.000001,
        progressive_playback_gate_passed=progressive_claim,
    )

    with pytest.raises(
        runner.RunnerError,
        match="^TECHNICAL_RTF_GATE_FAILED$",
    ):
        runner._validate_technical(outcome, required_seconds=1800.0)


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        (
            {"host_paging_observed": None},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_MISSING",
        ),
        (
            {"qwenpaw_slowdown_observed": None},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_MISSING",
        ),
        (
            {"memory_growth_bytes": None},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_MISSING",
        ),
        (
            {"sidecar_memory_growth_observed": None},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_MISSING",
        ),
        (
            {"qwenpaw_slowdown_observed": True},
            "TECHNICAL_MEMORY_SAFETY_GATE_FAILED",
        ),
        (
            {
                "memory_tail_median_bytes": 2_000_000_000,
                "memory_growth_bytes": 200_000_000,
                "sidecar_memory_growth_observed": True,
            },
            "TECHNICAL_MEMORY_SAFETY_GATE_FAILED",
        ),
        (
            {
                "peak_memory_bytes": (
                    runner.SIDECAR_PEAK_MEMORY_LIMIT_BYTES + 1
                )
            },
            "TECHNICAL_MEMORY_SAFETY_GATE_FAILED",
        ),
        (
            {"host_paging_observed": float("nan")},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {"qwenpaw_slowdown_observed": float("inf")},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {"pageout_delta": True},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {"memory_growth_bytes": -1},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {"memory_growth_limit_bytes": 134_217_729},
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {
                "memory_baseline_median_bytes": 2_000_000_001,
                "memory_growth_bytes": 0,
            },
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
        (
            {
                "memory_tail_median_bytes": 2_000_000_001,
                "memory_growth_bytes": 200_000_001,
                "sidecar_memory_growth_observed": True,
            },
            "TECHNICAL_MEMORY_SAFETY_EVIDENCE_INVALID",
        ),
    ),
)
def test_technical_memory_safety_gate_is_fail_closed(
    changes: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(runner.RunnerError, match=f"^{code}$"):
        runner._validate_technical(
            _valid_technical_outcome(**changes),
            required_seconds=1800.0,
        )


def test_host_paging_true_remains_nonblocking_whole_host_telemetry() -> None:
    outcome = _valid_technical_outcome(
        host_paging_observed=True,
        pageout_delta=1,
        peak_memory_bytes=runner.SIDECAR_PEAK_MEMORY_LIMIT_BYTES,
    )

    assert runner._validate_technical(
        outcome,
        required_seconds=1800.0,
    ) is outcome
    performance = runner._technical_evidence(outcome)["performance_gate"]
    assert performance == {
        "black_box_rtf_limit": 1.0,
        "black_box_rtf_passed": True,
        "progressive_playback_alternative": (
            "not_eligible_without_strict_ready_window_evidence"
        ),
        "host_paging_observed": True,
        "host_paging_interpretation": "whole_host_telemetry_only",
        "pageout_delta": 1,
        "swapout_delta": 0,
        "memory_baseline_median_bytes": 1_800_000_000,
        "memory_tail_median_bytes": 1_900_000_000,
        "memory_growth_bytes": 100_000_000,
        "memory_growth_limit_bytes": 134_217_728,
        "sidecar_memory_growth_observed": False,
        "qwenpaw_slowdown_observed": False,
        "sidecar_peak_memory_limit_bytes": (
            runner.SIDECAR_PEAK_MEMORY_LIMIT_BYTES
        ),
        "memory_safety_passed": True,
    }


@pytest.mark.parametrize(
    "value",
    (float("nan"), float("inf"), -float("inf")),
)
def test_technical_progressive_claim_rejects_non_boolean_numbers(
    value: float,
) -> None:
    with pytest.raises(
        runner.RunnerError,
        match="^TECHNICAL_PROGRESSIVE_EVIDENCE_INVALID$",
    ):
        runner._validate_technical(
            _valid_technical_outcome(
                progressive_playback_gate_passed=value,
            ),
            required_seconds=1800.0,
        )


@pytest.mark.parametrize(
    ("changes", "required_seconds"),
    (
        ({"stability_elapsed_seconds": float("nan")}, 1800.0),
        ({"stability_elapsed_seconds": float("inf")}, 1800.0),
        ({"chapter_audio_duration_seconds": float("nan")}, 1800.0),
        ({"chapter_audio_duration_seconds": float("inf")}, 1800.0),
        ({"chapter_audio_duration_seconds": 0.0}, 1800.0),
        ({"request_to_ready_seconds": float("nan")}, 1800.0),
        ({"request_to_ready_seconds": float("inf")}, 1800.0),
        ({"request_to_ready_seconds": -0.000001}, 1800.0),
        ({"peak_memory_bytes": float("nan")}, 1800.0),
        ({"peak_memory_bytes": float("inf")}, 1800.0),
        ({"peak_memory_bytes": -1}, 1800.0),
    ),
)
def test_technical_numeric_inputs_reject_missing_boundaries_and_non_finite(
    changes: dict[str, object],
    required_seconds: float,
) -> None:
    with pytest.raises(runner.RunnerError, match="^TECHNICAL_GATE_FAILED$"):
        runner._validate_technical(
            _valid_technical_outcome(**changes),
            required_seconds=required_seconds,
        )


def test_chain_gate_requires_multicharacter_voices_and_uncached_nano(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    class WeakChainExecutor(FakeExecutor):
        def run_automatic(
            self,
            config: runner.RunnerConfig,
            case: runner.ChapterCase,
        ) -> runner.ChainOutcome:
            return replace(
                super().run_automatic(config, case),
                distinct_character_count=1,
                distinct_voice_version_count=2,
                uncached_nano_job_count=0,
            )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=lambda config: WeakChainExecutor(),
    ) == 2
    assert _result(tmp_path)["error_codes"] == ["CHAIN_GATE_FAILED"]


def test_recovery_gate_rejects_a_false_author_visible_restore(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    class FalseRestoreExecutor(FakeExecutor):
        def restore_baseline(
            self,
            config: runner.RunnerConfig,
            baseline: runner.BaselineSnapshot,
            fence: runner.RecoveryFence,
            write_intent: runner.RecoveryWriteIntent | None,
        ) -> runner.RecoveryOutcome:
            return replace(
                super().restore_baseline(
                    config,
                    baseline,
                    fence,
                    write_intent,
                ),
                restored_current_edition_id=EDITION_AUTO,
            )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=lambda config: FalseRestoreExecutor(),
    ) == 4
    result = _result(tmp_path)
    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["error_codes"] == ["RECOVERY_GATE_FAILED"]


def test_failure_and_restore_failure_preserve_0600_recovery_without_leaking_evidence(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    executor = FakeExecutor(
        automatic_error=RuntimeError(f"private failure: {BASELINE_TEXT} {tmp_path}"),
        restore_error=RuntimeError(f"restore failure: {BASELINE_TEXT} {tmp_path}"),
    )

    exit_code = runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=lambda config: executor,
    )

    assert exit_code == 4
    recovery_path = tmp_path / "private-work" / "recovery.json"
    assert recovery_path.is_file()
    assert stat.S_IMODE(recovery_path.stat().st_mode) == 0o600
    recovery = json.loads(recovery_path.read_text("utf-8"))
    assert recovery["state"] == "RECOVERY_REQUIRED"
    assert recovery["baseline"]["content_markdown"] == BASELINE_TEXT
    result = _result(tmp_path)
    assert result["status"] == "RECOVERY_REQUIRED"
    assert set(result["error_codes"]) == {
        "BASELINE_RESTORE_FAILED",
        "EXECUTION_FAILED",
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert BASELINE_TEXT not in serialized
    assert str(tmp_path) not in serialized


def test_keyboard_interrupt_restores_baseline_and_returns_130(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    executor = FakeExecutor(automatic_error=KeyboardInterrupt())

    exit_code = runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=lambda config: executor,
    )

    assert exit_code == 130
    assert executor.calls == ["capture", "automatic", "restore"]
    assert _result(tmp_path)["status"] == "INTERRUPTED"
    assert not (tmp_path / "private-work" / "recovery.json").exists()


def test_prewrite_failure_can_clear_pending_intent_at_exact_old_fence(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    class PrewriteFailureExecutor(FakeExecutor):
        def run_automatic(
            self,
            config: runner.RunnerConfig,
            case: runner.ChapterCase,
        ) -> runner.ChainOutcome:
            del config, case
            self.calls.append("automatic")
            next_fence = runner.RecoveryFence(
                draft_version=self.fence.draft_version + 1,
                content_hash=self.fence.content_hash,
                current_edition_id=self.fence.current_edition_id,
                current_script_version_id=self.fence.current_script_version_id,
                pointer_version=self.fence.pointer_version,
            )
            intent = runner.RecoveryWriteIntent(
                operation_kind="DRAFT_WRITE",
                operation_fingerprint_sha256="a" * 64,
                old_fence=self.fence,
                next_fence=next_fence,
            )
            self.checkpoint(self.fence, intent)
            raise runner.RunnerError("SIMULATED_PREWRITE_FAILURE")

        def restore_baseline(
            self,
            config: runner.RunnerConfig,
            baseline: runner.BaselineSnapshot,
            fence: runner.RecoveryFence,
            write_intent: runner.RecoveryWriteIntent | None,
        ) -> runner.RecoveryOutcome:
            del config, baseline
            self.calls.append("restore")
            assert write_intent is not None
            assert write_intent.old_fence == fence
            self.checkpoint(fence, None)
            return runner.RecoveryOutcome(
                restored_draft_version=fence.draft_version + 1,
                restored_content_hash=fence.content_hash,
                restored_current_edition_id=fence.current_edition_id,
                restored_current_script_version_id=(
                    fence.current_script_version_id
                ),
                pointer_version_after_restore=fence.pointer_version,
                append_only_history_retained=True,
                new_authoritative_record_count=1,
            )

    executor = PrewriteFailureExecutor()
    exit_code = runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=lambda _config: executor,
    )

    assert exit_code == 2
    assert executor.calls == ["capture", "automatic", "restore"]
    assert not (tmp_path / "private-work" / "recovery.json").exists()
    assert _result(tmp_path)["error_codes"] == ["SIMULATED_PREWRITE_FAILURE"]


def test_resume_can_clear_pending_intent_at_exact_old_fence(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    class InterruptedBeforeWrite(FakeExecutor):
        def run_automatic(
            self,
            config: runner.RunnerConfig,
            case: runner.ChapterCase,
        ) -> runner.ChainOutcome:
            del config, case
            self.calls.append("automatic")
            intent = runner.RecoveryWriteIntent(
                operation_kind="DRAFT_WRITE",
                operation_fingerprint_sha256="a" * 64,
                old_fence=self.fence,
                next_fence=runner.RecoveryFence(
                    draft_version=self.fence.draft_version + 1,
                    content_hash=self.fence.content_hash,
                    current_edition_id=self.fence.current_edition_id,
                    current_script_version_id=(
                        self.fence.current_script_version_id
                    ),
                    pointer_version=self.fence.pointer_version,
                ),
            )
            self.checkpoint(self.fence, intent)
            raise runner.RunnerError("SIMULATED_PREWRITE_FAILURE")

        def restore_baseline(
            self,
            config: runner.RunnerConfig,
            baseline: runner.BaselineSnapshot,
            fence: runner.RecoveryFence,
            write_intent: runner.RecoveryWriteIntent | None,
        ) -> runner.RecoveryOutcome:
            del config, baseline, fence, write_intent
            self.calls.append("restore")
            raise runner.RunnerError("SIMULATED_RESTORE_HOLD")

    interrupted = InterruptedBeforeWrite()
    real_args = _arguments(
        tmp_path,
        fixture,
        mode="real",
        include_real_confirmations=True,
        run_id=str(BASE_REVISION),
    )
    assert runner.main(
        real_args,
        executor_factory=lambda _config: interrupted,
    ) == 4
    assert (tmp_path / "private-work" / "recovery.json").is_file()

    class ResumeAtOldFence(FakeExecutor):
        def restore_baseline(
            self,
            config: runner.RunnerConfig,
            baseline: runner.BaselineSnapshot,
            fence: runner.RecoveryFence,
            write_intent: runner.RecoveryWriteIntent | None,
        ) -> runner.RecoveryOutcome:
            del config, baseline
            self.calls.append("restore")
            assert write_intent is not None
            assert write_intent.old_fence == fence
            self.checkpoint(fence, None)
            return runner.RecoveryOutcome(
                restored_draft_version=fence.draft_version + 1,
                restored_content_hash=fence.content_hash,
                restored_current_edition_id=fence.current_edition_id,
                restored_current_script_version_id=(
                    fence.current_script_version_id
                ),
                pointer_version_after_restore=fence.pointer_version,
                append_only_history_retained=True,
                new_authoritative_record_count=1,
            )

    resumed = ResumeAtOldFence()
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        recovery_executor_factory=lambda _config: resumed,
    ) == 0
    assert resumed.calls == ["restore"]
    assert not (tmp_path / "private-work" / "recovery.json").exists()
    assert _result(tmp_path)["status"] == "BASELINE_RESTORED"


def test_existing_recovery_record_blocks_a_new_run_and_resume_only_restores(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    failed = FakeExecutor(
        automatic_error=RuntimeError("generation failed"),
        restore_error=RuntimeError("restore failed"),
    )
    real_args = _arguments(
        tmp_path,
        fixture,
        mode="real",
        include_real_confirmations=True,
        run_id=str(BASE_REVISION),
    )
    assert runner.main(
        real_args,
        executor_factory=lambda config: failed,
    ) == 4
    recovery_path = tmp_path / "private-work" / "recovery.json"
    original_recovery = recovery_path.read_bytes()

    blocked = FakeExecutor()
    assert runner.main(
        real_args,
        executor_factory=lambda config: blocked,
    ) == 2
    assert blocked.calls == []
    assert recovery_path.read_bytes() == original_recovery
    assert _result(tmp_path)["error_codes"] == ["RECOVERY_RECORD_EXISTS"]

    restoring = FakeExecutor()
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        executor_factory=lambda _config: (_ for _ in ()).throw(
            AssertionError("resume must not construct the normal executor")
        ),
        recovery_executor_factory=lambda config: restoring,
    ) == 0
    assert restoring.calls == ["restore"]
    assert not recovery_path.exists()
    result = _result(tmp_path)
    assert result["status"] == "BASELINE_RESTORED"
    assert result["recovery"]["working_copy_content_restored"] is True
    assert result["recovery"]["author_visible_edition_restored"] is True
    assert "recovered_run_fingerprint_sha256" in result["recovery"]


def test_resume_is_rejected_in_validate_only_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    assert runner.main(_arguments(tmp_path, fixture, resume=True)) == 2
    assert "RESUME_REQUIRES_REAL_MODE" in capsys.readouterr().out


def test_explicit_run_id_is_preserved_for_operator_envelope_binding(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    argv = [
        *_arguments(tmp_path, fixture),
        "--run-id",
        str(REQUEST_AUTO),
    ]
    config = runner.build_runner_config(runner.build_parser().parse_args(argv))
    assert config.run_id == REQUEST_AUTO

    argv[-1] = str(UUID(int=0))
    with pytest.raises(runner.RunnerError, match="RUN_ID_INVALID"):
        runner.build_runner_config(runner.build_parser().parse_args(argv))


def test_pass_candidate_requires_a_strict_positive_human_listening_record(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
    )
    executor = FakeExecutor()

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            run_id=str(REQUEST_AUTO),
        ),
        executor_factory=lambda config: executor,
    ) == 0
    result = _result(tmp_path)
    assert result["status"] == "PASS_CANDIDATE"
    assert result["human_listening"]["state"] == "PASS"
    assert result["human_listening"]["reviewer_fingerprint_sha256"] == _sha256(
        "reviewer-t4k-01"
    )
    assert "reviewer-t4k-01" not in json.dumps(result)


def test_listening_record_must_name_this_run_outputs_exactly(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
        output_hashes=("c" * 64,),
    )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            run_id=str(REQUEST_AUTO),
        ),
        executor_factory=lambda config: FakeExecutor(),
    ) == 2
    assert _result(tmp_path)["error_codes"] == ["LISTENING_OUTPUT_MISMATCH"]


def test_finalization_replays_evidence_only_after_second_file_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
    )
    original_write = runner._atomic_write
    failed_once = False

    def fail_second_evidence_file(
        directory: runner._SecureDirectory,
        name: str,
        data: bytes,
        code: str,
        **kwargs: object,
    ) -> None:
        nonlocal failed_once
        if name == "listening-template.md" and not failed_once:
            failed_once = True
            raise runner.RunnerError("EVIDENCE_WRITE_FAILED")
        original_write(directory, name, data, code, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "_atomic_write", fail_second_evidence_file)
    argv = _arguments(
        tmp_path,
        fixture,
        mode="real",
        include_real_confirmations=True,
        listening_record=listening,
        run_id=str(REQUEST_AUTO),
    )

    assert runner.main(
        argv,
        executor_factory=lambda _config: FakeExecutor(),
    ) == 2
    recovery_path = tmp_path / "private-work" / "recovery.json"
    pending = json.loads(recovery_path.read_text("utf-8"))
    assert pending["state"] == "FINALIZATION_PENDING"
    assert (tmp_path / "evidence" / "result.json").is_file()
    factories: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            run_id=str(REQUEST_AUTO),
            resume=True,
        ),
        executor_factory=lambda _config: factories.append("normal")
        or FakeExecutor(),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
    ) == 0

    assert factories == []
    assert not recovery_path.exists()
    assert _result(tmp_path)["status"] == "PASS_CANDIDATE"


def test_finalized_claim_can_finish_cleanup_after_unlink_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
    )
    original_unlink = runner._unlink_secure
    failed_once = False

    def fail_after_claim_finalized(
        directory: runner._SecureDirectory,
        name: str,
    ) -> None:
        nonlocal failed_once
        if name == "recovery.json" and not failed_once:
            failed_once = True
            raise runner.RunnerError("RECOVERY_RECORD_DELETE_FAILED")
        original_unlink(directory, name)

    monkeypatch.setattr(runner, "_unlink_secure", fail_after_claim_finalized)
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            run_id=str(REQUEST_AUTO),
        ),
        executor_factory=lambda _config: FakeExecutor(),
    ) == 2
    recovery_path = tmp_path / "private-work" / "recovery.json"
    pending = json.loads(recovery_path.read_text("utf-8"))
    assert pending["state"] == "FINALIZATION_PENDING"
    finalized = runner.RecoveryClaimSnapshot(
        state="FINALIZED",
        recovery_generation=pending["generation"],
        latest_recovery_sha256=runner._recovery_record_sha256(pending),
    )
    observe, read, transitions = _claim_head_harness(finalized)
    factories: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            listening_record=listening,
            run_id=str(REQUEST_AUTO),
            resume=True,
        ),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 0

    assert factories == []
    assert transitions[-1].state == "FINALIZED"
    assert not recovery_path.exists()


def test_finalized_callback_output_swap_rolls_back_and_keeps_recovery(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    listening = _write_bound_listening_bundle(
        tmp_path,
        run_id=REQUEST_AUTO,
    )
    observe, read, transitions = _claim_head_harness(
        runner.RecoveryClaimSnapshot("PREPARED", 0, None)
    )
    output = tmp_path / "evidence"
    displaced_output = tmp_path / "evidence-displaced"
    swapped = False

    def swap_after_finalized(
        state: str,
        generation: int,
        digest: str,
    ) -> None:
        nonlocal swapped
        observe(state, generation, digest)
        if state == "FINALIZED" and not swapped:
            swapped = True
            output.rename(displaced_output)
            output.mkdir(mode=0o700)

    argv = _arguments(
        tmp_path,
        fixture,
        mode="real",
        include_real_confirmations=True,
        listening_record=listening,
        run_id=str(REQUEST_AUTO),
    )
    assert runner.main(
        argv,
        executor_factory=lambda _config: FakeExecutor(),
        recovery_state_observer=swap_after_finalized,
        recovery_claim_state_reader=read,
    ) == 2

    recovery_path = tmp_path / "private-work" / "recovery.json"
    assert recovery_path.is_file()
    assert json.loads(recovery_path.read_text("utf-8"))["state"] == (
        "FINALIZATION_PENDING"
    )
    assert transitions[-1].state == "FINALIZATION_PENDING"
    assert (displaced_output / "result.json").is_file()
    assert list(output.iterdir()) == []

    # Restore the exact physical output directory and prove that resume only
    # replays evidence publication; no normal or recovery executor is built.
    output.rmdir()
    displaced_output.rename(output)
    factories: list[str] = []
    assert runner.main(
        [*argv, "--resume"],
        executor_factory=lambda _config: factories.append("normal")
        or FakeExecutor(),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 0

    assert factories == []
    assert transitions[-1].state == "FINALIZED"
    assert not recovery_path.exists()
    assert _result(tmp_path)["status"] == "PASS_CANDIDATE"


def _valid_listening_payload() -> dict[str, object]:
    return {
        "schema_version": runner.LISTENING_SCHEMA,
        "reviewer_pseudonym": "reviewer-t4k-01",
        "reviewed_at": "2026-08-27T12:00:00Z",
        "verdict": "pass",
        "output_hashes": ["b" * 64],
        "checks": {
            "narrator_character_distinguishable": True,
            "voices_stable": True,
            "no_missing_or_repeated_text": True,
            "all_samples_intelligible_mandarin": True,
            "no_abnormal_pause_or_seam": True,
            "loudness_consistent": True,
        },
    }


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write_bound_listening_bundle(
    directory: Path,
    *,
    run_id: UUID,
    output_hashes: tuple[str, ...] = ("b" * 64,),
    verdict: str = "pass",
) -> Path:
    directory.chmod(0o700)
    record_path = directory / "listening.json"
    record = _valid_listening_payload()
    record["verdict"] = verdict
    if verdict == "fail":
        checks = record["checks"]
        assert isinstance(checks, dict)
        checks["no_abnormal_pause_or_seam"] = False
    record["output_hashes"] = sorted(output_hashes)
    record_data = _canonical_json_bytes(record)
    record_path.write_bytes(record_data)
    record_path.chmod(0o600)

    reviewed_at = record["reviewed_at"]
    run_fingerprint = _sha256(str(run_id))
    binding = {
        "run_fingerprint_sha256": run_fingerprint,
        "target_scope_sha256": _sha256(f"{NOVEL_ID}:{DOCUMENT_ID}"),
        "automatic_edition_id_sha256": _sha256(str(EDITION_AUTO)),
        "automatic_edition_fingerprint_sha256": "8" * 64,
        "manual_edition_id_sha256": _sha256(str(EDITION_MANUAL)),
        "manual_edition_fingerprint_sha256": "9" * 64,
    }
    receipt = {
        "schema_version": runner.LISTENING_FINALIZATION_RECEIPT_SCHEMA,
        "finalized_at": reviewed_at,
        "verdict": verdict,
        "probe_request_fingerprint_sha256": "d" * 64,
        **binding,
        "listening_record_sha256": hashlib.sha256(record_data).hexdigest(),
        "reviewed_roles": ["旁白", "林晚", "沈川"],
    }
    receipt_data = _canonical_json_bytes(receipt)
    receipt_path = directory / runner.LISTENING_FINALIZATION_RECEIPT_FILENAME
    receipt_path.write_bytes(receipt_data)
    receipt_path.chmod(0o600)

    claim = {
        "schema_version": runner.LISTENING_CLAIM_SCHEMA,
        "state": "PREPARED",
        "claimed_at": reviewed_at,
        "verdict": verdict,
        "probe_request_fingerprint_sha256": "d" * 64,
        **binding,
        "listening_record_sha256": hashlib.sha256(record_data).hexdigest(),
        "finalization_receipt_sha256": hashlib.sha256(
            receipt_data
        ).hexdigest(),
    }
    output_metadata = directory.resolve(strict=True).lstat()
    output_binding = {
        "output_directory_canonical_sha256": _sha256(
            str(directory.resolve(strict=True))
        ),
        "output_directory_identity_sha256": hashlib.sha256(
            json.dumps(
                {
                    "st_dev": output_metadata.st_dev,
                    "st_ino": output_metadata.st_ino,
                    "st_uid": output_metadata.st_uid,
                    "st_mode": output_metadata.st_mode,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    claim.update(output_binding)
    claim["self_sha256"] = hashlib.sha256(
        json.dumps(
            claim,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    claim_path = runner.LISTENING_CLAIM_REGISTRY_DIRECTORY / (
        f"{run_fingerprint}.claim"
    )
    claim_data = _canonical_json_bytes(claim)
    claim_path.write_bytes(claim_data)
    claim_path.chmod(0o600)
    commit = {
        "schema_version": runner.LISTENING_COMMIT_SCHEMA,
        "state": "COMMITTED",
        "committed_at": reviewed_at,
        "claim_sha256": hashlib.sha256(claim_data).hexdigest(),
        "run_fingerprint_sha256": run_fingerprint,
        "listening_record_sha256": hashlib.sha256(record_data).hexdigest(),
        "finalization_receipt_sha256": hashlib.sha256(
            receipt_data
        ).hexdigest(),
        **output_binding,
    }
    commit["self_sha256"] = hashlib.sha256(
        json.dumps(
            commit,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    commit_path = claim_path.with_suffix(".commit")
    commit_path.write_bytes(_canonical_json_bytes(commit))
    commit_path.chmod(0o600)
    return record_path


@pytest.mark.parametrize("unsafe", ["file-mode", "parent-mode", "repository"])
def test_listening_record_requires_private_external_owner_only_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe: str,
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "listening.json"
    path.write_text(json.dumps(_valid_listening_payload()), encoding="utf-8")
    path.chmod(0o600)
    if unsafe == "file-mode":
        path.chmod(0o644)
    elif unsafe == "parent-mode":
        tmp_path.chmod(0o755)
    else:
        monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)

    with pytest.raises(runner.RunnerError, match="LISTENING_RECORD_INVALID"):
            runner._load_listening_record(
            path,
            run_id=REQUEST_AUTO,
                novel_id=UUID(NOVEL_ID),
                document_id=UUID(DOCUMENT_ID),
                automatic_edition_id_sha256=_sha256(str(EDITION_AUTO)),
                automatic_edition_fingerprint_sha256="8" * 64,
                manual_edition_id_sha256=_sha256(str(EDITION_MANUAL)),
                manual_edition_fingerprint_sha256="9" * 64,
            expected_output_hashes=("b" * 64,),
            collector_collected_at="2026-08-27T12:00:00Z",
        )


def test_listening_record_rejects_symlink_and_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    target = tmp_path / "target.json"
    target.write_text(json.dumps(_valid_listening_payload()), encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "listening.json"
    link.symlink_to(target)
    with pytest.raises(runner.RunnerError, match="LISTENING_RECORD_INVALID"):
        runner._load_listening_record(
            link,
            run_id=REQUEST_AUTO,
            novel_id=UUID(NOVEL_ID),
            document_id=UUID(DOCUMENT_ID),
            automatic_edition_id_sha256=_sha256(str(EDITION_AUTO)),
            automatic_edition_fingerprint_sha256="8" * 64,
            manual_edition_id_sha256=_sha256(str(EDITION_MANUAL)),
            manual_edition_fingerprint_sha256="9" * 64,
            expected_output_hashes=("b" * 64,),
            collector_collected_at="2026-08-27T12:00:00Z",
        )

    link.unlink()
    duplicate = json.dumps(_valid_listening_payload())[:-1] + ',"verdict":"pass"}'
    link.write_text(duplicate, encoding="utf-8")
    link.chmod(0o600)
    with pytest.raises(runner.RunnerError, match="LISTENING_RECORD_INVALID"):
        runner._load_listening_record(
            link,
            run_id=REQUEST_AUTO,
            novel_id=UUID(NOVEL_ID),
            document_id=UUID(DOCUMENT_ID),
            automatic_edition_id_sha256=_sha256(str(EDITION_AUTO)),
            automatic_edition_fingerprint_sha256="8" * 64,
            manual_edition_id_sha256=_sha256(str(EDITION_MANUAL)),
            manual_edition_fingerprint_sha256="9" * 64,
            expected_output_hashes=("b" * 64,),
            collector_collected_at="2026-08-27T12:00:00Z",
        )


def test_baseline_accepts_empty_text_but_rejects_hash_mismatch() -> None:
    empty = runner.BaselineSnapshot(
        draft_version=1,
        content_hash=_sha256(""),
        content_markdown="",
        base_revision_id=None,
        pointer_version=1,
        current_edition_id=BASELINE_EDITION,
        current_script_version_id=BASELINE_SCRIPT,
        edition_history_count=1,
    )
    assert runner._validate_baseline(empty) == empty

    with pytest.raises(runner.RunnerError, match="BASELINE_INVALID"):
        runner._validate_baseline(
            runner.BaselineSnapshot(
                draft_version=1,
                content_hash="a" * 64,
                content_markdown="",
                base_revision_id=None,
                pointer_version=1,
                current_edition_id=BASELINE_EDITION,
                current_script_version_id=BASELINE_SCRIPT,
                edition_history_count=1,
            )
        )


def test_fixture_symlink_is_rejected_without_following_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _write_fixture(tmp_path / "actual-fixture.json")
    link = tmp_path / "fixture-link.json"
    link.symlink_to(target)

    assert runner.main(_arguments(tmp_path, link)) == 2
    assert "FIXTURE_PATH_UNSAFE" in capsys.readouterr().out


def test_existing_output_directory_permissions_are_rejected_without_chmod(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    output = tmp_path / "evidence"
    output.mkdir(mode=0o755)
    os.chmod(output, 0o755)

    assert runner.main(_arguments(tmp_path, fixture, output_dir=output)) == 2
    assert stat.S_IMODE(output.stat().st_mode) == 0o755


def test_fixture_parse_and_manifest_hash_come_from_one_stable_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = _write_fixture(tmp_path / "fixture.json")
    original_bytes = fixture_path.read_bytes()
    original_reader = runner._read_stable_regular_file
    calls = 0

    def read_then_switch(
        path: Path,
        code: str,
        *,
        maximum_bytes: int,
    ) -> bytes:
        nonlocal calls
        calls += 1
        raw = original_reader(path, code, maximum_bytes=maximum_bytes)
        path.write_text('{"schema_version":"switched"}', encoding="utf-8")
        return raw

    monkeypatch.setattr(runner, "_read_stable_regular_file", read_then_switch)

    fixture = runner.load_fixture(
        fixture_path,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )

    assert calls == 1
    assert fixture.automatic.source_text == AUTO_TEXT
    assert fixture.manifest_sha256 == hashlib.sha256(original_bytes).hexdigest()


def test_fixture_single_read_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    raw = json.dumps(_fixture_payload(), ensure_ascii=False)
    fixture_path.write_text(
        raw[:-1] + f',"schema_version":"{runner.FIXTURE_SCHEMA}"}}',
        encoding="utf-8",
    )

    with pytest.raises(runner.RunnerError, match="FIXTURE_UNREADABLE"):
        runner.load_fixture(
            fixture_path,
            automatic_case_id="chapter-auto-zero-blockers",
            manual_case_id="chapter-real-blocker",
        )


def test_fixture_override_is_strict_and_never_reopens_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_path = _write_fixture(tmp_path / "fixture.json")
    loaded = runner.load_fixture(
        fixture_path,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )
    fixture_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_read_stable_regular_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fixture_override must not reopen the manifest")
        ),
    )

    assert runner.main(
        _arguments(tmp_path, fixture_path),
        fixture_override=loaded,
    ) == 0
    assert _result(tmp_path)["fixture"]["manifest_sha256"] == (
        loaded.manifest_sha256
    )

    invalid = replace(loaded, manifest_sha256="not-a-sha256")
    assert runner.main(
        _arguments(tmp_path, fixture_path),
        fixture_override=invalid,
    ) == 2
    assert "FIXTURE_OVERRIDE_INVALID" in capsys.readouterr().out


def test_fixture_override_must_match_selected_case_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_path = _write_fixture(tmp_path / "fixture.json")
    loaded = runner.load_fixture(
        fixture_path,
        automatic_case_id="chapter-auto-zero-blockers",
        manual_case_id="chapter-real-blocker",
    )
    mismatched = replace(
        loaded,
        automatic=replace(loaded.automatic, case_id="different-automatic-case"),
    )

    assert runner.main(
        _arguments(tmp_path, fixture_path),
        fixture_override=mismatched,
    ) == 2
    assert "FIXTURE_OVERRIDE_INVALID" in capsys.readouterr().out


def _leave_recovery_record(
    tmp_path: Path,
    fixture: Path,
    *,
    run_id: str,
) -> Path:
    failed = FakeExecutor(
        automatic_error=RuntimeError("generation failed"),
        restore_error=RuntimeError("restore failed"),
    )
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            run_id=run_id,
        ),
        executor_factory=lambda _config: failed,
    ) == 4
    return tmp_path / "private-work" / "recovery.json"


def _capture_initial_recovery_record(
    tmp_path: Path,
    fixture: Path,
    *,
    run_id: str,
) -> bytes:
    captured: list[bytes] = []

    class CaptureAfterBaseline(FakeExecutor):
        def run_automatic(
            self,
            config: runner.RunnerConfig,
            case: runner.ChapterCase,
        ) -> runner.ChainOutcome:
            del config, case
            captured.append(
                (tmp_path / "private-work" / "recovery.json").read_bytes()
            )
            raise RuntimeError("simulated crash after baseline record")

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            run_id=run_id,
        ),
        executor_factory=lambda _config: CaptureAfterBaseline(),
    ) == 2
    assert len(captured) == 1
    assert not (tmp_path / "private-work" / "recovery.json").exists()
    return captured[0]


def _claim_head_harness(
    initial: runner.RecoveryClaimSnapshot,
) -> tuple[
    Any,
    Any,
    list[runner.RecoveryClaimSnapshot],
]:
    current = initial
    transitions: list[runner.RecoveryClaimSnapshot] = []

    def observe(state: str, generation: int, digest: str) -> None:
        nonlocal current
        current = runner.RecoveryClaimSnapshot(state, generation, digest)
        transitions.append(current)

    def read() -> runner.RecoveryClaimSnapshot:
        return current

    return observe, read, transitions


def _rewrite_recovery_payload(path: Path, payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("self_sha256", None)
    payload = {
        **unsigned,
        "self_sha256": hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    path.write_bytes(_canonical_json_bytes(payload))
    path.chmod(0o600)


def test_full_recovery_authentication_precedes_one_ahead_claim_reconcile(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    raw = _capture_initial_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    recovery_path = tmp_path / "private-work" / "recovery.json"
    recovery_path.write_bytes(raw)
    recovery_path.chmod(0o600)
    observe, read, transitions = _claim_head_harness(
        runner.RecoveryClaimSnapshot("PREPARED", 0, None)
    )
    factories: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(REQUEST_AUTO),
        ),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 2

    assert factories == []
    assert transitions == []
    assert _result(tmp_path)["error_codes"] == ["RECOVERY_RECORD_RUN_MISMATCH"]


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [
        ("claim", "RECOVERY_RECORD_CLAIM_MISMATCH"),
        ("fixture", "RECOVERY_RECORD_SCOPE_MISMATCH"),
    ],
)
def test_one_ahead_wrong_binding_or_fixture_never_advances_claim(
    tmp_path: Path,
    tamper: str,
    expected_code: str,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    raw = _capture_initial_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    recovery_path = tmp_path / "private-work" / "recovery.json"
    payload = json.loads(raw)
    if tamper == "claim":
        payload["claim"]["claim_identity_sha256"] = "f" * 64
    else:
        payload["fixture"]["fixture_id"] = "different-fixture"
    _rewrite_recovery_payload(recovery_path, payload)
    observe, read, transitions = _claim_head_harness(
        runner.RecoveryClaimSnapshot("PREPARED", 0, None)
    )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        recovery_executor_factory=lambda _config: (_ for _ in ()).throw(
            AssertionError("invalid record must not construct recovery executor")
        ),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 2

    assert transitions == []
    assert _result(tmp_path)["error_codes"] == [expected_code]


def test_fully_valid_write_before_claim_crash_reconciles_then_recovers(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    raw = _capture_initial_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    recovery_path = tmp_path / "private-work" / "recovery.json"
    recovery_path.write_bytes(raw)
    recovery_path.chmod(0o600)
    observe, read, transitions = _claim_head_harness(
        runner.RecoveryClaimSnapshot("PREPARED", 0, None)
    )

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        recovery_executor_factory=lambda _config: FakeExecutor(),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 0

    assert transitions[0].state == "BASELINE_SEALED"
    assert transitions[0].recovery_generation == 1
    assert transitions[-1].state == "FINALIZED"
    assert not recovery_path.exists()


def test_listening_pending_rejects_replayed_older_recovery_generation(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    old_raw = _capture_initial_recovery_record(
        tmp_path,
        fixture,
        run_id=str(REQUEST_AUTO),
    )
    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            run_id=str(REQUEST_AUTO),
        ),
        executor_factory=lambda _config: FakeExecutor(),
    ) == 3
    recovery_path = tmp_path / "private-work" / "recovery.json"
    latest = json.loads(recovery_path.read_text("utf-8"))
    claim_snapshot = runner.RecoveryClaimSnapshot(
        state="LISTENING_PENDING",
        recovery_generation=latest["generation"],
        latest_recovery_sha256=runner._recovery_record_sha256(latest),
    )
    recovery_path.write_bytes(old_raw)
    recovery_path.chmod(0o600)
    observe, read, transitions = _claim_head_harness(claim_snapshot)
    factories: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(REQUEST_AUTO),
        ),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
        recovery_state_observer=observe,
        recovery_claim_state_reader=read,
    ) == 2

    assert factories == []
    assert transitions == []
    assert _result(tmp_path)["error_codes"] == [
        "RECOVERY_CLAIM_HEAD_MISMATCH"
    ]


def test_resume_rejects_cross_run_recovery_before_any_executor_factory(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    recovery_path = _leave_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    recovery_before = recovery_path.read_bytes()
    calls: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(REQUEST_AUTO),
        ),
        executor_factory=lambda _config: calls.append("normal") or FakeExecutor(),
        recovery_executor_factory=lambda _config: calls.append("recovery")
        or FakeExecutor(),
    ) == 2

    assert calls == []
    assert recovery_path.read_bytes() == recovery_before
    assert _result(tmp_path)["error_codes"] == ["RECOVERY_RECORD_RUN_MISMATCH"]


def test_resume_rejects_noncanonical_recovery_run_id_before_factory(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    recovery_path = _leave_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    payload = json.loads(recovery_path.read_text("utf-8"))
    payload["run_id"] = str(BASE_REVISION).upper()
    recovery_path.write_text(json.dumps(payload), encoding="utf-8")
    recovery_path.chmod(0o600)
    called = False

    def forbidden_recovery_factory(
        _config: runner.RunnerConfig,
    ) -> FakeExecutor:
        nonlocal called
        called = True
        return FakeExecutor()

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        recovery_executor_factory=forbidden_recovery_factory,
    ) == 2
    assert called is False
    assert _result(tmp_path)["error_codes"] == ["RECOVERY_RECORD_INVALID"]


def test_resume_keyboard_interrupt_keeps_recovery_and_returns_130(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    recovery_path = _leave_recovery_record(
        tmp_path,
        fixture,
        run_id=str(BASE_REVISION),
    )
    recovery_before = recovery_path.read_bytes()

    def interrupted_factory(
        _config: runner.RunnerConfig,
    ) -> FakeExecutor:
        raise KeyboardInterrupt

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        recovery_executor_factory=interrupted_factory,
    ) == 130
    assert recovery_path.read_bytes() == recovery_before
    result = _result(tmp_path)
    assert result["status"] == "INTERRUPTED"
    assert result["error_codes"] == ["INTERRUPTED"]


@pytest.mark.parametrize("protected_attribute", ["REPOSITORY_ROOT", "CURRENT_PAWAPP_ROOT"])
def test_output_inside_source_or_current_pawapp_root_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    protected_attribute: str,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    protected = tmp_path / f"protected-{protected_attribute.lower()}"
    protected.mkdir(mode=0o700)
    monkeypatch.setattr(runner, protected_attribute, protected)

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            private_work_dir=tmp_path / "private-external",
            output_dir=protected / "evidence",
        )
    ) == 2
    assert "OUTPUT_PATH_TOO_BROAD" in capsys.readouterr().out
    assert not (protected / "evidence").exists()


@pytest.mark.parametrize("unsafe_directory", ["private", "output"])
def test_real_mode_never_chmods_an_existing_unsafe_directory(
    tmp_path: Path,
    unsafe_directory: str,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    private = tmp_path / "private-work"
    output = tmp_path / "evidence"
    private.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    target = private if unsafe_directory == "private" else output
    target.chmod(0o755)
    factory_called = False

    def forbidden_factory(_config: runner.RunnerConfig) -> FakeExecutor:
        nonlocal factory_called
        factory_called = True
        return FakeExecutor()

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            private_work_dir=private,
            output_dir=output,
        ),
        executor_factory=forbidden_factory,
    ) == 2
    assert factory_called is False
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_validate_only_creates_missing_nested_directories_owner_only(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    private = tmp_path / "nested-private" / "run"
    output = tmp_path / "nested-output" / "evidence"

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            private_work_dir=private,
            output_dir=output,
        )
    ) == 0
    for path in (
        private.parent,
        private,
        output.parent,
        output,
    ):
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_output_directory_rename_swap_fails_closed_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    output = tmp_path / "evidence"
    moved = tmp_path / "evidence-moved"
    original_replace = runner.os.replace
    swapped = False

    def swap_before_replace(
        source: str,
        destination: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if destination == "result.json" and not swapped:
            swapped = True
            output.rename(moved)
            output.mkdir(mode=0o700)
        original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(runner.os, "replace", swap_before_replace)

    assert runner.main(
        _arguments(tmp_path, fixture, output_dir=output)
    ) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "code": "OUTPUT_PATH_UNSAFE",
        "schema_version": runner.RESULT_SCHEMA,
        "status": "FAILED",
    }
    assert captured.err == ""


def test_recovery_symlink_is_never_followed_or_mutated(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    private = tmp_path / "private-work"
    private.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    victim.write_text("private-victim", encoding="utf-8")
    victim.chmod(0o600)
    (private / "recovery.json").symlink_to(victim)
    factories: list[str] = []

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
            private_work_dir=private,
            resume=True,
            run_id=str(BASE_REVISION),
        ),
        executor_factory=lambda _config: factories.append("normal")
        or FakeExecutor(),
        recovery_executor_factory=lambda _config: factories.append("recovery")
        or FakeExecutor(),
    ) == 2
    assert factories == []
    assert victim.read_text("utf-8") == "private-victim"
    assert (private / "recovery.json").is_symlink()


def test_existing_evidence_symlink_is_never_followed_or_replaced(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)
    victim = tmp_path / "victim-result.json"
    victim.write_text("do-not-touch", encoding="utf-8")
    victim.chmod(0o600)
    (output / "result.json").symlink_to(victim)

    assert runner.main(
        _arguments(tmp_path, fixture, output_dir=output)
    ) == 2
    assert victim.read_text("utf-8") == "do-not-touch"
    assert (output / "result.json").is_symlink()


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_exit"),
    [
        (RuntimeError("private unexpected detail"), "UNEXPECTED_FAILURE", 2),
        (KeyboardInterrupt(), "INTERRUPTED", 130),
    ],
)
def test_main_redacts_unexpected_factory_failure_and_keyboard_interrupt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    expected_code: str,
    expected_exit: int,
) -> None:
    fixture = _write_fixture(tmp_path / "fixture.json")

    def failing_factory(_config: runner.RunnerConfig) -> FakeExecutor:
        raise failure

    assert runner.main(
        _arguments(
            tmp_path,
            fixture,
            mode="real",
            include_real_confirmations=True,
        ),
        executor_factory=failing_factory,
    ) == expected_exit
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "code": expected_code,
        "schema_version": runner.RESULT_SCHEMA,
        "status": expected_code if expected_code == "INTERRUPTED" else "FAILED",
    }
    assert "private unexpected detail" not in captured.out
    assert captured.err == ""
