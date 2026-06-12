"""EntityRevisionService — 实体快照版本管理"""

from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import TextArchive
from modules.world.repositories import CoreEntityRepository, EntityRevisionRepository
from modules.world.services.helpers import parse_uuid


class EntityRevisionService:
    """实体快照版本业务服务"""

    def __init__(self) -> None:
        self._repo = EntityRevisionRepository()
        self._entity_repo = CoreEntityRepository()

    async def create_snapshot(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        revision_reason: str = "ai_import",
        source_chapter_id: str | None = None,
    ) -> dict:
        """对实体当前状态打快照"""
        eid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self._entity_repo.get(db, eid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )

        snapshot = {
            "entity_type": entity.entity_type,
            "name": entity.name,
            "summary": entity.summary,
            "public_info": entity.public_info,
            "hidden_truth": entity.hidden_truth,
            "content_json": entity.content_json,
            "importance": entity.importance,
            "importance_level": entity.importance_level,
            "reveal_level": entity.reveal_level,
            "status": entity.status,
        }

        chapter_id = parse_uuid(source_chapter_id) if source_chapter_id else None
        revision = await self._repo.create(
            db,
            entity_id=eid,
            novel_id=nid,
            snapshot=snapshot,
            source_chapter_id=chapter_id,
            revision_reason=revision_reason,
        )

        return {
            "revision_id": str(revision.id),
            "entity_id": str(revision.entity_id),
            "revision_reason": revision.revision_reason,
            "created_at": str(revision.created_at),
        }

    async def get_revisions(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        """获取实体的版本列表"""
        eid = parse_uuid(entity_id, "entity_id")

        # 验证实体存在
        entity = await self._entity_repo.get(db, eid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )

        revisions, total = await self._repo.get_revisions(
            db,
            eid,
            skip=skip,
            limit=limit,
        )

        items = [
            {
                "revision_id": str(r.id),
                "entity_id": str(r.entity_id),
                "revision_reason": r.revision_reason,
                "created_at": str(r.created_at),
            }
            for r in revisions
        ]

        return {"items": items, "total": total}

    async def rollback_to_revision(
        self,
        db: AsyncSession,
        entity_id: str,
        revision_id: str,
        novel_id: str,
    ) -> dict:
        """回滚实体到指定版本（回滚前自动打快照）"""
        eid = parse_uuid(entity_id, "entity_id")
        rid = parse_uuid(revision_id, "revision_id")
        _ = parse_uuid(novel_id, "novel_id")

        # 先对当前状态打快照
        await self.create_snapshot(db, entity_id, novel_id, revision_reason="rollback")

        # 获取目标版本
        revision = await self._repo.get_revision(db, rid)
        if revision is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Revision {revision_id} not found",
            )

        snapshot = revision.snapshot
        from modules.world.schemas import CoreEntityUpdate

        update_data = CoreEntityUpdate(
            entity_type=snapshot.get("entity_type"),
            name=snapshot.get("name"),
            summary=snapshot.get("summary"),
            public_info=snapshot.get("public_info"),
            hidden_truth=snapshot.get("hidden_truth"),
            content_json=snapshot.get("content_json"),
            importance=snapshot.get("importance"),
            importance_level=snapshot.get("importance_level"),
            reveal_level=snapshot.get("reveal_level"),
            status=snapshot.get("status"),
        )

        entity = await self._entity_repo.update(db, eid, update_data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found after rollback",
            )

        from modules.world.schemas import CoreEntityResponse

        return CoreEntityResponse.model_validate(entity).model_dump()

    async def rollback_to_scene_index(
        self,
        db: AsyncSession,
        entity_id: str,
        target_scene_index: int,
        novel_id: str,
    ) -> dict:
        """回滚实体到指定 Scene 索引（优先使用 TextArchive，否则回退到 EntityRevision）"""
        eid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"CoreEntity {entity_id} not found",
            )

        stmt = (
            select(TextArchive)
            .where(
                TextArchive.entity_id == eid,
                TextArchive.scene_index <= target_scene_index,
            )
            .order_by(TextArchive.scene_index.desc())
        )
        result = await db.execute(stmt)
        archives = list(result.scalars().all())

        restored_fields: list[str] = []
        warnings: list[str] = []

        from modules.world.schemas import CoreEntityUpdate

        if archives:
            # 按 field_name 分组，取每个字段最近的归档值
            latest_by_field: dict[str, str | None] = {}
            for archive in archives:
                if archive.field_name not in latest_by_field:
                    latest_by_field[archive.field_name] = archive.text_content

            field_to_attr = {
                "summary": "summary",
                "public_info": "public_info",
                "hidden_truth": "hidden_truth",
                "content_json": "content_json",
            }

            update_values: dict[str, object] = {}
            for field_name, attr_name in field_to_attr.items():
                if field_name not in latest_by_field:
                    continue
                value = latest_by_field[field_name]
                if field_name == "content_json":
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            warnings.append("无法解析 content_json 归档值")
                            continue
                    if value is None:
                        continue
                update_values[attr_name] = value
                restored_fields.append(field_name)

            if update_values:
                update_data = CoreEntityUpdate(**update_values)
                await self._entity_repo.update(db, eid, update_data)
        else:
            revisions, _ = await self._repo.get_revisions(
                db,
                eid,
                skip=0,
                limit=1,
            )
            if not revisions:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"No revision or archive found for entity {entity_id}",
                )
            revision = revisions[0]
            snapshot = revision.snapshot
            update_data = CoreEntityUpdate(
                entity_type=snapshot.get("entity_type"),
                name=snapshot.get("name"),
                summary=snapshot.get("summary"),
                public_info=snapshot.get("public_info"),
                hidden_truth=snapshot.get("hidden_truth"),
                content_json=snapshot.get("content_json"),
                importance=snapshot.get("importance"),
                importance_level=snapshot.get("importance_level"),
                reveal_level=snapshot.get("reveal_level"),
                status=snapshot.get("status"),
            )
            await self._entity_repo.update(db, eid, update_data)
            restored_fields = [
                "summary",
                "public_info",
                "hidden_truth",
                "content_json",
                "entity_type",
                "name",
                "importance",
                "importance_level",
                "reveal_level",
                "status",
            ]
            warnings.append(
                "未找到 TextArchive 记录，已回退到最近 EntityRevision",
            )

        rollback_archive = TextArchive(
            novel_id=nid,
            entity_id=eid,
            field_name="rollback",
            text_content=f"rollback to scene_index {target_scene_index}",
            scene_index=target_scene_index,
            source="manual_rollback",
            meta={"restored_fields": restored_fields},
        )
        db.add(rollback_archive)
        await db.flush()

        return {
            "entity_id": str(eid),
            "target_scene_index": target_scene_index,
            "restored_fields": restored_fields,
            "warnings": warnings,
        }
