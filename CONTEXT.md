# CONTEXT.md — 领域词汇与当前边界

本文件是当前代码的领域词汇表，不承载历史实施计划或未来架构设想。系统架构、数据库和
模块 API 的权威来源依次为 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块
README、ORM 模型与 Alembic migration。当前文档范围由
`docs/architecture/architecture-documents.toml` 登记；该清单只防遗漏，不改变上述事实
优先级。

## 1. 核心资产

| 中文概念 | 英文 | 当前承载 | 含义 |
|---|---|---|---|
| 核心实体 | CoreEntity | `core_entities` | 世界对象身份根表。`entity_type` 区分人物、地点、势力、物品、事件、规则、秘密等；统一保存名称、摘要、可见性、状态、扩展 JSON 与图片版本元数据。 |
| 对象图片 | World object image | 私有 S3 `world-objects` bucket + CoreEntity 图片元数据 | 可选的作者识别辅助资料；浏览器只通过 owner + `novel_id` 门禁读取缩略图或完整图，不取得 object key。 |
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
| 世界书类别与工作稿 | `world_bible_categories` / `world_bible_page_drafts` | 自定义类别只定义展示信息；工作稿是可丢弃的服务器编辑快照，发布后才以页面 revision 进入已采用世界观。 |
| 世界书修订与投影 | `world_bible_page_revisions` / `world_bible_page_projections` | 页面保存点与可编译的派生投影；投影是缓存，不是事实源。 |
| 世界观简介 | `world_bible_synopsis_heads` / `world_bible_synopsis_revisions` | 仅作者模式可用的 P1 LLM 派生背景；revision 不可变且可回滚，head 只协调 stale、pin、刷新任务与持久化自动授权。它不替代确定性 `World Core Brief`，reader/character 不得读取。 |
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
| 小说总纲 | `story_outline_heads` / `story_outline_revisions` | outline 拥有的小说级上位结构资产；按 `World → StoryOutline → OutlineArc → Scene` 约束粒度。revision 不可变，head 以 base/current CAS 指向当前版；手工采用总纲不会创建剧情线、篇章纲、Scene、伏笔或揭示。 |
| 剧情线 / 篇章纲 | `plot_threads` / `outline_arcs` | 组织可执行的剧情结构；PlotThread 是作者侧信息推进聚合根，篇章纲只引用既有剧情线。 |
| Scene | `scenes` | 最小叙事单元，包含逻辑顺序、结构字段、来源和结构整理 metadata。 |
| Scene 章节映射 | `scene_chapter_links` | Scene 与章节的轻量关联。 |
| Scene 物理片段 | `scene_spans` | 从 `scenes.scene_chunks` 派生的只读索引，保存章节和 offset/paragraph 边界。 |
| Scene 建议决定 | `scene_fusion_suggestions` | 承载 Phase 1c 融合决定和重复提取的 replacement 审查；未采用的替换候选只保存在 suggestion payload，不是 active Scene，不进入下游事实链。 |
| 伏笔 / 揭示 | `foreshadowing_plans` / `reveal_plans` | PlotThread 信息推进的底层投影与兼容读模型；作者侧不再作为独立顶层模块。 |
| 正文版本 | `writing_drafts` | 章节正文的多版本承载；普通正文只有工作稿/已发布成熟度，未采用 AI 文本以兼容 `candidate` 保存为待处理建议，并保存 conflict snapshot 与生成 provenance。 |
| 写作冲突检查 | `writing_conflict_checks` / `writing_conflict_items` | 规则检查、证据、AI 软判断和建议的记录；不自动修改正文或已采用资产。 |
| 导入记录 | `import_records` | 文件导入元信息；不保存上传原文。 |
| 导入章节 | `imported_chapters` | 仍由 world 事件/关系/版本来源 FK 引用的章节正文表；上传主路径以 WritingDraft 作为编辑承载。 |
| 深度导入 | imports workflow | 受控多阶段工作流：启动时持久化一次批量授权，确定性 Scene 规划/切分/补全后抽取世界对象、别名/关系与结构资产；异常结果进入待处理。 |

`chapter_cards` 不是当前 ORM 表。不要把旧章节卡 JSON 或历史计划当作 Scene 的事实来源。

## 4. 记忆、检索、上下文与地图册

