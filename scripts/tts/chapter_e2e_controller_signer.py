#!/usr/bin/env python3
"""Internal one-shot OpenSSH signing primitive for T4-K controller tests.

There is intentionally no production signer class or public method accepting a
caller-constructed controller artifact.  Formal signing will only be wired
inside the fixed controller process after that same process has collected the
browser and runtime observations.  Until then the production trust root stays
empty and this module exposes only the error/constants needed by the internal
test seam.

The internal primitive starts a fresh private ssh-agent, loads one explicit
test key with ``ssh-add -c -t 120``, confirms the agent initially contained no
identities, signs exactly one AUTH-2 DTO through that agent, removes all
identities, and terminates the agent.

OpenSSH cannot introspect constraints on a pre-existing agent identity.  Such
an agent is therefore never trusted.  If the platform lacks the fixed
confirmation UI, the ceremony fails closed rather than dropping ``-c``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Final, Mapping

from scripts.tts.chapter_e2e_controller_host import (
    CanonicalControllerArtifact,
)
from scripts.tts.chapter_e2e_controller_trust import (
    ALLOWED_SIGNERS_PATH,
    CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
    CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
    CONTROLLER_TRUST_ROOT_HOLD_ERROR,
    PREFLIGHT_SIGNATURE_NAMESPACE,
    REPORT_SIGNATURE_NAMESPACE,
    SSH_KEYGEN_PATH,
    TRUST_POLICY_PATH,
    ControllerTrustError,
    _decode_canonical_mapping,
    _load_policy_from_paths,
)


SSH_AGENT_PATH: Final = Path("/usr/bin/ssh-agent")
SSH_ADD_PATH: Final = Path("/usr/bin/ssh-add")
FIXED_AGENT_LIFETIME_SECONDS: Final = 120
AGENT_START_TIMEOUT_SECONDS: Final = 5
SIGN_TIMEOUT_SECONDS: Final = 30
_SIGNATURE_BEGIN: Final = b"-----BEGIN SSH SIGNATURE-----\n"
_SIGNATURE_END: Final = b"-----END SSH SIGNATURE-----"

_ACCOUNT_HOME: Final = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
FIXED_KEY_DIRECTORY: Final = (
    _ACCOUNT_HOME
    / "Library"
    / "Application Support"
    / "AI小说世界2026"
    / "controller-authority"
)
FIXED_PRIVATE_KEY_PATH: Final = FIXED_KEY_DIRECTORY / "controller_ed25519"
FIXED_PUBLIC_KEY_PATH: Final = FIXED_KEY_DIRECTORY / "controller_ed25519.pub"
PACKAGED_ASKPASS_PATH: Final = Path(__file__).resolve().with_name(
    "controller_ssh_askpass.sh"
)
FIXED_ASKPASS_CANDIDATES: Final = (
    PACKAGED_ASKPASS_PATH,
    Path("/usr/libexec/ssh-askpass"),
    Path("/usr/X11R6/bin/ssh-askpass"),
)

CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR: Final = (
    "CONTROLLER_SIGNING_CEREMONY_HOLD"
)
CONTROLLER_SIGNING_INPUT_INVALID_ERROR: Final = (
    "CONTROLLER_SIGNING_INPUT_INVALID"
)
CONTROLLER_SIGNING_KEY_INVALID_ERROR: Final = "CONTROLLER_SIGNING_KEY_INVALID"

_PREFLIGHT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "issued_at",
        "expires_at",
        "nonce_sha256",
        "run_fingerprint_sha256",
        "target_scope_sha256",
        "operator_envelope_sha256",
        "fixture_manifest_sha256",
        "required_stability_milliseconds",
        "required_captures",
        "controller_id",
        "controller_build_sha256",
        "signing_key_id",
        "signer_principal",
        "signature_namespace",
        "trust_policy_sha256",
        "allowed_signers_sha256",
    }
)
_REPORT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "signed_at",
        "preflight_payload_sha256",
        "run_fingerprint_sha256",
        "target_scope_sha256",
        "probe_request_sha256",
        "request_fingerprint_sha256",
        "automatic_edition_fingerprint_sha256",
        "manual_edition_fingerprint_sha256",
        "listening_output_hashes",
        "required_stability_milliseconds",
        "observed_captures",
        "window_started_at",
        "window_ended_at",
        "stability_elapsed_milliseconds",
        "metric_sample_count",
        "metric_sample_chain_sha256",
        "collector_report_sha256",
        "probe_report_sha256",
        "controller_id",
        "controller_build_sha256",
        "browser_binary_sha256",
        "signing_key_id",
        "signer_principal",
        "signature_namespace",
        "trust_policy_sha256",
        "allowed_signers_sha256",
    }
)


class ControllerSigningError(RuntimeError):
    """Fail-closed signing error carrying only a stable public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _openssh_fingerprint(blob: str) -> str:
    try:
        decoded = base64.b64decode(blob, validate=True)
    except (ValueError, binascii.Error):
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR) from None
    if not decoded:
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)
    return "SHA256:" + base64.b64encode(
        hashlib.sha256(decoded).digest()
    ).decode("ascii").rstrip("=")


