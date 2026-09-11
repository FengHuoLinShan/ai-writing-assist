# D3a 槽位报告（R05 story：总纲/篇章/Scene、outline_state 工作流）

日期：2026-09-11。基线：`main` @ `e7d0b8d5b`（coverage-ledger.csv 指纹）。全部只读；
未运行测试/构建/make，无网络。93 个账本路径全覆盖：生产文件逐文件语义阅读（3 个大文件
——scene_workbench.py、repositories.py、generator.py——为"结构清单+关键段精读"，其余全文）；
generation/ 子包 models 全文+其余结构化阅读；测试文件 conftest 全文、test_scene_workbench
测试名清单逐条阅读、其余按测试名清单+抽读（autospec 合规已抽查核验，未发现违规 patch）。
未发现 P0/P1 级问题。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/story/README.md,已审,F6 文档消费者+全部 story 调用方,无发现：与实现核对一致（4+16 张表归属、/api/story 与 /api/outline 前缀、one-click 授权语义、P20/story_reference_review 契约、phase3_structure_simple_v3、basis_manifest v1/v2 均与代码吻合）
backend/modules/story/__init__.py,已审,模块导入面,无发现：1 行 docstring
backend/modules/story/api.py,已审,/api/story 路由（app.main 注册）,D3a-1
backend/modules/story/assistant_information_tools.py,已审,assistant OPERATIONS（app.bootstrap 注册 story.edit_information_plan）,D3a-10
backend/modules/story/assistant_planning_tools.py,已审,assistant OPERATIONS（story.create_thread/story.create_arc）,无发现：预览/重验/采用闭环完整，provenance 保留 assistant_run_id+approved_by
backend/modules/story/assistant_structure_workflow.py,已审,assistant OPERATIONS（story.plan_structure/story.adopt_structure）,无发现：复用 P20 submit_layer_generation/apply_structure_preview；整层范围强制（_require_scope 拒绝排除项与子范围）；fingerprint 绑定 p20_context.stable_hash
backend/modules/story/assistant_tools.py,已审,assistant OPERATIONS（story.save_outline/create_scenes/save_card/save_script/edit_scene）,D3a-10
backend/modules/story/contracts.py,已审,world 影响预览/跨模块读契约,D3a-7（文件尾 import SceneBoundaryReview 未入 __all__ 的顺序依赖写法，无功能问题）
backend/modules/story/facade.py,已审,跨模块稳定 seam（writing/evidence/imports 消费）,X1-S3 部分证据（见历史候选复核）；转发均为制度性 seam
backend/modules/story/generation.py,已审,story/tasks.py 四个 handler,D3a-3（one_click_preview 零调用）
backend/modules/story/information_dependencies.py,已审,story/service basis hash、proactive 受影响场景、repositories capture_change_scenes,D3a-8（O(plans+links+scenes) 内存扫描，代码已注记）
backend/modules/story/outline_state/__init__.py,已审,模块导入面,无发现：V1 docstring 已过时（现为 P20 v2 全域）但不误导
backend/modules/story/outline_state/ai_workflow_service.py,已审,任务 handler（outline_analyze/outline_generate）+助手/api 采用,D3a-2、D3a-4（analyze/generate/generate_for_task/generate_legacy_preview_for_task 生产零调用）、D3a-7
backend/modules/story/outline_state/analysis_context.py,已审,evidence compilation outline_analysis_loader、scene_fusion_draft related context,无发现：确定性投影/排序/去重；重叠判定 fail-open（无章号计划不入选）有据
backend/modules/story/outline_state/analysis_context_facade.py,已审,cross-module seam,无发现：纯转发
backend/modules/story/outline_state/api.py,已审,/api/outline 路由（旧公开前缀，app.main 注册）,D3a-1（同型入队流 3 处）、D3a-6（线程/篇章 CRUD schema 宽松）、观察：PermissionError→400 与 story/api 403 不一致（既有 wire 契约，不动）
backend/modules/story/outline_state/contracts.py,已审,evidence/writing/interaction 跨模块契约,无发现：语义字段状态机（present/not_applicable/uncertain+manual 恒 None）有完整 docstring；SceneExecutionBundleContract 为执行束权威形状
backend/modules/story/outline_state/deep_import_repair_facade.py,已审,imports workflow 修复 seam,无发现：纯转发+惰性导入
backend/modules/story/outline_state/deep_import_repair_service.py,已审,imports deep import Phase3 修复,无发现（结构+关键段精读）：small_sample 目标数与 imports 侧 sweep 配对；fallback_thread_type 仍产出 legacy 词表（secondary/hidden/foreshadowing）——README 已声明前端保留旧分类，非缺陷
backend/modules/story/outline_state/facade.py,已审,跨模块 outline seam（冻结 __all__）,无发现：33 符号冻结面+惰性导入；注释明确新增名需删除测试
backend/modules/story/outline_state/foreshadowing_facade.py,已审,evidence/world 伏笔只读 seam,无发现
backend/modules/story/outline_state/foreshadowing_repository.py,已审,ForeshadowingPlanService,按生成源验证→D3a-5（get_by_novel 覆写与 reveal 版 ~40 行同构，Python 内过滤+切片）
backend/modules/story/outline_state/generation/__init__.py,已审,子包说明,无发现
backend/modules/story/outline_state/generation/context_builder.py,已审,PlotStructureGenerator.prepare（deep import Phase3）,无发现（结构化阅读）：上下文构建+Scene 摘要卡
backend/modules/story/outline_state/generation/context_renderer.py,已审,parser 提示词渲染,无发现（结构化阅读）：_PromptTextGuard 边界转义
backend/modules/story/outline_state/generation/parser.py,已审,PlotStructureParser（deep import Phase3）,无发现（结构+关键段）：simple 结构 parameter_version=phase3_structure_simple_v3；phase3 证据批审
backend/modules/story/outline_state/generation/persister.py,已审,generator.apply_preview/generate(persist=True) 授权自动流水线,无发现（关键段精读）：持久化前 _check_duplicates 仅告警不阻断（有 warnings 回执）；别名附着既有实体不重复建（名称→ID 映射由上游传入）
backend/modules/story/outline_state/generator.py,已审,imports/workflow.py:936（容器 outline.generate_structure）+ 采用路径,无发现（结构+关键段精读）：prepare/execute/fresh 三段与 fingerprint 围栏；apply_preview 仅经 OutlineAIWorkflowService.apply_structure_preview 可达
backend/modules/story/outline_state/p20_context.py,已审,P20GenerationService.prepare（提交/恢复/采用 4 次调用）,D3a-7（stable_hash 权威定义点）、D3a-8（prepare 全量读 threads/arcs/scenes/plans+角色实体排序，每生命周期 4 次）；排序与指纹确定性良好
backend/modules/story/outline_state/p20_schemas.py,已审,/api/outline/generate + outline_generate 任务 + P20 apply,无发现：严格 Literal 契约、uncertain_fields 自动归一（hidden_content/target_ref 补记有注释）、arc/scene 区间校验
backend/modules/story/outline_state/p20_service.py,已审,任务生成+显式采用（api 与助手共用）,D3a-8（_retire_stale_information_projections/_find_projection 全表载入）；其余无发现：短引用完整性+时间序确定性违规、采用前双段 freshness+项目排它锁+begin_nested+CAS replace 闭环
backend/modules/story/outline_state/reveal_facade.py,已审,evidence reader reveal 决策 seam,无发现
backend/modules/story/outline_state/reveal_repository.py,已审,RevealPlanService/reveal_visibility,按生成源验证→D3a-5
backend/modules/story/outline_state/reveal_visibility.py,已审,reader reveal 策略（reader_safety 消费）,无发现：章级截断保守语义（cutoff 章本身保持隐藏）有注释
backend/modules/story/outline_state/review_attention.py,已审,scene_draft_review/scene_resolution,无发现：需作者决定的判定矩阵（v1 review_issues/legacy needs_review/auto_verified）
backend/modules/story/outline_state/scene_coverage.py,已审,evidence/cross-module coverage 健康检查,无发现
backend/modules/story/outline_state/scene_draft_review.py,已审,scene_workbench 融合/拆分预览审阅,无发现（结构化阅读）：字段引用/来源映射构造，纯函数
backend/modules/story/outline_state/scene_execution_bundle.py,已审,writing 执行束 + story 场景上下文,D3a-7（_hash 为 dataclass 感知变体）；story_assets 惰性富集防递归（docstring 声明）
backend/modules/story/outline_state/scene_facade.py,已审,跨模块 Scene seam（evidence/writing/imports 消费）,无发现：全部惰性导入转发；get_scene 按 ID 无 novel 过滤（F4 共享事实 3 同类，调用方门禁补偿）
backend/modules/story/outline_state/scene_fusion_draft.py,已审,scene_workbench 融合预览（同步+任务双模式）,D3a-2（:314-318 checkpoint 变体：commit→expire_all→in_transaction 检查，次序与标准序不同）；证据加载 hash 校验+指纹+降级路径（任务模式禁降级）正确
backend/modules/story/outline_state/scene_replacement.py,已审,scene_facade.commit_deep_import_scene_candidates（imports 消费）,D3a-7（_hash_payload 无 default=str 变体）；其余无发现：保护性重叠组件分析（BFS 连通）+指纹建议+全 Scene 行锁
backend/modules/story/outline_state/scene_resolution.py,已审,story/facade 导入场景定向核对 5 seam（imports/助手消费）,D3a-7（fingerprint 内联哈希）；其余无发现：锚点唯一定位失败关闭、成组核对、rollback 冲突检测
backend/modules/story/outline_state/scene_source_service.py,已审,scene_facade bind/checkpoint seam（evidence/writing 消费）,无发现：reanchor 状态机（exact/reanchored/chapter_only/unresolved）与 checkpoint based_on_hash 重验正确
backend/modules/story/outline_state/scene_workbench.py,已审,/api/outline scene-workbench 全部路由,无发现（结构+关键段精读：入队/融合/替换/健康/进度段精读，其余按结构清单）；D3a-9（_next_scene_index advisory lock 与其它路径不一致）；融合保存先锁建议行再锁 Scene 行有注释
backend/modules/story/outline_state/schemas.py,已审,/api/outline CRUD schema,D3a-6（线程/篇章/计划 Create/Update/Response 非 strict：status 自由字符串、extra 默认忽略；与 Scene/p20 严格面不一致）
backend/modules/story/outline_state/services.py,已审,/api/outline 服务层+scene 写路径,无发现：StructureAssetFilterMixin/user_edited 元数据标记/场景断章 chunk 分割均闭环；split_chapters 新建路径无 scene_order 锁（D3a-9 关联）；__getattr__ 惰性导出 PlotStructureGenerator 有注释
backend/modules/story/outline_state/story_outline_generation.py,已审,story_outline_generate 任务 + api 提交预检,D3a-2（_open_task_client F2-3 配对；:582 checkpoint）、D3a-7（_stable_hash）；其余无发现：三审计（证据/正史污染/世界规则）+一次语义修订共享 30min 预算；本地章节日程正则拦截
backend/modules/story/outline_state/story_outline_repository.py,已审,StoryOutlineService,无发现：advisory lock+FOR UPDATE head、复合约束由 F4 覆盖
backend/modules/story/outline_state/story_outline_schemas.py,已审,story-outline API schema,无发现：strict、执行画像版本绑定（story_execution_profile.v1）
backend/modules/story/outline_state/story_outline_service.py,已审,/api/outline/story-outline + apply_generated_preview,无发现：幂等键+request_hash、base_revision CAS、任务回执 replace CAS、来源 provenance 校验（含 project ref 必须等于 novel_id）闭环；_hash 无 default=str（JSON-mode dump 安全，属 F1-3 变体）
backend/modules/story/outline_state/structure_dedup.py,已审,structure_dedup_facade（助手 smart-dedup 消费）,无发现（结构化阅读）：suggest 只读、apply 需 confirmed、执行指纹预校验、_assert_same_novel
backend/modules/story/outline_state/structure_dedup_facade.py,已审,跨模块 dedup seam,无发现
backend/modules/story/outline_state/tasks.py,已审,任务 registry 7 handler（4 活跃+3 退役 unsupported）,D3a-2（_require_llm_execution_snapshot 现存 2 份之一，含 legacy 无快照回填路径）；退役 handler fail-closed 有中文可展示信息
backend/modules/story/outline_state/tests/__init__.py,已审,测试包,无发现：空
backend/modules/story/outline_state/tests/conftest.py,已审,story 模块测试,无发现：真库 fixture（db_session+Project 行），无 mock 失真
backend/modules/story/outline_state/tests/test_ai_api.py,已审,story 模块测试（5 测试）,无发现：AI 入队 API 层测试（清单+抽读）
backend/modules/story/outline_state/tests/test_ai_workflow_service.py,已审,story 模块测试（7 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_analysis_context.py,已审,story 模块测试（1 测试）,无发现
backend/modules/story/outline_state/tests/test_context_integration.py,已审,story 模块测试（7 测试，autospec=2）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_deep_import_simple_structure_parser.py,已审,story 模块测试（4 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_foreshadowing_reveal.py,已审,story 模块测试（33 测试，autospec=9）,无发现（清单+抽读；mock.patch 全部带 autospec=True，已逐点核验 :811/:852/:908/:918）
backend/modules/story/outline_state/tests/test_imports_integration.py,已审,story 模块测试（2 测试，autospec=2）,无发现
backend/modules/story/outline_state/tests/test_p20_context.py,已审,story 模块测试（5 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_p20_layer_generation.py,已审,story 模块测试（24 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_project_gate.py,已审,story 模块测试（1 测试）,无发现：project 门禁隔离
backend/modules/story/outline_state/tests/test_repositories.py,已审,story 模块测试（20 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_scene.py,已审,story 模块测试（37 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_scene_coverage.py,已审,story 模块测试（1 测试）,无发现
backend/modules/story/outline_state/tests/test_scene_execution_bundle.py,已审,story 模块测试（2 测试）,无发现
backend/modules/story/outline_state/tests/test_scene_fusion_draft.py,已审,story 模块测试（16 测试，autospec=1）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_scene_resolution.py,已审,story 模块测试（7 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_scene_source_service.py,已审,story 模块测试（6 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_scene_workbench.py,已审,story 模块测试（71 测试）,无发现：测试名清单逐条阅读——覆盖健康/过滤/novel 隔离/融合建议指纹/替换采用/锁序/热模式/分页全量场景；断言有效
backend/modules/story/outline_state/tests/test_services.py,已审,story 模块测试（25 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_story_outline.py,已审,story 模块测试（9 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_story_outline_generation.py,已审,story 模块测试（20 测试，autospec=19）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_structure_asset_filters.py,已审,story 模块测试（2 测试）,无发现
backend/modules/story/outline_state/tests/test_structure_dedup.py,已审,story 模块测试（12 测试）,无发现（清单+抽读）
backend/modules/story/outline_state/tests/test_task_ai_transactions.py,已审,story 模块测试（20 测试，autospec=12）,无发现（清单+抽读）：checkpoint/快照/取消终态事务测试
backend/modules/story/outline_state/tests/test_tasks.py,已审,story 模块测试（6 测试，autospec=10）,无发现（清单+抽读）
backend/modules/story/outline_state/thread_facade.py,已审,evidence/world 剧情线 seam,无发现：反向查找 500 上限分页扫描有界
backend/modules/story/outline_state/world_dependencies.py,已审,story/facade → world 影响预览（ADR-0022 消费）,D3a-8（作者触发全量结构扫描，代码已注记 ponytail）；_snapshot 行级 source_hash 含全部列（datetime 归一 UTC）
backend/modules/story/proactive.py,已审,story_reference_review handler + 助手 source.changed 观察者,D3a-7（_hash 异构变体：默认分隔符且无 default=str）；source_hash 重放围栏正确
backend/modules/story/schemas.py,已审,/api/story 请求响应+LLM 输出 schema,无发现：extra=forbid 一致、UUID 归一 validator、confirmed Literal[True] 门禁；前后向引用 model_rebuild 有注释说明
backend/modules/story/service.py,已审,story 卡/脚本全部写路径与执行束读 seam,D3a-7（_hash_payload 同语义副本）；其余无发现：CAS+for_update+来源重验+project 门禁闭环，basis v1/v2 分版本哈希
backend/modules/story/tasks.py,已审,任务 registry 5 handler（story_reference_review+四预览）,D3a-2（checkpoint 序列未入 F2-4 清单；_open_client 为 F2-3 六处之一）、D3a-7
backend/modules/story/tests/__init__.py,已审,测试包,无发现
backend/modules/story/tests/test_assistant_information_tools.py,已审,story 模块测试（1 测试）,无发现
backend/modules/story/tests/test_assistant_structure_workflow.py,已审,story 模块测试（1 测试）,无发现
backend/modules/story/tests/test_assistant_tools.py,已审,story 模块测试（2 测试）,无发现
backend/modules/story/tests/test_information_dependencies.py,已审,story 模块测试（3 测试）,无发现：monkeypatch get_settings（非 patch，合规）
backend/modules/story/tests/test_story_service.py,已审,story 模块测试（6 测试）,无发现（清单+抽读）
backend/modules/story/tests/test_story_tasks.py,已审,story 模块测试（3 测试）,无发现（清单+抽读）
```

注：以上 93 行与 slot-paths-W2.json "D3a" 数组逐一对应（程序化核对 93/93，顺序一致）。

## 发现

优先级计数：P0=0，P1=0，P2=2（D3a-1/2），P3=8（D3a-3..10）。

### D3a-1
- **ID**：D3a-1（=A5-1 及其同型扩展）
- **位置/符号**：`backend/modules/story/api.py:448-505 _enqueue_confirmed_task`、`:508-568 _enqueue_one_click_task`；同型流还有 `backend/modules/story/outline_state/api.py:164-232 _enqueue_confirmed_outline_task`、`:374-449 api_generate_story_outline`、`:889-938 api_preview_scene_fusion_task`
- **问题与触发**：story/api.py 两函数除 task_type/action 常量与 one-click 多出的 `submit_authorized`/`authorization_scope` 两个 meta 键外逐字相同（operation 幂等查询→require_fresh_confirmation→meta 组装含 build_project_llm_execution_snapshot→enqueue_task_with_optional_operation→attach_result_ref→flush，~55 行重复）。outline_state/api.py 另有 3 处同形流（差异：响应类型、meta 展平 vs 嵌套、fusion 的 attach_result_ref 条件在 enqueue 之后）。
- **调用链证据**：api_submit_character_card_task/reaction/script 走 `_enqueue_confirmed_task`；api_submit_one_click_task 走 `_enqueue_one_click_task`；api_analyze_outline 走 `_enqueue_confirmed_outline_task`；api_generate_story_outline 与 api_preview_scene_fusion_task 各自内联。
- **现有契约**：operation_id 幂等键语义、`request_payload` 形状（story 嵌套 `{"request":...,"action":...}` vs outline 顶层展平）、meta_version、202/201 状态码、错误文案（HTTPException vs ConflictError）。
- **最小方案**：story/api.py 内合并为单函数 `+ extra_meta: dict | None = None`（A5-1 原案，逐字保留 meta 键序不影响 JSON 语义）；outline_state 3 处第二步收敛（跨 router，可放 outline_state/api.py 模块内 helper，先不动 meta 形状差异）。
- **预期收益**：~55 行（story 内）+ 后续 ~60 行（outline 内）；新增 Story 任务类型不再复制入队样板。
- **风险**：低——纯内部重排；meta 形状差异必须保持（worker 侧 `_parse_task_request` 兼容两种）。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/story"`；对 4 个提交端点各断言 202/201、重复 operation_id 返回原任务、meta 含 llm_execution_snapshot。
- **回滚**：单文件 revert。
- **裁定**：实施候选
- **优先级**：P2

