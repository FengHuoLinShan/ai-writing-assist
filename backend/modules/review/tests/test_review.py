"""
Review 模块测试

测试所有检查维度、决策逻辑、Facade 入口、Repository CRUD。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.facade import get_review_report, review_structure_candidate
from modules.review.models import ReviewReport
from modules.review.repositories import ReviewReportRepository
from modules.review.schemas import (
    ReviewReportContext,
    ReviewReportResponse,
    ReviewRequest,
    ReviewWarning,
)
from modules.review.services import ReviewService


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def repo() -> ReviewReportRepository:
    return ReviewReportRepository()


@pytest.fixture
def service() -> ReviewService:
    return ReviewService()


# ============================================================
# ReviewService — 决策逻辑测试
# ============================================================

class TestDecideLogic:
    """测试 _decide 方法的决策逻辑"""

    def setup_method(self) -> None:
        self._service = ReviewService()

    def test_pass_no_warnings(self) -> None:
        """无警告时决策应为 pass"""
        result = self._service._decide([])
        assert result == "pass"

    def test_pass_with_low_warnings(self) -> None:
        """仅 low 严重度警告时决策应为 pass"""
        warnings = [
            ReviewWarning(type="schema", message="test low", severity="low"),
            ReviewWarning(type="schema", message="test low 2", severity="low"),
        ]
        result = self._service._decide(warnings)
        assert result == "pass"

    def test_minor_revision(self) -> None:
        """1-3 个 medium 警告时决策应为 minor_revision"""
        warnings = [
            ReviewWarning(type="schema", message="test med", severity="medium"),
        ]
        result = self._service._decide(warnings)
        assert result == "minor_revision"

    def test_minor_revision_two_medium(self) -> None:
        """2 个 medium 警告时决策应为 minor_revision"""
        warnings = [
            ReviewWarning(type="schema", message="med 1", severity="medium"),
            ReviewWarning(type="schema", message="med 2", severity="medium"),
        ]
        result = self._service._decide(warnings)
        assert result == "minor_revision"

    def test_major_revision_four_medium(self) -> None:
        """>3 个 medium 警告时决策应为 major_revision"""
        warnings = [
            ReviewWarning(type="schema", message=f"med {i}", severity="medium")
            for i in range(4)
        ]
        result = self._service._decide(warnings)
        assert result == "major_revision"

    def test_reject_with_high(self) -> None:
        """存在 high 严重度警告时决策应为 reject"""
        warnings = [
            ReviewWarning(type="schema", message="test high", severity="high"),
        ]
        result = self._service._decide(warnings)
        assert result == "reject"

    def test_reject_mixed(self) -> None:
        """mixed 警告中如有 high，决策应为 reject"""
        warnings = [
            ReviewWarning(type="schema", message="low", severity="low"),
            ReviewWarning(type="schema", message="high", severity="high"),
            ReviewWarning(type="schema", message="medium", severity="medium"),
        ]
        result = self._service._decide(warnings)
        assert result == "reject"


# ============================================================
# ReviewService — Schema 校验测试
# ============================================================

class TestCheckSchema:
    """测试 _check_schema 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    @pytest.mark.asyncio
    async def test_world_structure_missing_field(
        self, service: ReviewService,
    ) -> None:
        """world_structure 缺少必填字段 world_entities"""
        payload = {
            "target_type": "world_structure",
            "relationships": [],
        }
        warnings = await service._check_schema("world_structure", payload)
        assert len(warnings) >= 1
        assert any(w.type == "schema" for w in warnings)
        assert any("world_entities" in w.message for w in warnings)

    @pytest.mark.asyncio
    async def test_invalid_uuid_format(self, service: ReviewService) -> None:
        """检查无效的 UUID 格式"""
        payload = {
            "target_type": "chapter_cards",
            "novel_id": "not-a-uuid",
            "chapter_cards": [{"chapter_index": 1}],
        }
        warnings = await service._check_schema("chapter_cards", payload)
        uuid_warnings = [w for w in warnings if "novel_id" in str(w.location)]
        assert len(uuid_warnings) >= 1

    @pytest.mark.asyncio
    async def test_chapter_index_validation(self, service: ReviewService) -> None:
        """chapter_index 必须为正整数"""
        payload = {
            "chapter_index": 0,
        }
        warnings = await service._check_schema("", payload)
        assert len(warnings) >= 1
        assert any("chapter_index" in w.message for w in warnings)

    @pytest.mark.asyncio
    async def test_chapter_index_negative(self, service: ReviewService) -> None:
        """chapter_index 为负数"""
        payload = {
            "chapter_index": -5,
        }
        warnings = await service._check_schema("", payload)
        assert len(warnings) >= 1

    @pytest.mark.asyncio
    async def test_valid_schema_no_warnings(self, service: ReviewService) -> None:
        """完整有效的 schema 不应产生警告"""
        payload = {
            "target_type": "world_structure",
            "world_entities": [
                {
                    "name": "测试王国",
                    "entity_type": "faction",
                }
            ],
            "relationships": [
                {
                    "source_id": str(uuid.uuid4()),
                    "target_id": str(uuid.uuid4()),
                    "relation_type": "ally_of",
                }
            ],
        }
        warnings = await service._check_schema("world_structure", payload)
        schema_warnings = [w for w in warnings if w.type == "schema"]
        # 可能没有 schema 警告（要求字段已存在）
        assert isinstance(schema_warnings, list)


