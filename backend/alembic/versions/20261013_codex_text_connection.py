"""Allow verified local Codex connections without a fabricated API secret."""

import sqlalchemy as sa

from alembic import op

revision = "20261013_codex_text_connection"
down_revision = "20261010_evolution_source_epoch"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "account_llm_credentials",
        "encrypted_api_key",
        existing_type=sa.JSON(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_account_llm_connection_secret",
        "account_llm_credentials",
        "(provider_id = 'codex') = (encrypted_api_key IS NULL)",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM account_llm_credentials WHERE provider_id = 'codex'"
        )
    ):
        raise RuntimeError(
            "Disconnect Codex connections before downgrading; no credentials are deleted"
        )
    op.drop_constraint(
        "ck_account_llm_connection_secret", "account_llm_credentials", type_="check"
    )
    op.alter_column(
        "account_llm_credentials",
        "encrypted_api_key",
        existing_type=sa.JSON(),
        nullable=False,
    )
