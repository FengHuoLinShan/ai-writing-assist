# Module: evolution / 演化系统模块

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎：
"读取正文 → 观察 → 身份解析 → 状态解释 → 校验 → 窄批次提交"的运行所有权。
当前已有持久化单 Scene 管线、冻结恢复、队列 handler 和正文/场景变更失效。
默认导入入口仍由 deep_import 编排；项目级旧/新 owner 门禁已落地并经原生 PG
验证。入口替代、观察期与真实质量验收仍未完成，旧编排尚未退役。

## 契约层（`contracts.py` / `observations.py`）

- `SourceRevisionRef`：不可变来源引用。range_hash 由 content_hash + 偏移确定性
  推导；章节序号只用于展示排序，来源身份由 draft/content_hash/revision 承担——
  同字数替换、复制、恢复旧稿都产生可识别变化。
- `ObservationEnvelope`：原文观察外壳。modality 区分观察到的事件、角色陈述、
  信念、假设、作者规划、比喻与非字面、不明确；逐字证据必须携带自己的来源范围；
  未解析提及保留 `MentionRef` 身份并记录原因，禁止为凑 schema 伪造实体 UUID。
- `IdentityResolution`：reuse / new_candidate / ambiguous / unrelated 四态；
  reuse 必须带候选证据，ambiguous 必须有两个以上候选。身份去重与观察积累分离
  ——命中已有身份不跳过新观察。
- `TypedStateOperation`：类型化状态操作。location.observe 与 location.move 分离
  （后者需移动证据）；knowledge.* 必须指明认知主体；`documentary_assertion`
  承载尚不能安全投影的观察且不改变核心状态；前值未知允许 before 为空（assert
  语义），不得伪造前值。
- `EvolutionReceipt` + `CommittedPrefix`：跨模块交接回执与已提交前缀游标。
  failed / blocked / unknown_billing 的回执 committed_prefix 必须等于前值且
  不得倒退——游标只在领域提交成功后推进；coverage 按 inspected / not_run /
  unknown / excluded / stale / unsupported 分列，局部完成不折叠成全量完成。
- 稳定观察身份（`derive_observation_id`）：来源范围 + 观察语义 + 契约版本的
  sha256，不含输出位置与 run id——批次重排/合并不重建身份（T06），另一 run
  同断言去重，契约版本提升产生新一代观察并保留旧身份可对照。

- 窄提交协调器（E03c，`commit.py`）：freeze → apply 两段协议。模型返回后
  先冻结负载；apply 短事务内重验 owner epoch、来源 manifest 与父回执，
  任一漂移抛 `CommitConflictError` 作废重准备；领域写入由注入 applier 完成，
  回执持久化后游标才推进；同 attempt 重入重放原回执不重复写入（T10/T11
  故障注入测试覆盖：持久化失败复用冻结不重采样、响应丢失重放原回执）。
  存储经 `AttemptStore` port 注入，由 `PostgresAttemptStore` 持久化。

- 持久化与编排（E04，`models.py` / `store.py` / `orchestrator.py`）：
  `evolution_runs`（owner epoch、已提交前缀游标、根预算）、
  `evolution_frozen_attempts`、`evolution_receipts` 三表与 Alembic 迁移
  `20260921_evolution_tables`；`PostgresAttemptStore` 绑定 `(db, novel_id)`
  作用域实现 AttemptStore 协议——回执落库同事务推进游标与 head（不可改写），
  `reserve_budget` 条件 UPDATE 原子预留（T21 不透支）。编排内核：
  `prepare_scene_input` 前序屏障（T07：Scene N+1 输入实际包含 Scene N 的
  已提交回执；前序未提交显式 blocked，不携带假结论）；前序状态内容为
  **结构化观察**（A04，2026-09-22 审查）：覆盖最近
  `PRIOR_OBSERVATION_WINDOW` 个已提交 Scene，保留 modality/主体/来源
  Scene——传闻在下一 Scene 输入里仍是传闻，窗口与截断在
  `previous_observations_coverage` 显式披露（未注入不等于不存在）；
  `plan_parallel_batches`
  确定性准入（同 Scene 依赖键不相交可并行；键冲突或叙事顺序强制分批，
  不采信模型自称可并行）。注册的 Scene handler 已接此路径；默认导入尚未切换，
  不允许把显式演化任务与旧导入同时用于同一项目的正式写入。

