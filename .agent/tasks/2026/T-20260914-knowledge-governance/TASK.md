---
id: T-20260914-knowledge-governance
title: 全产品知识治理：全知导演、最小知情生成、独立复核
status: completed
created: 2026-09-14T00:00:00+08:00
updated: 2026-09-15T09:24:00+08:00
---

# 全产品知识治理：全知导演、最小知情生成、独立复核

## 恢复快照

- **最终状态（2026-09-15）**：M0–M12 全部完成；知识治理覆盖 Writing、World、Story、Imports、Map、Interaction/RP、Assistant 与检查类能力，统一采用门禁和前端双分区/阶段/阻断展示已落地。全量 CI、专用 PostgreSQL、完整 functional Playwright、文档门禁及 DeepSeek v4 Flash 最小真实审查均通过；仅本地工作树，未 commit/push/部署。

- 实际完成：分支 `codex/knowledge-governance`（基线 4db3df9b6）；**M0–M4、M8、M11-AST、M5 主体已完成**。M5 已落地：新模块 `modules/world/services/worldbuilding/knowledge_governance.py`（`govern_world_output` audit+≤1返修+复审、`world_scope_entries`（source_refs+rendered_context→scope receipt，全票 required，author_messages 不入知识源）、`serialize_governed_output`、`require_knowledge_review_passed` 门禁 helper、`knowledge_blocked_reply`）；generation center 六入口接线（core entity/existing page/new page 建议 → `_govern_structured`（返修=同 schema 决策守卫重跑，回执进 payload `knowledge_review` 字段——`CoreEntityDraftSuggestionPayload`/`WorldBiblePageDraftSuggestionPayload` 尾部加字段）；chat → `_govern_text`（blocked 换阻断说明）；design_iteration → blocked 抛 400 不建 checkpoint；converge/explore → blocked 整体扣留；semantic_inspection → blocked 抛 400 不落诊断）；Ask World `_govern_answer`（blocked → no_answer 形态，`AskWorldResponse.knowledge_review`）；synopsis `_govern_synopsis`（audit-only，blocked 版本不晋升 ready，回执进 generation_meta_json）；采用门禁三处（`SuggestionQueueService.confirm`/`apply_world_generation_page_draft` 的 `_require_knowledge_review_passed`——world_bible_page_draft 恒管、core_entity* 仅 source_module=="world"、payload 带 knowledge_review 键即管；作者改写 page apply 标记 `author_edited: True`；`adoption_package_service.apply` 单点覆盖 package/focused/review resolution）；六个响应 schema + AskWorldResponse 尾部加 `knowledge_review` 字段；测试基建 `modules/world/tests/governance_fakes.py`（`GovernedWorldAuditMixin`，`audit_verdicts` 队列驱动 blocked/返修路径；假 client 的 `generate_structured` 对 AuditVerdictOutput 分流且不计入 `requests` 断言序列——已应用到 `_FakeWorldGenerationClient`/`_FakeSynopsisClient`/cocreation `_FakeChatClient`/prompt_templates `_FakeLLMClient`）。
- M6 已落地：**P20**——`p20_service.py` 返修 `range(3)`→`range(2)`（初稿→一次返修→终审，仍失败抛 P20SemanticAuditError）；`P20GenerationService.last_knowledge_review`（`_knowledge_review_payload`：policy_version/capability="story.outline.p20"/status/audit_rounds/revisions/context_fingerprint）经 `ai_workflow_service.generate_layer_for_task` 进 task_result；`P20ApplyService.apply` 门禁（receipt 非 passed → P20ConflictError「旧版本任务；请重新生成」）。三审计本就读权威包（plan.context）。**card/reaction/script previews**——`StoryGenerationService._govern_preview`（minimal receipt：compiled_context+scene_context 两条 entry；audit→blocked 时同 schema 返修→复审；unverifiable 不返修直接 blocked 回执）；`CardPreview/ReactionPreview/ScriptPreview` 尾部加 `knowledge_review` 字段；one_click 复用三个已治理 preview 自动覆盖。**总纲**——`story_outline_generation.generate_for_task` 返回值附 knowledge_review；`story_outline_service.apply_generated_preview` allowlist 加 knowledge_review + 门禁（非 passed → StoryOutlineConflictError）。**scene fusion**——既有「候选→确定性检查→≤1返修→失败抛错」结构保持，semantic_meta 附 receipt（capability="story.scene_fusion"）。`story.outline.analyze` 并入 M9 检查类。
- M7 已就绪底座：**组级治理 helper** `modules/evidence/compilation/knowledge/group.py`（`GroupSource`/`build_group_scope`（组 key 参与指纹，全票 required）/`govern_group_output`（audit→blocked 且有回调→≤1 返修→复审；unverifiable 不返修）/`serialize_group_output`）——已导出 knowledge `__init__` + compilation/contracts re-export 链（业务侧经 `modules.evidence.contracts` 导入 `GroupSource/build_group_scope/govern_group_output/serialize_group_output`），单测 5 项（test_group.py）。**Phase 2 Scene 抽取已接线**：adapter 按 Scene 正文 + workflow context 指纹冻结组级 scope，原始结构化输出 audit-only；blocked 返回空物化结果，并行路径标记 `quality_failed`、bulk 在任何写入前失败关闭，Context snapshot 同步标记失败；回执随 `SceneEntityExtractionOutput` 及 Scene checkpoint 保存。
- M7 剩余接线配方（全部用上述 helper，模式同 world/story）：
  ① **imports Phase 2**：已完成（audit-only，review 同时进 `SceneEntityExtractionOutput` 与 checkpoint；blocked 不持久化）。
  ② **imports Phase 1a/1b/1c**：`workflow_structure_phase.py`/`workflow_scene_phase.py` 各 LLM step 后同模式（capability=imports.scene_slicing/scene_enrichment/scene_fusion，group_key=窗口/Scene）。
  ③ **imports Phase 3 + review resolution + targeted completion**：候选组/问题组同模式（capability=imports.structure_analysis/review_resolution/targeted_completion）。
  ④ **实体融合**：`world/entity_fusion.py::suggest_for_task→_decide_task_plan` 决策结果聚合后一次组级 audit（capability="world.entity_fusion"，group_key=workflow_id/task_id，sources=扫描的实体对指纹+evidence）；blocked → 该批建议标记 knowledge_review=blocked（M5 confirm 门禁自动拦截）。
  ⑤ **alias/relation 手动任务**：`imports/entity_extraction/scene_entity_alias_relation_task.py` 聚合 receipt 后一次组级 audit（capability="world.alias_relations.extract"），review 写入建议 payload（EntityRelationSuggestionPayload/EntityAliasSuggestionPayload 加 knowledge_review 字段）→ confirm 门禁自动生效。
  ⑥ **Map**：`world/services/map/` 的 visual brief/prompt 生成处接 audit（capability=world.map_structure.generate/map_atlas.plan/map_image_prompt）；栅格像素不作事实来源保持。
  ⑦ 测试：各相位 fake client 加 AuditVerdictOutput 分流（参照 `modules/world/tests/governance_fakes.py::GovernedWorldAuditMixin` 模式——audit 调用不计入既有请求断言序列）。
