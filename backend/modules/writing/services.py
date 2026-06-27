"""
Writing 业务逻辑层

调用 repository 完成业务操作。
服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.contracts import WritingDraftContract
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    DraftListItem,
    VersionHistoryResponse,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)
from shared.utils import parse_uuid


class WritingDraftService:
    """正文草稿业务服务"""

    def __init__(self) -> None:
        self._repo = WritingDraftRepository()

    async def create_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """创建新草稿（自动创建新版本）"""
        draft = await self._repo.create(db, data)
        return WritingDraftResponse.model_validate(draft)

    async def get_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> WritingDraftResponse:
        """获取草稿详情"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        return WritingDraftResponse.model_validate(draft)

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftUpdate,
        novel_id: str,
    ) -> WritingDraftResponse:
        """更新草稿"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        draft = await self._repo.update(db, did, data)
        return WritingDraftResponse.model_validate(draft)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """删除草稿"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        await self._repo.delete(db, did)

    async def get_latest_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftResponse:
        """获取章节最新草稿"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No draft found for chapter {chapter_index} in novel {novel_id}",
            )
        return WritingDraftResponse.model_validate(draft)

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> VersionHistoryResponse:
        """获取章节版本历史"""
        nid = parse_uuid(novel_id, "novel")
        versions = await self._repo.get_version_history(db, nid, chapter_index)
        items = [DraftListItem.model_validate(v) for v in versions]
        return VersionHistoryResponse(
            novel_id=novel_id,
            chapter_index=chapter_index,
            versions=items,
            total=len(items),
        )

    async def get_draft_contract(
        self,
        db: AsyncSession,
        draft_id: str,
    ) -> WritingDraftContract | None:
        """获取草稿契约（供其他模块使用，不存在返回 None）"""
        did = parse_uuid(draft_id, "draft")
        draft = await self._repo.get(db, did)
        if draft is None:
            return None
        return self._to_contract(draft)

    async def get_latest_draft_contract(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        """获取章节最新草稿契约（供其他模块使用，不存在返回 None）"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            return None
        return self._to_contract(draft)

    @staticmethod
    def _to_contract(draft: object) -> WritingDraftContract:
        """将 ORM draft 转为契约对象"""
        return WritingDraftContract(
            novel_id=str(draft.novel_id),  # type: ignore[union-attr]
            chapter_index=draft.chapter_index,  # type: ignore[union-attr]
            chapter_card_id=str(draft.chapter_card_id) if draft.chapter_card_id else None,
            title=draft.title,  # type: ignore[union-attr]
            content=draft.content,  # type: ignore[union-attr]
            version_number=draft.version_number,  # type: ignore[union-attr]
            status=draft.status,  # type: ignore[union-attr]
        )

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引"""
        nid = parse_uuid(novel_id, "novel")
        return await self._repo.list_chapter_indices(db, nid)

    # ============================================================
    # 内部工具
    # ============================================================


class WritingAnalysisService:
    async def analyze_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        content: str,
    ) -> tuple[bool, str]:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest
        from modules.memory.facade import create_memory_update_proposals
        from modules.memory.schemas import ChapterStateExtraction
        from shared.constants import DEFAULT_LLM_TIMEOUT

        settings = get_settings()

        system_prompt = (
            "你是一个小说地缘/势力资产分析助手。"
            "从章节正文中识别实质性地缘变化或角色移动。"
            "若发现主要角色更换了所处场景/城市，必须提取入 character_shifts；"
            "若发现某军队、宗门、势力占据、撤出或潜伏于某地点，"
            "必须提取入 faction_shifts。"
            "宁可不抽，绝不盲目提取路人或一次性无名地标。"
            "输出 JSON 对象，包含：\n"
            "- summary: 情节主线脉络极简总结\n"
            "- character_shifts: 角色位移数组，每项含 character_name, "
            "destination_location_name, movement_type\n"
            "- faction_shifts: 势力割据变更数组，每项含 faction_name, "
            "target_location_name, "
            "new_relation(controls/stationed_at/hidden_presence), description\n"
        )

        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content[:8000]},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm = LLMClient()
        try:
            import asyncio

            parsed = await asyncio.wait_for(
                llm.generate_structured(request, ChapterStateExtraction),
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except TimeoutError:
            return False, "timeout"
        except Exception:
            try:
                raw = await llm.generate(request)
                parsed = ChapterStateExtraction.model_validate_json(raw.content)
            except Exception:
                return False, "failed"

        if not parsed.character_shifts and not parsed.faction_shifts:
            return False, "success"

        extraction_result = {
            "summary": parsed.summary,
            "geo_mutations": {
                "character_shifts": [s.model_dump() for s in parsed.character_shifts],
                "faction_shifts": [s.model_dump() for s in parsed.faction_shifts],
            },
        }

        proposals = await create_memory_update_proposals(
            db,
            novel_id,
            source_type="chapter_text",
            source_id=f"chapter_{chapter_index}",
            extraction_result=extraction_result,
        )

        return len(proposals) > 0, "success"
