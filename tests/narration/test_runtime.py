from __future__ import annotations

import hashlib
import importlib.util
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError

import pytest

from backend.narration import model_assets


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_LOCK = REPOSITORY_ROOT / "docker/tts-sidecar/model-source.lock.json"
LIFECYCLE_RUNNER = REPOSITORY_ROOT / "scripts/tts/validate_sidecar_lifecycle.py"


def _load_lifecycle_runner():
    name = "t1b_validate_sidecar_lifecycle_test_module"
    spec = importlib.util.spec_from_file_location(name, LIFECYCLE_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _mutated_lock(tmp_path: Path, mutate) -> Path:  # noqa: ANN001
    row = json.loads(PRODUCTION_LOCK.read_text(encoding="utf-8"))
    mutate(row)
    path = tmp_path / "mutated-lock.json"
    path.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _accept_mutated_lock(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(model_assets, "MODEL_LOCK_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())


def test_production_lock_is_exact_three_component_twenty_nine_allowlist() -> None:
    lock = model_assets.load_and_validate_lock(PRODUCTION_LOCK)

    assert lock["allowed_component_ids"] == list(model_assets.ALLOWED_COMPONENT_IDS)
    assert lock["component_count"] == 3
    assert lock["artifact_count"] == 29
    assert sum(len(row["artifacts"]) for row in lock["components"]) == 29


def test_lock_hash_drift_is_rejected_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    path.write_bytes(PRODUCTION_LOCK.read_bytes() + b"\n")

    with pytest.raises(model_assets.ModelAssetError, match="hash mismatch") as caught:
        model_assets.load_and_validate_lock(path)

    assert caught.value.code == "LOCK_HASH_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda row: row["components"][0]["artifacts"][0].update(path="../escape"), "LOCK_PATH_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(path="/absolute"), "LOCK_PATH_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(path="nested\\windows"), "LOCK_PATH_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(url="https://evil.example/asset"), "LOCK_ORIGIN_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(url=row["components"][0]["artifacts"][1]["url"]), "LOCK_ORIGIN_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(size=-1), "LOCK_SIZE_INVALID"),
        (lambda row: row["components"][0]["artifacts"][0].update(hash="0" * 64), "LOCK_DIGEST_INVALID"),
        (lambda row: row["components"][0].update(revision="main"), "LOCK_REVISION_INVALID"),
        (lambda row: row["allowed_component_ids"].append("moss-voice-generator"), "LOCK_ALLOWLIST_MISMATCH"),
    ],
)
def test_mutated_lock_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    code: str,
) -> None:
    path = _mutated_lock(tmp_path, mutation)
    _accept_mutated_lock(monkeypatch, path)

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.load_and_validate_lock(path)

    assert caught.value.code == code


def test_dry_run_does_not_create_assets_root(tmp_path: Path) -> None:
    assets_root = tmp_path / "assets"

    result = model_assets.install_release(PRODUCTION_LOCK, assets_root, dry_run=True)

    assert result["operation"] == "dry_run"
    assert result["artifact_count"] == 29
    assert result["network_used"] is False
    assert not assets_root.exists()


def test_offline_missing_release_fails_without_partial_directory(tmp_path: Path) -> None:
    assets_root = tmp_path / "assets"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.install_release(PRODUCTION_LOCK, assets_root, offline=True)

    assert caught.value.code == "OFFLINE_RELEASE_MISSING"
    assert not model_assets.release_root(assets_root).exists()


