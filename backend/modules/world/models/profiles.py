"""Worldbuilding profile ORM models."""

from __future__ import annotations

from .common import (
    JSON,
    PG_UUID,
    Base,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    Mapped,
    StatusMixin,
    String,
    Text,
    TimestampMixin,
    UniqueConstraint,
    UUIDMixin,
    mapped_column,
    uuid,
)

# ============================================================
# Worldbuilding profiles — 世界观强类型 / 通用档案
# ============================================================


class _ProfileMixin(TimestampMixin, StatusMixin):
    """Common fields for worldbuilding profile tables."""

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extra_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class SpeciesProfile(Base, _ProfileMixin):
    __tablename__ = "species_profiles"
    __table_args__ = {"comment": "种族/物种档案"}

    origin_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    physiology_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifespan: Mapped[str | None] = mapped_column(String(128), nullable=True)
    abilities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weaknesses_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    culture_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FactionProfile(Base, _ProfileMixin):
    __tablename__ = "faction_profiles"
    __table_args__ = {"comment": "势力/阵营档案"}

    ideology_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    leader_entity_ids_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    member_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    territory_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resources_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    public_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LocationProfile(Base, _ProfileMixin):
    __tablename__ = "location_profiles"
    __table_args__ = {"comment": "地点档案"}

    map_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    climate: Mapped[str | None] = mapped_column(String(128), nullable=True)
    population_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    resources_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    hazards_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    controlling_faction_ids_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )


class RuleProfile(Base, _ProfileMixin):
    __tablename__ = "rule_profiles"
    __table_args__ = {"comment": "世界规则档案"}

    rule_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    principle_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exceptions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consequences_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ItemProfile(Base, _ProfileMixin):
    __tablename__ = "item_profiles"
    __table_args__ = {"comment": "重要物品档案"}

    item_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    powers_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    limitations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    owner_entity_ids_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    origin_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SecretProfile(Base, _ProfileMixin):
    __tablename__ = "secret_profiles"
    __table_args__ = {"comment": "秘密/伏笔档案"}

    truth_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    holder_entity_ids_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    reveal_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unrevealed",
    )
    linked_target_refs_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )


class EntityProfileTemplate(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "entity_profile_templates"
    __table_args__ = (
        UniqueConstraint("novel_id", "profile_type", name="uq_profile_template_type"),
        UniqueConstraint("novel_id", "id", name="uq_profile_template_novel_id"),
        {"comment": "通用世界资产模板"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_type: Mapped[str] = mapped_column(String(64), nullable=False)
    template_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    display_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class GenericEntityProfile(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "generic_entity_profiles"
    __table_args__ = (
        UniqueConstraint("novel_id", "entity_id", name="uq_generic_profile_entity"),
        {"comment": "通用世界资产档案"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("entity_profile_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extra_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
