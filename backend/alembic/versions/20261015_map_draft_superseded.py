"""retain replaced automatic map candidates as superseded revisions

Revision ID: 20261015_map_draft_superseded
Revises: 20261015_spatial_clues
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_map_draft_superseded"
down_revision = "20261015_spatial_clues"
branch_labels = None
depends_on = None


def _replace_status_check(statuses: tuple[str, ...]) -> None:
    op.drop_constraint("ck_map_revision_status", "map_atlas_revisions", type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    op.create_check_constraint(
        "ck_map_revision_status", "map_atlas_revisions", f"status IN ({values})"
    )


def upgrade() -> None:
    _replace_status_check(("candidate", "saved", "rejected", "superseded"))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM map_atlas_revisions "
                "WHERE status = 'superseded')"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Superseded map candidates exist; downgrade would discard review history"
        )
    _replace_status_check(("candidate", "saved", "rejected"))
