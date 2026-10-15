# Assistant — 项目助手（ADR-0023）

## 统一 AI 运行信封

`assistant_turn` 在 worker 领取时冻结 root capability、请求额度和 30 分钟 deadline；恢复与
重排累计同一 run。信封只写任务私有元数据，公共响应仍只返回既有结果投影。

Assistant 拥有跨页面讨论、Agent 执行、成组提案与提醒展示；不拥有世界事实、正文、结构、
RP 历史或领域复核。PydanticAI 仅通过 Project LLM gateway 执行注册工具，内部资料只经
Evidence 读取；业务写入需具体批次确认与来源重验。

专项能力子目录：

- `forecast/`：保存资料的短期前瞻——feed、显式 evaluate、候选 assessment 与 prepare
  子 run，行为细节见「保存资料的短期前瞻」；
- `teams/`：ADR-0027 有限协作蓝图的冻结方法文本与共享运行器，行为细节见
  「有限协作（ADR-0027）」。

## 会话迁移

`session_models.py` 接管原 World 共创会话和消息的唯一 ORM。物理表仍使用
`world_cocreation_sessions` / `world_cocreation_messages`，无需复制数据或重建身份；旧 World 类型与入口复用共享会话存储；World 保留世界模型上下文与持久共创任务。World source/checkpoint/outcome 判断由组合根注册的 World port 执行。
讨论不是 Canon；checkpoint 和候选内容仍引用原 World 载体。

## 执行记录

HTTP 入口为 `/api/assistant`；账户与项目身份由服务端验证。RP 提醒通过 Interaction 路由
接入，调用方只传 journey ID，不接受由浏览器指定隐藏项目或 owner。

- `assistant_runs`：owner/project/session、请求与冻结上下文、任务、预算、私有检查点和结果。
- `assistant_action_batches`：具体操作预览、基线指纹、确认、依赖与执行回执。
- `assistant_notices`：领域结果引用及已读/暂缓/忽略；不替代领域问题处置。
- `assistant_watches`：项目持续授权、待检变化、到期与合并进度。

公开响应不得返回运行私有检查点或供应商思考内容。RP 独立消息树/attempt 继续归 Interaction。

运行协议 v2 起冻结逐工具的参数签名与实现修订；v1 的目录保持独立快照。新增工具不自动进入
旧运行，修改签名/修订时必须保留兼容实现或明确拒绝。确认批次也重验操作签名，已完成回执
的重放不重新写入。人工正文可使用 `review_world_constraints`，原 AI 建议继续用原资料审稿。
实现与验收状态见项目持久任务记录；仅离线协议通过不等于原生联网或产品质量验收。

新作者运行使用 v7：运行快照冻结每项操作的完整参数 schema、版本与目录元数据（用途、
R0–R4 风险、可能计费类别、可撤销性、前置条件、产出、目标类型、事务形态及留痕规则）。
模型先用 `find_operations` 获取至多八项摘要，再用 `describe_operation` 读取单项完整说明；
R0 目录读取经 `read_operation` 进入领域读取端口。已下线或改版的冻结项仍可查看原说明，
但不能执行；其他未变化的项可以继续使用。v1–v6 运行仍按原两字段操作快照和
`available_operations` 恢复，原批次确认与显式重试规则不变。目录元数据是声明；物化后的
`prepare/apply` 回调通过 `ASSISTANT_OPERATION_TRACE` 记录提议、预览、确认、拒绝、执行、失败和
多阶段结果未知。HTTP 写路由须绑定目录 `operation_id` 或给出明确豁免，C3 提醒和对象档案路由
也经同一端口接入；静态 ratchet 禁止未绑定写路由增加。高频正文 autosave 豁免留痕，因为版本草稿
历史已经保存该编辑节奏，且明细不复制正文。