| 概念 | 当前承载 | 含义 |
|---|---|---|
| 记忆事件 / 快照 | `memory_events` / `memory_scene_checkpoints` / `memory_scene_snapshots` / `memory_snapshots` | Scene 是唯一基础阶段；历史状态只由带 Scene 锚点的 MemoryEvent 确定性重放，禁止用当前 World 补历史。 |
| 字段差分 | `delta_log` | memory 拥有的结构化 before/after 记录；不替代 TextArchive。 |
| RAG 分块 | `rag_chunks` | 文字、来源、offset、Scene/Span、可见性、索引版本和 embedding 状态。 |
| AI 参考资料确认 | `context_confirmations` | 手动 AI 操作前用户确认过的资料选择、结果引用与 `compile_options` 摘要。 |
| 自动上下文快照 | `context_snapshots` | 真实 LLM 调用的审计记录，保存摘要、hash、预算、资产选择与结果引用；完整 rendered context 仅显式保留。 |
| 编译上下文 | CompiledContext | evidence compilation 按 scope、视角、预算和候选模式选择、裁剪并解释资料的中间表示。 |
| AI 地图册 | `map_atlas_runs` / `map_atlas_nodes` / `map_atlas_pages` / `map_atlas_annotations` | 基于已确认资料生成的候选图片及作者采用后的画廊；不作为时间化世界事实。 |

地图册经既有 generation-background operation `world.map_atlas.generate` 取得 author-full 的
canonical world background，并以 RAG `map_atlas` purpose 补充已确认正文和 Scene。工作稿仅在
作者显式开启时加入，候选对象始终排除。每次 run 固化 secret-free context snapshot、source
manifest 与 hash；manifest 按真实来源类型和 ID 记录 context/world loader 计算的内容 hash，
不信任文本模型回传的来源 hash。候选图分别记录直接支持、AI 视觉补全和资料冲突。采用图片只改变地图册
画廊，不会写回 World、Memory 或正文事实。

图片固定由 `gpt-image-2` 生成并存入私有 S3。浏览器通过 owner 与 `novel_id` 双门禁的后端
接口读取。项目永久删除以 share/exclusive project lock 封住晚到上传，并用不依赖项目 FK 的
全局前缀清理任务移除对象。

世界对象图片同样不进入 PostgreSQL：`core_entities` 只保存版本与更新时间，响应只公开
`has_image`。单机 MinIO 将地图册和对象图片放在两个私有 bucket；对象软废弃、融合和别名化
不移动或删除图片，项目永久删除才排入对应项目前缀清理。

Evidence indexing 通过 nullable `scene_span_id` 关联 Scene 物理片段，但不建跨模块硬 FK；
compilation 负责“选、裁、确认、追踪”。imports、writing 等模块只能通过 evidence facade 或
contract 消费它们。

## 5. 状态、采用与隔离

- **Account / Owner**：`accounts` 是公开浏览器身份根；每个项目只有一个
  `owner_id → accounts.id`。邮箱与 Authing 微信是互斥主身份，不自动绑定或合并。
- **作者展示状态**：结构化资产统一投影为 `display_state = review / active / archived`，界面分别显示“待处理 / 已采用 / 历史”。`display_state` 是领域派生语义，不替代兼容期原始 `status` 字段。
- **正文成熟度**：正文使用“工作稿 / 已发布”；Scene 等确有编辑生命周期的内容可显示工作稿。未采用的 AI 正文是待处理建议，不是普通工作稿。
- **来源与注意原因**：`source`、`attention_reasons` 和 `suggested_action` 与生命周期分离。`conflicted`、低置信、POV 风险、`needs_review` 是注意原因，不是新的主状态。
- **内部状态**：`candidate` / `proposal` / `canonical`、地图册页面 checkpoint、任务 `pending/running/failed` 和审计 confirmation/snapshot 可用于实现和诊断，但不得作为并列的作者心智模型。
- **授权自动流水线**：深度导入等流水线必须在启动时持久化授权策略与范围；规则明确且可回滚的结果可自动采用，冲突、低置信和无法消歧结果进入待处理，完成结果按已采用/待处理/未采用汇总。
- **历史状态**：`deprecated` / `ignored` / `merged` / `rolled_back` 等进入历史并默认从主工作区隐藏；除项目永久删除和地图等明确操作外不默认硬删除。
- **novel_id**：项目隔离键。任何跨模块 facade、查询、合并、任务和恢复流程都不得跨项目
  读取或写入资产。
- **Schema guard**：API、LLM 结构化输出和入库都必须经过 Pydantic/调用方校验；不得
  `eval`、`exec` 或直接持久化未校验的 LLM 文本。

## 6. RP 互动旅程

`interaction` 是独立于作者创作资产三层的私人故事领域。它不读取或写入 World、Outline、
RAG、writing 或 memory；每个旅程以一个隐藏的 `project_kind=interaction` 项目作为
`novel_id + owner_id` 隔离根。

