# W0-A：调用清单与能力映射冻结（只读调查）

调查基线：origin/main 5a2524dae（工作树 HEAD 81ef210e8 = 基线 + 1 个文档提交）
工作树：`<repo>/.worktrees/ai-run-envelope`（分支 `codex/ai-run-envelope`）
方法：全 `backend/` AST 扫描（`ast.Call` 节点 + 词法链根名）+ 只读运行 `validate_capability_bindings()`（当前 0 issues）。未修改任何代码文件。

## 0. 排除口径与理由

- `backend/**/tests/**`、`test_*.py`、`conftest.py`、`evals/tests/**`：Fake/Spy client 定义（如 `modules/writing/tests/governance_fakes.py:13`），非生产路径。
- `backend/evals/**`：`evals/__init__.py:1` 自述 "Developer-only semantic evaluation toolkit"；全库 grep `from evals|import evals` 只命中 `evals/` 内部，`app/` 与 `modules/` 零引用；仅 `python -m evals.cli` / `evals.rp_long_memory` 手工离线运行。
- `backend/scripts/**`：开发/运维 CLI（`doctor.py:684`、`check_llm.py:21`、`check_embedding.py`、`deep_import_phase01_real_llm_check.py:103-121` monkeypatch 后手工跑真实 LLM），不在服务进程调用链。
- `backend/tools/prompt_contracts/**`：静态门禁自身；`probes.py:78/108` 是 `re.search` 误报。
- `infrastructure/llm/providers.py:225/278`、`infrastructure/embedding/worker.py`：provider SDK 适配层与本地推理进程，由 EXEMPT seam 语义覆盖。

---

# A1：全部生产调用点

## A1-0 结论口径

- 模块内**受管入口**调用点 **42 个**（`run_managed_generate` / `run_managed_structured` / `run_project_agent` / `open_project_image_client`）。
- 模块内**裸 client / 原生 provider** 调用点 **14 个**。
- 基础设施 seam（EXEMPT 文件内）**17 个**。
- 首轮非目标（embedding / health / account / eval）约 **25 个**，见 A3。

## A1-1 Writing

| # | 证据 | 函数 | 形态 | capability | 该文件声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 1 | `modules/writing/services.py:3303` | `WritingGenerationService.generate_candidate_for_task._governed_generate` | `run_managed_generate`（`step_name=writing.generation.candidate.generate`，:3306） | `writing.generate`（动态 `plan.knowledge_policy_id`，源 :3135 = `knowledge_plan["policy_id"]`；:3183 `require_capability_policy("writing.generate")` 写死） | `("writing.generate",)` :49 | 命中 Name 标记 |
| 2 | `modules/writing/semantic_review.py:865` | `WritingSemanticWorkflowService.review_for_task` | `run_managed_structured`（`step_name=f"writing.semantic_review.chunk_{index}"`，:863） | `writing.semantic_review` | `("writing.semantic_review",)` :50 | 命中 |
| 3 | `modules/writing/semantic_review.py:1434` | `WritingSemanticWorkflowService.revise_for_task` | `run_managed_structured`（`step_name="writing.targeted_revision.generate"`，:1438） | `writing.targeted_revision` | 仅 `writing.semantic_review` :50 | 命中文件，**绑定缺项**（A2-1） |
| 4 | `modules/writing/conflict_ai.py:268` | `ConflictCheckAiReviewService._execute_task_review` | `run_managed_structured`（:269） | `writing.conflict_check.ai_review`（治理 :283 `capability=AI_REVIEW_ACTION`） | 两能力 :51-54 | 命中 |
| 5 | `modules/writing/conflict_ai.py:583` | `ConflictSuggestionService.run_for_task` | `run_managed_structured`（:584） | `writing.conflict_check.ai_suggestion`（:598） | 同上 | 命中 |

