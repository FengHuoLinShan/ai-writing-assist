# CONTEXT.md — 领域词汇与当前边界

本文件是当前代码的领域词汇表，不承载历史实施计划或未来架构设想。系统架构、数据库和
模块 API 的权威来源依次为 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块
README、ORM 模型与 Alembic migration。

## 1. 核心资产

| 中文概念 | 英文 | 当前承载 | 含义 |
|---|---|---|---|
| 核心实体 | CoreEntity | `core_entities` | 世界对象身份根表。`entity_type` 区分人物、地点、势力、物品、事件、规则、秘密等；统一保存名称、摘要、可见性、状态和扩展 JSON。 |
| 类型化档案 | Entity Profile | `species_profiles`、`faction_profiles`、`location_profiles`、`rule_profiles`、`item_profiles`、`secret_profiles` | 高频对象类型的 1:1 强字段扩展。 |
| 通用档案 | GenericEntityProfile | `generic_entity_profiles` | 没有专属强表的实体 profile；配合 `entity_profile_templates` 描述 schema/展示。 |
| 人物 | Character | `characters` | `entity_id → core_entities.id` 的人物扩展。 |
| 人物知识 | CharacterKnowledge | `character_knowledge` | 角色对特定目标的稀疏知识覆盖；不预建角色×世界对象矩阵。 |
| 事件 | Event | `events` | `entity_id → core_entities.id` 的事件扩展，保存时间顺序、来源章节和地点。 |
| 关系 | EntityRelation | `entity_relations` | 两个 CoreEntity 间的关系边，带来源、强度、状态和复核审计。 |
| 别名 | Alias | `core_entities.content_json.aliases` | 内联到已有对象；不是独立实体或数据表。 |
| 目标引用 | TargetRef | `shared.target_ref` | 跨模块定位事实的 `target_type` / `target_id` / `target_path` 结构。 |
| 文本归档 | TextArchive | `text_archive` | 长文本字段的回滚归档。 |
| 实体修订 | EntityRevision | `entity_revisions` | 兼容型实体快照；活跃回滚优先查 TextArchive。 |

`canonical` 关系边以 `(novel_id, source_id, target_id, relation_type)` 作为 PostgreSQL
业务幂等键。所有对象与关系操作必须保持 `novel_id` 隔离。

## 2. 世界书、可见性与待处理资产

| 概念 | 当前承载 | 含义 |
|---|---|---|
| 世界书页 | `world_bible_pages` | 作者可编辑的世界观组织页；它引用和解释事实，但不拥有 CoreEntity/关系等已采用事实。 |
| 世界书修订与投影 | `world_bible_page_revisions` / `world_bible_page_projections` | 页面保存点与可编译的派生投影；投影是缓存，不是事实源。 |
| 页面模板 | 代码注册表 + `template_key` / `template_version` | 内置模板目前不使用 `world_bible_page_templates` 数据表。 |
| 生成模板 | `generation_prompt_templates` / revisions | 项目级 Prompt 模板及版本；运行时仍受固定 scaffold 与 Pydantic 输出契约约束。 |
| 知识标签 | `knowledge_tags` 及其授予/排除表 | 用标签表达群体知识；`CharacterKnowledge` 只记录偏离默认知识的个体覆盖。 |
| 读者揭示策略 | `reader_reveal_policies` | Reader 视角的揭示位置和状态，不等同于人物是否知道。 |
| 知识可见性 | `knowledge_visibility_policies` | 事实的 public/tag/private 可见性策略。 |
| 创设建议 | `creation_suggestion_queue` | 会改动结构化资产的普通 AI 建议先进入此队列，作者采用后才调用 world 领域命令写入当前有效资产。 |
| 冲突队列 | `conflict_check_queue` | 世界设定冲突与叙事风险的待处理项；它是当前表，不是未来预留。 |

## 3. 结构、正文与导入

| 概念 | 当前承载 | 含义 |
|---|---|---|
| 剧情线 / 篇章纲 | `plot_threads` / `outline_arcs` | 组织可执行的剧情结构。 |
| Scene | `scenes` | 最小叙事单元，包含逻辑顺序、结构字段、来源和结构整理 metadata。 |
| Scene 章节映射 | `scene_chapter_links` | Scene 与章节的轻量关联。 |
| Scene 物理片段 | `scene_spans` | 从 `scenes.scene_chunks` 派生的只读索引，保存章节和 offset/paragraph 边界。 |
| 伏笔 / 揭示 | `foreshadowing_plans` / `reveal_plans` | 结构资产，带来源与状态。 |
| 正文版本 | `writing_drafts` | 章节正文的多版本承载；普通正文只有工作稿/已发布成熟度，未采用 AI 文本以兼容 `candidate` 保存为待处理建议，并保存 conflict snapshot 与生成 provenance。 |
| 写作冲突检查 | `writing_conflict_checks` / `writing_conflict_items` | 规则检查、证据、AI 软判断和建议的记录；不自动修改正文或已采用资产。 |
| 导入记录 | `import_records` | 文件导入元信息；不保存上传原文。 |
| 导入章节 | `imported_chapters` | 仍由 world 事件/关系/版本来源 FK 引用的章节正文表；上传主路径以 WritingDraft 作为编辑承载。 |
| 深度导入 | imports workflow | 受控多阶段工作流：启动时持久化一次批量授权，确定性 Scene 规划/切分/补全后抽取世界对象、别名/关系与结构资产；异常结果进入待处理。 |

