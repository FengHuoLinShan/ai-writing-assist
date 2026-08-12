# Module: world / 世界对象与关系管理模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

对象包括地点、组织、物品、事件、规则、能力体系、秘密、传说、资源、人物引用。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- 手动创建对象默认直接写入 `status="canonical"`，并保留 `created_by` / `approved_by`；显式传入 `draft` / `candidate` 的旧调用仍保持原状态
- 正文世界对象自动识别统一由 imports 深度导入体系负责：首次导入使用
  `POST /api/imports/deep`，已有 Scene 的补抽使用
  `POST /api/imports/stages/world-objects`（Phase 2a/2b）
- AI 抽取对象以 `status="candidate"` 入库，等待用户确认、合并或忽略；不自动提升为正史
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSONB 字段
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入 `content_json.aliases`，单条别名携带 `status/source/workflow_id/scene_id/confidence/needs_review` 元数据
- 待复核别名可在确认前修改目标对象、别名文本和别名类型；来源、workflow、Scene、引用和置信度作为只读证据保留
- “待处理”入口按对象 / 别名 / 关系三个子 tab 处理复核队列；对象库、别名、关系页仍保留全量管理能力
- `link_to_existing` / `alias_of_existing` 候选只有在目标已解析为同项目已采用对象 ID 且不是源候选自身时，才按“已有对象”聚合展示；目标仅有名称、指向待处理对象或指向自身时仍留在普通待处理队列。确认后源候选标记 `status="merged"` 并记录 `resolved_as="alias"`，不硬删除、不提升为正史
- 深度导入 Phase 2b 发现的关系写入 `entity_relations(status="candidate")`，两端可解析到 canonical / draft / candidate 工作对象
- 待确认关系可在确认前修改源对象、目标对象、关系类型、描述和强度；引用和来源章节作为只读证据保留，复核审计写入 `review_meta`
- 待处理关系按有向 `(source_id, target_id)` 分组，别名按 owner 对象分组；Scene 只用于筛选和展示，反向关系不自动归并
- 类型目录只是推荐与保守同义词建议；关系和别名的数据库/Pydantic 契约仍接受自由字符串，自定义值未经用户点击不得替换
- 关系筛选用来命中对象对，返回时仍包含该有向对的完整待处理成员；指纹也基于完整快照，避免筛选后提交必然过期
- 分组列表为每组/每条别名返回 SHA-256 `execution_fingerprint`；批处理必须 `confirmed=true`，批次内先按 UUID 全局稳定顺序锁定端点和关系行，再为每个决策使用 savepoint；单组原子、组间可部分成功
- 人物扩展表 `characters` 保留历史独立 `aliases` JSONB 字段，新别名应优先写入 `core_entities.content_json.aliases`
- `characters` / `events` / `character_knowledge` 活跃扩展只能挂在同项目、类型匹配且已采用的 `CoreEntity` 下；人物 CoreEntity 被创建或提升为 canonical 时会确定性补齐最小 `characters` 档案，使导入人物立即可用于 POV、生成中心和人物上下文。作者显式保存人物档案时原位升级该 scaffold；自动 scaffold 不阻断后续类型纠正。列表与写作上下文默认排除父对象或 CoreEntity 目标已转为待处理/已归档的历史扩展行
- 对象分级：core / important / normal / temporary
- 版本回滚基于 `TextArchive` 归档与 `EntityRevision` 兜底（活跃回滚路由优先查询 `TextArchive`，无归档时回退到最近 `EntityRevision` 快照）

### 作者态投影

对象、关系与创设建议在保留原始状态的同时，附加稳定的作者视图字段：

- `display_state`: `active` / `review` / `archived`
- `source`: 来源模块或创建者
- `attention_reasons`: 如 `conflict` / `needs_review` / `low_confidence`
- `suggested_action`: 建议的下一步动作

`GET /api/world/entities?display_state=active|review|archived` 可以按作者态筛选；
旧 `status` 筛选与原始状态字段保持兼容；冲突仍作为
`attention_reasons=["conflict"]` 保留，不丢失原始审查态。

未显式传入 `status` / `display_state` 时，实体列表默认排除
`accepted / deprecated / ignored / merged / rejected / rolled_back` 全部历史态，
仍保留 active 与 review。别名列表会先综合别名自身与 owner 实体的投影态，
再做默认历史排除和分页，因此 `items` / `total` 使用同一条件；
显式 `display_state=archived` 或原始 `status` 筛选仍可审计历史。

手动 `DELETE /api/world/entities/{entity_id}` 是专用软废弃流程：主状态
转为 `deprecated` 前写入 `manual_delete` 修订快照，之后以
`entity_deprecated` 标记 context 失效。修订和 context 标记均是带独立
savepoint 的 best-effort 辅助审计；其失败会记日志，不回滚主删除。
这类降级日志只记录规范化实体 UUID、受限原因 token 与异常类型，不记录对象名称、用户文本、
异常 message 或控制字符；公开 API 的稳定错误语义不变。

### 对象库普通 / 热点模式

`GET /api/world/entities` 新增可选 `view_mode=normal|hot`。省略参数仍为
`normal`，完整保留原搜索相关度、`importance DESC → name → id`、分页和作者态筛选；
普通模式不读取 RAG 活动统计，`ranking/facets/ranking_context` 均为空。

热点模式读取 RAG 稳定只读 port 的原始出场章节，并在 world 内计算只读排名：

```text
semantic_importance = core 至少 0.85；important 至少 0.65；其他 clamp(importance, 0, 1)
weighted_occurrences = Σ 2^(-(截至章 - 出场章) / 6)
recent_heat = 1 - exp(-weighted_occurrences / 3)
combined_score = 0.65 × semantic_importance + 0.35 × recent_heat
```

`semantic_importance >= 0.75` 或级别为 core/important 标记“重要”；
`recent_heat >= 0.55` 标记“近期热点”，两者允许重叠。`focus=important|hot|other`
只在热点模式有效。facets 在其他筛选后、focus 与分页前统计；搜索时文本相关度优先，其后才是
组合分、最近出场章、名称和 ID。热点模式先读取全项目轻量投影完成排序和分页，再加载当前页
完整对象，不在前端重排当前页。活动索引不可用时 recent heat 为零并退化为长期重要性排序。
该派生排名不写回 `CoreEntity.importance`，也不改变生成上下文和现有 RAG importance。
RAG 术语只消费 canonical 对象名称和仍有效的别名；`ignored/rejected/deprecated/rolled_back`
别名及带 `rolled_back=true` 的历史别名不参与出场标注。别名忽略、工作流回滚、实体版本回滚
和自动入库对象清理都会通过组合根 port 请求轻量重标注。

