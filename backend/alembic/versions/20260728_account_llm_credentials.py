"""Add account LLM credentials and remove legacy project API keys.

Revision ID: 20260728_account_llm
Revises: 20260724_task_owners
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260728_account_llm"
down_revision = "20260724_task_owners"
branch_labels = None
depends_on = None


def _uuid_type():
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _strip_project_llm_secrets(value: Any) -> tuple[dict, bool]:
    settings = dict(value) if isinstance(value, dict) else {}
    raw_llm = settings.get("llm")
    if not isinstance(raw_llm, dict):
        return settings, False
    llm = dict(raw_llm)
    changed = False
    for field_name in ("api_key", "api_keys_by_provider"):
        if field_name in llm:
            llm.pop(field_name, None)
            changed = True
    if changed:
        settings["llm"] = llm
    return settings, changed


def upgrade() -> None:
    guid = _uuid_type()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("account_llm_credentials"):
        op.create_table(
            "account_llm_credentials",
            sa.Column("id", guid, nullable=False),
            sa.Column("owner_id", guid, nullable=False),
            sa.Column("provider_id", sa.String(64), nullable=False),
            sa.Column("encrypted_api_key", sa.JSON(), nullable=False),
            sa.Column("key_fingerprint", sa.String(64), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["accounts.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "provider_id",
                name="uq_account_llm_credential_owner_provider",
            ),
        )
        op.create_index(
            "ix_account_llm_credentials_owner_id",
            "account_llm_credentials",
            ["owner_id"],
        )
    elif "ix_account_llm_credentials_owner_id" not in {
        item["name"]
        for item in inspector.get_indexes("account_llm_credentials")
    }:
        op.create_index(
            "ix_account_llm_credentials_owner_id",
            "account_llm_credentials",
            ["owner_id"],
        )

    projects = sa.table(
        "projects",
        sa.column("id", guid),
        sa.column("settings", sa.JSON()),
    )
    rows = bind.execute(sa.select(projects.c.id, projects.c.settings)).all()
    for row in rows:
        cleaned, changed = _strip_project_llm_secrets(row.settings)
        if changed:
            bind.execute(
                projects.update()
                .where(projects.c.id == row.id)
                .values(settings=cleaned)
            )


def downgrade() -> None:
    # Deleted project secrets are intentionally not reconstructable.
    op.drop_index(
        "ix_account_llm_credentials_owner_id",
        table_name="account_llm_credentials",
    )
    op.drop_table("account_llm_credentials")
