# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。
它不是复杂 GraphRAG 系统，也不是自动剧情推理系统。

## 负责

- 文本分块（按段落 / 按长度 / 中文小说分块）
- Embedding 生成（可降级）
- Embedding worker 预热与运行时诊断
- 关键词检索（SQL LIKE 文本匹配）
- 项目词典检索（人物别名、世界对象别名、剧情线名称）
- 混合检索（关键词 + 项目词典 + 关系 + 重要性 + 向量）
- metadata 过滤（entity_id、character_id、thread_id、chapter_index）
- 有序章节 chunk 读取（供人物、世界对象、章节卡抽取）

## 不负责

- 复杂 GraphRAG 社区摘要
- Neo4j / Qdrant 集成
- 自动剧情推理
- 自动合并正史对象
- Cross-encoder reranker

## 数据表

- `rag_chunks` — RAG 文本片段主表

章节正文索引要求 `chunk_index` 和 `index_version` 始终存在。`index_chapter_with_report` 使用 `(novel_id, source_type, chapter_index, chunk_index, index_version)` upsert 当前章节 chunk，并删除同章旧版本或不在当前结果中的 stale chunk。

## 检索类型

| 检索类型 | 方法 | 说明 |
|----------|------|------|
| 精确检索 | `find_by_entity/character/thread/chapter` | 按关联 ID 精确过滤 |
| 关键词检索 | `keyword_search` | SQL LIKE 文本匹配，SQLite 兼容 |
| 混合检索 | `hybrid_search` | 合并关键词 + metadata/关系 + 向量候选后统一评分 |
| 向量检索 | `vector_search` | pgvector `<#>` inner-product 距离升序召回，返回相似度分数 |
| 抽取检索 | `retrieve(mode="extraction")` | 明确关系命中即可召回，避免字段关键词缺失导致 no_chunks |

## 中文小说分块参数

`ChunkingService.split_chinese_novel` 面向中文长篇小说正文，默认参数为：

- 目标长度 `target_length = 900` 字
- 硬上限 `max_length = 1400` 字
- 相邻 chunk 重叠 `overlap = 160` 字

切分优先在语义边界（场景转换/地点转换/段落/句末标点）处进行，并记录每个 chunk 在原文中的 `start_offset` / `end_offset`。

## Scene 关联

`RagChunk` 通过 `scene_id` 与 `outline` 模块的 Scene 卡近似关联。索引章节时：

1. 通过 `modules.outline.facade.get_scenes_by_novel` 读取当前小说的 Scene 列表。
2. 筛选 `chapter_ids` 包含当前章节索引的 Scene。
3. 将 chunk 的字符偏移范围与 `scene_chunks` 的 `[start_pos, end_pos]` 区间做重叠匹配。
4. 命中第一个重叠 Scene 时写入 `scene_id`，无匹配时留空。

## 混合评分公式

```
score = 0.45 × vector_score
      + 0.30 × keyword_score
      + 0.15 × relation_score
      + 0.10 × importance_score
```

索引版本 `cn-novel-v1` 使用正文 offset、chunk_index 和 embedding_status 记录索引质量。embedding 失败不阻塞索引，但会写入 warnings 并让前端提示“结果可能不准确”。失败或待重新向量化的 chunk 可通过 `rag_retry_embeddings` 任务重试 embedding；该任务不重新切段、不删除 chunk，也不修改来源元数据。

## 对外契约

其他模块可通过 `contracts.py` 和 `facade.py` 使用本模块：

```python
from modules.rag.contracts import RagChunkContract, RagQueryContract, RagResultBundle
from modules.rag.facade import retrieve, split_text_into_chunks, get_ordered_chapter_chunks
```

### Facade 方法

- `retrieve(db, novel_id, query, *, entity_ids, character_ids, thread_ids, chapter_index, mode="search", top_k=12) -> RagResultBundle`
  - 核心混合检索接口