### 项目活跃门禁

除不带项目语义的全局世界书模板目录，以及未提供 `novel_id` 的纯
Prompt 校验外，`/api/world` 与 `/api/world/map-atlas` 的项目级读、写、预览和入队入口都在业务操作前通过
`modules.project.facade.require_active_project()` 校验项目。不存在和已进入
回收站的项目统一返回 404，不暴露该项目的实体、别名、关系、地图册或任务存在性。

## 职责

- 世界对象 CRUD（CoreEntity / `WorldEntityService`）
- 对象关系管理（EntityRelation）
- 别名管理（`EntityAliasService`，内联于 CoreEntity.aliases JSONB，支持待复核别名元数据）
- 候选别名确认（将候选对象解析为目标对象别名，并复用关系迁移/去重逻辑）
- 对象去重（EntityDedupService）
- 对象融合建议（WorldEntityFusionService，LLM 只生成建议，用户确认后应用）
- 面向项目级智能去重的实体融合子 facade（`entity_facade.suggest_entity_fusion` /
  `entity_facade.apply_entity_fusion`；root `facade.py` 仅 re-export）
- 世界上下文/检索词典/批次（`EntityContextService`）
- 实体统计与自动抽取批次查询（`EntityStatsService`）
- 实体 embedding 回填（`EntityEmbeddingService`）
- 向其他模块提供世界上下文（`get_world_context`）
- 人物档案与知识边界（Character / CharacterKnowledge）

## World Bible 工作稿与世界观简介

World Bible 页面是作者组织和解释世界事实的手册层；`CoreEntity`、Profile、关系和事件仍是
结构化正史来源。AI 地图册只消费这些来源，不反向写入。新版编辑流程不直接覆盖正式页：

1. 作者创建或打开 `world_bible_page_drafts` 工作稿；标题、类别、概览、结构化 sections、
   关联资产引用和排序均可编辑，结构化资产只提供引用与跳转编辑。
2. 发布时以 `base_version_number` 做行锁 + CAS；版本冲突返回 409 并保留工作稿。
3. 发布原子更新 `canonical` 页面、递增 `version_number`、写不可变 revision、删除工作稿，
   并标记作者版世界观简介 stale。恢复旧页面版本只创建新工作稿，不覆盖历史。
4. 页面类 AI 只在生成中心产生完整页面提案。作者可先编辑标题、类别、概览、sections
   和关联资产，再通过
   `POST /api/world/generation-center/suggestions/{id}/apply-page-draft` 落服务器工作稿；
   generic `/confirm` 明确拒绝该 suggestion target，AI 不能直接发布页面或改写 canonical。

`WorldBibleLifecycleService` 统一拥有正式页创建/更新、工作稿发布、revision、projection /
简介 / context 失效，以及生成中心使用的页面/工作稿 source baseline。生成建议与应用建议
复用同一内容 hash、draft identity 和更新时间比较；`WorldBibleService` 只保留页面查询与
projection 任务编排，激活解析不再调用它的私有 hash helper。

页面 projection refresh 以
`("page_projection", page_id, projection_type)` 调用 tasks facade 的数据库级 keyed
coalescing，不再扫描最近一批全局 task。并发提交在部分唯一索引上收敛到同一个
pending/running task，终态仍保留历史。该 key 只解决排队重复；projection 的 page version、
source hash 与提交 CAS 仍是领域新鲜度和旧结果不得覆盖新页面的权威边界。
普通非流式刷新请求由 `DbSession` 的 request-owned transaction 在 function-scope dependency 结束时提交；返回 task ID 后，后续浏览器轮询可以立即从独立连接读取该任务。

世界观简介优先以已发布页面为综合主干，再用结构化对象和关系补充校验。输入仅保留约
50 万字符的异常安全栏，单页可使用约 20 万字符，不按常规短上下文压缩；输出导航上限约
4000 词元，避免因旧 1200 词元限制截掉作者页面后半部分。provider 超限时任务显式失败，
不静默改用更短资料。

编辑器始终显示主操作“保存并发布”；即使当前只打开正式页、尚未显式创建工作稿，也会先
保存服务器工作稿再发布。单独的“保存工作稿”只保存，不改变正式页。

`free_text` 保留为兼容概览；`sections_json` 保存最多 64 个有稳定 `section_id` 的有序资料段。
section 只支持 `markdown/checklist/asset_collection`，局部引用必须指向页面级已校验
TargetRef 的 hash，`projection_policy` 和 `sensitivity_hint` 只能收紧投影/可见性。页面正文
始终是资料而非事实源，也不能选择 Prompt role、工具或 system scaffold。

页面模板由 `world_bible_page_templates` 与不可变 revision 管理。内置模板只在代码注册，项目
模板不能覆盖内置 key，也不能保存 Prompt、provider、API key、工具调用或可执行表达式。
应用模板只改服务器工作稿；恢复历史模板会把旧快照写成当前模板的新版本，不覆盖历史，也
不会自动改写已发布页面。

内置类别为 `background/species/faction/location/rule/secret/custom`。项目自定义类别只
保存 `key/name/description/color/icon/sort_order/status/default_template_key`；默认模板只影响
新建页面选择，`category_key` 创建后不可修改，归档不删除历史页面，也不定义模板 schema
或资产激活规则。

`world_bible_synopsis` 是独立的作者模式 P1 section，UI 名称为“世界观简介”。它由 LLM
从已采用结构化世界事实和 `canonical/confirmed` 页面派生，允许按资料本身选择最有用的
导航结构，不要求固定类别或穷举全部事实。已发布页面在 manifest 中优先于单个对象和关系，
Prompt 要求以页面为综合骨架、把对象和关系作为补充证据，并把内部关系枚举改写成自然语言，
避免退化为资产清单。结构化契约要求至少一个含 claim 的 section，不能把空 JSON 当成成功；
输出中的短来源 key 必须映射回冻结 manifest；
服务保存不可变 revision、来源、source manifest/hash、coverage、Prompt/model/provider 和项目
LLM execution snapshot。
它不能替代确定性、不可驱逐的 P0 `World Core Brief`，也永不进入 reader/character/POV。
无成功版本时只使用有界确定性降级资料。恢复旧简介会固定 revision 并暂停自动晋升，直到
作者取消固定并刷新。

