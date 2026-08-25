from __future__ import annotations

import json
import types
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from .models import ContractIssue, FieldMapping, PromptContract
from .probes import run_probe
from .registry import ContractRegistryError, import_schema_model

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
TARGET_MODELS = {
    "core_entities": "modules.world.models.CoreEntity",
    "world_bible_page_drafts": "modules.world.models.WorldBiblePageDraft",
    "world_bible_synopsis_revisions": "modules.world.models.WorldBibleSynopsisRevision",
    "entity_relations": "modules.world.models.EntityRelation",
    "delta_log": "modules.story.continuity.models.DeltaLog",
    "scenes": "modules.story.outline_state.models.Scene",
    "plot_threads": "modules.story.outline_state.models.PlotThread",
    "outline_arcs": "modules.story.outline_state.models.OutlineArc",
    "foreshadowing_plans": "modules.story.outline_state.models.ForeshadowingPlan",
    "reveal_plans": "modules.story.outline_state.models.RevealPlan",
}
CRITICAL_MAPPINGS = {
    "world_generation_core_entity": {
        ("name", "core_entities.name"),
        ("summary", "core_entities.summary"),
        ("details", "core_entities.content_json.details"),
    },
}


def validate_contracts(
    contracts: list[PromptContract], *, include_fixtures: bool = False
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for contract in contracts:
        issues.extend(validate_contract(contract))
        if include_fixtures:
            issues.extend(validate_fixture(contract))
    return issues


def validate_contract(contract: PromptContract) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    try:
        schema_model = import_schema_model(contract.schema_model)
    except (AttributeError, ImportError, ContractRegistryError) as exc:
        return [
            ContractIssue(
                severity="P1",
                contract_id=contract.id,
                code="schema.import_failed",
                message=str(exc),
                path="schema_model",
            )
        ]

    paths = schema_field_paths(schema_model)
    issues.extend(_validate_strict_schema_coverage(contract, paths))
    issues.extend(_validate_forbidden_fields(contract, paths))
    issues.extend(_validate_schema_sources(contract, paths))
    issues.extend(_validate_critical_mappings(contract))
    issues.extend(_validate_ignored_reasons(contract))
    issues.extend(_validate_required_evidence(contract, paths))
    issues.extend(_validate_targets(contract))
    for probe in contract.probes:
        issues.extend(run_probe(probe, contract.id))
    return issues


def validate_fixture(
    contract: PromptContract, fixture_dir: Path = FIXTURE_DIR
) -> list[ContractIssue]:
    path = fixture_dir / f"{contract.id}.json"
    if not path.exists():
        return [
            ContractIssue(
                severity="P1",
                contract_id=contract.id,
                code="fixture.missing",
                message="Missing golden fixture.",
                path=path.name,
            )
        ]
    schema_model = import_schema_model(contract.schema_model)
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    try:
        schema_model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", [])) or path.name
        return [
            ContractIssue(
                severity="P1",
                contract_id=contract.id,
                code="fixture.invalid",
                message=str(first.get("msg", "Fixture does not validate.")),
                path=location,
            )
        ]
    return []


def schema_field_paths(model: type[Any]) -> set[str]:
    paths: set[str] = set()
    _collect_model_paths(model, "", paths)
    return paths


def _collect_model_paths(model: type[Any], prefix: str, paths: set[str]) -> None:
    fields = getattr(model, "model_fields", None)
    if not fields:
        return
    for name, field in fields.items():
        path = f"{prefix}.{name}" if prefix else name
        paths.add(path)
        for nested in _nested_models(field.annotation):
            _collect_model_paths(nested, path, paths)


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _nested_models(args[0]) if args else []
    if origin in (list, tuple, set, frozenset):
        return _nested_models(args[0]) if args else []
    if origin in (types.UnionType, getattr(types, "UnionType", object)):
        nested_models: list[type[BaseModel]] = []
        for arg in args:
            nested_models.extend(_nested_models(arg))
        return list(dict.fromkeys(nested_models))
    if origin is not None and str(origin) == "typing.Union":
        nested_models = []
        for arg in args:
            nested_models.extend(_nested_models(arg))
        return list(dict.fromkeys(nested_models))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return []


def _validate_strict_schema_coverage(
    contract: PromptContract,
    paths: set[str],
) -> list[ContractIssue]:
    if not contract.strict_schema_coverage:
        return []

    issues: list[ContractIssue] = []
    declared = set(contract.declared_prompt_fields)
    for field in sorted(declared - paths):
        issues.append(
            ContractIssue(
                severity="P1",
                contract_id=contract.id,
                code="schema.strict_declared_missing",
                message="Strict prompt field is not present in schema.",
                path=field,
            )
        )

    schema_roots = {path for path in paths if "." not in path}
    covered_roots = {field.split(".", 1)[0] for field in declared}
    covered_roots.update(item.source.split(".", 1)[0] for item in contract.ignored_fields)
    for root in sorted(schema_roots - covered_roots):
        issues.append(
            ContractIssue(
                severity="P1",
                contract_id=contract.id,
                code="schema.strict_root_undeclared",
                message="Strict schema root is neither declared nor ignored.",
                path=root,
            )
        )
    return issues


def _validate_forbidden_fields(
    contract: PromptContract, paths: set[str]
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for forbidden in contract.forbidden_fields:
        prompt_hits = [
            field
            for field in contract.declared_prompt_fields
            if _path_contains_segment(field, forbidden)
        ]
        schema_hits = [path for path in paths if _path_contains_segment(path, forbidden)]
        for path in sorted(set(prompt_hits + schema_hits)):
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id=contract.id,
                    code="field.forbidden",
                    message=(
                        f"Forbidden field is declared or present in schema: {forbidden}"
                    ),
                    path=path,
                )
            )
    return issues


