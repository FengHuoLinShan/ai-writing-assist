# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。

## 数据表

- rag_chunks — source_type / source_id / content_mode / source_content_hash / chapter_index / chunk_index / offset / text / embedding / object refs / scene refs / visibility / index metadata
- rag_index_state — novel/chapter/content_mode 级的 requested/indexed source ID+hash、status、warnings

## 服务

- ChunkingService：文本分块（按段落/按长度/中文小说分块）
- RetrievalService：混合检索（向量+关键词+项目词典+关系+重要性）
- IndexingService：章节索引编排、embedding 重试与索引质量诊断（读取草稿 → 分块 → 入库）

## 检索类型

- 精确检索：entity_id / character_id / thread_id / chapter_index
- 关键词检索：专名 / 别名 / 章节名
- 项目词典检索：人物 name+aliases、世界对象 name+aliases（core_entities.content_json.aliases）、剧情线名称
- 向量检索：语义相似
- metadata 过滤：visibility / importance / source_type
- 抽取模式：`mode="extraction"` 时允许明确 entity/character/thread/chapter 关系命中作为有效召回

`chapter_index` 是 exact chapter 过滤；`reference_chapter_index` 只影响时序衰减评分；
`visible_until_chapter` 是读者进度上界硬过滤，召回 `chapter_index <= 上界` 的 chunk，
并默认保留 `chapter_index IS NULL` 的全局 chunk。若同时传 exact `chapter_index`，
则 exact chapter 语义优先。

## 混合评分

加权公式见 `shared/constants.py`（RAG_VECTOR_WEIGHT 等）。embedding 失败时降级为关键词/词典检索，返回 `warnings` 和 `degraded`。

## 章节自动索引

通过 `publish_chapter` 发布任务自动触发章节索引；手动重建仍可直接提交 RAG 索引任务。流程：读取正文 → `cn-novel-v1` 分块策略 → 词典匹配标注 → SceneSpan/Scene 归因 → 替换旧 chunk → 生成 embedding。

章节索引通过 `modules.outline.facade.get_scene_spans_by_chapter()` 读取 outline 派生
span，优先按 chunk offset 与 span offset 重叠写入 `scene_span_id` 和 `scene_id`；
只有 source draft/hash 一致且 mapping 精确的 span 可自动归因；
`chapter_only/unresolved` 不写 Scene 证据关联。RAG 不直接依赖 outline
models/repositories，也不为 `scene_span_id` 建跨模块硬 FK。

章节正文 chunk 的幂等键包含 `content_mode`；`source_id` 指向执行时选中的
writing draft，`source_content_hash` 记录其 hash。canonical/working 索引独立替换，
彼此不覆盖。writing 的 working 选择只包含已采用的 draft/published/canonical 兼容状态；
未采用 AI `candidate` 不会成为 RAG 正文来源。

autosave/publish 调用 `request_chapter_index()` 幂等标脏状态；对同一状态键仅保留
一个 pending/running 任务，执行时重读最新 requested source。RAG 文本仅用于候选召回，
证据输出必须由 writing 重读原文并校验 hash，过期 chunk 丢弃并告警。

### Facade

```python
async def create_chunk(db, novel_id, data) -> RagChunkResponse
async def retrieve(db, novel_id, query, *, entity_ids=None, character_ids=None, thread_ids=None, chapter_index=None, visible_until_chapter=None, visibility=None, mode="search", top_k=12, reference_chapter_index=None) -> RagResultBundle
async def index_chapter(db, novel_id, chapter_index) -> int
async def index_chapter_with_report(db, novel_id, chapter_index, *, content_mode="canonical") -> RagIndexReport
async def request_chapter_index(db, novel_id, chapter_index, *, content_mode) -> dict
async def mark_chapter_index_dirty(db, novel_id, chapter_index, *, content_mode) -> dict
async def get_index_freshness(db, novel_id, *, content_mode, chapter_from=None, chapter_to=None) -> dict
async def get_ordered_chapter_chunks(db, novel_id, start_chapter, end_chapter=None) -> list[RagChunkContract]
async def get_index_status(db, novel_id) -> dict
async def prewarm_embedding_runtime() -> dict
async def list_chunks(db, novel_id, skip=0, limit=20) -> tuple[list[RagChunkResponse], int]
async def split_text_into_chunks(text, method="paragraph", **kwargs) -> list[str]
```

### 任务

- `rag_index_chapter` — 单章 RAG 索引任务，供发布任务和手动维护入口复用
- `rag_reindex_novel` — 全量/范围重建项目章节索引，返回每章 chunk 数与 embedding warnings
- `rag_retry_embeddings` — 只重试 failed / pending_vectorization chunk 的 embedding，不重新切段、不删除 chunk、不修改来源元数据

## API

```
POST /api/rag/chunks           # 创建 RAG 片段
GET  /api/rag/chunks           # 获取 RAG 片段列表
POST /api/rag/retrieve         # 混合检索
POST /api/rag/chunks/split     # 分割文本为片段（工具接口，不写入数据库）
GET  /api/rag/metrics          # 索引、检索、重试指标与 embedding worker 状态
POST /api/rag/prewarm          # 预热 embedding worker
POST /api/rag/rebuild          # 提交项目章节范围重建任务
POST /api/rag/retry-embeddings # 提交 embedding 重试任务
```

`POST /api/rag/retrieve` 支持 `mode=search/context/extraction`，响应包含 `warnings` 和 `degraded`。
`GET /api/rag/chunks` 额外返回 `embedding_failed_count`、`retryable_embedding_count`、
`configured_embedding_dim`、`indexed_embedding_dim`、`embedding_dimension_mismatch`、
`embedding_runtime`、`degraded` 与 `warnings`，供前端提示索引质量。

## 不做

- 复杂 GraphRAG 社区摘要 / Neo4j
- 实时全量 Mention embedding
- 复杂 reranker
