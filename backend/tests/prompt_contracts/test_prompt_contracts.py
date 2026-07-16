from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.prompt_contracts.models import FieldMapping, PromptContract
from tools.prompt_contracts.registry import ContractRegistryError, load_contracts
from tools.prompt_contracts.report import format_json
from tools.prompt_contracts.validators import (
    schema_field_paths,
    validate_contract,
    validate_contracts,
    validate_fixture,
)


def test_registry_loads_all_deep_import_contracts() -> None:
    contracts = load_contracts()

    assert {contract.id for contract in contracts} == {
        "world_generation_core_entity",
        "world_generation_world_bible_page",
        "world_generation_world_bible_new_page",
        "world_bible_synopsis",
        "phase1a_scene_slicing",
        "phase1b_scene_enrichment",
        "phase2_world_extraction",
        "phase2_alias_relation",
        "phase3_structure_simple",
        "scene_entity_extraction",
        "story_outline",
    }


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write_contract(tmp_path / "one.json", {"id": "dup"})
    _write_contract(tmp_path / "two.json", {"id": "dup"})

    with pytest.raises(ContractRegistryError, match="duplicate contract id"):
        load_contracts(tmp_path)


def test_registry_rejects_illegal_schema_prefix(tmp_path: Path) -> None:
    _write_contract(
        tmp_path / "bad.json",
        {
            "id": "bad",
            "schema_model": "os.PathLike",
        },
    )

    with pytest.raises(ContractRegistryError, match="illegal schema_model prefix"):
        load_contracts(tmp_path)


def test_registry_rejects_unknown_probe_name(tmp_path: Path) -> None:
    _write_contract(
        tmp_path / "bad.json",
        {
            "id": "bad",
            "probes": ["not_a_probe"],
        },
    )

    with pytest.raises(ContractRegistryError, match="unknown probe"):
        load_contracts(tmp_path)


def test_schema_validator_extracts_nested_list_field_paths() -> None:
    from modules.imports.llm_schemas import Phase2WorldExtractionOutput

    paths = schema_field_paths(Phase2WorldExtractionOutput)

    assert "objects.name" in paths
    assert "relations.relation_type" in paths
    assert "deltas.subject_name" in paths
    assert "uncertain_items.supporting_scene_ids" in paths
    assert "map_observation_proposals.proposal_type" in paths
    assert "map_observation_proposals.quote" in paths
    assert "map_observation_proposals.character_name" in paths
    assert "map_observation_proposals.event_name" in paths
    assert "map_observation_proposals.path_name" in paths
    assert "map_observation_proposals.controller_name" in paths


def test_strict_schema_coverage_rejects_undeclared_schema_root() -> None:
    contract = _load_contract("scene_entity_extraction")
    contract = replace(
        contract,
        declared_prompt_fields=[
            field
            for field in contract.declared_prompt_fields
            if field != "map_observation_proposals"
        ],
    )

    issues = validate_contract(contract)

    assert any(
        issue.code == "schema.strict_root_undeclared"
        and issue.path == "map_observation_proposals"
        for issue in issues
    )


def test_generation_center_schema_contract_forbids_llm_controlled_fields() -> None:
    contract = _load_contract("world_generation_core_entity")

    assert {"status", "approved_by", "novel_id", "id"} <= set(contract.forbidden_fields)
    assert {
        ("name", "core_entities.name"),
        ("summary", "core_entities.summary"),
        ("details", "core_entities.content_json.details"),
    } <= {(mapping.source, mapping.target) for mapping in contract.required_mappings}


def test_forbidden_field_validator_reports_status_as_p1() -> None:
    contract = PromptContract(
        id="forbidden_status",
        version=1,
        owner="tests",
        schema_model="modules.outline.generation.models.SimpleStructureOutput",
        declared_prompt_fields=["plot_threads.status"],
        forbidden_fields=["status"],
    )

    issues = validate_contract(contract)

    assert any(
        issue.severity == "P1"
        and issue.code == "field.forbidden"
        and issue.path == "plot_threads.status"
        for issue in issues
    )


