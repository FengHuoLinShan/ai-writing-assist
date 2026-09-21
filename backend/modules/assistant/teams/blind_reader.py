"""Sequential prose-only reading: later revelations never rewrite earlier beliefs."""

import json

from pydantic_ai import ModelRetry

from core.errors import ConflictError, ValidationError
from infrastructure.llm.agent_runtime import run_project_agent
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.assistant.teams.contracts import TeamAnswer, blueprint_snapshot
from modules.assistant.teams.runner import validate_team_answer
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import read_novel_evidence
from modules.story.contracts import ReadingNode
from modules.writing.facade import build_manuscript_range_ref, list_manuscript_sources


async def run_blind_reading(service, db, task, run_id, payload, deps, profile):
    if payload["team"] != blueprint_snapshot(
        "blind_reader", version=payload["team"].get("version", 1)
    ):
        raise ConflictError("原盲读协议不可恢复，请开始新任务")
    if deps.work.context_confirmation_id:
        raise ValidationError("盲读只解锁已选正文，不能把作者资料确认包交给读者")
    end = deps.work.chapter_index
    start = payload.get("reading_start_chapter") or max(1, end - 7)
    if not start <= end or end - start >= 8:
        raise ValidationError("一次盲读最多八章，请选择连续阅读范围")
    drafts = await list_manuscript_sources(
        db, deps.novel_id, list(range(start, end + 1)), content_mode="working"
    )
    excluded = {value.rsplit(":", 1)[-1] for value in deps.work.excluded_targets}
    if len(drafts) != end - start + 1 or any(draft.id in excluded for draft in drafts):
        raise ConflictError("阅读范围缺章或包含排除资料，请缩小范围")
    drafts = sorted(drafts, key=lambda item: item.chapter_index)
    if any(len(draft.content or "") > 20000 for draft in drafts):
        raise ValidationError("该章超出单次盲读范围，请先划分场景")
    manifest = [
        {
            "draft_id": draft.id,
            "source_hash": draft.content_hash,
            "chapter_index": draft.chapter_index,
        }
        for draft in drafts
    ]
    scope_hash = content_hash(manifest)
    row = await service.require_run(db, deps.novel_id, run_id)
    trail = dict(
        (row.checkpoint_json or {}).get("blind_reading_v1")
        or {"source_hash": scope_hash, "nodes": []}
    )
    if trail["source_hash"] != scope_hash:
        raise ConflictError("正文已变化，请建立新的阅读轨迹；旧猜测不会被改写")
    await db.commit()

    async def checkpoint(_values=None):
        await deps.revalidate(list(deps.evidence_refs))
        row = await service.require_run(db, deps.novel_id, run_id, lock=True)
        if row.status != "running" or str(row.task_id) != str(task.id):
            raise ConflictError("本次盲读已停止")
        row.budget_json = deps.budget.model_dump(mode="json")
        row.checkpoint_json = {
            **row.checkpoint_json,
            "blind_reading_v1": trail,
            "evidence_refs": dict(deps.evidence_refs),
            "collaboration_v1": {
                "blueprint": "blind_reader",
                "scope_hash": scope_hash,
                "phase": "investigating",
                "completion": "partial",
                "items": [],
                "reading_done": len(trail["nodes"]),
                "reading_total": len(drafts),
            },
        }
        await db.commit()

    for index, draft in enumerate(drafts):
        if index < len(trail["nodes"]):
            node = trail["nodes"][index]
            if (
                node["source_hash"] != draft.content_hash
                or content_hash(node["beliefs"]) != node["belief_hash"]
            ):
                raise ConflictError("历史阅读回执失效")
            continue
        source = await build_manuscript_range_ref(
            db,
            deps.novel_id,
            draft_id=draft.id,
            content_mode="working",
            start_offset=0,
            end_offset=len(draft.content or ""),
        )
        value = await read_novel_evidence(
            db,
            novel_id=deps.novel_id,
            source_ref=source,
            visibility=VisibilityContextContract(
                mode="reader",
                cutoff_chapter=draft.chapter_index,
                cutoff_scene_id=str(deps.work.scene_id)
                if deps.work.scene_id and draft.chapter_index == end
                else None,
            ),
            before=0,
            after=0,
        )
        deps.remember(value)
        await db.commit()
        text = value["text"]

        def validate(_ctx, output):
            if any(
                belief.excerpt not in text
                for belief in [*output.known, *output.guesses, *output.newly_revealed]
            ):
                raise ModelRetry(
                    "只能引用刚读过正文中的逐字片段；没有原文支持的猜测不要冒充证据"
                )
            return output

        result = await run_project_agent(
            deps.client,
            LLMCallRequest(
                model=deps.client.model_name,
                messages=[
                    LLMMessage(
                        role="system",
                        content="你是第一次阅读故事的读者。只知道此前冻结认知与本次正文。"
                        "不使用模型对作品的外部记忆或猜测未来当作事实。区分知道、推测和未解问题；"
                        "新增揭示对照早先猜测，但不能修改过去节点。引用只取本段原文。",
                    ),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "prior_beliefs": [
                                    node["beliefs"] for node in trail["nodes"]
                                ],
                                "prose": text,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
            ),
            tools=[],
            deps=None,
            output_type=ReadingNode,
            output_validator=validate,
            budget=deps.budget,
            future_requests=6,
            input_limit=profile.hard_input_tokens,
            checkpoint=checkpoint,
            capability_id="assistant.turn",
        )
        beliefs = result.output.model_dump(mode="json")
        trail["nodes"].append(
            {**manifest[index], "beliefs": beliefs, "belief_hash": content_hash(beliefs)}
        )
        await checkpoint()
    result = await run_project_agent(
        deps.client,
        LLMCallRequest(
            model=deps.client.model_name,
            messages=[
                LLMMessage(
                    role="system",
                    content="根据已经冻结的阅读轨迹，分析铺垫、猜测和揭示是否公平。"
                    "不要把模型猜测当成真实读者偏好；只给建议，不签署领域问题，不提出修改操作。"
                    "保留有意歧义，明确开始章节之前的内容未读。",
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "author_goal": payload["message"],
                            "reading_trail": trail,
                            "evidence": deps.evidence_refs,
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
        ),
        tools=[],
        deps=deps,
        output_type=TeamAnswer,
        output_validator=validate_team_answer,
        budget=deps.budget,
        future_requests=3,
        input_limit=profile.hard_input_tokens,
        checkpoint=checkpoint,
        capability_id="assistant.turn",
    )
    await checkpoint()
    row = await service.require_run(db, deps.novel_id, run_id, lock=True)
    state = dict(row.checkpoint_json["collaboration_v1"])
    state.update(
        {
            "phase": "reviewing",
            "completion": "complete",
            "reading_nodes": trail["nodes"],
            "reading_start_chapter": start,
            "reading_end_chapter": end,
        }
    )
    row.checkpoint_json = {**row.checkpoint_json, "collaboration_v1": state}
    await db.commit()
    return result.output
