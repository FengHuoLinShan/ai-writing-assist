# CONTEXT.md — AI 长篇小说结构化创作引擎 v2.0

领域术语表、概念关系图、状态流转。保持本文与 `docs/agents/domain.md` 一致。

## 1. 核心产物（Core Products）

系统产生结构化创作资产，而非直接生成完整正文。

| 中文概念 | 英文 | 数据表 | 职责 |
|---------|------|--------|------|
| 核心实体 | CoreEntity | `core_entities` | 世界对象主表。`entity_type` 区分 **character** / location / faction / item / concept / event / creature / skill / rule / secret / legend / resource / other。别名内联在 `aliases` JSONB |
| 人物 | Character | `characters` | `entity_id` FK→CoreEntity。存人物特有字段（role, personality, desire, fear, secret, weakness, stance, voice_style 等） |
| 人物知识 | CharacterKnowledge | `character_knowledge` | 某角色对某事物的了解程度（unknown / rumor / partial / full / false_belief） |
| 剧情线 | PlotThread | `plot_threads` | 主线/支线/隐藏线/关系线/反派线/伏笔线。含起止章节、表层目标、隐藏真相、读者/作者已知状态 |
| 篇章纲 | OutlineArc | `outline_arcs` | 小说卷/篇章结构。含 arc_goal, core_conflict, entry_hook, midpoint_turn, climax, result, next_hook |
| 章节卡 | ChapterCard | `chapter_cards` | 单章的 goal, main_conflict, emotional_point, plot_function, must_happen / must_not_happen |
| 场景卡 | SceneCard | JSONB in `chapter_cards.scene_cards` | 场景级细化（不单独建表，MVP 放 JSONB） |
| 伏笔计划 | ForeshadowingPlan | `foreshadowing_plans` | 埋点→加强→收束 三阶段。含 surface_meaning, hidden_meaning |
| 揭示计划 | RevealPlan | `reveal_plans` | 秘密的分阶段揭示。含 target 和 reveal_stages |
| 长期记忆 | MemoryRecord | `memory_records` | 章节状态快照、事件记录、角色变化、知识变更、伏笔进展、资源变化 |
| 正文草稿 | WritingDraft | `writing_drafts` | 人工写作的章节正文。支持 version_number 递增的多版本管理 |
| RAG 分块 | RagChunk | `rag_chunks` | 正文分块 + embedding 向量 + 元信息标注（entity_ids, character_ids, thread_ids） |
| 事件 | Event | `core_entities` (entity_type="event") | 小说时间线事件。timeline_order 存于 content_json |
| 导入记录 | ImportRecord | `import_records` | 小说文件导入跟踪。不存原文 |
| 候选实体 | EntityCandidate | `entity_candidates` | AI 抽取的候选对象池，待用户确认后 promote 为正史 |
| 关系 | EntityRelation | `relationships` | 实体间关系（人物、势力、对象、通用）。source_id/target_id 为 UUID hex 字符串 |
| 修订快照 | EntityRevision | `entity_revisions` | CoreEntity 的编辑历史快照，支持 rollback |

## 2. 状态流转（Status Lifecycle）

遵循 **状态优先于删除**：用 `status` 字段，永不做硬 DELETE。

```
                    ┌─→ ignored
draft → candidate ──┤
                    ├─→ canonical ──→ deprecated
                    ├─→ conflicted
                    └─→ pending (waiting for user)

异步任务:
pending → running → done / failed / cancelled
```

### 候选对象建议动作（CandidateAction）

```
create_new           — 创建新正史 CoreEntity
merge_with_existing  — 合并到已有实体
alias_of_existing    — 标记为已有实体的别名
ignore               — 忽略
temporary_only       — 仅临时场景
needs_user_decision  — 等待用户决策
```

### 重要性级别（ImportanceLevel）

```
core > important > normal > temporary > alias
```

实体抽取阈值：严格模式 ≥0.75，正常模式 ≥0.45。

## 3. 关键揭示层级（Reveal）

| 层级 | 含义 |
|------|------|
| author_only | 仅作者知道 |
| hinted | 已埋伏笔 |
| revealed | 已揭示给读者 |
| fully_known | 读者和角色都已知 |

人物知识层级：unknown → rumor → partial → full；特殊：false_belief（角色自认为知道但实际错误）。

## 4. 系统三层（Architecture Layers）

| 层 | 模块 | 说明 |
|---|------|------|
| **事实层** | `project`, `world`, `memory` | 小说的正史事实。world 拥有 CoreEntity + Character + Event + EntityRelation；memory 拥有事件溯源快照 |
| **结构层** | `outline` | 把事实组织为可执行的剧情计划。PlotThread + OutlineArc + ChapterCard |
| **辅助层** | `rag`, `context`, `writing`, `imports` | 检索增强（RAG 分块）、上下文编译（跨模块组装 LLM context）、正文草稿承载、文件导入 |

模块通信：跨模块只能导入 `contracts.py` 和 `facade.py`。Facade/API 不写复杂业务逻辑。

