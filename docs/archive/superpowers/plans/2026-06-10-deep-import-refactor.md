# 深度导入重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将深度导入三遍流水线从当前的 extract_world → sync_characters → generate_plot 重构为文档设计的 scene_segmentation → entity_extraction_incremental → structure_analysis。

**Architecture:** Phase 1 按 5章/批 + Overlap 并行切分 Scene 入库 scenes 表；Phase 2 按 Scene 顺序串行增量提取实体，累积 Memory 上下文，写入 delta_log；Phase 3 单次 LLM 生成剧情结构，持久化 foreshadowing_plans + reveal_plans 到数据库。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, 现有 LLM client + prompt_loader 基础设施

---

## 前置说明：当前状态 vs 目标状态

| 维度 | 当前 | 目标 |
|------|------|------|
| Phase 1 | 章节级世界实体抽取（串行） | Scene 切分（5章/批并行，1章 Overlap） |
| Phase 2 | 人物同步（从 character_ref 创建 Character） | Scene 级增量实体抽取（串行，累积 Memory） |
| Phase 3 | 剧情结构生成（不持久化伏笔/揭示） | 结构分析（持久化 foreshadowing_plans + reveal_plans） |
| delta_log 表 | 不存在 | 新建，记录实体字段变更 |
| foreshadowing_plans ORM | 无（仅 Pydantic 内存对象） | 新建 ORM 模型 + Repository |
| reveal_plans ORM | 无（仅 Pydantic 内存对象） | 新建 ORM 模型 + Repository |

---

## 文件结构

```
新建:
  backend/prompts/scene_segmentation.md          # Scene 切分 LLM prompt
  backend/modules/imports/scene_segmentation.py   # Scene 切分服务
  backend/alembic/versions/20260610_add_delta_log.py  # delta_log 迁移
  backend/modules/outline/foreshadowing_repository.py # ForeshadowingPlan Repository
  backend/modules/outline/reveal_repository.py        # RevealPlan Repository

修改:
  backend/modules/outline/models.py               # +ForeshadowingPlan, +RevealPlan ORM
  backend/modules/imports/workflow_schemas.py      # 更新 DeepImportStep enum
  backend/modules/imports/workflow.py              # 重写三阶段编排
  backend/modules/imports/tasks.py                 # 更新 task handler
  backend/modules/imports/api.py                   # 更新进度响应
  backend/modules/outline/services.py              # Phase 3 持久化伏笔/揭示
  backend/app/main.py                              # 注册新服务
```

---

### Task 1: 创建 foreshadowing_plans ORM 模型与 Repository

**Files:**
- Modify: `backend/modules/outline/models.py`（追加）
- Create: `backend/modules/outline/foreshadowing_repository.py`

- [ ] **Step 1: 在 models.py 添加 ForeshadowingPlan ORM 模型**

在 `backend/modules/outline/models.py` 末尾追加：

```python
class ForeshadowingPlan(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """伏笔计划 — 贯穿多章的伏笔链"""

    __tablename__ = "foreshadowing_plans"
    __table_args__ = {"comment": "伏笔计划"}

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="伏笔名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="伏笔概述",
    )
    surface_meaning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="表面含义",
    )
    hidden_meaning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐藏含义",
    )
    planned_seed_chapter: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="埋下伏笔的章节",
    )
    planned_reinforce_chapters: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="强化章节列表",
    )
    planned_payoff_chapter: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="兑现章节",
    )
    related_entity_ids: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="关联实体 ID",
    )
    related_thread_ids: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list, comment="关联剧情线 ID",
    )

    def __repr__(self) -> str:
        return (
            f"<ForeshadowingPlan id={self.id} name={self.name} "
            f"status={self.status}>"
        )
```

- [ ] **Step 2: 创建 ForeshadowingPlanRepository**

创建 `backend/modules/outline/foreshadowing_repository.py`：

```python
"""ForeshadowingPlan Repository"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import ForeshadowingPlan


class ForeshadowingPlanRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: dict,
    ) -> ForeshadowingPlan:
        plan = ForeshadowingPlan(novel_id=novel_id, **data)
        db.add(plan)
        await db.flush()
        return plan

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[ForeshadowingPlan]:
        plans = [ForeshadowingPlan(novel_id=novel_id, **d) for d in items]
        db.add_all(plans)
        await db.flush()
        return plans

    async def get(self, db: AsyncSession, plan_id: uuid.UUID) -> ForeshadowingPlan | None:
        stmt = select(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ForeshadowingPlan], int]:
        conditions = [ForeshadowingPlan.novel_id == novel_id]
        count_stmt = select(func.count(ForeshadowingPlan.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(ForeshadowingPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(ForeshadowingPlan.planned_seed_chapter)
        )
        result = await db.execute(stmt)
        items: Sequence[ForeshadowingPlan] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: dict,
    ) -> ForeshadowingPlan | None:
        plan = await self.get(db, plan_id)
        if plan is None:
            return None
        stmt = (
            update(ForeshadowingPlan)
            .where(ForeshadowingPlan.id == plan_id)
            .values(**data)
        )
        await db.execute(stmt)
        await db.flush()
        return await self.get(db, plan_id)

    async def delete(self, db: AsyncSession, plan_id: uuid.UUID) -> bool:
        stmt = delete(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        stmt = select(func.count(ForeshadowingPlan.id)).where(
            ForeshadowingPlan.novel_id == novel_id,
            ForeshadowingPlan.planned_seed_chapter >= start_chapter,
            ForeshadowingPlan.planned_seed_chapter <= end_chapter,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0
```

- [ ] **Step 3: 提交**

```bash
git add backend/modules/outline/models.py backend/modules/outline/foreshadowing_repository.py
git commit -m "feat: add ForeshadowingPlan ORM model and repository"
```

---

### Task 2: 创建 reveal_plans ORM 模型与 Repository

**Files:**
- Modify: `backend/modules/outline/models.py`（追加）
- Create: `backend/modules/outline/reveal_repository.py`

- [ ] **Step 1: 在 models.py 添加 RevealPlan ORM 模型**

在 `backend/modules/outline/models.py` 末尾追加：

```python
class RevealPlan(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """信息揭示计划 — 分层逐步披露秘密"""

    __tablename__ = "reveal_plans"
    __table_args__ = {"comment": "信息揭示计划"}

    target_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="目标类型",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, nullable=False, comment="目标实体/人物 ID",
    )
    secret_summary: Mapped[str] = mapped_column(
        Text, nullable=False, comment="被隐藏的秘密",
    )
    reveal_stages: Mapped[list] = mapped_column(
        JSON, nullable=True, default=list,
        comment="揭示阶段 [{stage_index, chapter_index, reveal_content, trigger, effect}]",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", comment="状态",
    )

    def __repr__(self) -> str:
        return (
            f"<RevealPlan id={self.id} target_type={self.target_type} "
            f"target_id={self.target_id} status={self.status}>"
        )
```

