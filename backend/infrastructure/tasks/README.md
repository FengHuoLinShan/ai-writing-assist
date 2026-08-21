# infrastructure/tasks — 轻量任务队列

## 定位

轻量任务队列，不使用 Redis/Arq。使用 PostgreSQL async_tasks 表 + 进程内 worker。

`async_tasks.novel_id` 是任务项目边界的一等、可索引且不可变的权威键，并以
`ON DELETE CASCADE` 关联 `projects.id`。`meta.novel_id` 仅保留为兼容投影：入队和 ORM
写入都会规范化两者，DB trigger 与 ORM 事件拒绝不一致或变更；全局任务的列为 NULL 且不得
携带非空 metadata identity。
项目任务的投影必须精确等于列的 canonical 小写连字符 UUID 文本，不能以大写、无连字符或
空字符串等等价拼写绕过数据库校验。
所有当前业务处理器在注册表声明为 `owner_scope="project"`，普通
`facade.enqueue_task(..., novel_id=...)` 必须显式传入 owner，只有显式注册的
`owner_scope="global"` 处理器可以传 `novel_id=None`。

## 目录

```
infrastructure/tasks/
├── README.md
├── __init__.py
├── models.py       # AsyncTask ORM 模型
├── worker.py       # TaskWorker 进程内 worker
├── liveness.py     # control-loop marker 与零输出健康检查 CLI
├── registry.py     # TaskRegistry 任务注册中心
└── api.py          # FastAPI 路由（提交/查询/取消）
```

## 当前任务处理器

任务处理器仍由各业务模块的 `tasks.py` 声明。`app.task_runtime` 拥有显式启动 manifest，
并由 API 与 worker 两个组合根共同调用以注册这些声明。基础设施本身不导入或发现业务模块。
当前注册项为：

- project：`smart_dedup_scan`
- world：`world_alias_relation_extraction`、
  `world_entity_fusion_suggestions`、`world_bible_projection_refresh`、
  `world_bible_synopsis_refresh`、`world_generation_suggestion`、`world_validation`、`map_atlas_generate`、
  `map_atlas_storage_cleanup`、`world_object_image_cleanup`
- outline：`plot_structure_generate`、`chapter_card_extraction`、
  `chapter_scene_generate`、`outline_analyze`、
  `outline_generate`、`scene_fusion_preview`
- evidence（持久化 type 保留 `rag_*`）：`rag_index_chapter`、`rag_reindex_novel`、`rag_retry_embeddings`、
  `rag_reannotate_entities`
- writing：`publish_chapter`、`writing_generate`、`writing_semantic_review`、
  `writing_targeted_revision`、`writing_conflict_ai_review`、
  `writing_conflict_item_ai_suggestion`
- imports：`deep_import`、`scene_auto_extraction`、`world_object_auto_extraction`、
  `plot_structure_auto_extraction`
- interaction：`interaction_story_generate`、`interaction_summary_refresh`

`deep_import` 完成时可把 post-import adoption package 的 compact receipt 写入既有
`result.phase_artifacts`；这不是新任务类型或队列状态。包组装失败不得覆盖已完成的
imports result，恢复、rollback 与 asset summary 仍由 imports 自己拥有。

两个存储清理处理器均为 `owner_scope=global`：`novel_id=NULL`。项目永久删除任务
只保存 canonical 项目前缀；替换图片清理只保存对象 ID 与旧图片版本。两者
均不保存 S3 凭证，不进入普通 task API。
其余当前处理器均为 project scope。

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

- `get_task_owner()` 只从一等 `AsyncTask.novel_id` 返回授权所需的
  `TaskOwnerContract.novel_id`；查询不加载 task meta/result，任务不存在或缺少 owner 时
  返回 `None`。
- `get_completed_task_payload()` 仅在 `task_id + task_type + novel_id + done`
  全部匹配时返回冻结的 apply 结果、revision token 与白名单上下文，
  不暴露任意 task meta；可选 `FOR UPDATE` 串行化幂等采用。
  `replace_completed_task_result()` 在同一严格范围内用 revision CAS 保存
  采用结果，并与调用方的领域写入共享事务。业务模块据此校验异步
  preview / scan 来源，不直接导入 tasks ORM。
- `cancel_unfinished_tasks_for_novel()` 仅取消指定 `novel_id` 的
  `pending/running` 任务，不自行提交事务。
- `cancel_exact_task()` 供领域按 `task_id + task_type + novel_id` 取消一个
  确切的 pending/running attempt；重复调用返回当前终态，不暴露 task ORM。
