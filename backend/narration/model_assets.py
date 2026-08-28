"""Pinned MOSS Nano model/source installation and verification.

The production Sidecar never downloads assets.  A separate lifecycle owner
uses this module to create one immutable, content-addressed release and then
mounts the asset root read-only into the Sidecar.
"""

from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import errno
import fcntl
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import tempfile
import threading
import time
from typing import BinaryIO, Final, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MODEL_LOCK_SCHEMA: Final = "moss-tts-t1-dep-model-source-lock/1.1"
MODEL_LOCK_SHA256: Final = "c6491f44c87e05d3d8075a102d65c019e7b40608a977baa05366929e7684e137"
MODEL_INVENTORY_SHA256: Final = "d0f173dbc661d0352825dd28a5b35a1c65d60be540badacf7ef3b1a57b0b416d"
SOURCE_TREE_SHA256: Final = "547f61c24427a59d802cc31dfe532e135303b6b9f71469be19a7f35acd5d4c94"
MODEL_TREE_SHA256: Final = "92419b269673cd698afab06ef0e3f0b60673862c86190cc6c57ed010db9aca98"
ALLOWED_COMPONENT_IDS: Final = (
    "moss-tts-nano-source",
    "moss-tts-nano-100m-onnx",
    "moss-audio-tokenizer-nano-onnx",
)
EXPECTED_ARTIFACT_COUNTS: Final = {
    "moss-tts-nano-source": 13,
    "moss-tts-nano-100m-onnx": 10,
    "moss-audio-tokenizer-nano-onnx": 6,
}
EXPECTED_REPOSITORIES: Final = {
    "moss-tts-nano-source": ("github", "OpenMOSS/MOSS-TTS-Nano"),
    "moss-tts-nano-100m-onnx": (
        "huggingface",
        "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
    ),
    "moss-audio-tokenizer-nano-onnx": (
        "huggingface",
        "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX",
    ),
}
READY_SCHEMA: Final = "moss-tts-model-assets-ready/1.0"
SIDECAR_UID: Final = 65532
SIDECAR_GID: Final = 65532
MAX_ARTIFACT_BYTES: Final = 2 * 1024 * 1024 * 1024
_HEX = re.compile(r"^[0-9a-f]+$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class ModelAssetError(RuntimeError):
    """Fail-closed model lifecycle error with a stable redacted code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_HF_REDIRECT_HOSTS: Final = frozenset({"huggingface.co", "us.aws.cdn.hf.co"})
_APPROVED_DOWNLOAD_HOSTS: Final = _HF_REDIRECT_HOSTS | {"raw.githubusercontent.com"}
_TRANSPARENT_PROXY_FAKE_IP_RANGE: Final = ipaddress.ip_network("198.18.0.0/15")
_MAX_REDIRECTS: Final = 3
_MAX_DOWNLOAD_ATTEMPTS: Final = 3
_RETRYABLE_HTTP_STATUS: Final = frozenset({408, 425, 429, 500, 502, 503, 504})


def _reject_private_resolution(host: str) -> None:
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise ModelAssetError("DOWNLOAD_DNS_FAILURE", "artifact host cannot be resolved") from error
    if not addresses:
        raise ModelAssetError("DOWNLOAD_DNS_FAILURE", "artifact host has no address")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        transparent_proxy_mapping = (
            host in _APPROVED_DOWNLOAD_HOSTS
            and address.version == 4
            and address in _TRANSPARENT_PROXY_FAKE_IP_RANGE
        )
        if not address.is_global and not transparent_proxy_mapping:
            raise ModelAssetError("DOWNLOAD_PRIVATE_ADDRESS_FORBIDDEN", "artifact host resolved outside public Internet")


def _safe_redirect_url(current_url: str, location: str) -> str:
    """Accept only observed official HF cache/CDN redirects.

    Signed query values are intentionally neither returned in diagnostics nor
    persisted.  Callers record only hop status and host class.
    """

    candidate = urljoin(current_url, location)
    current = urlsplit(current_url)
    target = urlsplit(candidate)
    if (
        target.scheme != "https"
        or target.username is not None
        or target.password is not None
        or target.port is not None
        or target.fragment
        or target.hostname not in _HF_REDIRECT_HOSTS
    ):
        raise ModelAssetError("DOWNLOAD_REDIRECT_FORBIDDEN", "artifact redirect target is not approved")
    if current.hostname == "huggingface.co" and target.hostname == "huggingface.co":
        if not target.path.startswith("/api/resolve-cache/"):
            raise ModelAssetError("DOWNLOAD_REDIRECT_FORBIDDEN", "Hugging Face cache redirect path is not approved")
    elif not (current.hostname == "huggingface.co" and target.hostname == "us.aws.cdn.hf.co"):
        raise ModelAssetError("DOWNLOAD_REDIRECT_FORBIDDEN", "artifact redirect transition is not approved")
    _reject_private_resolution(str(target.hostname))
    return candidate


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_blob_sha1_file(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(raw: object) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise ModelAssetError("LOCK_PATH_INVALID", "artifact path is invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ModelAssetError("LOCK_PATH_INVALID", "artifact path is not canonical")
    return path


def _validate_url(component: Mapping[str, object], artifact: Mapping[str, object]) -> str:
    raw = artifact.get("url")
    if not isinstance(raw, str):
        raise ModelAssetError("LOCK_URL_INVALID", "artifact URL is missing")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or unquote(parsed.path) != parsed.path
    ):
        raise ModelAssetError("LOCK_URL_INVALID", "artifact URL is not fixed HTTPS")
    repository = str(component["repository"])
    revision = str(component["revision"])
    relative = str(artifact["path"])
    provider = component["provider"]
    if provider == "github":
        expected_host = "raw.githubusercontent.com"
        expected_path = f"/{repository}/{revision}/{relative}"
    elif provider == "huggingface":
        expected_host = "huggingface.co"
        expected_path = f"/{repository}/resolve/{revision}/{relative}"
    else:
        raise ModelAssetError("LOCK_PROVIDER_INVALID", "provider is not approved")
    if parsed.hostname != expected_host or parsed.path != expected_path:
        raise ModelAssetError("LOCK_ORIGIN_INVALID", "artifact origin or revision differs from lock")
    return raw


def load_and_validate_lock(lock_path: Path) -> dict[str, object]:
    """Load the one accepted production lock and reject every drift."""

    try:
        raw = lock_path.read_bytes()
    except OSError as error:
        raise ModelAssetError("LOCK_UNREADABLE", "production model lock is unreadable") from error
    if _sha256_bytes(raw) != MODEL_LOCK_SHA256:
        raise ModelAssetError("LOCK_HASH_MISMATCH", "production model lock hash mismatch")
    try:
        lock = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelAssetError("LOCK_JSON_INVALID", "production model lock is invalid JSON") from error
    if not isinstance(lock, dict) or lock.get("schema_version") != MODEL_LOCK_SCHEMA:
        raise ModelAssetError("LOCK_SCHEMA_INVALID", "production model lock schema mismatch")
    if lock.get("allowed_component_ids") != list(ALLOWED_COMPONENT_IDS):
        raise ModelAssetError("LOCK_ALLOWLIST_MISMATCH", "component allowlist mismatch")
    if lock.get("component_count") != 3 or lock.get("artifact_count") != 29:
        raise ModelAssetError("LOCK_COUNT_MISMATCH", "production model lock count mismatch")
    inventory = lock.get("inventory")
    trees = lock.get("runtime_tree_canonicalization")
    if not isinstance(inventory, dict) or inventory.get("sha256") != MODEL_INVENTORY_SHA256:
        raise ModelAssetError("LOCK_INVENTORY_MISMATCH", "inventory fingerprint mismatch")
    if not isinstance(trees, dict) or (
        trees.get("source_tree_sha256") != SOURCE_TREE_SHA256
        or trees.get("model_tree_sha256") != MODEL_TREE_SHA256
    ):
        raise ModelAssetError("LOCK_TREE_MISMATCH", "runtime tree fingerprint mismatch")
    components = lock.get("components")
    if not isinstance(components, list) or [row.get("component_id") for row in components if isinstance(row, dict)] != list(ALLOWED_COMPONENT_IDS):
        raise ModelAssetError("LOCK_COMPONENTS_INVALID", "components are missing, duplicated, or reordered")

    seen_paths: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    artifact_count = 0
    canonical_components: list[dict[str, object]] = []
    for row in components:
        if not isinstance(row, dict):
            raise ModelAssetError("LOCK_COMPONENT_INVALID", "component entry is invalid")
        component_id = row.get("component_id")
        if component_id not in ALLOWED_COMPONENT_IDS:
            raise ModelAssetError("LOCK_COMPONENT_FORBIDDEN", "component is not approved")
        expected_provider, expected_repository = EXPECTED_REPOSITORIES[str(component_id)]
        if row.get("provider") != expected_provider or row.get("repository") != expected_repository:
            raise ModelAssetError("LOCK_ORIGIN_INVALID", "component origin differs from lock policy")
        if row.get("download_allowed") is not True or not _REVISION.fullmatch(str(row.get("revision", ""))):
            raise ModelAssetError("LOCK_REVISION_INVALID", "component revision is not approved")
        artifacts = row.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != EXPECTED_ARTIFACT_COUNTS[str(component_id)]:
            raise ModelAssetError("LOCK_ARTIFACTS_INVALID", "component artifact count mismatch")
        selected_bytes = 0
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ModelAssetError("LOCK_ARTIFACT_INVALID", "artifact entry is invalid")
            relative = _safe_relative_path(artifact.get("path"))
            identity = (str(component_id), relative.as_posix())
            if identity in seen_paths:
                raise ModelAssetError("LOCK_DUPLICATE_PATH", "artifact path is duplicated")
            seen_paths.add(identity)
            url = _validate_url(row, artifact)
            if url in seen_urls:
                raise ModelAssetError("LOCK_DUPLICATE_URL", "artifact URL is duplicated")
            seen_urls.add(url)
            size = artifact.get("size")
            if isinstance(size, bool) or not isinstance(size, int) or not (1 <= size <= MAX_ARTIFACT_BYTES):
                raise ModelAssetError("LOCK_SIZE_INVALID", "artifact size is invalid")
            algorithm = artifact.get("hash_algorithm")
            digest = artifact.get("hash")
            length = 64 if algorithm == "sha256" else 40 if algorithm == "git-blob-sha1" else 0
            if not isinstance(digest, str) or len(digest) != length or not _HEX.fullmatch(digest):
                raise ModelAssetError("LOCK_DIGEST_INVALID", "artifact digest is invalid")
            selected_bytes += size
            artifact_count += 1
        if selected_bytes != row.get("selected_bytes"):
            raise ModelAssetError("LOCK_SELECTED_BYTES_MISMATCH", "component byte count mismatch")
        normalized = json.loads(json.dumps(row))
        normalized["artifacts"] = sorted(normalized["artifacts"], key=lambda item: item["path"])
        canonical_components.append(normalized)
    canonical_components.sort(key=lambda item: item["component_id"])
    if artifact_count != 29 or _sha256_bytes(_canonical_bytes({"components": canonical_components})) != MODEL_INVENTORY_SHA256:
        raise ModelAssetError("LOCK_INVENTORY_MISMATCH", "canonical inventory mismatch")
    return lock


def release_root(assets_root: Path) -> Path:
    return assets_root / "releases" / MODEL_INVENTORY_SHA256


def _ensure_controlled_directory(
    path: Path,
    *,
    code: str,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> None:
    try:
        details = path.lstat()
    except OSError as error:
        raise ModelAssetError(code, "controlled asset directory is unavailable") from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise ModelAssetError(code, "controlled asset directory is invalid")
    if details.st_mode & stat.S_IXUSR == 0:
        raise ModelAssetError("RELEASE_PERMISSION_INVALID", "controlled asset directory is not traversable")
    if details.st_mode & 0o022:
        raise ModelAssetError("RELEASE_PERMISSION_INVALID", "controlled asset directory is group/world writable")
    if expected_uid is not None and details.st_uid != expected_uid:
        raise ModelAssetError("RELEASE_OWNER_MISMATCH", "controlled asset owner differs from Sidecar identity")
    if expected_gid is not None and details.st_gid != expected_gid:
        raise ModelAssetError("RELEASE_GROUP_MISMATCH", "controlled asset group differs from Sidecar identity")


def _expected_release_entries(
    lock: Mapping[str, object], release: Path
) -> tuple[set[str], set[str]]:
    files = {"READY.json"}
    directories: set[str] = set()
    for component, artifact in _iter_artifacts(lock):
        target = _artifact_target(release, component, artifact)
        relative = target.relative_to(release).as_posix()
        files.add(relative)
        parent = PurePosixPath(relative).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return files, directories


def _verify_exact_tree_contents(
    lock: Mapping[str, object],
    release: Path,
    *,
    immutable_modes: bool,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> None:
    try:
        release_details = release.lstat()
    except OSError as error:
        raise ModelAssetError("RELEASE_TREE_UNREADABLE", "release tree root is unreadable") from error
    if stat.S_ISLNK(release_details.st_mode) or not stat.S_ISDIR(release_details.st_mode):
        raise ModelAssetError("RELEASE_TREE_SYMLINK", "release tree root is invalid")
    if immutable_modes and stat.S_IMODE(release_details.st_mode) != 0o555:
        raise ModelAssetError("RELEASE_PERMISSION_INVALID", "immutable release root mode differs from 0555")
    if expected_uid is not None and release_details.st_uid != expected_uid:
        raise ModelAssetError("RELEASE_OWNER_MISMATCH", "release root owner differs from Sidecar identity")
    if expected_gid is not None and release_details.st_gid != expected_gid:
        raise ModelAssetError("RELEASE_GROUP_MISMATCH", "release root group differs from Sidecar identity")
    expected_files, expected_directories = _expected_release_entries(lock, release)
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for raw_root, directory_names, file_names in os.walk(release, topdown=True, followlinks=False):
        root = Path(raw_root)
        for name in directory_names:
            path = root / name
            relative = path.relative_to(release).as_posix()
            try:
                details = path.lstat()
            except OSError as error:
                raise ModelAssetError("RELEASE_TREE_UNREADABLE", "release tree is unreadable") from error
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise ModelAssetError("RELEASE_TREE_SYMLINK", "release tree contains a symlink or non-directory")
            if details.st_mode & stat.S_IXUSR == 0:
                raise ModelAssetError("RELEASE_PERMISSION_INVALID", "release directory is not traversable")
            if immutable_modes and stat.S_IMODE(details.st_mode) != 0o555:
                raise ModelAssetError("RELEASE_PERMISSION_INVALID", "immutable release directory mode differs from 0555")
            if expected_uid is not None and details.st_uid != expected_uid:
                raise ModelAssetError("RELEASE_OWNER_MISMATCH", "release directory owner differs from Sidecar identity")
            if expected_gid is not None and details.st_gid != expected_gid:
                raise ModelAssetError("RELEASE_GROUP_MISMATCH", "release directory group differs from Sidecar identity")
            actual_directories.add(relative)
        for name in file_names:
            path = root / name
            relative = path.relative_to(release).as_posix()
            try:
                details = path.lstat()
            except OSError as error:
                raise ModelAssetError("RELEASE_TREE_UNREADABLE", "release tree is unreadable") from error
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
                raise ModelAssetError("RELEASE_TREE_SYMLINK", "release tree contains a symlink or non-file")
            if immutable_modes and stat.S_IMODE(details.st_mode) != 0o444:
                raise ModelAssetError("RELEASE_PERMISSION_INVALID", "immutable release file mode differs from 0444")
            if expected_uid is not None and details.st_uid != expected_uid:
                raise ModelAssetError("RELEASE_OWNER_MISMATCH", "release file owner differs from Sidecar identity")
            if expected_gid is not None and details.st_gid != expected_gid:
                raise ModelAssetError("RELEASE_GROUP_MISMATCH", "release file group differs from Sidecar identity")
            actual_files.add(relative)
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ModelAssetError("RELEASE_TREE_NOT_EXACT", "release tree differs from the exact allowlist")


def _verify_exact_release_tree(
    lock: Mapping[str, object],
    assets_root: Path,
    release: Path,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> None:
    _ensure_controlled_directory(
        assets_root,
        code="ASSETS_ROOT_INVALID",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _ensure_controlled_directory(
        assets_root / "releases",
        code="RELEASES_ROOT_INVALID",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _ensure_controlled_directory(
        release,
        code="RELEASE_ROOT_INVALID",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _verify_exact_tree_contents(
        lock,
        release,
        immutable_modes=True,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )


def _artifact_target(release: Path, component: Mapping[str, object], artifact: Mapping[str, object]) -> Path:
    relative = _safe_relative_path(artifact["path"])
    if component["component_id"] == "moss-tts-nano-source":
        root = release / "source"
    else:
        root = release / "models" / str(component["repository"]).rsplit("/", 1)[-1]
    target = root.joinpath(*relative.parts)
    try:
        target.resolve(strict=False).relative_to(release.resolve(strict=False))
    except ValueError as error:
        raise ModelAssetError("TARGET_PATH_ESCAPE", "artifact target escapes release") from error
    return target


def _iter_artifacts(lock: Mapping[str, object]) -> Iterator[tuple[Mapping[str, object], Mapping[str, object]]]:
    for component in lock["components"]:  # type: ignore[index]
        for artifact in component["artifacts"]:  # type: ignore[index]
            yield component, artifact


def _verify_artifact(path: Path, artifact: Mapping[str, object]) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        code = "ARTIFACT_SYMLINK_FORBIDDEN" if error.errno == errno.ELOOP else "ARTIFACT_OPEN_FAILED"
        raise ModelAssetError(code, "installed artifact cannot be opened safely") from error
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size != artifact["size"]:
            raise ModelAssetError("ARTIFACT_SIZE_MISMATCH", "installed artifact is missing or has wrong size")
        sha256 = hashlib.sha256()
        blob_sha1 = hashlib.sha1(usedforsecurity=False)
        blob_sha1.update(f"blob {details.st_size}\0".encode("ascii"))
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                sha256.update(block)
                blob_sha1.update(block)
        actual_sha256 = sha256.hexdigest()
        locked = actual_sha256 if artifact["hash_algorithm"] == "sha256" else blob_sha1.hexdigest()
        if locked != artifact["hash"]:
            raise ModelAssetError("ARTIFACT_HASH_MISMATCH", "installed artifact hash mismatch")
        return actual_sha256
    finally:
        os.close(descriptor)


def verify_release(
    lock_path: Path,
    assets_root: Path,
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> dict[str, object]:
    lock = load_and_validate_lock(lock_path)
    release = release_root(assets_root)
    marker = release / "READY.json"
    if not release.is_dir() or release.is_symlink() or not marker.is_file() or marker.is_symlink():
        raise ModelAssetError("RELEASE_NOT_READY", "immutable model release is not published")
    _verify_exact_release_tree(
        lock,
        assets_root,
        release,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    source_rows: list[dict[str, str]] = []
    model_rows: list[dict[str, str]] = []
    for component, artifact in _iter_artifacts(lock):
        actual = _verify_artifact(_artifact_target(release, component, artifact), artifact)
        relative = str(artifact["path"])
        if component["component_id"] == "moss-tts-nano-source":
            source_rows.append({"path": relative, "sha256": actual})
        else:
            model_rows.append({"name": f"{component['component_id']}/{relative}", "sha256": actual})
    source_hash = _sha256_bytes(_canonical_bytes(source_rows))
    model_hash = _sha256_bytes(_canonical_bytes(sorted(model_rows, key=lambda row: row["name"])))
    if source_hash != SOURCE_TREE_SHA256 or model_hash != MODEL_TREE_SHA256:
        raise ModelAssetError("RELEASE_TREE_MISMATCH", "installed runtime tree hash mismatch")
    try:
        ready = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelAssetError("READY_MARKER_INVALID", "release marker is invalid") from error
    expected = {
        "schema_version": READY_SCHEMA,
        "inventory_sha256": MODEL_INVENTORY_SHA256,
        "source_tree_sha256": SOURCE_TREE_SHA256,
        "model_tree_sha256": MODEL_TREE_SHA256,
        "artifact_count": 29,
    }
    if ready != expected:
        raise ModelAssetError("READY_MARKER_MISMATCH", "release marker does not match verified trees")
    return {**expected, "release_path": str(release)}


def _download_to(
    stream: BinaryIO,
    target: Path,
    artifact: Mapping[str, object],
    *,
    cancel_event: threading.Event | None = None,
    resume_from: int = 0,
    preserve_partial: bool = False,
) -> None:
    expected_size = int(artifact["size"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.part")
    sha256 = hashlib.sha256()
    blob_sha1 = hashlib.sha1(usedforsecurity=False)
    blob_sha1.update(f"blob {expected_size}\0".encode("ascii"))
    observed = resume_from
    completed = False
    try:
        if target.exists() or target.is_symlink():
            raise ModelAssetError("DOWNLOAD_TARGET_EXISTS", "artifact target already exists")
        if resume_from:
            try:
                details = temporary.lstat()
            except OSError as error:
                raise ModelAssetError(
                    "DOWNLOAD_RESUME_INVALID", "artifact partial file is unavailable"
                ) from error
            if (
                stat.S_ISLNK(details.st_mode)
                or not stat.S_ISREG(details.st_mode)
                or details.st_size != resume_from
                or not (0 < resume_from <= expected_size)
            ):
                raise ModelAssetError(
                    "DOWNLOAD_RESUME_INVALID", "artifact partial file is invalid"
                )
            try:
                with temporary.open("rb") as partial:
                    for block in iter(lambda: partial.read(1024 * 1024), b""):
                        sha256.update(block)
                        blob_sha1.update(block)
                output_stream = temporary.open("ab")
            except OSError as error:
                raise ModelAssetError(
                    "DOWNLOAD_TEMP_OPEN_FAILED",
                    "artifact partial file cannot be resumed",
                ) from error
        else:
            try:
                output_stream = temporary.open("xb")
            except FileExistsError as error:
                raise ModelAssetError(
                    "DOWNLOAD_TEMP_EXISTS", "artifact temporary file already exists"
                ) from error
            except OSError as error:
                raise ModelAssetError(
                    "DOWNLOAD_TEMP_OPEN_FAILED",
                    "artifact temporary file cannot be opened",
                ) from error
        with output_stream as output:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ModelAssetError("DOWNLOAD_CANCELLED", "artifact download was cancelled after peer failure")
                block = stream.read(min(1024 * 1024, expected_size - observed + 1))
                if not block:
                    break
                if cancel_event is not None and cancel_event.is_set():
                    raise ModelAssetError("DOWNLOAD_CANCELLED", "artifact download was cancelled after peer failure")
                observed += len(block)
                if observed > expected_size:
                    raise ModelAssetError("DOWNLOAD_SIZE_MISMATCH", "download exceeded locked size")
                sha256.update(block)
                blob_sha1.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if observed != expected_size:
            raise ModelAssetError("DOWNLOAD_SIZE_MISMATCH", "download did not match locked size")
        observed_hash = sha256.hexdigest() if artifact["hash_algorithm"] == "sha256" else blob_sha1.hexdigest()
        if observed_hash != artifact["hash"]:
            raise ModelAssetError("DOWNLOAD_HASH_MISMATCH", "download did not match locked digest")
        os.chmod(temporary, 0o444)
        os.replace(temporary, target)
        completed = True
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if not completed and not preserve_partial:
            temporary.unlink(missing_ok=True)


def _partial_size(target: Path, artifact: Mapping[str, object]) -> int:
    temporary = target.with_name(f".{target.name}.part")
    try:
        details = temporary.lstat()
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise ModelAssetError(
            "DOWNLOAD_RESUME_INVALID", "artifact partial file cannot be inspected"
        ) from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or not (0 <= details.st_size <= int(artifact["size"]))
    ):
        raise ModelAssetError(
            "DOWNLOAD_RESUME_INVALID", "artifact partial file is invalid"
        )
    return details.st_size


def _discard_partial(target: Path) -> None:
    temporary = target.with_name(f".{target.name}.part")
    try:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
    except OSError as error:
        raise ModelAssetError(
            "DOWNLOAD_PARTIAL_CLEANUP_FAILED", "artifact partial file cannot be removed"
        ) from error


def _retry_wait(attempt: int, cancel_event: threading.Event | None) -> None:
    delay = min(0.25 * attempt, 1.0)
    if cancel_event is None:
        time.sleep(delay)
    elif cancel_event.wait(delay):
        raise ModelAssetError(
            "DOWNLOAD_CANCELLED", "artifact download was cancelled after peer failure"
        )


def _download_artifact(
    url: str,
    artifact: Mapping[str, object],
    target: Path,
    *,
    timeout_seconds: float,
    cancel_event: threading.Event | None = None,
) -> None:
    opener = build_opener(_NoRedirect())
    last_retryable: ModelAssetError | None = None
    for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
        if cancel_event is not None and cancel_event.is_set():
            _discard_partial(target)
            raise ModelAssetError("DOWNLOAD_CANCELLED", "artifact download was cancelled after peer failure")
        resume_from = _partial_size(target, artifact)
        if resume_from == int(artifact["size"]):
            _download_to(
                io.BytesIO(b""),
                target,
                artifact,
                cancel_event=cancel_event,
                resume_from=resume_from,
                preserve_partial=True,
            )
            return
        current_url = url
        try:
            for hop in range(_MAX_REDIRECTS + 1):
                parsed = urlsplit(current_url)
                if parsed.hostname is None:
                    raise ModelAssetError(
                        "DOWNLOAD_ORIGIN_MISMATCH", "download host is invalid"
                    )
                _reject_private_resolution(parsed.hostname)
                headers = {
                    "User-Agent": "ai-novel-world-2026-model-installer/1"
                }
                if resume_from:
                    headers["Range"] = f"bytes={resume_from}-"
                request = Request(current_url, headers=headers)
                try:
                    response = opener.open(request, timeout=timeout_seconds)
                except HTTPError as error:
                    if 300 <= error.code < 400:
                        location = error.headers.get("Location")
                        if not location or hop >= _MAX_REDIRECTS:
                            raise ModelAssetError(
                                "DOWNLOAD_REDIRECT_FORBIDDEN",
                                "artifact redirect chain is invalid",
                            ) from error
                        current_url = _safe_redirect_url(current_url, location)
                        continue
                    code = (
                        "DOWNLOAD_HTTP_RETRYABLE"
                        if error.code in _RETRYABLE_HTTP_STATUS
                        else "DOWNLOAD_HTTP_FAILURE"
                    )
                    raise ModelAssetError(code, "artifact download failed") from error
                except (URLError, TimeoutError, OSError) as error:
                    raise ModelAssetError(
                        "DOWNLOAD_TRANSPORT_FAILURE",
                        "artifact download transport failed",
                    ) from error
                with response:
                    expected_status = 206 if resume_from else 200
                    if response.geturl() != current_url or response.status != expected_status:
                        raise ModelAssetError(
                            "DOWNLOAD_RANGE_MISMATCH"
                            if resume_from
                            else "DOWNLOAD_ORIGIN_MISMATCH",
                            "download origin or status changed",
                        )
                    expected_remaining = int(artifact["size"]) - resume_from
                    content_length = response.headers.get("Content-Length")
                    if (
                        content_length is None
                        or not content_length.isdigit()
                        or int(content_length) != expected_remaining
                    ):
                        raise ModelAssetError(
                            "DOWNLOAD_SIZE_MISMATCH",
                            "response length differs from locked remaining bytes",
                        )
                    if resume_from:
                        expected_range = (
                            f"bytes {resume_from}-{int(artifact['size']) - 1}/"
                            f"{int(artifact['size'])}"
                        )
                        if response.headers.get("Content-Range") != expected_range:
                            raise ModelAssetError(
                                "DOWNLOAD_RANGE_MISMATCH",
                                "response Content-Range differs from the locked artifact",
                            )
                    _download_to(
                        response,
                        target,
                        artifact,
                        cancel_event=cancel_event,
                        resume_from=resume_from,
                        preserve_partial=True,
                    )
                    return
            raise ModelAssetError(
                "DOWNLOAD_REDIRECT_FORBIDDEN", "artifact redirect limit exceeded"
            )
        except (OSError, TimeoutError, URLError) as error:
            failure = ModelAssetError(
                "DOWNLOAD_TRANSPORT_FAILURE", "artifact download transport failed"
            )
            failure.__cause__ = error
        except ModelAssetError as error:
            failure = error
        retryable = failure.code in {
            "DOWNLOAD_TRANSPORT_FAILURE",
            "DOWNLOAD_HTTP_RETRYABLE",
            "DOWNLOAD_SIZE_MISMATCH",
        }
        if not retryable or attempt == _MAX_DOWNLOAD_ATTEMPTS:
            _discard_partial(target)
            raise failure
        last_retryable = failure
        try:
            _retry_wait(attempt, cancel_event)
        except ModelAssetError:
            _discard_partial(target)
            raise
    _discard_partial(target)
    raise last_retryable or ModelAssetError(
        "DOWNLOAD_RETRY_EXHAUSTED", "artifact download retries were exhausted"
    )


@contextmanager
def _exclusive_install_lock(assets_root: Path):
    try:
        assets_root.mkdir(parents=True, exist_ok=True)
        if assets_root.is_symlink():
            raise ModelAssetError("ASSETS_ROOT_INVALID", "assets root cannot be a symlink")
        lock_path = assets_root / ".install.lock"
        stream = lock_path.open("a+b")
    except ModelAssetError:
        raise
    except OSError as error:
        raise ModelAssetError("INSTALL_LOCK_OPEN_FAILED", "install lock cannot be opened") from error
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ModelAssetError("INSTALL_LOCKED", "another model install owns the release lock") from error
        yield
    finally:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


def _cleanup_orphan_staging(staging_parent: Path) -> int:
    if not staging_parent.exists():
        return 0
    if staging_parent.is_symlink() or not staging_parent.is_dir():
        raise ModelAssetError("STAGING_ROOT_INVALID", "staging root is invalid")
    removed = 0
    for candidate in staging_parent.iterdir():
        if not candidate.name.startswith(f".staging.{MODEL_INVENTORY_SHA256}."):
            continue
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                candidate.unlink()
            else:
                _remove_owned_tree(candidate)
            removed += 1
        except OSError as error:
            raise ModelAssetError("STAGING_CLEANUP_FAILED", "orphan staging cleanup failed") from error
    return removed


def _remove_owned_tree(path: Path) -> None:
    """Remove only a resolved staging/final tree already owned by this call."""

    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return
    for raw_root, directory_names, file_names in os.walk(path, topdown=False, followlinks=False):
        root = Path(raw_root)
        for name in file_names:
            candidate = root / name
            if not candidate.is_symlink():
                os.chmod(candidate, 0o600)
        for name in directory_names:
            candidate = root / name
            if not candidate.is_symlink():
                os.chmod(candidate, 0o700)
        os.chmod(root, 0o700)
    shutil.rmtree(path)


def _make_release_immutable(staging: Path) -> None:
    directories: list[Path] = []
    for raw_root, directory_names, _ in os.walk(staging, topdown=False, followlinks=False):
        root = Path(raw_root)
        directories.append(root)
        for name in directory_names:
            path = root / name
            if path.is_symlink():
                raise ModelAssetError("RELEASE_TREE_SYMLINK", "staging contains a symlink")
    for directory in directories:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(directory, 0o555)


def _publish_staging(
    lock: Mapping[str, object],
    staging: Path,
    final: Path,
    *,
    expected_uid: int | None,
    expected_gid: int | None,
) -> None:
    # Two checks close both injection windows: one before permissions change,
    # then one on the immutable tree immediately before the same-filesystem
    # directory rename.
    _verify_exact_tree_contents(
        lock,
        staging,
        immutable_modes=False,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _make_release_immutable(staging)
    _verify_exact_tree_contents(
        lock,
        staging,
        immutable_modes=True,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.parent.is_symlink():
        raise ModelAssetError("RELEASES_ROOT_INVALID", "releases root cannot be a symlink")
    if staging.parent.resolve() != final.parent.resolve():
        raise ModelAssetError("RELEASE_PUBLISH_PARENT_MISMATCH", "staging and final must share one atomic rename parent")
    try:
        os.replace(staging, final)
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            code = "RELEASE_ALREADY_EXISTS"
        elif error.errno in {errno.EACCES, errno.EPERM}:
            code = "RELEASE_PUBLISH_PERMISSION_DENIED"
        elif error.errno == errno.EXDEV:
            code = "RELEASE_PUBLISH_CROSS_DEVICE"
        elif error.errno == errno.ENOENT:
            code = "RELEASE_PUBLISH_PARENT_MISSING"
        else:
            code = "RELEASE_PUBLISH_FAILED"
        raise ModelAssetError(code, "immutable release cannot be published") from error


def install_release(
    lock_path: Path,
    assets_root: Path,
    *,
    dry_run: bool = False,
    offline: bool = False,
    timeout_seconds: float = 120.0,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    max_parallel_downloads: int = 4,
) -> dict[str, object]:
    """Install or verify exactly one immutable production release."""

    lock = load_and_validate_lock(lock_path)
    final = release_root(assets_root)
    if timeout_seconds <= 0 or timeout_seconds > 600:
        raise ModelAssetError("DOWNLOAD_TIMEOUT_INVALID", "download timeout is invalid")
    if isinstance(max_parallel_downloads, bool) or not isinstance(max_parallel_downloads, int) or not (1 <= max_parallel_downloads <= 4):
        raise ModelAssetError("DOWNLOAD_CONCURRENCY_INVALID", "download concurrency must be between one and four")
    if dry_run:
        return {
            "operation": "dry_run",
            "artifact_count": 29,
            "inventory_sha256": MODEL_INVENTORY_SHA256,
            "release_path": str(final),
            "network_used": False,
            "max_parallel_downloads": max_parallel_downloads,
        }
    with _exclusive_install_lock(assets_root):
        if final.exists():
            return {
                "operation": "verified_existing",
                **verify_release(
                    lock_path,
                    assets_root,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                ),
            }
        if offline:
            raise ModelAssetError("OFFLINE_RELEASE_MISSING", "offline verification requires an existing complete release")
        staging_parent = assets_root / "releases"
        staging_parent.mkdir(parents=True, exist_ok=True)
        orphan_count = _cleanup_orphan_staging(staging_parent)
        try:
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".staging.{MODEL_INVENTORY_SHA256}.",
                    dir=staging_parent,
                )
            )
        except OSError as error:
            raise ModelAssetError("STAGING_CREATE_FAILED", "staging directory cannot be created") from error
        published = False
        try:
            cancellation = threading.Event()

            def download_one(item: tuple[Mapping[str, object], Mapping[str, object]]) -> None:
                component, artifact = item
                target = _artifact_target(staging, component, artifact)
                _download_artifact(
                    str(artifact["url"]),
                    artifact,
                    target,
                    timeout_seconds=timeout_seconds,
                    cancel_event=cancellation,
                )

            first_error: ModelAssetError | None = None
            executor = ThreadPoolExecutor(
                max_workers=max_parallel_downloads,
                thread_name_prefix="moss-model-download",
            )
            futures = [executor.submit(download_one, item) for item in _iter_artifacts(lock)]
            try:
                for future in as_completed(futures):
                    try:
                        future.result()
                    except CancelledError:
                        continue
                    except (KeyboardInterrupt, SystemExit):
                        cancellation.set()
                        for pending in futures:
                            pending.cancel()
                        raise
                    except BaseException as error:
                        failure = (
                            error
                            if isinstance(error, ModelAssetError)
                            else ModelAssetError(
                                "DOWNLOAD_WORKER_FAILURE",
                                "artifact download worker failed unexpectedly",
                            )
                        )
                        if (
                            first_error is None
                            and failure.code != "DOWNLOAD_CANCELLED"
                        ):
                            first_error = failure
                        cancellation.set()
                        for pending in futures:
                            pending.cancel()
                if first_error is not None:
                    raise first_error
                if cancellation.is_set():
                    raise ModelAssetError("DOWNLOAD_CANCELLED", "artifact download set was cancelled")
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            ready = {
                "schema_version": READY_SCHEMA,
                "inventory_sha256": MODEL_INVENTORY_SHA256,
                "source_tree_sha256": SOURCE_TREE_SHA256,
                "model_tree_sha256": MODEL_TREE_SHA256,
                "artifact_count": 29,
            }
            # Verify actual bytes before the marker or release name becomes visible.
            source_rows: list[dict[str, str]] = []
            model_rows: list[dict[str, str]] = []
            for component, artifact in _iter_artifacts(lock):
                actual = _verify_artifact(_artifact_target(staging, component, artifact), artifact)
                relative = str(artifact["path"])
                if component["component_id"] == "moss-tts-nano-source":
                    source_rows.append({"path": relative, "sha256": actual})
                else:
                    model_rows.append({"name": f"{component['component_id']}/{relative}", "sha256": actual})
            if _sha256_bytes(_canonical_bytes(source_rows)) != SOURCE_TREE_SHA256 or _sha256_bytes(_canonical_bytes(sorted(model_rows, key=lambda row: row["name"]))) != MODEL_TREE_SHA256:
                raise ModelAssetError("RELEASE_TREE_MISMATCH", "downloaded runtime tree hash mismatch")
            marker_tmp = staging / ".READY.json.part"
            try:
                with marker_tmp.open("xb") as stream:
                    stream.write(_canonical_bytes(ready))
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as error:
                raise ModelAssetError("READY_MARKER_WRITE_FAILED", "release marker cannot be written") from error
            os.chmod(marker_tmp, 0o444)
            os.replace(marker_tmp, staging / "READY.json")
            _publish_staging(
                lock,
                staging,
                final,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            published = True
            parent_fd = os.open(final.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            try:
                verified = verify_release(
                    lock_path,
                    assets_root,
                    expected_uid=expected_uid,
                    expected_gid=expected_gid,
                )
            except Exception as verification_error:
                try:
                    _remove_owned_tree(final)
                except OSError as cleanup_error:
                    raise ModelAssetError("FINAL_CLEANUP_FAILED", "failed release could not be removed") from cleanup_error
                raise verification_error
            return {"operation": "installed", "orphan_staging_removed": orphan_count, **verified}
        except BaseException as failure:
            cleanup_target = final if published else staging
            try:
                _remove_owned_tree(cleanup_target)
            except OSError as cleanup_error:
                code = "FINAL_CLEANUP_FAILED" if published else "STAGING_CLEANUP_FAILED"
                raise ModelAssetError(
                    code, "failed install tree could not be removed"
                ) from cleanup_error
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                raise ModelAssetError("INSTALL_INTERRUPTED", "model install was interrupted") from failure
            if isinstance(failure, ModelAssetError):
                raise
            if isinstance(failure, OSError):
                raise ModelAssetError(
                    "INSTALL_FILESYSTEM_FAILURE",
                    "model install filesystem operation failed",
                ) from failure
            raise ModelAssetError(
                "INSTALL_UNEXPECTED_FAILURE", "model install failed unexpectedly"
            ) from failure
