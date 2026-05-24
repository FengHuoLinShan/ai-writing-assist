# Module: timeline / 轻量时间线模块

## 定位

timeline 模块负责事件顺序和剧情防错。它不是复杂时间推理系统，也不是历史模拟器。

回答的问题：
- 哪些事件已经发生？
- 发生顺序是什么？
- 事件位于哪章或哪个阶段？
- 读者是否知道？
- 哪些角色知道？
- 当前结构是否提前发生或提前揭示？

## 核心原则

- 事件通过 `order_index` 排序（绝对值，非章节内顺序）
- AI 生成的事件先进入 `candidate` 状态
- 用户确认后才进入 `canonical` 正史

## 数据表

| 表名 | 用途 |
|------|------|
| `timeline_events` | 正史时间线事件 |

### timeline_events 核心字段

- `order_index` — 事件顺序索引（必填，唯一排序依据）
- `chapter_index` — 所属章节索引（可选，用于章节关联）
- `title` / `summary` — 事件信息
- `event_type` — 事件类型
- `related_*_ids` — 关联的角色、对象、剧情线、地点
- `geo_effects` — 地理影响（JSONB 数组）
- `visibility` — 读者可见性
- `known_by_character_ids` — 已知该事件的角色
- `status` — candidate / canonical / deprecated

## 对外契约（contracts.py）

```python
@dataclass(frozen=True)
class TimelineEventContract:
    id: str
    title: str
    summary: str
    order_index: int
    chapter_index: int | None
    event_type: str | None
    related_character_ids: list[str]
    related_entity_ids: list[str]
    related_thread_ids: list[str]
    related_location_ids: list[str]
    geo_effects: list[dict]
    visibility: str
    known_by_character_ids: list[str]

@dataclass(frozen=True)
class TimelineConflictWarningContract:
    type: str
    description: str
    severity: str
    source_event_ids: list[str]
    suggestion: str | None
```

## Facade（facade.py）

```python
async def get_relevant_timeline_context(db, novel_id, chapter_index=None, related_entity_ids=None, character_id=None, limit=12) -> list[TimelineEventContext]
async def check_timeline_conflicts(db, novel_id, structure_candidate) -> list[TimelineConflictWarning]
```

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/novels/{novel_id}/timeline/events` | 创建事件 |
| GET | `/api/novels/{novel_id}/timeline/events` | 事件列表 |
| GET | `/api/novels/{novel_id}/timeline/events/{id}` | 事件详情 |
| PUT | `/api/novels/{novel_id}/timeline/events/{id}` | 更新事件 |
| DELETE | `/api/novels/{novel_id}/timeline/events/{id}` | 删除事件 |

## 冲突检查维度

`check_timeline_conflicts` 检查：

1. **顺序矛盾** — 候选事件的 order_index 在已有事件之后，但 chapter_index 却在之前
2. **事件重复** — 标题相同或高度重叠
3. **角色位置冲突** — 同一角色在同一章节出现在不同地点

## 测试方式

```bash
cd backend
python -m pytest modules/timeline/tests/ -v
```

## 依赖

- `core.base` — Base ORM、UUIDMixin、NovelMixin、TimestampMixin
- `core.database` — 数据库连接
- `core.dependencies` — DbSession
- `shared.enums` — EventType 等枚举
- `shared.types` — 类型别名
- `shared.constants` — 分页常量

## 不做

- TimelineAnchor（时间锚点）
- 相对时间归一化
- 复杂因果链
- 日历系统
- 精确日期推理
- 自动历史推演
