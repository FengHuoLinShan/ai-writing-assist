# A1 / A2 后续批次交接

本文件是执行切片和当前源码导航；产品契约仍以
[操作入口计划](../../../../../docs/plans/2026-10-15-agent-operation-surface.md) 与
ADR-0038 为准，不改变三份计划全部实施的范围。

## 基线、协作和验证

- A0a 已在主树；A0b 三个实现提交 f9a9d8f14、87752e8fd、203018dfd 正由
  Sol/high 在 map-assistant-review/codex/operation-trace-review 独立审修。
  HTTP trace context 未实际绑定的 P1 已复现并由 Sol 直接修复，但尚未集成；
  新批次须以审修后的主树为基线，不能以原实现测试绿色替代审查。
- Assistant 核心、组合根、service_keys、路由绑定表和 Alembic env 各批次只有一个写入者。
  其他模块新增纯 OPERATIONS_SPEC，提供精确接线清单。所有新增写路由需绑定目录项或真实
  豁免理由，不得加入旧路由 ratchet baseline。问题和 Git 冲突由 Sol/high 直接修复。
- 唯一最终后端解释器为
  `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python`
  （3.14.8 / Pydantic 2.14.0），配目标树 backend cwd。不得用原 repo 的 3.14.7 venv
  改 golden 或作最终证据；不安装/同步依赖。工程 PG 由 root 串行分配独立 DB。
- 不接触评测 65302、封存 R3、holdout 或真实数据；不发模型请求；仅本地提交，不推送或发布。

## A1：真实领域能力与第一波路由

- World 类型转换实现位于
  `backend/modules/world/services/core/entity_type_transition_service.py`，
  融合位于 `entity_fusion.py`，历史 API 位于 `api/history.py`、`api/revisions.py`。
  调用已有领域服务，准备阶段冻结完整来源、目标与基线；融合/采用为 R3，不因可恢复降级。
  不能靠写 ORM 复刻领域行为。Generic profile 桥接/类型转换文件由 C0 Luna 使用，
  A1 初期只新增工具文件，避免共享写。
- Story 伏笔/揭示真实入口在 `outline_state/api.py` 的 foreshadowing/reveals 段；
  读取 facade 在 `foreshadowing_facade.py`、`reveal_facade.py`。时间线、排序、拆合
  要核对既有服务及授权范围；不用任意正文表达式或模型指令当作执行器。
- Writing 批注领域操作在 `comments.py`，章节/工作稿入口在 `api.py`。
  章节管理与批注状态接入同一校验/CAS，正文采用和发布状态仍为 R3。
- Evolution 已有 `assistant_tools.py` 的 prepare_reading/prepare_spatial_rescan，
  应先核对已覆盖内容，再补缺项；只准备自己的授权预览，助手确认不能代替计费运行授权。
- Evidence 现有目录只有专项 forecast；项目检索、来源回读、知识范围预览应复用已有读取端口，
  作为 R0 目录项，继续守 owner/novel/Scene cutoff/隐藏资料边界。
- 每个插件包含完整 v2 元数据、显式 trace 字段、risk/fee/transaction_mode、版本与参数
  快照；准备与执行使用同一 schema/校验，并通过真实路由覆盖测试验证，而非只检查装饰器文字。

## A2：目标运行

### 现有源码入口

- `backend/modules/assistant/models.py:AssistantRun`：mode 当前只有 author/background；
  session_id 可空，既有 uq_assistant_session_active 只约束 pending/running 非空会话。
  新 goal 不绑定会话，来源会话仅记检查点；新增每项目 pending/running/waiting_approval
  部分唯一索引，不能借复用会话索引实现。
- `service.py`、`operations.py`、`tasks.py`、`api.py` 拥有现有轮次、预览批次、执行及恢复。
  先追踪真实调用，不改变 v1–v6 冻结和原作者批次语义；goal 专用编排可独立模块，
  不把新目标语义塞进原会话状态机。
- `backend/infrastructure/llm/agent_runtime.py:AgentRunBudget` 当前 mode 为 author/rp/background，
  固定旧额度和 30 分钟。`infrastructure/llm/schemas.py` 定义 AIChargeState 与运行授权。
  旧预算模型本身不足以表达目标的作者可选根预算；复用运行信封/累计回执，不能通过改旧默认值
  隐式放宽既有模式，也不能在恢复时清零 started_at、请求或未知用量。