## A1-2 World

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 6 | `world_generation_center_service.py:506` | `WorldGenerationCenterService.design_iteration` | `run_managed_structured`（`:510` step_name、`:515` governance capability） | `world.generation.design_iteration` | :56-62 **缺该项** | 命中，**缺项**（A2-3） |
| 7 | `world_generation_center_service.py:660` | `_generate_chat_reply` | **裸 `client.generate`** | `world.generation.chat`（治理 :615-617） | :56-62 含 chat | **不命中**（`generate` 非 marker） |
| 8 | `world_generation_center_service.py:1334` / `:1359` | `_run_structured_with_quality_review` | `run_managed_structured`（step_name 动态） | 由调用方决定：convergence/exploration/semantic_inspection/suggestion/composite（:2723、:2787、:2888、:2916、:3056、:1485） | :56-62 含 5 项 | 命中 |
| 9 | `world_generation_center_service.py:1538` | `_audit_proposal_decisions` | `run_managed_structured`（:1574） | 跟随 step_name | :56-62 | 命中 |
| 10 | `modules/world/entity_fusion.py:1748` | `WorldEntityFusionService._decide` | `run_managed_structured` | `world.entity_fusion`（:827） | :73 | 命中 |
| 11 | `modules/world/map_atlas_workflow.py:750` | `_spatial_evidence` | **裸 `client.generate_structured`** | `world.map_atlas.plan` | :75-78 含 | 命中属性标记 |
| 12 | `map_atlas_workflow.py:1492` | `_plan` | **裸 `client.generate_structured`** | `world.map_atlas.plan` | 同上 | 命中 |
| 13 | `map_atlas_workflow.py:1813` / `:1843` / `:1857` | `_generate_page` | `open_project_image_client` + **`client.edit`** + **`client.generate(prompt/size/quality)`** | `world.map_image_prompt` | :75-78 含 | 仅 :1813 命中；`:1843`/`:1857` **不命中** |
| 14 | `modules/world/map_structure_workflow.py:672` | `run_structure` | 裸 `client.generate_structured` | `world.map_structure.generate`（:693） | :79 | 命中 |
| 15 | `ask_world_service.py:594` | `AskWorldService._generate` | `run_managed_structured`（:595） | `world.ask`（:522） | :66 | 命中 |
| 16 | `world_bible_synopsis_service.py:1211` | `_generate_synopsis` | `run_managed_structured` | `world.world_bible.synopsis`（:1188） | :67-69 | 命中 |
| 17 | `world_validation_service.py:1411` | `_semantic_review` | `run_managed_structured` | `world.validation` | :70-72 | 命中 |

注：`modules/world/tasks.py:74` 声明 `world.alias_relations.extract`，但该文件只在 `:226/:250/:373` 做 confirmation action 授权编排，**无 provider 调用点**（A2-5）。

## A1-3 Story

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 18 | `modules/story/generation.py:249` | `StoryGenerationService._run` | `run_managed_structured`（:253） | 动态：`story.character_card`/`reaction`/`script`（:290/:294、:334/:338、:377/:381） | 三项全声明 :91-95 | 命中 |
| 19 | `ai_workflow_service.py:550` | `_run_analysis_llm` | `run_managed_generate` | `story.outline.analyze` | :87-90 | 命中 |
| 20 | `p20_service.py:333` / `:425` | `_run_candidate` / `_run_audit` | `run_managed_structured`（:337/:444） | `story.outline.p20`（治理 :169） | :86 | 命中 |
| 21 | `story_outline_generation.py:655` / `:725` | `_run_candidate` / `_run_preview_audit` | `run_managed_structured`（:40） | `story.story_outline.generate` | :83-85 | 命中 |
| 22 | `scene_fusion_draft.py:533` | `_run_fusion_synthesis` | `run_managed_structured`（:374） | `story.scene_fusion` | :97-99 | 命中 |
| 23 | `structure_dedup.py:588` | `_decide` | `run_managed_structured`（:616） | `story.structure_dedup` | :96 | 命中 |
| 24 | `story/outline_state/generation/parser.py:162` / `:382` | `_parse_deep_import_simple` / `_review_structure_evidence` | `run_managed_structured`（`outline.structure_parser.*`） | 实际 `imports.structure_analysis`（`generator.py:254-256`；parser 只走 phase3 deep-import，`:85-89` 拒绝 legacy 全量生成，`:142` `parameter_version="phase3_structure_simple_v3"`） | 声明 `("story.outline.p20",)` :155 | **错绑**（A2-7） |
| 25 | `modules/story/tasks.py:475/:521/:580/:631` | 四类 story task | 无直接调用点（仅 open client 后委托 `generation.py`） | `story.one_click`（:614）经三项子调用合成 | `story.one_click` 全库未绑定 | 不命中 |

