from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from .models import ContractIssue

REPO_ROOT = Path(__file__).resolve().parents[3]


def phase2_delta_subject_to_map_target(contract_id: str) -> list[ContractIssue]:
    from modules.imports.llm_schemas import Phase2WorldDelta
    from modules.imports.phase2_world_extraction import _to_delta_event

    delta = Phase2WorldDelta(
        subject_name="克莱恩",
        category="location",
        field="current_location",
        new="廷根",
        supporting_scene_ids=["scene-1"],
    )
    event = _to_delta_event(delta)
    if event.meta.get("target_name") == "克莱恩":
        return []
    return [
        ContractIssue(
            severity="P1",
            contract_id=contract_id,
            code="probe.phase2_delta_subject_to_map_target",
            message="Phase2 delta subject_name is not exposed as map target_name.",
            path="deltas.subject_name",
        )
    ]


def generation_center_builtin_templates_validate(
    contract_id: str,
) -> list[ContractIssue]:
    from modules.world.services.worldbuilding.generation_prompt_template_service import (
        BUILTIN_GENERATION_TEMPLATES,
        validate_template,
    )

    issues: list[ContractIssue] = []
    for key, template in BUILTIN_GENERATION_TEMPLATES.items():
        validation_issues = validate_template(
            prompt_text=str(template.get("prompt_text", "")),
            object_template=str(template.get("object_template", "")),
            variables_json=list(template.get("variables_json", [])),
        )
        for issue in validation_issues:
            if issue.severity == "P1":
                issues.append(
                    ContractIssue(
                        severity="P1",
                        contract_id=contract_id,
                        code=f"builtin_template.{issue.code}",
                        message="Built-in Generation Center template is invalid.",
                        path=f"builtin:{key}.{issue.path or ''}".rstrip("."),
                    )
                )
    return issues


def generation_center_frontend_template_options_match(
    contract_id: str,
) -> list[ContractIssue]:
    from modules.world.services.worldbuilding.generation_prompt_template_service import (
        BUILTIN_GENERATION_TEMPLATES,
        SUPPORTED_OBJECT_TEMPLATES,
    )

    view_path = REPO_ROOT / "frontend-console" / "views" / "generateView.js"
    text = view_path.read_text(encoding="utf-8")
    match = re.search(r"const TEMPLATE_TYPE_OPTIONS = \[(.*?)\]", text, re.S)
    if not match:
        return [
            ContractIssue(
                severity="P1",
                contract_id=contract_id,
                code="frontend.template_options_missing",
                message=(
                    "Generation Center frontend template type options were not found."
                ),
                path="frontend-console/views/generateView.js",
            )
        ]
    issues: list[ContractIssue] = []
    frontend_options = set(re.findall(r'"([^"]+)"', match.group(1)))
    backend_options = set(SUPPORTED_OBJECT_TEMPLATES)
    if frontend_options != backend_options:
        issues.append(
            ContractIssue(
                severity="P1",
                contract_id=contract_id,
                code="frontend.template_options_drift",
                message=(
                    "Generation Center frontend template type options differ from "
                    "backend supported object templates."
                ),
                path="frontend-console/views/generateView.js",
            )
        )

    prompts_match = re.search(
        r"const BUILTIN_TEMPLATE_PROMPTS = \{(.*?)\n\}",
        text,
        re.S,
    )
    if not prompts_match:
        issues.append(
            ContractIssue(
                severity="P1",
                contract_id=contract_id,
                code="frontend.template_prompts_missing",
                message="Generation Center frontend fallback prompts were not found.",
                path="frontend-console/views/generateView.js",
            )
        )
        return issues

    frontend_prompts = {
        key: json.loads(literal)
        for key, literal in re.findall(
            r'^\s*(\w+):\s*("(?:\\.|[^"\\])*")',
            prompts_match.group(1),
            re.M,
        )
    }
    backend_prompts = {
        key: str(template["prompt_text"])
        for key, template in BUILTIN_GENERATION_TEMPLATES.items()
    }
    if frontend_prompts != backend_prompts:
        issues.append(
            ContractIssue(
                severity="P1",
                contract_id=contract_id,
                code="frontend.template_prompts_drift",
                message=(
                    "Generation Center frontend fallback prompts differ from "
                    "backend built-in templates."
                ),
                path="frontend-console/views/generateView.js",
            )
        )
    return issues


def generation_center_docs_commands_present(contract_id: str) -> list[ContractIssue]:
    required = {
        "Makefile": ["prompt-contracts", "generate-e2e"],
        "docs/prompts/Prompt体系设计.md": [
            "world_generation_core_entity",
            "make prompt-contracts",
        ],
        "backend/modules/world/README.md": [
            "generation-prompt-templates",
            "template_version_conflict",
            "make generate-e2e",
        ],
        "frontend-console/e2e/scenario-coverage.md": ["make generate-e2e"],
    }
    issues: list[ContractIssue] = []
    for relative, needles in required.items():
        path = REPO_ROOT / relative
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                issues.append(
                    ContractIssue(
                        severity="P2",
                        contract_id=contract_id,
                        code="docs.command_or_contract_missing",
                        message=(
                            "Generation Center prompt-template docs are missing an "
                            "expected command or contract reference."
                        ),
                        path=f"{relative}:{needle}",
                    )
                )
    return issues


PROBES: dict[str, Callable[[str], list[ContractIssue]]] = {
    "generation_center_builtin_templates_validate": (
        generation_center_builtin_templates_validate
    ),
    "generation_center_docs_commands_present": (generation_center_docs_commands_present),
    "generation_center_frontend_template_options_match": (
        generation_center_frontend_template_options_match
    ),
    "phase2_delta_subject_to_map_target": phase2_delta_subject_to_map_target,
}


def run_probe(name: str, contract_id: str) -> list[ContractIssue]:
    return PROBES[name](contract_id)
