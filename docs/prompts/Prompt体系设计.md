# Prompt 体系设计文档（实际实现）

## 1. 设计原则

系统使用受确定性工作流编排的 Prompt 完成正文生成、结构生成、
抽取和切分任务，不构建自治多 Agent 运行时。

统一原则：

- 结构化 Prompt 输出经 schema 校验的 JSON；正文 Prompt 输出可审阅文本候选
- LLM 输出不直接写入已采用或正史状态
- 领域资产的持久化 `status` 不应由 Prompt 决定；定位、恢复等内部工作流可以用
  `resolved / partial / unresolved / uncertain` 表达本次判断是否可物化
- 创建/关联/忽略主要通过 `suggested_action` 或调用方路由语义决定
- reveal、知识边界以及待处理建议与已采用资产的隔离由调用方服务和上下文编译器共同保证

## 2. 当前活跃 Prompt

| 文件 | 用途 | 主要调用方 |
|------|------|-----------|
| `story_outline.md` | 预写阶段的小说总纲 strict preview | `StoryOutlineGenerationService` |
| `p20_plot_thread.md` | 当前剧情线及其信息推进的 strict preview | `P20GenerationService` |
| `p20_outline_arc.md` | 当前篇章纲的 strict preview，只引用已有剧情线 | `P20GenerationService` |
| `p20_planned_scene.md` | 当前 Planned Scene 细纲的 strict preview | `P20GenerationService` |
| `p20_evidence_audit.md` | P20 候选的项目证据、已物化范围与外部正史污染审计 | `P20GenerationService` |
| `p20_scope_rule_audit.md` | P20 候选的层级权限、世界规则与人物边界审计 | `P20GenerationService` |
| `p20_author_instruction_audit.md` | P20 候选逐字段遵守本次作者明确边界的独立审计 | `P20GenerationService` |
| `rag_reranker.md` | 模式感知的 RAG 证据价值排序与 abstention | `modules.evidence.indexing.reranker` |
| `scene_entity_extraction.md` | 深度导入 Phase 2a，Scene 世界对象、Delta 与不确定项抽取 | imports |
| `map_atlas_workflow.py` | 内联 step `world.map_atlas.plan.structured`：把已确认资料规划为最多 20 页的地图册层级；图片 Prompt 交给固定 Image API | world 地图册 |
| `alias_relation_extraction.md` | 深度导入 Phase 2b，基于完整锁定 Scene 与冻结对象/关系引用提取别名和关系连续性 | imports |
| `entity_fusion.py` | 内联 step `world.entity_fusion.decision.structured`：项目级智能去重与深度导入 `phase2_dedup` 共用的结构化实体融合判定；导入路径只发送同 workflow candidate 的类型、名称、已确认别名、截断摘要和 Scene/章节来源，不加载整书 RAG | world |
| `scene_fusion_draft.py` | 内联 step `outline.scene_fusion.draft.structured`：基于选中 Scene 卡和精确正文生成融合语义草稿 | Scene 工作台 |
| `world_generation_center_service.py` | 内联 steps `world.generation.chat.generate`、`world.generation.convergence.map/reduce`、`world.generation.exploration.preview`、`world.generation.semantic_inspection`、`world.generation.core_entity.structured`、`world.generation.world_bible_page.structured`、`world.generation.world_bible_new_page.structured`：世界设定共创、只读收束、一跳探索、当前页检修与结构化建议；加强复核在同一冻结账户模型上追加 `.quality_review` 第二遍 | world 生成中心 |
| `ask_world_service.py` | 内联 step `world.ask`（snapshot prompt name `world.ask.v1`）：只根据当前项目作者可见证据生成带引用回答或明确拒答 | world 作者问答 |
| `world_bible_synopsis_service.py` | 内联 step `world.world_bible.synopsis.structured`：把已采用世界事实压缩为作者版 P1 世界观简介 | world 世界书简介刷新任务 |
| `generation_prompt_template_service.py` | 内置创作视角与项目级自定义模板；作为 author brief 进入生成中心 | world 对象共创 |
| `writing/services.py` | 内联 step `writing.generation.candidate.generate`：根据已确认上下文生成正文候选 | writing 正文生成 |
| `writing/semantic_review.py` | 内联 steps `writing.semantic_review.chunk_N`、`writing.targeted_revision.generate`：冻结正文/合同的独立近读与 finding-bound 返修 | writing 审查返修 |
| `outline/ai_workflow_service.py` | 内联 step `outline.ai_workflow.analyze.generate`：回答作者指定的大纲结构问题 | outline 手动大纲分析 |
| `interaction/prompts.py` | 内联 `interaction-story-v2`：模型知识 RP 故事正文与可选隐藏尾部元数据 | interaction 故事任务 |
| `interaction/prompts.py` | 内联 `interaction-summary-v1` / `interaction-summary-output-v1`：一次生成新分段概要与更新后总回顾 | interaction 回顾任务 |

## 3. Prompt Contract System

深度导入链路和生成中心结构化建议链路使用 `backend/tools/prompt_contracts/` 做开发期漂移检查，覆盖
Phase 1a Scene slicing、anchor repair、continuous-gap recovery、Phase 1b Scene enrichment、
Phase 1c Scene fusion、Phase 2 world extraction、
Phase 2b alias/relation、Phase 3 simple structure、StoryOutline preview、P20 三类当前层
创作、P21 RAG evidence reranker，以及 Generation Center 的
`world_generation_core_entity`、`world_generation_world_bible_page`、
`world_generation_world_bible_new_page` 和 `world_bible_synopsis`。检查入口是
`make prompt-contracts` 或 `cd backend && python -m tools.prompt_contracts check`。

Contract 使用 JSON 声明 prompt 字段、Pydantic schema、关键持久化映射、目标表列和
纯函数 probe。它不执行真实 LLM、不访问数据库、不扫描全仓库，也不允许任意 callable、
shell、表达式或动态代码执行。默认只有 P0/P1 阻断；文档漂移先作为 P2 记录。

