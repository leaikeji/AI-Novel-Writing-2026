"""Close the analyzed-to-generation transaction and render-job identity gaps.

Revision ID: 20260827_0017
Revises: 20260826_0016

This fix-forward migration changes no user content.  It permits an approved
generation request to continue from ``analyzed`` to ``queued`` while enforcing
at commit time that a queued/playable request and its Edition are created in
the same transaction.  It also makes one segment-render job identify exactly
one render row.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0017"
down_revision = "20260826_0016"
branch_labels = None
depends_on = None


def _install_request_guard(*, allow_analyzed_generation: bool) -> None:
    analyzed_branch = (
        "(OLD.state='analyzed' AND NEW.state IN ('queued','cancel_requested','failed')) OR"
        if allow_analyzed_generation
        else ""
    )
    op.execute(
        sa.text(
            f"""
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
                {analyzed_branch}
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


def upgrade() -> None:
    _install_request_guard(allow_analyzed_generation=True)

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT source_job_id
                FROM narration_segment_renders
                GROUP BY source_job_id
                HAVING count(*) > 1
              ) THEN
                RAISE EXCEPTION 'duplicate narration render source_job_id blocks 0017';
              END IF;
            END $$;
            """
        )
    )
    op.create_unique_constraint(
        "uq_narration_segment_render_source_job",
        "narration_segment_renders",
        ["source_job_id"],
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_guard_generation_request_edition()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.state IN ('queued','rendering','partial_ready','ready')
                 AND NOT EXISTS (
                   SELECT 1 FROM narration_editions e
                   WHERE e.request_id=NEW.id
                 )
              THEN
                RAISE EXCEPTION 'generation request state requires an Edition in the same transaction';
              END IF;
              RETURN NEW;
            END $$;

            CREATE FUNCTION narration_guard_edition_generation_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM narration_requests r
                WHERE r.id=NEW.request_id
                  AND r.intent IN ('create','update','batch')
                  AND r.state IN ('queued','rendering','partial_ready','ready')
              )
              THEN
                RAISE EXCEPTION 'Edition requires a compatible generation request in the same transaction';
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_generation_request_requires_edition
            AFTER INSERT OR UPDATE ON narration_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_generation_request_edition();

            CREATE CONSTRAINT TRIGGER trg_t4_edition_requires_generation_request
            AFTER INSERT ON narration_editions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_guard_edition_generation_request();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TRIGGER trg_t4_edition_requires_generation_request ON narration_editions;
            DROP TRIGGER trg_t4_generation_request_requires_edition ON narration_requests;
            DROP FUNCTION narration_guard_edition_generation_request();
            DROP FUNCTION narration_guard_generation_request_edition();
            """
        )
    )
    op.drop_constraint(
        "uq_narration_segment_render_source_job",
        "narration_segment_renders",
        type_="unique",
    )
    _install_request_guard(allow_analyzed_generation=False)
