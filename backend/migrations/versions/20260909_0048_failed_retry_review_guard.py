"""Keep the review-action guard out of authorized failed-render retries.

Revision ID: 20260909_0048
Revises: 20260909_0047
"""

from alembic import op


revision = "20260909_0048"
down_revision = "20260909_0047"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        DO $migration$
        DECLARE
          function_definition text;
          old_fragment text :=
            'IF OLD.state IS DISTINCT FROM ''queued'' AND NEW.state=''queued'' THEN';
          new_fragment text :=
            'IF OLD.state IN (''analyzed'',''review_required'') AND NEW.state=''queued'' THEN';
        BEGIN
          SELECT pg_get_functiondef(
            'narration_require_review_action()'::regprocedure
          ) INTO function_definition;
          IF position(old_fragment IN function_definition)=0 THEN
            RAISE EXCEPTION
              'review-action guard does not contain the expected first-queue condition';
          END IF;
          IF position(new_fragment IN function_definition)>0 THEN
            RAISE EXCEPTION
              'review-action guard already contains the retry-compatible condition';
          END IF;
          EXECUTE replace(function_definition, old_fragment, new_fragment);
        END
        $migration$;
        """
    )


def downgrade():
    raise RuntimeError(
        "failed-render retry guard migration is forward-only; do not restore the conflicting review guard"
    )
