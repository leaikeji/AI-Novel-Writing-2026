#!/usr/bin/env python3
"""Move a frozen allowlist of retired local TTS media into recovery isolation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
from typing import NamedTuple


class ManifestRow(NamedTuple):
    asset_id: str
    storage_path: str
    byte_size: int
    content_hash: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> tuple[ManifestRow, ...]:
    required = {
        "id",
        "storage_backend",
        "storage_path",
        "byte_size",
        "content_hash",
    }
    rows: list[ManifestRow] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if set(reader.fieldnames or ()) != required:
            raise ValueError("retired media manifest columns are not canonical")
        for line_number, raw in enumerate(reader, start=2):
            asset_id = raw["id"]
            storage_path = raw["storage_path"]
            relative = PurePosixPath(storage_path)
            if (
                raw["storage_backend"] != "local"
                or not asset_id
                or not storage_path
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.parts[:1] != ("assets",)
            ):
                raise ValueError(f"unsafe retired media row at line {line_number}")
            try:
                byte_size = int(raw["byte_size"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"invalid byte size at line {line_number}"
                ) from error
            content_hash = raw["content_hash"]
            if (
                byte_size < 0
                or len(content_hash) != 64
                or any(character not in "0123456789abcdef" for character in content_hash)
                or asset_id in seen_ids
                or storage_path in seen_paths
            ):
                raise ValueError(f"invalid retired media identity at line {line_number}")
            seen_ids.add(asset_id)
            seen_paths.add(storage_path)
            rows.append(ManifestRow(asset_id, storage_path, byte_size, content_hash))
    if not rows:
        raise ValueError("retired media manifest is empty")
    return tuple(rows)


def _inside(root: Path, relative: str, *, must_exist: bool) -> Path:
    root = root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    resolved = candidate.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise ValueError(f"media path escapes its root: {relative}")
    return resolved


def isolate(
    *,
    manifest_path: Path,
    media_root: Path,
    isolation_root: Path,
    apply: bool,
    confirmed_manifest_sha256: str | None,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest_sha256 = _sha256(manifest_path)
    if apply and confirmed_manifest_sha256 != manifest_sha256:
        raise ValueError("apply requires the exact frozen manifest SHA-256")
    rows = _load_manifest(manifest_path)
    media_root = media_root.resolve(strict=True)
    if not media_root.is_dir():
        raise ValueError("media root must be a directory")
    isolation_root = isolation_root.resolve(strict=False)
    if isolation_root.exists() and any(isolation_root.iterdir()):
        raise ValueError("isolation root must be absent or empty")
    isolation_root.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    verified: list[tuple[ManifestRow, Path, Path]] = []
    for row in rows:
        source = _inside(media_root, row.storage_path, must_exist=True)
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"retired media source is not a regular file: {row.asset_id}")
        stat = source.stat()
        if stat.st_size != row.byte_size or _sha256(source) != row.content_hash:
            raise ValueError(f"retired media identity mismatch: {row.asset_id}")
        destination = _inside(isolation_root, row.storage_path, must_exist=False)
        if destination.exists():
            raise ValueError(f"retired media destination already exists: {row.asset_id}")
        total_bytes += stat.st_size
        verified.append((row, source, destination))

    moved: list[tuple[Path, Path]] = []
    if apply:
        try:
            for _row, source, destination in verified:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(os.fspath(source), os.fspath(destination))
                moved.append((source, destination))
        except Exception:
            for source, destination in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(os.fspath(destination), os.fspath(source))
            raise
        shutil.copy2(manifest_path, isolation_root / "retired-media.csv")

    return {
        "schema_version": "plan62-retired-tts-media-isolation/1",
        "mode": "apply" if apply else "dry-run",
        "manifest_sha256": manifest_sha256,
        "asset_count": len(rows),
        "byte_size": total_bytes,
        "moved_count": len(moved),
        "media_root": os.fspath(media_root),
        "isolation_root": os.fspath(isolation_root),
    }


def restore(
    *,
    manifest_path: Path,
    media_root: Path,
    isolation_root: Path,
    confirmed_manifest_sha256: str | None,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest_sha256 = _sha256(manifest_path)
    if confirmed_manifest_sha256 != manifest_sha256:
        raise ValueError("restore requires the exact frozen manifest SHA-256")
    rows = _load_manifest(manifest_path)
    media_root = media_root.resolve(strict=True)
    isolation_root = isolation_root.resolve(strict=True)
    if not media_root.is_dir() or not isolation_root.is_dir():
        raise ValueError("media and isolation roots must be directories")

    total_bytes = 0
    verified: list[tuple[ManifestRow, Path, Path]] = []
    for row in rows:
        source = _inside(isolation_root, row.storage_path, must_exist=True)
        destination = _inside(media_root, row.storage_path, must_exist=False)
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"isolated media is not a regular file: {row.asset_id}")
        if destination.exists():
            raise ValueError(f"active media destination already exists: {row.asset_id}")
        stat = source.stat()
        if stat.st_size != row.byte_size or _sha256(source) != row.content_hash:
            raise ValueError(f"isolated media identity mismatch: {row.asset_id}")
        total_bytes += stat.st_size
        verified.append((row, source, destination))

    moved: list[tuple[Path, Path]] = []
    try:
        for _row, source, destination in verified:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(os.fspath(source), os.fspath(destination))
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(os.fspath(destination), os.fspath(source))
        raise

    return {
        "schema_version": "plan62-retired-tts-media-isolation/1",
        "mode": "restore",
        "manifest_sha256": manifest_sha256,
        "asset_count": len(rows),
        "byte_size": total_bytes,
        "moved_count": len(moved),
        "media_root": os.fspath(media_root),
        "isolation_root": os.fspath(isolation_root),
    }


def verify_isolation(
    *,
    manifest_path: Path,
    media_root: Path,
    isolation_root: Path,
    confirmed_manifest_sha256: str | None,
) -> tuple[tuple[ManifestRow, Path], ...]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest_sha256 = _sha256(manifest_path)
    if confirmed_manifest_sha256 != manifest_sha256:
        raise ValueError("isolation verification requires the exact frozen manifest SHA-256")
    rows = _load_manifest(manifest_path)
    media_root = media_root.resolve(strict=True)
    isolation_root = isolation_root.resolve(strict=True)
    if not media_root.is_dir() or not isolation_root.is_dir():
        raise ValueError("media and isolation roots must be directories")

    copied_manifest = isolation_root / "retired-media.csv"
    if (
        not copied_manifest.is_file()
        or copied_manifest.is_symlink()
        or _sha256(copied_manifest) != manifest_sha256
    ):
        raise ValueError("isolation manifest copy does not match the frozen manifest")

    verified: list[tuple[ManifestRow, Path]] = []
    for row in rows:
        active_path = _inside(media_root, row.storage_path, must_exist=False)
        isolated_path = _inside(isolation_root, row.storage_path, must_exist=True)
        if active_path.exists():
            raise ValueError(f"retired media still exists in the active root: {row.asset_id}")
        if not isolated_path.is_file() or isolated_path.is_symlink():
            raise ValueError(f"isolated media is not a regular file: {row.asset_id}")
        stat = isolated_path.stat()
        if stat.st_size != row.byte_size or _sha256(isolated_path) != row.content_hash:
            raise ValueError(f"isolated media identity mismatch: {row.asset_id}")
        verified.append((row, isolated_path))
    return tuple(verified)


def inspect_isolation(
    *,
    manifest_path: Path,
    media_root: Path,
    isolation_root: Path,
    confirmed_manifest_sha256: str | None,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    verified = verify_isolation(
        manifest_path=manifest_path,
        media_root=media_root,
        isolation_root=isolation_root,
        confirmed_manifest_sha256=confirmed_manifest_sha256,
    )
    return {
        "schema_version": "plan62-retired-tts-media-isolation/1",
        "mode": "verify-isolation",
        "manifest_sha256": _sha256(manifest_path),
        "asset_count": len(verified),
        "byte_size": sum(row.byte_size for row, _path in verified),
        "verified_count": len(verified),
        "media_root": os.fspath(media_root.resolve(strict=True)),
        "isolation_root": os.fspath(isolation_root.resolve(strict=True)),
    }


def purge_isolation(
    *,
    manifest_path: Path,
    media_root: Path,
    isolation_root: Path,
    confirmed_manifest_sha256: str | None,
) -> dict[str, object]:
    manifest_path = manifest_path.resolve(strict=True)
    manifest_sha256 = _sha256(manifest_path)
    verified = verify_isolation(
        manifest_path=manifest_path,
        media_root=media_root,
        isolation_root=isolation_root,
        confirmed_manifest_sha256=confirmed_manifest_sha256,
    )
    isolation_root = isolation_root.resolve(strict=True)
    total_bytes = sum(row.byte_size for row, _path in verified)

    # Every file is identity-checked before the first unlink. Only allowlisted
    # payloads and the verified isolation-local manifest copy are removed.
    for _row, isolated_path in verified:
        isolated_path.unlink()
    (isolation_root / "retired-media.csv").unlink()
    for directory in sorted(
        (path for path in isolation_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.rmdir()

    return {
        "schema_version": "plan62-retired-tts-media-isolation/1",
        "mode": "purge-isolation",
        "manifest_sha256": manifest_sha256,
        "asset_count": len(verified),
        "byte_size": total_bytes,
        "purged_count": len(verified),
        "media_root": os.fspath(media_root.resolve(strict=True)),
        "isolation_root": os.fspath(isolation_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--isolation-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--verify-isolation", action="store_true")
    mode.add_argument("--purge-isolation", action="store_true")
    parser.add_argument("--confirm-manifest-sha256")
    args = parser.parse_args()
    try:
        if args.restore:
            result = restore(
                manifest_path=args.manifest,
                media_root=args.media_root,
                isolation_root=args.isolation_root,
                confirmed_manifest_sha256=args.confirm_manifest_sha256,
            )
        elif args.verify_isolation:
            result = inspect_isolation(
                manifest_path=args.manifest,
                media_root=args.media_root,
                isolation_root=args.isolation_root,
                confirmed_manifest_sha256=args.confirm_manifest_sha256,
            )
        elif args.purge_isolation:
            result = purge_isolation(
                manifest_path=args.manifest,
                media_root=args.media_root,
                isolation_root=args.isolation_root,
                confirmed_manifest_sha256=args.confirm_manifest_sha256,
            )
        else:
            result = isolate(
                manifest_path=args.manifest,
                media_root=args.media_root,
                isolation_root=args.isolation_root,
                apply=args.apply,
                confirmed_manifest_sha256=args.confirm_manifest_sha256,
            )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
