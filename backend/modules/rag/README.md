# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。

`get_scene_mapping_coverage()` 是只读稳定 facade，对 chapter-text chunk 批量对账
`scene_id + scene_span_id + source_id + source_content_hash + offset overlap`，分开返回
valid、dangling、wrong-source 和 expected-overlap 分母。它是覆盖健康指标，不代替
RAG P@5/MRR/R@10 语义质量评测。
它不是复杂 GraphRAG 系统，也不是自动剧情推理系统。

## 负责

- 文本分块（按段落 / 按长度 / 中文小说分块）
- Embedding 生成（可降级）
- Embedding worker 预热与运行时诊断
- 关键词检索（SQL LIKE 文本匹配）
- 项目词典检索（人物别名、世界对象别名、剧情线名称）
- 混合检索（关键词 + 项目词典 + 关系 + 重要性 + 向量）
- metadata 过滤（entity_id、character_id、thread_id、chapter_index、visible_until_chapter）
- 有序章节 chunk 读取（供人物、世界对象、章节卡抽取）

## 不负责

- 复杂 GraphRAG 社区摘要
- Neo4j / Qdrant 集成
- 自动剧情推理
- 自动合并正史对象
- Cross-encoder reranker

## 数据表

- `rag_chunks` — 可删除重建的检索块；正文块指向具体 writing draft
- `rag_index_state` — 按 novel/chapter/content mode 保存请求源与已索引源的 ID/hash 和状态

章节正文索引要求 `chunk_index` 和 `index_version` 始终存在。幂等键包含
`content_mode`，canonical 与 working 分别重建；`source_id/source_content_hash`
必须指向实际执行时选中的 draft。working 来源只读取 writing 已采用版本；未采用 AI
`candidate` 不进入 latest working 或 RAG 索引。

TaskWorker 中的章节索引不在 PostgreSQL 事务内等待 embedding provider 或本地
embedding 队列。它在每个短事务开始时先取 `Project FOR SHARE`：先读取并切分
source，通过 lease/project fence checkpoint 释放读事务并立即过期 session
identity map，再生成 embedding；入库前重新取 project lock，并在同一索引状态锁下
校验 source ID/hash。成功替换 chunk 和
完成 index state 后立即 fenced commit，不把 state/chunk 锁带入下一章或 memory 阶段。
预计算期间若产生新 source，旧计划不入库，最多重新读取 3 次；同一 source 的
重复任务在入库前合并；最终索引延迟统计包含同一任务中废弃计划的重读与
embedding 时间。这只改变内部事务切分，不改变 RAG API、chunk schema、
`novel_id` 隔离或 source hash 契约。

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

`RagChunk` 通过 `scene_id` 与 `outline` 模块的 Scene 卡近似关联，并通过
nullable `scene_span_id` 指向 outline 派生的 `SceneSpan`。`scene_span_id` 不加
跨模块硬 FK，避免 RAG ORM 依赖 outline 内部模型。索引章节时：

1. 通过 `modules.outline.facade.get_scene_spans_by_chapter` 读取当前章节 span。
2. 优先用 chunk 的字符偏移与 span 的 `start_offset/end_offset` 做重叠匹配。
3. 命中 span 时同时写入 `scene_id` 与 `scene_span_id`。
4. 只有 source draft/hash 一致且 mapping 精确的 span 可写入自动 Scene 归因。
5. `chapter_only` / `unresolved` 或无匹配时 `scene_id` / `scene_span_id` 留空并进入复核。

`chapter_index` 是精确章节过滤；`reference_chapter_index` 只参与时间衰减评分；
`visible_until_chapter` 是读者进度上界硬过滤，检索时只召回该章及以前的 chunk。
`chapter_index IS NULL` 的 chunk 默认保留；如果调用方同时指定 exact
`chapter_index`，则仍按 exact chapter 过滤。

## 混合评分公式

```
score = 0.45 × vector_score
      + 0.30 × keyword_score
      + 0.15 × relation_score
      + 0.10 × importance_score
```

索引版本 `cn-novel-v1` 使用正文 offset、chunk_index 和 embedding_status 记录索引质量。embedding 失败不阻塞索引，但会写入 warnings 并让前端提示“结果可能不准确”。失败或待重新向量化的 chunk 可通过 `rag_retry_embeddings` 任务重试 embedding；该任务不重新切段、不删除 chunk，也不修改来源元数据。

TaskWorker 重试向量时也不在数据库事务内等待 embedding provider。
每批先获取 `Project FOR SHARE` 再读取候选，复制 chunk ID、
text、待重试状态和 source/version 指纹后执行 lease-fenced checkpoint；
provider 返回后重新获取 project lock，再按同一 `novel_id + chunk IDs`
锁定重读，所有短事务都保持 project 先于 chunk 的锁顺序。
只有 text、状态和来源/版本指纹全部未变的候选才写回；已被并发任务
成功推进、删除或移出请求范围的 chunk 计入已解决但不覆盖，其他仍可重试的
过期计划会跳过并按新值重读。计数按 chunk ID 去重，避免同一行在并发状态
推进中被重复累计。
每批写回后立即 checkpoint，批内 provider 失败则持久化仍匹配的失败结果并
终止本次任务循环。普通 `retry_embeddings()` 仍由 API/service 调用方拥有事务，
不自主 commit。

## 对外契约

其他模块可通过 `contracts.py` 和 `facade.py` 使用本模块：

```python
from modules.rag.contracts import RagChunkContract, RagQueryContract, RagResultBundle
from modules.rag.facade import retrieve, split_text_into_chunks, get_ordered_chapter_chunks
```

### Facade 方法

- `retrieve(db, novel_id, query, *, entity_ids, character_ids, thread_ids, chapter_index, visible_until_chapter, mode="search", top_k=12) -> RagResultBundle`
  - 核心混合检索接口
