# ADR-0011 — Keyed task coalescing 与领域 owner

- **状态**: Accepted
- **日期**: 2026-07-24
- **决策来源**: 持续风险审查 D-01、D-04、D-07、D-11 的用户确认实施

## 背景

`async_tasks` 已提供 claim、lease、attempt、heartbeat、stale recovery 和项目删除 fence，
但它是任务传输与执行状态，不应同时承担每个业务工作流的领域真相。

此前四条路径缺少一致的并发身份：

- RAG 章节索引只有 source hash 和状态，没有能阻止旧 attempt 提交的 durable owner/generation；
- imports 的阶段、恢复和 checkpoint 直接依赖通用 task ORM，领域状态与 transport 状态双写；
- World Bible projection 通过扫描最近 50 条全局任务寻找重复请求，无法覆盖高并发与长历史；
- RAG entity reannotation 以 query-then-insert 创建 pending follower，数据库不能保证唯一。

这些问题不能靠扩大查询窗口或增加进程内锁解决；多 worker 下需要数据库可判定的 keyed
coalescing，同时需要由领域表持有不可从通用 task 状态推断的 owner、generation 与 checkpoint。

## 决策

### 1. `async_tasks` 提供通用 keyed coalescing

`async_tasks.novel_id` 同时是任务项目边界的一等、可索引且不可变列，并以
`ON DELETE CASCADE` 外键关联 `projects.id`。`meta.novel_id` 仅保留兼容投影：新任务以显式
`enqueue_task(..., novel_id=...)` 建立规范 UUID 的列/投影，数据库与 ORM 拒绝漂移；显式
`owner_scope="global"` 的任务两处都为 NULL/缺失。当前业务 handler 全部为 project scope，
所有授权、lifecycle 和 worker preflight 均以列为准，HTTP 与前端 wire 不变。

`async_tasks.coalescing_key` 保存内部 SHA-256，不保存或暴露原始 key。v1 输入严格为：

```text
canonical JSON(
  novel_id = normalized UUID string,
  scope = ordered string list,
  task_type = task type,
  version = 1
)
```

canonical JSON 使用 `ensure_ascii=True`、紧凑分隔符和键排序。key 不包含 API Key、
LLM credential 或任意 secret，也不进入 API、错误和日志。

数据库分别保证同一 key 最多一个 `pending` 和一个 `running` task：

- `reuse_active`：复用 pending 或 running；适合一次只需一个活动执行的刷新/索引；
- `one_pending_follower`：复用 pending，但 running 存在时允许且只允许一个 pending
  后继；适合运行期间发生的新失效通知。

终态 task 保留历史，不参与唯一约束。并发插入以数据库唯一冲突收敛，不把
query-then-insert 当作正确性边界。

固定 scope 为：

- imports 五类工作流：`("imports_pipeline",)`；`task_type` 仍是 v1 key 的组成部分；
- World Bible projection：`("page_projection", page_id, projection_type)`；
- RAG chapter index：`("chapter_index", chapter_index, content_mode)`；
- RAG entity reannotation：`("entity_activity",)`。

### 2. 领域状态与 task transport 分离

RAG 的 `rag_index_state` 持有当前 `active_task_id + generation`。owner 变化时 generation
递增；claim、checkpoint 和 finalize 必须同时验证来源与 owner generation，旧 task/attempt
即使晚到也不能覆盖新索引状态。

imports 新增 `import_workflow_runs`，按项目保存 workflow type、阶段、章节范围、状态、
generation、当前 task/attempt/lease owner、授权与 LLM 快照以及 prepare/checkpoint/progress。
一个项目最多存在一个 `pending/running` 或 `recovery_required=true` 的 run。首版保持
`workflow_id == task_id`，不改变既有 wire；`async_tasks` 继续负责排队、lease、heartbeat
与公开 task 状态，但不再是 imports 可恢复阶段的唯一事实源。

World Bible projection 继续以 page/source version/hash CAS 决定派生结果能否晋升；
keyed task 只保证排队收敛，不替代领域新鲜度判断。RAG reannotation 同理只把失效通知
收敛到一个 pending follower，不把 task key 当作对象词典版本。

### 3. 迁移与重启 reconciliation

迁移只为能从现有无 secret task meta 完整解析的已知任务生成 v1 key。若存量数据违反新
唯一性，按 `created_at, id` 确定性保留最新活动记录，其余转为
`cancelled/superseded_migration`。无法证明 project/章节范围的畸形 imports 活动记录直接
取消，failed 历史记录清除不可执行的 recovery 标记，不猜测缺失身份后绑定新请求。

该数据迁移必须连接数据库并在事务内执行，不支持 `alembic --sql` 离线渲染：v1 hash 回填与
存量 winner 裁决需要读取真实行。离线跳过回填再创建唯一索引会在存量库产生不可验证结果，
因此 migration 在输出 DDL 前显式拒绝 offline mode。

存量 imports task 回填为领域 run；存量 RAG 活动索引 task 与 state 建立 owner。启动恢复仍
必须处理 task 与领域 owner 不一致、owner task 已终态、lease 丢失和 source drift，不能假定
一次 migration 永久消除运行时崩溃窗口。

部署前遗留的 running imports task 不继承已经失去 worker 的 lease。支持人工恢复的
deep-import/stage task 转为 `failed + recovery_required`，由用户从冻结 checkpoint 恢复；
采用自动重启语义且没有人工恢复入口的 map enrichment 则清空旧 lease 并回到 `pending`。
worker 启动在通用 stale scan 后另做 imports/RAG owner reconciliation，覆盖迁移后的未来
crash 窗口。imports 的 novel/task-scoped 懒恢复还会识别通用 retry 重新置为 pending 的
terminal map run；若项目已有更新的 active/recovery run，则旧 map task 不得夺取 owner。
当重启发生在 heartbeat 宽限期内，启动扫描尚不能判定旧 lease 已失活；因此后续 stale scan
实际转换 task 状态后，必须再次运行同一组领域 owner reconciliation，不能把“只在进程启动时
调用一次”当作 crash-window 正确性前提。

## 结果与非目标

- 不修改 HTTP API、前端 wire 或 task 状态响应。
- 不引入 Redis、新队列、新依赖或跨进程协调服务；数据库唯一约束是多 worker 收敛点。
- 不把所有任务强制迁移为 keyed task；调用方必须选择稳定、无 secret 的领域 scope。
- `async_tasks` 仍不成为跨模块业务 ORM。调用方只使用 tasks facade/contracts；领域 owner
  由所属模块实现。
- 删除 keyed scope 后，World/RAG 并发去重测试必须失败；删除领域 owner/generation 后，
  RAG 旧 attempt 与 imports 恢复 fence 测试必须失败。这是两类 seam 的 deletion test。
