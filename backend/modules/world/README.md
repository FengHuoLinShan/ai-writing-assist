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
- 深度导入与独立地图补充的类型化地图候选都通过稳定 `contracts.py` / `facade.py` seam
  进入 world；`MapObservationCandidateInput.source_workflow` 只允许
  `deep_import | map_enrichment`，并分别写入真实来源字符串。world 按
  `novel_id + workflow_id + scene_id + source_item_key + proposal_type` 生成 UUIDv5，并保存原始
  payload hash。相同重试复用已有 observation；同一身份内容变化返回 409，且不覆盖作者编辑。
  world 同时校验冻结授权快照的 novel/章节 scope；map enrichment 还必须固定
  `stage="map_observations"`、与逐字证据等长的精确偏移、Scene 内序号和 64 位
  SHA-256 来源/证据指纹，并将快照指纹写入只读来源。
  PostgreSQL 首次并发写入使用确定性身份锁，避免空行无法行锁导致的唯一冲突。导入
  proposal 类型是来源身份的一部分，作者可编辑内容，但不能原地切换类型。map enrichment
  可携带已由 imports 冻结词典唯一解析的 canonical 目标/地点 ID；world 会重验项目、
  类型与 canonical 状态，但跨 organization/faction 的同名歧义必须由 imports 在 seam
  之前拒绝。地点恰有一个作者可见 active 地图中心绑定时，world 确定性分配
  map/hex，其他候选进入项目收件箱。所有结果仍为 candidate，
  不自动生成 Fact。
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

对象、关系、创设建议与地图 observation/fact 响应在保留原始
`status` / `review_state` / `fact_status` 的同时，附加稳定的作者视图字段：

- `display_state`: `active` / `review` / `archived`
- `source`: 来源模块或创建者
- `attention_reasons`: 如 `conflict` / `needs_review` / `low_confidence`
- `suggested_action`: 建议的下一步动作

`GET /api/world/entities?display_state=active|review|archived` 可以按作者态筛选；
旧 `status` 筛选与原始状态字段保持兼容。地图界面将 candidate / conflicted
统一表达为“待处理”，confirmed 表达为“已采用”；冲突仍作为
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
Prompt 校验外，`/api/world` 与
`/api/world/maps` 的项目级读、写、预览和入队入口都在业务操作前通过
`modules.project.facade.require_active_project()` 校验项目。不存在和已进入
回收站的项目统一返回 404，不暴露该项目的实体、别名、关系、地图或任务存在性。

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

World Bible 页面是作者组织和解释世界事实的手册层；`CoreEntity`、Profile、关系、
事件和已确认地图事实仍是结构化正史来源。新版编辑流程不直接覆盖正式页：

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
  candidate 写入契约；world 只提供受控的对象、别名、关系和地图观察持久化 seam。

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
| `map_configs` | 动态地图配置（世界/城市/区域/地下城，自引用树，PRD §4.1） |
| `map_tiles` | 六边形地形网格（轴向坐标 q,r，PRD §4.2） |
| `map_location_bindings` | 地点绑定（core_entities.entity_type=location → hex，PRD §4.3） |
| `map_location_layouts` | 地点布局节点（中心 hex、占用半径、锁定状态、快速创建/拖拽来源） |
| `map_markers` | 动态标记（P1 预留：character/event/item，按 Scene 时间层显隐，PRD §4.5） |
| `map_territory_tiles` | 势力范围（组织控制区域，可与地形/地点/标记叠加） |
| `map_terrain_layers` | 手绘地形图层（素材、透明度、显隐、锁定、层级） |
| `map_terrain_regions` | 手绘地形区域（一次连续手绘或可命名区域） |
| `map_terrain_patches` | 手绘地形 patch（region 覆盖的离散 hex） |
| `map_terrain_bindings` | 手绘地形区域与地点的用户确认绑定（footprint / influence） |
| `map_layer_nodes` | 地图递归图层树（局部显隐、锁定、透明度、排序与缩放范围的唯一权威） |
| `map_path_layers` | 连续线路图层资源（仅保存 transport / water 类别，显示属性由图层树 leaf 拥有） |
| `map_paths` | 可归档道路/水系资产、端点绑定和独立内容 revision |
| `map_path_nodes` | 线路有序连续轴向控制点、宽度、张力与分段类型 |
| `map_visual_revisions` | 每次已提交视觉编辑的不可变状态与资源级正向/反向变更；随地图永久删除级联清理 |
| `map_observations` | 地图观察事实候选（来源证据、置信度、审查状态；默认不污染正式事实） |
| `map_facts` | 已确认时间化地图事实（由 observation 确认生成，供世界动态地图消费） |
| ~~`entity_aliases`~~ | 已移除，别名存 `core_entities.content_json.aliases` JSONB |
| ~~`entity_candidates`~~ | 已废弃；候选对象存于 `core_entities.status="candidate"` |
| ~~`relationships`~~ | 已废弃，使用 `entity_relations` |

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