`chapter_cards` 不是当前 ORM 表。不要把旧章节卡 JSON 或历史计划当作 Scene 的事实来源。

## 4. 记忆、检索、上下文与地图

| 概念 | 当前承载 | 含义 |
|---|---|---|
| 记忆事件 / 快照 | `memory_events` / `memory_snapshots` | 事件溯源与阶段性全景快照。 |
| 字段差分 | `delta_log` | memory 拥有的结构化 before/after 记录；不替代 TextArchive。 |
| RAG 分块 | `rag_chunks` | 文字、来源、offset、Scene/Span、可见性、索引版本和 embedding 状态。 |
| AI 参考资料确认 | `context_confirmations` | 手动 AI 操作前用户确认过的资料选择和结果引用。 |
| 自动上下文快照 | `context_snapshots` | 真实 LLM 调用的审计记录，保存摘要、hash、预算、资产选择与结果引用；完整 rendered context 仅显式保留。 |
| 编译上下文 | CompiledContext | context 模块按 scope、视角、预算和候选模式选择、裁剪并解释资料的中间表示。 |
| 地图观察 | `map_observations` | 带时间/空间锚点和证据的观察层；尚未转化为 Fact 的可操作 observation 在作者界面显示为待处理。 |
| 地图事实 | `map_facts` | 经领域规则或作者采用后形成的时间化地图事实，作者界面显示为已采用。 |
| 地图基础资产 | `map_configs`、tiles、地点布局/绑定、地形、标记、势力范围表 | world/map 子系统；完整表清单在 `docs/01_数据库设计.md`。 |

RAG 通过 nullable `scene_span_id` 关联 Scene 物理片段，但不建跨模块硬 FK。context
负责“选、裁、确认、追踪”，RAG 负责“找”；imports、writing 等模块只能通过 facade 或
contract 消费它们。

## 5. 状态、采用与隔离

- **作者展示状态**：结构化资产统一投影为 `display_state = review / active / archived`，界面分别显示“待处理 / 已采用 / 历史”。`display_state` 是领域派生语义，不替代兼容期原始 `status` 字段。
- **正文成熟度**：正文使用“工作稿 / 已发布”；Scene 等确有编辑生命周期的内容可显示工作稿。未采用的 AI 正文是待处理建议，不是普通工作稿。
- **来源与注意原因**：`source`、`attention_reasons` 和 `suggested_action` 与生命周期分离。`conflicted`、低置信、POV 风险、`needs_review` 是注意原因，不是新的主状态。
- **内部兼容状态**：`candidate` / `proposal` / `canonical`、地图 observation/fact 状态、任务 `pending/running/failed` 和审计 confirmation/snapshot 可继续用于实现、接口兼容和诊断，但不得作为并列的作者心智模型。
- **授权自动流水线**：深度导入等流水线必须在启动时持久化授权策略与范围；规则明确且可回滚的结果可自动采用，冲突、低置信和无法消歧结果进入待处理，完成结果按已采用/待处理/未采用汇总。
- **历史状态**：`deprecated` / `ignored` / `merged` / `rolled_back` 等进入历史并默认从主工作区隐藏；除项目永久删除和地图等明确操作外不默认硬删除。
- **novel_id**：项目隔离键。任何跨模块 facade、查询、合并、任务和恢复流程都不得跨项目
  读取或写入资产。
- **Schema guard**：API、LLM 结构化输出和入库都必须经过 Pydantic/调用方校验；不得
  `eval`、`exec` 或直接持久化未校验的 LLM 文本。

## 6. 受控 LLM 工作流

项目不构建自治或多 Agent 运行时。`infrastructure.llm.agent_step_harness` 提供
`ManagedLLMStep`、schema/output guard、预算、超时、journal 和错误分类：

- step 可声明 read、suggest、draft 或 act-with-confirmation 权限；`autonomous` 被拒绝。
- orchestrator 负责阶段顺序、并发、恢复、降级和写入；step 不自主选择工具或跨模块编排。
- 运行时 Prompt、调用方和输出契约以 `docs/prompts/Prompt体系设计.md` 为准，不在本文件
  固定 Prompt 数量或旧文件清单。
- 项目级 LLM Profile 位于 `projects.settings.llm`，全局默认和作者偏好位于 settings 模块。
  有效业务配置按项目 → 全局 → 系统默认物化；业务 provider 字段不从 `LLM_*` 环境变量
  继承，显式测试 override 仅用于测试路径。

## 7. 模块边界与文档使用

当前业务模块为 `project`、`world`、`memory`、`outline`、`rag`、`context`、`writing`、
`imports`、`settings`；`map` 是 world 子系统，`infrastructure/tasks` 是共享基础设施。

生产业务代码只能跨模块依赖 `contracts.py`、`facade.py` 或已注册 DI port。应用组合根、
测试 fixture 与 migration 的模型导入是受限例外，不可据此在业务层直接依赖其他模块内部
models/repositories/services。

旧 plan、审计快照和历史术语只用于追溯。判断当前行为时，先读对应模块 README、ORM、
migration 与测试，再更新此词汇表。