| 概念 | 当前承载 | 含义 |
|---|---|---|
| 互动旅程 | `interaction_journeys` | RP 故事容器，保存标题、旅程级开关、当前选中叶、selection epoch、回顾 head 和活动状态。 |
| 消息节点 | `interaction_message_nodes` | 不可变的用户/模型内容节点；修改、重新生成和其他分支通过新 sibling 表达，不原地改写历史。 |
| 分支选择 | `interaction_branch_selections` | 每个分岔父节点唯一的当前选中子节点；只有代码计算出的选中路径进入 Prompt、回顾和默认导出。 |
| 生成 attempt | `interaction_generation_attempts` | 排队、上下文准备、流式缓冲、停止、失败和完成的领域状态；任务 transport 终态不能替代它。 |
| 分段概要 | `interaction_summary_segments` | 按 token 规模压缩已选故事的不可变记忆段，记录覆盖锚点和脱敏 producer provenance。 |
| 总回顾 | `interaction_overview_revisions` | 世界与起点、玩家角色、当前局面、人物势力、转折、未决事项和必须记住内容的活动总概要；revision 不可变，journey head 选择当前版。 |
| 看海模式 | interaction 确定性循环 | 用户留在故事页且开关开启时，逐段提交有界 story attempt；不是自治 Agent，也不让模型自行调用工具。 |

旅程“正史”只表示当前代码级选中路径，不等于原作品正史。未选 sibling、失败残段和模型训练
先验都不自动成为已经发生的历史；用户明确修正优先，并由后续回顾收敛。RP 第一版背景来自
用户开场、模型训练知识、选中历史和有效总回顾，不支持原作导入或按章节分叉。

## 7. 受控 LLM 工作流

项目不构建自治或多 Agent 运行时。`infrastructure.llm.agent_step_harness` 提供
`ManagedLLMStep`、schema/output guard、预算、超时、journal 和错误分类：

- step 可声明 read、suggest、draft 或 act-with-confirmation 权限；`autonomous` 被拒绝。
- orchestrator 负责阶段顺序、并发、恢复、降级和写入；step 不自主选择工具或跨模块编排。
- 运行时 Prompt、调用方和输出契约以 `docs/prompts/Prompt体系设计.md` 为准，不在本文件
  固定 Prompt 数量或旧文件清单。
- 账号级模型连接由 account 的 `account_llm_credentials` 承载每个 provider 的加密 Key，
  并复用 owner 唯一的 `global_llm_defaults.provider_id` 选择当前 provider。新业务调用的
  provider、model 与 Key 只来自项目 owner 的已验证账号连接及固定 provider 模板；
  DeepSeek `deepseek-v4-flash` 是默认模板，Kimi `kimi-k3` 在真实兼容门禁通过并显式启用前
  不可达。
- `projects.settings.llm` 只保留非 secret 的项目工作流兼容设置，不能覆盖账号连接的
  provider/model/Key。可恢复任务的 project snapshot 冻结提交时的 provider/model、
  非 secret 参数和项目工作流设置，但不保存 Key；恢复时使用同 provider 当前轮换后的
  账号 Key，provider 已清除时 fail-closed。
- 旧 `global_llm_defaults` 继续提供非 secret 兼容默认/展示字段，不是运行时凭据真相源。
  业务 provider 字段不从 `LLM_*` 环境变量继承，显式测试 override 仅用于测试路径。

## 8. 模块边界与文档使用

当前业务模块为 `account`、`project`、`world`、`memory`、`outline`、`story`、
`evidence`、`writing`、`imports`、`interaction`；RAG 索引与 Context 编译/确认归 evidence，
账户连接与全局偏好归 account，项目偏好及有效配置
归 project；`map` 是 world 子系统，
`infrastructure/tasks` 是共享基础设施。`interaction` 是 RP 私人故事领域，不属于作者
创作资产的事实层、结构层或辅助层。

生产业务代码只能跨模块依赖 `contracts.py`、`facade.py` 或已注册 DI port。应用组合根、
测试 fixture 与 migration 的模型导入是受限例外，不可据此在业务层直接依赖其他模块内部
models/repositories/services。

旧 plan、审计快照和历史术语只用于追溯。判断当前行为时，先读对应模块 README、ORM、
migration 与测试，再更新此词汇表。跨模块语义或资产所有权发生变化时，同一开发轮必须按
`docs/architecture/documentation-maintenance.md` 更新受影响文档，并运行
`make docs-check BASE_REF=origin/main`；无语义变化也要在 PR 中显式记录核对结论。
