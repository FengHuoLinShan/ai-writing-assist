"""EntityAliasService — 核心实体别名 CRUD。

别名统一存储在 core_entities.content_json.aliases 中，支持 dict 与历史
string 两种格式。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import CoreEntityUpdate
from modules.world.services.common import parse_uuid
from modules.world.services.core.dedup_service import EntityDedupService

# 别名列表一次性拉取的实体上限（低并发场景，分页作用于别名列表）。
MAX_LIST_ALIAS_ENTITIES = 10000
ALIAS_TARGET_STATUSES = {"draft", "canonical", "candidate"}


class EntityAliasService:
    """处理 core_entities.content_json.aliases 的别名业务服务。"""

    def __init__(
        self,
        repo: CoreEntityRepository | None = None,
        context_marker=None,
    ) -> None:
        self.repo = repo or CoreEntityRepository()
        self._context_marker = context_marker

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

    def _alias_response(self, entity, alias_item: dict) -> dict:
        return {
            "entity_id": str(entity.id),
            "entity_name": entity.name,
            "alias": alias_item.get("alias", ""),
            "alias_type": alias_item.get("type", "name"),
            "status": alias_item.get("status"),
            "source": alias_item.get("source"),
            "workflow_id": alias_item.get("workflow_id"),
            "scene_id": alias_item.get("scene_id"),
            "scene_index": alias_item.get("scene_index"),
            "confidence": alias_item.get("confidence"),
            "needs_review": alias_item.get("needs_review"),
            "reviewed_at": alias_item.get("reviewed_at"),
            "reviewed_by": alias_item.get("reviewed_by"),
            "reviewed_from": alias_item.get("reviewed_from"),
            "quote": alias_item.get("quote"),
        }

    def _assert_valid_target(self, entity) -> None:
        if entity.status not in ALIAS_TARGET_STATUSES:
            raise DomainValidationError(
                "Alias target must be draft, canonical, or candidate, "
                f"got {entity.status}",
                status_code=422,
            )

    def _find_alias_index(self, aliases: list, alias: str) -> int:
        normalized_alias = alias.strip()
        for index, alias_item in enumerate(aliases):
            existing, _ = self._normalize_alias_item(alias_item)
            if existing == normalized_alias:
                return index
        return -1

    def _has_duplicate_alias(
        self,
        aliases: list,
        alias: str,
        *,
        ignore_index: int | None = None,
    ) -> bool:
        normalized_alias = " ".join(str(alias or "").strip().split()).lower()
        for index, alias_item in enumerate(aliases):
            if ignore_index is not None and index == ignore_index:
                continue
            existing, _ = self._normalize_alias_item(alias_item)
            if " ".join(existing.strip().split()).lower() == normalized_alias:
                return True
        return False

    async def _mark_context_changed(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_id: str,
        reason: str,
    ) -> None:
        try:
            marker = self._context_marker
            if marker is None:
                from modules.context.facade import mark_asset_context_changed

                marker = mark_asset_context_changed

            await marker(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason=reason,
            )
        except Exception:
            # Context confirmation invalidation is best-effort, matching entity service.
            pass

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
        q: str | None = None,
        status: str | None = None,
        needs_review: bool | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> dict:
        """列出项目下所有实体的别名，返回标准分页结构。"""
        result = await self._collect_aliases(db, novel_id)
        result = self._filter_aliases(
            result,
            q=q,
            status=status,
            needs_review=needs_review,
            source=source,
            workflow_id=workflow_id,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
        )
        return {
            "items": result[skip : skip + limit],
            "total": len(result),
        }

    def _filter_aliases(
        self,
        aliases: list[dict],
        *,
        q: str | None = None,
        status: str | None = None,
        needs_review: bool | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
    ) -> list[dict]:
        query = (q or "").strip().lower()

        def _matches(item: dict) -> bool:
            if query:
                haystack = " ".join(
                    str(item.get(key) or "")
                    for key in ("entity_name", "alias", "alias_type", "quote")
                ).lower()
                if query not in haystack:
                    return False
            if status and item.get("status") != status:
                return False
            if needs_review is not None and item.get("needs_review") is not needs_review:
                return False
            if source and item.get("source") != source:
                return False
            if workflow_id and item.get("workflow_id") != workflow_id:
                return False
            if scene_id and item.get("scene_id") != scene_id:
                return False
            if scene_index is not None and item.get("scene_index") != scene_index:
                return False
            if (
                source_chapter_index is not None
                and item.get("source_chapter_index") != source_chapter_index
            ):
                return False
            confidence = item.get("confidence")
            if confidence_min is not None and (
                confidence is None or float(confidence) < confidence_min
            ):
                return False
            if confidence_max is not None and (
                confidence is None or float(confidence) > confidence_max
            ):
                return False
            return True

        return [item for item in aliases if _matches(item)]

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
                        "scene_id": alias_item.get("scene_id")
                        if isinstance(alias_item, dict)
                        else None,
                        "scene_index": alias_item.get("scene_index")
                        if isinstance(alias_item, dict)
                        else None,
                        "source_chapter_index": alias_item.get(
                            "source_chapter_index"
                        )
                        if isinstance(alias_item, dict)
                        else None,
                        "confidence": alias_item.get("confidence")
                        if isinstance(alias_item, dict)
                        else None,
                        "needs_review": alias_item.get("needs_review")
                        if isinstance(alias_item, dict)
                        else None,
                        "reviewed_at": alias_item.get("reviewed_at")
                        if isinstance(alias_item, dict)
                        else None,
                        "reviewed_by": alias_item.get("reviewed_by")
                        if isinstance(alias_item, dict)
                        else None,
                        "reviewed_from": alias_item.get("reviewed_from")
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

        content = dict(entity.content_json or {})
        aliases = list(content.get("aliases", []))
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

    async def update_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
        changes: dict,
    ) -> dict:
        """更新实体别名条目的元数据；None 值表示移除对应字段。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self.repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise NotFoundError("Entity not found")

        content = dict(entity.content_json or {})
        aliases = list(content.get("aliases", []))
        normalized_alias = alias.strip()
        for index, alias_item in enumerate(aliases):
            existing, alias_type = self._normalize_alias_item(alias_item)
            if existing != normalized_alias:
                continue

            updated = dict(alias_item) if isinstance(alias_item, dict) else {
                "alias": existing,
                "type": alias_type,
            }
            updated["alias"] = existing
            updated["type"] = updated.get("type") or alias_type or "name"
            for key, value in changes.items():
                if value is None:
                    updated.pop(key, None)
                else:
                    updated[key] = value

            aliases[index] = updated
            content["aliases"] = aliases
            entity.content_json = content
            await db.flush()
            return {
                "entity_id": str(entity.id),
                "entity_name": entity.name,
                "alias": existing,
                "alias_type": updated.get("type", "name"),
                "status": updated.get("status"),
                "source": updated.get("source"),
                "workflow_id": updated.get("workflow_id"),
                "confidence": updated.get("confidence"),
                "needs_review": updated.get("needs_review"),
                "reviewed_at": updated.get("reviewed_at"),
                "reviewed_by": updated.get("reviewed_by"),
                "reviewed_from": updated.get("reviewed_from"),
                "quote": updated.get("quote"),
            }

        raise NotFoundError(f"Alias not found: {alias}")

    async def edit_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        old_alias: str,
        *,
        target_entity_id: str | None = None,
        alias: str | None = None,
        alias_type: str | None = None,
        confirm_review: bool = True,
    ) -> dict:
        """Edit alias text/type and optionally move it to another target entity."""
        nid = parse_uuid(novel_id, "novel_id")
        source_eid = parse_uuid(entity_id, "entity_id")
        source = await self.repo.get(db, source_eid)
        if source is None or source.novel_id != nid:
            raise NotFoundError("Entity not found")

        target = source
        if target_entity_id:
            target_eid = parse_uuid(target_entity_id, "target_entity_id")
            target = await self.repo.get(db, target_eid)
            if target is None or target.novel_id != nid:
                raise NotFoundError("Target entity not found")
        self._assert_valid_target(target)

        source_content = dict(source.content_json or {})
        source_aliases = list(source_content.get("aliases", []))
        source_index = self._find_alias_index(source_aliases, old_alias)
        if source_index < 0:
            raise NotFoundError(f"Alias not found: {old_alias}")

        old_item = source_aliases[source_index]
        existing_alias, existing_type = self._normalize_alias_item(old_item)
        next_alias = " ".join(
            str(alias if alias is not None else existing_alias).strip().split()
        )
        if not next_alias:
            raise DomainValidationError("Alias text cannot be empty")
        next_type = alias_type or existing_type or "name"

        updated = dict(old_item) if isinstance(old_item, dict) else {
            "alias": existing_alias,
            "type": existing_type,
        }
        updated["alias"] = next_alias
        updated["type"] = next_type
        if confirm_review:
            updated["status"] = "canonical"
            updated["needs_review"] = False
            updated["reviewed_at"] = datetime.now(UTC).isoformat()
            updated["reviewed_by"] = "manual"
            updated["reviewed_from"] = "world_aliases_edit"

        affected_ids = {str(source.id)}
        if str(target.id) == str(source.id):
            if self._has_duplicate_alias(
                source_aliases,
                next_alias,
                ignore_index=source_index,
            ):
                raise ConflictError(f"Alias already exists: {next_alias}")
            source_aliases[source_index] = updated
            source_content["aliases"] = source_aliases
            source.content_json = source_content
        else:
            target_content = dict(target.content_json or {})
            target_aliases = list(target_content.get("aliases", []))
            if self._has_duplicate_alias(target_aliases, next_alias):
                raise ConflictError(f"Alias already exists: {next_alias}")
            del source_aliases[source_index]
            source_content["aliases"] = source_aliases
            source.content_json = source_content
            target_aliases.append(updated)
            target_content["aliases"] = target_aliases
            target.content_json = target_content
            affected_ids.add(str(target.id))

        await db.flush()
        for changed_id in affected_ids:
            await self._mark_context_changed(
                db,
                novel_id=novel_id,
                entity_id=changed_id,
                reason="alias_updated",
            )
        return {
            **self._alias_response(target, updated),
            "affected_ids": sorted(affected_ids),
        }

    async def resolve_candidate_as_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        *,
        target_entity_id: str,
        alias: str,
        alias_type: str = "alias",
    ) -> dict:
        """Resolve a candidate entity as an alias of another entity."""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(candidate_id, "candidate_id")
        tid = parse_uuid(target_entity_id, "target_entity_id")
        candidate = await self.repo.get(db, cid)
        target = await self.repo.get(db, tid)
        if candidate is None or candidate.novel_id != nid:
            raise NotFoundError("Candidate entity not found")
        if target is None or target.novel_id != nid:
            raise NotFoundError("Target entity not found")
        if candidate.id == target.id:
            raise DomainValidationError("Cannot resolve an entity as its own alias")
        if candidate.status not in {"draft", "candidate"}:
            raise DomainValidationError(
                f"Alias candidate must be draft or candidate, got {candidate.status}",
                status_code=422,
            )
        self._assert_valid_target(target)

        normalized_alias = " ".join(str(alias or "").strip().split())
        if not normalized_alias:
            raise DomainValidationError("Alias text cannot be empty")

        target_content = dict(target.content_json or {})
        target_aliases = list(target_content.get("aliases", []))
        if self._has_duplicate_alias(target_aliases, normalized_alias):
            raise ConflictError(f"Alias already exists: {normalized_alias}")

        candidate_meta = dict((candidate.content_json or {}).get("_meta") or {})
        alias_payload = {
            "alias": normalized_alias,
            "type": alias_type or "alias",
            "status": "canonical",
            "needs_review": False,
            "reviewed_at": datetime.now(UTC).isoformat(),
            "reviewed_by": "manual",
            "reviewed_from": "world_candidate_alias_resolution",
        }
        for key in (
            "source",
            "workflow_id",
            "scene_id",
            "scene_index",
            "source_scene_index",
            "source_chapter_index",
            "confidence",
            "quote",
        ):
            if candidate_meta.get(key) is not None:
                alias_payload[key] = candidate_meta[key]

        target_aliases.append(alias_payload)
        target_content["aliases"] = target_aliases
        target.content_json = target_content

        dedup_service = EntityDedupService()
        migration_result = await dedup_service._migrate_relations(
            db,
            novel_id,
            candidate_id,
            target_entity_id,
        )
        self_loops_cleaned = 0
        created_self_loop_ids = migration_result.get("created_self_loop_ids", [])
        if created_self_loop_ids:
            self_loops_cleaned = await dedup_service._relation_repo.deprecate_many(
                db,
                [parse_uuid(rel_id, "relation_id") for rel_id in created_self_loop_ids],
            )

        candidate_content = dict(candidate.content_json or {})
        candidate_content["merged_into"] = str(target.id)
        candidate_content["merged_at"] = datetime.now(UTC).isoformat()
        candidate_content["resolved_as"] = "alias"
        candidate_content["resolved_alias"] = normalized_alias
        candidate_content["resolved_alias_type"] = alias_type or "alias"
        await self.repo.update(
            db,
            candidate,
            CoreEntityUpdate(status="merged", content_json=candidate_content),
        )
        await db.flush()

        await self._mark_context_changed(
            db,
            novel_id=novel_id,
            entity_id=str(target.id),
            reason="alias_updated",
        )
        await self._mark_context_changed(
            db,
            novel_id=novel_id,
            entity_id=str(candidate.id),
            reason="candidate_resolved_as_alias",
        )
        affected_ids = [str(candidate.id), str(target.id)]
        return {
            **self._alias_response(target, alias_payload),
            "candidate_entity_id": str(candidate.id),
            "target_entity_id": str(target.id),
            "affected_ids": affected_ids,
            "merged_ids": [str(candidate.id)],
            "relations_migrated": migration_result["migrated"],
            "relations_deduplicated": migration_result["deduplicated"],
            "self_loops_cleaned": self_loops_cleaned,
        }

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

        content = dict(entity.content_json or {})
        aliases = list(content.get("aliases", []))
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
