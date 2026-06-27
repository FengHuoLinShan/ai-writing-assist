"""
shared/enums.py 单元测试

验证所有 StrEnum 类的成员唯一性和值正确性。
"""

from shared.enums import (
    AliasType,
    CandidateAction,
    CharacterRole,
    EntityType,
    EventType,
    ExtractionMode,
    ForeshadowingStatus,
    ImportanceLevel,
    KnowledgeLevel,
    ObjectStatus,
    RelationDirection,
    RelationType,
    RevealLevel,
    TaskStatus,
    TaskType,
    Visibility,
)


def _assert_unique_values(enum_cls):
    """确保枚举成员值唯一"""
    values = [m.value for m in enum_cls]
    assert len(values) == len(set(values)), f"{enum_cls.__name__} 有重复值"


class TestEntityType:
    def test_values_unique(self):
        _assert_unique_values(EntityType)

    def test_has_character(self):
        assert EntityType.character == "character"

    def test_has_location(self):
        assert EntityType.location == "location"

    def test_member_count(self):
        assert len(EntityType) == 10


class TestObjectStatus:
    def test_values_unique(self):
        _assert_unique_values(ObjectStatus)

    def test_canonical_value(self):
        assert ObjectStatus.canonical == "canonical"

    def test_draft_value(self):
        assert ObjectStatus.draft == "draft"


class TestCandidateAction:
    def test_values_unique(self):
        _assert_unique_values(CandidateAction)

    def test_member_count(self):
        assert len(CandidateAction) == 6


class TestImportanceLevel:
    def test_values_unique(self):
        _assert_unique_values(ImportanceLevel)

    def test_has_core(self):
        assert ImportanceLevel.core == "core"


class TestKnowledgeLevel:
    def test_values_unique(self):
        _assert_unique_values(KnowledgeLevel)

    def test_has_unknown(self):
        assert KnowledgeLevel.unknown == "unknown"


class TestCharacterRole:
    def test_values_unique(self):
        _assert_unique_values(CharacterRole)

    def test_has_protagonist(self):
        assert CharacterRole.protagonist == "protagonist"


class TestVisibility:
    def test_values_unique(self):
        _assert_unique_values(Visibility)


class TestRevealLevel:
    def test_values_unique(self):
        _assert_unique_values(RevealLevel)


class TestEventType:
    def test_values_unique(self):
        _assert_unique_values(EventType)

    def test_has_plot(self):
        assert EventType.plot == "plot"


class TestRelationType:
    def test_values_unique(self):
        _assert_unique_values(RelationType)


class TestRelationDirection:
    def test_values_unique(self):
        _assert_unique_values(RelationDirection)

    def test_has_directed_and_undirected(self):
        assert RelationDirection.directed == "directed"
        assert RelationDirection.undirected == "undirected"


class TestTaskStatus:
    def test_values_unique(self):
        _assert_unique_values(TaskStatus)

    def test_has_pending_and_done(self):
        assert TaskStatus.pending == "pending"
        assert TaskStatus.done == "done"

    def test_member_count(self):
        assert len(TaskStatus) == 5


class TestTaskType:
    def test_values_unique(self):
        _assert_unique_values(TaskType)


class TestExtractionMode:
    def test_values_unique(self):
        _assert_unique_values(ExtractionMode)

    def test_has_strict_normal_full(self):
        assert ExtractionMode.strict == "strict"
        assert ExtractionMode.normal == "normal"
        assert ExtractionMode.full == "full"


class TestAliasType:
    def test_values_unique(self):
        _assert_unique_values(AliasType)


class TestForeshadowingStatus:
    def test_values_unique(self):
        _assert_unique_values(ForeshadowingStatus)

    def test_has_seeded_and_paid_off(self):
        assert ForeshadowingStatus.seeded == "seeded"
        assert ForeshadowingStatus.paid_off == "paid_off"