### D3a-2
- **ID**：D3a-2（F2-3/F2-4 的调用方侧证据补充，cross-ref F2-3、F2-4）
- **位置/符号**：snapshot CM 四处：`story/tasks.py:444 _open_client`、`outline_state/story_outline_generation.py:550 _open_task_client`、`outline_state/ai_workflow_service.py:166 _open_task_llm_client`、`outline_state/scene_fusion_draft.py:284 _open_llm_client`（变体：快照缺失时自行 build + 在 CM 内做 checkpoint）。checkpoint 三步序列四处：`story/tasks.py:270-276 _checkpoint_before_provider`、`story_outline_generation.py:582-590`、`ai_workflow_service.py:475-488 _checkpoint_before_external_call`（含 expire_all 必要性长注释）、`scene_fusion_draft.py:314-318`（次序变体：commit→expire_all→再查 in_transaction）
- **问题与触发**：F2-4 的十处清单漏计 story 侧两处（story/tasks.py:270、story_outline_generation.py:582）；scene_fusion_draft 的次序变体（先 expire_all 后断言）是 helper 收敛时必须归一的第三种形态。`_require_llm_execution_snapshot` 全仓现存 2 份（outline_state/tasks.py:61、writing/tasks.py:17），非历史候选所述 4 份——story 版含"提交早于快照机制"的回填分支（build+commit），收敛时须参数化或保留。
- **调用链证据**：见上；六处 F2-3 变体中 3 处在 story（含 F2 清单内 3 个 + fusion 变体为 F2 未列的第 7 处）。
- **现有契约**：AGENTS snapshot seam；README(tasks) checkpoint 契约；fusion CM 的"provider 前无事务"断言。
- **最小方案**：并入 F2-3/F2-4 批次：公开 snapshot CM 增加对应参数（timeout/是否内联 checkpoint/快照缺失策略）；F2-4 helper 收敛时把 fusion 次序变体归一为标准序（commit→断言→expire_all）并跑 fusion 任务测试。
- **预期收益**：随 F2-3/F2-4 主批（~110+40 行）；story 侧消除 4+4 处漂移面。
- **风险**：中低——`_require_llm_execution_snapshot` 回填分支涉及旧任务恢复语义，须保留 fail-closed。
- **依赖**：F2-9（llm_runtime 内部去重）先行；主批归 F2/D1。
- **验证命令/断言**：`make test TESTS="modules/story"`（含 test_task_ai_transactions/test_scene_fusion_draft/test_story_outline_generation）；固定输入 snapshot 恢复对比。
- **回滚**：逐调用方 revert。
- **裁定**：实施候选（与 F2 配对同批）
- **优先级**：P2

