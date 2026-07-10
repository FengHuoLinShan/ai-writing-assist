# Module: context / 上下文编译模块

## 定位

context 模块决定本次 AI 操作能看到哪些资料、哪些资料要被裁剪，以及哪些确认记录需要在资产变化后标脏。

RAG 负责“找”，context 负责“选、裁、确认、追踪”。

## 职责

- 按需聚合 `project / world / memory / outline / rag`
- 基于 `scope`、`scene_id`、`budget_tokens`、`reveal_mode` 进行裁剪
- 输出兼容 bundle 或分层 `CompiledContext`
- 手动 AI 操作前创建 `context_confirmations`
- 为自动 AI 流水线创建 `context_snapshots` 审计记录
- 在任务完成后把结果引用回写到确认记录
- 在资产变化后把历史确认记录标记为 stale
- 为前端 AI 参考资料审查台返回 section 元数据、激活原因、来源摘要和预算裁剪事件

## 不负责

- 不直接执行 LLM 调用
- 不直接做 RAG 检索算法
- 不做剧情推理
- 不默认保存完整 Markdown；完整 `rendered_context` 只能由调用方显式开启并受保留策略清理
- 不让用户直接编辑最终 prompt；用户确认的是结构化参考资料清单

## 核心 facade

```python
async def compile_structure_context(...) -> StructureContextBundle
async def compile_with_tiers(...) -> CompiledContext
async def render_compiled_context_markdown(...) -> str
async def confirm_context(...) -> ContextConfirmationContract
async def require_confirmation(...) -> ContextConfirmationContract
async def require_fresh_confirmation(...) -> ContextConfirmationContract
async def attach_result_ref(...) -> ContextConfirmationContract
async def mark_asset_context_changed(...) -> int
async def open_context_snapshot(db, request: ContextSnapshotRequest) -> ContextSnapshotContract
async def succeed_context_snapshot(...) -> ContextSnapshotContract
async def fail_context_snapshot(...) -> ContextSnapshotContract
async def build_snapshot_health_summary(...) -> dict
async def mark_stale_running_snapshots(...) -> int
async def prune_rendered_context(...) -> int
async def run_snapshot_maintenance(...) -> dict
async def grep_novel_evidence(...) -> dict
async def search_novel_evidence(...) -> dict
async def read_novel_evidence(...) -> dict
async def inspect_novel_target(...) -> dict
async def trace_novel_evidence(...) -> dict
async def record_evidence_link(...) -> EvidenceLinkContract
```

`create_context_snapshot()`、`mark_context_snapshot_succeeded()` 和
`mark_context_snapshot_failed()` 保留为兼容 wrapper；新生产调用应使用
`ContextSnapshotRequest` + `open/succeed/fail` 生命周期入口。

## 数据表

| 表 | 说明 |
|----|------|
| `context_confirmations` | AI 参考资料确认记录，保存 `action`、`scope`、`context_mode`、`selected_asset_ids`、`result_refs`、`stale_reasons` |
| `context_snapshots` | 自动 AI 调用上下文审计记录，保存 `task_id`、`workflow_id`、`phase`、`context_mode`、`included_asset_ids`、摘要、`prompt_hash`、token/section metadata、`result_refs`、错误信息和可选 `rendered_context` |
| `evidence_links` | 使用 `TargetRef + claim_path` 将对象/人物知识/结构字段连到 `SourceRangeRef`；只记录 provenance，不判定事实真假 |

`context_confirmations` 和 `context_snapshots` 是两套语义：

- `context_confirmations` 面向手动 AI 操作，表示用户确认过的参考资料选择。
- `context_snapshots` 面向自动流水线审计，表示一次真实 LLM 调用使用过的上下文视图。

默认只保存可复现摘要和 metadata；`retain_rendered_context=True` 时才保存完整上下文并设置过期时间。清理任务只清空 `rendered_context` 和 `rendered_context_expires_at`，不删除快照行、hash、资产 ID、结果引用或 metadata。

## AI 参考资料审查台

手动 AI 操作的确认弹窗使用 `CompiledContext` 作为中间表示：

```text
Loader 聚合业务资料
  -> ContextCompiler 生成 ContextSection IR
  -> enforce_budget 记录 evicted/truncated budget_events
  -> API 返回 sections + selected_asset_ids + warnings
  -> 前端渲染“参考资料清单”，而不是 raw Markdown
```

