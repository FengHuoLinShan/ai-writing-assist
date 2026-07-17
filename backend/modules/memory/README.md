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

`memory_events` 使用 `(novel_id, chapter_index, sequence)` 作为章内幂等键。重建某章事件时，`MemoryService.record_events` 通过仓储层逐条 upsert 并清理新事件流之外的尾部事件，避免并发 delete-then-insert 交错。

全景重放优先从最近快照开始，只对后续事件做 keyset 分页增量应用；快照事件数和重建终点使用聚合查询计算，避免大世界长章节范围一次性加载全部 `memory_events`。
事件列表同样使用稳定 `(chapter_index, sequence, id)` keyset 分批读取，
`total` 由 SQL 聚合计算，保持现有 API 返回形状。DeltaLog 的 deep-import workflow
计数与回滚在数据库中先按 `novel_id + source + workflow_id + auto_ingested +
rolled_back` 过滤；回滚再按 ID keyset 分批加锁更新，不扫描其他 workflow 或项目。

从 `from_chapter` 重建时，该项目范围内原 `current` 快照会转为 `stale`，
再生成新 `current` 快照；旧快照作为历史保留，不在重建中硬删除。重建终点继续通过
`MAX(chapter_index)` 聚合 seam 获取，不全量加载事件。普通 capture 和重建共用同章
supersede 语义：写入新 `current` 前先把同项目、同章节旧 `current` 转为 `stale`；
PostgreSQL 以事务级 advisory lock 串行化该章节的并发 capture。
`GET .../status` 中的 `has_stale` 只表示存在需要重建的章节：该章有 `stale`
且没有同章 `current` 替代。已被新快照正常取代的历史 `stale` 仍保留用于审计，
但不再把整个项目误报为待重建。

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

以上全部入口都在读取、快照写入或重建前通过 project facade 校验 active
project。不存在与回收站项目统一返回 404，不暴露其 memory 记录。

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
