# RAG + LLM 全系统生产级优化方案

## 概述

基于已落地的 v2.0 架构（PostgreSQL 17 + pgvector + pg_trgm），针对测试中暴露的三大痛点进行生产级优化：

1. **中文多词检索脱靶** — RAG 混合检索中文查询命中率归零
2. **SQLAlchemy JSONB 隐式序列化异常** — asyncpg 驱动与 GIN 索引边界不匹配
3. **大模型故障导致写作者心流中断** — LLM 异常传播到核心保存链路

---

## 一、RAG 核心检索层硬化 (`modules/rag`)

### 1.1 中文分词器替换

**文件**: `backend/modules/rag/services.py` — `RetrievalService` 类

**现状问题**:
- `hybrid_search` 中 `chinese_terms` 直接用 `query.split()` 分词，无法处理中文标点分隔的词组
- 如 `"克莱恩·莫雷蒂 渴望 目标"` 中 `"克莱恩·莫雷蒂"` 被当作一个词，但 chunk 文本中 "克莱恩" 和 "渴望" 不连续，导致整串匹配失败
- 当前已修复为多词独立匹配（`matched / len(chinese_terms)`），但分词粒度仍依赖空格

**优化方案**:
1. 在 `RetrievalService` 中新增 `_smart_tokenize_chinese(query)` 静态方法：
   - 使用 `re.split(r'[\s,，.。!！?？、·]+', query)` 按空格和中文标点切分
   - 过滤单字（`len(term) >= 2`），避免 `%一%` `%的%` 导致全表扫描
   - 返回 `list[str]` 词项列表
2. 替换 `hybrid_search` 中 `chinese_terms = [q.strip().lower() for q in query.split() if q.strip()]` 为 `chinese_terms = self._smart_tokenize_chinese(query)`
3. `keyword_search` 的 `query_terms` 也同步使用新分词器

### 1.2 关键词评分梯度化

**文件**: `backend/modules/rag/services.py` — `hybrid_search` 方法

**现状问题**:
- 中文匹配已改为 `matched / len(chinese_terms)` 覆盖率评分，但单词查询仍为 0/1 二值
- 英文 `_compute_keyword_score` 已是覆盖率评分，逻辑一致

**优化方案**:
1. 统一中英文评分逻辑：中文多词用覆盖率，单词用子串匹配（0/1）
2. 新增 **位置邻近度加分**：当多个查询词在 chunk 文本中距离较近时，额外加分
   - 计算 `min_distance = min(|pos_i - pos_j|)` 对所有匹配词对
   - `proximity_bonus = max(0, 1.0 - min_distance / 500) * 0.2`
   - 最终 `keyword_score = min(1.0, overlap_ratio + proximity_bonus)`

### 1.3 JSONB 显式序列化

**文件**: `backend/modules/rag/repositories.py` — `_json_array_contains_all` 方法

**现状问题**:
- `column.cast(JSONB).contains(values)` 直接传入 Python list，asyncpg 驱动可能无法正确绑定到 PostgreSQL GIN 索引
- 实测中 `keyword_search` + `character_ids` 过滤在 PG 上能工作，但边界条件（空列表、UUID 格式）可能不稳定

**优化方案**:
1. 将 `values` 显式序列化为 JSON 字符串后 cast：
   ```python
   import json
   target_json = json.dumps(values)
   return column.cast(JSONB).contains(cast(target_json, JSONB))
   ```
2. 空列表提前短路返回 `True`（不过滤）

### 1.4 RAG 测试补充

**文件**: `backend/modules/rag/tests/test_rag.py`

新增测试：
1. `test_smart_tokenize_chinese` — 验证分词器对空格、标点、单字的处理
2. `test_hybrid_search_chinese_multi_term` — 验证中文多词查询的覆盖率评分
3. `test_jsonb_contains_explicit_serialization` — 验证 JSONB 过滤在 PG 上的正确性
4. `test_keyword_search_chinese_punctuation` — 验证含中文标点的查询

---

## 二、Context Compiler 地缘感知扩展 (`modules/context`)

### 2.1 现状分析

**文件**: `backend/modules/context/services/loaders/rag_chunks_loader.py`

