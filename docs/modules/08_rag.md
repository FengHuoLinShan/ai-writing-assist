# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。

## 数据表

- rag_chunks — source_type / source_id / chapter_index / chunk_index / start_offset / end_offset / char_count / text / summary / embedding / entity_ids / character_ids / thread_ids / visibility / importance / index_version / embedding_status / embedding_error / index_warnings / meta

## 服务

- ChunkingService：文本分块（按段落/按长度/中文小说分块）
- RetrievalService：混合检索（向量+关键词+项目词典+关系+重要性）
- IndexingService：章节索引编排（读取草稿 → 分块 → 入库）

## 检索类型

- 精确检索：entity_id / character_id / thread_id / chapter_index
- 关键词检索：专名 / 别名 / 章节名
- 项目词典检索：人物 name+aliases、世界对象 name+aliases（core_entities.content_json.aliases）、剧情线名称
- 向量检索：语义相似
- metadata 过滤：visibility / importance / source_type
- 抽取模式：`mode="extraction"` 时允许明确 entity/character/thread/chapter 关系命中作为有效召回

## 混合评分

加权公式见 `shared/constants.py`（RAG_VECTOR_WEIGHT 等）。embedding 失败时降级为关键词/词典检索，返回 `warnings` 和 `degraded`。

## 章节自动索引

通过 `publish_chapter` 发布任务自动触发章节索引；手动重建仍可直接提交 RAG 索引任务。流程：读取正文 → `cn-novel-v1` 分块策略 → 词典匹配标注 → 替换旧 chunk → 生成 embedding。

章节正文 chunk 的幂等键是 `(novel_id, source_type, chapter_index, chunk_index, index_version)`；带来源对象的 chunk 额外包含 `source_id`。`index_version` 不允许为空，重建章节时会 upsert 当前 chunk 并清理同章旧版本/stale chunk。

### Facade

```python
async def create_chunk(db, novel_id, data) -> RagChunkResponse
async def retrieve(db, novel_id, query, *, entity_ids=None, character_ids=None, thread_ids=None, chapter_index=None, visibility=None, mode="search", top_k=12, reference_chapter_index=None) -> RagResultBundle
async def index_chapter(db, novel_id, chapter_index) -> int
async def index_chapter_with_report(db, novel_id, chapter_index) -> RagIndexReport
async def get_ordered_chapter_chunks(db, novel_id, start_chapter, end_chapter=None) -> list[RagChunkContract]
async def get_index_status(db, novel_id) -> dict
async def list_chunks(db, novel_id, skip=0, limit=20) -> tuple[list[RagChunkResponse], int]
async def split_text_into_chunks(text, method="paragraph", **kwargs) -> list[str]
```

### 任务

- `rag_index_chapter` — 单章 RAG 索引任务，供发布任务和手动维护入口复用
- `rag_reindex_novel` — 全量/范围重建项目章节索引，返回每章 chunk 数与 embedding warnings

## API

```
POST /api/rag/chunks           # 创建 RAG 片段
GET  /api/rag/chunks           # 获取 RAG 片段列表
POST /api/rag/retrieve         # 混合检索
POST /api/rag/chunks/split     # 分割文本为片段（工具接口，不写入数据库）
```

`POST /api/rag/retrieve` 支持 `mode=search/context/extraction`，响应包含 `warnings` 和 `degraded`。
`GET /api/rag/chunks` 额外返回 `embedding_failed_count/degraded/warnings` 供前端提示索引质量。

## 不做

- 复杂 GraphRAG 社区摘要 / Neo4j
- 实时全量 Mention embedding
- 复杂 reranker
