# Module: imports / 小说文件导入模块

## 定位

imports 模块负责小说文件的导入与解析。它不是一个独立的创作模块，而是将外部小说文件转换为系统内部章节正文的通道。
同时，imports 负责深度导入的工作流编排：把已导入章节交给 Scene 切分、实体抽取和结构分析三个阶段执行。

当前 ORM 表为：

- `import_records`：导入文件元数据；
- `imported_chapters`：仍被来源 FK 使用的章节正文记录，上传主路径不把它作为第二编辑入口；
- `import_workflow_runs`：项目级 workflow owner/generation、授权快照和可恢复 checkpoint。

## 负责

- 上传并解析 txt / epub / html 格式的小说文件；mobi / azw3 保留上传白名单与
  内容校验，但当前锁定依赖未声明其解析器包，不能视为已验证可用格式
- 自动检测文本编码
- 按章节模式（第X章、Chapter X、卷X 等）自动分章
- 将解析结果写入 writing_drafts（每章一个已发布正文版本），上传响应返回已保存章节摘要
- 记录导入历史
- 提交并编排深度导入任务（`async_tasks` 负责调度/lease，
  `import_workflow_runs` 负责领域恢复事实）
- 提交并编排分阶段自动提取任务：Scene、世界对象与别名/关系、剧情结构；作者默认先从
  Scene 骨架开始，但该推荐不自动提交任务，完整导入始终保留为显式选择
- 完整和分阶段提交在 project exclusive 短事务锁内检查同项目 run；
  `import_workflow_runs` 另以 partial unique index 保证同项目最多一个
  `pending/running` 或 recovery-required run。已有 owner 时返回原
  `task_id/workflow_type`，不重复入队；该锁不跨 provider I/O
- 在重复导入时返回覆盖确认要求，确认后才入队；确认只冻结
  `replace_existing` 意图，不在任务执行前修改 Scene 或实体
