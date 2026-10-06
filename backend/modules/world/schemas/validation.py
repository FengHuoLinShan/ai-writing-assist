"""世界书校验策略、校验运行与影响预览 schema。"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from modules.world.schemas._common import (
    OptionalUuidStr,
    UuidStr,
    _optional_uuid_validator,
    _validate_lower_sha256,
)
from modules.world.schemas.bible import _validate_world_policy_regex


class WorldValidationFrontmatterSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list, max_length=128)
    optional: list[str] = Field(default_factory=list, max_length=128)
    field_types: dict[
        str,
        Literal[
            "string",
            "date",
            "number",
            "boolean",
            "object",
            "array",
            "array:string",
            "array:wikilink",
        ],
    ] = Field(default_factory=dict)
    enums: dict[str, list[str | int | float | bool]] = Field(default_factory=dict)
    patterns: dict[str, str] = Field(default_factory=dict)
    min_items: dict[str, int] = Field(default_factory=dict)
    required_items: dict[str, list[str]] = Field(default_factory=dict)
    unique_arrays: list[str] = Field(default_factory=list, max_length=128)
    source_prefixes: list[str] = Field(default_factory=list, max_length=32)
    title_matches_source_stem: bool = False
    unknown_fields: Literal["ignore", "warning", "error"] = "warning"

    @model_validator(mode="after")
    def validate_schema(self) -> WorldValidationFrontmatterSchema:
        collections = [
            self.required,
            self.optional,
            list(self.field_types),
            list(self.enums),
            list(self.patterns),
            list(self.min_items),
            list(self.required_items),
            self.unique_arrays,
        ]
        fields = [field for values in collections for field in values]
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", field) for field in fields):
            raise ValueError("frontmatter schema field names are invalid")
        if len(self.required) != len(set(self.required)) or len(self.optional) != len(
            set(self.optional)
        ):
            raise ValueError("frontmatter schema fields must be unique")
        if set(self.required) & set(self.optional):
            raise ValueError("frontmatter fields cannot be required and optional")
        for mapping in (
            self.field_types,
            self.enums,
            self.patterns,
            self.min_items,
            self.required_items,
        ):
            if len(mapping) > 128:
                raise ValueError("frontmatter schema is too large")
        for field, values in self.enums.items():
            if (
                not values
                or len(values) > 128
                or any(
                    isinstance(value, float) and not math.isfinite(value)
                    for value in values
                )
            ):
                raise ValueError(f"frontmatter enum {field} is invalid")
        for field, pattern in self.patterns.items():
            self.patterns[field] = _validate_world_policy_regex(pattern)
        if any(not 0 <= value <= 10_000 for value in self.min_items.values()):
            raise ValueError("frontmatter min_items is invalid")
        if any(len(values) > 128 for values in self.required_items.values()):
            raise ValueError("frontmatter required_items is too large")
        if any(
            not value
            or len(value) > 256
            or value.startswith(("/", "~"))
            or ".." in value.split("/")
            for value in self.source_prefixes
        ):
            raise ValueError("frontmatter source_prefixes are invalid")
        return self


class WorldValidationPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=128)
    operator: Literal[
        "contains",
        "not_contains",
        "max_chars",
        "page_type_exists",
        "regex",
        "forbid_regex",
        "frontmatter_required",
        "field_equals",
        "numeric_tolerance",
    ]
    value: str | int | dict[str, Any]
    page_type: str | None = Field(default=None, max_length=64)
    severity: Literal["error", "warning"] = "error"
    message: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_value(self) -> WorldValidationPolicyRule:
        if self.operator == "max_chars":
            if not isinstance(self.value, int) or not 1 <= self.value <= 10_000_000:
                raise ValueError("max_chars requires an integer from 1 to 10000000")
        elif self.operator in {"field_equals", "numeric_tolerance"}:
            if not isinstance(self.value, dict):
                raise ValueError(f"{self.operator} requires an object")
            required = (
                {"field", "equals"}
                if self.operator == "field_equals"
                else {"field", "expected", "tolerance"}
            )
            if set(self.value) != required or not isinstance(
                self.value.get("field"), str
            ):
                raise ValueError(f"{self.operator} has invalid fields")
            if self.operator == "numeric_tolerance" and (
                isinstance(self.value.get("expected"), bool)
                or isinstance(self.value.get("tolerance"), bool)
                or not isinstance(self.value.get("expected"), int | float)
                or not isinstance(self.value.get("tolerance"), int | float)
                or self.value["tolerance"] < 0
                or not math.isfinite(float(self.value["expected"]))
                or not math.isfinite(float(self.value["tolerance"]))
            ):
                raise ValueError("numeric_tolerance requires bounded numeric values")
        elif not isinstance(self.value, str) or not self.value:
            raise ValueError(f"{self.operator} requires a non-empty string")
        if self.operator in {"regex", "forbid_regex"}:
            self.value = _validate_world_policy_regex(str(self.value))
        return self


class WorldValidationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(
        ..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=128
    )
    gate: Literal[
        "structure",
        "ontology",
        "knowledge",
        "society",
        "experience",
        "history",
        "counterfactual",
        "narrative",
        "saturation",
    ]
    question: str = Field(..., min_length=1, max_length=1000)


class WorldValidationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_validation_policy.v1"]
    enabled: bool = True
    policy_version: str = Field(..., min_length=1, max_length=64)
    semantic_enabled: bool = False
    frontmatter_schemas: dict[str, WorldValidationFrontmatterSchema] = Field(
        default_factory=dict
    )
    rules: list[WorldValidationPolicyRule] = Field(default_factory=list, max_length=256)
    required_questions: list[WorldValidationQuestion] = Field(
        default_factory=list, max_length=256
    )
    packet_character_limit: int = Field(default=32_000, ge=4_000, le=80_000)
    max_packets: int = Field(default=24, ge=1, le=256)
    max_input_characters: int = Field(default=800_000, ge=4_000, le=8_000_000)
    max_output_tokens_per_packet: int = Field(default=1_500, ge=256, le=8_000)
    per_packet_timeout_seconds: int = Field(default=180, ge=30, le=1800)

    @model_validator(mode="after")
    def validate_semantic_questions(self) -> WorldValidationPolicy:
        if len(self.frontmatter_schemas) > 64 or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", page_type)
            for page_type in self.frontmatter_schemas
        ):
            raise ValueError("frontmatter_schemas page types are invalid")
        ids = [item.question_id for item in self.required_questions]
        if len(ids) != len(set(ids)):
            raise ValueError("validation question ids must be unique")
        rule_ids = [item.rule_id for item in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("validation rule ids must be unique")
        if self.required_questions and not self.semantic_enabled:
            raise ValueError("required_questions require semantic_enabled=true")
        if self.semantic_enabled and not self.required_questions:
            raise ValueError("semantic_enabled=true requires required_questions")
        return self


class WorldValidationPolicyStatus(BaseModel):
    active: bool
    policy_version: str | None = None
    semantic_enabled: bool = False
    estimated_input_characters: int = 0
    estimated_packets: int = 0
    max_input_characters: int = 0
    max_packets: int = 0
    will_exceed_budget: bool = False
    policy: WorldValidationPolicy | None = None
    draft: WorldValidationPolicyDraftInfo | None = None


class WorldValidationPolicyDraftInfo(BaseModel):
    draft_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    page_id: OptionalUuidStr = None
    updated_at: datetime | None = None
    policy: WorldValidationPolicy


class WorldValidationPolicyDraftUpsert(BaseModel):
    """Author-readable policy editor payload persisted to the rule page draft."""

    model_config = ConfigDict(extra="forbid")

    policy: WorldValidationPolicy
    summary: str = Field(default="", max_length=2000)
    expected_updated_at: datetime | None = None


class WorldValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1, max_length=128)
    layer: Literal["structure", "engine", "semantic"]
    severity: Literal["error", "warning"]
    category: str = Field(..., min_length=1, max_length=64)
    action: Literal["CLOSE", "SPLIT", "KEEP-GATE", "CANDIDATE", "AUTHOR-REQUIRED"]
    message: str = Field(..., min_length=1, max_length=1000)
    source_key: str | None = Field(default=None, max_length=256)
    location: str | None = Field(default=None, max_length=500)
    excerpt: str | None = Field(default=None, max_length=1000)
    question_id: str | None = Field(default=None, max_length=128)


class WorldValidationSemanticAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(..., min_length=1, max_length=128)
    verdict: Literal["pass", "mixed", "fail", "author-required"]
    category: str = Field(..., min_length=1, max_length=64)
    action: Literal["CLOSE", "SPLIT", "KEEP-GATE", "CANDIDATE", "AUTHOR-REQUIRED"]
    explanation: str = Field(..., min_length=1, max_length=1000)
    source_key: str | None = Field(default=None, max_length=256)
    location: str | None = Field(default=None, max_length=500)
    excerpt: str | None = Field(default=None, max_length=1000)


class WorldValidationSemanticOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[WorldValidationSemanticAnswer] = Field(
        ..., min_length=1, max_length=256
    )


class WorldValidationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    operation_id: uuid.UUID
    scope: Literal["targeted", "full"]
    trigger: str = Field(default="manual", min_length=1, max_length=64)
    review_domains: list[Literal["world", "story", "prose", "map"]] = Field(
        default_factory=lambda: ["world"], min_length=1, max_length=4
    )
    review_depth: Literal[0, 1] = 1
    expected_impact_scope_hash: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    target_type: (
        Literal["world_bible_draft", "world_adoption_package", "semantic_gap"] | None
    ) = None
    target_id: str | None = None
    root_type: (
        Literal["world_bible_page", "world_bible_page_draft", "core_entity"] | None
    ) = None
    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_target(self) -> WorldValidationRunCreate:
        if self.scope == "targeted" and not (self.target_type and self.target_id):
            raise ValueError("targeted validation requires target_type and target_id")
        if self.scope == "full" and (
            self.target_type or self.target_id or self.root_type
        ):
            raise ValueError("full validation forbids target_type and target_id")
        if self.target_type == "semantic_gap" and not self.root_type:
            raise ValueError("semantic_gap validation requires root_type")
        if self.target_type != "semantic_gap" and self.root_type:
            raise ValueError("root_type is only valid for semantic_gap validation")
        if self.target_type != "semantic_gap" and self.review_domains != ["world"]:
            raise ValueError("cross-domain review requires a targeted root")
        if self.review_depth == 0 and self.review_domains != ["world"]:
            raise ValueError("root-only review cannot include downstream domains")
        if "world" not in self.review_domains or len(self.review_domains) != len(
            set(self.review_domains)
        ):
            raise ValueError("review domains must be unique and include the World root")
        return self


class WorldValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    novel_id: Annotated[str, BeforeValidator(_optional_uuid_validator)]
    task_id: OptionalUuidStr = None
    context_confirmation_id: str | None = None
    trigger: str
    scope: Literal["targeted", "full"]
    target_type: str | None = None
    target_id: str | None = None
    status: Literal["queued", "running", "completed", "failed", "stale"]
    verdict: (
        Literal["pass", "mixed", "fail", "author-required", "insufficient-evidence"]
        | None
    ) = None
    gate: Literal["pass", "warn", "block"] | None = None
    policy_version: str
    manifest_hash: str
    dependency_hash: str
    receipt_hash: str | None = None
    findings: list[WorldValidationFinding] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    coverage_ledger: list[dict[str, Any]] = Field(default_factory=list)
    budget_ledger: dict[str, Any] = Field(default_factory=dict)
    warning_receipt: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = 0
    impact: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    stale_reason: str | None = None
    continued_count: int = 0
    review: dict[str, Any] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldValidationReviewItemRecord(BaseModel):
    finding_id: str
    disposition: Literal["resolved", "acknowledged", "deferred"]
    note: str = ""
    finding_snapshot: dict[str, Any] = Field(default_factory=dict)
    reviewed_at: datetime | None = None


class WorldValidationReviewItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1, max_length=128)
    disposition: Literal["resolved", "acknowledged", "deferred"]
    note: str = Field(default="", max_length=1000)


class WorldValidationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WorldValidationReviewItemInput] = Field(..., min_length=1, max_length=256)


class WorldValidationReviewListResponse(BaseModel):
    items: list[WorldValidationReviewItemRecord] = Field(default_factory=list)
    total: int = 0


class WorldValidationFindingsPage(BaseModel):
    items: list[WorldValidationFinding] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    dispositions: dict[str, str] = Field(default_factory=dict)


class WorldValidationRunContinueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class WorldValidationRunListResponse(BaseModel):
    items: list[WorldValidationRunResponse] = Field(default_factory=list)
    total: int = 0


class WorldValidationWarningAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_receipt_hash: str = Field(..., min_length=64, max_length=64)
    finding_ids: list[str] = Field(..., min_length=1, max_length=256)
    reason: str = Field(..., min_length=1, max_length=1000)

    @field_validator("expected_receipt_hash")
    @classmethod
    def validate_receipt_hash(cls, value: str) -> str:
        return _validate_lower_sha256(value, "expected_receipt_hash")


class WorldBibleImpactPathNode(BaseModel):
    page_id: UuidStr
    title: str
    version_number: int = Field(..., ge=1)
    section_titles: list[str] = Field(default_factory=list, max_length=64)


class WorldBibleImpactedPage(BaseModel):
    page_id: UuidStr
    title: str
    page_type: str
    version_number: int = Field(..., ge=1)
    distance: int = Field(..., ge=1)
    path: list[WorldBibleImpactPathNode] = Field(..., min_length=2, max_length=256)


class WorldBibleImpactOmission(BaseModel):
    reason: Literal[
        "invalid_page_reference",
        "unavailable_page_reference",
        "pending_page_reference",
        "response_limit",
    ]
    referring_page_id: OptionalUuidStr = None
    referring_page_title: str | None = None
    count: int = Field(default=1, ge=1)


class WorldBiblePublishImpactSource(BaseModel):
    draft_id: UuidStr
    page_id: OptionalUuidStr = None
    title: str
    page_version: int | None = Field(default=None, ge=1)
    draft_updated_at: datetime | None = None
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class WorldBiblePublishImpactResponse(BaseModel):
    source: WorldBiblePublishImpactSource
    added_outgoing_refs: int = Field(default=0, ge=0)
    removed_outgoing_refs: int = Field(default=0, ge=0)
    affected_pages: list[WorldBibleImpactedPage] = Field(
        default_factory=list,
        max_length=200,
    )
    omissions: list[WorldBibleImpactOmission] = Field(default_factory=list)
    automatic_actions: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    complete: bool = True
    impact_scope_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class WorldImpactPreviewItem(BaseModel):
    """One proven dependent source enumerated by the impact preview."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "world_bible_page",
        "core_entity",
        "entity_relation",
        "character",
        "story_thread",
        "outline_arc",
        "outline_scene",
        "story_outline",
        "prose_chapter",
        "map_node",
    ]
    id: str
    label: str = Field(..., min_length=1, max_length=500)
    version: str | None = Field(default=None, max_length=128)
    source_hash: str | None = Field(default=None, max_length=128)
    distance: int | None = Field(default=None, ge=1, le=64)
    detail: str | None = Field(default=None, max_length=1000)
    target_ref: dict[str, str] | None = None
    source_ref: dict[str, Any] | None = None
    match_basis: Literal["declared", "literal"] = "declared"

    @field_validator("id", mode="before")
    @classmethod
    def coerce_impact_item_id(cls, value: object) -> str:
        return str(value)


class WorldImpactPreviewSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Literal[
        "world_pages",
        "world_entities",
        "characters",
        "story_threads",
        "prose",
        "map",
    ]
    items: list[WorldImpactPreviewItem] = Field(default_factory=list, max_length=200)
    uncovered: list[str] = Field(default_factory=list)
    truncated: bool = False
    scope_hash: str | None = None


class WorldImpactPreviewTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["world_bible_page", "core_entity", "entity_relation"]
    target_id: str
    label: str | None = Field(default=None, max_length=500)

    @field_validator("target_id", mode="before")
    @classmethod
    def coerce_impact_target_id(cls, value: object) -> str:
        return str(value)


class WorldImpactPreviewResponse(BaseModel):
    """Read-only cross-module impact enumeration with explicit uncovered notes."""

    model_config = ConfigDict(extra="forbid")

    target: WorldImpactPreviewTarget
    sections: list[WorldImpactPreviewSection] = Field(default_factory=list, max_length=8)
    uncovered: list[str] = Field(default_factory=list)
    complete: bool = True
    scope_hash: str | None = None


class WorldImpactSourceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    novel_id: str
    item: WorldImpactPreviewItem


class WorldImpactSourceReadResponse(BaseModel):
    label: str
    text: str
    source_hash: str
    target_ref: dict[str, str] | None = None
    source_ref: dict[str, Any] | None = None
    truncated: bool = False
