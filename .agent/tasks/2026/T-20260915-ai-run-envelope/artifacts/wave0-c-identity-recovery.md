# W0-C 只读核实：运行身份、持久化位置与恢复路径

> 调查基线：origin/main 5a2524dae（干净 worktree，git status 为空时采集）；文中 `backend/infrastructure/llm/agent_step_harness.py`、`schemas.py`、`workflow_budget.py` 三处的行号因 W1-Core 并发写入已位移，引用时请按新版本文件核对，其余全部文件行号仍等于该基线。

worktree `<repo>/.worktrees/ai-run-envelope`（分支 codex/ai-run-envelope，基线 origin/main 5a2524dae）。全程只读：未创建/修改任何文件，未运行 git 写操作、未安装依赖、未启动服务、未跑测试。路径均相对 worktree 根。

总览结论：**operation / run / task 三个身份在现有代码里不是三个独立对象，而是同一批 UUID 的不同投影**。Assistant 与 Imports 是"三个 ID 合一"，Interaction 与 Map 是"run 稳定、task 换行"。统一信封必须先接受这个既成事实，再谈分离。

---

## 1. operation identity（幂等键与 receipt）

### 1.1 通用 task 通道：operation_id 就是 AsyncTask.id
- `backend/infrastructure/tasks/enqueuer.py:114-167` `enqueue_operation_task`：`task_id = uuid.UUID(str(operation_id))`（124），先 `db.get(AsyncTask, task_id)` 命中即复用（126-138），否则用该 UUID 建 pending 行（139-151）；并发插入冲突走 `begin_nested` + `IntegrityError` 兜底再读回（148-166）。docstring 明说"包含 terminal tasks"（123）。
- 幂等校验：`enqueuer.py:86-95` `build_task_submission_fingerprint`（payload 规范化 sha256）；落库为 `meta["operation_fingerprint"]`（142）；`_validate_operation_task`（98-111）要求 `task_type / novel_id / operation_fingerprint` 三者一致，否则 `ValueError("operation_id cannot be reused with a different request")`（111）→ API 层转 409。
- 读回：`enqueuer.py:170-194` `get_operation_task`（可空 operation_id 直接返回 None，179-180）。
- 稳定 seam：`backend/infrastructure/tasks/facade.py:72-89`（enqueue_operation_task）、`92-119`（enqueue_task_with_optional_operation：**operation_id 为空时退化为普通 enqueue，无幂等**）、`122-136`（get_operation_task）。
- 另一条独立通道：coalescing key（非 UUID）。`enqueuer.py:28-50` sha256(task_type+novel_id+scope+version=1)；`259-322` 建/复用；`325-352` 查最新。注意 key 是 sha256 hex，`AsyncTask.coalescing_key` 有 pending/running 两个部分唯一索引（`backend/infrastructure/tasks/models.py:41-65`），且注释要求"不得进入公开响应或日志"（155-160）。

### 1.2 各领域 receipt 落点
| 领域 | 提交入口（先查后写） | 幂等字段来源 |
|---|---|---|
| Writing 冲突复核 | `backend/modules/writing/api.py:176-196`（get_operation_task）→ `208-244`（enqueue） | 客户端 `operation_id` |
| Writing 冲突建议 | `writing/api.py:301-341` | 同上（此处非空必填 327） |
| Writing 正文生成 | `backend/modules/writing/services.py:2571-2586`（可换用 `operation_payload` 做 identity，2572） | 客户端 `operation_id` |
| World 生成建议 | `backend/modules/world/api.py:723-767` | 客户端 `operation_id` |
| Story / Outline | `backend/modules/story/api.py:459-505`、`backend/modules/story/outline_state/api.py:171-232`、`382-449`、`896-937` | 客户端 `operation_id` |
| Assistant | `backend/modules/assistant/service.py:394-405`（按 `AssistantRun.id == operation_id` 先查）→ `479-502` | 客户端 `operation_id`（= AssistantRun.id = AsyncTask.id） |
| Assistant inline 子操作 | `backend/modules/assistant/operations.py:199-204` | **确定性 uuid5**：`uuid5(run_id, capability + fingerprint([args, preview]))` |
| Interaction | `backend/modules/interaction/services.py:2243-2257`（`_idempotent_attempt`） | 客户端字符串 `idempotency_key`（8-128），唯一约束 `(owner_id, idempotency_key)` `backend/modules/interaction/models.py:338-342` |
| Interaction see-sea 自动续写 | `interaction/services.py:2393` | 服务器派生 `f"see-sea:{journey.id}:{response_to.id}"` |

### 1.3 UUID 生成与复用规则（四种）
1. 客户端提供 → 直接当主键：`enqueuer.py:124`、`assistant/service.py:456-457`。
2. 服务器 uuid4：普通 enqueue `enqueuer.py:72-83`（`id=task_id or uuid.uuid4()`）；lease `models.py:172`。
3. 服务器确定性 uuid5：assistant inline 子操作 `assistant/operations.py:199-204`。
4. 内容摘要（非 UUID）：coalescing key `enqueuer.py:28-50`；task fingerprint `enqueuer.py:86-95`；Assistant `request_hash` `assistant/service.py:375-392`（并允许"web_backend 省略"的兼容哈希，377-392）。

### 1.4 重复请求如何命中同一次操作
- 有 operation_id：同一行返回 `CoalescedTaskContract(task_id, status, reused=True)`，**状态是当前真实状态**（可能是 done/failed/cancelled），不重新执行；fingerprint 不符则 409。
- Assistant：命中后还要求 `same_request`（request_hash 匹配）才返回既有 run，否则 409 `assistant_operation_changed`（`assistant/service.py:491-502`）。
- Interaction：命中即返回既有 attempt（**包含 failed**，`interaction/services.py:768-777`；continue 另有 `usage["continuation_keys"]` 去重 `1483-1488, 1501-1505`）。
- 无 operation_id：无任何幂等，每次都是新 task（`facade.py:110-119`）。

