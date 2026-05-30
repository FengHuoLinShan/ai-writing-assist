"""
Memory 业务逻辑层

调用 repository 完成业务操作，包含记忆创建、提案管理和确认流程。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.repositories import (
    MemoryProposalRepository,
    MemoryRecordRepository,
)
from modules.memory.schemas import (
    MemoryProposalResponse,
    MemoryRecordContext,
    MemoryRecordCreate,
    MemoryRecordResponse,
    MemoryRecordUpdate,
    MemoryUpdateProposalContext,
)
from shared.utils import parse_uuid

_DEFAULT_RECENT_LIMIT = 8
_DEFAULT_ENTITY_LIMIT = 20
_DEFAULT_PROPOSAL_LIMIT = 50


class MemoryService:
    """记忆业务服务"""

    def __init__(self) -> None:
        self._record_repo = MemoryRecordRepository()
        self._proposal_repo = MemoryProposalRepository()

    # ============================================================
    # 记忆记录 CRUD
    # ============================================================

    async def create_memory_record(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MemoryRecordCreate,
    ) -> MemoryRecordResponse:
        """创建新的记忆记录"""
        nid = parse_uuid(novel_id)
        record = await self._record_repo.create(db, nid, data)
        return MemoryRecordResponse.model_validate(record)

    async def get_memory_record(
        self,
        db: AsyncSession,
        record_id: str,
        novel_id: str,
    ) -> MemoryRecordResponse:
        """获取记忆记录详情"""
        rid = parse_uuid(record_id)
        nid = parse_uuid(novel_id)
        record = await self._record_repo.get(db, rid)
        if record is None or str(record.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory record {record_id} not found",
            )
        return MemoryRecordResponse.model_validate(record)

    async def list_memory_records(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
        memory_type: str | None = None,
        status: str | None = None,
        before_chapter_index: int | None = None,
    ) -> tuple[list[MemoryRecordResponse], int]:
        """获取记忆记录列表"""
        nid = parse_uuid(novel_id)
        items, total = await self._record_repo.get_multi(
            db,
            nid,
            skip=skip,
            limit=limit,
            memory_type=memory_type,
            status=status,
            before_chapter_index=before_chapter_index,
        )
        return [MemoryRecordResponse.model_validate(r) for r in items], total

    async def update_memory_record(
        self,
        db: AsyncSession,
        record_id: str,
        data: MemoryRecordUpdate,
        novel_id: str,
    ) -> MemoryRecordResponse:
        """更新记忆记录"""
        rid = parse_uuid(record_id)
        nid = parse_uuid(novel_id)
        # 先校验所有权
        record = await self._record_repo.get(db, rid)
        if record is None or str(record.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory record {record_id} not found",
            )
        record = await self._record_repo.update(db, rid, data)
        return MemoryRecordResponse.model_validate(record)

    async def delete_memory_record(
        self,
        db: AsyncSession,
        record_id: str,
        novel_id: str,
    ) -> None:
        """删除记忆记录"""
        rid = parse_uuid(record_id)
        nid = parse_uuid(novel_id)
        record = await self._record_repo.get(db, rid)
        if record is None or str(record.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory record {record_id} not found",
            )
        await self._record_repo.delete(db, rid)

    # ============================================================
    # 提案管理
    # ============================================================

    async def list_pending_proposals(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[MemoryProposalResponse], int]:
        """获取待处理的提案列表"""
        nid = parse_uuid(novel_id)
        items, total = await self._proposal_repo.get_pending(
            db, nid, skip=skip, limit=limit
        )
        return [MemoryProposalResponse.model_validate(p) for p in items], total

    async def create_memory_update_proposals(
        self,
        db: AsyncSession,
        novel_id: str,
        source_type: str,
        source_id: str,
        extraction_result: dict[str, Any],
    ) -> list[MemoryUpdateProposalContext]:
        """从抽取结果创建记忆提案

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            source_type: 来源类型（如 chapter_text / outline_change）
            source_id: 来源 ID
            extraction_result: AI 抽取结果，格式为
                {
                    "proposals": [
                        {
                            "proposal_type": "create_memory",
                            "payload": {...},
                            "confidence": 0.8,
                            "reason": "...",
                            "chapter_index": 5,
                        },
                        ...
                    ]
                }

        Returns:
            list[MemoryUpdateProposalContext]: 创建的提案列表
        """
        nid = parse_uuid(novel_id)
        sid = parse_uuid(source_id) if source_id else None

        proposals = extraction_result.get("proposals", [])
        results: list[MemoryUpdateProposalContext] = []

        for prop in proposals:
            proposal = await self._proposal_repo.create(
                db,
                novel_id=nid,
                proposal_type=prop.get("proposal_type", "create_memory"),
                payload=prop.get("payload", {}),
                chapter_index=prop.get("chapter_index"),
                confidence=prop.get("confidence", 0.5),
                reason=prop.get("reason"),
                source_text_excerpt=prop.get("source_text_excerpt"),
            )
            results.append(MemoryUpdateProposalContext.model_validate(proposal))

        return results

    async def confirm_memory_proposal(
        self,
        db: AsyncSession,
        proposal_id: str,
        novel_id: str,
        edited_payload: dict[str, Any] | None = None,
        decided_by: str | None = None,
    ) -> MemoryRecordContext:
        """确认记忆提案，写入 canonical memory

        Args:
            db: 数据库 session
            proposal_id: 提案 ID
            novel_id: 项目 ID
            edited_payload: 编辑后的 payload（如未提供则使用原 payload）
            decided_by: 决策者标识

        Returns:
            MemoryRecordContext: 创建的正史记忆记录

        Raises:
            HTTPException: 提案不存在或已被处理
        """
        pid = parse_uuid(proposal_id)
        nid = parse_uuid(novel_id)
        proposal = await self._proposal_repo.get(db, pid)
        if proposal is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory proposal {proposal_id} not found",
            )
        if proposal is None or str(proposal.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory proposal {proposal_id} not found",
            )
        if proposal.decision != "pending":
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=f"Memory proposal {proposal_id} already decided as {proposal.decision}",
            )

        # 使用编辑后的 payload 或原始 payload 创建记忆记录
        payload = edited_payload or proposal.payload

        # 构建记忆记录创建数据
        create_data = MemoryRecordCreate(
            memory_type=payload.get("memory_type", proposal.proposal_type),
            target_type=payload.get("target_type"),
            target_id=(
                str(payload["target_id"]) if payload.get("target_id") else None
            ),
            chapter_index=payload.get("chapter_index", proposal.chapter_index),
            title=payload.get("title"),
            summary=payload.get("summary", ""),
            content_json=payload.get("content_json", {}),
            visibility=payload.get("visibility", "reader_known"),
            known_by_character_ids=payload.get("known_by_character_ids", []),
            related_entity_ids=payload.get("related_entity_ids", []),
            related_character_ids=payload.get("related_character_ids", []),
            related_thread_ids=payload.get("related_thread_ids", []),
            importance=payload.get("importance", 0.5),
            status="canonical",
            source_text_excerpt=(
                payload.get("source_text_excerpt")
                or proposal.source_text_excerpt
            ),
        )

        # 先创建正史记忆记录
        record = await self._record_repo.create(db, proposal.novel_id, create_data)

        # 再标记提案为 approved（记录创建成功后）
        await self._proposal_repo.decide(
            db, pid, decision="approved", decided_by=decided_by
        )

        geo_mutations = payload.get("geo_mutations")
        if geo_mutations:
            import logging
            _geo_logger = logging.getLogger(__name__)
            chapter_index = proposal.chapter_index

            for shift in geo_mutations.get("character_shifts", []):
                try:
                    char_name = shift.get("character_name", "")
                    loc_name = shift.get("destination_location_name", "")
                    movement_type = shift.get("movement_type", "")
                    if not char_name or not loc_name:
                        continue

                    from modules.world.facade import find_character_id_by_name
                    from modules.world.facade import find_entity_id_by_name
                    from modules.world.facade import update_character_location

                    char_id = await find_character_id_by_name(db, novel_id, char_name)
                    loc_id = await find_entity_id_by_name(db, novel_id, loc_name, entity_type="location")

                    if char_id and loc_id:
                        text_state = f"目前正{movement_type}至{loc_name}。" if movement_type else f"目前位于{loc_name}。"
                        await update_character_location(
                            db, novel_id, char_id, loc_id, text_state, chapter_index or 0,
                        )
                    else:
                        _geo_logger.warning(
                            "角色位移分发跳过: char=%s found=%s, loc=%s found=%s",
                            char_name, char_id is not None, loc_name, loc_id is not None,
                        )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("角色位移分发失败: %s", e)

            for shift in geo_mutations.get("faction_shifts", []):
                try:
                    faction_name = shift.get("faction_name", "")
                    loc_name = shift.get("target_location_name", "")
                    new_relation = shift.get("new_relation", "stationed_at")
                    description = shift.get("description", "")
                    if not faction_name or not loc_name:
                        continue

                    from modules.world.facade import find_entity_id_by_name, upsert_relationship

                    faction_id = await find_entity_id_by_name(db, novel_id, faction_name, entity_type="faction")
                    loc_id = await find_entity_id_by_name(db, novel_id, loc_name, entity_type="location")

                    if faction_id and loc_id:
                        await upsert_relationship(
                            db, novel_id, faction_id, loc_id,
                            "faction", "location", new_relation, description,
                        )
                    else:
                        _geo_logger.warning(
                            "势力割据分发跳过: faction=%s found=%s, loc=%s found=%s",
                            faction_name, faction_id is not None, loc_name, loc_id is not None,
                        )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("势力割据分发失败: %s", e)

            try:
                char_ids = []
                entity_ids = []
                for shift in geo_mutations.get("character_shifts", []):
                    from modules.world.facade import find_character_id_by_name
                    cid = await find_character_id_by_name(db, novel_id, shift.get("character_name", ""))
                    if cid:
                        char_ids.append(cid)
                for shift in geo_mutations.get("faction_shifts", []):
                    from modules.world.facade import find_entity_id_by_name
                    fid = await find_entity_id_by_name(db, novel_id, shift.get("faction_name", ""), entity_type="faction")
                    lid = await find_entity_id_by_name(db, novel_id, shift.get("target_location_name", ""), entity_type="location")
                    if fid:
                        entity_ids.append(fid)
                    if lid:
                        entity_ids.append(lid)

                if char_ids or entity_ids:
                    from modules.outline.facade import merge_chapter_involved_ids
                    await merge_chapter_involved_ids(
                        db, novel_id, chapter_index or 0, char_ids, entity_ids,
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("章节关联合并失败: %s", e)

        return MemoryRecordContext.model_validate(record)

    # ============================================================
    # 提案决策支持
    # ============================================================

    async def decide_proposal(
        self,
        db: AsyncSession,
        proposal_id: uuid.UUID,
        decision: str,
        decided_by: str | None = None,
    ) -> None:
        """对記憶提案做出決策（approved/rejected）"""
        await self._proposal_repo.decide(
            db, proposal_id, decision=decision, decided_by=decided_by,
        )

    async def get_memory_proposal(
        self,
        db: AsyncSession,
        proposal_id: str,
        novel_id: str,
    ) -> MemoryProposalResponse:
        """获取记忆提案详情"""
        pid = parse_uuid(proposal_id)
        nid = parse_uuid(novel_id)
        proposal = await self._proposal_repo.get(db, pid)
        if proposal is None or str(proposal.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Memory proposal {proposal_id} not found",
            )
        return MemoryProposalResponse.model_validate(proposal)

    # ============================================================
    # Facade 支持方法
    # ============================================================

    async def get_recent_story_memory(
        self,
        db: AsyncSession,
        novel_id: str,
        before_chapter_index: int | None = None,
        limit: int = _DEFAULT_RECENT_LIMIT,
    ) -> list[MemoryRecordContext]:
        """获取最近的故事记忆"""
        nid = parse_uuid(novel_id)
        items, _ = await self._record_repo.get_multi(
            db,
            nid,
            status="canonical",
            before_chapter_index=before_chapter_index,
            limit=limit,
        )
        return [MemoryRecordContext.model_validate(r) for r in items]

    async def get_entity_memory(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        limit: int = _DEFAULT_ENTITY_LIMIT,
    ) -> list[MemoryRecordContext]:
        """获取与某实体关联的记忆"""
        nid = parse_uuid(novel_id)
        eid = parse_uuid(entity_id)
        records = await self._record_repo.get_by_entity(
            db, nid, eid, limit=limit
        )
        return [MemoryRecordContext.model_validate(r) for r in records]

    # ============================================================
    # 内部工具
    # ============================================================

