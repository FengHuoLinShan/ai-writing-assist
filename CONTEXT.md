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
| 场景卡 | Scene | `scenes` | 最小叙事单元。旧 `chapter_cards.scene_cards` JSONB 仅作历史兼容/冗余上下文，不是当前权威来源 |
| 伏笔计划 | ForeshadowingPlan | `foreshadowing_plans` | 埋点→加强→收束 三阶段。含 surface_meaning, hidden_meaning |
| 揭示计划 | RevealPlan | `reveal_plans` | 秘密的分阶段揭示。含 target 和 reveal_stages |
| 长期记忆 | MemoryRecord | `memory_records` | 章节状态快照、事件记录、角色变化、知识变更、伏笔进展、资源变化 |
| 正文草稿 | WritingDraft | `writing_drafts` | 人工写作的章节正文。支持 version_number 递增的多版本管理 |
| RAG 分块 | RagChunk | `rag_chunks` | 正文分块 + embedding 向量 + 元信息标注（entity_ids, character_ids, thread_ids） |
| 事件 | Event | `core_entities` (entity_type="event") | 小说时间线事件。timeline_order 存于 content_json |
| 导入记录 | ImportRecord | `import_records` | 小说文件导入跟踪。不存原文 |
| 候选创作资产 | Candidate Creative Asset | 多表状态表达 | AI 或系统从正文中提取出的、具备长期维护价值但尚未被用户确认的结构化资产。可对应 CoreEntity、Relation、Event、Scene、PlotThread 等对象；默认进入 candidate 或等价待确认状态，可进入工作上下文但不进入正史上下文 |
| ~~候选实体~~ | ~~EntityCandidate~~ | ~~`entity_candidates`~~ | 已废弃。候选对象不再使用独立候选表，改由对应资产表的状态与自动入库元数据表达 |
| 关系 | EntityRelation | `entity_relations` | 实体间关系（人物、势力、对象、通用）。source_id/target_id 为 UUID hex 字符串 |
| 修订快照 | EntityRevision | `entity_revisions` | CoreEntity 的编辑历史快照，支持 rollback |

## 2. 状态流转（Status Lifecycle）

遵循 **状态优先于删除**：业务运行时默认用 `status` 字段表达废弃/忽略/冲突。项目永久删除和 demo 开发库重建可以硬 DELETE。

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

模块通信：跨模块生产代码只能导入 `contracts.py`、`facade.py` 或 DI port。`api.py` 是 HTTP 入口，不作为模块间调用接口。Facade/API 不写复杂业务逻辑。

## 5. 关键流程约定（Key Conventions）

### 候选→正史（Candidate → Canonical）
默认流程：
1. AI 生成 → 入 candidate / proposal 状态
2. 用户审查（确认/编辑/忽略/合并）
3. 用户确认后 promote 为 canonical
4. 后台任务不在无用户授权的情况下自动 promote

例外：用户明确启动的自动流水线（如深度导入）可批量写入候选创作资产，但必须先通过 Pydantic schema 校验，并保留来源、可编辑/可回滚标记。

### 工作上下文（Working Context）
工作上下文是 AI 流水线内部使用的临时上下文层，用于长文档批量导入、后续结构分析和跨阶段抽取。它可以读取正史资产、草稿资产、候选创作资产、证据片段、置信度和来源依赖，但不等同于正史上下文。

- 长文档导入的第二轮/后续阶段可以基于候选创作资产继续抽取，避免等待用户逐条确认后才推进剧情线、篇章纲、关系和伏笔分析
- 工作上下文中的候选资产只能作为待确认依据，不作为用户确认后的硬事实
- 由候选资产派生的 PlotThread、OutlineArc、EntityRelation、ForeshadowingPlan、RevealPlan 等下游资产必须保持 draft / candidate / pending 等待确认状态
- 下游资产必须记录来源依赖；当依赖的候选资产被拒绝、合并或改名时，下游资产需要标记为需复核或重新计算
- 面向正式写作、最终一致性校验和用户确认后的输出时，应使用正史上下文，而不是直接使用未确认的工作上下文

实现方向：
1. 近期：在上下文编译入口提供显式模式（如 `context_mode="canonical" | "working"`）。默认使用 canonical；深度导入、批量抽取和结构分析等内部流水线显式请求 working。
2. 后续：当候选审查、回放和可解释性需求稳定后，引入持久化上下文快照表，记录 task_id、phase、context_mode、included_asset_ids、rendered_context 或摘要、prompt_hash、created_at，用于审计、复现和问题定位。
3. 持久化快照只记录当次 AI 调用使用过的上下文视图，不替代正史资产表，也不改变 candidate → canonical 的用户确认语义。
4. 第一版不新增上下文快照表；用户确认后的 AI 参考资料只在生成结果或任务 `_meta` 中保存摘要与资产 ID（context_mode、scope、range、reveal_mode、included/excluded asset ids、asset_counts、include_pending_objects、user_note、compiled_at），不保存完整 rendered context。
5. 手动 AI 操作应先创建 AI 参考资料确认记录，再把 `context_confirmation_id` 传给正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象等接口。确认记录第一版保存摘要与资产 ID，后续可扩展为持久化上下文快照与回放入口。
6. `/api/context/confirm` 负责按用户当前选择重新编译上下文并创建确认记录，而不是只保存前端已预览结果；这样可以避免预览与最终执行之间的数据漂移。

