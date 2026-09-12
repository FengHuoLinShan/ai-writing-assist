# D5b 槽位报告（R07：imports 工作流状态 / API / 审核减负）

日期：2026-09-11。基线：`main` @ `e7d0b8d5b`；`api.py` 与 `tests/test_import_api.py`
含他任务未提交 WIP（路由顺序修复），按工作树审查并标注，不做 HEAD/WIP 拆分修复建议。
全部只读；未运行测试/构建/make，无网络。73 个路径逐一覆盖；生产码逐文件语义阅读，
大文件（orchestrator 2155 行、workflow_llm_adapters 2001 行、review_resolution 1640 行）
全量读毕，测试文件按定向映射抽查（import 面 + 关键断言定位）。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/imports/AGENTS.md,已审,make docs-check / 开发者,无发现：约束与当前实现一致（run 授权快照、fail-closed、恢复语义均已在代码核实）
backend/modules/imports/CLAUDE.md,已审,宿主导入,无发现：单行 @AGENTS.md re-export
backend/modules/imports/README.md,已审,make docs-check / 开发者,无发现：API 面、恢复语义、专项补全、审核减负章节与代码逐项核对一致；阶段预算描述与 shared/deep_import_settings.py 默认表一致
backend/modules/imports/__init__.py,已审,模块命名空间,无发现：docstring 提及 mobi 支持与 README"未验收格式"口径略宽，仅文档措辞
backend/modules/imports/adoption_policy.py,已审,orchestrator/facade/assistant_tools、test_adoption_policy,无发现：授权快照构造 fail-closed；asset_summary 三态互斥且有 legacy 分支保留
backend/modules/imports/api.py,已审（含 WIP 改动）,app.main 路由注册 / 前端,D5b-2；D5b-3（WIP 路由顺序修复本身正确）；其余门禁（active/exclusive/owner-404 统一）无缺陷
backend/modules/imports/assistant_tools.py,已审,modules.assistant OPERATIONS 注册面 / tasks.handle_imports_completion_review / source.changed 观察者,无发现：preview==apply 重验、imports.resume 沿用原授权、完成回执只投影不审稿
backend/modules/imports/contracts.py,已审,interaction/RP（SourceUpdate*）、api.py（TaskNotFoundError）,无发现：frozen dataclass；MAX_IMPORT_FILE_SIZE 与 parsers 白名单一致
backend/modules/imports/env_helpers.py,已审,service_phase_artifacts、D5a 旋钮函数、test_workflow_llm_runtime,无发现：空串/非法值回默认，仅代码审查未读 env 值
backend/modules/imports/facade.py,已审,跨模块 seam（assistant/proactive、interaction、app 装配）,无发现：薄代理符合分层；get_active_organization 读领域 run（A1-3 结论见复核节）
backend/modules/imports/orchestrator.py,已审,facade + tasks 6 个 handler,D5b-1（resume 后 failed phase 死循环）；D5b-8（start/start_stage 与 _record_progress 闭包重复）
backend/modules/imports/review_resolution.py,已审,orchestrator.run_stage_task(review_resolution)、api 端点、assistant imports.resolve_review,D5b-2（ValueError→500 的两个触发点在此文件）；确认/预算/资格门禁语义无缺陷
backend/modules/imports/review_resolution_quality.py,已审,review_resolution.run_resolution eligible 分支,无发现：QUALIFIED_RUNS 空表 fail-closed，prompt/profile/model 三元隔离
backend/modules/imports/review_resolution_schemas.py,已审,api 请求体 / judge 输出 schema / judgment_outcome,无发现：judgment_outcome 证据不验→incomplete、冲突→decision、不足→optional 的失败关闭顺序正确
backend/modules/imports/schemas.py,已审,api/services/assistant_tools,D5b-6（ImportedChapterResponse/ListResponse 生产零引用）
backend/modules/imports/service_phase_artifacts.py,已审,D5a 服务路径 + workflow_scene_phase,无发现：敏感键脱敏、禁止正文键、32KB 预算截断闭环
backend/modules/imports/service_progress_limits.py,已审,workflow_progress/D5a,无发现：三数组有界且保留 dropped 计数
backend/modules/imports/service_progress_logs.py,已审,workflow_progress/D5a,无发现：事件/门禁写入均经 sanitize 与截断
backend/modules/imports/services.py,已审,api.py + facade,无发现：savepoint 隔离解析失败、IntegrityError 并发去重、错误文案不泄 SQL
backend/modules/imports/source_update.py,已审,facade（interaction RP source revision）,无发现：preview hash 覆盖 base_manifest/changes、apply 重验 hash + exclusive 锁 + destructive 二次确认
backend/modules/imports/tasks.py,已审,任务注册面（7 个 handler，均 manual_resume）,A1-5 领域侧登记（4 个 handler else 分支，唯一触发方为直调 handler 的测试）；X1-8 消费点之一
backend/modules/imports/tests/__init__.py,已审,pytest 包标记,无发现：空文件
backend/modules/imports/tests/conftest.py,已审,模块测试 fixtures,无发现：复用根 db_session，样例语料无真实数据
backend/modules/imports/tests/test_adoption_policy.py,已审（定向）,adoption_policy,无发现：三态/快照断言有效
backend/modules/imports/tests/test_alias_relation_task_workflow.py,已审（定向映射，属 D5a 实现域）,entity_extraction Phase2b task,无发现（本槽位范围外深审归 D5a/E1）
backend/modules/imports/tests/test_assistant_recovery.py,已审（定向）,assistant OPERATIONS imports.resume,无发现：恢复沿用原授权断言有效
backend/modules/imports/tests/test_chapter_loader.py,已审（定向映射，D5a）,chapter_loader,无发现
backend/modules/imports/tests/test_completion_control.py,已审（定向）,completion_control + workflow_runs checkpoint 合并,无发现：作者 defer 控制不被 worker 覆盖的断言在位
backend/modules/imports/tests/test_custom_entity_type_boundary.py,已审（定向映射，D5a）,entity 类型系统门禁,无发现
backend/modules/imports/tests/test_deep_import_dedup.py,已审（定向映射，D5a）,deep_import_dedup,无发现
backend/modules/imports/tests/test_deep_import_retry.py,已审（定向映射，D5a）,deep_import_retry,无发现
backend/modules/imports/tests/test_import_api.py,已审（含 WIP 改动）,api.py HTTP 契约,D5b-3 佐证（WIP 新增 review-summary 路由遮蔽回归测试）；404 不泄漏 owner/meta 断言有效
backend/modules/imports/tests/test_imports.py,已审（定向）,parsers/services/repositories,无发现：happy path/空内容/非法类型覆盖
backend/modules/imports/tests/test_imports_integration.py,已审（定向）,workflow 全链集成,无发现：复用 phase 实现的集成断言在位
backend/modules/imports/tests/test_phase1a_context.py,已审（定向映射，D5a）,phase1a_context,无发现
backend/modules/imports/tests/test_phase1b_prompt_p11.py,已审（定向映射，D5a）,workflow_llm_adapters P11 prompt,无发现
backend/modules/imports/tests/test_phase2_dedup_pipeline.py,已审（定向）,workflow_entity_phase dedup 管道,无发现
backend/modules/imports/tests/test_phase2_scene_tag_inclusion_p11.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_phase2b_v2.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_post_import_adoption.py,已审（定向）,orchestrator._assemble_post_import_package,无发现：best-effort 包失败不改变导入终态的断言在位
backend/modules/imports/tests/test_real_file_import.py,已审（定向）,parsers 真实文件,无发现：未 mock 真实文件验收符合 README 口径
backend/modules/imports/tests/test_relation_provenance.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_review_resolution.py,已审,review_resolution,无发现：预算共享/资格不继承/补查不重复消费断言有效（D5b-1 的 review_resolution 路径不受 run_step 门禁影响）
backend/modules/imports/tests/test_review_resolution_foundation.py,已审（定向映射，D5a）,scene_slicing,无发现
backend/modules/imports/tests/test_scene_commit.py,已审（定向映射，D5a）,scene_commit,无发现
backend/modules/imports/tests/test_scene_enrichment_p11.py,已审（定向映射，D5a）,scene_enrichment,无发现
backend/modules/imports/tests/test_scene_entity_extraction.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_scene_entity_llm_adapters.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_scene_entity_text.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_scene_entity_workflow.py,已审（定向映射，D5a）,entity_extraction,无发现
backend/modules/imports/tests/test_scene_fusion.py,已审（定向映射，D5a；D5a-2 旧 reducer 所在）,scene_fusion,无新发现（D5a-2 已登记）
backend/modules/imports/tests/test_scene_fusion_phase1c.py,已审（定向映射，D5a）,scene_fusion_phase1c,无发现
backend/modules/imports/tests/test_scene_phase_refactor.py,已审（定向）,scene 阶段重构回归,无发现
backend/modules/imports/tests/test_scene_slicing_p10.py,已审（定向映射，D5a）,scene_slicing/llm_adapters,无发现
backend/modules/imports/tests/test_scene_stage_task_transactions.py,已审（定向）,orchestrator fenced scene stage 事务,无发现：prepare/commit/漂移拒绝断言有效；13 处直调 run_task/run_stage_task（不经 handler else）
backend/modules/imports/tests/test_source_update.py,已审（定向）,source_update,无发现：hash 漂移/destructive 确认断言在位
backend/modules/imports/tests/test_structure_quality_gate.py,已审（定向）,workflow_structure_phase,无发现
backend/modules/imports/tests/test_targeted_completion.py,已审（定向）,orchestrator/targeted_completion,无发现
backend/modules/imports/tests/test_targeted_completion_integration.py,已审（定向）,orchestrator+workflow_runs 集成,无发现：单飞/恢复断言在位
backend/modules/imports/tests/test_workflow.py,已审（定向，4641 行）,workflow 全部阶段,兼容 adapter 测试（:316-395）与 monkeypatch seam 测试（:941、:3384）为 D5b-4/D5b-5 唯一消费者；failed-phase 拒绝测试固化了 D5b-1 的一半契约
backend/modules/imports/tests/test_workflow_llm_runtime.py,已审（定向）,workflow_llm_adapters env 旋钮,无发现
backend/modules/imports/tests/test_workflow_orchestration.py,已审（定向，1686 行）,orchestrator 编排,无新发现：resume 测试只断言队列级恢复，未覆盖 D5b-1 的重跑路径（漏测点）
backend/modules/imports/tests/test_workflow_runs.py,已审,workflow_runs,D5b-9 佐证（reconcile 参数无效不影响现有断言）；owner/generation CAS 断言完整
backend/modules/imports/workflow.py,已审,orchestrator,D5b-4 佐证；D5b-5 佐证（re-export）；D5b-6（死 _accepts_keyword）；D5b-7（8 个转发方法）
backend/modules/imports/workflow_entity_phase.py,已审,workflow phase runner seam,无新发现：2 处 except Exception 均为降级统计+失败收敛，非吞异常
backend/modules/imports/workflow_llm_adapters.py,已审,workflow.py 各阶段 + D5a,D5b-5（_workflow_constant/_call_structured seam）；D5b-11（setdefault 死行、del 参数 seam）
backend/modules/imports/workflow_phase_runner.py,已审,workflow.py 与各 phase 文件的请求/Protocol seam,无发现：frozen dataclass + 泛型 Protocol 与 README 描述一致
backend/modules/imports/workflow_progress.py,已审,workflow.py/各 phase/assistant_tools,无发现：诊断计数单一权威 refresh；_redact_checkpoint_strings 有深度上限
backend/modules/imports/workflow_runs.py,已审,tasks._claim_workflow_attempt/orchestrator/facade/run_worker startup,D5b-9；其余 owner/generation/CAS/恢复语义无缺陷（详见共享事实）
backend/modules/imports/workflow_runtime.py,已审,各 phase runner 的 Protocol,无发现：私有方法名兼容是文档化决定（docstring 自述为 monkeypatch 测试保留）
backend/modules/imports/workflow_scene_phase.py,已审,workflow.py scene_full runner,D5b-10（iscoroutinefunction(db.add)）；D5b-5 同族（_phase0_422_recommendation 动态反查）；失败收敛路径与 D5b-1 相关
backend/modules/imports/workflow_schemas.py,已审,全模块进度契约,无发现：phase/quality_status/current_phase 三词汇分立且 description 注明取值域
backend/modules/imports/workflow_structure_phase.py,已审,workflow.py structure runner,无新发现：失败/保底路径与 artifact 门禁闭环
```

## 发现

### D5b-1
- **ID**：D5b-1
- **位置/符号**：`backend/modules/imports/orchestrator.py:1368-1396` `_progress_from_task`（仅 `phase=="running"` 或「有 targeted_completion checkpoint 且 failed」时归一为 pending）；`backend/modules/imports/workflow.py:272-273` `run_step` 的 `raise ValueError(f"无法处理当前进度状态: {progress.phase}")`
- **问题与触发（X2 链复核修正）**：原文所称“任何优雅失败都会形成 resume 死循环”过宽。普通优雅失败持久化 `phase="failed"` 时 `recovery_required=false`，只提供 dismiss，直接调用 resume 也会被拒绝。真实触发需要 `phase="failed"` 与 `recovery_required=true` 同时保留；当前可达入口是优雅失败已提交、worker 尚未终态化时进程死亡，stale 扫描再把任务标成可恢复。用户只有一次 resume 机会，但 `_progress_from_task` 在无 targeted_completion checkpoint 时不归一 phase，`run_step` 立即再次失败；第二次失败收敛为 dismiss-only，resume/abandon 与批量清理入口一起丢失。targeted_completion 已有特例，standalone review_resolution 不经 `run_step`，均不属于该窗口。完整证据见 `units/X2.md` 的“失败三类”。
- **调用链证据**：失败持久化：orchestrator.py:594-598（run_task）、:825-829（run_stage_task）、:998-1002（fenced scene stage）均先 `_record_progress`（内含 `task.result = updated.model_dump()` + `_runs.checkpoint` + `db.commit()`）再抛错；worker 侧 `_handler_failure_result`（infrastructure/tasks/worker.py:193-219）只追加 lifecycle 元数据不改 phase；恢复链 orchestrator.py:1525-1589 `resume_interrupted` 与 infrastructure/tasks/lifecycle.py:125-199 `resume_manual` 均不重置 phase。测试固化了「failed 不自动重跑」（test_workflow.py:3949-3958）与「失败持久化 phase=failed」（test_workflow_orchestration.py:1454-1470），但无任何测试覆盖 fail→resume→重跑成功；resume 测试 fixture（test_workflow_orchestration.py:320-360）的 result 恰好不含 phase 键，掩盖了该路径。
- **现有契约**：README「任务在 available_actions 含 resume+abandon 时展示恢复操作；resume 校验 failed 与双份 recovery flag 后转回 pending，不伪装成仍在 running」；`_progress_from_task` 对 running→pending 的归一说明中断重跑是受支持语义。failed 不可直接重跑（test_rejects_failed_state）针对的是程序内直接重入，不是人工恢复。
- **最小方案**（功能性修复，按计划 §2 单列，不混入优化批次）：在恢复链单点归一——`resume_interrupted` 组装 `result_data` 时（或 `_progress_from_task` 的归一条件改为「`phase=="failed"` 且本次为 manual_resume 恢复的 attempt」）把 `phase` 置回 `"pending"`（保留 `phase_errors`/`quality_status` 诊断）；补一条 fail→resume→handler 重跑的回归测试。
- **预期收益**：窄中断窗口的一次恢复机会可用；避免恢复后立即失败并丢失 abandon/批量清理入口，同时不改变普通 dismiss-only 失败语义。
- **风险**：需保证不把「未恢复意图的 failed」自动重跑——归一必须只发生在显式 resume 路径；fenced scene stage 的 prepare 指纹校验不受影响（phase 与 input_fingerprint 正交）。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_workflow_orchestration.py modules/imports/tests/test_workflow_runs.py"`；新增断言：构造 run.progress.phase="failed"+recovery_required → resume_interrupted → claim → run_task 不抛「无法处理当前进度状态」。
- **回滚**：单点 revert（orchestrator 一处归一 + 一个测试）。
- **裁定**：功能性缺陷，单列修复任务（按 §7 属恢复能力破坏；触发窗口窄但后果确定，维持 P1）
- **优先级**：P1

