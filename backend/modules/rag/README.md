# Module: rag / 检索增强模块

## 定位

rag 模块负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息。
它不是复杂 GraphRAG 系统，也不是自动剧情推理系统。

## 负责

- 文本分块（按段落 / 按长度 / 中文小说分块）
- Embedding 生成（可降级）
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

## 检索类型

| 检索类型 | 方法 | 说明 |
|----------|------|------|
| 精确检索 | `find_by_entity/character/thread/chapter` | 按关联 ID 精确过滤 |
| 关键词检索 | `keyword_search` | SQL LIKE 文本匹配，SQLite 兼容 |
| 混合检索 | `hybrid_search` | 关键词 + 项目词典 + 关系 + 重要性 + 向量 |
| 向量检索（预留） | `vector_search` | pgvector 余弦距离查询 |
| 抽取检索 | `retrieve(mode="extraction")` | 明确关系命中即可召回，避免字段关键词缺失导致 no_chunks |

## 混合评分公式

```
score = 0.45 × vector_score
      + 0.30 × keyword_score
      + 0.15 × relation_score
      + 0.10 × importance_score
```

索引版本 `cn-novel-v1` 使用正文 offset、chunk_index 和 embedding_status 记录索引质量。embedding 失败不阻塞索引，但会写入 warnings 并让前端提示“结果可能不准确”。

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
- `get_ordered_chapter_chunks(db, novel_id, start_chapter, end_chapter=None) -> list[RagChunkContract]`
  - 给抽取链路提供有序正文材料
- `split_text_into_chunks(text, method, **kwargs) -> list[str]`
  - 文本分割工具

## API 路由

```
POST /api/rag/chunks?novel_id=xxx       — 创建片段
GET  /api/rag/chunks?novel_id=xxx        — 片段列表
POST /api/rag/retrieve?novel_id=xxx      — 混合检索
POST /api/rag/chunks/split               — 文本分割工具
```

`retrieve` 响应包含 `warnings` 与 `degraded`；`chunks` 列表响应额外包含 `embedding_failed_count`。

## 服务

| 服务 | 职责 |
|------|------|
| `ChunkingService` | 文本分块（按段落 / 按长度） |
| `RetrievalService` | 混合检索与评分 |
| `IndexingService` | `cn-novel-v1` 章节索引与 embedding 诊断 |

## 测试

```bash
cd backend
pytest modules/rag/tests/ -v
```

## 依赖

- `core.database` — 数据库 session
- `core.base` — ORM base class
- `shared.constants` — 评分权重常量
- `shared.enums` — Visibility 枚举

## 不做

- 复杂 GraphRAG 社区摘要
- Neo4j
- 实时全量 Mention embedding
- 自动合并正史对象
- 复杂 reranker