- 深度导入 Scene 阶段执行 `Phase0 deterministic plan → Phase1a scene slicing → Phase1b scene enrichment → Phase1c scene fusion → Scene commit`；Phase 1c 仅在 `high_quality=true` 时运行
- Phase 0 不调用 LLM；它按章节字符数计算窗口计划、owned range、固定右侧 2 章 overlap 和每窗 `max_tokens` 上限。默认目标输入约 `72000` 字符，窗口最多 20 章。DeepSeek v4 Flash 实测 `0.36`、`0.4`、`0.6` 都出现过截断；`0.75` 一次四窗首轮通过，但同一 1–60 章末窗的复跑仍在 `19898/19898` 处 `finish_reason=length`，因此不将偶然通过视为稳定。`max_tokens` 只是上限而不会强制模型用完，默认系数提升为 `1.0`，即 `max_tokens=clamp(round(input_chars * 1.0), 13000, 32768)`。这套阶段预算不继承项目通用 `max_tokens`；Phase 1b/2/3 从首次请求就使用各自冻结的 32768 上限，不实验更小预算。
- Phase 1a 切分并锁定 Scene 语义字段，同时要求从正文逐字复制起止 anchor；本地 materializer 负责唯一命中、offset、draft/hash 绑定和邻接/整章覆盖推断。Scene 按独立主要叙事目标、冲突或关键状态转变切分，不使用字数或每章数量阈值。每个窗口还会冻结前一章最多 2000 字尾部，以及通过 outline/world facade 取得的活跃剧情结构与 `author_safe` canonical 世界对象；相关人物最多 6 个、非人物对象最多 16 个，按正文提及、已有 Scene 关联、篇章/剧情线关联排序。锚点修复与连续覆盖缺口恢复同样使用统一 reasoning 策略。精确 span 重叠会先携带本地诊断要求模型纠正；若纠正后仍重叠，则隔离整个受影响章节范围并进入恢复或章节级 fallback，不允许重叠候选进入后续阶段。
- Phase 1b 每个 Scene 一个并发 enrichment 请求，不得改写 Phase 1a 已确定的语义和 `scene_chunks`。调用前按全部 chunks 校验 draft/hash/offset 并物化完整 Scene 正文，不发送混有相邻 Scene 的整章正文，也不做应用层输入截断、摘要或采样；同时合并冻结 Phase 1a 窗口中的相邻 Scene、活跃结构、人物 Top-6 和非人物对象 Top-16。模型可明确返回不适用的空 `emotional_beat` / `must_happen` / `must_not_happen`，本地按 `uncertain_fields` 与来源状态计算复核，不生成占位语义。输出 `max_tokens` 默认 32768，并从冻结的 effective `deep_import.phase1b.enrich_max_tokens` 传入 payload。
- Phase 1c 先按 Phase 1a 窗口成组审阅完整相邻候选序列，区分 `same_scene / duplicate / overlap / separate / uncertain`，再只对高置信、无不确定性且来源精确的连通组调用独立 synthesis。最终 Scene 语义由 synthesis 重新综合，不拼接成员字段；真实不适用的字段保持空值。其余结果写入 outline 融合建议队列；高置信 `separate` 以隐藏的 `dismissed` 决策保存，不增加作者待办，但会阻止智能去重重复询问。来源变化后才恢复全局扫描资格。旧独立跨章检测链已删除。
- Phase 1c 未显式配置 `decision_max_tokens / synthesis_max_tokens` 时继承有效项目/全局/系统 LLM `max_tokens`，并在任务提交时冻结；结构化调用默认超时为 360 秒。
- Phase 2a 的逐 Scene LLM 默认并发为 25，provider/LLM 超时为 240/270 秒。运行时降载只把 429、连接失败与超时视为 provider 压力信号：单波出现任一 429，或至少两个传输/超时失败时并发减半；schema、partial-list 等格式诊断只进入质量统计和 Prompt 修复，不触发降载。历史真实验收表明 64 并发会放大后半段尾延迟与批量超时，因此不恢复到 64。
- Phase 2a 的阶段内自动修复使用首轮失败 Scene 的稳定 ID 作为显式白名单，并显式关闭 Phase 2b；首轮持久化导致 working 世界上下文指纹变化时，不得把已完成 Scene 扩大为修复重跑范围，也不得因一个 P13 失败重放已完成的别名/关系阶段。修复结果按 Scene ID 覆盖失败 checkpoint，并保留其他已完成或来源不完整的 checkpoint。
- 深度导入保持自动流水线，不对每个 LLM step 重复弹出“AI 参考资料”确认；但首次提交必须显式传 `authorization_confirmed=true`，一次授权 `user_authorized_pipeline` 采用策略。Phase 3 结构分析显式使用 `context_mode="working"` 并包含待确认对象
- 分阶段世界对象自动提取执行 `Phase 2a 对象抽取 → phase2_dedup 自动去重 → Phase 2b 别名/关系`。去重只扫描本 workflow 新建、未编辑且仍为 candidate 的对象；既有资产仅保留名称/已确认别名的确定性复用，语义重复仍由项目级“智能去重”处理
- Phase 2a 对已持久化 Scene 以 Scene 为并发单元；每个请求消费当前 Scene 的版本绑定完整精确 span、锁定 Scene 卡、相关 active working 大纲、身份候选和前序证据，写入仍按 `scene_index` 串行归并
- Phase 2a 已收敛为 `ImportContextActivation v2 -> concurrent LLM -> deterministic materializer -> scene_index ordered persistence`。当前 Scene 在可见截止章/offset 以前的完整精确正文是唯一新事实证据；Top-6 人物 / Top-16 非人物对象只控制相关资产范围，不裁剪模型输入。provider 上下文超限按 Scene 显式失败，不静默缩短正文。Phase 2a/2b 的 DeepSeek 请求普通模式使用 `high` reasoning，高质量模式使用 `max`；Phase 2b 单调用默认超时 120 秒，高质量模式有效超时翻倍。
- Phase 2a/2b checkpoint 使用确定性 `input_fingerprint`；Phase 2a v2 额外纳入 context fingerprint 和 Prompt contract version，覆盖 Scene 语义、`scene_chunks` 的 draft/hash/offset 来源、实际消费正文、Scene 卡、相关大纲、身份候选和前序证据。只有 `done` / `skipped` checkpoint 的指纹与当前输入一致时才允许跳过；旧 checkpoint、缺失指纹、Prompt 升级或输入漂移均按 fail-safe 重新执行。Scene 正文选择优先使用 end-exclusive `start_offset:end_offset`；任一可见 SceneSpan 不精确或覆盖不完整时整 Scene 跳过，不会静默发送部分正文。
- Phase 2a 只输出长期世界对象、持久 Delta 和不确定项；关系与新别名完全由 Phase 2b 负责。Phase 2a 不接收后续 Scene 或右侧边界补充证据，模型不决定持久化动作、审核状态或 `needs_review`；服务端只接受已知 `entity-xxx` 身份引用和当前 Scene 中可逐字定位的证据
- Phase 2b 复用同一份完整精确 Scene activation，加入相关既有关系的 `relation-xxx` 引用；不使用旧 Scene/对象索引字符上限裁剪输入。v4 继续把输出视为当前 Scene 带来的关系增量，而非仍成立关系的摘要；并为别名增加 `name / title / identity` 三类最小主类，为关系增加 `state / social / spatial / causal / temporal / epistemic / intentional` 七类最小主类，同时保留自定义的精确 `alias_type / relation_type`。模型同时区分 established / reaffirmed / changed / ended 与 `enduring / stateful / episodic / uncertain`，只有 Scene 结束后仍成立的持久联系或持续状态可以进入候选；一次性动作和证据不足判断只保留诊断。具体关系类型优先复用既有类型，但不以固定数量限制真实关系。服务端重验对象、关系、逐字证据、持续性和快照来源，只写候选或补证据，不自动融合对象、覆盖或废弃已采用关系。
- Phase 2a 的 `ExtractedEntity` 与窗口级 `Phase2WorldObject` 在进入 world 的作者宽松 `CoreEntityCreate` 前仍执行固定系统 `entity_type` 校验；深度导入不会创建或复用项目自定义类型
- Phase 2 入库前通过 world facade 使用名称 / 别名 / embedding 去重能力；任何非 `ignore` 观察只要与同项目、同类型 working 对象规范名完全一致，就确定性复用 canonical/draft/candidate，不受模型返回 `create_new` 或 `link_to_existing` 影响，避免重跑制造影子候选。非同名别名建议仍必须解析为已采用对象 ID；未解析时只保留名称提示，不把歧义建议自动融合。重复关系走 create-or-merge，并在 progress/result 中记录 action、dedup、boundary supplement 和 degraded 统计
- `phase2_dedup` 复用 world 的结构化融合 step、语义/执行指纹与 candidate 软合并。`merge` / `alias_only` 置信度达到 `0.80` 且连通组无矛盾才自动应用；主对象按最早章节、最早 Scene、稳定 ID 选择。每组独立 savepoint 并在应用前重验 `novel_id` / workflow / candidate / `user_edited` / 指纹与当前任务 owner；冲突、输入漂移、低置信或 provider/格式失败只降级并保留原候选，随后继续 Phase 2b。checkpoint 纳入候选 ID、语义/执行指纹、策略版本和固定门槛；未漂移的已完成裁决不重复调用 LLM
- Phase 2b 在写入 world 候选别名前会拒绝模型字段占位词（当前包括 `变量`、
  `variable`、`placeholder`）；这类输出不进入待处理别名，也不参与实体别名去重。