### D5b-2
- **ID**：D5b-2
- **位置/符号**：`backend/modules/imports/api.py:546-557` `rollback_review_resolution`、`:560-571` `decide_review_resolution`（均无 ValueError 捕获）；触发点 `backend/modules/imports/review_resolution.py:725-731`（`rollback_resolution` 的 `raise ValueError("整理记录不存在")`）、`:1260-1262`（`accept_decision` 同文案）、`:1377-1378`（`inspect_resolution`）；兜底 `backend/app/main.py:601-617` 全局 500
- **问题与触发**：对不存在或不属于该项目的整理任务调用 `POST /api/imports/review-resolutions/{task_id}/rollback` 或 `/decisions`，领域层抛裸 `ValueError`，api 层未映射，落到全局 handler 返回 500「服务器内部错误」并记 error 级堆栈。同文件内同类条件语义不一：targeted-completions rollback 映射 404/409（api.py:447-464），scene-groups apply 用 `ConflictError`→409（api.py:574-588 + review_resolution.py:1494-1496），resume/abandon 用 `TaskNotFoundError`→404（api.py:360-417）。
- **调用链证据**：api.py 三个 review-resolution 端点中仅 submit 有 `_validate_chapter_count_limit` 的 DomainValidationError（DomainError handler 可映射）；rollback/decisions 的 `require_active_project_exclusive` 通过后，`run is None or str(run.novel_id) != novel_id` 走 ValueError 分支（review_resolution.py:727-731）。
- **现有契约**：README 安全节「不存在任务与归属不可访问统一 404，避免泄漏任务存在性」——该契约在 resume/abandon/targeted 已实现，review-resolutions 两个端点偏离（500 既泄露「服务端异常」又不符 404 统一口径）。
- **最小方案**（功能性修复单列）：与 targeted-completions 对齐——api 层捕 `ValueError`→404（不存在/归属不符）与 `ConflictError`（已有 409 通道）；或领域层改抛 `TaskNotFoundError`/`ConflictError`。响应码变化属可见行为变更，需按功能变更评审，不并入纯优化批次。
- **预期收益**：错误口径统一、消除正常用户输入触发的 500 与 error 级日志噪音。
- **风险**：前端若对 500 有分支需同步；404 统一口径不回显存在性，需保持文案。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_import_api.py modules/imports/tests/test_review_resolution.py"`；新增断言：未知 task_id 的 rollback/decisions 返回 404 且 body 不含 owner/meta。
- **回滚**：单端点 revert。
- **裁定**：实施候选（按功能变更处理响应差异）
- **优先级**：P2

