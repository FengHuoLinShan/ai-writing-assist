# Phase 3: Context Compiler 地缘感知扩展 — 详细实施计划

## 概述

Phase 1（RAG 核心检索层硬化）和 Phase 2（LLM 故障容灾）已完成。本计划仅覆盖 Phase 3：Context Compiler 地缘感知扩展。

**核心目标**：在 Context Compiler 编译上下文时，根据角色当前位置和地理拓扑可达性，对 RAG 检索到的 chunk 进行地缘过滤，剔除角色不可达的地理信息，提升 LLM 上下文质量。

---

## 关键设计决策

### D1: 角色→地点映射方式

**问题**：`Character.meta["current_location_id"]` 存储的是地点 ID，但缺少 facade 方法暴露。

**方案**：在 `character/facade.py` 新增 `get_character_location_id(db, novel_id, character_id)` 方法，返回 `str | None`。遵循跨模块只通过 facade 通信的架构约束。

### D2: Chunk→地点映射方式

**问题**：`RagChunkContract` 有 `entity_ids`（世界对象 ID），但 geo 模块使用 `location_id`（地理地点 ID），两者不同。

**方案**：利用 `bundle.geo_locations` 中已加载的地点数据构建 `world_entity_id → location_id` 映射表。`GeoLocationsLoader` 在 `RagChunksLoader` 之前执行（两者都在 dependent loaders 阶段），但 geo_locations 是从 world_entities 推导的，而 world_entities 是 prerequisite loader。因此 bundle 中 geo_locations 在 rag_chunks 加载时可能尚未就绪。

**修正方案**：将 `geo_locations` 加入 `_PREREQUISITE_LOADERS`，确保在 rag_chunks 之前加载完成。或者，在 `GeoReachabilityFilter` 中独立查询 geo 模块获取映射。

**最终方案**：`GeoReachabilityFilter` 通过 `geo.facade` 独立获取地点映射，不依赖 bundle 中的加载顺序。这样更解耦，且 filter 可以独立测试。

### D3: 过滤策略

**问题**：不可达 chunk 是直接删除还是降权？

**方案**：降权不删除。将不可达 chunk 的 `importance` 乘以 0.3 系数，并在 chunk 的 meta 中标记 `geo_filtered: True`。保留部分上下文用于"角色不知道但作者需要"的场景。排序后，降权 chunk 自然排到后面。

### D4: Chunk 中的地点信息来源

**问题**：`RagChunkContract` 没有 `meta` 字段，无法获取 `related_location_ids`。

**方案**：通过 chunk 的 `entity_ids` 交叉匹配 geo 地点的 `world_entity_id` 来确定 chunk 关联的地点。具体步骤：
1. 调用 `geo.facade` 获取小说所有地点（或通过 `get_location_tree` 获取）
2. 构建 `world_entity_id → location_id` 映射
3. 对每个 chunk 的 `entity_ids`，查找是否有对应的 location
4. 如果有，检查该 location 是否可达

---

## 实施步骤（TDD 垂直切片）

### Step 3.1: RED — `character.facade.get_character_location_id` 测试

**文件**: `backend/modules/character/tests/test_character.py`

新增测试：
- `test_get_character_location_id_returns_location` — 角色有 location 时返回
- `test_get_character_location_id_returns_none_when_no_location` — 角色无 location 时返回 None

### Step 3.2: GREEN — 实现 `character.facade.get_character_location_id`

**文件**: `backend/modules/character/facade.py`

新增方法：
```python
async def get_character_location_id(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
) -> str | None:
    """获取角色当前所在地点 ID"""
```

内部调用 `CharacterRepository` 读取 `meta["current_location_id"]`。

**文件**: `backend/modules/character/repositories.py`

新增方法：
```python
async def get_character_location_id(
    self, db: AsyncSession, character_id: uuid.UUID
) -> str | None:
```

### Step 3.3: RED — `GeoReachabilityFilter` 单元测试

**文件**: `backend/modules/context/tests/test_context.py`

新增 `TestGeoReachabilityFilter` 类：

1. `test_filter_removes_unreachable_chunks` — 模拟角色在 A 地，chunk 关联 B 地不可达，验证 chunk 被降权
2. `test_filter_preserves_reachable_chunks` — 模拟角色在 A 地，chunk 关联 B 地可达，验证 chunk 保留原权重
3. `test_filter_no_character_location_skips` — 角色无位置信息时，跳过过滤
4. `test_filter_no_chapter_index_skips` — 无 chapter_index 时，跳过过滤
5. `test_filter_chunk_without_entity_ids_preserved` — chunk 无 entity_ids 时保留

测试中 mock `character.facade.get_character_location_id` 和 `geo.facade.calculate_route`。