`ContextSection` 除了 `key/tier/content/token_count` 外，还包含面向审查台的只读字段：

- `title`：作者可读标题，例如“本次任务”“当前 Scene”“RAG 证据包”
- `preview`：审查用预览，不替代真正送入 LLM 的 section 内容
- `status`：`system / canonical / working / candidate / mixed / unknown`
- `activation_reason`：本段被激活的原因，例如当前 `scene_id`、章节范围或 RAG 命中
- `sources`：来源摘要，包含 `type/id/label/status`
- `can_exclude` 与 `excluded`：本次操作是否允许排除、是否已排除
- `truncated_reason`：预算裁剪原因

`reader` 编译使用独立的最小 section 路径：只保留用户任务、
ReaderRevealPolicy/公开基线允许的世界信息、从 writing 回读且 hash
校验通过的正文证据和不含剧情事实的项目风格。完整 Scene 卡、
剧情线、记忆、篇章纲和未过滤的动态约束不进入 reader `CompiledContext`。

`budget_events` 记录预算执行过程，包含 `section_key`、`event_type`、`reason`、`before_tokens`、`after_tokens`、`tier`。被 evict 的 section 不再返回正文，但会通过 `budget_events` 告知前端“已移除”；被 truncate 的 section 保留裁剪后的正文和裁剪原因。

`context_confirmations` 仍只持久化摘要字段：`selected_asset_ids`、`compile_options`、`warnings`、`result_refs`、`stale_reasons` 等。`sections` 和 `budget_events` 是本次编译的实时展示结果，不写入确认记录。

### Section 级排除

V1 复用 `excluded_asset_ids`，约定：

```json
{
  "excluded_asset_ids": {
    "context_sections": ["retrieval_evidence_packs", "style_assets"],
    "manual": ["asset-id-1"]
  }
}
```

- `excluded_asset_ids.context_sections` 表示本次 AI 操作临时排除的 section key。
- P0 section 不可排除，包括 `writing_objective`、`scene_blueprint` 和硬约束类 section。用户尝试排除时后端忽略，并返回 `核心参考资料不可排除：<key>` warning。
- `selected_asset_ids.context_sections` 记录最终参与编译且未被排除的 section key。
- `manual` 保留给既有资产 ID 排除输入，V1 不把它解释为 section key。
- V1 只支持 section 级控制，不做 item/entity 级事实编辑；更细粒度排除继续使用现有实体、人物、地点 ID 参数。

## Loader 依赖注入

`ContextCompiler` 的外部行为由 `SCOPE_LOADERS`、loader `name` 和 facade 入口保持稳定；loader 内部依赖统一通过构造函数注入 callable。生产默认 callable 仍委托既有 `project / world / memory / outline / rag` 稳定入口，测试可直接传入 fake callable，不需要在 `load()` 内 monkeypatch facade 或直接访问 DI container。

`load()` 只使用 `self._...` 依赖：

- `ProjectLoader(get_project_context_fn=...)`
- `WorldEntitiesLoader(get_world_context_fn=...)`
- `CharactersLoader(get_characters_context_fn=..., filter_context_by_character_knowledge_fn=..., get_scene_contract_fn=...)`
- `EventsLoader(get_events_context_fn=...)`
- `MemoryRecordsLoader(get_memory_panorama_fn=...)`
- `RagChunksLoader(retrieve_fn=...)`
- `SceneLoader(get_scene_contract_fn=...)`
- `PlotThreadsLoader(get_active_threads_fn=...)`
- `OutlineArcLoader(get_arc_by_chapter_fn=...)`

`RagChunksLoader` 会把 `CompileOptions.visible_until_chapter` 传给 RAG 的
`visible_until_chapter` 硬过滤；当该字段为空且存在 `chapter_index` 时，默认用当前章
作为读者进度上界。范围型上下文（例如深度导入 Phase 3 结构生成）必须显式传入范围
结束章，避免只用起始章过度过滤后续证据。`reference_chapter_index` 仍只作为 RAG
时间衰减评分 hint。

RAG loader 不会直接把 chunk text 视为事实。它按 `source_id` 从 writing 重读
当前原文、校验 source hash，然后才生成 section 的 source refs/hash metadata；
过期块被丢弃并返回降级警告。

## 小说证据服务与可见性

`NovelEvidenceService` 在 context 内集中编排 writing、RAG、outline 和 world，
对外只暴露确定性 grep/search/read/inspect/trace，不是自主选择工具的 Agent。