def test_required_mapping_validator_reports_missing_phase2_delta_map_target() -> None:
    contract = _load_contract("phase2_world_extraction")
    contract = replace(
        contract,
        required_mappings=[
            mapping
            for mapping in contract.required_mappings
            if not (
                mapping.source == "deltas.subject_name"
                and mapping.target == "map_observations.target_name"
            )
        ],
    )

    issues = validate_contract(contract)

    assert any(
        issue.severity == "P1"
        and issue.code == "mapping.required_missing"
        and issue.path == "deltas.subject_name -> map_observations.target_name"
        for issue in issues
    )


def test_target_table_validator_accepts_allowlisted_table_columns() -> None:
    contract = PromptContract(
        id="targets",
        version=1,
        owner="tests",
        schema_model="modules.imports.llm_schemas.Phase2WorldExtractionOutput",
        required_mappings=[
            FieldMapping("objects.name", "core_entities.name"),
            FieldMapping("relations.relation_type", "entity_relations.relation_type"),
            FieldMapping("deltas.category", "delta_log.category"),
            FieldMapping("deltas.subject_name", "map_observations.target_name"),
        ],
    )

    issues = validate_contract(contract)

    assert not [issue for issue in issues if issue.code.startswith("target.")]


def test_golden_fixtures_validate_against_all_schema_models() -> None:
    contracts = load_contracts()

    issues = [issue for contract in contracts for issue in validate_fixture(contract)]

    assert issues == []


def test_phase2_delta_subject_probe_passes() -> None:
    contract = _load_contract("phase2_world_extraction")

    issues = validate_contract(contract)

    assert not [
        issue
        for issue in issues
        if issue.code == "probe.phase2_delta_subject_to_map_target"
    ]


def test_all_prompt_contracts_pass_static_validation() -> None:
    issues = validate_contracts(load_contracts())

    assert issues == []


def test_phase3_simple_structure_contract_no_longer_declares_status() -> None:
    contract = _load_contract("phase3_structure_simple")

    assert "status" not in contract.declared_prompt_fields
    assert "plot_threads.current_stage" in {
        mapping.source for mapping in contract.required_mappings
    }


def test_generation_center_template_validator_reports_missing_variable() -> None:
    from modules.world.services.worldbuilding.generation_prompt_template_service import (
        validate_template,
    )

    issues = validate_template(
        prompt_text="聚焦 {{trope}}，写清楚誓言、神术、阵营冲突。",
        object_template="character",
        variables_json=[{"name": "trope", "required": True}],
        template_variables={},
    )

    assert any(issue.code == "variable.required_missing" for issue in issues)


def test_generation_center_template_validator_reports_unsupported_type() -> None:
    from modules.world.services.worldbuilding.generation_prompt_template_service import (
        validate_template,
    )

    issues = validate_template(
        prompt_text="这是足够长的安全模板。",
        object_template="unknown",
        variables_json=[],
    )

    assert any(issue.code == "template.unsupported_type" for issue in issues)


def test_generation_center_template_validator_rejects_expressions_and_loops() -> None:
    from modules.world.services.worldbuilding.generation_prompt_template_service import (
        validate_template,
    )

    issues = validate_template(
        prompt_text="聚焦 {{#each items}} 和 {{user.name|escape}}，生成对象草稿。",
        object_template="character",
        variables_json=[],
    )

    assert any(issue.code == "variable.invalid_placeholder" for issue in issues)


def test_prompt_contract_json_report_is_stable_for_generation_contract() -> None:
    contract = _load_contract("world_generation_core_entity")

    payload = format_json([contract], [])

    assert payload == (
        '{"contracts": ["world_generation_core_entity"], '
        '"issue_count": 0, "issues": []}'
    )


def _load_contract(contract_id: str) -> PromptContract:
    return next(contract for contract in load_contracts() if contract.id == contract_id)


def _write_contract(path: Path, overrides: dict) -> None:
    data = {
        "id": "contract",
        "version": 1,
        "owner": "tests",
        "schema_model": "modules.imports.llm_schemas.SceneSlicingOutput",
        "declared_prompt_fields": [],
        "forbidden_fields": [],
        "required_mappings": [],
        "observed_fields": [],
        "ignored_fields": [],
        "probes": [],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
