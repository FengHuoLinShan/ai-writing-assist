"""Frozen three-arm orchestration contracts with a deterministic provider substitute."""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pydantic_ai import Tool

from evals.experiment import experiment_evidence
from evals.review import export_review_html, export_review_jsonl
from evals.schemas import DatasetCase
from infrastructure.llm.agent_runtime import (
    AgentAllocation,
    AgentRunBudget,
    agent_allocation,
    run_project_agent,
)
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.collaboration import WorkItem, content_hash, run_work_items
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMToolCall,
)
from infrastructure.llm.workflow_budget import workflow_budget
from modules.assistant.teams.contracts import DEEP_REVIEW_ROLES, Investigation
from modules.assistant.teams.review_methods import review_methods

SOURCE = "昨日林晚承诺守住大门。今日他离开了，但作者没有说明离开的原因。"
SCOPED_INPUT = {
    "source_hash": content_hash(SOURCE),
    "text": SOURCE,
    "cutoff": 1,
    "allowed_tools": ["read_reference"],
    "allow_web": False,
}


async def run_arm(arm):
    budget = AgentRunBudget(policy_version="team_v1")
    receipts, calls = [], []
    role_names = list(DEEP_REVIEW_ROLES)
    roles = ["all"] if arm == "single_agent" else role_names
    items = [
        WorkItem(
            key=role,
            role=role,
            input_hash=content_hash(SCOPED_INPUT),
            depends_on=[roles[i - 1]] if arm == "workflow" and i else [],
        )
        for i, role in enumerate(roles)
    ]

    async def checkpoint(values):
        receipts.append(values)

    async def read_reference() -> dict:
        """Read the same frozen source; no external or cross-project access."""
        return dict(SCOPED_INPUT)

    tool = Tool(read_reference)

    async def investigate(item):
        assigned = role_names if item.role == "all" else [item.role]
        instructions = "\n".join(
            text
            for role in assigned
            for text in review_methods("deep_review", role).values()
        )

        scripted_output = {
            "summary": "离开的动机缺失，不能据此认定作者写错。",
            "checked_dimensions": assigned,
            "omissions": ["离开的原因尚未给出；不替代领域复核。"],
        }

        class ScriptedClient:
            model_name = "offline-scripted-collaboration"

            async def generate(self, request, *, transport_retries):
                calls.append(
                    {
                        "role": item.role,
                        "input_hash": content_hash(request.model_dump(mode="json")),
                    }
                )
                output_tool = next(
                    tool for tool in request.tools if tool.name.startswith("final_result")
                )
                return LLMCallResponse(
                    tool_calls=[
                        LLMToolCall(
                            id=f"answer-{item.role}",
                            name=output_tool.name,
                            arguments=json.dumps(scripted_output),
                        )
                    ]
                )

            async def generate_structured(self, request, schema, **kwargs):
                await meter.before_request()
                calls.append(
                    {
                        "role": item.role,
                        "input_hash": content_hash(request.model_dump(mode="json")),
                    }
                )
                await meter.completed(None)
                return schema.model_validate(scripted_output)

        # All three modes receive identical allowed evidence and method coverage.
        # Workflow chooses its three stages in code; members never delegate.
        with agent_allocation(
            AgentAllocation(
                item.key, request_limit=12 if item.role == "all" else 4, final_reserve=12
            )
        ):
            if arm == "workflow":
                evidence = await read_reference()
                with workflow_budget(budget, checkpoint, future_requests=12) as meter:
                    output = await run_managed_structured(
                        ScriptedClient(),
                        LLMCallRequest(
                            messages=[
                                LLMMessage(role="system", content=instructions),
                                LLMMessage(
                                    role="user",
                                    content=json.dumps(evidence, ensure_ascii=False),
                                ),
                            ]
                        ),
                        Investigation,
                        step_name="eval.deep_review.fixed_stage",
                        max_fix_attempts=0,
                        transport_retries=False,
                    )
                return output.model_dump(mode="json")
            answer = await run_project_agent(
                ScriptedClient(),
                LLMCallRequest(
                    messages=[
                        LLMMessage(role="system", content=instructions),
                        LLMMessage(
                            role="user",
                            content=json.dumps(SCOPED_INPUT, ensure_ascii=False),
                        ),
                    ]
                ),
                tools=[tool],
                deps=SimpleNamespace(),
                output_type=Investigation,
                budget=budget,
                input_limit=16000,
            )
        return answer.output.model_dump(mode="json")

    await run_work_items(
        items,
        roles=set(roles),
        execute=investigate,
        checkpoint=checkpoint,
        concurrency=3 if arm == "bounded_team" else 1,
    )
    before = len(calls)
    await run_work_items(
        items,
        roles=set(roles),
        execute=investigate,
        checkpoint=checkpoint,
        concurrency=3 if arm == "bounded_team" else 1,
    )
    return {
        "arm": arm,
        "scope_hash": content_hash(SCOPED_INPUT),
        "tool_contract_hash": content_hash(tool.function_schema.json_schema),
        "profile": {"model": "offline-scripted-collaboration", "provider": "in_process"},
        "budget_limit": {
            "requests": 30,
            "tools": 48,
            "investigation": 12,
            "final_reserve": 12,
        },
        "scripted_requests": len(calls),
        "provider_requests": 0,
        "usage": {
            "input_tokens": None,
            "output_tokens": None,
            "reason": "no_model_executed",
        },
        "recovery_repeated_requests": len(calls) - before,
        "domain_verification": "not_run_in_scheduler_lab",
        "results": [item.output for item in items],
        "statuses": [item.status for item in items],
    }


