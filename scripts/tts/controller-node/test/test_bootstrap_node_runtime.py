from __future__ import annotations

import importlib.util
import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "bootstrap_node_runtime.py"
PACKAGE_ROOT = MODULE_PATH.parent
SPEC = importlib.util.spec_from_file_location("controller_node_bootstrap", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def test_official_runtime_lock_has_exact_darwin_hashes() -> None:
    lock = bootstrap._load_lock()
    assert bootstrap._archive(lock, "darwin-arm64") == (
        "node-v24.19.0-darwin-arm64.tar.gz",
        "8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d",
    )
    assert bootstrap._archive(lock, "darwin-x64") == (
        "node-v24.19.0-darwin-x64.tar.gz",
        "d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316",
    )


def test_playwright_core_dependency_is_exact_and_integrity_locked() -> None:
    package = json.loads((PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = (PACKAGE_ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert package["engines"] == {"node": "24.19.0"}
    assert package["dependencies"] == {"playwright-core": "1.62.1"}
    assert "playwright-core@1.62.1:" in lock
    assert (
        "sha512-wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4"
        "Hi/rhDMjXGqHewDZ68nYZVw=="
    ) in lock
    runtime_lock = bootstrap._load_lock()
    assert runtime_lock["dependency"] == {
        "archive_filename": "playwright-core-1.62.1.tgz",
        "archive_sha512_base64": (
            "wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4"
            "Hi/rhDMjXGqHewDZ68nYZVw=="
        ),
        "name": "playwright-core",
        "package_json_sha256": (
            "1d962c9af7d389e0ec0d659c480878bc136aa35298d143716c6ac35ac678cb42"
        ),
        "pnpm_lock_sha256": (
            "c8637967e2632eaebd8948d719cd8f5829cfed78ca2d2376536ea6e0916b4b8c"
        ),
        "registry_tarball_url": (
            "https://registry.npmjs.org/playwright-core/-/playwright-core-1.62.1.tgz"
        ),
        "version": "1.62.1",
    }


@pytest.mark.parametrize(
    ("name", "link", "expected"),
    [
        ("node-v24.19.0-darwin-arm64/bin/node", "", True),
        ("../outside", "", False),
        ("node-v24.19.0-darwin-arm64/bin/npm", "../lib/node_modules/npm/bin/npm-cli.js", True),
        ("node-v24.19.0-darwin-arm64/bin/escape", "../../../../outside", False),
    ],
)
def test_archive_member_policy(name: str, link: str, expected: bool) -> None:
    member = tarfile.TarInfo(name)
    if link:
        member.type = tarfile.SYMTYPE
        member.linkname = link
    else:
        member.type = tarfile.REGTYPE
    assert bootstrap._safe_member(
        member,
        "node-v24.19.0-darwin-arm64",
    ) is expected


def test_extract_uses_python_311_compatible_manual_policy(tmp_path: Path) -> None:
    prefix = "node-v24.19.0-darwin-arm64"
    archive = tmp_path / "node.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        directory = tarfile.TarInfo(f"{prefix}/bin")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        handle.addfile(directory)
        node = tarfile.TarInfo(f"{prefix}/bin/node")
        node.mode = 0o755
        node.size = 4
        handle.addfile(node, io.BytesIO(b"node"))
        link = tarfile.TarInfo(f"{prefix}/bin/node-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "node"
        handle.addfile(link)
    extracted = bootstrap._extract(archive, tmp_path / "out", prefix)
    assert (extracted / "bin" / "node").read_bytes() == b"node"
    assert (extracted / "bin" / "node-link").is_symlink()
    assert (extracted / "bin" / "node-link").resolve() == (extracted / "bin" / "node")


def test_runtime_root_is_fixed_and_rejects_other_platform() -> None:
    root = bootstrap.runtime_root("darwin-arm64")
    assert root.is_absolute()
    assert "controller-runtime/node-v24.19.0-darwin-arm64" in str(root)
    with pytest.raises(bootstrap.RuntimeBootstrapError) as captured:
        bootstrap.runtime_root("linux-arm64")
    assert captured.value.code == "NODE_RUNTIME_PLATFORM_UNSUPPORTED"


def test_runtime_verification_requires_archive_bound_private_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "RUNTIME_PARENT", tmp_path)
    monkeypatch.setattr(bootstrap, "_platform_key", lambda: "darwin-arm64")
    root = bootstrap.runtime_root()
    node = root / "bin" / "node"
    node.parent.mkdir(parents=True)
    root.chmod(0o700)
    node.write_text("#!/bin/sh\nprintf 'v24.19.0\\n'\n", encoding="ascii")
    node.chmod(0o700)
    bootstrap._write_private_json(
        root / ".controller-runtime-receipt.json",
        {
            "node_executable_sha256": bootstrap._sha256(node),
            "node_version": "24.19.0",
            "platform": "darwin-arm64",
            "schema_version": bootstrap.RUNTIME_RECEIPT_SCHEMA,
            "source_archive_sha256": (
                "8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d"
            ),
        },
    )
    assert bootstrap.verify_runtime()["status"] == "verified"
    node.write_text("#!/bin/sh\nprintf 'v24.19.0\\n'\n# tampered\n", encoding="ascii")
    with pytest.raises(bootstrap.RuntimeBootstrapError) as captured:
        bootstrap.verify_runtime()
    assert captured.value.code == "NODE_RUNTIME_RECEIPT_INVALID"


def test_offline_dependency_prepare_and_tamper_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "RUNTIME_PARENT", tmp_path)
    archive = bootstrap.dependency_archive_path()
    archive.parent.mkdir(mode=0o700, parents=True)
    package_json = b'{"name":"playwright-core","version":"1.62.1"}\n'
    with tarfile.open(archive, "w:gz") as handle:
        directory = tarfile.TarInfo("package")
        directory.type = tarfile.DIRTYPE
        handle.addfile(directory)
        metadata = tarfile.TarInfo("package/package.json")
        metadata.size = len(package_json)
        handle.addfile(metadata, io.BytesIO(package_json))
        implementation_body = b"exports.chromium = {}\n"
        implementation = tarfile.TarInfo("package/index.js")
        implementation.size = len(implementation_body)
        handle.addfile(implementation, io.BytesIO(implementation_body))
        nested_body = b"exports.transport = {}\n"
        nested = tarfile.TarInfo("package/lib/server/transport.js")
        nested.size = len(nested_body)
        handle.addfile(nested, io.BytesIO(nested_body))
    archive.chmod(0o600)
    with archive.open("rb") as handle:
        archive_integrity = base64.b64encode(
            hashlib.file_digest(handle, "sha512").digest()
        ).decode("ascii")
    monkeypatch.setattr(
        bootstrap,
        "PLAYWRIGHT_ARCHIVE_SHA512_BASE64",
        archive_integrity,
    )
    monkeypatch.setattr(bootstrap, "_load_lock", lambda: {})
    prepared = bootstrap.prepare_dependencies()
    assert prepared["package_version"] == "1.62.1"
    assert str(tmp_path) in prepared["package_root"]
    package_root = bootstrap.dependency_root() / "node_modules" / "playwright-core"
    assert all(
        stat.S_IMODE(path.lstat().st_mode) == 0o700
        for path in package_root.rglob("*")
        if path.is_dir()
    )
    package_file = bootstrap.dependency_root() / "node_modules" / "playwright-core" / "index.js"
    package_file.chmod(0o600)
    package_file.write_text("tampered\n", encoding="ascii")
    package_file.chmod(0o400)
    with pytest.raises(bootstrap.RuntimeBootstrapError) as captured:
        bootstrap.verify_dependencies()
    assert captured.value.code == "NODE_DEPENDENCY_RECEIPT_INVALID"


def test_dependency_archive_rejects_links(tmp_path: Path) -> None:
    member = tarfile.TarInfo("package/escape")
    member.type = tarfile.SYMTYPE
    member.linkname = "../../outside"
    assert bootstrap._safe_dependency_member(member) is False
