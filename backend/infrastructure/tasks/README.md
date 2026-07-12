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

## Lease 与恢复策略

每次 claim 都会物化新的 `lease_id` 并递增 `attempt`。心跳和最终状态更新都必须同时匹配
`task_id + running + lease_id`；stale scanner 清空旧 lease 后，旧 worker 不能覆盖新 attempt。

handler 注册时声明四种冻结策略：

- `auto_requeue`：只用于已证明幂等的派生任务，未耗尽 `max_attempts` 时可重排。
- `manual_resume`：imports 等有 checkpoint/回滚入口的流程，stale 后进入
  `failed + recovery_required`。
- `restart_origin`：不证明安全重放，由前端引导回业务来源重新发起。
- `never_retry`：明确不可重试。

`GET /api/tasks/{task_id}` 加性返回 `attempt / max_attempts / stale / lifecycle /
available_actions`。前端只渲染后端返回的固定 action，不根据 heartbeat 或 task type
自行推测恢复方式。

其他业务模块只通过 `contracts.py` 和 `facade.py` 读取 lifecycle 投影，不跨模块
import `models.py` 或 `lifecycle.py`。
