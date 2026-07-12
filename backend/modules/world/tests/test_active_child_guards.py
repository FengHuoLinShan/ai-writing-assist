"""非 canonical CoreEntity 不得通过扩展表绕过建议采用流程。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.imports.models import ImportedChapter, ImportRecord
from modules.world.models import Character, CharacterKnowledge, CoreEntity, Event
from modules.world.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
    CharacterUpdate,
    EventCreate,
    EventUpdate,
)
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EventService,
)
from modules.world.tests.helpers import _create_project


def _entity(
    novel_id: str,
    *,
    entity_type: str,
    name: str,
    status: str = "canonical",
    compatibility_shadow: bool = False,
) -> CoreEntity:
    content_json = None
    if compatibility_shadow:
        content_json = {
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": uuid.uuid4().hex,
            }
        }
    return CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        entity_type=entity_type,
        name=name,
        status=status,
        content_json=content_json,
    )


@pytest.mark.asyncio
async def test_character_shadow_cannot_create_or_expose_active_profile(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    shadow = _entity(
        novel_id,
        entity_type="character",
        name="待处理人物",
        status="candidate",
        compatibility_shadow=True,
    )
    db_session.add(shadow)
    await db_session.flush()

    service = CharacterService()
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            novel_id,
            CharacterCreate(entity_id=str(shadow.id), name=shadow.name),
        )

    # 模拟旧版绕过服务层留下的 canonical 扩展行。
    db_session.add(
        Character(
            entity_id=shadow.id,
            novel_id=uuid.UUID(novel_id),
            name=shadow.name,
            status="canonical",
        )
    )
    await db_session.flush()

    items, total = await service.list(db_session, novel_id)
    assert items == []
    assert total == 0
    context = await service.get_characters_context(
        db_session,
        novel_id,
        [str(shadow.id)],
    )
    assert context.characters == []
    with pytest.raises(NotFoundError):
        await service.update(
            db_session,
            str(shadow.id),
            CharacterUpdate(current_goal="绕过采用"),
            novel_id=novel_id,
        )


@pytest.mark.asyncio
async def test_character_profile_requires_character_owner_type(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location = _entity(novel_id, entity_type="location", name="不是人物")
    db_session.add(location)
    await db_session.flush()

    with pytest.raises(ValidationError):
        await CharacterService().create(
            db_session,
            novel_id,
            CharacterCreate(entity_id=str(location.id), name="错误人物档案"),
        )


@pytest.mark.asyncio
async def test_character_location_requires_adopted_location(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    owner = _entity(novel_id, entity_type="character", name="已采用人物")
    shadow_location = _entity(
        novel_id,
        entity_type="location",
        name="待处理地点",
        status="candidate",
        compatibility_shadow=True,
    )
    character = Character(
        entity_id=owner.id,
        novel_id=uuid.UUID(novel_id),
        name=owner.name,
        status="canonical",
        meta={"location_id": str(shadow_location.id)},
    )
    db_session.add_all([owner, shadow_location, character])
    await db_session.flush()

    service = CharacterService()
    with pytest.raises(NotFoundError):
        await service.update_location(
            db_session,
            novel_id,
            str(owner.id),
            str(shadow_location.id),
            "不应写入",
            1,
        )
    assert await service.get_location_id(db_session, novel_id, str(owner.id)) is None
    with pytest.raises(NotFoundError):
        await service.get_characters_at_location(
            db_session,
            novel_id,
            str(shadow_location.id),
        )


@pytest.mark.asyncio
async def test_event_shadow_and_unadopted_location_are_rejected_and_hidden(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    shadow_event = _entity(
        novel_id,
        entity_type="event",
        name="待处理事件",
        status="candidate",
        compatibility_shadow=True,
    )
    canonical_event = _entity(novel_id, entity_type="event", name="已采用事件")
    canonical_location = _entity(novel_id, entity_type="location", name="已采用地点")
    shadow_location = _entity(
        novel_id,
        entity_type="location",
        name="待处理地点",
        status="draft",
        compatibility_shadow=True,
    )
    record = ImportRecord(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        file_name="event-guard.txt",
        file_type="txt",
        status="done",
    )
    chapter = ImportedChapter(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        import_record_id=record.id,
        chapter_index=1,
        title="第一章",
        content="事件证据",
    )
    db_session.add_all(
        [
            shadow_event,
            canonical_event,
            canonical_location,
            shadow_location,
            record,
            chapter,
        ]
    )
    await db_session.flush()

    service = EventService()
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            novel_id,
            EventCreate(
                entity_id=str(shadow_event.id),
                source_chapter_id=str(chapter.id),
                location_entity_id=str(canonical_location.id),
                timeline_order=1,
            ),
        )
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            novel_id,
            EventCreate(
                entity_id=str(canonical_event.id),
                source_chapter_id=str(chapter.id),
                location_entity_id=str(shadow_location.id),
                timeline_order=2,
            ),
        )

    legacy = Event(
        entity_id=shadow_event.id,
        novel_id=uuid.UUID(novel_id),
        source_chapter_id=chapter.id,
        location_entity_id=canonical_location.id,
        timeline_order=1,
    )
    legacy_unadopted_location = Event(
        entity_id=canonical_event.id,
        novel_id=uuid.UUID(novel_id),
        source_chapter_id=chapter.id,
        location_entity_id=shadow_location.id,
        timeline_order=2,
    )
    db_session.add_all([legacy, legacy_unadopted_location])
    await db_session.flush()

    items, total = await service.list(db_session, novel_id)
    assert items == []
    assert total == 0
    assert await service.get_events_in_order(db_session, novel_id) == []
    assert (
        await service.get_events_for_chapter(
            db_session,
            novel_id,
            str(chapter.id),
        )
        == []
    )
    with pytest.raises(NotFoundError):
        await service.update(
            db_session,
            str(shadow_event.id),
            EventUpdate(timeline_order=3),
            novel_id=novel_id,
        )


@pytest.mark.asyncio
async def test_knowledge_with_unadopted_character_or_target_is_rejected_and_hidden(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    character_owner = _entity(novel_id, entity_type="character", name="已采用人物")
    shadow_character = _entity(
        novel_id,
        entity_type="character",
        name="待处理人物",
        status="candidate",
        compatibility_shadow=True,
    )
    canonical_target = _entity(novel_id, entity_type="item", name="已采用物品")
    shadow_target = _entity(
        novel_id,
        entity_type="item",
        name="待处理物品",
        status="ignored",
        compatibility_shadow=True,
    )
    canonical_character = Character(
        entity_id=character_owner.id,
        novel_id=uuid.UUID(novel_id),
        name=character_owner.name,
        status="canonical",
    )
    legacy_shadow_character = Character(
        entity_id=shadow_character.id,
        novel_id=uuid.UUID(novel_id),
        name=shadow_character.name,
        status="canonical",
    )
    db_session.add_all(
        [
            character_owner,
            shadow_character,
            canonical_target,
            shadow_target,
            canonical_character,
            legacy_shadow_character,
        ]
    )
    await db_session.flush()

    service = CharacterKnowledgeService()
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            novel_id,
            CharacterKnowledgeCreate(
                character_id=str(character_owner.id),
                target_type="item",
                target_id=str(shadow_target.id),
                knowledge_level="full",
            ),
        )
    with pytest.raises(NotFoundError):
        await service.create(
            db_session,
            novel_id,
            CharacterKnowledgeCreate(
                character_id=str(shadow_character.id),
                target_type="item",
                target_id=str(canonical_target.id),
                knowledge_level="full",
            ),
        )

    hidden_by_target = CharacterKnowledge(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        character_id=character_owner.id,
        target_type="item",
        target_id=shadow_target.id,
        knowledge_level="full",
        status="canonical",
    )
    hidden_by_character = CharacterKnowledge(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        character_id=shadow_character.id,
        target_type="item",
        target_id=canonical_target.id,
        knowledge_level="full",
        status="canonical",
    )
    db_session.add_all([hidden_by_target, hidden_by_character])
    await db_session.flush()

    listed = await service.list(db_session, novel_id)
    assert listed.items == []
    assert listed.total == 0
    context = await CharacterService().get_character_knowledge_context(
        db_session,
        novel_id,
        str(character_owner.id),
    )
    assert context == []
    with pytest.raises(NotFoundError):
        await service.update(
            db_session,
            str(hidden_by_target.id),
            CharacterKnowledgeUpdate(known_content="不应允许更新"),
            novel_id=novel_id,
        )
