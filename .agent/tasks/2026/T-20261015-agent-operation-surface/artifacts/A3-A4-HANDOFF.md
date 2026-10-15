# A3 / A4 后续批次交接

核实时间：2026-10-16。状态：待实施；属于用户明确要求的三份计划全部执行范围。
实现用 Luna/max，Sol/high 独立 review 并直接修复。真实数周使用数据依赖不伪造。

当前状态优先见主TASK恢复快照：A3 Luna候选e68已交Sol独立审修，A4 Luna正实施，
并非尚未启动；本文早期描述保留为验收要求，不能把未接线候选算交付。

## A3 作者侧 Interaction 与 Collaboration

- 先核对 ADR-0018、ADR-0027、ADR-0038 与真实服务。作者项目、隔离 RP 旅程项目及其只读
  来源项目不是同一个授权范围。现有 Assistant 默认只接受 author 项目；新增操作必须证明
  当前账户拥有目标旅程及项目，不扩大 RP 角色运行时能力，不伪造 author 上下文。
- 覆盖作者侧 RP 设置、旅程管理与摘要刷新。摘要刷新若涉及模型，先做真实预算/资料/费用
  预览，执行只复用冻结的领域授权与根预算。不要把普通资源刷新标成不计费模型操作。
- Collaboration 先提供试改和跨域原子采用的准备，复用现有工作区/封存/差异与 merge 服务。
  准备不排队、不修改作者资产；实际原子采用仍为 R3，每次显式确认。不能把团队自治或
  授权开启/扩大加入目录；长期历史删除、公开导出和凭据均保持禁止类别。
- 每项走实际 SPEC、组合根注册、HTTP binding/留痕、新目录冻结及必要的 task/read_result
  适配。纯插件文件存在不算接线完成，缺适配的多阶段操作明确停下。
- 作者手动界面继续可用；scope 漂移/409/跨账户/匿名 demo/重复确认/领域事务失败需真实
  API 与独立 PG 会话验证。新增路由不能扩宽历史豁免或 import 基线。

## A4 可先做的工程与外部依赖

- 当前 aggregate/export 会合并实时事件频次，但序列仅来自 >180 天的归档汇总，尚不含当前
  明细序列。先让当前与归档序列可复现、无重复计数；按会话/运行/调用分组、数据库序列及
  明确时间窗确定顺序，边界和数据覆盖范围可解释。输出不含项目资产、会话、运行或目标 ID。
- 当前保留字段不能证明所有接受率、编辑后接受率、恢复率、耗时或计费用量。先核对实际
  事件与 usage 契约；有分子无分母时报告不可测或覆盖率，不填 0，不把执行成功当作者接受。
  去标识归档目前不保留全部耗时/用量，新增汇总只能向前可靠计量，不能补造过去指标。
- 报告可排序候选模式、列出可追溯的聚合计数及覆盖缺口；真实 Top 3 代码化依赖至少数周
  使用数据。合成测试数据只证明分组、去重、隐私和计算正确，不证明真实高频模式或收益。
- 留痕开关仍本地单用户默认开启、公开默认关闭、demo 不写；180 天后只保留无 ID 汇总。
  不将报表统计作为扩大操作、预算或持续授权的依据。
- 结合作者界面提供清楚的筛选/覆盖说明与导出，错误和加载状态可信；无数据时直说无样本。
  检查范围、权限及真实正文反向检索，确保报告/CSV/序列均无正文、凭据或可逆资产标识。

## 开始前恢复

从已集成的最新 primary 固定提交新分支；A2 Goal 与 C2 正在并行改 Assistant 组合根，避免
共写其服务和版本冻结，必要接线由 Sol 顺序组合。核心规则见主 TASK 和 A1-A2-HANDOFF。
主代理独占 TASK.md。测试仅 correct primary venv、假 DATABASE_URL 与向 root 排队的新专用
PG DB；不访问默认开发库、封存 R3、holdout、65302 或真实模型。无推送/PR/main 合并/部署。

## 2026-10-16 A4 源码复核补充

