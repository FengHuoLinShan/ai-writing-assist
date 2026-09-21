"""T13 入口副作用对齐：助手保存工作稿后与 API 入口同样请求章节重索引。

对应 docs/plans/novelcraft-v4/g0/G0-基线与保护.md §2 的缺口整改（第一段）：
助手改写/新章应用路径此前只写工作稿不触发索引；统一回执（I02）落地前，
先与 api.py / assistant_candidate_tools.py 的既有显式调用对齐。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.evidence.indexing.models import RagIndexState
from modules.writing.assistant_tools import OPERATIONS, ReviseChapter
from modules.writing.facade import create_draft_only


def _context() -> AssistantOperationContext:
    return AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(scope="project")
    )


async def _working_index_states(db: AsyncSession, novel_id: str) -> list[RagIndexState]:
    from uuid import UUID

    return list(
        (
            await db.execute(
                select(RagIndexState)
                .where(
                    RagIndexState.novel_id == UUID(novel_id),
                    RagIndexState.content_mode == "working",
                )
                .order_by(RagIndexState.chapter_index)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_assistant_revise_apply_requests_working_index(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    db, nid = db_session, test_project_id
    content = "林舟推门而入，屋内烛火未熄。"
    draft = await create_draft_only(db, nid, 3, "第三章", content)
    source_hash = hashlib.sha256(content.encode()).hexdigest()
    args = ReviseChapter(
        draft_id=draft.id,
        source_hash=source_hash,
        replacements=[
            {
                "start": content.index("烛火未熄"),
                "end": content.index("烛火未熄") + len("烛火未熄"),
                "original": "烛火未熄",
                "replacement": "烛火摇曳",
            }
        ],
    )
    context = _context()
    operation = OPERATIONS["writing.revise"]
    preview = await operation.prepare(db, nid, args, context=context)

    result = await operation.apply(db, nid, args, preview, context=context)

    assert result["label"] == "已保存新工作稿"
    states = await _working_index_states(db, nid)
    assert [state.chapter_index for state in states] == [3]
