"""Persist narration review pointers and immutable owner-action evidence.

Revision ID: 20260827_0020
Revises: 20260827_0019

The migration extends the existing project PostgreSQL schema only.  Existing
requests remain nullable and are deliberately not guessed/backfilled: a legacy
review request without a provable current version must be restarted by the
author instead of silently binding the latest script row.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_0020"
down_revision = "20260827_0019"
branch_labels = None
depends_on = None


def _install_request_guard(*, review_pointers: bool) -> None:
    pointer_declaration = (
        "pointer_changed boolean;"
        if review_pointers
        else ""
    )
    insert_pointer_guard = (
        """
                IF NEW.review_script_id IS NOT NULL OR
                   NEW.current_review_version_id IS NOT NULL
                THEN
                  RAISE EXCEPTION 'narration request review pointer must start empty';
                END IF;
        """
        if review_pointers
        else ""
    )
    pointer_guard = (
        """
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
        """
        if review_pointers
        else ""
    )
    pointer_exclusions = (
        ",'review_script_id','current_review_version_id'"
        if review_pointers
        else ""
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION narration_guard_request()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE actual_count integer; min_position integer; max_position integer;
                    {pointer_declaration}
            BEGIN
              IF TG_OP='INSERT' THEN
                IF NEW.state<>'created' THEN
                  RAISE EXCEPTION 'narration request must be inserted in created state';
                END IF;
                {insert_pointer_guard}
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

              {pointer_guard}
              IF (to_jsonb(OLD)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'{pointer_exclusions}]) <>
                 (to_jsonb(NEW)-ARRAY['state','version','allows_edition','allows_render',
                                      'cancel_requested_at','cancel_actor','cancel_reason_code',
                                      'failure_code','updated_at','completed_at'{pointer_exclusions}])
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
                (OLD.state='cancel_requested' AND NEW.state='cancelled'))
              THEN RAISE EXCEPTION 'invalid narration request state transition'; END IF;
              RETURN NEW;
            END $$;
            """
        )
    )


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.add_column(
        "narration_requests",
        sa.Column("review_script_id", uuid_type, nullable=True),
    )
    op.add_column(
        "narration_requests",
        sa.Column("current_review_version_id", uuid_type, nullable=True),
    )
    op.create_check_constraint(
        "ck_narration_request_review_pointer_shape",
        "narration_requests",
        "(review_script_id IS NULL AND current_review_version_id IS NULL) OR "
        "(review_script_id IS NOT NULL AND current_review_version_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_narration_request_review_script_document",
        "narration_requests",
        "narration_scripts",
        ["review_script_id", "document_id"],
        ["id", "document_id"],
    )
    op.create_foreign_key(
        "fk_narration_request_current_review_version",
        "narration_requests",
        "narration_script_versions",
        ["current_review_version_id", "review_script_id"],
        ["id", "script_id"],
    )
    op.create_unique_constraint(
        "uq_narration_request_review_script_guard",
        "narration_requests",
        ["id", "review_script_id"],
    )
    op.create_index(
        "ix_narration_requests_review_pointer",
        "narration_requests",
        ["review_script_id", "current_review_version_id"],
    )
    _install_request_guard(review_pointers=True)

    op.create_table(
        "narration_script_review_actions",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("owner_id", uuid_type, nullable=False),
        sa.Column("workspace_id", uuid_type, nullable=False),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("request_id", uuid_type, nullable=False),
        sa.Column("request_allows_render", sa.Boolean(), nullable=False),
        sa.Column("script_id", uuid_type, nullable=False),
        sa.Column("parent_version_id", uuid_type, nullable=False),
        sa.Column("result_version_id", uuid_type, nullable=False),
        sa.Column("result_edition_id", uuid_type, nullable=True),
        sa.Column("action_kind", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_version_before", sa.BigInteger(), nullable=False),
        sa.Column("request_version_after", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_kind IN ('patch_segment','reanalyze_segments','approve')",
            name="ck_narration_review_action_kind",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_narration_review_action_request_hash",
        ),
        sa.CheckConstraint(
            "request_allows_render IS TRUE",
            name="ck_narration_review_action_generation_request",
        ),
        sa.CheckConstraint(
            "request_version_before >= 1 AND "
            "request_version_after = request_version_before + 1",
            name="ck_narration_review_action_request_versions",
        ),
        sa.CheckConstraint(
            "actor_type = 'owner' AND length(btrim(actor_id)) > 0",
            name="ck_narration_review_action_owner_actor",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_narration_review_action_idempotency_key",
        ),
        sa.CheckConstraint(
            "(action_kind = 'approve' AND result_version_id = parent_version_id "
            "AND result_edition_id IS NOT NULL) OR "
            "(action_kind IN ('patch_segment','reanalyze_segments') "
            "AND result_version_id <> parent_version_id "
            "AND result_edition_id IS NULL)",
            name="ck_narration_review_action_result_shape",
        ),
        sa.ForeignKeyConstraint(
            [
                "request_id",
                "owner_id",
                "workspace_id",
                "novel_id",
                "request_allows_render",
            ],
            [
                "narration_requests.id",
                "narration_requests.owner_id",
                "narration_requests.workspace_id",
                "narration_requests.novel_id",
                "narration_requests.allows_render",
            ],
            name="fk_narration_review_action_request_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["script_id", "parent_version_id"],
            ["narration_script_versions.script_id", "narration_script_versions.id"],
            name="fk_narration_review_action_parent_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["script_id", "result_version_id"],
            ["narration_script_versions.script_id", "narration_script_versions.id"],
            name="fk_narration_review_action_result_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "script_id"],
            ["narration_requests.id", "narration_requests.review_script_id"],
            name="fk_narration_review_action_request_script",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_edition_id", "request_id"],
            ["narration_editions.id", "narration_editions.request_id"],
            name="fk_narration_review_action_result_edition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_edition_id", "result_version_id"],
            ["narration_editions.id", "narration_editions.script_version_id"],
            name="fk_narration_review_action_edition_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "workspace_id",
            "idempotency_key",
            name="uq_narration_review_action_idempotency",
        ),
        sa.UniqueConstraint(
            "request_id",
            "request_version_after",
            name="uq_narration_review_action_request_version",
        ),
    )
    op.create_index(
        "ix_narration_review_actions_request_created",
        "narration_script_review_actions",
        ["request_id", "created_at", "id"],
    )
    op.create_index(
        "ix_narration_review_actions_parent",
        "narration_script_review_actions",
        ["script_id", "parent_version_id"],
    )
    op.create_index(
        "ix_narration_review_actions_result",
        "narration_script_review_actions",
        ["script_id", "result_version_id"],
    )
    op.create_index(
        "ix_narration_review_actions_edition",
        "narration_script_review_actions",
        ["result_edition_id"],
    )
    op.create_index(
        "uq_narration_review_action_approve_request",
        "narration_script_review_actions",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("action_kind = 'approve'"),
    )
    op.execute(
        "CREATE TRIGGER trg_t4_narration_script_review_actions_immutable "
        "BEFORE UPDATE OR DELETE ON narration_script_review_actions "
        "FOR EACH ROW EXECUTE FUNCTION narration_reject_mutation()"
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_require_review_action()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE current_approval_kind varchar(32);
                    current_is_approved boolean;
            BEGIN
              IF OLD.current_review_version_id IS NOT NULL AND
                 OLD.current_review_version_id<>NEW.current_review_version_id
              THEN
                IF NOT EXISTS (
                  SELECT 1 FROM narration_script_review_actions a
                  WHERE a.request_id=NEW.id
                    AND a.script_id=NEW.review_script_id
                    AND a.parent_version_id=OLD.current_review_version_id
                    AND a.result_version_id=NEW.current_review_version_id
                    AND a.request_version_before=OLD.version
                    AND a.request_version_after=NEW.version
                    AND a.action_kind IN ('patch_segment','reanalyze_segments')
                ) THEN
                  RAISE EXCEPTION 'review pointer change requires an immutable action';
                END IF;
              END IF;
              IF OLD.state IS DISTINCT FROM 'queued' AND NEW.state='queued' THEN
                IF NEW.review_script_id IS NULL OR
                   NEW.current_review_version_id IS NULL
                THEN
                  RAISE EXCEPTION 'queued narration request requires a proven review pointer';
                END IF;

                SELECT sv.approval_kind,sv.is_approved
                  INTO current_approval_kind,current_is_approved
                FROM narration_script_versions sv
                WHERE sv.id=NEW.current_review_version_id
                  AND sv.script_id=NEW.review_script_id;
                IF NOT FOUND OR current_is_approved IS NOT TRUE THEN
                  RAISE EXCEPTION 'queued narration request requires its current approved version';
                END IF;

                IF current_approval_kind='manual_after_review' THEN
                  IF NOT EXISTS (
                    SELECT 1 FROM narration_script_review_actions a
                    JOIN narration_editions e ON e.id=a.result_edition_id
                    WHERE a.request_id=NEW.id
                      AND a.script_id=NEW.review_script_id
                      AND a.parent_version_id=NEW.current_review_version_id
                      AND a.result_version_id=NEW.current_review_version_id
                      AND a.request_version_before=OLD.version
                      AND a.request_version_after=NEW.version
                      AND a.action_kind='approve'
                      AND e.request_id=NEW.id
                      AND e.script_version_id=NEW.current_review_version_id
                  ) THEN
                    RAISE EXCEPTION 'manual review continuation requires approval action and Edition';
                  END IF;
                ELSIF current_approval_kind<>'auto_no_blockers' OR
                      current_approval_kind IS NULL
                THEN
                  RAISE EXCEPTION 'queued narration request has an invalid approval kind';
                END IF;
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_review_action_required
            AFTER UPDATE ON narration_requests
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_require_review_action();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_require_manual_script_approval_action()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE became_manual_approved boolean;
            BEGIN
              IF TG_OP='INSERT' THEN
                became_manual_approved :=
                  NEW.state='approved' AND
                  NEW.approval_kind='manual_after_review';
              ELSE
                became_manual_approved :=
                  NEW.state='approved' AND
                  NEW.approval_kind='manual_after_review' AND
                  OLD.state IS DISTINCT FROM 'approved';
              END IF;
              IF became_manual_approved THEN
                IF NOT EXISTS (
                  SELECT 1
                  FROM narration_script_review_actions a
                  JOIN narration_requests r ON r.id=a.request_id
                  JOIN narration_editions e ON e.id=a.result_edition_id
                  WHERE a.action_kind='approve'
                    AND a.request_id=NEW.approval_request_id
                    AND a.script_id=NEW.script_id
                    AND a.parent_version_id=NEW.id
                    AND a.result_version_id=NEW.id
                    AND a.actor_type='owner'
                    AND a.actor_id=NEW.approved_actor_id
                    AND r.review_script_id=NEW.script_id
                    AND r.current_review_version_id=NEW.id
                    AND r.state IN ('queued','rendering','partial_ready','ready')
                    AND r.version>=a.request_version_after
                    AND e.request_id=r.id
                    AND e.script_version_id=NEW.id
                ) THEN
                  RAISE EXCEPTION
                    'manual script approval requires action, Edition, and queued request';
                END IF;
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_manual_script_approval_required
            AFTER INSERT OR UPDATE ON narration_script_versions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_require_manual_script_approval_action();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION narration_require_review_action_target()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE request_row narration_requests%ROWTYPE;
                    result_parent uuid;
                    result_state varchar(24);
                    result_approval_kind varchar(32);
            BEGIN
              SELECT * INTO request_row
              FROM narration_requests
              WHERE id=NEW.request_id;
              IF NOT FOUND OR
                 request_row.review_script_id IS DISTINCT FROM NEW.script_id OR
                 request_row.current_review_version_id IS DISTINCT FROM NEW.result_version_id
              THEN
                RAISE EXCEPTION 'review action must target the request current pointer';
              END IF;

              SELECT parent_version_id,state,approval_kind
                INTO result_parent,result_state,result_approval_kind
              FROM narration_script_versions
              WHERE id=NEW.result_version_id AND script_id=NEW.script_id;
              IF NOT FOUND THEN
                RAISE EXCEPTION 'review action result version is missing';
              END IF;

              IF NEW.action_kind IN ('patch_segment','reanalyze_segments') THEN
                IF request_row.state<>'review_required' OR
                   request_row.version<>NEW.request_version_after OR
                   result_parent IS DISTINCT FROM NEW.parent_version_id OR
                   result_state<>'review_required'
                THEN
                  RAISE EXCEPTION 'correction action does not match request final state';
                END IF;
              ELSIF NEW.action_kind='approve' THEN
                IF request_row.state NOT IN
                     ('queued','rendering','partial_ready','ready') OR
                   request_row.version<NEW.request_version_after OR
                   result_state<>'approved' OR
                   result_approval_kind<>'manual_after_review' OR
                   NOT EXISTS (
                     SELECT 1 FROM narration_editions e
                     WHERE e.id=NEW.result_edition_id
                       AND e.request_id=NEW.request_id
                       AND e.script_version_id=NEW.result_version_id
                   )
                THEN
                  RAISE EXCEPTION 'approval action does not match request final state and Edition';
                END IF;
              END IF;
              RETURN NEW;
            END $$;

            CREATE CONSTRAINT TRIGGER trg_t4_review_action_target_required
            AFTER INSERT ON narration_script_review_actions
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION narration_require_review_action_target();
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM narration_script_review_actions) OR
                 EXISTS (
                   SELECT 1 FROM narration_requests
                   WHERE review_script_id IS NOT NULL OR
                         current_review_version_id IS NOT NULL
                 )
              THEN
                RAISE EXCEPTION
                  '0020 downgrade refused: review audit evidence or current pointers exist';
              END IF;
            END $$;
            """
        )
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_t4_review_action_target_required "
        "ON narration_script_review_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS narration_require_review_action_target()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_t4_manual_script_approval_required "
        "ON narration_script_versions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS narration_require_manual_script_approval_action()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_t4_review_action_required "
        "ON narration_requests"
    )
    op.execute("DROP FUNCTION IF EXISTS narration_require_review_action()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_t4_narration_script_review_actions_immutable "
        "ON narration_script_review_actions"
    )
    op.drop_index(
        "ix_narration_review_actions_request_created",
        table_name="narration_script_review_actions",
    )
    op.drop_table("narration_script_review_actions")
    op.drop_index(
        "ix_narration_requests_review_pointer",
        table_name="narration_requests",
    )
    op.drop_constraint(
        "uq_narration_request_review_script_guard",
        "narration_requests",
        type_="unique",
    )
    op.drop_constraint(
        "fk_narration_request_current_review_version",
        "narration_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_narration_request_review_script_document",
        "narration_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_narration_request_review_pointer_shape",
        "narration_requests",
        type_="check",
    )
    op.drop_column("narration_requests", "current_review_version_id")
    op.drop_column("narration_requests", "review_script_id")
    _install_request_guard(review_pointers=False)
