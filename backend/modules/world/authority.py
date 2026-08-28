"""Closed Phase 0 wire and canonical-byte rules for world authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AuthorityValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _clean_trimmed_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be text")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFC", normalized).strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


def _clean_identifier(value: str) -> str:
    normalized = _clean_trimmed_text(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", normalized):
        raise ValueError("identifier must use the v1 ASCII pattern")
    return normalized


def _clean_section_identifier(value: str) -> str:
    normalized = _clean_trimmed_text(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", normalized):
        raise ValueError("section identifier must use the v1 ASCII pattern")
    return normalized


def _clean_page_type_identifier(value: str) -> str:
    normalized = _clean_trimmed_text(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", normalized):
        raise ValueError("page type must use the v1 ASCII pattern")
    return normalized


Identifier = Annotated[
    str,
    BeforeValidator(_clean_identifier),
    Field(min_length=1, max_length=128),
]
SectionIdentifier = Annotated[
    str,
    BeforeValidator(_clean_section_identifier),
    Field(min_length=1, max_length=64),
]
PageTypeIdentifier = Annotated[
    str,
    BeforeValidator(_clean_page_type_identifier),
    Field(min_length=1, max_length=64),
]


def _clean_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _canonical_value(value: Any, *, allow_legacy_float: bool = False) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("canonical datetimes must include a timezone")
        normalized = value.astimezone(UTC)
        return normalized.isoformat().replace("+00:00", "Z")
    if isinstance(value, float):
        if not allow_legacy_float or not math.isfinite(value):
            raise ValueError("floats are forbidden in canonical values")
        return value
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [
            _canonical_value(item, allow_legacy_float=allow_legacy_float)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _canonical_value(item, allow_legacy_float=allow_legacy_float)
            for item in value
        ]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _clean_text(str(key))
            if normalized_key in normalized:
                raise ValueError("canonical object keys must remain unique")
            normalized[normalized_key] = _canonical_value(
                item,
                allow_legacy_float=allow_legacy_float,
            )
        return normalized
    return value


def canonical_json(value: Any) -> str:
    """Return the version-1 canonical JSON representation."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _legacy_canonical_digest(value: Any) -> str:
    canonical = json.dumps(
        _canonical_value(value, allow_legacy_float=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class VersionedArtifactRef(AuthorityValue):
    artifact_id: Identifier
    version: StrictInt = Field(ge=1)
    digest: Sha256

    @field_validator("artifact_id")
    @classmethod
    def normalize_artifact_id(cls, value: str) -> str:
        value = _clean_identifier(value)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value):
            raise ValueError("invalid artifact_id")
        return value


KERNEL_REF = VersionedArtifactRef(
    artifact_id="world.canon-kernel",
    version=1,
    digest="f8d47106cd0c8803739815de39439bbb6d6d95e4b0657d63763060f82671ff6c",
)
STATEMENT_SCHEMA_REF = VersionedArtifactRef(
    artifact_id="world.statement-schema",
    version=1,
    digest="3eda28fd8a246e2c44cfd36683b754b221de5a340ce0c04be58a85f186c6c81e",
)
EMPTY_RULE_REF = VersionedArtifactRef(
    artifact_id="world.canon-rules.empty",
    version=1,
    digest="c110c7c624f2715b92eb5b0283b316470fbb8b2a6ab49379c157ec014920bad1",
)
BOOTSTRAP_POLICY_REF = VersionedArtifactRef(
    artifact_id="world.canon.bootstrap-empty",
    version=1,
    digest="a1104c58dcb18c278a1fab2b5b944b4f76d05a49d9a22a2412df1e9e7b56cc29",
)
EXPLICIT_AUTHOR_POLICY_REF = VersionedArtifactRef(
    artifact_id="world.canon.explicit-author",
    version=1,
    digest="2ee3ff5a3c5d64259b5712a3d17f869b6d717e1efd0325effb8cebd1f328d1b6",
)
PERSISTED_WORKFLOW_POLICY_REF = VersionedArtifactRef(
    artifact_id="world.canon.persisted-workflow",
    version=1,
    digest="bdced8af8cc6eb4619c73a2f4592e323b37c0778f2c638cfb51818df4be4f0ef",
)

SEALED_ARTIFACTS = {
    (item.artifact_id, item.version): item
    for item in (KERNEL_REF, STATEMENT_SCHEMA_REF, EMPTY_RULE_REF)
}
AUTHORIZATION_POLICIES = {
    (item.artifact_id, item.version): item
    for item in (
        BOOTSTRAP_POLICY_REF,
        EXPLICIT_AUTHOR_POLICY_REF,
        PERSISTED_WORKFLOW_POLICY_REF,
    )
}

SEALED_ARTIFACT_DESCRIPTORS: dict[tuple[str, int], dict[str, Any]] = {
    ("world.canon-kernel", 1): {
        "kind": "canon_kernel",
        "version": 1,
        "artifact_id": "world.canon-kernel",
        "canonicalization": "python-json-sort-keys-utf8-v1",
        "manifest_version": 1,
        "statement_claim_ref_max_depth": 1,
    },
    ("world.statement-schema", 1): {
        "kind": "statement_schema",
        "version": 1,
        "artifact_id": "world.statement-schema",
        "statement_kinds": {
            "entity_name": 1,
            "entity_scalar": 1,
            "entity_relation": 1,
        },
        "scalar_kinds": {
            "text": 1,
            "integer": 1,
            "decimal": 1,
            "boolean": 1,
            "enum": 1,
        },
    },
    ("world.canon-rules.empty", 1): {
        "kind": "canon_rule_set",
        "version": 1,
        "artifact_id": "world.canon-rules.empty",
        "rules": [],
    },
}

AUTHORIZATION_POLICY_DESCRIPTORS: dict[tuple[str, int], dict[str, Any]] = {
    ("world.canon.explicit-author", 1): {
        "kind": "canon_authorization_policy",
        "version": 1,
        "policy_id": "world.canon.explicit-author",
        "authorizer": "current_project_owner",
        "executor_kinds": ["account_request"],
        "requires_explicit_confirmation": True,
        "requires_expected_head": True,
        "allows_ai_authorizer": False,
    },
    ("world.canon.persisted-workflow", 1): {
        "kind": "canon_authorization_policy",
        "version": 1,
        "policy_id": "world.canon.persisted-workflow",
        "authorizer": "persisted_project_owner",
        "executor_kinds": ["task_attempt"],
        "requires_current_owner_at_commit": True,
        "requires_expected_head": True,
        "requires_persisted_exact_scope": True,
        "allows_ai_authorizer": False,
    },
    ("world.canon.bootstrap-empty", 1): {
        "kind": "canon_authorization_policy",
        "version": 1,
        "policy_id": "world.canon.bootstrap-empty",
        "authorizer": "closed_bootstrap_subject",
        "executor_kinds": ["bootstrap"],
        "requires_empty_manifest": True,
        "allows_ai_authorizer": False,
    },
}

for _key, _ref in SEALED_ARTIFACTS.items():
    if canonical_digest(SEALED_ARTIFACT_DESCRIPTORS[_key]) != _ref.digest:
        raise RuntimeError(f"sealed artifact descriptor drift: {_ref.artifact_id}")
for _key, _ref in AUTHORIZATION_POLICIES.items():
    if canonical_digest(AUTHORIZATION_POLICY_DESCRIPTORS[_key]) != _ref.digest:
        raise RuntimeError(f"authorization policy descriptor drift: {_ref.artifact_id}")


def require_registered_artifact(ref: VersionedArtifactRef) -> None:
    expected = SEALED_ARTIFACTS.get((ref.artifact_id, ref.version))
    if expected is None or expected.digest != ref.digest:
        raise ValueError("unknown artifact version or digest")


def require_registered_authorization_policy(ref: VersionedArtifactRef) -> None:
    expected = AUTHORIZATION_POLICIES.get((ref.artifact_id, ref.version))
    if expected is None or expected.digest != ref.digest:
        raise ValueError("unknown authorization policy version or digest")


class ResourceRef(AuthorityValue):
    kind: Literal["world_bible_page", "entity_profile_template"]
    version: Literal[1] = 1
    novel_id: uuid.UUID
    resource_id: uuid.UUID


class ExactResourceRevisionRef(AuthorityValue):
    resource: ResourceRef
    revision_id: uuid.UUID
    revision_digest: Sha256


class EmptySelectorPayload(AuthorityValue):
    pass


class WholeSelector(AuthorityValue):
    kind: Literal["whole"] = "whole"
    version: Literal[1] = 1
    payload: EmptySelectorPayload = Field(default_factory=EmptySelectorPayload)


class WorldBiblePageFieldSelectorPayload(AuthorityValue):
    field: Literal["title", "free_text"]


class WorldBiblePageFieldSelector(AuthorityValue):
    kind: Literal["world_bible_page.field"] = "world_bible_page.field"
    version: Literal[1] = 1
    payload: WorldBiblePageFieldSelectorPayload


class WorldBiblePageSectionSelectorPayload(AuthorityValue):
    section_id: SectionIdentifier


class WorldBiblePageSectionSelector(AuthorityValue):
    kind: Literal["world_bible_page.section"] = "world_bible_page.section"
    version: Literal[1] = 1
    payload: WorldBiblePageSectionSelectorPayload


class WorldBiblePageMetadataSelectorPayload(AuthorityValue):
    key: Literal["validation_policy", "card_subject_ref_v1"]


class WorldBiblePageMetadataSelector(AuthorityValue):
    kind: Literal["world_bible_page.metadata"] = "world_bible_page.metadata"
    version: Literal[1] = 1
    payload: WorldBiblePageMetadataSelectorPayload


class EntityProfileTemplateFieldSelectorPayload(AuthorityValue):
    field_key: Identifier


class EntityProfileTemplateFieldSelector(AuthorityValue):
    kind: Literal["entity_profile_template.field"] = "entity_profile_template.field"
    version: Literal[1] = 1
    payload: EntityProfileTemplateFieldSelectorPayload


type SelectorValue = Annotated[
    WholeSelector
    | WorldBiblePageFieldSelector
    | WorldBiblePageSectionSelector
    | WorldBiblePageMetadataSelector
    | EntityProfileTemplateFieldSelector,
    Field(discriminator="kind"),
]


class TargetRefV1(AuthorityValue):
    kind: Literal["target_ref"] = "target_ref"
    version: Literal[1] = 1
    revision: ExactResourceRevisionRef
    selector: SelectorValue


class AssertRefV1(AuthorityValue):
    kind: Literal["assert_ref"] = "assert_ref"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    assert_id: uuid.UUID
    assert_digest: Sha256


type GroundRefV1 = Annotated[TargetRefV1 | AssertRefV1, Field(discriminator="kind")]


class ReferentRefV1(AuthorityValue):
    novel_id: uuid.UUID
    referent_id: uuid.UUID


class TextScalarV1(AuthorityValue):
    kind: Literal["text"] = "text"
    version: Literal[1] = 1
    value: str

    _normalize_value = field_validator("value")(_clean_text)


class IntegerScalarV1(AuthorityValue):
    kind: Literal["integer"] = "integer"
    version: Literal[1] = 1
    value: StrictInt


class DecimalScalarV1(AuthorityValue):
    kind: Literal["decimal"] = "decimal"
    version: Literal[1] = 1
    value: str

    @field_validator("value")
    @classmethod
    def normalize_decimal(cls, value: str) -> str:
        value = _clean_trimmed_text(value)
        if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value):
            raise ValueError("decimal must be plain decimal text")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal") from exc
        normalized = format(decimal_value, "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return "0" if normalized in {"-0", ""} else normalized


class BooleanScalarV1(AuthorityValue):
    kind: Literal["boolean"] = "boolean"
    version: Literal[1] = 1
    value: StrictBool


class EnumScalarV1(AuthorityValue):
    kind: Literal["enum"] = "enum"
    version: Literal[1] = 1
    value: Identifier

type ScalarValueV1 = Annotated[
    TextScalarV1 | IntegerScalarV1 | DecimalScalarV1 | BooleanScalarV1 | EnumScalarV1,
    Field(discriminator="kind"),
]


class EntityNameStatementV1(AuthorityValue):
    kind: Literal["entity_name"] = "entity_name"
    version: Literal[1] = 1
    subject: ReferentRefV1
    name: Annotated[str, Field(min_length=1, max_length=255)]

    _normalize_name = field_validator("name")(_clean_trimmed_text)


class EntityScalarFieldV1(AuthorityValue):
    schema_revision: ExactResourceRevisionRef
    field_key: Identifier


class EntityScalarStatementV1(AuthorityValue):
    kind: Literal["entity_scalar"] = "entity_scalar"
    version: Literal[1] = 1
    subject: ReferentRefV1
    field: EntityScalarFieldV1
    value: ScalarValueV1


RelationKindV1 = Literal[
    "state", "social", "spatial", "causal", "temporal", "epistemic", "intentional"
]


class EntityRelationStatementV1(AuthorityValue):
    kind: Literal["entity_relation"] = "entity_relation"
    version: Literal[1] = 1
    subject: ReferentRefV1
    relation_kind: RelationKindV1
    relation_type: Annotated[str, Field(min_length=1, max_length=128)]
    object: ReferentRefV1

    _normalize_relation_type = field_validator("relation_type")(_clean_trimmed_text)


type StatementValueV1 = Annotated[
    EntityNameStatementV1 | EntityScalarStatementV1 | EntityRelationStatementV1,
    Field(discriminator="kind"),
]


class TimelessScopeV1(AuthorityValue):
    kind: Literal["timeless"] = "timeless"
    version: Literal[1] = 1


class PointScopeV1(AuthorityValue):
    kind: Literal["point"] = "point"
    version: Literal[1] = 1
    calendar_ref: VersionedArtifactRef
    value: StrictInt


class IntervalScopeV1(AuthorityValue):
    kind: Literal["interval"] = "interval"
    version: Literal[1] = 1
    calendar_ref: VersionedArtifactRef
    start: StrictInt
    end: StrictInt
    start_inclusive: StrictBool = True
    end_inclusive: StrictBool = False

    @model_validator(mode="after")
    def validate_interval(self) -> IntervalScopeV1:
        if self.start > self.end:
            raise ValueError("interval start must not exceed end")
        return self


type TimeScopeV1 = Annotated[
    TimelessScopeV1 | PointScopeV1 | IntervalScopeV1,
    Field(discriminator="kind"),
]


class StatementClaimRefV1(AuthorityValue):
    kind: Literal["statement_claim_ref"] = "statement_claim_ref"
    version: Literal[1] = 1
    regime: Literal["objective_world.v1"] = "objective_world.v1"
    polarity: Literal["positive", "negative"]
    statement: StatementValueV1
    time_scope: TimeScopeV1


type SchemaRefV1 = VersionedArtifactRef | ExactResourceRevisionRef


class AssertValueV1(AuthorityValue):
    novel_id: uuid.UUID
    regime: Literal["objective_world.v1"] = "objective_world.v1"
    polarity: Literal["positive", "negative"]
    statement: StatementValueV1
    schema_ref: SchemaRefV1
    time_scope: TimeScopeV1
    source_refs: list[TargetRefV1] = Field(default_factory=list)
    hard_grounds: list[GroundRefV1] = Field(default_factory=list)
    provenance_actor_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_closed_assertion(self) -> AssertValueV1:
        referents = [self.statement.subject]
        if isinstance(self.statement, EntityRelationStatementV1):
            referents.append(self.statement.object)
        if any(ref.novel_id != self.novel_id for ref in referents):
            raise ValueError("statement referents must belong to the same novel")
        if (
            isinstance(self.statement, EntityScalarStatementV1)
            and self.statement.field.schema_revision.resource.novel_id != self.novel_id
        ):
            raise ValueError("scalar schema must belong to the same novel")
        nested_novel_ids = [
            ref.revision.resource.novel_id for ref in self.source_refs
        ] + [
            (
                ref.novel_id
                if isinstance(ref, AssertRefV1)
                else ref.revision.resource.novel_id
            )
            for ref in self.hard_grounds
        ]
        if any(novel_id != self.novel_id for novel_id in nested_novel_ids):
            raise ValueError("assertion references must belong to the same novel")
        for refs, label in (
            (self.source_refs, "source_refs"),
            (self.hard_grounds, "hard_grounds"),
        ):
            digests = [canonical_digest(ref) for ref in refs]
            if len(digests) != len(set(digests)) or digests != sorted(digests):
                raise ValueError(f"{label} must be unique and canonically sorted")
        return self


def assertion_content_digest(assertion: AssertValueV1) -> str:
    """Hash the semantic assertion envelope, excluding audit-only provenance."""
    value = assertion.model_dump(mode="json")
    value.pop("provenance_actor_ref", None)
    return canonical_digest(value)


FamilyAuthority = Literal["formal-disabled", "canon-owned"]


class CanonManifestV1(AuthorityValue):
    kind: Literal["canon_manifest"] = "canon_manifest"
    version: Literal[1] = 1
    active_resources: list[ExactResourceRevisionRef] = Field(default_factory=list)
    selected_assertions: list[AssertRefV1] = Field(default_factory=list)
    kernel_ref: VersionedArtifactRef = KERNEL_REF
    schema_refs: list[VersionedArtifactRef] = Field(
        default_factory=lambda: [STATEMENT_SCHEMA_REF]
    )
    rule_ref: VersionedArtifactRef = EMPTY_RULE_REF
    validation_policy_ref: ExactResourceRevisionRef | None = None
    calendar_ref: VersionedArtifactRef | None = None
    pinned_dependencies: list[TargetRefV1] = Field(default_factory=list)
    family_authority: dict[
        Literal["name", "typed_scalar", "binary_relation", "event_time", "belief"],
        FamilyAuthority,
    ]

    @model_validator(mode="after")
    def validate_closed_manifest(self) -> CanonManifestV1:
        require_registered_artifact(self.kernel_ref)
        require_registered_artifact(self.rule_ref)
        for ref in self.schema_refs:
            require_registered_artifact(ref)
        required = {"name", "typed_scalar", "binary_relation", "event_time", "belief"}
        if set(self.family_authority) != required:
            raise ValueError("family_authority must cover every Phase 0 family")
        resource_keys = [
            (ref.resource.kind, str(ref.resource.resource_id))
            for ref in self.active_resources
        ]
        if resource_keys != sorted(resource_keys) or len(resource_keys) != len(
            set(resource_keys)
        ):
            raise ValueError("active_resources must be unique and canonically sorted")
        assertion_keys = [
            (str(ref.novel_id), str(ref.assert_id)) for ref in self.selected_assertions
        ]
        if len(assertion_keys) != len(set(assertion_keys)):
            raise ValueError("selected_assertions must be unique")
        schema_keys = [
            (ref.artifact_id, ref.version, ref.digest) for ref in self.schema_refs
        ]
        if len(schema_keys) != len(set(schema_keys)):
            raise ValueError("schema_refs must be unique")
        dependency_digests = [canonical_digest(ref) for ref in self.pinned_dependencies]
        if len(dependency_digests) != len(set(dependency_digests)):
            raise ValueError("pinned_dependencies must be unique")
        return self


def empty_canon_manifest() -> CanonManifestV1:
    return CanonManifestV1(
        family_authority={
            "name": "formal-disabled",
            "typed_scalar": "formal-disabled",
            "binary_relation": "formal-disabled",
            "event_time": "formal-disabled",
            "belief": "formal-disabled",
        }
    )


def resource_revision_digest(
    resource: ResourceRef,
    revision_id: uuid.UUID,
    snapshot: dict[str, Any],
) -> str:
    return canonical_digest(
        {
            "kind": "resource_revision_digest_input",
            "version": 1,
            "resource": resource,
            "revision_id": revision_id,
            "snapshot": snapshot,
        }
    )


def legacy_resource_revision_digest(
    resource: ResourceRef,
    revision_id: uuid.UUID,
    snapshot: dict[str, Any],
) -> str:
    """Verify snapshots accepted before Canon v1 rejected JSON floats."""
    return _legacy_canonical_digest(
        {
            "kind": "resource_revision_digest_input",
            "version": 1,
            "resource": resource,
            "revision_id": revision_id,
            "snapshot": snapshot,
        }
    )


BOOTSTRAP_DECISION_NAMESPACE = uuid.UUID("7d771d15-3f43-4d19-99c9-0d525747794f")


def bootstrap_decision_id(novel_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(BOOTSTRAP_DECISION_NAMESPACE, str(novel_id))


class BootstrapEmptyInputV1(AuthorityValue):
    kind: Literal["bootstrap_empty"] = "bootstrap_empty"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    expected_previous_head: None = None


class PageDraftSnapshotV1(AuthorityValue):
    draft_id: uuid.UUID
    page_id: uuid.UUID | None = None
    base_version_number: int | None = Field(default=None, ge=1)
    title: str
    page_type: PageTypeIdentifier
    page_meta_json: dict[str, Any]
    free_text: str | None = None
    sections_json: list[dict[str, Any]]
    linked_asset_refs_json: list[dict[str, Any]]
    sort_order: int
    template_key: Identifier | None = None
    template_version: int = Field(ge=1)
    updated_at: datetime

    _normalize_title = field_validator("title")(_clean_text)


class PagePublishInputV1(AuthorityValue):
    kind: Literal["page_publish"] = "page_publish"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    draft_snapshot: PageDraftSnapshotV1
    impact_scope_hash: Sha256
    validation_run_id: uuid.UUID | None = None


class AssertBatchInputV1(AuthorityValue):
    kind: Literal["assert_batch"] = "assert_batch"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    assertions: list[AssertValueV1]
    candidate_snapshot: dict[str, Any]
    selected_item_keys: list[Identifier]
    source_refs: list[TargetRefV1]


class RevertCompatibilityJudgmentV1(AuthorityValue):
    kind: Literal["revert_compatibility_judgment"] = (
        "revert_compatibility_judgment"
    )
    version: Literal[1] = 1
    current_manifest_digest: Sha256
    target_manifest_digest: Sha256
    result: Literal["compatible"] = "compatible"


class RevertInputV1(AuthorityValue):
    kind: Literal["revert"] = "revert"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    target_revision_id: uuid.UUID
    expected_previous_head: uuid.UUID
    compatibility_judgment: RevertCompatibilityJudgmentV1


class FamilyCutoverInputV1(AuthorityValue):
    kind: Literal["family_cutover"] = "family_cutover"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    family: Literal["name", "typed_scalar", "binary_relation", "event_time", "belief"]
    migration_input: dict[str, Any]


type AdmissionInputValueV1 = Annotated[
    BootstrapEmptyInputV1
    | PagePublishInputV1
    | AssertBatchInputV1
    | RevertInputV1
    | FamilyCutoverInputV1,
    Field(discriminator="kind"),
]


class AccountAuthorizerRefV1(AuthorityValue):
    kind: Literal["account"] = "account"
    version: Literal[1] = 1
    account_id: uuid.UUID


class BootstrapPrincipalRefV1(AuthorityValue):
    kind: Literal["bootstrap"] = "bootstrap"
    version: Literal[1] = 1
    subject: Literal["world.canon.bootstrap"] = "world.canon.bootstrap"


type AuthorizerRefV1 = Annotated[
    AccountAuthorizerRefV1 | BootstrapPrincipalRefV1,
    Field(discriminator="kind"),
]


class AccountRequestExecutorRefV1(AuthorityValue):
    kind: Literal["account_request"] = "account_request"
    version: Literal[1] = 1
    account_id: uuid.UUID


class TaskAttemptExecutorRefV1(AuthorityValue):
    kind: Literal["task_attempt"] = "task_attempt"
    version: Literal[1] = 1
    task_id: uuid.UUID
    task_type: Identifier
    attempt: StrictInt = Field(ge=1)
    lease_id: uuid.UUID


type ExecutorRefV1 = Annotated[
    AccountRequestExecutorRefV1 | TaskAttemptExecutorRefV1 | BootstrapPrincipalRefV1,
    Field(discriminator="kind"),
]


class CanonDecisionRefV1(AuthorityValue):
    id: uuid.UUID
    digest: Sha256


class CanonAdmissionReceiptV1(AuthorityValue):
    kind: Literal["canon_admission_receipt"] = "canon_admission_receipt"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    canon_revision_id: uuid.UUID
    manifest_digest: Sha256
    decision: CanonDecisionRefV1
    authorizer: AuthorizerRefV1
    executor: ExecutorRefV1
    authorization_policy: VersionedArtifactRef
    authorization_decision: Literal["allow"] = "allow"
    action: Literal[
        "bootstrap_empty_canon",
        "page_publish",
        "assert_batch",
        "revert",
        "family_cutover",
    ]
    affected_families: list[
        Literal["name", "typed_scalar", "binary_relation", "event_time", "belief"]
    ]
    affected_resources: list[ExactResourceRevisionRef]
    admission_input: AdmissionInputValueV1
    admission_input_digest: Sha256
    expected_previous_head: uuid.UUID | None
    committed_at: datetime

    @model_validator(mode="after")
    def validate_receipt(self) -> CanonAdmissionReceiptV1:
        require_registered_authorization_policy(self.authorization_policy)
        if self.novel_id != self.admission_input.novel_id:
            raise ValueError("receipt input must belong to the same novel")
        for ref in self.affected_resources:
            if ref.resource.novel_id != self.novel_id:
                raise ValueError("affected resource must belong to the same novel")
        if canonical_digest(self.admission_input) != self.admission_input_digest:
            raise ValueError("admission input digest does not match")

        action_by_input = {
            "bootstrap_empty": "bootstrap_empty_canon",
            "page_publish": "page_publish",
            "assert_batch": "assert_batch",
            "revert": "revert",
            "family_cutover": "family_cutover",
        }
        if self.action != action_by_input[self.admission_input.kind]:
            raise ValueError("receipt action does not match admission input")

        if isinstance(self.admission_input, BootstrapEmptyInputV1):
            if not (
                isinstance(self.authorizer, BootstrapPrincipalRefV1)
                and isinstance(self.executor, BootstrapPrincipalRefV1)
                and self.authorization_policy == BOOTSTRAP_POLICY_REF
                and self.expected_previous_head is None
                and not self.affected_families
                and not self.affected_resources
                and self.decision.digest == self.admission_input_digest
            ):
                raise ValueError("invalid bootstrap receipt")
            return self

        if not isinstance(self.authorizer, AccountAuthorizerRefV1):
            raise ValueError("non-bootstrap authorizer must be an account")
        if self.expected_previous_head is None:
            raise ValueError("non-bootstrap receipt requires an expected head")
        expected_decision_digest = canonical_digest(
            {
                "kind": "canon_decision",
                "version": 1,
                "expected_previous_head": self.expected_previous_head,
                "admission_input_digest": self.admission_input_digest,
            }
        )
        if self.decision.digest != expected_decision_digest:
            raise ValueError("decision digest does not match")
        if (
            isinstance(self.admission_input, RevertInputV1)
            and self.admission_input.expected_previous_head
            != self.expected_previous_head
        ):
            raise ValueError("revert input does not match its expected head")
        if isinstance(self.executor, AccountRequestExecutorRefV1):
            if (
                self.executor.account_id != self.authorizer.account_id
                or self.authorization_policy != EXPLICIT_AUTHOR_POLICY_REF
            ):
                raise ValueError("invalid explicit-author receipt")
        elif isinstance(self.executor, TaskAttemptExecutorRefV1):
            if self.authorization_policy != PERSISTED_WORKFLOW_POLICY_REF:
                raise ValueError("invalid persisted-workflow receipt")
        else:
            raise ValueError("invalid non-bootstrap executor")
        return self


class PagePublishPreviewInputV1(AuthorityValue):
    kind: Literal["page_publish"] = "page_publish"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    draft_id: uuid.UUID
    expected_impact_scope_hash: Sha256 | None = None
    validation_run_id: uuid.UUID | None = None


class RevertPreviewInputV1(AuthorityValue):
    kind: Literal["revert"] = "revert"
    version: Literal[1] = 1
    novel_id: uuid.UUID
    target_revision_id: uuid.UUID


type AdmissionPreviewInputV1 = Annotated[
    PagePublishPreviewInputV1 | RevertPreviewInputV1,
    Field(discriminator="kind"),
]


class CanonAdmissionPreviewRequest(AuthorityValue):
    novel_id: uuid.UUID
    expected_previous_head: uuid.UUID
    input: AdmissionPreviewInputV1


class CanonAdmissionRequest(AuthorityValue):
    novel_id: uuid.UUID
    decision_id: uuid.UUID
    expected_previous_head: uuid.UUID
    confirmed: Literal[True]
    input: AdmissionInputValueV1


class CanonRevertRequest(AuthorityValue):
    novel_id: uuid.UUID
    decision_id: uuid.UUID
    expected_previous_head: uuid.UUID
    target_revision_id: uuid.UUID
    confirmed: Literal[True]


class CanonAdmissionPreviewResponse(AuthorityValue):
    current_head_id: uuid.UUID
    normalized_input: AdmissionInputValueV1
    input_digest: Sha256
    changes: dict[str, Any]


class CanonRevisionResponse(AuthorityValue):
    id: uuid.UUID
    novel_id: uuid.UUID
    version_number: int
    parent_revision_id: uuid.UUID | None
    manifest_digest: Sha256
    created_at: datetime
    changes: dict[str, Any] = Field(default_factory=dict)


class CanonHeadResponse(AuthorityValue):
    novel_id: uuid.UUID
    current_revision: CanonRevisionResponse