### 必须同时完成的行为

- 默认关闭、显式 allowlist；计划是严格数据，至多 30 步 DAG；参数引用只允许类型化前序产出，
  展开有界，无 eval/表达式/任意工具。模型计划经 owner 当前验证的 Project gateway。
- 作者审批冻结 op_id/module/object/risk/budget/自动上限；确定性范围比较发现任何扩大即停点。
  资料是数据，不能授权自己；重规划不能凭模型声称“范围一致”。
- 每步 uuid5(run, step, 参数指纹)，执行前 prepare/重验；R0/R1 自动，R2 每目标开关默认关，
  R3 始终确认、R4 单独确认。演示身份拒写；被排除类别永不入目录。
- 多阶段操作按领域回执对账；未知收费或结果未知停点，不重试/跳过/宣称成功。暂停、失败、
  恢复、作者修改和重复推进累计同一根预算；80% 停下请示，不能偷偷增加额度。
- R2 自动写入前记录可恢复 manifest，支持一键恢复目标开始前版本；恢复本身也要重验作者
  后续编辑，避免覆盖新改动。没有真实领域恢复能力的操作不能被纳入 R2 自动范围。
- 前端可审计划、删改步骤、预算、R2 开关、停点/暂停/恢复及变更清单；错误/冲突/项目切换
  保留用户输入。原 conversation 单轮继续可用。
- PostgreSQL 验证活动唯一性、幂等、并发推进、取消、重启恢复、预算和漂移；故障注入覆盖
  多阶段“服务已提交但进程未记成功”与未知收费，不只做内存 helper 测试。

## 后续验收与范围

A3 作者侧 Interaction / Collaboration、地图与势力后续能力仍需实施。A4 可以先实现去标识
报表，但至少数周真实数据和前三高频模式选择不能用合成数据冒充；真实门禁单列。
新批次依然 Luna/max 实现、Sol/high 审查并直接修复；root 负责集成、最终检查和唯一 TASK 写入。


## 2026-10-16 A1新批次已启动

- A0b与扩大回归Sol净修复已在primary32e63b630；root原扩大套2178通过、RuntimeWarning转error
  无失败，只有既有Pydantic schema warning。该基线优先于本文开头的旧A0b审查中描述。
- luna_high_frequency_ops（Luna/max）在map-assistant-operations/codex/high-frequency-operations-impl，
  从dbdd88715启动A1第一波纯插件。旧codex/map-assistant-operations/748分支保留。
- map-operation-catalog-impl仍有旧A0未提交WIP（bootstrap/core/config/keys/trace等），仅核对过状态，
  没有切分支/覆盖/清理；不可拿它当新批工作树。
- C0b Sol仍独占Evidence compilation、World dossier、keys/bootstrap；C4a Luna只动Story OneClick
  simulation片段。A1不改Assistant已有核心、app/main/bootstrap、共享route表或Alembic env，提供
  精确注册、route binding与冻结版本清单，后续Sol直接装配。不得引入function import预算增长。
- UI Sol已在map-clue-review/codex/copilot-ui-integration-review提交73d3cadb第一轮C3b/C2b审修；
  248文件/3134前端、27后端source/unified定向与lint/build门通过。待C0b分页/demo安全净fix和
  工程PG再followup同Sol做真实HTTP/并行独立session联调，当前暂结束释放实施槽。


## 2026-10-16 当前后续入口补充

- primary19589fa11（业务代码a18b80cd5）已集成C0b安全审修和C3b/C2b真实组合，
  root86后端/3专用PG/3134前端及lint/build通过；本文开头旧A0b状态仅为历史。
- A2现有稳定执行契约在 `modules/assistant/contracts.py`，不是core：
  `AssistantOperationContext` 已有run_id/owner/work/operation_id/llm_snapshot/internal_meta
  及trace_actor_type（支持goal）。操作注册装配在 `app/assistant_operation_registry.py`，
  已严格校验纯SPEC和trace参数声明。目标引擎复用这些契约，但不要调用conversation
  `decide_batch`冒充goal状态机或改变原确认上限。
- 当前 `operations.execute_suggestion` 是已有根累计调用示例：固定 operation_id、
  `_execution_mode=inline_only` 与 `_parent_task_id`、领域任务回执、`workflow_budget`
  以及 `read_result`。A2及C2新R1操作需证明没有独立排队后脱离父预算的付费路径。