### D5b-3
- **ID**：D5b-3
- **位置/符号**：`backend/modules/imports/api.py:591-602`（WIP：`GET /{record_id}` 移至文件尾，附顺序约束注释）；`/review-summary`（:506）为唯一被遮蔽的单段字面量 GET
- **问题与触发**：WIP 修复正确——FastAPI 按声明序匹配，`/{record_id}` 在前会把 `GET /api/imports/review-summary`（单段路径）吞成 record_id 查询→404；`/workflows/recent|impact` 为双段路径不受影响。该修复含新增回归测试（test_import_api.py:905-920）。残留面：该顺序约束仅靠一条代码注释维护，无机制防护，后续新增单段字面量 GET（或有人把动态路由移回）会静默复发。
- **调用链证据**：git diff（工作树）显示 `get_import` 从 :246 移至文件尾并加注释；WIP 测试断言 review-summary 返回 200 且 `total_candidates` 字段存在。
- **现有契约**：本 WIP 之前 `review-summary` 对外不可用（404），README:441 已记载该端点——属「既有功能错误被 WIP 修复」，审查以工作树为准认可该行为。
- **最小方案**：保留 WIP；可选加一条路由顺序守卫测试（遍历 `import_api.router.routes`，断言所有字面量 GET 路径声明序在 `/{record_id}` 之前），把注释升级为可执行约束。
- **预期收益**：防回归；一个测试的成本。
- **风险**：无。
- **依赖**：WIP 归属其原任务，守卫测试应随该任务落地或经其作者确认后追加。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_import_api.py"`。
- **回滚**：删测试即可。
- **裁定**：实施候选（低价值可选；WIP 本身保留）
- **优先级**：P3