留痕只保存声明参数的类型、长度、分桶或按作品独立盐值生成的 HMAC；未声明字段只保存出现标记，
不存正文、prompt、模型输出或密钥。单事务写入把成功事件放在业务事务内，trace 自身用 savepoint
隔离；多阶段异常记为结果未知，不自动重放。留痕写入失败不阻断业务；响应发送前的 HTTP 留痕缺口用
`x-novelcraft-operation-trace-incomplete` 标记，v7 助手运行在 checkpoint 和结果中标记
`operation_trace_incomplete`，以便作者识别记录缺口。账户偏好由 `/operation-traces/preference`
管理：本机默认开启，公开账户默认关闭并需作者主动开启，演示账户永不记录。作者可通过
`/operation-traces/aggregate` 查看汇总，或 `/operation-traces/export` 导出去标识的操作与序列频次；
明细保留 180 天，到期后聚合并删除。
现有任务 worker 的维护节拍每次归档一个有过期明细的作品；即使作者不打开汇总页，闲置作品也会清理。

## 主动检查与提醒

正文保存与 Evidence 资产失效事件、RP 有效路径/回顾/来源变化在同一事务标记待检。
初始关闭；开启保存项目、owner、类别、排除范围、联网许可和每日额度。普通变化稳定 60 秒后
可领取，同一目标 10 分钟合并；每日默认 12 次且每项目仅一项后台分析。关闭/修改授权会让
旧任务在下一模型请求或最终结果提交前失败关闭。

World/Writing 复用原领域审稿任务；RP 使用 Interaction 的连续性任务。Assistant 只保存
任务引用和提示投影。来源变化时抑制旧通知，已读/忽略/暂缓不会把领域问题判为已解决；
相同问题的证据未变化时保持原展示决定。当前作者/RP 均有站内回访与提醒入口。
独立审稿所需原 confirmation 不可被新助手范围替换；无法证明排除范围一致时返回明确冲突。

## 统一作者提醒（ADR-0040 §13，C3a 后端切片）

`modules.assistant.notices_api.router` 声明 `/api/assistant/unified-notices`：GET 按章节或
Scene 聚合；POST `/dispositions` 处理已读、稍后（1–720 小时）和忽略；PUT/DELETE
`/category-mutes/{source_id}/{category}` 以行版本静默或恢复类别。路由先校验当前 owner 的
活跃项目；Scene scope 再经 `OUTLINE_SCENE_SERVICE` 按同一 novel 校验。写操作沿请求事务
flush，不在领域服务内 commit；处置与类别静默服务入口拒绝公开 demo 只读身份。

`app.notice_source_registry.notice_sources` 物化只读 provider spec。Assistant 聚合只调用此
registry；每个并行来源各自打开和关闭 AsyncSession，超时或异常显示“暂时无法读取”并令响应
`partial=true`，不会被当作空结果缓存。来源没有领域处置时，`assistant_notice_dispositions`
按项目、来源、稳定键和依据指纹独立 CAS；稍后到期回到未读，忽略只绑定原指纹。类别静默由
独立 `assistant_notice_category_mutes` 保存，不混入 `assistant_notices`。已有处置入口仍由来源
adapter 转发。
Writing 冲突项的领域 `later` 没有唤醒时间，统一入口的定时“稍后”使用上述展示处置记录；
到期后原 open 项重新出现，领域忽略仍走原条目状态。前瞻卡超过 10 条或单章待重算项超过
100 条时，已读取条目继续显示，并附“还有更多”导航提醒，不把整个来源报为不可用。

首批注册 `story.structure`、`writing.conflict`、`writing.invalidation`、
`assistant.proactive` 和 `assistant.forecast`。`story.structure` 迁移原前端结构缺项规则，
冲突检查读取已保存正文基线并包括 G8b 地图基线；短期前瞻仍走原 forecast CAS。Assistant
主动提醒适配器只投影现有 active AssistantNotice（含当前可见的 map_changes 与 editorial_issue），
不改变审读队列的作者裁定。Evolution 的 G8a 地图册来源核对、地图空间提醒、档案/状态、演化阅读、
对象一致性和世界推进提醒仍由各自后续来源接入；本切片不把它们伪装为已支持。

组合根必须注册 `ASSISTANT_NOTICE_SOURCES`，挂载上述 router，并把
`modules.assistant.notice_models` 的两张 ORM 表纳入 bootstrap/Alembic 元数据；来源/操作仍是
纯 spec。离线 provider 测试通过不代表共享 app 装配或提醒前端标签已上线。

## 成组执行与恢复