LLM 返回的 claim 若全部无法映射到当前 source manifest，不会让自动维护任务失败；服务会
改用同一 manifest 生成带合法逐条来源的确定性降级 revision，并在 coverage / omitted reasons
中标记 degraded。空 manifest 仍不伪造无来源事实。

自动维护默认关闭。首次启用会持久化授权范围、workflow、`editable=false` 和
`rollback=true`；现有 PostgreSQL 任务队列按项目合并刷新任务，提交前以 source hash CAS
决定是否晋升，过期结果保留为 `superseded` 并最多补排一个后续任务。
`world_bible_synopsis_refresh` 使用仅 TaskWorker 可调用的两阶段 seam：先按
`project FOR SHARE -> source/head` 冻结纯 JSON manifest、source/desired hash、
current/pinned/active 指针与不含密钥的项目 LLM execution snapshot，经 lease-fenced
checkpoint 释放事务后才调用 LLM。返回后重做 project guard 并以新鲜
source/head 重验；任何来源、desired、pin、current 或 active 漂移都不得晋升。
模型 client 和受管 structured step 使用 1800 秒上限；前端通过任务状态轮询，不设置整体
等待截止时间。
revision/head/补排任务在同一个最终 lease-fenced 短事务提交，旧失败不得
覆盖新成功或作者固定状态。普通 `refresh_now()` 仍由调用方拥有事务，不主动
commit。active-task 状态只通过 tasks facade 的 lifecycle contract 读取，world 不直接依赖
tasks ORM。

## 边界

明确不做：

- 人物档案管理 → character 已迁入 world，不再独立模块
- 对象 embedding 全量实时更新 → rag 模块
- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库

## AI 抽取确认策略

- 手动 AI 抽取或补抽默认写入 `candidate`，不得自动提升为 `canonical`。
- 只有用户明确启动并确认的自动流水线可直接写入 `canonical`；这类路径必须保留来源、可编辑/可回滚标记，并有对应测试覆盖。
- 本模块不恢复旧 `entity_candidates` 表；候选状态由 `core_entities.status` 表达。
- `POST /api/world/entities/fusion-suggestions` 只创建异步建议任务，建议结果保存在
  `AsyncTask.result`；`POST /api/world/entities/fusion-suggestions/apply` 必须
  `confirmed=true` 才会写库。`canonical -> canonical` 合并还必须逐条显式
  `allow_canonical_merge=true`；将已采用来源对象改为目标对象别名则必须逐条显式
  `allow_canonical_alias=true`。后者只迁移关系和登记别名，不融合正文内容，并把来源对象
  标记为历史态。
- 项目级“智能去重”按钮复用同一套 world 实体融合逻辑；它只改变入口和结果聚合，
  不放宽用户确认、正史二次确认或 novel_id 隔离规则。
- 智能去重确认 candidate 之间的机械融合时，来源转为 `merged`，主对象仍保持
  `candidate` 并继续等待作者采用；去重确认本身不等于采用为正史。
- 智能去重把对象确认为别名时，如果目标对象已存在同文本的待复核别名，会原位确认该别名
  而不是以重复冲突跳过；来源对象、关系迁移和别名复核状态在同一事务完成，因此待处理别名
  列表可在执行后的当前页刷新中立即收敛。
- `world_entity_fusion_suggestions` 任务使用模块内 task-only seam：先按
  `project FOR SHARE -> world read` 复制 pair / 对象摘要证据 DTO 与 semantic / execution
  fingerprint，并持久化项目 LLM execution snapshot；然后经 TaskWorker lease fence
  checkpoint 释放事务，才进行多轮 LLM 决策。task-only seam 不在
  首次 checkpoint 前调用可能进入 embedding / reranker 的 RAG 证据检索；普通
  `suggest()` 仍保留由调用方管理事务的 RAG 证据语义。每批入结果前再按同一锁顺序
  重读 pair / asset / disposition fingerprint，漂移项只记录固定原因并跳过。
  该 seam 会主动 `commit()`，因此拒绝 API 或普通 service session；普通
  `suggest()` 仍保留调用方事务所有权和当前 profile 解析语义。
- `world_alias_relation_extraction` 手动补抽只通过现有
  `world.run_alias_relation_extraction` DI 键的 task-only port 执行。提交时持久化
  secret-free 项目 LLM execution snapshot 与 `context_confirmation_id`；worker 先冻结
  Scene 语义/正文指纹、精确对象索引 hash、确认边界与 context snapshot，
  经 lease-fenced checkpoint 释放事务后才调用 LLM。`llm_complete` 只保存经
  Pydantic 验证、Scene 唯一性检查、内容/长度有界且不含 prompt/secret 的
  detached receipt，并冻结实际 timeout/concurrency；重试直接复用。每个
  Scene 的 context snapshot 只关联该 Scene 产生的 result refs。
  最终短事务按 `project FOR UPDATE -> running source-writer tasks -> current
  task attempt -> fresh confirmation/profile/Scene/draft/entity -> aliases/relations/context
  snapshot/confirmation/task checkpoint` 的锁序提交。已运行的 `deep_import`、
  `scene_auto_extraction` 或 `world_object_auto_extraction`
  会使 finalizer fail closed；新的同步写入受项目 `FOR SHARE` 门禁阻塞，新 claim
  任务的写入则在 worker commit guard 处阻塞。普通 `extract_alias_relations()` 和
  Deep Import Phase 2b 的调用/返回契约不变。
- 工作台扫描由 world 生成 semantic / execution fingerprints：前者控制
  `keep_separate` 是否继续抑制 pair，后者覆盖实体内容、人物/事件扩展、
  别名和关系拓扑，用于 apply 乐观锁。`apply_entity_fusion_group()` 会先校验
  整组和主对象方向，严格路径不吞异常。项目级扫描会先在完整候选边集上形成
  connected components，再按建议预算裁剪；同组融合完成后，world 用最终对象状态
  重新生成 `keep_separate` semantic fingerprints。
- 候选合并/清洗完成后，响应会尽量返回 `affected_ids` / `merged_ids`；前端只能按精确 ID 更新本地候选列表，缺少这些字段时刷新当前 tab，不按名称或候选组猜测删除。
- 确认为别名不是深合并：仅写入目标别名、迁移/去重关系并标记源候选为 `merged`，不得合并 summary/public_info/hidden_truth 或人物扩展字段。
- `CreationSuggestion` 中的 `core_entity` / `core_entity_draft` 经用户确认后直接写入 `canonical`，并保留建议 ID、来源、证据与 `approved_by` 审计。
- `entity_relation` / `entity_alias` 建议必须通过各自的 schema 验证和领域服务写入；未支持的 `target_type` 直接拒绝，不得标记为已接受后空操作。
- 生成中心的新对象先写 `creation_suggestion_queue`。队列服务同时物化一条
  `draft` / `candidate` 兼容影子，并以 `_meta.compatibility_shadow=true` 与
  `suggestion_id` 关联；采用或编辑后采用时提升同一条对象，合并/设为别名时由队列原子裁决并归档同一影子，忽略时同步标记该影子为 `ignored`。待处理影子不能绕过队列直接 CRUD，所有裁决都必须经过建议队列的 compare-and-set 门禁。
