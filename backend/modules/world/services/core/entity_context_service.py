"""EntityContextService — 核心实体上下文查询服务。

提供上下文包、摘要列表、检索词典、名称查询与自动入库批次分组。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import WorldContextBundle, WorldEntityContext
from modules.world.services.common import parse_uuid


class EntityContextService:
    """处理核心实体上下文查询的业务服务。"""

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self._repo = repo or CoreEntityRepository()

    @staticmethod
    def _active_alias_term(alias_item: object) -> str:
        if isinstance(alias_item, str):
            return alias_item
        if not isinstance(alias_item, dict):
            return ""
        status = str(alias_item.get("status") or "").strip().lower()
        if status in {"ignored", "rejected", "deprecated", "rolled_back"}:
            return ""
        if alias_item.get("rolled_back") is True:
            return ""
        return str(alias_item.get("alias") or "")

    @staticmethod
    def _is_pending_suggestion_shadow(entity: CoreEntity) -> bool:
        meta = dict((entity.content_json or {}).get("_meta") or {})
        return bool(
            entity.status in {"draft", "candidate"}
            and meta.get("compatibility_shadow") is True
            and meta.get("suggestion_id")
        )

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
        current_chapter: int | None = None,
        include_review: bool = False,
    ) -> WorldContextBundle:
        """获取世界上下文包，默认只包含已采用对象。

        ``include_review=True`` 用于需要 working context 的受控流程，
        会额外包含 draft / candidate / conflicted；归档状态始终排除。
        """
        nid = parse_uuid(novel_id, "novel_id")
        statuses = (
            ("canonical", "draft", "candidate", "conflicted")
            if include_review
            else ("canonical",)
        )

        if entity_ids:
            eids = [parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self._repo.get_by_ids(db, nid, eids, statuses=statuses)
        else:
            entities = await self._repo.get_by_type_and_status(
                db,
                nid,
                statuses=statuses,
                limit=limit,
            )

        # Filter expired temporary entities
        if current_chapter is not None:
            from modules.project.facade import get_project_context

            project_ctx = await get_project_context(db, novel_id)
            expiry = 30
            if project_ctx is not None and project_ctx.settings:
                expiry = project_ctx.settings.get("temporary_entity_expiry_chapters", 30)

            filtered: list[CoreEntity] = []
            for entity in entities:
                content = entity.content_json or {}
                meta = content.get("_meta", {})
                if (
                    meta.get("temporary") is True
                    and meta.get("source_chapter_index") is not None
                ):
                    src_ch = int(meta["source_chapter_index"])
                    if current_chapter - src_ch > expiry:
                        continue
                filtered.append(entity)
            entities = filtered

        contexts = [_entity_to_context(entity, reveal_mode) for entity in entities]

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    async def list_entity_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        statuses: list[str] | tuple[str, ...] | None = None,
        display_state: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """获取实体 ID / 名称 / 类型摘要列表。"""
        nid = parse_uuid(novel_id, "novel_id")
        query_kwargs = {"entity_type": entity_type, "limit": limit}
        if statuses is not None:
            query_kwargs["statuses"] = statuses
        elif display_state is not None:
            from modules.world.asset_state import statuses_for_display_state

            display_statuses = statuses_for_display_state(display_state)
            if display_statuses is None:
                raise ValueError("display_state must be active, review, or archived")
            query_kwargs["statuses"] = tuple(display_statuses)
        result = await self._repo.get_by_type_and_status(db, nid, **query_kwargs)
        return [
            {"id": item.id, "name": item.name, "entity_type": item.entity_type}
            for item in result
        ]

    async def list_entity_terms(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 500,
        include_review: bool = False,
    ) -> list[dict]:
        """获取已采用实体的检索词典项 (name + content_json.aliases)。

        别名存储约定见 core_entities.content_json.aliases (per world/CLAUDE.md)。
        """
        nid = parse_uuid(novel_id, "novel_id")
        entities = await self._repo.list_by_novel(db, nid, limit=limit)
        terms: list[dict] = []
        for item in entities:
            if item.status != "canonical" and not (
                include_review and item.status in {"draft", "candidate", "conflicted"}
            ):
                continue
            item_terms = [item.name]
            aliases = (item.content_json or {}).get("aliases", [])
            item_terms.extend(self._active_alias_term(alias) for alias in aliases)
            terms.append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "entity_type": item.entity_type,
                    "status": item.status,
                    "terms": [t for t in item_terms if t],
                }
            )
        return terms

    async def get_entity_importance_map(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, dict[str, object]]:
        """Return canonical entity importance for derived RAG chunks."""
        nid = parse_uuid(novel_id, "novel_id")
        rows = await self._repo.list_ranking_candidates(
            db,
            nid,
            status="canonical",
        )
        return {
            str(row["id"]): {
                "importance": float(row["importance"]),
                "importance_level": str(row["importance_level"]),
            }
            for row in rows
        }

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称查正史实体 ID，返 str 或 None。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.find_entity_by_name(
            db,
            nid,
            name,
            entity_type=entity_type,
        )

    async def find_working_entity_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称或别名解析 working context 内的实体。

        深度导入 Phase 2b 需要在同一 workflow 刚创建的 candidate 对象之间
        生成关系，因此这里显式包含 canonical / draft / candidate。
        """
        nid = parse_uuid(novel_id, "novel_id")
        query = " ".join(str(name or "").strip().split()).lower()
        if not query:
            return None

        entities = await self._repo.list_by_novel(
            db,
            nid,
            entity_type=entity_type,
            limit=10000,
        )
        for item in entities:
            if item.status not in ("canonical", "draft", "candidate"):
                continue
            if self._is_pending_suggestion_shadow(item):
                continue
            if " ".join((item.name or "").strip().split()).lower() == query:
                return str(item.id)
            aliases = (item.content_json or {}).get("aliases", [])
            for alias_item in aliases:
                alias_text = (
                    alias_item
                    if isinstance(alias_item, str)
                    else alias_item.get("alias", "")
                )
                if " ".join(str(alias_text).strip().split()).lower() == query:
                    return str(item.id)
        return None

    async def find_working_entities_by_names(
        self,
        db: AsyncSession,
        novel_id: str,
        names: list[str] | tuple[str, ...] | set[str],
        entity_type: str | None = None,
    ) -> dict[str, str]:
        """批量按名称或别名解析 working context 内的实体 ID。"""
        nid = parse_uuid(novel_id, "novel_id")
        normalized_to_originals: dict[str, list[str]] = {}
        for name in names:
            normalized = " ".join(str(name or "").strip().split()).lower()
            if normalized:
                original = str(name)
                originals = normalized_to_originals.setdefault(normalized, [])
                if original not in originals:
                    originals.append(original)
        if not normalized_to_originals:
            return {}

        entities = await self._repo.list_by_novel(
            db,
            nid,
            entity_type=entity_type,
            limit=10000,
        )
        resolved: dict[str, str] = {}
        for item in entities:
            if item.status not in ("canonical", "draft", "candidate"):
                continue
            if self._is_pending_suggestion_shadow(item):
                continue
            item_id = str(item.id)
            item_name = " ".join((item.name or "").strip().split()).lower()
            for original in normalized_to_originals.get(item_name, []):
                resolved.setdefault(original, item_id)
            aliases = (item.content_json or {}).get("aliases", [])
            for alias_item in aliases:
                alias_text = (
                    alias_item
                    if isinstance(alias_item, str)
                    else alias_item.get("alias", "")
                )
                normalized_alias = " ".join(str(alias_text).strip().split()).lower()
                for original in normalized_to_originals.get(normalized_alias, []):
                    resolved.setdefault(original, item_id)
        return resolved

    async def list_entity_batches(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        """获取自动入库实体的批次分组列表。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.get_entity_batches(db, nid, limit=limit)


def _entity_to_context(
    entity: CoreEntity,
    reveal_mode: str,
) -> WorldEntityContext:
    hidden = None
    if reveal_mode in {"author_only", "author_full"}:
        hidden = entity.hidden_truth

    return WorldEntityContext(
        entity_id=str(entity.id),
        entity_type=entity.entity_type,
        name=entity.name,
        summary=entity.summary,
        public_info=entity.public_info,
        hidden_truth=hidden,
        importance=entity.importance,
        importance_level=entity.importance_level,
        reveal_level=entity.reveal_level,
        status=entity.status,
    )
