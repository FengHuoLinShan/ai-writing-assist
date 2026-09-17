# infrastructure/tasks — 轻量任务队列

## 定位

轻量任务队列，不使用 Redis/Arq。使用 PostgreSQL async_tasks 表 + 进程内 worker。

`async_tasks.novel_id` 是任务项目边界的一等、可索引且不可变的权威键，并以
`ON DELETE CASCADE` 关联 `projects.id`。`meta.novel_id` 仅保留为兼容投影：入队和 ORM
写入都会规范化两者，DB trigger 与 ORM 事件拒绝不一致或变更；全局任务的列为 NULL 且不得
携带非空 metadata identity。
项目任务的投影必须精确等于列的 canonical 小写连字符 UUID 文本，不能以大写、无连字符或
空字符串等等价拼写绕过数据库校验。
除 `map_atlas_storage_cleanup` 和 `world_object_image_cleanup` 两个存储清理处理器外，
当前业务处理器在注册表声明为 `owner_scope="project"`。普通
`facade.enqueue_task(..., novel_id=...)` 必须显式传入 owner；只有显式注册的
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
└── api.py          # FastAPI 路由（提交/查询/取消/重试）
```

## 当前任务处理器

任务处理器仍由各业务模块的 `tasks.py` 声明。`app.task_runtime` 拥有显式启动 manifest，
并由 API 与 worker 两个组合根共同调用以注册这些声明。基础设施本身不导入或发现业务模块。
当前注册项为：

- assistant：`assistant_turn`，持久化 PydanticAI 消息检查点，manual_resume 不重置预算。
- 变化后的确定性回访：`imports_completion_review`、`story_reference_review`，分别由
  Imports、Story 持有覆盖缺口和引用失效结果，不伪装成语义审稿。
- interaction Agent：`interaction_agent_story_generate` 沿原 attempt 的 restart_origin 规则；
  `interaction_continuity_review` 是独立的只读增量检查，manual_resume，结果仍归 Interaction。
  旧 `interaction_story_generate` 继续收束旧执行版本，不在恢复时升级协议。

`_task_priority=background` 是基础设施的低优先级标记。多槽 worker 为前台留一个位置，
普通队列不领取 `_execution_mode=inline_only` 子任务。该类领域复核由助手在原 task scope
内调用既有 inline executor；父子 lease 同时约束提交，共享累计预算。inline 的 progress
与 worker 一样脱离 ORM identity map，领域 `expire_all()` 不得丢失 lease/进度身份。

父子关系在子任务创建时写入 `_parent_task_id`，取消按该关系查找，不能依赖领域稍后投影的
结果引用。取消按子任务→父任务锁序收敛；失联扫描清理终态父任务的遗留子任务，可恢复父任务
仍保留原子任务。子任务不可从通用重试接口独立运行。inline 心跳与取消清理使用调用者的数据库
绑定，不能转向另一个默认数据库；独立清理事务只收束任务元数据，不提交已撤回的领域写入。

- project：`smart_dedup_scan`
- world：`world_alias_relation_extraction`、
  `world_entity_fusion_suggestions`、`world_bible_projection_refresh`、
  `world_bible_synopsis_refresh`、`world_generation_suggestion`、`world_cocreation_turn`、`world_validation`、`map_atlas_generate`、`world_map_schematic_generate`、
  `map_atlas_storage_cleanup`、`world_object_image_cleanup`
  （`world_generation_suggestion` 的 meta 可携带 `session_id`/`session_action`：任务成功后由
  world 域把回合与成果追加进持久化共创会话，见 ADR-0021；transport 合并与任务指纹不受影响）
- story：`story_outline_generate`、`outline_analyze`、`outline_generate`、`scene_fusion_preview`、
  `story_character_card_generate`、`story_reaction_propose`、`story_scene_script_generate`、`story_one_click`。
  `plot_structure_generate`、`chapter_card_extraction`、`chapter_scene_generate` 仅为存量任务返回
  `unsupported` 的兼容注册，不是当前生产生成入口
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

`interaction_story_generate` 对 source-bound 旅程在同一 attempt 内冻结 selection epoch 与
source context epoch：prepare 时编译版本化 source packet，流式 checkpoint 与 finalize 都重验
两个 epoch；来源归档、manifest draft/hash 失效或任一 epoch 漂移时以
`source_context_stale` / `source_context_blocked` 失败关闭 attempt，不退回纯模型知识生成。
资料参考包只存 hash、引用与预算摘要，不长期保存 rendered source context。

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

手动模型任务还必须在所属业务 API 校验 `context_confirmation_id`，把 ID 写入 secret-free
request/meta，并在首次 provider I/O 前调用 Evidence 的 `prepare_confirmed_ai_action()` 重编译
通用 Context 指纹。operation receipt 只能复用已绑定同一请求/confirmation 的任务，不能把
无确认请求升级成已授权任务。内部格式修复、复核和返修复用原 confirmation；自动流水线只在
启动时确认一次，内部阶段继续使用冻结 snapshot。

三种入队原语同时构成提交协议：普通 `enqueue_task` 是 `append`；
`enqueue_operation_task` 由不可伪造的 request fingerprint 投影为 `exact_operation`；
`enqueue_coalesced_task` 在私有 meta 记录实际 `reuse_active` 或 `one_pending_follower` 模式。
调用方传入的同名私有字段和 operation fingerprint 会被 enqueuer 丢弃并按实际路径重建，不能
通过 metadata 冒充更强幂等保证。公开状态只返回模式枚举，不返回 fingerprint 或 coalescing key。

成果页的追踪视图在前端组合确切 task 的 `operation` 与领域 Evidence
Confirmation。tasks 只拥有提交/运行/恢复事实，不推导或持久领域采用、拒绝与来源
失效状态；已清理旧 task 时，Confirmation 与成果引用仍可独立读取。

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
available_actions / operation`。`operation` 是版本化的作者安全投影，统一给出实际
`submission_mode`、当前 `stage`、稳定 `error_code`、是否可恢复、是否可能扣费、是否已有
部分结果及固定 action。前端优先消费该投影，不根据 heartbeat、异常文案或 task type 推测
恢复方式；旧 task 没有 coalescing 模式 receipt 时只标记 `legacy`。`result` 顶层以下划线开头
的键是 worker 私有 checkpoint：数据库与
lifecycle 恢复路径保留原值，但 task status API 永不返回；非下划线公共结果保持原 wire
shape。业务 handler 不得把前端所需字段放进私有键。

