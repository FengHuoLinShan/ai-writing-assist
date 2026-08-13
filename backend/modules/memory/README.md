# Module: memory / 长期记忆模块

## 定位

memory 模块维护世界状态变化历史，而不是维护另一份正史对象库。

## 负责

- 记录带 Scene 锚点的 `memory_events`
- 生成与读取 `memory_snapshots`
- 提供实体时间线查询
- 从指定章节开始重建记忆事件和快照
- 通过 facade 提供全景与类型化差分写入口

## 数据表

| 表 | 说明 |
|----|------|
| `memory_events` | 每章事件流 |
| `memory_snapshots` | 阶段性全景快照 |
| `memory_scene_checkpoints` | 每个 Scene 结束后的分维度轻量状态与覆盖缺口 |
| `memory_scene_snapshots` | stage0、周期、章末和 latest 的稀疏全量 Scene 快照 |
| `delta_log` | 结构化字段差分日志 |

`memory_events` 使用 `(novel_id, chapter_index, sequence)` 作为章内幂等键。重建某章事件时，`MemoryService.record_events` 通过仓储层逐条 upsert 并清理新事件流之外的尾部事件，避免并发 delete-then-insert 交错。

新写入同时以 `scene_id / scene_index / scene_sequence / dimension` 固定 Scene
原子阶段。Scene 阶段从 stage0 空状态开始，只重放该 Scene 及之前的 MemoryEvent；
Scene 时点状态的稳定维度固定为 `entities`、`relations`、`locations`、`knowledge`；
AI 地图册不属于 Scene memory。
缺少 Scene 锚点的旧事件会形成分维度 coverage gap，
不得回退读取当前 World。系统定向重试后仍不能覆盖时进入人工修复。人工修复只 supersede
同 Scene、同维度、system-generated 的当前版本，manual / confirmed 版本始终保留，并从
该点重建后续系统投影。

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
GET  /api/novels/{novel_id}/memories/scene-checkpoints?scene_id=...
POST /api/novels/{novel_id}/memories/scene-checkpoints/ensure
POST /api/novels/{novel_id}/memories/scene-checkpoints/rebuild
POST /api/novels/{novel_id}/memories/scene-checkpoints/repair
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
async def replace_scene_memory_events(
    db, novel_id, *, scene_id, scene_index, chapter_index, events
)
async def create_delta_log(db, novel_id, **kwargs)
async def ensure_scene_checkpoints(db, novel_id, scene_id)
async def get_scene_checkpoints(db, novel_id, scene_id)
```

`get_continuity_evidence_for_writing(...)` 返回写作冲突检查可消费的上一章角色位置证据；它只暴露来源摘要和 `memory_chapter` 打开目标，不要求 writing 读取 memory 内部事件结构。

`ingest_delta_events(...)` 是 deep-import 等跨模块批量写入 `delta_log` 的稳定入口。
调用方传入 `MemoryDeltaEventIngest`，由 `MemoryService` 统一处理 JSON 编码、
provenance 合并、`auto_ingested=True`、DeltaLog row creation 和可选
`result_refs` 回填。`create_delta_log(...)` 保留为兼容 shim，不再作为 imports
等新调用点的首选接口。

Scene 重提即使返回零 Delta，imports 也会通过
`replace_scene_memory_events(...)` 显式清空该 Scene 旧事件流。任何 Scene
事件流变更都会先使该点及后续系统 checkpoint / 稀疏快照失效，
避免修正后继续读取旧投影。

人工修复请求必须带上页面当前展示的 `expected_checkpoint_id`。
并发重建已更换 checkpoint 时返回 409，要求用户先重读新事实与证据，
不会把旧页面的决定套用到新版本。对无 Scene 锚点事实的人工确认
会作为显式 coverage boundary 传递给所有后续系统 checkpoint；新增未锚定
事实仍会再次 fail closed。

context 只在带 Scene 的角色视角正文生成确认中消费这份投影。它会调用
`ensure_scene_checkpoints()`，但不改变 memory 对事件、coverage 和人工修复的所有权；
当前 World 对象只用来向作者指出未锚定项，不会回写 checkpoint 或填充历史空白。

Facade 只保留跨模块稳定函数名和返回形状；`delta_log` 写入、deep-import 统计和
provenance 规则由 `MemoryService` 拥有，避免 facade 直接持有 ORM 业务逻辑。

## 测试

```bash
cd backend
pytest modules/memory/tests/ -v
```
