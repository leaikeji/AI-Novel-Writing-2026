"""Permit cancelled model-run evidence at the live cancel-request fence.

Revision ID: 20260827_0019
Revises: 20260827_0018

The worker must append one audit row before acknowledging cancellation.  That
short transaction observes ``background_jobs.state='cancel_requested'`` while
the exact attempt, executor epoch, and resource lease are still live.  Other
result classifications continue to require ``running``.
"""

from alembic import op


revision = "20260827_0019"
down_revision = "20260827_0018"
branch_labels = None
depends_on = None


def _function_sql(*, permit_cancel_requested: bool) -> str:
    state_guard = (
        "NOT ((job_state='running' AND NEW.result_classification<>'cancelled') "
        "OR (job_state='cancel_requested' AND "
        "NEW.result_classification='cancelled'))"
        if permit_cancel_requested
        else "job_state<>'running'"
    )
    return f"""
        CREATE OR REPLACE FUNCTION narration_guard_model_run_execution_fence()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target_job_id uuid; job_state text;
                attempt_row background_job_attempts%ROWTYPE;
                epoch_state text; lock_row background_resource_locks%ROWTYPE;
                db_now timestamptz := clock_timestamp();
        BEGIN
          IF NEW.created_at<db_now-interval '5 seconds'
             OR NEW.created_at>db_now+interval '1 second'
          THEN
            RAISE EXCEPTION 'model run record requires the authoritative database clock';
          END IF;
          SELECT a.job_id INTO target_job_id FROM background_job_attempts a
          WHERE a.id=NEW.attempt_id;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'model run record requires an existing attempt';
          END IF;
          SELECT state INTO job_state FROM background_jobs
          WHERE id=target_job_id FOR UPDATE;
          SELECT * INTO attempt_row FROM background_job_attempts
          WHERE id=NEW.attempt_id AND job_id=target_job_id FOR UPDATE;
          IF NOT FOUND OR {state_guard}
             OR attempt_row.completed_at IS NOT NULL
             OR attempt_row.lease_until<=db_now
          THEN
            RAISE EXCEPTION 'model run record requires the live current attempt';
          END IF;
          SELECT state INTO epoch_state FROM background_executor_epochs
          WHERE id=attempt_row.executor_epoch_id FOR KEY SHARE;
          IF NOT FOUND OR epoch_state<>'active' THEN
            RAISE EXCEPTION 'model run record requires an active executor epoch';
          END IF;
          SELECT * INTO lock_row FROM background_resource_locks
          WHERE resource_key=attempt_row.resource_key FOR UPDATE;
          IF NOT FOUND OR
             (lock_row.resource_key,lock_row.lease_owner,lock_row.lease_token,
              lock_row.lease_generation) IS DISTINCT FROM
             (attempt_row.resource_key,attempt_row.lease_owner,
              attempt_row.resource_lease_token,
              attempt_row.resource_lease_generation) OR
             lock_row.lease_until<=db_now
          THEN
            RAISE EXCEPTION 'model run record requires the attempt resource fence';
          END IF;
          RETURN NEW;
        END $$;
    """


def upgrade() -> None:
    op.execute(_function_sql(permit_cancel_requested=True))


def downgrade() -> None:
    op.execute(_function_sql(permit_cancel_requested=False))
