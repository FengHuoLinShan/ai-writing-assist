# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。

## 数据表

- rag_chunks — source_type / text / summary / embedding (Vector(1024)) / entity_ids / character_ids / thread_ids / visibility / meta

## 服务

- ChunkingService：文本分块（按段落/按长度）
- RetrievalService：混合检索（向量+关键词+关系+重要性）
- IndexingService：章节索引编排（读取草稿 → 分块 → 入库）

## 检索类型

- 精确检索：entity_id / character_id / thread_id / chapter_index
- 关键词检索：专名 / 别名 / 章节名
- 向量检索：语义相似
- metadata 过滤：visibility / importance / source_type

## 混合评分

```text
score = 0.45 * vector_score + 0.30 * keyword_score + 0.15 * relation_score + 0.10 * importance_or_recency_score
```

- vector_score 现在为真实余弦相似度（查询 embedding vs chunk embedding），不再为 0
- 查询时调用 `LLMClient.generate_embedding()` 生成查询向量
- 索引时批量生成所有 chunk 的 embedding 并存储

## 章节自动索引

保存草稿时自动触发 `rag_index_chapter` 异步任务：

1. 读取该章节最新草稿正文
2. 按段落分割为 chunk
3. 文本匹配已有角色名，填入 `character_ids`
4. 删除该章节旧 chunk（替换而非追加）
5. 存入 RAG 库

### Facade

```python
async def index_chapter(db, novel_id, chapter_index) -> int
```

### 任务

- `rag_index_chapter` — 由 writing API 的 saveDraft 端点自动触发

## API

```
POST /api/rag/chunks           # 创建 RAG 片段
GET  /api/rag/chunks           # 获取 RAG 片段列表
POST /api/rag/retrieve         # 混合检索
POST /api/rag/chunks/split     # 分割文本为片段（工具接口，不写入数据库）
```

## 不做

- 复杂 GraphRAG 社区摘要 / Neo4j
- 实时全量 Mention embedding
- 复杂 reranker
