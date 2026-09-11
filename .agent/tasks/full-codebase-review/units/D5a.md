# D5a 槽位报告（R07 imports：解析/切分/融合/抽取/去重/预检/断点恢复阶段流水）

日期：2026-09-11。基线：`main` @ `e7d0b8d5b`（coverage-ledger.csv 指纹）。全部只读审查；
未运行测试/构建/make，无网络。slot-paths-W2.json D5a 数组 34 个路径逐一语义阅读完成，
无受阻项。范围内无 WIP 文件（api.py/test_import_api.py 归 D5b，未审）。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/imports/chapter_loader.py,已审,workflow.py:330 / orchestrator.py:1021,1112 / phase2_world_extraction.py:794 / workflow_llm_adapters.py:338,无发现：批量加载与 include_missing 语义正确
backend/modules/imports/completion_control.py,已审,api（D5b）defer/resume/recent/impact 入口,D5a-12b：跨 orchestrator 私有成员访问；defer/来源清单重验与 generation 递增语义正确
backend/modules/imports/completion_hints.py,已审,parallel.py:555 / alias_relation.py:373,无发现：hint 须名字可在 source_text 定位且有有效 quote；与 README 契约一致
backend/modules/imports/context_snapshot_helpers.py,已审,snapshots.py:51,无发现：脱敏 snapshot payload、v2 activation 与 legacy 双形态、token 估算闭合
backend/modules/imports/deep_import_dedup.py,已审,workflow_structure_phase.py:69（Phase 3 后结构去重）,无发现：auto_apply 需同 workflow+confidence>=0.96；失败降级保留候选
backend/modules/imports/deep_import_retry.py,已审,scene_slicing/enrichment/fusion/phase2_world 各阶段 retry 入口,无发现：错误五类分类、重试硬性钳 1 次、redact_diagnostic 脱敏
backend/modules/imports/entity_extraction/__init__.py,已审,稳定公共导出面（README 指定）,D5a-5b：__all__ 导出私有符号（_alias_relation_failure_scene_index 等 2 个）作 monkeypatch seam
backend/modules/imports/entity_extraction/scene_entity_alias_relation.py,已审,SceneEntityExtractionService._execute_alias_relation_phase（Phase 2b 主路径）,D5a-7b（synthesis 无关）；D5a-8a（fence 双份）；D5a-5 死 helper（_trim_phase2b_scene_text/_compact_entity_index_for_scene/_build_alias_relation_entity_index/_scene_indices_for_failure 仅测试或零引用）；checkpoint/超时/降级语义无缺陷
backend/modules/imports/entity_extraction/scene_entity_alias_relation_task.py,已审,world_alias_relation_extraction 任务 DI seam（prepare/execute/finalize）,无发现：confirmation 重验、receipt hash、manifest 漂移拒绝、strict 持久化事务隔离均闭合
backend/modules/imports/entity_extraction/scene_entity_bulk.py,已审,SceneEntityExtractionService bulk/small-sample 分支,D5a-1（P1：LOTM 硬编码 prompt 生产可达）；D5a-5c（small_sample_supplement_timeout_seconds getattr 动态反查）；fallback 占位候选 begin_nested 保护正确
backend/modules/imports/entity_extraction/scene_entity_checkpoint.py,已审,Phase 2a/2b checkpoint 与指纹,无发现：scene_input_fingerprint v1/v2、phase2_checkpoint_by_scene 兼容两种形态；fail-safe 指纹缺失即重跑
backend/modules/imports/entity_extraction/scene_entity_config.py,已审,Phase 2 全部旋钮,A2-2 复核（薄声明式包装无动态反查）；ContextVar settings context 与 high_quality 倍增语义正确
backend/modules/imports/entity_extraction/scene_entity_extraction.py,已审,extract_by_scenes/extract_alias_relations 生产主入口,无重大发现：持久化 Scene 恒走 parallel v3 路径（:297）；legacy 分支仅为测试/临时 Scene；D5a-5a（~40 个兼容 wrapper）
backend/modules/imports/entity_extraction/scene_entity_llm_adapters.py,已审,call_llm_extraction/call_alias_relation_extraction（P13 v4/P14 v5）,D5a-11（新对象 name∉Scene 未强制拦截）；确定性 materializer（证据逐字定位/ref 重验/字段缺证清空）与 finally close 均正确
backend/modules/imports/entity_extraction/scene_entity_parallel.py,已审,Phase 2a 生产主路径（ImportContextActivation v3 并发）,D5a-7a（updated_context/accumulated_memory 只写不读）；checkpoint 跳过指纹、降载（单波 429 或 2 传输失败减半）、provider 前关事务均与 README 一致
backend/modules/imports/entity_extraction/scene_entity_persistence.py,已审,_persist_entities/relations/alias_relation_output/deltas,无重大发现：同名 working 确定性复用、高置信语义相似仅记录建议不自动合并、P14 十二类拒绝 reason、stale previous relation 冻结重验；对照 AGENTS 别名附着/不重复建实体边界无违规
backend/modules/imports/entity_extraction/scene_entity_phase2b_context.py,已审,Phase 2b 冻结上下文契约,无发现：confirmation selected/excluded 过滤、prompt/私有字段分离、fingerprint、注入转义闭合
backend/modules/imports/entity_extraction/scene_entity_single_scene.py,已审,serial per-Scene 路径（legacy/临时 Scene；batched 内部）,D5a-4（zip 错位 bug，生产不可达）；SingleSceneEntityExtractor 兼容类仅测试
backend/modules/imports/entity_extraction/scene_entity_snapshots.py,已审,Phase 2/2b context snapshot,无发现：profile resolver 同源脱敏、context_bundle 时 source_refs fail-closed
backend/modules/imports/entity_extraction/scene_entity_strategy.py,已审,Phase 2 路由选择,无发现：empty/checkpoint_resume/small_sample/bulk/batched 判定简单正确
backend/modules/imports/entity_extraction/scene_entity_text.py,已审,Scene 正文与上下文 helper,无发现：select_scene_text 优先 exact offset、段落 fallback、整章兜底；trim 仅 small-sample supplement 路径
backend/modules/imports/llm_schemas.py,已审,Phase 1/2 全部 LLM 输出 schema,无发现：宽松 coerce 后仍受枚举/逐字证据/extra=forbid 约束；SceneChunk offset 配对校验正确
backend/modules/imports/parsers.py,已审,services.py:76（上传主路径）/ source_update.py:57（RP source）,D5a-9：parse_txt 死分支 + 空 content 章节无条件 append；EPUB/MOBI 有界校验与安全成员路径校验闭合
backend/modules/imports/phase1a_context.py,已审,workflow_scene_phase（Phase 0 上下文冻结）,无发现：author_safe canonical 过滤、fingerprint 校验 apply 时 fail-closed、novel_id 校验
backend/modules/imports/phase2_world_extraction.py,已审,生产零调用（仅 evals/prompt probe _to_delta_event + 测试）,D5a-3（P2：window 级路径与 Phase2WorldExtractor 生产不可达；existing_checkpoints 形参接受即丢弃）
backend/modules/imports/scene_candidates.py,已审,workflow_scene_phase.py:795（仅 ScenePrefetchResult/SceneCandidate）,D5a-6：SceneReinforcementResult/SceneCandidateBatch/SceneCandidateQuality/build_scene_candidate_quality_stats 零引用
backend/modules/imports/scene_commit.py,已审,workflow_scene_phase（Scene commit 最终 fenced 写入）,D5a-12a：suggestion 引用 conflict 候选时静默丢弃；重叠 fail-closed 断言与冻结覆盖校验无缺陷
backend/modules/imports/scene_enrichment.py,已审,workflow_scene_phase（Phase 1b）,无发现：source integrity 六类校验、field_evidence 逐字定位失败即清空+uncertain、锁定字段保护与 README 一致
backend/modules/imports/scene_fusion.py,已审,生产仅用 FinalSceneCandidate/Phase1bReducerOutput,D5a-2（P2：Phase1bSceneFusion 等 ~1000 行死代码内嵌 LOTM 情节锚点与 1-7 章特化）；活模型 validators 无缺陷
backend/modules/imports/scene_fusion_phase1c.py,已审,workflow.py:438（高质量 Phase 1c）,D5a-7b：synthesis 相关窗口过滤器（split(":")）永不命中恒走全部窗口；boundary review 分组/证据校验/高置信连通组语义与 README 一致
backend/modules/imports/scene_planning.py,已审,Phase 0 确定性窗口规划,A2-2 复核（6 个旋钮薄包装）；窗口/overlap/max_tokens clamp 与 README 公式一致
backend/modules/imports/scene_slicing.py,已审,Phase 1a 主路径（Phase1aSceneSlicer）,无重大发现：锚点唯一命中物化、精确重叠隔离+恢复+章节 fallback、缺口吸收与覆盖校验 fail-safe；循环结构复杂但各步诊断完整
backend/modules/imports/targeted_completion.py,已审,deep_import workflow 的 targeted_completion 阶段 + rollback 入口,D5a-10：batch_snapshots/context_fingerprints 列表翻倍冗余；授权冻结重验、100k 输入预算、0.90 门槛、partial 恢复、幂等回滚均与 README 一致
backend/modules/imports/worldbuilding_risk.py,已审,生产零消费者（rg 全仓无 import）,D5a-6 附注：ImportWriteRiskClassifier 当前无生产调用方（Worldbuilding Workspace v1 遗留），删除前需核对 D2 槽位
```

## 发现

### D5a-1
- **ID**：D5a-1
- **位置/符号**：`backend/modules/imports/entity_extraction/scene_entity_bulk.py:416-423`（`_supplement_small_sample_entities_with_llm` 的 `memory_context`）；连带 `:56-78`（`bulk_entity_memory_context` 的 1-7 章特判）
- **问题与触发**：小样本补充 sweep 的 prompt `memory_context` 硬编码《诡秘之主》具体实体与设定——"重点检查：周明瑞/克莱恩别名、莫雷蒂家庭、廷根地点、黑夜女神教会与值夜者线索、塔罗/灰雾/占卜/转运仪式、奥黛丽、阿尔杰、非凡者、魔药、罗塞尔日记和塔罗会规则"——并含内部评测名"前一轮抽取低于 Codex5.3 标准"。触发条件：Phase 2a 路由为 `small_sample_parallel`（8-12 个 Scene）且首轮抽取数低于 `PHASE2_SMALL_SAMPLE_TARGET_ENTITIES=29` 时自动调用 supplement。`bulk_entity_memory_context` 在 `chapter_ids == {1..7}` 时向 bulk 提示注入"神秘学概念/力量体系、组织/教会/聚会"等特定题材引导——任何用户的小说导入第 1-7 章即命中。
- **调用链证据**：`extract_by_scenes`（scene_entity_extraction.py:352-362 small_sample_parallel 分支）→ `bulk_result` 后 `_supplement_small_sample_entities`（:407-413，`created < 29` 即触发）→ `_supplement_small_sample_entities_with_llm`（bulk.py:386-464）→ `_call_llm_extraction(memory_context=…)`。bulk 提示经 `_process_scenes_bulk`（bulk.py:144）注入。持久化侧由 materializer 的"证据必须逐字位于当前 Scene"门禁兜底，幻觉实体多数不会落库，但每次 sweep 都发送无关指令，浪费预算并系统性偏置抽取。
- **现有契约**：AGENTS.md"默认用作者/读者语言…不暴露内部心智模型"；imports README 无任何 1-7 章或特定作品特化的授权；该文本是早期 1-7 章真实语料验收的遗留。
- **最小方案**：删除《诡秘之主》专有实体列表与 "Codex5.3" 字样，改为通用措辞（"补充遗漏的长期资产，目标不超过 N 个；只依据当前正文与已有对象"）；`bulk_entity_memory_context` 删除 `set(range(1,8))` 特判分支，统一通用提示。
- **预期收益**：消除对所有用户 1-7 章导入的第三方内容注入与题材偏置；移除版权作品梗概的源码级硬编码。
- **风险**：低。1-7 章验收基线指标可能变化（当时按该语料调参），需在改动说明中记录；无对外接口变化。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`；`rg "克莱恩|周明瑞|塔罗|Codex5.3" backend/modules` 生产码归零；固定输入的 supplement prompt 对比。
- **回滚**：单文件 revert。
- **裁定**：实施候选（功能性修复，非纯优化；按计划 §2 单列）
- **优先级**：P1

