"""Add immutable writing-method action snapshots.

Revision ID: 20260905_0041
Revises: 20260903_0040
No novel content changes and no model calls.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20260905_0041"
down_revision = "20260903_0040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "writing_skill_dispatches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(40), nullable=False),
        sa.Column("entry", sa.String(16), nullable=False),
        sa.Column("action_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_kind", sa.String(24), nullable=False),
        sa.Column("scope_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", pg.UUID(as_uuid=True)),
        sa.Column("client_input_hash", sa.String(64), nullable=False),
        sa.Column("route_request_key", sa.String(64), nullable=False),
        sa.Column("route_snapshot", pg.JSONB(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("method_packet", pg.JSONB()),
        sa.Column("job_ref", sa.String(240)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "workspace_id", "agent_id", "entry", "action_id", name="uq_writing_skill_action"),
        sa.ForeignKeyConstraint(["novel_id", "owner_id", "workspace_id"], ["novels.id", "novels.owner_id", "novels.workspace_id"], ondelete="CASCADE", name="fk_writing_skill_novel_scope"),
        sa.CheckConstraint("owner_id = '29cf94d9-a5c9-54ec-912c-5dfff8738c4c'::uuid AND workspace_id = 'f0e2e632-bc99-52d2-9916-bb906aa4da6e'::uuid", name="ck_writing_skill_local_scope"),
        sa.CheckConstraint("agent_id = 'ai-novel-writer' AND entry IN ('button','native')", name="ck_writing_skill_entry"),
        sa.CheckConstraint("(scope_kind = 'novel' AND novel_id IS NOT NULL AND scope_id = novel_id) OR (scope_kind = 'creation_draft' AND novel_id IS NULL)", name="ck_writing_skill_scope"),
        sa.CheckConstraint("state IN ('claimed','routing_started','route_ready','assembled','dispatch_started','dispatched','failed','cancelled','unknown','stale')", name="ck_writing_skill_state"),
        sa.CheckConstraint("fence >= 1", name="ck_writing_skill_fence"),
    )
    op.execute("""
    CREATE FUNCTION writing_skill_dispatch_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.id, NEW.owner_id, NEW.workspace_id, NEW.agent_id, NEW.entry,
             NEW.action_id, NEW.scope_kind, NEW.scope_id, NEW.novel_id,
             NEW.client_input_hash, NEW.route_request_key, NEW.route_snapshot, NEW.created_at)
         IS DISTINCT FROM
         ROW(OLD.id, OLD.owner_id, OLD.workspace_id, OLD.agent_id, OLD.entry,
             OLD.action_id, OLD.scope_kind, OLD.scope_id, OLD.novel_id,
             OLD.client_input_hash, OLD.route_request_key, OLD.route_snapshot, OLD.created_at)
      THEN RAISE EXCEPTION 'writing skill action snapshot is immutable'; END IF;
      IF OLD.method_packet IS NOT NULL AND NEW.method_packet IS DISTINCT FROM OLD.method_packet
      THEN RAISE EXCEPTION 'writing skill packet is immutable'; END IF;
      IF OLD.job_ref IS NOT NULL AND NEW.job_ref IS DISTINCT FROM OLD.job_ref
      THEN RAISE EXCEPTION 'writing skill job reference is immutable'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER writing_skill_dispatch_immutable BEFORE UPDATE ON writing_skill_dispatches
    FOR EACH ROW EXECUTE FUNCTION writing_skill_dispatch_immutable();
    """)


def downgrade():
    # Old application code tolerates this additive table. Dropping it would
    # erase action IDs and permit uncertain work to be silently repeated.
    raise RuntimeError("retain writing dispatch evidence: roll back application without schema downgrade")