- Phase 3 只基于已提交 Scene 证据生成结构化结论，每条结果必须引用输入 Scene；没有 Scene
  证据时返回空结果和复核诊断，不调用 provider，也不回退到 P20 创作 Prompt。完成后会通过
  outline facade 生成结构去重建议；只自动应用同一 deep import workflow 内的高置信重复，
  跨已有资产的建议仅写入任务结果
- Phase 3 结构化请求同样使用冻结的 `deep_import.phase3.structure_max_tokens`（默认 32768），不再按 prompt 长度进行 token 阶梯扩容；该字段会出现在项目设置与任务冻结快照中。格式/transport 故障可保留一次同预算修复/重试，业务质量 replacement rerun 继续是独立门禁，两者都不扩大 `max_tokens`。
- 深度导入 Phase 2 拆为 Phase 2a 世界对象/Delta 抽取与 Phase 2b 别名/关系提取；Phase 2b 失败只降级，不丢弃已抽取对象
- 深度导入 Phase 2/Phase 3 的真实 LLM 调用通过 `modules.evidence.facade` 写入 `context_snapshots` 审计记录
- Phase 2a/2b 的活跃 LLM adapter 只消费 workflow 持久化的 effective project
  profile snapshot；缺少 snapshot 时 fail closed，不回退环境 Key，并在每次调用后关闭 client
- Phase 1/2/3 的 snapshot client 统一由 project runtime seam 构造；主 workflow
  与 Phase 2 并发 adapter 都传递当前 `novel_id` 供 managed-step journal 聚合；
  structured call 在成功和异常路径均通过 `finally` 关闭 client
