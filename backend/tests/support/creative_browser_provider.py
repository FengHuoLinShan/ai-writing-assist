"""Synthetic provider responses only; browser still uses real API, SQL and worker."""

import json

from infrastructure.llm.schemas import LLMCallResponse, LLMUsage


def structured_reply(request):
    final = request.messages[-1].content
    if "schema: " not in final:
        return None
    schema = json.loads(final.split("schema: ", 1)[1])["title"]
    if schema == "SceneSlicingOutput":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        chapters = json.loads(
            user.split("<CHAPTER_TEXT_JSON>", 1)[1].split("</CHAPTER_TEXT_JSON>", 1)[0]
        )
        value = {
            "window_edges": {
                "leading_relation": "new_scene",
                "trailing_relation": "ends_in_input",
            },
            "scenes": [
                {
                    "title": chapter["title"],
                    "goal": "阅读正文变化",
                    "core_conflict_status": "not_applicable",
                    "start_chapter": chapter["chapter_index"],
                    "end_chapter": chapter["chapter_index"],
                    "start_anchor": chapter["content"][:40],
                    "end_anchor": chapter["content"][-40:],
                    "boundary_status": "complete",
                    "confidence": 0.7 if chapter["content"] == "边界需要核对。" else 0.95,
                }
                for chapter in chapters
            ],
        }
    elif schema == "SceneSample":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        quote = user.splitlines()[1]
        value = {
            "observations": [
                {
                    "predicate": quote,
                    "quote": quote,
                    "modality": "event_observed",
                }
            ],
            "scene_events": [],
        }
        location = (
            "白石城"
            if "林舟在白石城。" in quote
            else ("渡口" if "林舟出现在渡口" in quote else None)
        )
        if location:
            value["observations"][0]["mentions"] = [
                {"surface": "林舟", "entity_type": "character"}
            ]
            value["scene_events"] = [
                {
                    "dimension": "locations",
                    "event_type": "entity_moved",
                    "subject_surface": "林舟",
                    "snapshot_after": {"text_state": location},
                    "source_observation_indices": [0],
                }
            ]
    elif schema == "StateReview":
        payload = json.loads(
            next(
                message.content for message in request.messages if message.role == "user"
            )
        )
        value = {
            "events": [
                {
                    "event_index": index,
                    "verdict": "supported",
                    "reason": "fixture在场",
                    "quotes": [payload["scene_text"]],
                }
                for index, _ in enumerate(payload["events"])
            ]
        }
    elif schema == "Phase2aSceneExtractionOutput":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        current = json.loads(
            user.split("<untrusted_scene_context_json>", 1)[1].split("</", 1)[0]
        )["current_scene_text"]
        if "林舟又名小舟。" in current:
            quote = "林舟又名小舟。林舟和青竹是盟友。"
            value = {
                "entities": [
                    {
                        "name": name,
                        "entity_type": "character",
                        "identity_disposition": "new",
                        "evidence_quotes": [quote],
                        "field_evidence": {"name": [quote], "entity_type": [quote]},
                        "confidence": 0.95,
                    }
                    for name in ("林舟", "青竹")
                ]
            }
        else:
            value = {}
    elif schema == "AliasRelationExtractionOutput":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        context = json.loads(
            user.split("<untrusted_phase2b_context_json>", 1)[1].split("</", 1)[0]
        )
        refs = {
            item["name"]: item["prompt_ref"] for item in context["identity_candidates"]
        }
        value = (
            {
                "aliases": [
                    {
                        "entity_ref": refs["林舟"],
                        "alias": "小舟",
                        "identity_scope": "durable",
                        "identity_basis": "原文又名",
                        "evidence_quotes": ["林舟又名小舟。"],
                        "confidence": 0.95,
                    }
                ]
            }
            if "林舟" in refs
            else {}
        )
    elif schema == "SceneEnrichmentOutput":
        value = {
            "narrative_tag": "transition",
            "narrative_function": "承接场景行动",
            "confidence": 0.9,
        }
    elif schema == "AuditVerdictOutput":
        value = {
            "verdict": "pass",
            "findings": [],
            "dimensions": [
                {"dimension": item, "checked": True}
                for item in (
                    "prior_prose",
                    "world_rules",
                    "world_entities",
                    "outline",
                    "scene_state",
                    "imported_assets",
                )
            ],
        }
    elif schema == "SimpleStructureOutput":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        cards = json.loads(user.split("【Scene卡片 JSON】\n", 1)[1].split("\n\n", 1)[0])
        value = {
            "plot_threads": [
                {
                    "title": "本轮剧情线索",
                    "summary": cards[0]["summary"],
                    "confidence": 0.95,
                    "supporting_scene_ids": [card["scene_id"] for card in cards],
                }
            ]
        }
    elif schema == "StructureEvidenceReviewOutput":
        user = next(
            message.content for message in request.messages if message.role == "user"
        )
        value = {
            "reviews": [
                {
                    "candidate_id": item["candidate_id"],
                    "verdict": "supported",
                    "confidence": 0.96,
                    "evidence": [{"quote": item["scene_text"]}],
                }
                for item in json.loads(user)["review_items"]
            ]
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
            can_revise = "revise" in payload["recipe"]["capabilities"]
            if revision == 0:
                items = [
                    {
                        "logical_key": "cause",
                        "capability": "investigate",
                        "question": "查清有限合作的动机",
                    }
                ]
            elif revision == 1 and can_revise:
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
            elif revision == 2 and can_revise:
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
                "finish": revision >= (3 if can_revise else 1),
                "reason": "核对两种解释",
            }
        elif schema == "WorkOutput":
            value = {"summary": payload["question"], "claims": []}
            if payload["question"] == "查清有限合作的动机":
                source = json.loads(payload["sources"].split("\n派生理解", 1)[0])[0]
                value["claims"] = [
                    {
                        "kind": "interpretation",
                        "text": "她接受帮助，但信任程度仍需核对。",
                        "evidence_keys": [source["key"]],
                    }
                ]
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
