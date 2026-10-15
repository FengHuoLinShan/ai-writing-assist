# 架构决策索引

本目录记录会长期约束实现的架构决策。ADR 正文保留作出决策时的背景和取舍；实现演进只通过
状态、补充说明或新的取代 ADR 表达，不把历史正文改写成当前模块说明。当前运行事实仍应先查
`docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块 README、ORM、migration 与测试。

新增、改名或调整 ADR 状态时，必须同步本索引，并运行：

```bash
make docs-check BASE_REF=origin/main
```

## 编号 ADR

| ADR | 状态 | 当前约束 |
|---|---|---|
| [ADR-0001](0001-state-assembler-ownership.md) | Accepted / Amended | `state_assembler` 现归属 world；Story continuity 经 world 稳定 seam 消费对象状态。 |
| [ADR-0002](0002-base-crud-service-shape.md) | Accepted | world 通用 CRUD 使用受限 BaseCRUDService 形状，不额外建立空 port。 |
| [ADR-0003](0003-leaflet-for-map-viewport.md) | Superseded | 旧 Leaflet 地图视口已由 ADR-0012 的 AI 地图册取代。 |
| [ADR-0004](0004-novel-evidence-retrieval-seams.md) | Accepted / Amended | writing 保持原文事实源；RAG 与 Context 归 evidence，允许受限的一跳只读提名，检索范围不等同已选资料或采用权限。 |
| [ADR-0005](0005-core-entity-type-transition.md) | Accepted | CoreEntity 支持受控自定义类型和可逆 Profile 迁移。空间类型由 ADR-0035 有意偏离（模型可读取并维护）；对象类型的 AI 边界不变。 |
| [ADR-0006](0006-world-bible-context-activation-ownership.md) | Accepted / Amended | world 拥有世界书资料，evidence/compilation 拥有激活规则和编译审计。 |
| [ADR-0007](0007-world-generation-center-consolidation.md) | Accepted | 世界设定 AI 统一进入生成中心；其接口收口部分取代 ADR-0006 的旧共存范围。 |
| [ADR-0008](0008-plot-thread-information-progression.md) | Accepted | 大纲按当前层创作，PlotThread 聚合信息推进，伏笔/揭示保留投影。 |
| [ADR-0009](0009-vue-frontend-incremental-migration.md) | Accepted / Implemented | Vue 3 SFC 已接管实际页面，hash router 仅保留 route-host seam；2026-09-12 将迁移期像素/DOM冻结要求修订为功能、数据、幂等性与可访问性回归。 |
| [ADR-0009 附录 A](0009-appendix-a-keep-alive-policy.md) | Accepted / Implemented | 所有视图离开时卸载；草稿和恢复状态使用显式 session，不缓存活 DOM。 |
| [ADR-0010](0010-public-browser-account-system.md) | Accepted / Amended | 公开账号、浏览器会话和 owner 门禁；账户连接/全局偏好归 account，项目偏好/effective composition 归 project；公开演示只读 principal 与 owner 副本是唯一受限例外。 |
| [ADR-0011](0011-keyed-task-coalescing-and-domain-owners.md) | Accepted | 任务合并只管 transport，领域 owner/generation/checkpoint 由所属模块保存。 |
| [ADR-0012](0012-ai-map-atlas-image-storage.md) | Accepted / Implemented | 统一空间版本与图片表现，保留固定图片模型、私有 S3、独立凭证与删除竞态边界。 |
| [ADR-0013](0013-operation-receipts-and-page-local-recovery.md) | Accepted | 作者发起的 AI 长任务以 operation receipt 去重，最多两个 attempt，只在原页恢复。 |
| [ADR-0014](0014-world-object-images-and-single-node-minio.md) | Accepted | 对象图片只经鉴权 API 读取；单机 MinIO 用私有双桶、受限应用凭据和 32GiB 硬配额。 |
| [ADR-0015](0015-story-evidence-and-settings-physical-fusion.md) | Accepted / Implemented | Story 已吸收 outline/memory，Evidence 已吸收 RAG/Context，账户与项目设置已分别归 account/project；持久化身份与稳定路由保持兼容。 |
| [ADR-0016](0016-worldbook-import-and-validation-governance.md) | Accepted | world 拥有受限文本目录导入与校验领域状态；外部脚本不执行，政策须作者激活，Ruby/WorldCheck 只作本地验收 oracle。 |
| [ADR-0017](0017-world-fact-authority-and-canon-revisions.md) | Accepted / Phase 0 implemented | 以 `novel_id` 级完整 CanonRevision、内联准入回执和单向 family cutover 收敛世界事实权威；Phase 0 已交付 C0、Page 选择与封闭回放。 |
| [ADR-0018](0018-versioned-author-source-context-for-rp.md) | Accepted / Amended（2026-10-07 缓存例外，M3 落地） | RP 只能以同 owner、显式版本化的 author 资料只读绑定进入 Evidence；source 读与 interaction 写严格分离；唯一例外为 RP 原作包私有派生缓存（完整预算前材料＋一个编译正文，ADR-0018 修订）。 |
| [ADR-0019](0019-local-theme-resource-packages.md) | Accepted | 现代简约双模式、浏览器本地受限主题资源包、无服务端上传及手机统一编辑器。 |
| [ADR-0020](0020-world-library-topics-and-workspace.md) | Accepted | 资料库主题目录（嵌套/多主题引用/发布转换）与作者工作区（收藏/最近访问/视图偏好）归 World 模块自有；统一 `/api/world/library` 只读合并分页，目录不构成事实依赖。 |
| [ADR-0021](0021-world-cocreation-session-persistence.md) | Accepted | 共创终态消息和 checkpoint 指针已持久化并以 CAS 推进；完整历史阅读界面、同步聊天回执和完整 world-state 增量续写尚未完成，不自动采用。 |
| [ADR-0022](0022-world-review-ownership.md) | Accepted / Implemented | 复核聚合与回执归 World（validation run 扩展影响清单/覆盖进度/逐项复核记录/失效原因）；Evidence 只读供证，Story/Writing/地图经稳定只读接口提供来源；定向查漏与分批续接复用同一 run；政策编辑复用 rule 页版本化政策。 |
| [ADR-0023](0023-bounded-agent-runtime.md) | Accepted / Implementation in progress | PydanticAI 有界单 Agent、项目助手与 RP 工具执行；Project 连接、Evidence 可见性、成组确认与领域所有权继续有效。目标运行内的写入确认适用由 ADR-0038 §6 修订（已采纳未实施）。 |
| [ADR-0024](0024-anonymous-public-demo-rp.md) | Accepted / Implemented | 公开演示使用 24 小时匿名 owner、精确冻结 source 与前台 taskless SSE；临时 Key 零持久化，不能放宽普通 source owner 边界。 |
| [ADR-0025](0025-product-knowledge-governance.md) | Accepted / Implemented | 全产品知识治理：全知导演、最小知情生成、独立复核；静态能力注册表 + 版本化回执 + 一次语义返修 + held release；不新增表/事实库/Agent 平台。第 4 条对参考维度的适用由 ADR-0037 §1 修订（只提醒不阻断，已采纳未实施）。 |
| [ADR-0026](0026-persistence-write-semantics-and-copy-policy.md) | Accepted / Implemented | 持久化数据五分类（可变/不可变修订/可变指针/派生/引导）；触发器为权威守卫；复制走身份映射→拓扑→单次最终态 INSERT；不可变历史不转移，demo copy 以追加 demo_import 修订重建副本历史。 |
| [ADR-0027](0027-bounded-collaboration.md) | Accepted / Implemented (experimental) | 注册业务蓝图的有限协作，单宿主三成员、受限投影、共享根预算和领域受理；角色排演保持观察与分支隔离。 |
| [ADR-0028](0028-shared-demo-account-login.md) | Accepted / Implemented | 演示共享账号口令登录：fail-closed 配置、常时比较 + peer 节流 + 安全审计、单配置账号的等价会话；不引入通用口令体系。 |
| [ADR-0030](0030-spreadsheet-migration.md) | Accepted | 表格迁移只走 `/api/imports/migrations`（仅 .xlsx/.csv），确认即采用并经 world/story 窄 facade 落为带来源、可撤销的已采用资产；AI 整理仅预览。 |
| [ADR-0029](0029-local-cli-image-only.md) | Accepted / Implementation in progress | 本机 CLI 只用于世界对象图片与地图册页面生成；文字路径断开并失败关闭，2026-10-14 收窄批准与领取入口、修正 RP 连接判断，并删除文字客户端与工具中继端点（`run_local_agent` 保留但无生产入口）；服务端拼提示词、逐任务确认主机权限、无产品工具、复核重编码输出，结果只作候选；旧文字 job 兼容实现边界见 [Local Agent](../modules/23_local_agent.md)，不代表重新授权文字路径。 |
| [ADR-0031](0031-module-dependency-directions.md) | Accepted / 第一、二、三批已实现 | 模块依赖方向分层与逐对裁定：低层调高层只能经消费方 contracts 的 SPI Protocol + 组合根 DI port；三批共消灭 24 个双向对（顶层双向对清零），G3③c 再随本机文字路径退役消除 4 条 local_agent 入边（world 图片入边保留），G8b 新增 `world.read_map_node_heads` 只读批量 head DI 键（棘轮零增量）。 |
| [ADR-0032](0032-guided-flow-orchestration.md) | Accepted / 实施中（BR-3） | Assistant 内 guided_flow 确定性编排层：服务端注册带版本步骤表（模型不可改）、三种步骤类型、进度由领域产物推导不存步索引、复用 AssistantRun 与既有开关/白名单、不新增依赖边；流程任务一律确定性 operation_id。 |

| [ADR-0033](0033-codex-text-runtime.md) | Accepted / Implementation in progress | 本机单用户账户文本连接默认 Luna/max，受限纯文本步骤与业务工具提案，沿用项目 facade 与信封；公开账户禁用，旧本机文字快照继续拒绝。 |
| [ADR-0035](0035-genre-neutral-spatial-model-and-custom-vocabulary.md) | Accepted / 未实施 | 空间文档 v2：小而封闭的计算特性内核加开放的项目类型（作者自定义或模型在世界演化中涌现，稳定 UUID、独立复核、作者优先、归档墓碑；特性在作者采用引用该类型的地图版本后才参与提醒）；多空间、行程声明、复用 `ObservationModality` 全部 7 种模态的处置、按章节或 Scene ID 生效（锚点按当前顺序解析，融合跟随替换，删除标待核对；档案与势力共用）；空间类型、档案面向与势力形态共用一份项目词表；类型清单指纹只进 `consumer_read_set`，并行时按顺序写入去重，证据失效退回涌现中；先把 `geometry_hash` 约束部分冻结为 v1 字段白名单，保证升级不改指纹；层级保留 `level` 列并新增可选 `level_type_ref`；空间类型对 ADR-0005 有意偏离；势力领地仅预留只读投影，现有势力字段保留待阶段 1 决定。 |
| [ADR-0036](0036-evolution-optional-reading-steps-and-spatial-discovery.md) | Accepted / 未实施 | 世界演化可选阅读步骤契约（登记表、API 默认关与新界面显式开启、失败隔离、并行生成顺序写入、根预算内按步骤子额度、覆盖四态、补扫与重算取代、方法指纹不含项目数据、共用契约测试；`discover_details` 为第一个实例，对象档案发现为第二个新增实例）；地图自动冷启动作为空间发现步骤挂在演化上（独立复核、不阻断主理解提交）；草图在已有候选或已保存版本上做增量候选（每节点至多一条待审 `auto_draft`，旧候选标 `superseded`，按批次合并生成），必要时才整片重做（层级来源按优先级取舍，矛盾标待核对）；允许绑定演化 World 候选地点；扩展 G8a 地图册消费端口覆盖线索派生节点；从不自动采用、不生成图片；演化成为默认导入入口前保留手动生成回退，深度导入不再增加阶段。 |
| [ADR-0037](0037-map-spatial-advisory-dimension.md) | Accepted / 未实施 | 修订 ADR-0025：新增参考维度，`map_spatial` 以参考维度进入写作/剧本/问答，缺失或省略不阻断、审查只出提示；参考维度省略单独记录、不进 `omitted`、不影响 `scope_complete`，只提醒，`policy_version` 升级；Scene 无位置身份时不猜地点；v1 地图即可做最小切片；地图变化沿用 G8b 读时比对、正文变化沿用 G8a；空间提醒不拦截；各能力开关默认关，经对比评测后开启。 |
| [ADR-0038](0038-ai-operation-catalog-goal-runs-and-trace.md) | Accepted / 未实施 | 合并原助手地图势力操作、统一操作目录与目标运行、操作留痕三份草案：界面与 AI 共用操作目录（剩余 `OPERATIONS` 插件先收口到注册表，未声明写路由棘轮），R0–R4 风险分级，目录项声明事务形态（单事务／多阶段，多阶段按领域回执对账、结果未知时停下），按需发现与下线失败关闭；作者指令与模型推断分开；模型规划的目标运行 `goal_run_v1`（`assistant_runs` 新增 `goal` 模式、不绑定对话会话、停点用 `waiting_approval`、部分唯一索引保证每项目一个活动目标运行；确定性范围比较，重新规划不得扩权；修订 ADR-0023 写入确认在目标运行内的适用）；费用只记计费状态不估金额；目录层留痕（会话加单调序号、保存点隔离、不记内容、高频操作按会话时间窗合并或豁免、180 天汇总）与代码化；首批地图与势力操作（势力待阶段 1）；用户已裁定作者可按目标开启 R2 自动执行（默认关）、本机默认记录界面操作；目标运行默认关闭。 |
| [ADR-0039](0039-world-object-dossier-layers-and-interfaces.md) | Accepted / 未实施 | 所有世界对象三层分工：World 存作者设定（按类型内核面向，含人物表达方式、地点与物件感官细节；作者自定义/演化涌现的项目面向存于 ADR-0035 统一项目词表并接入 `EntityProfileTemplate`；条目带来源、证据、生效区间（锚点规则同 ADR-0035）、可见性与状态，只经档案修订入口写入）、Story continuity 存按类型注册的时点状态与有向态度、Evolution 台账存派生倾向；旧接口写回与当前拼接相同则不改、不同则收拢为唯一作者条目（其他标已过时、可恢复），保留 409；`current_*` 迁移前先出映射表与读取方清单；作者有效期默认优先，结构化项按对齐键检测剧情覆盖并提醒，“允许剧情覆盖”开关默认关；Evidence 汇总三层的统一读取接口与简报（台账经只读 DI 键，ADR-0031 依赖表补登记）；演化对象档案发现（ADR-0036 可选阅读步骤契约的第二个新增实例）与更新提案，从不自动采用。 |
| [ADR-0040](0040-writing-copilot-scene-director-and-unified-notices.md) | Accepted / 未实施 | 合并原场景导演与副驾驶对齐两份草案：写作副驾驶对齐为本场、对象、导演、提醒四个标签；统一推演协议 `simulation_v3`（导演轮次、世界推进步、状态试验、RP 观察者回合为模式，基于 ID，协议不设上限、入口可有运行策略，沿用 ADR-0027 角色模拟规则），下线 `rehearsal_v1`／`observation_v2`（不再新建、旧运行只读，RP 过评测门禁后迁移）；场景导演一次点击推进一轮、不设人物/轮数产品上限（省略须披露）、发散度三档、少量事实硬规则；人物表演卡与反同质化；可勾选素材与角度存为参考剧本（保存内容副本），只提供思路、不进入 story 依据 hash、不作已采用剧本约束，正文另写（单章 AI 生成可经 `director_reference` 参考维度读取，或手写）；历史剧本树长期保留，只由作者删除、30 天可恢复；对象简报与 `object_dossier`、`character_pattern` 参考维度（省略按 ADR-0037 单独记录）；各领域注册只读提醒来源，Assistant 只经 `app/notice_source_registry` 聚合统一提醒（不直接导入 world/evolution；来源分已有与待接入，结构缺项改由 Story 计算），无处置机制的来源用独立处置记录；只提示不拦截；实施按参考维度 → 对象接口 → 统一提醒 → 导演的顺序。 |
| [ADR-0041](0041-world-progression-candidate-simulation.md) | Accepted / 未实施 | Story 持有世界推进：自由推进与导向推进（作者设定大致剧情或目标节点，模型推演路径并报告不自然处）；参与者默认上限 12 可自定义；一次点击一步，步长可选时间/节拍/自动，每步报告推进量，步数不设低上限、按模型推荐步长；作为 `simulation_v3` 的世界推进模式，角色视角意图、结构化输入契约下的确定性交汇检测与一致性检查；产物只能采用为大纲级候选或导演起点；不写 continuity/World/正文；默认关闭。 |

2026-09-15 的运行信封实现补充：已冻结能力使用 `AIRunEnvelopeV1` 累计请求与恢复，未冻结规模的
C3 任务仍按 ADR-0023/0025 的授权和领域边界暂停，不以通用临时额度替代产品裁决。

`ADR-0009 附录 A` 延续 ADR-0009 的编号，不是第二个独立决策编号。

## 主题 ADR 与细化索引

| ADR | 状态 | 当前约束 |
|---|---|---|
| [Character 能力并入 World](character-module-merge-to-world.md) | Accepted / Implemented | character 不再是独立模块，人物事实和知识边界归 world。 |
| [LLM、Worker、Embedding 背压与 CSP](llm-worker-embedding-backpressure-and-csp.md) | Accepted | 共享 LLM/任务基础设施采用有界并发、恢复和前端 CSP 基线。 |
| [Embedding batch queue 索引](embedding-batch-queue-architecture.md) | Accepted / Index | 指向上游背压 ADR 的 embedding 批处理细化，不建立第二事实源。 |
| [LLM 限流与熔断索引](llm-concurrency-throttling-circuit-breaker.md) | Accepted / Index | 指向上游背压 ADR 的并发和熔断细化。 |
| [imports 子包拆分](imports-module-decomposition.md) | Partially implemented | `entity_extraction/` 已落地；parsing/workflow/scene 仍保留兼容扁平入口。 |
| [world services 子包布局](world-services-subpackage-layout.md) | Implemented | 已按 core/map/worldbuilding 分区，并保留必要兼容 import seam。 |
| [Outline / Writing 依赖方向](outline-writing-bidirectional-dependency.md) | Partially superseded | offset 断章入口已取消；Scene contract loader 与只读 facade 边界继续有效；通用机制并入 ADR-0031（story↔writing 先例）。 |

## 状态约定

- **Proposed**：尚未批准或尚未成为实现约束。
- **Accepted**：已批准，后续实现必须遵守。
- **Implemented**：Accepted 决策已经在当前代码兑现。
- **Partially implemented**：只兑现了明确列出的部分，剩余范围不能当作当前事实。
- **Partially superseded**：部分原决策已被后续实现或决策取代，正文保留追溯。
- **Superseded**：原决策已被后续 ADR 完整取代，仅保留历史追溯。
- **Index**：细化导航，不制造第二个权威决策源。

完整性由 `docs/architecture/architecture-documents.toml` 和
`scripts/check_architecture_docs.py` 自动校验；`docs/README.md` 只链接本索引，不再手工维护
一份容易漏项的 ADR 子集。

ADR-0033 的 2026-10-14 已授权修订登记独立模型池、Luna 500k 完整输入与确定性 confirmed_scope；旧恢复限制保留。

- [ADR-0034 — 数据库配对的私有图片备份与恢复](0034-db-paired-private-object-backups.md)
