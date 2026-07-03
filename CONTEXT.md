# CONTEXT.md — AI 长篇小说结构化创作引擎 v2.0

领域术语表、概念关系图、状态流转。保持本文与 `docs/agents/domain.md` 一致。

## 1. 核心产物（Core Products）

系统产生结构化创作资产，而非直接生成完整正文。

| 中文概念 | 英文 | 数据表 | 职责 |
|---------|------|--------|------|
| 核心实体 | CoreEntity | `core_entities` | 世界对象主表。`entity_type` 区分 **character** / location / faction / item / concept / event / creature / skill / rule / secret / legend / resource / other。别名内联在 `aliases` JSONB |
| 人物 | Character | `characters` | `entity_id` FK→CoreEntity。存人物特有字段（role, personality, desire, fear, secret, weakness, stance, voice_style 等） |
| 人物知识 | CharacterKnowledge | `character_knowledge` | 某角色对某事物的了解程度（unknown / rumor / partial / full / false_belief） |
| 剧情线 | PlotThread | `plot_threads` | 主线/支线/隐藏线/关系线/反派线/伏笔线。含起止章节、表层目标、隐藏真相、读者/作者已知状态 |
| 篇章纲 | OutlineArc | `outline_arcs` | 小说卷/篇章结构。含 arc_goal, core_conflict, entry_hook, midpoint_turn, climax, result, next_hook |
| 章节卡 | ChapterCard | `chapter_cards` | 单章的 goal, main_conflict, emotional_point, plot_function, must_happen / must_not_happen |
| 场景卡 | Scene | `scenes` | 最小叙事单元。旧 `chapter_cards.scene_cards` JSONB 仅作历史兼容/冗余上下文，不是当前权威来源 |
| 伏笔计划 | ForeshadowingPlan | `foreshadowing_plans` | 埋点→加强→收束 三阶段。含 surface_meaning, hidden_meaning |
| 揭示计划 | RevealPlan | `reveal_plans` | 秘密的分阶段揭示。含 target 和 reveal_stages |
| 长期记忆 | Memory | `memory_events` / `memory_snapshots` / `delta_log` | 章节事件、时间性快照和结构化字段差分。memory 拥有 temporal delta/snapshot 与 delta ingestion；world 拥有 canonical state assembly |
| 正文草稿 | WritingDraft | `writing_drafts` | 人工写作的章节正文。支持 version_number 递增的多版本管理 |
| RAG 分块 | RagChunk | `rag_chunks` | 正文分块 + embedding 向量 + 元信息标注（entity_ids, character_ids, thread_ids） |
| 事件 | Event | `core_entities` (entity_type="event") | 小说时间线事件。timeline_order 存于 content_json |
| 导入记录 | ImportRecord | `import_records` | 小说文件导入跟踪。不存原文 |
| 候选创作资产 | Candidate Creative Asset | 多表状态表达 | AI 或系统从正文中提取出的、具备长期维护价值但尚未被用户确认的结构化资产。可对应 CoreEntity、Relation、Alias、Event、Scene、PlotThread 等对象；默认进入 candidate 或等价待确认状态，可进入工作上下文但不进入正史上下文 |
| ~~候选实体~~ | ~~EntityCandidate~~ | ~~`entity_candidates`~~ | 已废弃。候选对象不再使用独立候选表，改由对应资产表的状态与自动入库元数据表达 |
| 关系 | EntityRelation | `entity_relations` | 实体间关系（人物、势力、对象、通用）。source_id/target_id 为 UUID hex 字符串 |
| 修订快照 | EntityRevision | `entity_revisions` | CoreEntity 的编辑历史快照，支持 rollback |
| 空间连续性地图 | Spatial Continuity Map | `map_*` | 写作伴随的空间连续性工具，用于表达 Scene 中地点、人物/事件位置、势力范围和相邻 Scene 的移动合理性。它是作者校对空间事实的辅助资产，不是自动推演、战棋模拟或地图美术系统 |
| Scene 级空间连续性 | Scene Spatial Continuity | `scenes` + `map_*` | 单个 Scene 及其相邻 Scene 之间的空间事实一致性，包括主地点、在场人物/事件、所属势力范围和移动跳变是否合理。第一版只提供轻提示，不阻断写作、发布或 AI 生成；它优先服务写作时的事实校对，不替代剧情因果、时间线或路线规划 |
| 空间连续性提示 | Spatial Continuity Hint | `scenes` + `map_*` | 面向作者的非阻断提示，用于指出 Scene 空间事实缺失或可疑跳变。第一版只基于结构化地图事实，不读正文、不调用 LLM、不推断未记录位置；只覆盖缺少主地点、缺少地图上下文和人物跨地图；主入口在写作页 Scene 面板，地图页用于展开查看和修正 |
| 创作工作流 Agent | Creative Workflow Agent | 跨模块概念 | 面向长篇小说创作任务的受控 AI 执行层。它不是通用自治多 Agent 平台；agent 化的目的不是追求自由自治，而是借鉴 Claude Code 关于工具调用、上下文超限、schema 容错、任务恢复和可验证执行的工程处理方式。它围绕创作工作流提供工具注册、权限门、上下文/记忆管理和可验证任务循环，多 Agent 只作为受控的内部执行策略。第一阶段服务系统内部长流程任务，如深度导入、Scene 整理、世界对象抽取、剧情结构分析和写作前上下文准备；用户看到任务计划、权限确认、进度、证据和可回滚结果，而不是泛用自由对话 agent。默认只能写入 draft / candidate / pending 等待确认资产；canonical 必须由用户确认后产生。Agent 工具只能通过现有模块稳定接口、service 编排入口或明确 DI port 执行业务动作，不直接暴露底层数据库、任意文件系统或任意代码执行 |
| Agent Harness | Agent Harness | 跨模块概念 | 支撑创作工作流 Agent 的横切执行底座，不是新的用户可见创作资产。第一阶段优先覆盖工具调用协议、上下文管理、LLM 输出容错和任务循环可观测性；目标是让现有深度导入、Scene 整理、世界对象抽取和结构分析更稳定、更可恢复、更可验证，而不是先增加新 UI 或新多 Agent 协调器。第一阶段以 imports 深度导入作为试验场，第一条竖切线是 Phase 0/1 Scene 提取；第一版代码应留在 `backend/modules/imports/` 内部（如 `managed_llm_step.py` 或 `agent_step_harness.py`），不先创建 `modules/agent`。在真实 LLM 长流程中验证 harness pattern 且 Phase 0/1、Phase 2 形成稳定复用后，再决定是否抽到共享 `backend/infrastructure/agent/` |
| LLM 供应商配置 | LLM Provider Profile | `projects.settings["llm"]` | 项目级 LLM 供应商配置，采用 OpenAI-compatible 形状表达 api_key、base_url、model 和常用生成参数。系统提供国内外供应商模板用于预填，包括 DeepSeek、Kimi、通义千问/阿里云百炼、智谱、百川、MiniMax、腾讯混元、百度千帆、阶跃星辰、零一万物、硅基流动、火山方舟和自定义 OpenAI-compatible 网关；模板只是可编辑默认值，用户选择后仍可调整 Base URL、模型、timeout、max_tokens、temperature、top_p 和供应商扩展 JSON。Agent Harness 不硬编码供应商。业务 LLM 调用以项目级配置为权威来源；环境变量只作为未配置项目的 fallback、本机开发和真实 LLM 验收 override。每次长流程运行应记录脱敏后的 effective provider/model/host/timeout/参数摘要和字段来源（project/env/test_override/default） |
| LLM Step Harness | LLM Step Harness | 跨模块概念 | Agent Harness 第一阶段的最小交付物，用于包住现有 Phase 0 / Phase 1a / Phase 1b LLM 调用，而不是重写深度导入 workflow 编排。它统一处理输入上下文预算、LLM timeout / retry / total watchdog、schema validate / repair / degraded fallback、step 级 JSONL / timeline / checkpoint 诊断，以及 step 的只读/写入、权限级别和可重跑粒度定义。Phase 0/1 的上下文超限治理采用五层链路：step input budget、tool/context result budget、snip、microcompact/collapse、autocompact fallback；任何裁剪或压缩都必须写入 degraded diagnostics，且压缩摘要只作为 working context，不产生正史事实 |
| 受控 LLM 步骤 | Managed LLM Step | 跨模块概念 | 介于主创作工作流 Agent 和普通工具调用之间的确定性 LLM 执行单元，适用于 Phase 0 / Phase 1a / Phase 1b。它比普通 tool call 更重，包含 prompt 构造、上下文预算、LLM 调用、schema 守门、retry、degraded fallback 和 journal；但比 subagent 更轻，不自主规划、不选择下一步、不长期持有记忆、不递归启动 agent、不拥有 workflow。主 orchestrator 仍负责调度、并发、合并、降级和写库 |
| Step/Tool Envelope | Step/Tool Envelope | 跨模块概念 | Agent Harness 对单个确定性执行单元的统一描述和结果包，借鉴 Claude Code 的 `ToolDef` / ToolStart / ToolEnd 思路，但第一阶段不让 LLM 自主选择下一步。每个 envelope 至少声明 name、input_schema、output_schema、permission_level、read_only、concurrent_safe、timeout、retry_policy、context_budget 和 output_guard；每次执行记录 call_id、started_at、elapsed_ms、attempts、input_hash、output_hash、token_budget、error_kind、degraded_reason 和 quality_stats。Phase 0/1 的 `phase0_prefetch`、`phase1a_reinforce`、`phase1b_fusion` 是 Managed LLM Step；Workflow Read、Novel Text Search / Read 是只读工具。二者都应逐步收敛到该 envelope；workflow 顺序暂时仍由现有 orchestrator 决定 |
| Agent Run Journal | Agent Run Journal | 跨模块概念 | 创作工作流 Agent 的追加式运行日志，用于把 Step/Tool Envelope 的关键执行事件持续落盘，借鉴 Claude Code 先写 transcript 再进入长模型请求的恢复思路。第一版不新增数据库表，复用 async task result、phase_timeline、checkpoints、quality_stats 和真实 LLM JSONL；每条事件记录 workflow_id、run_id、call_id、envelope_name、phase、event_type、started_at、elapsed_ms、attempts、input_hash、output_hash、error_kind、degraded_reason、checkpoint_ref 和 quality_stats。它只服务诊断、恢复、验收和调参，不作为用户创作资产；待 Phase 0/1 真实 60 章稳定后，再决定是否沉淀为正式表 |
| Step 输出守门 | Step Output Guard | 跨模块概念 | LLM Step Harness 对每个 LLM step 输出的确定性守门层，参考 Claude Code 的工具 schema / 结果 envelope 思路，但面向本项目的 Pydantic 业务 schema。它先做严格 schema 校验，并只允许确定安全的轻量归一化（如缺失列表归一为空列表、兼容字段别名）；解析失败或 schema 失败时最多进行 1 次有边界的 repair，repair 输入包含原始输出、目标 schema 摘要和校验错误；repair 后仍失败则记录 raw output hash、schema_errors、repair_attempts、error_kind、degraded_reason，并回退为可审计的空结果、上一阶段候选或局部 fallback。Step 输出守门不得把未通过 schema 的内容写入 canonical，也不得无限重试或静默吞错 |
| Workflow Read Tool | Workflow Read Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于读取 workflow 状态、task result、checkpoint、phase timeline、quality stats、phase errors 和诊断摘要。它不等同于任意数据库、任意文件或任意日志读取；输出必须受预算、截断和脱敏约束 |
| 小说正文搜索工具 | Novel Text Search Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于查找相关正文片段。第一版不新建第二套索引，而是在 imports 内部通过 adapter 优先调用 `modules.rag.facade.retrieve(...)`，把 `RagChunkContract` 转成 agent anchor；如果 RAG 无索引、embedding 失败或无命中，则降级为对 writing 最新草稿的有界关键词扫描，并记录 degraded reason。它负责返回 chapter_index、chunk_index、offset、scene_id、rag_chunk_id、短 snippet、匹配原因或 score，为后续精读定位候选材料；它不是把全文直接交给 LLM 的工具 |
| 小说正文读取工具 | Novel Text Read Tool | 跨模块概念 | 创作工作流 Agent 的只读内部工具，用于按 search anchor、rag_chunk_id、scene_id、chapter range 或 paragraph/offset range 读取精确正文片段。正文最高权威源是 `writing.facade.get_latest_draft_for_chapter()` 返回的最新章节草稿；RAG chunk text 只作为快速 fallback 或 stale offset 降级备援，避免索引过期时读错正文。Read 必须带范围；无范围读整章且超过预算时返回 context_overflow 并提示先 search 或缩小范围。所有结果都带 chapter_index、chunk_index、start_offset、end_offset、scene_id、rag_chunk_id 和 source_type anchor，并遵守上下文预算、snip 和 degraded diagnostics 规则 |
| Agent 权限阶梯 | Agent Trust Ladder | 跨模块概念 | 创作工作流 Agent 的权限模型，分为 Read、Suggest、Draft、Act with Confirmation、Autonomous。Read 只能读取受 novel_id 隔离、预算、截断和脱敏约束的工作流状态与正文片段；Suggest 只能生成候选计划或建议；Draft 可在用户启动的自动流程中写入 draft / candidate / pending 并保留 provenance、needs_review 和 rollback 信息；Act with Confirmation 包括 promote canonical、废弃已有资产、批量覆盖和合并实体，必须用户确认；第一阶段不开放 Autonomous |