## A1-4 Imports

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 26 | `modules/imports/workflow_llm_adapters.py:1332` / `:1360` | `_run_deep_import_structured_call`（+ `.repair`） | `run_managed_structured`（step_name 参数） | 动态 governance：`imports.scene_slicing`（`:503`，含 phase1a anchor repair `:611` / recovery `:732`）、`imports.scene_enrichment`（`:890`）、`imports.scene_fusion`（`:1104`） | 仅 scene_plan/scene_slicing/structure_analysis :149-153 | 命中，**缺 2 项**（A2-4） |
| 27 | `scene_entity_llm_adapters.py:116` | `call_llm_extraction` | `run_managed_structured`（:120） | `imports.entity_extraction`（治理 :219） | :146-148 | 命中 |
| 28 | `scene_entity_llm_adapters.py:488` | `call_alias_relation_extraction` | `run_managed_structured`（:492） | `world.alias_relations.extract`（链：`scene_entity_extraction.py:1662` → `scene_entity_alias_relation.py:618` → `scene_entity_alias_relation_task.py:601-603/:638`） | 同上，**缺该项** | **缺项**（A2-5） |
| 29 | `modules/imports/review_resolution.py:192` / `:1211` | `judge` / `audited_scene_judgment` | `run_managed_structured` | `imports.review_resolution`（:237/:1250） | :109 | 命中 |
| 30 | `modules/imports/targeted_completion.py:244` | `_complete_batch.generate` | `run_managed_structured`（:259） | `imports.targeted_completion`（:286） | :110 | 命中 |
| 31 | `workflow_scene_phase.py` / `workflow_entity_phase.py` / `workflow_structure_phase.py` / `scene_planning.py` | 阶段编排 | **无调用点** | 声明 scene_plan/slicing/enrichment/fusion/entity_extraction/structure_analysis | :101-108 | 不命中；`scene_planning.py:128` 明确 `"llm_calls": 0`，`imports.scene_plan` 全库无运行时使用者 |

## A1-5 Evidence

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 32 | `knowledge/workflow.py:264` / `:367` | `run_knowledge_director` / `run_knowledge_audit` | `run_managed_structured`（`:257/:273`、`:366/:374`） | `policy.capability_id`（动态，来自 `govern_group_output(capability=…)`，`group.py:108-126`） | 整文件 `("infrastructure.format_repair",)` :133-135 | **错绑**（A2-6） |
| 33 | `modules/evidence/indexing/reranker.py:236` | `rerank` | `run_managed_structured`（`RERANKER_STEP_NAME="rag.reranker.generate"` :22/:248） | `infrastructure.reranker` | :132 | 命中 |
| 34 | `services/retrieval_query_planner.py:384` | `_generate_query_expansion` | `run_managed_structured`（:36/:405） | `infrastructure.rag_query_planner` | :129-131 | 命中 |
| 35 | `services/focused_evidence.py:801` | `FocusedEvidenceService._nominate.generate` | `run_managed_structured`（:802） | `infrastructure.rag_query_planner` | :139-141 | 命中 |
| 36 | `services/selection_proposal.py:101` | `ContextSelectionProposalService.propose` | `run_managed_structured`（:102） | 声明 `infrastructure.rag_query_planner` | :142-144 | 命中，**待复核**（A2-8） |
| 37 | `indexing/retrieval.py:503-514`、`loaders/rag_chunks_loader.py:131-148`、`focused_tasks.py:257-286` | `retrieve` / `_fused_rerank` / focused 任务 | 仅 open client 后传给 `rerank_results` / `FocusedEvidenceService` | 由真实调用点 `reranker.py:236`、`focused_evidence.py:801` 承担 | 三文件均未登记 | 不命中 |

