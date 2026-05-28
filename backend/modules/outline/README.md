# Module: outline / 结构化剧情模块

## 定位

outline 模块是当前系统的核心创作模块。它把事实层中的世界对象、人物、地理历史、记忆和时间线转化为可执行的剧情结构。

这是系统的【结构层】核心——把事实组织成可执行的剧情计划。

## 核心产物

| 产出类型 | 数据表 | 说明 |
|---------|--------|------|
| PlotThread | `plot_threads` | 剧情线（主线/支线/暗线/关系线/反派线/伏笔线） |
| OutlineArc | `outline_arcs` | 篇章纲（8-15 章的小剧情闭环） |
| ChapterCard | `chapter_cards` | 章节卡（每章的目标、冲突、状态变化） |
| SceneCard | chapter_cards.scene_cards JSONB | 场景卡（MVP 阶段放在 chapter_cards 的 JSONB 字段） |
| ForeshadowingPlan | `foreshadowing_plans` | 伏笔计划 |
| RevealPlan | `reveal_plans` | 信息揭示计划 |

## 职责

- 剧情线创建与管理（PlotThread）
- 篇章纲创建与管理（OutlineArc）
- 章节卡创建与管理（ChapterCard）
- 伏笔计划创建与管理（ForeshadowingPlan）
- 信息揭示计划创建与管理（RevealPlan）
- 按章节索引查询章节卡
- 获取活跃剧情线
- 从候选数据创建章节卡
- 向其他模块提供大纲上下文

## 边界

明确不做：
- 一次性生成 500 章详细章节卡
- 自动决定故事终局
- 复杂多 Agent 大纲辩论
- 自动无确认修改正史大纲
- AI 自动生成完整正文（→ writing 模块）
- 正文审稿（→ review 模块）
- 上下文编译（→ context 模块）

## 数据表

| 表名 | 用途 |
|------|------|
| `plot_threads` | 剧情线定义 |
| `outline_arcs` | 篇章纲（8-15 章剧情闭环） |
| `chapter_cards` | 章节卡（每章核心结构） |
| `foreshadowing_plans` | 伏笔计划 |
| `reveal_plans` | 信息揭示计划 |

### plot_threads 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID（FK → projects.id）
- `name` — 剧情线名称
- `thread_type` — 类型（main / secondary / hidden / relationship / villain / foreshadowing）
- `summary` — 概要
- `visible_goal` — 对外可见目标
- `hidden_truth` — 暗线真相
- `start_chapter` — 起始章节
- `planned_payoff_chapter` — 计划收束章节
- `current_stage` — 当前阶段
- `related_character_ids` — 关联人物（JSONB）
- `related_entity_ids` — 关联世界对象（JSONB）
- `related_memory_ids` — 关联记忆（JSONB）
- `reader_known_state` / `author_known_state` — 读者/作者已知状态
- `status` — 状态（draft / candidate / canonical / deprecated）

### outline_arcs 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `title` — 篇章标题
- `arc_index` — 篇章序号
- `start_chapter` / `end_chapter` — 起止章节
- `arc_goal` — 篇章目标
- `core_conflict` — 核心冲突
- `main_opposition` — 主要对抗力量
- `entry_hook` / `midpoint_turn` / `climax` / `result` / `next_hook` — 标准三幕结构
- `related_thread_ids` — 关联剧情线（JSONB）
- `related_character_ids` — 关联人物（JSONB）
- `related_entity_ids` — 关联对象（JSONB）

### chapter_cards 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `chapter_index` — 章节序号（唯一约束，不可为空）
- `title` — 章节标题
- `arc_id` — 所属篇章（FK）
- `chapter_goal` — 章节目标
- `main_conflict` — 主要冲突
- `emotional_point` — 情绪点
- `plot_function` — 剧情功能
- `must_happen` / `must_not_happen` — 必须/禁止发生的事情（JSONB）
- `involved_character_ids` / `involved_entity_ids` / `related_thread_ids` — 关联（JSONB）
- `visible_progress` / `hidden_progress` / `offscreen_progress` — 各层面进展（JSONB）
- `foreshadowing_actions` — 伏笔操作（JSONB）
- `ending_hook` — 章节尾钩
- `scene_cards` — 场景卡片（JSONB，MVP 阶段不拆独立表）

### foreshadowing_plans 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `name` — 伏笔名称
- `summary` — 概要
- `surface_meaning` — 表面含义
- `hidden_meaning` — 隐藏含义
- `planned_seed_chapter` — 计划埋设章节
- `planned_reinforce_chapters` — 计划加强章节（JSONB）
- `planned_payoff_chapter` — 计划收束章节
- `related_entity_ids` / `related_thread_ids` — 关联（JSONB）