## 2. 状态流转（Status Lifecycle）

遵循 **状态优先于删除**：业务运行时默认用 `status` 字段表达废弃/忽略/冲突。项目永久删除和 demo 开发库重建可以硬 DELETE。

```
                    ┌─→ ignored
draft → candidate ──┤
                    ├─→ canonical ──→ deprecated
                    ├─→ conflicted
                    └─→ pending (waiting for user)

异步任务:
pending → running → done / failed / cancelled
```

### 候选对象建议动作（CandidateAction）

```
create_new           — 创建新正史 CoreEntity
merge_with_existing  — 合并到已有实体
alias_of_existing    — 标记为已有实体的别名
ignore               — 忽略
temporary_only       — 仅临时场景
needs_user_decision  — 等待用户决策
```

### 重要性级别（ImportanceLevel）

```
core > important > normal > temporary > alias
```

实体抽取阈值：严格模式 ≥0.75，正常模式 ≥0.45。

## 3. 关键揭示层级（Reveal）

| 层级 | 含义 |
|------|------|
| author_only | 仅作者知道 |
| hinted | 已埋伏笔 |
| revealed | 已揭示给读者 |
| fully_known | 读者和角色都已知 |

人物知识层级：unknown → rumor → partial → full；特殊：false_belief（角色自认为知道但实际错误）。

