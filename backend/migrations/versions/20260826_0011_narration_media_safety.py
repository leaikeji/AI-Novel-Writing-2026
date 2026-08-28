"""Harden narration media ownership, references, and recoverable GC.

Revision ID: 20260826_0011
Revises: 20260826_0010

This is a PostgreSQL-only, frozen migration.  It performs no filesystem or
network I/O.  Existing ambiguity fails preflight instead of being silently
deduplicated because choosing a physical blob owner is a product/data decision.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260826_0011"
down_revision = "20260826_0010"
branch_labels = None
depends_on = None


LOCAL_OWNER = "29cf94d9-a5c9-54ec-912c-5dfff8738c4c"
LOCAL_WORKSPACE = "f0e2e632-bc99-52d2-9916-bb906aa4da6e"


def _preflight() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM media_assets
                GROUP BY storage_backend, storage_path HAVING count(*) > 1
              ) THEN
                RAISE EXCEPTION
                  'T1-E preflight: duplicate physical media owners; audit and fix forward';
              END IF;
              IF EXISTS (
                SELECT 1 FROM media_assets
                WHERE octet_length(storage_path) NOT BETWEEN 1 AND 1024
              ) THEN
                RAISE EXCEPTION
                  'T1-E preflight: media storage_path exceeds bounded unique-key contract';
              END IF;
              IF EXISTS (
                SELECT 1 FROM novels n JOIN media_assets m ON m.id=n.cover_asset_id
                WHERE n.cover_asset_id IS NOT NULL AND m.state <> 'ready'
                UNION ALL
                SELECT 1 FROM narration_render_assets r
                  JOIN media_assets m ON m.id=r.asset_id WHERE m.state <> 'ready'
                UNION ALL
                SELECT 1 FROM narration_exports e
                  JOIN media_assets m ON m.id=e.asset_id WHERE m.state <> 'ready'
                UNION ALL
                SELECT 1 FROM voice_profile_versions v
                  JOIN media_assets m ON m.id=v.reference_asset_id
                  WHERE v.reference_asset_id IS NOT NULL AND m.state <> 'ready'
                UNION ALL
                SELECT 1 FROM voice_profile_versions v
                  JOIN media_assets m ON m.id=v.preview_asset_id
                  WHERE v.preview_asset_id IS NOT NULL AND m.state <> 'ready'
              ) THEN
                RAISE EXCEPTION
                  'T1-E preflight: an existing structured reference targets non-ready media';
              END IF;
            END $$;
            """
        )
    )


def _create_tables_and_constraints() -> None:
    op.create_check_constraint(
        "ck_media_asset_storage_path_length",
        "media_assets",
        "octet_length(storage_path) BETWEEN 1 AND 1024",
    )
    op.create_unique_constraint(
        "uq_media_asset_physical_blob",
        "media_assets",
        ["storage_backend", "storage_path"],
    )
    op.create_unique_constraint(
        "uq_media_asset_job_scope",
        "media_assets",
        ["id", "owner_id", "workspace_id", "novel_id"],
    )
    op.create_unique_constraint(
        "uq_background_job_media_scope",
        "background_jobs",
        ["id", "owner_id", "workspace_id", "novel_id"],
    )

    op.create_table(
        "active_job_assets",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["job_id", "owner_id", "workspace_id", "novel_id"],
            ["background_jobs.id", "background_jobs.owner_id", "background_jobs.workspace_id", "background_jobs.novel_id"],
            name="fk_active_job_asset_job_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id", "novel_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id", "media_assets.novel_id"],
            name="fk_active_job_asset_media_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role IN ('input','working','output','checkpoint')",
            name="ck_active_job_asset_role",
        ),
        sa.CheckConstraint(
            "released_at IS NULL OR released_at >= acquired_at",
            name="ck_active_job_asset_lifecycle",
        ),
    )
    op.create_index(
        "ix_active_job_assets_unreleased",
        "active_job_assets",
        ["asset_id", "released_at"],
    )

    op.create_table(
        "media_gc_deletion_plans",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_backend", sa.String(40), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("file_present", sa.Boolean(), nullable=False),
        sa.Column("device", sa.BigInteger()),
        sa.Column("inode", sa.BigInteger()),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id", "owner_id", "workspace_id", "novel_id"],
            ["media_assets.id", "media_assets.owner_id", "media_assets.workspace_id", "media_assets.novel_id"],
            name="fk_media_gc_plan_asset_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "asset_id", "generation", name="uq_media_gc_plan_generation"
        ),
        sa.CheckConstraint("generation >= 0", name="ck_media_gc_plan_generation"),
        sa.CheckConstraint("byte_size >= 0", name="ck_media_gc_plan_byte_size"),
        sa.CheckConstraint(
            "(file_present IS TRUE AND device IS NOT NULL AND inode IS NOT NULL) OR "
            "(file_present IS FALSE AND device IS NULL AND inode IS NULL)",
            name="ck_media_gc_plan_file_identity",
        ),
        sa.CheckConstraint(
            "octet_length(storage_path) BETWEEN 1 AND 1024",
            name="ck_media_gc_plan_storage_path_length",
        ),
    )