def test_install_failure_never_publishes_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_download(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise model_assets.ModelAssetError("TEST_DOWNLOAD_FAILURE", "redacted")

    monkeypatch.setattr(model_assets, "_download_artifact", fail_download)
    assets_root = tmp_path / "assets"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.install_release(PRODUCTION_LOCK, assets_root)

    assert caught.value.code == "TEST_DOWNLOAD_FAILURE"
    assert not model_assets.release_root(assets_root).exists()
    assert list((assets_root / "releases").glob(f".staging.{model_assets.MODEL_INVENTORY_SHA256}.*")) == []


def test_atomic_file_download_rejects_truncated_extra_and_bad_hash(tmp_path: Path) -> None:
    payload = b"locked-bytes"
    target = tmp_path / "component" / "asset.bin"
    artifact = {
        "size": len(payload),
        "hash_algorithm": "sha256",
        "hash": hashlib.sha256(payload).hexdigest(),
    }
    model_assets._download_to(io.BytesIO(payload), target, artifact)
    assert target.read_bytes() == payload
    assert not list(target.parent.glob("*.part"))

    for suffix, code in ((b"", "DOWNLOAD_SIZE_MISMATCH"), (b"extra", "DOWNLOAD_SIZE_MISMATCH")):
        rejected = tmp_path / f"rejected-{len(suffix)}.bin"
        stream = io.BytesIO(payload[:-1] if not suffix else payload + suffix)
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._download_to(stream, rejected, artifact)
        assert caught.value.code == code
        assert not rejected.exists()

    bad = dict(artifact, hash="0" * 64)
    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._download_to(io.BytesIO(payload), tmp_path / "bad.bin", bad)
    assert caught.value.code == "DOWNLOAD_HASH_MISMATCH"
    assert not (tmp_path / "bad.bin").exists()


def test_http_redirect_is_rejected_without_following(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        followed = False

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/payload")
                self.end_headers()
            else:
                type(self).followed = True
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"payload")

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr(model_assets, "_reject_private_resolution", lambda _host: None)
        url = f"http://127.0.0.1:{server.server_port}/redirect"
        artifact = {"size": 7, "hash_algorithm": "sha256", "hash": hashlib.sha256(b"payload").hexdigest()}
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._download_artifact(url, artifact, tmp_path / "payload", timeout_seconds=2)
        assert caught.value.code == "DOWNLOAD_REDIRECT_FORBIDDEN"
        assert RedirectHandler.followed is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_redirect_policy_allows_only_observed_hf_cache_and_cdn_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_assets, "_reject_private_resolution", lambda _host: None)
    origin = "https://huggingface.co/Org/Repo/resolve/" + "a" * 40 + "/model.onnx"
    cache = model_assets._safe_redirect_url(origin, "/api/resolve-cache/models/Org/Repo/cache-key")
    assert cache.startswith("https://huggingface.co/api/resolve-cache/")
    cdn = model_assets._safe_redirect_url(origin, "https://us.aws.cdn.hf.co/object?signature=redacted")
    assert cdn.startswith("https://us.aws.cdn.hf.co/")

    for location in (
        "http://us.aws.cdn.hf.co/object",
        "https://evil.example/object",
        "https://user:password@us.aws.cdn.hf.co/object",
        "https://127.0.0.1/object",
        "/unapproved-relative-path",
    ):
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._safe_redirect_url(origin, location)
        assert caught.value.code == "DOWNLOAD_REDIRECT_FORBIDDEN"