生成中心的用户自定义模板另有运行时 validator：保存、预览和生成前校验
`{{variable_name}}` 占位符、必填变量、模板长度、对象类型和危险指令。运行时 validator
只渲染模板片段，不暴露完整正文、隐藏系统提示、API key 或 raw LLM payload；真正的
结构化输出契约仍由后端固定 scaffold 和 Pydantic schema 控制。

## 4. 历史 Prompt

| 文件 | 状态 | 说明 |
|------|------|------|
| `structure_review_memory.md` | 已删除 | `review` 模块已移除，不再保留 Prompt 文件 |
| `extract_chapter_scene.md` | 已删除 | 与 imports Scene stage 的 Phase 1a/1b 重复；正文到 Scene 统一由深度导入场景阶段负责 |
| `extract_character.md` | 已删除 | 旧人物补抽入口已移除且无生产调用；不保留无工作流、无输出物化契约的孤立 Prompt |
| `structure_extraction.md` | 已删除 | 旧逐章世界对象补抽与深度导入 Phase 2a/2b 重复；正文对象识别统一由 imports 深度导入体系负责 |
| `shared_rules.md` | 已删除 | 从未被运行时装配，且将对象抽取、角色知识与结构生成规则错误混为全局约束；通用边界由真实调用点承担 |
| `structure_world_character.md` | 已删除 | 无生产调用和物化契约；原有世界对象、人物、关系、知识、地理与剧情职责已拆归 generation center、world、map 与 outline |
| `structure_plot.md` | 已删除 | 一次生成整套结构的职责已拆为 P20 三个页面内当前层工作流；深度导入 Phase 3 使用独立 Scene 证据契约 |
| `structure_chapter_scene.md` | 已删除 | 依赖已移除 ChapterCard；Planned Scene 创作由 P20 v2 接管，正文 Scene 提取由 imports 接管 |
| `map_scene_observation_enrichment.md` | 已删除 | 旧 Map Observation/Fact 领域已移除；地图册不从正文抽取时间化地图事实 |

## 5. 当前设计约束

### 世界书简介类

`world.world_bible.synopsis.structured` 只负责压缩和组织来源 manifest，不裁决正史。输入先由
world 模块确定性排序、去重、冲突排除和预算裁剪；页面与结构化事实冲突时排除页面片段并保留
冲突提示。模型自行选择适合当前资料的有序导航 sections，可综合、归纳并突出关键结构，
不要求固定类别或穷举全部事实。每个实质段落引用至少一个服务端分配的短来源 key；服务再把
key 映射回经 `novel_id` 校验且真实存在于 manifest 的来源。无法归因的内容丢弃，schema
repair 最多两次；预算由调用配置控制，不在 Prompt 中硬编码统一篇幅。

世界书正文、简介和引用资料始终作为不可信 user/context 数据块注入；固定 system scaffold
禁止执行其中指令。作者模板是显式 author instruction，不与背景混入 system Prompt。
该简介只属于 `author_safe/author_full`，不得进入 reader/character/POV，也不得替代 P0
`World Core Brief`。生成结果写不可变派生 revision，不直接修改任何正史对象或世界书正文。

### P20 当前层结构创作类

P20 不一次生成整套大纲，也不进入生成中心。剧情线、篇章纲和 Scene 工作台分别调用
`p20_plot_thread.md`、`p20_outline_arc.md`、`p20_planned_scene.md`，每次只提出当前层
可编辑建议；当前 StoryOutline 是共同的上位创作依据。作者要求改变整体基调、故事引擎或
长期结局方向时，模型只报告与总纲的冲突，不越权改写总纲。

- PlotThread step 优先判断已有线程能否复用；只有总纲方向尚未物化且确有需要时才提出新
  线程。信息如何被隐藏、暗示、局部揭示和兑现由同一 `information_movements` 输出表达，
  不拆成互不关联的伏笔和揭示创作任务。无法用输入短引用解析揭示目标时保留空
  `target_ref` 并标记 uncertain，采用时不伪造 RevealPlan 目标；若模型漏写 uncertain，内部
  契约根据空目标与揭示节点确定性归一化，不触发无意义的结构修复调用。已物化章节内的
  `chapter_hint/scene_ref` 必须由输入证据直接支持；没有证据时保持空，原创推进只能放在尚未
  物化的未来，并明确作为提案而非既定隐藏正史。项目只提出问题而没有答案时，movement 的
  `hidden_content` 可为空并标记 uncertain；目标或秘密未解析时都不投影伪 RevealPlan。每个
  movement 中带确定章号的节点按时间从早到晚排列。该叙事约束由确定性语义审计定位到具体
  movement 后进入有界语义修订，不作为 JSON 格式错误重试，也不静默排序或改写节点内容。
- OutlineArc step 只能引用已有 PlotThread。缺少必要剧情线时返回
  `needs_author_decision`，不得跨层暗建线程。
- Planned Scene step 以“可独立规划、修订、续写和检查的因果叙事单元”定义 Scene，
  不按章节或固定节拍拆分。它可以跨章，允许无真实冲突及其他真实不适用字段；新建时不制造
  `scene_chunks`、章节 ID 或正文锚点，修订已映射 Scene 时也无权改变这些事实字段。

