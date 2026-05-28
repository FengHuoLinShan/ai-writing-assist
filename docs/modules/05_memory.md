# Module: memory / 长期记忆模块

## 定位

memory 模块维护小说推进过程中的状态变化。它不是聊天记忆，也不是向量库。

## MVP 简化

- memory_records — 记忆记录
- memory_update_proposals — 状态更新提案

## 原则

- AI 只生成 proposal
- 用户确认后才写入 memory_records

## memory_type

chapter_state / event / character_state / knowledge / foreshadowing / resource / outline_drift / geo_history

## 写后状态抽取流程

```text
用户手写正文 / 结构变更
    ↓
结构复查与状态抽取 Prompt
    ↓
memory_update_proposals
    ↓
用户确认 / 编辑 / 拒绝
    ↓
memory_records
```

## Facade

```python
async def get_recent_story_memory(db, novel_id, before_chapter_index=None, limit=8, reveal_mode="author_safe") -> list[MemoryRecordContext]
async def get_entity_memory(db, novel_id, entity_id, limit=20) -> list[MemoryRecordContext]
async def create_memory_update_proposals(db, novel_id, source_type, source_id, extraction_result) -> list[MemoryUpdateProposalContext]
async def confirm_memory_proposal(db, proposal_id, novel_id, edited_payload=None, decided_by=None) -> MemoryRecordContext
```

## API

```
# 记录
GET    /api/novels/{nid}/memories/records
GET    /api/novels/{nid}/memories/records/{id}

# 提案
GET    /api/novels/{nid}/memories/proposals/pending
POST   /api/novels/{nid}/memories/proposals/{pid}/decide
```

## 不做

- 多张高度细分 memory 表
- 自动无确认写入 canonical
- 全自动推断复杂因果