- 非 task 的内部兼容调用也会临时构建 secret-free execution snapshot，再经 project
  runtime 恢复当前 Key；不再从通用 `ProjectContext.settings` 取得运行时凭据
- Phase 2a/2b context snapshot 使用与活跃 adapter 相同的 profile resolver，
  记录脱敏 model/provider/base-url host/字段来源，不保存 API Key 或 URL query
- 深度导入 Phase 1/2/3 prompt、Pydantic schema、关键字段映射和目标表列通过 `make prompt-contracts` 做开发期漂移检查；该检查不调用真实 LLM、不访问数据库

## 不负责

- 直接实现世界对象、记忆或大纲的业务规则
- 绕过各模块 facade 直接写跨模块内部模型
- 直接 import context 模块内部的 models / repositories / services
- 文本改写或格式转换导出

## 数据表

- import_records：导入操作记录（元信息，不存正文）
- import_workflow_runs：授权/LLM 快照、prepare/checkpoint、权威进度及
  `task_id + generation + owner attempt/lease` 所有权
- async_tasks：队列调度、lease 与任务 API 兼容投影；progress/result 继续供前端轮询

`context_snapshots` 由 context 模块拥有。imports 只通过 facade 创建、标记成功/失败和回写 result refs，不直接访问 context 内部表或 repository。

## 跨模块依赖

- writing.facade.create_draft — 写入解析后的章节正文
- outline facade / DI handler — 深度导入 Phase 1/3
- world facade / DI handler — 深度导入 Phase 2a 对象抽取、Phase 2b 别名/关系提取
- context.facade — Phase 2/3 LLM 调用上下文快照审计
- memory.facade.capture_snapshot — Phase 2 后记录记忆快照

Phase 2 的存量对象去重通过 `world.facade.get_world_context(..., include_review=True)` 显式读取 active + review 对象，避免同 workflow 的待处理对象被重复创建。imports 不直接 import world/outline/context 的 model、repository 或 service。

## 流水线授权与资产结果

`POST /api/imports/deep` 和三个 stage 入口的请求都携带：

- `adoption_policy="user_authorized_pipeline"`（当前唯一受支持策略）；
- `authorization_confirmed=true`（必填且必须为 true）。

facade/orchestrator 默认不授权；缺少显式 `authorization_confirmed=True` 会在入队前拒绝。新任务把带 `authorized_at`、novel/章节/stage scope、`provenance_required`、以及 `rollback.mode=workflow_owned_soft_deprecate` 的 `authorization_snapshot` 写入 `import_workflow_runs`，并投影到 `async_tasks.meta/result` 保持现有 wire。worker 进度和最终结果继续保留该快照；恢复同样 fail closed：快照缺失、未确认、策略不受支持或 scope 与 run 范围不一致时，直接拒绝执行。

新提交的 `deep_import` 和三个 stage task 还会在入队前生成
secret-free `llm_execution_snapshot`，同时写入 task meta 和初始 result。
worker 恢复时冻结使用提交时的 model、生成参数、字段来源和
deep-import 设置（含提交时已物化的 env/default）；当前 API Key
可轮换，但 endpoint/extra hash 漂移会
fail closed。旧的本地任务若没有此字段，兼容路径在首次新 worker
执行时补抓快照；新生产提交不使用该兼容分支。

完成结果增加 `asset_summary={adopted, review, not_adopted, by_kind}`。`by_kind` 固定包含 `scene/entity/relation/alias/structure`，缺失 phase 统计显式记 0。Scene 的 `needs_review` fallback、world candidate/关系/别名、不确定结构和跨旧资产去重建议进入 review。结构去重保留旧的 suggestion-pair 统计作为兼容字段，同时通过 `structure_dedup.current_workflow_asset_outcomes` 按当前 workflow 的唯一资产计算 review / not_adopted；旧资产之间的建议不进入本次资产汇总，同一资产出现在多个 pair 中也只计一次。Phase 3 自身的 `review_asset_count`、`uncertain_count` 与去重资产结果合并后会按结构总数 clamp，保持 adopted / review / not_adopted 互斥且总和等于本次结构资产数。高置信实体去重建议进入 review；只有授权策略明确允许且无 review 标记的工作资产计入 adopted。ignored、temporary-only、provenance conflict 和同 workflow 去重时被软废弃的重复结构计入 not_adopted。低置信结果不会自动提升为 canonical。