def _create_functions_and_triggers() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_media_has_live_reference(p_asset_id uuid)
            RETURNS boolean LANGUAGE sql STABLE AS $$
              SELECT
                EXISTS (SELECT 1 FROM novels n WHERE n.cover_asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_render_assets r WHERE r.asset_id=p_asset_id)
                OR EXISTS (SELECT 1 FROM narration_exports e WHERE e.asset_id=p_asset_id)
                OR EXISTS (
                  SELECT 1 FROM voice_profile_versions v
                  WHERE v.reference_asset_id=p_asset_id OR v.preview_asset_id=p_asset_id
                )
                OR EXISTS (
                  SELECT 1 FROM active_job_assets a
                  WHERE a.asset_id=p_asset_id AND a.released_at IS NULL
                )
                OR EXISTS (
                  SELECT 1 FROM narration_manifest_segments ms
                  JOIN narration_render_assets ra ON ra.render_id=ms.render_id
                  WHERE ra.asset_id=p_asset_id
                );
            $$;

            CREATE FUNCTION narration_guard_ready_media_reference()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              column_name text;
              referenced_id uuid;
              referenced_state text;
            BEGIN
              FOREACH column_name IN ARRAY TG_ARGV LOOP
                referenced_id := NULLIF(to_jsonb(NEW)->>column_name, '')::uuid;
                IF referenced_id IS NOT NULL THEN
                  SELECT m.state INTO referenced_state
                  FROM media_assets m WHERE m.id=referenced_id FOR UPDATE;
                  IF NOT FOUND OR referenced_state <> 'ready' THEN
                    RAISE EXCEPTION
                      'media reference requires an existing ready asset (%=%)',
                      column_name, referenced_id;
                  END IF;
                END IF;
              END LOOP;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_active_job_asset()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE job_state text;
            BEGIN
              IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'active job asset rows are append-only';
              END IF;
              IF TG_OP='UPDATE' THEN
                IF (to_jsonb(OLD)-'released_at') <> (to_jsonb(NEW)-'released_at')
                   OR OLD.released_at IS NOT NULL OR NEW.released_at IS NULL
                THEN
                  RAISE EXCEPTION 'active job asset only permits one-way release';
                END IF;
                RETURN NEW;
              END IF;
              SELECT j.state INTO job_state FROM background_jobs j
              WHERE j.id=NEW.job_id FOR UPDATE;
              IF NOT FOUND OR job_state NOT IN
                ('queued','running','retry_wait','cancel_requested')
              THEN
                RAISE EXCEPTION 'active job asset requires a non-terminal job';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_terminal_job_assets()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.state IN ('succeeded','failed','dead_letter','cancelled')
                 AND EXISTS (
                   SELECT 1 FROM active_job_assets a
                   WHERE a.job_id=NEW.id AND a.released_at IS NULL
                 )
              THEN
                RAISE EXCEPTION 'terminal job must release all active media assets';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_media_gc_plan()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE media_row media_assets%ROWTYPE;
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'media GC deletion plan is immutable';
              END IF;
              SELECT * INTO media_row FROM media_assets m
              WHERE m.id=NEW.asset_id FOR UPDATE;
              IF NOT FOUND OR media_row.state <> 'ready' THEN
                RAISE EXCEPTION 'media GC plan requires a ready locked asset';
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

            CREATE FUNCTION narration_guard_media_identity_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='DELETE' THEN
                IF OLD.asset_class IS NOT NULL OR OLD.state <> 'deleted' THEN
                  RAISE EXCEPTION 'narration/undeleted media rows cannot be deleted';
                END IF;
                RETURN OLD;
              END IF;
              IF OLD.state IN ('ready','quarantined','deleting','deleted') AND
                 (OLD.owner_id,OLD.workspace_id,OLD.novel_id,OLD.storage_backend,
                  OLD.storage_path,OLD.content_hash,OLD.byte_size,OLD.checksum_algorithm,
                  OLD.mime_type) IS DISTINCT FROM
                 (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                  NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.checksum_algorithm,
                  NEW.mime_type)
              THEN
                RAISE EXCEPTION 'published media physical identity is immutable';
              END IF;
              IF OLD.gc_generation <> NEW.gc_generation AND
                 NOT (OLD.state='ready' AND NEW.gc_generation=OLD.gc_generation+1
                      AND NEW.gc_marked_at IS NOT NULL)
              THEN
                RAISE EXCEPTION 'media GC generation may only advance by one while ready';
              END IF;
              IF OLD.state <> NEW.state AND NOT (
                (OLD.state='staging' AND NEW.state IN ('ready','quarantined','deleting')) OR
                (OLD.state='ready' AND NEW.state IN ('quarantined','deleting')) OR
                (OLD.state='quarantined' AND NEW.state='deleting') OR
                (OLD.state='deleting' AND NEW.state='deleted')
              ) THEN
                RAISE EXCEPTION 'invalid media state transition';
              END IF;
              IF NEW.state='deleting' AND OLD.state<>'deleting' AND
                 narration_media_has_live_reference(NEW.id)
              THEN
                RAISE EXCEPTION 'referenced media cannot transition to deleting';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_media_deleting_plan()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.state='deleting' AND NOT EXISTS (
                SELECT 1 FROM media_gc_deletion_plans p
                WHERE p.asset_id=NEW.id
                  AND (p.owner_id,p.workspace_id,p.novel_id,p.storage_backend,
                       p.storage_path,p.content_hash,p.byte_size,p.generation)
                      IS NOT DISTINCT FROM
                      (NEW.owner_id,NEW.workspace_id,NEW.novel_id,NEW.storage_backend,
                       NEW.storage_path,NEW.content_hash,NEW.byte_size,NEW.gc_generation)
              ) THEN
                RAISE EXCEPTION 'deleting media requires a matching durable GC plan';
              END IF;
              RETURN NEW;
            END $$;
            """
        )
    )

    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_novel_cover_ready "
        "BEFORE INSERT OR UPDATE OF cover_asset_id ON novels FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_ready_media_reference('cover_asset_id')"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_voice_assets_ready "
        "BEFORE INSERT OR UPDATE OF reference_asset_id,preview_asset_id ON voice_profile_versions "
        "FOR EACH ROW EXECUTE FUNCTION narration_guard_ready_media_reference("
        "'reference_asset_id','preview_asset_id')"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_render_asset_ready "
        "BEFORE INSERT OR UPDATE OF asset_id ON narration_render_assets FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_ready_media_reference('asset_id')"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_export_asset_ready "
        "BEFORE INSERT OR UPDATE OF asset_id ON narration_exports FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_ready_media_reference('asset_id')"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_active_job_asset_ready "
        "BEFORE INSERT OR UPDATE OF asset_id ON active_job_assets FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_ready_media_reference('asset_id')"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_active_job_asset_lifecycle "
        "BEFORE INSERT OR UPDATE OR DELETE ON active_job_assets FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_active_job_asset()"
    ))
    op.execute(sa.text(
        "CREATE CONSTRAINT TRIGGER trg_t1e_terminal_job_assets "
        "AFTER INSERT OR UPDATE ON background_jobs DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION narration_guard_terminal_job_assets()"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_media_gc_plan_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON media_gc_deletion_plans FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_media_gc_plan()"
    ))
    op.execute(sa.text(
        "CREATE TRIGGER trg_t1e_media_identity "
        "BEFORE UPDATE OR DELETE ON media_assets FOR EACH ROW "
        "EXECUTE FUNCTION narration_guard_media_identity_v2()"
    ))
    op.execute(sa.text(
        "CREATE CONSTRAINT TRIGGER trg_t1e_media_deleting_plan "
        "AFTER INSERT OR UPDATE ON media_assets DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION narration_guard_media_deleting_plan()"
    ))


def upgrade() -> None:
    _preflight()
    _create_tables_and_constraints()
    _create_functions_and_triggers()


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM active_job_assets)
                 OR EXISTS (SELECT 1 FROM media_gc_deletion_plans)
              THEN
                RAISE EXCEPTION
                  'T1-E downgrade refused: durable job/GC media evidence exists; fix forward';
              END IF;
            END $$;
            """
        )
    )
    for trigger, table in (
        ("trg_t1e_media_deleting_plan", "media_assets"),
        ("trg_t1e_media_identity", "media_assets"),
        ("trg_t1e_media_gc_plan_immutable", "media_gc_deletion_plans"),
        ("trg_t1e_terminal_job_assets", "background_jobs"),
        ("trg_t1e_active_job_asset_lifecycle", "active_job_assets"),
        ("trg_t1e_active_job_asset_ready", "active_job_assets"),
        ("trg_t1e_export_asset_ready", "narration_exports"),
        ("trg_t1e_render_asset_ready", "narration_render_assets"),
        ("trg_t1e_voice_assets_ready", "voice_profile_versions"),
        ("trg_t1e_novel_cover_ready", "novels"),
    ):
        op.execute(sa.text(f"DROP TRIGGER {trigger} ON {table}"))
    for function in (
        "narration_guard_media_deleting_plan()",
        "narration_guard_media_identity_v2()",
        "narration_guard_media_gc_plan()",
        "narration_guard_terminal_job_assets()",
        "narration_guard_active_job_asset()",
        "narration_guard_ready_media_reference()",
        "narration_media_has_live_reference(uuid)",
    ):
        op.execute(sa.text(f"DROP FUNCTION {function}"))
    op.drop_table("media_gc_deletion_plans")
    op.drop_index("ix_active_job_assets_unreleased", table_name="active_job_assets")
    op.drop_table("active_job_assets")
    op.drop_constraint(
        "uq_background_job_media_scope", "background_jobs", type_="unique"
    )
    op.drop_constraint("uq_media_asset_job_scope", "media_assets", type_="unique")
    op.drop_constraint("uq_media_asset_physical_blob", "media_assets", type_="unique")
    op.drop_constraint(
        "ck_media_asset_storage_path_length", "media_assets", type_="check"
    )