Writing 批注任务可通过 Assistant facade 创建一个独立、禁联网的项目会话，仅开放已有
World/Story 操作目录并生成相关资产的待确认提案。会话创建、prompt 组装与提交编排位于
`comment_proposals.py`，facade 只保留稳定签名并委托。正文修订候选和该批次各有任务回执；
助手未启用时返回明确的提案不可用结果，不改变正文候选的采用边界。

确认绑定方案指纹与用户选择；全组预检后逐业务原子组提交。失败组阻断其依赖，成功组保留
明确回执。`retry_operation_id` 只重试原确认中未完成项，同一重试回执不会重复写入。
会话保留作者决定。正文修订新建可恢复工作稿并保留来源、基线与批准人，不制造审稿通过结果。
旧共创消息和手工决定即使没有任务关联，也按当前章节、排除范围和原 confirmation 规则
参与讨论历史；当前任务的消息不重复注入。新额度续查及批次重新查证保留原联网选择与
渠道标记，缺少渠道标记的旧请求不自动获得 SearXNG 授权。
运行响应仅在原任务仍允许人工恢复且本轮预算未过期时返回 `can_resume=true`；任务缺失返回
404，预算或状态已不允许沿用时返回 409，并提示作者开始新一轮查证。

消息的 `assistant_run_id` 关联原运行，历史方案、失败/停止回合与成果可以重新打开；
旧 World 消息继续保留 outcome/checkpoint 引用。确认决定同时保存原 task 与 confirmation，
后续相同范围的讨论不会丢失决定。公开 sources 保留类型化领域引用和领域审稿的实际覆盖、
遗漏；已验证问题必须指向已有领域 finding，Assistant 不另立审稿结论。

部分成功批次只记录已完成操作真实目标的后置状态，原证据不被改写，无关资料仍按原基线重验。
原 confirmation 和复核 guard 不会因重试被替换；它们已失效时可通过
`POST /batches/{id}/recheck` 显式新建一轮剩余项查证，沿用原范围和排除项，不重做成功项，
新方案仍须确认。预览读取前同样检查排除、原确认和章节/Scene范围；无法证明整体预览覆盖时
失败关闭，不从最终采用确认倒推扩大读取授权。

主动服务在保存授权、领取旧待检项和执行时重验类别与排除目标。World 的原字符串 finding
位置由 World 按冻结 manifest 投影为来源/复核身份；提醒的新鲜度由 World/Writing 原读取
接口判断。RP 约定、回顾分区和固定来源有独立引用，只有可在本次物化资料中精确回读的
成对证据进入提醒。

## 领域提案与受控恢复

生成型工具通过 execute_suggestion 复用原领域任务，父关系与模型快照在创建子任务时保存；
工具准备/读取中的模型调用也纳入同一预算，不只统计最终生成。普通领域修改仍只进入确认批次。
结构提案沿用 P20，正文沿用原 generation / semantic review / targeted revision / candidate adoption。
公开 domain_result 是未采用提案或回执，不能代替领域审稿 finding 或已发生事实。

作者可以按精确 ID/hash 审阅 candidate。它不会进入 working/canonical 原文范围，也不自动获得
原确认、审稿或采用资格；采用与从历史继续写均重验当前 working 基线及编辑器未保存输入。
世界阶段成果从运行绑定会话，不接受模型指定会话或来源 manifest；旧决定默认继承，指针推进
加锁并核对旧值。保存成果、保存采用包与正式采用是不同操作。


## 自托管联网与维护补全

新运行 v5 保留 v4 的公开事实搜索、按本次引用读取网页和世界书历史工具、项目词表只读工具，
并新增只读 `map_spatial_brief`。它只返回当前授权范围内已采用地图的受限简报；地图 revision/hash
保存在私有运行检查点并于最终答复前重验，知识回执将其标为 `map_spatial` 参考维度。该工具需
`MAP_SPATIAL_ENABLED_CAPABILITIES` 含 `assistant.turn`，默认关闭。v1 使用独立快照，v2/v3/v4
按各自运行记录的工具与操作清单恢复，v5 新工具不会进入旧运行。
关闭时新运行不注册地图工具；已冻结的运行保留原目录，调用时仍重验开关。地图引用逐条作为独立
参考来源进入最终 `knowledge_scope_receipt`；普通回答仅记录实际读取范围，不代表已经通过独立知识审查。
v4 的 `project_vocabulary` 只读工具返回本作品有界词条身份、当前修订和特性，披露省略数；
只用于准备类型管理参数，不作为正文或世界事实证据。原确认、排除项或章节范围无法覆盖全书
词表时拒绝读取，领域修改仍需具体方案预览和作者确认。
`TurnCreate.web_backend=searxng-v1` 与 `allow_web` 同时启用才授权新渠道，历史浏览器偏好没有
backend 标记时不继承。首次自动创建讨论保留输入、参考范围与联网选择。能力接口分别返回
模型连接和私有搜索服务的状态、原因及受控入口；模型不可用时仍能读取讨论和已有回执。