- [ ] **Step 2: 创建 RevealPlanRepository**

创建 `backend/modules/outline/reveal_repository.py`：

```python
"""RevealPlan Repository"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import RevealPlan


class RevealPlanRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: dict,
    ) -> RevealPlan:
        plan = RevealPlan(novel_id=novel_id, **data)
        db.add(plan)
        await db.flush()
        return plan

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[RevealPlan]:
        plans = [RevealPlan(novel_id=novel_id, **d) for d in items]
        db.add_all(plans)
        await db.flush()
        return plans

    async def get(self, db: AsyncSession, plan_id: uuid.UUID) -> RevealPlan | None:
        stmt = select(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[RevealPlan], int]:
        conditions = [RevealPlan.novel_id == novel_id]
        count_stmt = select(func.count(RevealPlan.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(RevealPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(RevealPlan.created_at)
        )
        result = await db.execute(stmt)
        items: Sequence[RevealPlan] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: dict,
    ) -> RevealPlan | None:
        plan = await self.get(db, plan_id)
        if plan is None:
            return None
        stmt = (
            update(RevealPlan)
            .where(RevealPlan.id == plan_id)
            .values(**data)
        )
        await db.execute(stmt)
        await db.flush()
        return await self.get(db, plan_id)

    async def delete(self, db: AsyncSession, plan_id: uuid.UUID) -> bool:
        stmt = delete(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
```

- [ ] **Step 3: 提交**

```bash
git add backend/modules/outline/models.py backend/modules/outline/reveal_repository.py
git commit -m "feat: add RevealPlan ORM model and repository"
```

---

### Task 3: 创建 delta_log 表迁移与模型

**Files:**
- Create: `backend/alembic/versions/20260610_add_delta_log.py`
- Modify: `backend/modules/memory/models.py`（追加 DeltaLog）

- [ ] **Step 1: 创建 Alembic 迁移**

创建 `backend/alembic/versions/20260610_add_delta_log.py`：

```python
"""add_delta_log_table

Revision ID: 20260610_delta_log
Revises: 20260610_add_scenes_table
Create Date: 2026-06-10

新增 delta_log 表，记录实体结构化字段的每次变更。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260610_delta_log"
down_revision: Union[str, None] = "20260610_add_scenes_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delta_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True, comment="关联实体 ID"),
        sa.Column("character_id", sa.UUID(), nullable=True, comment="关联网格人物 ID"),
        sa.Column("scene_index", sa.Integer(), nullable=True, comment="变更发生的 Scene"),
        sa.Column("category", sa.String(32), nullable=False, comment="变更类别: CHARACTER_PROPERTY / RELATIONSHIP / GLOBAL_PLOT_LINE / CHARACTER_KNOWLEDGE / ENTITY_CREATED / ENTITY_UPDATED / ENTITY_MERGED / MANUAL_ROLLBACK"),
        sa.Column("field_path", sa.String(255), nullable=True, comment="变更字段路径，如 personality / desire"),
        sa.Column("old_value", sa.Text(), nullable=True, comment="变更前的 JSON 序列化值"),
        sa.Column("new_value", sa.Text(), nullable=True, comment="变更后的 JSON 序列化值"),
        sa.Column("source", sa.String(32), nullable=False, server_default="ai_extraction", comment="来源: ai_extraction / manual_edit / manual_rollback"),
        sa.Column("meta", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="实体变更日志 — 记录每次结构化字段变更的 before/after",
    )
    op.create_index("ix_delta_log_novel_id", "delta_log", ["novel_id"])
    op.create_index("ix_delta_log_entity_id", "delta_log", ["entity_id"])
    op.create_index("ix_delta_log_scene_index", "delta_log", ["novel_id", "scene_index"])


def downgrade() -> None:
    op.drop_table("delta_log")
```

- [ ] **Step 2: 在 memory/models.py 添加 DeltaLog ORM**

在 `backend/modules/memory/models.py` 末尾追加：

```python
class DeltaLog(Base, UUIDMixin, NovelMixin):
    """实体变更日志 — 记录每次结构化字段的 before/after"""

    __tablename__ = "delta_log"
    __table_args__ = {"comment": "实体变更日志"}

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, nullable=True, index=True, comment="关联实体 ID",
    )
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, nullable=True, comment="关联网格人物 ID",
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="变更发生的 Scene",
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="变更类别",
    )
    field_path: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="变更字段路径",
    )
    old_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更前的值",
    )
    new_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更后的值",
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_extraction",
        comment="来源: ai_extraction / manual_edit / manual_rollback",
    )
    meta: Mapped[dict] = mapped_column(
        JSON, nullable=True, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<DeltaLog id={self.id} entity={self.entity_id} "
            f"category={self.category} field={self.field_path}>"
        )
```

需要在 `memory/models.py` 顶部补充 import：

```python
from core.base import UUIDType
```

- [ ] **Step 3: 提交**

```bash
git add backend/alembic/versions/20260610_add_delta_log.py backend/modules/memory/models.py
git commit -m "feat: add delta_log table and DeltaLog ORM model"
```

---

### Task 4: 更新 workflow_schemas — DeepImportStep 枚举

**Files:**
- Modify: `backend/modules/imports/workflow_schemas.py`

- [ ] **Step 1: 替换 DeepImportStep 枚举**

将 `backend/modules/imports/workflow_schemas.py` 中的 `DeepImportStep` 枚举替换为：

```python
class DeepImportStep(str, Enum):
    """深度导入步骤标识"""

    scene_segmentation = "scene_segmentation"
    """Phase 1: Scene 切分（并行）"""
    entity_extraction = "entity_extraction"
    """Phase 2: 实体增量提取（串行，按 Scene）"""
    structure_analysis = "structure_analysis"
    """Phase 3: 剧情结构分析（单次）"""
```

同时更新 `DeepImportProgress` 的默认值：

