# Module: timeline / 轻量时间线模块

## 定位

timeline 模块负责事件顺序和剧情防错。不是复杂时间推理系统。

## 数据表

- timeline_events — order_index / chapter_index / title / summary / event_type / visibility / known_by_character_ids / related_* JSONB

## Facade

```python
async def get_relevant_timeline_context(db, novel_id, chapter_index=None, related_entity_ids=None, character_id=None, limit=12, reveal_mode="author_safe") -> list[TimelineEventContext]
async def get_geo_effects_up_to_chapter(db, novel_id, chapter_index) -> list[dict]
async def check_timeline_conflicts(db, novel_id, structure_candidate) -> list[TimelineConflictWarning]
```

## API

```
GET    /api/novels/{nid}/timeline/events
POST   /api/novels/{nid}/timeline/events
PUT    /api/novels/{nid}/timeline/events/{eid}
DELETE /api/novels/{nid}/timeline/events/{eid}
```

## 不做

- TimelineAnchor
- 相对时间归一化 / 日历系统 / 精确日期推理
- 复杂因果链 / 自动历史推演
