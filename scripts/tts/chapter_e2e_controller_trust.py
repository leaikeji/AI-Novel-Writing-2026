#!/usr/bin/env python3
"""Asymmetric public trust root for the fixed T4-K browser controller.

The production verifier is deliberately verification-only.  It reads two
fixed, repository-packaged public files and invokes the fixed OpenSSH
``ssh-keygen -Y verify`` implementation.  It has no private-key path, agent
socket, signing API, caller-selected trust file, or generic payload API.

The corresponding host controller is expected to keep an Ed25519 private key
outside the repository and QwenPaw container, load it into a short-lived
confirmation-constrained ssh-agent, and sign only the canonical DTOs frozen in
this module.  That host signing ceremony is not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Final, Mapping, Sequence


CONTROLLER_TRUST_POLICY_SCHEMA_VERSION: Final = (
    "moss-tts-t4k-controller-trust-policy/1.1"
)
CONTROLLER_PREFLIGHT_SCHEMA_VERSION: Final = (
    "moss-tts-t4k-controller-preflight/1.0"
)
CONTROLLER_REPORT_BINDING_SCHEMA_VERSION: Final = (
    "moss-tts-t4k-controller-report-binding/1.0"
)
CONTROLLER_ID: Final = (
    "ai-novel-world-2026-fixed-browser-controller/1.0"
)
PREFLIGHT_SIGNATURE_NAMESPACE: Final = (
    "t4k-controller-preflight@ai-novel-world-2026.local"
)
REPORT_SIGNATURE_NAMESPACE: Final = (
    "t4k-controller-report@ai-novel-world-2026.local"
)
FIXED_REQUIRED_STABILITY_MILLISECONDS: Final = 30 * 60 * 1000
FIXED_REQUIRED_CAPTURES: Final = (
    (1920, 1080, "collapsed"),
    (1920, 1080, "expanded"),
    (2560, 1440, "collapsed"),
    (2560, 1440, "expanded"),
)
SSH_KEYGEN_PATH: Final = Path("/usr/bin/ssh-keygen")
TRUST_DIRECTORY: Final = Path(__file__).resolve().with_name("trust")
TRUST_POLICY_PATH: Final = TRUST_DIRECTORY / "controller_trust_policy.json"
ALLOWED_SIGNERS_PATH: Final = TRUST_DIRECTORY / "controller_allowed_signers"
MAX_POLICY_BYTES: Final = 64 * 1024
MAX_ALLOWED_SIGNERS_BYTES: Final = 64 * 1024
MAX_PREFLIGHT_BYTES: Final = 32 * 1024
MAX_REPORT_BINDING_BYTES: Final = 96 * 1024
MAX_SIGNATURE_BYTES: Final = 16 * 1024
MAX_PREFLIGHT_LIFETIME_SECONDS: Final = 15 * 60
MAX_REPORT_AGE_SECONDS: Final = 15 * 60
MAX_FUTURE_SKEW_SECONDS: Final = 30

CONTROLLER_TRUST_ROOT_HOLD_ERROR: Final = "CONTROLLER_TRUST_ROOT_HOLD"
CONTROLLER_TRUST_POLICY_INVALID_ERROR: Final = (
    "CONTROLLER_TRUST_POLICY_INVALID"
)
CONTROLLER_SIGNATURE_INVALID_ERROR: Final = "CONTROLLER_SIGNATURE_INVALID"
CONTROLLER_PREFLIGHT_INVALID_ERROR: Final = "CONTROLLER_PREFLIGHT_INVALID"
CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR: Final = (
    "CONTROLLER_PREFLIGHT_BINDING_MISMATCH"
)
CONTROLLER_REPORT_BINDING_INVALID_ERROR: Final = (
    "CONTROLLER_REPORT_BINDING_INVALID"
)
CONTROLLER_REPORT_BINDING_MISMATCH_ERROR: Final = (
    "CONTROLLER_REPORT_BINDING_MISMATCH"
)

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID_RE: Final = re.compile(r"^t4k-controller-ed25519-[a-z0-9][a-z0-9-]{7,63}$")
_PRINCIPAL_RE: Final = re.compile(
    r"^t4k-controller-[a-z0-9][a-z0-9-]{7,63}@ai-novel-world-2026\.local$"
)
_OPENSSH_FINGERPRINT_RE: Final = re.compile(
    r"^SHA256:[A-Za-z0-9+/]{43}$"
)
_SIGNATURE_BEGIN: Final = "-----BEGIN SSH SIGNATURE-----"
_SIGNATURE_END: Final = "-----END SSH SIGNATURE-----"


class ControllerTrustError(RuntimeError):
    """Fail-closed trust error carrying only a stable public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_nonfinite_json(value: str) -> object:
    del value
    raise ValueError


