"""Execution, immutable experiments and receipts; never canonical story data."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin, UUIDType


def scoped_fk(field, table, *, delete="CASCADE"):
    return ForeignKeyConstraint(
        ["novel_id", field], [f"{table}.novel_id", f"{table}.id"], ondelete=delete
    )


class CollaborationCase(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "collaboration_cases"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "operation_id"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("accounts.id"))
    operation_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    request_hash: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str] = mapped_column(Text)
    goal_version: Mapped[int] = mapped_column(Integer, default=1)
    constraints_json: Mapped[list] = mapped_column(JSON, default=list)
    goal_history_json: Mapped[list] = mapped_column(JSON, default=list)
    grant_history_json: Mapped[list] = mapped_column(JSON, default=list)
    grant_json: Mapped[dict] = mapped_column(JSON)
    recipe_json: Mapped[dict] = mapped_column(JSON)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="active")


class CollaborationRun(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "collaboration_runs"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "operation_id"),
        scoped_fk("case_id", "collaboration_cases"),
        ForeignKeyConstraint(
            ["novel_id", "task_id"], ["async_tasks.novel_id", "async_tasks.id"]
        ),
        CheckConstraint(
            "status IN ('pending','running','completed','partial','failed',"
            "'cancelled','budget_exceeded')"
        ),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    operation_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSON)
    manifest_json: Mapped[dict] = mapped_column(JSON)
    llm_snapshot_json: Mapped[dict] = mapped_column(JSON)
    budget_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_revision: Mapped[int] = mapped_column(Integer, default=0)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(100))


class CreativeWorkspace(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "creative_workspaces"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "operation_id"),
        scoped_fk("case_id", "collaboration_cases"),
        scoped_fk("parent_id", "creative_workspaces", delete=None),
        ForeignKeyConstraint(
            ["novel_id", "current_revision_id"],
            ["creative_workspace_revisions.novel_id", "creative_workspace_revisions.id"],
            name="fk_creative_workspace_current",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    operation_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    label: Mapped[str] = mapped_column(String(200))
    baseline_json: Mapped[dict] = mapped_column(JSON)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    status: Mapped[str] = mapped_column(String(24), default="open")


class CreativeWorkspaceRevision(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "creative_workspace_revisions"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("workspace_id", "sequence"),
        scoped_fk("workspace_id", "creative_workspaces"),
        scoped_fk("parent_revision_id", "creative_workspace_revisions", delete=None),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    sequence: Mapped[int] = mapped_column(Integer)
    goal_version: Mapped[int] = mapped_column(Integer)
    patches_json: Mapped[list] = mapped_column(JSON)
    manifest_json: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))


class CollaborationArtifact(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "collaboration_artifacts"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        scoped_fk("run_id", "collaboration_runs"),
        scoped_fk("workspace_revision_id", "creative_workspace_revisions", delete=None),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    workspace_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    kind: Mapped[str] = mapped_column(String(32))
    manifest_json: Mapped[dict] = mapped_column(JSON)
    payload_json: Mapped[dict] = mapped_column(JSON)
    output_hash: Mapped[str] = mapped_column(String(64))


class CollaborationWorkItem(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "collaboration_work_items"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("run_id", "logical_key", "generation"),
        scoped_fk("run_id", "collaboration_runs"),
        scoped_fk("output_id", "collaboration_artifacts", delete=None),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','blocked',"
            "'cancelled','superseded')"
        ),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    logical_key: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    proposal_json: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    output_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    error_code: Mapped[str | None] = mapped_column(String(100))


class CreativeMergeReceipt(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "creative_merge_receipts"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "operation_id"),
        UniqueConstraint("revision_id"),
        scoped_fk("revision_id", "creative_workspace_revisions", delete=None),
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    operation_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    request_hash: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    authorizer_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("accounts.id"))
    authorization: Mapped[str] = mapped_column(String(32))
    results_json: Mapped[list] = mapped_column(JSON)


class DomainOutbox(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "domain_outbox"
    __table_args__ = (
        UniqueConstraint("receipt_id"),
        scoped_fk("receipt_id", "creative_merge_receipts"),
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    payload_json: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