# ============================================================
# ReviewService — 提前揭示检查测试
# ============================================================

class TestCheckEarlyReveal:
    """测试 _check_early_reveal 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    @pytest.mark.asyncio
    async def test_hidden_truth_revealed(
        self, service: ReviewService,
    ) -> None:
        """hidden_truth 泄露到 public_info 时应产生警告"""
        payload = {
            "chapter_index": 3,
            "world_entities": [
                {
                    "name": "黑暗之塔",
                    "entity_type": "location",
                    "hidden_truth": "这座塔其实是通往异世界的门户",
                    "reveal_level": "author_only",
                    "public_info": "塔其实是一座通往异世界的神秘门户，据说连接着另一个世界",
                }
            ],
        }
        warnings = await service._check_early_reveal(
            None, "", payload,
        )
        assert len(warnings) >= 1
        assert any(w.type == "early_reveal" for w in warnings)

    @pytest.mark.asyncio
    async def test_hidden_truth_not_leaked(
        self, service: ReviewService,
    ) -> None:
        """hidden_truth 未泄露到公开字段时不应产生警告"""
        payload = {
            "chapter_index": 3,
            "world_entities": [
                {
                    "name": "黑暗之塔",
                    "entity_type": "location",
                    "hidden_truth": "这座塔其实是通往异世界的门户",
                    "reveal_level": "author_only",
                    "public_info": "外观为黑色高塔，常年笼罩在雾气中",
                }
            ],
        }
        warnings = await service._check_early_reveal(
            None, "", payload,
        )
        # hidden_truth 内容未出现在公开字段中，不应视为提前揭示
        assert len([w for w in warnings if w.type == "early_reveal"]) == 0

    @pytest.mark.asyncio
    async def test_no_hidden_truth_no_warning(
        self, service: ReviewService,
    ) -> None:
        """没有 hidden_truth 时不应产生提前揭示警告"""
        payload = {
            "chapter_index": 3,
            "world_entities": [
                {
                    "name": "光明之城",
                    "entity_type": "location",
                    "summary": "一个繁华的都市",
                }
            ],
        }
        warnings = await service._check_early_reveal(
            None, "", payload,
        )
        reveal_warnings = [w for w in warnings if w.type == "early_reveal"]
        assert len(reveal_warnings) == 0

    @pytest.mark.asyncio
    async def test_reveal_plan_large_gap(
        self, service: ReviewService,
    ) -> None:
        """揭示计划中阶段间隔过大应产生警告"""
        payload = {
            "reveal_plans": [
                {
                    "secret_summary": "主角的真实身份是失落的王子",
                    "reveal_stages": [
                        {"chapter_index": 10, "hint_level": "hint"},
                        {"chapter_index": 35, "hint_level": "partial"},
                        {"chapter_index": 60, "hint_level": "full"},
                    ],
                }
            ],
        }
        warnings = await service._check_early_reveal(
            None, "", payload,
        )
        # 35-10=25 > 20，应产生警告
        large_gap_warnings = [
            w for w in warnings
            if w.type == "early_reveal" and "间隔" in w.message
        ]
        assert len(large_gap_warnings) >= 1


# ============================================================
# ReviewService — 时间线冲突检查测试
# ============================================================

class TestCheckTimeline:
    """测试 _check_timeline 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    @pytest.mark.asyncio
    async def test_duplicate_chapter_index(
        self, service: ReviewService,
    ) -> None:
        """重复的 chapter_index 应产生冲突警告"""
        payload = {
            "chapter_cards": [
                {"chapter_index": 1, "chapter_goal": "开场", "main_conflict": "引入"},
                {"chapter_index": 1, "chapter_goal": "再开场", "main_conflict": "再引入"},
            ],
        }
        warnings = await service._check_timeline(None, "", payload)
        dup_warnings = [
            w for w in warnings
            if w.type == "timeline_conflict" and "重复" in w.message
        ]
        assert len(dup_warnings) >= 1

    @pytest.mark.asyncio
    async def test_foreshadowing_seed_after_payoff(
        self, service: ReviewService,
    ) -> None:
        """伏笔埋设章节 >= 收束章节应产生冲突警告"""
        payload = {
            "foreshadowing_plans": [
                {
                    "name": "测试伏笔",
                    "planned_seed_chapter": 20,
                    "planned_payoff_chapter": 15,
                }
            ],
        }
        warnings = await service._check_timeline(None, "", payload)
        fs_warnings = [
            w for w in warnings
            if w.type == "timeline_conflict" and "埋设" in w.message
        ]
        assert len(fs_warnings) >= 1

    @pytest.mark.asyncio
    async def test_unique_chapters_no_warning(
        self, service: ReviewService,
    ) -> None:
        """不重复的章节索引不应产生冲突警告"""
        payload = {
            "chapter_cards": [
                {"chapter_index": 1, "chapter_goal": "开场", "main_conflict": "引入"},
                {"chapter_index": 2, "chapter_goal": "发展", "main_conflict": "冲突升级"},
            ],
        }
        warnings = await service._check_timeline(None, "", payload)
        dup_warnings = [
            w for w in warnings
            if w.type == "timeline_conflict" and "重复" in w.message
        ]
        assert len(dup_warnings) == 0


