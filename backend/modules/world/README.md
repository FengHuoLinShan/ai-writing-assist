# Module: world / 世界对象与关系管理模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

对象包括地点、组织、物品、事件、规则、能力体系、秘密、传说、资源、人物引用。

## 核心原则

- 每个作者项目创建空 `C0` 与唯一 Canon head。World Bible 发布经服务端
  Preview/Admit 把精确 PageRevision 选入新 CanonRevision；同 decision 幂等，head 变化或
  工作稿漂移时 409 且保留工作稿。
- Canon receipt 的 authorizer 只能由服务端取得的当前 owner 账户或封闭 C0
  bootstrap 主体承担；AI、worker、validation result 和请求体字段不能授权。
- 历史 replay 不只校验 receipt/manifest 各自 digest；bootstrap 必须是确定性空 C0，
  page publish 必须把唯一 affected PageRevision 与父 manifest 转换、工作稿快照和
  canonical 页面快照相互绑定，revert 的 affected resources 必须等于目标 manifest；
  任一部分被独立替换都 fail closed。Phase 0 migration 可为旧 PageRevision 中既有的有限浮点
  JSON 生成兼容 digest 并继续 replay；新 Canon 输入仍拒绝浮点和非有限数。
- Phase 0 所有 formal family 仍为 `formal-disabled`；`world_assertions` 仅为封闭
  carrier，当前不提供 Assert 准入或形式推理。
- 对象抽取不是 NER，而是长期创作资产识别
- 手动创建对象默认直接写入 `status="canonical"`，并保留 `created_by` / `approved_by`；显式传入 `draft` / `candidate` 的旧调用仍保持原状态
- 正文世界对象自动识别统一由 imports 深度导入体系负责：首次导入使用
  `POST /api/imports/deep`，已有 Scene 的补抽使用
  `POST /api/imports/stages/world-objects`（Phase 2a/2b）
- AI 抽取对象以 `status="candidate"` 入库，等待用户确认、合并或忽略；不自动提升为正史
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSON 字段；每项以
  `kind=name|title|identity` 保存稳定最小分类，以开放短文本 `type` 保存精确类型
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入 `content_json.aliases`，单条别名携带 `status/source/workflow_id/scene_id/confidence/needs_review` 元数据
- 待复核别名可在确认前修改目标对象、别名文本和别名类型；来源、workflow、Scene、引用和置信度作为只读证据保留
- `world/review` 统一待处理工作台按全部 / 对象 / 别名 / 关系切换；“全部”只做概览和推荐，三个类型队列各自搜索、筛选、分页与写入。已采用 Page/工作稿/CoreEntity 在 `world/bible` 资料库以同一 tagged Card read model 浏览；关系仍是主入口，旧 `objects/aliases` 只作深链兼容与批量工具
- 前端从生成中心对象结果读取既有 `suggestion.result_ref_json.id`，用 `entity_id + review_item` 精确打开兼容影子并恢复决策焦点；已采用、忽略、归档或不存在的对象不会因精确深链重新出现在待处理队列，API 与 suggestion wire 不变
- 已采用关系与别名列表复用各自既有 `q` 查询：关系匹配端点名称、精确类型、描述或引用，别名匹配别名、所属对象或引用；所有条件继续受同一 `novel_id` 门禁和服务端分页约束
- `link_to_existing` / `alias_of_existing` 候选只有在目标已解析为同项目已采用对象 ID 且不是源候选自身时，才按“已有对象”聚合展示；目标仅有名称、指向待处理对象或指向自身时仍留在普通待处理队列。确认后源候选标记 `status="merged"` 并记录 `resolved_as="alias"`，不硬删除、不提升为正史
- 深度导入 Phase 2b 发现的关系写入 `entity_relations(status="candidate")`，两端可解析到 canonical / draft / candidate 工作对象；`relation_kind` 只取 `state/social/spatial/causal/temporal/epistemic/intentional`，精确关系仍保存在 `relation_type`
- 待确认关系可在确认前修改源对象、目标对象、关系类型、描述和强度；引用和来源章节作为只读证据保留，复核审计写入 `review_meta`
- 作者端待处理关系在现有分组内就地配对：拖动任一端点卡到“关系发起方”或“关系承接方”槽会自动补齐另一端，一次配对后沿用现有 `review-batch` 决策；取消保留指纹草稿，归并、复用和忽略仍需确认
- 待处理关系按有向 `(source_id, target_id)` 分组，别名按 owner 对象分组；Scene 只用于筛选和展示，反向关系不自动归并
- 类型目录只为详细类型提供推荐与保守同义词建议；显式合法 kind 优先，kind 缺失时只对已知详细类型推导。自定义候选可暂缺 kind，但关系采用为 canonical、别名采用为 active 前必须由作者选择；详细类型原值不被改写
- 关系筛选用来命中对象对，返回时仍包含该有向对的完整待处理成员；指纹也基于完整快照，避免筛选后提交必然过期
- 关系列表的可选布尔参数 `has_reverse_candidates` 表示该有向组存在反向方向的待处理候选，`has_canonical_relation` 表示同一有向端点对已有正式关系；两个条件均在计算 `group_total`、`item_total` 和分页前应用
- 别名与关系列表的 `group_total` 是筛选后分组数，`item_total` 是这些组内仍有效、未采用的候选条目数；分页始终按组。工作台和 Project“今日工作”的待处理计数使用条目数，不以分组数或当前页行数替代
- 分组列表为每组/每条别名返回 SHA-256 `execution_fingerprint`；批处理必须 `confirmed=true`，批次内先按 UUID 全局稳定顺序锁定端点和关系行，再为每个决策使用 savepoint；单组原子、组间可部分成功
- 人物扩展表 `characters` 保留历史独立 `aliases` JSONB 字段，新别名应优先写入 `core_entities.content_json.aliases`
- `characters` / `events` / `character_knowledge` 活跃扩展只能挂在同项目、类型匹配且已采用的 `CoreEntity` 下；人物 CoreEntity 被创建或提升为 canonical 时会确定性补齐最小 `characters` 档案，使导入人物立即可用于 POV、生成中心和人物上下文。作者显式保存人物档案时原位升级该 scaffold；自动 scaffold 不阻断后续类型纠正。列表与写作上下文默认排除父对象或 CoreEntity 目标已转为待处理/已归档的历史扩展行
- 对象分级：core / important / normal / temporary
- 版本回滚基于 `TextArchive` 归档与 `EntityRevision` 兜底（活跃回滚路由优先查询 `TextArchive`，无归档时回退到最近 `EntityRevision` 快照）

### 对象图片

CoreEntity 的 `image_version` 和 `image_updated_at` 只记录可选图片的版本；API 响应派生
`has_image`，不保存或返回私有对象 key。`PUT /api/world/entities/{entity_id}/image` 在当前账户
owner 与 `novel_id` 双门禁内只接受真实 PNG/JPEG（严格小于 6MiB、最大 4096×4096）；服务端
去 EXIF/元数据并生成有界 WebP。`GET .../image?variant=thumbnail|full` 仅返回已鉴权的派生图。

账户最多保存 20 张人物图及合计 50 张其他对象图；回收站项目仍占配额，替换不增加占用。对象
软废弃、融合和别名化不迁移或删除图片，项目永久删除才通过精确对象/项目前缀清理收敛。对象图片
不进入 RAG、LLM 上下文或通用媒体库。

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

