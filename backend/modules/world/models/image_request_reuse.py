"""Image request reuse registry (B9 idempotent image generation).

One row per (novel, request content) hash: the object key of an already
generated asset that an identical request may reuse instead of calling the
provider again. The hash always includes the tenant dimension (novel +
owner); lookups always filter ``novel_id`` so reuse can never leak across
projects.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary

from .common import (
    Base,
    Integer,
    Mapped,
    NovelMixin,
    String,
    TimestampMixin,
    UUIDMixin,
    mapped_column,
    uuid,
)

_SOURCES = ("map_atlas", "world_object")


class ImageRequestReuse(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Reusable asset for an identical image request (provider-idempotency)."""

    __tablename__ = "image_request_reuse"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('" + "', '".join(_SOURCES) + "')",
            name="ck_image_request_reuse_source_type",
        ),
        Index(
            "uq_image_request_reuse_novel_hash",
            "novel_id",
            "request_hash",
            unique=True,
        ),
        {"comment": "图片请求幂等复用登记（B9）"},
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    asset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_from_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reuse_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