- `infrastructure/llm/workflow_budget.py:AIRunEnvelope` 已提供并发串行计量、checkpoint
  失败拒绝provider I/O、deadline/usage/unknown与step回执。复用运行信封，并将目标自己的
  根限制与80%停点持久化；不可复用 `AgentRunBudget` 旧author默认12请求当作者目标预算，
  也不能为目标随意提高旧author/RP/background默认值。
- A1章节重排暂无领域服务，不可直接改chapter_index；该字段参与版本唯一键、正文来源、
  批注、Story场景与Evolution冻结读取。保留独立领域切片，不在插件里ORM模拟。
  当前时间线可复用 `story.edit_information_plan` 的伏笔/揭示章节字段，应明确覆盖边界。
- A3仍需作者侧Interaction配置/旅程/摘要刷新及Collaboration试改/原子采用准备；
  不向RP角色运行时开放作者工具，不以“准备”代替真正的计费授权或R3确认。
- A4现有 `/operation-traces/aggregate` 与 `export` 只有事件频次及已过180天归档的序列。
  报表实施需正确聚合当前明细序列（按会话/DB序号及声明窗口）并与归档合并，
  还要给接受/拒绝/先改后接受、恢复率、耗时用量与留痕缺口；无法测量的分母标未知。
  不能把“没有明细序列”当无人使用，更不能用合成测试假装已累积数周真实数据或选择真实top3。

## 2026-10-16T01:44 当前实际接线与下一轮

- A1首批已在primary6a31ba327：实现20635fde5、Sol净审修3441ab980及API边界命名修复6a31。root2123扩大回归与2专用PG通过；目录v8/89项，旧v1–v7冻结保留。HTTP router在modules/assistant/operation_api.py，app仅挂载/通用trace，不再用app业务编排规避依赖。
- Evidence有原confirmation时整目标inspect失败关闭，精确source.read保留；不能只凭资产ID重读已省略的字段或正文。A1剩余章节重排/一般事实时间线仍未落地，不修改chapter_index假装排序。
- Goal Luna已无损接新基线（1d2c2f137+af3b00836），现有Assistant/core/config必要Goal接线由其单写；新AIRunEnvelope版本的跨域allowlist从审批冻结范围确定，不能全局放宽旧信封。World地图author decision当前绑定真实conversation/message，Goal不可伪造来源；map R2不在本批自动allowlist。
- C2预审确认两个对象参考Settings字段尚缺以及generic legacy时点证明同值不同field误匹配，待固定点由Sol直接修；不要把原WIP已测说成已审投产。A4仍需live序列/接受与恢复分母/耗时用量/缺口覆盖，不造数周数据或真实top3。

## 2026-10-16 剩余A1的实际领域起点

- Writing 的正式对象是 `WritingDraft`，不存在可随意编号的独立 Chapter 行；唯一键为
  `(novel_id, chapter_index, version_number)`，稳定正文来源还有 draft UUID/content_hash。
  `services.py` 是兼容再出口，真正草稿实现为 `draft_service.py`；章节列表、最新有效章和
  来源重验锁等已有 `writing.facade`，先追踪所有版本、批注、Story绑定和Evolution冻结读取。
  章节排序须形成可预览、并发重验、原子执行与可恢复的领域方法，同步真实列表/写作调用者，
  不能只在插件或前端重排列表、直接交换chapter_index或破坏旧来源身份。采用或影响已确认
  故事语义时按R3确认，不能藉R2自动执行绕过。具体最小方案由Luna读完真实链后实施，Sol审修。
- 一般事件时间线已有真实服务：`story/continuity/services.py::MemoryService.list_events`
  与 `get_entity_timeline`；HTTP为 `/api/novels/{novel_id}/memories/events` 和
  `/events/{entity_id}/timeline`，均先 active-project/owner 保护。Story facade当前未导出这两项。
  可复用服务提供真正R0目录读取，保留范围、分页、来源、状态和未知语义，不把伏笔/揭示计划
  当已发生事实，也不为补目录任意新增正史写操作。需要截止Scene的消费者必须过滤后续资料。
- 新目录/HTTP留痕、幂等回执及恢复都要同批实际接线；不能把提供纯SPEC当完成。
  当前共享组合由C0c Sol单写，后续实施树从已审primary开始，本域固定后Sol顺序组合。