三个别名只读入口（列表、分页、审核分组）共用一次按项目过滤的轻量投影，仅读取对象身份、
名称、状态和内联 aliases / `_meta`，沿用 importance / name / id 顺序；筛选、指纹和完整计数仍由
同一别名服务处理。工作流回滚继续使用完整对象扫描和加锁，不能复用只读投影替代写入快照。

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
- imports 专用的 `dedupe_deep_import_workflow_candidates` 只处理同 `workflow_id`、未编辑且仍为 candidate 的两端，复用同一融合判定、指纹重验与软合并。它不改变项目级智能去重、canonical 确认或 HTTP 契约
- 世界上下文/检索词典/批次（`EntityContextService`）
- 实体统计与自动抽取批次查询（`EntityStatsService`）
- 实体 embedding 回填（`EntityEmbeddingService`）
- 向其他模块提供世界上下文（`get_world_context`）
- 人物档案与知识边界（Character / CharacterKnowledge）

## World Bible 工作稿与世界观简介

`GET /api/world/knowledge-graph` 是只读关联图：仅展示已采用 World Bible 页面、已采用
CoreEntity，以及页面引用和已采用实体关系。它明确不推断 dependency 或变更影响；local
scope 支持 page/entity root 的 1–2 hop，结果有固定 cap、截断回执和来源 hash。

World Bible 页面是作者组织和解释世界事实的手册层；`CoreEntity`、Profile、关系和事件仍是
结构化正史来源。AI 地图册只消费这些来源，不反向写入。新版编辑流程不直接覆盖正式页：

1. 作者创建或打开 `world_bible_page_drafts` 工作稿；标题、类别、概览、结构化 sections、
   关联资产引用和排序均可编辑，结构化资产只提供引用与跳转编辑。
2. “保存并发布”先以只读 `GET /api/world/bible/drafts/{id}/publish-impact` 扫描当前项目内
   已采用页面的 typed 反向引用，列出最短直接／间接路径与未检查领域；不调用 LLM、不写
   task、revision 或建议。新界面把本次 source baseline 与引用 universe 的 scope hash 作为
   可选发布参数；引用边、页面版本或工作稿变化时返回 409 并保留工作稿，旧客户端仍可不传。
   发布本身继续以 `base_version_number` 做行锁 + CAS。
3. 前端先读取 Canon head 并调用 admission preview；确认后的唯一 Admit 事务原子
   更新 `canonical` 页面、递增 `version_number`、写带 digest 的不可变 PageRevision、
   选入新 CanonRevision、CAS 推进 head 并删除工作稿。恢复旧页面版本只创建
   新工作稿，不覆盖历史。
4. 页面类 AI 只在生成中心产生完整页面提案。作者可先编辑标题、类别、概览、sections
   和关联资产，再通过
   `POST /api/world/generation-center/suggestions/{id}/apply-page-draft` 落服务器工作稿；
   generic `/confirm` 明确拒绝该 suggestion target，AI 不能直接发布页面或改写 canonical。

`WorldBibleLifecycleService` 统一拥有正式页创建/更新、工作稿发布、发布影响预演、revision、
projection / 简介 / context 失效，以及生成中心使用的页面/工作稿 source baseline。影响预演
只在内存中对当前 `novel_id` 的已采用页面做 `O(P+E)` 广度遍历；损坏、不可见或非已采用页面
引用进入 omission，不能把“0 个显式引用”说成“0 个影响”。生成建议与应用建议
复用同一内容 hash、draft identity 和更新时间比较；`WorldBibleService` 只保留页面查询与
projection 任务编排，激活解析不再调用它的私有 hash helper。

正式页内容变化统一调用 lifecycle 的 `admit_draft()`，内部经 Canon Preview/Admit 后才允许
seal 页面修订；实际 seal 方法是 Authority 独占的内部 seam。旧页面 POST/PATCH 由 API adapter
转换为工作稿发布。纯 `status=archived` 只归档当前 workflow head，不改历史 PageRevision 或
Canon selection；恢复归档页仍须产生新工作稿和新 CanonRevision。

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

作者手动刷新简介时，worker 会重新物化 `world.world_bible.synopsis.refresh` confirmation，
并仅把其中实际 selected assets 对应的 source manifest 交给 provider；缺少 World 来源时失败
关闭。自动维护继续使用完整 manifest，人工任务也不会复用一个未绑定该 confirmation 的自动
任务。World 语义校验保持完整 manifest 的确定性门禁，但 LLM review packets 只来自相同的
confirmed allowlist。

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

内置类别为 `background/species/faction/location/rule/secret/custom`。`custom` 仅作为历史页面、
缺省调用与外部消费者的兼容兜底；作者从新建页面入口选择“新建分类”时，先创建项目
自定义分类，再用该分类创建工作稿，不会主动产生新的 `page_type="custom"` 页面。
项目自定义类别只保存 `key/name/description/color/icon/sort_order/status/default_template_key`；
默认模板只影响新建页面选择，`category_key` 创建后不可修改，归档不删除历史页面，
也不定义模板 schema 或资产激活规则。

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

地图册上传的 PNG 会剥离 tEXt/zTXt/iTXt/eXIf 等文本类辅助 chunk 后入库，
与 JPEG 的去元数据转码保持一致。地图册的独立图片上传是项目导入白名单之外的窄例外：仅该 owner-only
API 接受小于 50MB 的 PNG/JPEG，JPEG 在服务端校验、去元数据并转为
PNG 后才进入地图册私有 S3。此例外不改变 imports 的文稿上传白名单。

明确不做：

- 人物档案管理 → character 已迁入 world，不再独立模块
- 对象 embedding 全量实时更新 → evidence/indexing 子域
- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库

## 作者主动模型任务的 Context 门禁

生成中心聊天/收束/探索/建议、问世界、世界书语义检修、简介人工刷新、语义验证、对象融合与
地图册启动均要求 action 精确匹配的 `context_confirmation_id`。浏览器先通过 Evidence
非持久化预览审查 items，最终确认写一条记录；同步调用或 worker 在 provider I/O 前重新物化
并比较 `compiled_context_fingerprint`。生成中心与地图册直接消费确认后的编译 Context；问世界
和对象融合的领域候选按确认后的实际资产 allowlist 过滤，不能重新纳入作者排除项。自动简介
维护、导入去重等非手动内部阶段继续使用既有 snapshot，不重复弹窗。

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
- 世界书目录导入是 world 自有的受限文本入口，只接受相对路径标识与 UTF-8
  `.md/.txt/.json/.yaml/.yml`；单文件 2 MiB、正文总量 25 MiB、最多 2,000 文件。
  服务端不打开客户端路径，不执行脚本、Prompt、工具配置或 YAML 表达式。首次导入只创建
  `source_material` 工作稿；重导入以 `source_key/source_hash/baseline_content_hash` 做三方比较，
  双变和源缺失进入 `worldbook_import_conflict`，不覆盖、不删除。
- 已发布且 `page_key=validation-policy` 的页面可在
  `page_meta_json.validation_policy` 激活 `world_validation_policy.v1`。策略只接受
  有界命名 operator；`regex` / `forbid_regex` 禁止分组、或、反向引用与嵌套量词，
  不执行任意表达式、Prompt 或导入的配置文件。首次激活前保持旧项目行为；激活后，
  页面发布、采用包以及旧的对象/关系/别名/建议正典直写均必须经验证路径，避免旁路绕过。
- `world_validation_runs` 冻结 policy、manifest、依赖、target 与 ReviewPacket 哈希。
  结构层先运行，出错不消耗 LLM 预算；语义层仅使用项目级 secret-free snapshot，
  引文必须来自冻结分片。full run 以数据库部分唯一索引单飞，targeted run 不受影响。
  任一 policy/manifest/dependency/target hash 漂移都使回执变为 `stale/block`；
  `warn` 只能用当前 receipt hash 与完整 warning finding 集显式签收，
  `fail/author-required/insufficient-evidence` 不可绕过。