- `index_chapter_with_report(db, novel_id, chapter_index) -> RagIndexReport`
  - 索引章节并返回 chunk/embedding 诊断
- `get_index_status(db, novel_id) -> dict`
  - 返回索引统计、配置/实际向量维度、可重试 embedding 数、worker runtime 快照
- `prewarm_embedding_runtime() -> dict`
  - 预热本地 embedding worker 并返回维度、耗时和缓存统计
- `get_ordered_chapter_chunks(db, novel_id, start_chapter, end_chapter=None) -> list[RagChunkContract]`
  - 给抽取链路提供有序正文材料
- `split_text_into_chunks(text, method, **kwargs) -> list[str]`
  - 文本分割工具

## API 路由

```
POST /api/rag/chunks?novel_id=xxx       — 创建片段
GET  /api/rag/chunks?novel_id=xxx        — 片段列表
POST /api/rag/retrieve?novel_id=xxx      — 混合检索
GET  /api/rag/metrics                    — 检索/索引/重试指标与 worker 状态
POST /api/rag/prewarm                   — 预热 embedding worker
POST /api/rag/rebuild                   — 按章节范围重建索引
POST /api/rag/retry-embeddings          — 重试失败/待重向量化 chunk 的 embedding
POST /api/rag/chunks/split               — 文本分割工具
```

`/api/rag/rebuild` 接收 `novel_id`、`start_chapter`、`end_chapter`（后两者可选），
入队 `rag_reindex_novel` 异步任务，返回 `{task_id, status}`。

`/api/rag/retry-embeddings` 接收 `novel_id`、`start_chapter`、`end_chapter`、`statuses`（默认 `failed` 与 `pending_vectorization`），入队 `rag_retry_embeddings` 异步任务，返回 `{task_id, status}`。

`retrieve` 响应包含 `warnings` 与 `degraded`；`chunks` 列表响应额外包含 `embedding_failed_count`、`retryable_embedding_count`、`configured_embedding_dim`、`indexed_embedding_dim`、`embedding_dimension_mismatch` 与 `embedding_runtime`。

## 模块职责

| 文件 | 职责 |
|------|------|
| `chunking.py` | 文本分块：`ChunkingService`、中文小说分块、段落/长度分块 |
| `scoring.py` | 纯评分函数与 `Scorer`：关键词、关系、向量、重要性、时序衰减、动态权重 |
| `query_expansion.py` | 项目词典加载与查询扩展：`QueryExpander`（可注入 term_loader） |
| `retrieval.py` | 检索编排：`RetrievalOrchestrator` 组装 embedding → 扩展 → 召回 → 评分 → 去重 → 重排序 |
| `indexing.py` | 章节索引与 embedding 重试：`IndexingService` 把草稿分块、标注入库、生成/重试 embedding |
| `facade.py` | 对外稳定入口，组装上述模块并代理公共方法 |
| `tasks.py` | 异步任务薄入口，校验 task meta 并委托 facade/service |
| `api.py` | FastAPI 路由，所有端点通过 facade 委托 |

## 依赖注入约定

- `RetrievalOrchestrator` 构造函数可注入 `repo / scorer / query_expander / reranker_fn / embedder_fn / metrics / circuit_breaker`，默认使用仓库/评分器/容器单例。
- `IndexingService` 构造函数可注入 `repo` 与 `chunking`。
- `QueryExpander` 构造函数可注入 `term_loader`。
- 不引入抽象端口/protocol（ADR-0002），使用普通类与函数/构造函数注入。

## 测试

```bash
cd backend
pytest modules/rag/tests/ -v
```

## 依赖

- `core.database` — 数据库 session
- `core.base` — ORM base class
- `core.container` — 轻量 DI 容器
- `shared.constants` — 评分权重常量
- `shared.enums` — Visibility 枚举

## 不做

- 复杂 GraphRAG 社区摘要
- Neo4j
- 实时全量 Mention embedding
- 自动合并正史对象
- 复杂 reranker
