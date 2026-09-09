"""Remove retired pool/slot branches from the shared narration scope guard.

Revision ID: 20260909_0050
Revises: 20260909_0049

0049 removed the retired tables and columns, but the shared trigger function
still contained static SQL against those tables.  PostgreSQL prepares the
function expression on an unrelated voice-profile insert, so the stale branch
made new Qwen narrator creation fail.  This fix-forward migration rewrites only
the five frozen retired fragments and refuses an unexpected function body.
"""

from alembic import op


revision = "20260909_0050"
down_revision = "20260909_0049"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
        DO $plan62$
        DECLARE
          function_definition text;
          old_generic_slot text := $old_generic_slot$
      IF TG_TABLE_NAME='generic_voice_slots' AND NOT EXISTS
        (SELECT 1 FROM generic_voice_pools gp JOIN voice_profile_versions vv ON vv.id=(row_data->>'voice_version_id')::uuid
         JOIN voice_profiles vp ON vp.id=vv.profile_id WHERE gp.id=(row_data->>'pool_id')::uuid
           AND (vp.novel_id IS NULL OR vp.novel_id=gp.novel_id))
      THEN RAISE EXCEPTION 'generic voice slot scope mismatch'; END IF;
$old_generic_slot$;
          old_anonymous_slot text := $old_anonymous_slot$
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'slot_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
         WHERE gs.id=(row_data->>'slot_id')::uuid AND gp.novel_id=(row_data->>'novel_id')::uuid)
      THEN RAISE EXCEPTION 'anonymous voice slot novel mismatch'; END IF;
$old_anonymous_slot$;
          old_anonymous_match text := $old_anonymous_match$
      IF TG_TABLE_NAME='anonymous_speakers' AND row_data->>'slot_id' IS NOT NULL
         AND row_data->>'voice_version_id' IS NOT NULL AND NOT EXISTS
        (SELECT 1 FROM generic_voice_slots gs WHERE gs.id=(row_data->>'slot_id')::uuid
         AND gs.voice_version_id=(row_data->>'voice_version_id')::uuid)
      THEN RAISE EXCEPTION 'anonymous slot and voice version mismatch'; END IF;
$old_anonymous_match$;
          old_casting_target text := $old_casting_target$
      IF TG_TABLE_NAME='voice_casting_rules' AND
        ((row_data->>'target_slot_id' IS NOT NULL AND row_data->>'target_pool_id' IS NULL) OR
         (row_data->>'target_pool_id' IS NOT NULL AND NOT EXISTS
           (SELECT 1 FROM generic_voice_pools gp WHERE gp.id=(row_data->>'target_pool_id')::uuid
            AND gp.novel_id=(row_data->>'novel_id')::uuid)) OR
         (row_data->>'target_slot_id' IS NOT NULL AND NOT EXISTS
           (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
            WHERE gs.id=(row_data->>'target_slot_id')::uuid AND gs.pool_id=(row_data->>'target_pool_id')::uuid
              AND gp.novel_id=(row_data->>'novel_id')::uuid)))
      THEN RAISE EXCEPTION 'voice casting target scope mismatch'; END IF;
$old_casting_target$;
          old_edition_slot text := $old_edition_slot$
           AND ((row_data->>'slot_id') IS NULL OR EXISTS
             (SELECT 1 FROM generic_voice_slots gs JOIN generic_voice_pools gp ON gp.id=gs.pool_id
              WHERE gs.id=(row_data->>'slot_id')::uuid AND gs.voice_version_id=vv.id AND gp.novel_id=e.novel_id)))
$old_edition_slot$;
          rewritten text;
        BEGIN
          SELECT pg_get_functiondef(
            'narration_validate_scope()'::regprocedure
          ) INTO function_definition;
          rewritten := function_definition;

          IF position(trim(both E'\n' from old_generic_slot) IN rewritten)=0
             OR position(trim(both E'\n' from old_anonymous_slot) IN rewritten)=0
             OR position(trim(both E'\n' from old_anonymous_match) IN rewritten)=0
             OR position(trim(both E'\n' from old_casting_target) IN rewritten)=0
             OR position(trim(both E'\n' from old_edition_slot) IN rewritten)=0
          THEN
            RAISE EXCEPTION 'plan62_scope_guard_shape_changed';
          END IF;

          rewritten := replace(
            rewritten, trim(both E'\n' from old_generic_slot), ''
          );
          rewritten := replace(
            rewritten, trim(both E'\n' from old_anonymous_slot), ''
          );
          rewritten := replace(
            rewritten, trim(both E'\n' from old_anonymous_match), ''
          );
          rewritten := replace(
            rewritten, trim(both E'\n' from old_casting_target), ''
          );
          rewritten := replace(
            rewritten, trim(both E'\n' from old_edition_slot), '           )'
          );

          IF position('generic_voice_pools' IN rewritten)>0
             OR position('generic_voice_slots' IN rewritten)>0
             OR position('target_pool_id' IN rewritten)>0
             OR position('target_slot_id' IN rewritten)>0
          THEN
            RAISE EXCEPTION
              'plan62_scope_guard_retired_reference_remains pools=% slots=% target_pool=% target_slot=%',
              (length(rewritten)-length(replace(rewritten, 'generic_voice_pools', '')))/length('generic_voice_pools'),
              (length(rewritten)-length(replace(rewritten, 'generic_voice_slots', '')))/length('generic_voice_slots'),
              (length(rewritten)-length(replace(rewritten, 'target_pool_id', '')))/length('target_pool_id'),
              (length(rewritten)-length(replace(rewritten, 'target_slot_id', '')))/length('target_slot_id');
          END IF;
          EXECUTE rewritten;
        END
        $plan62$;
        """
    )


def downgrade():
    raise RuntimeError(
        "retired scope guard cleanup is forward-only; do not restore references to removed tables"
    )