- `world_core_checkpoint.v1` 是兼容保留的 typed 收束来源 checkpoint；新的生成中心保存动作写入
  `world_design_checkpoint.v1`。两者均不可采用且只在作者显式保存时持久化；design envelope
  内嵌 `world-state 0.1.0` 的 19 区、6 循环、22 切面、5 耦合链与 12 压测分类，seed 阶段
  未有证据的区域必须保持 `gap/not-run`，不得伪造成已覆盖。`world_core` 预设仅适用于无模板 CoreEntity 目标，
  收束响应返回原始 seed 去向、3–7 条 can/cannot/cost/failure/maintenance
  规则原子、阻断矛盾和一条日常＋故障纵切。只有作者 seed 全覆盖、
  来源 manifest 覆盖完整、规则与决定项一一绑定且无阻断矛盾时才返回
  `ready_for_handoff=true`。人物、总纲、Scene 和完整国家／历史不属于该预设。
  `world_adoption_package.v1` 是作者显式保存的 pending 包；完成的 Deep Import 也会按冻结的
  Scene hash、workflow 与授权回执幂等组装一个包。已自动写入的对象以 `existing_ref/no-op`
  显示，candidate 对象/关系仍由作者 preview/apply；apply 不重复创建前者。preview 不写库，按 source refs、
  checkpoint lineage 和 payload hash 给出预期 diff；apply 只采用 `include + proposed` 的
  CoreEntity（create/promote）/ EntityRelation，使用 package-local ref，在同一事务 CAS pending 并写 receipt。
  `open` / `rejected` 不写事实；v1 不支持 RuleProfile 或别名。
- 生成中心的新对象先写 `creation_suggestion_queue`。队列服务同时物化一条
  `draft` / `candidate` 兼容影子，并以 `_meta.compatibility_shadow=true` 与
  `suggestion_id` 关联；采用或编辑后采用时提升同一条对象，合并/设为别名时由队列原子裁决并归档同一影子，忽略时同步标记该影子为 `ignored`。待处理影子不能绕过队列直接 CRUD，所有裁决都必须经过建议队列的 compare-and-set 门禁。
- 作者明确选“修订此版”时，生成请求可携带 `revises_suggestion_id`。服务在模型调用前校验同项目、同生成目标且 parent 仍为 pending；模型返回后在同一 request transaction 创建新版并用现有 pending CAS 封存旧版及兼容影子。`result_ref_json.revision_link` 只保存单一 predecessor/successor，并以 typed `revision_link` 投影给读取端；采用、忽略等终态写入不得丢失该关系。“另起方案”不携带 parent，已采用设定的修改仍走既有对象或页面 revision 流程。
- imports 模块拥有深度导入和阶段化正文抽取的编排、授权快照、Scene 证据与
  candidate 写入契约；world 只提供受控的对象、别名和关系持久化 seam。

## 数据表

| 表名 | 用途 |
|------|------|
| `core_entities` | 统一核心实体正史库（原 `world_entities`）；可空 `image_version` / `image_updated_at` 只标记私有图片，不保存对象 key |
| `entity_relations` | 对象间关系边（原 `relationships`） |
| `events` | 事件扩展表（entity_id PK+FK → core_entities） |
| `characters` | 人物档案（entity_id PK+FK → core_entities） |
| `character_knowledge` | 人物知识边界 |
| `world_assertions` | 不可变受限断言 carrier；Phase 0 无准入入口 |
| `world_canon_revisions` | 完整 Canon manifest、内联 admission receipt 与 decision 投影 |
| `world_canon_heads` | 每个作者项目唯一的当前 CanonRevision 指针 |
| `world_bible_categories` | 项目自定义世界书类别；内置类别不落库 |
| `world_library_topics` | 资料库主题目录：作者组织用嵌套主题树，`parent_id` 复合外键保证同项目嵌套，service 拒绝成环移动；归档主题不归档其资料 |
| `world_library_topic_members` | 主题成员：对 Page / Draft / Entity 的多主题引用（`target_kind + target_id`，无跨表外键）；独立工作稿发布时转换为 page 引用并去重 |
| `world_library_favorites` | 作者工作区收藏（`novel_id + target` 唯一） |
| `world_cocreation_sessions` | 持久化共创会话（ADR-0021）：以 `source_kind + source_id` 绑定项目/资料页/世界对象/主题，保存工作区形状与 `current_checkpoint_id` 指针；推进指针要求 `expected_checkpoint_id`，漂移 409 保留提案 |
| `world_cocreation_messages` | 会话终态消息（作者消息/完成的模型回复/作者决定）：`(novel_id, session_id)` 复合外键级联删除；生成回合绑定 confirmation 与 task，候选成果以 `outcome_suggestion_id` 引用建议队列，读取时推导待审阅/已存工作稿/已采用/已否定 |

作者编辑接口基线：draft PATCH、entity PUT 与 character PUT 均要求 `expected_updated_at`
（行锁内校验；缺失/过期分别返回 `edit_baseline_required` / `edit_baseline_stale` 409），
内部服务调用不受影响。
| `world_library_recents` | 作者工作区最近访问（服务端保留最近 50 条） |
| `world_library_workspace_profiles` | 每项目一条的资料库视图偏好 JSON |
| `world_bible_page_drafts` | 新页或已有页的服务器工作稿与发布基线版本 |
| `world_bible_pages` | 已发布作者手册页面；新版 UI 只发布为 canonical |
| `world_bible_page_revisions` | 页面发布点的不可变快照与 `revision_digest`，项目/页面/版本唯一，并以复合外键阻止跨项目页面引用 |
| `world_bible_page_projections` | 与页面版本/source hash 绑定的派生投影 |
| `world_bible_page_templates` | 项目自定义页面布局模板；与代码内置模板 key 隔离 |
| `world_bible_page_template_revisions` | 页面模板每次修改/恢复产生的不可变快照 |
| `world_bible_synopsis_heads` | 每项目简介指针、stale/pin/task 与自动维护授权 |
| `world_validation_runs` | 冻结校验输入、分片/结果哈希、coverage/budget 账本、verdict/gate 与 warning 签收回执；第四期扩展影响清单/分批计划/失效原因/续接计数 |
| `world_validation_review_items` | 逐条 finding 的作者复核处置记录，复合外键绑定回执，快照含 target/manifest hash（ADR-0022） |
| `world_bible_synopsis_revisions` | 作者版世界观简介的不可变 LLM 派生版本 |
| `entity_revisions` | 实体快照版本表（旧版快照；当前活跃回滚优先使用 `TextArchive`，无归档时回退到 `EntityRevision`） |
| `map_atlas_runs` | AI 地图册计划、上下文快照、任务进度与停止状态 |
| `map_atlas_nodes` | 封面到街道/室内的层级节点与采用状态 |
| `map_atlas_pages` | 独立候选/已采用/拒绝/移出图片与派生链 |
| `map_atlas_annotations` | 未绑定图片标注及其空间图元绑定入口 |
| `map_atlas_revisions` | 节点拥有的不可变空间结构、来源、约束与图片展示配置 |
| ~~`entity_aliases`~~ | 已移除，别名存 `core_entities.content_json.aliases` JSONB |
| ~~`entity_candidates`~~ | 已废弃；候选对象存于 `core_entities.status="candidate"` |
| ~~`relationships`~~ | 已废弃，使用 `entity_relations` |

其余当前 ORM 表按子域归档如下，避免只更新主表时漏掉 schema 所有权：