- imports 模块拥有深度导入和阶段化正文抽取的编排、授权快照、Scene 证据与
  candidate 写入契约；world 只提供受控的对象、别名和关系持久化 seam。

## 数据表

| 表名 | 用途 |
|------|------|
| `core_entities` | 统一核心实体正史库（原 `world_entities`） |
| `entity_relations` | 对象间关系边（原 `relationships`） |
| `events` | 事件扩展表（entity_id PK+FK → core_entities） |
| `characters` | 人物档案（entity_id PK+FK → core_entities） |
| `character_knowledge` | 人物知识边界 |
| `world_bible_categories` | 项目自定义世界书类别；内置类别不落库 |
| `world_bible_page_drafts` | 新页或已有页的服务器工作稿与发布基线版本 |
| `world_bible_pages` | 已发布作者手册页面；新版 UI 只发布为 canonical |
| `world_bible_page_revisions` | 页面发布点的不可变快照，项目/页面/版本唯一 |
| `world_bible_page_projections` | 与页面版本/source hash 绑定的派生投影 |
| `world_bible_page_templates` | 项目自定义页面布局模板；与代码内置模板 key 隔离 |
| `world_bible_page_template_revisions` | 页面模板每次修改/恢复产生的不可变快照 |
| `world_bible_synopsis_heads` | 每项目简介指针、stale/pin/task 与自动维护授权 |
| `world_bible_synopsis_revisions` | 作者版世界观简介的不可变 LLM 派生版本 |
| `entity_revisions` | 实体快照版本表（旧版快照；当前活跃回滚优先使用 `TextArchive`，无归档时回退到 `EntityRevision`） |
| `map_atlas_runs` | AI 地图册计划、上下文快照、任务进度与停止状态 |
| `map_atlas_nodes` | 封面到街道/室内的层级节点与采用状态 |
| `map_atlas_pages` | 独立候选/已采用/拒绝/移出图片与派生链 |
| `map_atlas_annotations` | 前端文字标注、归一化坐标与下钻目标 |
| ~~`entity_aliases`~~ | 已移除，别名存 `core_entities.content_json.aliases` JSONB |
| ~~`entity_candidates`~~ | 已废弃；候选对象存于 `core_entities.status="candidate"` |
| ~~`relationships`~~ | 已废弃，使用 `entity_relations` |

其余当前 ORM 表按子域归档如下，避免只更新主表时漏掉 schema 所有权：

- 归档：`text_archive`；
- 类型化 Profile：`species_profiles`、`faction_profiles`、`location_profiles`、
  `rule_profiles`、`item_profiles`、`secret_profiles`、`entity_profile_templates`、
  `generic_entity_profiles`；
- 生成模板：`generation_prompt_templates`、`generation_prompt_template_revisions`；
- 知识边界：`knowledge_tags`、`character_knowledge_tags`、`asset_knowledge_tags`、
  `knowledge_tag_exclusions`、`knowledge_visibility_policies`、`reader_reveal_policies`；
- 作者待处理队列：`creation_suggestion_queue`、`conflict_check_queue`。

`character_knowledge.source_chapter_index` 表示人物学到该知识的章节。
读者/角色视角仅激活早于可见截止章的记录；无来源章节的旧数据默认排除，
只有显式标记 `is_public_baseline=true` 的开场公开知识例外。同章但没有更精确学习
位置的记录按保守规则排除。

### ORM 模型布局

`modules.world.models` 是兼容导出 package，导入该 package 会注册 world 所有
ORM 表到同一个 `core.base.Base.metadata`。具体模型按子域拆分：

- `models/core.py`：CoreEntity、Event、EntityRelation、EntityRevision、TextArchive。
- `models/character.py`：Character、CharacterKnowledge。
- `models/profiles.py`：世界资产 profile 与模板表。
- `models/worldbuilding.py`：生成模板、World Bible、知识标签、创设建议和冲突队列。
- `models/common.py`：共享 SQLAlchemy imports 与 pgvector/SQLite embedding column helper。
- `map_atlas_models.py`：地图册 run、node、page 与 annotation；图片字节存私有 S3。

旧路径 `from modules.world.models import CoreEntity` 与 `import modules.world.models`
保持可用；兼容别名 `WorldEntity` 等仍从 package 顶层导出。

### core_entities 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID（FK → projects.id）
- `entity_type` — 对象类型字符串。作者入口可保存 1–64 字符安全自定义类型；AI 抽取与建议创建仍只接受固定系统目录。类型转换和 Profile snapshot 协议见 ADR-0005
- `name` — 对象名称
- `summary` — 概要
- `public_info` — 对外公开信息
- `hidden_truth` — 隐藏真相
- `content_json` — 扩展信息（JSONB，内含 `aliases` 等动态属性）
- `importance` — 重要性（0~1）
- `importance_level` — 重要性级别（core / important / normal / temporary）
- `reveal_level` — 揭示层级（author_only / hinted / revealed / fully_known）
- `status` — 状态（candidate / draft / canonical / deprecated / ignored / conflicted；`pending` 属于 async_tasks）
- `embedding_text` — 用于向量化的文本
- `embedding` — 向量（768 维，生产环境使用 pgvector bge-base-zh-v1.5）
- `search_text` — 用于 pg_trgm 模糊搜索的 PostgreSQL 生成列（name + aliases），业务层不得显式写入
- `pinyin_string` — name 的拼音字符串缓存（用于去重音似特征）
- `created_by` / `approved_by` — 创建/确认者

### entity_relations 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `source_id` — 源对象 ID（FK → core_entities.id）
- `target_id` — 目标对象 ID（FK → core_entities.id）
- `relation_type` — 关系类型
- `description` — 关系描述
- `strength` — 关系强度（0~1）
- `quote` — 原文依据
- `review_meta` — 人工复核审计元数据（reviewed_by / reviewed_at / review_before / review_after）
- `status` — 状态（candidate / canonical / deprecated）
- `source_chapter_id` — 来源章节 ID
- `caused_by_event_id` — 导致此关系的事件 ID