## 4. 系统三层（Architecture Layers）

| 层 | 模块 | 说明 |
|---|------|------|
| **事实层** | `project`, `world`, `memory` | 小说的正史事实。world 拥有 CoreEntity + Character + Event + EntityRelation 以及 canonical state assembly；memory 拥有事件溯源、temporal snapshot 和 `delta_log` ingestion |
| **结构层** | `outline` | 把事实组织为可执行的剧情计划。PlotThread + OutlineArc + ChapterCard |
| **辅助层** | `rag`, `context`, `writing`, `imports` | 检索增强（RAG 分块）、上下文编译（跨模块组装 LLM context）、正文草稿承载、文件导入 |

模块通信：跨模块生产代码只能导入 `contracts.py`、`facade.py` 或 DI port。`api.py` 是 HTTP 入口，不作为模块间调用接口。Facade/API 不写复杂业务逻辑。

结构化差分边界：`delta_log` 归 memory 模块。deep import、world map 等模块需要记录
字段变化时，通过 `memory.facade.ingest_delta_events(...)` 或兼容 shim 委托 memory
完成 JSON 编码、provenance 合并和 row creation；world map 只接收已形成的 delta
event/delta_log 引用并组装地图候选观察，不拥有 memory provenance 拼装。

## 5. 关键流程约定（Key Conventions）

