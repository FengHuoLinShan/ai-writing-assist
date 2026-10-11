"""AI 用量诊断的能力名映射必须覆盖真实能力编号。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from modules.evidence.compilation.knowledge.policies import CAPABILITY_REGISTRY
from modules.project.ai_usage import _capability_label


def test_common_capability_ids_resolve_to_author_labels() -> None:
    assert _capability_label("writing.generate") == "AI 写作"
    assert _capability_label("writing.semantic_review") == "正文独立审查"
    assert _capability_label("writing.targeted_revision") == "定向返修"
    assert _capability_label("writing.comment_revision") == "批注改写"
    # 前缀回退：冲突检查的两个子能力共享命名空间标签
    assert _capability_label("writing.conflict_check.ai_review") == "设定冲突检查"
    assert _capability_label("writing.conflict_check.ai_suggestion") == "设定冲突检查"
    assert _capability_label("story.outline.analyze") == "大纲整理"
    assert _capability_label("world.generation.suggestion") == "世界观生成"
    assert _capability_label("infrastructure.rag_index_chapter") == "资料索引"
    assert _capability_label("interaction.forecast") == "读者互动"


def test_unknown_capability_still_shows_raw_id() -> None:
    assert _capability_label("totally.unknown") == "其他 AI 能力（totally.unknown）"
    assert _capability_label("") == "其他 AI 能力（）"


def test_every_registered_capability_has_a_label() -> None:
    """注册表与绑定表里的真实能力编号不得落入"其他 AI 能力"回退。

    之前的映射表用了虚构编号（如 writing.generation），导致最常用的
    写作能力在界面上显示内部 id。
    """
    from tools.prompt_contracts.capability_bindings import CAPABILITY_BINDINGS

    registered = set(CAPABILITY_REGISTRY)
    for capability_ids in CAPABILITY_BINDINGS.values():
        registered.update(capability_ids)
    unlabeled = sorted(
        capability_id
        for capability_id in registered
        if _capability_label(capability_id).startswith("其他 AI 能力")
    )
    assert unlabeled == []


@pytest.mark.asyncio
async def test_get_project_ai_usage_keeps_unknown_and_unconfirmed_markers(
    db_session,
    project_factory,
) -> None:
    """BR-0a：未知用量与计费未确认要透传到诊断入口，已知数字不变。"""
    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
    from infrastructure.tasks.models import AsyncTask
    from modules.project.ai_usage import get_project_ai_usage

    novel_id = str(await project_factory.create_project(title="用量未知"))
    known = {
        "version": 1,
        "operation_id": "op-known",
        "run_id": "run-known",
        "root_capability_id": "writing.generate",
        "novel_id": novel_id,
        "started_at": datetime.now(UTC).isoformat(),
        "request_limit": 10,
        "requests_started": 2,
        "requests_settled": 2,
        "steps": [
            {
                "step_name": "writing.generate.chunk",
                "step_capability_id": "writing.generate",
                "call_kind": "structured",
                "requests_started": 2,
                "requests_settled": 2,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        ],
    }
    partial_unknown = {
        "version": 1,
        "operation_id": "op-partial-unknown",
        "run_id": "run-partial-unknown",
        "root_capability_id": "writing.semantic_review",
        "novel_id": novel_id,
        "started_at": datetime.now(UTC).isoformat(),
        "request_limit": 10,
        "requests_started": 3,
        "requests_settled": 2,
        "requests_unknown": 1,
        "usage_complete": False,
        "charge_state": "possible",
        "steps": [
            {
                "step_name": "writing.semantic_review.chunk",
                "step_capability_id": "writing.semantic_review",
                "call_kind": "structured",
                "requests_started": 3,
                "requests_settled": 2,
                "requests_unknown": 1,
                "usage": {"prompt_tokens": 30, "completion_tokens": 20},
                "charge_state": "possible",
                "usage_complete": False,
            }
        ],
    }
    db_session.add_all(
        [
            AsyncTask(
                id=uuid.uuid4(),
                task_type="writing_generate",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: known},
            ),
            AsyncTask(
                id=uuid.uuid4(),
                task_type="writing_semantic_review",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: partial_unknown},
            ),
        ]
    )
    await db_session.flush()

    usage = await get_project_ai_usage(db_session, novel_id, days=30)

    # 已知部分数字不变
    assert usage["totals"]["requests"] == 4
    assert usage["totals"]["input_tokens"] == 130
    assert usage["totals"]["output_tokens"] == 70
    # 未知与未确认如实保留
    assert usage["totals"]["requests_unknown"] == 1
    assert usage["totals"]["charge_unconfirmed"] is True
    by_capability = {item["capability"]: item for item in usage["capabilities"]}
    assert by_capability["writing.generate"]["requests_unknown"] == 0
    assert by_capability["writing.generate"]["charge_unconfirmed"] is False
    assert by_capability["writing.semantic_review"]["requests_unknown"] == 1
    assert by_capability["writing.semantic_review"]["charge_unconfirmed"] is True


# =====================================================# BR-7: 用量按作品成果归因（只读查询，不做配额策略变化）
# =====================================================


async def _add_outcome_confirmation(
    db_session,
    novel_id: str,
    *,
    result_status: str,
    task_id: str,
) -> None:
    """构造带任务与草稿结果引用的确认记录（等价 attach_result_ref 链）。"""
    from modules.evidence.compilation.models import (
        ContextConfirmation,
        ContextConfirmationAssetRef,
    )

    record = ContextConfirmation(
        novel_id=uuid.UUID(novel_id),
        action="writing.generate",
        task="生成正文建议",
        scope="chapter",
        result_refs=[
            {"type": "task", "id": task_id},
            {"type": "writing_draft", "id": f"draft-{task_id}"},
        ],
        result_status=result_status,
    )
    db_session.add(record)
    await db_session.flush()
    for ref in record.result_refs:
        db_session.add(
            ContextConfirmationAssetRef(
                confirmation_id=record.id,
                novel_id=record.novel_id,
                asset_role="result",
                asset_type=ref["type"],
                asset_id=ref["id"],
            )
        )
    await db_session.flush()


def _usage_envelope(novel_id: str, capability: str, *, unknown: int = 0) -> dict:
    settled = 2
    return {
        "version": 1,
        "operation_id": f"op-{capability}-{unknown}",
        "run_id": f"run-{capability}-{unknown}",
        "root_capability_id": capability,
        "novel_id": novel_id,
        "started_at": datetime.now(UTC).isoformat(),
        "request_limit": 10,
        "requests_started": settled + unknown,
        "requests_settled": settled,
        "requests_unknown": unknown,
        **(
            {
                "usage_complete": False,
                "charge_state": "possible",
            }
            if unknown
            else {}
        ),
        "steps": [
            {
                "step_name": f"{capability}.chunk",
                "step_capability_id": capability,
                "call_kind": "structured",
                "requests_started": settled + unknown,
                "requests_settled": settled,
                "requests_unknown": unknown,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                **(
                    {
                        "usage_complete": False,
                        "charge_state": "possible",
                    }
                    if unknown
                    else {}
                ),
            }
        ],
    }


@pytest.mark.asyncio
async def test_get_project_ai_usage_attributes_usage_by_outcome(
    db_session,
    project_factory,
) -> None:
    """已采用 / 未采用返修 / 失败恢复 / 其他辅助四桶各归其位。"""
    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
    from infrastructure.tasks.models import AsyncTask
    from modules.project.ai_usage import get_project_ai_usage

    novel_id = str(await project_factory.create_project(title="成果归因"))
    adopted_id, rejected_id = uuid.uuid4(), uuid.uuid4()
    failed_id, pending_id, other_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            AsyncTask(
                id=adopted_id,
                task_type="writing_generate",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: _usage_envelope(novel_id, "writing.generate")},
            ),
            AsyncTask(
                id=rejected_id,
                task_type="writing_generate",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: _usage_envelope(novel_id, "writing.generate")},
            ),
            AsyncTask(
                id=failed_id,
                task_type="writing_generate",
                status="failed",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: _usage_envelope(novel_id, "writing.generate")},
            ),
            AsyncTask(
                id=pending_id,
                task_type="writing_generate",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: _usage_envelope(novel_id, "writing.generate")},
            ),
            AsyncTask(
                id=other_id,
                task_type="embedding_build",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={
                    AI_RUN_ENVELOPE_KEY: _usage_envelope(
                        novel_id, "infrastructure.embedding"
                    )
                },
            ),
        ]
    )
    await _add_outcome_confirmation(
        db_session, novel_id, result_status="adopted", task_id=str(adopted_id)
    )
    await _add_outcome_confirmation(
        db_session, novel_id, result_status="rejected", task_id=str(rejected_id)
    )
    await _add_outcome_confirmation(
        db_session, novel_id, result_status="running", task_id=str(failed_id)
    )
    await _add_outcome_confirmation(
        db_session, novel_id, result_status="done", task_id=str(pending_id)
    )
    await db_session.flush()

    usage = await get_project_ai_usage(db_session, novel_id, days=30)

    buckets = {bucket["key"]: bucket for bucket in usage["attribution"]["buckets"]}
    assert set(buckets) == {
        "adopted",
        "pending",
        "not_adopted",
        "failed",
        "other",
    }
    assert buckets["adopted"]["tasks"] == 1
    assert buckets["adopted"]["requests"] == 2
    assert buckets["adopted"]["input_tokens"] == 100
    assert buckets["not_adopted"]["tasks"] == 1
    assert buckets["not_adopted"]["requests"] == 2
    assert buckets["failed"]["tasks"] == 1
    assert buckets["failed"]["requests"] == 2
    assert buckets["pending"]["tasks"] == 1
    assert buckets["pending"]["requests"] == 2
    # 没有确认引用的任务单列为辅助消耗，不并入任何成果桶
    assert buckets["other"]["tasks"] == 1
    assert buckets["other"]["requests"] == 2
    for bucket in buckets.values():
        assert bucket["requests_unknown"] == 0
        assert bucket["charge_unconfirmed"] is False
    # 既有能力聚合与总量不受归因影响
    assert usage["totals"]["requests"] == 10


@pytest.mark.asyncio
async def test_get_project_ai_usage_attribution_keeps_unknown_markers(
    db_session,
    project_factory,
) -> None:
    """归因桶沿用 BR-0a 语义：未知请求单列，不折算为 0 或并入已知数。"""
    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
    from infrastructure.tasks.models import AsyncTask
    from modules.project.ai_usage import get_project_ai_usage

    novel_id = str(await project_factory.create_project(title="归因未知标记"))
    adopted_id, other_unknown_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            AsyncTask(
                id=adopted_id,
                task_type="writing_generate",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={AI_RUN_ENVELOPE_KEY: _usage_envelope(novel_id, "writing.generate")},
            ),
            AsyncTask(
                id=other_unknown_id,
                task_type="embedding_build",
                status="succeeded",
                novel_id=uuid.UUID(novel_id),
                meta={
                    AI_RUN_ENVELOPE_KEY: _usage_envelope(
                        novel_id, "infrastructure.embedding", unknown=2
                    )
                },
            ),
        ]
    )
    await _add_outcome_confirmation(
        db_session, novel_id, result_status="adopted", task_id=str(adopted_id)
    )
    await db_session.flush()

    usage = await get_project_ai_usage(db_session, novel_id, days=30)

    buckets = {bucket["key"]: bucket for bucket in usage["attribution"]["buckets"]}
    assert buckets["adopted"]["requests"] == 2
    assert buckets["adopted"]["requests_unknown"] == 0
    assert buckets["adopted"]["charge_unconfirmed"] is False
    assert buckets["other"]["requests"] == 2
    assert buckets["other"]["requests_unknown"] == 2
    assert buckets["other"]["charge_unconfirmed"] is True
    assert usage["totals"]["requests_unknown"] == 2


@pytest.mark.parametrize("charge_state", ["none", "recorded"])
async def test_legacy_usage_is_incomplete_without_inventing_unknown_requests(
    db_session, project_factory, charge_state
):
    from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
    from infrastructure.tasks.models import AsyncTask
    from modules.project.ai_usage import get_project_ai_usage

    novel_id = str(await project_factory.create_project(title="历史用量不可考"))
    envelope = {
        "version": 1,
        "operation_id": "legacy",
        "run_id": "legacy",
        "root_capability_id": "writing.generate",
        "novel_id": novel_id,
        "started_at": datetime.now(UTC).isoformat(),
        "request_limit": 10,
        "legacy_untracked": True,
        "usage_complete": False,
        "charge_state": charge_state,
        "steps": [],
    }
    db_session.add(
        AsyncTask(
            id=uuid.uuid4(),
            task_type="writing_generate",
            status="succeeded",
            novel_id=uuid.UUID(novel_id),
            meta={AI_RUN_ENVELOPE_KEY: envelope},
        )
    )
    await db_session.flush()
    usage = await get_project_ai_usage(db_session, novel_id)
    assert usage["totals"]["usage_complete"] is False
    assert usage["capabilities"][0]["usage_complete"] is False
    assert usage["totals"]["requests"] == 0
    assert usage["totals"]["requests_unknown"] == 0
    assert usage["totals"]["charge_unconfirmed"] is False
    bucket = next(item for item in usage["attribution"]["buckets"] if item["tasks"])
    assert bucket["usage_complete"] is False
    assert bucket["requests_unknown"] == 0
