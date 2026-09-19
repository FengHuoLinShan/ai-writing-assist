"""Add opt-in ensemble mode and immutable actor state owned by RP nodes."""

import sqlalchemy as sa

from alembic import op

revision = "20260920_interaction_ensemble"
down_revision = "20260920_story_simulation"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "generation_mode" not in {
        column["name"] for column in inspector.get_columns("interaction_journeys")
    }:
        op.add_column(
            "interaction_journeys",
            sa.Column(
                "generation_mode",
                sa.String(16),
                server_default="standard",
                nullable=False,
            ),
        )
    for table, name, columns in [
        ("interaction_journeys", "uq_interaction_journey_novel", ["novel_id", "id"]),
        (
            "interaction_message_nodes",
            "uq_interaction_node_journey_novel",
            ["novel_id", "journey_id", "id"],
        ),
    ]:
        if name not in {
            constraint["name"] for constraint in inspector.get_unique_constraints(table)
        }:
            op.create_unique_constraint(name, table, columns)
    if not inspector.has_table("interaction_actor_state_revisions"):
        op.create_table(
            "interaction_actor_state_revisions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "novel_id",
                sa.Uuid(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("journey_id", sa.Uuid(), nullable=False),
            sa.Column("message_node_id", sa.Uuid(), nullable=False),
            sa.Column("actor_id", sa.Uuid(), nullable=False),
            sa.Column("parent_id", sa.Uuid()),
            sa.Column("source_revision_id", sa.Uuid(), nullable=False),
            sa.Column("state_json", sa.JSON(), nullable=False),
            sa.Column("state_hash", sa.String(64), nullable=False),
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
            ),
            sa.UniqueConstraint(
                "novel_id", "journey_id", "id", name="uq_interaction_actor_state_scope"
            ),
            sa.UniqueConstraint(
                "message_node_id", "actor_id", name="uq_interaction_actor_state_node"
            ),
            sa.ForeignKeyConstraint(
                ["novel_id", "journey_id"],
                ["interaction_journeys.novel_id", "interaction_journeys.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["novel_id", "journey_id", "message_node_id"],
                [
                    "interaction_message_nodes.novel_id",
                    "interaction_message_nodes.journey_id",
                    "interaction_message_nodes.id",
                ],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["novel_id", "journey_id", "parent_id"],
                [
                    "interaction_actor_state_revisions.novel_id",
                    "interaction_actor_state_revisions.journey_id",
                    "interaction_actor_state_revisions.id",
                ],
            ),
        )
        op.create_index(
            "ix_interaction_actor_state_revisions_novel_id",
            "interaction_actor_state_revisions",
            ["novel_id"],
        )
    op.execute("""CREATE FUNCTION reject_interaction_actor_state_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'actor state revisions are immutable'; END $$""")
    op.execute("""CREATE TRIGGER interaction_actor_state_immutable
        BEFORE UPDATE OR DELETE ON interaction_actor_state_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_interaction_actor_state_update()""")


def downgrade():
    op.drop_table("interaction_actor_state_revisions")
    op.execute("DROP FUNCTION reject_interaction_actor_state_update()")
    op.drop_constraint(
        "uq_interaction_node_journey_novel", "interaction_message_nodes", type_="unique"
    )
    op.drop_constraint(
        "uq_interaction_journey_novel", "interaction_journeys", type_="unique"
    )
    op.drop_column("interaction_journeys", "generation_mode")