## 5. 关键流程约定（Key Conventions）

### 候选→正史（Candidate → Canonical）
1. AI 生成 → 入 candidate 状态
2. 用户审查（确认/编辑/忽略/合并）
3. 用户确认后 promote 为 canonical
4. **从不自动 promote**

### 实体抽取（Entity Extraction）
- **不是 NER**。不抽取路人、普通道具、代词、一次性场景元素
- 只识别值得长期维护的**创作资产**
- AI 抽取结果直接以 `status="canonical"` 入库（content_json._meta 记录自动入库元数据）

### novel_id 隔离（Project Isolation）
- 所有 API 在 service 层强制项目隔离
- 不跨 novel_id 合并关系、别名或正史对象
- BaseCRUDService 通过 keyword-only `novel_id` 参数强制该约束

### 别名管理（Aliases）
- 别名统一存储在 `core_entities.aliases` JSONB
- 标记为 `alias_of_existing` 而非创建新实体
- 别名类型：name / title / nickname / alias / translation / abbreviation

### 嵌入与向量（Embedding）
- 向量字段在 PostgreSQL 用 pgvector，在 SQLite 测试模式存 JSON 序列化文本
- embedding 失败不阻塞索引（chunk 仍创建，检索退化到纯文本）

### 文件导入（Import）
- 白名单格式：.txt / .epub / .html / .htm / .mobi / .azw3
- 文件限制 ≤50MB
- 不信任上传文件名（os.path.basename 保护）
- 不把原文存入 import_records

## 6. 核心枚举速查（Key Enums Reference）

详见 `shared/enums.py`。以下是关键枚举值：

| 枚举 | 值 |
|------|-----|
| ObjectStatus | draft, candidate, canonical, deprecated, ignored, conflicted, pending |
| EntityType | character, location, faction, item, concept, event, creature, skill, rule, power_system, secret, legend, resource, other |
| ImportanceLevel | core, important, normal, temporary, alias |
| RevealLevel | author_only, hinted, revealed, fully_known |
| KnowledgeLevel | unknown, rumor, partial, full, false_belief |
| CharacterRole | protagonist, antagonist, supporting, minor, mentor, love_interest, comic_relief, foil, narrator, cameo |
| Visibility | author_only, author_safe, reader_known, public |
| TaskStatus | pending, running, done, failed, cancelled |
| RelationType | parent_of, child_of, spouse_of, sibling_of, friend_of, rival_of, enemy_of, ally_of, mentor_of, student_of, lover_of, master_of, servant_of, member_of, leader_of, allied_with, at_war_with, trading_with, belongs_to, created_by, located_at, contains, controls, related_to, opposes, supports |
| ForeshadowingStatus | planned, seeded, reinforced, paid_off, abandoned |

## 7. AI 创作提示（Prompts）

系统使用 **7 个 prompt**（非复杂多 Agent）：

| Prompt | 用途 |
|--------|------|
| `structure_world_character.md` | 世界与人物结构生成 |
| `structure_plot.md` | 剧情结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 |
| `structure_review_memory.md` | 结构复查与状态抽取 |
| `structure_extraction.md` | 从章节正文抽取世界对象候选 |
| `extract_chapter_scene.md` | 从正文提取章节卡字段 |
| `extract_character.md` | 从正文提取人物档案字段 |

所有 prompt 通过 `infrastructure/llm/prompt_loader.py` 从 `backend/prompts/` 加载。

Prompt 合并策略：一次 prompt 输出多个 JSON 数组，入库时分别写入对应表。不按数据库表拆 prompt。

## 8. 技术栈概览（Tech Stack）

| 层 | 技术 |
|----|------|
| 后端 | Python 3.13 + FastAPI + async SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL 17 + pgvector + pg_trgm |
| LLM | OpenAI 兼容 API（支持结构化输出 response_format） |
| 任务队列 | PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED） |
| 前端 | Vanilla JS + CSS 变量 + Proxy 响应式状态 |
| 测试 | pytest + pytest-asyncio + SQLite 内存引擎 |
| 容器 | Docker Compose（PostgreSQL 17 + pgvector） |

## 9. 相关文档索引（Document Index）

| 文档 | 内容 |
|------|------|
| `docs/00_整体设计.md` | 系统三层结构、模块职责、目录结构 |
| `docs/01_数据库设计.md` | 16 张表完整字段定义 |
| `AGENTS.md` | AI agent 禁止事项、命令速查、命名规范 |
| `development-guide.md` | 开发命令、模块开发规则 |
| `testing-guide.md` | 测试约定（unit/integration/e2e） |
| `docs/adr/` | 架构决策记录 |
| `shared/enums.py` | 完整枚举定义 |
| `shared/constants.py` | 全局常量（分页/阈值/权重） |
| `modules/world/CLAUDE.md` | world 模块禁止事项 |
| `modules/imports/CLAUDE.md` | imports 模块禁止事项 |