### map_observations / map_facts 表

- `map_location_bindings` / `map_location_layouts` / `map_markers` /
  `map_territory_tiles` / `map_terrain_bindings` 是实体拥有的正式地图图层：
  新建或更新时关联实体必须为 `canonical`，且继续校验 `novel_id` 与实体类型。
  默认聚合状态和各图层独立列表只返回 canonical owner；历史
  `draft` / `candidate` owner 只进入显式 candidate preview，归档 owner 默认隐藏。
  `GET /api/world/maps/{map_id}/terrain?include_candidates=true` 可显式返回
  `candidate_bindings`，默认 `bindings` 只包含 confirmed 且 canonical-owner 的绑定。
- `map_configs.parent_entity_id` 和已确认的 `map_terrain_bindings` 同样只能引用已采用的 location；候选地形绑定可保留预览，但采用前会重新校验地点状态。
- `map_observations` 是世界动态地图的证据层：类型化地图建议、显式携带地图/空间元数据的 legacy `delta_events`、即时分析或人工编辑先写入 observation，默认 `review_state="candidate"`。普通剧情状态变化只保存在 memory delta log，不重复进入地图收件箱。
- observation 必须能说明目标名称/类型、动态类型、时间锚点、空间锚点、来源引用、证据摘要、置信度和审查状态；目标实体或地图尚未解析时可为空，但不得存入跨 `novel_id` 的实体引用。
- 同一 Scene 内具有精确正文 offset 的 observation 使用 `time_anchor.scene_sequence` 表达叙事先后；
  时间线只把相同 Scene 和相同 sequence 的同维度异值视为同一时刻冲突。旧事实缺少 sequence
  时保持原兼容冲突语义。
- 未分配且仍为 `candidate` / `conflicted` 的 observation 进入项目级地图收件箱；具体地图的
  observation、dashboard 和 playback 只读取精确 `map_id`，不会混入项目收件箱候选。
- `map_facts` 是正式时间化地图事实，由用户确认 observation 后生成，默认 `fact_status="confirmed"`；数据库以 `(novel_id, observation_id)` 保证一条 observation 只对应一个逻辑 Fact。重复采用内容一致时复用原 Fact，内容冲突返回 409。
- 人物位置、事件发生地、线路状态和势力边界的待解析值使用显式
  `payload_kind="proposal"` proposal union。proposal 保持 `normalization_state="untyped"`；
  作者把它补齐为 canonical `MapDynamicValueV1` 后，服务端才可能允许确认。
- `value_json.schema_version=1` 使用类型化地图动态 schema，覆盖 location、route_state、status、
  boundary、resource、terrain、crisis 和 semantic；响应附加 `normalized_value`、
  `dimension_key` 与 `normalization_state`。无版本旧值继续兼容读取，无法安全解释时只进入
  未结构化展示，不会让整条时间线失败。
- `MapFact` 是唯一持久化动态事实。Scene 状态、`MapDelta`、冲突、连续性问题和
  `WorldDynamic` 都由 confirmed facts 确定性派生；candidate 只进入显式待处理预览，不参与
  正式状态或连续性判断。
- 公共作者 PATCH 只允许修改目标对象、作者值、空间锚点和候选审查状态；来源引用、证据、
  workflow、原始置信度、Scene/章节来源与来源时间只读，额外字段返回 422。响应中的
  `eligibility` 由服务端统一检查 canonical value、同项目已采用对象、active 地图、空间引用
  及 Scene/章节或人工 initial-state；前端不复制这套资格规则。
- 空间锚点使用类型化 `MapSpatialAnchor`。带 `path_id` 的锚点必须解析到同一
  `novel_id + map_id` 的线路；deep import 无法解析的引用不会入库，并在来源 metadata
  记录 `invalid_spatial_anchor`。确认 Fact 时固化 path revision、名称和代表坐标；线路后续
  编辑或归档不改写历史 Fact，待处理 observation 引用已归档线路时必须重新关联后才能确认。