- 失效传播（E05，`invalidation.py`）：`compute_source_change` 物理差异
  （同字数替换也给出非空受影响窗口，T08）；`apply_source_invalidation`
  传播正文变更——证据索引换源重建（旧结果不再显示有效）+ Scene 派生投影
  软 supersede（保守扩大到受影响章锚定的最早 Scene 起，范围记入回执）；
  `apply_scene_reorder_invalidation` 处理场景重排（事件序号对齐 + 从最早
  移动 Scene 起失效）。Writing 的 working/published 保存、回退、删除及 Story
  场景更新/撤销/融合/拆分/重排均接相同边界；派生事件标 source_stale，演化 run
  推进 epoch 并记录待重算范围，不自动发起付费重算。作者确认与已提交回执保留。
  地图直接重读 Story 合法事件，不维护第二份事实；其余未接线消费者仍在回执
  显式列为 unsupported，不以局部完成冒充全量失效。

- 场景步管线（G2，`pipeline.py`）：`run_scene_step` 按 §4.1 顺序组合——
  前序屏障（T07）→ 预算原子预留（T21，先预留再采样）→ provider 采样
  （sampler 注入，事务外；生产接项目 LLM 入口）→ 稳定观察 → E02 身份
  解析 → 冻结（T10）→ 窄提交（E03c/E04）。来源绑定（A02，2026-09-22
  审查）携带草稿内码点区间：整稿指纹与 Scene 区间分别验证，服务端按
  权威草稿切片逐字比对 scene_text——同一章可分多 Scene；观察偏移映射
  回草稿绝对空间；跨章使用 additional_sources（最多 16 段），全量重验
  且不插入无来源分隔符。引用重复时须显式码点范围；虚构/越界/错位引用
  在编译阶段失败关闭，sampled 结果与计量保留。跨章引用拆成精确来源链，
  观察身份绑定所有区间。跨章 Scene 的原子事件在末章生效；Story 事件
  snapshot_after.meta 保留证据身份。已注册 evolution_scene_step_v2 handler，
  尚未重定向生产导入入口，deep_import 仍持有旧编排。
  生产 sampler 只对 Scene 中唯一的逐字引文校准码点偏移，保留模型原范围和宿主
  `exact-unique-scene/v1` 对齐回执；重叠重复、缺失引文仍严格拒绝，不修改旧冻结失败。
- 理解读取（`reading.py`，经 facade 导出 `read_committed_understanding`）：只消费
  live 成功回执的完整连续前缀，重验父回执、Scene 映射、全部递归正文根与同 Scene
  最新回执。保留原观察模态、逐字引用与稳定身份，不带入当前 World 的额外事实。
  默认最多读取八个 run、每 run 二百步、返回三条理解；超范围显式列为未覆盖。
  已冻结引用按原身份重验，无关后续提交不使它失效；重算同 Scene 不复活旧理解。
  Evidence 将该只读投影放入实际授权 InputManifest，Collaboration 留存其传递依赖。
- 建议有效性缝（G2，`consumers.py`）：`check_suggestion_validity` 按证据
  索引指纹判定（T17）——新来源已请求未重建、或声称指纹与当前索引不符
  即失效；来源一致才保持有效资格；无状态返回 unknown。失效回执已把
  assistant_suggestion_validity 列为可检查项；当前仍无 Assistant 生产调用方，
  不能把内核测试等同前端建议失效已接线。