### 候选→正史（Candidate → Canonical）
默认流程：
1. AI 生成 → 入 candidate / proposal 状态
2. 用户审查（确认/编辑/忽略/合并）
3. 用户确认后 promote 为 canonical
4. 后台任务不在无用户授权的情况下自动 promote

例外：用户明确启动的自动流水线（如深度导入）可批量写入候选创作资产，但必须先通过 Pydantic schema 校验，并保留来源、可编辑/可回滚标记。

### 工作上下文（Working Context）
工作上下文是 AI 流水线内部使用的临时上下文层，用于长文档批量导入、后续结构分析和跨阶段抽取。它可以读取正史资产、草稿资产、候选创作资产、证据片段、置信度和来源依赖，但不等同于正史上下文。

- 长文档导入的第二轮/后续阶段可以基于候选创作资产继续抽取，避免等待用户逐条确认后才推进剧情线、篇章纲、关系和伏笔分析
- 工作上下文中的候选资产只能作为待确认依据，不作为用户确认后的硬事实
- 由候选资产派生的 PlotThread、OutlineArc、EntityRelation、ForeshadowingPlan、RevealPlan 等下游资产必须保持 draft / candidate / pending 等待确认状态
- 深度导入中基于待确认世界对象生成的 EntityRelation 和 Alias 也是待确认世界对象证据；它们可以参与后续 working context，但在用户确认前不应被视为正史事实
- 下游资产必须记录来源依赖；当依赖的候选资产被拒绝、合并或改名时，下游资产需要标记为需复核或重新计算
- 面向正式写作、最终一致性校验和用户确认后的输出时，应使用正史上下文，而不是直接使用未确认的工作上下文

实现方向：
1. 近期：在上下文编译入口提供显式模式（如 `context_mode="canonical" | "working"`）。默认使用 canonical；深度导入、批量抽取和结构分析等内部流水线显式请求 working。
2. Deep import snapshot v1：深度导入 Phase 2/Phase 3 的真实 LLM 调用会写入 `context_snapshots`，记录 task_id、workflow_id、phase、context_mode、included_asset_ids、摘要、prompt_hash、token/section metadata、result_refs、created_at，用于审计、复现和问题定位。
3. 持久化快照只记录当次 AI 调用使用过的上下文视图，不替代正史资产表，也不改变 candidate → canonical 的用户确认语义。
4. `context_snapshots` 默认不保存完整 rendered context；只保存摘要、资产 ID、hash 和 metadata。调用方显式启用 `retain_rendered_context=true` 时才保存完整上下文，并按保留策略清理 `rendered_context` 字段，不删除快照行和 provenance metadata。
5. Snapshot lifecycle v1：context 模块提供 `snapshot_health_summary` 聚合和显式 maintenance API，默认 dry-run；超时 running 快照标为 `failed/stale_running`，full context 清理只清正文和过期时间。
6. 手动 AI 操作应先创建 AI 参考资料确认记录，再把 `context_confirmation_id` 传给正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象等接口。手动 AI 第一版继续使用 `context_confirmations`；后续可在快照表稳定后迁移或补充回放入口。
7. `/api/context/confirm` 负责按用户当前选择重新编译上下文并创建确认记录，而不是只保存前端已预览结果；这样可以避免预览与最终执行之间的数据漂移。

用户控制边界：
- 正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象必须先展示并确认“AI 参考资料”，再执行 LLM 调用
- 深度导入不插入手动上下文确认；它保持自动化体验，由系统内部维护 working context，并在完成后集中展示结果、降级原因和待复核资产
- 上下文页保留为高级预览/调试台；手动 AI 操作应在自身流程中打开参考资料确认界面，而不是要求用户跳转到上下文页

“AI 参考资料”第一版可控项：
- 章节/Scene 范围
- 揭示模式（作者安全、作者全知、读者已知、角色视角）
- 是否包含待确认对象（内部状态为 candidate 的候选创作资产）
- 排除本次不想引用的世界对象、人物、剧情线、伏笔
- 本次 AI 额外注意事项