三个 strict schema 都允许 `no_change` 和 `needs_author_decision`，不规定输出数量，也不让
LLM 输出数据库 ID、status、source、needs_review 或持久化动作。作者指令、总纲、确认上下文
和已有资产全部作为 fenced 不可信 user JSON；模型只使用服务端短引用。每次首次请求就在
system 中附带目标 schema 的完整 JSON Schema，不依赖校验失败后的 repair 请求才告知字段结构。
候选生成后并行执行项目证据/外部正史污染、层级权限/世界规则和作者指令忠实性三类审计；候选、
审计、最多两次完整语义修订和复审共享同一个 30 分钟阶段预算；额外修订不会重新获得一份
30 分钟预算。审计给出字段或短引用修正时必须逐项执行，无法可靠修正则清空引用并标记不确定。
作者明确排除的内容不能借
`author_decisions` 的问题、选项、例子或不确定项重新进入候选。审计会区分已物化章节事实与尚未
写作的原创未来，
不会把“缺少现成证据”误当成禁止创作。确认编译要求
`budget_tokens=0`，完整实际确认内容进入 provider，不做 P20 应用层裁剪；人物最多 6 个、
非人物对象最多 16 个仅是相关资产范围。人物先通过稳定 facade 分页读取全部同项目候选，再按显式
选择、作者指令/总纲命中、Scene 出现、结构关联和 author-safe 档案相关性选择，不能把首个 50 条
分页误当全库。provider 上下文超限时任务失败，不静默摘要。

生成结果只进入 `outline_generate` 可编辑 preview。采用时服务重建总纲、所选资产和确认内容
共同构成的 fingerprint，并在一个 savepoint 中原子应用。新增资产记录 AI provenance；修订
保留 ID 与原 source，并追加前值快照。PlotThread 的 information movement 由确定性
materializer 投影到 `foreshadowing_plans` / `reveal_plans`，两边用同一
`information_movement_id` 关联。

### RAG 证据重排序类

`rag.reranker.generate` 只在确定性混合检索和 embedding 去重之后工作，不负责回答查询、
生成创作内容或裁决项目事实。`RERANKER_ENABLED` 默认关闭；开启后，`search`、`context`
和 `extraction` 在候选数大于最终 `top_k` 时都可调用项目 LLM。输入包含检索 mode、可选下游
purpose、原始召回分及已有 `2 * top_k` 候选池的完整 chunk 正文，不在 reranker 内再次按
候选数量或字符数静默裁剪。查询、正文和元数据以转义后的不可信 user JSON 注入，模型只引用
`candidate-NNN` 短引用。
重排必须以查询指定的对象、能力、关系和时间边界判断证据价值；“练习、能力、发现、边界”等
通用词命中不能把无关技能或事件提升为证据。

整轮 P21 调用（包括结构修复）使用同一 1800 秒总预算，项目 client 的请求超时与该
预算一致；前端调用窗口为 35 分钟，用于覆盖服务端持久化与响应交付余量。

strict 输出先审阅完整候选集合，再只列出值得保留的 `direct / supporting /
counterevidence / topical_only` 候选；无实际价值的候选可以省略，不要求模型机械复述
`irrelevant` 项。输出同时包含整体 `supported / partially_supported / unsupported /
uncertain`、依据、不确定项和置信度。确定性 materializer 拒绝重复或未知引用；
`extraction` 不采用仅主题相关片段。高置信 `unsupported` 返回空结果，构成真正
abstention；`uncertain`、低置信或 provider/schema 失败保留原排序并告警。证据角色是确定性
首要层级，避免主题提及覆盖直接证据；同一角色内依次使用模型证据价值分、模型显式顺序和原始
混合分稳定排序，不再使用固定 30%/70% 权重。

### 小说总纲类

`outline.story_outline.generate.structured` 用于世界设定之后、正式写作之前的长篇总纲创设。
system 只加载 `story_outline.md`；作者意图、项目概况、世界书简介/页面、核心规则、
显式选择或自动 Top-K 的人物/对象和可选当前总纲全部作为不可信 user JSON 数据块注入。
输入不加载章节正文、Scene、RAG、OutlineArc、PlotThread、伏笔或揭示计划。World Bible
page / 核心规则始终走有界 Top-K；人物和普通对象仅在没有显式选择时自动 Top-K，作者
显式选择始终优先。

结构化输出严格只有 `title / creative_core / outline_markdown / major_storylines /
macro_movements / open_decisions`，数组无固定数量；禁止 ID、status、版本号和章号字段。
导航数组只辅助浏览，不作为关系键；schema 不要求名称唯一或字符串精确交叉引用。
结果只是可编辑 preview，不创建 StoryOutline revision，也不写任何下层结构资产。
任务使用 project LLM execution snapshot，worker 先核对提交时 context hash，再做 provider 前
checkpoint，并在 provider 后重验 context hash，同时在 task meta 保留实际纳入/省略 ID、
Top-K reason、source refs 和 hash。

项目上下文是“已采用事实”的唯一来源；模型对作品标题或同名作品的外部记忆不能作为
证据。作者明确禁止借用外部正史时，这类污染即使被放入例子或开放决策也会被拒绝。
创作未来仍是总纲的核心职责：新设计可以大胆、具体，但必须是本版方向、条件提案或
开放决策，不能冒充项目正史。首次候选后的窄语义审计只检查这一证据边界、作者明确指令、
已采用设定冲突和层级越界，不以审计模型的创意偏好要求修改。如需语义修订，最多重生一次；
一般证据/作者意图审计不读取外部正史；另一个独立污染检测 step 只利用模型知识判断
候选已经出现的细节是否来自项目未提供的同名作品后续，不得补充候选未出现的正史。
第三个独立 step 只检查候选是否违反已采用世界硬规则或人物知识/行动边界；普通提案和
`open_decisions` 也不能把明确致命或禁止的机制当作普通选项。
候选、三类审计和修订共享 1800 秒总时限。所有 structured 请求从首次调用就携带 exact
`OUTPUT_CONTRACT`，避免让 provider 在 `json_object` 模式中猜测字段。
精确章号、章数区间和“前 N 章”式宏观阶段由本地确定性守卫兜底拒绝。

作者编辑 preview 后通过 `POST /api/outline/story-outline/generate/apply` 显式采用。
该入口只接受 task ID、编辑后的 strict content、CAS base revision 和 idempotency key；
服务端会校验 completed task 的 `task_type / novel_id / action / result / context provenance`，
然后写入 `source=ai_generated` revision。客户端不能提交 provenance，因此不能把 AI
preview 伪装成 manual revision，也不能引用其他项目的 task。