- `index_chapter_with_report(db, novel_id, chapter_index) -> RagIndexReport`
  - 索引章节并返回 chunk/embedding 诊断
- `request_chapter_index(db, novel_id, chapter_index, *, content_mode) -> dict`
  - 幂等标脏并确保同一状态键最多一个 pending/running 任务
- `mark_chapter_index_dirty(db, novel_id, chapter_index, *, content_mode) -> dict`
  - 只标脏不额外入队，供已有 `publish_chapter` 工作流负责执行时使用
- `get_index_freshness(db, novel_id, *, content_mode, chapter_from=None, chapter_to=None) -> dict`
  - 返回指定模式/范围的 fresh/stale 状态
- `get_index_status(db, novel_id) -> dict`
  - 返回索引统计、配置/实际向量维度、可重试 embedding 数、worker runtime 快照
- `prewarm_embedding_runtime() -> dict`
  - 预热本地 embedding worker 并返回维度、耗时和缓存统计
- `get_ordered_chapter_chunks(db, novel_id, start_chapter, end_chapter=None) -> list[RagChunkContract]`
  - 给抽取链路提供有序正文材料
- `split_text_into_chunks(text, method, **kwargs) -> list[str]`
  - 文本分割工具

### Task-only seams

`rag.index_chapter_for_task` 注册为组合根 DI port，不是 RAG facade 公开契约。
它严格依赖 TaskWorker 的 commit hook；普通 API/service session 由调用方拥有
事务，调用该 port 会直接拒绝。Deletion test：删除该 port 并让 task 复用
`index_chapter_with_report` 会重新在 embedding 期间持有事务；反过来让现有
入口自主 commit，会破坏 API、world draft provider 和 eval 等调用方拥有
事务的契约。因此该 DI seam 承载不同的事务所有权，不是 pass-through
重复接口。

`rag_retry_embeddings` 由 RAG 自己的 task handler 消费，因此使用模块内部
`retry_embeddings_for_task()` seam，不额外注册跨模块 DI port。它同样要求
TaskWorker commit hook，普通 session 会直接拒绝。Deletion test：让 task handler
回用普通 `retry_embeddings()` 会再次在 provider 等待期间持有 chunk/project
读事务；反向替换普通入口则会破坏调用方的事务所有权。

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

chunks CRUD/list、retrieve、rebuild 和 retry-embeddings 都在读写或入队前校验
active project；不存在与回收站项目统一返回 404。`metrics`、`prewarm`
与不入库的纯文本 `chunks/split` 是全局工具，明确豁免项目门禁。

`/api/rag/rebuild` 接收 `novel_id`、`start_chapter`、`end_chapter`（后两者可选），
以及 `content_mode`，入队 `rag_reindex_novel` 异步任务，返回 `{task_id, status}`。

`/api/rag/retry-embeddings` 接收 `novel_id`、`start_chapter`、`end_chapter`、`statuses`（默认 `failed` 与 `pending_vectorization`），入队 `rag_retry_embeddings` 异步任务，返回 `{task_id, status}`。

`retrieve` 响应包含 `warnings` 与 `degraded`；`chunks` 列表响应额外包含 `embedding_failed_count`、`retryable_embedding_count`、`configured_embedding_dim`、`indexed_embedding_dim`、`embedding_dimension_mismatch` 与 `embedding_runtime`。

RAG 文本只是候选召回材料。context 或证据 API 在输出前必须通过 writing
重读 `source_id` 对应的当前原文并校验 `source_content_hash`；不匹配的块丢弃并报
索引过期。删除所有 RAG 派生数据后可由 writing 事实源完整恢复。

作者检索页消费 context evidence API，而不是直接展示未校验的 RAG chunk。当前 HTTP/facade
不新增分页 cursor：前端单次请求最多 100 条命中，但首批只挂载 20 张结果卡，随后按 20 条
渐进显示；检索条件保存在前端 URL，临时显示游标不进入 wire 或 URL。该展示策略不改变
RAG 检索排序、chunk schema 或跨模块稳定接口。

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
- LLM reranker 启用时先召回 `2 * top_k` 候选，再通过 project runtime client
  重排并截断；reranker 失败保留原排序和 warning。Embedding 继续只读取
  `EMBEDDING_*` 配置，不继承项目 chat profile。
- Pilot v1.1 的旧 P@5/MRR/R@10 把 no-answer case 错误纳入
  ranking 聚合，且 visibility cutoff 未落入机器可执行字段，
  因此旧数值已作废。新 runner 只对 answerable case 聚合 ranking
  metric，no-answer 独立记 false-positive/abstention；QC 会阻断缺 cutoff
  或 positive source 越界的 visibility case。修复后的 127-case fresh
  v1.1 artifact 为 P@5/MRR/R@10=0.1656/0.6098/0.8996，no-answer
  false-positive rate=1.0，visibility leakage=0；只有 R@10 和 leakage
  达到当前门槛。`RERANKER_ENABLED` 因此保持默认关闭。
  后续优化必须在同一冻结
  dataset/metric/threshold 上比较，不按被测模型换题或换门槛。
- 即使调用方持有绑定 novel 的 project chat client，remote embedding 也会
  委托给无 project profile 的独立 client。
- `IndexingService` 构造函数可注入 `repo` 与 `chunking`。
- `QueryExpander` 构造函数可注入 `term_loader`。
- 不引入抽象端口/protocol（ADR-0002），使用普通类与函数/构造函数注入。

## 测试

```bash
cd backend
pytest modules/rag/tests/ -m "not real_llm and not external_data"

# 真实 embedding 提供方只在显式验收中调用
cd ../.. && make test-real-llm
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
- 自动合并已采用世界对象
- 复杂 reranker
