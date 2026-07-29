"""Add isolated RP interaction projects and immutable journey history.

Revision ID: 20260728_interaction
Revises: 20260728_account_llm
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260728_interaction"
down_revision = "20260728_account_llm"
branch_labels = None
depends_on = None


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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    project_columns = {
        item["name"] for item in inspector.get_columns("projects")
    }
    if "project_kind" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "project_kind",
                sa.String(32),
                nullable=False,
                server_default="author",
            ),
        )
    if "ix_projects_project_kind" not in {
        item["name"] for item in sa.inspect(bind).get_indexes("projects")
    }:
        op.create_index("ix_projects_project_kind", "projects", ["project_kind"])
    project_checks = {
        item["name"]
        for item in sa.inspect(bind).get_check_constraints("projects")
    }
    if (
        bind.dialect.name == "postgresql"
        and "ck_projects_project_kind" not in project_checks
    ):
        op.create_check_constraint(
            "ck_projects_project_kind",
            "projects",
            "project_kind IN ('author', 'interaction')",
        )

    expected_tables = {
        "interaction_journeys",
        "interaction_message_nodes",
        "interaction_branch_selections",
        "interaction_generation_attempts",
        "interaction_summary_segments",
        "interaction_overview_revisions",
        "interaction_account_preferences",
    }
    existing_tables = expected_tables & set(
        sa.inspect(bind).get_table_names()
    )
    if existing_tables == expected_tables:
        # Databases initialized by the former live-ORM baseline already contain
        # the interaction tables. Add columns introduced while this still-
        # unreleased migration was under review before treating it as current.
        journey_columns = {
            item["name"]
            for item in sa.inspect(bind).get_columns("interaction_journeys")
        }
        if "overview_failure" not in journey_columns:
            op.add_column(
                "interaction_journeys",
                sa.Column(
                    "overview_failure",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                ),
            )
        revision_columns = {
            item["name"]
            for item in sa.inspect(bind).get_columns(
                "interaction_overview_revisions"
            )
        }
        if "coverage_anchor_node_id" not in revision_columns:
            op.add_column(
                "interaction_overview_revisions",
                sa.Column("coverage_anchor_node_id", guid, nullable=True),
            )
        if "coverage_path_hash" not in revision_columns:
            op.add_column(
                "interaction_overview_revisions",
                sa.Column(
                    "coverage_path_hash",
                    sa.String(64),
                    nullable=True,
                ),
            )
        segment_columns = {
            item["name"]
            for item in sa.inspect(bind).get_columns(
                "interaction_summary_segments"
            )
        }
        if "based_on_overview_revision_id" not in segment_columns:
            op.add_column(
                "interaction_summary_segments",
                sa.Column(
                    "based_on_overview_revision_id",
                    guid,
                    nullable=True,
                ),
            )
        if "based_on_checkpoint_revision_id" not in segment_columns:
            op.add_column(
                "interaction_summary_segments",
                sa.Column(
                    "based_on_checkpoint_revision_id",
                    guid,
                    nullable=True,
                ),
            )
        return
    if existing_tables:
        names = ", ".join(sorted(existing_tables))
        raise RuntimeError(
            "partial interaction schema found before migration: "
            f"{names}"
        )

    op.create_table(
        "interaction_journeys",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("owner_id", guid, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("title_source", sa.String(16), nullable=False),
        sa.Column("opening_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("see_sea_enabled", sa.Boolean(), nullable=False),
        sa.Column("action_options_enabled", sa.Boolean(), nullable=False),
        sa.Column("setup_clarification_used", sa.Boolean(), nullable=False),
        sa.Column(
            "see_sea_last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("selected_leaf_node_id", guid, nullable=True),
        sa.Column("selection_epoch", sa.Integer(), nullable=False),
        sa.Column("overview_head_revision_id", guid, nullable=True),
        sa.Column("overview_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "overview_failure",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "latest_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_interaction_journey_status",
        ),
        sa.CheckConstraint(
            "title_source IN ('fallback', 'model', 'manual')",
            name="ck_interaction_journey_title_source",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interaction_journeys_novel_id",
        "interaction_journeys",
        ["novel_id"],
        unique=True,
    )
    op.create_index(
        "ix_interaction_journeys_owner_id",
        "interaction_journeys",
        ["owner_id"],
    )
    op.create_index(
        "ix_interaction_journey_owner_status_activity",
        "interaction_journeys",
        ["owner_id", "status", "latest_activity_at"],
    )

    op.create_table(
        "interaction_message_nodes",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("journey_id", guid, nullable=False),
        sa.Column("parent_node_id", guid, nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "message_kind",
            sa.String(16),
            nullable=False,
            server_default="story",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("completion_state", sa.String(16), nullable=False),
        sa.Column("end_reason", sa.String(64), nullable=True),
        sa.Column("branch_hint", sa.String(40), nullable=True),
        sa.Column(
            "story_ended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("action_suggestions", sa.JSON(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("origin_attempt_id", guid, nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_interaction_message_role",
        ),
        sa.CheckConstraint(
            "message_kind IN ('setup', 'story')",
            name="ck_interaction_message_kind",
        ),
        sa.CheckConstraint(
            "completion_state IN ('complete', 'partial')",
            name="ck_interaction_message_completion",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["interaction_journeys.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_node_id"],
            ["interaction_message_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("origin_attempt_id"),
    )
    op.create_index(
        "ix_interaction_message_nodes_novel_id",
        "interaction_message_nodes",
        ["novel_id"],
    )
    op.create_index(
        "ix_interaction_message_nodes_journey_id",
        "interaction_message_nodes",
        ["journey_id"],
    )
    op.create_index(
        "ix_interaction_message_nodes_parent_node_id",
        "interaction_message_nodes",
        ["parent_node_id"],
    )
    op.create_index(
        "ix_interaction_message_journey_created",
        "interaction_message_nodes",
        ["journey_id", "created_at", "id"],
    )
    op.create_index(
        "ix_interaction_message_parent_created",
        "interaction_message_nodes",
        ["journey_id", "parent_node_id", "created_at"],
    )

    op.create_table(
        "interaction_branch_selections",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("journey_id", guid, nullable=False),
        sa.Column("parent_node_id", guid, nullable=True),
        sa.Column("parent_key", sa.String(36), nullable=False),
        sa.Column("selected_child_node_id", guid, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["interaction_journeys.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_node_id"],
            ["interaction_message_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_child_node_id"],
            ["interaction_message_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "journey_id",
            "parent_key",
            name="uq_interaction_selected_child",
        ),
    )
    op.create_index(
        "ix_interaction_branch_selections_novel_id",
        "interaction_branch_selections",
        ["novel_id"],
    )
    op.create_index(
        "ix_interaction_branch_selections_journey_id",
        "interaction_branch_selections",
        ["journey_id"],
    )

    op.create_table(
        "interaction_generation_attempts",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("journey_id", guid, nullable=False),
        sa.Column("owner_id", guid, nullable=False),
        sa.Column("response_to_node_id", guid, nullable=False),
        sa.Column("task_id", guid, nullable=True),
        sa.Column("result_node_id", guid, nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_selection_epoch", sa.Integer(), nullable=False),
        sa.Column("visible_text", sa.Text(), nullable=False),
        sa.Column("visible_offset", sa.Integer(), nullable=False),
        sa.Column("metadata_text", sa.Text(), nullable=False),
        sa.Column("finish_reason", sa.String(64), nullable=True),
        sa.Column("error_kind", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column("llm_execution_snapshot", sa.JSON(), nullable=False),
        sa.Column("context_path_hash", sa.String(64), nullable=False),
        sa.Column("context_node_ids", sa.JSON(), nullable=False),
        sa.Column("reference_node_ids", sa.JSON(), nullable=False),
        sa.Column("continuation_count", sa.Integer(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("last_checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN "
            "('pending', 'preparing_context', 'running', "
            "'awaiting_continue', 'completed', "
            "'failed', 'cancelled', 'stopped')",
            name="ck_interaction_attempt_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["interaction_journeys.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["response_to_node_id"],
            ["interaction_message_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint("result_node_id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_interaction_attempt_idempotency",
        ),
    )
    for column in ("novel_id", "journey_id", "owner_id", "response_to_node_id"):
        op.create_index(
            f"ix_interaction_generation_attempts_{column}",
            "interaction_generation_attempts",
            [column],
        )
    op.create_index(
        "ix_interaction_attempt_owner_active",
        "interaction_generation_attempts",
        ["owner_id", "status"],
    )
    op.create_index(
        "ix_interaction_attempt_journey_created",
        "interaction_generation_attempts",
        ["journey_id", "created_at"],
    )

    op.create_table(
        "interaction_summary_segments",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("journey_id", guid, nullable=False),
        sa.Column("start_node_id", guid, nullable=False),
        sa.Column("end_node_id", guid, nullable=False),
        sa.Column("path_hash", sa.String(64), nullable=False),
        sa.Column("based_on_overview_revision_id", guid, nullable=True),
        sa.Column("based_on_checkpoint_revision_id", guid, nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("producer", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["interaction_journeys.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "journey_id",
            "path_hash",
            "end_node_id",
            name="uq_interaction_summary_path_end",
        ),
    )
    op.create_index(
        "ix_interaction_summary_segments_novel_id",
        "interaction_summary_segments",
        ["novel_id"],
    )
    op.create_index(
        "ix_interaction_summary_segments_journey_id",
        "interaction_summary_segments",
        ["journey_id"],
    )
    op.create_index(
        "ix_interaction_summary_segments_path_hash",
        "interaction_summary_segments",
        ["path_hash"],
    )

    op.create_table(
        "interaction_overview_revisions",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("journey_id", guid, nullable=False),
        sa.Column("anchor_node_id", guid, nullable=False),
        sa.Column("path_hash", sa.String(64), nullable=False),
        sa.Column("coverage_anchor_node_id", guid, nullable=True),
        sa.Column("coverage_path_hash", sa.String(64), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("based_on_revision_id", guid, nullable=True),
        sa.Column("started_overview_epoch", sa.Integer(), nullable=False),
        sa.Column("promoted", sa.Boolean(), nullable=False),
        sa.Column("producer", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source IN ('automatic', 'manual')",
            name="ck_interaction_overview_source",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["journey_id"],
            ["interaction_journeys.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interaction_overview_revisions_novel_id",
        "interaction_overview_revisions",
        ["novel_id"],
    )
    op.create_index(
        "ix_interaction_overview_revisions_journey_id",
        "interaction_overview_revisions",
        ["journey_id"],
    )
    op.create_index(
        "ix_interaction_overview_journey_created",
        "interaction_overview_revisions",
        ["journey_id", "created_at"],
    )

    op.create_table(
        "interaction_account_preferences",
        sa.Column("id", guid, nullable=False),
        sa.Column("owner_id", guid, nullable=False),
        sa.Column(
            "see_sea_notice_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interaction_account_preferences_owner_id",
        "interaction_account_preferences",
        ["owner_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("interaction_account_preferences")
    op.drop_table("interaction_overview_revisions")
    op.drop_table("interaction_summary_segments")
    op.drop_table("interaction_generation_attempts")
    op.drop_table("interaction_branch_selections")
    op.drop_table("interaction_message_nodes")
    op.drop_table("interaction_journeys")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "ck_projects_project_kind",
            "projects",
            type_="check",
        )
    op.drop_index("ix_projects_project_kind", table_name="projects")
    op.drop_column("projects", "project_kind")