- `list_running_task_types_for_novel()` 只返回指定项目、指定类型集中的
  running task type，并必须显式排除当前 task id；它不加载 meta/result。
  `require_running_task_attempt()` 则以
  `task_id + task_type + novel_id + running + lease_id + attempt` 锁定当前 attempt，
  仅供已按 project-first 锁序进入的短 finalizer 使用。
- `delete_tasks_for_novel()` / `delete_tasks_for_novels()` 仅供项目永久删除后
  清理任务历史。

业务模块不得直接依赖 `AsyncTask` ORM 执行这些跨模块操作。

## Keyed coalescing

需要数据库级任务合并的业务模块使用 `facade.enqueue_coalesced_task()` 和
`get_latest_coalesced_task()`，不查询或构造 `AsyncTask`。内部 key 是
`novel_id + task_type + ordered scope + version=1` 的 canonical JSON SHA-256；
UUID 先规范化，JSON 固定使用 ASCII、紧凑分隔符和键排序。scope 只能包含稳定、无 secret
的领域身份，不得包含 API Key、credential、完整 prompt 或用户隐私正文。摘要本身也不进入
公开响应、错误和日志。

数据库部分唯一索引分别保证同一 key 最多一个 `pending` 和一个 `running`：

- `reuse_active` 复用 pending 或 running，适合章节索引和页面投影；
- `one_pending_follower` 复用 pending，但 running 时允许一个后继，适合运行期间仍可能收到
  新失效通知的 RAG entity reannotation。

并发 query 后的 insert 仍可能冲突，facade 在 savepoint 内 flush 并读取胜出 task；正确性
依赖数据库唯一约束，不依赖进程内锁。done/failed/cancelled 保留历史且不占活动唯一约束。
当前固定 scope 为：

- imports：`("imports_pipeline",)`，五种 task type 仍分别进入 key；
- World projection：`("page_projection", page_id, projection_type)`；
- RAG chapter：`("chapter_index", chapter_index, content_mode)`；
- RAG reannotation：`("entity_activity",)`。

keyed coalescing 只拥有排队收敛，不拥有领域新鲜度。World 仍以 page/source version/hash
CAS 决定 projection 是否可晋升；RAG 以 `rag_index_state.active_task_id + generation`
fence 旧 attempt；imports 以自己的 workflow run 保存 generation、owner 与 checkpoint。

## Operation receipt

作者显式发起的长耗时 AI 任务可经 `facade.enqueue_operation_task()` 使用客户端 UUID
作为 task id。服务端对 `novel_id + task_type + canonical request fingerprint` 重验：同请求
复用原任务（包括终态），同 ID 异请求冲突。receipt 不取代 keyed active coalescing 或
业务 owner/source fence，不保存 secret。

声明 `retry_transient_llm_errors=True` 的 handler 在 task 内关闭 LLM client transport retry，
由 worker 仅对明确临时 provider 错误自动重排，总 attempt 上限为 2。业务不得
在首次临时失败时提前写终态失败。

## 任务领取

使用 `SELECT ... FOR UPDATE SKIP LOCKED` 并发安全领取。
项目任务优先于全局清理任务，避免持续失败的最旧清理阻塞作者工作流。
`auto_requeue` handler 失败以 `updated_at + attempt` 执行持久化的 1/2/4/8/16/30 秒
有界退避；retry 在等待期不可领取，不占 worker 并发槽，重新可领取后按
本次入队时间排序，而非永久使用首次 `created_at` 抢占 FIFO。

## Lease 与恢复策略

### Control-loop liveness 与 task lease heartbeat

生产组合根向 `TaskWorker` 注入同步 control-loop observer。`run_forever()` 在 startup recovery
与 reconciler 返回后、每次控制循环开始时更新 `/tmp` 中的 monotonic marker；
`python infrastructure/tasks/liveness.py` 只在 PID 1 的独立 argv token 为 `run_worker.py` 且
marker 不超过 30 秒时以零输出返回成功。observer 失败不会阻断 claim、执行、lease heartbeat 或
任务状态写入，只会让 marker 自然过期。

这是进程控制循环的部署健康信号，不是 per-task lease heartbeat：后者仍以
`task_id + running + lease_id` fence 更新 task progress、驱动 stale recovery，并承担任务状态
正确性；control-loop marker 不读取或写入数据库任务状态。

生产 SIGTERM 也只由 `run_worker.py` 这个组合根处理：它调用 `TaskWorker.stop()`，使 worker
停止领取新任务并等待已领取任务返回；通用 `TaskWorker` 不依赖操作系统信号。run_worker 自身在 SIGTERM 后启动 120 秒排空计时，第二次 SIGTERM 立即强制
取消在跑任务；生产 Compose 的 `stop_grace_period: 2m` 是这段 drain 的外层上限。超过上限后 Docker 会发送 SIGKILL，未完成任务
仍由既有 lease heartbeat 与 stale recovery 按崩溃路径恢复，因此 graceful drain 不承诺任意长任务必然完成。