def _make_exact_empty_release(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    lock = model_assets.load_and_validate_lock(PRODUCTION_LOCK)
    assets_root = tmp_path / "assets"
    release = model_assets.release_root(assets_root)
    expected_files, expected_directories = model_assets._expected_release_entries(lock, release)
    for relative in expected_directories:
        (release / relative).mkdir(parents=True, exist_ok=True)
    for relative in expected_files:
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"{}" if relative == "READY.json" else b"")
        target.chmod(0o444)
    for directory in sorted((path for path in release.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o555)
    release.chmod(0o555)
    return lock, assets_root, release


def test_exact_release_tree_rejects_extra_file_directory_and_symlink(tmp_path: Path) -> None:
    lock, assets_root, release = _make_exact_empty_release(tmp_path)
    model_assets._verify_exact_release_tree(lock, assets_root, release)

    extra = release / "models" / "unexpected.bin"
    extra.parent.chmod(0o755)
    extra.write_bytes(b"unexpected")
    extra.chmod(0o444)
    extra.parent.chmod(0o555)
    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._verify_exact_release_tree(lock, assets_root, release)
    assert caught.value.code == "RELEASE_TREE_NOT_EXACT"
    extra.parent.chmod(0o755)
    extra.unlink()
    extra.parent.chmod(0o555)

    unexpected_directory = release / "unexpected-directory"
    release.chmod(0o755)
    unexpected_directory.mkdir()
    unexpected_directory.chmod(0o555)
    release.chmod(0o555)
    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._verify_exact_release_tree(lock, assets_root, release)
    assert caught.value.code == "RELEASE_TREE_NOT_EXACT"
    release.chmod(0o755)
    unexpected_directory.rmdir()
    release.chmod(0o555)

    victim = next(path for path in release.rglob("*") if path.is_file() and path.name != "READY.json")
    victim.parent.chmod(0o755)
    victim.unlink()
    victim.symlink_to(release / "READY.json")
    victim.parent.chmod(0o555)
    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._verify_exact_release_tree(lock, assets_root, release)
    assert caught.value.code == "RELEASE_TREE_SYMLINK"
    victim.parent.chmod(0o755)
    victim.unlink()
    model_assets._remove_owned_tree(release)


def test_exact_release_tree_rejects_controlled_parent_symlink(tmp_path: Path) -> None:
    lock = model_assets.load_and_validate_lock(PRODUCTION_LOCK)
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    real_releases = tmp_path / "real-releases"
    real_releases.mkdir()
    (assets_root / "releases").symlink_to(real_releases, target_is_directory=True)
    release = real_releases / model_assets.MODEL_INVENTORY_SHA256
    release.mkdir()

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._verify_exact_release_tree(lock, assets_root, release)
    assert caught.value.code == "RELEASES_ROOT_INVALID"


def test_release_directory_requires_traverse_permission(tmp_path: Path) -> None:
    lock, assets_root, release = _make_exact_empty_release(tmp_path)
    directory = release / "source"
    directory.chmod(0o644)
    try:
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._verify_exact_release_tree(lock, assets_root, release)
        assert caught.value.code == "RELEASE_PERMISSION_INVALID"
    finally:
        directory.chmod(0o755)
        model_assets._remove_owned_tree(release)


def test_install_lock_is_nonblocking_and_orphan_cleanup_is_scoped(tmp_path: Path) -> None:
    assets_root = tmp_path / "assets"
    with model_assets._exclusive_install_lock(assets_root):
        with pytest.raises(model_assets.ModelAssetError) as caught:
            with model_assets._exclusive_install_lock(assets_root):
                pass
        assert caught.value.code == "INSTALL_LOCKED"

    staging = assets_root / "releases"
    owned = staging / f".staging.{model_assets.MODEL_INVENTORY_SHA256}.orphan"
    unrelated = staging / "unrelated"
    owned.mkdir(parents=True)
    unrelated.mkdir()
    assert model_assets._cleanup_orphan_staging(staging) == 1
    assert not owned.exists()
    assert unrelated.is_dir()


def test_hf_same_origin_307_is_followed_once_and_still_hash_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"locked-hf-metadata"
    origin = "https://huggingface.co/Org/Repo/resolve/" + "a" * 40 + "/metadata.json"
    cache_path = "/api/resolve-cache/models/Org/Repo/cache-key"

    class Response(io.BytesIO):
        status = 200

        def __init__(self, body: bytes, url: str):
            super().__init__(body)
            self._url = url
            self.headers = {"Content-Length": str(len(body))}

        def geturl(self) -> str:
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    class Opener:
        calls = 0

        def open(self, request, timeout):  # noqa: ANN001
            del timeout
            self.calls += 1
            if self.calls == 1:
                headers = Message()
                headers["Location"] = cache_path
                raise HTTPError(request.full_url, 307, "redirect", headers, None)
            return Response(payload, "https://huggingface.co" + cache_path)

    opener = Opener()
    monkeypatch.setattr(model_assets, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(model_assets, "_reject_private_resolution", lambda _host: None)
    artifact = {"size": len(payload), "hash_algorithm": "sha256", "hash": hashlib.sha256(payload).hexdigest()}
    target = tmp_path / "metadata.json"

    model_assets._download_artifact(origin, artifact, target, timeout_seconds=2)

    assert opener.calls == 2
    assert target.read_bytes() == payload


def test_dns_policy_only_allows_global_or_fixed_host_transparent_proxy_fake_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def addresses(value: str):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 443))]

    monkeypatch.setattr(model_assets.socket, "getaddrinfo", lambda *_args, **_kwargs: addresses("198.18.0.130"))
    model_assets._reject_private_resolution("huggingface.co")
    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._reject_private_resolution("evil.example")
    assert caught.value.code == "DOWNLOAD_PRIVATE_ADDRESS_FORBIDDEN"

    for value in ("127.0.0.1", "10.0.0.1", "169.254.1.1"):
        monkeypatch.setattr(model_assets.socket, "getaddrinfo", lambda *_args, _value=value, **_kwargs: addresses(_value))
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._reject_private_resolution("huggingface.co")
        assert caught.value.code == "DOWNLOAD_PRIVATE_ADDRESS_FORBIDDEN"