### D3a-3
- **ID**：D3a-3
- **位置/符号**：`backend/modules/story/generation.py:204-234 StoryGenerationService.one_click_preview`
- **问题与触发**：生产零调用。`handle_story_one_click` 有意按角色循环 `card_preview`+`reaction_preview`（每角色独立 reveal 上下文）再 `script_preview`，不走单次 `one_click_preview`；全仓 rg 仅定义点命中。
- **调用链证据**：`rg -n "one_click_preview" --type py` → 仅 generation.py:204/219。
- **现有契约**：无外部契约（模块内公共方法）。
- **最小方案**：删除该方法（~31 行）。
- **预期收益**：消除"看似可用的一次性 one-click LLM 路径"误导（其单次调用形态与授权逐角色上下文语义相悖，误用会破坏角色隔离）。
- **风险**：极低。
- **依赖**：无。
- **验证命令/断言**：`rg "one_click_preview" backend -g '*.py'` 归零；`make test TESTS="modules/story"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D3a-4
- **ID**：D3a-4
- **位置/符号**：`backend/modules/story/outline_state/ai_workflow_service.py:716 analyze`、`:757 generate`、`:253 generate_for_task`、`:401 generate_legacy_preview_for_task`、`:150-163 _open_llm_client`；连带 `generator.py:88 prepare_task_preview`、`:147 execute_task_preview`、`:177 require_task_preview_fresh` 仅剩这些死方法调用
- **问题与触发**：P20 v2（`generate_layer_for_task`）与 StoryOutline 新链（`StoryOutlineGenerationService.generate_for_task`）是 outline_generate/story_outline_generate 的唯一生产路径；旧整体生成/分析的 4 个服务方法仅 `tests/test_task_ai_transactions.py` 引用。`PlotStructureGenerator.generate` 本身仍活跃（imports/workflow.py:936 经容器 `outline.generate_structure` 调用；`apply_preview` 经 `apply_structure_preview` 旧契约分支可达）。
- **调用链证据**：rg 全仓：`analyze_for_task`（tasks.py:256 生产）；`generate_layer_for_task`（tasks.py:310 生产）；`generate_for_task`/`generate_legacy_preview_for_task`/`.analyze(`/`.generate(`（仅测试）。
- **现有契约**：3 个退役 handler（plot_structure_generate 等）已恒返回 unsupported；analyze_for_task 是 outline_analyze 的活跃实现（勿删）。
- **最小方案**：删除 4 个死方法+`_open_llm_client`，迁移 test_task_ai_transactions.py 中对应用例（保留 analyze_for_task 用例）；generator 三个 task-preview 方法随删或留待 generator 重构单独裁定。
- **预期收益**：~200 行服务侧+连带；消除"两代 outline AI 工作流并存"的阅读成本。
- **风险**：中——测试迁移量大（该文件 20 测试多数锚定这些方法）；删除属公开类方法收缩（模块内私有使用，无跨模块消费者）。
- **依赖**：与 E1 测试横查配对。
- **验证命令/断言**：`rg "generate_legacy_preview_for_task|OutlineAIWorkflowService\(\)\.analyze\(|\.generate_for_task\(" backend -g '*.py'` 仅剩 StoryOutlineGenerationService 版本；`make test TESTS="modules/story"`。
- **回滚**：revert。
- **裁定**：实施候选（测试迁移成本高，排在低风险批之后）
- **优先级**：P3

### D3a-5
- **ID**：D3a-5（=A3-2 领域侧，形态更新）
- **位置/符号**：`outline_state/foreshadowing_repository.py:19-84 get_by_novel` 与 `reveal_repository.py:16-101 get_by_novel`（各 ~40 行同构：SQL 过滤+全量载入+Python `included()` 过滤+`filtered[skip:skip+limit]`）；`outline_state/services.py:515-535 ForeshadowingPlanService.update` 与 `:597-616 RevealPlanService.update`（逐字同构）、create/create_batch 同型
- **问题与触发**：两者均已继承 StructurePlanRepository（F4 证据），但 get_by_novel 的 related_thread_id/unassigned 关系过滤各自复制；服务层 update/create 亦成对复制。分页在 Python 内完成（先载全量）。
- **调用链证据**：逐行比对两 repo/两 service。
- **现有契约**：列表过滤参数（related_thread_id/unassigned）与响应 total 语义（过滤后计数）。
- **最小方案**：基类 get_by_novel 增加可选 `relation_filter: Callable[[ModelT], bool]` ClassVar/hook（或子类声明 `related_thread_field`），两个子类各删覆写；service 层 update 上移 `StructureAssetFilterMixin`（该 mixin 已有 update 钩子，计划类无 user_edited 差异，需参数化 require_source）。
- **预期收益**：~80 行；新增计划类型不再复制过滤逻辑。
- **风险**：低；Python 内过滤语义（valid 集合依赖全量活跃 thread）必须保留或改为 SQL EXISTS。
- **依赖**：A3-1 主批（StructurePlanRepository 收敛）同文件簇。
- **验证命令/断言**：`make test TESTS="modules/story/outline_state/tests/test_foreshadowing_reveal.py"`（33 测试含 unassigned/related 过滤断言）。
- **回滚**：逐文件 revert。
- **裁定**：实施候选
- **优先级**：P3

### D3a-6
- **ID**：D3a-6（A3-3 story 面证据；X1-6 相邻但不等价）
- **位置/符号**：`outline_state/schemas.py:29-96 PlotThreadCreate/Update/Response`、`:109-187 OutlineArc*`（status: 自由 str≤32、无 extra="forbid"）；对照 `SceneCreate.status: Literal["draft","canonical"]`、`p20_schemas.py` 全 Literal、`generation/models.py:15 thread_type Literal`
- **问题与触发**：线程/篇章/信息计划的写路径接受任意 status 字符串（≤32），而查询/清理假设的词表是 {draft, candidate, proposal, canonical, deprecated}（services.py 清理过滤、repositories `status.in_(["draft","canonical"])` 活跃判定、analysis_context 再排除 abandoned）；deep import fallback 仍写入 legacy thread_type（secondary/hidden/foreshadowing）。生成侧 schema 已收敛 main/sub/background 且未知词拒绝（README 契约），CRUD 侧未跟上。
- **调用链证据**：PlotThreadCreate.thread_type: str max32 vs GeneratedThread Literal+归一映射；前端按 README"现有手工未知类型保留"。
- **现有契约**：对外 API 接受现状词表；旧记录含 legacy 词；README 声明前端保留未知旧分类。
- **最小方案**：不改接受范围的版本——在 `outline_state/schemas.py` 补 status/thread_type 词表常量并加 OpenAPI 文档化 description；收紧 Literal 属功能变更，须先清点现存行值（含 demo 重建语义可放宽）单独立项。
- **预期收益**：词表单一可查；为 X1-6 类枚举收敛提供 story 面清单。
- **风险**：收紧会拒绝既有合法旧值——默认不做。
- **依赖**：A3-3 主普查（F 组机制侧）。
- **验证命令/断言**：`rg -n "status" backend/modules/story/outline_state/schemas.py | head`；如收紧：`make test TESTS="modules/story"` + 存量词表清点。
- **回滚**：revert。
- **裁定**：保留现状（记录性发现；收紧需产品确认）
- **优先级**：P3

### D3a-7
- **ID**：D3a-7（F1-3 stable_hash census 的 story 面增补，cross-ref F1-3）
- **位置/符号**：同语义副本（`json.dumps(ensure_ascii=False, sort_keys, separators=(",",":"), default=str)`→sha256）：`story/tasks.py:60 _stable_hash`、`story/service.py:76 _hash_payload`、`outline_state/story_outline_generation.py:107`、`outline_state/scene_replacement.py:490`（无 default=str）、`outline_state/structure_dedup.py:1030`、`outline_state/p20_context.py:39 stable_hash`（公共，助手指纹依赖）、`outline_state/ai_workflow_service.py:620 _stable_fingerprint`、`outline_state/story_outline_service.py:522 _hash`（无 default=str）。结构异构变体：`story/proactive.py:169 _hash`（默认分隔符+无 default=str）、`outline_state/scene_resolution.py:64 fingerprint`、`outline_state/scene_execution_bundle.py:199 _hash`（dataclass 递归）、`outline_state/information_dependencies.py:139`（列过滤内联）
- **问题与触发**：F1-3 统计口径（`def _?stable_hash`）覆盖不到本槽位多数命名变体与内联点；story 面至少 8 个同语义定义 + 4 个异构变体，其中 p20_context.stable_hash 是助手采用包指纹的对外依赖、proactive._hash 仅用于任务提交/重放自洽（异构无碍）、scene_execution_bundle/information_dependencies 哈希进入 story_context_hash/basis（换实现即失效全部已存指纹）。
- **调用链证据**：rg `_stable_hash|_hash_payload|stable_hash|_hash(` 逐点读实现（见各文件行号）。
- **现有契约**：所有已持久化指纹（content_hash、basis_hash、source_fingerprint、context_hash、suggestion source_fingerprint）字节敏感。
- **最小方案**：并入 F1-3 批次：按变体分组迁移，`p20_context.stable_hash` 可作为 story 面临时权威（先改名导出），异构 4 处单独命名保留（指纹族不同，禁混同）；逐点固定输入样本断言字节不变。
- **预期收益**：story 面收敛 4-6 份；census 完整。
- **风险**：指纹失效风险集中——必须逐点样本比对，不可一次统一签名。
- **依赖**：F1-3 权威位置裁定（F2 认领）。
- **验证命令/断言**：迁移前后对固定样本（含 Unicode/None/UUID 字符串）哈希比对；`make test TESTS="modules/story"`。
- **回滚**：逐点 revert。
- **裁定**：实施候选（并入 F1-3 主批）
- **优先级**：P3

### D3a-8
- **ID**：D3a-8
- **位置/符号**：`outline_state/p20_service.py:1207-1295 _retire_stale_information_projections/_find_projection`（`select(model).where(novel_id)` 全量载入后在 Python 按 provenance_meta JSON 匹配；retire 在 `_apply_threads` 每线程循环内调用→O(threads×plans) 行载入）；`story/information_dependencies.py:58-164`（每次 basis hash/受影响场景计算全量载 PlotThread+SceneChapterLink+Scene+三类 plan）；`outline_state/world_dependencies.py:79-90`、`thread_facade.py:73-84`（有界 500）
- **问题与触发**：demo 规模下可接受（代码内 3 处 "ponytail" 注记自认）；大项目长篇应用时每次剧本保存（basis v2 必走 script_information_basis）与每次 P20 线程层采用都会放大。
- **调用链证据**：service.py:820/:1213 调 script_information_basis；p20_service._apply_threads:826 调 `_project_information_movements`→retire。
- **现有契约**：指纹/选择结果必须与现 SQL 语义逐条一致（JSON 精确成员判断，SQLite/PG 双方言）。
- **最小方案**：不改语义的版本——为 `projection_owner_thread_id`/`information_movement_id` 建 JSONB 表达式索引或改 SQL `->>` 过滤（PG+SQLite JSON1 双实现）；`script_information_basis` 可缓存 per-scene 章节集。收益待测：先按 performance.md 流程在大数据集建基线再动手。
- **预期收益**：收益待测（每次保存/采用减少 O(plans) 行载入）。
- **风险**：中——JSON 过滤跨方言行为需等价测试。
- **依赖**：性能基线（P2 链 4 取证）。
- **验证命令/断言**：`make test TESTS="modules/story"`+SQL 计数对比；性能按 docs/diagnostics/performance.md。
- **回滚**：revert。
- **裁定**：补证据（性能候选，不进第一批）
- **优先级**：P3

### D3a-9
- **ID**：D3a-9
- **位置/符号**：scene_index 分配锁不一致：advisory lock（`scene_workbench.py:2031 _next_scene_index`、`:1057 apply_replacement_suggestion`、`services.py:798 get_next_scene_index`←`create_scene_for_chapter`）；仅项目排它锁（`p20_service.py:904-909 _apply_scenes` 在 require_active_project_exclusive 后 `max(scene_index)+1`）；无锁（`services.py:945 split_chapters` 新建 Scene 的 shift+create、`POST /api/outline/scenes` 客户端自带 scene_index）
- **问题与触发**：scene_index 无唯一约束（scene_workbench.py:2033 注释自认"无唯一约束兜底"），普通创建路径本就允许重复 index；P20 采用与 split 的新建路径不取 advisory lock，理论上与 fusion/quick-create 并发可撞号。产品语义上 index 是软排序（reorder 要求全集合），重复仅造成显示顺序不稳定。
- **调用链证据**：各路径读码；`api_create_scene`→`SceneService.create`→`repo.create` 直用 `data.scene_index`。
- **现有契约**：现有 wire 允许客户端指定 index；无唯一约束。
- **最小方案**：P20 `_apply_scenes` 与 `split_chapters` 新建分支补 `repo.lock_scene_order`（两处各 1 行，语义不变、只增串行化）；统一"所有服务端分配必须持锁"约定写入模块 README。不做唯一约束迁移。
- **预期收益**：消除服务端路径撞号的并发窗口。
- **风险**：极低（锁粒度为 novel 级事务锁，仅在写路径）。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/story/outline_state/tests/test_p20_layer_generation.py test_scene_workbench.py"`。
- **回滚**：revert。
- **裁定**：实施候选（顺手批）
- **优先级**：P3

### D3a-10
- **ID**：D3a-10
- **位置/符号**：`story/assistant_tools.py:86/:199-200/:257` 调 `StoryService()._require_character/_require_scene` 私有方法；`story/assistant_information_tools.py:19 from modules.story.service import _hash_payload`
- **问题与触发**：同包内跨文件私有访问（非跨模块越界，包边界未破）；`_hash_payload` 为哈希族收敛（D3a-7）前的临时耦合。
- **调用链证据**：读码。
- **现有契约**：无。
- **最小方案**：`_require_scene/_require_character` 提为模块级函数或 StoryService 公共方法（改名 require_scene/require_character）；hash 随 D3a-7/F1-3 批次归位。
- **预期收益**：边界可读性；低收益顺手改。
- **风险**：无。
- **依赖**：D3a-7。
- **验证命令/断言**：`make test TESTS="modules/story/tests"`。
- **回滚**：revert。
- **裁定**：实施候选（顺手批）
- **优先级**：P3

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A5-1 story/api.py 两 enqueue 95% 相同 | 仍成立（扩大） | `_enqueue_confirmed_task`(448-505) vs `_enqueue_one_click_task`(508-568) 差异仅常量+2 个 meta 键；outline_state/api.py 另有 3 处同形流。见 D3a-1 |
| A3-3 业务枚举 Literal→StrEnum（story 面） | 部分成立（需按兼容面分批） | story 严格面已 Literal 化（p20/schemas/scene/generation）；缺口在线程/篇章 CRUD status 自由字符串与 legacy thread_type 词（见 D3a-6）；收紧=接受范围变更，须存量清点后单独立项 |
| A5-6 prepare/finalize 冻结序列 helper | 待查→按现状裁定（story 侧基本已覆盖） | 历史无位置明细，无法逐字对回。story 现状冻结序列已由既有 seam 承载：`prepare_confirmed_ai_action`（evidence facade）+`restore_project_llm_execution_settings`+create_context_snapshot（story/tasks.py `_prepare_task_input`）；剩余可收敛部分是 checkpoint 三步（归 F2-4/D3a-2），非独立 helper。历史收益估计不继承 |
| A5-10 stable_hash 收敛（调用方 story_outline_generation.py:550） | 仍成立（census 需增补） | :550 现为 `_open_task_client`（A5-2/F2-3 配对点）；该文件 stable_hash 定义在 :107，用于 source_fingerprint/source_refs（:474/:1043-1095）。story 面 8 同语义+4 异构点，见 D3a-7。与 F1-3 合并裁定 |
| A5-2/F2-3 六处私有 snapshot CM（调用方侧） | 仍成立（story 侧 4 处） | F2 清单 3 处在位（tasks.py:444、story_outline_generation.py:549、ai_workflow_service.py:166）+ fusion 变体 scene_fusion_draft.py:284（F2 未列）。见 D3a-2 |
| A5-3/A1-7 checkpoint/快照链（调用方侧） | 仍成立（清单增补） | story checkpoint 三步 4 处（2 处未入 F2-4 清单）；`_require_llm_execution_snapshot` 历史称 4 份，现全仓 2 份（outline_state/tasks.py:61 含 legacy 回填、writing/tasks.py:17）——部分已解决。见 D3a-2 |
| X1-6 story 工作流状态词汇与 TaskStatus 关系（独立核实） | 不等价、不立项（与 D7 判断一致） | story 生产码不直接写 AsyncTask.status（`_mark_confirmation_task_terminal` 传给 attach_result_ref 的 "cancelled/failed" 是 result-ref 状态词，非队列态）；领域词汇各自成体系：scene {candidate,draft,canonical,deprecated}+planning_state、fusion 建议 {pending,adopted,dismissed,stale}、计划状态词表、review/needs_review 元数据。与 TaskStatus 无同形转换，禁止误等价 |
| A3-1 PlotThread/OutlineArc 收敛 StructurePlanRepository（领域侧） | 仍成立（语义差异已定位） | 两 repo 未继承（F4 证据）；关键差异：PlotThread.update 以 `value is not None` 判提供（无法清空可空字段），OutlineArc.update 以 `model_fields_set` 判提供（title/status 例外不可清）——收敛必须参数化"提供判定"钩子，证实 F4"钩子覆写式非纯 4 行"判断。另 D3a-5 补充计划类 update/get_by_novel 同构 |
| A3-2 reveal/foreshadowing 45 行重复 | 仍成立（形态更新，规模≈80 行） | 两 repo 各自覆写 get_by_novel（~40 行同构，Python 过滤+切片）；两 service update/create 成对逐字同构。见 D3a-5 |
| A3-5 手写 novel_id 列（story 面） | 已解决（story 面已收敛） | F4 共享事实 1：story 8 类+continuity 1 类已用 NovelMixin；本槽位 models 引用核对一致（models 文件归 F4） |
| X1-S3 story/facade 死导出 3 项 | 部分成立（需逐符号复核归主 Agent） | 逐符号外部消费 grep：`get_scene_story_basis_hash`、`persist_one_click_character_cards` 零跨模块消费者（仅 story 模块内使用，属"facade 公开面>实际消费面"）；`inspect_information_plan` 有 evidence/compilation/novel_evidence.py 消费、`get_scene_story_assets` 有 writing 消费、`get_scene_story_context` 有 evidence+writing 消费——历史"3 项"无法对应到现存符号，按现状以上述 2 项为候选（facade 面收缩需 public-surface 测试联动） |
| A3-6/A9-12 squash、迁移类项 | 不适用 | 归 F4，story 面无迁移文件 |
| Wave0/Phase1 其余落在 story 的项 | 无 | audit 各表中无其它 story 路径候选；`tools/deepseek_scene_probe`、frontend-console/docs 等均不在本槽位 |

## 共享事实（供 W3 链 4：总纲/篇章/Scene→Context 确认→Story/正文候选→审查/返修→采用/发布）

### 1. outline_state 状态机与权威源

- **StoryOutline**：权威源 `story_outline_heads.current_revision_id`；revisions 不可变（DB trigger，F4）；写路径一律 `lock_or_create_head`（PG advisory lock `story-outline:<uuid>` + FOR UPDATE）→ `_assert_base_revision` CAS → `idempotency_key+request_hash` 幂等。AI 采用额外要求 completed 任务回执 `replace_completed_task_result` CAS（revision_token）+context_provenance 版本/哈希校验（story_outline_service.py:428-491，project source ref 必须等于 novel_id）。
- **Scene**：状态 {candidate, draft, canonical, deprecated}（无硬删，deprecate 带 `deprecated_reason/deprecated_at/replaced_by_scene_ids/fused_into_scene_id` 回指）；`structure_meta.planning_state` {planned, materialized} 区分 P20 规划 Scene；语义字段状态（present/not_applicable/uncertain）只信任特定 source/semantic_origin（contracts.py:346-397 白名单：deep_import、manual_fusion、phase1b/1c、author_reviewed、p20_planned_scene），manual Scene 恒 None 保持历史行为。scene_index 软排序、无唯一约束（D3a-9）。
- **剧情线/篇章/信息计划**：status 词表实际为 {draft, candidate, proposal, canonical, deprecated}（+abandoned 在 analysis_context 被排除）；活跃判定惯例 `status.in_(["draft","canonical"])`；provenance_meta 承载 source/workflow_id/auto_ingested/user_edited/needs_review/cleanup_status/ai_revision_history/p20_* 指纹。写路径 schema 未收敛词表（D3a-6）。
- **信息推进投影（P20）**：ForeshadowingPlan/RevealPlan 由 PlotThread.information_movements 投派生，所有权用 `provenance_meta.information_movement_id`（uuid5(thread_id+movement_ref) 确定性）+`projection_owner_thread_id`；采用时 `_retire_stale_information_projections` 退役不再存在的投影（退役保留 related_thread_ids 剥离而非硬删，最后一个 owner 才 deprecated）。reveal 投影缺 target/hidden_content 时跳过物化并标 needs_review（不伪造）。
- **Scene 融合/替换建议**：`scene_fusion_suggestions.status` {pending, adopted, dismissed, stale}；durable 指纹 `source_fingerprint`（scene_replacement.py:27）+suggestion_key；过期→stale（apply 路径 persist_stale 提交）。basis_manifest v1/v2 双版本：v2 记录关联剧情线/篇章/信息计划指纹（service.py:826-834），staleness 按存储版本分算法。
- **执行束（writing 消费）**：`SceneExecutionBundleContract`（contracts.py:324-343）= scene+story_outline revision+story_execution_profile+upstream_manifest+contract_hash+可选 story_assets/story_assets_hash；story_assets 由 story/facade.get_scene_story_assets 提供（adopted-only，hash 含 basis 排除自身逻辑）。

### 2. Scene 生命周期关键路径

创建：manual（POST /scenes 客户端 index）、quick-create（advisory lock+max+1）、P20 planned（project exclusive+max+1）、deep_import（imports commit 全 Scene 行锁+保护性重叠成组建议）、fusion（advisory lock）。更新：SceneService.update 持行锁做 structure_meta read-modify-write（防 review/merge 丢键）+user_edited 标记。断章/拆分/融合均"预览无副作用+保存重验"。删除=deprecated+span 镜像（SceneRepository.delete 场景仅直接硬删走 repo.delete，产品路由走 deprecate）。SceneSpan 是 scene_chunks 的派生读模型（sync_scene_spans 镜像），reanchor 状态机 exact/reanchored/chapter_only/unresolved（scene_source_service.py:309-354），checkpoint 按 based_on_hash 重验防静默过期。

### 3. assistant 工具面（story OPERATIONS 全集，经 app/bootstrap 注册）

`story.save_outline`、`story.create_scenes`、`story.save_card`、`story.save_script`、`story.edit_scene`（assistant_tools.py）；`story.create_thread`、`story.create_arc`（assistant_planning_tools.py）；`story.edit_information_plan`（assistant_information_tools.py）；`story.plan_structure`（permission=suggest，读回执 read_result）、`story.adopt_structure`（assistant_structure_workflow.py）。共同形态：preview→(作者确认)→apply 内重算 preview 全等比较（CAS）→领域服务落库；provenance 记 assistant_run_id/approved_by。plan_structure 强制整层范围（拒绝排除项/子范围确认），复用 `OutlineAIWorkflowService.submit_layer_generation` 与 P20 采用包；adopt 校验 contract_version=outline_layer_v2+requires_apply+确认沿用。

### 4. 旧公开前缀与任务类型清单（本槽位持有的 api.py）

- `/api/outline`（outline_state/api.py，router prefix :105）：story-outline 5 路由（get/revisions CRUD/apply/generate/generate-apply）、threads 5、arcs 5、scene-workbench 17（含 deprecated 的 fusion/preview 同步路由与 preview-task 任务路由）、scenes 9、analyze/generate/generate-apply 3、foreshadowing 5、reveals 5。`require_active_project` 全覆盖。
- `/api/story`（story/api.py，prefix :73）：character-cards 6、script-files/revisions 7、story-context 1、tasks 4（card/reaction/script/one-click）、scene-centric 别名 10（Scene 视角 wire，均转发资源型路由+path/body 一致性校验）。
- `/api/novels/{novel_id}/memories`：continuity/api.py（D3b 持有，不在本槽位覆盖行）。
- 任务类型：活跃 `story_reference_review`(manual_resume)、`story_character_card_generate`/`story_reaction_propose`/`story_scene_script_generate`/`story_one_click`(auto_requeue≤2+retry_transient_llm)、`story_outline_generate`/`outline_analyze`/`outline_generate`/`scene_fusion_preview`(auto_requeue≤2)、退役恒 unsupported `plot_structure_generate`/`chapter_card_extraction`/`chapter_scene_generate`。

### 5. LLM 输入构造与预算（链 4 相关）

- **Story 四预览**：confirmation 重物化（prepare_confirmed_ai_action）→ 逐角色独立 compile_with_tiers（budget 6000 tokens，reveal_mode=character，visible_until=当前 Scene）→ context snapshot（story 相位）→ one-click 额外 source_hashes（outline 投影剔除自身回灌+compiled sections+文本哈希）+ 终局双围栏（context_hash 重验+source_hashes 重验）+project exclusive 后才持久化。输入上限 96k chars/输出 48k，timeout 1800s，temperature 0.45。
- **StoryOutline**：提交时 prepare 定 fingerprint（top-k：world 24/character 12/entity 24，显式选择优先+排除确认资产不可回流）→任务内 prepare 重验→生成（1 候选+3 审计[证据/正史污染/世界规则]+1 语义修订共享 30min 预算）→fresh prepare 重验。本地正则拦截"总纲写章号日程"。输入上限 96k chars，超限 fail-closed。
- **P20 v2**：确认必须 budget_tokens=0（无淘汰）；prepare 4 次/生命周期（提交、任务初、生成后 fresh、排它锁内 locked_fresh）；候选+每轮 3 并行审计（evidence/scope_rule/author_instruction）最多 2 次语义修订；短引用完整性+信息节点时间序为确定性违规。采用时再次双段 freshness+begin_nested。
- **Scene fusion v2**：证据仅取 hash 校验通过的精确 span 文本；confirmed author 任务带 pinned Scene 集校验、不加载 legacy overlay；任务模式禁确定性降级、锁章节版本重验证据指纹；同步模式可降级并明示"AI 调用未完成"。
- 六处/四处 snapshot CM 与 checkpoint 序列现状见 D3a-2（收敛主批归 F2-3/F2-4）。

### 6. 其他（不构成发现）

- `_workbench_error`（outline api）将 PermissionError 映射 400，story/api `_error` 映射 403——两个前缀的既有 wire 差异，前端按各自 surface 消费；统一属功能变更。
- `apply_replacement_suggestion` 端点对 persist_stale 冲突显式 `db.commit()`（api.py:1019-1022）保留 stale 标记——有意设计。
- story 测试 autospec 合规：所有 `mock.patch` 调用均带 autospec=True（已逐点核验 test_foreshadowing_reveal/test_scene_fusion_draft）；monkeypatch 用于 settings/方法替换，无 mock 失真迹象（横查归 E1）。
- README 与实现核对一致；`outline_state/__init__.py` 的 V1 docstring 已过时但不误导（可顺手更新，不值发现项）。

## 受阻

无。备注两点覆盖方法说明：(1) scene_workbench.py（3062 行）、repositories.py（1918 行）、generator.py、structure_dedup.py、scene_draft_review.py、deep_import_repair_service.py 及 generation/ 子包采用"结构清单+关键段精读"覆盖（关键段=入队/锁序/融合/替换/持久化/快照路径），已在覆盖行逐路径标注；(2) 测试文件以 conftest 全文+测试名清单逐条+抽读方式覆盖，断言有效性抽查未发现削弱点。