### D5a-2
- **ID**：D5a-2
- **位置/符号**：`backend/modules/imports/scene_fusion.py:29-107`（`LOTM_1_TO_7_EVENT_ANCHORS`，78 行《诡秘之主》第 1-7 章情节锚点）；`:876-879`（`scene_count_guidance` 含"不要把塔罗占卜、转运仪式、灰雾会面、非凡者交易和代号聚会合并吞掉"）；`:461-480`（手写 getenv）；`:428-846`（`build_phase1b_windows`/`Phase1bWindow`/`Phase1bSceneFusion`）；`:991-1343`（fallback helper 链）；`:408-417`（`Phase1bFusionResult`）
- **问题与触发**：旧 Phase 1b windowed reducer 全链生产零调用——`rg "Phase1bSceneFusion|build_phase1b_windows|Phase1bWindow|Phase1bFusionResult"` 仅命中本文件与 `modules/imports/tests/test_scene_fusion.py`、`test_workflow.py`；`workflow_llm_adapters.py` 只 import `Phase1bReducerOutput` 模型。生产 Scene 流水为 Phase1aSceneSlicer → Phase1bSceneEnricher → Phase1cSceneFusionService（workflow.py:438）。死代码内嵌约 180 行第三方版权小说情节文本与 `chapters == set(range(1,8)) → 目标 9 个 Scene` 的特化逻辑；一旦被复活/复制即把该内容注入任意用户请求与 fallback Scene 字段。
- **调用链证据**：见上；活符号仅为 `FinalSceneCandidate`（scene_enrichment/commit/phase1c 使用）、`Phase1bReducerOutput`（workflow_llm_adapters.py:793,1462）及其 validator 依赖的 `_coerce_score`/`_normalize_discard_reason`/`_unique_sorted`。`workflow_llm_adapters.py:779 _Phase1bSceneFusionLLM`（D5b 文件）同为死代码。
- **现有契约**：imports README 内部结构节称 scene_fusion.py 为"内部兼容/修复路径使用的候选融合组件"——但 rg 证实无生产调用方，文档表述与实际可达性不符。
- **最小方案**：删除 `LOTM_1_TO_7_EVENT_ANCHORS`、`Phase1bSceneFusion`、`build_phase1b_windows`、`Phase1bWindow`、`Phase1bFusionResult`、`_WindowFusionResult` 及仅被其调用的 helper（`_fallback_candidates_for`、`_deterministic_final_candidates_for`、`_with_chapter_coverage_fallbacks`、`_with_minimum_scene_count_fallbacks`、`_chapter_fallback_candidates`、`_chapter_event_anchor`、`_build_window_payload`、`_recommended_scene_count`、`_candidate_summary` 等）；保留 `FinalSceneCandidate`/`Phase1bReducerOutput`/共享 coerce；迁移或删除 test_scene_fusion.py 中针对 reducer 的测试。同批处理 workflow_llm_adapters.py 的 `_Phase1bSceneFusionLLM`（cross-ref D5b）。
- **预期收益**：约 1000 行死路径删除；消除第三方内容驻留与"两套 Phase 1b 语义"的误用面。
- **风险**：测试迁移量大（两个测试文件）；须逐符号确认 `_fallback_candidates_for` 等无 FinalSceneCandidate 生产调用方（已核：仅死链内部互调）。
- **依赖**：与 D5b 协调 workflow_llm_adapters.py 同名死类。
- **验证命令/断言**：`rg "Phase1bSceneFusion|LOTM" backend` 仅剩历史记录；`make test TESTS="modules/imports/tests"`；`make docs-check`（README 内部结构节同步）。
- **回滚**：单文件 revert + 测试还原。
- **裁定**：实施候选
- **优先级**：P2

