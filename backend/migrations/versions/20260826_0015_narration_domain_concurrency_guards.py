"""Serialize narration aggregate decisions against concurrent child writes.

Revision ID: 20260826_0015
Revises: 20260826_0014

This fix-forward migration adds only row-locking trigger guards.  It performs
no data rewrite and no filesystem or network I/O.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_0015"
down_revision = "20260826_0014"
branch_labels = None
depends_on = None


def _install_serialized_script_child_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_approved_child()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              old_parent_id uuid;
              new_parent_id uuid;
              locked_parent record;
            BEGIN
              old_parent_id := CASE
                WHEN TG_OP IN ('UPDATE','DELETE') THEN OLD.script_version_id
                ELSE NULL
              END;
              new_parent_id := CASE
                WHEN TG_OP IN ('INSERT','UPDATE') THEN NEW.script_version_id
                ELSE NULL
              END;

              FOR locked_parent IN
                SELECT sv.id, sv.state
                FROM narration_script_versions sv
                WHERE sv.id=old_parent_id OR sv.id=new_parent_id
                ORDER BY sv.id
                FOR UPDATE
              LOOP
                IF locked_parent.state='approved' THEN
                  RAISE EXCEPTION 'approved narration script children are immutable';
                END IF;
              END LOOP;
              RETURN COALESCE(NEW,OLD);
            END $$;
            """
        )
    )


def _restore_0010_script_child_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_approved_child()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE parent_id uuid;
            BEGIN
              parent_id := CASE
                WHEN TG_OP='DELETE' THEN OLD.script_version_id
                ELSE NEW.script_version_id
              END;
              IF EXISTS (
                SELECT 1 FROM narration_script_versions
                WHERE id=parent_id AND state='approved'
              )
              THEN
                RAISE EXCEPTION 'approved narration script children are immutable';
              END IF;
              IF TG_OP='UPDATE' AND EXISTS (
                SELECT 1 FROM narration_script_versions
                WHERE id=OLD.script_version_id AND state='approved'
              )
              THEN
                RAISE EXCEPTION 'approved narration script children are immutable';
              END IF;
              RETURN COALESCE(NEW,OLD);
            END $$;
            """
        )
    )


def upgrade() -> None:
    _install_serialized_script_child_guard()
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_lock_settings_aggregate()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              old_novel_id uuid;
              new_novel_id uuid;
              locked_novel_id uuid;
            BEGIN
              old_novel_id := CASE
                WHEN TG_OP IN ('UPDATE','DELETE') THEN OLD.novel_id
                ELSE NULL
              END;
              new_novel_id := CASE
                WHEN TG_OP IN ('INSERT','UPDATE') THEN NEW.novel_id
                ELSE NULL
              END;
              FOR locked_novel_id IN
                SELECT n.id
                FROM novels n
                WHERE n.id=old_novel_id OR n.id=new_novel_id
                ORDER BY n.id
                FOR UPDATE
              LOOP
                NULL;
              END LOOP;
              RETURN COALESCE(NEW,OLD);
            END $$;

            CREATE TRIGGER trg_t1_narration_settings_aggregate_lock
            BEFORE INSERT OR UPDATE OR DELETE ON novel_narration_settings
            FOR EACH ROW EXECUTE FUNCTION narration_lock_settings_aggregate();

            CREATE TRIGGER trg_t1_narration_override_aggregate_lock
            BEFORE INSERT OR UPDATE OR DELETE ON narration_scope_overrides
            FOR EACH ROW EXECUTE FUNCTION narration_lock_settings_aggregate();

            CREATE FUNCTION narration_lock_voice_rights_aggregate()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE
              old_rights_id uuid;
              new_rights_id uuid;
              locked_rights_id uuid;
            BEGIN
              old_rights_id := CASE
                WHEN TG_OP IN ('UPDATE','DELETE') THEN OLD.rights_record_id
                ELSE NULL
              END;
              new_rights_id := CASE
                WHEN TG_OP IN ('INSERT','UPDATE') THEN NEW.rights_record_id
                ELSE NULL
              END;
              FOR locked_rights_id IN
                SELECT rr.id
                FROM voice_rights_records rr
                WHERE rr.id=old_rights_id OR rr.id=new_rights_id
                ORDER BY rr.id
                FOR UPDATE
              LOOP
                NULL;
              END LOOP;
              RETURN COALESCE(NEW,OLD);
            END $$;

            CREATE TRIGGER trg_t1_voice_rights_aggregate_lock
            BEFORE INSERT OR UPDATE OR DELETE ON voice_rights_events
            FOR EACH ROW EXECUTE FUNCTION narration_lock_voice_rights_aggregate();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_t1_voice_rights_aggregate_lock
              ON voice_rights_events;
            DROP FUNCTION narration_lock_voice_rights_aggregate();
            DROP TRIGGER trg_t1_narration_override_aggregate_lock
              ON narration_scope_overrides;
            DROP TRIGGER trg_t1_narration_settings_aggregate_lock
              ON novel_narration_settings;
            DROP FUNCTION narration_lock_settings_aggregate();
            """
        )
    )
    _restore_0010_script_child_guard()