async def run():
    arms = [await run_arm(arm) for arm in ("single_agent", "workflow", "bounded_team")]
    return {
        "evidence": experiment_evidence(
            dataset=SCOPED_INPUT,
            source_fingerprints={"synthetic-commitment": content_hash(SOURCE)},
            implementation_files=[Path(__file__)],
            receipts=[],
        ),
        "scope": (
            "orchestration contracts only; domain acceptance "
            "has separate PostgreSQL tests"
        ),
        "arms": arms,
    }


def export_blind_review(report, directory):
    """Reuse the repository human-review format, withholding arm labels and gold."""
    mapping, cases = {}, []
    ordered = sorted(
        report["arms"], key=lambda arm: content_hash(arm["arm"] + content_hash(SOURCE))
    )
    for i, arm in enumerate(ordered, 1):
        case_id = f"blind-review-{i:02d}"
        mapping[case_id] = arm["arm"]
        cases.append(
            DatasetCase(
                case_id=case_id,
                suite="world",
                scenario="review_candidate",
                source_group_id="synthetic-commitment",
                split="dev",
                input={"text": SOURCE, "status": "脚本替身样本，仅用于检查评审材料流程"},
                reference={
                    "candidate": {
                        "summary": "\n".join(
                            dict.fromkeys(item["summary"] for item in arm["results"])
                        ),
                        "findings": list(
                            {
                                content_hash(finding): finding
                                for item in arm["results"]
                                for finding in item["findings"]
                            }.values()
                        ),
                        "checked_dimensions": sorted(
                            {
                                dimension
                                for item in arm["results"]
                                for dimension in item["checked_dimensions"]
                            }
                        ),
                        "omissions": list(
                            dict.fromkeys(
                                omission
                                for item in arm["results"]
                                for omission in item["omissions"]
                            )
                        ),
                    }
                },
            )
        )
    export_review_html(cases, directory / "blind-review.html")
    export_review_jsonl(cases, directory / "blind-review.jsonl")
    (directory / "blind-review-key.private.json").write_text(
        json.dumps(mapping, indent=2)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "collaboration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    export_blind_review(report, args.output_dir)


if __name__ == "__main__":
    main()