## A1-6 Interaction / RP

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 38 | `modules/interaction/tasks.py:73` | `handle_interaction_story_generate`（summary 分支） | `run_project_agent`（`output_type=InteractionSummaryOutput` :78） | `interaction.summary_refresh` | 仅 `("interaction.story_generate",)` :112 | **缺项**（A2-2） |
| 39 | `tasks.py:88` | 同上（非 agent 分支） | 裸 `summary_client.generate_structured`（:90） | `interaction.summary_refresh` | 同上 | 命中文件 |
| 40 | `tasks.py:118` | 同上（正文流） | 裸 `client.generate_stream` | `interaction.story_generate` | 同上 | 命中属性标记 |
| 41 | `tasks.py:208` | `handle_interaction_summary_refresh` | 裸 `client.generate_structured`（:210） | `interaction.summary_refresh` | 同上，缺项 | 命中文件 |
| 42 | `modules/interaction/streaming.py:274` / `:313` | `stream_anonymous_rp_attempt` | 裸 `generate_structured` / `generate_stream` | `interaction.summary_refresh` / `interaction.anonymous_story` | :117-120 | 命中 |
| 43 | `modules/interaction/generation.py:922` | `govern_held_story` | `run_managed_generate` | `interaction.story_generate` | :113-116（`summary_refresh` 无实际调用点，仅编排） | 命中 |
| 44 | `modules/interaction/agent_runtime.py:450` / `:511` | `InteractionAgentRun.stream` | `run_project_agent`（准备）+ 裸 `client.generate_stream`（正文） | `interaction.story_generate` | :121-124 | 命中 |
| 45 | `agent_runtime.py:313` / `:534` | `research_general_fact` 工具 | **裸 `self.client.research`**（→ `client.py:667-680` → `providers.py:338` → `native_search.py:248/:322`） | 无 | 同上 | **不命中**（`research` 非 marker） |
| 46 | `modules/interaction/proactive.py:236` | `handle_continuity_review` | 裸 `client.generate_structured` | `interaction.continuity_review` | :125 | 命中 |

## A1-7 Assistant

| # | 证据 | 函数 | 形态 | capability | 声明集合 | 门禁 |
|---|---|---|---|---|---|---|
| 47 | `modules/assistant/service.py:940` / `:1021` | `AssistantService.execute` / `.repair` | `run_project_agent` | `assistant.turn`（:1037） | `("assistant.turn",)` :127 | 命中 |
| 48 | `modules/assistant/evidence_tools.py:362` | `research_fact`（:331） | **裸 `deps.client.research`**（→ `providers.py:342` → `native_search.py:248` `responses.create(tools=[web_search])` / `:322` `chat.completions.create(tools=[$web_search])`） | 无 | 文件未登记 | **完全不命中** |

## A1-8 基础设施 seam（EXEMPT）

`agent_step_harness.py:827/:880`、`agent_runtime.py:320/:361`、`client.py:605/:661/:737/:740/:981/:984/:1076`、`image_client.py:180`、`native_search.py:248/:322`、`providers.py:225/:278/:342`。

---

# A2：错绑 / 缺项清单

### A2-1 Writing targeted revision —— 缺项
- 证据：`semantic_review.py:1434-1438`（`step_name="writing.targeted_revision.generate"`），`:1450` 再记 provenance。
- 现状：`capability_bindings.py:50` 只声明 `writing.semantic_review`；`writing.targeted_revision` 已在注册表（`policies.py:174-185`）但全库无绑定（`validate_capability_bindings()` 输出 "never bound"）。
- 影响：定向返修是 `confirmation=required` + `ADOPTION_REQUIRES_PASS_AND_REVIEW`（:183-184），现按 `writing.semantic_review`（`ADOPTION_DISPLAY_ONLY`，:168）统计与治理。
- 建议：`("writing.semantic_review", "writing.targeted_revision")`，信封按 `writing.targeted_revision.*` 前缀归属。

