"""Writing 批注运行 → World/Story 设定提案的提交编排。

供 assistant facade 委托；会话创建、prompt 组装与提交都在本模块完成，
facade 只保留稳定签名。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.assistant.operations import catalog
from modules.assistant.schemas import SessionCreate, TurnCreate, WorkContext
from modules.assistant.service import AssistantService
from modules.project.facade import get_any_project_context

_COMMENT_PROPOSAL_PROMPT_HEAD = (
    "核对这些正文批注是否需要世界书或故事结构的配套修改。"
    "仅提出有来源支持的具体待确认方案；没有必要修改时说明无提案。"
    "不得直接采用或写入任何资产。批注：\n"
)


def project_assistant_enabled() -> bool:
    from modules.assistant.service import get_settings

    return get_settings().assistant_enabled


async def submit_comment_proposals(
    db: AsyncSession,
    *,
    novel_id: str,
    draft_id: str,
    chapter_index: int,
    source_hash: str,
    comments: list[str],
    operation_id: str,
) -> dict:
    """Prepare World/Story proposals for a Writing comment run."""
    if not project_assistant_enabled():
        raise ConflictError("项目助手未启用，相关设定提案尚未运行")
    project = await get_any_project_context(db, novel_id)
    if project is None:
        raise NotFoundError("项目不存在")
    service = AssistantService()
    session = await service.create_session(
        db,
        SessionCreate(novel_id=uuid.UUID(novel_id), title="本章批注相关设定提案"),
    )
    names = {name for name in catalog() if name.startswith(("world.", "story."))}
    request = TurnCreate(
        novel_id=uuid.UUID(novel_id),
        operation_id=uuid.UUID(operation_id),
        context=WorkContext(
            page="writing",
            chapter_index=chapter_index,
            draft_id=uuid.UUID(draft_id),
            source_hash=source_hash,
            scope="current",
            task_hint="design",
        ),
        allow_web=False,
        message=(
            _COMMENT_PROPOSAL_PROMPT_HEAD
            + "\n".join(f"- {value[:500]}" for value in comments)[:15000]
        ),
    )
    run = await service.submit(
        db, str(session.id), request, str(project.owner_id), operation_names=names
    )
    return {"run_id": run["id"], "session_id": str(session.id)}