私有 AI 运行信封只写 `meta["_ai_run_envelope"]`（`infrastructure.llm.schemas.AI_RUN_ENVELOPE_KEY`），
不写 `result`，因此 `story_outline_generate` 等按 result 顶层 exact-key 校验的领域采用路径不受影响；
`GET /api/tasks/{task_id}` 的 meta/result 投影继续剥离下划线键；公共 `operation.possible_charge`
只暴露聚合布尔值，不返回信封身份、模型、用量、Prompt 或 provider 诊断。
worker 与 inline 在 handler 执行前为 attempt 注入 `task_id/attempt/lease_id` 并建立或恢复同一 run：
自动 requeue、stale 恢复与 manual resume 只更换执行载体，不重置累计计数、冻结额度或 deadline；
inline 子任务复用父 run，不另开账本。快照通过 `TaskLifecycleService.checkpoint_run_envelope()` 的
窄 lease-fenced merge 落库，只合并该私有键，不提交或覆盖 handler 的业务事务；lease 丢失时拒绝写入。
终态快照由 `finalize(envelope=...)` 与任务终态在同一事务提交，stale 扫描与 cancel 路径在同一事务内
把未 settle 的请求收敛为 unknown/possible。没有信封且已领取过一次（`attempt > 1`）的旧在途任务标记
`legacy_untracked` 且 `usage_complete=false`，不回填猜测计数；首次领取的新任务从本 attempt 开始完整跟踪。