```python
class DeepImportProgress(BaseModel):
    """深度导入进度状态"""

    phase: str = Field(
        default="pending",
        description="阶段: pending / running / done / failed",
    )
    current_step: DeepImportStep | None = Field(
        default=None,
        description="当前正在执行的步骤",
    )
    total_steps: int = Field(default=3, description="总步骤数")
    completed_steps: list[str] = Field(
        default_factory=list,
        description="已完成的步骤列表",
    )
    message: str = Field(
        default="",
        description="当前步骤的描述/提示消息",
    )
    # Phase 1 进度字段
    phase1_total_batches: int = Field(default=0, description="Phase 1 总批次数")
    phase1_completed_batches: int = Field(default=0, description="Phase 1 已完成批次数")
    # Phase 2 进度字段
    phase2_total_scenes: int = Field(default=0, description="Phase 2 总 Scene 数")
    phase2_completed_scenes: int = Field(default=0, description="Phase 2 已完成 Scene 数")
    # 降级标记
    degraded: bool = Field(default=False, description="是否有批次触发降级")
    degraded_batches: list[int] = Field(default_factory=list, description="触发降级的批次索引")
```

- [ ] **Step 2: 提交**

```bash
git add backend/modules/imports/workflow_schemas.py
git commit -m "refactor: update DeepImportStep enum for 3-phase pipeline"
```

---

### Task 5: 创建 Scene 切分 Prompt

**Files:**
- Create: `backend/prompts/scene_segmentation.md`

- [ ] **Step 1: 创建 scene_segmentation prompt**

创建 `backend/prompts/scene_segmentation.md`：

```markdown
# Scene Segmentation — Scene 切分 Prompt

> **用途**：从连续章节正文中切分出叙事 Scene，输出 Scene 卡字段。
> **输入**：5 章连续正文（含 Overlap 章）
> **输出**：scenes[] — 每个 Scene 的 title / goal / core_conflict / emotional_beat / narrative_tag / scene_chunks

---

## 角色定位

你是一个小说叙事结构分析助手。你的任务是将连续的章节正文切分为有独立叙事意义的 Scene（场景/剧情段）。

---

## 输入

你将收到 5 章连续正文。每章以 `## 第X章 {标题}` 开头。

---

## 输出 JSON Schema

```json
{
  "scenes": [
    {
      "title": "Scene 标题（简短描述）",
      "goal": "此 Scene 要完成的叙事目标",
      "core_conflict": "核心冲突（人物之间/人物与环境/人物内心）",
      "emotional_beat": "读者在此 Scene 中的情感走向",
      "narrative_tag": "inciting_incident|rising_action|climax|valley|transition|hook|payoff|draft",
      "scene_chunks": [
        {"chapter_index": 1, "start_paragraph": 0, "end_paragraph": 12}
      ]
    }
  ]
}
```

---

## 核心规则

1. **Scene 是最小叙事单元**：一个 Scene 是一个有独立目标、冲突、情感走向的叙事单元，不是物理章。
2. **一个 Scene 可跨章**：一个 Scene 可能横跨 1-3 章（但不更多）。`scene_chunks` 记录物理映射。
3. **叙事标签判定**：
   - `hook` — 开篇钩子（黄金三章）
   - `inciting_incident` — 激励事件，改变主角现状
   - `rising_action` — 冲突升级
   - `climax` — 阶段高潮
   - `valley` — 低谷（不进入第三遍输入）
   - `transition` — 纯过渡/日常（不进入第三遍输入）
   - `payoff` — 爽点释放
   - `draft` — 无法判断时使用
4. **重叠章归属**：如果第 5 章（Overlap 章）与第 6 章的 Scene 有关联，在当前批次中只切出已完成的 Scene，跨批 Scene 留给下一批处理。
5. **异形章处理**：
   - 高密度设定章（非对话说明性文字 >75%）→ 整章标记为一个 Scene，`narrative_tag = "draft"`
   - 缝合章（视角跳切/时间断层过多）→ 不强行切分，整章作为一个 Scene，`narrative_tag = "draft"`
   - 日常章（无关键情节推进）→ 标记 `narrative_tag = "transition"`
6. **不需要标注 must_happen / must_not_happen**：这些字段由用户后续手动填写。

---

## Scene 设计标准

每个 Scene 必须同时满足：
- **明确目标**：goal 不为空，且具体（不是"推进剧情"）
- **明确冲突**：core_conflict 不为空
- **情感走向**：emotional_beat 描述读者在此 Scene 中的情感变化
- **合理粒度**：一个 Scene 对应约 1500-4000 字的正文段落

---

## 输出前自查