---

## 2. run identity（领域运行的模型、创建时机、起止边界）

### 2.1 五个身份对象
| 对象 | ORM | 创建点 | 与 task 的关系 |
|---|---|---|---|
| AssistantRun | `backend/modules/assistant/models.py:37-82` | `assistant/service.py:456-477`；后台 `assistant/proactive.py:376` | `run.id = operation_id = task.id`（456-457、479-486、504） |
| InteractionGenerationAttempt | `backend/modules/interaction/models.py:328-448` | `interaction/services.py:2300-2350`（`_create_attempt`） | `attempt.id ≠ task.id`；`attempt.task_id`（373-377，nullable+unique）在 2342-2348 指向一个**新建** task |
| ImportWorkflowRun | `backend/modules/imports/models.py:144-230` | `backend/modules/imports/workflow_runs.py:303-354`（唯一创建函数 `create_pending`） | `run.id = task_id`（326-329，注释 "workflow_id == task_id"）；`task_id` 唯一 FK CASCADE（173-178） |
| MapAtlasRun | `backend/modules/world/map_atlas_models.py:27-82` | `world/map_atlas_service.py:164-185`（主）、`835-842`（upload）、`1173-1185`（edit/regenerate） | `task_id` 可空、无唯一约束、FK SET NULL（45-50）；**同一 run 会被反复改绑新 task**：185/299/777/1105/1242 |
| 普通 AsyncTask | `backend/infrastructure/tasks/models.py:34-160` | `enqueuer.py:53-83` `_new_task` | run == task（无独立领域 run） |

### 2.2 一次逻辑运行的起止边界（按领域实际定义）
- **Assistant**：run 行从 `submit` 建 pending（`service.py:476`）到终态 `completed/waiting_approval/failed/cancelled/budget_exceeded`（CheckConstraint `models.py:46-50`）。同一 run 内可被 `resume_manual_task` 重排（`service.py:713-729`）；"续算"走 **新 run + 新 operation_id**（`RunResume.operation_id` 必填于 renew_budget，`backend/modules/assistant/schemas.py:80-89`；`service.py:678-703`，带 `continuation_of=run_id` 写入 payload，697/373-374）。
- **Interaction**：attempt 行是运行边界；`length` 截断时 `attempt.status="pending"` + `continuation_count += 1` + **换新 task**（`interaction/generation.py:1040-1059`；上限 1，1029-1039）；`awaiting_continue` 时用户点继续同样换新 task（`interaction/services.py:1506-1516`，上限 1，1492-1493）。同一 attempt 的旧 task_id **被覆盖丢失**。
- **Imports**：run 行是运行边界，`run.task_id` 不变；恢复只做 `generation += 1`（`workflow_runs.py:474`），队列行走 `resume_manual_task` 复用同一行（`backend/infrastructure/tasks/facade.py:176-190` → `lifecycle.py:187-190`）。
- **Map**：run 行是运行边界，可跨多个 async_tasks 行与多个 attempt；`stop_run` 只置 `stop_requested=True`（`map_atlas_service.py:217-231`），workflow 在页间置 `paused`（`map_atlas_workflow.py:2105-2109`）；`resume_run` 复用同一 run 但**入队新 task 并覆盖 `run.task_id`**（`map_atlas_service.py:296-299`，mode=`one_pending_follower`，helper 1537-1553，scope=("map_atlas_run", run.id)）。edit/regenerate 会**新建 run**（1173-1185）。结束 = status ∈ {review_ready, completed}（拒绝集 225，活跃判据 1516-1524）。
- **普通 task**：task 行自身即 run；无跨 attempt 的运行对象。

### 2.3 由此得到的关键事实（供信封设计冻结）
- `run_id` 与 `task_id` 在 Assistant / Imports 上**恒等**，在 Interaction / Map 上**分离**且 task 会换行。不存在统一的"task 属于 run"外键关系；只能按领域取 ID。
- 领域层已存在第二套 attempt 计数：Imports `generation`（`workflow_runs.py:336/474`）与 `owner_attempt`（`194-200`）；Map 靠 `run.task_id != task.id` 判出局（`map_atlas_workflow.py:330-331`）。AsyncTask.attempt 不足以表达跨 task 的运行进度。

---

## 3. task identity（attempt / lease / recovery_policy 与丢失路径）

### 3.1 字段与冻结
- `backend/infrastructure/tasks/models.py:122-160`：`attempt`（122-126，首次 claim 后为 1）、`max_attempts`（127-131，来自 TaskDefinition 冻结）、`recovery_policy`（132-137）、`lease_id`（138-144，String(36)）、`stale_detected_at`（145-149）、`transition_reason`（150-154）、`coalescing_key`（155-160，禁止外泄）。
- claim 时生成：`models.py:165-175` `mark_running(lease_id=str(uuid.uuid4()))`，attempt 自增 171，清 error/finished/transition_reason（173-175）。
- 定义来源：`backend/infrastructure/tasks/registry.py:38-86`（register）、`126-153`（`@task_handler`）；默认 `recovery_policy="restart_origin"`、`max_attempts=1`（43-44），`retry_transient_llm_errors=False`（47）。
- novel 身份冻结：`models.py:209-230` before_insert/before_update 钩子 + `identity.py:31-63`（`novel_id` 权威、`meta.novel_id` 只是兼容投影，更新时禁止漂移）。