### 抽取类

- `scene_entity_extraction.md`
- `alias_relation_extraction.md`

这类 Prompt 面向“从已有正文中识别长期资产”，重点是：

- 不是 NER，而是长期创作资产识别
- `scene_entity_extraction.md`（P13）只读取一个锁定 Scene 的完整精确正文及相关结构上下文，输出长期世界对象、持久 Delta 和不确定项；关系、新别名、数据库 ID、持久化动作和审核状态不属于该契约
- P13 的既有身份只允许引用服务端生成的 `entity-xxx`；每个可物化观察必须提供当前 Scene 中可逐字定位的证据。正文与项目资料都作为 fenced 不可信 JSON 注入，system prompt 保持静态
- P13 不按固定类别或数量凑结果，也不对输入做应用层字符/token 裁剪。直接名称/别名命中全部保留；其余人物 Top-6、非人物对象 Top-16 是相关性边界
- `alias_relation_extraction.md`（P14 v3）独占新别名和对象关系；它复用同一份冻结的完整 Scene 正文、相关结构、`entity-xxx` 身份候选和 `relation-xxx` 既有关系引用，不接受数据库 ID，也不做应用层输入裁剪。关系输出是当前 Scene 带来的增量，不是本 Scene 中仍成立关系的摘要；模型用“删去本 Scene 是否会改变关系可信度、状态、强度或后续创作约束”做反事实判断。模型先判断联系是否在 Scene 结束后仍成立，区分 `enduring / stateful / episodic / uncertain`；只有持久结构和持续状态能进入关系候选，会面、提及、检测、支付、感谢等一次性动作只保留诊断。模型同时区分新建、有实质新证据的再次确认、改变和终止；日常称呼、例行共处和重复记载不算再次确认。关系类型优先复用已有类型和稳定语义族，但不以数量上限裁剪真实关系。确定性 materializer 重新校验项目归属、冻结关系、逐字证据、持续性和快照来源，只写待复核候选或补充证据，不自动覆盖或废弃已采用关系。别名不创建重复对象，并作为带 `identity_scope`、判断依据和快照来源的待复核内联证据写入目标对象
- 临时对象优先忽略或标记为临时
- 深度导入只有在任务保存授权快照后才可执行允许的候选写入，并保留 `auto_ingested`、workflow、证据和回滚元数据；P13 的身份引用、类型和证据由确定性 materializer 校验，异常结果进入 `uncertain_items` 或待处理

### AI 地图册规划与图片 Prompt

`world.map_atlas.plan.structured` 消费 `world.map_atlas.generate` 编译出的 author-full canonical
资料、RAG `map_atlas` 证据和可选工作稿。规划前会对至多 20 个已采用地点以每批 5 个提取
可审计的空间线索；只有服务端选择的已发布 World Bible 段落和经 RAG 原文回读校验的正文可进入
该步骤。输出由 `AtlasPlan` 校验：最多 20 页、无环、父级先于
子级、默认不深于街道，并为每页分别列出直接来源、AI 视觉补全、冲突和标注。来源短引用必须
属于当前 `novel_id`；run 固化 secret-free context snapshot、source manifest 与 hash。

图片 Prompt 使用地点完整名称作为语义锚点，但明确要求成图不出现文字、字母、数字、方向箭头、
距离、比例尺、图例或层级标签；前端标注层只显示地点或地标名称，不显示层级、方向、距离、比例或图例。
生成、整图编辑、蒙版与多参考图直接调用固定 `gpt-image-2` Image API；
图片模型不输出结构化业务状态，也不能把视觉补全写回正式世界资料。

### Scene 切分与深化

深度导入 Scene 阶段的 Phase 1a / Phase 1b / Phase 1c Prompt 在 imports 的
`workflow_llm_adapters.py` 中按职责分别组装，并通过 adapter、token budget 和 schema
guard 输出中间候选或融合候选。项目不保留独立的 legacy Scene 切分 Prompt 或单章恢复
入口；所有导入正文的 Scene 提取统一进入正式深度导入链。

Phase 1a 把三个不同判断拆成独立 Prompt：

- 主窗口切分先整体理解连续正文，以“可独立规划、修订、续写和检查的因果叙事单元”
  定义 Scene。目标、冲突、状态、认知、POV、时空变化只是判断线索，不是固定检查表；
  不按章节、字数或目标数量切分。输出同时声明窗口左右延续关系、每个 Scene 的
  boundary basis、confidence 和 conflict status。真实没有核心冲突时允许
  `core_conflict=null + core_conflict_status=not_applicable`，不得制造伪冲突。
- anchor repair 只消费锁定 Scene、起止章节正文和相邻已验证边界，只负责定位；可以
  `partial` 或 `unresolved`，不能为了满足 schema 伪造另一侧 anchor。
- continuous-gap recovery 一次消费完整连续缺口、左右 Scene 卡、边界正文和相关结构
  上下文。模型按正文顺序返回 `extend_left / new_scene / extend_right` segments；缺口
  全部属于相邻 Scene 时可以不新增 Scene，也没有 segment/Scene 数量上限。

窗口调用前冻结前一章最多 2000 字尾部、当前范围的 active working Scene/篇章纲/剧情线，
以及 `author_safe` canonical 人物 Top-6 和非人物世界对象 Top-16。选择顺序固定为正文直接
提及、已有 Scene 关联、篇章/剧情线关联；没有相关资产时保持空上下文，不加载整库对象。
bundle 保存实际纳入/省略 ID、选择原因、内容 hash 和 contract version。普通 deep import
在单次运行内复用该 bundle；Scene-only stage 使用 prepare v2 冻结 fingerprint，并在正式
提交前重编译，未完成的 v1 prepare 必须重新提交。