def test_publish_rechecks_exact_tree_after_injection_before_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock, _, staging = _make_exact_empty_release(tmp_path)
    for directory in [staging, *(path for path in staging.rglob("*") if path.is_dir())]:
        directory.chmod(0o755)
    final = staging.parent / f"published-{model_assets.MODEL_INVENTORY_SHA256}"
    original = model_assets._verify_exact_tree_contents
    calls = 0

    def inject_after_first_check(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        original(*args, **kwargs)
        if calls == 1:
            injected = staging / "injected-after-check.bin"
            injected.write_bytes(b"injected")
            injected.chmod(0o444)

    monkeypatch.setattr(model_assets, "_verify_exact_tree_contents", inject_after_first_check)
    try:
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets._publish_staging(
                lock,
                staging,
                final,
                expected_uid=None,
                expected_gid=None,
            )
        assert caught.value.code == "RELEASE_TREE_NOT_EXACT"
        assert calls == 2
        assert not final.exists()
    finally:
        model_assets._remove_owned_tree(staging)


def test_artifact_verification_rejects_symlink_with_nofollow(tmp_path: Path) -> None:
    payload = b"locked"
    real = tmp_path / "real.bin"
    real.write_bytes(payload)
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    artifact = {"size": len(payload), "hash_algorithm": "sha256", "hash": hashlib.sha256(payload).hexdigest()}

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._verify_artifact(link, artifact)

    assert caught.value.code in {"ARTIFACT_SYMLINK_FORBIDDEN", "ARTIFACT_SIZE_MISMATCH"}


def test_publish_staging_successfully_renames_same_filesystem_exact_tree(tmp_path: Path) -> None:
    lock, _, staging = _make_exact_empty_release(tmp_path)
    final = staging.parent / f"published-{model_assets.MODEL_INVENTORY_SHA256}"

    model_assets._publish_staging(
        lock,
        staging,
        final,
        expected_uid=None,
        expected_gid=None,
    )

    assert final.is_dir()
    assert not staging.exists()
    model_assets._verify_exact_tree_contents(lock, final, immutable_modes=True)
    model_assets._remove_owned_tree(final)


def test_download_concurrency_is_bounded_and_publication_remains_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()

    def observe(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1

    monkeypatch.setattr(model_assets, "_download_artifact", observe)
    assets_root = tmp_path / "assets"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.install_release(
            PRODUCTION_LOCK,
            assets_root,
            max_parallel_downloads=4,
        )

    assert caught.value.code == "ARTIFACT_OPEN_FAILED"
    assert 2 <= maximum <= 4
    assert not model_assets.release_root(assets_root).exists()
    assert not list((assets_root / "releases").glob(f".staging.{model_assets.MODEL_INVENTORY_SHA256}.*"))


def test_first_parallel_download_error_cancels_set_and_never_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = 0
    started_lock = threading.Lock()

    def fail_one(_url, artifact, _target, **_kwargs) -> None:  # noqa: ANN001
        nonlocal started
        with started_lock:
            started += 1
        if artifact["path"] == "LICENSE":
            raise model_assets.ModelAssetError("INJECTED_FIRST_ERROR", "redacted")
        time.sleep(0.03)

    monkeypatch.setattr(model_assets, "_download_artifact", fail_one)
    assets_root = tmp_path / "assets"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.install_release(PRODUCTION_LOCK, assets_root, max_parallel_downloads=4)

    assert caught.value.code == "INJECTED_FIRST_ERROR"
    assert started < 29
    assert not model_assets.release_root(assets_root).exists()
    assert not list((assets_root / "releases").glob(f".staging.{model_assets.MODEL_INVENTORY_SHA256}.*"))


def test_download_concurrency_outside_one_to_four_is_rejected(tmp_path: Path) -> None:
    for value in (0, 5, True):
        with pytest.raises(model_assets.ModelAssetError) as caught:
            model_assets.install_release(
                PRODUCTION_LOCK,
                tmp_path / str(value),
                dry_run=True,
                max_parallel_downloads=value,
            )
        assert caught.value.code == "DOWNLOAD_CONCURRENCY_INVALID"


def test_unexpected_parallel_worker_failure_cancels_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_unexpectedly(_url, artifact, _target, **_kwargs) -> None:  # noqa: ANN001
        if artifact["path"] == "LICENSE":
            raise RuntimeError("injected unexpected worker failure")
        time.sleep(0.02)

    monkeypatch.setattr(model_assets, "_download_artifact", fail_unexpectedly)
    assets_root = tmp_path / "assets"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets.install_release(
            PRODUCTION_LOCK,
            assets_root,
            max_parallel_downloads=4,
        )

    assert caught.value.code == "DOWNLOAD_WORKER_FAILURE"
    assert not model_assets.release_root(assets_root).exists()
    assert not list(
        (assets_root / "releases").glob(
            f".staging.{model_assets.MODEL_INVENTORY_SHA256}.*"
        )
    )


def test_download_retries_with_exact_range_and_resumes_partial_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"range-resume-locked-payload"
    split = 9
    url = "https://huggingface.co/Org/Repo/resolve/" + "a" * 40 + "/asset.bin"

    class Response(io.BytesIO):
        def __init__(
            self,
            body: bytes,
            *,
            status: int,
            headers: dict[str, str],
        ) -> None:
            super().__init__(body)
            self.status = status
            self.headers = headers

        def geturl(self) -> str:
            return url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    class Opener:
        def __init__(self) -> None:
            self.ranges: list[str | None] = []

        def open(self, request, timeout):  # noqa: ANN001
            del timeout
            requested_range = request.get_header("Range")
            self.ranges.append(requested_range)
            if len(self.ranges) == 1:
                return Response(
                    payload[:split],
                    status=200,
                    headers={"Content-Length": str(len(payload))},
                )
            assert requested_range == f"bytes={split}-"
            return Response(
                payload[split:],
                status=206,
                headers={
                    "Content-Length": str(len(payload) - split),
                    "Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}",
                },
            )

    opener = Opener()
    monkeypatch.setattr(model_assets, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(model_assets, "_reject_private_resolution", lambda _host: None)
    monkeypatch.setattr(model_assets, "_retry_wait", lambda *_args: None)
    artifact = {
        "size": len(payload),
        "hash_algorithm": "sha256",
        "hash": hashlib.sha256(payload).hexdigest(),
    }
    target = tmp_path / "asset.bin"

    model_assets._download_artifact(url, artifact, target, timeout_seconds=2)

    assert opener.ranges == [None, f"bytes={split}-"]
    assert target.read_bytes() == payload
    assert not (tmp_path / ".asset.bin.part").exists()


def test_download_retry_is_bounded_and_exhaustion_cleans_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"retry-exhaustion"
    url = "https://huggingface.co/Org/Repo/resolve/" + "a" * 40 + "/asset.bin"

    class Response(io.BytesIO):
        def __init__(self, start: int) -> None:
            super().__init__(payload[start : start + 1])
            self.status = 206 if start else 200
            self.headers = {"Content-Length": str(len(payload) - start)}
            if start:
                self.headers["Content-Range"] = (
                    f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )

        def geturl(self) -> str:
            return url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    class Opener:
        calls = 0

        def open(self, request, timeout):  # noqa: ANN001
            del timeout
            self.calls += 1
            raw_range = request.get_header("Range")
            start = int(raw_range.removeprefix("bytes=").removesuffix("-")) if raw_range else 0
            return Response(start)

    opener = Opener()
    monkeypatch.setattr(model_assets, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(model_assets, "_reject_private_resolution", lambda _host: None)
    monkeypatch.setattr(model_assets, "_retry_wait", lambda *_args: None)
    artifact = {
        "size": len(payload),
        "hash_algorithm": "sha256",
        "hash": hashlib.sha256(payload).hexdigest(),
    }
    target = tmp_path / "asset.bin"

    with pytest.raises(model_assets.ModelAssetError) as caught:
        model_assets._download_artifact(url, artifact, target, timeout_seconds=2)

    assert caught.value.code == "DOWNLOAD_SIZE_MISMATCH"
    assert opener.calls == model_assets._MAX_DOWNLOAD_ATTEMPTS
    assert not target.exists()
    assert not (tmp_path / ".asset.bin.part").exists()


def test_lifecycle_runner_defaults_to_dry_run_without_docker() -> None:
    result = subprocess.run(
        [sys.executable, str(LIFECYCLE_RUNNER)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    row = json.loads(result.stdout)

    assert row["status"] == "dry_run"
    assert row["mode"] == "dry-run"
    assert row["steps"] == []
    assert row["real_requirements"]["broad_cleanup_permitted"] is False
    requirements = row["real_requirements"]
    assert requirements["model_input_exactly_one_of"] == [
        "--assets-root",
        "--source-model-volume",
    ]
    assert requirements["source_model_volume_required_labels"] == {
        "ai.novel.world.project": "AI小说世界2026",
        "ai.novel.world.purpose": "tts-model-and-source-assets",
    }
    assert requirements["source_model_volume_mount"] == "readonly"
    assert requirements["source_model_volume_inspection"] == (
        "before_and_after_initializer_create"
    )
    assert requirements["source_model_volume_cleanup_permitted"] is False
    assert requirements["offline_artifact_verification_count"] == 29
    assert requirements["token_host_bind_permitted"] is False
    assert requirements["token_transport"] == (
        "docker_create_then_cp_single_file_then_start_attach"
    )


def _real_runner_args(
    runner,
    tmp_path: Path,
    *model_input: str,
):
    prefix = "ai-novel-2026-t1b-a1b2c3d4"
    return runner.build_parser().parse_args(
        [
            "--mode",
            "real",
            "--resource-prefix",
            prefix,
            "--image-ref",
            f"ai-novel-world/moss-tts-sidecar:{prefix}",
            "--expected-image-digest",
            "sha256:" + "a" * 64,
            "--lock-file",
            str(tmp_path / "LOCK-NANO"),
            "--lock-grant",
            "LOCK-NANO/test-grant-01",
            "--token-file",
            str(tmp_path / "sidecar-token.secret"),
            "--confirm-real-nano",
            runner.RUNNER_CONFIRMATION,
            "--confirm-active-kill",
            runner.KILL_CONFIRMATION,
            *model_input,
        ]
    )


def test_real_runner_model_input_is_exactly_one_and_source_is_narrow(
    tmp_path: Path,
) -> None:
    runner = _load_lifecycle_runner()

    with pytest.raises(runner.RunnerError) as missing:
        runner._validate_real_arguments(_real_runner_args(runner, tmp_path))
    assert missing.value.code == "MODEL_INPUT_EXACTLY_ONE_REQUIRED"

    with pytest.raises(runner.RunnerError) as both:
        runner._validate_real_arguments(
            _real_runner_args(
                runner,
                tmp_path,
                "--assets-root",
                str(tmp_path / "assets"),
                "--source-model-volume",
                "ai-novel-2026-moss-models",
                "--confirm-source-model-volume",
                runner.SOURCE_MODEL_VOLUME_CONFIRMATION,
            )
        )
    assert both.value.code == "MODEL_INPUT_EXACTLY_ONE_REQUIRED"

    host_args = _real_runner_args(
        runner,
        tmp_path,
        "--assets-root",
        str(tmp_path / "assets"),
    )
    host_names = runner._validate_real_arguments(host_args)
    assert host_names.model_volume.endswith("-model")

    with pytest.raises(runner.RunnerError) as unconfirmed:
        runner._validate_real_arguments(
            _real_runner_args(
                runner,
                tmp_path,
                "--source-model-volume",
                "ai-novel-2026-moss-models",
            )
        )
    assert unconfirmed.value.code == "SOURCE_MODEL_VOLUME_CONFIRMATION_REQUIRED"

    for source, code in (
        ("foreign-models", "SOURCE_MODEL_VOLUME_INVALID"),
        (
            "ai-novel-2026-t1b-a1b2c3d4-model",
            "SOURCE_MODEL_VOLUME_COLLISION",
        ),
        (
            "ai-novel-2026-t1b-a1b2c3d4-secret",
            "SOURCE_MODEL_VOLUME_COLLISION",
        ),
    ):
        with pytest.raises(runner.RunnerError) as caught:
            runner._validate_real_arguments(
                _real_runner_args(
                    runner,
                    tmp_path,
                    "--source-model-volume",
                    source,
                    "--confirm-source-model-volume",
                    runner.SOURCE_MODEL_VOLUME_CONFIRMATION,
                )
            )
        assert caught.value.code == code

    source_args = _real_runner_args(
        runner,
        tmp_path,
        "--source-model-volume",
        "ai-novel-2026-moss-models",
        "--confirm-source-model-volume",
        runner.SOURCE_MODEL_VOLUME_CONFIRMATION,
    )
    source_names = runner._validate_real_arguments(source_args)
    assert source_args.source_model_volume != source_names.model_volume


@pytest.mark.parametrize(
    "labels",
    [
        {
            "ai.novel.world.project": "wrong-project",
            "ai.novel.world.purpose": "tts-model-and-source-assets",
        },
        {
            "ai.novel.world.project": "AI小说世界2026",
            "ai.novel.world.purpose": "wrong-purpose",
        },
        {},
    ],
)
def test_source_model_volume_requires_exact_existing_project_labels(
    monkeypatch: pytest.MonkeyPatch,
    labels: dict[str, str],
) -> None:
    runner = _load_lifecycle_runner()
    source = "ai-novel-2026-moss-models"
    commands: list[list[str]] = []

    def inspect(_transcript, _name, argv, **_kwargs):  # noqa: ANN001, ANN003
        commands.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"Name": source, "Labels": labels}),
            stderr="",
        )

    monkeypatch.setattr(runner, "_command", inspect)
    with pytest.raises(runner.RunnerError) as caught:
        runner._inspect_source_model_volume(
            {"model_input": {"source_labels_verified": False}},
            source,
            5,
        )

    assert caught.value.code == "SOURCE_MODEL_VOLUME_LABEL_MISMATCH"
    assert commands == [
        ["docker", "volume", "inspect", source, "--format", "{{json .}}"]
    ]


def test_source_volume_init_is_readonly_offline_and_token_uses_stopped_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_lifecycle_runner()
    source = "ai-novel-2026-moss-models"
    args = _real_runner_args(
        runner,
        tmp_path,
        "--source-model-volume",
        source,
        "--confirm-source-model-volume",
        runner.SOURCE_MODEL_VOLUME_CONFIRMATION,
    )
    names = runner._validate_real_arguments(args)
    create = runner._init_create_command(names, args)
    copied = runner._token_copy_command(names, args)
    started = runner._init_start_command(names)
    joined = " ".join(create)

    assert create[:2] == ["docker", "create"]
    assert f"{runner.RUN_LABEL}={names.run_id}" in create
    assert (
        f"type=volume,src={source},dst=/input/assets,readonly" in create
    )
    assert "type=bind" not in joined
    assert str(args.token_file) not in joined
    assert "/input/token" not in joined
    assert joined.count("/opt/ai-novel-world/tts-sidecar/runtime/install_models.py") == 2
    assert joined.count("--verify --offline") == 2
    assert runner.MODEL_INVENTORY_SHA256 in joined
    assert f"trap 'rm -f {runner.INIT_TOKEN_PATH}' EXIT" in joined
    assert copied == [
        "docker",
        "cp",
        str(args.token_file),
        f"{names.init_client}:{runner.INIT_TOKEN_PATH}",
    ]
    assert started == ["docker", "start", "--attach", names.init_client]

    transcript = {"model_input": {"source_labels_verified": False}}
    valid_labels = {
        "ai.novel.world.project": "AI小说世界2026",
        "ai.novel.world.purpose": "tts-model-and-source-assets",
    }

    def inspect(_transcript, _name, argv, **_kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"Name": source, "Labels": valid_labels}),
            stderr="",
        )

    monkeypatch.setattr(runner, "_command", inspect)
    runner._inspect_source_model_volume(transcript, source, 5)
    assert transcript["model_input"]["source_labels_verified"] is True

    inspected_for_cleanup: list[str] = []

    def absent(_transcript, _kind, name, _run_id, _timeout):  # noqa: ANN001
        inspected_for_cleanup.append(name)
        return "absent"

    monkeypatch.setattr(runner, "_ownership", absent)
    assert runner._cleanup_real(
        {},
        names,
        args,
        image_created=False,
    ) == []
    assert source not in inspected_for_cleanup


def test_host_assets_init_compatibility_keeps_only_assets_bind(
    tmp_path: Path,
) -> None:
    runner = _load_lifecycle_runner()
    args = _real_runner_args(
        runner,
        tmp_path,
        "--assets-root",
        str(tmp_path / "assets"),
    )
    names = runner._validate_real_arguments(args)
    create = runner._init_create_command(names, args)
    bind_mounts = [item for item in create if item.startswith("type=bind,")]

    assert bind_mounts == [
        f"type=bind,src={args.assets_root},dst=/input/assets,readonly"
    ]
    assert all("token" not in mount for mount in bind_mounts)


def test_initializer_inspection_proves_source_readonly_and_outputs_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_lifecycle_runner()
    source = "ai-novel-2026-moss-models"
    args = _real_runner_args(
        runner,
        tmp_path,
        "--source-model-volume",
        source,
        "--confirm-source-model-volume",
        runner.SOURCE_MODEL_VOLUME_CONFIRMATION,
    )
    names = runner._validate_real_arguments(args)
    row = {
        "Config": {
            "User": "0:0",
            "Labels": {runner.RUN_LABEL: names.run_id},
        },
        "HostConfig": {"NetworkMode": "none"},
        "State": {"Running": False, "Status": "created"},
        "Mounts": [
            {
                "Destination": "/input/assets",
                "RW": False,
                "Type": "volume",
                "Name": source,
            },
            {
                "Destination": "/output/secret",
                "RW": True,
                "Type": "volume",
                "Name": names.secret_volume,
            },
            {
                "Destination": "/output/model",
                "RW": True,
                "Type": "volume",
                "Name": names.model_volume,
            },
        ],
    }
    commands: list[list[str]] = []

    def inspect(_transcript, _name, argv, **_kwargs):  # noqa: ANN001, ANN003
        commands.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(row),
            stderr="",
        )

    monkeypatch.setattr(runner, "_command", inspect)
    runner._verify_initializer_security({}, names, args)
    assert commands == [
        [
            "docker",
            "container",
            "inspect",
            names.init_client,
            "--format",
            "{{json .}}",
        ]
    ]

    row["Mounts"][0]["RW"] = True
    with pytest.raises(runner.RunnerError) as caught:
        runner._verify_initializer_security({}, names, args)
    assert caught.value.code == "INITIALIZER_SECURITY_MISMATCH"


