"""Closed Pydantic wire types for the v1 world authority kernel."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WORLD_KERNEL_SPEC_VERSION = "world-kernel.v1"
WORLD_BASE_SCHEMA_REF = "builtin:world-base-schema.v1"
WORLD_AUTHORIZATION_POLICY_REF = "builtin:world-canon-author-policy.v1"
WORLD_CANON_MANIFEST_SCHEMA = "world_canon_manifest.v1"
WORLD_CANON_RECEIPT_SCHEMA = "world_canon_admission_receipt.v1"


class ResourceRevisionRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_kind: Literal[
        "world_bible_page",
        "world_bible_page_template",
        "core_entity",
        "entity_profile_template",
    ]
    resource_id: uuid.UUID
    revision_kind: Literal[
        "world_bible_page_revision",
        "world_bible_page_template_revision",
        "entity_revision",
        "entity_profile_template_revision",
    ]
    revision_id: uuid.UUID
    selector: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_kind_pair(self) -> ResourceRevisionRefV1:
        expected = {
            "world_bible_page": "world_bible_page_revision",
            "world_bible_page_template": "world_bible_page_template_revision",
            "core_entity": "entity_revision",
            "entity_profile_template": "entity_profile_template_revision",
        }[self.resource_kind]
        if self.revision_kind != expected:
            raise ValueError("resource and revision kinds do not match")
        if self.selector == "latest" or self.selector == "head":
            raise ValueError("mutable selectors are not allowed")
        return self

    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.resource_kind,
            str(self.resource_id),
            str(self.revision_id),
            self.selector,
        )


class WorldCanonManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_canon_manifest.v1"] = WORLD_CANON_MANIFEST_SCHEMA
    novel_id: uuid.UUID
    kernel_spec_version: Literal["world-kernel.v1"] = WORLD_KERNEL_SPEC_VERSION
    resources: list[ResourceRevisionRefV1] = Field(default_factory=list, max_length=4096)
    selected_assertion_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4096)
    schema_refs: list[str] = Field(default_factory=lambda: [WORLD_BASE_SCHEMA_REF])
    rule_refs: list[str] = Field(default_factory=list)
    policy_refs: list[str] = Field(
        default_factory=lambda: [
            WORLD_BASE_SCHEMA_REF,
            WORLD_AUTHORIZATION_POLICY_REF,
        ]
    )
    calendar_refs: list[str] = Field(default_factory=list)
    correspondence_refs: list[ResourceRevisionRefV1] = Field(default_factory=list)
    inactive_resource_refs: list[ResourceRevisionRefV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_closed_manifest(self) -> WorldCanonManifestV1:
        if self.schema_refs != sorted(set(self.schema_refs)):
            raise ValueError("schema refs must be unique and sorted")
        if self.rule_refs != sorted(set(self.rule_refs)):
            raise ValueError("rule refs must be unique and sorted")
        if self.policy_refs != sorted(set(self.policy_refs)):
            raise ValueError("policy refs must be unique and sorted")
        if self.calendar_refs != sorted(set(self.calendar_refs)):
            raise ValueError("calendar refs must be unique and sorted")
        if self.selected_assertion_ids != sorted(set(self.selected_assertion_ids)):
            raise ValueError("assertion ids must be unique and sorted")
        for refs in (
            self.resources,
            self.correspondence_refs,
            self.inactive_resource_refs,
        ):
            keys = [item.sort_key() for item in refs]
            if keys != sorted(set(keys)):
                raise ValueError("resource refs must be unique and sorted")
        active = {(item.resource_kind, item.resource_id) for item in self.resources}
        inactive = {
            (item.resource_kind, item.resource_id)
            for item in self.inactive_resource_refs
        }
        if active & inactive:
            raise ValueError("a resource cannot be both active and inactive")
        if self.rule_refs or self.calendar_refs or self.correspondence_refs:
            raise ValueError(
                "v1 does not support rules, calendars, or correspondence refs"
            )
        required_policy_refs = sorted(
            [WORLD_BASE_SCHEMA_REF, WORLD_AUTHORIZATION_POLICY_REF]
        )
        if self.policy_refs != required_policy_refs:
            raise ValueError("v1 policy refs are fixed")
        if WORLD_BASE_SCHEMA_REF not in self.schema_refs:
            raise ValueError("the v1 base schema is required")
        return self


class WorldCanonAdmissionReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_canon_admission_receipt.v1"] = (
        WORLD_CANON_RECEIPT_SCHEMA
    )
    novel_id: uuid.UUID
    canon_revision_id: uuid.UUID
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    committer_principal: str = Field(min_length=1, max_length=128)
    action: Literal[
        "initialize", "publish_page", "adopt", "promote", "canonical_edit", "revert"
    ]
    authorization_scope: Literal["world.canon.commit"] = "world.canon.commit"
    authorization_policy_ref: Literal["builtin:world-canon-author-policy.v1"] = (
        WORLD_AUTHORIZATION_POLICY_REF
    )
    authorization_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["allowed"] = "allowed"
    committed_at: datetime
    expected_previous_head: uuid.UUID | None


class NameStatementV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["name"] = "name"
    version: Literal[1] = 1
    subject_entity_id: uuid.UUID
    value: str = Field(min_length=1, max_length=255)
    name_kind: Literal["primary", "alias"]

    @field_validator("value")
    @classmethod
    def trim_value(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name value must not be blank")
        return stripped


class TypedScalarStatementV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["typed_scalar"] = "typed_scalar"
    version: Literal[1] = 1
    subject_entity_id: uuid.UUID
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value_type: Literal["string", "integer", "decimal", "boolean", "enum"]
    value: str | int | bool
    unit: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_typed_value(self) -> TypedScalarStatementV1:
        value = self.value
        valid = (
            (self.value_type in {"string", "enum"} and isinstance(value, str))
            or (
                self.value_type == "integer"
                and isinstance(value, int)
                and not isinstance(value, bool)
            )
            or (self.value_type == "boolean" and isinstance(value, bool))
        )
        if self.value_type == "decimal" and isinstance(value, str):
            try:
                valid = str(Decimal(value)) == value
            except InvalidOperation:
                valid = False
        if not valid:
            raise ValueError("value does not match value_type")
        return self


class BinaryRelationStatementV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["binary_relation"] = "binary_relation"
    version: Literal[1] = 1
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relation_kind: Literal[
        "state", "social", "spatial", "causal", "temporal", "epistemic", "intentional"
    ]
    relation_type: str = Field(min_length=1, max_length=64)


StatementValueV1 = Annotated[
    NameStatementV1 | TypedScalarStatementV1 | BinaryRelationStatementV1,
    Field(discriminator="kind"),
]


class TimelessScopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["timeless"] = "timeless"


class PointScopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["point"] = "point"
    time_ref: ResourceRevisionRefV1
    phase: Literal["pre", "at", "post"]


class IntervalScopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["interval"] = "interval"
    start_ref: ResourceRevisionRefV1
    end_ref: ResourceRevisionRefV1


TimeScopeV1 = Annotated[
    TimelessScopeV1 | PointScopeV1 | IntervalScopeV1,
    Field(discriminator="kind"),
]


class WorldCanonSummaryResponse(BaseModel):
    canon_revision_id: uuid.UUID
    parent_id: uuid.UUID | None
    manifest_digest: str
    created_at: datetime
    resource_count: int
    assertion_count: int
    head_version: int | None = None
    current: bool


class WorldCanonInitializePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_revision_ids: list[uuid.UUID] = Field(default_factory=list, max_length=256)


class WorldCanonInitializePreviewResponse(BaseModel):
    expected_previous_head: uuid.UUID
    preview_digest: str
    resource_count: int


class WorldCanonInitializeRequest(WorldCanonInitializePreviewRequest):
    expected_previous_head: uuid.UUID
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]


class WorldCanonRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_previous_head: uuid.UUID
    target_canon_revision_id: uuid.UUID
    confirmed: Literal[True]


class EntityProfileFieldSchemaV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=64)
    value_type: Literal["string", "integer", "decimal", "boolean", "enum"]
    required: bool = False
    unit: str | None = Field(default=None, max_length=32)
    enum_values: list[str] = Field(default_factory=list, max_length=64)
    default: str | int | bool | None = None

    @model_validator(mode="after")
    def validate_field(self) -> EntityProfileFieldSchemaV1:
        if self.value_type == "enum" and not self.enum_values:
            raise ValueError("enum fields require enum_values")
        if self.value_type != "enum" and self.enum_values:
            raise ValueError("enum_values are only valid for enum fields")
        if self.default is not None:
            candidate = TypedScalarStatementV1(
                subject_entity_id=uuid.UUID(int=0),
                field_key=self.key,
                value_type=self.value_type,
                value=self.default,
                unit=self.unit,
            )
            if self.value_type == "enum" and candidate.value not in self.enum_values:
                raise ValueError("default must be one of enum_values")
        return self


class EntityProfileRelationSchemaV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=64)
    relation_kind: Literal[
        "state", "social", "spatial", "causal", "temporal", "epistemic", "intentional"
    ]
    target_entity_types: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("target_entity_types")
    @classmethod
    def validate_target_types(cls, values: list[str]) -> list[str]:
        pattern = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
        if any(not pattern.fullmatch(value) for value in values):
            raise ValueError("target entity types must be stable type keys")
        if len(values) != len(set(values)):
            raise ValueError("target entity types must be unique")
        return values


class EntityProfileTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: uuid.UUID
    profile_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    fields: list[EntityProfileFieldSchemaV1] = Field(default_factory=list, max_length=64)
    relations: list[EntityProfileRelationSchemaV1] = Field(
        default_factory=list, max_length=64
    )

    @model_validator(mode="after")
    def unique_fields(self) -> EntityProfileTemplateCreateRequest:
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("template field keys must be unique")
        relation_types = [relation.relation_type for relation in self.relations]
        if len(relation_types) != len(set(relation_types)):
            raise ValueError("template relation types must be unique")
        if not self.fields and not self.relations:
            raise ValueError("template requires fields or relations")
        return self


class EntityProfileTemplateRevisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[EntityProfileFieldSchemaV1] = Field(default_factory=list, max_length=64)
    relations: list[EntityProfileRelationSchemaV1] = Field(
        default_factory=list, max_length=64
    )

    @model_validator(mode="after")
    def unique_fields(self) -> EntityProfileTemplateRevisionCreateRequest:
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("template field keys must be unique")
        relation_types = [relation.relation_type for relation in self.relations]
        if len(relation_types) != len(set(relation_types)):
            raise ValueError("template relation types must be unique")
        if not self.fields and not self.relations:
            raise ValueError("template requires fields or relations")
        return self


class EntityProfileTemplateAdoptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: uuid.UUID
    confirmed: Literal[True]


class EntityProfileTemplateResponse(BaseModel):
    template_id: uuid.UUID
    revision_id: uuid.UUID
    novel_id: uuid.UUID
    profile_type: str
    version_number: int
    status: str
    fields: list[EntityProfileFieldSchemaV1]
    relations: list[EntityProfileRelationSchemaV1] = Field(default_factory=list)


class WorldPromotionCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_mode: Literal["B"] = "B"
    polarity: Literal["positive", "negative"] = "positive"
    statement: StatementValueV1
    time_scope: TimeScopeV1 = Field(default_factory=TimelessScopeV1)
    schema_revision_ref: ResourceRevisionRefV1
    source_revision_ref: ResourceRevisionRefV1
    cite_refs: list[ResourceRevisionRefV1] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_promotable_family(self) -> WorldPromotionCandidateV1:
        if isinstance(self.statement, NameStatementV1):
            raise ValueError("Name authority uses the entity canonical write seam")
        if self.schema_revision_ref.resource_kind != "entity_profile_template":
            raise ValueError("promotion requires an exact profile template revision")
        return self


class WorldPromotionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WorldPromotionCandidateV1] = Field(min_length=1, max_length=256)


class WorldPromotionPreviewResponse(BaseModel):
    expected_previous_head: uuid.UUID
    preview_digest: str
    item_count: int


class WorldPromotionApplyRequest(WorldPromotionPreviewRequest):
    expected_previous_head: uuid.UUID
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]


class WorldFormalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: StatementValueV1
    time_scope: TimeScopeV1 = Field(default_factory=TimelessScopeV1)
    canon_revision_id: uuid.UUID | None = None
    max_assertions: int = Field(default=4096, ge=1, le=4096)
    diagnostics: bool = False


class WorldFormalQueryObligations(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_scope: Literal["machine", "assumed", "open"] = Field(
        serialization_alias="S"
    )
    formal_coverage: Literal["machine", "assumed", "open"] = Field(
        serialization_alias="F"
    )
    identity: Literal["machine", "assumed", "open"] = Field(
        serialization_alias="I"
    )
    execution: Literal[
        "complete", "budget-truncated", "unsupported-family", "invalid-context"
    ] = Field(serialization_alias="X")


class WorldFormalQueryResponse(BaseModel):
    verdict: Literal["true", "false", "both", "unknown"]
    product_verdict: Literal["verified-formal-relative", "incomplete", "invalid"]
    canon_revision_id: uuid.UUID
    positive_support_count: int
    negative_support_count: int
    source_summaries: list[str] = Field(default_factory=list)
    direct_authority_ids: list[uuid.UUID] = Field(default_factory=list)
    obligations: WorldFormalQueryObligations
