"""Evolution 持久化模型：run 注册表、冻结尝试与回执（V4 E04）。

- ``evolution_runs``：理解推进的唯一运行注册表——owner epoch、游标
  （committed prefix）与根预算都在这里；同项目同时只有一个有效写入世代。
- ``evolution_frozen_attempts``：prepare 阶段冻结的窄批次负载（T10 恢复基础）。
- ``evolution_receipts``：已领域提交的回执（追加式，不更新不删除）；
  run head 指针与游标推进只在回执落库的同一事务内发生。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, UUIDMixin

EVOLUTION_RUN_MODES = ("bootstrap", "append", "revise", "scoped_recompute")


class EvolutionRun(Base, UUIDMixin, NovelMixin):
    """一个项目的演化理解运行：owner epoch、游标与根预算的权威行。"""

    __tablename__ = "evolution_runs"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "run_key",
            name="uq_evolution_run_novel_key",
        ),
        {"comment": "演化理解运行注册表：owner epoch / 游标 / 根预算"},
    )

    run_key: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="bootstrap / append / revise / scoped_recompute",
    )
    owner_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="切换或重建时推进；旧 epoch 的 worker 无提交权",
    )
    active_engine: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="evolution",
        comment="当前有效引擎标识；E07 切换期区分 evolution/legacy",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        comment="active / drained / stopped",
    )
    committed_scene_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=-1,
        comment="已提交前缀游标：Scene 序号；-1 表示尚未提交任何 Scene",
    )
    committed_source_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    head_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="最新已提交回执对应的冻结尝试 ID",
    )
    budget_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="根预算总额（模型调用计次）；跨重试累计",
    )
    budget_remaining: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="剩余预算；原子预留（T21）后递减",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        default=lambda: datetime.now(UTC),
    )


class EvolutionFrozenAttempt(Base, UUIDMixin, NovelMixin):
    """prepare 阶段冻结的窄批次：模型返回后的完整待提交内容。"""

    __tablename__ = "evolution_frozen_attempts"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "run_key",
            "attempt_key",
            name="uq_evolution_frozen_attempt_key",
        ),
        {"comment": "演化窄提交冻结负载（T10 恢复基础）"},
    )

    run_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    attempt_key: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    producer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_receipt: Mapped[str | None] = mapped_column(String(120), nullable=True)
    previous_prefix_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="frozen",
        comment="frozen / applied / abandoned",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )


class EvolutionReceiptRecord(Base, UUIDMixin, NovelMixin):
    """已领域提交的回执：追加式记录，游标推进的依据。"""

    __tablename__ = "evolution_receipts"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "run_key",
            "attempt_key",
            name="uq_evolution_receipt_attempt",
        ),
        {"comment": "演化窄提交回执（T11 重放依据）"},
    )

    run_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    attempt_key: Mapped[str] = mapped_column(String(120), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    committed_scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