### 3.2 worker 获取 / 心跳 / lease 丢失
- 领取：`backend/infrastructure/tasks/lifecycle.py:621-720` `claim_next`（`FOR UPDATE SKIP LOCKED` 695；重试退避 `_handler_retry_ready` 30-58；coalescing 门 660-717）与 `722-762` `claim_exact`（inline 用）。两者都在提交前 `mark_running`（718 / 760）。
- worker 侧：`backend/infrastructure/tasks/worker.py:489-516` `_claim_task`，`415-439` `_execute_claimed_task`（注入 task_scope 423-426、commit hook 427-429、progress hook 430-432）。
- 心跳：worker `786-815` `_heartbeat_loop`（独立 session，30s，`shared/constants.py:54`）；`lifecycle.py:764-785` `heartbeat` 以 `status=="running" AND lease_id==?` 为条件（777-781），**返回 False 即取消 runner**（worker.py:803-807）。
- lease-fenced 更新（已有实现，共 6 处）：
  1. `lifecycle.py:498-523` `checkpoint_running_attempt`（窄 merge：progress+result+meta+heartbeat_at，514-519）——唯一被 worker/inline 复用为"提交即 checkpoint"的通道；
  2. `lifecycle.py:764-785` heartbeat；
  3. `lifecycle.py:787-862` `finalize`（terminal 用 UPDATE…WHERE lease（844-853）；`status=="pending"`（重排）走 SELECT FOR UPDATE（798-828））；**lease 不符时 rollback 业务写入**（857-861）；
  4. `lifecycle.py:864-894` `requeue_transient_failure`；
  5. `lifecycle.py:309-337` `require_running_attempt`（SELECT FOR UPDATE + lease+attempt；不符 `raise asyncio.CancelledError` 337）；
  6. inline：`backend/infrastructure/tasks/inline.py:160-196` `_install_commit_fence`（每个 handler commit 先走 checkpoint，拒绝则 rollback+CancelledError 180-182）。
- 心跳丢失（stale）路径：`lifecycle.py:943-1010` `recover_stale`（阈值 `TASK_MAX_HEARTBEAT_GAP=120s`，`shared/constants.py:57`；`heartbeat_at < cutoff` 或 `heartbeat_at IS NULL AND started_at < cutoff`，954-958；skip_locked 960）；`_transition_stale` 1031-1096（清 `lease_id` 1055、写 `result["lifecycle"].transitions` ≤50 条 1036-1050、auto_requeue 且 attempt<max → pending 1057-1063，否则 failed 1064-1068，manual_resume 追加 interrupted/recoverable 标记 1070-1094）。
- 兜底：worker `888-903` `_recover_stale_task_transitions` + `reconcile_scoped_task_owners`（`897-901`），worker 启动/周期执行（`817-845` 附近）。
- inline 子任务：`meta["_execution_mode"]="inline_only"`、`meta["_parent_task_id"]`（`assistant/operations.py:211`、`writing/semantic_review.py:286-292`、`writing/services.py:2565-2570` 显式白名单校验）；父任务取消会级联取消子任务（`lifecycle.py:250-264`），父不可用时子任务被取消（`984-1007`）；inline 子任务必须与原 fenced parent + 共享 budget 同时存在（`inline.py:48-61`）。

---

## 4. 私有持久化位置（实际读写函数:行号）

### 4.1 AsyncTask.result / meta
- 写（成功）：`worker.py:601-618`——`result_data` 完全来自 handler 返回值，再 `merge_managed_llm_provenance`（606-610），然后 finalize `status="done"`；`lifecycle.py:840-841` `values["result"] = result_data` **整体替换**。
- 写（取消）：`worker.py:635-655`（handler 内 CancelledError）→ rollback → finalize cancelled + `result_data` = 旧 result 快照合并 provenance（636-643）。
- 写（失败/重排）：`worker.py:664-723` → `_handler_failure_result`（193-219，以 `_task_result_snapshot` 154-156 为底 + lifecycle）。
- 写（attempt 内渐进）：`lifecycle.py:498-523`（result/meta 窄 merge）；`lifecycle.py:116-122` `update_projection`（域侧维护公开投影）；`lifecycle.py:407-448` `replace_completed_result`（done 行 CAS + `updated_at` 单调，`_next_revision` 469-479）。
- 读：`lifecycle.py:339-405` `get_completed_payload`——**原样复制 result（398）与 meta 的特定键（376-393）**，不剥私有键；`tasks/api.py:305-306`（公开）；域内直读见 §7.2 清单。
- 私有键约定（现状）：`_execution_mode`、`_parent_task_id`、`_task_priority`、`_assistant_policy`、`_focused_request`、`_llm_execution_snapshot`、`_alias_relation_task_v1`（测试 `backend/infrastructure/tasks/tests/test_api.py:141-159`）；最接近 envelope 的先例是 `backend/modules/evidence/compilation/focused_tasks.py:156-157`（`"_focused_request"` + `"_llm_execution_snapshot"`）与 277/314 的回写。

### 4.2 managed_llm_steps（v0 兼容投影）全部读写点
- 键常量 `backend/infrastructure/llm/agent_step_harness.py:29` `MANAGED_LLM_PROVENANCE_KEY = "managed_llm_steps"`；ContextVar 55-58；采集 228-235；scope 238-246；合并去重 249-267（identity = step_name+novel_id+profile_source+profile_hash，204-210）。
- 生成：`run_managed_generate` 808-813、`run_managed_structured` 861-866（每次调用 `_collect_managed_llm_provenance`）。
- 写：`worker.py:606-610`（成功 result）、`637-643`（取消）、`669-675`（失败/重排）；`inline.py:98-102`（inline 成功）；**`backend/modules/story/tasks.py:442-443` 写进 task.meta**；`backend/modules/writing/semantic_review.py:1197` 写进 handler result。
- 读：`backend/modules/story/outline_state/story_outline_service.py:248-259`（采用前 **exact-key allowlist**）、`frontend-console/vue/views/outline/story/storyOutlineData.js:193-203`（浏览器 **exact-key allowlist**）、调用点 `frontend-console/vue/views/outline/story/useStoryOutline.js:155`、e2e mock `frontend-console/e2e/outline-scenes.spec.js:533-546`、测试 `frontend-console/tests/vue/outline/story/storyOutlinePreview.test.js:63`。
- 每 step 的 journal/quality_stats **不落库**：`run_managed_generate/structured` 用 `_unwrap_step_result`（`agent_step_harness.py:980-985`）只返回 `result.output`，`StepExecutionResult.journal_events`（417/721/750）与 `_quality_stats_with_runtime`（988-996）随之丢弃；`ManagedLLMStep` 在生产代码中无外部使用者（仅 `infrastructure/llm/__init__.py` 导出与测试）。