### D5a-3
- **ID**：D5a-3
- **位置/符号**：`backend/modules/imports/phase2_world_extraction.py:87-543`（`Phase2WorldExtractor` 及 `run/_run_windows/_process_window/_persist_outputs`，约 1250 行）
- **问题与触发**：window 级 Phase 2 路径生产不可达。`rg "Phase2WorldExtractor"` 全仓仅 phase2_world_extraction.py 自身、3 个模块测试、evals/prompt-contract probe（`_to_delta_event` 与 fixture 字符串）。生产 Phase 2 入口是 `workflow_entity_phase.py → workflow._extract_entities_by_scene → SceneEntityExtractionService.extract_by_scenes`（Scene 级 v3 activation）。`run(existing_checkpoints=…)` 在 :122 `del existing_checkpoints`——形参接受即丢弃，进一步证明该路径无 checkpoint 恢复消费。README"Phase2WorldExtractor 继承同一实现"描述与"生产主路径是 SceneEntityExtractionService"的现实并存，但未标注本文件生产不可达。
- **调用链证据**：见上；`_to_delta_event`、`Phase2WorldDelta`（llm_schemas）是 probe 依赖的活符号；`phase2_world_window_v1` 参数版本另被 story/outline_state/generation/parser.py 作为字符串消费（outline 侧，与本类无关）。
- **现有契约**：README 内部结构节；prompt-contracts fixtures（phase2_world_extraction.json）依赖 `_to_delta_event` 契约稳定。
- **最小方案**：保留 `_to_delta_event` 及 probe 契约（迁至 llm_schemas 旁或保留小模块），删除 `Phase2WorldExtractor` 类与 window 级 run 链；迁移 test_chapter_loader/test_scene_phase_refactor/test_workflow 中相关用例；README 内部结构节同步。归 P3 亦可接受（无内容卫生问题），列为 P2 因体量与"两套 Phase 2 输入契约"误用面。
- **预期收益**：约 1200 行死路径删除；Phase 2 语义单一（Scene 级）。
- **风险**：evals/prompt_contracts 的 fixture 复核（probe 只用 `_to_delta_event`，可保留）。
- **依赖**：无跨槽依赖；README 同步。
- **验证命令/断言**：`rg "Phase2WorldExtractor" backend` 归零（除历史记录）；`make test TESTS="modules/imports/tests"`；prompt-contract 门禁。
- **回滚**：单文件 revert + 测试还原。
- **裁定**：实施候选
- **优先级**：P2