`VisibilityContextContract` 有三种模式：

- `author`：无剧透截止。
- `reader`：必须有 `cutoff_chapter`，可选同章 `cutoff_scene_id/cutoff_offset`。
- `character`：除上述截止外必须有 `character_id`。

writing、RAG、SceneSpan/checkpoint、ReaderRevealPolicy 和 CharacterKnowledge 各层先过滤，
context 在返回前再校验来源位置。CharacterKnowledge 只在学习位置严格早于
截止章时生效；同章无顺序、缺少章且未标记 `is_public_baseline` 的旧数据默认排除并告警。
编译和对象检查会明示这类保守降级；inspect/trace 还会从 writing
回读 evidence link，伪造或失效引用不计入证据，并返回 `index_fresh=false`。

深度导入只在 schema 校验通过且 quote 能唯一定位到当前可见原文时，在事实写入同一
savepoint 记录 active evidence link。无法定位时只记 `needs_review` 与原因，
不伪造 offset/source ref。

```http
POST /api/context/evidence/grep
POST /api/context/evidence/search
POST /api/context/evidence/read
POST /api/context/evidence/inspect
POST /api/context/evidence/trace
```

## Deep Import Activation

`prepare_import_context_activation()` 是 Phase 2a 的唯一跨模块预检入口。它通过
outline facade 获取当前 Scene 与最多两个前序 brief，通过 world facade 获取派生世界
背景，并读取当前 Scene 在可见截止章/offset 以前的精确正文范围。后续
Scene 和跨章 Scene 中越过截止的 span 永不进入该 activation；Phase 2b
别名/关系对账保留全局证据语义。activation、预算事件和来源摘要写入 context snapshot
metadata，不产生正史事实。

## 快照生命周期维护

`context_snapshots` 的生命周期治理由 context 模块拥有，入口是 facade 和只读/维护 API：

生产代码通过 `open_context_snapshot()` 打开 running 快照，通过
`succeed_context_snapshot()` / `fail_context_snapshot()` 完成生命周期标记。宽参数
`create_context_snapshot()` 仅用于兼容旧调用。

```http
GET  /api/context/snapshots?novel_id=...&workflow_id=...
GET  /api/context/snapshots/{snapshot_id}?novel_id=...
POST /api/context/snapshots/maintenance
```

维护 API 默认 `dry_run=true`，只返回会变更的数量；调用方必须显式传 `dry_run=false` 才会修改数据库。请求字段包括：

- `novel_id` 必填
- `workflow_id` 可选
- `running_timeout_minutes` 默认 120
- `prune_rendered_context` 默认 true
- `retain_latest_full_context_per_project` 默认 200
- `dry_run` 默认 true

维护规则：

- 超时 `running` 快照会在执行模式下转为 `status="failed"`、`error_kind="stale_running"`。
- 完整 `rendered_context` 按过期时间和每项目最近保留上限清理。
- 维护不改 `result_refs`、hash、asset ids、section/token metadata 或快照行本身。

`SnapshotHealthSummary` 是轻量聚合，只包含数量、状态/phase 分布、超时 running、保留 full context 数和最近失败摘要；不返回完整 prompt、`rendered_context` 或完整 result refs。

## 主要选项

| 选项 | 含义 |
|------|------|
| `scope` | `project / world / world_character / arc / chapter / full` |
| `scene_id` | Scene-centric 编译入口 |
| `context_mode` | `canonical` 或 `working` |
| `content_mode` | 正文事实源和 RAG 索引视图：`canonical` / `working` |
| `include_pending_objects` | 是否纳入待确认对象 |
| `reveal_mode` | `author_safe / author_full / reader / character` |
| `visible_until_chapter` | RAG 读者进度上界；为空时单章上下文默认使用 `chapter_index` |
| `visible_until_scene_id/visible_until_offset` | 可选同章 Scene/字符截止点 |
| `budget_tokens` | 总预算，前端默认 4000 |
| `excluded_asset_ids.context_sections` | 本次临时排除的可选 context section key |

## 兼容字段说明

`StructureContextBundle` 里仍保留一些旧字段名：

- `memory_records`
- `timeline_events`
- `geo_locations`

这些名字主要是兼容现有渲染器和测试，不表示系统仍存在同名业务模块或数据表。

## 测试

```bash
cd backend
pytest modules/context/tests/ -v
```
