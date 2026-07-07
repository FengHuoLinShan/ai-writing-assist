# Module: context / 上下文编译模块

## 定位

context 模块决定“这次 AI 操作到底能看到哪些资料”，不是单纯把数据库内容拼起来。

当前有两条能力线：

- `compile_structure_context()`：兼容旧调用方的结构化 bundle
- `compile_with_tiers()`：当前前端和 AI 参考资料确认流程使用的分层编译器
- `context_snapshots` facade：自动 AI 流水线的上下文快照审计记录

`compile_with_tiers()` 不只是生成最终 Markdown。它先生成可审查的 `CompiledContext` IR，再由 API 和前端把每个 section 的标题、状态、来源、激活原因、token 和裁剪结果展示给用户。

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

`CompiledContext` 是当前主路径，按 tier 组织内容并做预算裁剪。前端的生成中心任务页、AI 参考资料确认、outline 生成等都优先使用这一层；旧 `context` hash 入口已由路由层重定向到 `generate?tab=task`。

每个 `ContextSection` 会携带审查台元数据：

| 字段 | 含义 |
|------|------|
| `title` | 面向作者的标题 |
| `preview` | 审查预览，不等同于最终 prompt |
| `status` | `system / canonical / working / candidate / mixed / unknown` |
| `activation_reason` | 本段为什么被选入 |
| `sources` | 来源摘要，包含 `type/id/label/status` |
| `can_exclude` | 本次操作是否允许排除 |
| `excluded` | 是否已被排除 |
| `truncated_reason` | 被预算裁剪时的原因 |

`enforce_budget()` 除了保留 `evicted_keys` 和 `truncated_keys`，还会生成 `budget_events`。前端据此显示“已裁剪 / 已移除”、裁剪前后 token 和原因。被 evict 的 section 不返回正文，但保留事件；被 truncate 的 section 返回裁剪后的正文。

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

确认弹窗展示的是结构化参考资料清单，不展示 raw Markdown textarea，也不允许用户直接编辑最终 prompt。用户确认的是“本次 AI 调用可参考哪些 section、哪些 section 被裁剪、哪些来源被激活”，不是直接确认一段 prompt 文本。

`POST /api/context/confirm` 会落库一条 `context_confirmations`，并在响应中返回本次编译的 `sections` 和 `budget_events` 供前端展示。这些展示详情不持久化；持久化仍只保存 `selected_asset_ids`、`compile_options`、`warnings`、`result_refs`、`stale_reasons` 等摘要。

### Section 级排除

V1 复用 `excluded_asset_ids`，新增约定：

```json
{
  "excluded_asset_ids": {
    "context_sections": ["retrieval_evidence_packs", "style_assets"],
    "manual": ["asset-id-1"]
  }
}
```

- `context_sections` 是本次 AI 操作临时排除的 section key，不写入长期偏好。
- `manual` 保留给既有“排除资产 ID”输入。
- P0 section 不可排除。尝试排除 `writing_objective`、`scene_blueprint` 或硬约束类 section 时，后端忽略并返回 `核心参考资料不可排除：<key>` warning。
- `selected_asset_ids.context_sections` 记录最终参与编译且未被排除的 section key。
- V1 只做 section 级控制，不做 item/entity 级事实编辑；实体、人物、地点级控制继续走既有 ID 参数。

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
- 不提供完整上下文预设系统、作者长期偏好配置或 item 级事实编辑
