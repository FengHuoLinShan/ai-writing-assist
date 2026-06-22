"""Memory Schema 校验测试 — Round 1"""

import uuid

import pytest
from pydantic import ValidationError

from modules.memory.schemas import (
    ChapterPanorama,
    CharacterLocationInPanorama,
    EntityInPanorama,
    MemoryEventResponse,
    MemoryStatusResponse,
    RelationInPanorama,
    SnapshotResponse,
)


# Shared mock ORM objects for from_attributes validation tests.


class _MockEventORM:
    id = uuid.uuid4()
    novel_id = uuid.uuid4()
    chapter_index = 3
    sequence = 2
    event_type = "entity_created"
    entity_id = id
    entity_type = "character"
    snapshot_before = None
    snapshot_after = {"name": "test"}
    source = "ai_extraction"
    created_at = None


class _MockSnapshotORM:
    id = uuid.uuid4()
    novel_id = uuid.uuid4()
    chapter_index = 10
    status = "current"
    events_until = 42
    created_at = None


class TestEntityInPanorama:
    """EntityInPanorama schema 校验"""

    def test_valid_minimal(self) -> None:
        """最简合法数据"""
        e = EntityInPanorama(id=str(uuid.uuid4()), entity_type="character", name="张三")
        assert e.name == "张三"
        assert e.importance == 0.5
        assert e.importance_level == "normal"

    def test_missing_required_fields(self) -> None:
        """缺少必填字段抛 ValidationError"""
        with pytest.raises(ValidationError):
            EntityInPanorama(id=str(uuid.uuid4()))  # 缺少 entity_type 和 name

    def test_importance_default(self) -> None:
        """importance 默认值为 0.5"""
        e = EntityInPanorama(id=str(uuid.uuid4()), entity_type="location", name="长安")
        assert e.importance == 0.5


class TestRelationInPanorama:
    """RelationInPanorama schema 校验"""

    def test_valid_minimal(self) -> None:
        """最简合法数据"""
        r = RelationInPanorama(
            id=str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relation_type="father_of",
        )
        assert r.relation_type == "father_of"
        assert r.strength == 0.5

    def test_missing_relation_type(self) -> None:
        """缺少 relation_type 抛错"""
        with pytest.raises(ValidationError):
            RelationInPanorama(
                id=str(uuid.uuid4()),
                source_id=str(uuid.uuid4()),
                target_id=str(uuid.uuid4()),
            )


class TestCharacterLocationInPanorama:
    """CharacterLocationInPanorama schema 校验"""

    def test_valid_with_defaults(self) -> None:
        """合法数据 + 默认值"""
        loc = CharacterLocationInPanorama(location_id=str(uuid.uuid4()))
        assert loc.text_state == ""
        assert loc.chapter_index is None


class TestChapterPanorama:
    """ChapterPanorama 全景响应校验"""

    def test_empty_panorama(self) -> None:
        """空全景结构正确"""
        p = ChapterPanorama(novel_id=str(uuid.uuid4()), chapter_index=1)
        assert p.entities == []
        assert p.relations == []
        assert p.character_locations == {}
        assert p.character_knowledge == []

    def test_with_entities_and_relations(self) -> None:
        """含数据全景序列化正确"""
        nid = str(uuid.uuid4())
        entity = EntityInPanorama(id=nid, entity_type="character", name="李四")
        relation = RelationInPanorama(
            id=str(uuid.uuid4()),
            source_id=nid,
            target_id=str(uuid.uuid4()),
            relation_type="friend_of",
        )
        p = ChapterPanorama(
            novel_id=nid,
            chapter_index=3,
            entities=[entity],
            relations=[relation],
        )
        assert len(p.entities) == 1
        assert len(p.relations) == 1
        assert p.entities[0].name == "李四"

    def test_character_locations_dict(self) -> None:
        """character_locations dict 序列化正确"""
        cid = str(uuid.uuid4())
        loc = CharacterLocationInPanorama(
            location_id=str(uuid.uuid4()), text_state="位于长安"
        )
        p = ChapterPanorama(
            novel_id=str(uuid.uuid4()),
            chapter_index=5,
            character_locations={cid: loc},
        )
        assert p.character_locations[cid].text_state == "位于长安"


class TestMemoryEventResponse:
    """MemoryEventResponse schema 校验"""

    def test_from_attributes(self) -> None:
        """from_attributes ORM 转换、UUID 转 str"""
        eid = uuid.uuid4()
        nid = uuid.uuid4()

        # 使用共享 mock ORM 对象
        _MockEventORM.id = eid
        _MockEventORM.novel_id = nid
        _MockEventORM.entity_id = eid

        resp = MemoryEventResponse.model_validate(_MockEventORM())
        assert resp.id == str(eid)
        assert resp.novel_id == str(nid)
        assert resp.chapter_index == 3
        assert resp.snapshot_before is None

    def test_snapshot_before_none_valid(self) -> None:
        """snapshot_before=None 合法"""
        resp = MemoryEventResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"x": 1},
            snapshot_before=None,
        )
        assert resp.snapshot_before is None


class TestSnapshotResponse:
    """SnapshotResponse schema 校验"""

    def test_from_attributes(self) -> None:
        """from_attributes 转换、UUID 转 str"""
        sid = uuid.uuid4()
        nid = uuid.uuid4()

        _MockSnapshotORM.id = sid
        _MockSnapshotORM.novel_id = nid

        resp = SnapshotResponse.model_validate(_MockSnapshotORM())
        assert resp.id == str(sid)
        assert resp.novel_id == str(nid)
        assert resp.chapter_index == 10
        assert resp.status == "current"
        assert resp.events_until == 42


class TestMemoryStatusResponse:
    """MemoryStatusResponse 状态响应校验"""

    def test_empty_first_use(self) -> None:
        """空状态（首次使用）"""
        s = MemoryStatusResponse(novel_id=str(uuid.uuid4()))
        assert s.latest_chapter is None
        assert s.latest_snapshot_chapter is None
        assert s.has_stale is False
        assert s.stale_from_chapter is None

    def test_with_snapshots(self) -> None:
        """有快照状态"""
        s = MemoryStatusResponse(
            novel_id=str(uuid.uuid4()),
            latest_chapter=10,
            latest_snapshot_chapter=10,
            has_stale=False,
        )
        assert s.latest_chapter == 10

    def test_with_stale(self) -> None:
        """有 stale 状态"""
        s = MemoryStatusResponse(
            novel_id=str(uuid.uuid4()),
            latest_chapter=15,
            latest_snapshot_chapter=10,
            has_stale=True,
            stale_from_chapter=5,
        )
        assert s.has_stale is True
        assert s.stale_from_chapter == 5