- 在场投影（G2，story/continuity/presence.py，经 story facade
  `project_scene_presence` 导出）：从已提交事件推导 confirmed_in_scene /
  last_observed 与路线段——仅当后一事件自带移动来源证据才标 traveled，
  否则 unknown（T03：不造路程/方式/时间）。仅投影当前有效 Scene，保留已撤销场景
  的作者历史但不回流当前位置。World 的 MapSceneContext 生产接口消费该 DTO，按
  对象身份匹配地图位置并保留原文回读引用；不占地图几何或创建另一份事实源。

- 恢复与 fencing（E06，`recovery.py`）：`replay_committed_prefix`
  键集分页有界重放已提交回执链（链缺口 fail-closed、检查点信任锚跳过
  早期页）；`verify_run_checkpoint` 校验游标与 head 一致性并执行恢复期
  owner fence；`store.save_receipt` 以 epoch 条件更新完成 T12 完整
  fencing（旧 worker 回执在持久化边界被拒，游标不动）。性能测量工具
  `tools/evolution_checkpoint_bench.py` 与 1k/5k/10k 档位结果见
  `docs/plans/novelcraft-v4/e06/E06-恢复与性能测量.md`。

- 迁移切换（E07，`ownership.py` / `compat.py` / `tasks.py` / `legacy_adapter.py`）：
  影子运行 `execution_mode=shadow`（迁移 `20260921_evolution_shadow`）——
  执行模式盖章进冻结负载，首次执行与恢复经同一写入策略解析强制替换为
  隔离 applier（即使调用方传入会写正式表的 applier），提交边界
  `apply_frozen` 亦拒绝影子负载的正式领域写（2026-09-22 审查 A01），不
  产生第二套有效事实，影子回执留在 evolution 自己的表里供对比。
  `ownership.switch_project_engine` 先持 Project 独占锁，按 expected_epoch
  排空或明确停止 Imports 与 live Evolution run，撤销理解队列/lease，再推进
  项目 owner epoch 与 schema floor。入队、恢复、预算和提交均重验冻结 token；
  预算及历史不清零。迁移 `20260922_understanding_owner` 以 PG trigger 拒绝
  旧 SQL 写入；触发器的 Project share 锁用 NOWAIT，避免旧心跳锁序死锁。
  全部旧 v1 任务（含 shadow）拒绝续写，新任务协议为 `evolution_scene_step_v2`，
  防止旧二进制复用新任务 token。已有 live run 的项目迁为 read_only，旧队列项
  在建立 guard 前取消，避免最早 pending 卡住其他项目。schema floor 升至 2 后
  禁止切回 legacy/downgrade，可暂停并由兼容新版恢复。
  在途兼容分类保留费用，从可验证批次继续；v2 handler 走真实
  路径（生产采样经项目账户入口；请求可带
  章稿内码点区间，scene_id 与章号经 outline_state 权威校验——A02；恢复
  优先含**任意已提交 Scene** 的幂等重放，按稳定请求身份
  `compute_scene_manifest_hash`（run/scene/正文/整稿版本/区间）判定，
  同请求重试拿原回执不重采样不扣费，修订请求指纹不同不套用旧回执
  ——A08）；deep_import
  入口适配层返回真实新回执形状 + deprecation 提示（实际路由重定向待
  canary）。E08 退役登记表见
  `docs/plans/novelcraft-v4/e08/E08-退役登记表.md`（核销条件满足前不删码）。