### D5b-4
- **ID**：D5b-4
- **位置/符号**：`backend/modules/imports/workflow_entity_phase.py:30-53`（`run_full_pipeline_phase`）、`:290-311`（`run_stage_only`）；`backend/modules/imports/workflow_structure_phase.py:141-168`（同前）、`:315-341`（同前）；`backend/modules/imports/workflow_scene_phase.py:86-110`（`ScenePhaseRunner.run`）
- **问题与触发**：A6-1 现状复核后扩大为 5 个旧签名兼容 adapter（历史记 4 个，漏数 scene 的 `run`）：全部只把位置参数重包成 request dataclass 后转发到新签名。生产零调用（workflow.py 只走 `run_full_pipeline`/`run_stage`，rg 全仓证实）；唯一调用方是兼容测试 `test_workflow.py:316-395`。
- **调用链证据**：`rg "run_full_pipeline_phase|run_stage_only" backend --type py` 非定义命中仅 test_workflow.py:348/358/367/379；`ScenePhaseRunner.run` 仅 test_workflow.py:340。
- **现有契约**：无对外契约；`workflow_runtime.py` docstring 已声明兼容面只针对 monkeypatch 私有方法名，不含这些 adapter。
- **最小方案**：重写 test_workflow.py 该测试为直接调 `run_full_pipeline`/`run_stage`（断言 request 组装字段），删 5 个 adapter（约 100 行）。
- **预期收益**：~100 行；消除新旧双签名并存的误用面。
- **风险**：极低（测试内迁移，断言不减）。
- **依赖**：无。
- **验证命令/断言**：`rg "run_full_pipeline_phase|run_stage_only|ScenePhaseRunner\(\w+\).run\(" backend/modules` 归零；`make test TESTS="modules/imports/tests/test_workflow.py"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-5
- **ID**：D5b-5
- **位置/符号**：`backend/modules/imports/workflow_llm_adapters.py:44-51` `_workflow_constant`（5 个调用点：:130/:147/:188/:236/:254）；`:1987-2000` `_call_structured` 的 monkeypatch 三级 seam；`backend/modules/imports/workflow.py:35-40`（`_compact_phase1b_payload`/`_run_deep_import_structured_call` 的 self-re-export）；`backend/modules/imports/workflow_scene_phase.py:63-72` `_phase0_422_recommendation`（同族动态反查）
- **问题与触发**：A2-2 残余。声明式旋钮表已落地（`shared/deep_import_settings.py`），但 5 个旋钮的 default 仍经 `import_module("modules.imports.workflow")` 动态 getattr——而目标常量（`PHASE1B_SMALL_SAMPLE_MAX_TOKENS` 等）就定义在本文件 :24-41，workflow.py 只是 re-export；该机制唯一作用是让 `test_workflow.py:3384-3400` 能 monkeypatch `modules.imports.workflow.SMALL_SAMPLE_STRUCTURE_TARGET_COUNT`。`_call_structured` 同理：先查本模块全局是否被替换，再动态 import workflow 模块取同名函数，服务 `test_workflow.py:941-947` 的 re-export 恒等断言与旧 patch 路径。每次结构化调用多一次 import_module/getattr 间接。
- **调用链证据**：`rg "_workflow_constant" backend/modules/imports` 命中如上；workflow_structure_phase.py:28-31 同模式；测试消费者仅两处（见上）；`_workflow_constant` 的 ImportError "partially initialized" 分支在运行时调用场景下不可达（非 import 期调用）。
- **现有契约**：无对外契约；env 旋钮（`PHASE1B_COMPACT_TEXT_LIMIT` 等）经 `deep_import_int_setting(env_name=...)` 是正式配置通道，与该 seam 正交。
- **最小方案**：迁移 2 个测试（改为 patch `workflow_llm_adapters`/`workflow_structure_phase` 模块属性），删除 `_workflow_constant`、`_call_structured` 的 workflow 模块回退分支（保留模块内全局替换一级即可）、workflow.py:35-40 re-export、`_phase0_422_recommendation` 改直读本模块常量；约 40 行 + 每调用一次间接消除。
- **预期收益**：默认值单一权威；消除「测试 patch workflow 模块」的隐性契约。
- **风险**：低；须同步迁移 patch 路径，否则测试失效。
- **依赖**：无（与 D5a 的同族副本清理可同批）。
- **验证命令/断言**：`rg "_workflow_constant" backend` 归零；`make test TESTS="modules/imports/tests/test_workflow.py modules/imports/tests/test_scene_slicing_p10.py"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-6
- **ID**：D5b-6
- **位置/符号**：`backend/modules/imports/workflow.py:12`（`import inspect`）与 `:83-93`（`_accepts_keyword`）；`backend/modules/imports/schemas.py:49-66`（`ImportedChapterResponse`/`ImportedChapterListResponse`）
- **问题与触发**：workflow.py 的 `_accepts_keyword` 文件内零调用、无 re-export（生产唯一 `from modules.imports.workflow import` 仅 `DeepImportWorkflow`，rg 证实），`import inspect` 仅被它使用——死代码；同名 helper 在 imports 内共 4 份（workflow_scene_phase.py:31、entity_extraction/scene_entity_parallel.py:29、scene_entity_alias_relation.py:747，cross-ref D5a）。两个 Pydantic 响应模型生产零引用（任何 api/facade/service 均未使用），仅 `tests/unit/test_imports_extra.py:52-53` 导入自测。
- **调用链证据**：`rg "_accepts_keyword" modules/imports/workflow.py` 仅定义行；`rg "ImportedChapterResponse" backend --type py` 非定义命中仅 E1 测试。
- **现有契约**：无（wire 上不存在这两个模型的端点）。
- **最小方案**：删 workflow.py 死函数 + `import inspect`；删两个死 schema 及 E1 对应测试段（保留断言精神可并入 list 响应测试）；4 份 `_accepts_keyword` 收敛到模块内单一位置（归 D5a 主导，D5b 只删自己那份）。
- **预期收益**：~35 行 + 消除「响应模型存在即有端点」误读。
- **风险**：极低；E1 测试删除需走 E1 槽位确认。
- **依赖**：`_accepts_keyword` 收敛依赖 D5a。
- **验证命令/断言**：`rg "ImportedChapterResponse|def _accepts_keyword" backend` 剩余符合预期；`make test TESTS="modules/imports"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-7
- **ID**：D5b-7
- **位置/符号**：`backend/modules/imports/workflow.py:566-654`（`_start_phase/_finish_phase/_emit_progress/_mark_step_completed/_merge_checkpoints/_merge_audit_summary/_merge_snapshot_health_summary/_refresh_snapshot_health_summary` 8 个纯转发方法）
- **问题与触发**：A6-3 领域侧残余。8 个方法逐参数转发 `DeepImportProgressTracker` 同名静态/类方法；各 phase runner 经 `workflow._x(...)` 间接调用（生产 81 处），`workflow_runtime.py` Protocol 亦逐一声明。转发层无附加语义。
- **调用链证据**：workflow_progress.py 中 Tracker 实现为单一权威；`rg "workflow\._(start_phase|finish_phase|...)" backend/modules/imports -g '!tests'` = 81 处。
- **现有契约**：无对外契约；README「旧 runner 方法保留兼容 adapter」指的是本批转发所在的 seam 演进。
- **最小方案**：phase runner 直接 import `DeepImportProgressTracker`（机械替换 81 处调用点），删 8 个转发方法并收缩 `DeepImportWorkflowRuntime` Protocol；`_diagnostic_samples/_update_phase1_batch_counts`（真实实现，非转发）随迁至 tracker 或保留。
- **预期收益**：~90 行；进度语义单一入口（assistant_tools.py:471 已示范直用 Tracker）。
- **风险**：diff 大但纯机械；monkeypatch 测试若 patch `workflow._start_phase` 需同步迁移（rg 测试侧确认后执行）。
- **依赖**：建议在 D5b-4 同文件批内做，减少二次触碰。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_workflow.py modules/imports/tests/test_scene_phase_refactor.py"`。
- **回滚**：整体 revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-8
- **ID**：D5b-8
- **位置/符号**：`backend/modules/imports/orchestrator.py:163-261` `start` 与 `:263-377` `start_stage`（~110 行同构）；`:546-556`/`:708-734`/`:909-966` 三份 `_record_progress` 闭包与两份 `_completion`（:558-576/:736-754）
- **问题与触发**：A6-4 领域侧残余。`start`/`start_stage` 的授权快照构造、活动 run 检查、llm snapshot 构建、重复导入确认、freeze_future_resolution/freeze_completion_permission、enqueue、reuse 响应组装逐段相同（差异仅 stage 校验、scenes-only 重复检查、targeted stage 422）；闭包差异为 world_objects 的 0.8 钳制与 scene 阶段进度换算。变更传播时需同步改 2-3 处。
- **调用链证据**：逐段比对两方法；facade.py:62-135 两入口分别转发。
- **现有契约**：对外响应字段（`workflow_type`/`stage`/消息文案）不同，折叠须参数化保留。
- **最小方案**：抽私有 `_begin_workflow_start(db, ..., stage)` 返回（authorization_snapshot, active, llm_snapshot, resolution, permission），两入口仅保留差异分支；闭包差异以参数（stage 进度换算函数）合并。
- **预期收益**：~80-120 行；提交策略变更单点化。
- **风险**：中低——入队前的确认/授权顺序是安全语义，折叠须逐分支保持等价并有固定输入对比。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_workflow_orchestration.py modules/imports/tests/test_import_api.py"`；对 deep/scenes/world_objects/plot_structure 四入口的响应字段逐一断言不变。
- **回滚**：按文件 revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-9
- **ID**：D5b-9
- **位置/符号**：`backend/modules/imports/workflow_runs.py:164-183` `reconcile_scoped_task_owners` 的 `include_restartable_history` 参数；`:157-162` `reconcile_task_owners`（传 `True`）
- **问题与触发**：参数无效——`elif include_restartable_history or novel_id is not None: selection_predicate = active_predicate` 与 `else` 分支完全相同，查询恒为 active/recovery 谓词；`include_restartable_history=True` 不产生任何行为差异。名字暗示"含可重启历史"，实为误导。
- **调用链证据**：逐行比对 :178-183；`rg include_restartable_history` 仅定义点、reconcile_task_owners 传参点，无测试依赖。
- **现有契约**：无对外契约（模块内方法）。
- **最小方案**：删参数与 elif（保留 else），`reconcile_task_owners` 改直调；或如确有"收敛 failed 非 recovery 历史"意图则按意图实现并补测试——二选一，当前证据下选删除。
- **预期收益**：~6 行 + 消除假语义。
- **风险**：无。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_workflow_runs.py"`（现有 12 个测试全绿）。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-10
- **ID**：D5b-10
- **位置/符号**：`backend/modules/imports/workflow_scene_phase.py:42-58` `_enqueue_rag_reindex_after_scene_commit`（`:48` `inspect.iscoroutinefunction(getattr(db, "add", None))`），调用点 `:713`
- **问题与触发**：生产代码用「`db.add` 是否为协程函数」区分真实 `AsyncSession`（同步 add → 入队 RAG 重索引）与 AsyncMock 测试替身（协程 add → 静默跳过入队）。行为等价于生产内嵌 Mock 检测：真实生产路径恒入队（无功能缺陷），但任何「`add` 为异步」的真实/替代 session 实现会静默丢失 RAG 重索引入队，且该分支在测试里使 Scene commit 的 RAG 副作用不可见。
- **调用链证据**：`rg "iscoroutinefunction\(getattr\(db" backend` 仅此一处；`enqueue_task` 为同步 ORM 写入。
- **现有契约**：AGENTS「生产禁 import/检测 Mock」——此处是形状嗅探而非 import Mock，字面合规、精神相近；README Scene commit 节承诺 RAG 入队。
- **最小方案**：改为显式参数（`enqueue_rag: bool = True`，fenced/非 fenced 调用点按语境传值）或测试侧 monkeypatch `enqueue_task`，删除嗅探。
- **预期收益**：消除隐藏测试 seam；RAG 入队行为在生产/测试一致可见。
- **风险**：低；需确认现有测试依赖该嗅探跳过的数量（test_scene_commit/test_scene_stage_task_transactions）。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_scene_commit.py modules/imports/tests/test_scene_stage_task_transactions.py"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5b-11
- **ID**：D5b-11
- **位置/符号**：`backend/modules/imports/workflow_llm_adapters.py:329-333`（`extra.setdefault("thinking", ...)` 下一行即被 `extra["thinking"] = ...` 无条件覆盖，setdefault 死行）；`orchestrator.py:237-241`/:351-355（对自身 `async def` 方法返回值做 `inspect.isawaitable` 判断，恒真，为测试 sync stub 保留）；`workflow_llm_adapters.py:57-58/:86-87/:318-320`（`del default`/`del high_quality` 等 seam 兼容形参）
- **问题与触发**：微项集合：死行、恒真防御、占位形参。均无行为缺陷，但制造「存在第二条配置路径」的误读。
- **调用链证据**：逐行读码；`_deepseek_request_extra` 的 thinking 覆盖使 setdefault 永无效。
- **现有契约**：无。
- **最小方案**：删 setdefault 死行；`isawaitable` 防御保留与否随 D5b-8 折叠一并裁定（若测试 stub 改 async 则删）。
- **预期收益**：~10 行，可读性。
- **风险**：无。
- **依赖**：D5b-8。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_phase1b_prompt_p11.py"`。
- **回滚**：revert。
- **裁定**：顺手修改（默认保留，随伴生批次处理）
- **优先级**：P3