“AI 参考资料”弹窗编辑规则：
- 弹窗内编辑的是参考资料选择规则和本次补充说明，不直接编辑编译后的 Markdown 上下文正文
- 用户调整范围、揭示模式、是否包含待确认对象或排除资产后，通过“重新整理参考资料”重新调用上下文编译并刷新预览
- 如用户发现结构化资产本身错误，应跳转或弹出对应资产编辑表单；保存后再重新整理参考资料
- “本次 AI 额外注意事项”可作为临时高优先级上下文参与本次调用，并记录到 `_meta.user_note`，但不写入正史资产
- 第一版不支持手动粘贴/改写完整上下文 Markdown，避免产生脱离结构化资产体系的临时事实

用户可见文案应使用“待确认对象”，不直接暴露“候选资产 / candidate asset”等工程术语；代码、数据库和文档中的领域术语仍可使用 candidate / 候选创作资产。

待确认对象默认值：
- 正文生成默认不包含待确认对象
- 手动剧情分析、手动剧情结构生成、手动补抽世界对象默认包含待确认对象，并在界面提示“包含待确认对象，结果需复核”
- 深度导入内部自动使用待确认对象推进后续阶段，但不打断用户逐步确认

待确认对象变更后的影响处理：
- 第一版只标记受影响结果，不自动级联重算或覆盖用户已编辑内容
- 当生成结果或任务 `_meta.included_asset_ids` 引用了被忽略、合并、改名或提升的待确认对象时，相关结果应标记为 `needs_review` 或 `stale_context`
- `ready` 表示当前参考资料仍有效；`needs_review` 表示结果依赖待确认对象，需要用户复核；`stale_context` 表示依赖对象已发生结构性变化，建议重新分析或重新生成
- 用户可手动触发“用当前 AI 参考资料重新分析/重新生成”

### 实体抽取（Entity Extraction）
- **不是 NER**。不抽取路人、普通道具、代词、一次性场景元素
- 只识别值得长期维护的**创作资产**
- 深度导入等用户确认启动的抽取结果默认作为候选创作资产入库，`content_json._meta` 记录自动入库元数据；用户确认后再提升为正史

