from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

import pytest

import scripts.tts.chapter_e2e_controller_signer as signer_module
from scripts.tts.chapter_e2e_controller_host import (
    CanonicalControllerArtifact,
    PreflightObservation,
    _test_controller_host,
    derive_preflight_expectation,
)
from scripts.tts.chapter_e2e_controller_signer import (
    CONTROLLER_SIGNING_INPUT_INVALID_ERROR,
    ControllerSigningError,
    _test_signer,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
    CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    PREFLIGHT_SIGNATURE_NAMESPACE,
    REPORT_SIGNATURE_NAMESPACE,
    SSH_KEYGEN_PATH,
    PreflightExpectation,
    _test_verifier,
    canonical_json_bytes,
)


NOW = datetime(2026, 8, 27, 14, 0, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-2222-4333-8444-555555555555"
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
KEY_ID = "t4k-controller-ed25519-test-key-01"
PRINCIPAL = "t4k-controller-test-key-01@ai-novel-world-2026.local"
BUILD_SHA = hashlib.sha256(b"controller-build").hexdigest()
BROWSER_SHA = hashlib.sha256(b"browser-build").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _materials(tmp_path: Path) -> dict[str, Path]:
    private = tmp_path / "controller"
    generated = subprocess.run(
        [
            str(SSH_KEYGEN_PATH),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(private),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert generated.returncode == 0
    private.chmod(0o600)
    public = private.with_suffix(".pub")
    public.chmod(0o600)
    fields = public.read_text(encoding="ascii").split()
    blob = base64.b64decode(fields[1], validate=True)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode().rstrip("=")
    allowed = tmp_path / "allowed_signers"
    allowed_raw = (
        f'{PRINCIPAL} namespaces="{PREFLIGHT_SIGNATURE_NAMESPACE},'
        f'{REPORT_SIGNATURE_NAMESPACE}" ssh-ed25519 {fields[1]}\n'
    ).encode()
    allowed.write_bytes(allowed_raw)
    allowed.chmod(0o600)
    policy_payload = {
        "schema_version": CONTROLLER_TRUST_POLICY_SCHEMA_VERSION,
        "generation": 1,
        "allowed_signers_sha256": hashlib.sha256(allowed_raw).hexdigest(),
        "keys": [
            {
                "algorithm": "ssh-ed25519",
                "allowed_controller_build_sha256": [BUILD_SHA],
                "allowed_browser_build_sha256": [BROWSER_SHA],
                "key_id": KEY_ID,
                "not_after": _timestamp(NOW + timedelta(days=1)),
                "not_before": _timestamp(NOW - timedelta(days=1)),
                "principal": PRINCIPAL,
                "public_key_fingerprint": fingerprint,
                "status": "active",
            }
        ],
    }
    policy = tmp_path / "policy.json"
    policy.write_bytes(canonical_json_bytes(policy_payload))
    policy.chmod(0o600)
    marker = tmp_path / "confirmation-invoked"
    prompt_capture = tmp_path / "confirmation-prompt"
    askpass = tmp_path / "askpass"
    askpass.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' confirmed >> {shlex.quote(str(marker))}\n"
        f"printf '%s' \"$1\" > {shlex.quote(str(prompt_capture))}\n"
        "printf '%s\\n' yes\n",
        encoding="utf-8",
    )
    askpass.chmod(0o700)
    return {
        "private": private,
        "public": public,
        "allowed": allowed,
        "policy": policy,
        "askpass": askpass,
        "marker": marker,
        "prompt": prompt_capture,
    }


def _artifact(materials: dict[str, Path]) -> CanonicalControllerArtifact:
    host = _test_controller_host(
        materials["policy"],
        materials["allowed"],
        controller_build_sha256=BUILD_SHA,
        browser_binary_sha256=BROWSER_SHA,
    )
    return host.build_preflight(
        PreflightObservation(
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
            envelope_nonce="nonce",
            envelope_fingerprint_sha256=_sha("envelope"),
            fixture_manifest_sha256=_sha("fixture"),
            issued_at=NOW,
        )
    )


def _complete_unsigned_preflight_artifact() -> CanonicalControllerArtifact:
    payload = {
        "allowed_signers_sha256": _sha("empty allowed signers"),
        "controller_build_sha256": BUILD_SHA,
        "controller_id": "ai-novel-world-2026-fixed-browser-controller/1.0",
        "expires_at": _timestamp(NOW + timedelta(minutes=10)),
        "fixture_manifest_sha256": _sha("fixture"),
        "issued_at": _timestamp(NOW),
        "nonce_sha256": _sha("nonce"),
        "operator_envelope_sha256": _sha("envelope"),
        "required_captures": [
            {
                "assistant_mode": mode,
                "target_css_height": height,
                "target_css_width": width,
            }
            for width, height, mode in (
                (1920, 1080, "collapsed"),
                (1920, 1080, "expanded"),
                (2560, 1440, "collapsed"),
                (2560, 1440, "expanded"),
            )
        ],
        "required_stability_milliseconds": 1_800_000,
        "run_fingerprint_sha256": _sha("run"),
        "schema_version": CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
        "signature_namespace": PREFLIGHT_SIGNATURE_NAMESPACE,
        "signer_principal": PRINCIPAL,
        "signing_key_id": KEY_ID,
        "target_scope_sha256": _sha("scope"),
        "trust_policy_sha256": _sha("empty policy"),
    }
    return CanonicalControllerArtifact(
        schema_version=CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
        signature_namespace=PREFLIGHT_SIGNATURE_NAMESPACE,
        payload=canonical_json_bytes(payload),
    )


def test_production_generic_signer_is_not_exposed() -> None:
    source = Path(signer_module.__file__).read_text(encoding="utf-8")
    assert "os.environ" not in source
    assert '"-c"' in source
    assert '"-t"' in source
    assert "FIXED_AGENT_LIFETIME_SECONDS" in source
    assert not hasattr(signer_module, "FixedControllerSigner")
    assert "FixedControllerSigner" not in signer_module.__all__
    assert signer_module.FIXED_ASKPASS_CANDIDATES[0] == (
        Path(signer_module.__file__).resolve().with_name(
            "controller_ssh_askpass.sh"
        )
    )
def test_one_shot_private_agent_adds_confirmation_and_lifetime_then_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials(tmp_path)
    artifact = _artifact(materials)
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/untrusted-preexisting-agent.sock")
    signer = _test_signer(
        policy_path=materials["policy"],
        allowed_signers_path=materials["allowed"],
        private_key_path=materials["private"],
        public_key_path=materials["public"],
        askpass_path=materials["askpass"],
    )

    signed = signer.sign_preflight(artifact)

    assert signed.startswith(b"-----BEGIN SSH SIGNATURE-----\n")
    assert materials["marker"].read_text(encoding="utf-8").splitlines() == [
        "confirmed"
    ]
    confirmation_prompt = materials["prompt"].read_text(encoding="utf-8")
    assert confirmation_prompt.startswith("Allow use of key ")
    assert "\nKey fingerprint SHA256:" in confirmation_prompt
    assert confirmation_prompt.endswith(".")
    derived = derive_preflight_expectation(
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        envelope_nonce="nonce",
        envelope_fingerprint_sha256=_sha("envelope"),
        fixture_manifest_sha256=_sha("fixture"),
    )
    verifier = _test_verifier(materials["policy"], materials["allowed"])
    verified = verifier.verify_preflight(
        artifact.payload,
        signed,
        expectation=PreflightExpectation(
            nonce_sha256=derived.nonce_sha256,
            run_fingerprint_sha256=derived.run_fingerprint_sha256,
            target_scope_sha256=derived.target_scope_sha256,
            operator_envelope_sha256=derived.operator_envelope_sha256,
            fixture_manifest_sha256=derived.fixture_manifest_sha256,
        ),
        now=NOW,
    )
    assert verified.key_id == KEY_ID


def test_signer_rejects_generic_or_wrong_namespace_payload_before_agent(
    tmp_path: Path,
) -> None:
    materials = _materials(tmp_path)
    signer = _test_signer(
        policy_path=materials["policy"],
        allowed_signers_path=materials["allowed"],
        private_key_path=materials["private"],
        public_key_path=materials["public"],
        askpass_path=materials["askpass"],
    )
    valid = _artifact(materials)
    wrong = CanonicalControllerArtifact(
        schema_version=valid.schema_version,
        signature_namespace=REPORT_SIGNATURE_NAMESPACE,
        payload=valid.payload,
    )

    with pytest.raises(ControllerSigningError) as captured:
        signer.sign_preflight(wrong)
    assert captured.value.code == CONTROLLER_SIGNING_INPUT_INVALID_ERROR
    assert not materials["marker"].exists()


def test_signer_does_not_write_signature_or_agent_socket_to_repository(
    tmp_path: Path,
) -> None:
    materials = _materials(tmp_path)
    artifact = _artifact(materials)
    signer = _test_signer(
        policy_path=materials["policy"],
        allowed_signers_path=materials["allowed"],
        private_key_path=materials["private"],
        public_key_path=materials["public"],
        askpass_path=materials["askpass"],
    )
    before = {
        path.relative_to(Path.cwd())
        for path in Path.cwd().glob("**/*.sshsig")
        if ".git" not in path.parts
    }
    signer.sign_preflight(artifact)
    after = {
        path.relative_to(Path.cwd())
        for path in Path.cwd().glob("**/*.sshsig")
        if ".git" not in path.parts
    }
    assert after == before
