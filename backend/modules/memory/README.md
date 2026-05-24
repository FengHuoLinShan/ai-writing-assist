# Module: memory / 长期记忆模块

## 定位

memory 模块维护小说推进过程中的状态变化历史。它不是聊天记忆，也不是向量库。
它记录"发生了什么变化"，而非"当前是什么状态"。

- World / Character / Outline 是**当前状态**
- Memory 是**状态变化历史**

## 核心原则

- AI 只生成 proposal（`memory_update_proposals`）
- 用户确认后才写入 canonical memory（`memory_records`）
- 候选先行：所有 AI 输出先进入 proposal，经用户确认才入正史

## 数据表

| 表名 | 用途 |
|------|------|
| `memory_records` | 正史长期记忆记录 |
| `memory_update_proposals` | AI 生成的候选记忆，待用户确认 |

### memory_records 核心字段

- `memory_type` — 记忆类型：chapter_state / event / character_state / knowledge / foreshadowing / resource / outline_drift / geo_history
- `chapter_index` — 所属章节索引
- `summary` — 记忆摘要（必填）
- `content_json` — 详细结构化内容
- `visibility` — 读者可见性
- `known_by_character_ids` — 已知该记忆的角色
- `related_*_ids` — 关联的对象、角色、剧情线
- `importance` — 重要性（0.0 ~ 1.0）
- `status` — canonical / deprecated

### memory_update_proposals 核心字段

- `proposal_type` — 提案类型
- `payload` — 提案内容（JSONB，确认后据此创建 memory_records）
- `confidence` — AI 置信度
- `decision` — pending / approved / rejected

## 对外契约（contracts.py）

```python
@dataclass(frozen=True)
class MemoryRecordContract:
    id: str
    memory_type: str
    chapter_index: int | None
    title: str | None
    summary: str
    visibility: str
    known_by_character_ids: list[str]
    related_entity_ids: list[str]
    related_character_ids: list[str]
    related_thread_ids: list[str]
    importance: float

@dataclass(frozen=True)
class MemoryUpdateProposalContract:
    id: str
    proposal_type: str
    payload: dict
    confidence: float
    reason: str | None
    decision: str
```

## Facade（facade.py）

```python
async def get_recent_story_memory(db, novel_id, before_chapter_index=None, limit=8) -> list[MemoryRecordContext]
async def get_entity_memory(db, novel_id, entity_id, limit=20) -> list[MemoryRecordContext]
async def create_memory_update_proposals(db, novel_id, source_type, source_id, extraction_result) -> list[MemoryUpdateProposalContext]
async def confirm_memory_proposal(db, proposal_id, edited_payload=None, decided_by=None) -> MemoryRecordContext
```

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/novels/{novel_id}/memories/records` | 创建记忆记录 |
| GET | `/api/novels/{novel_id}/memories/records` | 记忆记录列表 |
| GET | `/api/novels/{novel_id}/memories/records/{id}` | 记忆记录详情 |
| PUT | `/api/novels/{novel_id}/memories/records/{id}` | 更新记忆记录 |
| DELETE | `/api/novels/{novel_id}/memories/records/{id}` | 删除记忆记录 |
| GET | `/api/novels/{novel_id}/memories/proposals/pending` | 待处理提案列表 |
| POST | `/api/novels/{novel_id}/memories/proposals/{id}/decide` | 处理提案 |

## 标准流程

```
用户手写正文 / 结构变更
    ↓
结构复查与状态抽取 Prompt
    ↓
memory_update_proposals（create_memory_update_proposals）
    ↓
用户确认 / 编辑 / 拒绝（confirm_memory_proposal）
    ↓
memory_records（正史）
    ↓
必要时同步 character_knowledge / timeline / outline
```

## 测试方式

```bash
cd backend
python -m pytest modules/memory/tests/ -v
```

## 依赖

- `core.base` — Base ORM、UUIDMixin、NovelMixin、TimestampMixin
- `core.database` — 数据库连接
- `core.dependencies` — DbSession
- `shared.enums` — MemoryType 等枚举
- `shared.types` — 类型别名
- `shared.constants` — 分页常量

## 不做

- 多张高度细分 memory 表
- 自动无确认写入 canonical memory
- 全自动推断复杂因果
- 长期对话记忆系统
