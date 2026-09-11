from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.services import ValidationError
from backend.narration.novel_deletion import author_confirmed_deletion_context
from scripts.maintain_novel_recycle_bin import verified_context


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_receipt(root: Path, novel_id: UUID, version: int, manifest: str) -> Path:
    database = b"database backup"
    media = b"media backup"
    (root / "backups").mkdir()
    (root / "backups/database.dump").write_bytes(database)
    (root / "backups/media.tar.gz").write_bytes(media)
    evidence = json.dumps(
        {
            "schema": "novel-purge-restore-evidence/1",
            "result": "PASS",
            "novel_id": str(novel_id),
            "expected_version": version,
            "database_backup_sha256": _sha(database),
            "media_backup_sha256": _sha(media),
        },
        sort_keys=True,
    ).encode()
    (root / "backups/restore-evidence.json").write_bytes(evidence)
    receipt = json.dumps(
        {
            "schema": "novel-purge-backup-receipt/2",
            "novel_id": str(novel_id),
            "expected_version": version,
            "target_manifest_sha256": manifest,
            "database_backup": {
                "path": "backups/database.dump",
                "sha256": _sha(database),
            },
            "media_backup": {
                "path": "backups/media.tar.gz",
                "sha256": _sha(media),
            },
            "isolated_restore": {
                "result": "PASS",
                "evidence_path": "backups/restore-evidence.json",
                "evidence_sha256": _sha(evidence),
            },
        },
        sort_keys=True,
    ).encode()
    directory = root / "purge-receipts"
    directory.mkdir()
    path = directory / f"{novel_id}.v{version}.json"
    path.write_bytes(receipt)
    return path


def test_verified_receipt_is_bound_to_exact_target_and_real_files(tmp_path: Path) -> None:
    novel_id = uuid4()
    path = write_receipt(tmp_path, novel_id, 7, "c" * 64)

    context = verified_context(
        path, novel_id=novel_id, expected_version=7, manifest_sha256="c" * 64
    )

    assert context.novel_id == novel_id
    assert context.backup_receipt_sha256 == _sha(path.read_bytes())


def test_receipt_target_or_backup_tampering_fails_closed(tmp_path: Path) -> None:
    novel_id = uuid4()
    path = write_receipt(tmp_path, novel_id, 7, "c" * 64)

    with pytest.raises(ValueError, match="target differs"):
        verified_context(
            path, novel_id=novel_id, expected_version=8, manifest_sha256="c" * 64
        )

    (tmp_path / "backups/database.dump").write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="摘要校验失败"):
        verified_context(
            path, novel_id=novel_id, expected_version=7, manifest_sha256="c" * 64
        )


def test_receipt_cannot_escape_trusted_root_or_use_plain_verified_flag(tmp_path: Path) -> None:
    novel_id = uuid4()
    path = write_receipt(tmp_path, novel_id, 7, "c" * 64)
    data = json.loads(path.read_text())
    data["database_backup"]["path"] = "../outside.dump"
    data["verified"] = True
    path.write_text(json.dumps(data))

    with pytest.raises(ValidationError, match="越出受信目录|不存在"):
        verified_context(
            path, novel_id=novel_id, expected_version=7, manifest_sha256="c" * 64
        )


def test_author_confirmation_is_exact_and_target_bound() -> None:
    novel_id = uuid4()
    context = author_confirmed_deletion_context(
        novel_id,
        expected_version=7,
        confirmation_text="确认删除",
    )
    assert context.novel_id == novel_id
    assert context.expected_version == 7

    with pytest.raises(ValidationError, match="逐字输入"):
        author_confirmed_deletion_context(
            novel_id,
            expected_version=7,
            confirmation_text="确认删除 ",
        )