### 4.3 Assistant checkpoint_json
- 写：`assistant/service.py:184-200`（`record_run_event`，events/event_sequence）、`801-804`（evidence_refs）、`812`（model_history）、`989-992`（planned_answer）、`1075-1080`（planned_answer/quality_review_done/knowledge_review）、`1121-1124`、`1150-1154`（清 model_history）、`1184-1188`（清 planned_answer）、`1223-1226`（failure kind+frames）；`backend/modules/assistant/api.py:205-209`（stop 时清 model_history）。
- 读：`service.py:581-587`（读时清理）、`735-738`（events 游标）、`778-779`（saved_state）、`844-846`（evidence_refs 复用 + revalidate）、`984`（model_history 作为 agent state）、`1099`（knowledge_review）、`1177`（preliminary planned_answer）；`backend/modules/assistant/operations.py:389`、`487`（evidence_refs）。
- 公开性：`AssistantRun` 只经 `service.view`（`service.py:532-543`）出网，字段为 id/session_id/status/result/usage/error/task_id/can_resume/updated_at；测试 `backend/modules/assistant/tests/test_assistant.py:272` 断言响应中不含 `checkpoint_json` 与 `llm_snapshot`。

### 4.4 Interaction agent_checkpoint_json / usage
- 写：`interaction/generation.py:649-652` `_write_knowledge_hold`（knowledge_hold，ADR-0025 held release）、`498-507` 与 `525-530`（usage 首次写入）、`606-632`（usage token 累计 + continuation_keys）、`633` last_checkpoint_at；`backend/modules/interaction/agent_runtime.py:134-155` `checkpoint`（budget/references/model_history/knowledge_hold，usage 增量写回 138-146，`usage["agent_budget"]` 145）、`157-159` save_model_state。
- 读：`agent_runtime.py:124-132` `load`（state/budget(mode="rp")/references）、`136`（prior budget 做增量）、`150-152`（保留 hold）；`interaction/generation.py:643-646`；`backend/modules/interaction/runtime_policy.py:60-77` `clear_private_agent_state`（关闭时只保留 budget/evidence_receipts/knowledge_hold，**丢弃 model_history**）；调用点 `generation.py:1114`、`interaction/services.py:2662`。
- 公开性：attempt 经 `_attempt_response`（`interaction/services.py:1302` 附近，含 continuation_count 508）出网，`agent_checkpoint_json` 不出网；`streaming.py:38`/`repositories.py:27` 含 `awaiting_continue` 状态。

### 4.5 Imports workflow checkpoint
- ORM：`backend/modules/imports/models.py:206-230`（authorization_snapshot / llm_execution_snapshot / prepare_checkpoint / checkpoints / progress）。
- 写：`workflow_runs.py:341-350`（创建）、`408-439` `checkpoint`（progress 434、prepare_checkpoint 435-436、checkpoints 437-438；并回灌 completion_control 419-433）、`441-461` `complete`（449）、`463-479` `resume`（474-477）、`481-496` `abandon`；直写 `backend/modules/imports/orchestrator.py:1508-1515`、`1649`；`completion_control.py:59-66/123-135/156/160`；`review_resolution.py:796/1394/1613`；`targeted_completion.py:1205`。
- 读：`workflow_runs.py:498-527` `_attempt_from_run`（冻结整包）、`94-118` `meta_projection`（先回灌 prepare_checkpoint 再覆盖身份/snapshot）、`120-121` `progress_projection`；`orchestrator.py:84-98`（域视图）、`1329-1357`（由 progress 重建 DeepImportProgress）、`1393-1413`（恢复 llm snapshot，缺失回填 task.meta 1404-1407）、`1364-1390`（授权）、`1486-1552`（resume_interrupted）；`completion_control.py:13-22`（直接读 checkpoints 列）。

### 4.6 Map context_snapshot 等
- 写：`world/map_atlas_service.py:177-180`（创建，含 context_confirmation_id）、`771`（image_execution_snapshot）、`world/map_atlas_workflow.py:1369-1380 / 1433 / 1444 / 1481 / 1489 / 1549-1553 / 1570-1574`（spatial_evidence/knowledge_reviews）、`world/map_structure_images.py:150-159`。
- 读：`map_atlas_workflow.py:405-407`（confirmation）、`475`、`1235`、`1324`、`1341-1357`（上一 run + context_snapshot_id）、`1388-1392`（restore provider 设置）、`2075`；`map_atlas_service.py:121-122`（active run 比对）、`284/295`（resume 判分支）、`1620-1623`（`_run_dict`→evidence summary）；`map_structure_images.py:19`。
- `llm_execution_snapshot` 只在创建时写（`map_atlas_service.py:143-147/175`），edit/regenerate run 保持 `{}`。

