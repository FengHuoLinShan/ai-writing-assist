"""Worldbuilding Workspace schema：画像、世界书页面、知识图谱、分类。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.schemas._common import UuidStr

# Worldbuilding Workspace v1
# ============================================================


class TargetRefSchema(BaseModel):
    """Worldbuilding TargetRef wire shape."""

    target_type: str = Field(..., min_length=1, max_length=64)
    target_id: str = Field(..., min_length=1, max_length=255)
    target_path: str = Field(default="", max_length=512)
    relation: Literal["requires", "informs", "derives", "conflicts"] = "informs"


class WorldProfileUpsertRequest(BaseModel):
    """Create or update a strong/generic worldbuilding profile."""

    status: str = Field(default="draft", max_length=32)
    source: str = Field(default="manual", max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    extra_json: dict[str, Any] = Field(default_factory=dict)
    data_json: dict[str, Any] | None = Field(default=None)

    origin_summary: str | None = None
    physiology_summary: str | None = None
    lifespan: str | None = None
    abilities_json: list[dict[str, Any]] | None = None
    weaknesses_json: list[dict[str, Any]] | None = None
    culture_summary: str | None = None
    language_summary: str | None = None
    public_baseline: bool | None = None

    ideology_summary: str | None = None
    leader_entity_ids_json: list[str] | None = None
    member_rules: str | None = None
    territory_refs_json: list[dict[str, Any]] | None = None
    resources_json: list[dict[str, Any]] | None = None

    map_refs_json: list[dict[str, Any]] | None = None
    climate: str | None = None
    population_summary: str | None = None
    hazards_json: list[dict[str, Any]] | None = None
    controlling_faction_ids_json: list[str] | None = None

    rule_domain: str | None = None
    principle_summary: str | None = None
    constraints_json: list[dict[str, Any]] | None = None
    exceptions_json: list[dict[str, Any]] | None = None
    consequences_json: list[dict[str, Any]] | None = None

    item_class: str | None = None
    powers_json: list[dict[str, Any]] | None = None
    limitations_json: list[dict[str, Any]] | None = None
    owner_entity_ids_json: list[str] | None = None

    truth_summary: str | None = None
    holder_entity_ids_json: list[str] | None = None
    risk_level: str | None = None
    reveal_status: str | None = None
    linked_target_refs_json: list[dict[str, Any]] | None = None


class WorldProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    novel_id: str
    entity_type: str
    profile_kind: str
    status: str
    source: str = "manual"
    confidence: float | None = None
    evidence_refs_json: list = Field(default_factory=list)
    extra_json: dict = Field(default_factory=dict)
    data_json: dict | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldProfileListResponse(BaseModel):
    items: list[WorldProfileResponse]
    total: int


class WorldProfileMigrateResponse(BaseModel):
    entity_id: str
    migrated: bool
    profile: WorldProfileResponse


class WorldBibleSection(BaseModel):
    section_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    section_type: Literal["markdown", "checklist", "asset_collection"] = "markdown"
    title: str = Field(..., min_length=1, max_length=120)
    body_markdown: str = Field(default="", max_length=30000)
    sort_order: int = Field(default=0, ge=-100000, le=100000)
    linked_asset_ref_hashes: list[str] = Field(default_factory=list, max_length=100)
    projection_policy: Literal["eligible", "excluded"] = "eligible"
    sensitivity_hint: Literal[
        "author_only",
        "author_safe",
        "public_baseline",
    ] = "author_safe"

    @field_validator("linked_asset_ref_hashes")
    @classmethod
    def validate_ref_hashes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            current = str(value).strip().removeprefix("sha256:")
            if len(current) != 64 or any(ch not in "0123456789abcdef" for ch in current):
                raise ValueError(
                    "linked asset ref hashes must be lowercase sha256 values"
                )
            if current not in normalized:
                normalized.append(current)
        return normalized


def _validate_world_bible_sections(
    sections: list[WorldBibleSection],
) -> list[WorldBibleSection]:
    ids = [section.section_id for section in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("World Bible section_id must be unique within a page")
    return sorted(sections, key=lambda item: (item.sort_order, item.section_id))


_FORBIDDEN_PAGE_TEMPLATE_KEYS = frozenset(
    {
        "api_key",
        "depth",
        "macro",
        "outlet",
        "prompt",
        "provider",
        "role",
        "system",
        "tool",
        "tools",
    }
)


def _reject_executable_template_values(value: Any, *, path: str = "template") -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_PAGE_TEMPLATE_KEYS:
                raise ValueError(f"{path}.{key} is not allowed in a page template")
            _reject_executable_template_values(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_executable_template_values(child, path=f"{path}[{index}]")
    return value


class WorldBiblePageCreate(BaseModel):
    novel_id: str
    page_type: str = Field(default="custom", max_length=64)
    page_key: str | None = Field(default=None, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    status: str = Field(default="draft", max_length=32)
    page_meta_json: dict[str, Any] = Field(default_factory=dict)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    activation_defaults_json: dict[str, Any] = Field(default_factory=dict)
    template_key: str | None = Field(default=None, max_length=128)
    sort_order: int = 0
    created_by: str | None = Field(default=None, max_length=64)

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection],
    ) -> list[WorldBibleSection]:
        return _validate_world_bible_sections(value)


class WorldBiblePageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, max_length=32)
    page_meta_json: dict[str, Any] | None = None
    free_text: str | None = None
    sections_json: list[WorldBibleSection] | None = Field(default=None, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] | None = None
    activation_defaults_json: dict[str, Any] | None = None
    template_key: str | None = Field(default=None, max_length=128)
    sort_order: int | None = None
    updated_by: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBiblePageUpdate:
        for field_name in {
            "title",
            "status",
            "page_meta_json",
            "linked_asset_refs_json",
            "activation_defaults_json",
            "sections_json",
            "sort_order",
        }:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection] | None,
    ) -> list[WorldBibleSection] | None:
        return None if value is None else _validate_world_bible_sections(value)


class WorldBibleValidationReceipt(BaseModel):
    scope: Literal["targeted", "domain_full"]
    scope_label: str
    source_version: int = Field(..., ge=1)
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    impact_scope_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime


class WorldBiblePageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UuidStr
    novel_id: UuidStr
    page_type: str
    page_key: str
    title: str
    status: str
    page_meta_json: dict = Field(default_factory=dict)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list)
    linked_asset_refs_json: list = Field(default_factory=list)
    activation_defaults_json: dict = Field(default_factory=dict)
    template_key: str | None = None
    template_version: int = 1
    version_number: int = 1
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    validation_receipt: WorldBibleValidationReceipt | None = None


class WorldBiblePageListResponse(BaseModel):
    items: list[WorldBiblePageResponse]
    total: int


class WorldKnowledgeGraphNode(BaseModel):
    id: str
    kind: Literal["world_bible_page", "core_entity"]
    label: str
    status: str


class WorldKnowledgeGraphEdge(BaseModel):
    relation_type: str | None = None
    id: str
    kind: Literal["page_reference", "page_entity_reference", "entity_relation"]
    source_id: str
    target_id: str
    status: str = "canonical"
    authority: str | None = None
    source_ref: dict[str, str] | None = None
    revision: int | None = None
    source_hash: str | None = None
    provenance: dict[str, Any] | None = None
    via_relation_id: str | None = None
    dependency_relation: Literal["requires", "informs", "derives", "conflicts"] | None = (
        None
    )


class WorldKnowledgeGraphResponse(BaseModel):
    nodes: list[WorldKnowledgeGraphNode] = Field(default_factory=list)
    edges: list[WorldKnowledgeGraphEdge] = Field(default_factory=list)
    truncated: bool = False
    truncation_reasons: list[str] = Field(default_factory=list)
    omitted_counts: dict[str, int] = Field(default_factory=dict)
    source_manifest: list[dict[str, str]] = Field(default_factory=list)
    source_hash: str
    dependency_coverage: bool = False
    note: str = "Relationships are associations, not change-impact dependencies."


class WorldBibleCategoryCreate(BaseModel):
    novel_id: str
    category_key: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str = Field(default="#64748B", pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str = Field(default="", max_length=16)
    sort_order: int = 100
    default_template_key: str | None = Field(default=None, max_length=128)


class WorldBibleCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None
    status: Literal["active", "archived"] | None = None
    default_template_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBibleCategoryUpdate:
        for field_name in {"name", "color", "icon", "sort_order", "status"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WorldBibleCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UuidStr
    novel_id: UuidStr
    category_key: str
    name: str
    description: str | None = None
    color: str
    icon: str
    sort_order: int
    status: str
    builtin: bool = False
    default_template_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldBibleCategoryListResponse(BaseModel):
    items: list[WorldBibleCategoryResponse]