### A2-2 Interaction summary —— 缺项（重点）
- 证据：`tasks.py:73`（`run_project_agent`）、`:88`、`:208`，三处均为 `InteractionSummaryOutput`（:78/:90/:210）；`streaming.py:274` 同语义已正确登记 `summary_refresh`。
- 现状：`capability_bindings.py:112` 仅 `("interaction.story_generate",)`。
- 风险：`:73` 是 Agent 路径，按文件主能力归因会误记为 RP 正文生成。
- 建议：补 `interaction.summary_refresh`。

### A2-3 World design iteration —— 缺项 + 挂错文件（重点）
- 证据：`world_generation_center_service.py:506` + `:510` + `:515`。
- 现状：该文件声明集合（`:56-62`）不含 `design_iteration`；该能力反挂到 `cocreation_session_service.py`（`:63-65`），而该文件 grep `design_iteration|run_managed|generate_structured|client.generate` **命中 0**。
- 建议：`world_generation_center_service.py` 补 `world.generation.design_iteration`；`cocreation_session_service.py` 条目改为委托说明或移除。

### A2-4 Imports enrichment / fusion —— 缺项（重点）
- 证据：`workflow_llm_adapters.py:889-890`、`:1103-1104`，两者都经 `:1332` 真正调用 provider，`:1388-1390` 用 `governance["capability"]` 做治理，repair 分支 `:1360`。
- 现状：声明集合（`:149-153`）缺 `imports.scene_enrichment`、`imports.scene_fusion`；而声明了这两项的 `workflow_scene_phase.py:101-106` 无调用点。
- 附带：`imports.scene_plan` 全库无运行时使用者（`scene_planning.py:128` `"llm_calls": 0`）。
- 建议：adapters 补两项；`scene_plan` 条目注明"确定性规划，无 LLM 调用点"。

### A2-5 Imports entity extraction / alias relation —— 缺项 + 挂错文件（重点）
- 证据：`scene_entity_llm_adapters.py:488-492`；链：`scene_entity_extraction.py:1662-1672` → `scene_entity_alias_relation.py:618/:626` → `scene_entity_alias_relation_task.py:601-603`、`:638`。
- 现状：`:146-148` 只声明 `imports.entity_extraction`；`world.alias_relations.extract` 挂在 `modules/world/tasks.py:74`，该文件无调用点。
- 建议：adapters 补 `world.alias_relations.extract`；`world/tasks.py` 条目改注为"任务授权入口"。

### A2-6 knowledge director / audit —— 错绑（重点）
- 证据：`knowledge/workflow.py:264-273`（director shard，`step_name=f"{policy.capability_id}.knowledge.director.shard_N"`）与 `:367-374`（audit verdict）；capability 取 `policy.capability_id`（`:287/:345`），policy 由调用方 `govern_group_output(capability=…)` 传入（`group.py:108-126`）。
- 生产调用方（全部带行号）：`writing.conflict_check.ai_review`（`conflict_ai.py:283`）、`ai_suggestion`（:598）、`imports.structure_analysis`（`generator.py:256`）、`assistant.turn`（`assistant/service.py:1037`）、`imports.entity_extraction`（`scene_entity_llm_adapters.py:219`）、`world.alias_relations.extract`（`scene_entity_alias_relation_task.py:603`）、`imports.review_resolution`（`review_resolution.py:237/:1250`）、`imports.targeted_completion`（:286）、`world.entity_fusion`（`entity_fusion.py:827`）、`world.map_structure.generate`（`map_structure_workflow.py:693`）、`world.map_atlas.*`（`map_atlas_workflow.py:1522`）、imports 治理字典（`workflow_llm_adapters.py:1390`）、`writing.generate`（`writing/services.py:3321`）。
- 现状：整文件登记为 `infrastructure.format_repair`（`policies.py:673-684`，`outputs=(OUTPUT_INTERNAL,)`、`adoption=NONE`、"不得产出答案"）。
- 判断：director 决定生成者可见来源（`workflow.py:240-244`），audit verdict 直接是 apply/采用门禁（`:295-353`、`group.py:108+`），属有答案/权限效果的业务推理；真正的格式修复在 `client.py:981 _repair_structured_format`（EXEMPT）。故为**错绑**。
- 建议：登记为"跨能力 helper"并列出全部服务 capability，或新增 `infrastructure.knowledge_governance` 豁免并说明其只产出内部治理结论；信封按 `policy.capability_id` + `.knowledge.director/.audit` 归属真实能力。

