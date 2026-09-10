"""Exact, author-confirmed deletion of one novel and its narration closure."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
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
    actor: str = "local-author",
) -> dict[str, object]:
    """Delete one exact novel, then unlink only its frozen local media files."""

    if type(novel_id) is not UUID or type(expected_version) is not int or expected_version < 1:
        raise ValueError("novel deletion requires an exact UUID and positive version")
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
                    "media_count,media_bytes,confirmed_actor,created_at,updated_at) "
                    "VALUES (:id,:novel_id,:version,:title_sha256,'purging',"
                    "CAST(:manifest AS jsonb),:media_count,:media_bytes,:actor,:now,:now)"
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


__all__ = ["delete_novel_with_narration"]
