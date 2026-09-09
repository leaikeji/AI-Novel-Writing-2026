"""Register the Qwen TTS execution resource for new segment jobs.

Revision ID: 20260908_0043
Revises: 20260905_0042

Historical jobs and resource leases are intentionally left unchanged. Only
new ``narration.segment_render`` jobs are rebound to the Qwen resource class.
"""

from alembic import op


revision = "20260908_0043"
down_revision = "20260905_0042"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DROP TRIGGER trg_background_resource_policy_immutable "
        "ON background_resource_class_policies"
    )
    op.execute(
        "DROP TRIGGER trg_background_resource_slot_immutable "
        "ON background_resource_class_slots"
    )
    op.execute(
        "DROP TRIGGER trg_background_job_kind_policy_immutable "
        "ON background_job_kind_policies"
    )
    try:
        op.execute(
            """
            INSERT INTO background_resource_class_policies
              (resource_class, requires_publish_fence, exact_resource_key,
               max_concurrency, version, created_actor, created_at)
            VALUES
              ('qwen-tts', true, 'qwen-tts:inference', 1, 1,
               'migration:20260908_0043', clock_timestamp())
            ON CONFLICT (resource_class) DO NOTHING
            """
        )
        op.execute(
            """
            INSERT INTO background_resource_class_slots
              (resource_class, slot_number, resource_key, enabled, created_at)
            VALUES
              ('qwen-tts', 0, 'qwen-tts:inference', true, clock_timestamp())
            ON CONFLICT (resource_class, slot_number) DO NOTHING
            """
        )
        op.execute(
            """
            UPDATE background_job_kind_policies
               SET resource_class='qwen-tts',
                   version=version+1,
                   created_actor='migration:20260908_0043',
                   created_at=clock_timestamp()
             WHERE job_kind='narration.segment_render'
               AND resource_class<>'qwen-tts'
            """
        )
    finally:
        op.execute(
            "CREATE TRIGGER trg_background_resource_policy_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE ON "
            "background_resource_class_policies FOR EACH ROW EXECUTE FUNCTION "
            "narration_reject_registry_mutation()"
        )
        op.execute(
            "CREATE TRIGGER trg_background_resource_slot_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE ON "
            "background_resource_class_slots FOR EACH ROW EXECUTE FUNCTION "
            "narration_reject_registry_mutation()"
        )
        op.execute(
            "CREATE TRIGGER trg_background_job_kind_policy_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE ON "
            "background_job_kind_policies FOR EACH ROW EXECUTE FUNCTION "
            "narration_reject_registry_mutation()"
        )


def downgrade():
    raise RuntimeError(
        "Qwen TTS resource migration is forward-only; do not reactivate MOSS"
    )
