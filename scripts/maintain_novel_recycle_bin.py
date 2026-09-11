#!/usr/bin/env python3
"""Inspect or execute one exact recycle-bin purge from a verified backup receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from uuid import UUID

from backend.narration.novel_deletion import (
    MaintenanceDeletionContext,
    load_ui_maintenance_context,
)


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def verified_context(
    receipt_path: Path, *, novel_id: UUID, expected_version: int, manifest_sha256: str
) -> MaintenanceDeletionContext:
    if receipt_path.parent.name != "purge-receipts":
        raise ValueError("backup receipt must be installed in purge-receipts")
    expected_name = f"{novel_id}.v{expected_version}.json"
    if receipt_path.name != expected_name:
        raise ValueError("backup receipt target differs from the exact purge target")
    context = load_ui_maintenance_context(
        novel_id,
        expected_version=expected_version,
        backup_root=receipt_path.parent.parent,
    )
    if context.manifest_sha256 != manifest_sha256:
        raise ValueError("backup receipt manifest differs from the exact purge target")
    return context


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--novel-id", type=UUID, required=True)
    value.add_argument("--expected-version", type=int, required=True)
    value.add_argument("--manifest-sha256", required=True)
    value.add_argument("--backup-receipt", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.expected_version < 1 or not SHA256.fullmatch(args.manifest_sha256):
        raise SystemExit("invalid exact target version or manifest sha256")
    context = verified_context(
        args.backup_receipt,
        novel_id=args.novel_id,
        expected_version=args.expected_version,
        manifest_sha256=args.manifest_sha256,
    )
    summary = {
        "mode": "verified",
        "novel_id": str(context.novel_id),
        "expected_version": context.expected_version,
        "manifest_sha256": context.manifest_sha256,
        "backup_receipt_sha256": context.backup_receipt_sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