- 归档：`text_archive`；
- 类型化 Profile：`species_profiles`、`faction_profiles`、`location_profiles`、
  `rule_profiles`、`item_profiles`、`secret_profiles`、`entity_profile_templates`、
  `entity_profile_template_revisions`、
  `generic_entity_profiles`；
- 生成模板：`generation_prompt_templates`、`generation_prompt_template_revisions`；
- 知识边界：`knowledge_tags`、`character_knowledge_tags`、`asset_knowledge_tags`、
  `knowledge_tag_exclusions`、`knowledge_visibility_policies`、`reader_reveal_policies`；
- 作者待处理队列：`creation_suggestion_queue`、`conflict_check_queue`。

`character_knowledge.source_chapter_index` 表示人物学到该知识的章节。
读者/角色视角仅激活早于可见截止章的记录；无来源章节的旧数据默认排除，
只有显式标记 `is_public_baseline=true` 的开场公开知识例外。同章但没有更精确学习
位置的记录按保守规则排除。模型上下文还只消费 `status="canonical"` 的记录，并按目标
选择唯一有效检查点：先取最晚生效章，再按更新时间和稳定 ID 消除数据库返回顺序的影响。
同一目标、同一生效位置应使用 PUT 修正而不是继续新增；历史和已归档记录仍保留在人物知识
列表供作者审阅。`false_belief` / `misunderstood` 只把明确填写的 `misconception` 交给角色，
不会回退泄露作者已知事实。

### ORM 模型布局

`modules.world.models` 是兼容导出 package，导入该 package 会注册 world 所有
ORM 表到同一个 `core.base.Base.metadata`。具体模型按子域拆分：

- `models/core.py`：CoreEntity、Event、EntityRelation、EntityRevision、TextArchive。
- `models/character.py`：Character、CharacterKnowledge。
- `models/profiles.py`：世界资产 profile 与模板表。
- `models/worldbuilding.py`：生成模板、World Bible、知识标签、创设建议和冲突队列。
- `models/authority.py`：不可变 Assert、CanonRevision/head 与 Profile Template revision。
- `models/common.py`：共享 SQLAlchemy imports 与 pgvector/SQLite embedding column helper。
- `map_atlas_models.py`：统一地图 node/revision 与图片 run/page/annotation；图片字节仍存私有 S3。

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
- `image_version` / `image_updated_at` — 可空图片版本元数据；响应以 `has_image` 表示可读取性，文件字节和存储 key 不进入数据库/API wire
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
`accept_separately` 通过 `separate_relations[]` 为每个所选候选提供独立的最终端点、
类型、描述和强度，且同一决策中的最终关系键不得重复；`ignore` 把所选候选改为
`deprecated`。`unselected_action` 默认为 `keep_pending`，显式设为 `ignore` 时
一并忽略该有向组未选成员。同端点同类型已有正式关系时复用该关系；
归并来源写入 `review_history`，其他候选记录 `merged_into_relation_id` 后进入历史，
未选候选默认继续保持 `candidate`。因此大于 50 条的单组可分次处理，不要将整组成员数误作本次限额。
每个决策仍只使用一个完整组指纹和一个 savepoint；分别采用任一成员失败时整组回滚。
响应保留 `canonical_relation_id` / `archived_relation_ids` 兼容字段，并增加
`canonical_relation_ids` / `reused_canonical_relation_ids` / `ignored_relation_ids` /
`remaining_candidate_ids` 供工作台展示明确处理结果。

### aliases（内联 JSONB）

存储于 `core_entities.content_json.aliases`，格式为列表：
```json
[
  {"alias": "别名文本", "kind": "name|title|identity", "type": "name|title|nickname|alias|translation|abbreviation|自定义字符串"}
]
```

- 别名不创建新实体行
- `CoreEntity` 的通用创建、更新和采用入口会统一规范化该列表；已生效的自定义 `type` 必须有 `kind`，candidate 可暂缺
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

`map_atlas_nodes` 是统一目录，`map_atlas_revisions` 保存空间与展示版本；
`map_atlas_runs`、`map_atlas_pages` 与 `map_atlas_annotations` 保留图片生命周期。候选页分别保存直接资料、AI 视觉补全和冲突；加入地图册只新增
已采用页面，不修改 World 事实。图片字节存私有 S3，完整契约见 `docs/modules/15_map.md`。
纯空间节点的目录调整不依赖生图任务；未绑定世界地点的地图可修改标题，绑定地点名称仍由世界对象拥有。
读取当前地图与候选时重新核对来源，过期提示只更新响应，不改不可变版本或历史；保存与采用仍严格校验。
规划前可从正式 World Bible 和已回读正文提取空间线索；它们只补充持久化 page prompt，
不生成坐标、比例、方向或 annotation 几何字段。

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

## 统一地图内部结构

- `map_atlas_service.py`：owner 门禁、run/树查询、页面审查、派生候选、标注和图片读取。
- `map_atlas_workflow.py`：Context 编译、计划校验、父子串行生图、checkpoint 与 finalization。
- `map_atlas_storage.py`：PNG 校验与 map-atlas 自有 boto3 adapter，所有同步 I/O 在线程池执行。
- `map_atlas_tasks.py`：`manual_resume` 生成任务和不依赖项目 FK 的全局前缀清理。
- `map_atlas_facade.py`：项目永久删除唯一需要的全局 cleanup enqueue seam。
- `map_structure_schemas.py` / `map_structure_geometry.py`：受限图元与关系、确定性布局、三点仿射校准及结构 PNG。
- `map_structure_service.py`：节点独立创建、版本 CAS、候选与历史、图片层有效性、章首阅读投影。
- `map_structure_workflow.py` / `map_structure_images.py`：同一 confirmation 内的关系提取和结构引导生图；不重新发现已有节点身份。

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
`assemble_post_import_adoption_package()` 是 imports 完成 Phase 2 后提交冻结
workflow/result refs 的唯一跨模块入口；它只组装 pending package，不重放既有 adopted 写入；
`preview_worldbuilding_activation()` 调用确定性 activation preview 服务；
`get_world_bible_projection_candidates()` 按项目解析固定页面/CoreEntity TargetRef，并执行
最大深度 2 的页面链接或关系展开；BFS 每层批量读取实体、页面 projection 与关系，返回顺序、循环去重、256 项上限和过期 projection 回退不变；`get_world_bible_page_source_manifest()` 返回可审计的
页面版本、section 与 source hash；
`mark_worldbuilding_context_stale()` 保持函数内 lazy import `modules.evidence.facade`，
避免扩大 evidence ↔ world 循环 import 风险。

`get_world_background()` 返回只读的 `WorldBackgroundBundleContract`。它从已采用世界对象、
关系、事件、秘密、已发布 World Bible 页面和人物知识边界派生 token-aware 条目，供 context
编译；地图册 operation 使用 author-full canonical 模式，不写回任何事实。

`get_author_attention_summary()` 是 Project“今日工作”消费的只读稳定投影，返回冻结的
`WorldAttentionSummaryContract`：同一 `novel_id` 下待处理的世界对象、别名和关系数量及
确定性 `total`，并附加 pending 世界书冲突、审核组和未被兼容 shadow 覆盖的待采用建议。
checkpoint、stale/resolved 冲突、已处理建议和 task-only 临时结果不进入投影；对象、别名按实际处理组去重，
关系在首页保留 A→B 与 B→A 两条有向提醒并分别携带对应 `group_id`；关系工作台可显示反向候选提示，
但不自动归并两个方向。三类计数均使用当前仍有效且未采用的候选条目数，已采用、忽略、过期和历史项不计入。
实现位于 world 自己的 attention service，复用既有查询服务并
保持项目过滤；别名成员的 Scene/章节来源通过稳定响应字段读取，三类审核 target 保留对象或组
标识供领域页精确定位。root `facade.py` 仅 re-export，响应不包含正文、原始任务、owner 或密钥。