def test_lifecycle_runner_fake_writes_redacted_structured_transcript(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "fake-transcript.json"
    result = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_RUNNER),
            "--mode",
            "fake",
            "--transcript",
            str(transcript),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    stdout_row = json.loads(result.stdout)
    saved = json.loads(transcript.read_text(encoding="utf-8"))

    assert stdout_row == saved
    assert saved["status"] == "fake_pass"
    assert saved["runner_sha256"] == hashlib.sha256(
        LIFECYCLE_RUNNER.read_bytes()
    ).hexdigest()
    assert saved["secrets_recorded"] is False
    assert saved["audio_bytes_recorded"] is False
    assert transcript.stat().st_mode & 0o777 == 0o600


def test_lifecycle_runner_real_mode_fails_before_docker_without_confirmations() -> None:
    result = subprocess.run(
        [sys.executable, str(LIFECYCLE_RUNNER), "--mode", "real"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    row = json.loads(result.stdout)

    assert result.returncode == 2
    assert row["status"] == "failed"
    assert row["error_code"] == "REAL_CONFIRMATION_REQUIRED"
    assert row["steps"] == []


def test_lifecycle_runner_invalid_token_fails_redacted_before_docker(
    tmp_path: Path,
) -> None:
    lock_file = tmp_path / "LOCK-NANO"
    token_file = tmp_path / "sidecar-token.secret"
    transcript = tmp_path / "invalid-token.json"
    lock_file.write_bytes(b"")
    token_file.write_bytes(b"a" * 64 + b"\n")
    lock_file.chmod(0o600)
    token_file.chmod(0o600)
    prefix = "ai-novel-2026-t1b-b1c2d3e4"

    result = subprocess.run(
        [
            sys.executable,
            str(LIFECYCLE_RUNNER),
            "--mode",
            "real",
            "--resource-prefix",
            prefix,
            "--image-ref",
            f"ai-novel-world/moss-tts-sidecar:{prefix}",
            "--expected-image-digest",
            "sha256:" + "a" * 64,
            "--lock-file",
            str(lock_file),
            "--lock-grant",
            "LOCK-NANO/test-grant-01",
            "--token-file",
            str(token_file),
            "--source-model-volume",
            "ai-novel-2026-moss-models",
            "--confirm-source-model-volume",
            "USE-LABELED-READONLY-MOSS-MODEL-VOLUME",
            "--confirm-real-nano",
            "RUN-T1-B-REAL-NANO",
            "--confirm-active-kill",
            "KILL-DEDICATED-T1-B-SIDECAR",
            "--transcript",
            str(transcript),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    row = json.loads(result.stdout)

    assert result.returncode == 2
    assert result.stderr == ""
    assert row["status"] == "failed"
    assert row["error_code"] == "TOKEN_CONFIGURATION_INVALID"
    assert row["steps"] == []
    assert json.loads(transcript.read_text(encoding="utf-8")) == row