声明 `retry_transient_llm_errors=True` 的任务由 worker 决策 LLM 重试：只有明确分类为 transient 的
provider 错误才自动重排，且本次 attempt 的失败回执先于 lease 释放、在同一事务内持久化；认证、额度、
内容过滤与结构错误不再被通用 handler-error 分支重排。运行信封自身的拒绝（预算耗尽、deadline、
身份漂移、缺受管 step、checkpoint 失效）一律失败关闭，不进入任何自动重排；普通非 LLM 任务的
`auto_requeue` 语义不变。
任务一次权威 run 的 canonical capability 用 `TaskRegistry.register(..., root_capability_id=...)` 显式
声明，信封按声明 opt-in：只有声明的任务才建立/恢复账本并在 handler 前做 lease-fenced 落盘（被拒即
终止旧 attempt）；未声明任务保持改造前行为，不建信封也不标 legacy。没有"未声明回退"能力名；领域
一旦在任务内显式绑定 capability，就必须声明同一个 root，恢复路径还会校验持久化 run 的 root 与声明
不漂移。
声明的任务必须通过 `run_request_limit` 冻结一次 run 的请求额度（静态值，或从任务冻结输入同步
计算 A 的 callable），可选 `run_token_limit` 冻结累计 token 上限（闸门按已结算用量判定，
manual resume 按注册值续算 token）；只有领域已有整条 run 的 wall-clock 边界时才声明
`run_deadline_seconds`，单 step/provider timeout 不冒充 run deadline——但只挂单 step
timeout 的串行长链（如 writing generate、story one_click/reaction、smart dedup）补保守
总墙钟护栏（7200/3600s），只切病态挂起、不约束正常长链。已声明 root 却无法冻结额度会在
provider 前失败关闭，不得回退到通用临时上限。`writing_generate` 在入队时把确认编译产物的
确定性来源计数冻结为 `included_sources_upper_bound`，配额按真实 K 计算而不是退回 16384
物理上界（1,544 请求虚高 cap 仅历史在途任务才会走到）；`writing_conflict_*` 两任务按"两次
attempt 合法重放 12 + transport 余量 4"冻结 16，覆盖完整合法成功路径。当前
`evidence_focused_search` 使用 L0=9，并保留各 step 自身 timeout，不新增 run 总 deadline；
远程 embedding 的 RAG 任务（`rag_index_chapter` 64 请求 / `rag_reindex_novel` 4096 /
`rag_retry_embeddings` 2048，均含 token 上限与 run deadline）以宽上界冻结"批量 + 逐
chunk fallback"量级，越界失败关闭并保留 manual resume；
章节范围导致 Scene 数量运行期才知的 `world_alias_relation_extraction` 暂不声明 root，等待
Phase 0 估算或分批授权。
task type 的权威 run 若会跨多个队列行，通过注册的 `run_id` resolver 从冻结 meta 解析
稳定领域 ID；未声明时仍使用 task id。旧 task 缺少信封但已有跨 task run id 时，首次领取标记
`legacy_untracked/usage_complete=false`，不把不可考的历史用量写成 0。
旧 awaiting-continue 的历史分段同样不当作未消费额度；领域从 0 可用额度建立兼容账本，
再以一条 `author_resume` 授权追加唯一可用的新分段额度。
Interaction story task 的注册声明还提供一个窄 mirror callback，把队列快照同步到
`InteractionGenerationAttempt.agent_checkpoint_json`；`length/看海` 续写换 task 时沿用 attempt.id
的 `run_id`，不另开账本。每个合法 manual/看海续段只追加一次同分段 `author_resume`
额度，并保留 deadline；旧 task 终态 mirror 发现 attempt 已由更高授权版本的新 task 接管时
只收口旧队列行，不覆盖新快照。
mirror 读 attempt 使用 `FOR UPDATE SKIP LOCKED`：运行中 checkpoint 未取得 attempt 锁时在
provider I/O 前失败关闭；终态与领域 stop/archive 碰撞时不持 task 锁回等 attempt，由已持有
attempt 的领域事务收口，避免 task→attempt 与 attempt→task 互等。

task status/cancel/retry 在查询 task 前通过组合根注入的
`project.require_active` 检查 query `novel_id`，回收站项目统一返回 404，
不暴露 task meta/result。通用 submit 保留“模块专属类型/未知类型”的原有
校验顺序。所有业务任务默认只能通过所属模块 API 提交，不允许用
`POST /api/tasks` 绕过业务 request schema、确认或授权。只有注册时显式提供
`generic_submit_schema`（Pydantic `BaseModel` 类）的纯基础设施任务才能使用通用
submit；其 `meta` 先按该 schema 重建，再在存在 `novel_id` 时执行项目门禁。校验失败的
422 只返回受控字段位置与错误类型，不回显提交值或动态 mapping key。
infrastructure 仅依赖 DI 容器键，不 import project 模块。

