"""Permit proven manual retry of one failed narration segment.

Revision ID: 20260828_0024
Revises: 20260827_0023

This fix-forward migration changes no schema shape and no user content.  It
only reopens four failed production states while the exact source job has both
a queued lifecycle state and a pending immutable manual-retry command in the
same fixed local scope.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0024"
down_revision = "20260827_0023"
branch_labels = None
depends_on = None


def _install_retry_evidence_function() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_failed_segment_retry_authorized_v1(
              p_source_job_id uuid,
              p_owner_id uuid,
              p_workspace_id uuid,
              p_novel_id uuid,
              p_request_id uuid
            ) RETURNS boolean LANGUAGE sql STABLE AS $$
              SELECT EXISTS (
                SELECT 1
                FROM background_jobs j
                JOIN background_manual_retry_commands c
                  ON c.job_id=j.id
                 AND c.owner_id=j.owner_id
                 AND c.workspace_id=j.workspace_id
                WHERE j.id=p_source_job_id
                  AND j.owner_id=p_owner_id
                  AND j.workspace_id=p_workspace_id
                  AND j.novel_id=p_novel_id
                  AND j.request_id=p_request_id
                  AND j.request_allows_render IS TRUE
                  AND j.job_kind='narration.segment_render'
                  AND j.resource_class='moss-nano'
                  AND j.state='queued'
                  AND c.state='pending'
              );
            $$;
            """
        )
    )


