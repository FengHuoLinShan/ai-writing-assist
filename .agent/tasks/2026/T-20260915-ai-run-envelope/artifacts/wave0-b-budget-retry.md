# W0-B 调查报告：逐能力请求上界 / deadline / retry / possible charge

> **修订版：2026-09-15 第二轮，修正"默认值当最大值"。**
> 第一轮调查报告（同日）系统性地把**默认值**当成了**合法最大值**，导致 world.map_structure.generate、world.validation、
> world.entity_fusion、world.map_atlas.plan 等能力被错误标注为"无有限上界"。本轮逐行重核了三件事：
> (a) 真实 schema / Pydantic Field 上界（ge/le/max_length/max_length 组合），而非默认值；
> (b) 任务恢复策略（recovery_policy / max_attempts / retry_transient_llm_errors）对尝试层的真实乘数；
> (c) provider 尝试层级在**合法最大参数**下的次数。
> **修订基线**：worktree HEAD = 288dbd1c5（分支 codex/ai-run-envelope），工作树干净。第一轮基线 81ef210e8 与本 HEAD 的
> backend 差异仅 5 个文件（infrastructure/llm 下的 agent_step_harness.py、schemas.py、workflow_budget.py、README.md、tests/test_run_envelope.py），
> client.py、retry.py、modules/**、infrastructure/tasks/** 均未变，故其行号仍然有效。
> 本轮所有行号均在本 HEAD 上**重新打开文件核对过**；`agent_step_harness.py` 的 `run_managed_generate` / `run_managed_structured`
> 在本 HEAD 实测位于 **873 / 926 行**（第一轮引用的 826/840 已漂移，本轮已更新）。
> 未验证项一律标注"未核实"并说明原因，不猜测。
> **第三轮（W2.1 接手主 Agent）已修正 story.structure_dedup 与深导入结论，见 §6a；§4.5/§5 中与 §6a 冲突的第二轮断言作废，主表已同步。**

## 0. 预算语义（供 Wave 3/4 使用）

- **算法上界 A** = 本次冻结工作量下的主请求 + 既有 transport/schema/format/semantic retry + 既有自动 requeue。
- **本次初始额度 L0 = min(A, capability 的单次授权安全闸门 H)**。
- **H 是产品安全闸门**。本轮不定义 H 的数值；但必须明确两点：
  1. **C3 能力**（运行中才发现规模）的 H 必须显著小于 A，且必须**分批/分阶段授权**——A 只能说明"最坏要花多少"，
     不能作为一次性下发的额度。
  2. **world.entity_fusion 深导入路径**（A_total=180009；pair 决策 180000 + audit 9）必须显著小于 A 地授权，且**不可直接授权**：它既没有 schema
     收紧，也没有请求数闸门，额度必须由分批（按 `_TASK_REVALIDATION_BATCH_SIZE`=12 对一批）逐批追加。
- **A 只统计"会打到 provider 的请求"**；命中 checkpoint 跳过、确定性判定（无需 LLM）的 pair 不计入。
- **A 的口径是"单次授权动作在合法最大参数与既有自动重试下能发出的请求数"**。manual_resume / resume_manual 是
  **新的用户授权动作**（lifecycle.py:125-194 不校验 max_attempts，不自动发生），因此不计入单次 A，只在"用户手动续算"
  条目单独标注。

## 1. 分类口径（每项能力归入且只归入一类）

- **C1 编译期全局常量上界**：不依赖任何运行输入，代码/schema 中就有常量封顶（常量、字面量循环次数、冻结的
  request_limit、schema 的 max_length 组合）。
- **C2 本次冻结工作量下可动态计算的有限上界**：需要 K/S/P/M 等**冻结输入**，但输入本身已有 schema 上限，或在执行前
  已被冻结（task plan / receipt / checkpoint）。**这类能力不需要新增产品输入限制**——公式基于冻结值即可。
- **C3 运行中才发现规模、需要分批/分阶段授权**：规模由上一阶段模型输出（Scene 数、窗口数、批次数）决定，
  上界只能在运行期分片确定，必须分批授权。

## 2. 计量记号

- **R** = client 层 transport 尝试次数 = `settings.llm_retry_max_attempts`（core/config.py:311-313，env
  `LLM_RETRY_MAX_ATTEMPTS`，默认 3；shared/constants.py:41）。**注意：R 的来源是 env int，没有代码上界**，
  文中"R=3"指**默认上限口径**；生产调大该 env 会整体抬高所有 A。
- **关键分叉**：infrastructure/tasks/worker.py:591-593 在每次 handler 执行前
  `llm_transport_retry_scope(enabled=not definition.retry_transient_llm_errors)`。因此 task 注册
  `retry_transient_llm_errors=True` 时 **R=1**（client.py:614 读 ContextVar，retry.py:35-38 默认 True），
  重试改由任务层整链重放承担；未开该开关时 **R=3**。同步 API 路径（不进 worker）R=3。
- **U(a,f)** = 一次 `run_managed_structured` 的 provider 请求数 = `(a+1)·R + f·R`（client.py:732-742 主循环
  `for attempt in range(max_fix_attempts + 1)`；client.py:940-1043 format repair 独立循环）。
  `run_managed_generate` = `1·R`（agent_step_harness.py:873-923）。默认值：`run_managed_structured` 的
  `max_fix_attempts=2`、`format_repair_attempts=0`（agent_step_harness.py:933,938；client.py:690,695）。
- **T** = 任务层整链重放乘数：`recovery_policy="auto_requeue"` 且 `attempt < max_attempts` 时（worker.py:181-190）
  总尝试 = max_attempts，**下文取 T = max_attempts**；`manual_resume` / `restart_origin` 时 **T=1**
  （worker.py:665 的 `terminal_recovery_policy` / `_should_auto_requeue_handler_failure` 均要求 auto_requeue）。
- **常用值**：R3 时 U(2,0)=9、U(2,1)=12、U(1,0)=6、U(1,1)=9、U(0,1)=3；R1 时 U(2,0)=3、U(2,1)=4、
  U(1,0)=2、U(1,1)=3、U(0,1)=2、U(0,0)=1。
- **治理层**：`run_knowledge_audit` = U(2,0)（workflow.py:367-376）；`govern_group_output` 无 repair 回调时
  只审一次 = U(2,0)（group.py:151-167）；`govern_world_output` 有 repair 时 ≤ 2 次审计（knowledge_governance.py:188-189）。

## 3. 主表

列含义：**入口**=能力真实入口 `文件:行`；**A 公式**=合法最大参数下的公式；**分类**见 §1；
**依据**=本轮核对到的关键行号。

| 能力 | 入口 文件:行 | A 公式（合法最大参数） | A 数值 | 分类 | deadline 来源 | retry 层级 | 依据行号 |
|---|---|---|---|---|---|---|---|
| writing.generate | writing/services.py:3303（run_governed_generation services.py:3319；director workflow.py:247-292；audit workflow.py:428-436） | T2 × [⌈K/64⌉·U(2,0) + U(2,0)+U(2,0)]，R=1 | 6⌈K/64⌉+8 | **C2**（K=|receipt.included| 在执行前冻结；scope.py:183-184、workflow.py:259-262；repair=None 故无返修段 services.py:3325） | step 1800s（services.py:3307；常量 services.py:89） | R=1（writing/tasks.py:163-167 retry_llm=True）→ fix 3 → task ×2 | writing/services.py:3292-3333；workflow.py:55,247-292,356-436；writing/tasks.py:163-167；**修正：第一轮多算了一段返修 U(2,0)** |
| writing.semantic_review | writing/semantic_review.py:865（chunk 循环 :856） | T2 × min(chunks,24) × U(2,0)，R=1 | 144 | C1（`_MAX_REVIEW_CHUNKS=24` 硬常量 + 超限抛错） | step 1800s（semantic_review.py:35,870） | R=1（writing/tasks.py:214-218）→ fix 3 → task ×2 | semantic_review.py:36,703-713；writing/tasks.py:214-218 |
| writing.targeted_revision | writing/semantic_review.py:1434 | T2 × U(1,0)，R=1 | 4 | C1 | step 1800s（semantic_review.py:1439） | R=1（writing/tasks.py:258-262）→ fix 2 → task ×2 | writing/tasks.py:258-262 |
| writing.conflict_check.ai_review | writing/conflict_ai.py:268 | T2 × U(2,0)，R=1 | 6 | C1 | 无 step timeout=，仅 provider 180s（core/config.py:302） | R=1（writing/tasks.py:300-304）→ fix 3 → task ×2 | writing/tasks.py:300-304 |
| writing.conflict_check.ai_suggestion | writing/conflict_ai.py:583 | T2 × U(2,0)，R=1 | 6 | C1 | 同上 | R=1（writing/tasks.py:359-363）→ fix 3 → task ×2 | writing/tasks.py:359-363 |
| world.generation.chat | world_generation_center_service.py:599/611/615（重试循环 :659） | (1+pro)×2×R3 + U(2,0) | 21（pro）/15 | C1（`range(2)` 字面量 + pro 布尔） | 阶段 asyncio.timeout 1800（:598）+ step 1800 | R=3（同步 API）→ client.generate 无 fix 层 → 手写 ≤2 覆盖重试 → 审计 fix3 | world_generation_center_service.py:598-615,659 |
| world.generation.design_iteration | world_generation_center_service.py:506（治理 :513） | T2 × [U(2,0)·2 + U(2,0)·2]，R=1 | 24 | C2（冻结的迭代计划） | step 1800（:511） | R=1（world/tasks.py:492-496）→ 审计 fix3 + 决策守卫 ≤2（:1480）+ 复审 | world/tasks.py:492-496；world_generation_center_service.py:511-513,1480 |
| world.generation.convergence | world_generation_center_service.py:2848-2927（map :2884、reduce :2912） | C≤256；(2C−1)×2×(1或2)×U(2,0) + U(2,0)，R=3 | ≤18405 | C2（C=分块数，分块后 `len(sources) > 256` 直接抛错） | 阶段 asyncio.timeout 1800（:715） | R=3（同步 API）→ 每 pass ≤2 覆盖重试（:3051-3077）× pro 质量复检 ≤2（:1342-1366）× U(2,0) + 审计 fix3 | world_generation_center_service.py:120,2606-2610,2875-2927,3034-3077 |
| world.generation.exploration | world_generation_center_service.py:2771-2799 | 2×(1或2)×U(2,0) + U(2,0)，R=3 | ≤45 | C1 | 阶段 1800（:800） | R=3；known-keys ≤2（structured_reference_retry.py:23-34）× pro 复检 ≤2 | world_generation_center_service.py:2771-2799 |
| world.generation.semantic_inspection | world_generation_center_service.py:2707-2737 | 同 exploration | ≤45 | C1 | 阶段 1800（:889） | 同上 | 同上 |
| world.generation.suggestion | 生成 world_generation_center_service.py:1039/1640/1648（task 入口 :991） | task：T2×48；同步 API：4×48 | 96（task）/192（同步） | C2（决策状态 / 守卫上限 2 为常量但需运行期状态判定；冻结建议计划） | 阶段 1800（:1036）+ step 1800 | task R=1（world/tasks.py:592-596）×2；同步 API R=3；决策守卫 ≤2（:1480）、返修守卫 ≤2（:1407）、审计 fix3 | world/tasks.py:592-596；world_generation_center_service.py:991,1036-1039,1407,1480,1640-1648 |
| world.ask | world/services/worldbuilding/ask_world_service.py:594 | 2×U(2,0) + U(2,0)，R=3 | 27 | C1 | 阶段 asyncio.timeout 1800（:590） | 同步 API→R=3；known-keys ≤2；审计 fix3；无返修（:520-540） | ask_world_service.py:44,520-540,590-594 |
| world.world_bible.synopsis | world_bible_synopsis_service.py:1211 | T2 × [U(2,0)+U(2,0)]，R=3 | 36 | C1 | step+provider 1800（:51,1254） | R=3（world/tasks.py:694-697 未开 retry_llm）→ fix3；govern_world_output repair=None → 无返修；task ×2 | world/tasks.py:694-697 |
| world.validation | world/services/worldbuilding/world_validation_service.py:1411（packet 循环 :1380） | **A = 6P**：T2 × P × U(2,0)，P=`min(planned_packets, max_packets)`，R=1，P≤256 | **1536** | **C2**（P 由冻结的 packet 计划决定；`max_packets` schema 上限 256，默认 24——第一轮误把默认 24 当上限） | per_packet_timeout_seconds 默认 180s（schemas.py:3219），无外层 asyncio | R=1（world/tasks.py:31-35）→ fix3 → task ×2；已完成 packet 按 input_hash 跳过（:1377-1382） | **schemas.py:3216 `max_packets: int = Field(default=24, ge=1, le=256)`**；world_validation_engine.py:1100-1214（batch 切片 :1203-1210）；world_validation_service.py:852-894,1380-1419；world/tasks.py:31-35 |
| world.entity_fusion（交互任务路径） | world/entity_fusion.py:1748（_decide；候选循环 :764-780；plan :646-652） | T2 × 3M × U(1,0)，M=`max_suggestions`≤200，R=1 | **2400** | **C2**（M 的 schema 上限 200；pairs=3M 由 M 与候选集决定） | 无 step timeout=、无 asyncio（仅 provider 180s） | R=1（world/tasks.py:436-440）→ fix2 → task ×2；批 12 对仅做 checkpoint（:34,:764） | **schemas.py:1715 `max_suggestions: int = Field(default=50, ge=1, le=200)`**；world/api.py:3091-3131（FastAPI 校验请求体）；entity_fusion.py:646-652,764-780,1723-1774;world/tasks.py:436-440 |
| world.entity_fusion（**深导入路径·不可直接授权的异常高风险**） | imports/workflow_entity_phase.py:579 → world/entity_facade.py:532-551 → entity_fusion.py:419-432（`max_suggestions=10_000`） | N×3M×U(1,0)，M=10000，N=2（deep_import manual_resume，但 checkpoint 复用不重放已完成对）；成对上限 30000；另有整段 knowledge audit | **180009**（pair 180000 + audit 9） | **C3（异常高风险；必须分批授权）** | 无 heredoc timeout、无 asyncio；唯一护栏是 `deep_import` 任务的 lease/心跳 | R=3（imports/tasks.py:61 `recovery_policy="manual_resume"`，**未开 retry_llm**）；`deep_import_dedup` 异常被吞掉降级（workflow_entity_phase.py:589-599） | entity_fusion.py:419-432（注释仅称"一次导入上限 1 万对象"，**无硬性收紧**）、:646-652、:764-780、:827-853；imports/workflow_entity_phase.py:553-599；imports/tasks.py:61 |
| world.alias_relations.extract | world/tasks.py:164 → imports/entity_extraction/scene_entity_alias_relation.py:613-636 → scene_entity_llm_adapters.py:429-497 | T2 × S × U(0,1)，R=1 | 4S | **C2**（S=所选章节范围内的 Scene 数，任务输入在执行前冻结） | 每 scene wait_for（scene_entity_alias_relation.py:617-633）+ **全阶段** `phase2_alias_relation_total_timeout_seconds`（scene_entity_config.py:186+） | R=1（world/tasks.py:164-168 retry_llm=True）→ fix0+format1 → task ×2；并发由 `phase2_alias_relation_concurrency()` 决定 | world/tasks.py:164-168；scene_entity_alias_relation.py:613-636；scene_entity_llm_adapters.py:435,488-497 |
| world.map_structure.generate | world/map_structure_workflow.py:672（批次循环 :639-653） | **⌈S/5⌉ × [U(1,0)+U(1,0)(治理)]，R=3，且 S≤20（schema：location_ids+feature_ids 合计 ≤20）** | **60** | **C2**（S 的上限来自 schema，不是默认值） | provider 120s（map_structure_workflow.py:658 `timeout_override=120`）；无 harness timeout | R=3（map_atlas_tasks.py:19-21 `manual_resume`，未开 retry_llm）；`max_fix_attempts=1`（:687）；治理审计 fix3，无返修（:691-722） | **map_structure_schemas.py:288 `if not 1 <= len(self.location_ids)+len(self.feature_ids) <= 20`**（两个字段各自 max_length=20，:279-280）；map_structure_workflow.py:219-316（symbols 只来自 selected）、:639-653、:687、:691-722；map_atlas_tasks.py:19-21 |
| world.map_atlas.plan | world/map_atlas_workflow.py:1492 + :750 | U(2,0) + U(1,0) + focused(1+2n)，R=3；**plan 路径 nodes≤20** | **16+2n（n 未核实上界）** | **C3（n 不受常量约束，需分批）** | 无 harness timeout（仅 provider 快照 timeout） | R=3（map_atlas_tasks.py:28-32 `manual_resume`，max_attempts=20 只对 auto_requeue 有意义）；fix3 / fix2 | map_atlas_workflow.py:750,1492,1317；**map_atlas_schemas.py:186 `nodes: list[AtlasNodePlan] = Field(max_length=20)`**、:462 pages max_length=20 |
| world.map_image_prompt（页级图片 generate/edit） | world/map_atlas_workflow.py:1843（edit）/1857（generate），循环 :1840-1868 | pages × 3（仅 `error.retryable and not error.possible_charge and attempt<2` 才重发；possible_charge/未知错误 → 1 次即止） | ≤60（plan 路径 pages≤20）/ 3（结构路径） | **C2**（pages 由冻结的 AtlasPlan.nodes 上限 20 决定） | 图片 client timeout=profile.timeout（image_runtime.py:109）；退避 2^attempt（:1867） | image SDK `max_retries=0`（image_client.py:151）；应用层 `for attempt in range(3)`（:1840） | map_atlas_workflow.py:1317,1840-1868；map_atlas_schemas.py:186 |
| story.story_outline.generate | story/outline_state/story_outline_generation.py:588-646（候选 :655、审计 :725、返修 :634） | T2 × [2×U(2,1) + 2×3×U(2,1)]，R=1 | 64 | C1（全常量：2 候选、3 审计维度、2 轮） | 阶段 1800s（:588）+ step 1800（:664,:755）+ provider 1800（:517） | R=1（outline_state/tasks.py:83-87）→ fix3+repair1；审计 3 维度串行；task ×2 | outline_state/tasks.py:83-87 |
| story.outline.p20 | story/outline_state/p20_service.py:228-306（候选 :326、审计 :425） | T2 × [2×U(2,1) + 2×3×U(2,1)]，R=1 | 64 | C1 | 阶段 1800s（:228）+ step 1800（:342,:449） | R=1（outline_state/tasks.py:269-273）；fix3+repair1；3 审计 gather；task ×2 | outline_state/tasks.py:269-273 |
| story.outline.analyze | story/outline_state/ai_workflow_service.py:533-582 | T2 × 1 × R1 | 2 | C1 | 无 harness timeout；仅 provider 180s | R=1（outline_state/tasks.py:233-237）；无结构化修复层；task ×2 | outline_state/tasks.py:233-237 |
| story.character_card | story/generation.py:265-307（_run :241-263，治理 :55-202） | T2 × [U(2,1)+U(2,0)]（被阻断时 ×2） | 28（通过 12） | C1 | step 1800（:258）；审计无 timeout | R=1（story/tasks.py:452-456）；fix3+repair1；task ×2 | story/generation.py:241-263,265-307；story/tasks.py:452-456 |
| story.reaction | story/generation.py:309-346（循环 story/tasks.py:525-536） | T2 × N × [U(2,1)+U(2,0)]，N≤24，R=1 | 672 | **C2**（N=冻结的 character_ids，schema max_length=24） | 同 character_card | R=1（story/tasks.py:498-502）；每角色一整链；task ×2 | **story/schemas.py:247 `character_ids: list[str] = Field(default_factory=list, max_length=24)`**；story/tasks.py:504-536 |
| story.script | story/generation.py:348-389 | T2 × 1 × [U(2,1)+U(2,0)] | 28 | C1 | 同 character_card | R=1（story/tasks.py:557-561）；task ×2 | story/tasks.py:557-561 |
| story.one_click | story/tasks.py:608-613，循环 :636-672 | T2 × [N×(14+14) + 14]，N≤24，R=1 | 1372 | **C2**（N≤24，story/schemas.py:295） | 同 character_card；串行 2N+1 条链，无阶段预算 | R=1（story/tasks.py:608-612）；子能力各自 fix3+repair1/审计 3；task ×2 | story/schemas.py:295；story/tasks.py:608-672 |
| story.scene_fusion | task：outline_state/scene_fusion_draft.py:533（阶段 :370）；废弃同步 API：outline_state/api.py:860-881 | task：T2×2×U(1,1)；同步 API：2×U(1,1)(R3) | 12（task）/18（废弃 API） | C1 | 阶段 1800s（:370）+ step 1800（:585）+ provider 1800（:311） | task R=1（outline_state/tasks.py:351-355）；fix2+repair1；task ×2 | outline_state/tasks.py:351-355 |
| story.structure_dedup（去重 task） | story/outline_state/structure_dedup.py:588；task project/tasks.py:9；深导入 imports/deep_import_dedup.py:25-35 | **第三轮修正**：smart_dedup 拆分 `world_legacy_budget=max_suggestions//3`、`outline_budget=max_suggestions−world_legacy_budget`（默认 120→40/80；API 上限 300→100/200）；outline 每类 `max_pairs=2×outline_budget`，keep_separate 不写入建议也不触发全局提前停止 ⇒ 默认 5 类×160 pair×U(1,0)=2×T2 = **3200**；API 上限 300 时 5×400×2×2 = **8000**。深导入：4 类、max_suggestions=40、每类 80 pair、R=3、max_fix_attempts=1 ⇒ 4×80×6 = **1920** | 3200（默认）/ 8000（API 上限）/ 深导入 1920 | **C2**（outline_budget 与 API 上限均已冻结；深导入 C2） | 无 harness timeout（:563-624 未传）；仅 provider 180s | 去重 task R=1（project/tasks.py:9-14 retry_llm=True）；fix1（structure_dedup.py:617 max_fix_attempts=1）；task ×2。深导入：R=3（imports/tasks.py:61 manual_resume 未开 retry_llm），经 `outline_facade` 调用 `open_project_llm_client` | structure_dedup.py:122-133,617,752-758；smart_dedup.py:86-92,144-157；project/schemas.py:479（`max_suggestions le=300`）；project/tasks.py:9-14；deep_import_dedup.py:25-35 |
| imports.scene_plan | imports/workflow.py:302-339（scene_planning.py:128 `llm_calls=0`） | 0 | 0 | C1（无 provider I/O） | 无 | 无 | imports/workflow.py:302-339；scene_planning.py:128 |
| imports.scene_slicing | workflow_scene_phase.py:222 → workflow.py:341-366 → scene_slicing.py:117-306 | W×(T×2×(F+G))×2 + S×F + G_gap×F；W=Phase0 窗口数、S=Scene 数**由模型决定** | 无编译期常量上界 | **C3（必须分批授权）** | 步骤 wait_for `phase1a.scene_slicing_timeout_seconds` 默认 900（workflow_llm_adapters.py:110-119,485） | R=3（imports/tasks.py:61 manual_resume）；窗口并发 50（scene_slicing.py:28）；token 升级 ≤3；整窗重发 ≤2（:602-607）；结构化 max_fix1+format1=3；语义纠错 ≤2 | scene_slicing.py:28,602-607,2386-2391；workflow_llm_adapters.py:313-314 |
| imports.scene_enrichment | workflow_scene_phase.py:372 → workflow.py:368-407 → scene_enrichment.py:73-124 | S × 2 × (F+G) | 24S（S 无编译期上限） | **C3** | 步骤 wait_for `phase1b.enrich_timeout_seconds` 默认 1200（workflow_llm_adapters.py:122-131,877） | R=3；每 Scene 独立、并发 200（scene_enrichment.py:20）；重试 ≤2；max_fix1+format1=3 | scene_enrichment.py:20,183-193 |
| imports.scene_fusion | workflow_scene_phase.py:482,524 → workflow.py:409-464 → scene_fusion_phase1c.py:70- | (G_r+C) × (F+G)（F=2,G=0 时 12×(G_r+C)）；G_r≤W，C≤S/2 | 12×(W+S/2)（W、S 无编译期上限） | **C3** | 每调用 wait_for `phase1c.timeout_seconds` 默认 1200（workflow_llm_adapters.py:1093-1099） | R=3；并发 `phase1c.concurrency` 默认 20（workflow.py:451-457）；max_fix1+format1=3 | workflow.py:451-457；workflow_llm_adapters.py:1093-1099 |
| imports.entity_extraction | workflow_entity_phase.py:90 → workflow.py:730-776 → scene_entity_extraction.py:238-312 与 scene_entity_llm_adapters.py:116,488 | 2a: S×(F+A)=12S + 重跑 F_a×12；2b: S×U(0,1)=2S | 14S+12F_a（S 无编译期上限） | **C3** | 每 Scene wait_for `phase2.parallel_llm_timeout_seconds` 默认 900；provider 360；2b 600/120 | R=3；并发 25（2a）/4（2b）；2a `max_fix_attempts=1`+format1 且 transport_retries 受 worker 影响 ⇒3；2b `max_fix_attempts=0`+format1 ⇒2；失败 Scene 可整段重跑 | scene_entity_llm_adapters.py:38-43,116-129,435-497；workflow_entity_phase.py:652-707 |
| imports.structure_analysis | workflow_structure_phase.py:134-281 → story/outline_state/generation/parser.py:162,382 | 质量门 ≤2 × [U(1,1)(R3)=9 + B×U(1,1)=9B] | 18+18B（B 无编译期上限） | **C3** | 首次调用 wait_for `phase3.structure_timeout_seconds` 默认 1200（workflow_structure_phase.py:165-176）；质量门重跑不在其内 | R=3（imports/tasks.py:138）；主调用 max_fix1+transport True+format1=9；复核每批 9；质量门重跑 ≤1 | workflow_structure_phase.py:165-176；parser.py:289,546-560 |
| imports.review_resolution | review_resolution.py:1211（场景）与 :192（问题组） | 问题组 ≤3×(1+A)=30/组；场景组 2×(1+A)=20/组 | 30·G_groups + 20·G_scene | **C2**（组数按 scene_id 以 32 键切块；asset_keys≤10000） | 单次 wait_for 600s（:191-224）；client timeout 540 | R=3（imports/tasks.py:175）；judge max_fix0+transport False⇒1；audit ≤9 无返修；MAX_GROUP_REQUESTS=3 + revise/verify ≤2 | review_resolution.py:191-224,367-371,1211；review_resolution_schemas.py:25 |
| imports.targeted_completion | targeted_completion.py:244（批次 :209-308） | batches × (2 + G) = 21·batches；显式 roots≤100；**自动 roots 无上限** | 21·batches（自动 roots 路径无编译期上界） | **C3（自动 roots 路径）/ C2（显式 roots 路径）** | 每批 wait_for 600s（:33,243-256）+ client 540 | R=3（imports/tasks.py:163）；max_fix1+transport False⇒2；audit 9+repair 2+复审 9 | targeted_completion.py:33,209-308,518-599；imports/tasks.py:163 |
| interaction.story_generate（非 agent） | interaction/tasks.py:88,118 + generation.py:784-936 | 4×U(1,0)(R3) + 1 + U(2,0)(R3) + 1·R3 + U(2,0)(R3) | 46 | C1 | provider 900s/请求（tasks.py:69,113）；治理段无 asyncio | R=3（interaction/tasks.py:38 `restart_origin`）；summary ≤4 pass×6；主流 transport_retries=False⇒1；audit1 9；repair 3；audit2 9 | interaction/tasks.py:38-40,88-118 |
| interaction.story_generate（agent） | interaction/tasks.py:73 + infrastructure/llm/agent_runtime.py:414-520 | 8 + 9+3+9 | 29 | C1 | agent 段 `asyncio.timeout(remaining_seconds)`≤1800（agent_runtime.py:478,80-85） | R=3；Agent(request_limit=12 但此路径 8 次上限) | agent_runtime.py:80-85,414-520 |
| interaction.summary_refresh | interaction/tasks.py:208（handler :189） | T2 × [2×U(1,0) 且 transport_retries=False⇒每次 1] | 8（LLMInvalidResponseError 不可重试时 2） | C1 | provider 900s（:204）；无 asyncio | task auto_requeue ×2（tasks.py:189-196）；内层 `retry_with_backoff(max_attempts=2)` | interaction/tasks.py:189-220；retry.py:64-73,84-96 |
| interaction.continuity_review | interaction/proactive.py:236 | U(2,0)(R3) | 9 | C1 | 无 timeout_override ⇒ 默认 180s（core/config.py:302）；请求前输入预算检查 :230-234 | R=3（interaction/tasks.py:31 manual_resume）；fix3；无外层循环 | interaction/proactive.py:230-236；interaction/tasks.py:31 |
| interaction.anonymous_story | interaction/streaming.py:274（summary）与 :313（正文），治理 :339-344 | 4×U(1,0)(R3) + 1 + 9 + 3 + 9 | 46 | C1 | 无 timeout_override ⇒ 180s/请求；无 asyncio，仅 is_disconnected | 非 worker（SSE）⇒R=3；summary ≤4 pass；流 transport_retries=False⇒1；治理 9/3/9 | interaction/streaming.py:256-259,274,313,339-344 |
| assistant.turn | assistant/service.py:940（主 agent）、:1021（repair）、:987-1064（复核） | 非 pro：request_limit=12；pro：12 + 2×U(2,0)(R3)=12+18 | 12（非 pro）/30（pro） | **C1**（request_limit 常量；但 workflow_budget.py:438-447 已有 `authorize_additional_requests`，作者显式续算可抬高额度） | agent 段 `asyncio.timeout(budget.remaining_seconds)`≤1800（agent_runtime.py:80-85,478）；知识审查无 asyncio；provider 默认 180s | R=3；`Agent(usage_limits=UsageLimits(request_limit=budget.limits[0]))`（agent_runtime.py:483）与 `budget.reserve` 双约束；工具内联每次 attempt 记 1（workflow_budget.py:22-25）；审查 9×2 | agent_runtime.py:76（`{"author": (12, 32, 4), ...}`）,478-483；assistant/service.py:980；workflow_budget.py:22-25,438-447 |
| infrastructure.rag_query_planner | evidence/compilation/services/retrieval_query_planner.py:384 | 1 × 每次 compile 扩展（max_fix=0、transport_retries=False、format=0） | 1/次 | C1 | `LLM_QUERY_PLANNER_TIMEOUT_SECONDS=30`（:37,411） | 无内层重试；外层 except 直接降级返回确定性计划（:355-366） | retrieval_query_planner.py:37,355-366,406-411 |
| infrastructure.reranker | evidence/indexing/reranker.py:236 | U(2,1) = 4R | 12（R=3） | C1 | `RERANKER_TOTAL_TIMEOUT_SECONDS=1800`（:24,253） | 单次无外层循环；fix3+format1 | reranker.py:24,236-255 |
| infrastructure.format_repair | client.py:940-1043（内层兜底，无独立入口） | f × R（f=format_repair_attempts） | 0 / 3 / 12 | C1 | 随宿主 step 的 timeout | 由宿主 max_fix 循环全败后触发（client.py:913-928） | client.py:690-695,913-928,940-1043 |
| infrastructure.embedding | infrastructure/llm/client.py:1079-1144（调用方 retrieval.py:50、embedding_writer.py:69,121） | `retry_with_backoff(max_attempts=R)` = R/批 | 3/批 | C2（批次数由索引任务决定） | provider timeout（profiles/config） | transport 层 R（retry.py:119-191） | client.py:1079-1144；retry.py:119-191 |
| infrastructure.account_connection_test | modules/account/settings_service.py:144-146 | 1（models.list）/次连接测试 | 1 | C1 | timeout=30（:144，硬编码） | SDK `max_retries=0`（image_client.py:151） | settings_service.py:144-146 |

## 4. 重点核实分节（本轮逐条核对结果）

### 4.1 world.map_structure.generate：为什么是 60
1. 批次公式：`for start in range(0, len(symbols), 5)`（map_structure_workflow.py:639-653），每批 5 个 symbol。
2. `symbols` 只来自本次选择：`selected = {k: by_id[k] for k in feature_ids}` 再并上 `location_ids` 解析出的 canonical
   location 实体（:264-312）。没有把 baseline 文档全部 features 纳入。
3. schema 上限：`MapGenerateRequest` 对两个字段各自 `max_length=20`，且模型校验器强制
   `1 <= len(location_ids) + len(feature_ids) <= 20`（map_structure_schemas.py:279-290）。**故 S ≤ 20**。
4. 每批请求数：`max_fix_attempts=1` ⇒ 结构化 `U(1,0)=2·R`；`govern_group_output(repair 缺省 None)` ⇒ 审计 1 次
   `U(2,0)=3·R`；R=3（map_atlas_tasks.py:19-21 `manual_resume`，未开 `retry_transient_llm_errors`）⇒ 6+9=15。
5. **A = ⌈20/5⌉ × 15 = 60**。第一轮的"15⌈S/5⌉ / 无常量上界"是**默认值当最大值**的典型错误（把"用户选多少就多少"
   当成了无上限，忽略了 schema 校验器）。
6. **第一轮表格里还写了 `fix2+format1`，与代码 `max_fix_attempts=1`、`format_repair_attempts` 未传（=0）不符**，
   按代码修正为 fix1，即 U(1,0)=6 而非 12。

### 4.2 world.validation：A = 6P，P ≤ 256
1. 真实公式是 **每个 packet 一次 `run_managed_structured`**（world_validation_service.py:1380-1419），
   所以"请求数 = packet 数 × 尝试层"，**不是**"请求数 = 1 × ..."。
2. packet 数：`build_review_packets`（world_validation_engine.py:1100-1215）按 `packet_character_limit` 切块；
   调用点传 `allow_over_budget=True`（world_validation_service.py:852-859），此时返回的批次
   `len(batch) + 1 > policy.max_packets` 即 break（:1203-1210）⇒ **单次执行 P ≤ max_packets**。
3. `max_packets` 的真实上界：schemas.py:3216 `max_packets: int = Field(default=24, ge=1, le=256)` ⇒ **P ≤ 256**。
   第一轮用默认 24 算出 144，属"默认值当最大值"。
4. 尝试层：R=1（world/tasks.py:31-35 `retry_transient_llm_errors=True`）→ fix3 ⇒ U(2,0)=3；task auto_requeue
   max_attempts=2 ⇒ T=2。
5. **A = 2 × 256 × 3 = 1536**。已完成 packet 按 `input_hash` 跳过（:1377-1382），故 A 是"全部 packet 都要打"的最坏上界；
   实际被 `allow_over_budget` 切成多个执行批次时，A 应按"每次执行 ≤256 packet × 单次尝试层"分片计算。

### 4.3 world.entity_fusion：交互 2400 / 深导入 180000 + 9（必须单列）
1. pair 数 = `max_pairs=max_suggestions * 3`（entity_fusion.py:650），逐对一次 `_decide`（:764-780）→
   每对一次 `run_managed_structured(max_fix_attempts=1)`（:1748-1774）⇒ `U(1,0)=2·R`。
2. 交互任务路径：`max_suggestions` 来自 schema，**上限 200**（schemas.py:1715）；任务 R=1（world/tasks.py:436-440）；
   **A = 2 × (3×200) × 2 = 2400**。
3. **深导入路径（异常高风险，不可直接授权）**：entity_fusion.py:419-432 直接给
   `limit=10_000, max_suggestions=10_000`，**绕过了 schema 校验**（该入口只走
   imports/workflow_entity_phase.py:579 → entity_facade.py:532-551，不经 FastAPI/Pydantic 请求体），
   代码里唯一"依据"是 :420-421 的注释（"一次导入上限 1 万对象"），**没有任何硬性收紧**。
   pair 上限 = 30000；`_TASK_REVALIDATION_BATCH_SIZE=12`（:34）只用于 checkpoint 落盘，**不是请求闸门**；
   deep_import 任务的 R=3（imports/tasks.py:61 `manual_resume`，未开 retry_llm）。
   pair 决策部分 **A_pair = 30000 × 2 × 3 = 180000**；当前代码随后还会对整段结果做一次
   knowledge audit（`max_fix_attempts=2`、transport R=3），所以完整 manifest 的
   **A_total = 180000 + 9 = 180009**。此前 180000 只覆盖 pair 决策，保留为风险量级简称，
   不再当作完整请求上界。
4. **为什么不能进常规 L0**：它 (a) 不经过任何 schema/产品输入校验；(b) 没有请求数闸门、没有 per-batch 授权；
   (c) 异常被吞成降级结果（workflow_entity_phase.py:589-599），失败不会自动止血；(d) 单次动作的请求量比表中
   第二大的 world.generation.convergence（18405）还高一个数量级。
   **要求：H 必须显著小于 A，且按 12 对一批逐批追加授权；在此之前不得把该路径纳入自动额度下发。**
   （注：第一轮正文写"最坏 60000 次/尝试 ×2 = 180000"，与它自己表里的 600 不一致；本轮以 pair 上限
   30000 × U(1,0) 的 R=3 口径给出 180000，并明确它是**pair 决策部分**的上界；本轮准入
   manifest 另计 9 次 knowledge audit。）

### 4.4 执行前已冻结工作量的能力：只记动态公式，不新增产品输入限制
- **writing.generate**：K = `receipt.included` 的条目数（scope.py:183-184），receipt 由
  `KnowledgeScopeReceipt` 在生成 plan 时冻结（contracts.py:161-221），执行时只读
  `plan.knowledge_scope_receipt`（writing/services.py:3312-3318）。分片 64（workflow.py:55,259-262）。
  **公式 `A = T2 × (⌈K/64⌉·U(2,0) + U(2,0) + U(2,0))`，R=1 ⇒ 6⌈K/64⌉+8。**
  第一轮在此基础上多算了一段返修（`hooks.repair=None`，workflow.py:460-469 直接 blocked），并写了
  "无常量上界"——**本类不需新增产品输入限制，但 C2 分类要求 L0 由冻结 K 计算**。
- **world.alias_relations.extract**：S = 所选章节范围内 Scene 数，任务输入在入队时冻结；
  **A = T2 × S × U(0,1) = 4S**（R=1）。
- 同类：story.reaction / story.one_click 的 N≤24、imports.review_resolution 的组数、world.map_atlas.plan 的 pages≤20，
  都是"冻结输入 + schema 上限"，归 C2。

### 4.5 其余行本轮重核发现的问题
- **第一轮 `world.generation.suggestion` 同步 API 上界写 144**，但同一公式 `4×48` 应为 **192**（算术错误，本轮修正）。
- **第一轮 `world.map_structure.generate` 的 retry 层级写成 `fix2+format1`**，代码是 `max_fix_attempts=1`、
  无 format repair（map_structure_workflow.py:687）⇒ **U(1,0)=6**。同一行内自相矛盾（公式写 U(1,0)，注释写 fix2），本轮统一。
- **第一轮 `story.structure_dedup` 写 3200**：按代码重核，`max_pairs=max_suggestions*2` 在**每个资产类型内部**
  生效（structure_dedup.py:122-133），全局 `len(suggestions) >= max_suggestions` 才提前 break（:132,200）；
  smart_dedup 传给 outline 的预算是 `outline_budget = max(1, max_suggestions - max(1, max_suggestions//3))`
  （smart_dedup.py:91-92,151），默认 120 ⇒ 每类 ≤87 对，5 类 ⇒ ≤435 次 LLM。**聚合器的 max_suggestions 是未校验 int
  （project/tasks.py:51 默认 120），所以 A 随它线性增长，不能写成常量 3200。**
- **第一轮 `imports.entity_extraction` 2b 写 6S**：2b 是 `U(0,1)`，R=3 时 = 3（1 主 + 1 format，且 transport
  在 worker 内被关闭）；R=1 时为 2。本轮按 R 显式分列，公式写 `2S（R=1）/ 6S（R=3）`。
- **第一轮 `map_image_prompt` 的 A 依赖 `AtlasPlan.nodes max_length=20`**——已核实
  map_atlas_schemas.py:186、`run.planned_page_count = len(plan.nodes)`（map_atlas_workflow.py:1317），结论保持。
- **第一轮 `assistant.turn` 说"30 分钟内 manual resume 可重复"**：在 HEAD 288dbd1c5 上，额度提升走
  `authorize_additional_requests()`（workflow_budget.py:438-447），属新的作者授权动作，会计入 authorization_revision；
  结论方向一致但机制表述本轮已更新。

## 5. 本轮修正清单（原值 → 新值 → 证据 文件:行号）

1. **world.map_structure.generate 上界**：15⌈S/5⌉「无常量上界」→ **60**（S≤20 时 4 批 ×15）。
   证据：map_structure_schemas.py:279-290（两字段 max_length=20 + 合计 ≤20 校验器）；map_structure_workflow.py:264-312,639-653,687,691-722。
2. **world.map_structure.generate retry 层级**：fix2+format1（U(1,0)=12）→ **fix1，无 format repair（U(1,0)=6）**。
   证据：map_structure_workflow.py:687（`max_fix_attempts=1`）；client.py:695（`format_repair_attempts=0` 默认）。
3. **world.map_structure.generate transport 口径**：15×R3 → 保持 R=3，但补上依据。
   证据：map_atlas_tasks.py:19-21（manual_resume，未开 retry_llm）；worker.py:591-593。
4. **world.validation 上界**：2×24×3=**144**（默认 24 当上限）→ **6P，P≤256 ⇒ 1536**。
   证据：schemas.py:3216（`max_packets ... le=256`）；world_validation_engine.py:1203-1210（batch ≤ max_packets）；
   world_validation_service.py:852-894,1380-1419；world/tasks.py:31-35。
5. **world.entity_fusion 交互路径上界**：600 → **2400**（3×200 对 × U(1,0)=2 × T2）。
   证据：schemas.py:1715（`max_suggestions ... le=200`）；entity_fusion.py:650（`max_pairs=max_suggestions*3`）、
   :764-780、:1748-1774；world/tasks.py:436-440。
6. **world.entity_fusion 深导入路径**：60000 次/尝试 ×2（正文）与表内 600 自相矛盾 → **180000 pair 决策 + 9 audit，单列为"不可直接授权的
   异常高风险路径"**，并写明不得进入常规 L0。
   证据：entity_fusion.py:419-432,646-652,764-780；imports/workflow_entity_phase.py:553-599；imports/tasks.py:61。
7. **writing.generate 公式**：2×(3⌈K/64⌉+4) → **6⌈K/64⌉+8**（去掉不存在的返修段），并把"无常量上界"改为
   **C2（冻结 K）**，明确不新增产品输入限制。
   证据：workflow.py:460-469（repair=None 直接 blocked）；writing/services.py:3312-3333；
   scope.py:183-184；contracts.py:161-221；workflow.py:55。
8. **world.alias_relations.extract 分类**：无常量上界 → **C2（冻结 S）**；公式保持 4S 并补 R=1 依据。
   证据：world/tasks.py:164-168；scene_entity_llm_adapters.py:435,488-497。
9. **world.generation.suggestion 同步 API 算术**：144 → **192**（4×48）。
   证据：world_generation_center_service.py:991,1036-1039,1407,1480,1640-1648。
10. **story.structure_dedup 上界**：3200（常量）→ **870（默认 120，随未校验的聚合预算线性增长）**，并标注聚合器风险。
    证据：structure_dedup.py:122-133,752-758；smart_dedup.py:86-92,151；project/tasks.py:9-14,46-54；
    deep_import_dedup.py:28-35。
11. **R 的属性说明**：新增「R 来自 env int（core/config.py:311-313），无代码上界；文中 R=3 是默认上限口径」。
12. **agent_step_harness.py 行号**：run_managed_generate 826→**873**、run_managed_structured 840→**926**、
    默认参数 840-845→**933,938**（本 HEAD 文件 1031 行）。
13. **assistant.turn 额度机制**：补 `authorize_additional_requests()`（workflow_budget.py:438-447）与
    `UsageLimits(request_limit=budget.limits[0])`（agent_runtime.py:483）的真实依据。

## 6. 仍存疑项

1. **`world.map_atlas.plan` 的 n（Focused Evidence 分页）没有找到硬上界**：plan 路径的 `nodes ≤ 20` 已核实，
   但 focused 检索的分页次数 n 只在预算/工具层收敛，未见 schema 或常量上限——**未核实**，归 C3，需分批授权。
   待查：`focused_tasks.py:238` 的 `max_attempts=5` 与单次 focused 请求数的乘积关系。
2. **`imports.targeted_completion` 自动 roots 上限未核实**：显式 roots ≤100 有证据，自动 roots 由
   `completion_hints`/needs_review provenance 决定（targeted_completion.py:518-599），未找到常量上限。
3. **`smart_dedup_scan` 聚合预算无校验**：`project/tasks.py:51` 用 `int(meta.get("max_suggestions", 120))`，
   API 侧是否另有 schema 限制**未核实**；若确无，则项目级智能去重的 A 随该 int 线性增长（近似无界）。
4. **`imports.structure_analysis` 的 S 与 B 上限未核实**：B 只按 60000 字符切批（parser.py:289,546-560），
   S=Phase3 资产数由模型输出决定。
5. **`R=3` 之外，`llm_timeout` 等 provider 参数也无代码上界**（core/config.py:302 默认 180s）；
   A 的口径与 R 一样依赖"部署未调大 env"这一前提。
6. **第一轮 `story.structure_dedup` 的 3200 是否来自某个未读到的调用点**：本轮按代码重核未复现该数字；
   若主 Agent 有反例（例如某调用点显式传 `max_suggestions=160` 且 asset_types 只有 5 类），请提供调用点，
   我会再核算。


## 6a. 第三轮复核（2026-09-15 W2.1 接手主 Agent，逐行对照代码）

第二轮的 story.structure_dedup 复算（870）与"未校验 int"存疑已被第三轮推翻，以下结论以代码为准：

1. **smart_dedup 预算拆分（smart_dedup.py:91-92）**：`world_legacy_budget = max(1, max_suggestions // 3)`、
   `outline_budget = max(1, max_suggestions − world_legacy_budget)`。默认 120 ⇒ 40/80；第二轮引用的
   `max(1, max_suggestions − max(1, max_suggestions//3))` 算出的 87 是算术错误（120−40=80）。
2. **outline 侧每类 pair 上限（structure_dedup.py:128）**：`max_pairs = max_suggestions × 2`（此处
   max_suggestions 实参即 outline_budget）⇒ 默认每类 ≤160 对，5 类 ⇒ ≤800 对/attempt。
3. **keep_separate 不提前停止（structure_dedup.py:132-133,151-152,200-201）**：`_decide` 返回
   keep_separate 时 `continue`，不追加建议；全局提前停止只在 `len(suggestions) >= max_suggestions`
   时触发。最坏路径是"全部 pair 都被 keep_separate"，全部 pair 都要打一次 LLM。行为由
   `test_structure_dedup.py::test_keep_separate_decisions_never_stop_the_scan_or_create_suggestions` 固化。
4. **每对请求次数（structure_dedup.py:617 `max_fix_attempts=1`）**：去重 task 注册
   `retry_transient_llm_errors=True` ⇒ worker 关闭 transport retry ⇒ R=1 ⇒ U(1,0)=2。
5. **任务层乘数（project/tasks.py:9-14）**：`auto_requeue`、`max_attempts=2` ⇒ T=2。
   **默认最坏上界 A = 5×160×2×2 = 3200**。
6. **API 合法上限（project/schemas.py:479）**：`max_suggestions: int = Field(default=120, ge=1, le=300)`
   ——第二轮"未校验 int"的存疑已被此 schema 推翻。上限 300 ⇒ outline_budget=200 ⇒
   A = 5×400×2×2 = **8000**。task meta 的 `int(meta.get(...))` 读的是经该 schema 校验后冻结的入队值。
7. **深导入路径（deep_import_dedup.py:25-35）**：4 类资产（无 scene）、`max_suggestions=40` ⇒
   每类 ≤80 对；R=3（imports task `manual_resume` 未开 retry_llm）；`max_fix_attempts=1` ⇒ 每对
   U(1,0)=2·R=6。**A = 4×80×6 = 1920**（第二轮写 640，漏乘了 R=3 的 transport 尝试）。参数由
   `test_deep_import_dedup.py::test_structure_review_budget_is_frozen_for_deep_import` 固化。
8. **world entity 部分**：smart_dedup 的 world 建议走 `world_facade.suggest_entity_fusion`，属于
   `world.entity_fusion` 能力（交互路径公式 3M×U(1,0)×T2，M≤200），与 outline 侧的
   `story.structure_dedup` 分属两个 root capability，不重复计入本能力，也不并入其 A。
9. **writing.generate 公式复核（维持第二轮 6⌈K/64⌉+8，本轮补齐推导）**：R=1（writing/tasks.py:163-167
   retry_llm=True）、task ×2（auto_requeue max_attempts=2）；director 分片 64（workflow.py:55）每片
   U(2,0)=3；candidate 是 `run_managed_generate` 单请求（services.py:3303）=1；audit 一次
   U(2,0)=3（knowledge/workflow.py:367-376）；repair=None 无返修段。
   A = 2×(3⌈K/64⌉+1+3) = **6⌈K/64⌉+8**。
10. **C1/C2/C3 归类（按任务协议三分）**：C1=编译期常量（如 world.validation=1536、story.outline.p20=64）；
    C2=本次冻结工作量可动态计算（writing.generate 6⌈K/64⌉+8、story.structure_dedup 3200/8000、
    深导入 1920、world.alias_relations.extract 4S 等）；C3=运行中才知规模、需分批授权（imports 各阶段、
    targeted_completion 自动 roots、world.entity_fusion 深导入 180009 的常规路径）。
    第二轮 §6 存疑项 1-5 维持，但第 3、6 条（structure_dedup）按本轮结论关闭。

## 7. 与第一轮一致的结论（本轮未推翻）

1. **R 不是全局常量**：worker.py:591-593 把 task 的 `retry_transient_llm_errors` 翻译成 transport retry 的 1/3 分叉，
   公式必须带 R 或按路径分别给出。
2. **请求上界的真正瓶颈在数据规模**（imports 的 S/B、writing 的 K），但这些规模在执行前多数已冻结（C2）；
   真正需要运行期分片的是 imports 各阶段与 targeted_completion 自动 roots（C3）。
3. **现有 `managed_llm_steps` 是 provenance 而非账本**（无 token、按 identity 去重，
   agent_step_harness.py:228-302 附近）；文本链路没有 possible charge 语义，唯一有该语义的是 Map 图片
   （image_client.py:38-52,96-121,246-260；map_atlas_workflow.py:1840-1877,1952-1959）。
4. **计量旁路仍未收口**（第一轮 §6 的 6 条）：transport retries 关闭时 `generate_structured` 直连 provider
   （client.py:736-742）、`generate_stream` 不查 `current_workflow_budget()`（client.py:630-665）、
   `research` 不走 WorkflowBudget（client.py:667-683）、embedding 远程分支（client.py:1134-1144）、
   无 budget 上下文的 `run_managed_*` 完全不计量、静态门禁覆盖不到直接构造的 image client
   （modules/account/settings_service.py:144-146）。本轮只复核了这些结论未发现反例，故保留。

（本轮仅只读分析 + 改写本文件一份；未修改源码、测试、TASK.md，未 git add/commit/push，未安装依赖、未启动服务、未跑 pytest。）
