"""Add public browser accounts, identities, sessions, OTPs, and project ownership.

Revision ID: 20260723_account_system
Revises: 20260722_scene_memory
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260723_account_system"
down_revision = "20260722_scene_memory"
branch_labels = None
depends_on = None

BOOTSTRAP_ID = "00000000-0000-0000-0000-000000000000"


def _uuid_type():
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    guid = _uuid_type()
    op.create_table(
        "accounts",
        sa.Column("id", guid, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("support_code", sa.String(32), nullable=False),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_claimed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'pending_deletion', 'banned')",
            name="ck_accounts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_status", "accounts", ["status"])
    op.create_index("ix_accounts_support_code", "accounts", ["support_code"], unique=True)
    op.create_index("ix_accounts_purge_after", "accounts", ["purge_after"])
    op.execute(
        sa.text(
            "INSERT INTO accounts "
            "(id, status, support_code, created_at, updated_at) "
            "VALUES (:id, 'active', 'LEGACY-000000', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"
        ).bindparams(id=BOOTSTRAP_ID)
    )

    op.create_table(
        "account_identities",
        sa.Column("id", guid, nullable=False),
        sa.Column("account_id", guid, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "issuer", "subject", name="uq_account_identity_subject"
        ),
    )
    op.create_index(
        "ix_account_identities_account_id",
        "account_identities",
        ["account_id"],
        unique=True,
    )

    op.create_table(
        "web_sessions",
        sa.Column("id", guid, nullable=False),
        sa.Column("account_id", guid, nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("csrf_digest", sa.String(64), nullable=False),
        sa.Column("identity_type", sa.String(32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reauthenticated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_web_sessions_account_id", "web_sessions", ["account_id"])
    op.create_index(
        "ix_web_sessions_token_digest",
        "web_sessions",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_web_sessions_account_active",
        "web_sessions",
        ["account_id", "revoked_at"],
    )
    op.create_index(
        "ix_web_sessions_idle_expires_at", "web_sessions", ["idle_expires_at"]
    )
    op.create_index(
        "ix_web_sessions_absolute_expires_at",
        "web_sessions",
        ["absolute_expires_at"],
    )

    op.create_table(
        "email_login_challenges",
        sa.Column("id", guid, nullable=False),
        sa.Column("email_digest", sa.String(64), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("account_id", guid, nullable=True),
        sa.Column("peer_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "purpose IN ('login', 'reauth')",
            name="ck_email_login_challenge_purpose",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_login_challenges_email_digest",
        "email_login_challenges",
        ["email_digest"],
    )
    op.create_index(
        "ix_email_login_challenges_account_id",
        "email_login_challenges",
        ["account_id"],
    )
    op.create_index(
        "ix_email_login_challenges_expires_at",
        "email_login_challenges",
        ["expires_at"],
    )
    op.create_index(
        "ix_email_challenge_rate_window",
        "email_login_challenges",
        ["email_digest", "created_at"],
    )

    op.create_table(
        "account_security_events",
        sa.Column("id", guid, nullable=False),
        sa.Column("account_id", guid, nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("peer_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_security_events_account_id",
        "account_security_events",
        ["account_id"],
    )
    op.create_index(
        "ix_account_security_events_event_type",
        "account_security_events",
        ["event_type"],
    )
    op.create_index(
        "ix_account_security_events_created_at",
        "account_security_events",
        ["created_at"],
    )

    op.create_table(
        "account_consents",
        sa.Column("id", guid, nullable=False),
        sa.Column("account_id", guid, nullable=False),
        sa.Column("policy_type", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "policy_type", "version", name="uq_account_consent_version"
        ),
    )
    op.create_index("ix_account_consents_account_id", "account_consents", ["account_id"])

    op.add_column(
        "projects",
        sa.Column("owner_id", guid, nullable=True, server_default=BOOTSTRAP_ID),
    )
    op.execute(
        sa.text("UPDATE projects SET owner_id = :id WHERE owner_id IS NULL").bindparams(
            id=BOOTSTRAP_ID
        )
    )
    op.alter_column("projects", "owner_id", nullable=False, server_default=None)
    op.create_foreign_key(
        "fk_projects_owner_id_accounts",
        "projects",
        "accounts",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    for table in ("global_llm_defaults", "global_author_preferences"):
        op.create_foreign_key(
            f"fk_{table}_owner_id_accounts",
            table,
            "accounts",
            ["owner_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table in ("global_author_preferences", "global_llm_defaults"):
        op.drop_constraint(f"fk_{table}_owner_id_accounts", table, type_="foreignkey")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_id_accounts", "projects", type_="foreignkey")
    op.drop_column("projects", "owner_id")
    op.drop_table("account_consents")
    op.drop_table("account_security_events")
    op.drop_table("email_login_challenges")
    op.drop_table("web_sessions")
    op.drop_table("account_identities")
    op.drop_table("accounts")