Phase 1b 不再把 Scene 覆盖章节的整章正文交给模型。确定性 materializer 按全部
`scene_chunks` 重验 source draft/hash/offset 并物化完整 Scene 正文，且不设置应用层输入
字符/token 裁剪、摘要或采样；跨窗口 Scene 会合并相关冻结 bundle，并按正文提及、Scene
关联、篇章/剧情线关联重新选择人物 Top-6 和非人物对象 Top-16。调用还包含当前和相邻
Phase 1a Scene 卡、相关 active working Scene/篇章纲/剧情线，以及 context/source
fingerprint。

Phase 1b 输出契约 v2 使用可空 `emotional_beat / must_happen / must_not_happen`、现有
作者界面 taxonomy 内的 `narrative_tag`、自由 `narrative_function`、`basis`、
`uncertain_fields` 和 `confidence`。空值且字段未列入 `uncertain_fields` 表示明确不适用，
列入则表示证据不足或存在冲突；模型不决定 `needs_review`，也不为满足必填制造情绪、事件
或禁止项。来源/provider 失败时本地保留空语义和 `narrative_tag=draft` 并进入复核；
`imported` 只属于历史兼容值，提交时归一为 `draft`，导入来源由 `source=deep_import` 表达。
`valley` 和 `transition` 仍是合法叙事标签，Phase 2 不据此跳过 Scene。

Phase 1c v2 分为两个独立 Prompt。boundary review 按 Phase 1a 窗口成组读取完整候选
序列与正文，一次覆盖窗口拥有的全部相邻边界，输出 `same_scene / duplicate / overlap /
separate / uncertain`、融合意图、依据、置信度和候选内部 concern；它不移动边界或改写
Scene 卡。只有来源精确、无 concern/uncertainty 且边界高置信的同一 Scene 连通组才进入
synthesis。synthesis 基于组内全部正文和相关长篇结构上下文重新理解完整因果过程，输出
统一 Scene 语义，不以第一个候选为骨架，也不拼接成员字段。真实无冲突或无禁止项可以
为空；低置信或含 uncertain 字段的综合结果只形成建议，不自动采用。

正文、Scene 卡、项目资料和已有资产都作为转义后的不可信 user JSON 数据块注入，不能
闭合数据边界或覆盖 system 权限。所有窗口完成后，确定性 materializer 统一协调 edge，
再执行 anchor repair 和连续 gap recovery；恢复结果必须通过唯一 anchor、offset、顺序、
无重叠、无空洞、source draft/hash 和邻居存在性校验，并按整个 gap 原子应用。失败时保留
精确整章 fallback，不部分采用模型结果。
原 outline `extract_chapter_scene.md` 及其独立 preview/apply 工作流已删除；手写正文和
导入正文都通过 `POST /api/imports/stages/scenes` 复用同一 Scene 提取能力。

### Scene 工作台融合类

`outline.scene_fusion.synthesis.v2` 是同步、只读的结构化 step，并复用 Phase 1c 的
`SceneFusionSynthesisOutputContract`。输入包含用户当前选中的完整 Scene 卡、通过 writing
稳定 range ref 重新校验的全部精确 SceneSpan 正文，以及当前范围相关的 active Scene、
篇章纲、剧情线、伏笔/揭示、人物 Top-6 和非人物世界对象 Top-16；不扩展为无关整库扫描，
也不做应用层输入裁剪。单次最多选择 20 个 Scene。输出包含可空语义、
`core_conflict_status / narrative_function / basis / uncertain_fields / confidence`；章节映射、
Scene chunk、POV、状态和 provenance 由 outline 确定性逻辑保持。调用失败时只返回带
warning 和 uncertain 状态的确定性草稿，不写入任何 Scene；保存仍需用户显式选择。
融合语义会综合全部选中 Scene 的兼容信息并去重；`primary_scene_id`
只在多个方案同样有证据支持或冲突无法兼容时作为意图、叙事重心和
表达取向的偏好信号，不是融合骨架，也不得导致其他 Scene 的有证据信息被忽略。
原 Scene 的 must/must-not 先按其原有边界理解；融合后已经失效的“不得进入下一 Scene”类
边界约束必须移除或改写，确定性语义审计发现这类自相矛盾时会要求一次有界修订。
provider 调用前完成 context/DTO 编译并结束数据库事务。作者保存后，明确不适用与仍不确定
的字段状态写入 `structure_meta`；后者继续触发复核，不因点击保存而自动变成完整设定。

### 正文生成类

`writing.generation.candidate.generate` 把模型定位为长篇小说共同创作者，
直接输出可审阅的正文候选，不输出提纲、分析或 JSON。默认模式输出目标章的
完整替换稿；当前 Scene 即使跨章也只提供结构上下文，不能把 Scene 当成候选的
替换范围。续写模式接收锁定 base draft 的完整正文，只输出从最后一句开始的
新增正文；确定性 materializer 将其追加到原文，并拒绝擅自增加会约束后文的
长期规则、承诺、期限、关系变化或重大后果。已确认上下文作为
有边界的 user/context 数据注入，不进入 system Prompt。

写作上下文优先包含当前 Scene、当前章活跃剧情线、相关人物和物品。
人物与相关世界对象超出预算时，按显式选择、Scene、篇章、剧情线和
RAG 证据的关联顺序取 Top-K；人物上限 6，相关世界对象上限 16。
该 Prompt 不预设字数、段落数量、描写比例或统一节奏模板，允许模型补充
不改变重大设定的局部、可逆写作细节。结果只保存为 candidate，仍需作者显式采用。

### 手动大纲分析类