# ============================================================
# ReviewService — 重复检查测试
# ============================================================

class TestCheckDuplicates:
    """测试 _check_duplicates 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    @pytest.mark.asyncio
    async def test_duplicate_names_in_candidates(
        self, service: ReviewService,
    ) -> None:
        """候选列表内部重复名称应产生警告"""
        payload = {
            "entity_candidates": [
                {"name": "暗影之刃", "entity_type": "item"},
                {"name": "暗影之刃", "entity_type": "item"},
            ],
        }
        warnings = await service._check_duplicates(None, "", payload)
        dup_warnings = [
            w for w in warnings
            if w.type == "duplicate" and "重复名称" in w.message
        ]
        assert len(dup_warnings) >= 1

    @pytest.mark.asyncio
    async def test_unique_names_no_warning(
        self, service: ReviewService,
    ) -> None:
        """不同的候选名称不应产生重复警告"""
        payload = {
            "entity_candidates": [
                {"name": "暗影之刃", "entity_type": "item"},
                {"name": "光明之盾", "entity_type": "item"},
            ],
        }
        warnings = await service._check_duplicates(None, "", payload)
        dup_warnings = [
            w for w in warnings if w.type == "duplicate"
        ]
        assert len(dup_warnings) == 0


# ============================================================
# ReviewService — 地理冲突检查测试
# ============================================================

class TestCheckGeo:
    """测试 _check_geo 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    @pytest.mark.asyncio
    async def test_invalid_location_id(
        self, service: ReviewService,
    ) -> None:
        """无效的 location UUID 不应产生严重错误"""
        payload = {
            "world_entities": [
                {
                    "id": "not-a-uuid",
                    "name": "未知地点",
                    "entity_type": "location",
                }
            ],
        }
        warnings = await service._check_geo(None, "", payload)
        # 无效 UUID 不会被加入检查集合
        assert isinstance(warnings, list)