**优先级计数**：P0=0，P1=1（D5b-1），P2=1（D5b-2），P3=9（D5b-3…D5b-11）。

## 历史候选复核

| ID | 结论 | 证据 |
|---|---|---|
| A6-1（workflow_entity/structure_phase 4 个旧签名 shim ~140 行，唯一调用方 test_workflow.py:348-379） | 仍成立（规模 4→5） | 4 个 shim 在位且行号吻合；另 `ScenePhaseRunner.run`（workflow_scene_phase.py:86-110）为同型第 5 个，同一测试 :340 调用。生产零调用。见 D5b-4。 |
| A6-3（imports 9 个转发 classmethod 删 ~90 行） | 仍成立（D5b 侧残余 8 个） | workflow.py:566-654 八个纯转发到 DeepImportProgressTracker；生产 81 处经 seam 调用；另 `_diagnostic_samples`/`_update_phase1_batch_counts` 为真实实现不在删除范围。见 D5b-7。 |
| A6-4（full/stage 双入口折叠 ~150-200 行） | 仍成立（D5b 侧残余 ~110+40 行） | orchestrator.start vs start_stage 同构段、`_record_progress`/`_completion` 三份闭包。D5a 侧（entity 阶段双入口）由 D5a 复核。见 D5b-8。 |
| A6-8 / X1-6 领域侧（imports 7 路状态收敛） | 不立项（词汇表不等价，与 D7 判定一致；imports 侧独立证据） | imports 词汇实为不同状态机而非同词多写：① 队列 `AsyncTask.status`（pending/running/done/failed/cancelled，权威=infrastructure/tasks）；② `ImportWorkflowRun.status`（同 5 值但转换图不同：done 仅 owner CAS 写入、failed 必须伴 recovery_required 才可 resume、generation 递增语义；是队列投影+领域守卫，经 reconcile 收敛，非第二权威）；③ `progress.phase`（工作流执行态 pending/running/done/failed）；④ `quality_status`（complete/partial/failed 质量维度）；⑤ `current_phase/current_step`（展示定位）；⑥ checkpoint 单元状态（done/skipped/…，fail-safe 重跑语义）；⑦ review outcome（organized/decision/optional/incomplete，处置语义）。合并会破坏 §6「名称不构成等价关系」。X1-6 机制侧（F2-5 队列枚举收敛）不影响本域。 |
| A1-3 领域侧（imports get_active_organization 改读队列权威源，run.status 降为 fencing 内部状态） | 误报/保留现状 | run 是 imports 领域权威（README 明示 run 持 generation/owner/checkpoint），队列权威收敛机制已在位：worker startup 注册 `reconcile_workflow_task_owners`（run_worker.py:114-122），且所有写路径（`_find_active_import_task`、`_enqueue_workflow`、`_claim_workflow_attempt`、`_get_recoverable_deep_import_run`）读前 lazy reconcile。唯一不 reconcile 的读取点是 `facade.get_active_organization`（消费者仅 assistant/proactive.py 建议门控）——陈旧正读只会延迟一条建议，陈旧 recovery 读使恢复入口提前可见，均 fail-open 无害。改读队列 = 产品语义变更（NV），无证据支持立项。 |
| A1-5（4 handler 样板 + 删测试专用 else 分支） | 仍成立 | tasks.py:78-81/:103-104/:124-129/:149-154 else 分支在位；唯一触发方为直调 handler 的测试（test_workflow.py:4633、tests/unit/test_imports_extra.py:1216/:1233，后者归 E1）。`targeted_completion`/`import_review_resolution` 两个新 handler 已无 else（恒走 domain claim），证实双轨是存量兼容。删 else 需迁移 3 个测试（改 flagged session 或 run_attempt）。 |
| X1-8 领域侧（_uses_domain_workflow_run 双轨） | 功能变更→设计现状（确认 F2 结论，补充 imports 消费点） | flag 是运行时 session 标记（worker fenced session 恒真 / inline 执行器置真），生产恒走 domain 分支。imports 侧消费点共 2 处：tasks.py:24-28（4 个旧 handler 分支）+ orchestrator.py:680-683（`fenced_session` 选择 fenced scene stage 事务纪律）——后者即使"消亡"也需保留等价判定（fenced 与非 fenced 路径行为不同），故 X1-8 的实际动作=测试迁移+删 tasks.py else（同 A1-5），orchestrator 处应保留。 |
| A2-2 残余（_workflow_constant 动态反查，15 旋钮→声明式表 220→40 行） | 部分仍成立（主体已解决） | 声明式表已落地 `shared/deep_import_settings.py`（DEFAULT_SETTINGS 全量表 + project/global/env 解析链），15 个旋钮函数已薄化为一行 `deep_import_int_setting(...)` 调用。残余=5 处 `_workflow_constant` 动态 default + `_call_structured` monkeypatch seam + `_phase0_422_recommendation`，消费者仅 2 个测试。见 D5b-5。 |