### reveal_plans 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `target_type` — 目标类型
- `target_id` — 目标 ID
- `secret_summary` — 秘密概要
- `reveal_stages` — 揭示阶段（JSONB，每阶段包含章节索引和揭示内容）

## 对外契约（contracts.py）

```python
@dataclass
class PlotThreadContract:
    novel_id: str
    thread_id: str
    name: str
    thread_type: str
    summary: str | None
    current_stage: str | None
    status: str

@dataclass
class OutlineArcContract:
    novel_id: str
    arc_id: str
    title: str
    arc_index: int | None
    arc_goal: str | None
    core_conflict: str | None
    status: str

@dataclass
class ChapterCardContract:
    novel_id: str
    card_id: str
    chapter_index: int
    title: str | None
    chapter_goal: str
    main_conflict: str
    status: str
```

## Facade（facade.py）

```python
async def get_chapter_card(
    db, novel_id: str, chapter_index: int,
) -> ChapterCardContract | None: ...

async def get_active_threads(
    db, novel_id: str, chapter_index: int | None = None,
) -> list[PlotThreadContract]: ...

async def get_arc_context(
    db, novel_id: str, arc_id: str,
) -> OutlineArcContract: ...

async def create_chapter_cards_from_candidate(
    db, novel_id: str, candidate_payload: dict,
) -> list[ChapterCardContract]: ...
```

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/outline/threads` | 剧情线列表 |
| POST | `/api/outline/threads` | 创建剧情线 |
| GET | `/api/outline/threads/{thread_id}` | 剧情线详情 |
| PUT | `/api/outline/threads/{thread_id}` | 更新剧情线 |
| DELETE | `/api/outline/threads/{thread_id}` | 删除剧情线 |
| GET | `/api/outline/arcs` | 篇章纲列表 |
| POST | `/api/outline/arcs` | 创建篇章纲 |
| GET | `/api/outline/arcs/{arc_id}` | 篇章纲详情 |
| PUT | `/api/outline/arcs/{arc_id}` | 更新篇章纲 |
| DELETE | `/api/outline/arcs/{arc_id}` | 删除篇章纲 |
| GET | `/api/outline/chapters` | 章节卡列表 |
| POST | `/api/outline/chapters` | 创建章节卡 |
| GET | `/api/outline/chapters/{chapter_id}` | 章节卡详情 |
| PUT | `/api/outline/chapters/{chapter_id}` | 更新章节卡 |
| DELETE | `/api/outline/chapters/{chapter_id}` | 删除章节卡 |
| GET | `/api/outline/chapters/by-index/{chapter_index}` | 按索引查章节卡 |
| GET | `/api/outline/foreshadowing` | 伏笔计划列表 |
| POST | `/api/outline/foreshadowing` | 创建伏笔计划 |
| GET | `/api/outline/foreshadowing/{f_id}` | 伏笔计划详情 |
| PUT | `/api/outline/foreshadowing/{f_id}` | 更新伏笔计划 |
| DELETE | `/api/outline/foreshadowing/{f_id}` | 删除伏笔计划 |
| GET | `/api/outline/reveals` | 揭示计划列表 |
| POST | `/api/outline/reveals` | 创建揭示计划 |
| GET | `/api/outline/reveals/{reveal_id}` | 揭示计划详情 |
| PUT | `/api/outline/reveals/{reveal_id}` | 更新揭示计划 |
| DELETE | `/api/outline/reveals/{reveal_id}` | 删除揭示计划 |
| POST | `/api/outline/chapters/from-candidate` | 从候选批量创建章节卡 |

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM、UUIDMixin、TimestampMixin、StatusMixin、NovelMixin
- `core.dependencies` — DbSession
- `shared.enums` — PlotThreadType、ObjectStatus、Visibility 等
- `shared.types` — NovelID、PlotThreadID、ArcID、ChapterCardID 等
- `shared.constants` — DEFAULT_PAGE_SIZE、MAX_PAGE_SIZE

## 测试方式

```bash
cd backend
python -m pytest modules/outline/tests/ -v
```

## 结构生成流程

```text
Context Compiler
    ↓
剧情结构生成 Prompt
    ↓
PlotThread / OutlineArc / ForeshadowingPlan / RevealPlan 候选
    ↓
用户确认
    ↓
章节与场景结构生成 Prompt
    ↓
ChapterCard + scene_cards 候选
    ↓
结构复查
    ↓
用户确认入正史
```

章节卡抽取会先确保目标章节已建立 RAG 索引，再使用有序 chunk 正文材料调用 `extract_chapter_scene` Prompt。AI 输出的章节卡保持 candidate 状态，等待用户确认。

## MVP

第一阶段实现 plot_threads、outline_arcs、chapter_cards 的完整 CRUD 和 facade。
SceneCard 放在 chapter_cards.scene_cards JSONB。
ForeshadowingPlan 和 RevealPlan 提供基础 CRUD。