完整 Deep Import 成功后，imports 以冻结的 Phase 2 Scene hash、实体/关系 result refs、workflow 与授权回执通过 world facade
幂等创建 post-import `world_adoption_package.v1`。它不改变 Phase 2 的 adopted/review/checkpoint/
resume/rollback/asset_summary；包创建失败仅记录诊断，导入仍保持成功。已写入 canonical 资产只作
`existing_ref/no-op` 预览，candidate 实体/关系与 World Bible revision 仍需作者显式 preview/apply。
冻结 result ref 漂移或单包超过 31 个资产时显式记录组包失败，不静默截断。

`force=true` 的重复 Scene 提取把替换意图写入 task meta，直到 Scene commit 才执行。
commit 只软废弃 workflow-owned、未人工编辑的 `draft/candidate`；`canonical`、
`user_edited`、人工 Scene 和无合法 ownership 的 Scene 均受保护。新候选与受保护 Scene
重叠时不写入 active Scene，而是按重叠连通组持久化 replacement suggestion。完整导入的
Phase 2/3 使用 commit 后的有效 active Scene 集；Scene-only 重提和完整重提均不提前清理
world entities。任务在 commit 前失败时旧资产保持不变。

放弃可恢复 workflow 时会按 `novel_id + workflow_id` 整批回滚：Scene、世界对象、候选关系、候选别名和结构资产软废弃，Memory DeltaLog 在 `meta` 中标记 `rolled_back`。回滚幂等、保留审计字段，且不处理其他 workflow/小说或已标记 `user_edited` 的资产。

## 上下文快照边界

- Phase 2 保持由确定性工作流装配专用上下文，不重接通用 context compiler；Phase 2a 快照记录 `import-context-v2` 的完整紧凑上下文、来源与 fingerprint，Phase 2b 快照保留实际发送给 provider 的完整 fenced user payload、相关对象/关系引用、来源与 fingerprint，二者都回写 result refs。上下文和快照准备完成后先提交事务，再发起 provider 调用。
- Phase 3 结构分析由深度导入调用时传入 `workflow_id` / `task_id` 并开启 `audit_context_snapshot=True`；手动 AI 操作默认不创建 snapshot。
- Phase 3 继续复用 outline 的全书 Scene 摘要链路，不默认加载全书正文；追加 derived world background，并对空结构、无引用或无有效篇章范围执行至多一次 workflow-owned replacement rerun。
- Phase 3 快照使用 `context_mode="working"` 和 `include_pending_objects=true`，记录结构上下文的 section/token metadata。若当前编译结果未暴露完整 asset ids，只记录可见资产并在 metadata 中说明。
- 默认不保存完整 rendered context；调用方显式开启保留时才落库，并由 context 模块按保留策略清理。

## 快照健康摘要兼容

深度导入任务结果现在优先返回 `snapshot_health_summary`，用于展示快照数量、状态分布、超时 running、保留 full context 数和最近失败摘要。

`audit_summary` 暂时保留为兼容 alias，旧前端或旧测试仍可读取；新代码应优先读取 `snapshot_health_summary`，再回退到 `audit_summary`。前端只展示“快照健康摘要 / 快照状态”的轻量信息，不新增审计工作台。

快照维护入口由 context 模块提供：`POST /api/context/snapshots/maintenance`，默认 `dry_run=true`，imports 不直接访问 `context_snapshots` 表。

## 深度导入恢复语义

提交 deep-import/stage task 前会通过 project facade 验证当前 LLM
execution snapshot。API Key、Base URL 或 model 不可用时直接返回 400，
不入队，也不执行 force 覆盖前的派生数据废弃。worker 内的工作流
`phase="failed"` 必须收敛为 task `failed`；失败保留当前进度，只有成功终态写入 100%。

