"""State assembler 测试 — 通过 assemble() 公开接口验证正史状态装配。

约束 (per backend/tests/CLAUDE.md):
- 不绕过 facade 直接 import services/repositories 做断言
- models 可用于 fixture 数据准备
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity

# ============================================================
# Tracer bullet — canonical entities filter
# ============================================================


async def test_assemble_returns_only_canonical_entities(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    from modules.world.state_assembler import assemble

    canonical_a = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="item",
        name="正史之剑",
        status="canonical",
    )
    canonical_b = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="item",
        name="正史之盾",
        status="canonical",
    )
    draft = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="item",
        name="草稿之物",
        status="draft",
    )
    db_session.add_all([canonical_a, canonical_b, draft])
    await db_session.flush()

    state = await assemble(db_session, novel_id)

    assert len(state["entities"]) == 2
    assert {e["name"] for e in state["entities"]} == {"正史之剑", "正史之盾"}


async def test_assemble_returns_only_canonical_relations(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """EntityRelationRepository.get_by_novel 不支持 status 过滤,
    必须在 source 层用 Python 端筛 (与旧 facade.py:568 行为一致)。"""
    from modules.world.models import EntityRelation
    from modules.world.state_assembler import assemble

    src = uuid.uuid4()
    tgt = uuid.uuid4()
    canonical_rel = EntityRelation(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        source_id=src,
        target_id=tgt,
        relation_type="ally",
        status="canonical",
    )
    draft_rel = EntityRelation(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        source_id=src,
        target_id=uuid.uuid4(),
        relation_type="enemy",
        status="draft",
    )
    db_session.add_all([canonical_rel, draft_rel])
    await db_session.flush()

    state = await assemble(db_session, novel_id)

    assert len(state["relations"]) == 1
    assert state["relations"][0]["relation_type"] == "ally"


async def test_assemble_extracts_character_locations_from_meta(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """character_locations 从 Character.meta JSON 读 location_id, key=character_id。
    没有 location_id 的 character 不进入 dict。"""
    from modules.world.models import Character
    from modules.world.state_assembler import assemble

    loc_id = str(uuid.uuid4())
    with_loc = Character(
        entity_id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        name="有位置的人",
        meta={"location_id": loc_id, "text_state": "在城门口", "chapter_index": 3},
    )
    without_loc = Character(
        entity_id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        name="无位置的人",
        meta={},
    )
    db_session.add_all([with_loc, without_loc])
    await db_session.flush()

    state = await assemble(db_session, novel_id)

    assert len(state["character_locations"]) == 1
    only_key = next(iter(state["character_locations"]))
    entry = state["character_locations"][only_key]
    assert entry["location_id"] == loc_id
    assert entry["text_state"] == "在城门口"
    assert entry["chapter_index"] == 3


async def test_assemble_includes_character_knowledge(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    from modules.world.models import CharacterKnowledge
    from modules.world.state_assembler import assemble

    char_id = uuid.uuid4()
    knowledge = CharacterKnowledge(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        character_id=char_id,
        target_type="entity",
        target_id=uuid.uuid4(),
        knowledge_level="rumor",
        known_content="听说某处有宝藏",
    )
    db_session.add(knowledge)
    await db_session.flush()

    state = await assemble(db_session, novel_id)

    assert len(state["character_knowledge"]) == 1
    entry = state["character_knowledge"][0]
    assert entry["knowledge_level"] == "rumor"
    assert entry["known_content"] == "听说某处有宝藏"
    assert entry["character_id"] == str(char_id)


async def test_assemble_preserves_zero_importance(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """CLAUDE.md §5: 0.0 是合法 importance, 不能用 if value: 过滤掉。"""
    from modules.world.state_assembler import assemble

    zero = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="item",
        name="零重要之物",
        status="canonical",
        importance=0.0,
    )
    db_session.add(zero)
    await db_session.flush()

    state = await assemble(db_session, novel_id)

    assert len(state["entities"]) == 1
    assert state["entities"][0]["importance"] == 0.0
    assert state["entities"][0]["name"] == "零重要之物"


async def test_assemble_propagates_db_errors(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """CLAUDE.md §8: DB 异常必须向上传播, 不允许 try/except: pass。
    旧 facade.py:595-611 在 knowledge 读失败时静默返回空, 是 bug。"""
    from unittest.mock import patch

    from sqlalchemy.exc import OperationalError

    from modules.world.state_assembler import assemble

    def boom(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("connection lost"))

    with patch(
        "modules.world.repositories.CoreEntityRepository.get_by_novel",
        side_effect=boom,
    ):
        with pytest.raises(OperationalError):
            await assemble(db_session, novel_id)


async def test_assemble_returns_empty_shape_for_empty_novel(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """没有任何正史数据的 novel 应该返空 shape, 不是抛错。"""
    from modules.world.state_assembler import assemble

    state = await assemble(db_session, novel_id)

    assert state == {
        "entities": [],
        "relations": [],
        "character_locations": {},
        "character_knowledge": [],
    }


async def test_assemble_isolates_novel_id_across_all_sections(
    db_session: AsyncSession,
) -> None:
    """A novel 的正史数据不能漏到 B novel 的快照里 (CLAUDE.md §4)。"""
    from modules.world.models import (
        Character,
        CharacterKnowledge,
        CoreEntity,
        EntityRelation,
    )
    from modules.world.state_assembler import assemble

    novel_a = uuid.uuid4()
    novel_b = uuid.uuid4()
    nid_a_str = str(novel_a)
    nid_b_str = str(novel_b)

    a_char_id = uuid.uuid4()
    a_rel_src = uuid.uuid4()
    a_rel_tgt = uuid.uuid4()

    db_session.add_all(
        [
            # novel A 的正史
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_a,
                entity_type="item",
                name="A 的剑",
                status="canonical",
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_b,
                entity_type="item",
                name="B 的剑",
                status="canonical",
            ),
            EntityRelation(
                id=uuid.uuid4(),
                novel_id=novel_a,
                source_id=a_rel_src,
                target_id=a_rel_tgt,
                relation_type="ally",
                status="canonical",
            ),
            EntityRelation(
                id=uuid.uuid4(),
                novel_id=novel_b,
                source_id=uuid.uuid4(),
                target_id=uuid.uuid4(),
                relation_type="ally",
                status="canonical",
            ),
            Character(
                entity_id=a_char_id,
                novel_id=novel_a,
                name="A 主角",
                meta={"location_id": str(uuid.uuid4())},
            ),
            Character(
                entity_id=uuid.uuid4(),
                novel_id=novel_b,
                name="B 主角",
                meta={"location_id": str(uuid.uuid4())},
            ),
            CharacterKnowledge(
                id=uuid.uuid4(),
                novel_id=novel_a,
                character_id=a_char_id,
                target_type="entity",
                target_id=uuid.uuid4(),
                knowledge_level="full",
                known_content="A 知道",
            ),
            CharacterKnowledge(
                id=uuid.uuid4(),
                novel_id=novel_b,
                character_id=uuid.uuid4(),
                target_type="entity",
                target_id=uuid.uuid4(),
                knowledge_level="full",
                known_content="B 知道",
            ),
        ]
    )
    await db_session.flush()

    state_a = await assemble(db_session, nid_a_str)

    assert {e["name"] for e in state_a["entities"]} == {"A 的剑"}
    assert {r["relation_type"] for r in state_a["relations"]} == {"ally"}
    assert {k["known_content"] for k in state_a["character_knowledge"]} == {"A 知道"}
    # character_locations 严格只含 A 的 a_char_id, 不含 B 的 character
    assert len(state_a["character_locations"]) == 1
    assert str(a_char_id) in state_a["character_locations"]

    # 验证 B novel 的快照不混 A 数据
    state_b = await assemble(db_session, nid_b_str)
    assert {e["name"] for e in state_b["entities"]} == {"B 的剑"}
    assert {k["known_content"] for k in state_b["character_knowledge"]} == {"B 知道"}
    assert len(state_b["character_locations"]) == 1
    assert str(a_char_id) not in state_b["character_locations"]


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