## 共享事实（供 W3 链 2：文稿导入→结构整理/抽取→作者确认→资产）

### 1. 工作流状态机（imports 域）

**权威源分层**：队列运行态权威 = `AsyncTask`（infrastructure/tasks）；领域运行态权威 = `ImportWorkflowRun`（imports，`novel_id` 隔离、partial unique index 保同项目单活动/recovery run、`id==task_id` 首版兼容）；run 由两条路径与队列收敛——worker startup `reconcile_workflow_task_owners`（run_worker.py:114-122，全量 active/recovery）+ 写路径 lazy `reconcile_scoped_task_owners(task_id|novel_id)`（claim/提交/恢复/放弃前）。

**run.status 合法转换与来源**（`ACTIVE_RUN_STATUSES = {pending, running}`，另有独立布尔 `recovery_required`）：

```
create_pending ──────────► pending (gen=1)                      [orchestrator._enqueue_workflow，project exclusive 锁内]
pending ──claim_attempt──► running(owner=task,attempt,lease)    [tasks._claim_workflow_attempt；失败抛 ImportWorkflowOwnershipLost(CancelledError)]
running ──checkpoint─────► running（progress/prepare/checkpoints 持久化，作者 defer 控制合并）
running ──complete───────► done（清 owner；触发 source.changed 观察者）
running ──fail───────────► failed(±recovery_required)           [recovery_required=manual_resume 且 task.recovery_required]
failed(+rr) ──resume─────► pending（gen+1）                     [orchestrator.resume_interrupted→runs.resume；同事务 resume_manual_task]
failed(+rr) ──abandon────► cancelled（先资产软废弃/补全撤销再 cancel_recoverable_task）
任意 ──reconcile──────────► 按 task lifecycle 投影（cancelled/done/failed/pending/running；running 无 lease→cancelled）
```

