#!/usr/bin/env python3
"""Install or verify the fixed repository-external Node controller runtime."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Final, Mapping
from urllib.request import Request, urlopen


LOCK_PATH: Final = Path(__file__).resolve().with_name("runtime-lock.json")
ACCOUNT_HOME: Final = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
RUNTIME_PARENT: Final = (
    ACCOUNT_HOME
    / "Library"
    / "Application Support"
    / "AI小说世界2026"
    / "controller-runtime"
)
MAX_ARCHIVE_BYTES: Final = 96 * 1024 * 1024
MAX_DEPENDENCY_BYTES: Final = 256 * 1024 * 1024
MAX_DEPENDENCY_FILES: Final = 64_000
SCHEMA_VERSION: Final = "moss-tts-t4k-controller-node-runtime-lock/1.0"
RUNTIME_RECEIPT_SCHEMA: Final = "moss-tts-t4k-controller-node-runtime-receipt/1.0"
DEPENDENCY_RECEIPT_SCHEMA: Final = (
    "moss-tts-t4k-controller-node-dependency-receipt/1.0"
)
PACKAGE_JSON_SHA256: Final = (
    "1d962c9af7d389e0ec0d659c480878bc136aa35298d143716c6ac35ac678cb42"
)
PNPM_LOCK_SHA256: Final = (
    "c8637967e2632eaebd8948d719cd8f5829cfed78ca2d2376536ea6e0916b4b8c"
)
PLAYWRIGHT_ARCHIVE_SHA512_BASE64: Final = (
    "wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4"
    "Hi/rhDMjXGqHewDZ68nYZVw=="
)


class RuntimeBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _load_lock(path: Path = LOCK_PATH) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
        package_json_sha = _sha256_bytes(path.with_name("package.json").read_bytes())
        pnpm_lock_sha = _sha256_bytes(path.with_name("pnpm-lock.yaml").read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeBootstrapError("NODE_RUNTIME_LOCK_INVALID") from None
    if (
        type(value) is not dict
        or frozenset(value)
        != {
            "archives",
            "base_url",
            "dependency",
            "node_version",
            "schema_version",
            "shasums_url",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("node_version") != "24.19.0"
        or value.get("base_url")
        != "https://nodejs.org/download/release/v24.19.0"
        or value.get("shasums_url")
        != "https://nodejs.org/download/release/v24.19.0/SHASUMS256.txt"
        or type(value.get("archives")) is not dict
        or type(value.get("dependency")) is not dict
    ):
        raise RuntimeBootstrapError("NODE_RUNTIME_LOCK_INVALID")
    dependency = value["dependency"]
    if (
        frozenset(dependency)
        != {
            "archive_filename",
            "archive_sha512_base64",
            "name",
            "package_json_sha256",
            "pnpm_lock_sha256",
            "registry_tarball_url",
            "version",
        }
        or dependency.get("archive_filename") != "playwright-core-1.62.1.tgz"
        or dependency.get("archive_sha512_base64")
        != PLAYWRIGHT_ARCHIVE_SHA512_BASE64
        or dependency.get("name") != "playwright-core"
        or dependency.get("version") != "1.62.1"
        or dependency.get("package_json_sha256") != PACKAGE_JSON_SHA256
        or dependency.get("pnpm_lock_sha256") != PNPM_LOCK_SHA256
        or dependency.get("registry_tarball_url")
        != "https://registry.npmjs.org/playwright-core/-/playwright-core-1.62.1.tgz"
        or package_json_sha != PACKAGE_JSON_SHA256
        or pnpm_lock_sha != PNPM_LOCK_SHA256
    ):
        raise RuntimeBootstrapError("NODE_RUNTIME_LOCK_INVALID")
    return value


def _platform_key() -> str:
    if platform.system() != "Darwin":
        raise RuntimeBootstrapError("NODE_RUNTIME_PLATFORM_UNSUPPORTED")
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "darwin-arm64"
    if machine in {"x86_64", "amd64"}:
        return "darwin-x64"
    raise RuntimeBootstrapError("NODE_RUNTIME_PLATFORM_UNSUPPORTED")


def _archive(lock: Mapping[str, object], platform_key: str) -> tuple[str, str]:
    archives = lock.get("archives")
    row = archives.get(platform_key) if type(archives) is dict else None
    if (
        type(row) is not dict
        or frozenset(row) != {"filename", "sha256"}
        or type(row.get("filename")) is not str
        or type(row.get("sha256")) is not str
        or len(row["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in row["sha256"])
        or row["filename"] != f"node-v24.19.0-{platform_key}.tar.gz"
    ):
        raise RuntimeBootstrapError("NODE_RUNTIME_LOCK_INVALID")
    return row["filename"], row["sha256"]


def runtime_root(platform_key: str | None = None) -> Path:
    key = _platform_key() if platform_key is None else platform_key
    if key not in {"darwin-arm64", "darwin-x64"}:
        raise RuntimeBootstrapError("NODE_RUNTIME_PLATFORM_UNSUPPORTED")
    return RUNTIME_PARENT / f"node-v24.19.0-{key}"


def dependency_root() -> Path:
    return RUNTIME_PARENT / "observer-dependencies-playwright-core-1.62.1"


def dependency_archive_path() -> Path:
    return RUNTIME_PARENT / "offline-cache" / "playwright-core-1.62.1.tgz"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        raise RuntimeBootstrapError("NODE_RUNTIME_IO_FAILED") from None


def _verify_runtime_parent(*, create: bool = False) -> None:
    try:
        if create and not RUNTIME_PARENT.exists():
            RUNTIME_PARENT.mkdir(mode=0o700, parents=True, exist_ok=False)
        details = RUNTIME_PARENT.lstat()
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) & 0o077
            or RUNTIME_PARENT.resolve(strict=True) != RUNTIME_PARENT
        ):
            raise RuntimeBootstrapError("NODE_RUNTIME_PARENT_UNSAFE")
    except RuntimeBootstrapError:
        raise
    except OSError:
        raise RuntimeBootstrapError("NODE_RUNTIME_PARENT_UNSAFE") from None


def _read_exact_json(path: Path, keys: frozenset[str], error_code: str) -> Mapping[str, object]:
    try:
        details = path.lstat()
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeBootstrapError(error_code) from None
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) & 0o077
        or type(value) is not dict
        or frozenset(value) != keys
        or raw != f"{_canonical_json(value)}\n".encode("ascii")
    ):
        raise RuntimeBootstrapError(error_code)
    return value


def _write_private_json(path: Path, value: Mapping[str, object]) -> None:
    try:
        path.write_text(f"{_canonical_json(value)}\n", encoding="ascii")
        path.chmod(0o400)
    except OSError:
        raise RuntimeBootstrapError("NODE_RUNTIME_IO_FAILED") from None


def verify_runtime(root: Path | None = None) -> Mapping[str, object]:
    _verify_runtime_parent()
    expected_root = runtime_root()
    candidate = expected_root if root is None else root
    if candidate != expected_root:
        raise RuntimeBootstrapError("NODE_RUNTIME_PATH_INVALID")
    node = candidate / "bin" / "node"
    receipt_path = candidate / ".controller-runtime-receipt.json"
    try:
        root_details = candidate.lstat()
        node_details = node.lstat()
        if (
            not candidate.is_absolute()
            or stat.S_ISLNK(root_details.st_mode)
            or not stat.S_ISDIR(root_details.st_mode)
            or root_details.st_uid != os.getuid()
            or stat.S_IMODE(root_details.st_mode) & 0o077
            or stat.S_ISLNK(node_details.st_mode)
            or not stat.S_ISREG(node_details.st_mode)
            or node_details.st_uid != os.getuid()
            or node_details.st_nlink != 1
            or stat.S_IMODE(node_details.st_mode) & 0o022
            or not os.access(node, os.X_OK)
            or node.resolve(strict=True).parent.parent != candidate.resolve(strict=True)
        ):
            raise RuntimeBootstrapError("NODE_RUNTIME_IDENTITY_INVALID")
        receipt = _read_exact_json(
            receipt_path,
            frozenset(
                {
                    "node_executable_sha256",
                    "node_version",
                    "platform",
                    "schema_version",
                    "source_archive_sha256",
                }
            ),
            "NODE_RUNTIME_RECEIPT_INVALID",
        )
        lock = _load_lock()
        _filename, expected_archive_sha = _archive(lock, _platform_key())
        node_sha = _sha256(node)
        if (
            receipt.get("schema_version") != RUNTIME_RECEIPT_SCHEMA
            or receipt.get("node_version") != "24.19.0"
            or receipt.get("platform") != _platform_key()
            or receipt.get("source_archive_sha256") != expected_archive_sha
            or receipt.get("node_executable_sha256") != node_sha
        ):
            raise RuntimeBootstrapError("NODE_RUNTIME_RECEIPT_INVALID")
        completed = subprocess.run(
            [str(node), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            timeout=10,
            check=False,
        )
    except RuntimeBootstrapError:
        raise
    except (OSError, subprocess.SubprocessError):
        raise RuntimeBootstrapError("NODE_RUNTIME_UNAVAILABLE") from None
    if completed.returncode != 0 or completed.stdout != b"v24.19.0\n":
        raise RuntimeBootstrapError("NODE_RUNTIME_VERSION_MISMATCH")
    return {
        "node_executable_sha256": node_sha,
        "node_version": "24.19.0",
        "platform": _platform_key(),
        "schema_version": "moss-tts-t4k-controller-node-runtime/1.0",
        "status": "verified",
    }


def _safe_dependency_member(member: tarfile.TarInfo) -> bool:
    path = Path(member.name)
    return bool(
        not path.is_absolute()
        and path.parts
        and path.parts[0] == "package"
        and ".." not in path.parts
        and not member.issym()
        and not member.islnk()
        and not member.isdev()
        and not member.isfifo()
        and (member.isfile() or member.isdir())
    )


def _dependency_tree_sha256(package_root: Path) -> str:
    digest = hashlib.sha256()
    count = 0
    total = 0
    try:
        root_details = package_root.lstat()
        if (
            stat.S_ISLNK(root_details.st_mode)
            or not stat.S_ISDIR(root_details.st_mode)
            or root_details.st_uid != os.getuid()
            or stat.S_IMODE(root_details.st_mode) & 0o077
        ):
            raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
        for path in sorted(package_root.rglob("*"), key=lambda item: item.relative_to(package_root).as_posix()):
            count += 1
            if count > MAX_DEPENDENCY_FILES:
                raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
            relative = path.relative_to(package_root).as_posix()
            details = path.lstat()
            mode = stat.S_IMODE(details.st_mode)
            if (
                stat.S_ISLNK(details.st_mode)
                or details.st_uid != os.getuid()
                or mode & 0o077
            ):
                raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
            if stat.S_ISDIR(details.st_mode):
                digest.update(f"D\0{relative}\0{mode:o}\n".encode("utf-8"))
                continue
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
            total += details.st_size
            if total > MAX_DEPENDENCY_BYTES:
                raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
            digest.update(
                f"F\0{relative}\0{mode:o}\0{details.st_size}\0{_sha256(path)}\n".encode(
                    "utf-8"
                )
            )
    except RuntimeBootstrapError:
        raise
    except OSError:
        raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID") from None
    return digest.hexdigest()


def verify_dependencies(root: Path | None = None) -> Mapping[str, object]:
    _load_lock()
    _verify_runtime_parent()
    expected_root = dependency_root()
    candidate = expected_root if root is None else root
    if candidate != expected_root:
        raise RuntimeBootstrapError("NODE_DEPENDENCY_PATH_INVALID")
    package_root = candidate / "node_modules" / "playwright-core"
    receipt = _read_exact_json(
        candidate / ".controller-dependency-receipt.json",
        frozenset(
            {
                "package_name",
                "package_tree_sha256",
                "package_version",
                "schema_version",
                "source_archive_sha512_base64",
            }
        ),
        "NODE_DEPENDENCY_RECEIPT_INVALID",
    )
    try:
        candidate_details = candidate.lstat()
        modules_details = (candidate / "node_modules").lstat()
        package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID") from None
    if (
        stat.S_ISLNK(candidate_details.st_mode)
        or not stat.S_ISDIR(candidate_details.st_mode)
        or candidate_details.st_uid != os.getuid()
        or stat.S_IMODE(candidate_details.st_mode) & 0o077
        or stat.S_ISLNK(modules_details.st_mode)
        or not stat.S_ISDIR(modules_details.st_mode)
        or modules_details.st_uid != os.getuid()
        or stat.S_IMODE(modules_details.st_mode) & 0o077
        or package.get("name") != "playwright-core"
        or package.get("version") != "1.62.1"
    ):
        raise RuntimeBootstrapError("NODE_DEPENDENCY_IDENTITY_INVALID")
    tree_sha = _dependency_tree_sha256(package_root)
    if (
        receipt.get("schema_version") != DEPENDENCY_RECEIPT_SCHEMA
        or receipt.get("package_name") != "playwright-core"
        or receipt.get("package_version") != "1.62.1"
        or receipt.get("source_archive_sha512_base64")
        != PLAYWRIGHT_ARCHIVE_SHA512_BASE64
        or receipt.get("package_tree_sha256") != tree_sha
    ):
        raise RuntimeBootstrapError("NODE_DEPENDENCY_RECEIPT_INVALID")
    return {
        "package_name": "playwright-core",
        "package_root": str(package_root),
        "package_tree_sha256": tree_sha,
        "package_version": "1.62.1",
        "schema_version": "moss-tts-t4k-controller-node-dependency/1.0",
        "status": "verified",
    }


def _download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "ai-novel-world-2026-t4k-bootstrap/1"})
    total = 0
    try:
        with urlopen(request, timeout=30) as response, destination.open("xb") as output:
            if response.geturl() != url:
                raise RuntimeBootstrapError("NODE_RUNTIME_DOWNLOAD_REDIRECTED")
            while True:
                chunk = response.read(min(1024 * 1024, MAX_ARCHIVE_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise RuntimeBootstrapError("NODE_RUNTIME_ARCHIVE_TOO_LARGE")
                output.write(chunk)
    except RuntimeBootstrapError:
        raise
    except OSError:
        raise RuntimeBootstrapError("NODE_RUNTIME_DOWNLOAD_FAILED") from None
    if total == 0:
        raise RuntimeBootstrapError("NODE_RUNTIME_DOWNLOAD_FAILED")


def _safe_member(member: tarfile.TarInfo, prefix: str) -> bool:
    path = Path(member.name)
    if path.is_absolute() or not path.parts or path.parts[0] != prefix or ".." in path.parts:
        return False
    if member.isdev() or member.isfifo() or member.islnk():
        return False
    if member.issym():
        target = Path(member.linkname)
        if target.is_absolute():
            return False
        resolved_parts: list[str] = list(path.parent.parts)
        for part in target.parts:
            if part == "..":
                if not resolved_parts:
                    return False
                resolved_parts.pop()
            elif part not in {"", "."}:
                resolved_parts.append(part)
        return bool(resolved_parts) and resolved_parts[0] == prefix
    return member.isfile() or member.isdir()


def _extract(archive: Path, destination: Path, prefix: str) -> Path:
    try:
        with tarfile.open(archive, mode="r:gz") as handle:
            members = handle.getmembers()
            if (
                not members
                or len({member.name for member in members}) != len(members)
                or any(not _safe_member(member, prefix) for member in members)
            ):
                raise RuntimeBootstrapError("NODE_RUNTIME_ARCHIVE_UNSAFE")
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for member in members:
                if not member.isdir():
                    continue
                target = destination / member.name
                target.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
                target.chmod(member.mode & 0o777)
            for member in members:
                if not member.isfile():
                    continue
                target = destination / member.name
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise RuntimeBootstrapError("NODE_RUNTIME_EXTRACTION_FAILED")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            for member in members:
                if not member.issym():
                    continue
                target = destination / member.name
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                os.symlink(member.linkname, target)
    except RuntimeBootstrapError:
        raise
    except (OSError, tarfile.TarError):
        raise RuntimeBootstrapError("NODE_RUNTIME_EXTRACTION_FAILED") from None
    extracted = destination / prefix
    if not extracted.is_dir():
        raise RuntimeBootstrapError("NODE_RUNTIME_EXTRACTION_FAILED")
    return extracted


def install_runtime() -> Mapping[str, object]:
    lock = _load_lock()
    key = _platform_key()
    filename, expected_sha = _archive(lock, key)
    destination = runtime_root(key)
    if destination.exists() or destination.is_symlink():
        return verify_runtime(destination)
    _verify_runtime_parent(create=True)
    temporary = Path(tempfile.mkdtemp(prefix="node-bootstrap-", dir=RUNTIME_PARENT))
    try:
        archive = temporary / filename
        _download(f"{lock['base_url']}/{filename}", archive)
        if _sha256(archive) != expected_sha:
            raise RuntimeBootstrapError("NODE_RUNTIME_ARCHIVE_HASH_MISMATCH")
        extracted = _extract(archive, temporary / "extract", filename.removesuffix(".tar.gz"))
        extracted.chmod(0o700)
        node = extracted / "bin" / "node"
        _write_private_json(
            extracted / ".controller-runtime-receipt.json",
            {
                "node_executable_sha256": _sha256(node),
                "node_version": "24.19.0",
                "platform": key,
                "schema_version": RUNTIME_RECEIPT_SCHEMA,
                "source_archive_sha256": expected_sha,
            },
        )
        os.rename(extracted, destination)
        return verify_runtime(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def prepare_dependencies() -> Mapping[str, object]:
    """Install playwright-core from the fixed, pre-provisioned offline archive."""
    _load_lock()
    _verify_runtime_parent()
    archive = dependency_archive_path()
    destination = dependency_root()
    if destination.exists() or destination.is_symlink():
        return verify_dependencies(destination)
    try:
        archive_details = archive.lstat()
        if (
            stat.S_ISLNK(archive_details.st_mode)
            or not stat.S_ISREG(archive_details.st_mode)
            or archive_details.st_uid != os.getuid()
            or archive_details.st_nlink != 1
            or stat.S_IMODE(archive_details.st_mode) & 0o022
            or archive_details.st_size <= 0
            or archive_details.st_size > MAX_ARCHIVE_BYTES
        ):
            raise RuntimeBootstrapError("NODE_DEPENDENCY_ARCHIVE_UNSAFE")
        with archive.open("rb") as handle:
            archive_sha512 = base64.b64encode(
                hashlib.file_digest(handle, "sha512").digest()
            ).decode("ascii")
    except RuntimeBootstrapError:
        raise
    except OSError:
        raise RuntimeBootstrapError("NODE_DEPENDENCY_ARCHIVE_UNAVAILABLE") from None
    if archive_sha512 != PLAYWRIGHT_ARCHIVE_SHA512_BASE64:
        raise RuntimeBootstrapError("NODE_DEPENDENCY_ARCHIVE_HASH_MISMATCH")
    temporary = Path(tempfile.mkdtemp(prefix="dependency-bootstrap-", dir=RUNTIME_PARENT))
    try:
        extracted = temporary / "package"
        with tarfile.open(archive, mode="r:gz") as handle:
            members = handle.getmembers()
            if (
                not members
                or len({member.name for member in members}) != len(members)
                or len(members) > MAX_DEPENDENCY_FILES
                or any(not _safe_dependency_member(member) for member in members)
                or sum(member.size for member in members if member.isfile())
                > MAX_DEPENDENCY_BYTES
            ):
                raise RuntimeBootstrapError("NODE_DEPENDENCY_ARCHIVE_UNSAFE")
            package_destination = extracted / "node_modules" / "playwright-core"
            package_destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for member in members:
                relative_parts = Path(member.name).parts[1:]
                if not relative_parts:
                    continue
                target = package_destination.joinpath(*relative_parts)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    target.chmod(0o700)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise RuntimeBootstrapError("NODE_DEPENDENCY_EXTRACTION_FAILED")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o500 if member.mode & 0o111 else 0o400)
        # ``Path.mkdir(parents=True)`` creates intermediate parents with its
        # default mode, not the explicit mode supplied for the final path.
        # npm archives commonly omit directory entries, so normalize every
        # extracted directory before computing the private tree identity.
        for directory in sorted(
            (item for item in package_destination.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            directory.chmod(0o700)
        package = json.loads(
            (package_destination / "package.json").read_text(encoding="utf-8")
        )
        if package.get("name") != "playwright-core" or package.get("version") != "1.62.1":
            raise RuntimeBootstrapError("NODE_DEPENDENCY_PACKAGE_MISMATCH")
        tree_sha = _dependency_tree_sha256(package_destination)
        _write_private_json(
            extracted / ".controller-dependency-receipt.json",
            {
                "package_name": "playwright-core",
                "package_tree_sha256": tree_sha,
                "package_version": "1.62.1",
                "schema_version": DEPENDENCY_RECEIPT_SCHEMA,
                "source_archive_sha512_base64": PLAYWRIGHT_ARCHIVE_SHA512_BASE64,
            },
        )
        extracted.chmod(0o700)
        (extracted / "node_modules").chmod(0o700)
        os.rename(extracted, destination)
        return verify_dependencies(destination)
    except RuntimeBootstrapError:
        raise
    except (OSError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeBootstrapError("NODE_DEPENDENCY_EXTRACTION_FAILED") from None
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def verify_all() -> Mapping[str, object]:
    return {
        "dependency": verify_dependencies(),
        "runtime": verify_runtime(),
        "schema_version": "moss-tts-t4k-controller-node-environment/1.0",
        "status": "verified",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "verify",
            "verify-runtime",
            "verify-dependencies",
            "install-runtime",
            "prepare-dependencies",
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "verify":
            report = verify_all()
        elif args.command == "verify-runtime":
            report = verify_runtime()
        elif args.command == "verify-dependencies":
            report = verify_dependencies()
        elif args.command == "install-runtime":
            report = install_runtime()
        else:
            report = prepare_dependencies()
    except RuntimeBootstrapError as error:
        print(_canonical_json({"error_code": error.code, "status": "hold"}))
        return 78
    print(_canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