当前 `RagChunksLoader` 直接调用 `rag.facade.retrieve`，无地理可达性过滤。`MemoryRecordsLoader` 同理。

**架构约束**:
- 跨模块只能通过 `facade.py` 和 `contracts.py` 通信
- `geo.facade` 已有 `calculate_route` 方法，接受 `source_location_id`, `target_location_id`, `chapter_index`，返回 `RouteCalculationResult`（含 `is_reachable`）
- `character.facade` 已有 `get_characters_at_location` 方法

### 2.2 优化方案

**新增文件**: `backend/modules/context/services/loaders/geo_filter.py`

1. 创建 `GeoReachabilityFilter` 类：
   - 接受 `novel_id`, `chapter_index`, `character_ids` 参数
   - 通过 `character.facade.get_character_location_id` 获取当前角色位置
   - 对每个 chunk 的 `entity_ids`（地点相关）调用 `geo.facade.calculate_route` 检查可达性
   - 返回过滤后的 chunk 列表

2. 在 `RagChunksLoader.load` 中集成：
   - RAG 检索后，如果 `options.character_ids` 非空且 `options.chapter_index` 非空，执行地缘过滤
   - 不可达的 chunk 降权（不直接删除，降低 `importance` 评分），保留部分上下文用于"角色不知道但作者需要"的场景

**修改文件**: `backend/modules/context/services/types.py`

- `CompileOptions` 新增 `enable_geo_filter: bool = False` 选项

**修改文件**: `backend/modules/context/facade.py`

- `compile_structure_context` 新增 `enable_geo_filter: bool = False` 参数

**修改文件**: `backend/modules/context/contracts.py`

- `StructureContextBundle` 新增 `geo_filtered: bool = False` 标记

### 2.3 地缘过滤测试

**文件**: `backend/modules/context/tests/test_context.py`

新增测试：
1. `test_geo_filter_removes_unreachable_chunks` — 验证不可达 chunk 被降权
2. `test_geo_filter_preserves_reachable_chunks` — 验证可达 chunk 保留
3. `test_geo_filter_disabled_by_default` — 验证默认不启用

---

## 三、LLM 故障容灾降级 (`modules/writing`, `modules/character`)

### 3.1 现状分析

**文件**: `backend/modules/writing/api.py` — `save_and_analyze` 端点

当前已有基本降级：
```python
try:
    proposal_created = await analysis_service.analyze_chapter(...)
except Exception as e:
    _logger.error("地缘资产AI提取非致命性失败，已安全降级。详情: %s", str(e))
    proposal_created = False
```

**文件**: `backend/modules/character/tasks.py` — `handle_character_extract`

当前 LLM 异常会返回 `{"status": "llm_failed"}`，但 RAG 检索失败直接返回 `no_chunks`，无重试机制。

### 3.2 优化方案

**文件**: `backend/modules/character/tasks.py`

1. **RAG 检索降级**：当 `character_ids` 过滤导致 0 结果时，自动回退到无过滤检索
   ```python
   # 先尝试带角色过滤的检索
   result = await _rag_retrieve(db, novel_id, query, character_ids=[character_id], top_k=5)
   # 降级：无过滤检索
   if result.total == 0:
       result = await _rag_retrieve(db, novel_id, query, top_k=5)
   ```

2. **LLM 重试机制**：利用 `shared/constants.py` 中已有的 `LLM_RETRY_MAX_ATTEMPTS=3` 和 `LLM_RETRY_BASE_DELAY=1.0`
   ```python
   for attempt in range(LLM_RETRY_MAX_ATTEMPTS):
       try:
           extract_result = await llm.generate_structured(request, _CharacterExtractOutput)
           break
       except Exception as exc:
           if attempt < LLM_RETRY_MAX_ATTEMPTS - 1:
               await asyncio.sleep(LLM_RETRY_BASE_DELAY * (2 ** attempt))
           else:
               return {"character_id": character_id, "status": "llm_failed", "error": str(exc)}
   ```

**文件**: `backend/modules/writing/services.py` — `WritingAnalysisService`

