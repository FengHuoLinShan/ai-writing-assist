# WorldEntityService 职责拆分 — 候选 3 设计归档

- **Date:** 2026-06-22
- **Status:** Implemented on `minimal-core`
- **Scope:** `backend/modules/world`
- **Related plan:** `docs/superpowers/plans/2026-06-13-world-entity-service-decomposition.md`

## Goal

将 `WorldEntityService` 中积累的别名管理、embedding 回填、世界上下文/查询三类职责拆出为独立服务，使 `WorldEntityService` 退化为只做核心 CRUD 与创建时去重校验的薄协调层。

## Final Architecture

| 服务 | 文件 | 职责 |
|------|------|------|
| `WorldEntityService` | `backend/modules/world/services/entity_service.py` | Core CRUD + `create` 去重确认 + `list` 过滤 + `promote` |
| `EntityAliasService` | `backend/modules/world/services/entity_alias_service.py` | 管理 `core_entities.content_json.aliases`：列表/创建/删除 |
| `EntityEmbeddingService` | `backend/modules/world/services/entity_embedding_service.py` | 批量回填缺失的实体 embedding |
| `EntityContextService` | `backend/modules/world/services/entity_context_service.py` | 世界上下文包、检索词典、摘要列表、按名称查 ID、自动入库批次 |

Facade 与 API 层只改内部委托对象，**不改动外部签名**。

## Component Details

### `WorldEntityService`

- 继承 `CrudService`，通过 `repo = CoreEntityRepository()` 复用 base 的 `get/update/delete`。
- `create` 覆盖：在 `force_create=False` 时调用 `find_similar_by_search_text` 进行相似度冲突检查，返回 409 与候选列表。
- `list` 覆盖：增加 `entity_type/status/q` 过滤，并返回 `CoreEntityListResponse` 包装。
- `promote`：将 `draft/candidate` 状态实体提升为 `canonical`。
- 不再包含别名、embedding、上下文、检索词典、批次等逻辑。

### `EntityAliasService`

- 依赖注入：`__init__(repo: CoreEntityRepository | None = None)`，默认新建 repository。
- `list_aliases`：拉取项目下实体，扁平化 `content_json.aliases`，支持 `skip/limit`；兼容历史 `str` 与当前 `dict` 两种格式。
- `create_alias`：检查跨 `novel_id` 与重复别名，分别返回 404/409；成功后追加 `{"alias": ..., "type": ...}` 并 `db.flush()`。
- `delete_alias`：删除首个归一化后匹配的别名，未找到返回 404。

### `EntityEmbeddingService`

- 无状态服务；`backfill_embeddings(db, novel_id, *, batch_size=64)` 直接查询 `CoreEntity`。
- 过滤条件：`novel_id == nid`、`embedding is None`、`status in ("canonical", "draft")`。
- 空名实体会被过滤，避免 `generate_embedding` 返回与输入数量错位（已修复的 P0 index-mismatch bug）。
- BGE 客户端不可用或单批次失败时记录日志并跳过，继续下一批次。

### `EntityContextService`

- 依赖注入：`__init__(repo: CoreEntityRepository | None = None)`。
- `get_entity_context`：按 `entity_ids` 精确查询，或按 `novel_id` 拉取前 N 条；支持 `current_chapter` 临时实体过期过滤。
- `list_entity_summaries`：返回 `{id, name, entity_type}` 摘要。
- `list_entity_terms`：为正史/草稿实体构建检索词典（`name + aliases`）。
- `find_by_name`：委托 repository 按名称查实体 ID。
- `list_entity_batches`：委托 repository 的 `get_entity_batches`。
- 临时实体过期配置读取从 `WorldEntityService` 移入此处，project 配置不再泄露到实体 CRUD 服务。

## Data Flows

### 1. 创建实体

```
API /api/world/entities (POST)
  → _entity_service.create()
  → WorldEntityService.create()
    → find_similar_by_search_text (dedup)
    → CoreEntityRepository.create()
```

### 2. 列出别名

```
API /api/world/aliases (GET)
  → _alias_service.list_aliases()
  → EntityAliasService.list_aliases()
    → CoreEntityRepository.get_by_novel()
    → flatten content_json.aliases
```

### 3. 回填 embedding

```
Facade backfill_entity_embeddings()
  → _embedding_service.backfill_embeddings()
  → EntityEmbeddingService.backfill_embeddings()
    → select CoreEntity where embedding is None
    → BgeEmbeddingClient.generate_embedding(batch_texts)
    → set entity.embedding / entity.embedding_text
```

### 4. 获取世界上下文

```
Facade/API get_world_context()
  → _context_service.get_entity_context()
  → EntityContextService.get_entity_context()
    → get_by_ids 或 get_by_novel
    → optional temporary-entity expiry filtering
    → _entity_to_context
```

## Interface Stability

- `entity_facade.py` 中以下函数签名不变，仅内部转发：
  - `list_entities`
  - `list_entity_terms`
  - `get_world_context`
  - `find_entity_id_by_name`
  - `backfill_entity_embeddings`
- `api.py` 中别名与批次路由的外部契约不变。
- 新增服务已在 `backend/modules/world/services/__init__.py` 导出。

## Testing

- 新增服务单元测试：
  - `backend/modules/world/tests/test_entity_alias_service.py`
  - `backend/modules/world/tests/test_entity_embedding_service.py`
  - `backend/modules/world/tests/test_entity_context_service.py`
- 原 `tests/unit/test_world_extra.py` 中的上下文/embedding 测试已迁移到对应新服务。
- 验证命令与结果：
  ```bash
  cd backend && python -m pytest modules/world/tests/test_entity_*.py \
    modules/world/tests/test_world.py \
    modules/world/tests/test_world_object_management.py \
    tests/unit/test_world_extra.py -q
  # 188 passed

  cd backend && ruff check modules/world/services/entity_*.py \
    modules/world/entity_facade.py modules/world/api.py \
    modules/world/tests/test_entity_*.py tests/unit/test_world_extra.py
  # All checks passed
  ```

## Known Gaps / Candidate 4

候选 3 明确将以下两项留在 facade 中直写，属于候选 4 范围：

- `count_entities(db, novel_id, *, status_filter=None)` —— 统计实体数量。
- `list_auto_ingested_entities(db, novel_id, *, start_chapter, end_chapter, limit)` —— 列出深度导入自动生成的实体。

建议候选 4 将二者提取到独立服务（如 `EntityStatsService` 或 `EntityIngestionService`），并补充单元测试，使 facade 彻底无直接 SQL/ORM 查询。

## Design Decisions

1. **别名继续内联存储**：不恢复独立 `entity_aliases` 表，保持 `content_json.aliases` 作为长期资产存储位置。
2. **服务间不互相调用**：`EntityAliasService`、`EntityContextService`、`EntityEmbeddingService` 各自只依赖 repository；跨职责调用留在 facade/API 层组合。
3. **Project 配置隔离**：临时实体过期读取从 entity CRUD 移入 `EntityContextService`，避免 `WorldEntityService` 了解 project settings。
4. **保留历史 alias 格式**：`str` 与 `dict` 两种别名形式并存，统一归一化处理。
5. **Embedding 失败不阻断**：单批次失败记录日志后继续，避免一次坏数据导致整轮回填中断。

## Minor Notes

- `EntityAliasService` 使用 `self.repo`，而 `EntityContextService` 使用 `self._repo`；命名不一致但不影响行为，可在后续清理时统一。
- 别名归一化逻辑在 `EntityAliasService` 与 `EntityDedupService` 中存在重复，未来可考虑提取到共享 helper。