### D5a-4
- **ID**：D5a-4
- **位置/符号**：`backend/modules/imports/entity_extraction/scene_entity_single_scene.py:169-176`（`_process_scene` 的 `updated_context` 构造）
- **问题与触发**：`new_names = [e.name for e in entities if create_new]` 后 `zip(new_names, extraction.entities)` 按位置配对——实体混合 `link_to_existing` 与 `create_new` 时名字与实体错位：第一个新实体行丢失、后续新实体名配到别的实体类型。正确写法已在 scene_entity_text.py:270-281 `append_extracted_entities_to_context` 存在。
- **调用链证据**：`extract_by_scenes` :297 对全部持久化 UUID Scene 恒走 parallel 路径；`_process_scene` 仅在 legacy 临时 Scene 分支（:512-681）与 `_process_scenes_batched`（batched 内部串行）可达——两者生产不可达（测试/临时字典专用，注释 :293-296 自述）。
- **现有契约**：`updated_context` 是串行路径传给后续 Scene 的已有对象提示，仅进 prompt 不进资产。
- **最小方案**：改为 `f"- {e.name} ({e.entity_type})" for e in extraction.entities if e.suggested_action == "create_new"`，或直接复用 `append_extracted_entities_to_context`。
- **预期收益**：修复 legacy 路径实际逻辑错误；两处同语义实现归一。
- **风险**：极低（生产不可达路径）。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests/test_scene_entity_extraction.py"`；混合 action 实体的单测断言。
- **回滚**：revert。
- **裁定**：实施候选（顺手修）
- **优先级**：P3