def canonical_json_bytes(value: object) -> bytes:
    """Return the one accepted signed representation, including final LF."""

    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError):
        raise ControllerTrustError("CONTROLLER_CANONICAL_JSON_INVALID") from None


def _decode_canonical_mapping(
    raw: bytes,
    *,
    max_bytes: int,
    code: str,
) -> Mapping[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= max_bytes:
        raise ControllerTrustError(code)
    try:
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        _DuplicateJsonKey,
    ):
        raise ControllerTrustError(code) from None
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ControllerTrustError(code)
    return value


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    *,
    code: str,
) -> Mapping[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ControllerTrustError(code)
    return value


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: object, *, code: str) -> str:
    if not _is_sha256(value):
        raise ControllerTrustError(code)
    return str(value)


def _parse_timestamp(value: object, *, code: str) -> datetime:
    if type(value) is not str or len(value) != 20:
        raise ControllerTrustError(code)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise ControllerTrustError(code) from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ControllerTrustError(code)
    return parsed


def _timestamp(value: datetime, *, code: str) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise ControllerTrustError(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond != 0:
        raise ControllerTrustError(code)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_hashes(value: object, *, code: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise ControllerTrustError(code)
    hashes = tuple(value)
    if (
        any(not _is_sha256(item) for item in hashes)
        or hashes != tuple(sorted(hashes))
        or len(hashes) != len(set(hashes))
    ):
        raise ControllerTrustError(code)
    return tuple(str(item) for item in hashes)


def _read_public_file(path: Path, *, max_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        supplied = path.lstat()
        if (
            not path.is_absolute()
            or stat.S_ISLNK(supplied.st_mode)
            or not stat.S_ISREG(supplied.st_mode)
            or supplied.st_nlink != 1
            or stat.S_IMODE(supplied.st_mode) & 0o022
            or supplied.st_size > max_bytes
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size > max_bytes
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        raw = os.read(descriptor, max_bytes + 1)
        after = os.fstat(descriptor)
        resolved = path.resolve(strict=True).stat()
        if (
            len(raw) != before.st_size
            or len(raw) > max_bytes
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (after.st_dev, after.st_ino) != (resolved.st_dev, resolved.st_ino)
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        return raw
    except ControllerTrustError:
        raise
    except OSError as error:
        raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _openssh_fingerprint(key_blob: str, *, code: str) -> str:
    try:
        decoded = base64.b64decode(key_blob, validate=True)
    except (ValueError, binascii.Error):
        raise ControllerTrustError(code) from None
    if not decoded:
        raise ControllerTrustError(code)
    digest = base64.b64encode(hashlib.sha256(decoded).digest()).decode("ascii")
    return "SHA256:" + digest.rstrip("=")


@dataclass(frozen=True, slots=True)
class ControllerTrustKey:
    key_id: str
    principal: str
    public_key_fingerprint: str
    status: str
    not_before: datetime
    not_after: datetime
    allowed_controller_build_sha256: tuple[str, ...]
    allowed_browser_build_sha256: tuple[str, ...]
    allowed_signers_line: str | None


@dataclass(frozen=True, slots=True)
class ControllerTrustPolicy:
    generation: int
    policy_sha256: str
    allowed_signers_sha256: str
    keys: tuple[ControllerTrustKey, ...]

    def key(self, key_id: str) -> ControllerTrustKey:
        matches = tuple(item for item in self.keys if item.key_id == key_id)
        if not matches:
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        if len(matches) != 1:
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        return matches[0]


def _parse_allowed_signers(raw: bytes) -> dict[str, tuple[str, str]]:
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR) from None
    result: dict[str, tuple[str, str]] = {}
    for source_line in text.splitlines():
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        principal, options, key_type, key_blob = parts
        if (
            _PRINCIPAL_RE.fullmatch(principal) is None
            or principal in result
            or key_type != "ssh-ed25519"
            or options
            != (
                f'namespaces="{PREFLIGHT_SIGNATURE_NAMESPACE},'
                f'{REPORT_SIGNATURE_NAMESPACE}"'
            )
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        fingerprint = _openssh_fingerprint(
            key_blob,
            code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
        )
        result[principal] = (line, fingerprint)
    return result


def _load_policy_from_paths(
    policy_path: Path,
    allowed_signers_path: Path,
) -> tuple[ControllerTrustPolicy, bytes]:
    policy_raw = _read_public_file(policy_path, max_bytes=MAX_POLICY_BYTES)
    signers_raw = _read_public_file(
        allowed_signers_path,
        max_bytes=MAX_ALLOWED_SIGNERS_BYTES,
    )
    payload = _decode_canonical_mapping(
        policy_raw,
        max_bytes=MAX_POLICY_BYTES,
        code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
    )
    exact = _exact_mapping(
        payload,
        frozenset(
            {
                "schema_version",
                "generation",
                "allowed_signers_sha256",
                "keys",
            }
        ),
        code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
    )
    expected_signers_sha256 = hashlib.sha256(signers_raw).hexdigest()
    if (
        exact["schema_version"] != CONTROLLER_TRUST_POLICY_SCHEMA_VERSION
        or type(exact["generation"]) is not int
        or exact["generation"] < 1
        or exact["allowed_signers_sha256"] != expected_signers_sha256
        or type(exact["keys"]) is not list
    ):
        raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
    signers = _parse_allowed_signers(signers_raw)
    parsed_keys: list[ControllerTrustKey] = []
    seen_ids: set[str] = set()
    seen_principals: set[str] = set()
    for raw_key in exact["keys"]:
        key = _exact_mapping(
            raw_key,
            frozenset(
                {
                    "key_id",
                    "principal",
                    "algorithm",
                    "public_key_fingerprint",
                    "status",
                    "not_before",
                    "not_after",
                    "allowed_controller_build_sha256",
                    "allowed_browser_build_sha256",
                }
            ),
            code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
        )
        key_id = key["key_id"]
        principal = key["principal"]
        status_value = key["status"]
        if (
            type(key_id) is not str
            or _KEY_ID_RE.fullmatch(key_id) is None
            or key_id in seen_ids
            or type(principal) is not str
            or _PRINCIPAL_RE.fullmatch(principal) is None
            or principal in seen_principals
            or key["algorithm"] != "ssh-ed25519"
            or type(key["public_key_fingerprint"]) is not str
            or _OPENSSH_FINGERPRINT_RE.fullmatch(
                str(key["public_key_fingerprint"])
            )
            is None
            or status_value not in {"active", "revoked"}
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        not_before = _parse_timestamp(
            key["not_before"], code=CONTROLLER_TRUST_POLICY_INVALID_ERROR
        )
        not_after = _parse_timestamp(
            key["not_after"], code=CONTROLLER_TRUST_POLICY_INVALID_ERROR
        )
        builds = _normalize_hashes(
            key["allowed_controller_build_sha256"],
            code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
        )
        browser_builds = _normalize_hashes(
            key["allowed_browser_build_sha256"],
            code=CONTROLLER_TRUST_POLICY_INVALID_ERROR,
        )
        if not_before >= not_after:
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        allowed_line: str | None = None
        signer = signers.get(str(principal))
        if status_value == "active":
            if (
                signer is None
                or signer[1] != key["public_key_fingerprint"]
            ):
                raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
            allowed_line = signer[0]
        elif signer is not None:
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        parsed_keys.append(
            ControllerTrustKey(
                key_id=str(key_id),
                principal=str(principal),
                public_key_fingerprint=str(key["public_key_fingerprint"]),
                status=str(status_value),
                not_before=not_before,
                not_after=not_after,
                allowed_controller_build_sha256=builds,
                allowed_browser_build_sha256=browser_builds,
                allowed_signers_line=allowed_line,
            )
        )
        seen_ids.add(str(key_id))
        seen_principals.add(str(principal))
    if set(signers) != {
        item.principal for item in parsed_keys if item.status == "active"
    }:
        raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
    return (
        ControllerTrustPolicy(
            generation=int(exact["generation"]),
            policy_sha256=hashlib.sha256(policy_raw).hexdigest(),
            allowed_signers_sha256=expected_signers_sha256,
            keys=tuple(parsed_keys),
        ),
        signers_raw,
    )


@dataclass(frozen=True, slots=True)
class RequiredCapture:
    target_css_width: int
    target_css_height: int
    assistant_mode: str

    def to_payload(self) -> dict[str, object]:
        return {
            "target_css_width": self.target_css_width,
            "target_css_height": self.target_css_height,
            "assistant_mode": self.assistant_mode,
        }


def _required_captures() -> tuple[RequiredCapture, ...]:
    return tuple(RequiredCapture(*item) for item in FIXED_REQUIRED_CAPTURES)


@dataclass(frozen=True, slots=True)
class PreflightExpectation:
    nonce_sha256: str
    run_fingerprint_sha256: str
    target_scope_sha256: str
    operator_envelope_sha256: str
    fixture_manifest_sha256: str

    def __post_init__(self) -> None:
        if any(
            not _is_sha256(value)
            for value in (
                self.nonce_sha256,
                self.run_fingerprint_sha256,
                self.target_scope_sha256,
                self.operator_envelope_sha256,
                self.fixture_manifest_sha256,
            )
        ):
            raise ControllerTrustError(CONTROLLER_PREFLIGHT_INVALID_ERROR)


@dataclass(frozen=True, slots=True)
class VerifiedControllerPreflight:
    issued_at: datetime
    expires_at: datetime
    key_id: str
    principal: str
    controller_build_sha256: str
    payload_sha256: str
    policy_sha256: str
    allowed_signers_sha256: str


@dataclass(frozen=True, slots=True)
class ObservedCaptureBinding:
    target_css_width: int
    target_css_height: int
    requested_outer_width: int
    requested_outer_height: int
    observed_inner_width: int
    observed_inner_height: int
    device_pixel_ratio_micros: int
    screenshot_pixel_width: int
    screenshot_pixel_height: int
    assistant_mode_requested: str
    assistant_mode_observed: str
    calibration_attempt_count: int
    calibration_summary_sha256: str
    screenshot_sha256: str
    console_summary_sha256: str
    network_summary_sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "target_css_width": self.target_css_width,
            "target_css_height": self.target_css_height,
            "requested_outer_width": self.requested_outer_width,
            "requested_outer_height": self.requested_outer_height,
            "observed_inner_width": self.observed_inner_width,
            "observed_inner_height": self.observed_inner_height,
            "device_pixel_ratio_micros": self.device_pixel_ratio_micros,
            "screenshot_pixel_width": self.screenshot_pixel_width,
            "screenshot_pixel_height": self.screenshot_pixel_height,
            "assistant_mode_requested": self.assistant_mode_requested,
            "assistant_mode_observed": self.assistant_mode_observed,
            "calibration_attempt_count": self.calibration_attempt_count,
            "calibration_summary_sha256": self.calibration_summary_sha256,
            "screenshot_sha256": self.screenshot_sha256,
            "console_summary_sha256": self.console_summary_sha256,
            "network_summary_sha256": self.network_summary_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReportExpectation:
    preflight_payload_sha256: str
    run_fingerprint_sha256: str
    target_scope_sha256: str
    probe_request_sha256: str
    request_fingerprint_sha256: str
    automatic_edition_fingerprint_sha256: str
    manual_edition_fingerprint_sha256: str
    listening_output_hashes: tuple[str, ...]
    collector_report_sha256: str
    probe_report_sha256: str

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.preflight_payload_sha256,
                    self.run_fingerprint_sha256,
                    self.target_scope_sha256,
                    self.probe_request_sha256,
                    self.request_fingerprint_sha256,
                    self.automatic_edition_fingerprint_sha256,
                    self.manual_edition_fingerprint_sha256,
                    self.collector_report_sha256,
                    self.probe_report_sha256,
                )
            )
            or not self.listening_output_hashes
            or any(not _is_sha256(item) for item in self.listening_output_hashes)
            or tuple(sorted(self.listening_output_hashes))
            != self.listening_output_hashes
            or len(set(self.listening_output_hashes))
            != len(self.listening_output_hashes)
        ):
            raise ControllerTrustError(
                CONTROLLER_REPORT_BINDING_INVALID_ERROR
            )


@dataclass(frozen=True, slots=True)
class VerifiedControllerReportBinding:
    signed_at: datetime
    key_id: str
    principal: str
    controller_build_sha256: str
    browser_binary_sha256: str
    payload_sha256: str
    policy_sha256: str
    allowed_signers_sha256: str
    captures: tuple[ObservedCaptureBinding, ...]
    stability_elapsed_milliseconds: int
    metric_sample_count: int
    metric_sample_chain_sha256: str


def _parse_required_capture_payload(value: object, *, code: str) -> tuple[RequiredCapture, ...]:
    if type(value) is not list:
        raise ControllerTrustError(code)
    captures: list[RequiredCapture] = []
    for raw in value:
        item = _exact_mapping(
            raw,
            frozenset({"target_css_width", "target_css_height", "assistant_mode"}),
            code=code,
        )
        if (
            type(item["target_css_width"]) is not int
            or type(item["target_css_height"]) is not int
            or type(item["assistant_mode"]) is not str
        ):
            raise ControllerTrustError(code)
        captures.append(
            RequiredCapture(
                int(item["target_css_width"]),
                int(item["target_css_height"]),
                str(item["assistant_mode"]),
            )
        )
    result = tuple(captures)
    if result != _required_captures():
        raise ControllerTrustError(code)
    return result


def _parse_observed_captures(value: object) -> tuple[ObservedCaptureBinding, ...]:
    code = CONTROLLER_REPORT_BINDING_INVALID_ERROR
    if type(value) is not list:
        raise ControllerTrustError(code)
    fields = frozenset(
        {
            "target_css_width",
            "target_css_height",
            "requested_outer_width",
            "requested_outer_height",
            "observed_inner_width",
            "observed_inner_height",
            "device_pixel_ratio_micros",
            "screenshot_pixel_width",
            "screenshot_pixel_height",
            "assistant_mode_requested",
            "assistant_mode_observed",
            "calibration_attempt_count",
            "calibration_summary_sha256",
            "screenshot_sha256",
            "console_summary_sha256",
            "network_summary_sha256",
        }
    )
    captures: list[ObservedCaptureBinding] = []
    for raw in value:
        item = _exact_mapping(raw, fields, code=code)
        integer_fields = (
            "target_css_width",
            "target_css_height",
            "requested_outer_width",
            "requested_outer_height",
            "observed_inner_width",
            "observed_inner_height",
            "device_pixel_ratio_micros",
            "screenshot_pixel_width",
            "screenshot_pixel_height",
            "calibration_attempt_count",
        )
        if any(type(item[name]) is not int for name in integer_fields):
            raise ControllerTrustError(code)
        target = (
            int(item["target_css_width"]),
            int(item["target_css_height"]),
            str(item["assistant_mode_requested"]),
        )
        if (
            target not in FIXED_REQUIRED_CAPTURES
            or item["assistant_mode_observed"]
            != item["assistant_mode_requested"]
            or item["observed_inner_width"] != item["target_css_width"]
            or item["observed_inner_height"] != item["target_css_height"]
            or int(item["requested_outer_width"])
            < int(item["target_css_width"])
            or int(item["requested_outer_height"])
            < int(item["target_css_height"])
            or not 100_000 <= int(item["device_pixel_ratio_micros"]) <= 8_000_000
            or int(item["screenshot_pixel_width"]) < 1
            or int(item["screenshot_pixel_height"]) < 1
            or not 1 <= int(item["calibration_attempt_count"]) <= 8
            or any(
                not _is_sha256(item[name])
                for name in (
                    "calibration_summary_sha256",
                    "screenshot_sha256",
                    "console_summary_sha256",
                    "network_summary_sha256",
                )
            )
        ):
            raise ControllerTrustError(code)
        captures.append(
            ObservedCaptureBinding(
                **{name: item[name] for name in fields}  # type: ignore[arg-type]
            )
        )
    result = tuple(captures)
    observed_contract = tuple(
        (
            item.target_css_width,
            item.target_css_height,
            item.assistant_mode_requested,
        )
        for item in result
    )
    if observed_contract != FIXED_REQUIRED_CAPTURES:
        raise ControllerTrustError(code)
    return result


class _ControllerTrustVerifier:
    def __init__(
        self,
        *,
        policy_path: Path,
        allowed_signers_path: Path,
        ssh_keygen_path: Path = SSH_KEYGEN_PATH,
    ) -> None:
        if any(
            not isinstance(path, Path) or not path.is_absolute()
            for path in (policy_path, allowed_signers_path, ssh_keygen_path)
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_POLICY_INVALID_ERROR)
        self._policy_path = policy_path
        self._allowed_signers_path = allowed_signers_path
        self._ssh_keygen_path = ssh_keygen_path

    def _load_policy(self) -> tuple[ControllerTrustPolicy, bytes]:
        return _load_policy_from_paths(
            self._policy_path,
            self._allowed_signers_path,
        )

    def _verify_signature(
        self,
        payload: bytes,
        signature: bytes,
        *,
        namespace: str,
        principal: str,
        key: ControllerTrustKey,
    ) -> None:
        if (
            type(signature) is not bytes
            or not 1 <= len(signature) <= MAX_SIGNATURE_BYTES
        ):
            raise ControllerTrustError(CONTROLLER_SIGNATURE_INVALID_ERROR)
        try:
            signature_text = signature.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise ControllerTrustError(CONTROLLER_SIGNATURE_INVALID_ERROR) from None
        if (
            not signature_text.startswith(_SIGNATURE_BEGIN + "\n")
            or not signature_text.rstrip("\n").endswith(_SIGNATURE_END)
            or key.allowed_signers_line is None
        ):
            raise ControllerTrustError(CONTROLLER_SIGNATURE_INVALID_ERROR)
        temporary_root: Path | None = None
        try:
            temporary_root = Path(
                tempfile.mkdtemp(prefix="ai-novel-t4k-sshsig-")
            )
            temporary_root.chmod(0o700)
            allowed_path = temporary_root / "allowed_signers"
            signature_path = temporary_root / "report.sshsig"
            for path, data in (
                (allowed_path, (key.allowed_signers_line + "\n").encode("ascii")),
                (signature_path, signature),
            ):
                descriptor = os.open(
                    path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                )
                try:
                    offset = 0
                    while offset < len(data):
                        written = os.write(descriptor, data[offset:])
                        if written <= 0:
                            raise OSError
                        offset += written
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            environment = {
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
            }
            completed = subprocess.run(
                [
                    str(self._ssh_keygen_path),
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_path),
                    "-I",
                    principal,
                    "-n",
                    namespace,
                    "-s",
                    str(signature_path),
                ],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=10,
                check=False,
            )
            if completed.returncode != 0:
                raise ControllerTrustError(CONTROLLER_SIGNATURE_INVALID_ERROR)
        except ControllerTrustError:
            raise
        except (OSError, subprocess.SubprocessError):
            raise ControllerTrustError(CONTROLLER_SIGNATURE_INVALID_ERROR) from None
        finally:
            if temporary_root is not None:
                for name in ("report.sshsig", "allowed_signers"):
                    try:
                        (temporary_root / name).unlink()
                    except FileNotFoundError:
                        pass
                try:
                    temporary_root.rmdir()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _authorize_key(
        policy: ControllerTrustPolicy,
        *,
        key_id: object,
        principal: object,
        controller_build_sha256: object,
        signed_at: datetime,
        now: datetime,
    ) -> ControllerTrustKey:
        if (
            type(key_id) is not str
            or type(principal) is not str
            or not _is_sha256(controller_build_sha256)
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        key = policy.key(key_id)
        if (
            key.status != "active"
            or principal != key.principal
            or controller_build_sha256
            not in key.allowed_controller_build_sha256
            or not key.not_before <= signed_at < key.not_after
            or not key.not_before <= now < key.not_after
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        return key

    def verify_preflight(
        self,
        payload: bytes,
        signature: bytes,
        *,
        expectation: PreflightExpectation,
        now: datetime | None = None,
    ) -> VerifiedControllerPreflight:
        code = CONTROLLER_PREFLIGHT_INVALID_ERROR
        if type(expectation) is not PreflightExpectation:
            raise ControllerTrustError(code)
        current = now or datetime.now(timezone.utc).replace(microsecond=0)
        current_text = _timestamp(current, code=code)
        del current_text
        policy, _allowed = self._load_policy()
        if not any(item.status == "active" for item in policy.keys):
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        decoded = _decode_canonical_mapping(
            payload,
            max_bytes=MAX_PREFLIGHT_BYTES,
            code=code,
        )
        exact = _exact_mapping(
            decoded,
            frozenset(
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
            ),
            code=code,
        )
        issued_at = _parse_timestamp(exact["issued_at"], code=code)
        expires_at = _parse_timestamp(exact["expires_at"], code=code)
        _parse_required_capture_payload(exact["required_captures"], code=code)
        if (
            exact["schema_version"] != CONTROLLER_PREFLIGHT_SCHEMA_VERSION
            or exact["controller_id"] != CONTROLLER_ID
            or exact["signature_namespace"] != PREFLIGHT_SIGNATURE_NAMESPACE
            or exact["required_stability_milliseconds"]
            != FIXED_REQUIRED_STABILITY_MILLISECONDS
            or exact["trust_policy_sha256"] != policy.policy_sha256
            or exact["allowed_signers_sha256"]
            != policy.allowed_signers_sha256
            or expires_at <= issued_at
            or expires_at - issued_at
            > timedelta(seconds=MAX_PREFLIGHT_LIFETIME_SECONDS)
            or current < issued_at - timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
            or current >= expires_at
        ):
            raise ControllerTrustError(code)
        expected = {
            "nonce_sha256": expectation.nonce_sha256,
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "target_scope_sha256": expectation.target_scope_sha256,
            "operator_envelope_sha256": expectation.operator_envelope_sha256,
            "fixture_manifest_sha256": expectation.fixture_manifest_sha256,
        }
        if any(exact[name] != value for name, value in expected.items()):
            raise ControllerTrustError(
                CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR
            )
        key = self._authorize_key(
            policy,
            key_id=exact["signing_key_id"],
            principal=exact["signer_principal"],
            controller_build_sha256=exact["controller_build_sha256"],
            signed_at=issued_at,
            now=current,
        )
        self._verify_signature(
            payload,
            signature,
            namespace=PREFLIGHT_SIGNATURE_NAMESPACE,
            principal=key.principal,
            key=key,
        )
        return VerifiedControllerPreflight(
            issued_at=issued_at,
            expires_at=expires_at,
            key_id=key.key_id,
            principal=key.principal,
            controller_build_sha256=str(exact["controller_build_sha256"]),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            policy_sha256=policy.policy_sha256,
            allowed_signers_sha256=policy.allowed_signers_sha256,
        )

    def verify_report_binding(
        self,
        payload: bytes,
        signature: bytes,
        *,
        expectation: ReportExpectation,
        now: datetime | None = None,
    ) -> VerifiedControllerReportBinding:
        code = CONTROLLER_REPORT_BINDING_INVALID_ERROR
        if type(expectation) is not ReportExpectation:
            raise ControllerTrustError(code)
        current = now or datetime.now(timezone.utc).replace(microsecond=0)
        _timestamp(current, code=code)
        policy, _allowed = self._load_policy()
        if not any(item.status == "active" for item in policy.keys):
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        decoded = _decode_canonical_mapping(
            payload,
            max_bytes=MAX_REPORT_BINDING_BYTES,
            code=code,
        )
        exact = _exact_mapping(
            decoded,
            frozenset(
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
            ),
            code=code,
        )
        signed_at = _parse_timestamp(exact["signed_at"], code=code)
        started = _parse_timestamp(exact["window_started_at"], code=code)
        ended = _parse_timestamp(exact["window_ended_at"], code=code)
        captures = _parse_observed_captures(exact["observed_captures"])
        hashes = _normalize_hashes(exact["listening_output_hashes"], code=code)
        metric_count = exact["metric_sample_count"]
        elapsed = exact["stability_elapsed_milliseconds"]
        if (
            exact["schema_version"]
            != CONTROLLER_REPORT_BINDING_SCHEMA_VERSION
            or exact["controller_id"] != CONTROLLER_ID
            or exact["signature_namespace"] != REPORT_SIGNATURE_NAMESPACE
            or exact["required_stability_milliseconds"]
            != FIXED_REQUIRED_STABILITY_MILLISECONDS
            or exact["trust_policy_sha256"] != policy.policy_sha256
            or exact["allowed_signers_sha256"]
            != policy.allowed_signers_sha256
            or type(metric_count) is not int
            or metric_count < 31
            or type(elapsed) is not int
            or elapsed < FIXED_REQUIRED_STABILITY_MILLISECONDS
            or ended <= started
            or int((ended - started).total_seconds() * 1000) != elapsed
            or ended > signed_at
            or signed_at > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS)
            or current - signed_at > timedelta(seconds=MAX_REPORT_AGE_SECONDS)
            or not _is_sha256(exact["metric_sample_chain_sha256"])
            or not _is_sha256(exact["browser_binary_sha256"])
        ):
            raise ControllerTrustError(code)
        expected_values: dict[str, object] = {
            "preflight_payload_sha256": expectation.preflight_payload_sha256,
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "target_scope_sha256": expectation.target_scope_sha256,
            "probe_request_sha256": expectation.probe_request_sha256,
            "request_fingerprint_sha256": expectation.request_fingerprint_sha256,
            "automatic_edition_fingerprint_sha256": (
                expectation.automatic_edition_fingerprint_sha256
            ),
            "manual_edition_fingerprint_sha256": (
                expectation.manual_edition_fingerprint_sha256
            ),
            "collector_report_sha256": expectation.collector_report_sha256,
            "probe_report_sha256": expectation.probe_report_sha256,
        }
        if (
            hashes != expectation.listening_output_hashes
            or any(exact[name] != value for name, value in expected_values.items())
        ):
            raise ControllerTrustError(
                CONTROLLER_REPORT_BINDING_MISMATCH_ERROR
            )
        key = self._authorize_key(
            policy,
            key_id=exact["signing_key_id"],
            principal=exact["signer_principal"],
            controller_build_sha256=exact["controller_build_sha256"],
            signed_at=signed_at,
            now=current,
        )
        if (
            exact["browser_binary_sha256"]
            not in key.allowed_browser_build_sha256
        ):
            raise ControllerTrustError(CONTROLLER_TRUST_ROOT_HOLD_ERROR)
        self._verify_signature(
            payload,
            signature,
            namespace=REPORT_SIGNATURE_NAMESPACE,
            principal=key.principal,
            key=key,
        )
        return VerifiedControllerReportBinding(
            signed_at=signed_at,
            key_id=key.key_id,
            principal=key.principal,
            controller_build_sha256=str(exact["controller_build_sha256"]),
            browser_binary_sha256=str(exact["browser_binary_sha256"]),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            policy_sha256=policy.policy_sha256,
            allowed_signers_sha256=policy.allowed_signers_sha256,
            captures=captures,
            stability_elapsed_milliseconds=int(elapsed),
            metric_sample_count=int(metric_count),
            metric_sample_chain_sha256=str(
                exact["metric_sample_chain_sha256"]
            ),
        )


class FixedControllerTrustVerifier(_ControllerTrustVerifier):
    """Production verification port with no caller-selected trust material."""

    def __init__(self) -> None:
        super().__init__(
            policy_path=TRUST_POLICY_PATH,
            allowed_signers_path=ALLOWED_SIGNERS_PATH,
            ssh_keygen_path=SSH_KEYGEN_PATH,
        )


def _test_verifier(
    policy_path: Path,
    allowed_signers_path: Path,
    *,
    ssh_keygen_path: Path = SSH_KEYGEN_PATH,
) -> _ControllerTrustVerifier:
    """Internal test seam; production callers must use the fixed port."""

    return _ControllerTrustVerifier(
        policy_path=policy_path,
        allowed_signers_path=allowed_signers_path,
        ssh_keygen_path=ssh_keygen_path,
    )


__all__ = [
    "ALLOWED_SIGNERS_PATH",
    "CONTROLLER_ID",
    "CONTROLLER_PREFLIGHT_BINDING_MISMATCH_ERROR",
    "CONTROLLER_PREFLIGHT_INVALID_ERROR",
    "CONTROLLER_PREFLIGHT_SCHEMA_VERSION",
    "CONTROLLER_REPORT_BINDING_INVALID_ERROR",
    "CONTROLLER_REPORT_BINDING_MISMATCH_ERROR",
    "CONTROLLER_REPORT_BINDING_SCHEMA_VERSION",
    "CONTROLLER_SIGNATURE_INVALID_ERROR",
    "CONTROLLER_TRUST_POLICY_INVALID_ERROR",
    "CONTROLLER_TRUST_POLICY_SCHEMA_VERSION",
    "CONTROLLER_TRUST_ROOT_HOLD_ERROR",
    "FIXED_REQUIRED_CAPTURES",
    "FIXED_REQUIRED_STABILITY_MILLISECONDS",
    "FixedControllerTrustVerifier",
    "ObservedCaptureBinding",
    "PREFLIGHT_SIGNATURE_NAMESPACE",
    "PreflightExpectation",
    "REPORT_SIGNATURE_NAMESPACE",
    "ReportExpectation",
    "RequiredCapture",
    "TRUST_POLICY_PATH",
    "VerifiedControllerPreflight",
    "VerifiedControllerReportBinding",
    "canonical_json_bytes",
]
