"""Soft-delete world event extensions instead of hard-deleting them.

Revision ID: 20261006_event_soft_delete
Revises: 20261005_world_revision_metadata

``events`` 是唯一没有 ``status`` 的 ``CrudService`` 模型，删除会硬删扩展行。
对齐 ``entity_relations`` 先例：新增 ``status``（存量行回填 ``canonical``），
删除改置 ``deprecated``，读取路径只认 ``canonical``。
"""

import sqlalchemy as sa

from alembic import op

revision = "20261006_event_soft_delete"
down_revision = "20261005_world_revision_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="canonical",
            comment="状态：canonical/deprecated（删除只置 deprecated，保留历史）",
        ),
    )
    op.create_check_constraint(
        "ck_events_status",
        "events",
        "status IN ('canonical', 'deprecated')",
    )


def downgrade() -> None:
    # 旧代码不认识 status：保留 deprecated 行会让已删除的事件重新出现，
    # 因此按旧语义把它们真正删除后再去掉列。
    op.execute("DELETE FROM events WHERE status = 'deprecated'")
    op.drop_constraint("ck_events_status", "events", type_="check")
    op.drop_column("events", "status")