`candidate` 关系必须经用户复核后进入 `canonical`。`canonical` 关系以
`(novel_id, source_id, target_id, relation_type)` 为数据库幂等键。关系写入走仓储层
upsert；调用方不应再实现“先查再插”的并发控制。关系复核确认走
`PATCH /api/world/relations/{rel_id}/review-edit`；旧 `PUT /relations/{rel_id}`
若变更 status，也会写入等价 `review_meta`，避免绕过审计。
关系列表会按本次 `novel_id` 批量解析 `source_name` / `target_name`；前端不应把数据库 UUID
当作正常端点名称展示。

`POST /api/world/relations/review-batch` 每次最多 20 个决策、累计 50 条本次选中的关系。
`accept` 独立采用一条；`merge` 以用户选定的主关系和最终字段归并所选证据；
`ignore` 把所选候选改为 `deprecated`。同端点同类型已有正式关系时复用该关系；
归并来源写入 `review_history`，其他候选记录 `merged_into_relation_id` 后进入历史，
未选候选继续保持 `candidate`。因此大于 50 条的单组可分次处理，不要将整组成员数误作本次限额。

### aliases（内联 JSONB）

存储于 `core_entities.content_json.aliases`，格式为列表：
```json
[
  {"alias": "别名文本", "type": "name|title|nickname|alias|translation|abbreviation|自定义字符串"}
]
```

- 别名不创建新实体行
- 去重检查：别名不与已有别名重复（大小写不敏感）
- `PATCH /api/world/entities/{entity_id}/aliases` 只更新复核元数据；编辑文本或移动目标必须走 `/aliases/edit`
- `POST /api/world/entities/{candidate_id}/resolve-as-alias` 将候选对象登记为目标对象别名，并把源候选移出待确认对象队列
- 待处理别名的批量忽略不删除 JSONB 条目；它写入 `status="ignored"` / `needs_review=false` 和审计元数据。正式别名管理页的删除语义不变
- 别名分组扫描会稳定分页读完项目对象，不使用隐式 10,000 条截断；所有内联别名写入都先锁定 owner/目标对象，避免 JSONB 整体回写覆盖并发复核

### entity_revisions 表（legacy 快照兜底）

- 原用于实体快照版本管理
- `POST /api/world/entities/{entity_id}/rollback` 是当前活跃的版本回滚路由，请求体：`{ "target_scene_index": 12 }`；由 `EntityRevisionService.rollback_to_scene_index` 实现，优先使用 `TextArchive`，无归档时回退到最近 `EntityRevision`
- `POST /api/world/entities/{entity_id}/rollback-by-revision` 是 `entity_revisions` 的兼容路由，按显式 `revision_id` 回滚
- `EntityRevisionService` 同时承担活跃回滚实现与 legacy 兼容，不应再被描述为仅 read/compat

### AI 地图册表

`map_atlas_runs`、`map_atlas_nodes`、`map_atlas_pages` 与 `map_atlas_annotations` 只承载
图片生成与作者采用生命周期。候选页分别保存直接资料、AI 视觉补全和冲突；加入地图册只新增
已采用页面，不修改 World 事实。图片字节存私有 S3，完整契约见 `docs/modules/15_map.md`。

## 对外契约（contracts.py）

```python
@dataclass(frozen=True)
class CoreEntityContract:
    novel_id: str
    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None

@dataclass(frozen=True)
class EntityRelationContract:
    novel_id: str
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    quote: str | None = None
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None

@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约（legacy，活跃回滚优先使用 TextArchive，无归档时回退到 EntityRevision）"""
    entity_id: str
    revision_id: str
    revision_reason: str = "ai_import"
    created_at: str | None = None

@dataclass(frozen=True)
class DuplicateSuggestion:
    candidate_id: str = ""
    candidate_name: str = ""
    existing_entity_id: str = ""
    existing_entity_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    action: str = "needs_user_decision"

@dataclass(frozen=True)
class MergeResult:
    target_entity_id: str
    candidate_entity_id: str
    aliases_inherited: int = 0
    relations_migrated: int = 0
    relations_deduplicated: int = 0
    self_loops_cleaned: int = 0
    character_synced: bool = False
    conflicts_archived: int = 0

@dataclass(frozen=True)
class ResolveResult:
    action: str  # "merged" | "promoted" | "needs_user_decision"
    merge_result: MergeResult | None = None
    promoted_entity_id: str | None = None
    suggestions: list = field(default_factory=list)
```

## AI 地图册内部结构

- `map_atlas_service.py`：owner 门禁、run/树查询、页面审查、派生候选、标注和图片读取。
- `map_atlas_workflow.py`：Context 编译、计划校验、父子串行生图、checkpoint 与 finalization。
- `map_atlas_storage.py`：PNG 校验与 map-atlas 自有 boto3 adapter，所有同步 I/O 在线程池执行。
- `map_atlas_tasks.py`：`manual_resume` 生成任务和不依赖项目 FK 的全局前缀清理。
- `map_atlas_facade.py`：项目永久删除唯一需要的全局 cleanup enqueue seam。

生成上传持 project share lock 并复核 task lease；永久删除持 exclusive lock，先取消生成并排入
全局清理再删除项目，阻止晚到 worker 留下对象。`provider_in_flight` 失联必须由作者确认潜在重复
费用后重试。

## Facade

Root `facade.py` 是纯 re-export hub，不定义 async wrapper 或承载业务编排；
现有 `modules.world.facade.*` 生产路径保持可用，并由显式 `__all__` 与 public API
snapshot 测试冻结。新增跨模块函数前必须先证明现有 deep seam 无法表达，不能为单一
调用方增加 pass-through。具体薄委托按子域落在
`entity_facade.py`、`character_facade.py`、`event_facade.py`、`map_atlas_facade.py`
和 `worldbuilding_facade.py`。

`contracts.py` 只定义跨模块稳定 dataclass，不重导出 HTTP Pydantic schema。
HTTP 请求/响应类型属于 `schemas.py`；package root 不再兼容重导出 ORM、schema 或
facade 函数，跨模块调用必须显式使用 `contracts.py` / `facade.py` / 已注册 DI port。

