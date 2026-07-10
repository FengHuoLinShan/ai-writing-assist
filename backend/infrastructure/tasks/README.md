# infrastructure/tasks — 轻量任务队列

## 定位

轻量任务队列，不使用 Redis/Arq。使用 PostgreSQL async_tasks 表 + 进程内 worker。

## 目录

```
infrastructure/tasks/
├── README.md
├── __init__.py
├── models.py       # AsyncTask ORM 模型
├── worker.py       # TaskWorker 进程内 worker
├── registry.py     # TaskRegistry 任务注册中心
└── api.py          # FastAPI 路由（提交/查询/取消）
```

## 当前任务处理器

任务处理器由各业务模块在应用和 worker 启动时注册。当前注册项为：

- project：`smart_dedup_scan`
- world：`world_entity_extraction`、`world_alias_relation_extraction`、
  `world_entity_fusion_suggestions`、`world_bible_projection_refresh`
- outline：`plot_structure_generate`、`chapter_card_extraction`、
  `chapter_scene_generate`、`scene_cross_chapter_detection`、`outline_analyze`、
  `outline_generate`、`outline_chapter_scenes_extract`
- rag：`rag_index_chapter`、`rag_reindex_novel`、`rag_retry_embeddings`
- writing：`publish_chapter`、`writing_generate`、`writing_conflict_ai_review`
- imports：`deep_import`、`scene_auto_extraction`、`world_object_auto_extraction`、
  `plot_structure_auto_extraction`

实际注册名以各模块 `tasks.py` 的 `@task_handler(...)` 为准；不要从旧计划或示例中的
任务名推断当前可执行处理器。

## 对外接口

```python
from infrastructure.tasks import TaskWorker, TaskRegistry, task_handler

# 注册处理器
@task_handler("embedding_build")
async def handle_embedding(db, task):
    ...

# 启动 worker
worker = TaskWorker()
await worker.run_forever()   # 常驻循环
await worker.run_once()      # 单次执行
```

## 任务领取

使用 `SELECT ... FOR UPDATE SKIP LOCKED` 并发安全领取。
