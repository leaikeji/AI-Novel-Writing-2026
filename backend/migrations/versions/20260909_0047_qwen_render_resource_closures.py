"""Move active narration render closures to the Qwen resource class.

Revision ID: 20260909_0047
Revises: 20260909_0046
"""

from alembic import op


revision = "20260909_0047"
down_revision = "20260909_0046"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        DO $migration$
        DECLARE
          function_name text;
          function_definition text;
          old_fragment text := 'j.resource_class=''moss-nano''';
          new_fragment text := 'j.resource_class=''qwen-tts''';
        BEGIN
          FOREACH function_name IN ARRAY ARRAY[
            'narration_guard_ready_render_assets()',
            'narration_failed_segment_retry_authorized_v1(uuid,uuid,uuid,uuid,uuid)'
          ] LOOP
            SELECT pg_get_functiondef(function_name::regprocedure)
              INTO function_definition;
            IF position(old_fragment IN function_definition)=0 THEN
              RAISE EXCEPTION
                'narration closure % does not contain the expected MOSS resource class',
                function_name;
            END IF;
            IF position(new_fragment IN function_definition)>0 THEN
              RAISE EXCEPTION
                'narration closure % already contains the Qwen resource class',
                function_name;
            END IF;
            EXECUTE replace(function_definition, old_fragment, new_fragment);
          END LOOP;
        END
        $migration$;
        """
    )


def downgrade():
    raise RuntimeError(
        "Qwen render closure migration is forward-only; do not restore MOSS routing"
    )