### D5a-5
- **ID**：D5a-5
- **位置/符号**：a) `entity_extraction/scene_entity_extraction.py:726-1832`（"Compatibility wrappers"节约 40 个 1-3 行 wrapper，占文件近半）；b) `__init__.py:96-97,182-183`（`__all__` 导出 `_alias_relation_failure_scene_index`/`_effective_alias_relation_total_timeout_seconds`）；c) `scene_entity_bulk.py:32-43`（`small_sample_supplement_timeout_seconds` 经 `getattr(public_module,…)` 动态反查公共模块常量，且 if 结构冗余恒等价于 getattr 值）；d) 五个兼容 adapter 类（`SingleSceneEntityExtractor`/`ParallelSceneEntityExtractor`/`BulkSceneEntityExtractor`/`AliasRelationExtractor`/`SceneEntityPersistenceGateway`/`AliasRelationTaskWorkflow`，各文件尾部，`__getattr__` 全转发）；e) `scene_entity_alias_relation.py:794-807`（`_scene_indices_for_failure` 全仓零引用）；f) `:495-568`（`_trim_phase2b_scene_text`/`_compact_entity_index_for_scene`/`_build_alias_relation_entity_index` 等仅测试使用）
- **问题与触发**：Phase 2 子包为旧测试/monkeypatch seam 保留的兼容面（README 明示"保留的 helper 类仅用于旧测试/import 兼容，不是生产 DI seam"）。rg 证实五类与 `_scene_indices_for_failure` 生产零引用；wrapper 节是模块 helper 到 service 方法的纯转发。
- **调用链证据**：`rg "\b<类名>\b" -g '!tests/**'` 均无生产命中；测试引用集中在 test_scene_entity_workflow.py/test_scene_entity_extraction.py/test_relation_provenance.py。
- **现有契约**：README 明示兼容性质；删除属测试迁移工程，非行为变化。
- **最小方案**：分批迁移测试到 `modules.imports.entity_extraction` 公共面或具体实现子模块后删除 adapter 类与 `_scene_indices_for_failure`；`small_sample_supplement_timeout_seconds` 改为直接读常量+测试 monkeypatch 具体模块属性（A2-2 动态反查在本范围内的实例）。
- **预期收益**：消除双入口（mixin 方法 + adapter 转发）认知成本；每文件尾部 -30~60 行。
- **风险**：测试迁移量大；`__all__` 收缩需保留 monkeypatch 路径说明。
- **依赖**：与 E1（测试横查）协调批次顺序。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`；受影响符号 `rg` 生产归零。
- **回滚**：逐文件 revert。
- **裁定**：实施候选（分批）
- **优先级**：P3

### D5a-6
- **ID**：D5a-6
- **位置/符号**：`backend/modules/imports/scene_candidates.py:36-55,46-53`（`ScenePrefetchResult` 部分活、`SceneReinforcementResult`/`SceneCandidateBatch`/`SceneCandidateQuality`/`build_scene_candidate_quality_stats` 零引用）；`backend/modules/imports/worldbuilding_risk.py` 整文件（`ImportWriteRiskClassifier` 生产零消费者）
- **问题与触发**：`rg` 全仓证实四个符号仅存在于定义文件；README 已删旧 prefetch/reinforcement 流水但结果模型遗留。`worldbuilding_risk.py`（Worldbuilding Workspace v1 风险分类器）无生产 import（需与 D2 槽位交叉复核是否经动态/字符串引用）。
- **调用链证据**：rg 输出如上；ScenePrefetchResult 由 workflow_scene_phase.py:795 使用（活）。
- **现有契约**：无对外承诺。
- **最小方案**：删除四个死模型与统计函数；worldbuilding_risk 待 D2 交叉确认后同批处理。
- **预期收益**：约 90 行；消除"旧流水还活着"的误读。
- **风险**：极低；worldbuilding_risk 需先复核 D2 范围。
- **依赖**：D2 交叉复核。
- **验证命令/断言**：`rg "SceneReinforcementResult|build_scene_candidate_quality_stats" backend` 归零；`make test TESTS="modules/imports/tests"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5a-7
- **ID**：D5a-7
- **位置/符号**：a) `entity_extraction/scene_entity_parallel.py:375-376,529-535`（`updated_context`/`accumulated_memory` 赋值/追加后不再读取，`phase2_result` 不含二者）；b) `scene_fusion_phase1c.py:532-544`（`_synthesis_payload` 用 `source_id.split(":",1)[0]` 提取 window_id，但 candidate_id/window_id 均不含冒号 → `relevant_window_ids` 过滤器永不命中，恒走 :543-544 fallback 全部窗口）
- **问题与触发**：a 是 serial 实现残留的只写变量；b 是恒假的过滤逻辑（行为等于无过滤，synthesis payload 附带全部窗口的 reference_context，其中无章节正文、体量小，故无实际故障）。
- **调用链证据**：逐行核对；parallel 的返回 dict 键集不含 updated_context/accumulated_memory。
- **现有契约**：无对外差异。
- **最小方案**：a 删除两处死变量；b 删除失效过滤或改为按 `phase1a_context` 窗口 owned range 与候选章节相交判定（若确需过滤）。
- **预期收益**：消除误导性代码；checkpoint/状态体积微降。
- **风险**：极低。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`；Phase 1c synthesis payload 快照对比。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5a-8
- **ID**：D5a-8
- **位置/符号**：a) `entity_extraction/scene_entity_parallel.py:264-270` 与 `scene_entity_alias_relation.py:236-243`（"commit→isawaitable await→in_transaction raise" fence 探测双份同构）；b) `scene_fusion.py:461-480,912-920`（`_phase1b_window_chapters`/`_phase1b_window_overlap`/`_phase1b_total_timeout_seconds` 手写 `os.getenv` 解析，位于 D5a-2 死代码内）
- **问题与触发**：A6-7（fence 探测单 helper）与 A6-5（env helper 收编）在本槽位的取证。活代码中 fence 探测两处逐字同构仅错误文案不同；活代码 env 读取已统一经 `shared.deep_import_settings`，剩余手写 getenv 全部在 scene_fusion.py 死代码内（随 D5a-2 删除消失）。
- **调用链证据**：provider I/O 前置检查两处对照；`modules/imports/env_helpers.py` 已有 `positive_int_env`（D5b 文件）。
- **现有契约**：README"LLM 等待期间不持有数据库事务"。
- **最小方案**：entity_extraction 包内私有 `async def _release_transaction_before_provider_io(db, *, error_message)`，两处改调；b 随 D5a-2 处理，不单独立项。
- **预期收益**：~10 行收敛；provider 前事务释放语义单一。
- **风险**：极低。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5a-9
- **ID**：D5a-9
- **位置/符号**：`backend/modules/imports/parsers.py:379-381`（`parse_txt` 中 `if encoding is None: raise`——`detect_encoding` 恒返回字符串，死分支）；`:364-370`（`split_chapters` 对章节标题行无条件 `chapters.append`，文件以标题结尾时产生 `content=""` 的空章节）
- **问题与触发**：空章节经 services.py 上传路径写入空正文 draft 并 enqueue publish（services.py 只对 `total==0` 报错，不校验单章空 content）。触发：文本最后一个章节标题后无正文。
- **调用链证据**：detect_encoding 返回值域核对；services.py:88-98（D5b 文件）逐章创建。
- **现有契约**：AGENTS.md"成功、失败和空内容都必须落到明确状态"——空章节是可辩护现状（作者可见），但静默产生空章节+发布任务并非明确状态。
- **最小方案**：删除死分支；`split_chapters` 过滤 `content` 与 `title` 均为空的分片（或空 content 章节并入前一章节）。
- **预期收益**：消除空章节草稿与无效发布任务；-3 行死分支。
- **风险**：低；章节数变化影响上传响应断言，需测试更新。
- **依赖**：services.py 归 D5b，改动仅 parsers 侧即可。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`；"标题结尾文件"用例断言无空章节。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5a-10
- **ID**：D5a-10
- **位置/符号**：`backend/modules/imports/targeted_completion.py:900-901`（`"batch_snapshots": snapshots + snapshots, "batch_context_fingerprints": context_fingerprints + context_fingerprints`）
- **问题与触发**：checkpoint 内 snapshot id 与指纹列表按批数翻倍存储；下游 `page["batch_snapshots"][page["next_batch"]]` 只用前 N 项，后 N 项为纯冗余（疑似"实体遍/链接遍共享 snapshot"的遗留写法）。
- **调用链证据**：:842-845 每批 push 一次；:1016 按批索引读取；flush_links 重建 page 时（:1051）每 pending 一项，无翻倍。
- **现有契约**：无对外差异；仅 ImportWorkflowRun.checkpoints 体积。
- **最小方案**：改为 `list(snapshots)` / `list(context_fingerprints)`。
- **预期收益**：checkpoint 冗余减半；消除误读。
- **风险**：极低。
- **依赖**：无。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`（targeted_completion 相关）；恢复路径断言 snapshot id 定位正确。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

### D5a-11
- **ID**：D5a-11
- **位置/符号**：`backend/modules/imports/entity_extraction/scene_entity_llm_adapters.py:194-204`（`_materialize_phase2a_output` 的名称证据处理）
- **问题与触发**：README（imports :48）声明"实体的名称、类型、summary/public/hidden 字段分别绑定逐字证据；新对象名称必须出现在当前 Scene"。实现中 `entity_type` 缺证据会转 uncertain 拦截（:205-215），但 `name` 不在 `current_scene_text` 时仅跳过补证（:201 条件不满足），实体仍以 `create_new` 创建且 name 字段无逐字证据——声明契约未被 materializer 强制（evidence_quotes 在 Scene 内，但可不含名称）。
- **调用链证据**：逐行核对 materializer；persistence（`_persist_entities`）亦无 name∈Scene 校验；candidate 状态 + 证据缺失记录是现兜底。
- **现有契约**：README 声明 vs 实现差距；属"文档与代码不符或实现弱于声明"的候选，不是已证实的资产污染事故。
- **最小方案**：在 materializer 对 `identity_disposition == "new"` 且 `observation.name not in current_scene_text` 的观察转 `Phase2aUncertainItem`（对齐 entity_type 缺证处理），或在 README 修正声明。
- **预期收益**：名称幻觉实体从 candidate 区移入 uncertain 诊断；声明与实现一致。
- **风险**：召回下降（个别别名字形差异会被转 uncertain 需人工复核）；P13 v4 契约测试与 prompt-contract 快照需同步。
- **依赖**：README（本模块）同步；无跨模块。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`；构造 name∉Scene 观察的单测断言 uncertain。
- **回滚**：revert。
- **裁定**：补证据/实施候选（二选一：强实现或改文档）
- **优先级**：P3