- `archive_expired_operation_traces` 当前按数据库 `id` 排序，但只取严格超过180天的行，再按
  UTC日与 `session_id or run_id or call_id or row.id` 组成完整序列；若同一天同一组分两次跨过
  保留边界，两段分别归档，不能把它们当成同一次完整会话。报告还另用应用时钟计算明细边界。
  新报表须统一冻结统计时点，明确窗口/序列定义，并以分批归档前后不变的样例证明无重复或缺漏。
  不保存可逆ID或长期组标识来规避180天隐私规则；既有不可复原汇总也不能改称新口径的完整观测。
- 真实明细已有 `duration_ms`、白名单 usage 计数及 `usage_complete/usage_unknown` 标记；
  对应归档目前只有事件计数与操作序列。新可测指标只从有证据字段计算，报告历史覆盖缺口。
  `confirmed`、`edited`、`executed`、`restored/undone` 的生命周期必须结合实际生产写入位置核对，
  成功执行不能直接算作者接受，重复确认不能增大分母，未知结果也不能算失败或成功。
- `AssistantOperationTrace`、事件汇总、序列汇总都是 append-only/privacy 边界的一部分。
  新格式与旧目录/旧汇总要显式区分，保留历史，不重写旧事件。统计只给作者本人，
  不开放AI外部导出或扩大授权。实际样本不足时展示不可测和覆盖量，不用合成样本选真实Top3。

## A3 摘要根预算审修必做（Luna实际源码核对）

新摘要入口当前 `ROOT_BUDGET_ADAPTER_UNAVAILABLE` 是暂时安全停点，不是A3交付豁免。
后续Sol直接补任务级适配并验证真正执行，不能仅改预览的 `execution_ready`。

- `interaction/tasks.py` 的 `interaction_summary_refresh` 当前 auto_requeue/max_attempts=2、
  request_limit=8、deadline=None，handler 还套 `retry_with_backoff(max_attempts=2)`；
  structured修复可能另发一次请求。
- `workflow_budget.py` 的 unknown-stop 仅覆盖AIRunEnvelopeV4；V1 settle无usage会记unknown，
  后一次reserve仍能进行。Task worker的非EnvelopeError失败又可能auto_requeue。
  现有worker已经跨attempt恢复同一V1信封并在provider前按租约checkpoint，不能误称其重置账本。
- 真实复现应覆盖：第一次provider Timeout/结果未知 → 下一次retry/reserve零provider；
  worker重排/恢复不清原unknown、不重置start/deadline/累计；作者重新核对后新增unknown再次停。
  冻结源版本/路径/Project profile及finalizer stale fence也须实际worker验证。
- 收窄到该摘要任务，不全局放宽或迁移旧V1运行；原冻结运行与旅程只读来源边界保持。
  以精确TaskFacade任务回执证明幂等与恢复，overview的task pointer仅是当前投影，不代替回执账本。

## 2026-10-16 root复核的当前审修点

- A3 Sol已复现并修真实ProjectContext的novel_id误用、归档consumer导致旅程不可恢复、
  项目助手未开启时作者RP管理不可达。专库HTTP/worker、390/1280与组件草稿/409回归正在收尾。
  root已看两张RP面板截图；它们是设置变更前状态，不冒称保存后的视觉证明。
- root进一步发现A3 WIP把同一interaction_summary_refresh注册的deadline改1800、
  unknown/80%常开，实际影响了没有author_project_id的旧RP任务。Sol已确认并直接收窄，
  正按新作者任务的冻结绑定启用，旧RP的deadline=None及旧V1恢复合同保持；最终固定点
  仍须新作者/旧RP两类实际TaskWorker对照，不把一类绿色测试当整体兼容证据。
- A4 WIP的operation_trace_cutoff把now-180d向UTC午夜取整，归档只删该时点以前，
  原始标识会超180天多留不足一天。root已按实际源码确认，Luna明确将它列作Sol直接审修项，
  没有改写ADR0038到期后ID-free的口径。后续Sol必须修精确保留边界，且保当前/归档去重、
  分批与一次归档等价、旧摘要incomplete覆盖；不能永久保存组哈希或延迟删除raw规避。
  可评估首次到期前汇总整个已闭合UTC日、记录无ID完成窗口，再精确删除过期raw与按窗口
  去重的窄方案；这是审修方向，不是已实现结果。不得在Luna活跃树共享写入。