### A2-7 大纲结构解析 parser —— 错绑
- 证据：`generation/parser.py:162-166`（`:142` `phase3_structure_simple_v3`）、`:382-386`；`:85-89` 拒绝 legacy 全量生成；唯一调用方 `generator.py:165-194`，治理声明 `capability="imports.structure_analysis"`（`:256`）。
- 现状：`capability_bindings.py:155` 声明 `("story.outline.p20",)`；该能力真实调用点在 `p20_service.py:333/:425`。
- 建议：parser.py 改为 `("imports.structure_analysis",)`。

### A2-8（待复核）selection_proposal 输出可见性
- 证据：`selection_proposal.py:84-101`（作者 instruction → include/exclude）、`:63-69`（返回作者可读 `summary`），经 `facade.py:786` 暴露。
- 现状：声明 `infrastructure.rag_query_planner`（`policies.py:649-660`，`outputs=(OUTPUT_INTERNAL,)`）。
- 建议：冻结核对该返回值是否进入用户可见确认 UI；若是，应新登记业务 capability（仅注册表条目，不新增表/列/migration）。

---

# A3：infrastructure exemption 清单与首轮非目标

## A3-1 EXEMPT_FILES（`capability_bindings.py:34-43`，6 条，全部存在）

| 文件 | 理由（代码证据） |
|---|---|
| `modules/project/llm_runtime.py` | `open_project_llm_client`（:311）/ snapshot client / 能力快照注入（:126、:220-237）——owner 已验证账户 Key 的唯一取用 seam |
| `modules/project/image_runtime.py` | `open_project_image_client`（:98-109）——图片 client 工厂 seam |
| `infrastructure/llm/agent_step_harness.py` | `run_managed_generate`（:793/:827）、`run_managed_structured`（:834/:880）——受管入口实现本身 |
| `infrastructure/llm/client.py` | `generate`（:578/:605）、`generate_stream`（:630/:661）、`generate_structured`（:685/:737/:740）、`_repair_structured_format`（:981/:984）、`generate_simple`（:1076，**无生产调用者，死代码**） |
| `infrastructure/llm/agent_runtime.py` | `run_project_agent`（:444）与 `ProjectGatewayModel.request/request_stream`（:320/:361）——Agent 循环实现本身 |
| `infrastructure/llm/native_search.py` | `research_with_supplier` 原生联网（:248 deepseek `responses.create(tools=[web_search])`、:322 kimi `chat.completions.create(tools=[$web_search])`）——绕过 LLMClient 的直连 provider seam |

两点注意：(1) 门禁只遍历 `modules/`（`capability_bindings.py:196-203`），故 4 个 `infrastructure/` 条目本就不在扫描范围，真正生效的是 2 个 `modules/project/` 条目。(2) `infrastructure/llm/web_search.py` 不在 EXEMPT，但它只打外部检索服务 `WEB_SEARCH_URL`（:39、:221、:285），不是 LLM provider。

## A3-2 `infrastructure.*` 能力（`policies.py:648-708`，5 项）与实际绑定