- PATCH、assign、ignore、confirm 和 batch-review 必须携带当前 `expected_updated_at`；陈旧写入
  返回 409 和最新只读 observation。confirm 在 observation 行锁内重验 revision 与
  eligibility 后生成或复用 Fact；批量审查按 UUID 稳定加锁并先全量验证，避免部分写入。
- `PATCH /observations/{id}` 只能更新作者拥有的候选字段或把 `review_state` 设为
  `candidate` / `ignored` / `conflicted`；不得通过 PATCH 直接设为 `confirmed`。正式确认必须
  走 `/confirm`，以保证生成或复用对应 `map_facts`。
- 忽略候选只更新 `review_state="ignored"`，不硬删除候选记录。
- 深度导入仍完整保留 `memory.delta_log`；只有显式携带 `map_id`、空间锚点或类型化地图值的 legacy `delta_event` 才兼容接入 `map_observations`，新流程优先使用独立的类型化地图 proposal。历史无空间意图的自动 observation 保留审计，但不再进入默认地图收件箱。该接入不自动写正式 `map_facts`。
- 地图移动解释使用 `dynamic_type="movement_explanation"`，地图冲突使用 `dynamic_type="map_conflict"`；二者复用 observation/fact 流，不新增独立冲突表。
- 写作冲突检查通过 `summarize_scene_map_for_writing(..., include_candidates=False)` 消费 Scene 地图摘要，默认只返回已确认事实；用户在写作页显式勾选包含待确认对象时才会纳入 candidate observation，并在 writing 问题项标记 `needs_review`。

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

## 地图内部结构

`backend/modules/world/services/` 已按领域拆成子包：

- `services/core/`：核心实体、人物、事件、关系、去重、抽取、版本和回滚。
- `services/map/`：地图配置、快速创建、地点布局/绑定、底图 tile、覆盖地形、marker、territory、observation/fact、dashboard、playback、动态队列。
- `services/worldbuilding/`：世界书页面、模板、投影、作者资料整理和上下文摘要。
  其中 `worldbuilding_service.py` 是旧 import path 兼容 hub；实际实现按概念拆到
  `profile_service.py`、`world_bible_service.py`、`suggestion_queue_service.py`、
  `knowledge_tag_service.py`、`reader_safety_service.py`、`conflict_queue_service.py`
  和 `activation_preview_service.py`。
- `services/common.py`：跨子包通用 helper。
- `services/__init__.py`：顶层 re-export hub，保留常用 service 和 helper 的旧聚合入口。
- `services/map_service.py`：历史兼容导出层，不承载业务逻辑。

`modules.world.services.map_service` 保留旧测试和 API 路由 import 路径；具体地图实现位于 `services/map/`：

- `map_templates.py`：初始地形模板和详图 tile 生成。
- `map_config_service.py` / `map_tile_service.py` / `map_location_binding_service.py`：地图配置、tile 批量编辑、地点绑定。
- `map_marker_service.py` / `map_territory_service.py`：动态标记和势力范围。
- `map_archive.py` / `map_revision.py` / `map_editor_apply.py`：地图子树归档恢复、视觉 revision 与原子编辑命令批次。
- `map_layer_tree.py`：递归图层树、继承锁定/显隐/透明度/缩放及旧 terrain 字段兼容投影。
- `map_path.py`：连续道路/水系、控制点、端点吸附、归档恢复、容量与路径引用影响统计。
- `map_entity_presence.py`：世界对象跨 active 地图的只读空间 presence 聚合。
- `map_dynamic_service.py`：`MapDynamicFactService` 是 observation、fact、dashboard、playback、open target 的深层生命周期拥有者，并保留原稳定方法表面。
- `map_observation_service.py` / `map_fact_service.py`：观察事实候选、确认流转和正式事实状态的内部 mixin；旧 helper 类只作 import/test 兼容。
- `map_dashboard_service.py` / `map_playback_service.py` / `map_open_target_service.py`：只读派生视图、播放事件流和地图打开目标的内部 mixin。
- `map_timeline_service.py`：以明确 context/repository 依赖保留独立时间线投影；不依赖 owner Protocol。
- `map_dynamic_helpers.py`：动态地图 formatter、risk/priority/label、UUID 安全解析、空间锚点校验等私有 helper。
- `map_state_assembler.py`、`map_scene_summary.py`、`map_terrain.py`、`map_location_layout.py`、`map_quick_create.py`：独立地图入口，不通过 `map_service.py` 承载业务实现。

