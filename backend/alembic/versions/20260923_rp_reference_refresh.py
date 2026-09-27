"""Allow immutable RP reference revisions for unchanged manuscript versions."""

from alembic import op

revision = "20260923_rp_reference_refresh"
down_revision = "20260922_evolution_reading"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "uq_interaction_source_revision_manifest",
        "interaction_source_revisions",
        type_="unique",
    )
    op.create_index(
        "ix_interaction_source_revision_manifest",
        "interaction_source_revisions",
        ["source_novel_id", "manifest_hash"],
    )


def downgrade():
    # Existing repeated manifests must never be deleted to make rollback pass.
    op.create_unique_constraint(
        "uq_interaction_source_revision_manifest",
        "interaction_source_revisions",
        ["source_novel_id", "manifest_hash"],
    )
    op.drop_index(
        "ix_interaction_source_revision_manifest",
        table_name="interaction_source_revisions",
    )