独立 `scene_auto_extraction` stage task 在任何 health/provider 调用前先以
worker lease fence 持久化一次 v2 prepare：冻结项目 title/genre/tone、项目 LLM
execution snapshot 指纹、授权范围与每章
`chapter_index + source_draft_id + content_hash` 来源向量，以及
`high_quality/replace_existing` 提交语义，并保存完整紧凑 Phase 1a context bundle、
选择 trace、contract version 和 fingerprint。正式提交前会在章节锁内重编译该上下文；
任一剧情结构、世界对象或左侧边界漂移都拒绝 provider 结果。未完成的 v1 prepare
必须重新提交，不能由 v2 Prompt 继续消费。旧任务只在第一次
prepare 时补冻结 snapshot，重试不把动态 lease/attempt 纳入语义指纹。
LLM health、Phase 1a/1b 与高质量 Phase 1c 等待期间不持有数据库事务；
provider 结果提交前按 project 优先锁序重验项目、snapshot、来源向量和
当前 task type/novel/lease/attempt。PostgreSQL 上还会按章节升序取 writing
version advisory lock，与正文版本创建和原地内容修改串行化。正式 Scene、
融合建议、RAG 入队、run checkpoint 与 task progress/result 投影只在同一个最终
fenced transaction 中持久化；完整 owner token 任一字段失配、空结果或覆盖不完整时整体回滚。
provider 在最终
commit 前崩溃时允许 at-least-once 重试，正式资产依靠 provenance key 与原子
checkpoint 保持幂等。该 seam 不改变普通 deep import、world-object 或
plot-structure stage 的现有执行路径。

worker 启动时会检测 stale 的 deep-import/stage task，清空旧 lease 并收敛为
`failed + recovery_required`，但不会自动继续。前端只在任务 `available_actions`
包含 `resume + abandon` 时展示恢复操作；resume 校验 failed 与双份 recovery flag 后，
在同一事务复用原 task、递增 run generation 并转回 pending，不伪装成仍在 running。
`async_tasks.progress` 使用基于近期 1–60 章实测的阶段估算。完整深度导入中，Phase 1b 推进到 `30%`，高质量 Phase 1c 占 `30–35%`，Scene commit 与建议写入占 `35–40%`。独立 Scene stage 在 Phase 1c/commit 收敛到 100%。阶段内按当前
window / Scene 的 `completed / total` 线性估算，该值不是精确剩余时间。

## 深度导入内部结构

`DeepImportOrchestrator` 负责重复导入策略、任务提交、恢复和放弃清理；
task handler 先把队列 claim 转成不可变 workflow-attempt DTO；orchestrator
不查询或更新 `AsyncTask` ORM。`workflow_runs.py` 负责 run 锁、generation 与 CAS；
`DeepImportWorkflow` 只保留 worker 执行入口和 `DeepImportWorkflowRuntime`
要求的活跃 phase runner seam；旧 Scene prefetch / reinforcement /
single-chapter / fusion wrapper，以及非 runtime seam 的薄包装/死代码已从
`workflow.py` 移除。
阶段实现拆在同模块内部：

- `workflow_phase_runner.py` — Phase runner 的共享 request / Protocol seam；
  `workflow.py` 通过该 seam 调用各阶段，旧 runner 方法保留兼容 adapter
- `workflow_scene_phase.py` — Phase 0 / Phase 1a / Phase 1b / Phase 1c / Scene commit
- `workflow_entity_phase.py` — Phase 2a / Phase 2b 与 world_objects stage
- `workflow_structure_phase.py` — Phase 3、plot_structure stage 与小样本结构保底
- `workflow_progress.py` — progress timeline、诊断计数、checkpoint/audit/snapshot summary 合并
- `workflow_llm_adapters.py` — 深度导入 LLM adapter、Phase 1a/1b prompt 和 token 预算控制；Phase 0 只做确定性规划，不再有 LLM prefetch adapter
- `scene_planning.py` — Phase 0 章节字符统计、字符预算窗口 / overlap / max_tokens 规划
- `scene_slicing.py` — Phase 1a Scene 边界切分、owned range 过滤和章节级 fallback
- `scene_enrichment.py` — Phase 1b 逐 Scene 补字段、锁定字段保护、确定性 `scene_chunks`
- `scene_fusion_phase1c.py` — 高质量导入的相邻 Scene 边界审核、高置信融合与建议生成
- `scene_fusion.py` — 内部兼容/修复路径使用的候选融合组件；旧 `scene_prefetch.py` / `scene_reinforcement.py` 已删除
- `deep_import_retry.py` — 深度导入 LLM 错误分类与阶段可控 retry 策略
- `agent_step_harness.py` — 旧 imports 路径兼容导出；权威实现已迁至 `infrastructure/llm/agent_step_harness.py`

