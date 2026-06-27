"""State assembler 测试 — 通过 assemble() 公开接口验证正史状态装配。

使用 InMemoryStateSource / MagicMock 替换真实 DB，验证装配器的转换逻辑。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.state_assembler import (
    InMemoryStateSource,
    assemble,
    set_default_source,
)

# ============================================================
# Helpers
# ============================================================


def _make_entity(
    *,
    novel_id: str | None = None,
    name: str = "Entity",
    status: str = "canonical",
    importance: float = 0.5,
    **overrides: object,
) -> MagicMock:
    entity = MagicMock()
    entity.id = uuid.uuid4()
    entity.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    entity.entity_type = "item"
    entity.name = name
    entity.summary = None
    entity.public_info = None
    entity.hidden_truth = None
    entity.content_json = {}
    entity.importance = importance
    entity.importance_level = "normal"
    entity.reveal_level = "author_only"
    entity.status = status
    for key, value in overrides.items():
        setattr(entity, key, value)
    return entity


def _make_relation(
    *,
    novel_id: str | None = None,
    relation_type: str = "ally",
    status: str = "canonical",
    **overrides: object,
) -> MagicMock:
    relation = MagicMock()
    relation.id = uuid.uuid4()
    relation.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    relation.source_id = uuid.uuid4()
    relation.target_id = uuid.uuid4()
    relation.relation_type = relation_type
    relation.description = None
    relation.strength = 0.5
    relation.status = status
    for key, value in overrides.items():
        setattr(relation, key, value)
    return relation


def _make_character(
    *,
    novel_id: str | None = None,
    name: str = "Character",
    meta: dict | None = None,
    **overrides: object,
) -> MagicMock:
    character = MagicMock()
    character.entity_id = uuid.uuid4()
    character.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    character.name = name
    character.meta = meta or {}
    for key, value in overrides.items():
        setattr(character, key, value)
    return character


def _make_knowledge(
    *,
    novel_id: str | None = None,
    known_content: str = "知道",
    **overrides: object,
) -> MagicMock:
    knowledge = MagicMock()
    knowledge.id = uuid.uuid4()
    knowledge.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    knowledge.character_id = uuid.uuid4()
    knowledge.target_type = "entity"
    knowledge.target_id = uuid.uuid4()
    knowledge.knowledge_level = "full"
    knowledge.known_content = known_content
    knowledge.source_chapter_index = None
    knowledge.status = "canonical"
    for key, value in overrides.items():
        setattr(knowledge, key, value)
    return knowledge


def _set_source(**kwargs: object) -> None:
    set_default_source(InMemoryStateSource(**kwargs))


# ============================================================
# Tracer bullet — canonical entities filter
# ============================================================


async def test_assemble_returns_only_canonical_entities(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    _set_source(
        entities=[
            _make_entity(novel_id=novel_id, name="正史之剑", status="canonical"),
            _make_entity(novel_id=novel_id, name="正史之盾", status="canonical"),
            _make_entity(novel_id=novel_id, name="草稿之物", status="draft"),
        ]
    )
    try:
        state = await assemble(db_session, novel_id)

        assert len(state["entities"]) == 2
        assert {e["name"] for e in state["entities"]} == {"正史之剑", "正史之盾"}
    finally:
        set_default_source(None)


async def test_assemble_returns_only_canonical_relations(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """EntityRelationRepository.get_by_novel 不支持 status 过滤,
    必须在 source 层用 Python 端筛 (与旧 facade.py:568 行为一致)。"""
    _set_source(
        relations=[
            _make_relation(novel_id=novel_id, relation_type="ally", status="canonical"),
            _make_relation(novel_id=novel_id, relation_type="enemy", status="draft"),
        ]
    )
    try:
        state = await assemble(db_session, novel_id)

        assert len(state["relations"]) == 1
        assert state["relations"][0]["relation_type"] == "ally"
    finally:
        set_default_source(None)


async def test_assemble_extracts_character_locations_from_meta(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """character_locations 从 Character.meta JSON 读 location_id, key=character_id。
    没有 location_id 的 character 不进入 dict。"""
    loc_id = str(uuid.uuid4())
    _set_source(
        characters=[
            _make_character(
                novel_id=novel_id,
                name="有位置的人",
                meta={
                    "location_id": loc_id,
                    "text_state": "在城门口",
                    "chapter_index": 3,
                },
            ),
            _make_character(novel_id=novel_id, name="无位置的人", meta={}),
        ]
    )
    try:
        state = await assemble(db_session, novel_id)

        assert len(state["character_locations"]) == 1
        only_key = next(iter(state["character_locations"]))
        entry = state["character_locations"][only_key]
        assert entry["location_id"] == loc_id
        assert entry["text_state"] == "在城门口"
        assert entry["chapter_index"] == 3
    finally:
        set_default_source(None)


async def test_assemble_includes_character_knowledge(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    char_id = uuid.uuid4()
    _set_source(
        knowledge=[
            _make_knowledge(
                novel_id=novel_id,
                character_id=char_id,
                knowledge_level="rumor",
                known_content="听说某处有宝藏",
            )
        ]
    )
    try:
        state = await assemble(db_session, novel_id)

        assert len(state["character_knowledge"]) == 1
        entry = state["character_knowledge"][0]
        assert entry["knowledge_level"] == "rumor"
        assert entry["known_content"] == "听说某处有宝藏"
        assert entry["character_id"] == str(char_id)
    finally:
        set_default_source(None)


async def test_assemble_preserves_zero_importance(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """CLAUDE.md §5: 0.0 是合法 importance, 不能用 if value: 过滤掉。"""
    _set_source(
        entities=[
            _make_entity(
                novel_id=novel_id,
                name="零重要之物",
                status="canonical",
                importance=0.0,
            )
        ]
    )
    try:
        state = await assemble(db_session, novel_id)

        assert len(state["entities"]) == 1
        assert state["entities"][0]["importance"] == 0.0
        assert state["entities"][0]["name"] == "零重要之物"
    finally:
        set_default_source(None)


async def test_assemble_propagates_db_errors(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """CLAUDE.md §8: DB 异常必须向上传播, 不允许 try/except: pass。"""

    class FailingSource:
        async def list_canonical_entities(self, _db, _nid, *, skip, limit):
            raise OperationalError("SELECT", {}, Exception("connection lost"))

        async def list_canonical_relations(self, _db, _nid, *, skip, limit):
            return []

        async def list_characters(self, _db, _nid, *, skip, limit):
            return []

        async def list_character_knowledge(self, _db, _nid, *, skip, limit):
            return []

    set_default_source(FailingSource())  # type: ignore[arg-type]
    try:
        with pytest.raises(OperationalError):
            await assemble(db_session, novel_id)
    finally:
        set_default_source(None)


async def test_assemble_returns_empty_shape_for_empty_novel(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """没有任何正史数据的 novel 应该返空 shape, 不是抛错。"""
    _set_source()
    try:
        state = await assemble(db_session, novel_id)

        assert state == {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
    finally:
        set_default_source(None)


async def test_assemble_isolates_novel_id_across_all_sections(
    db_session: AsyncSession,
) -> None:
    """A novel 的正史数据不能漏到 B novel 的快照里 (CLAUDE.md §4)。

    InMemoryStateSource 本身不过滤 novel_id, 因此该测试改为验证
    assemble() 把 source 返回的行正确装配；隔离由生产 SqlAlchemyStateSource
    保证。本测试仍保留 source 不混数据的语义：分别给 A/B 喂不同数据。
    """
    novel_a = uuid.uuid4()
    novel_b = uuid.uuid4()
    nid_a_str = str(novel_a)
    nid_b_str = str(novel_b)

    a_char_id = uuid.uuid4()
    a_rel_src = uuid.uuid4()
    a_rel_tgt = uuid.uuid4()

    _set_source(
        entities=[
            _make_entity(novel_id=nid_a_str, name="A 的剑", status="canonical"),
            _make_entity(novel_id=nid_b_str, name="B 的剑", status="canonical"),
        ],
        relations=[
            _make_relation(
                novel_id=nid_a_str,
                source_id=a_rel_src,
                target_id=a_rel_tgt,
                relation_type="ally",
                status="canonical",
            ),
            _make_relation(novel_id=nid_b_str, relation_type="ally", status="canonical"),
        ],
        characters=[
            _make_character(
                novel_id=nid_a_str,
                entity_id=a_char_id,
                name="A 主角",
                meta={"location_id": str(uuid.uuid4())},
            ),
            _make_character(
                novel_id=nid_b_str,
                name="B 主角",
                meta={"location_id": str(uuid.uuid4())},
            ),
        ],
        knowledge=[
            _make_knowledge(
                novel_id=nid_a_str, character_id=a_char_id, known_content="A 知道"
            ),
            _make_knowledge(novel_id=nid_b_str, known_content="B 知道"),
        ],
    )
    try:
        state_a = await assemble(db_session, nid_a_str)

        assert {e["name"] for e in state_a["entities"]} == {"A 的剑"}
        assert {r["relation_type"] for r in state_a["relations"]} == {"ally"}
        assert {k["known_content"] for k in state_a["character_knowledge"]} == {"A 知道"}
        assert len(state_a["character_locations"]) == 1
        assert str(a_char_id) in state_a["character_locations"]

        state_b = await assemble(db_session, nid_b_str)
        assert {e["name"] for e in state_b["entities"]} == {"B 的剑"}
        assert {k["known_content"] for k in state_b["character_knowledge"]} == {"B 知道"}
        assert len(state_b["character_locations"]) == 1
        assert str(a_char_id) not in state_b["character_locations"]
    finally:
        set_default_source(None)


async def test_in_memory_source_drives_assemble_without_db(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """证明 StateSource seam 是真的 — 装配器不依赖 SQLAlchemy 也能跑。
    2 个 adapter (SqlAlchemy + InMemory) 让 seam 不是空抽象。"""
    from modules.world.models import (
        Character,
        CharacterKnowledge,
        CoreEntity,
        EntityRelation,
    )
    from modules.world.state_assembler import (
        InMemoryStateSource,
        assemble,
        set_default_source,
    )

    canon = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="item",
        name="内存里的剑",
        status="canonical",
    )
    rel = EntityRelation(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        source_id=uuid.uuid4(),
        target_id=uuid.uuid4(),
        relation_type="ally",
        status="canonical",
    )
    ch = Character(
        entity_id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        name="内存主角",
        meta={"location_id": str(uuid.uuid4())},
    )
    kn = CharacterKnowledge(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        character_id=ch.entity_id,
        target_type="entity",
        target_id=uuid.uuid4(),
        knowledge_level="full",
        known_content="全部知道",
    )

    set_default_source(
        InMemoryStateSource(
            entities=[canon],
            relations=[rel],
            characters=[ch],
            knowledge=[kn],
        )
    )
    try:
        # db_session 不被触碰 — InMemoryStateSource 完全在内存中
        state = await assemble(db_session, novel_id)

        assert {e["name"] for e in state["entities"]} == {"内存里的剑"}
        assert {r["relation_type"] for r in state["relations"]} == {"ally"}
        assert {k["known_content"] for k in state["character_knowledge"]} == {"全部知道"}
        assert len(state["character_locations"]) == 1
    finally:
        set_default_source(None)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())
