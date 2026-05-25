# Module: infrastructure / 基础设施模块

## 1. LLM 客户端

### 目录

```
infrastructure/llm/
├── client.py       — LLMClient（generate / generate_structured / generate_stream / generate_simple）
├── providers.py    — Provider（OpenAI 兼容 API / response_format）
├── retry.py        — 指数退避重试
├── schemas.py      — LLMCallRequest / LLMCallResponse / LLMMessage / LLMStreamChunk
└── errors.py       — LLMError / LLMInvalidResponseError
```

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
```

## 2. 异步任务系统

### 目录

```
infrastructure/tasks/
├── models.py       — AsyncTask ORM
├── worker.py       — Worker 循环（FOR UPDATE SKIP LOCKED）
├── registry.py     — @task_handler 装饰器注册
└── api.py          — 任务提交/状态查询 API
```

### 任务类型

- world_entity_extraction — 从章节正文抽取候选（已实现）
- embedding_build / rag_reindex / world_structure_generate / plot_structure_generate / chapter_scene_generate / structure_review / memory_extract / import_text（预留）

### 任务领取

```sql
SELECT * FROM async_tasks WHERE status = 'pending'
ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED;
```

### API

```
POST /api/tasks         # 提交任务
GET  /api/tasks/{id}    # 查询任务状态
```

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