`list_entity_terms(..., include_review=True)` 是 RP source revision 整理时的窄只读扩展；它返回正式与
待处理名称/别名用于发现关键同名歧义，不会将 candidate 属性自动提升为正史。对象、
关系与 CharacterKnowledge 只在 interaction source revision 创建时冻结读投影，RP 结果不回写 world。

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
| GET | `/api/world/relations/review-groups` | 按有向对象对分页返回待处理关系组、完整成员和执行指纹；可选 `has_reverse_candidates` / `has_canonical_relation` 在分组计数与分页前过滤 |
| POST | `/api/world/relations/review-batch` | 显式确认的关系采用、分别采用、归并或忽略批处理 |
| GET | `/api/world/aliases/review-groups` | 按所属对象分页返回待处理别名组 |
| POST | `/api/world/aliases/review-batch` | 显式确认的别名采用、编辑或忽略批处理 |
| POST | `/api/world/entities` | 手动创建世界对象；未传 `status` 时默认已采用 |
| GET | `/api/world/suggestions` | 创设建议队列，响应包含作者态投影 |
| POST | `/api/world/suggestions/{suggestion_id}/confirm` | 确认普通建议；世界书页面工作稿建议必须走专用 apply 路由 |
| POST | `/api/world/suggestions/{suggestion_id}/edit-confirm` | 编辑世界对象建议并原子采用 |
| POST | `/api/world/suggestions/{suggestion_id}/merge` | 将世界对象建议合并到已采用对象 |
| POST | `/api/world/suggestions/{suggestion_id}/resolve-as-alias` | 将世界对象建议设为已采用对象的别名 |
| POST | `/api/world/suggestions/{suggestion_id}/reject` | 拒绝建议 |
| POST | `/api/world/core-checkpoints` | 显式保存不可采用的 `world_core_checkpoint.v1` |
| POST | `/api/world/design-checkpoints` | 显式保存不可采用的 `world_design_checkpoint.v1`；新生成中心每三轮使用此入口 |
| GET | `/api/world/canon/head` | 读取当前 CanonRevision 摘要，不展开 manifest 或 receipt |
| GET | `/api/world/canon/revisions/{revision_id}` | 在 owner/novel 门禁内验证并读取历史 revision 摘要 |
| POST | `/api/world/canon/admissions/preview` | 冻结 Page publish 或 revert 的 exact input，零写入 |
| POST | `/api/world/canon/admissions` | 当前 owner 显式确认后的唯一 Admit；服务端注入 authorizer/executor |
| POST | `/api/world/canon/revert` | 追加一个选择旧 manifest 的新 revision，不移动 head 回旧记录 |
| POST | `/api/world/bible/drafts/{draft_id}/publish` | 兼容发布 adapter；新客户端成对提交 `expected_canon_head` 与 `canon_decision_id` 以支持安全重放，旧客户端可同时省略，内部均只调用 Admit |
| POST | `/api/world/bible/imports/preview` | 受限预览目录清单；返回统计、映射与 hash，不回显正文 |
| GET | `/api/world/bible/imports/{suggestion_id}` | 恢复 pending 导入的紧凑预览 |
| POST | `/api/world/bible/imports/{suggestion_id}/apply` | 以 preview hash 创建/更新未发布工作稿并写入冲突队列 |
| GET | `/api/world/bible/validation-policy` | 读取项目是否启用发布前校验 |
| POST | `/api/world/bible/validation-policy/activate` | 首次显式启用内置结构/引擎校验策略；重放幂等 |
| POST | `/api/world/bible/validation-runs` | 用 operation id 提交 targeted/full 校验任务 |
| GET | `/api/world/bible/validation-runs` | 按时间倒序读取项目近期校验回执 |
| GET | `/api/world/bible/validation-runs/latest` | 按 scope/target 读取最新回执并惰性重算 freshness |
| GET | `/api/world/bible/validation-runs/{run_id}` | 读取不含 Prompt、token、原始 model snapshot 的校验回执 |
| POST | `/api/world/bible/validation-runs/{run_id}/accept-warnings` | 作者对当前 receipt 的全部 warning 做显式签收 |
| POST/GET | `/api/world/adoption-packages` | 保存或读取 typed WorldAdoptionPackage 建议 |
| GET | `/api/world/adoption-packages/{suggestion_id}/preview` | 零写入预演 package 的覆盖、diff 与 hash |
| POST | `/api/world/adoption-packages/{suggestion_id}/apply` | 以 preview hash 原子采用 package 的 include 项；重复 apply 返回 receipt |

`world_adoption_package.v1` 首版采用核心对象 create/promote/existing_ref 与实体关系 create/promote/existing_ref。
promote 和外部关系端点以服务端指纹参与 preview hash，apply 在锁后复验；既有同一
canonical relation 是 `existing_ref` no-op，不合并或改写。每个新建对象/关系均保存
package、item、来源、authority 与 manifest provenance；同一对象再次被采纳时追加
`world_adoptions` 回执历史，不覆盖旧来源。v1 不支持 RuleProfile 或别名；v2 增加下述
专项填空和内联别名动作，RuleProfile 仍不属于该契约。

### 专项查漏的世界领域边界

`get_focused_world_terms()` 按显式 ID 或规范名/有效别名查同项目全部身份候选，不使用首个
模糊结果作为身份。`get_focused_world_neighbors()` 只返回初始根的一跳 canonical 关系及
两端 canonical 对象；include_review 仅允许读取待审根本身。两者以稳定 ID 分页并返回
`truncated/next_skip`，消费方须保存续查进度。这是内部作者资料 seam，Evidence 仍在返回
用户或送入模型前执行各资产可见性、截止点和显式排除门禁；不直接展示原始 hidden 字段。

专项补全继续使用 `WorldAdoptionPackageService`，不建立第二套采用引擎或事实表。
`authorize_focused_world_completion()` 只能在当前 owner 的入队请求中，用现有
CreationSuggestion 的封闭 accepted carrier 保存 `focused_world_completion.v1`：固定
root、source manifest、章节范围、最大一跳、动作白名单及 executor task。自动导入根可按
显式授权的 `import_completion_hints` 策略在同一源范围内逐批确定。普通 suggestion 的
save/confirm/edit 不接受该 carrier。owner 发起恢复时可为同一不变授权追加 executor grant，
不改原授权 fingerprint；worker 无权创造或扩大授权。

`submit_focused_world_package()` / `apply_focused_world_package()` 消费
`FocusedWorldPackageRequest` / `FocusedWorldPackageApplyRequest`。v2 包只允许新增对象、
关系、内联别名，以及 `summary/public_info/hidden_truth` 的 fill_empty；不接受任意 JSON
字段、非空覆盖、类型转换、页面发布或 candidate promotion。`None` 和纯空白字符串视为空，
零值和 false 不视为空。名称/身份歧义、无可靠原文、缺失关系 kind 和已填字段进入 open；
混合包采用后仍另存 pending 复核包，不因自动采用其他项而隐藏这些问题。

提交和最终采用都在短项目 exclusive 事务内复验当前 owner、授权、task attempt/lease、
当前 Writing draft/hash、精确范围与唯一 quote。直接库侧邻居允许携带
`direct_relation_ref={relation_id,source_hash}`；world 重新核对其仍为本项目根与目标的
canonical 一跳关系，不能仅凭调用方声明 depth=1 扩大范围。字段 baseline 和实际采用
preview hash 在锁后刷新重验。启用 World Validation Policy 的项目继续要求 full-scope
validation receipt；warning 仍需作者签收，worker 不代签。

