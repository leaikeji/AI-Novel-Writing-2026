"""Seal the exact ordered source manifest of each narration request.

Revision ID: 20260826_0014
Revises: 20260826_0013

T1 is not product-visible yet, so this migration refuses to invent sealing
evidence for existing request rows.  It performs no filesystem or network I/O.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_0014"
down_revision = "20260826_0013"
branch_labels = None
depends_on = None


EMPTY_SOURCE_SET_HASH = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)


def _require_no_requests(*, operation: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM narration_requests) THEN
                RAISE EXCEPTION
                  'T1 request-source {operation} refused: existing requests require an audited source-manifest fix-forward';
              END IF;
            END $$;
            """
        )
    )


def _drop_source_guard_triggers() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_narration_request_sources_scope
              ON narration_request_sources;
            DROP TRIGGER trg_t1_request_source_closure_parent
              ON narration_requests;
            DROP TRIGGER trg_t1_request_source_closure_child
              ON narration_request_sources;
            """
        )
    )


def _install_sealed_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_validate_request_source_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE parent narration_requests%ROWTYPE;
            BEGIN
              IF TG_OP='DELETE' THEN
                SELECT * INTO parent FROM narration_requests r
                WHERE r.id=OLD.request_id FOR UPDATE;
                IF NOT FOUND THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed request source rows are immutable';
              END IF;
              SELECT * INTO parent FROM narration_requests r
              WHERE r.id=NEW.request_id FOR UPDATE;
              IF NOT FOUND OR parent.novel_id<>NEW.novel_id
                 OR parent.state<>'created'
                 OR parent.sources_sealed_at IS NOT NULL
                 OR NEW.position<0 OR NEW.position>=parent.source_count
                 OR NOT (
                   parent.intent='batch' OR
                   (parent.intent='analyze_only' AND parent.document_id IS NULL
                    AND parent.source_revision_id IS NULL
                    AND parent.source_content_hash IS NULL)
                 )
              THEN
                RAISE EXCEPTION
                  'request source requires an unsealed created multi-source request and a reserved position';
              END IF;
              IF TG_OP='UPDATE' THEN
                RAISE EXCEPTION 'request source rows are append-only before sealing';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_narration_request_sources_scope
            BEFORE INSERT OR UPDATE OR DELETE ON narration_request_sources
            FOR EACH ROW EXECUTE FUNCTION narration_validate_request_source_v2();

            CREATE OR REPLACE FUNCTION narration_guard_request_source_closure_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE request_id_value uuid; parent narration_requests%ROWTYPE;
                    actual_count integer; min_position integer; max_position integer;
            BEGIN
              IF TG_TABLE_NAME='narration_requests' THEN
                request_id_value := CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
              ELSE
                request_id_value := CASE
                  WHEN TG_OP='DELETE' THEN OLD.request_id ELSE NEW.request_id END;
              END IF;
              SELECT * INTO parent FROM narration_requests
              WHERE id=request_id_value;
              IF NOT FOUND THEN RETURN COALESCE(NEW,OLD); END IF;
              SELECT count(*),min(position),max(position)
                INTO actual_count,min_position,max_position
              FROM narration_request_sources WHERE request_id=request_id_value;
              IF parent.sources_sealed_at IS NULL THEN
                RAISE EXCEPTION 'narration request source manifest must be sealed before commit';
              END IF;
              IF actual_count<>parent.source_count OR
                 (actual_count>0 AND
                  (min_position<>0 OR max_position<>actual_count-1))
              THEN
                RAISE EXCEPTION 'sealed request source count/positions do not match the parent manifest';
              END IF;
              IF parent.document_id IS NOT NULL AND actual_count<>0 THEN
                RAISE EXCEPTION 'direct-source request cannot own source rows';
              END IF;
              IF parent.document_id IS NULL AND actual_count=0 THEN
                RAISE EXCEPTION 'multi-source request requires at least one sealed source';
              END IF;
              RETURN COALESCE(NEW,OLD);
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_parent
            AFTER INSERT OR UPDATE ON narration_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();
            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_child
            AFTER INSERT OR UPDATE OR DELETE ON narration_request_sources
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();

            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE actual_count integer; min_position integer; max_position integer;
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN
                  RAISE EXCEPTION 'narration request must be inserted in created state';
                END IF;
                IF NEW.document_id IS NOT NULL THEN
                  IF NEW.source_count<>0 OR
                     NEW.source_set_hash<>'4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'
                  THEN
                    RAISE EXCEPTION 'direct request must freeze the empty child-source manifest';
                  END IF;
                  NEW.sources_sealed_at := clock_timestamp();
                ELSIF NEW.sources_sealed_at IS NOT NULL THEN
                  RAISE EXCEPTION 'multi-source request must be sealed after its children are inserted';
                END IF;
                RETURN NEW;
              END IF;

              IF OLD.sources_sealed_at IS NULL AND NEW.sources_sealed_at IS NOT NULL THEN
                IF OLD.state<>'created' OR NEW.state<>'created' OR OLD.document_id IS NOT NULL OR
                   (to_jsonb(OLD)-ARRAY['sources_sealed_at','updated_at',
                                         'allows_edition','allows_render']) <>
                   (to_jsonb(NEW)-ARRAY['sources_sealed_at','updated_at',
                                         'allows_edition','allows_render'])
                THEN
                  RAISE EXCEPTION 'request source seal is the only allowed pre-state mutation';
                END IF;
                SELECT count(*),min(position),max(position)
                  INTO actual_count,min_position,max_position
                FROM narration_request_sources WHERE request_id=OLD.id;
                IF actual_count<>OLD.source_count OR actual_count=0 OR
                   min_position<>0 OR max_position<>actual_count-1
                THEN
                  RAISE EXCEPTION 'request source seal requires the complete reserved source set';
                END IF;
                NEW.sources_sealed_at := clock_timestamp();
                NEW.updated_at := clock_timestamp();
                RETURN NEW;
              END IF;

              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'])
              THEN RAISE EXCEPTION 'narration request canonical input is immutable'; END IF;
              IF OLD.sources_sealed_at IS NULL THEN
                RAISE EXCEPTION 'unsealed request cannot change lifecycle state';
              END IF;
              IF OLD.state='created' AND NEW.state='analyzing'
                 AND OLD.document_id IS NULL
                 AND NOT (
                   SELECT count(*)=OLD.source_count AND count(*)>0
                          AND min(position)=0 AND max(position)=count(*)-1
                   FROM narration_request_sources rs WHERE rs.request_id=OLD.id
                 )
              THEN
                RAISE EXCEPTION 'sealed multi-source manifest drifted before analysis';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='created' AND NEW.state IN ('analyzing','cancel_requested')) OR
                (OLD.state='analyzing' AND NEW.state IN
                  ('analyzed','review_required','queued','cancel_requested','failed')) OR
                (OLD.state='review_required' AND NEW.state IN
                  ('analyzing','queued','cancel_requested','failed')) OR
                (OLD.state='queued' AND NEW.state IN
                  ('rendering','cancel_requested','failed')) OR
                (OLD.state='rendering' AND NEW.state IN
                  ('partial_ready','ready','cancel_requested','failed')) OR
                (OLD.state='partial_ready' AND NEW.state IN
                  ('ready','cancel_requested','failed')) OR
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _install_0012_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_validate_request_source_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE parent narration_requests%ROWTYPE;
            BEGIN
              SELECT * INTO parent FROM narration_requests r
              WHERE r.id=NEW.request_id FOR UPDATE;
              IF NOT FOUND OR parent.novel_id<>NEW.novel_id
                 OR parent.state<>'created' OR NOT (
                   parent.intent='batch' OR
                   (parent.intent='analyze_only' AND parent.document_id IS NULL
                    AND parent.source_revision_id IS NULL
                    AND parent.source_content_hash IS NULL)
                 )
              THEN
                RAISE EXCEPTION
                  'request source requires a created batch or multi-source analyze-only request in the same novel';
              END IF;
              RETURN NEW;
            END $$;

            CREATE TRIGGER trg_narration_request_sources_scope
            BEFORE INSERT OR UPDATE ON narration_request_sources FOR EACH ROW
            EXECUTE FUNCTION narration_validate_request_source_v2();

            CREATE OR REPLACE FUNCTION narration_guard_request_source_closure_v2()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE request_id_value uuid; parent narration_requests%ROWTYPE;
                    source_count integer; min_position integer; max_position integer;
            BEGIN
              IF TG_TABLE_NAME='narration_requests' THEN
                request_id_value := (to_jsonb(NEW)->>'id')::uuid;
              ELSE
                request_id_value := (to_jsonb(NEW)->>'request_id')::uuid;
              END IF;
              SELECT * INTO parent FROM narration_requests
              WHERE id=request_id_value;
              IF NOT FOUND THEN RETURN NEW; END IF;
              SELECT count(*),min(position),max(position)
                INTO source_count,min_position,max_position
              FROM narration_request_sources WHERE request_id=request_id_value;
              IF source_count>0 AND
                 (min_position<>0 OR max_position<>source_count-1)
              THEN
                RAISE EXCEPTION 'request source positions must be contiguous from zero';
              END IF;
              IF parent.document_id IS NOT NULL AND source_count<>0 THEN
                RAISE EXCEPTION 'direct-source request cannot also own source rows';
              END IF;
              IF parent.document_id IS NULL AND parent.state<>'created'
                 AND source_count=0
              THEN
                RAISE EXCEPTION 'multi-source request requires at least one frozen source';
              END IF;
              RETURN NEW;
            END $$;
            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_parent
            AFTER INSERT OR UPDATE ON narration_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();
            CREATE CONSTRAINT TRIGGER trg_t1_request_source_closure_child
            AFTER INSERT OR UPDATE ON narration_request_sources
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_request_source_closure_v2();

            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN
                  RAISE EXCEPTION 'narration request must be inserted in created state';
                END IF;
                RETURN NEW;
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'])
              THEN RAISE EXCEPTION 'narration request canonical input is immutable'; END IF;
              IF OLD.state='created' AND NEW.state='analyzing'
                 AND OLD.intent IN ('batch','analyze_only')
                 AND OLD.document_id IS NULL
                 AND NOT (
                   SELECT count(*)>0 AND min(position)=0
                          AND max(position)=count(*)-1
                   FROM narration_request_sources rs WHERE rs.request_id=OLD.id
                 )
              THEN
                RAISE EXCEPTION 'multi-source request requires at least one frozen source before analysis';
              END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='created' AND NEW.state IN ('analyzing','cancel_requested')) OR
                (OLD.state='analyzing' AND NEW.state IN
                  ('analyzed','review_required','queued','cancel_requested','failed')) OR
                (OLD.state='review_required' AND NEW.state IN
                  ('analyzing','queued','cancel_requested','failed')) OR
                (OLD.state='queued' AND NEW.state IN
                  ('rendering','cancel_requested','failed')) OR
                (OLD.state='rendering' AND NEW.state IN
                  ('partial_ready','ready','cancel_requested','failed')) OR
                (OLD.state='partial_ready' AND NEW.state IN
                  ('ready','cancel_requested','failed')) OR
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _install_seal_aware_cas_guard() -> None:
    """Permit only the request seal transition to keep its business version."""
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_cas()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE old_data jsonb := to_jsonb(OLD); new_data jsonb := to_jsonb(NEW);
            BEGIN
              IF TG_TABLE_NAME='narration_requests'
                 AND old_data->>'sources_sealed_at' IS NULL
                 AND new_data->>'sources_sealed_at' IS NOT NULL
                 AND NEW.version=OLD.version
              THEN
                RETURN NEW;
              END IF;
              IF NEW.version<>OLD.version+1 THEN
                RAISE EXCEPTION 'narration CAS version must increment by one';
              END IF;
              IF TG_TABLE_NAME='novel_narration_settings' AND
                 (old_data->'id',old_data->'novel_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id')
              THEN RAISE EXCEPTION 'narration settings identity is immutable'; END IF;
              IF TG_TABLE_NAME='narration_scope_overrides' AND
                 (old_data->'id',old_data->'novel_id',old_data->'scope_kind',old_data->'scope_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id',new_data->'scope_kind',new_data->'scope_id')
              THEN RAISE EXCEPTION 'narration override identity is immutable'; END IF;
              IF TG_TABLE_NAME='voice_profiles' AND
                 (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'novel_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'novel_id')
              THEN RAISE EXCEPTION 'voice profile scope identity is immutable'; END IF;
              IF TG_TABLE_NAME='character_voice_bindings' AND
                 (old_data->'id',old_data->'novel_id',old_data->'character_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id',new_data->'character_id')
              THEN RAISE EXCEPTION 'character voice binding identity is immutable'; END IF;
              IF TG_TABLE_NAME='narration_edition_state' AND
                 old_data->'edition_id' IS DISTINCT FROM new_data->'edition_id'
              THEN RAISE EXCEPTION 'edition state identity is immutable'; END IF;
              IF TG_TABLE_NAME='document_narration_state' AND
                 (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'document_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'document_id')
              THEN RAISE EXCEPTION 'document narration state identity is immutable'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _restore_0010_cas_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION narration_guard_cas()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE old_data jsonb := to_jsonb(OLD); new_data jsonb := to_jsonb(NEW);
            BEGIN
              IF NEW.version<>OLD.version+1 THEN
                RAISE EXCEPTION 'narration CAS version must increment by one';
              END IF;
              IF TG_TABLE_NAME='novel_narration_settings' AND
                 (old_data->'id',old_data->'novel_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id')
              THEN RAISE EXCEPTION 'narration settings identity is immutable'; END IF;
              IF TG_TABLE_NAME='narration_scope_overrides' AND
                 (old_data->'id',old_data->'novel_id',old_data->'scope_kind',old_data->'scope_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id',new_data->'scope_kind',new_data->'scope_id')
              THEN RAISE EXCEPTION 'narration override identity is immutable'; END IF;
              IF TG_TABLE_NAME='voice_profiles' AND
                 (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'novel_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'novel_id')
              THEN RAISE EXCEPTION 'voice profile scope identity is immutable'; END IF;
              IF TG_TABLE_NAME='character_voice_bindings' AND
                 (old_data->'id',old_data->'novel_id',old_data->'character_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'novel_id',new_data->'character_id')
              THEN RAISE EXCEPTION 'character voice binding identity is immutable'; END IF;
              IF TG_TABLE_NAME='narration_edition_state' AND
                 old_data->'edition_id' IS DISTINCT FROM new_data->'edition_id'
              THEN RAISE EXCEPTION 'edition state identity is immutable'; END IF;
              IF TG_TABLE_NAME='document_narration_state' AND
                 (old_data->'id',old_data->'owner_id',old_data->'workspace_id',old_data->'document_id') IS DISTINCT FROM
                 (new_data->'id',new_data->'owner_id',new_data->'workspace_id',new_data->'document_id')
              THEN RAISE EXCEPTION 'document narration state identity is immutable'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _require_no_requests(operation="upgrade")
    op.add_column(
        "narration_requests", sa.Column("source_count", sa.Integer(), nullable=False)
    )
    op.add_column(
        "narration_requests", sa.Column("source_set_hash", sa.String(64), nullable=False)
    )
    op.add_column(
        "narration_requests",
        sa.Column("sources_sealed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_narration_request_source_count",
        "narration_requests",
        "source_count >= 0",
    )
    op.create_check_constraint(
        "ck_narration_request_source_set_hash",
        "narration_requests",
        "source_set_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_narration_request_source_manifest_shape",
        "narration_requests",
        "(document_id IS NOT NULL AND source_count=0 AND "
        f"source_set_hash='{EMPTY_SOURCE_SET_HASH}') OR "
        "(document_id IS NULL AND source_count>0)",
    )
    _drop_source_guard_triggers()
    _install_sealed_guards()
    _install_seal_aware_cas_guard()


def downgrade() -> None:
    _require_no_requests(operation="downgrade")
    _drop_source_guard_triggers()
    _install_0012_guards()
    _restore_0010_cas_guard()
    op.drop_constraint(
        "ck_narration_request_source_manifest_shape",
        "narration_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_narration_request_source_set_hash", "narration_requests", type_="check"
    )
    op.drop_constraint(
        "ck_narration_request_source_count", "narration_requests", type_="check"
    )
    op.drop_column("narration_requests", "sources_sealed_at")
    op.drop_column("narration_requests", "source_set_hash")
    op.drop_column("narration_requests", "source_count")
