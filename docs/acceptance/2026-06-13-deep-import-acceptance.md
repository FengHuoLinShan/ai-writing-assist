# 深度导入流水线真实 LLM 验收记录

**日期**: 2026-06-13
**项目**: 《诡秘之主 第一部》
**章节范围**: 第 1-3 章
**执行命令**: `cd backend && python scripts/acceptance_deep_import.py`

## 验收结果

- **状态**: 通过
- **Workflow phase**: `done`
- **Degraded**: `False`
- **Completed steps**:
  1. `scene_segmentation`
  2. `entity_extraction`
  3. `structure_analysis`

## 生成资产数量

| 资产类型 | 数量 |
|---|---|
| scenes | 1 |
| entities | 10 |
| relations | 6 |
| delta_logs | 0 |
| memory_snapshots | 2 |
| plot_threads | 3 |
| outline_arcs | 1 |
| foreshadowing_plans | 3 |
| reveal_plans | 2 |

## 关键约束验证

- 使用真实 LLM（DeepSeek `deepseek-v4-flash`），未使用 mock。
- 自动写入的对象标记为 `canonical`，且 `content_json._meta.auto_ingested=true`。
- 所有派生数据均属于目标 `novel_id`，未跨项目泄漏。
- Phase 1 按 5 章/批 + 1 章 overlap 策略处理，1-3 章作为单批执行。
- Phase 2 按 Scene 串行提取实体与关系，每个 Scene 完成后更新记忆快照。
- Phase 3 生成剧情线、篇章纲、伏笔和揭示计划。

## 备注

- `delta_logs` 为 0 是因为本次 LLM 输出未包含 `delta_events`，符合 schema 可选设计；流水线未因此失败。
- embedding 调用返回 404（DeepSeek 不支持 embeddings 端点），实体去重回退到 ILIKE，不影响实体/关系写入。