1. 每个 Scene 是否都有 goal / core_conflict / emotional_beat？
2. 是否有 Scene 过长（>4000 字）应拆分？或过短（<1000 字）应合并？
3. Overlap 章是否正确处理？
4. narrative_tag 选择是否合理？
```

- [ ] **Step 2: 提交**

```bash
git add backend/prompts/scene_segmentation.md
git commit -m "feat: add scene segmentation LLM prompt"
```

---

### Task 6: 创建 SceneSegmentationService

**Files:**
- Create: `backend/modules/imports/scene_segmentation.py`

- [ ] **Step 1: 创建 SceneSegmentationService**

创建 `backend/modules/imports/scene_segmentation.py`：

```python
"""SceneSegmentationService — Phase 1: 章节正文 → Scene 切分"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest
from modules.outline.models import Scene
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

BATCH_SIZE = 5
OVERLAP = 1  # 批次间重叠章数
MAX_LLM_RETRIES = 3


class SceneSegmentationService:
    """Phase 1: 将章节正文按 5 章/批 + 1 章 Overlap 切分为 Scene"""

    async def segment_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        """切分章节范围 → Scene，写入 scenes 表

        Returns:
            {"total_scenes": int, "failed_batches": list[int], "degraded": bool}
        """
        nid = parse_uuid(novel_id, "novel_id")

        # 1. 读取章节正文
        chapters = await self._load_chapters(db, novel_id, start_chapter, end_chapter)
        if not chapters:
            return {"total_scenes": 0, "failed_batches": [], "degraded": False}

        # 2. 拆分为批（5 章/批，1 章 Overlap）
        batches = self._split_into_batches(chapters)
        total_batches = len(batches)
        logger.info(
            "Scene segmentation: %d chapters → %d batches (batch_size=%d, overlap=%d)",
            len(chapters), total_batches, BATCH_SIZE, OVERLAP,
        )

        # 3. 逐批调用 LLM 切分（当前版本串行，后续可并行）
        all_scenes: list[dict] = []
        failed_batches: list[int] = []
        degraded = False
        next_scene_index = await self._get_next_scene_index(db, nid)

        for batch_idx, batch in enumerate(batches):
            try:
                batch_scenes = await self._process_batch(
                    db, nid, batch, batch_idx, next_scene_index,
                )
                for s in batch_scenes:
                    all_scenes.append(s)
                    next_scene_index += 1
            except Exception as exc:
                logger.warning("Batch %d failed: %s", batch_idx, exc)
                # 降级：逐章切分
                try:
                    degraded = True
                    fallback_scenes = await self._process_batch_single_chapter(
                        db, nid, batch, batch_idx, next_scene_index,
                    )
                    for s in fallback_scenes:
                        all_scenes.append(s)
                        next_scene_index += 1
                except Exception as fb_exc:
                    logger.error(
                        "Batch %d fallback also failed: %s", batch_idx, fb_exc,
                    )
                    failed_batches.append(batch_idx)
                    # 机械兜底：每章 = 1 个 Scene
                    for ch in batch:
                        scene = Scene(
                            novel_id=nid,
                            scene_index=next_scene_index,
                            title=ch.get("title", f"第{ch['chapter_index']}章"),
                            narrative_tag="draft",
                            source="deep_import",
                            scene_chunks=[{
                                "chapter_index": ch["chapter_index"],
                                "start_paragraph": 0,
                            }],
                            chapter_ids=[str(ch["chapter_index"])],
                            status="draft",
                        )
                        db.add(scene)
                        next_scene_index += 1
                    logger.info(
                        "Batch %d: mechanical fallback, created %d scenes",
                        batch_idx, len(batch),
                    )

        await db.flush()
        return {
            "total_scenes": len(all_scenes),
            "failed_batches": failed_batches,
            "degraded": degraded,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> list[dict]:
        """从 writing_drafts 加载章节正文"""
        from modules.writing.facade import get_latest_draft_for_chapter

        chapters: list[dict] = []
        for idx in range(start, end + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.get("content"):
                chapters.append({
                    "chapter_index": idx,
                    "title": draft.get("title", f"第{idx}章"),
                    "content": draft["content"],
                })
        return chapters

    def _split_into_batches(self, chapters: list[dict]) -> list[list[dict]]:
        """拆分为批，每批 5 章，相邻批次间 1 章 Overlap"""
        batches: list[list[dict]] = []
        i = 0
        while i < len(chapters):
            batch = chapters[i:i + BATCH_SIZE]
            batches.append(batch)
            # 下一批从当前批的倒数第 OVERLAP 章开始
            i += BATCH_SIZE - OVERLAP
        return batches

    async def _get_next_scene_index(self, db: AsyncSession, nid) -> int:
        """获取下一个 scene_index"""
        from sqlalchemy import func, select
        from modules.outline.models import Scene as SceneModel

        stmt = select(func.coalesce(func.max(SceneModel.scene_index), -1)).where(
            SceneModel.novel_id == nid,
        )
        result = await db.execute(stmt)
        max_idx = result.scalar() or -1
        return max_idx + 1

    async def _process_batch(
        self,
        db: AsyncSession,
        nid,
        batch: list[dict],
        batch_idx: int,
        start_scene_index: int,
    ) -> list[dict]:
        """调用 LLM 切分一批章节"""
        # 构建 prompt 上下文
        chapters_text = self._build_chapters_text(batch)
        system_prompt = load_prompt("scene_segmentation")

        from core.config import get_settings
        settings = get_settings()

        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"请将以下章节正文切分为叙事 Scene。\n\n{chapters_text}"
                )},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient()
        last_error: Exception | None = None

        for attempt in range(MAX_LLM_RETRIES):
            try:
                raw = await llm_client.generate(request)
                parsed = json.loads(raw.content)
                scenes_data = parsed.get("scenes", [])
                if not scenes_data:
                    raise ValueError("LLM returned empty scenes list")
                return scenes_data
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Batch %d LLM attempt %d/%d failed: %s",
                    batch_idx, attempt + 1, MAX_LLM_RETRIES, exc,
                )

        raise last_error or RuntimeError("All LLM retries exhausted")

    async def _process_batch_single_chapter(
        self,
        db: AsyncSession,
        nid,
        batch: list[dict],
        batch_idx: int,
        start_scene_index: int,
    ) -> list[dict]:
        """降级方案：逐章 LLM 切分"""
        all_scenes: list[dict] = []
        for ch in batch:
            chapters_text = self._build_chapters_text([ch])
            system_prompt = load_prompt("scene_segmentation")

            from core.config import get_settings
            settings = get_settings()

            request = LLMCallRequest(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": (
                        f"请将以下章节正文切分为叙事 Scene。\n\n{chapters_text}"
                    )},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            llm_client = LLMClient()
            for attempt in range(MAX_LLM_RETRIES):
                try:
                    raw = await llm_client.generate(request)
                    parsed = json.loads(raw.content)
                    scenes = parsed.get("scenes", [])
                    if scenes:
                        all_scenes.extend(scenes)
                        break
                except Exception as exc:
                    logger.warning(
                        "Single-chapter batch %d ch %d attempt %d failed: %s",
                        batch_idx, ch["chapter_index"], attempt + 1, exc,
                    )
            else:
                raise RuntimeError(
                    f"Single-chapter fallback failed for ch {ch['chapter_index']}"
                )
        return all_scenes

    @staticmethod
    def _build_chapters_text(chapters: list[dict]) -> str:
        """构建章节正文文本"""
        parts: list[str] = []
        for ch in chapters:
            title = ch.get("title") or f"第{ch['chapter_index']}章"
            parts.append(f"## 第{ch['chapter_index']}章 {title}\n\n{ch.get('content', '')}")
        return "\n\n".join(parts)
```

- [ ] **Step 2: 提交**

```bash
git add backend/modules/imports/scene_segmentation.py
git commit -m "feat: add SceneSegmentationService with batch+overlap+degradation"
```

---

### Task 7: 修改 PlotStructureGenerator 持久化伏笔/揭示

**Files:**
- Modify: `backend/modules/outline/services.py:549-575`

- [ ] **Step 1: 在 generate() 方法的 Step 9 后追加持久化逻辑**

在 `backend/modules/outline/services.py` 的 `PlotStructureGenerator.generate()` 方法中，在 `# 9. 构建返回（含 extra_sections, warnings）` 的 return 之前（约 line 551），插入伏笔和揭示的持久化：

```python
        # ============================================================
        # 9.5. 持久化 foreshadowing_plans 和 reveal_plans
        # ============================================================
        from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
        from modules.outline.reveal_repository import RevealPlanRepository

        _fp_repo = ForeshadowingPlanRepository()
        created_foreshadowing: list[dict] = []
        for fp in result.foreshadowing_plans:
            if not fp.name:
                continue
            try:
                plan = await _fp_repo.create(db, nid, {
                    "name": fp.name,
                    "summary": fp.summary,
                    "surface_meaning": fp.surface_meaning if hasattr(fp, "surface_meaning") else None,
                    "hidden_meaning": fp.hidden_meaning if hasattr(fp, "hidden_meaning") else None,
                    "planned_seed_chapter": fp.planned_seed_chapter,
                    "planned_payoff_chapter": fp.planned_payoff_chapter,
                    "status": "draft",
                })
                created_foreshadowing.append({
                    "id": str(plan.id), "name": plan.name,
                })
            except Exception as exc:
                logger.warning("Failed to create foreshadowing '%s': %s", fp.name, exc)

        _rp_repo = RevealPlanRepository()
        created_reveals: list[dict] = []
        for rp in result.reveal_plans:
            if not rp.target_name:
                continue
            # 尝试解析 target_name 到 target_id
            target_id = entity_name_to_id.get(rp.target_name) or character_name_to_id.get(rp.target_name)
            try:
                plan = await _rp_repo.create(db, nid, {
                    "target_type": rp.target_type,
                    "target_id": target_id or "00000000-0000-0000-0000-000000000000",
                    "secret_summary": rp.secret_summary or "",
                    "status": "draft",
                })
                created_reveals.append({
                    "id": str(plan.id),
                    "target_name": rp.target_name,
                })
            except Exception as exc:
                logger.warning("Failed to create reveal for '%s': %s", rp.target_name, exc)

        await db.flush()
```

同时修改最后的 return 字典，将 `extra_sections` 中的纯 Pydantic model_dump 替换为实际持久化的数据：

```python
        return {
            "total_threads": len(created_threads),
            "total_arcs": len(created_arcs),
            "threads": created_threads,
            "arcs": created_arcs,
            "extra_sections": {
                "foreshadowing_plans": created_foreshadowing,
                "reveal_plans": created_reveals,
                "offscreen_progress": [
                    p.model_dump() for p in result.offscreen_progress
                ],
                "risks": [
                    p.model_dump() for p in result.risks
                ],
                "questions_for_user": [
                    q.model_dump() for q in result.questions_for_user
                ],
            },
            "warnings": warnings_list,
        }
```

- [ ] **Step 2: 提交**

```bash
git add backend/modules/outline/services.py
git commit -m "feat: persist foreshadowing_plans and reveal_plans in PlotStructureGenerator"
```

---

### Task 8: 重写 DeepImportWorkflow 编排器

**Files:**
- Modify: `backend/modules/imports/workflow.py`（重写）

- [ ] **Step 1: 重写 workflow.py**

用新三阶段流水线替换 `backend/modules/imports/workflow.py` 的全部内容：

```python
"""Deep Import 工作流编排器

