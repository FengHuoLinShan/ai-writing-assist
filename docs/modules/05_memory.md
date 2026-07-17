# Module: memory / 长期记忆模块

## 定位

memory 模块维护小说世界的“变化历史”，不是再存一份正史对象库。

当前实现采用事件溯源：

- `memory_events` 记录每章产生的变化事件，是真相源
- `memory_snapshots` 记录阶段性全景快照，用于快速查询
- `delta_log` 记录结构化字段的 before/after 差分，服务于导入分析、调试和回滚
- `memory_events` 的章内幂等键是 `(novel_id, chapter_index, sequence)`；单章重建事件流走 upsert，不再依赖全量删除后插入。
- 快照 `stale` 同时保留被同章新 `current` 取代的历史版本；状态接口只把“没有同章 current 替代”的 stale 视为待重建，避免历史审计记录造成持续脏状态误报。

## 职责

- 按章节查询世界全景 `panorama`
- 列出指定章节范围内的变化事件
- 查询单个实体的变化时间线
- 生成和列出记忆快照
- 在用户修正前文后，从指定章节开始重建后续事件和快照

## 数据表

| 表 | 说明 |
|----|------|
| `memory_events` | 每章的变化事件流，字段含 `chapter_index`、`sequence`、`event_type`、`snapshot_before`、`snapshot_after` |
| `memory_snapshots` | 阶段性全景快照，字段含 `chapter_index`、`full_state`、`events_until` |
| `delta_log` | 结构化字段变更审计，字段含 `scene_index`、`category`、`field_path`、`old_value`、`new_value` |

## 服务与对外入口

- `MemoryService`：全景查询、事件列表、实体时间线、快照管理、重建
- `facade.get_memory_panorama()`：跨模块读取某章全景
- `facade.get_continuity_evidence_for_writing()`：给写作冲突检查提供上一章角色位置证据和 `memory_chapter` 打开目标
- `facade.capture_snapshot()`：跨模块手动生成快照
- `facade.create_delta_log()`：跨模块写入结构化差分

## API

```http
GET  /api/novels/{novel_id}/memories/panorama
GET  /api/novels/{novel_id}/memories/events
GET  /api/novels/{novel_id}/memories/events/{entity_id}/timeline
POST /api/novels/{novel_id}/memories/snapshots/capture
GET  /api/novels/{novel_id}/memories/snapshots
POST /api/novels/{novel_id}/memories/rebuild
GET  /api/novels/{novel_id}/memories/status
```

查询参数要点：

- `panorama` 需要 `chapter_index`
- `events` 支持 `from_chapter` / `to_chapter`
- `timeline` 支持 `skip` / `limit`
- `rebuild` 需要 `from_chapter`

## 设计要点

- memory 不维护旧版 `memory_records` 或 `memory_update_proposals`
- `panorama` 是由事件流和快照重放得到的“某章世界状态视图”；快照后的增量事件按 `(chapter_index, sequence, id)` keyset 分页应用，避免大世界范围重放一次性加载全部事件
- 快照 `events_until` 和手动重建终点使用聚合查询计算，显式事件列表查询仍保留按章节范围返回完整列表的 API 语义
- `delta_log` 不是单独模块，而是 memory 提供给 world/imports/context 使用的结构化差分设施
- 文本字段回滚依赖 `world.text_archive`；memory 主要负责事件和差分历史

## 测试

```bash
cd backend
pytest modules/memory/tests/ -v
```