`worldbuilding_facade.py` 承载世界书上下文激活相关入口：
`preview_worldbuilding_activation()` 调用确定性 activation preview 服务；
`get_world_bible_projection_candidates()` 按项目解析固定页面/CoreEntity TargetRef，并执行
最大深度 2 的页面链接或关系展开；`get_world_bible_page_source_manifest()` 返回可审计的
页面版本、section 与 source hash；
`mark_worldbuilding_context_stale()` 保持函数内 lazy import `modules.context.facade`，
避免扩大 context ↔ world 循环 import 风险。

`get_world_background()` 返回只读的 `WorldBackgroundBundleContract`。它从已采用世界对象、
关系、事件、秘密、已发布 World Bible 页面和人物知识边界派生 token-aware 条目，供 context
编译；地图册 operation 使用 author-full canonical 模式，不写回任何事实。

`get_author_attention_summary()` 是 Project“今日工作”消费的只读稳定投影，返回冻结的
`WorldAttentionSummaryContract`：同一 `novel_id` 下待处理的世界对象、别名和关系数量及
确定性 `total`。实现位于 world 自己的 attention service，复用既有查询服务并保持
项目过滤；root `facade.py` 仅 re-export，响应不包含对象内容、原始状态、owner 或内部 ID。

```python
# ---- CoreEntity ----
async def list_entities(db, novel_id, *, entity_type=None, statuses=None, display_state=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]
async def get_entity_importance_map(db, novel_id) -> dict[str, dict[str, object]]
async def create_entity(db, novel_id, data: dict) -> dict
async def count_entities(db, novel_id, *, status_filter=None) -> int
async def backfill_entity_embeddings(db, novel_id, *, batch_size=64) -> int

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, ..., include_review=False) -> WorldContextBundle
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

# ---- Author workbench attention ----
async def get_author_attention_summary(db, novel_id) -> WorldAttentionSummaryContract

# Entity extraction is owned by imports `world_objects` deep-import stage.
# World no longer exposes a parallel `run_entity_extraction` facade.

# ---- Dedup ----
async def find_similar_entities(db, novel_id, name, aliases=None, ...) -> list[DuplicateSuggestionResult]
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> MergeResult
async def suggest_entity_fusion(db, novel_id, *, entity_type=None, status=None, ...) -> dict
async def apply_entity_fusion(db, novel_id, *, confirmed: bool, suggestions: list[dict]) -> dict

# ---- Relationships (thin proxy) ----
async def find_entity_id_by_name(db, novel_id, name, entity_type=None) -> str | None
async def upsert_relationship(db, novel_id, source_id, target_id, ...) -> None

# ---- EntityRelation ----
async def get_entity_relations(db, novel_id, skip=0, limit=100) -> tuple
async def create_relation(db, novel_id, data: dict) -> EntityRelationResponse
async def upsert_relation(db, novel_id, source_id, target_id, relation_type, ...) -> EntityRelationResponse

# ---- Events ----
async def create_event(db, novel_id, data: dict) -> dict
async def get_events_context(db, novel_id, limit=50) -> EventsContextBundle
async def get_full_state(db, novel_id) -> dict

# ---- Worldbuilding ----
async def preview_worldbuilding_activation(db, novel_id, *, entity_ids=None, ...) -> dict
async def get_world_bible_projection_candidates(db, novel_id, target_refs, *, expand_page_links=False, relation_types=None, max_depth=0, ...) -> WorldBibleActivationResolutionContract
async def get_world_bible_page_source_manifest(db, novel_id, page_ids) -> list[dict]
async def mark_worldbuilding_context_stale(db, novel_id, *, reason: str, asset_id="worldbuilding") -> int

# ---- EntityRevision (legacy rollback by revision_id) ----
async def get_entity_revisions(db, novel_id, entity_id, skip=0, limit=20) -> dict
async def rollback_to_revision(db, novel_id, entity_id, revision_id) -> dict

# ---- Character ----
async def create_character(db, novel_id, name, world_entity_id=None) -> CharacterResponse
async def list_characters(db, novel_id, skip=0, limit=100) -> tuple
async def get_characters_context(db, novel_id, character_ids, ...) -> CharacterContextBundle
async def get_character_knowledge_context(db, novel_id, character_id, target_ids=None) -> list
async def get_character_knowledge_entries(db, novel_id) -> list[dict]
async def filter_context_by_character_knowledge(db, novel_id, character_id, context_items) -> list[dict]
async def find_character_id_by_name(db, novel_id, name) -> str | None
async def update_character_location(db, novel_id, character_id, location_id, ...) -> None
async def get_characters_at_location(db, novel_id, location_id) -> list[dict]
async def get_character_location_id(db, novel_id, character_id) -> str | None
async def get_character_id_by_world_entity(db, novel_id, entity_id) -> str | None
```

