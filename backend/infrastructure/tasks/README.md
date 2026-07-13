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
  `chapter_scene_generate`、`outline_analyze`、
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

其他模块的稳定写入 seam 位于 `facade.py`：

- `get_task_owner()` 只返回授权所需的 `TaskOwnerContract.novel_id`；查询不加载
  task meta/result，任务不存在或缺少 owner 时返回 `None`。
- `cancel_unfinished_tasks_for_novel()` 仅取消指定 `novel_id` 的
  `pending/running` 任务，不自行提交事务。
- `delete_tasks_for_novel()` / `delete_tasks_for_novels()` 仅供项目永久删除后
  清理任务历史。

业务模块不得直接依赖 `AsyncTask` ORM 执行这些跨模块操作。

## 任务领取

使用 `SELECT ... FOR UPDATE SKIP LOCKED` 并发安全领取。

## Lease 与恢复策略

每次 claim 都会物化新的 `lease_id` 并递增 `attempt`。心跳和最终状态更新都必须同时匹配
`task_id + running + lease_id`；stale scanner 清空旧 lease 后，旧 worker 不能覆盖新 attempt。
项目软删除同样会取消未完成任务并清空 lease。已领取任务的下一次心跳因
lease 不匹配而失败，worker 取消 runner，handler session 回滚，旧 runner 的 finalize 不能
覆盖已持久化的 `cancelled` 状态。
即使 handler 在下一次心跳前返回，finalize 发现 lease 已失效时也会回滚当前
session，不会提交该 attempt 的业务写入。

`TaskWorker(task_preflight=...)` 支持组合根注入执行前门禁。worker 本身不依赖任何
业务模块；`run_worker.py` 统一注册业务 handler / DI，并仅对带 `meta.novel_id`
的任务调用 project 活跃性门禁，无 `novel_id` 的全局任务直接放行。

handler 注册时声明四种冻结策略：

- `auto_requeue`：只用于已证明幂等的派生任务，未耗尽 `max_attempts` 时可重排。
- `manual_resume`：imports 等有 checkpoint/回滚入口的流程，stale 后进入
  `failed + recovery_required`。
- `restart_origin`：不证明安全重放，由前端引导回业务来源重新发起。
- `never_retry`：明确不可重试。

`GET /api/tasks/{task_id}` 加性返回 `attempt / max_attempts / stale / lifecycle /
available_actions`。前端只渲染后端返回的固定 action，不根据 heartbeat 或 task type
自行推测恢复方式。

task status/cancel/retry 在查询 task 前通过组合根注入的
`project.require_active` 检查 query `novel_id`，回收站项目统一返回 404，
不暴露 task meta/result。通用 submit 保留“模块专属类型/未知类型”的原有
校验顺序；只在合法任务的 `meta.novel_id` 存在时执行项目门禁。
infrastructure 仅依赖 DI 容器键，不 import project 模块。

其他业务模块只通过 `contracts.py` 和 `facade.py` 读取 lifecycle 投影，不跨模块
import `models.py` 或 `lifecycle.py`。