地点布局与绑定的职责固定如下：`map_location_layouts.center_hex` 是编辑锚点，
`map_location_bindings` 是实际渲染范围。旧地图读取时不会自动补写；显式以
`sync_bindings=true` 保存才会物化缺失中心并整体平移既有 footprint。该操作保留绑定样式，
越界时原子失败，只把实际移动地点的 `map_quick_create` fact 软废弃，不产生世界事实。

`map_configs.editor_revision` 是地图视觉写入的 CAS 版本；tiles、地点布局/绑定、覆盖层、
marker、territory、generate、quick-create replace 和图层树成功修改时递增，
observation/fact 审查不计入该版本。统一编辑入口在同一事务内按顺序执行命令，成功只递增一次，
任何命令失败都回滚整批。每次递增同时写入不可变 `map_visual_revisions`，保存提交后的完整
可恢复状态和资源级 `before/after` 正反变更；旧单项 API 与 editor apply 共用该入口。
恢复历史版本必须携带当前 `expected_revision`，恢复成功产生新的 revision，不覆盖旧历史。
`map_layer_nodes` 是图层属性权威，旧 terrain 图层字段仅作兼容投影。
图层树还保存 exclusive/floor 结构和每个子层的楼层编号；当前激活子层与 isolate 是不写库的
前端会话状态。连续线路使用同一 editor apply CAS，线路本体只归档，空线路图层才允许删除。

开发管理工具 `python -m scripts.reset_map_subsystem` 当前只支持 dry-run 和可选的
`--backup-restore-drill`。它以固定 16 张 `map_*` 表 allowlist 比对 ORM/实库 schema、FK、
活跃资产引用与运行任务，并校验显式环境和 database fingerprint。CLI 不提供
`--execute` / `--yes` 或目标库删除分支；任何未来清空仍需单独授权和完整 cutover 流程。

## Facade

Root `facade.py` 是纯 re-export hub，不定义 async wrapper 或承载业务编排；
现有 `modules.world.facade.*` 生产路径保持可用，并由显式 `__all__` 与 public API
snapshot 测试冻结。新增跨模块函数前必须先证明现有 deep seam 无法表达，不能为单一
调用方增加 pass-through。具体薄委托按子域落在
`entity_facade.py`、`character_facade.py`、`event_facade.py`、`map_facade.py`
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

`get_world_background()` 返回只读的 `WorldBackgroundBundleContract`。它从世界对象、
关系、已确认地图事实和人物知识边界派生 token-aware 条目，供 context 编译；不拥有
新的正史表，也不写回任何事实。