**词汇归一对照**（勿跨列等价）：`run.status` 值域与 `AsyncTask.status` 相同但转换守卫不同（上表）；`progress.phase`（pending/running/done/failed）是结果文档内的执行态，`resume` 后归一规则见 D5b-1；`quality_status`（complete/partial/failed）是质量维度；`current_phase`（phase0_plan/phase1a_scene_slicing/phase1b_enrichment/phase1c_scene_fusion/scene_commit/entity_extraction/structure_analysis）是展示定位；checkpoint 单元状态（done/skipped）授权跳过；review outcome（organized/decision/optional/incomplete）是处置语义。`import_records.status`（processing/done/failed）属上传记录，独立于 workflow run。

### 2. 审核减负链确认语义（review_resolution，`imports.review_resolution.v1`）

- **授权**：显式请求 `ReviewResolutionRequest(authorization_confirmed=Literal[True])` → `freeze_resolution` 冻结章节正文 manifest（缺正文/含空 hash 即拒绝）、scope_hash、prompt_manifest（三个 prompt + 两个输出 schema + 预算常量的 stable_hash）；`authorize_resolution` 经 world facade 签发 `authorization_id`。完整导入内嵌走 `freeze_future_resolution`（仅选本 workflow 新候选）并在入队事务内 authorize。
- **执行**（`run_resolution`）：按 Scene 分组（≤32 key/组）→ 每组预算至多 3 次 LLM 调用（初审→格式返修/补查返修→终检共享预算，恢复不重置；`MAX_GROUP_REQUESTS=3`）→ 判定经 `judgment_outcome` 失败关闭（证据不唯一命中→incomplete；身份歧义/冲突/状态改变→decision 作者决定；支持不足→optional；仅 explicit+stable+≥0.90+全字段证据→eligible）→ eligible 还需 per-category held-out 资格表（`review_resolution_quality.qualified`，prompt/profile/model 三元隔离，当前空表=fail-closed 全部 optional）+ 候选指纹重验 + focused world package submit/apply。**模型自评永不直接等于写入授权**；每步经 ContextSnapshot 审计。
- **作者确认面**：decision 项经 `POST /review-resolutions/{task_id}/decisions`（指纹绑定+`begin_nested`）；场景组经 `.../scene-groups/{group_key}/apply`（组指纹+confirmed，成功后可自动 resume 原失败任务继续依赖核对）；撤销 `.../rollback`（运行中拒绝；整组 CAS，世界冲突→partial）。未知旧场景标保持 incomplete；未完成不计为已整理。
- **终态**：存在 incomplete → `phase=failed + recovery_required=True` + `DeepImportWorkflowFailedError`（任务转 failed，走 resume 续整理——此路径不经 `run_step`，不受 D5b-1 影响）。完整导入内嵌的局部整理失败降级为 partial，主流程继续。

