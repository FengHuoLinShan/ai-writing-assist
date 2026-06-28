# Module: context / 上下文编译模块

## 定位

context 模块决定本次 AI 操作能看到哪些资料、哪些资料要被裁剪，以及哪些确认记录需要在资产变化后标脏。

RAG 负责“找”，context 负责“选、裁、确认、追踪”。

## 职责

- 按需聚合 `project / world / memory / outline / rag`
- 基于 `scope`、`scene_id`、`budget_tokens`、`reveal_mode` 进行裁剪
- 输出兼容 bundle 或分层 `CompiledContext`
- 手动 AI 操作前创建 `context_confirmations`
- 在任务完成后把结果引用回写到确认记录
- 在资产变化后把历史确认记录标记为 stale

## 不负责

- 不直接执行 LLM 调用
- 不直接做 RAG 检索算法
- 不做剧情推理
- 不保存完整 Markdown 快照，只保存可重编译摘要

## 核心 facade

```python
async def compile_structure_context(...) -> StructureContextBundle
async def compile_with_tiers(...) -> CompiledContext
async def render_compiled_context_markdown(...) -> str
async def confirm_context(...) -> ContextConfirmationContract
async def require_confirmation(...) -> ContextConfirmationContract
async def attach_result_ref(...) -> ContextConfirmationContract
async def mark_asset_context_changed(...) -> int
```

## 数据表

| 表 | 说明 |
|----|------|
| `context_confirmations` | AI 参考资料确认记录，保存 `action`、`scope`、`context_mode`、`selected_asset_ids`、`result_refs`、`stale_reasons` |

## 主要选项

| 选项 | 含义 |
|------|------|
| `scope` | `project / world / world_character / arc / chapter / full` |
| `scene_id` | Scene-centric 编译入口 |
| `context_mode` | `canonical` 或 `working` |
| `include_pending_objects` | 是否纳入待确认对象 |
| `reveal_mode` | `author_safe / author_full / reader / character` |
| `budget_tokens` | 总预算，前端默认 4000 |

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