### 4.7 Evidence ContextSnapshot provenance
- ORM：`backend/modules/evidence/compilation/models.py:199-281`；**无 run/attempt 外键**，运行绑定只有 `task_id`（242，String(64)，无 FK）与 `workflow_id`（243）、`phase`（244）、`operation`（245）、`attempt`（264，默认 1，生产未见传值）、`model`（267）、`prompt_hash`（265，唯一指纹列）。
- provenance 实际落在 JSON 列：`compile_options`（268）、`included_asset_ids`（269）、`excluded_asset_ids`（270）、`context_summary`（271）、`section_metadata`（272）、`token_metadata`（273）、`result_refs`（275）。
- 写：open `compilation/facade.py:1168-1176` → `services/snapshot_service.py:627-636`（独立事务）→ `90-138` → `repositories.py:180-237`（status="running" 220，prompt_hash 222）；succeed `facade.py:1209-1222` → `snapshot_service.py:638-652` → `repositories.py:283-355`（CAS `WHERE status=='running'` 315-325，同终态幂等 340-351）；fail `facade.py:1259-1274` → `snapshot_service.py:654-670` → `repositories.py:310-314`（error 先 `redact_diagnostic`，`snapshot_service.py:186-187`）。组装点 `services/generation_background.py:410-499`（compile_options 白名单 443-477、context_summary 479-492）、usage `145-178`（context_snapshot_id 166-170）。
- 读：`compilation/facade.py` 稳定接口 open_generation 1168 / succeed_generation 1209 / fail_generation 1259 / get 1277 / list 1290 / build_snapshot_health_summary 1309 / mark_stale_running_snapshots 1356 / prune_rendered_context 1373；`modules/evidence/facade.py:3-4` 只是星号 re-export。
- 上游关联（无 FK，全是 JSON/meta）：`interaction/models.py:425-432`（attempt.source_context_snapshot_id 唯一硬 FK）；`story/tasks.py:399-416` + `746-754`（task.meta/result）；`imports/entity_extraction/scene_entity_snapshots.py:68-69`（snapshot.task_id = workflow_id）；`world/services/worldbuilding/world_generation_center_service.py:1682`（content_json._meta.context_usage）；`map_atlas_workflow.py:1347`（run.context_snapshot.context_snapshot_id）。
- 反向归属靠字符串：`snapshot_service.py:375-405` 用 `list_task_lifecycle_contracts` 判 owner 任务终态/超时（stale_running / owner_task_stale / owner_task_terminal）。
- 维护态：running→failed 批量转换 `snapshot_service.py:342-364`；清理 `repositories.py:357-398`（keep-latest 200）。

### 4.8 _ai_run_envelope
- 基线 5a2524dae 上全仓库 **0 处**（grep 覆盖 backend/frontend/docs）。当时唯一"信封"是 `managed_llm_steps` 投影 + 各领域 JSON checkpoint。调查期间 W1-Core 已在 `infrastructure/llm/schemas.py` 引入 `AI_RUN_ENVELOPE_KEY = "_ai_run_envelope"` 与 `read_ai_run_envelope()`。

---

## 5. 公共 wire（GET /api/tasks/{id} 与 managed_llm_steps 暴露面）

- 投影函数：`backend/infrastructure/tasks/api.py:38-51` `_public_task_result`——**只剥离顶层 `_` 前缀键**；`54-58` `_public_task_meta` = 同一规则 + 额外 `pop("operation_fingerprint")`。
- 端点：`api.py:274-322` `GET /api/tasks/{task_id}?novel_id=`（owner+novel 门禁 285-289）；响应模型 `TaskStatusResponse`（161-179）含 meta/result/attempt/max_attempts/stale/lifecycle/available_actions。取消/重试 `325-392`。
- 现有测试固化：`backend/infrastructure/tasks/tests/test_api.py:126-159`（`_alias_relation_task_v1` 被剥离、`private-provider-receipt` 不出现在响应体）、`163-189`（`operation_fingerprint`、`_focused_request`、`_llm_execution_snapshot` 被剥离）。
- **缺口 1（现状即存在）**：`managed_llm_steps` **无下划线前缀，因此当前就出现在公开 result**（worker `606-610`；inline `98-102`；`writing/semantic_review.py:1197` 的 review result）；`story/tasks.py:443` 写进 meta 的那份也**出现在公开 meta**（`_public_task_meta` 只 pop operation_fingerprint）。浏览器确有消费者：`useStoryOutline.js:155` + `storyOutlineData.js:193-203`。也就是说"任务 wire 只暴露脱敏内容"这一前提在 `managed_llm_steps` 上已经不成立（内容本身是 allowlist 化的 profile 摘要，但字段确实公开）。
- **缺口 2（新增 envelope 的真实风险）**：域内采用路径读的是**未剥离**的 result：`lifecycle.py:394-405` `get_completed_payload` 把 `row["result"]` 整包（含 `_` 键）交给调用方；`story/outline_state/story_outline_service.py:248-259` 做 **exact-key allowlist**（`set(task.result) - allowed_result_fields` → `StoryOutlineConflictError`）。因此把 `_ai_run_envelope` 写进 task.result 会**直接打断 Story Outline 预览采用**，除非改 `get_completed_payload` 过滤私有键或扩 allowlist。
- 其余公开响应**不含 task.result**：域内回执 schema 一律 `{task_id, status}` —— `writing/schemas.py:433/615/767`、`story/schemas.py:321`、`story/outline_state/schemas.py:649`、`world/schemas.py:611`、`world/map_structure_schemas.py:394-397`、`project/schemas.py:240-250`（作者待办，与 AsyncTask 无关）。通用轮询器 `frontend-console/shared/workflowProgress.js:335-402` 容忍额外字段（无 exact-key 校验）。
- 前端 exact-key 校验只有一处：`storyOutlineData.js:110/193-203`（story outline 任务结果）。由于该路径读的是公开 API（`_` 键被剥离），只要 envelope 保持下划线前缀且**不新增非下划线顶层键**，前端不受影响；反之（把 v1 字段平铺进 result/meta 顶层）会同时打断前后端。
- 其它暴露面：task `meta` 中的 `llm_execution_snapshot`（非下划线，多领域，如 `story/outline_state/api.py:204-210`、`world/api.py:747-750`、`writing/api.py:214`）当前**公开**；而 focused 任务用 `_llm_execution_snapshot`（私有）。两种先例并存，envelope 放置位置需要裁决。
- 日志脱敏：`infrastructure/llm/redaction.py:39-50`（URL 去 query/凭据、Bearer/Authorization/api_key/sk-、控制字符）；task 错误信息 `worker.py:136-151`（DB 错误统一文案）。`redact_diagnostic` 只做字符串级替换，**不做键白名单**——envelope 必须自身只放 allowlist 字段。

