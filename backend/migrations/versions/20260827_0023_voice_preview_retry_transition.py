"""Allow a running voice preview while its failed job is re-queued.

Revision ID: 20260827_0023
Revises: 20260827_0022

The voice preview is one user-visible execution spanning all bounded worker
attempts.  After an attempt fails, the job legitimately transitions from
``retry_wait`` back to ``queued`` while the preview remains ``running``.  The
0021 deferred closure omitted that one transition and therefore rolled back
normal retry promotion.  No existing preview, job, or media evidence is
rewritten by this migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0023"
down_revision = "20260827_0022"
branch_labels = None
depends_on = None


def _install_job_closure(*, allow_running_queued: bool) -> None:
    running_states = (
        "'queued','running','retry_wait','cancel_requested'"
        if allow_running_queued
        else "'running','retry_wait','cancel_requested'"
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_voice_preview_job_closure_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE job_row background_jobs%ROWTYPE;
            BEGIN
              SELECT * INTO job_row FROM background_jobs WHERE id=NEW.id;
              IF NOT FOUND OR job_row.job_kind<>'narration.voice_preview' THEN
                RETURN NULL;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM voice_previews p
                WHERE p.job_id=job_row.id
                  AND (p.owner_id,p.workspace_id,p.novel_id) IS NOT DISTINCT FROM
                      (job_row.owner_id,job_row.workspace_id,job_row.novel_id)
                  AND (
                    (p.status='queued' AND job_row.state IN
                      ('queued','running','retry_wait','cancel_requested')) OR
                    (p.status='running' AND job_row.state IN
                      ({running_states})) OR
                    (p.status='ready' AND job_row.state='succeeded') OR
                    (p.status='failed' AND job_row.state IN
                      ('failed','dead_letter')) OR
                    (p.status='cancelled' AND job_row.state='cancelled')
                  )
              ) THEN
                RAISE EXCEPTION 'voice preview job requires one coherent preview record';
              END IF;
              RETURN NULL;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _install_job_closure(allow_running_queued=True)


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1
                FROM voice_previews p
                JOIN background_jobs j ON j.id=p.job_id
                WHERE p.status='running'
                  AND j.job_kind='narration.voice_preview'
                  AND j.state='queued'
              ) THEN
                RAISE EXCEPTION
                  'T4 voice preview retry downgrade refused: running queued retry exists';
              END IF;
            END $$;
            """
        )
    )
    _install_job_closure(allow_running_queued=False)
