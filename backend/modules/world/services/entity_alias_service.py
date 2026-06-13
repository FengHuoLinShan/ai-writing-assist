"""EntityAliasService — 核心实体别名 CRUD。

别名统一存储在 core_entities.content_json.aliases 中，支持 dict 与历史
string 两种格式。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid


class EntityAliasService:
    """处理 core_entities.content_json.aliases 的别名业务服务。"""

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self.repo = repo or CoreEntityRepository()

    def _normalize_alias_item(self, alias_item: str | dict) -> tuple[str, str]:
        """将别名项归一化为 (alias_text, alias_type)。"""
        if isinstance(alias_item, str):
            return alias_item, "name"
        return alias_item.get("alias", ""), alias_item.get("type", "name")

    async def list_aliases(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """列出项目下所有实体的别名。"""
        nid = parse_uuid(novel_id, "novel_id")
        entities, _ = await self.repo.get_by_novel(db, nid, limit=10000)
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
                    }
                )
        return result[skip : skip + limit]

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
            raise HTTPException(status_code=404, detail="Entity not found")

        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        for alias_item in aliases:
            existing, _ = self._normalize_alias_item(alias_item)
            if existing == alias:
                raise HTTPException(
                    status_code=409, detail=f"Alias already exists: {alias}"
                )

        aliases.append({"alias": alias, "type": alias_type})
        content["aliases"] = aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "alias_type": alias_type}

    async def delete_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
    ) -> dict:
        """删除实体的指定别名；不存在时抛 404。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self.repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(status_code=404, detail="Entity not found")

        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        new_aliases: list = []
        found = False
        for alias_item in aliases:
            existing, _ = self._normalize_alias_item(alias_item)
            if existing == alias:
                found = True
                continue
            new_aliases.append(alias_item)

        if not found:
            raise HTTPException(status_code=404, detail=f"Alias not found: {alias}")

        content["aliases"] = new_aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "deleted": True}
