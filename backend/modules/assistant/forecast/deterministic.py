"""Turn actual domain receipts into bounded suggestions without provider calls."""

from modules.assistant.forecast.contracts import CandidateProposal, Statement
from modules.assistant.forecast.ranking import stable_issue_key
from modules.assistant.forecast.registry import SEMANTIC


def calculate(ctx, selected):
    rows, covered = [], set()
    facts = list(ctx.facts)
    if "assistant.cross_domain_root.v1" in selected:
        facts += [
            (
                fact.model_copy(
                    update={
                        "capability_id": "assistant.cross_domain_root.v1",
                        "title": "同一处改动的跨领域影响",
                        ("summary"): (
                            "这些领域引用指向同一个来源。各域意见与遗漏分别保留，需在各自原页面核对和确认。"
                        ),
                    }
                ),
                ref,
            )
            for fact, ref in facts
            if fact.capability_id == "world.rule_impact.v1"
        ]
    for fact, ref in facts:
        capability = fact.capability_id
        if capability not in selected or capability in SEMANTIC:
            continue
        covered.add(capability)
        if not fact.actionable:
            continue
        proposal = CandidateProposal(
            title=fact.title,
            kind="prepared_reference",
            verdict="propose",
            statements=[
                Statement(
                    text=fact.summary, basis="observed", evidence_ids=[ref.evidence_id]
                )
            ],
            why_now=fact.scope_label,
            unknowns=fact.unknowns,
        )
        rows.append(
            {
                "issue_key": stable_issue_key(
                    capability, ctx.scope.audience_key, fact.subject, "domain_receipt"
                ),
                "capability_id": capability,
                "tier": "next",
                "payload": {
                    "proposal": proposal.model_dump(mode="json"),
                    "evidence": [ref.model_dump(mode="json")],
                    "knowledge_review": {
                        "status": "deterministic",
                        "coverage": fact.scope_label,
                    },
                    "ranking": {
                        "task_help": 2,
                        "evidence": 2,
                        "executable": int(bool(fact.target)),
                    },
                    "navigation": fact.target,
                    "preparations": fact.preparations,
                    "actions": [
                        *[
                            {
                                "action_id": value["action_id"],
                                "label": value["label"],
                                "kind": "prepare_domain",
                                "requires_confirmation": True,
                                "available": True,
                            }
                            for value in fact.preparations
                        ],
                        *(
                            [
                                {
                                    "action_id": "forecast.open_domain",
                                    "label": "在原页面处理",
                                    "kind": "inspect",
                                    "requires_confirmation": False,
                                    "available": True,
                                }
                            ]
                            if fact.target
                            else []
                        ),
                        *(
                            [
                                {
                                    "action_id": "project.prepare_task",
                                    "label": "加入稍后处理",
                                    "kind": "prepare_domain",
                                    "requires_confirmation": True,
                                    "available": True,
                                }
                            ]
                            if ctx.scope.persona == "author"
                            else []
                        ),
                    ],
                },
            }
        )
    missing = set(selected) - SEMANTIC - covered
    return rows, missing