def _read_fixed_public_key(path: Path) -> tuple[str, str]:
    try:
        supplied = path.lstat()
        if (
            not path.is_absolute()
            or stat.S_ISLNK(supplied.st_mode)
            or not stat.S_ISREG(supplied.st_mode)
            or supplied.st_uid != os.getuid()
            or supplied.st_nlink != 1
            or stat.S_IMODE(supplied.st_mode) & 0o022
            or not 1 <= supplied.st_size <= 16 * 1024
        ):
            raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)
        raw = path.read_bytes()
        if len(raw) != supplied.st_size:
            raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)
        fields = raw.decode("ascii", errors="strict").strip().split()
        if len(fields) not in {2, 3} or fields[0] != "ssh-ed25519":
            raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)
        return fields[1], _openssh_fingerprint(fields[1])
    except ControllerSigningError:
        raise
    except (OSError, UnicodeDecodeError):
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR) from None


def _validate_private_key(path: Path, *, allow_unencrypted_test_key: bool) -> None:
    try:
        details = path.lstat()
        repository = Path(__file__).resolve().parents[2]
        resolved = path.resolve(strict=True)
        if (
            not path.is_absolute()
            or stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or resolved == repository
            or resolved.is_relative_to(repository)
        ):
            raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)
    except ControllerSigningError:
        raise
    except OSError:
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR) from None
    if allow_unencrypted_test_key:
        return
    # A successful empty-passphrase extraction proves the key is not encrypted.
    # Output and diagnostics are discarded; an encrypted key must fail here.
    try:
        result = subprocess.run(
            [
                str(SSH_KEYGEN_PATH),
                "-y",
                "-P",
                "",
                "-f",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR) from None
    if result.returncode == 0:
        raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)


def _validate_askpass(path: Path) -> None:
    try:
        details = path.lstat()
        if (
            not path.is_absolute()
            or stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) & 0o022
            or not stat.S_IMODE(details.st_mode) & 0o100
        ):
            raise ControllerSigningError(
                CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
            )
    except ControllerSigningError:
        raise
    except OSError:
        raise ControllerSigningError(
            CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
        ) from None


def _artifact_mapping(
    artifact: object,
    *,
    schema_version: str,
    namespace: str,
) -> Mapping[str, object]:
    if (
        type(artifact) is not CanonicalControllerArtifact
        or artifact.schema_version != schema_version
        or artifact.signature_namespace != namespace
    ):
        raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR)
    try:
        payload = _decode_canonical_mapping(
            artifact.payload,
            max_bytes=96 * 1024,
            code=CONTROLLER_SIGNING_INPUT_INVALID_ERROR,
        )
    except ControllerTrustError:
        raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR) from None
    expected_fields = (
        _PREFLIGHT_FIELDS
        if schema_version == CONTROLLER_PREFLIGHT_SCHEMA_VERSION
        else _REPORT_FIELDS
    )
    if (
        frozenset(payload) != expected_fields
        or payload.get("schema_version") != schema_version
        or payload.get("signature_namespace") != namespace
    ):
        raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR)
    return payload


@dataclass(frozen=True, slots=True)
class _SignerConfiguration:
    policy_path: Path
    allowed_signers_path: Path
    private_key_path: Path
    public_key_path: Path
    askpass_path: Path
    allow_unencrypted_test_key: bool