1. **LLM 超时保护**：为 `analyze_chapter` 添加 `asyncio.wait_for` 超时控制
   ```python
   import asyncio
   from shared.constants import DEFAULT_LLM_TIMEOUT

   parsed = await asyncio.wait_for(
       llm.generate_structured(request, ChapterStateExtraction),
       timeout=DEFAULT_LLM_TIMEOUT,
   )
   ```

2. **结构化输出降级**：当 `generate_structured` 抛出异常时，尝试 `generate` + 手动 JSON 解析
   ```python
   try:
       parsed = await llm.generate_structured(request, ChapterStateExtraction)
   except Exception:
       # 降级：普通生成 + 手动解析
       raw = await llm.generate(request)
       parsed = ChapterStateExtraction.model_validate_json(raw.content)
   ```

**文件**: `backend/modules/writing/api.py`

1. **`save_and_analyze` 返回值增强**：新增 `analysis_status` 字段，区分 `success` / `degraded` / `failed`
   ```python
   class SaveAndAnalyzeResponse(BaseModel):
       draft_id: str
       proposal_created: bool = False
       analysis_status: str = "success"  # success / degraded / failed
   ```

### 3.3 容灾测试

**文件**: `backend/modules/character/tests/test_character.py`

新增测试：
1. `test_extract_rag_fallback_without_character_filter` — RAG 角色过滤无结果时自动降级
2. `test_extract_llm_retry_on_failure` — LLM 失败时重试

**文件**: `backend/modules/writing/tests/` (如存在)

新增测试：
1. `test_save_and_analyze_llm_timeout_degradation` — LLM 超时时安全降级
2. `test_save_and_analyze_llm_failure_returns_draft_id` — LLM 完全失败时仍返回 draft_id

---

## 四、执行顺序

按 TDD 垂直切片，每个优化点独立 RED→GREEN→REFACTOR：

### Phase 1: RAG 核心检索层（最高优先级，阻塞其他所有 LLM 调用链路）

| 步骤 | 类型 | 内容 |
|------|------|------|
| 1.1 | RED | `_smart_tokenize_chinese` 分词器测试 |
| 1.2 | GREEN | 实现分词器，替换 `hybrid_search` 中的分词逻辑 |
| 1.3 | RED | JSONB 显式序列化测试 |
| 1.4 | GREEN | 修复 `_json_array_contains_all` |
| 1.5 | RED | 关键词评分梯度化 + 邻近度加分测试 |
| 1.6 | GREEN | 实现邻近度加分逻辑 |
| 1.7 | REFACTOR | 清理重复代码，运行全量测试 |

### Phase 2: LLM 故障容灾（高优先级，直接影响用户体验）

| 步骤 | 类型 | 内容 |
|------|------|------|
| 2.1 | RED | RAG 检索降级测试（角色过滤无结果时回退） |
| 2.2 | GREEN | 实现 `handle_character_extract` 中的 RAG 降级 |
| 2.3 | RED | LLM 重试机制测试 |
| 2.4 | GREEN | 实现重试逻辑 |
| 2.5 | RED | `save_and_analyze` 超时降级测试 |
| 2.6 | GREEN | 添加 `asyncio.wait_for` + `analysis_status` 字段 |
| 2.7 | REFACTOR | 清理优化 |

### Phase 3: Context 地缘感知（中优先级，提升生成质量）

| 步骤 | 类型 | 内容 |
|------|------|------|
| 3.1 | RED | `GeoReachabilityFilter` 单元测试 |
| 3.2 | GREEN | 实现 `geo_filter.py` |
| 3.3 | RED | `RagChunksLoader` 集成地缘过滤测试 |
| 3.4 | GREEN | 在 loader 中集成过滤逻辑 |
| 3.5 | RED | facade/contracts 参数扩展测试 |
| 3.6 | GREEN | 扩展 `CompileOptions` 和 `StructureContextBundle` |
| 3.7 | REFACTOR | 清理优化 |

---

## 五、架构约束遵守

- ✅ 跨模块只通过 `facade.py` 和 `contracts.py` 通信
- ✅ API 层不写复杂业务逻辑
- ✅ facade 不写复杂业务逻辑
- ✅ AI 输出不直接写入 canonical
- ✅ 不拼接原始 SQL，使用 SQLAlchemy 参数绑定
- ✅ 测试优先通过 facade + contracts 验证行为