World 负责世界书编辑/发布/恢复与历史读取；Story 负责信息计划编辑及版本影响；结果保留具体
任务、版本和成果引用。P20 原任务可跨设备打开专业预览，已采用回执只展示成果。内部历史
仍通过 Evidence；带原 confirmation、排除或截止限制时不得扩大为历史全量读取。

`POST /notices/{id}/recheck?novel_id=...` 以 operation_id 去重，重新检查当前授权的最新资料。
准备失败可由服务器的 change_key 恢复；不需要伪造旧任务。重新检查使用新的运行额度，旧预算
保持，活动任务不重复执行，仍受项目每日额度限制。RP 使用 journey-scoped 对应接口。

## 导入确认减负

`imports.resolve_review` 按明确章节/候选范围启动 Imports 智能整理，`imports.accept_review` 预览并采用作者选中的具体结果。v3 的 `review_resolution_result` 只经 Evidence 回读范围内的新鲜结果；固定 confirmation 或排除项无法证明一致时不开放整批结果。已获授权的后台整理不逐项回到助手确认，身份/事实冲突仍以领域操作批次处理。

## 最终答复复核

pro 模式将本轮实际工具证据冻结为 `assistant.turn` 组级 scope，先独立 audit；仅 blocked 时生成一份修正答复并复审。仍失败时只返回扣留说明且不准备 actions，回执进现有 run checkpoint/result。

## 有限协作（ADR-0027）

`POST /sessions/{id}/team-runs` 在同一助手任务内运行 `deep_review`，冻结蓝图、参数签名和
预算策略。三调查员使用独立 session、模型历史及相同授权的受限资料，自主调用只读工具；
原文引用必须精确回读。成果经 Writing 原语义审稿复核，主编保留争议和遗漏，最终答复继续
通过组级知识审查。`GET /runs/{id}/collaboration` 只返回阶段、覆盖和领域引用；
`POST /runs/{id}/collaboration/continue` 委托原恢复服务。来源变化显示旧报告失效。

`ASSISTANT_DEEP_REVIEW_ENABLED` 默认关闭；还需原 `ASSISTANT_ENABLED` 与可用模型。
首版 checkpoint 使用 `collaboration_v1`、上限 1 MiB，版本不兼容明确拒绝。team_v1 总额
30 请求/48 工具，每调查员最多 4 请求并保留 12 次最终复核额度；所有请求仍受同一任务信封。
成员完成回执先保存后发布；普通失败为 partial，权限/租约故障停止全组。取消保留回执。

同一团队入口还注册 world_stress、cross_revision、blind_reader、research、import_consult，各自
独立开关。只读蓝图禁止修改 plans；导入会诊只可为原疑难组当前候选准备 imports.accept_review。
跨章/World 方案选择后仍使用原批次和 fingerprint；确认后的复核另建同域任务，不把成功写入当质量通过。
盲读逐章冻结认知，研究必须本次明确联网；来源、未读范围与失败通过安全投影显示。

专项选择只授权本次提交；收到回执后恢复为普通讨论，不确定提交保留原 operation_id 与授权用于恢复。
坏响应与内容过滤仅使对应成员失败，账户限流/额度/认证错误仍中止整组。
关闭专项功能后不物化新方案、不启动修改后复核；旧方案回执及已物化批次保留，已执行修改不会因复核关闭而回滚。

## 审稿方法版本与离线对照

协作蓝图 v2 冻结连续性、人物知识、世界规则方法文本与 hash，成员加载冻结方法，
不增加工具权限。旧 v1 按原快照恢复。`deep_review` 的离线单调查员/顺序工作流/三成员
对照仅验证运行协议；原领域 finding 仍是已核实问题的唯一依据，默认质量开关保持关闭。

