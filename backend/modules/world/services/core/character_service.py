"""CharacterService — 人物业务。继承 BaseCRUDService (ADR-0002)。

知识边界 (CharacterKnowledge) 的 CRUD 移到 CharacterKnowledgeService (独立子类)。
本 service 只保留:
- 5 verb 继承自 base
- 8 个特例方法 (人物上下文 / 知识过滤 / facade 跨模块 leak)
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import NotFoundError, ValidationError
from modules.world.models import Character, CoreEntity
from modules.world.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
    CoreEntityRepository,
)
from modules.world.schemas import (
    CharacterContextBundle,
    CharacterContextItem,
    CharacterCreate,
    CharacterResponse,
    CharacterUpdate,
)
from modules.world.services.common import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class CharacterService(
    CrudService[Character, CharacterCreate, CharacterUpdate, CharacterResponse],
):
    """人物业务服务。

    5 verb 继承自 base; 知识 CRUD 在独立 CharacterKnowledgeService。
    """

    repo = CharacterRepository()
    response = CharacterResponse
    label = "Character"
    id_param = "character_id"  # Character PK 是 entity_id, parse_uuid 报错字段名

    # knowledge 业务方法不属 base 5 verb, 显式注入第二个 repo
    def __init__(self) -> None:
        self._knowledge_repo = CharacterKnowledgeRepository()
        self._entity_repo = CoreEntityRepository()

    # ============================================================
    # 5 verb 继承自 base
    # (list 加 clamp, create 校验 entity_id, 其它 3 verb 透传)
    # ============================================================

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CharacterCreate,
    ) -> CharacterResponse:
        """创建人物前校验关联 CoreEntity 存在且属于当前项目。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(data.entity_id, "entity_id")
        await self._require_canonical_entity(
            db,
            nid,
            eid,
            raw_id=data.entity_id,
            entity_type="character",
            label="CoreEntity",
        )
        existing = await self.repo.get(db, eid)
        if existing is not None:
            if existing.novel_id != nid:
                self._raise_404(data.entity_id)
            meta = dict(existing.meta or {})
            if meta.get("auto_materialized") is not True:
                raise ValidationError(f"Character {data.entity_id} already exists")

            changes = data.model_dump(
                exclude={"entity_id", "novel_id"},
                exclude_unset=True,
            )
            submitted_meta = changes.pop("meta", None)
            meta.update(submitted_meta or {})
            meta["auto_materialized"] = False
            changes["meta"] = meta
            updated = await self.repo.update(
                db,
                existing,
                CharacterUpdate.model_validate(changes),
            )
            if updated is None:
                self._raise_404(data.entity_id)
            return self._to_response(updated)
        try:
            obj = await self.repo.create(db, nid, data)
        except IntegrityError as exc:
            raise ValidationError(
                f"CoreEntity {data.entity_id} not found or conflict"
            ) from exc
        return self._to_response(obj)

    async def ensure_for_core_entity(
        self,
        db: AsyncSession,
        entity: CoreEntity,
    ) -> Character:
        """Ensure an adopted character identity has its minimum typed profile.

        CoreEntity is the identity root while ``characters`` stores optional
        character-specific details.  Author-facing character selectors and
        POV context require the typed row to exist, so adoption materializes a
        reversible scaffold.  An explicit Character create later upgrades the
        scaffold instead of creating a duplicate row.
        """

        if entity.entity_type != "character" or entity.status != "canonical":
            raise ValidationError("Only canonical character entities have profiles")

        existing = await self.repo.get(db, entity.id)
        core_meta = dict(entity.content_json or {})
        scaffold_meta = {
            "auto_materialized": True,
            "source": "core_entity",
            "core_summary": entity.summary,
            "public_info": entity.public_info,
        }
        if existing is not None:
            if existing.novel_id != entity.novel_id:
                raise ValidationError("Character profile belongs to another novel")
            existing_meta = dict(existing.meta or {})
            if existing_meta.get("auto_materialized") is True:
                existing_meta.update(scaffold_meta)
                updated = await self.repo.update(
                    db,
                    existing,
                    CharacterUpdate(
                        name=entity.name,
                        aliases=self._core_aliases(core_meta),
                        secret=entity.hidden_truth,
                        meta=existing_meta,
                        status="canonical",
                    ),
                )
                assert updated is not None
                return updated
            if existing.name != entity.name:
                updated = await self.repo.update(
                    db,
                    existing,
                    CharacterUpdate(name=entity.name),
                )
                assert updated is not None
                return updated
            return existing

        return await self.repo.create(
            db,
            entity.novel_id,
            CharacterCreate(
                entity_id=str(entity.id),
                name=entity.name,
                aliases=self._core_aliases(core_meta),
                secret=entity.hidden_truth,
                meta=scaffold_meta,
                status="canonical",
            ),
        )

    @staticmethod
    def _core_aliases(content_json: dict) -> list[dict]:
        aliases: list[dict] = []
        for item in content_json.get("aliases") or []:
            if isinstance(item, dict):
                alias = str(item.get("alias") or item.get("name") or "").strip()
                alias_type = str(item.get("type") or item.get("alias_type") or "alias")
            else:
                alias = str(item or "").strip()
                alias_type = "alias"
            if alias:
                aliases.append({"alias": alias, "type": alias_type})
        return aliases

    async def get(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> CharacterResponse:
        cid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        character = await self.repo.get(db, cid)
        self._assert_found_in_novel(character, id, nid)
        await self._require_canonical_entity(
            db,
            nid,
            cid,
            raw_id=id,
            entity_type="character",
            label="Character",
        )
        return self._to_response(character)

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        data: CharacterUpdate,
        *,
        novel_id: str,
    ) -> CharacterResponse:
        cid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        character = await self.repo.get(db, cid)
        self._assert_found_in_novel(character, id, nid)
        await self._require_canonical_entity(
            db,
            nid,
            cid,
            raw_id=id,
            entity_type="character",
            label="Character",
        )
        updated = await self.repo.update(db, character, data)
        self._assert_found_in_novel(updated, id, nid)
        return self._to_response(updated)

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterResponse], int]:
        """返 (items, total) tuple (非 ListResponse 包装, 与 WorldEntityService 不同)。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db,
            nid,
            skip=skip,
            limit=limit,
        )
        return [CharacterResponse.model_validate(c) for c in items], total

    # ============================================================
    # CharacterState 更新 (跨多字段, 非 5 verb 标准 update)
    # ============================================================

    async def update_character_state(
        self,
        db: AsyncSession,
        character_id: str,
        *,
        current_state: str | None = None,
        current_emotion: str | None = None,
        current_goal: str | None = None,
        novel_id: str,
    ) -> CharacterResponse:
        cid = parse_uuid(character_id, "character_id")
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, cid)
        if existing is None or existing.novel_id != nid:
            self._raise_404(character_id)
        await self._require_canonical_entity(
            db,
            nid,
            cid,
            raw_id=character_id,
            entity_type="character",
            label="Character",
        )
        update_data = CharacterUpdate(
            current_state=current_state,
            current_emotion=current_emotion,
            current_goal=current_goal,
        )
        character = await self.repo.update(db, existing, update_data)
        if character is None:
            self._raise_404(character_id)
        return CharacterResponse.model_validate(character)

    # ============================================================
    # 人物上下文 (供 context module 用)
    # ============================================================

    async def get_characters_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_ids: list[str],
        reveal_mode: str = "author_safe",
    ) -> CharacterContextBundle:
        nid = parse_uuid(novel_id, "novel_id")
        cids = [parse_uuid(cid, "character_id") for cid in character_ids]
        characters = await self.repo.get_by_ids(db, nid, cids)

        items = []
        for char in characters:
            item = CharacterContextItem(
                character_id=str(char.entity_id),
                name=char.name,
                role=char.role,
                appearance=char.appearance,
                personality=char.personality,
                desire=char.desire,
                fear=char.fear,
                weakness=char.weakness,
                current_goal=char.current_goal,
                current_state=char.current_state,
                current_emotion=char.current_emotion,
                stance=char.stance,
                voice_style=char.voice_style,
                behavior_rules=char.behavior_rules or [],
                relationship_summary=char.relationship_summary,
                meta=char.meta or {},
            )
            if reveal_mode == "author_only":
                item.secret = char.secret
            items.append(item)

        return CharacterContextBundle(
            characters=items,
            total=len(items),
            reveal_mode=reveal_mode,
        )

    async def get_character_knowledge_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        target_ids: list[str] | None = None,
    ) -> list:
        """返回 knowledge 上下文, 留为返回 dict (避免循环 import schema)。"""
        from modules.world.schemas import CharacterKnowledgeContext

        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        tids = [parse_uuid(tid) for tid in target_ids] if target_ids else None
        knowledge_list = await self._knowledge_repo.get_by_target(
            db,
            nid,
            cid,
            tids,
        )

        return [
            CharacterKnowledgeContext(
                target_type=k.target_type,
                target_id=str(k.target_id),
                knowledge_level=k.knowledge_level,
                known_content=k.known_content,
                misconception=k.misconception,
            )
            for k in knowledge_list
        ]

    async def filter_context_by_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        context_items: list[dict],
        *,
        visible_until_chapter: int | None = None,
    ) -> tuple[list[dict], int, int]:
        cid = parse_uuid(character_id, "character_id")
        nid = parse_uuid(novel_id, "novel_id")

        target_ids: set[str] = set()
        for item in context_items:
            t_id = item.get("target_id", "")
            if item.get("target_type", "") and t_id:
                target_ids.add(t_id)

        knowledge_map: dict[str, dict] = {}
        if target_ids:
            tid_uuids = [parse_uuid(tid) for tid in target_ids]
            records = await self._knowledge_repo.get_by_target(
                db,
                nid,
                cid,
                tid_uuids,
                visible_until_chapter=visible_until_chapter,
            )
            for rec in records:
                key = f"{rec.target_type}:{rec.target_id}"
                knowledge_map[key] = {
                    "target_type": rec.target_type,
                    "target_id": str(rec.target_id),
                    "knowledge_level": rec.knowledge_level,
                    "known_content": rec.known_content,
                    "misconception": rec.misconception,
                    "source_chapter_index": rec.source_chapter_index,
                    "is_public_baseline": rec.is_public_baseline,
                }

        filtered_items: list[dict] = []
        removed_count = 0
        replaced_count = 0

        for item in context_items:
            key = f"{item.get('target_type', '')}:{item.get('target_id', '')}"
            knowledge = knowledge_map.get(key) or knowledge_map.get(
                f"entity:{item.get('target_id', '')}"
            )

            if knowledge is None:
                filtered_item = self._public_character_visible_item(item)
                if filtered_item is None:
                    removed_count += 1
                    continue
                filtered_items.append(filtered_item)
                continue

            level = knowledge["knowledge_level"]
            metadata = {
                "knowledge_level": level,
                "knowledge_source_chapter_index": knowledge["source_chapter_index"],
                "knowledge_is_public_baseline": knowledge["is_public_baseline"],
            }

            if level == "unknown":
                removed_count += 1
            elif level in {"false_belief", "misunderstood"}:
                if not knowledge["misconception"]:
                    removed_count += 1
                    continue
                filtered_item = self._character_knowledge_identity(knowledge)
                filtered_item["content"] = knowledge["misconception"]
                filtered_item["summary"] = filtered_item["content"]
                filtered_item.update(metadata)
                filtered_item["is_misconception"] = True
                filtered_items.append(filtered_item)
                replaced_count += 1
            elif level == "restricted":
                filtered_item = self._character_knowledge_identity(knowledge)
                filtered_item.update(metadata)
                if knowledge["known_content"]:
                    filtered_item["content"] = knowledge["known_content"]
                    filtered_item["summary"] = knowledge["known_content"]
                else:
                    filtered_item.pop("content", None)
                    filtered_item.pop("summary", None)
                filtered_items.append(filtered_item)
            elif level in {"partial", "rumor"}:
                filtered_item = self._character_knowledge_identity(knowledge)
                filtered_item.update(metadata)
                if knowledge["known_content"]:
                    filtered_item["character_known_content"] = knowledge["known_content"]
                    filtered_item["content"] = knowledge["known_content"]
                    filtered_item["summary"] = knowledge["known_content"]
                else:
                    filtered_item.pop("content", None)
                    filtered_item.pop("summary", None)
                filtered_items.append(filtered_item)
            elif level == "full" and knowledge["known_content"]:
                filtered_item = self._character_knowledge_identity(knowledge)
                filtered_item.update(metadata)
                filtered_item["character_known_content"] = knowledge["known_content"]
                filtered_item["content"] = knowledge["known_content"]
                filtered_item["summary"] = knowledge["known_content"]
                filtered_items.append(filtered_item)
            else:
                removed_count += 1

        return filtered_items, removed_count, replaced_count

    @staticmethod
    def _character_knowledge_identity(knowledge: dict) -> dict:
        """Keep only target identity before adding the frozen knowledge version."""
        return {
            "target_type": knowledge["target_type"],
            "target_id": knowledge["target_id"],
        }

    @staticmethod
    def _public_character_visible_item(item: dict) -> dict | None:
        """Return the minimal public view for an item without explicit knowledge."""
        safe: dict = {}
        for field in (
            "target_type",
            "target_id",
            "id",
            "entity_id",
            "entity_type",
            "name",
            "status",
            "importance_level",
        ):
            if field in item and item[field] is not None:
                safe[field] = item[field]

        public_info = item.get("public_info")
        if public_info:
            safe["public_info"] = public_info
            safe["summary"] = public_info
            safe["content"] = public_info

        if not safe.get("name") and not safe.get("public_info"):
            return None
        safe["knowledge_level"] = "public_default"
        safe["visibility_source"] = "public_info"
        return safe

    # ============================================================
    # 跨模块 facade leak (PR 2)
    # ============================================================

    async def get_id_by_world_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        world_entity_id: str,
    ) -> str | None:
        """按核心实体 ID 查 character entity_id。返 str 或 None。

        novel_id 是跨模块契约的一部分，必须用于归属校验。
        """
        nid = parse_uuid(novel_id, "novel_id")
        weid = parse_uuid(world_entity_id, "entity_id")
        char = await self.repo.get(db, weid)
        if char is None or char.novel_id != nid:
            return None
        try:
            await self._require_canonical_entity(
                db,
                nid,
                weid,
                raw_id=world_entity_id,
                entity_type="character",
                label="Character",
            )
        except (NotFoundError, ValidationError):
            return None
        return str(char.entity_id)

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
    ) -> str | None:
        """按 character name 查正史 character 的 entity_id。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.find_character_by_name(db, nid, name)

    async def update_location(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        location_id: str,
        text_state: str,
        chapter_index: int,
    ) -> None:
        """更新 character 的位置元数据。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        loc_id = parse_uuid(location_id, "location_id")
        char = await self.repo.get(db, cid)
        if char is None or char.novel_id != nid:
            self._raise_404(character_id)
        await self._require_canonical_entity(
            db,
            nid,
            cid,
            raw_id=character_id,
            entity_type="character",
            label="Character",
        )
        await self._require_canonical_entity(
            db,
            nid,
            loc_id,
            raw_id=location_id,
            entity_type="location",
            label="Location",
        )
        await self.repo.update_character_meta_location(
            db,
            cid,
            loc_id,
            text_state,
            chapter_index,
        )

    async def get_characters_at_location(
        self,
        db: AsyncSession,
        novel_id: str,
        location_id: str,
    ) -> list[dict]:
        """查某 location 下的所有正史 character。"""
        nid = parse_uuid(novel_id, "novel_id")
        loc_id = parse_uuid(location_id, "location_id")
        await self._require_canonical_entity(
            db,
            nid,
            loc_id,
            raw_id=location_id,
            entity_type="location",
            label="Location",
        )
        return await self.repo.find_characters_by_location(db, nid, loc_id)

    async def get_location_id(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
    ) -> str | None:
        """查 character 的 location_id, 返 str 或 None。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        char = await self.repo.get(db, cid)
        if char is None or char.novel_id != nid:
            return None
        try:
            await self._require_canonical_entity(
                db,
                nid,
                cid,
                raw_id=character_id,
                entity_type="character",
                label="Character",
            )
        except (NotFoundError, ValidationError):
            return None
        location_id = await self.repo.get_character_location_id(db, cid)
        if location_id is None:
            return None
        try:
            location_uuid = parse_uuid(location_id, "location_id")
            await self._require_canonical_entity(
                db,
                nid,
                location_uuid,
                raw_id=location_id,
                entity_type="location",
                label="Location",
            )
        except (NotFoundError, ValidationError, ValueError):
            return None
        return location_id

    async def _require_canonical_entity(
        self,
        db: AsyncSession,
        novel_id,
        entity_id,
        *,
        raw_id: str,
        entity_type: str,
        label: str,
    ):
        entity = await self._entity_repo.get(db, entity_id)
        if entity is None or entity.novel_id != novel_id or entity.status != "canonical":
            raise NotFoundError(f"{label} {raw_id} not found in this novel")
        if entity.entity_type != entity_type:
            raise ValidationError(
                f"{label} {raw_id} must reference a {entity_type} CoreEntity",
                status_code=422,
            )
        return entity