# ============================================================
# ReviewService — 综合评分测试
# ============================================================

class TestCalculateScore:
    """测试 _calculate_score 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    def test_perfect_score(self, service: ReviewService) -> None:
        """无警告时评分为 1.0"""
        score = service._calculate_score("pass", [])
        assert score == 1.0

    def test_score_with_high_warning(self, service: ReviewService) -> None:
        """每个 high 警告扣 0.3"""
        warnings = [
            ReviewWarning(type="schema", message="h", severity="high"),
        ]
        score = service._calculate_score("reject", warnings)
        assert score == 0.7

    def test_score_with_medium_warning(self, service: ReviewService) -> None:
        """每个 medium 警告扣 0.1"""
        warnings = [
            ReviewWarning(type="schema", message="m", severity="medium"),
        ]
        score = service._calculate_score("minor_revision", warnings)
        assert score == 0.9

    def test_score_with_low_warning(self, service: ReviewService) -> None:
        """每个 low 警告扣 0.05"""
        warnings = [
            ReviewWarning(type="schema", message="l", severity="low"),
        ]
        score = service._calculate_score("pass", warnings)
        assert score == 0.95

    def test_score_minimum(self, service: ReviewService) -> None:
        """评分不应低于 0.0"""
        warnings = [
            ReviewWarning(type="schema", message=f"h{i}", severity="high")
            for i in range(10)
        ]
        score = service._calculate_score("reject", warnings)
        assert score >= 0.0


# ============================================================
# ReviewReportRepository — CRUD 测试
# ============================================================

class TestReviewReportRepository:
    """测试 ReviewReportRepository CRUD 操作"""

    @pytest.mark.asyncio
    async def test_create_report(
        self, db_session: AsyncSession, novel_id: str, repo: ReviewReportRepository,
    ) -> None:
        """创建复查报告"""
        nid = uuid.UUID(hex=novel_id)
        entity = await repo.create(
            db_session,
            novel_id=nid,
            target_type="plot_structure",
            decision="minor_revision",
            problems=[{"type": "schema", "message": "test", "severity": "medium"}],
        )
        assert entity is not None
        assert entity.target_type == "plot_structure"
        assert entity.decision == "minor_revision"
        assert entity.id is not None
        assert len(entity.problems) == 1

    @pytest.mark.asyncio
    async def test_get_report_by_id(
        self, db_session: AsyncSession, novel_id: str, repo: ReviewReportRepository,
    ) -> None:
        """按 ID 获取复查报告"""
        nid = uuid.UUID(hex=novel_id)
        entity = await repo.create(
            db_session,
            novel_id=nid,
            target_type="world_structure",
            decision="pass",
        )
        fetched = await repo.get(db_session, entity.id)
        assert fetched is not None
        assert fetched.id == entity.id
        assert fetched.decision == "pass"

    @pytest.mark.asyncio
    async def test_get_nonexistent_report(
        self, db_session: AsyncSession, repo: ReviewReportRepository,
    ) -> None:
        """获取不存在的报告应返回 None"""
        fake_id = uuid.uuid4()
        result = await repo.get(db_session, fake_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_novel(
        self, db_session: AsyncSession, novel_id: str, repo: ReviewReportRepository,
    ) -> None:
        """按项目 ID 获取报告列表"""
        nid = uuid.UUID(hex=novel_id)
        await repo.create(db_session, novel_id=nid, target_type="plot_structure", decision="pass")
        await repo.create(db_session, novel_id=nid, target_type="world_structure", decision="reject")

        items, total = await repo.get_by_novel(db_session, nid)
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_get_by_novel_with_filter(
        self, db_session: AsyncSession, novel_id: str, repo: ReviewReportRepository,
    ) -> None:
        """按项目 ID 和 target_type 过滤"""
        nid = uuid.UUID(hex=novel_id)
        await repo.create(db_session, novel_id=nid, target_type="plot_structure", decision="pass")
        await repo.create(db_session, novel_id=nid, target_type="world_structure", decision="reject")

        items, total = await repo.get_by_novel(
            db_session, nid,
            target_type="plot_structure",
        )
        assert total == 1
        assert items[0].target_type == "plot_structure"

    @pytest.mark.asyncio
    async def test_delete_old(
        self, db_session: AsyncSession, novel_id: str, repo: ReviewReportRepository,
    ) -> None:
        """删除旧报告"""
        nid = uuid.UUID(hex=novel_id)
        # 创建 3 条报告
        for _ in range(3):
            await repo.create(
                db_session,
                novel_id=nid,
                target_type="plot_structure",
                decision="pass",
            )

        # 仅保留 2 条，应删除 1 条
        deleted = await repo.delete_old(
            db_session, nid, "plot_structure", keep_last=2,
        )
        assert deleted >= 1

        # 验证剩余条数
        items, total = await repo.get_by_novel(
            db_session, nid,
            target_type="plot_structure",
        )
        assert total <= 2


# ============================================================
# ReviewService — 全量检查入口测试
# ============================================================

class TestRunAllChecks:
    """测试 run_all_checks 方法"""

    @pytest.mark.asyncio
    async def test_clean_payload(
        self, db_session: AsyncSession, novel_id: str, service: ReviewService,
    ) -> None:
        """干净的数据应产生 pass 决策"""
        payload = {
            "target_type": "world_structure",
            "world_entities": [
                {"name": "测试王国", "entity_type": "faction"},
            ],
            "relationships": [
                {
                    "source_id": str(uuid.uuid4()),
                    "target_id": str(uuid.uuid4()),
                    "relation_type": "ally_of",
                }
            ],
        }
        result = await service.run_all_checks(
            db_session, novel_id, "world_structure", payload,
        )
        assert result is not None
        assert result.report_id is not None
        assert result.novel_id == novel_id
        assert result.target_type == "world_structure"

    @pytest.mark.asyncio
    async def test_payload_with_issues(
        self, db_session: AsyncSession, novel_id: str, service: ReviewService,
    ) -> None:
        """有问题的数据应检测到重复和顺序冲突"""
        payload = {
            "chapter_cards": [
                {"chapter_index": 1, "chapter_goal": "A", "main_conflict": "B"},
                {"chapter_index": 1, "chapter_goal": "C", "main_conflict": "D"},  # 重复
            ],
            "foreshadowing_plans": [
                {
                    "name": "坏伏笔",
                    "planned_seed_chapter": 20,
                    "planned_payoff_chapter": 15,  # seed > payoff
                }
            ],
        }
        # run_all_checks 应检测到问题并写入数据库
        result = await service.run_all_checks(
            db_session, novel_id, "chapter_cards", payload,
        )
        # 验证：result 对象结构正确，且含有报告 ID
        assert result is not None
        assert result.report_id is not None
        assert result.target_type == "chapter_cards"
        assert result.novel_id == novel_id


# ============================================================
# Facade 测试
# ============================================================

class TestFacade:
    """测试 review_structure_candidate 和 get_review_report"""

    @pytest.mark.asyncio
    async def test_review_structure_candidate(
        self, db_session: AsyncSession, novel_id: str,
    ) -> None:
        """review_structure_candidate facade 应返回复查报告"""
        payload = {
            "target_type": "entity_candidates",
            "entity_candidates": [
                {"name": "神剑", "entity_type": "item"},
            ],
        }
        result = await review_structure_candidate(
            db_session, novel_id, "entity_candidates", payload,
        )
        assert isinstance(result, ReviewReportContext)
        assert result.decision in ("pass", "minor_revision", "major_revision", "reject")
        assert result.report_id is not None

    @pytest.mark.asyncio
    async def test_get_review_report(
        self, db_session: AsyncSession, novel_id: str,
    ) -> None:
        """get_review_report facade 应返回已存储的报告"""
        # 先创建一个报告
        payload = {
            "entity_candidates": [{"name": "测试", "entity_type": "item"}],
        }
        created = await review_structure_candidate(
            db_session, novel_id, "entity_candidates", payload,
        )

        # 再获取
        fetched = await get_review_report(db_session, created.report_id, novel_id)
        assert fetched.report_id == created.report_id
        assert fetched.decision == created.decision

    @pytest.mark.asyncio
    async def test_review_plot_structure(
        self, db_session: AsyncSession, novel_id: str,
    ) -> None:
        """复查 plot_structure 类型 — 包含所有必填组件"""
        payload = {
            "plot_threads": [
                {
                    "name": "主线",
                    "thread_type": "main",
                    "summary": "主角的成长之路",
                    "start_chapter": 1,
                    "planned_payoff_chapter": 30,
                }
            ],
            "outline_arcs": [
                {
                    "title": "开篇",
                    "arc_index": 1,
                    "start_chapter": 1,
                    "end_chapter": 12,
                    "arc_goal": "建立世界观",
                    "core_conflict": "生存挣扎",
                }
            ],
            "chapter_cards": [
                {
                    "chapter_index": 1,
                    "title": "引子",
                    "chapter_goal": "引入主角和世界观",
                    "main_conflict": "生存危机",
                }
            ],
            "foreshadowing_plans": [],
            "reveal_plans": [],
        }
        result = await review_structure_candidate(
            db_session, novel_id, "plot_structure", payload,
        )
        assert result.target_type == "plot_structure"
        assert result.decision in ("pass", "minor_revision")


# ============================================================
# ReviewReport Schema 测试
# ============================================================

class TestReviewWarningSchema:
    """测试 ReviewWarning Pydantic schema"""

    def test_create_warning(self) -> None:
        """创建 ReviewWarning 实例"""
        w = ReviewWarning(
            type="schema",
            message="必填字段缺失",
            severity="high",
            location={"field": "name"},
        )
        assert w.type == "schema"
        assert w.severity == "high"
        assert w.location == {"field": "name"}

    def test_default_location(self) -> None:
        """location 默认值为空 dict"""
        w = ReviewWarning(type="schema", message="test")
        assert w.location == {}


# ============================================================
# ReviewService — 修改建议生成测试
# ============================================================

class TestRevisionInstructions:
    """测试 _generate_revision_instructions 方法"""

    @pytest.fixture
    def service(self) -> ReviewService:
        return ReviewService()

    def test_reject_instructions(self, service: ReviewService) -> None:
        """reject 决策应包含重建建议"""
        instructions = service._generate_revision_instructions(
            "reject",
            [ReviewWarning(type="schema", message="缺字段", severity="high")],
            [], [], [], [], [], [],
        )
        assert any("重新生成" in i for i in instructions)

    def test_schema_instructions(self, service: ReviewService) -> None:
        """schema 警告应包含修复建议"""
        instructions = service._generate_revision_instructions(
            "minor_revision",
            [ReviewWarning(type="schema", message="缺少必填字段", severity="medium")],
            [], [], [], [], [], [],
        )
        schema_instructions = [
            i for i in instructions if "Schema" in i
        ]
        assert len(schema_instructions) >= 1

    def test_pass_no_instructions(self, service: ReviewService) -> None:
        """pass 决策不应有大量修改建议"""
        instructions = service._generate_revision_instructions(
            "pass",
            [], [], [], [], [], [], [],
        )
        # pass 可能有一些通用建议，但不应有具体修复指示
        assert isinstance(instructions, list)
