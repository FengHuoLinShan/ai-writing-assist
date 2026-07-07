from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["P0", "P1", "P2", "P3"]


@dataclass(frozen=True)
class FieldMapping:
    source: str
    target: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldMapping:
        return cls(source=str(data.get("source", "")), target=str(data.get("target", "")))


@dataclass(frozen=True)
class IgnoredField:
    source: str
    reason: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IgnoredField:
        return cls(source=str(data.get("source", "")), reason=str(data.get("reason", "")))


@dataclass(frozen=True)
class PromptContract:
    id: str
    version: int
    owner: str
    schema_model: str
    declared_prompt_fields: list[str] = field(default_factory=list)
    forbidden_fields: list[str] = field(default_factory=list)
    required_evidence_field: str | None = None
    strict_schema_coverage: bool = False
    required_mappings: list[FieldMapping] = field(default_factory=list)
    observed_fields: list[str] = field(default_factory=list)
    ignored_fields: list[IgnoredField] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptContract:
        return cls(
            id=str(data.get("id", "")),
            version=int(data.get("version", 1)),
            owner=str(data.get("owner", "")),
            schema_model=str(data.get("schema_model", "")),
            declared_prompt_fields=[
                str(item) for item in data.get("declared_prompt_fields", [])
            ],
            forbidden_fields=[str(item) for item in data.get("forbidden_fields", [])],
            required_evidence_field=(
                str(data["required_evidence_field"])
                if data.get("required_evidence_field")
                else None
            ),
            strict_schema_coverage=bool(data.get("strict_schema_coverage", False)),
            required_mappings=[
                FieldMapping.from_dict(item)
                for item in data.get("required_mappings", [])
            ],
            observed_fields=[str(item) for item in data.get("observed_fields", [])],
            ignored_fields=[
                IgnoredField.from_dict(item) for item in data.get("ignored_fields", [])
            ],
            probes=[str(item) for item in data.get("probes", [])],
        )


@dataclass(frozen=True)
class ContractIssue:
    severity: Severity
    contract_id: str
    code: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, str]:
        data = {
            "severity": self.severity,
            "contract_id": self.contract_id,
            "code": self.code,
            "message": self.message,
        }
        if self.path:
            data["path"] = self.path
        return data
