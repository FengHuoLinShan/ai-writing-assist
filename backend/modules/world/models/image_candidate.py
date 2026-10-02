"""World object image generation candidates (local-CLI backed, ADR-0029)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary

from .common import (
    JSON,
    PG_UUID,
    Base,
    Index,
    Integer,
    Mapped,
    NovelMixin,
    String,
    Text,
    TimestampMixin,
    UUIDMixin,
    mapped_column,
    uuid,
)

_STATUSES = (
    "queued",
    "generating",
    "review_ready",
    "adopted",
    "discarded",
    "failed",
    "cancelled",
)


class WorldObjectImageCandidate(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One local-CLI generated image awaiting the author's adopt/discard review."""

    __tablename__ = "world_object_image_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('" + "', '".join(_STATUSES) + "')",
            name="ck_world_object_image_candidates_status",
        ),
        Index(
            "ix_world_object_image_candidates_novel_entity_created",
            "novel_id",
            "entity_id",
            "created_at",
        ),
        {"comment": "对象图片生成候选（本机 CLI，ADR-0029）"},
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    executor_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    adopted_image_version: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    request_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="入队时冻结的幂等键（B9）；完成登记复用，避免生成期间实体"
        "被编辑导致登记键漂移",
    )