---

## 6. 恢复路径矩阵（当前实际行为）

| 路径 | 触发/入口 | attempt | run/领域状态 | 计数与预算 | deadline | 证据 |
|---|---|---|---|---|---|---|
| success | handler 正常返回 | attempt 不变 | done；域 run 各自终态 | 成功 result **整体替换**（旧 result 丢失）；provenance 并入 | 无 | worker.py:601-618、lifecycle.py:840-841 |
| failure（handler 异常） | worker except Exception | 不增；auto_requeue 且 attempt<max → status=pending（同 task 行） | 无自动域收敛 | `_handler_failure_result` 以旧 result 为底 → 旧计数保留；managed steps 并入 | 无 | worker.py:664-723、lifecycle.py:798-828 |
| transient（LLM 可重试错误） | 仅 `retry_transient_llm_errors=True`（21 处定义） | 同上，transition_reason="transient_retry" | — | **不动 result**（旧计数保留） | 无 | worker.py:677-696、lifecycle.py:864-894 |
| cancel（用户） | `POST /api/tasks/{id}/cancel` | 不变 | cancelled；域侧各自响应 | 旧 result 保留 + provenance 合并 | 无 | tasks/api.py:325-361、lifecycle.py:227-280/896-913、worker.py:635-662 |
| cancel（父任务） | inline 父取消 | 子任务 cancelled | — | — | 无 | lifecycle.py:250-264 |
| heartbeat stale | worker 周期 recover_stale | 不变；auto_requeue 且 attempt<max → pending，否则 failed | `transition_reason="heartbeat_timeout"` | 旧 result/lifecycle 保留并追加 transitions（≤50）；写 interrupted/recoverable/recovery_summary | 无（清 heartbeat_at） | lifecycle.py:943-1010、1031-1096 |
| lease 丢失（in-flight 被抢） | 心跳 update 返回 False | — | **不写任何终态**：finalize 因 lease 不匹配被拒（accepted=False） | — | — | worker.py:803-807、lifecycle.py:854-862 |
| manual resume | `resume_manual`；Assistant `POST /runs/{id}/resume`、imports `resume_deep_import` | 不变（下次 claim 才 +1） | 同 task 行回 pending，`transition_reason="manual_resume"` | **不清 result**；Assistant 复用同一 `budget_json` 且先 `reserve()` 校验剩余时间/额度 | Assistant：deadline **不重置**（`started_at` 持久在 budget_json） | lifecycle.py:125-194、assistant/service.py:706-729、imports/orchestrator.py:1486-1552、workflow_runs.py:463-479 |
| auto_requeue | 仅 `recovery_policy="auto_requeue"` 的 task 类型（world 7 处、writing 5 处、story 4+4 处、project 1 处、evidence index 4 处、map 2 处、interaction 1 处） | attempt+1 on re-claim | 无域 run 概念 | 旧计数保留；退避 1/2/4/8/16/30s | 无 | lifecycle.py:27-58、registry 各处 |
| restart_origin | 只作为 `available_actions` 暴露 | 不变（task 停在 failed） | 域自行重提交 | — | 无 | lifecycle.py:1132-1133；frontend-console/README.md:346、docs/frontend-backend-gap-analysis.md:23 |
| operation replay | 同 operation_id 再提交 | 不变 | 返回既有 task/run/attempt 的**当前状态** | 不重置 | 不重置 | enqueuer.py:126-138/170-194；assistant/service.py:394-405/491-502；interaction/services.py:768-777 |
| Interaction length 续写 | 自动（see-sea）或用户 continue | **新 task**，attempt 不变，continuation_count+1（≤1） | attempt pending/awaiting_continue | usage 累计（token 累加），budget 存 `agent_checkpoint_json["budget"]`，关闭时保留 | AgentRunBudget 30 分钟窗口（`started_at`）在同 attempt 内不重置 | interaction/generation.py:1040-1059、services.py:1506-1516、agent_runtime.py:124-155、runtime_policy.py:60-77 |
| Map 恢复 | `resume_run`（需 `confirm_possible_duplicate_charge`） | 新 task；run 不变 | in_flight 页 `retry_requires_confirmation` → 确认后回 prepared；status generating/planning | 页级 possible-charge 状态保留 | 无 | map_atlas_service.py:233-301、map_atlas_workflow.py:2189-2205 |
| Imports 恢复 | `resume_deep_import` → `resume` | 同 task，`generation += 1` | run pending→running | checkpoints/prepare/progress **全部保留** | 无 | workflow_runs.py:463-479、orchestrator.py:1486-1552 |
| stale 子任务/孤儿 | recover_stale 后置扫描 | — | inline 子任务 cancelled（parent_unavailable） | — | — | lifecycle.py:978-1007 |
| 域任务 owner 收敛 | `reconcile_*_task_owners`（Interaction / Imports / Map 各一） | — | 由队列终态反向收敛域 run | — | — | interaction/services.py:2604-2667、workflow_runs.py:225-287、map_atlas_workflow.py:2147-2213 |
| Evidence snapshot 维护 | `mark_stale_running_snapshots` / daily maintenance | — | running → failed（stale_running/owner_task_stale/owner_task_terminal） | — | — | snapshot_service.py:342-413、facade.py:1356/1394 |

**没有"重置预算/计数"的自动路径**——除 Assistant 显式 `renew_budget` 会**新开 run + 新 operation_id**（`assistant/schemas.py:85-89`、`service.py:678-703`）。这是既有"授权变更必须新 run"的先例，与计划中 `authorization_revision` 的意图一致。

