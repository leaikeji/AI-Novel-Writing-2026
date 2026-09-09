"""Correct the Qwen official-voice provenance revision key.

Revision ID: 20260909_0046
Revises: 20260909_0045
"""

from alembic import op


revision = "20260909_0046"
down_revision = "20260909_0045"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        DO $migration$
        DECLARE
          function_definition text;
          old_fragment text :=
            'version.parameters_json->''official_preset''->>''model_revision''=';
          new_fragment text :=
            'version.parameters_json->''official_preset''->>''local_model_revision''=';
        BEGIN
          SELECT pg_get_functiondef(
            'narration_check_official_voice_action_closure_v1()'::regprocedure
          ) INTO function_definition;
          IF position(old_fragment IN function_definition)=0 THEN
            RAISE EXCEPTION
              'Qwen official voice closure does not contain the expected revision key';
          END IF;
          EXECUTE replace(function_definition, old_fragment, new_fragment);
        END
        $migration$;
        """
    )


def downgrade():
    raise RuntimeError(
        "Qwen provenance correction is forward-only; do not restore a false guard"
    )