def _validate_schema_sources(
    contract: PromptContract, paths: set[str]
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    required_sources = [mapping.source for mapping in contract.required_mappings]
    required_sources.extend(contract.observed_fields)
    required_sources.extend(item.source for item in contract.ignored_fields)
    for source in sorted(set(required_sources)):
        if source not in paths:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id=contract.id,
                    code="schema.source_missing",
                    message="Contract source field is not present in schema.",
                    path=source,
                )
            )
    return issues


def _validate_critical_mappings(contract: PromptContract) -> list[ContractIssue]:
    expected = CRITICAL_MAPPINGS.get(contract.id, set())
    actual = {(mapping.source, mapping.target) for mapping in contract.required_mappings}
    return [
        ContractIssue(
            severity="P1",
            contract_id=contract.id,
            code="mapping.required_missing",
            message="Required prompt-to-persistence mapping is missing.",
            path=f"{source} -> {target}",
        )
        for source, target in sorted(expected - actual)
    ]


def _validate_ignored_reasons(contract: PromptContract) -> list[ContractIssue]:
    return [
        ContractIssue(
            severity="P1",
            contract_id=contract.id,
            code="field.ignore_reason_missing",
            message="Ignored field must include a reason.",
            path=item.source,
        )
        for item in contract.ignored_fields
        if not item.reason.strip()
    ]


def _validate_required_evidence(
    contract: PromptContract, paths: set[str]
) -> list[ContractIssue]:
    if not contract.required_evidence_field:
        return []
    roots = _mapped_source_roots(contract.required_mappings)
    issues: list[ContractIssue] = []
    for root in sorted(roots):
        evidence_path = f"{root}.{contract.required_evidence_field}"
        if evidence_path not in paths:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id=contract.id,
                    code="schema.evidence_missing",
                    message="Mapped list item lacks required evidence field.",
                    path=evidence_path,
                )
            )
    return issues


def _mapped_source_roots(mappings: list[FieldMapping]) -> set[str]:
    roots: set[str] = set()
    for mapping in mappings:
        if "." in mapping.source:
            roots.add(mapping.source.split(".", 1)[0])
    return roots


def _validate_targets(contract: PromptContract) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for mapping in contract.required_mappings:
        table, _, rest = mapping.target.partition(".")
        column = rest.split(".", 1)[0] if rest else ""
        if table not in TARGET_MODELS:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id=contract.id,
                    code="target.table_not_allowed",
                    message="Target table is not in prompt contract allowlist.",
                    path=mapping.target,
                )
            )
            continue
        model = _import_target_model(TARGET_MODELS[table])
        if column not in model.__table__.columns:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id=contract.id,
                    code="target.column_missing",
                    message="Target column is not present on allowlisted ORM model.",
                    path=mapping.target,
                )
            )
    return issues


def _import_target_model(path: str) -> type[Any]:
    module_name, _, attr = path.rpartition(".")
    module = import_module(module_name)
    return getattr(module, attr)


def _path_contains_segment(path: str, segment: str) -> bool:
    return segment in path.split(".")