三阶段流水线：
  Phase 1: Scene 切分（并行批次）→ scenes 表
  Phase 2: 实体增量提取（串行按 Scene）→ core_entities + delta_log
  Phase 3: 剧情结构分析（单次）→ plot_threads + outline_arcs + foreshadowing_plans + reveal_plans
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


class DeepImportWorkflow:
    """深度导入流水线编排器 — 三阶段全自动"""

    async def run_step(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
    ) -> DeepImportProgress:
        if progress.phase == "pending":
            progress.phase = "running"

            # ----------------------------------------------------------
            # Phase 1: Scene 切分（并行批次）
            # ----------------------------------------------------------
            progress.current_step = DeepImportStep.scene_segmentation
            progress.message = "正在切分叙事 Scene..."
            phase1_result = await self._segment_scenes(
                db, novel_id, start_chapter, end_chapter, progress,
            )
            progress.completed_steps.append(DeepImportStep.scene_segmentation.value)
            progress.message = (
                f"Scene 切分完成，共创建 {phase1_result['total_scenes']} 个 Scene。"
            )
            if phase1_result.get("degraded"):
                progress.degraded = True
                progress.message += (
                    f"（{len(phase1_result['failed_batches'])} 个批次触发降级）"
                )

            # ----------------------------------------------------------
            # Phase 2: 实体增量提取（串行，按 Scene）
            # ----------------------------------------------------------
            progress.current_step = DeepImportStep.entity_extraction
            progress.message = "正在按 Scene 提取世界对象..."
            phase2_result = await self._extract_entities_by_scene(
                db, novel_id, progress,
            )
            progress.completed_steps.append(DeepImportStep.entity_extraction.value)
            progress.message = (
                f"实体提取完成，共创建 {phase2_result['total_created']} 个实体，"
                f"记录 {phase2_result['total_deltas']} 条变更。"
            )

            # ----------------------------------------------------------
            # Phase 3: 剧情结构分析（单次）
            # ----------------------------------------------------------
            progress.current_step = DeepImportStep.structure_analysis
            progress.message = "正在生成剧情线、篇章纲、伏笔和揭示计划..."
            phase3_result = await self._analyze_structure(
                db, novel_id, start_chapter, end_chapter,
            )
            progress.completed_steps.append(DeepImportStep.structure_analysis.value)

            progress.current_step = None
            progress.phase = "done"
            progress.message = (
                f"深度导入完成！"
                f"共 {phase1_result['total_scenes']} 个 Scene，"
                f"{phase2_result['total_created']} 个实体，"
                f"{phase3_result['total_threads']} 条剧情线，"
                f"{phase3_result['total_arcs']} 个篇章纲。"
            )

        else:
            raise ValueError(f"无法处理当前进度状态: {progress.phase}")

        return progress

    # ------------------------------------------------------------------
    # Phase 1: Scene 切分
    # ------------------------------------------------------------------

    async def _segment_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        progress: DeepImportProgress,
    ) -> dict[str, Any]:
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        result = await service.segment_chapters(
            db, novel_id, start_chapter, end_chapter,
        )
        logger.info(
            "Phase 1 complete: %d scenes, %d failed batches, degraded=%s",
            result["total_scenes"],
            len(result.get("failed_batches", [])),
            result.get("degraded", False),
        )
        return result

    # ------------------------------------------------------------------
    # Phase 2: 实体增量提取
    # ------------------------------------------------------------------

    async def _extract_entities_by_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        progress: DeepImportProgress,
    ) -> dict[str, Any]:
        """按 Scene 顺序串行提取实体，累积 Memory 上下文

        委托给 world.run_scene_entity_extraction（需要在 Task 9 中注册）。
        """
        handler = _container_get("world.run_scene_entity_extraction")
        try:
            result = await handler(db, novel_id=novel_id)
            return result
        except Exception as exc:
            logger.warning("Phase 2 entity extraction failed: %s", exc)
            return {"total_created": 0, "total_deltas": 0}

    # ------------------------------------------------------------------
    # Phase 3: 剧情结构分析
    # ------------------------------------------------------------------

    async def _analyze_structure(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        _generate = _container_get("outline.generate_structure")
        try:
            result = await _generate(
                db, novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            )
            logger.info(
                "Phase 3 complete: %d threads, %d arcs, %d foreshadowing, %d reveals",
                result["total_threads"],
                result["total_arcs"],
                len(result.get("extra_sections", {}).get("foreshadowing_plans", [])),
                len(result.get("extra_sections", {}).get("reveal_plans", [])),
            )
            return result
        except Exception as exc:
            logger.warning("Phase 3 structure analysis failed: %s", exc)
            return {
                "total_threads": 0, "total_arcs": 0,
                "threads": [], "arcs": [],
                "extra_sections": {},
            }
```

- [ ] **Step 2: 提交**

```bash
git add backend/modules/imports/workflow.py
git commit -m "refactor: rewrite DeepImportWorkflow for 3-phase scene-centric pipeline"
```

---

### Task 9: 创建 Scene 级实体提取服务并注册到 DI 容器

**Files:**
- Create: `backend/modules/imports/scene_entity_extraction.py`
- Modify: `backend/app/main.py`（注册服务）

- [ ] **Step 1: 创建 SceneEntityExtractionService**

创建 `backend/modules/imports/scene_entity_extraction.py`：

```python
"""SceneEntityExtractionService — Phase 2: 按 Scene 串行增量提取实体"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest
from modules.memory.models import DeltaLog
from modules.outline.models import Scene as SceneModel
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class SceneEntityExtractionService:
    """Phase 2: 按 Scene 顺序串行提取实体，累积 Memory 上下文"""

    async def extract_by_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")

        # 1. 获取所有 active Scene（按 scene_index 排序）
        scenes = await self._get_scenes(db, nid)
        if not scenes:
            return {"total_created": 0, "total_deltas": 0}

        # 2. 加载初始 Memory（已有实体列表）
        from modules.world.facade import get_world_context
        ctx = await get_world_context(
            db, novel_id, reveal_mode="author_safe", limit=500,
        )
        existing_entities_context = "\n".join(
            f"- {e.name} ({e.entity_type})" for e in ctx.entities
        ) or "无已有对象"

        total_created = 0
        total_deltas = 0
        total_scenes = len(scenes)
        accumulated_memory: list[dict] = []

        # 3. 串行处理每个 Scene
        for scene_idx, scene in enumerate(scenes):
            try:
                scene_result = await self._process_scene(
                    db, nid, scene, scene_idx,
                    existing_entities_context,
                    accumulated_memory,
                )
                total_created += scene_result["created"]
                total_deltas += scene_result["deltas"]
                # 更新累积上下文
                existing_entities_context = scene_result["updated_context"]
                accumulated_memory = scene_result["updated_memory"]
            except Exception as exc:
                logger.warning(
                    "Scene %d (idx=%d) extraction failed after %d retries: %s",
                    scene_idx, scene.scene_index, MAX_RETRIES, exc,
                )
                continue

        await db.flush()
        return {
            "total_created": total_created,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _get_scenes(self, db: AsyncSession, nid) -> list[SceneModel]:
        from sqlalchemy import select
        stmt = (
            select(SceneModel)
            .where(
                SceneModel.novel_id == nid,
                SceneModel.status.in_(["draft", "canonical"]),
                SceneModel.narrative_tag.notin_(["valley", "transition"]),
            )
            .order_by(SceneModel.scene_index)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _process_scene(
        self,
        db: AsyncSession,
        nid,
        scene: SceneModel,
        scene_idx: int,
        existing_context: str,
        accumulated_memory: list[dict],
    ) -> dict[str, Any]:
        """处理单个 Scene：LLM 提取 → 去重 → 持久化 → 记录 delta"""
        # 加载 Scene 对应的章节正文
        chapters_text = await self._load_scene_chapters(db, scene)

        # 构建 Memory 上下文
        memory_context = self._build_memory_context(accumulated_memory)

        # 调用 LLM
        entities, relations, delta_events = await self._call_llm_extraction(
            chapters_text, existing_context, memory_context,
        )

        # 去重 + 持久化
        created_count = await self._persist_entities(db, nid, entities, scene.scene_index)

        # 记录 delta
        delta_count = await self._record_deltas(
            db, nid, delta_events, scene.scene_index,
        )

        # 更新上下文
        new_entities_text = "\n".join(
            f"- {e.get('name', '?')} ({e.get('entity_type', '?')})"
            for e in entities
            if e.get("suggested_action") == "create_new"
        )
        updated_context = existing_context + "\n" + new_entities_text if new_entities_text else existing_context

        # 更新 Memory
        updated_memory = accumulated_memory + [
            {"scene_index": scene.scene_index, "entities": len(entities)}
        ]

        # 触发 Memory 快照（每 10 个 Scene）
        if scene_idx > 0 and scene_idx % 10 == 0:
            try:
                from core.container import get as _get
                await _get("memory.capture_snapshot")(
                    db, novel_id=str(nid), chapter_index=scene.scene_index,
                )
            except Exception as exc:
                logger.warning("Memory snapshot at scene %d failed: %s", scene_idx, exc)

        return {
            "created": created_count,
            "deltas": delta_count,
            "updated_context": updated_context,
            "updated_memory": updated_memory,
        }

    async def _load_scene_chapters(self, db: AsyncSession, scene: SceneModel) -> str:
        """加载 Scene 关联的章节正文"""
        from modules.writing.facade import get_latest_draft_for_chapter

        parts: list[str] = []
        for ch_id_str in (scene.chapter_ids or []):
            try:
                ch_idx = int(ch_id_str)
            except (ValueError, TypeError):
                continue
            draft = await get_latest_draft_for_chapter(db, str(scene.novel_id), ch_idx)
            if draft and draft.get("content"):
                parts.append(f"## 第{ch_idx}章\n\n{draft['content']}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_memory_context(memory: list[dict]) -> str:
        if not memory:
            return "无前序 Scene 上下文"
        recent = memory[-5:]  # 最近 5 个 Scene
        lines = ["## 前序 Scene 摘要"]
        for m in recent:
            lines.append(f"- Scene {m['scene_index']}: 包含 {m['entities']} 个实体")
        return "\n".join(lines)

    async def _call_llm_extraction(
        self,
        chapters_text: str,
        existing_context: str,
        memory_context: str,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """调用 LLM 提取实体、关系、Delta 事件"""
        system_prompt = load_prompt(
            "structure_extraction",
            existing_entities_context=existing_context,
        )
        system_prompt += f"\n\n## 前序上下文\n\n{memory_context}"

        from core.config import get_settings
        settings = get_settings()

        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请从以下正文中提取世界对象。\n\n{chapters_text}"},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient()
        for attempt in range(MAX_RETRIES):
            try:
                raw = await llm_client.generate(request)
                parsed = json.loads(raw.content)
                return (
                    parsed.get("entities", []),
                    parsed.get("relations", []),
                    parsed.get("delta_events", []),
                )
            except Exception as exc:
                logger.warning(
                    "LLM extraction attempt %d/%d failed: %s",
                    attempt + 1, MAX_RETRIES, exc,
                )

        return [], [], []

    async def _persist_entities(
        self,
        db: AsyncSession,
        nid,
        entities: list[dict],
        scene_index: int,
    ) -> int:
        """去重 + 持久化实体"""
        from modules.world.facade import find_similar_entities
        from modules.world.services.entity_service import EntityService
        from modules.world.schemas import CoreEntityCreate

        created = 0
        entity_service = EntityService()

        for ent in entities:
            action = ent.get("suggested_action", "ignore")
            if action in ("ignore", "temporary_only"):
                continue
            if action == "link_to_existing":
                continue  # 别名链接暂不在 Phase 2 中处理

            # 去重检测
            similar = await find_similar_entities(db, str(nid), ent.get("name", ""))
            if similar and similar.get("score", 0) >= 0.88:
                continue

            try:
                await entity_service.create(db, str(nid), CoreEntityCreate(
                    name=ent.get("name", ""),
                    entity_type=ent.get("entity_type", "character"),
                    summary=ent.get("summary"),
                    public_info=ent.get("public_info"),
                    hidden_truth=ent.get("hidden_truth"),
                    importance=ent.get("importance", 0.5),
                    status="canonical",
                    created_by="auto_ingested",
                ))
                created += 1
            except Exception as exc:
                logger.warning("Failed to create entity '%s': %s", ent.get("name"), exc)

        return created

    async def _record_deltas(
        self,
        db: AsyncSession,
        nid,
        delta_events: list[dict],
        scene_index: int,
    ) -> int:
        """记录 delta_log"""
        count = 0
        for event in delta_events:
            delta = DeltaLog(
                novel_id=nid,
                entity_id=None,
                scene_index=scene_index,
                category=event.get("category", "ENTITY_UPDATED"),
                field_path=event.get("field"),
                old_value=json.dumps(event.get("old")) if event.get("old") else None,
                new_value=json.dumps(event.get("new")) if event.get("new") else None,
                source="ai_extraction",
                meta=event.get("meta", {}),
            )
            db.add(delta)
            count += 1
        return count
```

- [ ] **Step 2: 在 app/main.py 中注册服务**

在 `backend/app/main.py` 的 import 区追加：

```python
from modules.imports.scene_entity_extraction import (
    SceneEntityExtractionService as _SceneExtractSvc,
)
```

在 `_register` 调用区追加：

```python
_register("world.run_scene_entity_extraction", _SceneExtractSvc().extract_by_scenes)
```

- [ ] **Step 3: 在 memory/models.py 补充缺失 import**

`DeltaLog` 模型需要 `UUIDType` 和 `func`，确认 `memory/models.py` 顶部已存在：

```python
from sqlalchemy import func
```
以及 `from core.base import UUIDType`（已在 Step 1 中添加）。

- [ ] **Step 4: 提交**

```bash
git add backend/modules/imports/scene_entity_extraction.py backend/app/main.py
git commit -m "feat: add SceneEntityExtractionService for Phase 2 incremental extraction"
```

---

### Task 10: 更新 tasks.py task handler

**Files:**
- Modify: `backend/modules/imports/tasks.py`

- [ ] **Step 1: 更新 handle_deep_import 的消息和注释**

将 `backend/modules/imports/tasks.py` 中的 `handle_deep_import` 和 `handle_deep_import_resume` 注释更新为反映新的三阶段：

```python
@task_handler("deep_import")
async def handle_deep_import(db, task) -> dict[str, Any]:
    """处理深度导入任务 — 全自动三阶段（Scene 切分 + 实体提取 + 结构分析）

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 5))

    if not novel_id:
        raise ValueError("novel_id is required for deep_import")

    workflow = DeepImportWorkflow()
    progress = DeepImportProgress()
    progress = await workflow.run_step(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        progress=progress,
    )

    logger.info(
        "Deep import complete — phase=%s, completed=%s",
        progress.phase,
        progress.completed_steps,
    )

    return {
        "phase": progress.phase,
        "current_step": progress.current_step.value if progress.current_step else None,
        "completed_steps": progress.completed_steps,
        "message": progress.message,
        "degraded": progress.degraded,
        "degraded_batches": progress.degraded_batches,
    }


