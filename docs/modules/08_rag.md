# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。

## 数据表

- rag_chunks — source_type / text / summary / embedding / entity_ids / character_ids / thread_ids / visibility

## 服务

- RagService：分块、embedding、检索

## 检索类型

- 精确检索：entity_id / character_id / thread_id / chapter_index
- 关键词检索：专名 / 别名 / 章节名
- 向量检索：语义相似
- metadata 过滤：visibility / importance / source_type

## 混合评分

```text
score = 0.45 * vector_score + 0.30 * keyword_score + 0.15 * relation_score + 0.10 * importance_or_recency_score
```

## API

```
POST /api/rag/retrieve       # 混合检索
POST /api/rag/chunks/split   # 重建索引
GET  /api/rag/chunks         # 索引状态
```

## 不做

- 复杂 GraphRAG 社区摘要 / Neo4j
- 实时全量 Mention embedding
- 复杂 reranker