`outline.ai_workflow.analyze.generate` 把模型定位为与作者共同判断结构的长篇小说叙事顾问，
而不是固定节拍表的评分器。作者未指定问题时，模型自行识别最影响后续创作的结构关系；
作者给出明确目标时直接回答该问题。模型可按资料选择因果、冲突、节奏、铺垫与兑现、
信息揭示、Scene 功能、人物能动性或主题等有解释力的角度，但不要求逐项覆盖，不预设
三幕式、英雄旅程或统一标题/条数/篇幅。分析区分资料支持的观察、结构推断和供作者选择的
建议；提出改动时说明预期效果与代价，现有结构成立时也应直接说明。

上下文先在 confirmation 中固定：`chapter_index..visible_until_chapter` 表示作者确认的分析
范围，范围内 Scene 按叙事顺序呈现，并包含重叠篇章、区间重叠或被范围资产显式关联的
剧情线，以及伏笔和揭示计划；关联人物
取 Top-6，相关世界对象取 Top-16。任务按确认记录重编译上下文，确认指纹一致后才消费
确认后的 Markdown 和范围元数据，二者均作为
有边界的不可信 user/context JSON 注入，不能覆盖 system 规则；task range 与 confirmation
不一致时拒绝执行，显式范围未成功加载时确认或回放失败关闭。`confirmation.task` 是唯一经作者
确认的分析目标，任务 metadata 中的兼容性 `instruction` 不能覆盖它。输出是自由中文 Markdown，
只作为只读分析返回，不提供 apply、不写入
剧情线、篇章、Scene、伏笔、揭示或正史事实。

#### 单角色 POV 正文候选

`writing_pov_character` 生成目标章节的完整替换候选，不生成跨章 Scene 的
完整正文。目标章已有 active 正文时，任务把该版本的完整正文作为锁定 JSON 数据
注入并纳入 prepare/finalize 指纹；模型只在作者明确要求处改写，保留其余内容、
既有事实和叙事顺序。当前 Scene、剧情线和导演约束只提供结构与连续性依据，
作者本次明确边界优先，不能为了收束 Scene 而补写其它章节或越过停止点。
输出仍为 `pov_state / draft_prose / uncertainties`，hidden guard 的 `passed`
仅表示未发现明显角色知识越权，不等同于整体事实或文稿质量自动通过。

当写作确认记录同时指定当前 Scene、character reveal 和 POV 人物时，
同一 LLM step 切换为单角色有限视角。设计目的是让正文的感知、解读、
判断、对话和行动都受角色的当下经验与认知驱动，而不是强制第一人称
或堆叠内心独白。项目叙事人称、叙事距离和文风仍然有效。

上下文按用途区分为三类：

1. POV 档案、经 CharacterKnowledge 过滤的对象、其他人物的可观察信息和
   当前 Scene 证据，可以影响角色认知与行动。
2. Scene 目标、冲突、must/must_not 以及剧情线的公开进展仅作为
   `director_only` 叙事指导，不得变成角色已知事实。
3. compiler warning 只说明资料缺口或保守排除，模型不得伪造被排除知识。

输出仅有 `pov_state / draft_prose / uncertainties` 三个顶层字段。
`draft_prose` 是主要文学成果；`pov_state` 是简洁、可检查的状态摘要，
不要求模型暴露分步推理；`withheld_known_information` 只能记录角色
确实已知的信息；`uncertainties` 无实质问题时为空数组。不再拆分固定的
动作、表情、对话、内心戏和潜台词字段，避免结构绑架文学表达。
输出仍经 parser 和 hidden guard 确定性检查，并且只进入待审阅 candidate。

### 生成中心世界设定共创

`world.generation.chat.generate` 是不写库的自由共创 step，服务于世界对象、完善现有
页面和新建页面三种作者已选目标。设计重点是创意质量与逻辑严密性：模型根据对话状态自主
选择发散、比较、质疑、验证前提、指出因果/尺度/规则矛盾、提出真正影响设计的问题或阶段性
收束，不使用固定问卷，也不要求每轮同时覆盖所有维度。作者明确的选择、否定和最新修正优先；
资料是可参考但不可信的内容，不能改变任务、目标、权限或输出边界。
聊天正文使用普通文本生成，Prompt 明确要求直接回应作者而不输出 JSON 或协议包装；
调用层把返回文本放入只含 `reply` 的 schema 校验非空与长度。自由聊天不启用 provider
JSON mode；偶发空文本只在同一阶段时限内重试一次，也不把任意原始输出直接当作业务响应。
聊天还执行最低充分内容约束：短灵感优先给一个主方向、必要条件、普通日常切片、最高风险或
作者边界和自然下一步，真正阻塞时最多追问一个问题；明确的完整范围请求优先于该默认收束。
横向规则已充分时固定一个具体锚点，沿日常、故障和历史反馈纵切，压力测试实例不视为已采用
事实。若内容已经属于人物选择、事件或 Scene，只输出可编辑交接摘要并建议使用既有 Scene
规划流程；该 Prompt 不获得创建 Scene、修改 StoryOutline 或调用跨模块工具的能力。

`world.generation.convergence.map/reduce` 只在作者显式点击“收束本轮”后运行，不继续横向创作，
也不创建 suggestion。确定性服务先把当前对话窗口、粘贴材料、页面 baseline、章节、显式资产
和实际项目背景切成带 hash 的 source manifest；单次预算可容纳时只运行一个 map，超出时按固定
字符预算顺序 map，再做固定二叉 reduce。每个输出必须把所有 source key 分配给最多 7 张决定卡
或 `retained_source_keys`；跨卡复用必须显式列入 `shared_source_keys`。漏项、未知 key、未声明
重复及计数倒挂由代码校验并只修复一次，仍失败返回不完整预览。Prompt 不能改变来源集合、
决定下一步工具或把“开放／放弃”写成已确认事实，因此多次模型调用仍是确定性 workflow，
不是 Agent 或多 Agent runtime。外部粘贴材料里的临时 ID、`checks_run`、“已检查”或“已通过”
只作为来源声明，不能冒充本地对象或本地校验回执。map、reduce 和必要的修复调用共用一个
1800 秒端到端预算。