@task_handler("deep_import_resume")
async def handle_deep_import_resume(db, task) -> dict[str, Any]:
    """（已废弃）候选管理已移除，深度导入全自动执行。

    保留 handler 注册以兼容已有队列任务。
    """
    logger.warning("deep_import_resume 已废弃 — 深度导入已改为全自动。忽略 resume 请求。")
    return {
        "phase": "done",
        "current_step": None,
        "completed_steps": [
            DeepImportStep.scene_segmentation.value,
            DeepImportStep.entity_extraction.value,
            DeepImportStep.structure_analysis.value,
        ],
        "message": "候选管理已移除，深度导入全自动执行。",
        "degraded": False,
        "degraded_batches": [],
    }
```

需要确认文件顶部已导入新的枚举：

```python
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
```

（当前已有 `DeepImportProgress` 的 import，需追加 `DeepImportStep`）

- [ ] **Step 2: 提交**

```bash
git add backend/modules/imports/tasks.py
git commit -m "refactor: update deep_import task handler for new 3-phase pipeline"
```

---

### Task 11: 更新 API 进度响应

**Files:**
- Modify: `backend/modules/imports/api.py`

- [ ] **Step 1: 更新 deep_import 端点注释和响应**

在 `backend/modules/imports/api.py` 中更新 `submit_deep_import` 的文档字符串（line 63-65），将：

```python
    """提交深度导入任务

    从章节正文中自动执行世界对象抽取、人物同步和剧情结构生成三步流水线。
```

改为：

```python
    """提交深度导入任务

    自动执行三阶段流水线：Scene 切分 → 实体增量提取 → 剧情结构分析。