---

## 7. 旧在途兼容（legacy 识别与既有消费者）

### 7.1 现网可用的"版本标记"清单（都不是 run envelope 版本）
- 无任何 task 级 envelope 版本字段；`_ai_run_envelope` 缺失即唯一可判据。
- 已有可借用标记：Assistant `request_json["runtime_version"]=="3"`（`assistant/service.py:465`）；Interaction `llm_execution_snapshot["agent_runtime"]` 版本策略（`interaction/runtime_policy.py:80-101`）与 `version="anonymous-rp-v1"`（13-40）；task meta `llm_execution_snapshot`（各领域，非下划线）与 `_llm_execution_snapshot`（focused）；Imports `authorization_snapshot`/`workflow_runs.generation`；Map `context_snapshot` + 页级 `provider_in_flight/retry_requires_confirmation`。
- 结论：legacy 判定只能"无 envelope 键"⇒ v0；但**必须与"v1 但零 step"区分**（例如 v1 启动即失败），否则 `usage_complete=false` 会被误标。需要主 Agent 明确选择：写入即落空 envelope（推荐）还是靠额外版本键。

### 7.2 既有消费者（envelope 改动必须保持工作的读路径）
- 通用公开读：`tasks/api.py:305-306`（`_` 剥离）、`frontend-console/shared/workflowProgress.js:335-402`（浏览器轮询，读取 result 的 summary/phase/acceptance 等）。
- **原始 result 读（含 `_` 键，风险最高）**：`lifecycle.py:394-405` → 消费者 `writing/assistant_tools.py:194-196`、`writing/assistant_candidate_tools.py:90`、`writing/assistant_generation_tool.py:158`、`writing/semantic_review.py:1251-1255`、`project/smart_dedup.py:213-215/283-285`、`project/assistant_dedup_tool.py:72`、`evidence/compilation/focused_tasks.py:183/212`、`story/assistant_structure_workflow.py:186/223`、`story/service.py:181`、`story/outline_state/ai_workflow_service.py:605`、`world/map_structure_service.py:800`、`interaction/proactive.py:307`、`story/outline_state/story_outline_service.py:230`（**exact-key 校验**）、`story/outline_state/p20_service.py:516`。
- handler 内直读 `task.result`/`task.meta`（沿用私有键做断点续跑）：`imports/orchestrator.py`（154、159、496、521、640、694、852-887、967、1010、1102、1169、1330-1408）、`imports/targeted_completion.py:680-686`、`imports/review_resolution.py`（423-664、871-892、1003-1284）、`imports/entity_extraction/*`、`world/tasks.py`（46-749 多处）、`world/map_structure_workflow.py:610/629/766`、`world/map_atlas_tasks.py:46/77`、`story/tasks.py`（282/400-443/719/736）、`story/outline_state/tasks.py`（78-361）、`writing/tasks.py:43-369`、`evidence/indexing/tasks.py:30-192`、`evidence/compilation/focused_tasks.py:242-298`、`interaction/generation.py`（308、1252、1538、1762、1806）、`interaction/tasks.py:50`、`assistant/service.py:750`、`project/tasks.py:17-36`。
- 结论：直接"把 envelope 塞进 result/meta 顶层"会同时影响这 30+ 读取点；用 `_` 前缀可让它们全部忽略（无 exact-key 校验者），但 Story Outline 的 `get_completed_payload` 路径必须单独处理（见 §5 缺口 2）。

---

## 8. 与预期不符、需要主 Agent 决策的疑点