这些文件不改变 HTTP API 或数据库 schema。`async_tasks.result` 会额外返回
向后兼容的 `phase_artifacts`，用于记录真实服务分阶段 compact artifact、
checkpoint 摘要、repair 状态和质量门禁；不保存 API key、完整正文、raw prompt
或 raw LLM 输出。artifact builder 会递归移除 prompt/body/content/context/raw LLM
payload 字段，并只保留脱敏 provider 摘要。服务路径还会返回
`progress_events` 与 `acceptance_checks`：前者是 compact JSONL-like 事件流，
后者是结构化门禁结果，供前端默认/详细两级进度显示复用。前端通过现有任务轮询读取
这些字段。

## 真实服务验收与恢复证据

当前验收和恢复证据以内嵌在 `async_tasks.result` 的 compact 数据为准，不再通过旧
real-LLM artifact harness 驱动。正式 Scene 自动提取链路是
`phase0_plan -> phase1a_scene_slicing -> phase1b_enrichment -> phase1c_scene_fusion -> scene_commit`；
Phase 1a slicing 的 `max_tokens` 来自 Phase 0 window 的
`clamp(round(input_chars * max_tokens_per_input_char), min_max_tokens, max_max_tokens)`。

生产任务和 stage task 会写入：

- `phase_artifacts`：章节覆盖、阶段计数、checkpoint 摘要、repair 状态、质量状态和脱敏 provider 摘要
- `progress_events`：compact JSONL-like 事件流，供任务轮询和前端详细进度展示
- `acceptance_checks`：coverage、zero output、degraded、repair 等结构化门禁结果
- `phase_errors`：按阶段记录可机器读取的失败或降级原因

这些字段只保留恢复、审计和展示所需的 compact 信息，不保存 API key、完整正文、raw
prompt 或 raw LLM 输出。阶段恢复策略由服务路径自己执行：Phase 0 少量 batch 失败时
自动重跑并合并一次；Phase 1a 对有限缺章做一轮 single-chapter fallback；Phase 2a /
2b 通过 checkpoint 和当前 Scene commit 结果复用已完成单元，只重跑失败或未完成单元。

Phase2b 稳定性相关环境变量：

- `PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS`
- `PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS`

旧 `SCENE_CHAR_LIMIT / ENTITY_INDEX_CHAR_LIMIT / ENTITY_INDEX_FALLBACK_LIMIT` 设置仅为
配置兼容保留，P14 v2 生产路径不再消费这些输入裁剪值。

Phase 2 的 Scene 实体抽取实现位于 `entity_extraction/` 子包；
`modules.imports.entity_extraction` 是稳定公共导出入口。旧顶层
`scene_entity_extraction.py` 兼容 hub 已删除；测试和生产 monkeypatch 路径应指向
`modules.imports.entity_extraction` 或其具体实现子模块。

生产路径由 `SceneEntityExtractionService` 直接组合 single/parallel/bulk、Phase 2b task、
alias/relation 和 persistence 内部 mixin；`Phase2WorldExtractor` 继承同一实现，不再创建
第二个 legacy service。原先只描述唯一实现私有方法的 runtime Protocol 已删除；保留的
helper 类仅用于旧测试/import 兼容，不是生产 DI seam。

- `entity_extraction/scene_entity_strategy.py` — 选择 empty / small-sample parallel / bulk / batched / checkpoint resume 路由
- `entity_extraction/scene_entity_single_scene.py` — 单 Scene 串行 Phase 2a
- `entity_extraction/scene_entity_parallel.py` — 小样本并发抽取与 bulk 失败 fallback
- `entity_extraction/scene_entity_bulk.py` — bulk 抽取、小样本 LLM supplement 与 fallback 候选
- `entity_extraction/scene_entity_alias_relation.py` — Phase 2b 别名/关系抽取
- `entity_extraction/scene_entity_alias_relation_task.py` — 仅供 world 手动补抽任务的
  prepare/LLM/finalize 事务隔离与漂移重验；detached receipt 冻结实际
  timeout/concurrency 并保持 Phase 2b 动态总超时语义，每个 Scene 的 context
  snapshot 只回写该 Scene 自身产物引用；不改变 Deep Import Phase 2b 路径
- `entity_extraction/scene_entity_persistence.py` — entity / alias / relation / delta 写入
- `entity_extraction/scene_entity_text.py`、`entity_extraction/scene_entity_snapshots.py`、`entity_extraction/scene_entity_llm_adapters.py`
  — Scene 正文、context snapshot、LLM adapter 支撑逻辑
