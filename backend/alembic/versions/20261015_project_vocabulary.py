"""add project vocabulary immutable revisions

Revision ID: 20261015_project_vocabulary
Revises: 20261014_model_scope_budget
Create Date: 2026-10-15 14:20:24.168912
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261015_project_vocabulary"
down_revision: str | None = "20261014_model_scope_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_vocabulary_terms",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("redirect_to_id", sa.UUID(), nullable=True),
        sa.Column("author_confirmed", sa.Boolean(), nullable=False),
        sa.Column("preset_id", sa.String(length=48), nullable=True),
        sa.Column("preset_version", sa.Integer(), nullable=True),
        sa.Column("preset_item_key", sa.String(length=96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('space', 'level', 'feature', 'relation', 'transport', "
            "'traveler', 'access_condition', 'dossier_facing', 'faction_form', "
            "'territory_control')",
            name="ck_project_vocabulary_terms_kind",
        ),
        sa.CheckConstraint(
            "source IN ('author', 'model', 'preset')",
            name="ck_project_vocabulary_terms_source",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'emerging', 'archived', 'merged')",
            name="ck_project_vocabulary_terms_status",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "redirect_to_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_project_vocabulary_term_redirect_same_novel",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_project_vocabulary_terms_novel_id"
        ),
        sa.UniqueConstraint(
            "novel_id",
            "preset_id",
            "preset_version",
            "preset_item_key",
            name="uq_project_vocabulary_preset_item",
        ),
    )
    op.create_index(
        op.f("ix_project_vocabulary_terms_novel_id"),
        "project_vocabulary_terms",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_vocabulary_terms_novel_kind_status",
        "project_vocabulary_terms",
        ["novel_id", "kind", "status"],
        unique=False,
    )
    op.create_table(
        "project_vocabulary_revisions",
        sa.Column("term_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_project_vocabulary_revision_number"
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "term_id", "previous_revision_id"],
            [
                "project_vocabulary_revisions.novel_id",
                "project_vocabulary_revisions.term_id",
                "project_vocabulary_revisions.id",
            ],
            name="fk_project_vocabulary_revision_previous_same_novel",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "term_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_project_vocabulary_revision_term_same_novel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_project_vocabulary_revisions_novel_id"
        ),
        sa.UniqueConstraint(
            "novel_id", "term_id", "id", name="uq_project_vocabulary_revision_term_id"
        ),
        sa.UniqueConstraint(
            "novel_id",
            "term_id",
            "revision_number",
            name="uq_project_vocabulary_revision_number",
        ),
    )
    op.create_index(
        op.f("ix_project_vocabulary_revisions_novel_id"),
        "project_vocabulary_revisions",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_vocabulary_revisions_novel_term",
        "project_vocabulary_revisions",
        ["novel_id", "term_id", "revision_number"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_project_vocabulary_term_current_revision",
        "project_vocabulary_terms",
        "project_vocabulary_revisions",
        ["novel_id", "id", "current_revision_id"],
        ["novel_id", "term_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute("""CREATE FUNCTION reject_project_vocabulary_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE project_deleted boolean;
        BEGIN
        IF TG_OP = 'DELETE' THEN
            EXECUTE format(
                'SELECT NOT EXISTS (SELECT 1 FROM %I.projects WHERE id = $1)',
                TG_TABLE_SCHEMA
            ) INTO project_deleted USING OLD.novel_id;
            IF project_deleted THEN RETURN OLD; END IF;
        END IF;
        RAISE EXCEPTION 'project vocabulary history is immutable';
        END $$""")
    op.execute("""CREATE TRIGGER project_vocabulary_revisions_immutable
        BEFORE UPDATE OR DELETE ON project_vocabulary_revisions FOR EACH ROW
        EXECUTE FUNCTION reject_project_vocabulary_history_mutation()""")
    op.execute("""CREATE TRIGGER project_vocabulary_terms_preserve_history
        BEFORE DELETE ON project_vocabulary_terms FOR EACH ROW
        EXECUTE FUNCTION reject_project_vocabulary_history_mutation()""")


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM project_vocabulary_terms)"))
        .scalar()
    ):
        raise RuntimeError(
            "Project vocabulary history exists; downgrade would discard author data"
        )
    op.execute(
        "DROP TRIGGER project_vocabulary_terms_preserve_history "
        "ON project_vocabulary_terms"
    )
    op.execute(
        "DROP TRIGGER project_vocabulary_revisions_immutable "
        "ON project_vocabulary_revisions"
    )
    op.execute("DROP FUNCTION reject_project_vocabulary_history_mutation()")
    op.drop_constraint(
        "fk_project_vocabulary_term_current_revision",
        "project_vocabulary_terms",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_project_vocabulary_revisions_novel_term",
        table_name="project_vocabulary_revisions",
    )
    op.drop_index(
        op.f("ix_project_vocabulary_revisions_novel_id"),
        table_name="project_vocabulary_revisions",
    )
    op.drop_table("project_vocabulary_revisions")
    op.drop_index(
        "ix_project_vocabulary_terms_novel_kind_status",
        table_name="project_vocabulary_terms",
    )
    op.drop_index(
        op.f("ix_project_vocabulary_terms_novel_id"),
        table_name="project_vocabulary_terms",
    )
    op.drop_table("project_vocabulary_terms")
