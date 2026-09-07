"""Permit exactly one input freeze after a durable, content-free action claim.

Revision ID: 20260905_0042
Revises: 20260905_0041
Existing frozen evidence remains immutable. No tables or user data are removed.
"""
from alembic import op

revision = "20260905_0042"
down_revision = "20260905_0041"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION writing_skill_dispatch_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id, NEW.owner_id, NEW.workspace_id, NEW.agent_id, NEW.entry,
             NEW.action_id, NEW.scope_kind, NEW.scope_id, NEW.novel_id,
             NEW.client_input_hash, NEW.created_at)
         IS DISTINCT FROM
         ROW(OLD.id, OLD.owner_id, OLD.workspace_id, OLD.agent_id, OLD.entry,
             OLD.action_id, OLD.scope_kind, OLD.scope_id, OLD.novel_id,
             OLD.client_input_hash, OLD.created_at)
      THEN RAISE EXCEPTION 'writing skill action identity is immutable'; END IF;
      IF ROW(NEW.route_request_key, NEW.route_snapshot)
         IS DISTINCT FROM ROW(OLD.route_request_key, OLD.route_snapshot)
      THEN
        IF (OLD.route_snapshot->>'schema_version' = 'route-input-pending/1'
            AND OLD.route_request_key = repeat('0', 64)
            AND OLD.state = 'claimed' AND NEW.state = 'claimed'
            AND NEW.fence = OLD.fence + 1
            AND OLD.method_packet IS NULL AND NEW.method_packet IS NULL
            AND OLD.job_ref IS NULL AND NEW.job_ref IS NULL
            AND NEW.route_snapshot->>'policy_version' = 'writing-routing/1'
            AND NOT (NEW.route_snapshot ? 'schema_version')
            AND NEW.route_snapshot->'identity' = OLD.route_snapshot->'identity'
            AND NEW.route_snapshot->'projection'->'scope' = OLD.route_snapshot->'scope'
            AND NEW.route_request_key ~ '^[a-f0-9]{64}$'
            AND NEW.route_request_key <> repeat('0', 64)) IS NOT TRUE
        THEN RAISE EXCEPTION 'writing skill action snapshot is immutable'; END IF;
      END IF;
      IF NEW.route_snapshot->>'schema_version' = 'route-input-pending/1'
         AND (NEW.state NOT IN ('claimed', 'failed', 'cancelled', 'stale')
              OR NEW.method_packet IS NOT NULL OR NEW.job_ref IS NOT NULL)
      THEN RAISE EXCEPTION 'pending input cannot dispatch'; END IF;
      IF OLD.method_packet IS NOT NULL AND NEW.method_packet IS DISTINCT FROM OLD.method_packet
      THEN RAISE EXCEPTION 'writing skill packet is immutable'; END IF;
      IF OLD.job_ref IS NOT NULL AND NEW.job_ref IS DISTINCT FROM OLD.job_ref
      THEN RAISE EXCEPTION 'writing skill job reference is immutable'; END IF;
      RETURN NEW;
    END $$;
    """)


def downgrade():
    raise RuntimeError("retain pending action evidence: roll back application without schema downgrade")