def _install_request_guard(*, allow_failed_segment_retry: bool) -> None:
    failed_retry_branch = (
        """
                (OLD.state='failed' AND NEW.state='queued'
                 AND NEW.failure_code IS NULL
                 AND NEW.completed_at IS NULL
                 AND EXISTS (
                   SELECT 1
                   FROM narration_segment_renders sr
                   WHERE sr.request_id=OLD.id
                     AND sr.owner_id=OLD.owner_id
                     AND sr.workspace_id=OLD.workspace_id
                     AND sr.novel_id=OLD.novel_id
                     AND narration_failed_segment_retry_authorized_v1(
                       sr.source_job_id,OLD.owner_id,OLD.workspace_id,
                       OLD.novel_id,OLD.id
                     )
                 )) OR
        """
        if allow_failed_segment_retry
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE actual_count integer; min_position integer; max_position integer;
                    pointer_changed boolean;
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN
                  RAISE EXCEPTION 'narration request must be inserted in created state';
                END IF;
                IF NEW.review_script_id IS NOT NULL OR
                   NEW.current_review_version_id IS NOT NULL
                THEN
                  RAISE EXCEPTION 'narration request review pointer must start empty';
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

              pointer_changed := ROW(OLD.review_script_id,
                                     OLD.current_review_version_id)
                                 IS DISTINCT FROM
                                 ROW(NEW.review_script_id,
                                     NEW.current_review_version_id);
              IF pointer_changed THEN
                IF OLD.review_script_id IS NULL AND
                   OLD.current_review_version_id IS NULL AND
                   NEW.review_script_id IS NOT NULL AND
                   NEW.current_review_version_id IS NOT NULL AND
                   OLD.state='analyzing' AND NEW.state='analyzing' AND
                   NEW.version=OLD.version+1
                THEN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM narration_script_versions sv
                    JOIN narration_scripts s ON s.id=sv.script_id
                    WHERE sv.id=NEW.current_review_version_id
                      AND sv.script_id=NEW.review_script_id
                      AND s.document_id=NEW.document_id
                      AND s.revision_id=NEW.source_revision_id
                      AND s.content_hash=NEW.source_content_hash
                      AND sv.settings_fingerprint=NEW.settings_fingerprint
                  ) THEN
                    RAISE EXCEPTION 'initial review pointer provenance is invalid';
                  END IF;
                  NEW.updated_at := clock_timestamp();
                ELSIF OLD.review_script_id=NEW.review_script_id AND
                      OLD.current_review_version_id IS NOT NULL AND
                      NEW.current_review_version_id IS NOT NULL AND
                      OLD.current_review_version_id<>NEW.current_review_version_id AND
                      OLD.state='review_required' AND
                      NEW.state='review_required' AND
                      NEW.version=OLD.version+1
                THEN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM narration_script_versions sv
                    JOIN narration_scripts s ON s.id=sv.script_id
                    WHERE sv.id=NEW.current_review_version_id
                      AND sv.script_id=OLD.review_script_id
                      AND sv.parent_version_id=OLD.current_review_version_id
                      AND sv.state='review_required'
                      AND sv.settings_fingerprint=OLD.settings_fingerprint
                      AND s.document_id=OLD.document_id
                      AND s.revision_id=OLD.source_revision_id
                      AND s.content_hash=OLD.source_content_hash
                  ) THEN
                    RAISE EXCEPTION 'review pointer CAS target is invalid';
                  END IF;
                  NEW.updated_at := clock_timestamp();
                ELSE
                  RAISE EXCEPTION 'invalid narration request review pointer transition';
                END IF;
              END IF;
              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at','review_script_id','current_review_version_id']) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at','review_script_id','current_review_version_id'])
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
                (OLD.state='analyzed' AND NEW.state IN
                  ('queued','cancel_requested','failed')) OR
                (OLD.state='review_required' AND NEW.state IN
                  ('analyzing','queued','cancel_requested','failed')) OR
                (OLD.state='queued' AND NEW.state IN
                  ('rendering','cancel_requested','failed')) OR
                (OLD.state='rendering' AND NEW.state IN
                  ('partial_ready','ready','cancel_requested','failed')) OR
                (OLD.state='partial_ready' AND NEW.state IN
                  ('ready','cancel_requested','failed')) OR
                {failed_retry_branch}
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _install_render_guard(*, allow_failed_segment_retry: bool) -> None:
    failed_retry_branch = (
        """
        (OLD.state='failed' AND NEW.state='pending'
         AND narration_failed_segment_retry_authorized_v1(
           OLD.source_job_id,OLD.owner_id,OLD.workspace_id,OLD.novel_id,OLD.request_id
         )) OR
        """
        if allow_failed_segment_retry
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_ready_render()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.state='ready' THEN RAISE EXCEPTION 'ready render is immutable'; END IF;
              IF OLD.state IN ('cancelled','quarantined')
              THEN RAISE EXCEPTION 'cancelled/quarantined render is immutable'; END IF;
              IF TG_OP='DELETE' THEN RETURN OLD; END IF;
              IF (to_jsonb(OLD)-ARRAY['state','duration_ms','audio_validation_json','ready_at']) <>
                 (to_jsonb(NEW)-ARRAY['state','duration_ms','audio_validation_json','ready_at'])
              THEN RAISE EXCEPTION 'render canonical input and scope are immutable'; END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='pending' AND NEW.state IN ('rendering','ready','failed','cancelled','quarantined')) OR
                (OLD.state='rendering' AND NEW.state IN ('ready','failed','cancelled','quarantined')) OR
                {failed_retry_branch}
                false)
              THEN RAISE EXCEPTION 'invalid render state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _install_edition_guard(*, allow_failed_segment_retry: bool) -> None:
    unavailable_guard = (
        """
      IF OLD.state='unavailable' AND NOT (
        NEW.state='rendering' AND NEW.unavailable_reason IS NULL AND EXISTS (
          SELECT 1
          FROM narration_edition_segments es
          JOIN narration_segment_renders sr
            ON sr.owner_id=OLD.owner_id
           AND sr.workspace_id=OLD.workspace_id
           AND sr.novel_id=OLD.novel_id
           AND sr.request_id=OLD.request_id
           AND sr.render_fingerprint=es.render_fingerprint
          WHERE es.edition_id=OLD.id
            AND narration_failed_segment_retry_authorized_v1(
              sr.source_job_id,OLD.owner_id,OLD.workspace_id,
              OLD.novel_id,OLD.request_id
            )
        )
      ) THEN RAISE EXCEPTION 'unavailable edition is immutable'; END IF;
        """
        if allow_failed_segment_retry
        else """
      IF OLD.state='unavailable' THEN RAISE EXCEPTION 'unavailable edition is immutable'; END IF;
        """
    )
    failed_retry_branch = (
        "(OLD.state='unavailable' AND NEW.state='rendering') OR"
        if allow_failed_segment_retry
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_edition()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              {unavailable_guard}
              IF (to_jsonb(OLD)-ARRAY['state','unavailable_reason']) <>
                 (to_jsonb(NEW)-ARRAY['state','unavailable_reason'])
              THEN RAISE EXCEPTION 'edition production input is immutable'; END IF;
              IF OLD.state<>NEW.state AND NOT (
                (OLD.state='created' AND NEW.state IN ('rendering','partial_ready','ready','unavailable')) OR
                (OLD.state='rendering' AND NEW.state IN ('partial_ready','ready','unavailable')) OR
                (OLD.state='partial_ready' AND NEW.state IN ('ready','unavailable')) OR
                (OLD.state='ready' AND NEW.state='unavailable') OR
                {failed_retry_branch}
                false)
              THEN RAISE EXCEPTION 'invalid edition state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def _install_edition_segment_guard(*, allow_failed_segment_retry: bool) -> None:
    failed_retry_branch = (
        """
        (OLD.render_state='failed' AND NEW.render_state='queued'
         AND NEW.failure_code IS NULL
         AND EXISTS (
           SELECT 1
           FROM narration_editions e
           JOIN narration_segment_renders sr
             ON sr.owner_id=e.owner_id
            AND sr.workspace_id=e.workspace_id
            AND sr.novel_id=e.novel_id
            AND sr.request_id=e.request_id
            AND sr.render_fingerprint=OLD.render_fingerprint
           WHERE e.id=OLD.edition_id
             AND narration_failed_segment_retry_authorized_v1(
               sr.source_job_id,e.owner_id,e.workspace_id,e.novel_id,e.request_id
             )
         )) OR
        """
        if allow_failed_segment_retry
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_edition_segment()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.render_state IN ('ready','cancelled','quarantined')
              THEN RAISE EXCEPTION 'ready/cancelled/quarantined edition segment is immutable'; END IF;
              IF (to_jsonb(OLD)-ARRAY['render_state','failure_code']) <>
                 (to_jsonb(NEW)-ARRAY['render_state','failure_code'])
              THEN RAISE EXCEPTION 'edition segment production input is immutable'; END IF;
              IF OLD.render_state<>NEW.render_state AND NOT (
                (OLD.render_state='pending' AND NEW.render_state IN ('queued','rendering','ready','failed','cancelled','quarantined')) OR
                (OLD.render_state='queued' AND NEW.render_state IN ('rendering','ready','failed','cancelled','quarantined')) OR
                (OLD.render_state='rendering' AND NEW.render_state IN ('ready','failed','cancelled','quarantined')) OR
                {failed_retry_branch}
                false)
              THEN RAISE EXCEPTION 'invalid edition segment state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def upgrade() -> None:
    _install_retry_evidence_function()
    _install_request_guard(allow_failed_segment_retry=True)
    _install_render_guard(allow_failed_segment_retry=True)
    _install_edition_guard(allow_failed_segment_retry=True)
    _install_edition_segment_guard(allow_failed_segment_retry=True)


def downgrade() -> None:
    _install_edition_segment_guard(allow_failed_segment_retry=False)
    _install_edition_guard(allow_failed_segment_retry=False)
    _install_render_guard(allow_failed_segment_retry=False)
    _install_request_guard(allow_failed_segment_retry=False)
    op.execute(
        sa.text(
            "DROP FUNCTION narration_failed_segment_retry_authorized_v1(uuid,uuid,uuid,uuid,uuid)"
        )
    )