1. **`_ai_run_envelope` 写进 task.result 会打断 Story Outline 采用**（`story_outline_service.py:248-259` 的 exact-key allowlist 吃的是 `get_completed_payload` 的未剥离 result）。计划只声明"复用 result/meta 的 `_ai_run_envelope`"+"`_public_task_result()` 继续剥离"，但**域内采用路径不经过 `_public_task_result`**。需裁决：在 `get_completed_payload` 过滤私有键（改 infrastructure 契约，影响 15 个消费者）／扩 allowlist（改 story 域）／其他。
2. **成功路径整体替换 task.result**（`worker.py:601-618` + `lifecycle.py:840-841`）。若某 attempt 通过 checkpoint 写了 `_ai_run_envelope`，成功 finalize 时会被 handler 返回值覆盖而丢失（`merge_managed_llm_provenance` 之所以安全，是因为它显式并入 `result_data`）。计划中"成功/失败/取消/stale 合并同一 run"需要在 worker 成功分支显式并入 envelope，且要与"不覆盖 handler 业务事务"（128 行）相容。
3. **lease 已丢失时没有终态写入路径**：心跳被拒只 cancel runner（`worker.py:803-807`），随后 finalize 因 lease 不匹配 rollback 返回 False（`lifecycle.py:854-862`）。于是"取消/中断也写回执"在这条路径上无落点。需决定 envelope 是否接受"该 attempt 的回执只存在于 stale 转换写下的 result（`_transition_stale`）"。
4. **`managed_llm_steps` 当前就在公开 wire 上**（result 与 meta 两处，§5 缺口 1），且浏览器 Story Outline 用 **exact-key** 校验顶层键集合。计划说"v1 从同一 envelope 派生、现有消费者不得因新增字段失败"——若 v1 在**列表元素内**加字段没问题，若在**顶层**加非下划线键会同时打断前后端。需冻结"顶层只允许 `managed_llm_steps` 一个兼容键、其余全部下划线私有"这条不变量，并明确记录它是既有事实而非新增。
5. **operation / run / task 三身份在 Assistant 与 Imports 上恒等**（Assistant：`operation_id == AssistantRun.id == task.id`，`service.py:456-457/479-504`；Imports：`run.id == task_id`，`workflow_runs.py:326-329`），而在 Interaction / Map 上 run 持续、task 换行（`generation.py:1051`、`services.py:1516`、`map_atlas_service.py:299`）。计划里"task_id 只表示执行载体、不替代 run 身份"在这两个领域**没有承载物**——不存在独立的 run_id 列。需决定：接受"恒等即合法"并在文档中写死，还是要求新 envelope 自行携带 `run_id`（不新增列也能做，但 Assistant/Imports 无法与 operation 区分）。
6. **Interaction 没有 failure→resume 的领域路径**：story task 是 `restart_origin`（`interaction/tasks.py:38-39`），失败/中断后 attempt 由 reconciler 置 failed（`services.py:2657-2662`），用户只能 regenerate（新 attempt）。重放同一 idempotency_key 会直接返回那个 failed attempt（`services.py:768-777`），不会重跑。所以"manual resume 保持同一 run"对 Interaction story 不成立，只有 length 续写（`continuation_count`，上限 1）保持同一 attempt。
7. **Imports 的第二次 attempt 计数在领域列**（`generation`，`workflow_runs.py:474`）而不是 AsyncTask.attempt；**Map 的 attempt 边界靠 `run.task_id != task.id`**（`map_atlas_workflow.py:330-331`）。信封若只用 `task_attempt` 表达"第几次 provider 尝试"，两者都会算错（Imports 会把跨 generation 的同一 task 视作同一次；Map 会在换 task 后把 attempt 重置）。
8. **Evidence ContextSnapshot 没有可复用的运行绑定**：只有 `task_id`(String(64)，无 FK) / `workflow_id` / `phase` / `operation` / `attempt`(生产恒 1)。计划说"同步 Evidence 任务使用 ContextSnapshot provenance"，但快照行既无 run_id 也无 fingerprint 列，来源指纹散落在 `compile_options` 的多个 hash 键（`generation_background.py:443-477`）与 `context_summary["fingerprint"]`（RP，`interaction_story_context.py:457`）。需裁决：envelope 只把 snapshot_id 作为 step receipt 的一个字段回指，还是要求 Evidence 侧新增统一 provenance 投影（不新增列的前提下只能约定 JSON 键名）。
9. **legacy 判定缺少可靠标记**：除"无 `_ai_run_envelope`"外无任何 task 级版本字段。计划要求"旧在途 task 首次进入 v1 时标记 `legacy_untracked/usage_complete=false`"，但无法区分"v0 旧任务"与"v1 新任务尚未产生任何 provider 请求"。需决定是否在 run 首写时就落一个 `version=1 + requests_started=0` 的最小信封（这样"无键"就唯一等价于 v0）。
10. **task meta 存在两种 snapshot 私有性先例**：多数领域把 `llm_execution_snapshot` 明文放 meta（公开），focused 用 `_llm_execution_snapshot`（`focused_tasks.py:156-157`）。envelope 放 result 还是 meta、是否下划线，都会与其中一种先例冲突；且 `_public_task_meta` 目前只 pop `operation_fingerprint`。建议明确"私有运行态一律下划线 + result"并作为不变量，但需要主 Agent 确认这不是对外契约破坏（`managed_llm_steps` 已在 meta 有非下划线先例）。
11. **`restart_origin` 只有声明没有实现**（`lifecycle.py:1132-1133` 只把它放进 `available_actions`；前端文档明确它"走各自领域流程重新提交"，`frontend-console/README.md:346`、`docs/frontend-backend-gap-analysis.md:23`）。信封的"restart 不重置 run"需要说明：真正的 restart 由领域新提交产生**新 operation/新 run**，不在信封职责内。
12. **Assistant 的 `resume` 有两条语义**：不续算时复用同一 task+run 并复用同一 `budget_json`（先 `reserve()` 校验，`service.py:706-712`）；续算时**新 run + 新 operation_id**（`schemas.py:85-89`）。信封的 `authorization_revision` 需要同时覆盖这两条（前者不能加额度，后者是新 run），且 `previous_run_id` 只能从 `request_json["continuation_of"]`（`service.py:373-374`）取——该键目前只是 payload，不是列。
13. **`AgentRunBudget` 不是全领域通用**：deadline 是 `started_at + 30min` 的 wall-clock（`agent_runtime.py:80-85`），只被 Assistant（`budget_json`）与 Interaction agent（`agent_checkpoint_json["budget"]`）持久化；普通 task 完全没有预算/期限载体。`WorkflowBudget` 只是把 `AgentRunBudget` 挂到 ContextVar 的适配器（`workflow_budget.py:15-65`），自己不做持久化。信封若宣称"全部通道共用 deadline"，需要先把普通 task 的 deadline 落点定下来（只能在 result/meta 的私有键里）。
14. **provider possible-charge 的既有语义是页级而非请求级**（Map：`provider_in_flight`→`retry_requires_confirmation`，`map_atlas_workflow.py:1831/1866-1907/2022-2035`；`image_client.py:47-52/102/120/246-260`）。信封的 `charge_state` 需要与这套页级确认语义对齐，否则 `possible` 会在 Map 恢复时被重复呈现。

---

### 附：本次核实方法与限制
- 只读手段：grep/read + 两个只读子代理（Evidence snapshot provenance、Imports/Map run 恢复），子代理结论已由我抽样复核（`workflow_runs.py:326-329/463-479`、`map_atlas_service.py:233-301/1537-1553`、`evidence/compilation/models.py:224-281`、`workflow_runs.py:124` 逐行确认）。
- 未运行任何 pytest（任务允许但为节省时间未跑），因此"现有测试会/不会失败"的判断来自代码路径与断言文本，不含实际执行证据。
- 未核对 Alembic migration 与 ORM 的逐字段一致性；未核实生产库中是否存在历史遗留的意外 meta/result 形状。
- `backend/modules/imports/orchestrator.py` 的行号来自子代理且我仅部分复核（2127-2143、1486-1552、1329-1357 未逐行读）。