### D5a-12
- **ID**：D5a-12
- **位置/符号**：a) `backend/modules/imports/scene_commit.py:256-268`（fusion suggestion 的 `source_candidate_ids` 解析不到 `scene_ids_by_candidate_id` 时 `continue` 静默丢弃——conflict 状态候选有 key 记录但无 scene id 映射）；b) `backend/modules/imports/completion_control.py:81,101,159`（`orchestrator._runs.get_by_task`/`orchestrator._find_active_import_task`/`orchestrator._runs._clear_owner` 直接访问 orchestrator 私有成员）
- **问题与触发**：a：conflict（同 provenance key 存在 deprecated 历史）候选相关的 Phase 1c 融合建议被静默放弃且无诊断计数；b：模块级函数与 orchestrator 的私有耦合（orchestrator.py 归 D5b）。
- **调用链证据**：commit 流程逐行核对；completion_control 三处私有访问对照 orchestrator 公共面。
- **现有契约**：README"融合建议写入占 35-40% 进度…建议进入 review"；无"建议可静默丢弃"的授权。
- **最小方案**：a 在 `result` 增加 `dropped_suggestion_count` 诊断；b 由 orchestrator（D5b）暴露最小公共查询方法后改调。
- **预期收益**：建议丢失可观测；跨文件私有耦合消除。
- **风险**：极低。
- **依赖**：b 与 D5b 协调。
- **验证命令/断言**：`make test TESTS="modules/imports/tests"`。
- **回滚**：revert。
- **裁定**：实施候选
- **优先级**：P3

**优先级计数**：P0=0，P1=1（D5a-1），P2=2（D5a-2/3），P3=9（D5a-4/5/6/7/8/9/10/11/12）。
未发现安全、跨 novel_id 隔离或恢复破坏类新问题：novel_id 门禁、confirmation 重验、
checkpoint 指纹 fail-safe、provider 前事务释放、snapshot 脱敏、逐字证据物化、幂等回滚
均逐路径核对无缺陷。发现集中于：第三方作品内容硬编码（2 处）、生产不可达的大体量旧路径
（2 处）与兼容面/微冗余。

## 历史候选复核

| ID | 结论 | 证据 |
|---|---|---|
| A2-2（15 个旋钮函数 → 声明式表 + 删 `_workflow_constant` 动态反查） | 部分成立（重新定性） | `_workflow_constant` 动态反查唯一存在 `workflow_llm_adapters.py:44`（D5b 文件，5 处调用），落 D5b。本槽位范围内的旋钮（scene_entity_config.py 约 17 个、scene_planning.py 6 个、phase2_world_extraction.py 3 个）已是 `deep_import_int/float/bool_setting` 的单行薄包装，无动态反查；表驱动化仅省 ~80 行样板、收益有限。真正残留的"动态反查"在本范围有两处：`scene_entity_bulk.py:32-43` getattr 公共模块（D5a-5c）与 scene_fusion.py 三个手写 getenv（死代码，随 D5a-2 消失）。 |
| A6-3（imports 9 个转发 classmethod 删 ~90 行） | 领域侧部分成立 | 转发 classmethod 主体在 orchestrator/services（D5b 范围）。本范围对应物为 `scene_entity_extraction.py:726-1832` 约 40 个兼容 wrapper 与五个兼容 adapter 类（D5a-5）——同为"仅测试可达的转发面"，README 明示保留理由，删除=测试迁移工程。 |
| A6-4（full/stage 双入口折叠 ~150-200 行） | 不适用于本槽位（归 D5b） | full/stage 双入口在 orchestrator/facade 层（D5b 路径）；本范围各阶段服务无 full/stage 双入口。 |
| A6-5（env helper 收编） | 大部分已解决；残余在死代码 | 活代码 env/project 设置读取已统一经 `shared.deep_import_settings`（scene_entity_config 全部旋钮、scene_planning、phase2_world_extraction）与 `env_helpers.positive_int_env`（scene_slicing/enrichment）。手写 `os.getenv` 仅剩 scene_fusion.py:461/473/913 三处——全部位于 D5a-2 死代码内，随删除解决，不独立立项。 |
| A6-6（preflight 合并） | 不适用于本槽位 | preflight 实现在 infrastructure/tasks（F2 已审，worker 只读 preflight）；imports 深度导入提交前校验走 project facade（orchestrator，D5b）。本范围 34 路径无独立 preflight 实现。 |
| A6-7（fence 探测单 helper） | 仍成立（小规模） | 活代码两处逐字同构："commit→isawaitable await→in_transaction raise"于 scene_entity_parallel.py:266-270 与 scene_entity_alias_relation.py:237-243（差异仅错误文案）。见 D5a-8。其余 fence（checkpoint/lease）在 workflow 层（D5b）。 |
| A6-8（imports 7 路状态收敛） | 归 D5b（cross-ref） | 状态词汇权威源在 workflow_runs/orchestrator/progress（D5b 路径）。本范围仅见微项：scene_enrichment.py `_quality_stats` 的 `total_windows/completed_windows` 键名是窗口语义遗留（现按 Scene 计数）；`SceneCandidateRound "A"/"B"` 双轮词汇仅剩 "A" 在用。不独立立项。 |
| A2-3（deep import 接入 WorkflowBudget） | 待查/NV（归 D5b 裁定） | 机制侧（infrastructure WorkflowBudget）F2 已确认存在。本范围证据：各阶段使用自有冻结预算——Phase0 窗口 `clamp(round(input_chars*1.0),13000,32768)`、Phase1a token 阶梯 (24576,32768)、Phase2 冻结 32768、Phase2b 动态总超时、targeted_completion 100k 字符/600s——README 明示"这套阶段预算不继承项目通用 max_tokens"，为有意设计而非遗漏。是否再叠加 WorkflowBudget 属产品/成本语义变更，非本槽位可裁。 |

## 共享事实

### 1. 阶段流水图（入口 → 产物 → 恢复点；供 W3 链 2 使用）

生产链（完整 deep_import 与三个 stage 共用同一阶段服务，编排/授权/run 归 D5b）：