`workflow_preset=world_core` 是同一确定性工作流的窄预设，不是新 Agent。
对话每轮仅做 `expand / connect / pressure / consolidate` 一个动作；收束必须
将每条作者 seed 精确标记为体验承诺、已包含、开放或否定，并输出 3–7 条
`can/cannot/cost/failure/maintenance` 规则与一条日常＋故障纵切。应答
消息不能充当作者 seed；人物、故事总纲、Scene、完整地理、国家和历史不在
此预设的交接门内。服务端重算 seed 覆盖、来源覆盖、规则绑定、N/A 理由、
阻断矛盾与纵切引用；任一不符时只返回 `ready_for_handoff=false`，不写入资产。

收束结果如需成为采用依据，作者须另行显式保存为不可采用的
`world_design_checkpoint.v1`（旧 `world_core_checkpoint.v1` 继续可读），再保存
`world_adoption_package.v1`。checkpoint 把现有收束确定性投影为 seed 深度的完整世界状态分类，
未知区只记 gap/not-run；这两个保存操作不调用模型；
preview 与 apply 都由 world 的确定性 schema、source refs、lineage 与 CAS 校验完成，模型不能
创建或采用 package。
若 package 含完整 World Bible page proposal，eligible 文本的每条 claim 必须由同包 include
item/source mapping 覆盖；页面仍只在作者 apply 时通过既有 lifecycle 发布 revision，不新增模型步骤。

`world.generation.exploration.preview` 只在作者从当前世界书页请求相邻新页面时运行。服务端冻结
同一份 typed source manifest，并要求模型返回最多 3 个深度 1 缺口或明确停止原因；每项必须
引用已知 source key，不能写页面正文、递归寻找下一跳、调用工具或创建 suggestion。未知 key
只修复一次。作者单选后，后续结构化 Prompt 只收到该项及其证据；来源 snapshot 或请求内容
变化会在调用前由 fingerprint 拒绝。`world_bible_new_page` 的同一结构化输出可选携带一份完整
来源页修订，但只有具体内容改变时才各自写成两条 pending suggestion；不会自动应用或再探索。

`world.ask` 只处理作者查事实、比较关系和追来源的问题，不承担补设定或推荐下一项创作。
确定性服务先固定当前项目、作者可见性、正式 source version 和最多 5 个回读来源，再把问题与
有界 `SOURCE_EVIDENCE` 作为不可信数据交给模型。每条实质主张必须使用服务端提供的
`citation_key`；未知 key 只修复一次，仍无合法引用就失败。无相关证据时服务在模型调用前拒答；
有证据但不足以支持结论时 schema 要求 `no_answer=true` 且 claims 为空。模型不能调用工具、
保存回答、更新 Wiki 或声称已经修改设定。provider 返回后服务重新回读来源 hash，漂移则 409；
只读回答与作者随后显式保存为 pending suggestion 是两个独立动作。

当建议来自包含作者修订和助手回应的多轮对话时，结构化生成前先运行
`world.generation.conversation_decision_state`。该 step 不继续创作，只按时间顺序编译作者
当前目标、已确认要求、受支持发展、已否定内容、禁用专名、未决项、命名权限，以及可选的
“谁能知道／如何表达”边界。该边界只约束本轮提案，不写 CharacterKnowledge、术语表或世界
事实。后续生成只消费这个决策状态，不直接重放可能含作废方案的助手历史；检索 focus 也只
使用最新作者消息，
避免修正语句中的旧名称再次污染背景。禁用专名或未经允许的专名会触发确定性守卫并在同一
1800 秒总预算内重生成。候选还会经过一次窄语义审计，只检查是否违反作者已确认要求、复活
已否定内容、擅自解决未决项或越过知识表达边界，不因篇幅、字段完整度或审计模型的创意偏好
要求修改；连续违反
则不创建 suggestion。决策编译、候选和审计的实际 JSON schema 从首次请求即进入
`OUTPUT_CONTRACT`，避免只启用 provider `json_object` 后让模型猜字段、再付出完整修复调用。

结构化建议响应和待处理建议列表都以可选 `decision_state` 暴露这份摘要。页面建议把同一状态
保存在 typed payload，对象建议沿用既有 `_meta.author_decision_state`；恢复路径由服务端统一
投影，前端不推断 payload 形状。旧建议不调用模型回填。置信度仍保留给协议和确定性展示判断，
作者界面只在低置信或存在未决项时显示“请核对”，不显示分数。

作者是否要“修订此版”不是 Prompt 或模型判断。该动作由请求的可选
`revises_suggestion_id` 明确声明，并由确定性服务校验 parent、目标、页面 baseline、pending CAS 和
compatibility shadow 归档。“另起方案”不带 parent；已采用设定的修改走既有 revision 流程。
LLM 只在既定作者意图中生成内容，不能创建分支、复活旧版或选择应当采用哪一版。

三个结构化 step 分工如下：

- `world.generation.core_entity.structured` 忠实收束一个待处理世界对象建议，不进行第二次
  随机重设计。作者要求自由完成时允许模型运用创作判断；作者已有明确设计时，不为形式完整
  强加秘密、反转、关系、能力、代价或剧情用途。
- `world.generation.world_bible_page.structured` 综合完整当前工作稿、作者指令与项目背景，
  生成整页重构提案。当前页面是重要依据但不是唯一骨架；模型可重组标题、类别、概览和
  sections，不做末尾追加，也不降低既有 projection/sensitivity。作者已否定的
  助手方案不得在收束时复活。
- `world.generation.world_bible_new_page.structured` 生成完整新页面，并按资料自身选择合适的
  组织方式；不强制固定章节模板。页面模板只作为布局参考，不是创作内容清单。
  作者最新选择、否定和修正的优先级与现有页一致。

