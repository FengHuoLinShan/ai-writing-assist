"""EntityRevisionService — 实体快照版本管理"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.models import EntityRevision, TextArchive
from modules.world.repositories import CoreEntityRepository, EntityRevisionRepository
from modules.world.revision_history_schemas import (
    EntityRevisionItem,
    EntityRevisionListResponse,
    EntityRevisionSnapshotView,
)
from modules.world.services.common import parse_uuid
from modules.world.services.revision_notes import load_revision_notes

# ``create_snapshot(writing_chapter_index=UNSET)`` 的哨兵：不传时由服务自行查询
# 写作进度；显式传入 int（或 None 表示"无进度"）时直接落库，供批量调用方在
# 循环前只查一次后复用。
UNSET: object = object()

# 改动字段的稳定输出顺序（EntityRevisionField 的展示顺序）。
_REVISION_FIELD_ORDER: tuple[str, ...] = (
    "entity_type",
    "name",
    "summary",
    "public_info",
    "hidden_truth",
    "aliases",
    "content",
    "importance",
    "reveal_level",
    "status",
)


def _alias_texts(content_json: object) -> list[str]:
    """从 content_json.aliases 提取别名文本列表（忽略每条的复核元数据）。"""
    if not isinstance(content_json, dict):
        return []
    texts: list[str] = []
    for entry in content_json.get("aliases") or []:
        value = entry.get("alias") if isinstance(entry, dict) else entry
        if value is not None:
            texts.append(str(value))
    return texts


def _content_without_markers(content_json: object) -> dict:
    """去掉内部来源标记（``_meta``）与别名（单独比较）后的扩展内容。"""
    if not isinstance(content_json, dict):
        return {}
    content = dict(content_json)
    content.pop("_meta", None)
    content.pop("aliases", None)
    return content


def entity_state_dict(entity: object) -> dict:
    """实体当前状态的字段字典，与快照同构，用于改动字段比较。"""
    return {
        "entity_type": getattr(entity, "entity_type", None),
        "name": getattr(entity, "name", None),
        "summary": getattr(entity, "summary", None),
        "public_info": getattr(entity, "public_info", None),
        "hidden_truth": getattr(entity, "hidden_truth", None),
        "content_json": getattr(entity, "content_json", None),
        "importance": getattr(entity, "importance", None),
        "importance_level": getattr(entity, "importance_level", None),
        "reveal_level": getattr(entity, "reveal_level", None),
        "status": getattr(entity, "status", None),
    }


def diff_revision_snapshots(before: dict, after: dict) -> list[str]:
    """比较两份同构快照，返回按固定顺序排列的改动字段名。

    - 别名从 ``content_json.aliases`` 单独拆为 ``aliases``；
    - ``content`` 比较去掉内部来源标记（``_meta``）与别名后的剩余内容；
    - ``importance`` 覆盖数值与级别两列；
    - 没有差异时返回空列表。
    """
    changed: set[str] = set()
    for simple in (
        "entity_type",
        "name",
        "summary",
        "public_info",
        "hidden_truth",
        "status",
    ):
        if before.get(simple) != after.get(simple):
            changed.add(simple)
    if _alias_texts(before.get("content_json")) != _alias_texts(
        after.get("content_json")
    ):
        changed.add("aliases")
    if _content_without_markers(before.get("content_json")) != _content_without_markers(
        after.get("content_json")
    ):
        changed.add("content")
    if before.get("importance") != after.get("importance") or before.get(
        "importance_level"
    ) != after.get("importance_level"):
        changed.add("importance")
    if before.get("reveal_level") != after.get("reveal_level"):
        changed.add("reveal_level")
    return [field for field in _REVISION_FIELD_ORDER if field in changed]


def _snapshot_view(snapshot: dict) -> EntityRevisionSnapshotView:
    """带类型的快照视图：去掉内部来源标记，别名单独拆出。"""
    raw_content = snapshot.get("content_json")
    content = dict(raw_content) if isinstance(raw_content, dict) else {}
    aliases = _alias_texts(raw_content)
    content.pop("_meta", None)
    content.pop("aliases", None)
    return EntityRevisionSnapshotView(
        entity_type=str(snapshot.get("entity_type") or ""),
        name=str(snapshot.get("name") or ""),
        summary=snapshot.get("summary"),
        public_info=snapshot.get("public_info"),
        hidden_truth=snapshot.get("hidden_truth"),
        aliases=aliases,
        content_json=content,
        importance=snapshot.get("importance"),
        importance_level=snapshot.get("importance_level"),
        reveal_level=snapshot.get("reveal_level"),
        status=str(snapshot.get("status") or ""),
    )


def _ensure_utc(value: datetime | None) -> datetime | None:
    """SQLite 读出的无时区值统一补 UTC；已有 timezone 的统一转 UTC。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EntityRevisionService:
    """实体快照版本业务服务"""

    def __init__(self) -> None:
        self._repo = EntityRevisionRepository()
        self._entity_repo = CoreEntityRepository()

    @staticmethod
    async def _request_activity_refresh(db: AsyncSession, novel_id: str) -> None:
        from modules.world.services.core.entity_activity_invalidation import (
            request_entity_activity_reannotation,
        )

        await request_entity_activity_reannotation(db, novel_id)

    async def create_snapshot(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        revision_reason: str = "ai_import",
        source_chapter_id: str | None = None,
        writing_chapter_index: int | None | object = UNSET,
    ) -> dict:
        """对实体当前状态打快照。

        ``writing_chapter_index`` 缺省（UNSET）时自行查询当前写作进度并落库；
        批量调用方可在循环前查一次后显式传入。返回 dict 含 ``revision_id``
        与 ``snapshot``（保存前状态，供调用方计算改动字段）。
        """
        eid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError(f"CoreEntity {entity_id} not found")

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

        if writing_chapter_index is UNSET:
            from modules.world.services.common import current_writing_chapter_index

            writing_chapter_index = await current_writing_chapter_index(db, novel_id)

        chapter_id = parse_uuid(source_chapter_id) if source_chapter_id else None
        revision = EntityRevision(
            entity_id=eid,
            novel_id=nid,
            snapshot=snapshot,
            source_chapter_id=chapter_id,
            revision_reason=revision_reason,
            writing_chapter_index=(
                int(writing_chapter_index)  # type: ignore[arg-type]
                if writing_chapter_index is not None
                else None
            ),
        )
        db.add(revision)
        await db.flush()

        return {
            "revision_id": str(revision.id),
            "entity_id": str(revision.entity_id),
            "revision_reason": revision.revision_reason,
            "created_at": str(revision.created_at),
            "snapshot": snapshot,
        }

    async def record_change_summary(
        self,
        db: AsyncSession,
        revision_id: str,
        fields: list[str],
        restored_from_revision_id: str | None = None,
    ) -> None:
        """把本次改动字段写回修订行的 ``change_summary``（该表无触发器，可 UPDATE）。"""
        rid = parse_uuid(revision_id, "revision_id")
        summary = {
            "fields": list(fields),
            "restored_from_revision_id": restored_from_revision_id,
        }
        await db.execute(
            update(EntityRevision)
            .where(EntityRevision.id == rid)
            .values(change_summary=summary)
        )
        await db.flush()

    async def get_revisions(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> EntityRevisionListResponse:
        """获取实体的改动历史（强类型输出）。

        - ``created_at`` 统一带时区（SQLite 无时区值补 UTC）；
        - 批量读取备注填 ``change_note``；
        - ``changed_fields`` 优先读 ``change_summary``；缺保存记录时读取相邻
          一条修订推算（本页相邻行；页首额外读一条更新的修订），并标
          ``changed_fields_exact=False``；
        - ``restored_from_revision_id`` 只从 ``change_summary`` 读；
        - ``can_restore`` 按实体当前状态（deprecated 实体不给恢复）。
        """
        eid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        # 验证实体存在
        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError(f"CoreEntity {entity_id} not found")

        revisions, total = await self._repo.get_revisions(
            db,
            eid,
            skip=skip,
            limit=limit,
        )

        # 修订按 (created_at, id) 倒序；每条修订记录的是"改动前"快照，其改动
        # 结果等于相邻更新一条修订的快照。翻页首条的前一条不在本页时额外读一条。
        newer_snapshot: dict | None = None
        if skip > 0 and revisions:
            newer_rows, _ = await self._repo.get_revisions(
                db,
                eid,
                skip=skip - 1,
                limit=1,
            )
            if newer_rows:
                newer_snapshot = dict(newer_rows[0].snapshot or {})

        notes = await load_revision_notes(
            db,
            novel_id,
            "entity",
            [str(r.id) for r in revisions],
        )
        current_state = entity_state_dict(entity)
        can_restore = entity.status != "deprecated"

        items: list[EntityRevisionItem] = []
        for index, revision in enumerate(revisions):
            before_snapshot = dict(revision.snapshot or {})
            if index > 0:
                after_state = dict(revisions[index - 1].snapshot or {})
            elif newer_snapshot is not None:
                after_state = newer_snapshot
            else:
                after_state = current_state

            summary = (
                revision.change_summary
                if isinstance(revision.change_summary, dict)
                else None
            )
            if summary is not None and summary.get("fields") is not None:
                changed_fields = list(summary.get("fields") or [])
                changed_fields_exact = True
            else:
                changed_fields = diff_revision_snapshots(before_snapshot, after_state)
                changed_fields_exact = False
            restored = summary.get("restored_from_revision_id") if summary else None

            items.append(
                EntityRevisionItem(
                    revision_id=str(revision.id),
                    entity_id=str(revision.entity_id),
                    revision_reason=revision.revision_reason,
                    created_at=_ensure_utc(revision.created_at),  # type: ignore[arg-type]
                    writing_chapter_index=revision.writing_chapter_index,
                    change_note=notes.get(revision.id),
                    changed_fields=changed_fields,
                    changed_fields_exact=changed_fields_exact,
                    restored_from_revision_id=(str(restored) if restored else None),
                    snapshot=_snapshot_view(before_snapshot),
                    can_restore=can_restore,
                )
            )

        return EntityRevisionListResponse(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
            current_updated_at=_ensure_utc(entity.updated_at),  # type: ignore[arg-type]
        )

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

        entity = await self._entity_repo.get_for_update(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError(f"CoreEntity {entity_id} not found")

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
                await self._entity_repo.update(db, entity, update_data)
        else:
            revisions, _ = await self._repo.get_revisions(
                db,
                eid,
                skip=0,
                limit=1,
            )
            if not revisions:
                warnings.append("no rollback data available")
                return {
                    "entity_id": str(eid),
                    "target_scene_index": target_scene_index,
                    "restored_fields": restored_fields,
                    "warnings": warnings,
                }
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
            target_type = update_data.entity_type
            if target_type is not None and target_type != entity.entity_type:
                from modules.world.services.core.entity_type_transition_service import (
                    EntityTypeTransitionService,
                )

                await EntityTypeTransitionService().transition(
                    db,
                    entity=entity,
                    new_type=target_type,
                    changed_by="rollback",
                )
                await self._invalidate_type_change(db, novel_id, entity_id)
            await self._entity_repo.update(db, entity, update_data)
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
        await self._request_activity_refresh(db, novel_id)

        return {
            "entity_id": str(eid),
            "target_scene_index": target_scene_index,
            "restored_fields": restored_fields,
            "warnings": warnings,
        }

    @staticmethod
    async def _invalidate_type_change(
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> None:
        from modules.evidence.facade import mark_asset_context_changed
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_asset_context_changed(
            db,
            novel_id=novel_id,
            asset_type="world_entity",
            asset_id=entity_id,
            reason="entity_type_changed",
        )
        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="core_entity",
            source_id=entity_id,
        )

    async def seed_text_archive(
        self,
        db: AsyncSession,
        entity_id: str,
        novel_id: str,
        field_name: str,
        text_content: str,
        scene_index: int = 0,
    ) -> TextArchive:
        """E2E 测试专用：在验证实体所有权后插入一条 TextArchive 记录。"""
        eid = parse_uuid(entity_id, "entity_id")
        nid = parse_uuid(novel_id, "novel_id")

        entity = await self._entity_repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError("Entity not found")

        archive = TextArchive(
            novel_id=nid,
            entity_id=eid,
            field_name=field_name,
            text_content=text_content,
            scene_index=scene_index,
            source="test_seed",
        )
        db.add(archive)
        await db.flush()
        return archive