### Step 3.4: GREEN — 实现 `geo_filter.py`

**文件**: `backend/modules/context/services/loaders/geo_filter.py`

```python
class GeoReachabilityFilter:
    """地缘可达性过滤器"""

    UNREACHABLE_WEIGHT_FACTOR = 0.3

    async def filter_chunks(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        character_ids: list[str],
        chunks: list[dict],
        entity_to_location_map: dict[str, str],
    ) -> list[dict]:
        """
        对 chunks 执行地缘过滤：
        1. 获取首个人物的当前位置
        2. 对每个 chunk 的 entity_ids 查找对应 location
        3. 调用 geo.facade.calculate_route 检查可达性
        4. 不可达 chunk 降权
        """
```

### Step 3.5: RED — `RagChunksLoader` 集成地缘过滤测试

**文件**: `backend/modules/context/tests/test_context.py`

新增 `TestRagChunksLoaderGeoFilter` 类：

1. `test_rag_loader_applies_geo_filter_when_enabled` — enable_geo_filter=True 时应用过滤
2. `test_rag_loader_skips_geo_filter_when_disabled` — enable_geo_filter=False 时跳过过滤（默认行为）

### Step 3.6: GREEN — 在 `RagChunksLoader` 中集成过滤

**文件**: `backend/modules/context/services/loaders/rag_chunks_loader.py`

修改 `load` 方法：
- 在 RAG 检索后，如果 `options.enable_geo_filter` 且 `options.character_ids` 非空且 `options.chapter_index` 非空
- 构建 `entity_to_location_map`（通过 `geo.facade.get_location_tree` 或 bundle 中的 geo_locations）
- 调用 `GeoReachabilityFilter.filter_chunks`
- 用过滤后的 chunks 替换 `bundle.rag_chunks`

### Step 3.7: RED — facade/contracts 参数扩展测试

**文件**: `backend/modules/context/tests/test_context.py`

1. `test_compile_options_enable_geo_filter_default_false` — 默认不启用
2. `test_compile_options_enable_geo_filter_true` — 可显式启用
3. `test_structure_context_bundle_geo_filtered_default_false` — bundle 默认 geo_filtered=False
4. `test_facade_compile_with_geo_filter` — facade 传递 enable_geo_filter 参数

### Step 3.8: GREEN — 扩展 contracts + types + facade

**文件 1**: `backend/modules/context/services/types.py`

`CompileOptions` 新增字段：
```python
enable_geo_filter: bool = False
```

**文件 2**: `backend/modules/context/contracts.py`

`StructureContextBundle` 新增字段：
```python
geo_filtered: bool = False
```

**文件 3**: `backend/modules/context/facade.py`

`compile_structure_context` 新增参数：
```python
enable_geo_filter: bool = False,
```

传递到 `CompileOptions`。

### Step 3.9: REFACTOR — 清理 + 全量测试

1. 运行 `pytest backend/modules/context/tests/ -v` 确保 context 模块全部通过
2. 运行 `pytest backend/modules/character/tests/ -v` 确保 character 模块全部通过
3. 运行 `pytest backend/modules/rag/tests/ -v` 确保 RAG 模块全部通过
4. 检查代码风格一致性

---

## 涉及文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/modules/character/facade.py` | 修改 | 新增 `get_character_location_id` |
| `backend/modules/character/repositories.py` | 修改 | 新增 `get_character_location_id` |
| `backend/modules/character/tests/test_character.py` | 修改 | 新增 2 个测试 |
| `backend/modules/context/services/loaders/geo_filter.py` | **新建** | `GeoReachabilityFilter` 类 |
| `backend/modules/context/services/loaders/__init__.py` | 修改 | 导出 `GeoReachabilityFilter` |
| `backend/modules/context/services/loaders/rag_chunks_loader.py` | 修改 | 集成地缘过滤 |
| `backend/modules/context/services/types.py` | 修改 | `CompileOptions.enable_geo_filter` |
| `backend/modules/context/contracts.py` | 修改 | `StructureContextBundle.geo_filtered` |
| `backend/modules/context/facade.py` | 修改 | `compile_structure_context` 新增参数 |
| `backend/modules/context/tests/test_context.py` | 修改 | 新增 ~11 个测试 |

---

## 架构约束遵守

- ✅ 跨模块只通过 `facade.py` 和 `contracts.py` 通信（filter 调用 `character.facade` 和 `geo.facade`）
- ✅ API 层不写复杂业务逻辑
- ✅ facade 不写复杂业务逻辑（`get_character_location_id` 仅代理 repo）
- ✅ 不直接导入其他模块的 models/repositories/services
- ✅ 测试优先通过 facade + contracts 验证行为
