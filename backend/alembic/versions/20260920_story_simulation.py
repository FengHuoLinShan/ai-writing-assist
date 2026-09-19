"""Add isolated author rehearsal runs and immutable completed rounds."""

import sqlalchemy as sa

from alembic import op

revision = "20260920_story_simulation"
down_revision = "20260914_anonymous_rp_accounts"
branch_labels = None
depends_on = None


def _identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "novel_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
    ]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("story_simulation_runs"):
        op.create_table(
            "story_simulation_runs",
            *_identity(),
            sa.Column("scene_id", sa.Uuid(), nullable=False),
            sa.Column("parent_id", sa.Uuid()),
            sa.Column("fork_round", sa.Integer(), nullable=False),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column("request_json", sa.JSON(), nullable=False),
            sa.Column("budget_json", sa.JSON(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.UniqueConstraint("novel_id", "id", name="uq_story_simulation_run_novel"),
            sa.ForeignKeyConstraint(
                ["novel_id", "parent_id"],
                ["story_simulation_runs.novel_id", "story_simulation_runs.id"],
            ),
        )
        op.create_index(
            "ix_story_simulation_runs_novel_id", "story_simulation_runs", ["novel_id"]
        )
    if not inspector.has_table("story_simulation_steps"):
        op.create_table(
            "story_simulation_steps",
            *_identity(),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("round_number", sa.Integer(), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("intents_json", sa.JSON(), nullable=False),
            sa.Column("events_json", sa.JSON(), nullable=False),
            sa.Column("state_json", sa.JSON(), nullable=False),
            sa.UniqueConstraint(
                "novel_id",
                "run_id",
                "round_number",
                name="uq_story_simulation_step_round",
            ),
            sa.ForeignKeyConstraint(
                ["novel_id", "run_id"],
                ["story_simulation_runs.novel_id", "story_simulation_runs.id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_story_simulation_steps_novel_id", "story_simulation_steps", ["novel_id"]
        )
    op.execute("""CREATE FUNCTION reject_story_simulation_step_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'completed simulation steps are immutable'; END $$""")
    op.execute("""CREATE TRIGGER story_simulation_steps_immutable
        BEFORE UPDATE OR DELETE ON story_simulation_steps
        FOR EACH ROW EXECUTE FUNCTION reject_story_simulation_step_update()""")


def downgrade():
    op.drop_table("story_simulation_steps")
    op.drop_table("story_simulation_runs")
    op.execute("DROP FUNCTION reject_story_simulation_step_update()")