## 保存资料的短期前瞻

`forecast_v1` 子路由声明前缀 `/forecasts`，挂载后的完整入口是
`/api/assistant/forecasts`。feed 仅读取保存稿、领域回执和派生候选，不请求模型或创建任务。
显式 evaluate 用原 AssistantRun 和 `assistant_forecast`，最多四次请求（含复核与修复）。
语义任务、自动触发与 RP 各有默认关闭的开关。后台 forecast 与原 review 共享 active_run
和每日额度，分别保留自身稳定期与冷却期；原客户端保存设置不会覆盖新授权分区。

候选 assessment 不可变，读取先选择最新评估，再核对完整依赖和来源集合。正文、范围、
原 confirmation、排除项或主体变化会使旧结果失效。处置通过 notice.row_version CAS，
普通细节/拒绝方向不随标题变化重开。dirty 编辑器仅能查看上次保存稿。

前瞻将授权范围、证据快照、任务意图与界面焦点分为四个键；完整保存选区、光标段落和
排除项参与适用性校验。方向分别保存拒绝，旧候选不能覆盖已重新评估的 notice。
新请求显式冻结 `understanding_enabled`，旧任务恢复沿原消费协议；新旧卡片按各自
协议重验，不能给旧输入默默补入认知。作者写作前瞻可读取前章的持久理解与全部正文根，
生成及独立审查共享相同引用；同章/后章、Scene 焦点和历史截止不自动复用作者回顾理解。
理解容量不足整包省略并说明，始终优先保留当前任务资料。

prepare 为一个具体选择创建独立子 run 与唯一 batch，重新校验父评估，再经原领域确认。
确定性域回执可导航回原页面，缺少前置资料计入未检查。试改版本和跨域原子采用属于
[Collaboration](../../../docs/modules/21_collaboration.md)，不改变普通批次的部分成功与恢复语义。

## 引导流程（ADR-0032）

`guided_flow/` 子包是薄确定性编排层，不是新 Agent、不是 DSL：流程与步骤表在
服务端注册（`registry.py`，带版本号），模型与前端不可修改，运行期不开放任何可
编写的流程定义。注册时构建期校验：步骤只引用已注册 suggest 类操作或既有领域
任务、产物单一生产者、依赖只指向更早步骤（无环）；`require_flow` 在每次使用时
按当前操作目录重验引用，操作下线即失败关闭。

步骤类型仅三种：`auto`（只引用已注册 suggest 操作，复用 `operations.py` 的
uuid5 幂等执行与批次指纹；或既有领域任务如 `writing_semantic_review`）、
`author_confirm`（作者确认，复用既有资料确认协议与新鲜度重验，不新增确认
协议）、`author_choice`（作者真实选择）。停点只在：真实选择、扩大授权（资料
确认）、硬性阻断；不设“模型觉得该停”的停点。

进度由领域产物推导，不存当前步骤索引：确认的新鲜度读 Evidence 失效信号，
候选与审查回执读 Writing 任务的终态结果与候选 provenance（知识复核、独立
审查、采用回执）。运行记录（复用 `AssistantRun`，`request_json.protocol =
"guided_flow_v1"`，与 `forecast_v1` 同一判别模式，不建新表）只冻结流程版本、
输入指纹、授权范围（流程设置与确认引用）和停点原因；检查点为任务私有元数据，
公开响应只返回推导出的作者语言视图。已确认资料失效可由作者就地重新确认恢复，
不判硬失败；生成任务失败或流程定义版本漂移则失败关闭。同一流程同时只允许一个
活动 run：同输入重入回到同一停点（刷新/换设备恢复），不同输入冲突报错。

费用与幂等：流程提交的任务一律携带由（流程运行、步骤、输入指纹）确定的
`operation_id`，重复推进不产生第二个付费任务；每步预算沿用所引用操作自身预算
与 unknown 语义。流程开始本身不提交任务、不产生费用。流程设置（独立语义审查
开/关，默认开；滚动规划开/关与窗口章数，默认开、3 章）在生成开始前可修改并
重新冻结输入指纹，之后不可改。