`rollback_focused_world_package()` 是 owner 显式撤销入口。采用回执逐项保存 before/after，
填空只对仍等于本次 after 的字段执行逆变更；后续人工修改保留并报告 conflict。新对象/关系
只软废弃；新增别名按完整内联内容 CAS 恢复。世界领域后续关系、人物档案与页面引用阻止
自动软废弃新对象。实体逆变更先原子保存 EntityRevision，再标记 Context/简介失效和
出场词表重建。此能力不改变 Canon head，也不写 assertion 或 World Bible 正式页。

package 也可携带一个完整的 `world_bible_page` create/replace 提案：它只在同一 package
中有页面项时预锁 Canon head，再经 draft → Preview/Admit 创建正式 revision 并选入新
CanonRevision。eligible 页面文字必须有
同包已采用 item/source 的 claim mapping；open/rejected 只能放 `projection_policy=excluded`
section，且不会进入可投影正文。页面预览保持零写入并把页面版本/impact scope 纳入 package hash。
| POST | `/api/world/generation-center/chat` | 世界工作区共创聊天；按作者选择的来源/目标加载上下文，不创建建议、不写业务资产 |
| POST | `/api/world/generation-center/convergence` | 对当前显式来源范围做只读收束；返回确定性 manifest、覆盖状态与最多 7 张决定卡。`world_core` 预设额外返回可交接门和 typed core 快照；均不创建建议或工作稿 |
| POST | `/api/world/generation-center/exploration` | 从当前世界书页只读探索一跳相邻缺口；最多返回 3 项，不创建建议或工作稿 |
| POST | `/api/world/generation-center/semantic-inspection` | 检修当前世界书页；确定性错误可阻断，LLM 只产生“需要决定／可以改进”的待处理检查项和范围回执 |
| POST | `/api/world/generation-center/suggestions` | 旧同步建议入口，兼容期 deprecated |
| POST | `/api/world/generation-center/suggestions/task` | 按 `operation_id` 提交可恢复建议任务；202 返回 task receipt，结果仍是结构化待处理建议 |
| POST | `/api/world/generation-center/suggestions/{suggestion_id}/apply-page-draft` | 将经作者编辑的完整页面提案写入或创建服务器工作稿；不发布 canonical |
| POST | `/api/world/ask-world` | 作者端只读问答；只消费当前项目正式页面与已发布正文证据，每条实质主张附可回开的当前来源 |
| POST | `/api/world/ask-world/citations/open` | 在当前项目内重新回读一条回答引用并返回 current／stale／unavailable |
| POST | `/api/world/ask-world/suggestions` | 作者显式把仍新鲜的回答保存为一条 pending 世界书页面建议；不直接写页面、对象、地图或正典 |
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
| PUT | `/api/world/entities/{entity_id}/image` | 上传或替换私有对象图片；仅 PNG/JPEG，经服务端规范化为 WebP |
| GET | `/api/world/entities/{entity_id}/image` | 读取当前账户和项目已授权的缩略图或完整图（`variant=thumbnail` 或 `full`）；不返回 object key |
| DELETE | `/api/world/entities/{entity_id}` | 删除对象 |
| POST | `/api/world/entities/{entity_id}/promote` | 将草稿/候选实体提升为正史；可选携带名称、类型和概要，在同一事务中编辑后采用 |
| POST | `/api/world/entities/{candidate_id}/resolve-as-alias` | 将候选确认为目标对象别名 |
| GET | `/api/world/entities/{entity_id}/relations` | 实体关系列表 |
| DELETE | `/api/world/entities/{entity_id}/aliases` | 删除别名 |
| PATCH | `/api/world/entities/{entity_id}/aliases/edit` | 编辑/移动并确认别名 |
| GET | `/api/world/entities/{entity_id}/revisions` | 版本历史（legacy，只读兼容） |
| POST | `/api/world/entities/{entity_id}/rollback` | 回滚到指定 scene_index（优先 TextArchive，无归档时回退到 EntityRevision） |
| POST | `/api/world/entities/{entity_id}/rollback-by-revision` | 按 revision_id 回滚（`entity_revisions` 兼容） |
| GET | `/api/world/aliases` | 别名列表；`q` 支持别名、所属对象和引用搜索 |
| POST | `/api/world/aliases` | 添加别名 |
| GET | `/api/world/entity-batches` | 实体批次分组列表 |
| GET | `/api/world/relations` | 关系列表（v3）；`q` 支持端点名称、精确类型、描述和引用搜索 |
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

- entity fusion 和世界生成中心通过 project runtime seam 消费项目 owner 当前已验证的
  账户连接。生成中心每次操作先冻结一份不含 Key 的 provider/model 快照，聊天、
  建议、决定编译、语义守卫和必要修订全部沿用同一模型，不再按请求档位覆盖账户模型。
  `quality_mode=pro` 仅表示用同一冻结模型多做一遍有界复核并返回完整修订结果；
  `fast` 保持单遍生成。LLM 输出继续只形成 suggestion/draft，不直接成为 canonical。
- 世界生成中心的受管模型步骤总上限为 1800 秒。服务在 provider 调用前提交准备阶段
  checkpoint，确保等待期间没有数据库事务；聊天或结构化结果返回后在落库事务内重新校验
  项目仍 active 并持有共享项目锁，以 page→draft 行锁重读来源页面，再按同一准备流程只读
  复编所选章节/资产、显式 Scene/剧情线/人物/对象、世界观简介、Activation Profile 和实际
  提示资料。项目已进入回收站时返回 404；任一实际输入发生变化时以 409 丢弃过时结果，不在
  长事务中等待或静默落库，也不为这次复验建立第二条调用快照。多轮对话的决策编译、
  结构化生成和必要的语义守卫重试共同受同一个 1800 秒总预算约束，避免步骤叠加后越过
  浏览器 35 分钟等待窗口；单次 provider client 同样允许 1800 秒。
- 生成中心世界工作区的自由聊天不创建确认记录，也不写业务资产；只有
  `POST /api/world/generation-center/suggestions` 创建待处理 `CreationSuggestion`。
  服务依据作者明确选择的 target 做确定性分派，模型不能改变落库目标，也不能调用工具。
  对象建议继续进入待处理队列；页面建议只能经专用 apply 路由进入服务器工作稿。
  聊天直接使用普通文本生成，再由后端以只含 `reply` 的 schema 校验非空与长度；它不启用
  provider JSON mode，避免空 content 进入高成本格式修复。空文本最多在
  同一个 1800 秒阶段预算内重试一次。
- `POST /api/world/generation-center/convergence` 位于聊天和建议之间，只整理请求中最近
  40 条有效对话、粘贴材料、当前页面 baseline、章节摘录、显式资产与实际纳入的项目背景。
  作者可经既有 `selected_asset_refs` 加入最多 16 个其他已采用世界书页；
  convergence 按页面概览与 sections 组成可分块来源，当前页仍是唯一编辑 baseline。
  服务端先按内容 hash 生成 typed source manifest；单次装不下时按固定字符预算顺序 map，
  再以固定二叉 reduce 收束，模型不能决定来源集合、继续步骤或调用工具。每步必须使卡片来源
  与留在原处的来源完整覆盖 manifest；漏项、未知 key、未声明的跨卡重复或计数倒挂会修复一次，
  仍失败则返回 `complete=false`，且不能形成作者决定消息。模型返回后会重验当前页与已选参考的内容 hash，漂移返回 409。响应最多 7 张卡，整个 endpoint
  不创建 `CreationSuggestion`、对象、页面或工作稿；map、reduce 和必要修复共用一个 1800 秒
  端到端预算，模型返回后仍重验页面 baseline。