对象输出保留 `name / summary / public_info / hidden_truth / importance_level /
reveal_level / details / character_card`；页面输出为完整 `title / page_type / free_text /
sections / linked_asset_keys`。Prompt 不设置固定篇幅、必填创作维度或秘密/反转/冲突配额。
枚举、schema 校验、短资产 key 映射、稳定 section ID、模板版本、`novel_id` 隔离、上下文
快照和 suggestion-only 状态迁移由确定性代码负责。目标类型始终由作者选择，模型不能调用
工具、发布页面或写 canonical。多轮决策编译、最终生成和守卫重试共享 1800 秒端到端预算；
浏览器同步等待为 35 分钟，异步任务轮询不设总截止时间。

自由聊天、只读收束与三个结构化 step 共用 `generation_center` 上下文：显式选择与来源页引用优先，其后为当前 Scene、
剧情线、篇章/RAG 证据、相关人物和世界对象 Top-K、项目风格及可选世界观简介。人物自动
候选最多 6 个，非人物世界对象最多 16 个；没有章节、Scene、引用或检索证据时不默认注入
第一章剧情线。选中章节在总预算内优先取命中作者意图的窗口，无命中时保留头尾。
显式 Scene 必须属于当前项目且处于 `candidate/draft/canonical`；历史 `deprecated` Scene
在编译上下文和调用模型前拒绝，不能通过旧浏览器状态重新进入 Prompt。
当 Scene 与参考章节同时存在时，Scene 所在章是剧情线、篇章和 RAG 的有效剧情锚点；
选中章节只作为参考正文。Prompt 会告知模型背景可能经过选择、摘要和预算裁剪，
因此“未出现”不代表“不存在”。snapshot 另记录人物/对象实际纳入、未纳入 ID、
候选来源与 `top_k/not_loaded` 原因，预算裁剪后的 actual IDs 只包含模型真正看到的来源。

内置模板不规定对象必须拥有哪些字段，而是提供与类型相关的创作视角。
人物聚焦欲望、阻力、选择和行为逻辑；事件聚焦有因果的状态变化；物品聚焦
使用、持有与争夺；地点聚焦空间如何塑造行动与生活；组织聚焦集体决策与行动；
规则聚焦对世界运行和选择后果的稳定约束。外貌、秘密、反转、宿敌、代价、例外等
都只在对当前对象有帮助时发展，不为填满模板强行生成。

`不带模板` 不预设固定框架，允许对象暂时跨类别，并先收束为概念建议。
现有结构化输出仍确定性映射为 `concept`；这只是采用前的临时分类，不是对创作内容
的强制归类，作者可在采用前调整类型。模板不覆盖结构化 system scaffold，
不声明 JSON、数据库字段、状态或采用操作；这些边界继续由确定性代码与 schema 负责。

### RP 互动故事与回顾

interaction Prompt 由 `modules/interaction/prompts.py` 代码组装，不进入作者可编辑模板，
也不把模型固定称为 DM。它只消费用户开场、代码级选中路径和当前有效总回顾；未选 sibling、
失败残段、隐藏项目 ID 和作者资产不会进入普通故事上下文。

`interaction-story-v2` 直接输出可见故事。正文之后可以有一个带固定边界标记的可选 JSON
尾块，承载 `response_kind / suggested_title / branch_hint / story_ended /
action_suggestions`。framing parser 在流式过程中隔离尾块；尾块缺失、截断或 schema 无效时
只丢弃附加信息，不判废已经生成的正文。行动选项开启且当前情境适合时，模型尽量提供
1～3 个自然、具体、不剧透且有实质差异的建议；无法可靠提出时仍可返回 0 个，不自动补写、
修复或重试。模型只建议标题、发展提示和行动选项；
selection epoch、节点创建、分支选择、看海循环、停止、任务终态和 owner/novel 隔离全部由
代码决定。

普通模式保护用户角色的关键行动控制权；看海模式允许模型在保持人物性格、能力、关系和因果
一致的前提下自主推进。两者只切换少量静态 Prompt 规则。看海每一步仍由确定性工作流提交，
模型不能自行请求下一步、调用工具或跨模块写入。重新生成会加入有界的已拒绝发展作为
“不得当作历史、只避免机械重复”的参考。

`interaction-summary-v1` 一次返回：

- `segment_summary`：只概括本次新增的已选故事；
- `overview`：更新后的世界与起点、我的角色、当前局面、重要人物与势力、关键转折、
  正在发展的事情、必须继续记住七个自然语言分区。

重要性规则来自现有小说资产实践，但不读取或绑定 World 数据库实体：重点保留身份、能力、
物品、状态、关系、阵营、地点、关键选择、因果、承诺、代价、未决线索、明确纠正与长期偏好；
压缩重复描写和无后果细节。传闻、误解和局部认知必须保留不确定性，不得利用模型训练知识
提前补出用户尚未体验的幕后答案。已有手工总回顾是活动基线，旧原文不能越过它复活被删改
说法。

interaction 的故事与回顾 Prompt 都有显式版本；producer provenance 只记录脱敏
provider/model、Prompt/schema 版本、估算/完成 token 与调用次数，不记录 Key、完整
execution snapshot 或故事正文。

## 6. 通用约束的归属

项目不使用跨业务的全局共享 Prompt。每个真实 LLM 调用在静态 system scaffold 中声明
当前任务目的、数据边界、权限和输出契约；正文、作者输入与项目资料作为有边界的不可信
user/context 数据注入。模型不能执行数据库、文件或工具操作，输出必须通过当前调用的
Pydantic schema 和确定性业务校验。

对象去重、角色知识、秘密揭示、正史采用和 importance 等规则只放在拥有该领域语义的
Prompt、schema 或 materializer 中，不提升为所有创作任务的共同限制。Prompt 文件之间的
Markdown 链接不视为运行时装配；需要复用的静态 scaffold 必须由调用代码显式组合并测试。

Prompt 设计文档的职责是解释“为什么这样分工”，不是逐字复刻每个 Prompt 当前文件里的全部 JSON 字段。