依赖方向（ADR-0031）：guided_flow 只经操作目录或 facade 触达
Evidence/Writing/Project/Story；不新增模块依赖边，Assistant 仍禁止直接 import
World（骨架与采用经操作目录调用 `world.draft_opening_skeleton` /
`world.adopt_package`）。三个流程共用一张注册表与派发表（`flows.py`），按同一
机制追加推导、确认/选择输入与自动执行实现，不另起编排层。

HTTP 入口为 `/api/assistant/flows`（start/active/latest/view/advance/settings/abandon）；鉴权与项目隔离与 Assistant 其余入口一致，作者语言视图为唯一公开投影。开始请求按流程携带输入（`continue_writing` 需 `chapter_index`；`new_book_opening` 需 `input.vision` 与可选题材/篇幅意向；`editorial_revision` 无开始输入），推进请求除资料确认外支持 `choice`（作者选择停点的输入，由各流程在服务端校验）；视图的 `panel` 承载当前停点的作者面向载荷（方向卡、骨架包引用、修订条目、滚动窗口进度）。

已注册流程（`flows.py`，集成尾部 BR-3/4/5/6）：

- **`continue_writing` v3（流程 2）**：首页「引导续写第 N 章」→ 定位工作稿 →
  写作页就地核对/修改本章目标并完成资料确认（已有弹窗）→ 生成候选 → 自动接
  独立语义审查 → 停在「可审阅」，作者采用或定向返修。采用后停在「规划接下来
  几章」（BR-6 滚动规划）：作者确认后对第 N+1 至 N+K 章（K 为流程设置，默认
  3、上限 5）逐层规划剧情线、篇章与近期 Scene（最近最多两章）。每层另行确认
  完整结构资料，再生成候选；作者采用或明确略过后，才确认并生成下一层。
  原正文确认的排除项冻结保留，有排除时不得自动扩权；旧 v2 运行失败关闭，作者
  可结束后重开。所有非空层已采用且窗口有规划覆盖时完成，也可主动结束。
  回执身份绑定完整参数、来源与当前运行步骤；重复推进重用，来源或意图变化不
  复用旧任务。后方不足两章提示补窗；关闭滚动规划后采用正文即完成。
- **`new_book_opening` v1（流程 1）**：一句构想（+可选题材/篇幅意向）→
  方向卡 LLM step（`direction_cards.py`，一次结构化调用出 2-3 张候选，卡片只
  存任务与运行检查点不是资产；每流程至多 3 批，再要一批是新调用并提示费用）→ 作者
  选定并可修改字段 → `world.draft_opening_skeleton` 一次生成待审骨架包 →
  停点「骨架待确认」：作者在卡内逐条取舍并保存（排除/改名/简介、关系与规则正文、依赖与冲突原因）
  后流程经 `world.adopt_package` 采用所选条目（作者确认触发，prepare/apply
  复验、采用绑定当次预览指纹）→ 终点为「骨架可用」：生成故事总纲建议 / 继续深化世界观 / 开始写
  第一章（走流程 2），不自动写首章。知识审查未通过的包失败关闭，可查看不可
  采用；方向卡与未采用的骨架不进入任何生成上下文或检索。
- **`editorial_revision` v1（流程 3）**：审读台选中意见并填写处置（作者选择）
  → 桥接批注修订（复用 `editorial/issues/revise`，见下节；引文失效/hash 漂移
  沿用其失败关闭语义）→ 停点「候选可审阅」，作者在写作页采用 → 全部就绪后
  自动按（意见、采用稿）请求改后复核 → 停点展示「仍在 / 可能改善 / 无法判断」
  结论后完成。不做多意见自动融合。

方向卡通过 `assistant_direction_cards` durable task 使用 secret-free 项目执行快照与当前
账户 Key；生成结果通过租约保护的任务私有检查点保存，工作进程中断恢复复用已有
结果，不重付已完成调用。每批最多生成与格式修复两次请求，最长 360 秒；来源
或检查点指纹不一致失败关闭。生成前先落已发起标记；响应后结果未安全落盘
时停止自动恢复，费用待核对，不再次调用模型。流程开始并发用项目/流程 advisory transaction lock
序列化；SQL 在截断前筛项目、owner、协议与流程。开关与项目白名单保持默认关闭。