- `POST /api/world/generation-center/exploration` 只支持“当前世界书页 → 相邻新页面”的深度 1
  预览。服务固定同一份 source manifest，最多返回 3 个带来源证据的缺口，也允许返回 0 项并
  说明停止原因；不递归、不调用工具、不创建 suggestion。作者只能选择其中 1 项，后续请求以
  source snapshot 和 SHA-256 fingerprint 重验，过期则 409。选择后的既有结构化生成只接收该项；
  如新页面确实改变来源页含义，同一次模型结果可额外给出 1 份来源页完整修订，但两页分别成为
  pending suggestion，均不自动应用，也不会继续探索下一跳。
- `POST /api/world/generation-center/semantic-inspection` 固定在作者当前页面和精确版本上运行。
  页面基线、hash、引用和投影状态由确定性检查拥有“必须修复”；模型只可输出带证据、定位、
  下一步和定向重检说明的“需要决定／可以改进”。旧 pending 检查随页面版本失效，历史仍可回看；
  回执明确列出 scope、source version、checks run／not run、omissions 与完成时间，不把局部通过说成
  整个世界正确。
- `POST /api/world/ask-world` 是作者端只读窄 workflow。world 先按 `novel_id` 列出当前
  `canonical/confirmed` 页面，并通过 context 的现有规划检索和 evidence 回读获取已发布正文；
  保守字面门槛阻止仅凭语义相似回答，context 再按最多 5 个来源／24,000 字符编译证据和
  included／excluded／truncated trace。调用通过 `open_project_llm_client()` 使用项目 owner 当前
  已验证连接；模型不能改变来源集合，关键主张只能引用服务端 citation key。回答前后都会重开
  来源并核对 hash；问题要求的数量、日期、人物、地点或原因没有直接证据时必须
  拒答，不能以相关旁支事实代替答案。回答本身零业务写入；只有独立的 suggestions
  端点在作者点击后创建一条 pending `CreationSuggestion`，且保存前再次重算回答 hash 与来源版本。
- 外部模型交接 P1 不新增上传或导入接口：作者仍在普通消息中声明当前 world target，单份回包
  通过现有 `pasted_context` 进入 convergence。前端在请求前按 Unicode 字符拒绝超过 55,000
  字符的回包并保留原文，使用 Web Crypto SHA-256 在当前有界会话中跳过字节完全相同的重复包；
  语义相似不自动去重。只有完整且未过期的 convergence 才能确定性导出同一份 Markdown／复制
  文本，文件不含 raw Prompt、token 或主动渲染的内部 ID。外部临时 ID、`checks_run` 和
  “已通过”始终只是来源声明，不生成本地校验回执；项目级来源明确不声称全项目未变化。
- 视觉简报 P1 也是前端有界会话能力：只从完整、未 stale 的 convergence manifest 与作者选择
  生成可编辑文本，确认／复制／下载均不调用后端或写业务表。来源或作者决定变化后旧简报只读；
  结构化地图预览复用既有 quick-create context／preview，最终写入仍必须由作者在原 confirm 动作
  中确认。AI 地图册与世界对象图片都经项目图片 runtime seam 使用固定 `gpt-image-2`
  adapter 和私有 S3；候选图片不会反向生成世界事实。
- 自由聊天把模型定位为世界设定共创搭档；模型可根据对话自主选择
  发散、比较、质疑、关键追问或阶段性收束，不使用固定问卷。最终结构化
  step 对存在往返修订的多轮对话先编译 author decision state，区分已确认要求、受支持发展、
  已作废内容、禁用专名、未决项、命名权限，以及本轮适用的“谁能知道／如何表达”边界；
  最终提案不再直接消费包含旧方案的原始助手历史。知识与表达边界只约束本次生成，不能创建
  `CharacterKnowledge`、术语表或世界事实。
  提案随后只审计作者边界，不评价创意偏好或要求补齐字段；禁用专名重新出现、作者仍要求
  不命名却生成专名，或提案擅自解决未决项时，结果不能进入待处理队列，并在同一阶段预算内
  重生成一次。决策编译、提案和审计从首轮请求就收到实际 Pydantic JSON schema；不依赖
  provider 的 `json_object` 模式猜测字段后再做一次高成本格式修复。聊天中的助手建议只有
  被作者接受或后续明显沿用时才进入对象建议。
- 自由聊天默认只完成当前最低充分动作：短灵感先给一个主方向、必要时最多两个短备选、
  3～7 条必要条件、一个普通日常切片、一个最高风险或作者边界和一个自然下一步；真正阻塞时
  最多追问一个问题，且先给可用内容。作者明确要求完整范围时不得暗中缩小；横向框架已经充分
  而实例仍薄时，只沿一个地点或载体、一个群体或视角、一个时间窗口和一个扰动做日常、故障及
  可观察后果的纵切，只在修补明确因果断点时引入一个新概念。压力测试实例不自动成为已采用
  设定；结果变成全书／分部的核心前提、叙事读法、基调或读者承诺时，只给可编辑摘要并建议
  转到既有故事总览，只有落到人物选择、事件或场景行动时才指向 Scene 规划。聊天本身仍不能
  创建 Scene、改 StoryOutline 或执行跨模块动作。
- 生成建议响应和 `CreationSuggestion` 列表以可选 `decision_state` 返回同一份作者决定摘要；
  对象建议继续从既有 `content_json._meta.author_decision_state` 投影，页面建议在 typed payload
  内保存可选状态。旧记录不回填、不调用 LLM，返回空摘要；前端不得解析两种 payload 形状或
  把浏览器编辑结果伪装成服务端决定状态。
- 页面提案中的 `unresolved_choices` 会确定性写入 `author-open-questions` 检查清单；该分区
  固定为 `author_only` 且禁止上下文投影，随工作稿和发布版本保留并可由作者编辑。完整页面
  修订若遗漏既有清单，服务会保留它；页面已占满 64 个分区时拒绝静默丢弃未决项。
- 生成建议请求的可选 `revises_suggestion_id` 只表示作者已选择“修订此版”；LLM 不判断修订、另起或修改已采用设定。新版建立后，旧版沿用 `rejected` 终态作为历史，拒绝新版不会自动复活旧版。
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
E2E_DATABASE_URL='<dedicated-postgresql-url>' make generate-e2e
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
- `shared.enums` — EntityType、Visibility、CandidateAction 等
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

空间地图仍属于 World 的可编辑派生资产，不进入 Canon 或 Scene memory。纯空间节点可显示和跳转；
图片移出不影响空间版本。完整 API、数据上限、校准和阅读条件见 `docs/modules/15_map.md`。

地图持续创作支持区域、城市、街区与街道，沿街/入口/朝向关系和按章节查询地图地点。已有图元可经
原确认资料生成局部候选，逐项采用由服务端计算完整依赖；历史结构与图片预览均只读。来源标记不
进入几何指纹，正文与世界事实不回写。接口、来源和候选边界见 `docs/modules/15_map.md`。
提取结果保留可解释的覆盖/舍弃摘要，每条来源独立核验引文。上传底图可追溯到同节点中可证明相同
空间和锚点的已保存校准版本；这不等于图片生成来源，也不改变过期底图或阅读权限。

## 项目助手接入（ADR-0023）