### 3. orchestrator 幂等 / 取消 / 恢复语义

- **单飞**：全部 7 个任务类型共享 `scope=("imports_pipeline",)` coalescing + project exclusive 锁内 reconcile→`get_active_for_novel(for_update)` 复检；已有 owner 返回原 `task_id/workflow_type`（`_existing_task_response`，`reused_task: true`），不重复入队；targeted/review 另比对 scope_hash/roots，不匹配→409。
- **claim**：handler 先按 task scope reconcile 收敛 auto-retry 新 attempt，再 `claim_attempt`（run 必须 ACTIVE 且 owner 匹配）；产出不可变 `ImportWorkflowAttempt`（owner token=workflow_id+task_id+generation+attempt+lease_id），orchestrator 不触碰 AsyncTask ORM，进度经 `_project_task` 只写投影。
- **checkpoint**：provider I/O 前 `commit→expire_all`（fenced scene stage 强断言无事务）；每次进度经 `require_owner` 全字段 CAS 写 run；租约丢失抛 `ImportWorkflowOwnershipLost`（CancelledError 子类）→worker 按取消收束并回滚，旧 attempt 不能覆盖新 generation。
- **恢复**：仅 `failed+recovery_required` 可 resume（gen+1、复用原 task、双份 flag 清除、不伪装 running）；专项补全 deferred 可带 `stage=targeted_completion`+确认恢复；fenced scene stage 靠 v2 prepare 指纹（project profile/LLM snapshot/章节 source vector/Phase1a context/授权）在正式提交前全量重验，任一漂移拒绝 provider 结果。已知缺口=D5b-1。
- **放弃**：`abandon_recovery` 同事务完成 targeted 补全撤销→review_resolution 撤销→按 `novel_id+workflow_id` 软废弃 Scene/实体/结构资产/回滚 DeltaLog/别名/关系→cancel→run.cancelled；冲突计数值决定 cleanup_status=partial，不宣称全部成功。
- **取消**：用户经 `/api/tasks/{id}` cancel → reconcile 将 run 投影为 cancelled；进行中 worker 的下一步 owner 校验失败自然退出。

### 4. api.py 端点面（含门禁与错误映射）

| 端点 | 门禁 | 错误映射 |
|---|---|---|
| POST /upload | require_active_project；50MB 分块预检 | service DomainError/HTTPException 直抛；commit 失败回滚后重抛原异常 |
| GET ""（列表）、GET /{record_id}（WIP 移至尾部） | require_active_project；record 校验 novel_id 归属 | NotFoundError→404 |
| POST /deep、/stages/scenes、/stages/world-objects、/stages/plot-structure | require_active_project_exclusive；章节范围解析+章数上限；targeted 仅 world_objects/all | DomainValidationError→400 |
| POST /deep/resume、/deep/abandon | `_require_task_owner_active_project`（tasks facade 最小投影，不存在/越权/回收站统一 404 不回显） | TaskNotFoundError→404；ValueError→400（redact） |
| POST /targeted-completions | exclusive + 章数上限 | ValueError→400 |
| POST /targeted-completions/{id}/rollback、/defer | exclusive / owner-active | 404 / 409 |
| GET /workflows/recent、/workflows/impact | require_active_project | —（双段路径不受 /{record_id} 遮蔽） |
| GET /review-summary | require_active_project；聚合 dispositions+latest | WIP 修复了被 /{record_id} 遮蔽（D5b-3） |
| POST /review-resolutions | exclusive + 章数上限 + Literal[True] 确认 | DomainError 通道 |
| POST /review-resolutions/{id}/rollback、/decisions、/scene-groups/{key}/apply | exclusive | rollback/decisions 的 ValueError→**500（D5b-2）**；scene-groups→ConflictError 409 |

所有写入端点要求 `authorization_confirmed=true`（Pydantic 层强制）；owner 只从 tasks facade 最小投影读取，404 不回显 owner/meta/result。

## 受阻

无。备注：(1) `api.py`/`test_import_api.py` 为他任务 WIP，D5b-3 的守卫测试建议需与该任务归属者协调；(2) D5b-1 与 D5b-2 的最终修复需主 Agent 按 §2 单列功能性任务，不并入纯优化批次；(3) 测试文件按定向映射抽查而非逐行全读（25.6k 行），抽样集中于与本槽位发现相关的 test_workflow/test_workflow_orchestration/test_workflow_runs/test_import_api/test_review_resolution，其余测试的断言有效性横查归 E1。