`manual_resume` 任务若因信封额度耗尽而失败，公开 lifecycle 直接给出 resume；作者点击继续时按
该 task type 的冻结 L0 追加一次 `author_resume` 授权并增加 `authorization_revision`，不移动 deadline。
未耗尽额度的普通恢复不扩额，自动 retry/requeue/recovery 永不调用该授权路径。

公开 cancel/retry 都会按 `task_id + novel_id` 锁定任务行后重验状态。cancel 只把
`pending/running` 写为 `cancelled`；retry 只允许首个合格的 `failed -> pending`，并发后续
请求沿用 409。两者均与 worker 的 lease-fenced claim/finalize 串行化，不能用请求内旧状态
覆盖已经提交的终态或新 lease。

`story_outline_generate` 是 outline 模块专属的 `restart_origin` 任务：只能通过
`POST /api/outline/story-outline/generate` 提交。它在 provider 前持久化无 secret 的 project
LLM execution snapshot、Context confirmation 和 StoryOutline context provenance；worker 首次 prepare 必须匹配
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

`world_map_schematic_generate` 属于 project scope，使用 operation receipt 和 `manual_resume`；
按节点冻结地图基准及项目文本连接，最多四个 attempt，成功批次 checkpoint 可复用。模型结果
只落空间候选，任务完成不推进地图当前版本；不使用图片连接或新增队列基础设施。

RP max 沿用既有任务、lease、心跳与恢复策略；Interaction handler 通过 Project facade
传入冻结的900秒客户端超时，不延长失效lease，也不增加重试层数。

专项任务仍使用同一队列：`evidence_focused_search` 属于 Evidence compilation，额度为 9，
不新增 run 总 deadline；`targeted_completion`、`import_review_resolution` 属于 imports，均通过领域入口提交并
使用 manual_resume，但因运行期规模未冻结暂不建立 AI 运行信封。
通用 `/api/tasks` 不允许提交它们；状态响应隐藏 meta/result 顶层下划线内部字段。
查证 checkpoint 不给客户端回传为可修改状态，续查只接受任务标识并重验项目/来源/lease。

### 指定项目的单次任务执行

应用组合根创建的 Worker 可使用 `run_once(task_id=..., novel_id=...)`，两项必须同时提供且为
UUID。过滤在领取 SQL 中完成，只处理匹配的 pending 任务；不会领取、取消或修改其他排队任务。
不传参数仍是原队列领取方式。退避、coalescing、SKIP LOCKED、lease、preflight 和提交 fence
全部复用；该入口用于明确任务的手动验收，不是浏览器权限或项目边界的替代。

助手停止通过提交时保存的 `_parent_task_id` 查找 inline 子任务，范围仍含 novel_id；
不依赖稍后生成的证据回执。子任务 heartbeat 与取消清理绑定原数据库会话工厂；
父 lease 已失效时只允许按子 lease 完成终态清理，不提交领域写入。

普通 handler 失败保留由领域在 fenced checkpoint 中写入的匹配双恢复标记；只有 manual_resume 且 meta/result 同时为 true 才展示恢复。缺失或单边标记仍不授予恢复能力。

### 已完成阶段的领域继续

`resume_manual_task(..., allow_completed=True)` 是 Imports 已核验 deferred 阶段的窄继续入口；默认仍只恢复要求人工恢复的 failed task。调用方必须在同一事务持有项目与领域运行锁，确认范围、阶段和单飞后使用；队列仍执行 task type/novel、恢复策略与后继任务门禁。`list_recent_task_summaries` 只返回指定项目、任务类型的时间与状态，不暴露 meta/result。
### 共创回合恢复

`world_cocreation_turn` 使用 `auto_requeue`、至多两个 attempt 与现有 transport retry scope。World 持有业务判断，任务基础设施只提供 operation fingerprint、lease commit fence 和精确 `novel_id + task_type + session_id` 的最后操作查询；该类型禁止 generic submit。终态回合与可恢复结果原子保存，进度不等于采用内容；没有新任务表或调度器。design 精细模式把任务卡、初稿、两路审查、核验、返修、知识复审和终审按稳定阶段写入下划线私有 result；重排仅在输入 hash 相同时复用，公开任务响应继续过滤这些键。

### 知识治理阶段

长任务继续使用原 task/result/checkpoint 字段，可投影 `collecting_context / directing / generating / reviewing / repairing`。调度器不解释治理结论；业务域在 lease 内保存回执并在正式写入前重验。
