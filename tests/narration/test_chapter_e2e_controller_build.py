from pathlib import Path

import pytest

from scripts.tts.chapter_e2e_controller_build import (
    CONTROLLER_SOURCE_PATHS,
    REPOSITORY_ROOT,
    ControllerBuildError,
    fixed_controller_build_sha256,
)


REQUIRED_FORMAL_CONTROLLER_SOURCES = {
    "backend/narration/release_gate.py",
    "scripts/tts/chapter_e2e_browser_observer.py",
    "scripts/tts/chapter_e2e_collector.py",
    "scripts/tts/chapter_e2e_controller_evidence.py",
    "scripts/tts/chapter_e2e_controller_host.py",
    "scripts/tts/chapter_e2e_controller_lifecycle.py",
    "scripts/tts/chapter_e2e_controller_signer.py",
    "scripts/tts/chapter_e2e_controller_trust.py",
    "scripts/tts/chapter_e2e_executor.py",
    "scripts/tts/chapter_e2e_metric_chain.py",
    "scripts/tts/chapter_e2e_probe_request.py",
    "scripts/tts/chapter_e2e_probes.py",
    "scripts/tts/chapter_e2e_runtime_observer.py",
    "scripts/tts/validate_chapter_e2e.py",
    "scripts/tts/controller_node_runtime.py",
    "scripts/tts/controller_ssh_askpass.sh",
}


def test_build_identity_covers_the_formal_controller_import_closure() -> None:
    assert REQUIRED_FORMAL_CONTROLLER_SOURCES <= set(CONTROLLER_SOURCE_PATHS)
    assert len(CONTROLLER_SOURCE_PATHS) == len(set(CONTROLLER_SOURCE_PATHS))
    assert all((REPOSITORY_ROOT / relative).is_file() for relative in CONTROLLER_SOURCE_PATHS)


def test_build_identity_excludes_policy_and_runtime_evidence_to_avoid_hash_cycles() -> None:
    assert not any("controller_trust_policy.json" in item for item in CONTROLLER_SOURCE_PATHS)
    assert not any("controller_allowed_signers" in item for item in CONTROLLER_SOURCE_PATHS)
    assert not any(item.startswith("/tmp/") for item in CONTROLLER_SOURCE_PATHS)


def test_build_identity_changes_when_a_bound_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "controller.py"
    source.write_bytes(b"first\n")
    monkeypatch.setattr(
        "scripts.tts.chapter_e2e_controller_build.REPOSITORY_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        "scripts.tts.chapter_e2e_controller_build.CONTROLLER_SOURCE_PATHS",
        ("controller.py",),
    )

    first = fixed_controller_build_sha256()
    source.write_bytes(b"second\n")

    assert fixed_controller_build_sha256() != first


def test_build_identity_rejects_group_writable_bound_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "controller.py"
    source.write_bytes(b"fixed\n")
    source.chmod(0o620)
    monkeypatch.setattr(
        "scripts.tts.chapter_e2e_controller_build.REPOSITORY_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        "scripts.tts.chapter_e2e_controller_build.CONTROLLER_SOURCE_PATHS",
        ("controller.py",),
    )

    with pytest.raises(ControllerBuildError):
        fixed_controller_build_sha256()