每次 claim 都会物化新的 `lease_id` 并递增 `attempt`。心跳和最终状态更新都必须同时匹配
`task_id + running + lease_id`；stale scanner 清空旧 lease 后，旧 worker 不能覆盖新 attempt。
独立心跳在同一 lease fence 下同步 handler 内存中的最新 `progress`，使没有领域 checkpoint
的长任务也能持续向状态 API 暴露百分比；它不写业务 `result/meta`，也不提交 handler 的领域事务。
项目软删除同样会取消未完成任务并清空 lease。已领取任务的下一次心跳因
lease 不匹配而失败，worker 取消 runner，handler session 回滚，旧 runner 的 finalize 不能
覆盖已持久化的 `cancelled` 状态。
即使 handler 在下一次心跳前返回，finalize 发现 lease 已失效时也会回滚当前
session，不会提交删除线性化之后的业务写入。

Handler 可在确定性阶段边界显式 `db.commit()` 建立 checkpoint；该 commit 仍经过
project/lease fence，不是绕过 worker 原子性的普通提交。任何 provider、LLM 或 embedding
等慢外部 I/O，如果前面已发生 DB 读写，必须先通过这种可恢复 checkpoint 释放事务，
并在入库前重验来源与权限。`rag.index_chapter_for_task` 是当前章节索引的窄实现；
它不能从 API 或普通业务 session 调用。

已 claim 任务使用 worker 专用 handler session。每次 handler `db.commit()` 前均在同一
事务内按 `project FOR SHARE -> task running+lease` 的顺序执行 fence，并把与 session
分离的 task 对象上 `progress/result/meta` 合并回 lifecycle row。fence 通过时，业务
写入与 checkpoint 一次提交；项目删除或 lease 丢失已先线性化时，当前事务回滚并
取消 runner。删除前已成功提交的 deep-import checkpoint 保留，删除后不会产生新写入。

`TaskWorker(task_preflight=...)` 支持组合根注入执行前门禁。worker 本身不依赖任何
业务模块；`run_worker.py` 统一注册业务 handler / DI，并仅对带一等 `task.novel_id`
的任务调用 project 活跃性门禁，`novel_id` 为空的全局任务直接放行。
preflight 是严格只读契约；返回后若 handler session 存在 `new / dirty / deleted`
状态，worker 会将 attempt 标记失败并回滚，不会静默丢弃门禁写入。成功的
只读 preflight 产生的 autobegin 事务会在 handler 入场前回滚释放；已经验证后
绑定的日志 `novel_id` 与脱离 session 的 task meta/progress 保留。该边界不替代
handler checkpoint 和 finalize 的 project/lease fence。preflight 期间不允许 `commit()`，
带 ORM 待写状态的显式 `flush()` 也会失败。SQLAlchemy Core/driver DML 不会进入
`new / dirty / deleted`，因此不能仅凭 ORM 状态标记 attempt 失败；正常返回时
边界 rollback 仍会丢弃这类 DML。preflight 实现不得使用 Core/driver 写入。
`run_worker.py` 还会在注册 handler 前校验 LLM 运行配置；
`LLM_RATE_LIMIT_PER_MINUTE=0` 表示关闭额外的进程级 RPM 限制；`--reload`
模式会在启动 watchfiles 监督进程前先执行同一校验，并由每个重载后的子进程再次校验，
避免配置错误时只退出子进程而留下空转的监督进程。
worker 的 handler 前检查是非锁定活跃性读取，不在长时间 attempt 中持有
project 行锁，因此软删除可立即清除 lease 并通过 heartbeat 取消 runner。
仅最终状态写入前的短临界区使用 `FOR SHARE` 项目 fence，将成功 finalize
线性化在项目删除之前或之后。

每个 attempt 建立独立日志作用域。claim 阶段读取一等 `task.novel_id`，只记录是否存在
未验证 owner；只有组合根 preflight 通过 project facade 成功读取活跃项目后才绑定规范化
UUID。执行、完成、取消和失败日志复用该安全上下文，门禁失败、缺失或畸形 meta 不回显原值。
该作用域在异常和取消时同样清理；它只提供当前进程内任务关联，不是分布式 tracing。

handler 注册时声明四种冻结策略：

