"""Enforce one map fact for each project observation.

Revision ID: 20260722_map_fact_observation
Revises: 20260722_context_confirm_refs
"""

import sqlalchemy as sa

from alembic import op

revision = "20260722_map_fact_observation"
down_revision = "20260722_context_confirm_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    observation_constraints = inspector.get_unique_constraints("map_observations")
    if not any(
        item["name"] == "uq_map_observations_id_novel"
        for item in observation_constraints
    ):
        op.create_unique_constraint(
            "uq_map_observations_id_novel",
            "map_observations",
            ["id", "novel_id"],
        )

    constraints = inspector.get_unique_constraints("map_facts")
    if not any(
        item["name"] == "uq_map_facts_novel_observation" for item in constraints
    ):
        # Development projects are disposable, so this migration deliberately
        # fails closed instead of guessing which duplicate fact should survive.
        op.create_unique_constraint(
            "uq_map_facts_novel_observation",
            "map_facts",
            ["novel_id", "observation_id"],
        )

    foreign_keys = inspector.get_foreign_keys("map_facts")
    if not any(
        item["name"] == "fk_map_facts_observation_novel" for item in foreign_keys
    ):
        op.create_foreign_key(
            "fk_map_facts_observation_novel",
            "map_facts",
            "map_observations",
            ["observation_id", "novel_id"],
            ["id", "novel_id"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_map_facts_observation_novel",
        "map_facts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_map_facts_novel_observation",
        "map_facts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_map_observations_id_novel",
        "map_observations",
        type_="unique",
    )