通用共创会话/消息实现与 ORM 现归 Assistant；world_cocreation_sessions 与
world_cocreation_messages 物理表和身份保留。World 服务复用共享会话存储，保留本域世界模型
上下文与持久共创任务编排；分页、检查点行锁和作者决定随共享服务恢复。World 仍提供来源、成果、
checkpoint 语义，并持有世界事实、采用包和复核结论。助手通过本域操作预览创建/编辑对象、
工作稿、关系/别名与采用包；正式政策、基线、去重、Canonical 准入和版本历史不被绕过。

助手可直接进行只读世界复核。没有已发布政策时使用固定的 assistant-advisory-v1 语义问题，
快照存于 WorldValidationRun 的 plan_json 并标为 assistant_advisory，不能用于正式采用许可；
不会发布政策页面。已有政策（包括关闭）优先，政策/来源改变使旧诊断失效。
工作稿和地图 Evidence inspection 仅供 author；地图只读取采用的空间版本，不返回私有图片URL。

助手可保存并推进本次讨论的 Core/Design checkpoint、准备 World 采用包，以及将整页建议
保存为工作稿。会话、轮次、父 checkpoint 与来源 manifest 由服务器绑定；继承前检查读取范围，
保留旧决定。指针漂移拒绝保存，不产生另一套正史或会话写入。采用包来源标记为讨论生成提案，
仍须经过原 World 预览、覆盖、基线和 Canon 校验。

地图助手可加入当前作品已采用地点（未知坐标保持空白）、修改图元名称/备注，并处理原版本
采用/恢复。它不获得任意坐标、图片上传或校准写入参数；名称/备注操作保留原几何、来源和锁定
位置。地图回读附带有界版本元数据，历史版本不作为当前地理事实。

Writing 连续性检查只通过 `facade.list_adopted_map_continuity_facts` 读取当前 adopted node 的 saved revision；仅返回两端都绑定目标地点、constraint 保留来源且来源 hash/引文仍可重验的空间关系。该 seam 不返回坐标或图片、不把地图复制进 Scene memory，也不把缺少路线声明解释为确定的地理事实。


### 助手页面维护

世界书标题、正文和段落修改只进入工作稿；预览不创建草稿，执行重验页面/工作稿基线。
发布沿用 Canon head、影响范围与正式复核门禁，返回发布版本和回执。历史恢复拒绝覆盖已有
工作稿，创建新稿后仍需发布；历史检索经 Evidence，只开放作者完整资料范围，不能当作当前
事实或角色知识。人物档案的真实字段变化会在同事务使相关 Context 与主动检查来源失效。

### 地图结果导航与图片依赖

`map-atlas/capabilities` 及 Assistant 能力接口分别投影空间编辑、上传、站内生图和外部画面
说明的可用条件。存储仅做非 secret 配置检查；缺配置在图片提交前拒绝，不消耗图片请求。
结构地图仍可编辑，外部画面说明仍须原 Context 确认。图片网络/账户故障保留原工作流恢复。
地图页面接受 `node_id + revision_id` 只读比较历史版本，以及 `run_id + page_id` 精确打开
图片成果；采用/恢复仍经原 World 校验，并创建新版本。图片内容不会从状态摘要推断。

工作稿发布后，旧 draft 链接通过 `drafts/{id}/publication` 读取同项目不可变 Canon 发布回执，
定位其精确页面历史版本；不按名称猜页面、不重新创建工作稿。已放弃或无法验证的来源明确失败。

### 资料整理体验

名称精确匹配、精确别名和名称前缀优先于描述命中；只在别名数组中判断别名。作者对象详情提供图片、别名、关系及分页历史入口，复用原有 owner + novel_id 保护的接口。审阅可直接核对建议方向、交换端点并连续处理；批量表必须逐行形成明确决策，歧义与缺证项仍可保留。跨地图地点绑定由作者明确选择图元，每个地图通过原版本 CAS 分别保存，允许部分成功并显示回执，不按同名自动关联。
### 资料库、共创与复核的可靠性边界

资料库元数据写入按 `novel_id` 取得事务级 advisory lock，使主题移动防环、收藏/成员幂等和最近访问计数覆盖并发请求；读取视图偏好不创建空行。`working=false` 排除独立工作稿。共创 checkpoint 推进在会话行锁内刷新当前指针后比较基线，数据库错误不得被作为“会话不存在”吞掉。

验证回执中的作者处置不能覆盖非 `AUTHOR-REQUIRED` 硬错误；`deferred` 保留待处理状态，不计入完成数量。失败回执也要重验冻结输入；语义续接必须携带原 `context_confirmation_id`，该值随 run 返回并存于 `scope_json`，旧回执缺少此记录时需新建校验。校验政策工作稿的后续编辑要求 `expected_updated_at`，沿用工作稿行锁与 409 冲突。内置政策以内容指纹识别，版本名相同不会替换作者规则；政策定义中的匹配字符串不作为作品内容自匹配。

正文影响预演从已采用的内联别名提取 alias 文本；扫描达到批次上限且仍有 cursor 时明确截断。该预演依然只证明返回的显式引用和字面命中，不能代表跨域语义一致性已经验证。

## 持续模型、跨域复核与大库入口

`POST /api/world/cocreation-turns/task` 将聊天与完整模型推演纳入 `world_cocreation_turn`（chat/design）。输入绑定服务器会话、expected checkpoint、显式历史与聚焦面向；Model 内项目标识不代替业务 novel/owner。完整模型由 `POST /api/world/design-checkpoints/revisions` 按 typed changes 继承并推进，作者决定独立于近期消息，旧成果从独立会话继续。原同步聊天仅兼容，不承担恢复。

`GET /cocreation-sessions/.../messages` 支持 search、skip/limit 与 around_message_id，并返回实际 offset；session detail 带最后操作引用。历史浏览不自动进入模型，未保存的推演预览可回看/显式恢复。完整模型条目可送入既有待审建议，模型快照不可直接采用。

影响清单使用版本与范围 hash，`POST /api/world/impact-preview/source` 精确回读当前来源；`GET /api/world/bible/validation-runs/{run_id}/source` 打开复核实际依据。语义 run 冻结确认后保留的内容、领域/深度、影响范围与只读 Focused Evidence 回执，不能重新注入被排除全文。旧无实际语义范围的回执过期；阶段完成、作者签收与 Canon 采用保持分离。

资料库首屏使用统一轻量分页/概览，正文与对应工作稿按深链读取；draft 列表可按 page_id 过滤。模板、规则、简介及健康回执按入口加载。生成中心资料选择同样使用轻量分页，后端页面目录只来自确认保留的 manifest，不再加载全库正文。


### 审阅与导航体验约定

资料库有查询词时先按姓名/有效别名精确、前缀、包含、描述匹配排序，再使用既有稳定排序并分页。关联图支持人物根节点，边返回具体 `relation_type`；对象历史列表返回既有只读 `snapshot`，仍受owner和项目隔离。问世界只使用confirmation保留的正文范围及版本/来源指纹；缺失别名证据明确待核对，不用置信度替代原文。

智能整理导入候选使用 Imports 的 `import_review_resolution` 持久任务，工作台与项目助手共用入口；
结果区分已整理、需要决定、可选建议与处理未完成。授权、恢复、来源和质量资格边界见
`backend/modules/imports/README.md` 的“智能整理现有候选”。旧候选与旧授权不自动迁移。

导入整理新增的根 facade 入口：list_review_resolution_candidates、authorize_review_resolution、
resolve_redundant_review_alias、prepare_review_resolution_decision、apply_review_resolution_decision。
它们只处理可证明导入来源的候选；其他 AI 建议继续遵守原 confirmation 与领域采用规则。
作者注意事项读取 Imports 的新鲜分流，生命周期候选总数与必须决定的问题数分别展示。