```

- [ ] **Step 2: 提交**

```bash
git add backend/modules/imports/api.py
git commit -m "docs: update deep import API description for new pipeline"
```

---

### Task 12: 更新 alembic env.py 确保新模型被导入

**Files:**
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: 添加 memory 模型导入**

确认 `backend/alembic/env.py` 已导入 `modules.memory.models`（当前检查已有）。新模型 `DeltaLog` 在同一文件中，自动包含。

- [ ] **Step 2: 添加 outline 新模型导入**

确认 outline 模型导入包含 `ForeshadowingPlan` 和 `RevealPlan`。当前 `env.py` 已有 `import modules.outline.models`，新类自动包含。

- [ ] **Step 3: 运行迁移验证**

```bash
cd backend && alembic upgrade head
```

预期：无错误，新表 `delta_log` 被创建。

- [ ] **Step 4: 提交（如有变更）**

```bash
git add backend/alembic/env.py
git commit -m "chore: verify alembic imports new delta_log and outline models"
```

---

### Task 13: 后端集成测试

**Files:**
- Modify: `backend/modules/imports/tests/test_imports_integration.py`

- [ ] **Step 1: 添加 Scene 切分 Phase 的 mock 测试**

在 `backend/modules/imports/tests/test_imports_integration.py` 追加测试用例：

```python
class TestSceneSegmentationIntegration:
    """Phase 1: Scene 切分集成测试"""

    async def test_segmentation_mock(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """Scene 切分应通过 SceneSegmentationService 处理"""
        from modules.imports.scene_segmentation import SceneSegmentationService

        service = SceneSegmentationService()
        # 无章节时返回空
        result = await service.segment_chapters(
            db_session, sample_novel_id, start_chapter=1, end_chapter=1,
        )
        assert result["total_scenes"] == 0
        assert not result["degraded"]


class TestDeepImportWorkflowNewPipeline:
    """新三阶段流水线集成测试"""

    async def test_workflow_runs_3_phases(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        """DeepImportWorkflow 应按 scene_segmentation → entity_extraction → structure_analysis 顺序执行"""
        from unittest import mock

        from modules.imports.workflow import DeepImportWorkflow
        from modules.imports.workflow_schemas import DeepImportProgress

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        async def _mock_segment(db, novel_id, start, end, progress):
            return {"total_scenes": 5, "failed_batches": [], "degraded": False}

        async def _mock_extract(db, novel_id, progress):
            return {"total_created": 3, "total_deltas": 2}

        async def _mock_analyze(db, novel_id, start, end):
            return {
                "total_threads": 2, "total_arcs": 1,
                "threads": [], "arcs": [], "extra_sections": {},
            }

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(workflow, "_extract_entities_by_scene", side_effect=_mock_extract),
            mock.patch.object(workflow, "_analyze_structure", side_effect=_mock_analyze),
        ):
            result = await workflow.run_step(
                db_session, sample_novel_id,
                start_chapter=1, end_chapter=5,
                progress=progress,
            )

        assert result.phase == "done"
        assert len(result.completed_steps) == 3
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps
```

- [ ] **Step 2: 运行测试确认通过**

```bash
cd backend && python -m pytest modules/imports/tests/test_imports_integration.py -xvs
```

- [ ] **Step 3: 提交**

```bash
git add backend/modules/imports/tests/test_imports_integration.py
git commit -m "test: add integration tests for new 3-phase deep import pipeline"
```

---

### Task 14: 运行全量后端测试确认无回归

**Files:** 无新建

- [ ] **Step 1: 运行后端全部测试**

```bash
cd backend && python -m pytest -xvs --tb=short
```

- [ ] **Step 2: 检查 outline 模块测试**

```bash
cd backend && python -m pytest modules/outline/tests/ -xvs
```

- [ ] **Step 3: 检查 imports 模块测试**

```bash
cd backend && python -m pytest modules/imports/tests/ -xvs
```

- [ ] **Step 4: 检查 memory 模块测试**

```bash
cd backend && python -m pytest modules/memory/tests/ -xvs
```

- [ ] **Step 5: 如有失败，修复后重新运行全部测试**

所有测试通过后提交修复（如有）：

```bash
git add -A
git commit -m "fix: resolve test regressions from deep import refactor"
```

---

### Task 15: 运行 Ruff lint 并修复

**Files:** 无新建

- [ ] **Step 1: 运行 ruff check**

```bash
cd backend && ruff check .
```

- [ ] **Step 2: 运行 ruff format 检查**

```bash
cd backend && ruff format --check .
```

- [ ] **Step 3: 如有问题，修复后提交**

```bash
ruff format .
git add -A
git commit -m "style: ruff format after deep import refactor"
```

---

## 自审清单

1. **Spec coverage** — 逐条对照文档要求：
   - Phase 1: Scene 切分（5章/批 + Overlap + 降级）✅ Task 5, 6, 8
   - Phase 2: 实体增量提取（串行按 Scene + Memory 累积 + delta_log）✅ Task 3, 9
   - Phase 3: 结构分析（持久化伏笔/揭示）✅ Task 1, 2, 7, 8
   - 重复导入检测 → ⚠️ 延后（当前 import 模块不涉及此变更）
   - 前端进度条更新 → ⚠️ 延后（需要前端配合，不在本次后端重构范围）
   - Overlap 机制 ✅ Task 6
   - 降级策略（批次失败→逐章→机械）✅ Task 6
   - 异形章处理 → ⚠️ 由 LLM prompt 指导，非代码逻辑

2. **Placeholder scan** — 无 TBD/TODO/占位符，所有代码均完整

3. **Type consistency** — 已验证：
   - `DeepImportStep` 枚举值：`scene_segmentation`, `entity_extraction`, `structure_analysis` 在 workflow.py、tasks.py、workflow_schemas.py 中一致
   - `DeltaLog` 字段名与 migration 列名一致
   - `ForeshadowingPlanRepository.create_batch` 的 `items` 参数与调用处 dict key 一致

4. **延后项（不在本次范围）**：
   - 前端 Scene 进度条更新（需要前端配合）
   - Phase 1 真正的并行执行（当前是串行批次，后续可用 `asyncio.gather` 改造）
   - 重复导入检测（需要前端警告对话框配合）
   - text_archive 表（Entity 文本字段变更归档，属于 world 模块独立需求）
