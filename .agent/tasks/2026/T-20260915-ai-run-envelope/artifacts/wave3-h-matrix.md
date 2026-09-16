# Wave 3 H 建议矩阵与迁移裁决（主 Agent，2026-09-15）

口径：
- **A** = 本次冻结工作量下的主请求 + 既有 transport/schema/format/semantic retry + 既有自动 requeue（与 W0-B 第三轮一致）。
- **L0 = min(A, H)**；H 是单次授权安全闸门。
- **裁决原则（任务指令冻结）**：L0=A 时产品行为与现状完全一致（只是开始计量），不构成语义变化，直接迁移；只有 H<A 需要分批授权、或 A 在执行前无法冻结（C3）的能力才涉及产品语义，暂停并请求聚焦裁决。
- 因此本矩阵把能力分为三类：**迁移（L0=A）**、**暂停（需聚焦裁决）**、**非目标**。H 数值在没有产品证据时一律不发明；"H 建议"列只给出与 A 的关系和理由。

## 1. 迁移（本轮声明 root_capability_id + L0=A；仅已有 run 总时限时声明 deadline）

| 能力（root） | task type | A | L0 | H 建议 | deadline | 备注 |
|---|---|---|---|---|---|---|
| writing.generate | writing_generate | 6⌈K/64⌉+8（resolver 从冻结 receipt 算 K） | =A | H≥A：K 由作者确认的 scope receipt 冻结，单次授权已隐含 | 无 run 总时限；各 step 1800s | W3-A |
| writing.semantic_review | writing_semantic_review | 144 | =A | 同上（chunk≤24 常量） | 无 run 总时限；各 chunk step 1800s | W3-A |
| writing.targeted_revision | writing_targeted_revision | 4 | =A | — | 无 run 总时限；structured step 1800s | W3-A；错绑修正 |
| writing.conflict_check.ai_review / ai_suggestion | 对应两个 task | 6 / 6 | =A | — | 代码现有边界 | W3-A |
| story.story_outline.generate | story_outline_generate | 64 | =A | — | 无 run 总时限；单 attempt 阶段 1800s | W3-A |
| story.outline.analyze / p20 | outline_analyze / outline_generate | 2 / 64 | =A | — | 无 run 总时限；P20 单 attempt 阶段 1800s | W3-A |
| story.scene_fusion / character_card / reaction / script / one_click | 对应 task | 12 / 28 / 672 / 28 / 1372 | =A | reaction 的 672 由 schema max_length=24 冻结 | 无 run 总时限；保留各 step/attempt timeout | W3-A；one_click 为子链 canonical parent，子 step 归属 root |
| world.validation | world_validation | 6P，P≤256 ⇒ 1536 兜底 | =A | P 由冻结 packet 计划决定 | per-packet 180s×P 或 resolver | W3-B |
| world.entity_fusion | world_entity_fusion_suggestions | 3M×U(1,0)×T2，M≤200 ⇒ 2400 | =A | M 来自作者确认的 max_suggestions | — | W3-B |
| world.world_bible.synopsis | world_bible_synopsis_refresh | 36 | =A | — | 无 run 总时限；main/audit 各 1800s | W3-B |
| world.generation.suggestion | world_generation_suggestion | 96（task 路径） | =A | — | 1800s | W3-B |
| world.map_structure.generate | world_map_schematic_generate | 60 | =A | S≤20 由 schema 校验器冻结 | 120s×批次 | W3-B |
| world.generation.cocreation | world_cocreation_turn | chat fast 10 / chat pro 14 / design 24（任务路径，含至多两次 attempt） | =A | mode/quality_mode 在入队 payload 中冻结；同一 task type 使用 canonical parent | 无统一 run deadline；各 provider step 1800s | W4-N2；chat/design 子步骤仍按各自知识策略 |
| assistant.turn | assistant_turn | 12（非 pro）/ 30（pro） | =A | request_limit 常量即现行为 | 1800s | W3-C |
| interaction.summary_refresh | interaction_summary_refresh | 8 | =A | — | 无 run 总时限；provider 900s | W3-C；错绑修正 |
| interaction.continuity_review | interaction_continuity_review | 9 | =A | — | 无 run 总时限；provider 180s | W3-C |
| interaction.story_generate | interaction_story_generate / interaction_agent_story_generate | 每段 46 / 29 | 每个作者授权续段追加同额度 | length/manual/看海最多合法续写一段；不移动 deadline | 无 run 总时限；保留 provider/Agent 短边界 | W3-C；`InteractionGenerationAttempt.id` 是稳定 run，换 task 不换账本 |
| infrastructure.rag_query_planner | evidence_focused_search | 9（max_depth∈{0,1}） | =A | max_depth 由请求 schema 冻结 | 无 run 总时限；planner/nomination 各 30/600s | 主 Agent（已声明） |