### 深度导入 Scene 预取（Deep Import Scene Prefetch）
- Scene 预取是深度导入正式 Scene 切分前的机会主义加速层，用于并发请求 LLM 获取 batch 级候选切分结果；batch 是现有 Scene 切分批次的别名，不是新的领域对象
- 预取结果默认不等同于正式 Scene。只有通过提交门（Commit Gate）的高质量结果，才可按顺序写入 `draft Scene`
- 提交门是确定性质量边界，而不是 LLM 自评；它至少要求 schema 校验通过、章节范围匹配、来源 hash 匹配、章节引用合法且覆盖目标章节
- Phase 0 结果分为高质量候选和低质量参考：通过提交门的结果进入高质量候选，Phase 1a 可强参考；未通过提交门但 schema 可解析的结果进入低质量参考，Phase 1a 可参考但可重写；schema 不可解析或空结果只记录失败，不进入参考
- 未通过提交门的预取结果只能作为正式 Phase 1 的参考材料，与原文一起提供给 LLM；正式 Phase 1 可以重写这些低质量结果
- 通过提交门的预取结果进入可写候选集合，但在正式写库前仍可由 Phase 1b 自动整理；已写入正式 `Scene` 表后的 Scene 不应被后台静默覆盖，如需改写，应走显式重新导入或用户编辑路径
- 预取结果只作为本次异步任务的中间状态持久化，不升格为长期业务资产；它可进入任务结果或 workflow 中间结果，用于恢复、审计和后续 Phase 1 参考
- Scene 预取同时承担真实 LLM API 稳定性探针职责；Phase 0 只在两轮预取最终 422 错误率超过 40% 时阻断深度导入，超时、空结果和 schema 失败进入诊断与质量统计，不单独作为 Phase 0 阻断条件
- 因 API 稳定性阻断时，用户可见提示应推荐切换更稳定的官方 API，例如：“推荐使用官方 API 以保障稳定性与质量（强推 DeepSeek-v4-flash，质量高、价格低、并发超快）”
- 正式 Phase 1a 可并发补强两轮预取中的可解析 batch，默认并发 50；Round A / Round B 的每个 batch 分别带正文补强，不在 Phase 1a 合并相交结果。补强输出仍是中间候选，不预先拥有正式输出权。Phase 1a 对 422、网络错误和 timeout 允许 1 次 retry，schema 解析失败、空结果或质量不过提交门不 retry；最终 422 错误率单独统计，超过 40% 时阻断深度导入并提示 API 通道不稳定。相邻参考只取章节意义上的前后 batch（按 `batch_index` / 章节范围），不能使用 LLM 返回完成时间作为叙事顺序
- 通过提交门的高质量预取结果也应等待正式 Phase 1 的顺序归并器统一写库；提交门决定“可写”，顺序归并器负责“何时写、以什么 `scene_index` 写”
- 深度导入允许在正式写库前自动整理中间 Scene 候选，包括融合、切分、重排和保留重叠 Scene；自动整理只作用于本次 workflow 中间结果，不直接删除或覆盖已写入的正式 Scene
- Scene 预取可采用双轮错位批次：第一轮默认 5 章窗口按起始章节顺序分批（如 1-5、6-10），第二轮默认从第 3 章开始偏移后再按 5 章分批（如 3-7、8-12），不额外补书首边界，书尾不足 5 章时允许短 batch；两轮结果地位平等，都是 Scene 候选观察，用于降低固定 batch 边界截断 Scene 的风险，最终正式输出权由 Phase 1b 自动 fusion / reducer 决定
- Phase 0 是机会主义预取层，一般失败不阻断正式 Phase 1；每个预取 batch 对 422、网络错误和 timeout 允许 1 次 retry。若 retry 后该 batch 最终仍为 422，则计入 422 错误率；schema 解析失败、空结果或质量不过提交门不触发 Phase 0 retry。当 Phase 0 两轮预取的最终 422 错误率超过 40% 时，应阻断深度导入并提示 API 通道质量不稳定。422 错误率以两轮预取 batch 数为分母，不按章节数、成功 batch 数或实际请求次数计算；初次失败和 retry 情况应记录到 workflow 诊断信息。用户提示建议为：“推荐使用官方 API 以保障稳定性与质量（强推 DeepSeek-v4-flash，质量高价格低并发超快！）”
- Phase 0 的 LLM 超时时间默认与正式 Phase 1a 流程一致，因为二者输入的正文规模一致；Phase 0 的定位差异体现在并发、暂存和降级策略，而不是更短的请求时间预算
- 正式 Phase 1 分为带正文质量补强和无正文自动整理：Phase 1a 使用正文和两轮预取 Scene 结果补强每个 batch 的 Scene 质量，产出两轮平等候选；Phase 1b 不带正文，只基于补强后的两轮候选做自动融合、切分、重排和生成整理提示，再交由顺序归并器写入正式 Scene
- Phase 1b 自动整理后的 Scene 数量可以多于或少于 Phase 1a；数量变化本身不是错误，但输出必须覆盖目标章节，并保留可追溯到 Phase 1a Scene 和章节来源的依赖信息
- Phase 1b 自动整理可以生成或改写最终 Scene 的标题、目标、核心冲突、情绪节拍和叙事标签等展示字段；但必须保留来源章节和 scene_chunks，不能生成脱离来源的漂亮摘要
- Phase 1b 可以调整 `scene_chunks.start_paragraph`，但只能基于 Phase 1a 候选、证据锚点或已有范围校正；没有可靠锚点时应保守沿用来源候选值或 0，并标记边界不确定，不能凭空发明精确段落
- Phase 1b 可以丢弃尚未写入正式表的 Phase 1a 中间候选；丢弃必须记录原因，如已融合、已拆分、重复候选、低置信不可用或超出目标范围。丢弃中间候选不等同于删除用户资产
- Phase 1b 自动整理失败时应按 Scene / 候选粒度降级：成功整理的输出继续使用，失败、无效或缺失覆盖的局部结果回退到对应 Phase 1a 补强候选；不应因为少数 Scene 整理失败而整批回退
- Phase 1b 对 422、网络错误和 timeout 允许 1 次 retry，schema 解析失败或空结果不 retry；最终 422 错误率也单独统计，超过 40% 时不阻断整个深度导入，而是放弃 Phase 1b 自动整理结果，降级为 Phase 1a 候选顺序写库并标记 degraded；用户提示应说明自动整理失败，已使用质量补强结果继续导入，并建议切换官方 API 提高整理质量
- 每个 Phase 1b 输出 Scene 必须声明来源和操作类型，包括来源候选 ID、来源章节、整理操作（kept / merged / split / reordered / rewritten）、置信度和是否需要回退；未被任何 Phase 1b 输出引用且没有明确丢弃原因的 Phase 1a 候选应回退写入，避免内容丢失
- Phase 1b 自动整理按章节窗口分段执行，不做全书一次性整理；默认窗口 30 章、窗口 overlap 3 章、并发 4。Phase 1b 输出允许在窗口 overlap 覆盖范围内跨窗口边界形成连续 Scene，但不能越权覆盖远超当前窗口范围的章节。窗口 overlap 区域若多个窗口覆盖同一来源候选，优先采用该候选主要章节所在 core range 的主窗口输出；非主窗口输出只作为边界参考或 fallback。最终由顺序归并器按章节顺序合并窗口输出并应用候选覆盖 / 回退规则
- 最终写入 `Scene` 表时应保留自动整理 provenance，但不新增业务表；优先放入现有可承载元数据的 JSON 字段，记录自动入库标记、workflow_id、生成阶段（如 phase1b_fusion / phase1a_fallback）、来源候选 ID、来源轮次、来源章节、融合/切分/重写操作、置信度和可选降级原因；若边界不确定，还应记录 boundary_status、boundary_reason、needs_review 和 review_reason，供后续 Scene 整理界面提示复核
- 深度导入前端进度条周围应展示阶段质量统计和降级信息，包括 Phase 0 两轮请求数、成功数、422 率、timeout 数、schema 失败数，Phase 1a 成功数、fallback 数、422 率，Phase 1b 自动整理窗口数、成功窗口数、降级窗口数、422 率，最终写入 Scene 数、needs_review Scene 数和是否使用 phase1a_fallback；这些信息应随 workflow 进度更新，而不是只在任务结束后展示
- 深度导入前端除主进度条外，应动态显示当前处理位置，包括当前章节范围、当前章节和当前 Scene / 候选 / 整理窗口；主进度条和当前处理提示应有克制的光效或流动状态，用于表达任务正在推进，避免用户误判为卡死
- 当前处理位置和质量统计应持续写入异步任务 result，刷新页面后可恢复展示；建议记录 current_phase、current_round、current_chapter_range、current_chapter、current_scene_candidate_id、current_window、current_operation 和 quality_stats
- 深度导入任务应支持从中断处恢复，但继续执行需用户明确确认：worker 启动时触发一次中断任务检测，运行中循环检测 stale / interrupted deep_import 任务并将状态写入 task result / 可查询状态；前端发现可恢复任务时提示用户“检测到上次深度导入中断，可从当前阶段继续”，用户点击继续后才恢复原 deep_import 任务并复用 async task result 中的 checkpoint。恢复后继续展示阶段、章节、候选、窗口和质量统计
- 用户确认继续中断任务时，应复用原 deep_import task，将原 task 恢复为可领取状态（如 pending），不新建 recovery task；这样 localStorage 中的 task_id、workflow_id、checkpoint 和 provenance 保持稳定
- 中断恢复第一版不新增任务状态枚举；保持现有 pending / running / done / failed / cancelled 体系。检测到 stale running deep_import 时，在 task result / meta 中标记 interrupted、recoverable、interrupted_at、last_heartbeat_at、recovery_required 等恢复信息；用户确认继续后再将原 task 改回 pending
- 用户也可选择放弃恢复；放弃恢复是破坏性清理操作，前端必须先警告会清理本次 workflow 已写入的派生 Scene / 自动实体 / 关系 / delta 等结果。用户确认后，系统按 workflow_id / provenance 清理本次中断导入已写入的派生资产，并将原 task 标记 cancelled；默认将已暴露的派生资产标记 deprecated，只有纯中间且未暴露资产才可硬删除；不得删除用户编辑过、canonical 或不属于该 workflow 的资产
- 用户点击继续恢复前，应展示 checkpoint 摘要，包括上次中断阶段、已完成章节 / 窗口 / Scene、已写入 Scene 数、已抽取世界对象数、将重跑的最小范围，以及是否存在 deprecated / 冲突 / needs_review 资产
- 中断恢复允许按阶段粒度局部重跑：Phase 0 按 batch，Phase 1a 按 batch，Phase 1b 按窗口，Scene commit 按 Scene / provenance 补写且不得整批重复写，Phase 2 世界对象抽取按 Scene，Phase 3 结构分析可整阶段重跑
- Scene commit 阶段应使用稳定 provenance_key 做幂等判断；provenance_key 由 workflow_id、source_candidate_ids、fusion_operation 和 source_chapter_indices 等来源信息生成并写入 Scene meta。恢复时若同 provenance_key 的 Scene 已存在则跳过，缺失则补写，已存在但 status 为 deprecated 时不自动复活，应记录冲突并标记 needs_review / fallback
- Phase 2 世界对象抽取应按 Scene 记录 checkpoint，包含 scene_id、scene_provenance_key、状态、创建的实体 / 关系 / delta ID、错误类型和 retry 次数。恢复时已成功 Scene 跳过，failed / stale Scene 局部重跑；若已成功抽取的实体后来被用户 deprecated，不自动复活，应标记 needs_review
- Phase 3 结构分析恢复时可整阶段重跑；重跑前只将同 workflow_id 且 source=deep_import 的自动生成结构资产标记 deprecated，再写入新的 draft / candidate 结构结果。用户编辑过、canonical 或不属于该 workflow 的结构资产不应被自动覆盖
- Phase 1a 可使用扩展的中间 schema，记录边界状态、证据锚点、融合建议、拆分建议、置信度和缺失/不确定项；这些增强字段只保存在本次 workflow 中间结果中，不写入正式 `Scene` 表