首页通过 latest 查询恢复已完成骨架采用，刷新或项目已有内容后仍能撤销；已编辑
或被引用资产按领域回执保留。取舍保存 CAS 冲突保留编辑，重读前本地备份可恢复；
备份失败保留当前编辑并阻止无保护离页。审读台重新挂载读取活动流程恢复停点。
方向卡能力归属为 `assistant.guided_flow.direction_cards`，只声明对齐作者构想 `author_intent`，输出不构成世界事实或知识审查通过回执。审读修订的改后复核任务仍在途时保持流程进行中；终态回执才进入复核结果停点。

## 工作上下文的意图与选区范围（R00）

`WorkContext` 在既有定位字段之外携带两项经服务端复核的输入：

- `task_hint`：作者意图封闭集（`schemas.TASK_HINTS`，与 forecast 契约同源）。
  面板「这次要求」选择器经 turn/前瞻上下文传入；`work_directive` 把意图
  行为边界渲染进最终 user 消息（polish=不得扩大情节、新增设定或改动事实）。
  forecast runtime 对 polish 另有既有能力收窄（剔除扩情节项）。
- `selection_start/selection_end`：写作页选区的码点偏移（与前端
  `Array.from` 计数一致），必须成对、绑定草稿且与选区文本长度一致；
  `submit` 载草稿后 `verify_selection_range` 逐字复核，漂移抛
  `assistant_selection_stale`（失败关闭，不带失真选区进模型）。

## 本机 CLI（不再用于助手）

按 [ADR-0029](../../../docs/adr/0029-local-cli-image-only.md)，本机 CLI 只用于图片生成。
`assistant_turn`、语义前瞻和创作协作一律冻结项目账户连接，不读取项目的本机执行器；
能力接口不再因本机执行器而报告模型可用。此前冻结为本机执行的助手运行在执行时以
`assistant_runtime_changed` 失败关闭，不改走账户连接；运行投影仍可显示其旧授权状态。

## 作者编辑台

`/api/assistant/editorial/*` 仅服务当前 owner 的作者项目。Project 持有作者确认的版本化
编辑约定；Writing 持有工作稿与“交给编辑看”哈希；Assistant 持有 review、issue、作者处置和
定向复核。`assistant_editorial_reviews` 冻结工作稿 ID/hash、约定版本、排除范围和不含密钥的
Project 模型快照；worker 按 12000 字符片段顺序近读，卷/全书再按最多八节点逐层汇总。
每段前及报告发布前重验来源，缺章、排除或预算上限保留部分覆盖，续跑不重算已保存段。
作者可用 `/editorial/reviews/{id}/stop` 停止排队或运行中的审读；已完成分段保留，
来源与授权未变且用量已知时可从 `/resume` 续查。
worker 的每个异常出口都落到终态：仍由本任务持有且处于排队/运行时，工作稿、世界/结构资料
或编辑约定变化记为 `stale`，其余记为 `failed`；已被新任务接手的审读不改写。进程崩溃或租约
过期不会进入异常出口，读取审读时按任务生命周期把这类排队/运行行收敛为 `failed` 或
`cancelled`，以便续跑。前端在显式保存编辑约定、世界设定、大纲或发布正在审读的章节前提示
会让审读失效并请作者确认；自动保存不拦截，只在写作页提示本章审读中。

失败终态的 `error` 是作者语言（分段保留、可继续重试），内部诊断脱敏后收进 `view` 的
`error_detail` 次级字段，由前端折叠展示；领域冲突文案本身是作者语言，直接沿用。
`ReviewPass.summary` 必填非空：LLM 客户端把截断输出补全成空对象时，空对象不合法，
坏输出按失败处理，不会静默降级为“零意见完成”（客户端全局截断恢复策略不变）。
每段的读者层结论在编辑层调用前先落盘（`pending_editorial` 检查点）：同一段的编辑层
调用期间被停止或中断，续跑只补编辑层，不重复调用读者层。