- `auto_requeue`：只用于已证明幂等的派生任务，未耗尽 `max_attempts` 时可重排。
- `manual_resume`：imports 等有 checkpoint/回滚入口的流程，stale 后进入
  `failed + recovery_required`。
- `restart_origin`：不证明安全重放，由前端引导回业务来源重新发起。
- `never_retry`：明确不可重试。

worker 启动先执行通用 stale-task recovery，再在同一独立事务调用组合根注入的领域
reconciler。当前 RAG 会清理/补排失活 index owner，imports 会把 run 与 task 的
pending/running/terminal/manual-resume 状态收敛并同步或清空 attempt/lease owner，
interaction 会把已经失去活跃 task owner 的生成 attempt 收敛为明确 failed；已有可见正文
留在失败记录中供用户显式保留或重新生成，reconciler 不自动提升为 selected partial。任一
reconciler 失败则启动恢复事务回滚，不以半套 owner 状态继续工作。
如果 worker 在旧心跳仍处于宽限期时重启，启动扫描可能暂时保留旧 running owner；后续 stale
scanner 一旦实际把 task 自动重排或终态化，会立即再运行同一组领域 reconciler。这样最终
heartbeat timeout 不会让 RAG/imports/interaction 领域状态继续指向 failed task，且 keyed
唯一约束与领域 generation fence 仍负责多 worker 收敛。

`GET /api/tasks/{task_id}` 加性返回 `attempt / max_attempts / stale / lifecycle /
available_actions`。前端只渲染后端返回的固定 action，不根据 heartbeat 或 task type
自行推测恢复方式。`result` 顶层以下划线开头的键是 worker 私有 checkpoint：数据库与
lifecycle 恢复路径保留原值，但 task status API 永不返回；非下划线公共结果保持原 wire
shape。业务 handler 不得把前端所需字段放进私有键。

task status/cancel/retry 在查询 task 前通过组合根注入的
`project.require_active` 检查 query `novel_id`，回收站项目统一返回 404，
不暴露 task meta/result。通用 submit 保留“模块专属类型/未知类型”的原有
校验顺序。所有业务任务默认只能通过所属模块 API 提交，不允许用
`POST /api/tasks` 绕过业务 request schema、确认或授权。只有注册时显式提供
`generic_submit_schema`（Pydantic `BaseModel` 类）的纯基础设施任务才能使用通用
submit；其 `meta` 先按该 schema 重建，再在存在 `novel_id` 时执行项目门禁。校验失败的
422 只返回受控字段位置与错误类型，不回显提交值或动态 mapping key。
infrastructure 仅依赖 DI 容器键，不 import project 模块。

公开 cancel/retry 都会按 `task_id + novel_id` 锁定任务行后重验状态。cancel 只把
`pending/running` 写为 `cancelled`；retry 只允许首个合格的 `failed -> pending`，并发后续
请求沿用 409。两者均与 worker 的 lease-fenced claim/finalize 串行化，不能用请求内旧状态
覆盖已经提交的终态或新 lease。

`story_outline_generate` 是 outline 模块专属的 `restart_origin` 任务：只能通过
`POST /api/outline/story-outline/generate` 提交。它在 provider 前持久化无 secret 的 project
LLM execution snapshot 和 StoryOutline context provenance；worker 首次 prepare 必须匹配
提交时 `submission_context_hash`，不允许排队期间静默换用新上下文，然后做 lease-fenced
checkpoint；provider 等待期间不持有数据库事务，结束后重验 context hash。返回值是 strict
preview，不自动写已采用资产。之后的窄 apply seam 只暴露 completed task 的
`action / context_provenance` 白名单投影，并在同一事务内标记采用结果。

`outline_generate` v2 同样是 outline 专属 `restart_origin` 任务，只能从剧情线、篇章纲或
Scene 工作台的当前层 AI 入口提交。task meta 冻结 `target/mode`、StoryOutline、所选资产、
作者确认的实际 context、短引用表和整体 fingerprint；确认必须采用无驱逐编译。worker 在
provider 前 checkpoint，等待期间不持有数据库事务，finalize/apply 重新编译校验漂移。
未完成 v1 task fail closed；完成的 v1 preview 只保留旧 apply 兼容。

本轮已收敛或新增的跨模块 lifecycle 操作只通过 `contracts.py` 和 `facade.py`
读取投影，不新增对 `models.py` 或 `lifecycle.py` 的依赖。deep-import 的可恢复状态已迁到
imports-owned workflow run；World Bible projection 和 RAG 的重复入队已迁到数据库唯一的
keyed coalescing。新增任务仍需独立证明 scope、合并模式和领域新鲜度 fence，不能把现有 key
复制为通用默认。