### 手动 Scene 融合（Manual Scene Fusion）
- 手动 Scene 融合是作者整理 Scene 时的显式操作：用户选择多个已有 Scene，请求 LLM 生成一个融合后的新 Scene
- 融合操作不应静默覆盖原 Scene；融合结果出来后，由用户选择后续动作：保留原 Scene 并保存融合 Scene、保存融合 Scene 并将原 Scene 标记为 `deprecated`、放弃融合结果、继续编辑融合结果后再保存
- 保存的融合结果默认创建新的 `draft Scene`，并记录来源 Scene 依赖；原 Scene 只在用户明确选择时才标记为 `deprecated`
- 融合后的新 Scene 必须继续保留章节来源、scene_chunks 和可编辑字段，不能只保存 LLM 摘要
- 手动融合是导入后的作者整理工具，与深度导入写库前的自动整理并存；它要求用户明确选择输入 Scene，不由后台任务静默触发

### 创作资产整理筛选（Creative Asset Triage Filters）
- Scene、世界对象和相关派生资产的管理界面应支持按状态、标签和导入标记筛选，方便用户快速整理深度导入结果
- 基础筛选至少包括 status（draft / candidate / canonical / deprecated / ignored / conflicted / pending）、needs_review、boundary_status、review_reason、source=deep_import、workflow_id、自动入库标记、实体类型和章节范围
- 管理界面应能快速定位 deprecated、needs_review、边界不确定、phase1a_fallback、phase1b_fusion、恢复冲突和用户待确认对象
- 大数据量导入后，筛选应优先由后端 API 查询参数支持，并配合分页；前端可做轻量二次过滤和状态呈现，但不应依赖全量拉取后本地筛选
- 筛选只改变管理视图，不隐式修改资产状态；批量废弃、恢复、融合、忽略或提升为正史都必须是显式用户操作