- 当前里程碑：M12 已完成，任务关闭。
- 下一步：无；如需交付 Git/远端/生产，须另行授权 commit、push、PR 或部署。
- 阻塞：无。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist`，分支 `codex/knowledge-governance`，全部改动不 commit/push/部署。
- 最后核实：2026-09-15（`make test-ci TEST_WORKERS=2`、专用 PostgreSQL critical、完整 functional Playwright、DeepSeek v4 Flash PASS 路径均通过）。

## 目标与验收

- 目标与交付物：所有用户可见 AI 生成/检查能力统一为「冻结任务资料 → 导演完整审阅 → 服务端裁最小知情包 → 生成/检查 → 全知复核 → 最多一次语义返修 → 通过或阻断」的确定性工作流；新增 CapabilityKnowledgePolicy 注册表与 KnowledgeScopeReceipt / KnowledgeDirectorPlan / KnowledgeAuditReceipt 契约；各域接入；前端双分区与阶段展示。
- 完成条件：计划中 M0–M12 全部落地；收尾门禁全过（prompt-contracts、受影响测试/lint、PG critical/E2E、`PW_REUSE_EXISTING_SERVER=0` Playwright、`make test-ci TEST_WORKERS=2`、`make docs-check BASE_REF=origin/main`、`git diff --check`）。
- 非目标：不新增数据库表/migration、不新增第二事实库/Agent 平台/知识策略编辑器/依赖、不动受保护演示库、不 commit/push/部署。DeepSeek v4 Flash 真实调用已于 2026-09-15 获用户授权，仅在 M12 必要验收时使用并单独报告。

## 上下文与边界

- 关键路径与来源：实施方案已获用户批准（2026-09-14 对话，M0–M12 计划全文见批准版）；代码锚点：`interaction/streaming.py:115`（chunk 仅在 visible_offset 前进时发放——held 只需不写 visible_text）、`interaction/generation.py:553/:631`、`tools/prompt_contracts` 门禁、`tests/unit/test_novel_scoped_llm_usage.py`（AST）。
- 硬约束与授权范围：用户计划「已锁定默认值」全量生效；AGENTS.md 安全与 `novel_id` 隔离约束不放宽。
- 依赖：Writing 已接入的 `run_governed_generation`/`knowledge_review_payload` 从 `modules.evidence.contracts` 导入。
- 已确认事实：`release_state` 字段不存在，held 正文存 worker 私有 task-result checkpoint（下划线键，task API 永不返回）；`AsyncTask` 无 stage 列，走 result 投影；CharacterKnowledge repo 要求来源章或 baseline；world facade 是纯 re-export hub（不能有本地 async def，包装函数放 service 模块再 import）；managed harness 不向 client 透传 step_name（测试断言 schema 序列而非 step 名）。
- 假设与待决问题：P20 返修从 ≤2 收敛为 ≤1 为计划明确要求（M6 时改）。

## 里程碑与进度

- [x] M0 契约与治理底座（knowledge/ 子包、ADR-0025、单测）
- [x] M1 CompileOptions 扩展 + scope.py/reducer.py 范围冻结引擎
- [x] M2 check_knowledge_visibility 批量判定 + HiddenGuard 重构
- [x] M3 治理执行器 workflow.py + projection.py + prompt 契约
- [x] M4 Writing 试点接入（含 POV 硬校验、双门禁、作者改后失效、投影）
- [x] M5 World 接入（generation center 六入口 + Ask World + synopsis + 采用门禁三处；fusion/alias 并入 M7 组级 receipt、validation 并入 M9 检查类——见决策记录）
- [x] M6 Story 接入（P20 返修≤1+receipt+apply门禁；card/reaction/script 预览治理；总纲 receipt+apply门禁；scene fusion receipt；outline analyze→M9）
- [x] M7 Imports + Map 接入（组级 receipt：Phase1 窗口/Phase2 Scene/Phase3 候选组/review resolution 问题组在 `workflow*.py` Runner 冻结一份，组内 step 引用；Map visual brief 接 audit）
- [x] M8 Interaction/RP held release + 匿名 fail-closed（govern_held_story audit+一次返修+复审；SSE PASS 前零 chunk；hold 经 checkpoint/clear_private_agent_state 保留）
- [x] M9 Assistant + 检查类接入（项目助手阻断时一次返修并安全扣留；world constraint review 使用 author-full Evidence 范围）
- [x] M10 前端双分区/阶段/阻断/RP 等待区（生成资料与仅复核资料分区；治理阶段、阻断错误和 held 等待状态可见）
- [x] M11 legacy_unchecked 兼容收口（统一采用门禁 helper；Writing/World/Story 调用方与冲突检查完成收口）
- [x] M12 全量回归 + 文档同步 + 收尾门禁

## 决策、发现与失败

- 2026-09-14；实施方案获批；按里程碑顺序执行。
- M2：CharacterKnowledge repo 的 None-cutoff 分支要求来源章或 baseline；无来源手动知识不参与判定（与既有语义一致）。
- M2：world facade 纯 re-export hub 约束 → 包装函数定义在 service 模块。
- M3：审查 verdict 服务端按 finding 强度收口；unverifiable/not_checked 不返修直接阻断；新增 `raw_output`（blocked 时保留不可采用候选正文）与 `enforce_scope_complete` 开关。
- M4：Writing 用 `enforce_scope_complete=False`（作者确认界面已显式接受预算裁剪，omission 由审查者按 missing_required 判定）；knowledge audit 在生成任务内 inline 自动；semantic review 保持作者触发（工作台 attention_reasons 引导）——计划中「自动复用」按功能等价落地，M10 前端补「检查」阶段展示；返修走既有 targeted revision（作者触发，新 candidate 强制重审）。
- M4：POV 缺截止点由静默降级（loader 清组+告警）改为入口 422 硬拒；两处旧测试补 `visible_until_chapter=4`，符合新产品契约。
- M5：converge/explore/semantic_inspection/Ask World/synopsis 为 audit-only（不返修）——map/reduce 多趟或后台维护任务的返修需重建请求链，作者侧重试成本低于复杂度；建议类（core entity/page/suggestion）与 chat/design_iteration 保持完整 ≤1 返修。P20/story 的返修约束在 M6 处理。
- M5：采用门禁按来源区分——core_entity* 仅 generation center（source_module=="world"）强制，抽取路径（world_extraction）待 M5c/M7 接线后由 payload knowledge_review 键自动生效；`CoreEntityDraftSuggestionPayload.model_dump()` 会输出 `knowledge_review: None`，门禁判 `is not None` 而非键存在。
- M5：测试 fixture 依赖原文件 autouse `_require_generation_confirmation` 跳过（test_world_generation_center_api.py:3403）；world API 的 ValidationError 映射 400（非 writing 的 422）。
- M8：RP 切片省略导演步（Evidence compile 已做服务端可见性裁剪），仅 audit+一次返修——minimal scope receipt（source_context 指纹单条或空）；deferred 项如后续要求导演步再补。
- M8：agent checkpoint 整体重写会覆盖 hold → `InteractionAgentRun.checkpoint()` 重写前从 attempt 读最新 knowledge_hold 合并；`clear_private_agent_state` 保留 hold（私有留痕但不展示）。
- M11-AST：门禁用「文件级绑定清单」落地（M5–M9 未接线域仍静态绑定 capability ID），`make prompt-contracts` 已含此检查。
- Lint 收口：evidence fusion 契约测试要求业务模块不得 import `modules.evidence.compilation.*` → `REPAIR_INSTRUCTION_TEMPLATE` 进 knowledge `__init__` + compilation/contracts re-export 链，interaction 改从 `modules.evidence.contracts` 导入。
- M7 Phase 2：生产 adapter 恒附回执；为保留旧单测/monkeypatch seam，下游仅在 `knowledge_review` 字段存在且非 passed 时失败关闭。这不放宽生产路径，因为唯一 adapter 已恒写字段。
- 2026-09-15；用户明确授权调用 DeepSeek v4 Flash；实现期仍优先合成 provider，真实调用留给 M12 的必要验收。
- M7：Phase 1a/1b/1c、Phase 2、Phase 3、targeted completion、review resolution、实体融合、alias/relation 与 Map 三类输出均复用组级治理；blocked 在写入/采用前失败关闭。
- M9–M11：Assistant、手工世界约束检查、Writing 冲突检查接治理；统一 `require_knowledge_review_for_adoption` 经 evidence contracts 输出，legacy 待采用产物失败关闭；前端只把内部 `selection_role` 留在 session 存储，发给后端的 ref 保持既有稳定形状。
- M12：完整浏览器首轮因热更新与缺少 MinIO 环境出现 7 项失败；稳定代码、CI 同款私有 MinIO 环境下聚焦 8 项 7 通过（唯一文案断言同步后通过），最终完整套件全绿。DeepSeek v4 Flash 先正确阻断遗漏实体的样本，再对补齐来源实体的样本签署 PASS。

## 验证证据

- `python -m pytest modules/evidence/compilation/knowledge -q` → 45 passed（含 test_group.py 5 项组级治理）；`modules/world/tests/test_knowledge_visibility_service.py` → 15 passed。
- `python -m pytest modules/writing -q` → 227 passed（含 test_writing_knowledge_governance.py 5 项）；`modules/interaction` → 152 passed, 2 deselected；`tests/unit` → 1505 passed（含 evidence fusion 契约 + facade 公共面 + novel_scoped_llm_usage）。
- M5 后：`python -m pytest modules/world -q` → 946 passed（含新增 test_world_knowledge_governance.py 5 项：blocked 建议保存但不可采、返修通过可采用、chat blocked 不返回正文、legacy 建议采用 fail closed、Ask World blocked no_answer）；synopsis 35 passed。
- M6 后：`python -m pytest modules/story -q` → 502 passed, 12 skipped（P20 返修≤1 断言更新 + receipt fixture 注入 + apply 门禁测试）；`modules/imports` 基线 → 704 passed。
- `python -m tools.prompt_contracts check` → 24 contracts passed；`ruff check modules tests tools/prompt_contracts` → All checks passed。2026-09-14（M6 后全量重跑）。
- `python -m pytest modules/imports -q` → 707 passed（含 Phase 2 audit pass/blocked 与 blocked 写入前扣留用例）；`python -m tools.prompt_contracts check` → 24 contracts passed；受影响文件 `ruff check` 通过。2026-09-15。
- `make test-ci TEST_WORKERS=2` → deploy 270 passed；backend 5541 passed, 13 skipped，coverage 85.78%；frontend 191 files / 2479 tests passed；ruff、secret hygiene、依赖审计、docs-check 全绿。
- `E2E_DATABASE_URL=.../ai_novel_knowledge_e2e make test-postgresql-critical` → 33 passed；专用数据库已迁移至 Alembic head。
- `DATABASE_URL=.../ai_novel_knowledge_e2e PW_REUSE_EXISTING_SERVER=0 ... npm --prefix frontend-console run test:e2e:functional -- --workers=1 --retries=0`（含 CI 同款私有 MinIO）→ 287 passed, 2 skipped。
- DeepSeek `deepseek-v4-flash` 最小真实治理审查：不完整输出 → `missing_required/major` blocked；补齐同一来源中的三类实体后 → `status=passed`, `audit_status=passed`。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check` → passed。

## 交付结果

- 已交付：M0–M12 全部实现与验证（本地工作树，未提交）。
- 未交付：无任务内实现项；Git 提交、推送、PR 与部署不在授权范围内。
- 交付边界：仅本地工作树，不 commit/push/部署。
- 正式知识与后续任务：ADR-0025（Accepted / Implemented）；Prompt体系设计.md 与受影响模块权威文档已同步。