- `entity_extraction/scene_entity_checkpoint.py`、`entity_extraction/scene_entity_config.py` — checkpoint、错误分类和 Phase 2 常量

这些拆分不改变 `extract_by_scenes()` / `extract_alias_relations()` 已有返回字段、
snapshot/audit summary、LLM prompt 或 timeout 语义；checkpoint 仅追加
`input_fingerprint` 用于安全续跑。

## Facade

```python
async def import_file(db, novel_id, file_name, file_content) -> ImportResponse:
    """导入小说文件"""

async def start_deep_import(db, novel_id, start_chapter, end_chapter, force=False, *, adoption_policy="user_authorized_pipeline", authorization_confirmed=False) -> dict:
    """提交深度导入任务；重复导入时先返回 requires_confirmation"""

async def start_deep_import_stage(db, novel_id, start_chapter, end_chapter, *, stage, force=False, adoption_policy="user_authorized_pipeline", authorization_confirmed=False) -> dict:
    """提交分阶段自动提取任务：scenes / world_objects / plot_structure"""

async def run_submitted_deep_import_stage(db, task_id, *, stage) -> dict:
    """在隔离评测/手动 harness 内执行已提交且已授权的 stage task"""

```

`run_submitted_deep_import_stage()` 只是评测/手动 harness seam，不新增
HTTP 业务入口。它在 inline 执行期间用独立 session 更新 task
heartbeat，避免被 worker stale scanner 误判为中断；同时保留
managed provenance、失败状态和脱敏 error，结束时取消 heartbeat。

## API

```http
POST /api/imports/upload      — 上传文件（multipart）；201 表示导入记录、章节工作稿和发布任务已提交，后续请求可立即读取
GET  /api/imports             — 导入记录列表
GET  /api/imports/{id}        — 导入记录详情
POST /api/imports/deep        — 提交深度导入任务；活动任务复用原 task，资产重复时先返回 requires_confirmation
POST /api/imports/stages/scenes — 提交“从正文提取 Scene”任务，只执行 Phase 0/1a/1b/1c + Scene commit
POST /api/imports/stages/world-objects — 提交世界对象与别名/关系自动提取任务，只执行 Phase 2a/2b
POST /api/imports/stages/plot-structure — 提交剧情线自动提取任务，只执行 Phase 3
POST /api/imports/deep/resume — 用户确认后继续可恢复的原 deep_import task
POST /api/imports/deep/abandon — 放弃恢复并清理同 workflow 自动派生资产
```

该可见性来自 `DbSession` 的 request-owned transaction：function-scope dependency 在普通非流式响应开始前统一提交，路由本身不持有单独的成功提交逻辑。

## 安全约束

- upload、导入记录读取、deep-import/stage 入队以及 resume/abandon 都在
  业务操作前通过 project facade 确认项目仍活跃；不存在与已进入回收站的
  项目统一返回 404。
- resume/abandon 先按 `task_id` 确认任务存在，再校验任务归属项目；
  不存在任务与任务归属项目不可访问统一返回 `404 Not found`，避免泄漏 task
  是否存在；回收站项目不会触发恢复或清理。owner 只通过 tasks facade 的
  最小投影读取，404 不回显 owner ID、task meta 或 result。

- 文件类型白名单：txt, epub, html, htm, mobi, azw3
- 文件大小上限：50MB
- 文件名 sanitize：防止路径穿越
- 客户端声明的 MIME 不作为信任依据；统一解析入口在调用具体解析器前校验实际
  内容。TXT/HTML 必须可严格解码且不含二进制控制字符，HTML 还必须包含可识别
  标记；EPUB 必须满足 ZIP mimetype、container/OPF 结构、安全成员路径及有界解压
  （声明体积不可信：按实测解压输出复核，伪造头部的解压炸弹会被有界拦截）
  约束；MOBI/AZW3 必须满足 PalmDB、PalmDOC 与 MOBI header 联合签名
- 不保存上传文件到可执行目录，解析后即释放

## 测试

```bash
cd backend
pytest modules/imports/tests/ -m "not real_llm and not external_data"

# 仅显式启用真实模型验收
cd ../.. && make test-real-llm

# 真实小说语料不进入默认测试；路径由调用者显式提供
cd ../.. && make test-manual REAL_SOURCE_PATH=/abs/path/novel.txt
```