读者层仅接收已读正文片段与先前读者状态；作者层可读取 Evidence 精确回读的世界资料和 Story
当前范围的结构资料，保留引用清单和遗漏。模型 finding 必须有当前冻结正文中的唯一准确引文；
世界/结构引用也需精确回读。服务端将其标为 `editorial_suggestion`，绝不写 Writing 的
`independent_review`、正文、Story 或 World。作者处置保留版本与历史；改后复核只给仍在、
可能改善或无法判断，作者确认关闭。旧来源和约定变化标明失效。
意见卡的处理方向逐项列出涉及章节与代价；报告优先展示最多三项根因，后台提醒也只取这些
根因中来源仍有效、严重度高且无未核对事项的意见。优先级先看未核对范围、跨章覆盖和可回读
依据，再以模型给的严重度排序；作者意图关联必须精确命中已冻结约定，不能由模型自报充当证据。

### 意见转批注修订桥接（BR-4 流程 3）

作者在编辑台选中一条或多条意见并填写处置说明后，`POST /editorial/issues/revise`
经 Writing facade 的 `submit_comment_revision` 把每条意见的首条原文依据定位为选区，
连同意见文本与处置一起交给既有批注修订：仍只返回选区替换、走治理复审与候选采用
门禁。意见保持 `editorial_suggestion`，不转换成语义审查 finding，也不写独立复核。
引文无法唯一定位的意见逐条跳过并说明，不影响其余意见；审读冻结的正文 hash 与当前
工作稿不一致时整体失败关闭，提示重新审读。同一请求标识幂等：重放返回既有任务，
不重复创建批注或处置（处置历史带 `bridge_operation_id` 识别本请求此前写入）。
成功进入修订的意见记录一条「准备处理」处置并附处置说明。桥接候选 provenance 记录
`editorial_issue_ids`，作者采用候选后经组合根 DI 键按既有机制为每条相关意见请求
改后复核；复核无法成立（依据失效、上一轮用量未确认等）逐条跳过并说明，不阻塞采用。
修订选区只取首条原文依据；跨章意见的其余依据不进入本批次。不做多意见自动融合。
候选采用门禁不变：回执与引导停点都如实提示作者到写作页先完成独立审稿，通过后才能
采用；直接采用会被服务端 409 拒绝（「批注修订候选尚未通过独立审稿」）。
“部分采用”只有三类既有语义：助手确认批次中作者勾选的具体操作、编辑台对多条意见的
子集处置（含本桥接）、新书骨架包的逐条取舍（引导流程 1）；正文候选只能整体采用，
不存在逐段正文采用，本桥接不新增第四类。
本桥接已有引导流程挂接：`editorial_revision` v1（见「引导流程」）从审读台选中
意见开始，经同一桥接生成候选，并在采用后自动触发这里的改后复核。

手动审稿由 `ASSISTANT_ENABLED` 与默认关闭的 `ASSISTANT_EDITORIAL_ENABLED` 控制；后台还需
默认关闭的 `ASSISTANT_EDITORIAL_AUTOMATIC_ENABLED` 与单项目 `editorial_v1` 明确授权。
主动编辑设置保存使用 Watch `generation` 冲突校验，双标签页的旧设置不能静默覆盖新授权。
Watch 复用稳定期、每日额度和项目后台执行槽，仅在完成标记或未关闭问题相关结构变化排队；
旧结论失效、授权撤销或模型用量未知时失败关闭。只有已完成且来源仍新的高严重度问题进入
AssistantNotice，其余意见留在编辑台。联网不用于小说内审读。
原创内容评测样本、固定量表和零费用预检见
`backend/evals/datasets/editorial/README.md`；工程绿灯不代表真实模型内容质量通过。

本机文字根任务的逐次批准链已随本机文字审批路径退役删除，Assistant 不再提供
`mark_task_local_approved` 入口；仅图片任务保留本机审批，由 `local_agent` 模块
自身的 owner + novel_id 门禁端点处理。历史运行回执仍可经
`/api/local-agent/tasks/{task_id}/receipts` 只读查询，确认授权范围和任务租约契约保持不变。

编辑台的约定通过章节名称选择本轮不审范围，保存仍使用原版本化 excluded_targets
合同；历史非章节排除项和已选但不在当前列表的章节不会被清空。章节列表失败可以重试，
不阻断编辑约定读取或丢失未保存选择。

ADR-0033：助手模型就绪判定接受项目快照中的已验证 Codex 连接，不以是否保存 API Key 代替可用性；工具循环仍走同一有界网关，模板重建保持未设置字段，以继承 Luna/max 而不固化历史默认模型。