```
章节来源   load_chapter_range(chapter_loader) → [{chapter_index,title,content,source_draft_id,source_content_hash}]
           恢复点：run prepare（D5b）冻结每章 source_draft_id+content_hash 来源向量；漂移在 provider 结果提交前拒绝

Phase 0    scene_planning.build_scene_import_plan（确定性，无 LLM）
           产物：ScenePlanResult{chapters, windows[SceneWindowPlan(owned/covered/input_chars/max_tokens)], blocked}
           上下文冻结：phase1a_context.Phase1aContextBuilder.compile → 每窗 left_boundary(2000字)+reference_context(author_safe canonical Top6人物/Top16对象+outline)
           产物 manifest 带 contract_version="phase1a-context-v2"+fingerprint；apply_frozen_phase1a_context 校验后复用（恢复点）
           恢复点：Phase 0 少量 batch 失败自动重跑合并一次（workflow_scene_phase._merge_phase0_repair_result）

Phase 1a   Phase1aSceneSlicer.run（scene_slicing，窗口并发默认 50，token 阶梯 →24576→32768）
           LLM 输出 SceneSlicingOutput{scenes[逐字 start/end anchor], window_edges} → _normalize_output 本地唯一命中物化 SceneChunk(offset/hash/draft绑定)
           失效路径链：小上下文锚点修复(repair_anchors) → 邻接锚点推断 → 精确重叠隔离(_quarantine_exact_overlap_ranges，整章范围) → 连续缺口 LLM 恢复(recover_chapter) → 章节级 fallback → 平凡空白缺口吸收 → 剩余缺口标记 needs_review/精确 span fallback
           产物：SceneSliceCandidate[]（锁定 title/goal/core_conflict+scene_chunks）；恢复点：无跨 run checkpoint，窗口级 at-least-once，正式写入在 commit 幂等（provenance key）

Phase 1b   Phase1bSceneEnricher.run（scene_enrichment，每 Scene 并发默认 200、冻结 32768）
           前置 _materialize_scene_source 六类完整性校验（offset/hash/draft/覆盖）→ 不完整即 fallback 不发 LLM
           输入只含本 Scene 精确正文+前一 Scene 摘要+截止可见 outline/身份资料（director-only）
           证据门禁：emotional_beat/must_happen/must_not_happen 非空字段必须当前 Scene 逐字 field_evidence，找不到即清空+uncertain
           产物：FinalSceneCandidate（含 phase1b 指纹/字段状态）

Phase 1c   Phase1cSceneFusionService.run（scene_fusion_phase1c，仅 high_quality）
           边界审阅按 Phase 1a 窗口成组（relation∈same_scene/duplicate/overlap/separate/uncertain）
           自动融合仅限连通组：confidence≥0.92+无 uncertainties+双方 exact provenance+无 concerns+非 fallback → 独立 synthesis → 三语义字段逐字证据复验
           其余写 outline 融合建议队列（Phase1cSuggestion，pending/dismissed）
           产物：融合后 FinalSceneCandidate[] + suggestions

Scene      SceneCommitter.commit（scene_commit，经 story facade）
commit     最终 fenced 事务内：_assert_non_overlapping_exact_spans fail-closed → 冻结来源完整覆盖断言（draft hash+连续区间+章节匹配）→ batch create（provenance key 幂等）→ 建议持久化（remap 到实际 scene_id）
           replace_existing 路径：只软废弃 workflow-owned 未编辑 draft/candidate（保护逻辑在 story facade）

Phase 2a   SceneEntityExtractionService.extract_by_scenes（scene_entity_extraction）
           全部持久化 UUID Scene 恒走 _process_scenes_parallel_llm（scene_entity_parallel）：
           ImportContextActivation v3（evidence facade prepare_import_context_activation，current_scene_text 必须完整精确，否则 checkpoint=skipped 不发 LLM）
           → checkpoint 指纹跳过（done/skipped 且 phase2a_input_fingerprint 一致；v2 指纹含 context fingerprint+PHASE2A_PROMPT_CONTRACT_VERSION，漂移即重跑）
           → snapshot 预建 → db.commit 关事务 → 并发 LLM（默认 25，冻结 32768）→ 降载（单波任一 429 或 ≥2 传输失败减半，16 次健康恢复）
           → 按 scene_idx 串行归并持久化（persistence mixin）→ checkpoint（含 completion_hints）
           恢复点：每 Scene checkpoint 存 run.checkpoints.phase2；失败 Scene 由阶段内白名单修复重跑（workflow_entity_phase，D5b）

phase2_    （完整导入新 REST 默认先 dedup 后 2b；顺序由 workflow_entity_phase 编排）
dedup      结构化去重经 world facade 融合 step；同名 working 确定性复用在 _persist_entities 内已先行

Phase 2b   _execute_alias_relation_phase（scene_entity_alias_relation；同一 activation + 早于当前 Scene 的 relation-xxx）
           指纹=phase2b_scene_input_fingerprint(context_fingerprint+P14 contract)；LLMInvalidResponse→空输出降级 done(fallback)；动态总超时（wave 数×LLM 超时，env 显式覆盖时不扩）
           手动补抽任务走 AliasRelationTaskMixin.prepare/execute/finalize（alias_relation_task）：prepare 冻结 manifest（confirmation 重验+每 Scene snapshot）→ execute 无 DB 纯 provider+receipt hash → finalize 重编译 manifest 比对+重验 receipt+strict 事务
           恢复点：v1 prepare 未完成必须重新提交（v2 不可消费）；Phase 2b 失败只降级

Phase 3    outline/story facade（归 D3）；本范围仅 deep_import_dedup.StructureReviewAgent（structure_phase 调用）：Phase 3 后结构去重，auto_apply 需同 workflow+confidence≥0.96，失败降级

targeted_  targeted_completion.run_targeted_completion
completion 授权：freeze_completion_permission（章节 draft hash manifest）→ authorize_completion（world facade）→ 每次执行重验 version/enabled/authorization_id/manifest hash/permission fingerprint/rollback_receipts
           根：显式 targets 或 select_automatic_roots（本 workflow completion_hints+unresolved evidence links；字段已非空则不选）
           恢复点（核心）：state 存 run.checkpoints.targeted_completion{roots,root_position,continuation,page,packages,entity_results,...}；每批/每包 save()；失败→status=partial+recovery_required+raise（manual_resume 恢复）；defer/control 经 completion_control 读写 checkpoints（作者请求优先于 worker）
           每批：focused_evidence（100k 字符预算）→ per-batch snapshot → CompletionOutput（0.90/explicit 门槛）→ materialize（identity/quote 逐字重验）→ 实体包先行、跨批链接用已接受回执 ID → project exclusive 锁内 submit+apply world 包
           回滚：rollback_targeted_completion（幂等，reversed(packages) CAS，conflicts→partial）

Phase 2/3  persistence 层完成 written 资产后经 story facade capture_snapshot（ensure_scene_checkpoints，失败仅告警）；evidence context_snapshots 审计贯穿全部 LLM step
```

