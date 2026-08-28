"""Give every narration media asset an independent physical path.

Revision ID: 20260826_0013
Revises: 20260826_0012

The frozen 0012 layout addressed files only by their content digest.  That is
unsafe for the existing one-row-per-physical-path ownership and GC contract:
two logical assets containing identical bytes would otherwise collide.  This
forward migration changes only the database-side canonical-path guards.  It
never moves or rewrites files.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_0013"
down_revision = "20260826_0012"
branch_labels = None
depends_on = None


def _require_clean_forward_boundary() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM media_assets
                WHERE asset_class IS NOT NULL AND storage_backend='local'
              ) THEN
                RAISE EXCEPTION
                  'T1 asset-path preflight: existing narration media requires an audited filesystem-plus-database fix-forward before 0013';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_gc_deletion_plans p
                JOIN media_assets m ON m.id=p.asset_id
                WHERE m.asset_class IS NOT NULL AND m.storage_backend='local' AND
                  p.storage_path IS DISTINCT FROM m.storage_path
              ) THEN
                RAISE EXCEPTION
                  'T1 asset-path preflight: a GC plan does not match its asset path';
              END IF;
            END $$;
            """
        )
    )


def _require_clean_downgrade_boundary() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM media_assets
                WHERE asset_class IS NOT NULL AND storage_backend='local'
              ) THEN
                RAISE EXCEPTION
                  'T1 asset-path downgrade refused: scoped narration media exists; retain 0013 or perform an audited fix-forward';
              END IF;
            END $$;
            """
        )
    )


def _replace_gc_plan_guard(*, asset_scoped: bool) -> None:
    if asset_scoped:
        canonical_path = """
                    ('^assets/' ||
                     substr(replace(media_row.id::text,'-',''),1,2) || '/' ||
                     replace(media_row.id::text,'-','') || '/' ||
                     media_row.content_hash ||
                     '\\.(aac|flac|m4a|mp3|ogg|opus|wav)$')"""
    else:
        canonical_path = """
                    ('^assets/' || substr(media_row.content_hash,1,2) || '/' ||
                     media_row.content_hash ||
                     '\\.(aac|flac|m4a|mp3|ogg|opus|wav)$')"""
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_media_gc_plan()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE media_row media_assets%ROWTYPE;
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'media GC deletion plan is immutable';
              END IF;
              SELECT * INTO media_row FROM media_assets m
              WHERE m.id=NEW.asset_id FOR UPDATE;
              IF NOT FOUND OR media_row.state NOT IN ('ready','staging') THEN
                RAISE EXCEPTION 'media GC plan requires a locked ready or staging asset';
              END IF;
              IF NEW.created_at<clock_timestamp()-interval '5 seconds'
                 OR NEW.created_at>clock_timestamp()+interval '1 second'
              THEN
                RAISE EXCEPTION 'media GC plan requires the authoritative database clock';
              END IF;
              IF media_row.storage_backend<>'local'
                 OR media_row.asset_class IN ('source','voice_reference')
                 OR media_row.retention_policy IN
                    ('source','cover','uploaded_original','locked_voice','legal_hold','keep')
                 OR (media_row.expires_at IS NOT NULL
                     AND media_row.expires_at>clock_timestamp())
              THEN
                RAISE EXCEPTION 'media GC plan targets protected or unexpired media';
              END IF;
              IF media_row.content_hash !~ '^[0-9a-f]{{64}}$'
                 OR media_row.storage_path !~
                    {canonical_path}
                 OR NOT (CASE substring(media_row.storage_path from '\\.[^.]+$')
                   WHEN '.aac' THEN media_row.mime_type='audio/aac'
                   WHEN '.flac' THEN media_row.mime_type='audio/flac'
                   WHEN '.m4a' THEN media_row.mime_type='audio/mp4'
                   WHEN '.mp3' THEN media_row.mime_type='audio/mpeg'
                   WHEN '.ogg' THEN media_row.mime_type='audio/ogg'
                   WHEN '.opus' THEN media_row.mime_type='audio/ogg'
                   WHEN '.wav' THEN media_row.mime_type='audio/wav'
                   ELSE FALSE END)
              THEN
                RAISE EXCEPTION 'media GC plan requires a canonical narration audio path and MIME';
              END IF;
              IF media_row.state='staging' AND NOT (
                   NEW.reason_code='staging_orphan'
                   AND media_row.created_at<=clock_timestamp()-interval '24 hours'
                 )
              THEN
                RAISE EXCEPTION 'staging GC plan requires the server-side orphan grace';
              END IF;
              IF media_row.state='ready' AND NOT (
                   NEW.reason_code='unreferenced_derivative_after_grace'
                   AND media_row.asset_class IN
                     ('preview','segment_master','segment_playback','export')
                   AND media_row.gc_marked_at IS NOT NULL
                   AND media_row.gc_marked_at<=clock_timestamp()-interval '7 days'
                 )
              THEN
                RAISE EXCEPTION 'ready GC plan requires a marked derivative after grace';
              END IF;
              IF media_row.state='ready' AND NEW.file_present IS NOT TRUE THEN
                RAISE EXCEPTION 'ready media GC plan requires a present inode';
              END IF;
              IF (
                media_row.owner_id, media_row.workspace_id, media_row.novel_id,
                media_row.storage_backend, media_row.storage_path,
                media_row.content_hash, media_row.byte_size, media_row.gc_generation
              ) IS DISTINCT FROM (
                NEW.owner_id, NEW.workspace_id, NEW.novel_id,
                NEW.storage_backend, NEW.storage_path,
                NEW.content_hash, NEW.byte_size, NEW.generation
              ) THEN
                RAISE EXCEPTION 'media GC plan does not match canonical asset identity';
              END IF;
              IF narration_media_has_live_reference(NEW.asset_id) THEN
                RAISE EXCEPTION 'referenced media cannot enter a GC deletion plan';
              END IF;
              IF (SELECT count(*) FROM media_assets m
                  WHERE m.storage_backend=NEW.storage_backend
                    AND m.storage_path=NEW.storage_path) <> 1
              THEN
                RAISE EXCEPTION 'media GC plan requires exactly one physical blob owner';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _require_clean_forward_boundary()
    op.drop_constraint(
        "ck_media_asset_narration_canonical_path", "media_assets", type_="check"
    )
    op.create_check_constraint(
        "ck_media_asset_narration_canonical_path",
        "media_assets",
        "asset_class IS NULL OR storage_backend <> 'local' OR "
        "(content_hash ~ '^[0-9a-f]{64}$' AND storage_path ~ "
        "('^assets/' || substr(replace(id::text,'-',''),1,2) || '/' || "
        "replace(id::text,'-','') || '/' || content_hash || "
        "'\\.(aac|flac|m4a|mp3|ogg|opus|wav)$'))",
    )
    _replace_gc_plan_guard(asset_scoped=True)


def downgrade() -> None:
    _require_clean_downgrade_boundary()
    _replace_gc_plan_guard(asset_scoped=False)
    op.drop_constraint(
        "ck_media_asset_narration_canonical_path", "media_assets", type_="check"
    )
    op.create_check_constraint(
        "ck_media_asset_narration_canonical_path",
        "media_assets",
        "asset_class IS NULL OR storage_backend <> 'local' OR "
        "(content_hash ~ '^[0-9a-f]{64}$' AND storage_path ~ "
        "('^assets/' || substr(content_hash,1,2) || '/' || content_hash || "
        "'\\.(aac|flac|m4a|mp3|ogg|opus|wav)$'))",
    )
