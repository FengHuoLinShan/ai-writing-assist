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
