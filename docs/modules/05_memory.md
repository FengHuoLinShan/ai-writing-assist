# Module: memory / 长期记忆模块

## 定位

memory 模块负责小说世界变化的记录与回溯。采用事件溯源模式，每章正文写入时记录 MemoryEvent（真相源），每 10 章物化 MemorySnapshot 加速全景查询。

DeltaLog 记录实体结构化字段的 before/after 变更，用于版本回滚和 Context Compiler 的 Delta Timeline 输入。

## 数据表

| 表 | 职责 |
|----|------|
| `memory_events` | 记忆变化事件 — 每章写入时记录，重放可得任意章的世界全景 |
| `memory_snapshots` | 记忆阶段性快照 — 每 10 章物化，加速全景查询 |
| `delta_log` | 实体变更日志 — 记录每次结构化字段的 before/after |

## Services

- **MemoryService** — 全景查询 / 事件列表 / 实体时间线 / 快照管理 / 全量重建

## API

```
GET    /api/novels/{novel_id}/memories/panorama         # 获取指定章节的世界全景
GET    /api/novels/{novel_id}/memories/events            # 查询事件列表（按章节范围过滤）
GET    /api/novels/{novel_id}/memories/events/{entity_id}/timeline  # 单个实体的变化时间线
POST   /api/novels/{novel_id}/memories/snapshots/capture # 手动生成快照
GET    /api/novels/{novel_id}/memories/snapshots         # 列出所有快照
POST   /api/novels/{novel_id}/memories/rebuild           # 从前文修正点全量重建后续事件和快照
GET    /api/novels/{novel_id}/memories/status            # memory 模块当前状态
```

## 核心数据模型

### MemoryEvent（记忆变化事件）

```python
class MemoryEvent(Base):
    __tablename__ = "memory_events"

    chapter_index: int         # 所属章节
    sequence: int              # 章内事件顺序
    event_type: str            # 事件类型（如 entity_created, relationship_changed 等）
    entity_id: UUID | None     # 影响的实体 ID
    entity_type: str | None    # 实体类型
    snapshot_before: dict      # 变化前状态 JSON
    snapshot_after: dict       # 变化后状态 JSON
    source: str                # ai_extraction / manual_edit
```

### MemorySnapshot（记忆快照）

```python
class MemorySnapshot(Base):
    __tablename__ = "memory_snapshots"

    chapter_index: int         # 快照对应章节
    status: str                # current / stale
    full_state: dict           # 完整世界状态 JSON
    events_until: int | None   # 覆盖到第几个事件序号
```

### DeltaLog（变更日志）

```python
class DeltaLog(Base, UUIDMixin, NovelMixin):
    __tablename__ = "delta_log"

    entity_id: UUID | None     # 关联实体 ID
    character_id: UUID | None  # 关联网格人物 ID
    scene_index: int | None    # 变更发生的 Scene
    category: str              # 变更类别
    field_path: str | None     # 变更字段路径
    old_value: str | None      # 变更前的值
    new_value: str | None      # 变更后的值
    source: str                # ai_extraction / manual_edit / manual_rollback
    meta: dict                 # 扩展元数据
```

### DeltaLog category 枚举

```
CHARACTER_PROPERTY    — 角色属性变更
RELATIONSHIP          — 关系差分
GLOBAL_PLOT_LINE      — 全局线索变更
CHARACTER_KNOWLEDGE   — 角色知识边界变更
ENTITY_CREATED        — 新实体创建
ENTITY_UPDATED        — 实体字段更新
ENTITY_MERGED         — 实体合并
MANUAL_ROLLBACK       — 用户手动回滚
```

## 设计要点

- MemoryEvent 是变更真相源，所有基于事件的推导从这里出发
- Snapshot 每 10 章物化一次，加速全景查询（避免全量事件重放）
- DeltaLog 在 Scene 内坍缩后写入（同一 Scene 内同一字段多次变更只保留最终状态）
- Context Compiler 的 Delta Timeline 段直接读 DeltaLog
- 版本回滚：结构化字段通过 Delta Log 逆向重放，文本字段从 Text Archive 查询快照