### novel_id 隔离（Project Isolation）
- 所有 API 在 service 层强制项目隔离
- 不跨 novel_id 合并关系、别名或正史对象
- BaseCRUDService 通过 keyword-only `novel_id` 参数强制该约束

### 别名管理（Aliases）
- 别名统一存储在 `core_entities.aliases` JSONB
- 标记为 `alias_of_existing` 而非创建新实体
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入目标对象 aliases，单条别名保留 source、workflow_id、scene_id、confidence、quote、needs_review 等来源元数据
- 别名类型：name / title / nickname / alias / translation / abbreviation

### 嵌入与向量（Embedding）
- 向量字段在 PostgreSQL 用 pgvector，在 SQLite 测试模式存 JSON 序列化文本
- embedding 失败不阻塞索引（chunk 仍创建，检索退化到纯文本）

### 文件导入（Import）
- 白名单格式：.txt / .epub / .html / .htm / .mobi / .azw3
- 文件限制 ≤50MB
- 不信任上传文件名（os.path.basename 保护）
- 不把原文存入 import_records

## 6. 核心枚举速查（Key Enums Reference）

详见 `shared/enums.py`。以下是关键枚举值：

| 枚举 | 值 |
|------|-----|
| ObjectStatus | draft, candidate, canonical, deprecated, ignored, conflicted, pending |
| EntityType | character, location, faction, item, concept, event, creature, skill, rule, power_system, secret, legend, resource, other |
| ImportanceLevel | core, important, normal, temporary, alias |
| RevealLevel | author_only, hinted, revealed, fully_known |
| KnowledgeLevel | unknown, rumor, partial, full, false_belief |
| CharacterRole | protagonist, antagonist, supporting, minor, mentor, love_interest, comic_relief, foil, narrator, cameo |
| Visibility | author_only, author_safe, reader_known, public |
| TaskStatus | pending, running, done, failed, cancelled |
| RelationType | parent_of, child_of, spouse_of, sibling_of, friend_of, rival_of, enemy_of, ally_of, mentor_of, student_of, lover_of, master_of, servant_of, member_of, leader_of, allied_with, at_war_with, trading_with, belongs_to, created_by, located_at, contains, controls, related_to, opposes, supports |
| ForeshadowingStatus | planned, seeded, reinforced, paid_off, abandoned |

## 7. AI 创作提示（Prompts）

系统使用 **8 个 prompt**（非复杂多 Agent）：

| Prompt | 用途 |
|--------|------|
| `structure_world_character.md` | 世界与人物结构生成 |
| `structure_plot.md` | 剧情结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 |
| `structure_review_memory.md` | 结构复查与状态抽取 |
| `structure_extraction.md` | 从章节正文抽取世界对象候选 |
| `extract_chapter_scene.md` | 从正文提取章节卡字段 |
| `extract_character.md` | 从正文提取人物档案字段 |
| `scene_segmentation.md` | 深度导入中的 Scene 切分 |

所有 prompt 通过 `infrastructure/llm/prompt_loader.py` 从 `backend/prompts/` 加载。

Prompt 合并策略：一次 prompt 输出多个 JSON 数组，入库时分别写入对应表。不按数据库表拆 prompt。

## 8. 技术栈概览（Tech Stack）

| 层 | 技术 |
|----|------|
| 后端 | Python 3.13 + FastAPI + async SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL 17 + pgvector + pg_trgm |
| LLM | OpenAI 兼容 API（支持结构化输出 response_format） |
| 任务队列 | PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED） |
| 前端 | Vanilla JS + CSS 变量 + Proxy 响应式状态 |
| 测试 | pytest + pytest-asyncio + SQLite 内存引擎 |
| 容器 | Docker Compose（PostgreSQL 17 + pgvector） |

## 9. 相关文档索引（Document Index）

| 文档 | 内容 |
|------|------|
| `docs/00_整体设计.md` | 系统三层结构、模块职责、目录结构 |
| `docs/01_数据库设计.md` | 活跃表完整字段定义（已移除废弃模块表） |
| `AGENTS.md` | AI agent 禁止事项、命令速查、命名规范 |
| `development-guide.md` | 开发命令、模块开发规则 |
| `testing-guide.md` | 测试约定（unit/integration/e2e） |
| `docs/adr/` | 架构决策记录 |
| `shared/enums.py` | 完整枚举定义 |
| `shared/constants.py` | 全局常量（分页/阈值/权重） |
| `modules/world/CLAUDE.md` | world 模块禁止事项 |
| `modules/imports/CLAUDE.md` | imports 模块禁止事项 |