## 2. 暂停（需聚焦裁决后才能迁移）

| 能力 / task | 阻塞原因 | 解除条件（聚焦裁决要回答的问题） |
|---|---|---|
| world.entity_fusion 深导入路径（A=180009，经 deep_import 宿主；其中 pair 决策 180000 + knowledge audit 9） | 不经 schema 校验、无请求数闸门、异常被吞成降级；W0-B 判定"不可直接授权" | ①按 12 对一批的逐批授权 UI/交互；②批次间 checkpoint 与续算的授权记录；③H 取值（建议远小于 180009 且按批发放） |
| deep_import / scene_auto_extraction / world_object_auto_extraction / plot_structure_auto_extraction（imports.scene_slicing/enrichment/fusion/entity_extraction/structure_analysis） | C3：规模（W/S/B）由上一阶段模型输出决定，A 执行前不可冻结 | ①"零 provider 的 Phase 0 先估算规模"的产品交互；②分阶段授权与超范围时 checkpoint 暂停（不静默截断）的语义 |
| targeted_completion | 显式 roots ≤100 为 C2，但默认自动 roots 由运行期 completion_hints 决定（C3） | 限制自动 roots 上限或改为分批授权；或强制先展示估算再开始 |
| import_review_resolution | G_groups 由运行期问题组决定（repair_scenes 已冻结但组数未定） | 问题组数量在 enqueue 前冻结（Phase 0 化）或分批授权 |
| world.alias_relations.extract / world_alias_relation_extraction | 未显式 `scene_ids` 时章节范围内 Scene 数量只能在 handler 准备阶段确定，领取前无法冻结 A；不使用通用临时额度 | ①提交阶段完成零 provider 的 Scene manifest 并冻结 S；或 ②按章节/Scene 分批授权；之后恢复 W3-B 迁移 |
| map_atlas_generate（world.map_atlas.plan + 图片 generate/edit） | plan 路径 focused 检索分页 n 无常量上界（W0-B 存疑 1）；图片 possible-charge 语义要求在活动信封下重放仍受确认闸门保护 | ①n 的领域上界或分批授权；②声明 root 后图片 hook 生效（代码已由 W3-B 接好，声明即启用） |
| smart_dedup_scan（world.entity_fusion + story.structure_dedup 跨能力宿主） | 一个 task 真实跨两个业务 capability，无 canonical parent；step capability 归属会触发身份拒绝 | 裁决 canonical parent（如新建 project.dedup 宿主能力）或拆分任务；不得伪装 infrastructure.* |

## 3. 非目标（不建信封，维持现状）

embedding（rag_index_chapter/rag_reindex_novel/rag_retry_embeddings、本地 BGE）、健康检查、账户连接验证、离线 eval CLI、历史回填（既定首轮非目标）；world_bible_projection_refresh、imports_completion_review、rag_reannotate_entities（确定性，无 provider 请求）；两个存储清理 task。

## 4. 迁移后的统一行为

- 声明任务由 worker 在首次领取时建立信封：L0 与 deadline 从注册 resolver 冻结；恢复（auto_requeue/stale/manual resume）累计同一 run，不重置额度、不移动 deadline。
- 超过 L0：`AIRunBudgetExceededError` 失败关闭（不 requeue），保留给领域的作者续算路径（`authorize_additional_requests`，Wave 4/5 接 UI）。
- deadline 到期：reserve 拒绝 + 退避不再 sleep，保留原始错误类型。
- 旧在途任务（无信封且 attempt>1）标 `legacy_untracked`；首次领取的新任务从本 attempt 起完整跟踪。
