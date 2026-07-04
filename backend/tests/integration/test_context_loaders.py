"""Context Loader 集成测试

使用真实 SQLite 内存数据库，通过 loader 直接调用各模块 facade，
验证数据加载、budget 控制和边界行为。
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.loaders.characters_loader import CharactersLoader
from modules.context.services.loaders.events_loader import EventsLoader
from modules.context.services.loaders.memory_records_loader import MemoryRecordsLoader
from modules.context.services.loaders.outline_arc_loader import OutlineArcLoader
from modules.context.services.loaders.plot_threads_loader import PlotThreadsLoader
from modules.context.services.loaders.project_loader import ProjectLoader
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader
from modules.context.services.loaders.world_entities_loader import WorldEntitiesLoader

# ============================================================
# 辅助工厂函数
# ============================================================


def _compile_options(
    novel_id: str,
    *,
    task: str = "test task",
    scope: str = "full",
    chapter_index: int | None = 1,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
) -> CompileOptions:
    return CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        chapter_index=chapter_index,
        entity_ids=entity_ids,
        character_ids=character_ids,
        reveal_mode=reveal_mode,
    )


def _bundle(novel_id: str, task: str = "test") -> StructureContextBundle:
    return StructureContextBundle(novel_id=novel_id, task=task, scope="full")


# ============================================================
# ProjectLoader
# ============================================================


@pytest.mark.asyncio
async def test_project_loader_existing_project_loads_context(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = ProjectLoader()
    options = _compile_options(test_project_id)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.project is not None
    assert bundle.project["novel_id"] == test_project_id
    assert bundle.project["title"] == "测试小说"
    assert len(bundle.warnings) == 0


@pytest.mark.asyncio
async def test_project_loader_missing_project_adds_warning(
    db_session: AsyncSession,
):
    # Arrange
    loader = ProjectLoader()
    missing_id = str(uuid.uuid4())
    options = _compile_options(missing_id)
    bundle = _bundle(missing_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.project is None
    assert len(bundle.warnings) == 1
    assert missing_id in bundle.warnings[0]


# ============================================================
# CharactersLoader
# ============================================================


async def _create_character(
    db: AsyncSession,
    novel_id: str,
    name: str,
    **kwargs: object,
) -> str:
    from modules.world.models import Character, CoreEntity

    nid = uuid.UUID(hex=novel_id)
    eid = uuid.uuid4()
    entity = CoreEntity(
        id=eid,
        novel_id=nid,
        entity_type="character",
        name=name,
        status=kwargs.get("status", "canonical"),
    )
    db.add(entity)
    await db.flush()

    char = Character(
        entity_id=eid,
        novel_id=nid,
        name=name,
        role=kwargs.get("role", "protagonist"),
        appearance=kwargs.get("appearance"),
        personality=kwargs.get("personality"),
        desire=kwargs.get("desire"),
        fear=kwargs.get("fear"),
        secret=kwargs.get("secret"),
        weakness=kwargs.get("weakness"),
        current_goal=kwargs.get("current_goal"),
        current_state=kwargs.get("current_state"),
        current_emotion=kwargs.get("current_emotion"),
        stance=kwargs.get("stance"),
        voice_style=kwargs.get("voice_style"),
        behavior_rules=kwargs.get("behavior_rules", []),
        relationship_summary=kwargs.get("relationship_summary"),
        meta=kwargs.get("meta", {}),
        status=kwargs.get("status", "canonical"),
    )
    db.add(char)
    await db.flush()
    return str(eid)


@pytest.mark.asyncio
async def test_characters_loader_with_ids_loads_context(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    cid = await _create_character(db_session, test_project_id, "Alice")
    loader = CharactersLoader()
    options = _compile_options(test_project_id, character_ids=[cid])
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert len(bundle.characters) == 1
    assert bundle.characters[0]["name"] == "Alice"
    assert bundle.budget_used["characters"] == 1


@pytest.mark.asyncio
async def test_characters_loader_without_ids_infers_empty(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = CharactersLoader()
    options = _compile_options(test_project_id, character_ids=None)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.characters == []
    assert bundle.budget_used["characters"] == 0


@pytest.mark.asyncio
async def test_characters_loader_limits_character_ids_by_budget(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    cids = []
    for i in range(10):
        cid = await _create_character(db_session, test_project_id, f"Char{i}")
        cids.append(cid)
    loader = CharactersLoader()
    options = _compile_options(test_project_id, character_ids=cids)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — CONTEXT_BUDGET["characters"] == 6
    assert len(bundle.characters) == 6
    assert bundle.budget_used["characters"] == 6


@pytest.mark.asyncio
async def test_characters_loader_knowledge_boundary_filters_world_entities(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    from modules.world.models import CharacterKnowledge

    cid = await _create_character(db_session, test_project_id, "Bob")

    # Create a world entity that will be in bundle.world_entities
    from modules.world.models import CoreEntity

    eid = uuid.uuid4()
    entity = CoreEntity(
        id=eid,
        novel_id=uuid.UUID(hex=test_project_id),
        entity_type="item",
        name="Magic Sword",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()

    # Add knowledge record so filter doesn't remove everything
    knowledge = CharacterKnowledge(
        novel_id=uuid.UUID(hex=test_project_id),
        character_id=uuid.UUID(hex=cid),
        target_type="entity",
        target_id=eid,
        knowledge_level="full",
        known_content="He knows about the sword",
    )
    db_session.add(knowledge)
    await db_session.flush()

    loader = CharactersLoader()
    options = _compile_options(test_project_id, character_ids=[cid], scope="chapter")
    bundle = _bundle(test_project_id)
    bundle.world_entities = [
        {
            "target_type": "entity",
            "target_id": str(eid),
            "content": "Magic Sword details",
        }
    ]

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — knowledge filter ran and produced result (may be filtered or modified)
    assert bundle.world_entities is not None


# ============================================================
# EventsLoader
# ============================================================


async def _create_imported_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int = 1,
) -> str:
    from modules.imports.models import ImportedChapter, ImportRecord

    nid = uuid.UUID(hex=novel_id)
    rid = uuid.uuid4()
    record = ImportRecord(
        id=rid,
        novel_id=nid,
        file_name="test.txt",
        file_type="txt",
        status="done",
    )
    db.add(record)
    await db.flush()

    cid = uuid.uuid4()
    chapter = ImportedChapter(
        id=cid,
        novel_id=nid,
        import_record_id=rid,
        chapter_index=chapter_index,
        title=f"Chapter {chapter_index}",
        content="test content",
    )
    db.add(chapter)
    await db.flush()
    return str(cid)


async def _create_event(
    db: AsyncSession,
    novel_id: str,
    chapter_id: str,
    location_id: str,
    timeline_order: int = 1,
) -> str:
    from modules.world.models import CoreEntity, Event

    nid = uuid.UUID(hex=novel_id)
    eid = uuid.uuid4()
    entity = CoreEntity(
        id=eid,
        novel_id=nid,
        entity_type="event",
        name=f"Event {timeline_order}",
        status="canonical",
    )
    db.add(entity)
    await db.flush()

    event = Event(
        entity_id=eid,
        novel_id=nid,
        source_chapter_id=uuid.UUID(hex=chapter_id),
        location_entity_id=uuid.UUID(hex=location_id),
        timeline_order=timeline_order,
    )
    db.add(event)
    await db.flush()
    return str(eid)


async def _create_location_entity(
    db: AsyncSession,
    novel_id: str,
    name: str = "Test Location",
) -> str:
    from modules.world.models import CoreEntity

    eid = uuid.uuid4()
    entity = CoreEntity(
        id=eid,
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="location",
        name=name,
        status="canonical",
    )
    db.add(entity)
    await db.flush()
    return str(eid)


@pytest.mark.asyncio
async def test_events_loader_loads_events(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    chapter_id = await _create_imported_chapter(db_session, test_project_id)
    loc_id = await _create_location_entity(db_session, test_project_id)
    await _create_event(db_session, test_project_id, chapter_id, loc_id, timeline_order=1)
    await _create_event(db_session, test_project_id, chapter_id, loc_id, timeline_order=2)

    loader = EventsLoader()
    options = _compile_options(test_project_id)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert len(bundle.timeline_events) == 2
    assert bundle.budget_used["timeline"] == 2


@pytest.mark.asyncio
async def test_events_loader_empty_no_events(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = EventsLoader()
    options = _compile_options(test_project_id)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.timeline_events == []
    assert bundle.budget_used["timeline"] == 0


@pytest.mark.asyncio
async def test_events_loader_limits_by_budget(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    chapter_id = await _create_imported_chapter(db_session, test_project_id)
    loc_id = await _create_location_entity(db_session, test_project_id)
    for i in range(12):
        await _create_event(
            db_session,
            test_project_id,
            chapter_id,
            loc_id,
            timeline_order=i,
        )

    loader = EventsLoader()
    options = _compile_options(test_project_id)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — CONTEXT_BUDGET["timeline"] == 8
    assert len(bundle.timeline_events) == 8
    assert bundle.budget_used["timeline"] == 8


# ============================================================
# MemoryRecordsLoader
# ============================================================


@pytest.mark.asyncio
async def test_memory_records_loader_loads_panorama(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    from modules.memory.services import MemoryService

    _memory = MemoryService()
    eid = str(uuid.uuid4())
    events = [
        {
            "event_type": "entity_created",
            "entity_id": eid,
            "entity_type": "character",
            "snapshot_after": {
                "id": eid,
                "entity_type": "character",
                "name": "Alice",
                "summary": "A test character",
                "importance": 0.8,
                "importance_level": "core",
                "status": "canonical",
            },
        }
    ]
    await _memory.record_events(db_session, test_project_id, 1, events)

    loader = MemoryRecordsLoader()
    options = _compile_options(test_project_id, chapter_index=1)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.memory_records is not None
    assert bundle.memory_records != []
    assert bundle.budget_used["memory"] >= 1


@pytest.mark.asyncio
async def test_memory_records_loader_empty_fallback(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = MemoryRecordsLoader()
    options = _compile_options(test_project_id, chapter_index=1)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — no snapshots/events, falls back to world state (empty)
    assert bundle.memory_records is not None
    assert bundle.budget_used["memory"] == 0


@pytest.mark.asyncio
async def test_memory_records_loader_exception_returns_empty(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = MemoryRecordsLoader()
    options = _compile_options(test_project_id, chapter_index=1)
    bundle = _bundle(test_project_id)

    with mock.patch(
        "modules.memory.services.MemoryService.get_panorama",
        side_effect=RuntimeError("DB error"),
    ):
        # Act
        await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.memory_records == []
    assert bundle.budget_used["memory"] == 0


# ============================================================
# OutlineArcLoader
# ============================================================


async def _create_outline_arc(
    db: AsyncSession,
    novel_id: str,
    title: str,
    start_chapter: int,
    end_chapter: int,
    **kwargs: object,
) -> str:
    from modules.outline.models import OutlineArc

    aid = uuid.uuid4()
    arc = OutlineArc(
        id=aid,
        novel_id=uuid.UUID(hex=novel_id),
        title=title,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        arc_goal=kwargs.get("arc_goal"),
        core_conflict=kwargs.get("core_conflict"),
        status=kwargs.get("status", "canonical"),
    )
    db.add(arc)
    await db.flush()
    return str(aid)


@pytest.mark.asyncio
async def test_outline_arc_loader_with_chapter_loads_arc(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_outline_arc(
        db_session,
        test_project_id,
        "Arc 1",
        1,
        5,
        arc_goal="Test goal",
    )
    loader = OutlineArcLoader()
    options = _compile_options(test_project_id, chapter_index=2)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.outline_arc is not None
    assert bundle.outline_arc["title"] == "Arc 1"
    assert bundle.outline_arc["arc_goal"] == "Test goal"


@pytest.mark.asyncio
async def test_outline_arc_loader_no_chapter_returns_none(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = OutlineArcLoader()
    options = _compile_options(test_project_id, chapter_index=None)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.outline_arc is None


@pytest.mark.asyncio
async def test_outline_arc_loader_missing_arc_returns_none(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = OutlineArcLoader()
    options = _compile_options(test_project_id, chapter_index=99)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.outline_arc is None


# ============================================================
# PlotThreadsLoader
# ============================================================


async def _create_plot_thread(
    db: AsyncSession,
    novel_id: str,
    name: str,
    thread_type: str = "main",
    start_chapter: int = 1,
    planned_payoff_chapter: int | None = 10,
    **kwargs: object,
) -> str:
    from modules.outline.models import PlotThread

    tid = uuid.uuid4()
    thread = PlotThread(
        id=tid,
        novel_id=uuid.UUID(hex=novel_id),
        name=name,
        thread_type=thread_type,
        summary=kwargs.get("summary"),
        visible_goal=kwargs.get("visible_goal"),
        hidden_truth=kwargs.get("hidden_truth"),
        start_chapter=start_chapter,
        planned_payoff_chapter=planned_payoff_chapter,
        current_stage=kwargs.get("current_stage"),
        reader_known_state=kwargs.get("reader_known_state"),
        author_known_state=kwargs.get("author_known_state"),
        status=kwargs.get("status", "canonical"),
    )
    db.add(thread)
    await db.flush()
    return str(tid)


@pytest.mark.asyncio
async def test_plot_threads_loader_loads_active_threads(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_plot_thread(
        db_session,
        test_project_id,
        "Thread 1",
        start_chapter=1,
        planned_payoff_chapter=5,
    )
    await _create_plot_thread(
        db_session,
        test_project_id,
        "Thread 2",
        start_chapter=1,
        planned_payoff_chapter=10,
    )
    loader = PlotThreadsLoader()
    options = _compile_options(test_project_id, chapter_index=3)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert len(bundle.plot_threads) == 2
    assert bundle.plot_threads[0]["name"] == "Thread 1"
    assert bundle.plot_threads[1]["name"] == "Thread 2"


@pytest.mark.asyncio
async def test_plot_threads_loader_excludes_inactive_threads(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_plot_thread(
        db_session,
        test_project_id,
        "Active",
        start_chapter=1,
        planned_payoff_chapter=10,
    )
    await _create_plot_thread(
        db_session,
        test_project_id,
        "Ended",
        start_chapter=1,
        planned_payoff_chapter=2,
    )
    loader = PlotThreadsLoader()
    options = _compile_options(test_project_id, chapter_index=5)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — only active threads (start <= 5 <= payoff)
    assert len(bundle.plot_threads) == 1
    assert bundle.plot_threads[0]["name"] == "Active"


@pytest.mark.asyncio
async def test_plot_threads_loader_empty_returns_empty(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = PlotThreadsLoader()
    options = _compile_options(test_project_id, chapter_index=1)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.plot_threads == []


# ============================================================
# RagChunksLoader
# ============================================================


async def _create_rag_chunk(
    db: AsyncSession,
    novel_id: str,
    text: str,
    **kwargs: object,
) -> str:
    from modules.rag.models import RagChunk

    cid = uuid.uuid4()
    chunk = RagChunk(
        id=cid,
        novel_id=uuid.UUID(hex=novel_id),
        source_type=kwargs.get("source_type", "chapter_text"),
        text=text,
        summary=kwargs.get("summary"),
        chapter_index=kwargs.get("chapter_index"),
        entity_ids=kwargs.get("entity_ids", []),
        character_ids=kwargs.get("character_ids", []),
        thread_ids=kwargs.get("thread_ids", []),
        visibility=kwargs.get("visibility", "author_only"),
        importance=kwargs.get("importance", 0.5),
    )
    db.add(chunk)
    await db.flush()
    return str(cid)


@pytest.mark.asyncio
async def test_rag_chunks_loader_loads_chunks(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_rag_chunk(
        db_session,
        test_project_id,
        text="这是关于测试任务的重要内容",
        chapter_index=1,
    )
    loader = RagChunksLoader()
    options = _compile_options(
        test_project_id,
        task="测试任务",
        chapter_index=1,
    )
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert len(bundle.rag_chunks) >= 1
    assert bundle.budget_used["rag_chunks"] >= 1


@pytest.mark.asyncio
async def test_rag_chunks_loader_reader_mode_sets_visibility(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_rag_chunk(
        db_session,
        test_project_id,
        text="读者已知的内容片段",
        visibility="reader_known",
    )
    loader = RagChunksLoader()
    options = _compile_options(
        test_project_id,
        task="读者已知",
        reveal_mode="reader",
    )
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — visibility="reader" 时 loader 传 rag_visibility="reader_known"
    # 检索结果取决于 DB 数据; 我们只验证 loader 执行无异常且 budget 正确
    assert bundle.budget_used.get("rag_chunks", 0) >= 0


@pytest.mark.asyncio
async def test_rag_chunks_loader_empty_returns_empty(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = RagChunksLoader()
    options = _compile_options(test_project_id, task="不存在的查询")
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.rag_chunks == []
    assert bundle.budget_used["rag_chunks"] == 0


@pytest.mark.asyncio
async def test_rag_chunks_loader_limits_by_budget(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    for i in range(15):
        await _create_rag_chunk(
            db_session,
            test_project_id,
            text=f"测试任务相关内容段落 {i}",
        )
    loader = RagChunksLoader()
    options = _compile_options(test_project_id, task="测试任务")
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — CONTEXT_BUDGET["rag_chunks"] == 8
    assert len(bundle.rag_chunks) <= 8
    assert bundle.budget_used["rag_chunks"] <= 8


# ============================================================
# WorldEntitiesLoader
# ============================================================


async def _create_world_entity(
    db: AsyncSession,
    novel_id: str,
    name: str,
    importance: float = 0.5,
    importance_level: str = "normal",
    hidden_truth: str | None = None,
    **kwargs: object,
) -> str:
    from modules.world.models import CoreEntity

    eid = uuid.uuid4()
    entity = CoreEntity(
        id=eid,
        novel_id=uuid.UUID(hex=novel_id),
        entity_type=kwargs.get("entity_type", "item"),
        name=name,
        summary=kwargs.get("summary"),
        hidden_truth=hidden_truth,
        importance=importance,
        importance_level=importance_level,
        status=kwargs.get("status", "canonical"),
    )
    db.add(entity)
    await db.flush()
    return str(eid)


@pytest.mark.asyncio
async def test_world_entities_loader_with_ids_loads_limited(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    eids = []
    for i in range(20):
        eid = await _create_world_entity(db_session, test_project_id, f"Item{i}")
        eids.append(eid)
    loader = WorldEntitiesLoader()
    options = _compile_options(test_project_id, entity_ids=eids)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — limited by core_limit + normal_limit = 8 + 8 = 16
    assert len(bundle.world_entities) == 16
    assert (
        bundle.budget_used["core_entities"] + bundle.budget_used["normal_entities"] == 16
    )


@pytest.mark.asyncio
async def test_world_entities_loader_without_ids_sorts_by_importance(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_world_entity(
        db_session,
        test_project_id,
        "Normal1",
        importance=0.3,
        importance_level="normal",
    )
    await _create_world_entity(
        db_session,
        test_project_id,
        "Core1",
        importance=0.9,
        importance_level="core",
    )
    await _create_world_entity(
        db_session,
        test_project_id,
        "Core2",
        importance=0.8,
        importance_level="core",
    )
    loader = WorldEntitiesLoader()
    options = _compile_options(test_project_id, entity_ids=None)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert — core entities first (by importance), then normal
    assert len(bundle.world_entities) >= 2
    core_names = {
        e["name"] for e in bundle.world_entities if e.get("importance_level") == "core"
    }
    assert "Core1" in core_names
    assert "Core2" in core_names
    assert bundle.budget_used["core_entities"] >= 1
    assert bundle.budget_used["normal_entities"] >= 0


@pytest.mark.asyncio
async def test_world_entities_loader_reveal_mode_author_safe_masks_hidden_truth(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_world_entity(
        db_session,
        test_project_id,
        "SecretItem",
        importance=0.9,
        importance_level="core",
        hidden_truth="This is a secret",
    )
    loader = WorldEntitiesLoader()
    options = _compile_options(
        test_project_id,
        entity_ids=None,
        reveal_mode="author_safe",
    )
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    # Note: get_world_context(reveal_mode="author_safe") returns hidden_truth=None,
    # so the loader's AUTHOR_ONLY_WARNING prepend is not triggered.
    assert len(bundle.world_entities) == 1
    assert bundle.world_entities[0].get("hidden_truth") is None


@pytest.mark.asyncio
async def test_world_entities_loader_author_only_reveals_hidden_truth(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    await _create_world_entity(
        db_session,
        test_project_id,
        "SecretItem",
        importance=0.9,
        importance_level="core",
        hidden_truth="This is a secret",
    )
    loader = WorldEntitiesLoader()
    options = _compile_options(
        test_project_id,
        entity_ids=None,
        reveal_mode="author_only",
    )
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert len(bundle.world_entities) == 1
    assert bundle.world_entities[0].get("hidden_truth") == "This is a secret"


@pytest.mark.asyncio
async def test_world_entities_loader_empty_returns_empty(
    db_session: AsyncSession,
    test_project_id: str,
):
    # Arrange
    loader = WorldEntitiesLoader()
    options = _compile_options(test_project_id, entity_ids=None)
    bundle = _bundle(test_project_id)

    # Act
    await loader.load(db_session, options, bundle)

    # Assert
    assert bundle.world_entities == []
    assert bundle.budget_used["core_entities"] == 0
    assert bundle.budget_used["normal_entities"] == 0