```python
# ---- CoreEntity ----
async def list_entities(db, novel_id, *, entity_type=None, statuses=None, display_state=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]
async def create_entity(db, novel_id, data: dict) -> dict
async def count_entities(db, novel_id, *, status_filter=None) -> int
async def backfill_entity_embeddings(db, novel_id, *, batch_size=64) -> int

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, ..., include_review=False) -> WorldContextBundle
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

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

# ---- Map dynamic facts ----
async def create_map_observation_from_delta_event(db, novel_id, *, event: dict, scene_index: int, ...) -> dict
async def summarize_scene_map_for_writing(db, novel_id, scene_id, *, include_candidates=False) -> dict
async def get_confirmed_map_facts_through_scene(db, novel_id, scene_index) -> ConfirmedMapFactReplayContract

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

`summarize_scene_map_for_writing` 返回写作模块可消费的轻量 Scene 地图摘要，包括主地点、角色/事件/势力/风险、打开地图目标和候选支持状态。它是 world → writing 的稳定边界；writing 不直接读取 `map_observations` / `map_facts` 内部表。
`get_confirmed_map_facts_through_scene` 是 memory Scene 重放的只读稳定边界，只返回同项目、
confirmed 且带 Scene 锚点的事实，并单独返回 undated 数量供调用方 fail closed；candidate
永不进入历史阶段投影。
默认主地点只从 `canonical` 绑定推导；只有调用方显式传入
`include_candidates=True` 时才可纳入历史 `draft` / `candidate` 绑定，且响应会以
`depends_on_candidate=true` 和 `candidate_review_state` 标明尚未采用。

`get_world_context` 默认在查询层只返回 `canonical`，不会泄漏待处理对象。
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
| GET | `/api/world/maps` | 分页地图列表（`parent_map_id` / `status` / `skip` / `limit`；默认 active） |
| POST | `/api/world/maps` | 创建地图（含初始地形生成） |
| GET | `/api/world/maps/{map_id}` | 地图详情 |
| GET | `/api/world/maps/scene-summary` | 写作页 Scene 地图摘要 |
| GET | `/api/world/maps/open-target` | 统一地图打开目标（scene / focus entity / fallback） |
| GET | `/api/world/maps/quick-create/context` | 快速创建上下文（默认 canonical，可显式包含 candidate） |
| POST | `/api/world/maps/quick-create/preview` | 快速创建预览草稿；不落库、不识别正文、不创建世界对象 |
| POST | `/api/world/maps/quick-create/confirm` | 确认快速创建，一次只写入一张地图；`replace_map_id` 显式替换地点布局/绑定/quick-create fact，并保留其他地图图层 |
| PATCH | `/api/world/maps/{map_id}` | 更新地图配置 |
| DELETE | `/api/world/maps/{map_id}` | 兼容归档入口：归档完整子树并保留旧 204 响应形状 |
| GET | `/api/world/maps/{map_id}/archive-impact` | 查询归档子树及关联资产数量 |
| POST | `/api/world/maps/{map_id}/archive` | 锁定并归档完整地图子树 |
| POST | `/api/world/maps/{map_id}/restore` | 恢复完整子树；可用 `root_name` 仅重命名恢复根 |
| POST | `/api/world/maps/{map_id}/editor/apply` | 按 `expected_revision` 原子应用有序视觉编辑命令 |
| GET | `/api/world/maps/{map_id}/revisions` | 分页读取不可变视觉编辑历史（不返回完整状态快照） |
| POST | `/api/world/maps/{map_id}/revisions/{revision_number}/restore` | 重验依赖后恢复所选状态并生成新 revision |
| GET | `/api/world/maps/{map_id}/layer-tree` | 读取递归图层树及继承后的有效属性 |
| GET | `/api/world/maps/{map_id}/paths` | 按 active / archived / all 读取连续线路状态 |
| GET | `/api/world/maps/{map_id}/paths/{path_id}` | 读取单条 active 或 archived 线路及节点 |
| GET | `/api/world/maps/{map_id}/paths/{path_id}/archive-impact` | 查询线路归档前的 observation / fact 引用数量 |
| POST | `/api/world/maps/{map_id}/paths/{path_id}/archive` | 通过 editor history seam 归档线路 |
| POST | `/api/world/maps/{map_id}/paths/{path_id}/restore` | 重验图层、端点和几何后恢复线路 |
| POST | `/api/world/maps/{map_id}/generate` | 快速生成详图地形（中心 city + 外 road） |
| GET | `/api/world/maps/{map_id}/state` | 地图聚合状态（map+面包屑+地形+绑定，PRD §6.2） |
| GET | `/api/world/maps/{map_id}/dashboard` | 世界动态总控台派生状态（首屏层、动态队列、检查器、批量分组） |
| GET | `/api/world/maps/{map_id}/playback` | 世界动态播放派生状态（typed observation 轨道和事件） |
| GET | `/api/world/maps/{map_id}/timeline` | 类型化 Scene 时间线：差分、冲突、候选预览、未定时间事实和空间连续性问题 |
| GET | `/api/world/maps/{map_id}/state-at` | 指定 Scene 的正式有效地图状态；candidate 永不参与状态选择 |

`timeline` 默认不包含 candidate，并选择最近 50 个存在 confirmed fact 的 Scene stop；显式范围
最多跨 500 个 Scene。两个接口默认每页 100、最大 500 条，超限通过 `total/has_more` 明示，
不会静默把 candidate 合入正式状态。旧 `playback` 继续保持 `include_candidates=true` 的兼容
默认和原响应形状。
| GET | `/api/world/maps/{map_id}/location-layouts` | 地点布局节点列表 |
| PUT | `/api/world/maps/{map_id}/location-layouts` | 覆盖保存地点布局节点；`sync_bindings=true` 时事务化平移地点 footprint |
| PATCH | `/api/world/maps/{map_id}/tiles` | 批量编辑地形（PRD §6.3） |
| GET | `/api/world/maps/{map_id}/terrain` | 手绘地形图层/区域/patch/绑定聚合状态 |
| PATCH | `/api/world/maps/{map_id}/terrain/layers/{layer_id}` | 部分更新覆盖图层名称、显隐、锁定、透明度、排序、素材与 metadata |
| DELETE | `/api/world/maps/{map_id}/terrain/layers/{layer_id}` | 删除已解锁覆盖图层并返回 region/patch/binding 级联计数 |
| POST | `/api/world/maps/{map_id}/terrain/layers/{layer_id}/restore` | 重验图层/地点依赖后恢复归档覆盖图层 |
| PUT | `/api/world/maps/{map_id}/terrain/layers/{layer_id}/patches` | 覆盖保存某手绘地形图层最终 patches |
| POST | `/api/world/maps/{map_id}/terrain/regions/{region_id}/bindings` | 创建地形区域与地点绑定 |
| PATCH | `/api/world/maps/{map_id}/terrain/bindings/{binding_id}` | 更新地形绑定状态或类型 |
| POST | `/api/world/maps/{map_id}/location-bindings` | 批量创建地点绑定（PRD §6.4） |
| PATCH | `/api/world/maps/{map_id}/location-bindings/{binding_id}` | 更新地点绑定 |
| DELETE | `/api/world/maps/{map_id}/location-bindings/{binding_id}` | 删除地点绑定 |
| GET | `/api/world/maps/{map_id}/markers` | 动态标记列表（P1，可带 scene_id） |
| POST | `/api/world/maps/{map_id}/markers` | 创建动态标记（P1） |
| PATCH | `/api/world/maps/{map_id}/markers/{marker_id}` | 更新动态标记（P1） |
| DELETE | `/api/world/maps/{map_id}/markers/{marker_id}` | 归档动态标记（保留旧 204 形状） |
| POST | `/api/world/maps/{map_id}/markers/{marker_id}/restore` | 重验对象/Scene/坐标后恢复标记 |
| GET | `/api/world/maps/{map_id}/territories` | 势力范围列表（P2） |
| POST | `/api/world/maps/{map_id}/territories` | 批量创建势力范围（P2） |
| PATCH | `/api/world/maps/{map_id}/territories/{territory_id}` | 更新单格势力范围样式（P2） |
| DELETE | `/api/world/maps/{map_id}/territories/{territory_id}` | 删除单格势力范围（P2） |
| DELETE | `/api/world/maps/{map_id}/territories` | 按组织删除全部势力范围（P2） |
| GET | `/api/world/maps/{map_id}/focus` | 聚焦模式：仅返回指定组织势力范围（P2） |
| GET | `/api/world/maps/{map_id}/observations` | 地图观察事实候选列表，可按 `review_state` 过滤 |
| POST | `/api/world/maps/{map_id}/observations` | 创建地图观察事实候选 |
| GET | `/api/world/maps/project-observations/inbox` | 项目级未分配地图候选收件箱，支持类型、Scene、来源、置信度、完整度与稳定分页过滤 |
| PATCH | `/api/world/maps/project-observations/{observation_id}` | 以 `expected_updated_at` 更新未确认候选的作者字段 |
| POST | `/api/world/maps/project-observations/{observation_id}/assign` | 以 `expected_updated_at` 分配、换图或退回项目收件箱 |
| POST | `/api/world/maps/project-observations/{observation_id}/ignore` | 以 `expected_updated_at` 忽略项目候选 |
| PATCH | `/api/world/maps/{map_id}/observations/{observation_id}` | 以 `expected_updated_at` 更新 observation 作者字段（不直接确认） |
| POST | `/api/world/maps/{map_id}/observations/batch-review` | 以 `items=[{observation_id, expected_updated_at}]` 批量确认、忽略或标记冲突 |
| POST | `/api/world/maps/{map_id}/batch-actions` | 批量动作入口：候选确认/忽略/冲突、fact 状态、图层可见性 patch |
| POST | `/api/world/maps/{map_id}/observations/{observation_id}/confirm` | 确认 observation 并生成/复用正式 `map_facts` |
| POST | `/api/world/maps/{map_id}/observations/{observation_id}/ignore` | 忽略 observation，不生成正式事实 |
| GET | `/api/world/maps/{map_id}/facts` | 已确认地图事实列表，可按 `fact_status` 过滤 |
| PATCH | `/api/world/maps/{map_id}/facts/{fact_id}` | 软更新地图事实状态（confirmed / rolled_back / deprecated） |
| GET | `/api/world/entities/{entity_id}/map-presence` | 查询世界对象在 active 地图上的布局、绑定、标记、领地和地形 presence |

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
World Bible、生成模板，以及地图地形、地点、标记、势力范围、observation/fact 和 playback。
它是事实模块，不拥有正文、Scene、context confirmation 或 RAG 候选；AI 输出默认进入
待处理建议，只有用户明确授权的流水线才可按领域门禁写入可回滚资产。