`get_world_context` 默认在查询层只返回 `canonical`，不会泄漏待处理对象。
`get_entity_importance_map` 同样只投影 `canonical` 对象的 ID、importance 和
importance level；RAG 章节索引通过该稳定 facade 生成可重建 chunk 分数，不读取 world ORM，
也不让待处理对象影响已采用正文的检索排序。
只有明确需要 working context 的调用方才传 `include_review=True`，此时额外
包含 `draft` / `candidate` / `conflicted`，但始终排除已归档状态。
`compatibility_shadow` 在待处理期间只使用 `draft` / `candidate`，不会进入默认 active context；它只用于旧读取契约与可回滚迁移。队列采用后同一对象转为 `canonical`、可正常编辑，拒绝后转入 `ignored` 历史。

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/world/entities` | 世界对象列表；可按原始 `status` 或 `display_state` 筛选，`q` 支持名称、别名和描述的模糊搜索（名称/别名优先） |
| GET | `/api/world/entity-types` | 当前项目类型目录；固定顺序系统类型 + 全部状态对象使用过的项目自定义类型 |
| GET | `/api/world/review-type-catalog` | 关系/别名推荐类型、中文标签和保守同义词；`custom_allowed=true` |
| GET | `/api/world/relations/review-groups` | 按有向对象对分页返回待处理关系组、完整成员和执行指纹 |
| POST | `/api/world/relations/review-batch` | 显式确认的关系 accept / merge / ignore 批处理 |
| GET | `/api/world/aliases/review-groups` | 按所属对象分页返回待处理别名组 |
| POST | `/api/world/aliases/review-batch` | 显式确认的别名采用、编辑或忽略批处理 |
| POST | `/api/world/entities` | 手动创建世界对象；未传 `status` 时默认已采用 |
| GET | `/api/world/suggestions` | 创设建议队列，响应包含作者态投影 |
| POST | `/api/world/suggestions/{suggestion_id}/confirm` | 确认普通建议；世界书页面工作稿建议必须走专用 apply 路由 |
| POST | `/api/world/suggestions/{suggestion_id}/edit-confirm` | 编辑世界对象建议并原子采用 |
| POST | `/api/world/suggestions/{suggestion_id}/merge` | 将世界对象建议合并到已采用对象 |
| POST | `/api/world/suggestions/{suggestion_id}/resolve-as-alias` | 将世界对象建议设为已采用对象的别名 |
| POST | `/api/world/suggestions/{suggestion_id}/reject` | 拒绝建议 |
| POST | `/api/world/generation-center/chat` | 世界工作区共创聊天；按作者选择的来源/目标加载上下文，不创建建议、不写业务资产 |
| POST | `/api/world/generation-center/suggestions` | 按 `core_entity` / `world_bible_page` / `world_bible_new_page` 生成结构化待处理建议 |
| POST | `/api/world/generation-center/suggestions/{suggestion_id}/apply-page-draft` | 将经作者编辑的完整页面提案写入或创建服务器工作稿；不发布 canonical |
| GET/POST | `/api/world/bible/page-templates` | 列出内置/项目页面模板，或创建项目模板 |
| PATCH | `/api/world/bible/page-templates/{template_id}` | CAS 更新或归档项目页面模板 |
| GET | `/api/world/bible/page-templates/{template_id}/revisions` | 页面模板不可变版本历史 |
| POST | `/api/world/bible/page-templates/{template_id}/revisions/{version}/restore-draft` | 将历史快照恢复为当前模板的新版本 |
| POST | `/api/world/bible/drafts/{draft_id}/apply-template` | 把模板布局应用到服务器工作稿 |
| GET | `/api/world/generation-prompt-templates` | 生成中心 Prompt 模板列表（含内置模板） |
| POST | `/api/world/generation-prompt-templates` | 创建用户自定义 Prompt 模板 |
| POST | `/api/world/generation-prompt-templates/validate` | 校验模板变量、危险指令和输出契约 |
| POST | `/api/world/generation-prompt-templates/preview` | 预览模板渲染结果；不调用 LLM、不写库 |
| GET | `/api/world/generation-prompt-templates/{template_id}` | 模板详情 |
| PUT | `/api/world/generation-prompt-templates/{template_id}` | 更新模板并生成版本记录 |
| DELETE | `/api/world/generation-prompt-templates/{template_id}` | 软归档用户模板 |
| GET | `/api/world/generation-prompt-templates/{template_id}/revisions` | 模板版本历史 |
| POST | `/api/world/generation-prompt-templates/{template_id}/copy` | 复制内置模板为用户模板 |
| GET | `/api/world/entities/{entity_id}` | 对象详情 |
| PUT | `/api/world/entities/{entity_id}` | 更新对象 |
| DELETE | `/api/world/entities/{entity_id}` | 删除对象 |
| POST | `/api/world/entities/{entity_id}/promote` | 将草稿/候选实体提升为正史；可选携带名称、类型和概要，在同一事务中编辑后采用 |
| POST | `/api/world/entities/{candidate_id}/resolve-as-alias` | 将候选确认为目标对象别名 |
| GET | `/api/world/entities/{entity_id}/relations` | 实体关系列表 |
| DELETE | `/api/world/entities/{entity_id}/aliases` | 删除别名 |
| PATCH | `/api/world/entities/{entity_id}/aliases/edit` | 编辑/移动并确认别名 |
| GET | `/api/world/entities/{entity_id}/revisions` | 版本历史（legacy，只读兼容） |
| POST | `/api/world/entities/{entity_id}/rollback` | 回滚到指定 scene_index（优先 TextArchive，无归档时回退到 EntityRevision） |
| POST | `/api/world/entities/{entity_id}/rollback-by-revision` | 按 revision_id 回滚（`entity_revisions` 兼容） |
| GET | `/api/world/aliases` | 别名列表 |
| POST | `/api/world/aliases` | 添加别名 |
| GET | `/api/world/entity-batches` | 实体批次分组列表 |
| GET | `/api/world/relations` | 关系列表（v3） |
| POST | `/api/world/relations` | 创建关系（v3） |
| PUT | `/api/world/relations/{rel_id}` | 更新关系（v3） |
| PATCH | `/api/world/relations/{rel_id}/review-edit` | 编辑待确认关系并确认 |
| DELETE | `/api/world/relations/{rel_id}` | 删除关系（v3） |
| GET | `/api/world/events` | 事件列表 |
| POST | `/api/world/events` | 创建事件 |
| GET | `/api/world/events/{entity_id}` | 事件详情 |
| PUT | `/api/world/events/{entity_id}` | 更新事件 |
| DELETE | `/api/world/events/{entity_id}` | 删除事件 |
| GET | `/api/world/characters` | 人物列表 |
| POST | `/api/world/characters` | 创建人物 |
| GET | `/api/world/characters/{character_id}` | 人物详情 |

### AI 参考资料确认

- entity fusion 和世界生成中心通过 project runtime seam 消费项目 profile；
  LLM 输出继续只形成 suggestion/draft，不直接成为 canonical。
- 世界生成中心的受管模型步骤总上限为 1800 秒。服务在 provider 调用前提交准备阶段
  checkpoint，确保等待期间没有数据库事务；结构化结果返回后重新校验来源页面 baseline，
  来源发生变化时以 409 丢弃过时建议，不在长事务中等待或静默落库。多轮对话的决策编译、
  结构化生成和必要的语义守卫重试共同受同一个 1800 秒总预算约束，避免步骤叠加后越过
  浏览器 35 分钟等待窗口；单次 provider client 同样允许 1800 秒。
- 生成中心世界工作区的自由聊天不创建确认记录，也不写业务资产；只有
  `POST /api/world/generation-center/suggestions` 创建待处理 `CreationSuggestion`。
  服务依据作者明确选择的 target 做确定性分派，模型不能改变落库目标，也不能调用工具。
  对象建议继续进入待处理队列；页面建议只能经专用 apply 路由进入服务器工作稿。
  聊天直接使用普通文本生成，再由后端以只含 `reply` 的 schema 校验非空与长度；它不启用
  provider JSON mode，避免 DeepSeek 偶发空 content 导致一次高成本格式修复。空文本最多在
  同一个 1800 秒阶段预算内重试一次。
- 自由聊天把模型定位为世界设定共创搭档；模型可根据对话自主选择
  发散、比较、质疑、关键追问或阶段性收束，不使用固定问卷。最终结构化
  step 对存在往返修订的多轮对话先编译 author decision state，区分已确认要求、受支持发展、
  已作废内容、禁用专名、未决项和命名权限；最终提案不再直接消费包含旧方案的原始助手历史。
  提案随后只审计作者边界，不评价创意偏好或要求补齐字段；禁用专名重新出现、作者仍要求
  不命名却生成专名，或提案擅自解决未决项时，结果不能进入待处理队列，并在同一阶段预算内
  重生成一次。决策编译、提案和审计从首轮请求就收到实际 Pydantic JSON schema；不依赖
  provider 的 `json_object` 模式猜测字段后再做一次高成本格式修复。聊天中的助手建议只有
  被作者接受或后续明显沿用时才进入对象建议。
- 对象建议的 `summary` 不设统一字数或固定内容模板；`hidden_truth`
  只在设计确实存在隐藏层时生成，`character_card` 只用于人物且不为
  完整度填充无依据字段。`importance_level` 与 `reveal_level`
  由结构化 schema 枚举校验。
- 生成中心背景使用专用 `generation_center` scope：显式选择和来源页引用优先，随后是
  当前 Scene、当前章节活跃剧情线、相关篇章/RAG 证据，以及由这些资料关联的人物与
  世界对象。人物自动候选最多 6 个、非人物世界对象最多 16 个；作者显式选择优先占位。
  Scene 选择器读取全部 active ordered Scene；后端再次要求所选 Scene 处于
  `candidate/draft/canonical`，历史 `deprecated` Scene 在调用模型前 fail closed。
  没有章节、Scene、引用或检索证据时不注入第一章剧情线。作者选中的章节在总预算内优先
  提取命中创作意图的窗口，未命中时保留头尾，不固定只取每章开头 500 字。
- `core_entity` 使用对象 Prompt 模板；现有页继承服务器加载的页面/工作稿结构；新页面
  使用作者选择的类别和世界书页面模板。页面正文不从 URL 或浏览器缓存回传，source
  snapshot 固定页面/工作稿 hash、简介和 Activation Profile revision 及实际纳入/裁剪来源。
  以页面为来源的请求必须显式携带 `published(page_version)` 或
  `draft(page_version, draft_id, draft_updated_at)` baseline；作者预期已发布页时如新工作稿已出现，
  生成前直接返回 409，不静默替换输入。
- 生成中心 Prompt 模板按 `novel_id` 隔离；内置模板是只读虚拟模板，自定义模板支持
  `version_number`、内容 hash 和 revision 历史。使用 `template_id` 生成时会在 LLM
  调用前做 P1 阻断校验，并把模板版本/hash 写入草稿 `_meta`，用于提示模板漂移。
- 内置模板是创作视角，不是必填字段清单：它们引导模型理解人物的选择、
  事件的状态变化、物品的使用关系、地点的空间作用、组织的集体行动
  和规则对选择的约束，其他维度只在对当前对象有帮助时发展。
  `none` 允许概念暂时跨类别；结构化阶段仍暂存为 `concept`，作者可在采用前调整类型。
- 模板 `validate` / `preview` 不调用 LLM、不写世界对象；preview 只回显模板片段，
  长变量值会截断，避免完整正文或隐藏 prompt 泄漏。P1 会阻断保存和生成，P2/P3
  仅提示。`template_version` 过期会返回 409
  `template_version_conflict`，前端提示刷新或重新选择模板。
- 软归档模板不会出现在默认列表中，也不能再按 id 读取、更新或用于生成；需要继续
  编辑时应从内置模板或现有模板复制为新的自定义模板。

生成中心前端 E2E 需要使用 `frontend-console/playwright.config.js`，不要从仓库根目录
直接传 `frontend-console/e2e/generate.spec.js`。推荐命令：

```bash
make generate-e2e
# 等价于：
cd frontend-console && BACKEND_PORT=18000 FRONTEND_PORT=18080 npx playwright test e2e/generate.spec.js
```

| 方法 | 路径 | 用途 |
|------|------|------|
| PUT | `/api/world/characters/{character_id}` | 更新人物 |
| DELETE | `/api/world/characters/{character_id}` | 删除人物 |
| GET | `/api/world/characters/{character_id}/knowledge` | 人物知识边界列表 |
| POST | `/api/world/characters/{character_id}/knowledge` | 添加人物知识 |
| PUT | `/api/world/knowledge/{knowledge_id}` | 更新人物知识 |
| DELETE | `/api/world/knowledge/{knowledge_id}` | 删除人物知识 |
| POST | `/api/world/map-atlas/{novel_id}/runs` | 创建地图册计划与生成任务 |
| GET | `/api/world/map-atlas/{novel_id}/runs/latest` | 查询最新 run 与恢复状态 |
| GET | `/api/world/map-atlas/{novel_id}/runs/{run_id}/results` | 查询本次生成候选层级 |
| GET | `/api/world/map-atlas/{novel_id}/atlas` | 查询已采用地图册与画廊 |
| POST | `/api/world/map-atlas/{novel_id}/runs/{run_id}/stop` | 生成完当前页后停止 |
| POST | `/api/world/map-atlas/{novel_id}/runs/{run_id}/resume` | 恢复；潜在重复费用需显式确认 |
| POST | `/api/world/map-atlas/{novel_id}/pages/{page_id}/{adopt|reject|archive|restore}` | 独立页面审查与恢复 |
| POST | `/api/world/map-atlas/{novel_id}/pages/{page_id}/{edit|regenerate}` | 创建派生候选 |
| PATCH | `/api/world/map-atlas/{novel_id}/annotations/{annotation_id}` | 更新前端标注 |
| GET | `/api/world/map-atlas/{novel_id}/pages/{page_id}/image` | 鉴权读取私有 PNG |

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM、UUIDMixin、TimestampMixin、StatusMixin、NovelMixin
- `core.dependencies` — DbSession
- `shared.enums` — EntityType、ObjectStatus、Visibility、CandidateAction 等
- `shared.types` — NovelID、EntityID 等
- `shared.constants` — DEFAULT_PAGE_SIZE、相似度阈值

## 测试方式

```bash
cd backend
python -m pytest modules/world/tests/ -v
```

## 当前范围

world 当前拥有世界对象、关系、别名、人物与知识边界、建议队列、去重/融合、版本回滚、
World Bible、生成模板，以及 AI 地图册的计划、候选、画廊和标注。
它是事实模块，不拥有正文、Scene、context confirmation 或 RAG 候选；AI 输出默认进入
待处理建议，只有用户明确授权的流水线才可按领域门禁写入可回滚资产。
