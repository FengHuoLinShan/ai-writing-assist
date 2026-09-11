"""
shared/enums.py 单元测试

验证所有 StrEnum 类的成员唯一性和值正确性。
"""

from shared.enums import (
    CandidateAction,
    RelationType,
    TaskStatus,
)


def _assert_unique_values(enum_cls):
    """确保枚举成员值唯一"""
    values = [m.value for m in enum_cls]
    assert len(values) == len(set(values)), f"{enum_cls.__name__} 有重复值"


class TestCandidateAction:
    def test_values_unique(self):
        _assert_unique_values(CandidateAction)

    def test_member_count(self):
        assert len(CandidateAction) == 6


class TestRelationType:
    def test_values_unique(self):
        _assert_unique_values(RelationType)


class TestTaskStatus:
    def test_values_unique(self):
        _assert_unique_values(TaskStatus)

    def test_has_pending_and_done(self):
        assert TaskStatus.pending == "pending"
        assert TaskStatus.done == "done"

    def test_member_count(self):
        assert len(TaskStatus) == 5