| capability | 注册表 | 实际绑定文件 | 说明 |
|---|---|---|---|
| `infrastructure.rag_query_planner` | :649-660 | `retrieval_query_planner.py:129`、`focused_evidence.py:139`、`selection_proposal.py:142` | selection_proposal 待复核（A2-8） |
| `infrastructure.reranker` | :661-672 | `reranker.py:132` | 正确；调用点 `reranker.py:236` |
| `infrastructure.format_repair` | :673-684 | `knowledge/workflow.py:133` | **错绑**（A2-6）；真实实现在 `client.py:981`（EXEMPT） |
| `infrastructure.embedding` | :685-696 | **无任何文件绑定** | 注册表声明但门禁未落地 |
| `infrastructure.account_connection_test` | :697-708 | `account/settings_service.py:137` | 已登记但门禁从不触发（无 marker） |

注册表 46 项中未绑定 3 项：`writing.targeted_revision`、`story.one_click`、`infrastructure.embedding`。

## A3-3 首轮非目标对应调用点

**embedding / 本地 BGE**
- 实现：`infrastructure/embedding/client.py:334`、`worker.py:100/:109/:121`（sentence_transformers / ONNX 本地进程）、`infrastructure/llm/client.py:1079-1105`（`provider=="bge_onnx"` 分支）、`providers.py:352-374`（远程）。
- 调用点：`entity_embedding_service.py:57`、`embedding_writer.py:69/:121`、`tuning.py:211`、`retrieval.py:50`、`circuit_breaker.py:10`。全部不命中。

**健康检查**
- 实现：`infrastructure/llm/health.py:62`、`:156-165`（POST `/chat/completions`）、`:255/:280/:286/:313`。
- 调用点：`app/main.py:688`、`modules/imports/workflow.py:282/:290`（经 `:270 _check_llm_health`，阶段入口 `:149/:313/:298`）、`account/settings_service.py:75`、`scripts/check_llm.py:21`、`scripts/doctor.py:684`。全部不命中。

**账户连接验证**
- 证据：`account/settings_service.py:67` → `:75` `LLMHealthChecker`、`:273` 连接时调用；`:144-146` `OpenAIImageClient(...).verify_connection()`（实现 `image_client.py:158`）。不命中。

**离线 eval CLI**
- `evals/generation.py:257/:320/:387/:422/:487`、`evals/project_executor.py:99`、`evals/ragas_adapter.py:40`、`evals/rp_long_memory.py:2671/:2743`、`evals/scene_gold.py:114/:123`、`evals/codex_executor.py:102`。不扫描 + 无登记。

---

# 收尾结论

在冻结范围内（`backend/modules` 生产路径），42 个受管入口调用点中有 **11 个落在绑定错误或缺失的文件里**——`writing/semantic_review.py` 的 `targeted_revision`、`interaction/tasks.py` 的 `summary_refresh`、`world_generation_center_service.py` 的 `design_iteration`、`imports/workflow_llm_adapters.py` 的 enrichment/fusion、`imports/entity_extraction/scene_entity_llm_adapters.py` 的 alias_relations、`evidence/knowledge/workflow.py` 整文件误挂 `format_repair` 的两处、`story/generation/parser.py` 误挂 `story.outline.p20` 的两处；另有 **5 个生产调用点当前完全不被静态门禁识别**——`assistant/evidence_tools.py:362` 与 `interaction/agent_runtime.py:313` 的原生联网 research、`map_atlas_workflow.py:1843` 的图片 edit、`map_atlas_workflow.py:1857` 的图片 generate、`world_generation_center_service.py:660` 的自由问答 generate，其中只有 `assistant/evidence_tools.py` 所在文件完全未登记。即**当前"完全不可见或绑定错误"的生产调用点合计 16 个**，再加 1 个待复核的 `selection_proposal` 归属；而 `validate_capability_bindings()` 目前 0 issues 并不能反映这些偏差——因为 4 处声明（`cocreation_session_service.py`、`world/tasks.py`、`workflow_*_phase.py`、`map_structure_images.py`/`world_object_images.py`）在门禁上从不触发。
