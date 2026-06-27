# Module: infrastructure / 基础设施模块

## 1. LLM 客户端

`infrastructure/llm/` 目录提供 OpenAI 兼容的 LLM 调用能力。

### 核心方法

```python
llm = LLMClient(provider_name="openai")

# 普通调用
resp = await llm.generate(request)

# 结构化 JSON（Pydantic 校验 + 自动修复）
result = await llm.generate_structured(request, MySchema, max_fix_attempts=2)

# 流式输出
async for chunk in llm.generate_stream(request): ...

# 简写（字符串入参，字符串出参）
text = await llm.generate_simple(system_prompt, user_prompt)

# Embedding 生成（单文本 → list[float]，文本列表 → list[list[float]]）
embedding = await llm.generate_embedding(text)

# 切换 Provider（关闭旧连接，创建新连接）
await llm.switch_provider("openai", base_url="...")

# 关闭 Provider（释放 HTTP 连接）
await llm.close()

# 获取 Provider 状态
stats = await llm.get_usage_stats()
```

## 2. 异步任务系统

基于 PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED）。

### 任务类型

| 处理器 | 模块 | 说明 |
|--------|------|------|
| `world_entity_extraction` | world | 从章节正文抽取世界对象并按当前 world 规则入库 |
| `plot_structure_generate` | outline | 从正文生成剧情线+篇章纲 |
| `rag_index_chapter` | rag | 单章 RAG 索引 |
| `rag_reindex_novel` | rag | 全量/范围重建项目索引 |
| `publish_chapter` | writing | 发布章节草稿并触发后续索引/记忆流程 |
| `deep_import` | imports | 深度导入流水线（Scene 切分 → 实体提取 → 结构分析） |
| `deep_import_resume` | imports | 已废弃的兼容 handler；候选管理移除后直接返回完成状态 |

### API

```
POST /api/tasks            # 提交任务
GET  /api/tasks/{id}       # 查询任务状态
POST /api/tasks/{id}/cancel # 取消任务
```

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
