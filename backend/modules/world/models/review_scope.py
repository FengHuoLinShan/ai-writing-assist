"""Frozen author review membership; domain changes keep their own receipts."""

from sqlalchemy import JSON, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class WorldEntityReviewScope(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "world_entity_review_scopes"
    __table_args__ = (UniqueConstraint("novel_id", "operation_id"),)

    operation_id: Mapped[str] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    members_json: Mapped[list] = mapped_column(JSON, default=list)
    decisions_json: Mapped[dict] = mapped_column(JSON, default=dict)
