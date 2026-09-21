"""Synthetic provider responses only; browser still uses real API, SQL and worker."""

import json

from infrastructure.llm.schemas import LLMCallResponse, LLMUsage


def structured_reply(request):
    final = request.messages[-1].content
    if "schema: " not in final:
        return None
    schema = json.loads(final.split("schema: ", 1)[1])["title"]
    if schema == "AuditVerdictOutput":
        value = {
            "verdict": "pass",
            "findings": [],
            "dimensions": [
                {"dimension": item, "checked": True}
                for item in ("prior_prose", "world_rules", "outline")
            ],
        }
    elif schema in {
        "GraphDelta",
        "WorkOutput",
        "CheckOutput",
        "ReadingNode",
        "ForecastOutput",
    }:
        payload = json.loads(
            next(
                message.content for message in request.messages if message.role == "user"
            )
        )
        if schema == "GraphDelta":
            revision, items = payload["expected_plan_revision"], []
            if revision == 0:
                items = [
                    {
                        "logical_key": "cause",
                        "capability": "investigate",
                        "question": "查清有限合作的动机",
                    }
                ]
            elif revision == 1:
                items = [
                    {
                        "logical_key": key,
                        "capability": "revise",
                        "question": question,
                        "depends_on": ["cause"],
                    }
                    for key, question in (
                        ("caution", "保留谨慎"),
                        ("exchange", "交换条件"),
                    )
                ]
            elif revision == 2:
                trials = [
                    item for item in payload["new_artifacts"] if item["kind"] == "revise"
                ]
                items = [
                    {
                        "logical_key": f"check_{index}",
                        "capability": "test",
                        "question": "检查具体试改",
                        "workspace_revision_id": item["workspace_revision_id"],
                    }
                    for index, item in enumerate(trials)
                ]
                items.append(
                    {
                        "logical_key": "compare",
                        "capability": "compare",
                        "question": "比较原稿与两个改法",
                        "depends_on": ["check_0", "check_1"],
                        "dependency_policy": "all_terminal",
                    }
                )
            value = {
                "expected_plan_revision": revision,
                "items": items,
                "finish": revision >= 3,
                "reason": "核对两种解释",
            }
        elif schema == "WorkOutput":
            value = {"summary": payload["question"], "claims": []}
            if payload["question"] in {"保留谨慎", "交换条件"}:
                source = next(
                    item
                    for item in json.loads(payload["sources"])
                    if item["key"].startswith("writing_draft:")
                )
                value["patches"] = [
                    {
                        "kind": "writing_draft",
                        "id": source["key"].split(":")[1],
                        "value": {
                            **source["content"],
                            "content": source["content"]["content"]
                            + (
                                "她仍保留了退路。"
                                if payload["question"] == "保留谨慎"
                                else "她提出先交换必要的情报。"
                            ),
                        },
                    }
                ]
        elif schema == "CheckOutput":
            value = {
                "verdict": "passed",
                "findings": [],
                "preserved_constraints": payload["constraints"],
                "completed_checks": payload["checks"],
            }
        elif schema == "ReadingNode":
            value = {
                "known": [
                    {
                        "belief": "仅使用这一段可见文字。",
                        "excerpt": payload["prose"][:100],
                    }
                ],
                "unanswered": ["她是否会继续合作，尚未确定。"],
            }
        else:
            source = payload["sources"][0]
            quote = source["text"].strip()[:30]
            value = {
                "items": [
                    {
                        "capability_index": 0,
                        "question_kind": "continuation",
                        "anchor_evidence_id": source["evidence_id"],
                        "anchor_text": quote,
                        "proposal": {
                            "title": "保留一条谨慎合作的退路",
                            "kind": "creative_opportunity",
                            "statements": [
                                {
                                    "text": quote,
                                    "basis": "observed",
                                    "evidence_ids": [source["evidence_id"]],
                                }
                            ],
                            "why_now": "当前动作仍允许一次轻量回应。",
                            "directions": [
                                {
                                    "direction_id": "caution",
                                    "title": "轻量回应",
                                    "condition": "如果希望保留克制",
                                    "proposal": (
                                        "让她提出一个小条件，同时保留退出的余地。"
                                    ),
                                    "narrative_commitment": "low",
                                    "may_leave_open": True,
                                }
                            ],
                            "unknowns": ["这只是本轮测试中的一种创作选择。"],
                            "verdict": "propose",
                        },
                    }
                ]
            }
    else:
        return None
    return LLMCallResponse(
        content=json.dumps(value, ensure_ascii=False),
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
    )
