"""Exact, author-confirmed deletion of one novel and its narration closure."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import stat
from typing import Callable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import MediaAsset, Novel
from ..services import ValidationError
from .storage import NarrationStorage, StorageError, StoredFileIdentity


class NovelDeletionRuntime(Protocol):
    session_factory: Callable[[], Session]
    storage: NarrationStorage


@dataclass(frozen=True, slots=True)
class MaintenanceDeletionContext:
    """Trusted local maintenance proof; never accepted from an HTTP payload."""

    novel_id: UUID
    expected_version: int
    manifest_sha256: str
    backup_receipt_sha256: str
    isolated_restore_verified: bool


@dataclass(frozen=True, slots=True)
class _AuthorConfirmedDeletionContext:
    """Server-created proof for the recycle-bin typed confirmation flow."""

    novel_id: UUID
    expected_version: int


PURGE_BACKUP_ROOT_ENV = "AI_NOVEL_PURGE_BACKUP_ROOT"
DEFAULT_PURGE_BACKUP_ROOT = Path("/app/working.backups/ai-novel-world-2026")
PURGE_RECEIPT_SCHEMA = "novel-purge-backup-receipt/2"
PURGE_RESTORE_EVIDENCE_SCHEMA = "novel-purge-restore-evidence/1"
_MAX_CONTROL_FILE_BYTES = 1_048_576


def author_confirmed_deletion_context(
    novel_id: UUID,
    *,
    expected_version: int,
    confirmation_text: str,
) -> _AuthorConfirmedDeletionContext:
    """Build the narrow authorization produced by the exact UI phrase.

    The HTTP body never supplies filesystem paths, hashes, actors or a generic
    verification flag.  A maintenance receipt remains supported for operator
    workflows, but it is not a hidden prerequisite for the author's explicit
    two-step recycle-bin deletion.
    """

    if type(novel_id) is not UUID or type(expected_version) is not int or expected_version < 1:
        raise ValueError("novel deletion requires an exact UUID and positive version")
    if confirmation_text != "确认删除":
        raise ValidationError("请逐字输入“确认删除”")
    return _AuthorConfirmedDeletionContext(
        novel_id=novel_id,
        expected_version=expected_version,
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_file(
    root: Path,
    relative_path: object,
    *,
    max_bytes: int | None = None,
) -> Path:
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise ValidationError("永久删除备份回执包含无效路径")
    unresolved = root / relative_path
    if unresolved.is_symlink():
        raise ValidationError("永久删除备份回执不得引用软链接")
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as error:
        raise ValidationError("永久删除备份文件不存在或不可读取") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValidationError("永久删除备份路径越出受信目录") from error
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValidationError("永久删除备份回执只能引用普通文件")
    if max_bytes is not None and info.st_size > max_bytes:
        raise ValidationError("永久删除控制文件超过大小限制")
    return resolved


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError("永久删除备份回执格式无效") from error
    if not isinstance(value, dict):
        raise ValidationError("永久删除备份回执格式无效")
    return value


def load_ui_maintenance_context(
    novel_id: UUID,
    *,
    expected_version: int,
    backup_root: Path | None = None,
) -> MaintenanceDeletionContext:
    """Load and verify the exact server-owned backup grant for one UI purge."""

    configured_root = os.environ.get(PURGE_BACKUP_ROOT_ENV, "").strip()
    root = (
        backup_root
        if backup_root is not None
        else Path(configured_root) if configured_root else DEFAULT_PURGE_BACKUP_ROOT
    ).resolve()
    receipt_relative = f"purge-receipts/{novel_id}.v{expected_version}.json"
    receipt_path = _trusted_file(root, receipt_relative, max_bytes=_MAX_CONTROL_FILE_BYTES)
    raw = receipt_path.read_bytes()
    data = _read_json(receipt_path)
    if data.get("schema") != PURGE_RECEIPT_SCHEMA:
        raise ValidationError("永久删除备份回执版本不受支持")
    if data.get("novel_id") != str(novel_id) or data.get("expected_version") != expected_version:
        raise ValidationError("永久删除备份回执与当前小说版本不一致")
    manifest_sha256 = data.get("target_manifest_sha256")
    if not _is_sha256(manifest_sha256):
        raise ValidationError("永久删除备份回执缺少目标清单摘要")

    verified_hashes: dict[str, str] = {}
    for field in ("database_backup", "media_backup"):
        item = data.get(field)
        if not isinstance(item, dict):
            raise ValidationError("永久删除备份回执不完整")
        target = _trusted_file(root, item.get("path"))
        expected = item.get("sha256")
        actual = _sha256_file(target)
        if not _is_sha256(expected) or expected != actual:
            raise ValidationError("永久删除备份文件摘要校验失败")
        verified_hashes[field] = actual

    restore = data.get("isolated_restore")
    if not isinstance(restore, dict) or restore.get("result") != "PASS":
        raise ValidationError("永久删除缺少隔离恢复通过证据")
    evidence_path = _trusted_file(
        root, restore.get("evidence_path"), max_bytes=_MAX_CONTROL_FILE_BYTES
    )
    evidence_expected = restore.get("evidence_sha256")
    if not _is_sha256(evidence_expected) or _sha256_file(evidence_path) != evidence_expected:
        raise ValidationError("永久删除隔离恢复证据摘要校验失败")
    evidence = _read_json(evidence_path)
    if (
        evidence.get("schema") != PURGE_RESTORE_EVIDENCE_SCHEMA
        or evidence.get("result") != "PASS"
        or evidence.get("novel_id") != str(novel_id)
        or evidence.get("expected_version") != expected_version
        or evidence.get("database_backup_sha256") != verified_hashes["database_backup"]
        or evidence.get("media_backup_sha256") != verified_hashes["media_backup"]
    ):
        raise ValidationError("永久删除隔离恢复证据与目标不一致")
    return MaintenanceDeletionContext(
        novel_id=novel_id,
        expected_version=expected_version,
        manifest_sha256=manifest_sha256,
        backup_receipt_sha256=hashlib.sha256(raw).hexdigest(),
        isolated_restore_verified=True,
    )


@dataclass(frozen=True, slots=True)
class NovelDeletionMedia:
    asset_id: UUID
    storage_path: str
    content_hash: str
    byte_size: int
    identity: StoredFileIdentity | None

    def payload(self) -> dict[str, object]:
        return {
            "asset_id": str(self.asset_id),
            "storage_path": self.storage_path,
            "content_hash": self.content_hash,
            "byte_size": self.byte_size,
            "file_present": self.identity is not None,
            "device": self.identity.device if self.identity else None,
            "inode": self.identity.inode if self.identity else None,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_novel(session: Session, novel_id: UUID, expected_version: int) -> Novel:
    novel = session.scalar(
        select(Novel).where(Novel.id == novel_id).with_for_update()
    )
    if novel is None:
        raise ValidationError("小说不存在或已删除")
    if novel.version != expected_version:
        raise ValidationError("小说已在其他位置更新，请刷新后重试")
    if novel.recycled_at is None:
        raise ValidationError("小说必须先移入回收站才能永久删除")
    return novel


def _capture_media(
    session: Session,
    storage: NarrationStorage,
    novel_id: UUID,
) -> tuple[NovelDeletionMedia, ...]:
    rows = tuple(
        session.scalars(
            select(MediaAsset)
            .where(MediaAsset.novel_id == novel_id)
            .order_by(MediaAsset.id)
        ).all()
    )
    captured: list[NovelDeletionMedia] = []
    for row in rows:
        if row.storage_backend != "local" or row.byte_size is None or row.byte_size < 0:
            raise ValidationError("小说包含不可安全删除的媒体记录")
        identity = storage.capture_media_identity(row.storage_path, missing_ok=True)
        if identity is not None and identity.byte_size != row.byte_size:
            raise ValidationError("媒体文件与数据库大小不一致，已停止删除")
        captured.append(
            NovelDeletionMedia(
                asset_id=row.id,
                storage_path=row.storage_path,
                content_hash=row.content_hash,
                byte_size=row.byte_size,
                identity=identity,
            )
        )
    return tuple(captured)


def _freeze_targets(session: Session, novel_id: UUID) -> None:
    statements = (
        "CREATE TEMP TABLE nd_documents ON COMMIT DROP AS SELECT id FROM documents WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_creation_drafts ON COMMIT DROP AS SELECT id FROM novel_creation_drafts WHERE completed_novel_id=:novel_id",
        "CREATE TEMP TABLE nd_editions ON COMMIT DROP AS SELECT id FROM narration_editions WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_renders ON COMMIT DROP AS SELECT id FROM narration_segment_renders WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_requests ON COMMIT DROP AS SELECT id FROM narration_requests WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_scripts ON COMMIT DROP AS SELECT id FROM narration_scripts WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_script_versions ON COMMIT DROP AS SELECT id FROM narration_script_versions WHERE script_id IN (SELECT id FROM nd_scripts)",
        "CREATE TEMP TABLE nd_profiles ON COMMIT DROP AS SELECT id FROM voice_profiles WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_voice_versions ON COMMIT DROP AS SELECT id FROM voice_profile_versions WHERE profile_id IN (SELECT id FROM nd_profiles)",
        "CREATE TEMP TABLE nd_rights ON COMMIT DROP AS SELECT id FROM voice_rights_records WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_actions ON COMMIT DROP AS SELECT id FROM voice_action_commands WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_jobs ON COMMIT DROP AS SELECT id FROM background_jobs WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_attempts ON COMMIT DROP AS SELECT id FROM background_job_attempts WHERE job_id IN (SELECT id FROM nd_jobs)",
        "CREATE TEMP TABLE nd_model_runs ON COMMIT DROP AS SELECT id FROM model_run_records WHERE attempt_id IN (SELECT id FROM nd_attempts)",
        "CREATE TEMP TABLE nd_embedding_batches ON COMMIT DROP AS SELECT id,generation_id FROM embedding_index_batches WHERE novel_id=:novel_id",
        "CREATE TEMP TABLE nd_assets ON COMMIT DROP AS SELECT id FROM media_assets WHERE novel_id=:novel_id",
    )
    for statement in statements:
        session.execute(text(statement), {"novel_id": novel_id})


def _delete_database_closure(session: Session, novel_id: UUID) -> None:
    # Child-first ordering is intentional.  Foreign keys remain enabled; the
    # transaction-local authorization only suppresses immutable user triggers.
    statements = (
        "SET CONSTRAINTS ALL DEFERRED",
        "DELETE FROM writing_skill_dispatches WHERE scope_kind='creation_draft' AND scope_id IN (SELECT id FROM nd_creation_drafts)",
        "DELETE FROM creative_generation_jobs WHERE scope_type='novel_creation' AND scope_id IN (SELECT id FROM nd_creation_drafts)",
        "DELETE FROM novel_creation_drafts WHERE id IN (SELECT id FROM nd_creation_drafts)",
        "DELETE FROM document_narration_state WHERE document_id IN (SELECT id FROM documents WHERE novel_id=:novel_id)",
        "DELETE FROM narration_script_review_actions WHERE request_id IN (SELECT id FROM nd_requests) OR parent_version_id IN (SELECT id FROM nd_script_versions) OR result_version_id IN (SELECT id FROM nd_script_versions) OR result_edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_playback_progress WHERE edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_edition_state WHERE edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_manifest_segments WHERE edition_id IN (SELECT id FROM nd_editions) OR render_id IN (SELECT id FROM nd_renders)",
        "DELETE FROM narration_manifests WHERE edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_exports WHERE edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_edition_segments WHERE edition_id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_editions WHERE id IN (SELECT id FROM nd_editions)",
        "DELETE FROM narration_render_assets WHERE render_id IN (SELECT id FROM nd_renders)",
        "DELETE FROM narration_segment_renders WHERE id IN (SELECT id FROM nd_renders)",
        "DELETE FROM narration_script_issues WHERE script_version_id IN (SELECT id FROM nd_script_versions)",
        "DELETE FROM narration_segments WHERE script_version_id IN (SELECT id FROM nd_script_versions)",
        "DELETE FROM narration_scenes WHERE script_version_id IN (SELECT id FROM nd_script_versions)",
        "UPDATE narration_requests SET review_script_id=NULL,current_review_version_id=NULL WHERE id IN (SELECT id FROM nd_requests)",
        "UPDATE narration_script_versions SET parent_version_id=NULL WHERE id IN (SELECT id FROM nd_script_versions)",
        "DELETE FROM narration_script_versions WHERE id IN (SELECT id FROM nd_script_versions)",
        "DELETE FROM narration_scripts WHERE id IN (SELECT id FROM nd_scripts)",
        "DELETE FROM narration_settings_snapshots WHERE novel_id=:novel_id",
        "DELETE FROM narration_cloud_consents WHERE novel_id=:novel_id",
        "DELETE FROM narration_scope_overrides WHERE novel_id=:novel_id",
        "DELETE FROM voice_action_commands WHERE id IN (SELECT id FROM nd_actions)",
        "DELETE FROM voice_action_receipts WHERE resource_id IN (SELECT id FROM nd_actions)",
        "DELETE FROM novel_narration_settings WHERE novel_id=:novel_id",
        "DELETE FROM character_voice_bindings WHERE character_id IN (SELECT id FROM novel_characters WHERE novel_id=:novel_id)",
        "DELETE FROM anonymous_speakers WHERE novel_id=:novel_id",
        "DELETE FROM voice_casting_rules WHERE novel_id=:novel_id",
        "DELETE FROM pronunciation_entries WHERE profile_id IN (SELECT id FROM pronunciation_profiles WHERE novel_id=:novel_id)",
        "DELETE FROM pronunciation_profiles WHERE novel_id=:novel_id",
        "DELETE FROM asset_tombstones WHERE deletion_request_id IN (SELECT id FROM voice_deletion_requests WHERE novel_id=:novel_id)",
        "DELETE FROM voice_deletion_asset_plans WHERE novel_id=:novel_id",
        "DELETE FROM voice_deletion_requests WHERE novel_id=:novel_id",
        "DELETE FROM voice_reference_asset_links WHERE novel_id=:novel_id OR profile_id IN (SELECT id FROM nd_profiles)",
        "DELETE FROM voice_previews WHERE novel_id=:novel_id OR profile_id IN (SELECT id FROM nd_profiles)",
        "UPDATE voice_profiles SET current_version_id=NULL WHERE id IN (SELECT id FROM nd_profiles)",
        "DELETE FROM voice_profile_versions WHERE id IN (SELECT id FROM nd_voice_versions)",
        "DELETE FROM voice_profiles WHERE id IN (SELECT id FROM nd_profiles)",
        "DELETE FROM voice_rights_events WHERE rights_record_id IN (SELECT id FROM nd_rights)",
        "DELETE FROM voice_rights_records WHERE id IN (SELECT id FROM nd_rights)",
        "DELETE FROM active_job_assets WHERE job_id IN (SELECT id FROM nd_jobs) OR asset_id IN (SELECT id FROM nd_assets)",
        "DELETE FROM semantic_embeddings WHERE model_run_id IN (SELECT id FROM nd_model_runs) OR (batch_id,generation_id) IN (SELECT id,generation_id FROM nd_embedding_batches)",
        "DELETE FROM embedding_index_batches WHERE (id,generation_id) IN (SELECT id,generation_id FROM nd_embedding_batches)",
        "DELETE FROM embedding_generation_novels WHERE novel_id=:novel_id",
        "DELETE FROM model_run_records WHERE id IN (SELECT id FROM nd_model_runs)",
        "DELETE FROM background_job_attempts WHERE id IN (SELECT id FROM nd_attempts)",
        "DELETE FROM background_manual_retry_commands WHERE job_id IN (SELECT id FROM nd_jobs)",
        "DELETE FROM background_jobs WHERE id IN (SELECT id FROM nd_jobs)",
        "DELETE FROM narration_request_sources WHERE request_id IN (SELECT id FROM nd_requests)",
        "DELETE FROM narration_requests WHERE id IN (SELECT id FROM nd_requests)",
        "DELETE FROM media_gc_deletion_plans WHERE asset_id IN (SELECT id FROM nd_assets)",
        "DELETE FROM media_assets WHERE id IN (SELECT id FROM nd_assets)",
        "DELETE FROM novels WHERE id=:novel_id",
    )
    for statement in statements:
        session.execute(text(statement), {"novel_id": novel_id})


def delete_novel_with_narration(
    runtime: NovelDeletionRuntime,
    novel_id: UUID,
    *,
    expected_version: int,
    maintenance: MaintenanceDeletionContext | _AuthorConfirmedDeletionContext,
    actor: str = "local-author",
) -> dict[str, object]:
    """Delete one exact novel, then unlink only its frozen local media files."""

    if type(novel_id) is not UUID or type(expected_version) is not int or expected_version < 1:
        raise ValueError("novel deletion requires an exact UUID and positive version")
    receipt_sha256: str | None
    expected_manifest_sha256: str | None
    if isinstance(maintenance, MaintenanceDeletionContext):
        valid_context = (
            maintenance.novel_id == novel_id
            and maintenance.expected_version == expected_version
            and maintenance.isolated_restore_verified
            and len(maintenance.manifest_sha256) == 64
            and len(maintenance.backup_receipt_sha256) == 64
        )
        receipt_sha256 = maintenance.backup_receipt_sha256
        expected_manifest_sha256 = maintenance.manifest_sha256
    elif isinstance(maintenance, _AuthorConfirmedDeletionContext):
        valid_context = (
            maintenance.novel_id == novel_id
            and maintenance.expected_version == expected_version
        )
        receipt_sha256 = None
        expected_manifest_sha256 = None
    else:
        valid_context = False
        receipt_sha256 = None
        expected_manifest_sha256 = None
    if not valid_context:
        raise ValidationError("永久删除缺少与目标绑定的可信确认上下文")
    actor = actor.strip()
    if not actor or len(actor) > 120:
        raise ValueError("novel deletion actor is invalid")

    session_factory = runtime.session_factory
    storage = runtime.storage
    with session_factory() as session:  # type: ignore[operator]
        novel = _require_novel(session, novel_id, expected_version)
        document_ids = tuple(
            str(value)
            for value in session.scalars(
                text("SELECT id FROM documents WHERE novel_id=:novel_id ORDER BY id"),
                {"novel_id": novel_id},
            ).all()
        )
        media = _capture_media(session, storage, novel_id)
        title_sha256 = hashlib.sha256(novel.title.encode("utf-8")).hexdigest()
        session.rollback()

    request_id = uuid4()
    manifest = [item.payload() for item in media]
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValidationError("小说媒体清单与维护回执不一致")
    with session_factory() as session:  # type: ignore[operator]
        with session.begin():
            novel = _require_novel(session, novel_id, expected_version)
            active_count = session.scalar(
                text(
                    "SELECT count(*) FROM background_jobs "
                    "WHERE novel_id=:novel_id AND state IN "
                    "('queued','leased','running','retry_wait','cancelling')"
                ),
                {"novel_id": novel_id},
            )
            if int(active_count or 0):
                raise ValidationError("小说仍有进行中的后台任务，请稍后重试")
            current_media = _capture_media(session, storage, novel_id)
            if [item.payload() for item in current_media] != manifest:
                raise ValidationError("小说媒体在删除前已变化，请刷新后重试")
            current_document_ids = tuple(
                str(value)
                for value in session.scalars(
                    text("SELECT id FROM documents WHERE novel_id=:novel_id ORDER BY id"),
                    {"novel_id": novel_id},
                ).all()
            )
            if current_document_ids != document_ids:
                raise ValidationError("小说文档在删除前已变化，请刷新后重试")
            now = _utc_now()
            session.execute(
                text(
                    "INSERT INTO novel_deletion_audits "
                    "(id,novel_id,expected_version,title_sha256,state,media_manifest_json,"
                    "media_count,media_bytes,confirmed_actor,backup_receipt_sha256,created_at,updated_at) "
                    "VALUES (:id,:novel_id,:version,:title_sha256,'purging',"
                    "CAST(:manifest AS jsonb),:media_count,:media_bytes,:actor,:receipt_sha256,:now,:now)"
                ),
                {
                    "id": request_id,
                    "novel_id": novel_id,
                    "version": expected_version,
                    "title_sha256": title_sha256,
                    "manifest": json.dumps(manifest, separators=(",", ":")),
                    "media_count": len(media),
                    "media_bytes": sum(item.byte_size for item in media),
                    "actor": actor,
                    "receipt_sha256": receipt_sha256,
                    "now": now,
                },
            )
            session.execute(
                text("SELECT set_config('ai_novel.novel_deletion_request_id', :request_id, true)"),
                {"request_id": str(request_id)},
            )
            _freeze_targets(session, novel_id)
            _delete_database_closure(session, novel_id)
            session.execute(
                text(
                    "UPDATE novel_deletion_audits SET state='database_deleted',"
                    "database_deleted_at=:now,updated_at=:now WHERE id=:id"
                ),
                {"id": request_id, "now": _utc_now()},
            )

    removed_count = 0
    try:
        for item in media:
            identity = item.identity
            removed = storage.delete_media_verified(
                item.storage_path,
                expected_sha256=item.content_hash,
                expected_size=item.byte_size,
                expected_device=identity.device if identity else None,
                expected_inode=identity.inode if identity else None,
                expected_present=identity is not None,
                missing_ok=True,
            )
            storage.ensure_media_absent(item.storage_path)
            removed_count += int(removed)
    except (OSError, StorageError):
        with session_factory() as session:  # type: ignore[operator]
            with session.begin():
                session.execute(
                    text(
                        "UPDATE novel_deletion_audits SET state='media_cleanup_failed',"
                        "failure_code='NOVEL_DELETE_MEDIA_CLEANUP_FAILED',updated_at=:now "
                        "WHERE id=:id"
                    ),
                    {"id": request_id, "now": _utc_now()},
                )
        return {
            "deleted": True,
            "media_cleanup_pending": True,
            "deleted_media_count": removed_count,
            "deleted_document_ids": list(document_ids),
        }

    with session_factory() as session:  # type: ignore[operator]
        with session.begin():
            session.execute(
                text(
                    "UPDATE novel_deletion_audits SET state='completed',"
                    "media_deleted_at=:now,updated_at=:now WHERE id=:id"
                ),
                {"id": request_id, "now": _utc_now()},
            )
    return {
        "deleted": True,
        "media_cleanup_pending": False,
        "deleted_media_count": removed_count,
        "deleted_document_ids": list(document_ids),
    }


__all__ = [
    "MaintenanceDeletionContext",
    "author_confirmed_deletion_context",
    "delete_novel_with_narration",
    "load_ui_maintenance_context",
]