- 生产采样器（E09 第一步，`llm_sampler.py`）：首次入队经 Project facade 冻结
  secret-free `llm_snapshot_json`，``ProjectLLMSampler`` 经
  ``open_project_snapshot_llm_client`` 读取原 provider/model 与当前轮换 Key；账户
  默认连接变化不改写同一 run。旧 run 没有快照时允许冻结回执重放，拒绝新付费步，
  不猜补历史连接。一次 Scene 预留至多一次请求，禁用内部修复和传输重试；输出为 Pydantic
  schema 化窄观察（modality 七态/提及禁造 UUID/引用必须来自原文，校验
  失败即失败；scene_events 状态提议须引用本批观察序号 `source_observation_indices`
  作证据，knowledge 提议须带 `knowledge_subject`——经 `state_gate.py`
  语义门验证，2026-09-22 审查 A03）；Prompt 确定性注入正文与前序已提交
  回执身份（T07 注入面）；每次调用记录 paid_call_receipt 进入冻结负载可
  审计（任一尝试用量未知则总量 None + `usage_complete`/`unknown_attempts`
  显式留痕；最终失败也固化 failed_final 回执——A06/A07）。生产 provider
  ``project_llm`` 已注册到采样器注册表；真实模型验收单独授权执行，
  单元验证用冻结 fixture 客户端（不联网）。
  状态主体可使用 `subject_surface`；宿主只在引用观察实际解析的身份中消歧。
  全部引用必须满足主体与模态要求，混合传闻不能升级完整知识。机器状态负载还须通过
  Story 的实际物化 schema 校验，知识主体/稳定记录身份由宿主填写；不合法提议留在
  pending。此结构门只防类型、身份和模态越权，不能代替语义蕴含与否定句质量验收。

## 受控逐场景理解入口

`/api/evolution/engine` 由项目 owner 显式启用或暂停；`/reading/preview` 只读预览，
`POST /reading` 按确认指纹启动，`GET /reading` 读取进度，
`/reading/{run_key}/resume` 恢复同一任务。编排位于 `workflow.py`，沿用
`evolution_scene_step_v2` 与原队列、预算和回执。当前入口接受 bootstrap/append，
复用完整连续 Scene 前缀；未整理的正文末尾先经 Imports facade 的纯规划、切分、精确
定位及提交准备边界，不创建旧导入 owner。不跳过中间未映射章节、不猜测歧义范围。

`reading_plan_json` 保存每步 draft/hash/offset、Scene 顺序、操作身份和分段授权；
确认时重读来源、模型与项目 epoch。网络未知重试返回原任务，新 append 或额度耗尽后的 continue 授权才加预算。
下一 Scene 仅在上一回执提交后入队；队列元数据再绑定来源版本，未采样章节修改也会
封锁旧计划。历史读取不发模型请求，同一 run 始终使用原模型快照。

领域提交异常或服务器中断后，handler 先回滚领域事务，再经 Worker 的独立租约检查点
持久化恢复资格；已冻结 sampled/compiled 或已提交回执免费重放。费用未知的 sampling/
failed 结果不直接重试。作者暂停/owner 撤销使租约失效，不能复活任务。
场景准备使用同一 v2 队列的 prepare_scenes 操作，逐次请求先预留、冻结再调用，
SDK/结构化隐式重试关闭。已冻结结果重放不扣费，预算不足停下，旧任务终态后才可追加
授权；历次 preparation 请求/响应/用量不因 append 丢失。模型数组顺序不能成为 Scene
顺序，宿主按精确正文位置排序并校验读取顺序。整章兜底、未闭合右边界、未解决左承接
及低于 0.90 的边界置信留为待审草稿，人工确认后恢复；可选语义缺项不阻塞读取。
前一章尾部仅用于边界判断，固定 draft/hash 并参加失效，不作为本 Scene 新事实来源。
结果保存遵循 Project → run 锁序，改稿与 provider 返回并发时仍保留已付费结果、禁止应用。
`revise` 已按正文/Scene 首个变化处重算后缀；`scoped_recompute` 接作者指定
Scene 起点，若前序变化则保守扩大。继承场景还须是当前最新成功结果；新 run 保存逐条
核实的原回执 run/attempt 身份、
游标和前序观察，旧冻结失败、历史与费用保留；旧任务未终结时不启动新 run。
对象/命题入口使用 `entity_id` 或 `observation_id`，与 Scene 起点互斥；目标来自本 run
已提交的冻结观察（包括继承的原回执）。`GET /reading/{run_key}/targets` 提供有界分页和
名称/观察文字检索，保持项目所有权与模态，未命中不证明不存在。预览以最早相关 Scene
及来源首变位置确定保守后缀，实际目标、起点和扩大说明一起进入确认指纹与分段授权。
这已覆盖目标选择与顺序后缀重算；细粒度依赖闭包和旧入口等价替代仍未完成。

