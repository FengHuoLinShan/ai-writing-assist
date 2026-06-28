# Context Snapshot Lifecycle v1

Status: Implemented v1.

## Settled Direction

`context_snapshots` 下一步优先服务开发/运维排障和 deep import 可解释性，不先服务普通创作者，也不立刻迁移手动 AI。

下一步最小交付物是 Snapshot Lifecycle v1：先治理快照生命周期、保留策略和健康摘要，再做完整上下文回放、diff 或审计工作台。

`context_snapshots.status` 保持执行结果三态：

- `running`
- `succeeded`
- `failed`

超时或失联的 `running` 快照不新增 `stale` 主状态；生命周期清理应转为 `status="failed"`，并用 `error_kind="stale_running"` 或 `error_kind="timeout"` 表示清理原因。依赖资产变化导致的上下文过期应使用独立语义，不能污染调用执行状态。

`rendered_context` 清理先做显式维护入口，不新增后台定时任务。`context.facade.prune_rendered_context(...)` 是权威入口；调用方可以接维护命令、脚本或受控 API。清理只清空 `rendered_context` 和 `rendered_context_expires_at`，不删除 snapshot 行，也不清 metadata、hash、asset ids 或 result refs。

## Language

**快照健康摘要 / Snapshot Health Summary**:
面向任务结果和维护入口的轻量聚合，只描述 snapshot 数量、状态分布、超时 running、retained full context 和最近失败原因。它不是审计详情、不是完整上下文回放，也不包含完整 `rendered_context`、prompt 或 result refs 列表。

## Aggregation

快照健康摘要的主聚合键是 `workflow_id`。Deep import 完成结果按 `workflow_id` 汇总；Phase 2/3 局部排障按 `workflow_id + phase` 汇总；项目维护入口按 `novel_id` 汇总并可选过滤 `workflow_id`。`task_id` 是异步任务承载 ID，不作为业务审计主聚合键。

## Running Timeout

Lifecycle v1 使用统一保守阈值：`running_timeout_minutes = 120`。维护入口只处理 `status="running"` 且 `created_at < now - 120min` 的快照，并将其转为 `status="failed"`、`error_kind="stale_running"`。后续可根据导入文件大小、章节数量或 Scene 数做简单动态阈值，但 v1 不引入 phase-specific 复杂配置。

## Maintenance Entry

Lifecycle v1 暴露后端维护 API，但不做前端工作台。维护 API 默认 `dry_run=true`，调用方必须显式传 `dry_run=false` 才会修改数据。

建议入口：

```http
POST /api/context/snapshots/maintenance
```

建议请求字段：

- `novel_id` 必填
- `workflow_id` 可选
- `running_timeout_minutes` 默认 120
- `prune_rendered_context` 默认 true
- `retain_latest_full_context_per_project` 默认 200
- `dry_run` 默认 true

响应应包含快照健康摘要、超时 running 数、清理 full context 数，以及 dry-run 下的 would-change 数。

## Compatibility

新设计术语和字段使用 `snapshot_health_summary`。现有 `audit_summary` 作为兼容字段暂时保留，内容可以与 `snapshot_health_summary` 等同；新代码和文档应优先使用 `snapshot_health_summary`。前端读取时应优先读 `snapshot_health_summary`，再回退到 `audit_summary`。

## Scope Boundary

Lifecycle v1 只处理调用执行状态和数据保留，不处理依赖资产变化后的上下文有效性。资产变更后是否标记 snapshot 或 result 为需复核，属于后续 `Context Validity / 上下文有效性` 设计。

Lifecycle v1 不迁移手动 AI 操作。手动 AI 继续使用 `context_confirmations`；Lifecycle v1 不为手动 AI 生成 snapshot、不做双写，也不改变确认弹窗语义。未来如需迁移，可单独设计 `context_confirmations` 与 `context_snapshots` 的弱关联，例如 snapshot 可选 `context_confirmation_id`。

Lifecycle v1 不新增数据库字段。超时 running、full context 保留、健康摘要、dry-run、workflow/phase 聚合都使用现有 `context_snapshots` 字段和运行时聚合表达。只有未来做 Context Validity、手动 AI 关联、自动调度记录或回放索引时，才重新评估 schema 变更。

## Deferred

- 手动 AI 操作是否迁移到 `context_snapshots`
- 完整 rendered context 回放和 diff
- 用户可见审计工作台
- 自动定时清理任务
- 基于文件大小或导入规模的动态 running 超时阈值
- Context Validity / 上下文有效性：依赖资产变化后标记 snapshot 或 result 是否需复核