用户控制边界：
- 正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象必须先展示并确认“AI 参考资料”，再执行 LLM 调用
- 深度导入不插入手动上下文确认；它保持自动化体验，由系统内部维护 working context，并在完成后集中展示结果、降级原因和待复核资产
- 上下文页保留为高级预览/调试台；手动 AI 操作应在自身流程中打开参考资料确认界面，而不是要求用户跳转到上下文页

“AI 参考资料”第一版可控项：
- 章节/Scene 范围
- 揭示模式（作者安全、作者全知、读者已知、角色视角）
- 是否包含待确认对象（内部状态为 candidate 的候选创作资产）
- 排除本次不想引用的世界对象、人物、剧情线、伏笔
- 本次 AI 额外注意事项

“AI 参考资料”弹窗编辑规则：
- 弹窗内编辑的是参考资料选择规则和本次补充说明，不直接编辑编译后的 Markdown 上下文正文
- 用户调整范围、揭示模式、是否包含待确认对象或排除资产后，通过“重新整理参考资料”重新调用上下文编译并刷新预览
- 如用户发现结构化资产本身错误，应跳转或弹出对应资产编辑表单；保存后再重新整理参考资料
- “本次 AI 额外注意事项”可作为临时高优先级上下文参与本次调用，并记录到 `_meta.user_note`，但不写入正史资产
- 第一版不支持手动粘贴/改写完整上下文 Markdown，避免产生脱离结构化资产体系的临时事实

用户可见文案应使用“待确认对象”，不直接暴露“候选资产 / candidate asset”等工程术语；代码、数据库和文档中的领域术语仍可使用 candidate / 候选创作资产。

待确认对象默认值：
- 正文生成默认不包含待确认对象
- 手动剧情分析、手动剧情结构生成、手动补抽世界对象默认包含待确认对象，并在界面提示“包含待确认对象，结果需复核”
- 深度导入内部自动使用待确认对象推进后续阶段，但不打断用户逐步确认

待确认对象变更后的影响处理：
- 第一版只标记受影响结果，不自动级联重算或覆盖用户已编辑内容
- 当生成结果或任务 `_meta.included_asset_ids` 引用了被忽略、合并、改名或提升的待确认对象时，相关结果应标记为 `needs_review` 或 `stale_context`
- `ready` 表示当前参考资料仍有效；`needs_review` 表示结果依赖待确认对象，需要用户复核；`stale_context` 表示依赖对象已发生结构性变化，建议重新分析或重新生成
- 用户可手动触发“用当前 AI 参考资料重新分析/重新生成”

### 实体抽取（Entity Extraction）
- **不是 NER**。不抽取路人、普通道具、代词、一次性场景元素
- 只识别值得长期维护的**创作资产**
- 深度导入等用户确认启动的抽取结果默认作为候选创作资产入库，`content_json._meta` 记录自动入库元数据；用户确认后再提升为正史

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

系统使用 **8 个 prompt**（非复杂多 Agent）：

| Prompt | 用途 |
|--------|------|
| `structure_world_character.md` | 世界与人物结构生成 |
| `structure_plot.md` | 剧情结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 |
| `structure_review_memory.md` | 结构复查与状态抽取 |
| `structure_extraction.md` | 从章节正文抽取世界对象候选 |
| `extract_chapter_scene.md` | 从正文提取章节卡字段 |
| `extract_character.md` | 从正文提取人物档案字段 |
| `scene_segmentation.md` | 深度导入中的 Scene 切分 |

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
| `docs/01_数据库设计.md` | 活跃表完整字段定义（已移除废弃模块表） |
| `AGENTS.md` | AI agent 禁止事项、命令速查、命名规范 |
| `development-guide.md` | 开发命令、模块开发规则 |
| `testing-guide.md` | 测试约定（unit/integration/e2e） |
| `docs/adr/` | 架构决策记录 |
| `shared/enums.py` | 完整枚举定义 |
| `shared/constants.py` | 全局常量（分页/阈值/权重） |
| `modules/world/CLAUDE.md` | world 模块禁止事项 |
| `modules/imports/CLAUDE.md` | imports 模块禁止事项 |
