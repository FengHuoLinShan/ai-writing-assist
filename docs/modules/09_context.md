# Module: context / 上下文编译模块

## 定位

context 模块决定“这次 AI 操作到底能看到哪些资料”，不是单纯把数据库内容拼起来。

当前有两条能力线：

- `compile_structure_context()`：兼容旧调用方的结构化 bundle
- `compile_with_tiers()`：当前前端和 AI 参考资料确认流程使用的分层编译器
- `context_snapshots` facade：自动 AI 流水线的上下文快照审计记录

## 数据与来源

context 本身不拥有业务事实，但当前**有自己的确认与审计记录表**：

- `context_confirmations`：AI 参考资料确认记录，保存 action、scope、selected_asset_ids、warnings、result_refs、stale_reasons 等摘要
- `context_snapshots`：自动 AI 调用上下文快照，保存 task_id、workflow_id、phase、context_mode、included_asset_ids、摘要、prompt_hash、token/section metadata、result_refs 和错误信息

聚合来源仍来自：

- `project`
- `world`
- `memory`
- `outline`
- `rag`

## 编译模式

### 1. 兼容 bundle

`StructureContextBundle` 仍然保留一些历史字段名以兼容现有渲染器和测试，例如：

- `memory_records`：现在实际承载的是记忆全景/快照视图，不是旧表 `memory_records`
- `timeline_events`：来源于 `world` 的事件上下文
- `geo_locations`：当前通常为空，geo 模块已移除

### 2. 分层编译器

`CompiledContext` 是当前主路径，按 tier 组织内容并做预算裁剪。前端 `contextView`、AI 参考资料确认、outline 生成等都优先使用这一层。

## Loader 架构

`ContextCompiler` 使用 loader 策略按需拉取数据。当前主来源可概括为：

| Loader | 当前来源 |
|--------|----------|
| `ProjectLoader` | `project.facade` |
| `WorldEntitiesLoader` / `CharactersLoader` | `world.facade` |
| `EventsLoader` | `world.facade.get_events_context()` |
| `MemoryRecordsLoader` | `memory` 全景查询 |
| `OutlineArcLoader` / `SceneLoader` / `PlotThreadsLoader` | `outline` 服务与 facade |
| `RagChunksLoader` | `rag.facade.retrieve()` |

## AI 参考资料确认

手动 AI 操作在 world / outline / writing / generate 等入口发起前，可先创建确认记录：

- `confirm_context()`：编译并落一条 `context_confirmations`
- `require_confirmation()`：校验 action / novel_id / confirmation_id 是否匹配
- `attach_result_ref()`：把后续任务或产物回写到确认记录
- `mark_asset_context_changed()`：资产变更后把相关确认记录标脏

关键参数：

- `context_mode`：`canonical` / `working`
- `include_pending_objects`：是否允许待确认对象进入本次上下文
- `excluded_asset_ids`：显式排除的资产
- `user_note`：用户对本次 AI 操作的补充提醒

## 自动上下文快照

深度导入 Phase 2/Phase 3 的真实 LLM 调用会通过 context facade 创建 `context_snapshots`：

- Phase 2 记录当前实体抽取实际送入 LLM 的 handcrafted context，不重接 context compiler。
- Phase 3 记录结构分析使用的 working context，并设置 `include_pending_objects=true`。
- 默认只保存摘要、资产 ID、hash 和 token/section metadata；完整 `rendered_context` 需要调用方显式开启，并由保留策略清理。
- `context_snapshots` 不替代 `context_confirmations`，也不替代 `memory_snapshots`。

Lifecycle v1 为快照提供显式维护入口：

- `build_snapshot_health_summary()`：按 `novel_id` 和可选 `workflow_id` 聚合快照健康摘要。
- `mark_stale_running_snapshots()`：把超过运行超时的 `running` 快照标为 `failed/stale_running`，默认 dry-run。
- `prune_rendered_context()`：只清理完整 `rendered_context` 和过期时间，不删除快照或 provenance metadata。
- `run_snapshot_maintenance()`：组合超时标记、full context 清理和健康摘要返回。

维护 API 默认 `dry_run=true`；调用方必须显式传 `dry_run=false` 才会修改数据。

## 预算与裁剪

当前默认总预算由 `CompileOptions.budget_tokens` 控制，前端默认 4000。

分类预算仍由 `CONTEXT_BUDGET` 提供，包括：

- `core_entities`
- `normal_entities`
- `characters`
- `memory`
- `foreshadowing`
- `timeline`
- `geo_relations`
- `relationship_edges`
- `rag_chunks`

## API

```http
POST /api/context/compile
POST /api/context/render
POST /api/context/confirm
POST /api/context/recompile
GET  /api/context/snapshots
GET  /api/context/snapshots/{snapshot_id}
POST /api/context/snapshots/maintenance
```

## 不做

- 不把整个项目全量塞进一次请求
- 不绕过 reveal / knowledge / pending-object 约束
- 不负责剧情推理或生成正文