class _ControllerSigner:
    def __init__(self, configuration: _SignerConfiguration) -> None:
        self._configuration = configuration

    def _authorize(
        self,
        payload: Mapping[str, object],
        *,
        timestamp_field: str,
    ) -> None:
        configuration = self._configuration
        try:
            policy, _raw = _load_policy_from_paths(
                configuration.policy_path,
                configuration.allowed_signers_path,
            )
        except ControllerTrustError as error:
            raise ControllerSigningError(error.code) from None
        active = tuple(key for key in policy.keys if key.status == "active")
        if not active:
            raise ControllerSigningError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        if (
            payload.get("trust_policy_sha256") != policy.policy_sha256
            or payload.get("allowed_signers_sha256")
            != policy.allowed_signers_sha256
            or type(payload.get(timestamp_field)) is not str
        ):
            raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR)
        try:
            signed_at = datetime.strptime(
                str(payload[timestamp_field]), "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR) from None
        matches = tuple(
            key
            for key in active
            if key.key_id == payload.get("signing_key_id")
            and key.principal == payload.get("signer_principal")
            and key.not_before <= signed_at < key.not_after
            and payload.get("controller_build_sha256")
            in key.allowed_controller_build_sha256
        )
        if len(matches) != 1:
            raise ControllerSigningError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        if (
            "browser_binary_sha256" in payload
            and payload.get("browser_binary_sha256")
            not in matches[0].allowed_browser_build_sha256
        ):
            raise ControllerSigningError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        _blob, fingerprint = _read_fixed_public_key(
            configuration.public_key_path
        )
        if fingerprint != matches[0].public_key_fingerprint:
            raise ControllerSigningError(CONTROLLER_SIGNING_KEY_INVALID_ERROR)

    def sign_preflight(self, artifact: CanonicalControllerArtifact) -> bytes:
        payload = _artifact_mapping(
            artifact,
            schema_version=CONTROLLER_PREFLIGHT_SCHEMA_VERSION,
            namespace=PREFLIGHT_SIGNATURE_NAMESPACE,
        )
        self._authorize(payload, timestamp_field="issued_at")
        return self._one_shot_sign(
            artifact.payload,
            namespace=PREFLIGHT_SIGNATURE_NAMESPACE,
        )

    def sign_report_binding(
        self,
        artifact: CanonicalControllerArtifact,
    ) -> bytes:
        payload = _artifact_mapping(
            artifact,
            schema_version=CONTROLLER_REPORT_BINDING_SCHEMA_VERSION,
            namespace=REPORT_SIGNATURE_NAMESPACE,
        )
        self._authorize(payload, timestamp_field="signed_at")
        return self._one_shot_sign(
            artifact.payload,
            namespace=REPORT_SIGNATURE_NAMESPACE,
        )

    def _one_shot_sign(self, payload: bytes, *, namespace: str) -> bytes:
        configuration = self._configuration
        if namespace not in {
            PREFLIGHT_SIGNATURE_NAMESPACE,
            REPORT_SIGNATURE_NAMESPACE,
        }:
            raise ControllerSigningError(CONTROLLER_SIGNING_INPUT_INVALID_ERROR)
        _validate_askpass(configuration.askpass_path)
        _validate_private_key(
            configuration.private_key_path,
            allow_unencrypted_test_key=(
                configuration.allow_unencrypted_test_key
            ),
        )
        _read_fixed_public_key(configuration.public_key_path)

        temporary_root: Path | None = None
        agent: subprocess.Popen[bytes] | None = None
        agent_environment: dict[str, str] | None = None
        try:
            temporary_root = Path(
                tempfile.mkdtemp(prefix="t4k-agent-", dir="/tmp")
            )
            temporary_root.chmod(0o700)
            socket_path = temporary_root / "agent.sock"
            agent_environment = {
                "DISPLAY": ":0",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
                "SSH_ASKPASS": str(configuration.askpass_path),
                "SSH_ASKPASS_REQUIRE": "force",
            }
            agent = subprocess.Popen(
                [str(SSH_AGENT_PATH), "-D", "-a", str(socket_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=agent_environment,
                start_new_session=True,
            )
            deadline = time.monotonic() + AGENT_START_TIMEOUT_SECONDS
            while not socket_path.exists():
                if agent.poll() is not None or time.monotonic() >= deadline:
                    raise ControllerSigningError(
                        CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
                    )
                time.sleep(0.01)
            agent_environment = {
                **agent_environment,
                "SSH_AGENT_PID": str(agent.pid),
                "SSH_AUTH_SOCK": str(socket_path),
            }
            empty = subprocess.run(
                [str(SSH_ADD_PATH), "-l"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=agent_environment,
                timeout=10,
                check=False,
            )
            if empty.returncode != 1:
                raise ControllerSigningError(
                    CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
                )
            constrained_at = time.monotonic()
            added = subprocess.run(
                [
                    str(SSH_ADD_PATH),
                    "-c",
                    "-t",
                    str(FIXED_AGENT_LIFETIME_SECONDS),
                    str(configuration.private_key_path),
                ],
                stdin=None,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=agent_environment,
                timeout=SIGN_TIMEOUT_SECONDS,
                check=False,
            )
            if added.returncode != 0:
                raise ControllerSigningError(
                    CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
                )
            listed = subprocess.run(
                [str(SSH_ADD_PATH), "-l", "-E", "sha256"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=agent_environment,
                timeout=10,
                check=False,
            )
            _blob, expected_fingerprint = _read_fixed_public_key(
                configuration.public_key_path
            )
            listed_text = listed.stdout.decode("ascii", errors="ignore")
            if (
                listed.returncode != 0
                or listed_text.count("SHA256:") != 1
                or expected_fingerprint not in listed_text
                or time.monotonic() - constrained_at
                >= FIXED_AGENT_LIFETIME_SECONDS
            ):
                raise ControllerSigningError(
                    CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
                )
            signed = subprocess.run(
                [
                    str(SSH_KEYGEN_PATH),
                    "-Y",
                    "sign",
                    "-f",
                    str(configuration.public_key_path),
                    "-n",
                    namespace,
                ],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=agent_environment,
                timeout=SIGN_TIMEOUT_SECONDS,
                check=False,
            )
            signature = signed.stdout
            if (
                signed.returncode != 0
                or time.monotonic() - constrained_at
                >= FIXED_AGENT_LIFETIME_SECONDS
                or not signature.startswith(_SIGNATURE_BEGIN)
                or not signature.rstrip(b"\n").endswith(_SIGNATURE_END)
            ):
                raise ControllerSigningError(
                    CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
                )
            return signature
        except ControllerSigningError:
            raise
        except (OSError, subprocess.SubprocessError):
            raise ControllerSigningError(
                CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR
            ) from None
        finally:
            if agent_environment is not None:
                try:
                    subprocess.run(
                        [str(SSH_ADD_PATH), "-D"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=agent_environment,
                        timeout=5,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
            if agent is not None:
                agent.terminate()
                try:
                    agent.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    agent.kill()
                    agent.wait(timeout=5)
            if temporary_root is not None:
                shutil.rmtree(temporary_root, ignore_errors=True)


def _test_signer(
    *,
    policy_path: Path,
    allowed_signers_path: Path,
    private_key_path: Path,
    public_key_path: Path,
    askpass_path: Path,
) -> _ControllerSigner:
    """Internal test seam using only temporary key and agent material."""

    return _ControllerSigner(
        _SignerConfiguration(
            policy_path=policy_path,
            allowed_signers_path=allowed_signers_path,
            private_key_path=private_key_path,
            public_key_path=public_key_path,
            askpass_path=askpass_path,
            allow_unencrypted_test_key=True,
        )
    )


__all__ = [
    "CONTROLLER_SIGNING_CEREMONY_HOLD_ERROR",
    "CONTROLLER_SIGNING_INPUT_INVALID_ERROR",
    "CONTROLLER_SIGNING_KEY_INVALID_ERROR",
    "ControllerSigningError",
    "FIXED_AGENT_LIFETIME_SECONDS",
    "FIXED_PRIVATE_KEY_PATH",
    "FIXED_PUBLIC_KEY_PATH",
]