### 2. 抽取去重语义（对照 AGENTS"别名附着已有对象、不重复建实体"）

- **确定性复用（防影子候选）**：`_persist_entities` 先 `find_working_entity_id_by_name`（同项目+同名+同类型 working 对象）——命中即把本次 field_evidence 逐字引用挂到已有对象（evidence link），不建新实体。模型返回 `create_new`/`link_to_existing` 不影响该判定。
- **语义相似不自动合并**：`create_new` 前 `find_similar_entities`（名称/别名/embedding）取 similarity≥0.88 的最高分仅写入 `_meta.suggested_target_entity_id`，仍创建 candidate 并计 `review_suggested`——语义重复留给项目级智能去重（world 域，D2）。
- **模型 link 建议只记录**：`suggested_existing_entity_name` 解析结果存 `_meta.suggested_existing_entity_id`，不直接改写已有对象。
- **Materializer 硬门禁（P13，scene_entity_llm_adapters）**：逐字 evidence_quotes 必须在当前 Scene 正文内，否则整条观察转 uncertain；`existing` disposition 必须引用 activation 提供的已知 prompt_ref（类型不一致→ignore+identity_issue）；summary/public_info/hidden_truth 缺证清空并标 uncertain；`entity_type` 经固定系统枚举校验（`_AI_WORLD_ENTITY_TYPES`，不建项目自定义类型）。
- **P14 别名/关系（persistence._persist_alias_relation_output）**：十二类确定性拒绝（unknown ref、跨 novel/非 active、self relation、evidence 不在 Scene、`episodic/uncertain` scope 不持久化、established 已存在、previous relation 冻结重验 `_live_relation_matches_frozen`/端点与 novel 匹配、reaffirmed 类型矛盾）；占位别名（变量/variable/placeholder/未知/unknown/某人/某物/n/a/none）不进入候选；与已有候选名称/别名完全相同的别名建议拒绝（`alias_matches_existing_name_or_alias`）；关系写候选走 `create_or_merge_relation`，changed/ended 强制留 review。
- **Phase 2 window 级路径（phase2_world_extraction）**：同语义实现存在但生产不可达（D5a-3），其 owned/overlap 归并与 invalid scene ref 诊断是独立实现——Phase 2 输入契约有两套的事实随 D5a-3 处理。
- **结构去重**（deep_import_dedup）：仅自动应用 source_workflow==target_workflow 且 confidence≥0.96 的 merge/deprecate_duplicate；其余保留建议。

### 3. LLM 输入构造点清单（预算与 schema 校验）

| 构造点 | schema | 预算/超时 | 备注 |
|---|---|---|---|
| scene_slicing._window_payload（Phase 1a） | SceneSlicingOutput | 窗口 max_tokens=clamp(round(input_chars*1.0),13000,32768)；阶梯 24576/32768；retry 单次 | 输入=窗口章节全文+left_boundary+reference_context |
| scene_slicing repair_anchors / recover_chapter | SceneAnchorRepairOutput / SceneRecoveryOutput | 小上下文；README 统一 reasoning+32768 输出上限 | anchor 长度 4-80 由 schema 钳制 |
| scene_enrichment._scene_payload（Phase 1b） | SceneEnrichmentOutput | 冻结 32768（env PHASE1B_ENRICH_MAX_TOKENS）；retry 含 empty_result | 本 Scene 精确正文+前一 Scene 摘要+可见 outline |
| scene_fusion_phase1c._boundary_review_payload / _synthesis_payload | story contracts（SceneBoundaryReviewOutput/Synthesis） | 由 workflow_llm_adapters 包装（D5b）；decision/synthesis max_tokens 提交时冻结，默认继承有效项目 LLM max_tokens | 360s 结构化超时（README） |
| scene_entity_llm_adapters.call_llm_extraction（P13 v4） | Phase2aSceneExtractionOutput（extra=forbid） | max_tokens=32768、client_timeout 360/LLM 900、temperature 0.3、fix_prompt 一次 | 输入 fenced `<untrusted_scene_context_json>`（&<>与 U+2028/9 转义）；prompt_context 剥离 `_` 私有键；snapshot client finally close |
| scene_entity_llm_adapters.call_alias_relation_extraction（P14 v5） | AliasRelationExtractionOutput（extra=forbid） | 32768/600s；transport_retries=True | render_phase2b_user_payload 构造 fenced payload，与审计落库同源 |
| targeted_completion._complete_batch | CompletionOutput（附完整 JSON Schema 于 system prompt） | 输入 100_000 字符硬限、max_tokens 32768、600s、low reasoning（deepseek） | 确定性 materialize 在 imports 侧（0.90 门槛） |
| phase2_world_extraction._window_payload | Phase2WorldExtractionOutput | 32768（死代码路径，D5a-3） | — |
| workflow_llm_adapters（Phase 1a/1b prompt 与 token 控制、`_workflow_constant`） | — | — | 文件归 D5b；A2-2 动态反查唯一所在 |

所有结构化调用统一经 `infrastructure.llm.agent_step_harness.run_managed_structured`（F2 seam）；
client 一律经 `create_project_snapshot_llm_client`（secret-free snapshot→当前账户 Key），成功与异常路径 `finally close`；snapshot 审计经 `modules.evidence.facade`，脱敏字段与来源见 context_snapshot_helpers/scene_entity_snapshots。

### 4. 其他移交

- `SceneEntityExtractionService` 的 Phase 2 结果字典键（`total_windows/completed_windows`、"A"/"B" 轮次词汇）是窗口/双轮时代遗留，X1-6 类状态词汇收敛时一并核对（D5b 主责）。
- `worldbuilding_risk.py` 零消费者结论需 D2 交叉复核（world 侧可能经字符串/动态引用）——已列入 D5a-6。
- `workflow_llm_adapters.py` 的 `_Phase1bSceneFusionLLM`（死）与 `_workflow_constant`（A2-2）归 D5b 处理，cross-ref D5a-2/A2-2。

## 受阻

无。