## 测试

`modules/evolution/tests/`：契约校验语义（含游标纪律）与稳定身份性质。

## 2026-09-22 实施复核

同 run 重试保持 mode/execution_mode 不变，冲突在采样前拒绝。未提交冻结恢复
必须核对本次请求指纹和已冻结的 Scene 身份；队列去重绑定完整请求而非正文前
64 字。新单区间请求沿用原 manifest 公式，历史回执仍可读取和幂等返回。

E05 已接实际正文与场景变更入口；已提交观察经 Evidence 进入独立 case，C01/C02
的持久理解进入后一个新 case 和作者写作前瞻，地图经 Story 生产读取。生产 handler
纵切见 `evals/v4_vertical_slice.py` 与 `test_g2_consumers.py`；真实模型另用
`evals/v4_live.py`，共享费用账本并保留失败。E07 项目门禁、旧任务恢复封锁、迁移与队列
互不阻塞已有原生 PG 验证；完整 G2、G3 与 E08 尚未达标。确定性 API/浏览器及
影子规模结果不替代模型语义质量或真实用户验收。见
[实施审查与后续顺序](../plans/novelcraft-v4/IMPLEMENTATION-AUDIT-20260922.md)。

采样契约区分 predicate 的语义概括与 quote 的连续逐字证据：quote 不得补主语、还原代词或改动连词。模型违反时保留冻结失败，不能通过放宽原文匹配推进前缀。

独立状态复核（`state_review.py`）：通过引用/类型门的候选仍不可写入正式状态。
新运行使用单独的 `evolution.state_review` 调用，完整回读当前 Scene，逐项检查
否定、条件、时态、主体、角色认知及移动来源；仅 supported 且有原文逐字依据才放行。
漏项、重复序号、无依据、矛盾或无法确定均保留为待决定候选，不产生状态效果。
复核输入绑定 attempt、来源、parent receipt、epoch、前序输入及全部候选，提交时再次
验证绑定。采样与复核各预留一次根预算、禁自动重试、各自冻结费用回执；采样后额度
不足显示 needs_budget，追加授权后只执行尚未调用的复核。复核结果已保存时免费恢复，
请求已发出但结果不明或最终失败则待核对，禁止重发。旧计划/冻结没有复核版本时不
自动增加付费步骤，其未复核状态提议进入待决定，历史已提交回执不改写。独立调用
降低自我确认风险，工程测试不等于真实模型语义质量通过。


新阅读计划还冻结 World 候选版本，逐 Scene 运行 Phase2a、别名/关系和独立复核；
具体请求/schema、费用与原输出保留，候选写入与理解回执原子提交。旧对象新描述不自动
覆盖；无截止证明的后文别名不用于前文身份解析。World 采用入口在短事务内回读候选
所绑定的真实回执和最新来源，正文变更后拒绝直接采用。作者可从理解入口分页查看
候选及原文证据；这尚不等于 Phase3/高质量融合和完整旧链迁移完成。

World v2 在同场新身份经独立复核后冻结候选 UUID，状态复核在该绑定上进行；
World 候选、状态、关系物化快照和回执同事务提交。新身份未创建则不发布悬空状态，
同场同名竞争保持待决定。关系历史限定真实前缀回执（含继承），不从当前 World 描述
倒推历史，最多注入最近64个相关场景并明确范围。旧 v1/v0 运行保持原调用顺序。
