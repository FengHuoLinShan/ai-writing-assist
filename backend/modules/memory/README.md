# Module: memory / 长期记忆模块

## 定位

memory 模块维护世界状态变化历史，而不是维护另一份正史对象库。

## 负责

- 记录 `memory_events`
- 生成与读取 `memory_snapshots`
- 提供实体时间线查询
- 从指定章节开始重建记忆事件和快照
- 通过 facade 提供全景与类型化差分写入口

## 数据表

| 表 | 说明 |
|----|------|
| `memory_events` | 每章事件流 |
| `memory_snapshots` | 阶段性全景快照 |
| `delta_log` | 结构化字段差分日志 |

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

## Facade

```python
async def get_memory_panorama(db, novel_id, chapter_index)
async def get_continuity_evidence_for_writing(
    db,
    novel_id,
    chapter_index,
    *,
    pov_character_id,
    current_location_id,
    current_location_name=None,
)
async def capture_snapshot(db, novel_id, chapter_index)
async def ingest_delta_events(db, novel_id, events, *, result_refs=None)
async def create_delta_log(db, novel_id, **kwargs)
```

`get_continuity_evidence_for_writing(...)` 返回写作冲突检查可消费的上一章角色位置证据；它只暴露来源摘要和 `memory_chapter` 打开目标，不要求 writing 读取 memory 内部事件结构。

`ingest_delta_events(...)` 是 deep-import 等跨模块批量写入 `delta_log` 的稳定入口。
调用方传入 `MemoryDeltaEventIngest`，由 `MemoryService` 统一处理 JSON 编码、
provenance 合并、`auto_ingested=True`、DeltaLog row creation 和可选
`result_refs` 回填。`create_delta_log(...)` 保留为兼容 shim，不再作为 imports
等新调用点的首选接口。

Facade 只保留跨模块稳定函数名和返回形状；`delta_log` 写入、deep-import 统计和
provenance 规则由 `MemoryService` 拥有，避免 facade 直接持有 ORM 业务逻辑。

## 测试

```bash
cd backend
pytest modules/memory/tests/ -v
```
