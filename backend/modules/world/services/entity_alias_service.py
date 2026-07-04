"""EntityAliasService — 核心实体别名 CRUD。

别名统一存储在 core_entities.content_json.aliases 中，支持 dict 与历史
string 两种格式。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid

# 别名列表一次性拉取的实体上限（低并发场景，分页作用于别名列表）。
MAX_LIST_ALIAS_ENTITIES = 10000


class EntityAliasService:
    """处理 core_entities.content_json.aliases 的别名业务服务。"""

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self.repo = repo or CoreEntityRepository()

    def _normalize_alias_item(self, alias_item: str | dict) -> tuple[str, str]:
        """将别名项归一化为 (alias_text, alias_type)，并去除别名文本首尾空格。"""
        if isinstance(alias_item, str):
            return alias_item.strip(), "name"
        return alias_item.get("alias", "").strip(), alias_item.get("type", "name")

    def _candidate_alias_payload(
        self,
        *,
        alias: str,
        alias_type: str,
        workflow_id: str | None,
        scene_id: str | None,
        scene_index: int | None,
        confidence: float,
        quote: str | None,
    ) -> dict:
        return {
            "alias": alias,
            "type": alias_type or "alias",
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": workflow_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "confidence": confidence,
            "quote": quote,
            "needs_review": True,
        }

    def _alias_needs_candidate_metadata(self, alias_item: str | dict) -> bool:
        if not isinstance(alias_item, dict):
            return True
        return (
            alias_item.get("source") != "deep_import"
            or alias_item.get("status") != "candidate"
            or alias_item.get("needs_review") is not True
        )

    async def list_aliases(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """列出项目下所有实体的别名。"""
        result = await self._collect_aliases(db, novel_id)
        return result[skip : skip + limit]

    async def list_aliases_page(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """列出项目下所有实体的别名，返回标准分页结构。"""
        result = await self._collect_aliases(db, novel_id)
        return {
            "items": result[skip : skip + limit],
            "total": len(result),
        }

    async def _collect_aliases(self, db: AsyncSession, novel_id: str) -> list[dict]:
        nid = parse_uuid(novel_id, "novel_id")
        entities = await self.repo.list_by_novel(db, nid, limit=MAX_LIST_ALIAS_ENTITIES)
        result: list[dict] = []
        for entity in entities:
            aliases = (entity.content_json or {}).get("aliases", [])
            for alias_item in aliases:
                alias_text, alias_type = self._normalize_alias_item(alias_item)
                result.append(
                    {
                        "entity_id": str(entity.id),
                        "entity_name": entity.name,
                        "alias": alias_text,
                        "alias_type": alias_type,
                        "status": alias_item.get("status")
                        if isinstance(alias_item, dict)
                        else None,
                        "source": alias_item.get("source")
                        if isinstance(alias_item, dict)
                        else None,
                        "workflow_id": alias_item.get("workflow_id")
                        if isinstance(alias_item, dict)
                        else None,
                        "confidence": alias_item.get("confidence")
                        if isinstance(alias_item, dict)
                        else None,
                        "needs_review": alias_item.get("needs_review")
                        if isinstance(alias_item, dict)
                        else None,
                        "quote": alias_item.get("quote")
                        if isinstance(alias_item, dict)
                        else None,
                    }
                )
        return result

    async def create_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
        alias_type: str = "name",
    ) -> dict:
        """为实体添加别名；重复时抛 409。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self.repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError("Entity not found")

        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        normalized_alias = alias.strip()
        for alias_item in aliases:
            existing, _ = self._normalize_alias_item(alias_item)
            if existing == normalized_alias:
                raise ConflictError(f"Alias already exists: {alias}")

        aliases.append({"alias": alias, "type": alias_type})
        content["aliases"] = aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "alias_type": alias_type}

    async def append_candidate_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        alias: str,
        alias_type: str = "alias",
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        confidence: float = 0.5,
        quote: str | None = None,
    ) -> bool:
        """追加深度导入产生的待复核别名，已存在时返回 False。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self.repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError("Entity not found")

        content = dict(entity.content_json or {})
        aliases = list(content.get("aliases", []))
        normalized_alias = " ".join(str(alias or "").strip().split())
        if not normalized_alias:
            return False
        normalized_key = normalized_alias.lower()
        for index, alias_item in enumerate(aliases):
            existing, _ = self._normalize_alias_item(alias_item)
            if " ".join(existing.strip().split()).lower() == normalized_key:
                if not self._alias_needs_candidate_metadata(alias_item):
                    return False
                _, existing_type = self._normalize_alias_item(alias_item)
                enriched = self._candidate_alias_payload(
                    alias=normalized_alias,
                    alias_type=existing_type or alias_type or "alias",
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_index=scene_index,
                    confidence=confidence,
                    quote=quote,
                )
                if isinstance(alias_item, dict):
                    enriched = {**alias_item, **enriched}
                    enriched["type"] = alias_item.get("type") or enriched["type"]
                aliases[index] = enriched
                content["aliases"] = aliases
                entity.content_json = content
                await db.flush()
                return True

        aliases.append(
            self._candidate_alias_payload(
                alias=normalized_alias,
                alias_type=alias_type,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_index=scene_index,
                confidence=confidence,
                quote=quote,
            )
        )
        content["aliases"] = aliases
        entity.content_json = content
        await db.flush()
        return True

    async def delete_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
    ) -> dict:
        """删除实体的指定别名；不存在时抛 404。

        删除首个归一化后文本匹配的别名；这与原始 WorldEntityService 行为一致。
        """
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self.repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError("Entity not found")

        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        new_aliases: list = []
        found = False
        normalized_alias = alias.strip()
        for alias_item in aliases:
            existing, _ = self._normalize_alias_item(alias_item)
            if existing == normalized_alias:
                found = True
                continue
            new_aliases.append(alias_item)

        if not found:
            raise NotFoundError(f"Alias not found: {alias}")

        content["aliases"] = new_aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "deleted": True}
