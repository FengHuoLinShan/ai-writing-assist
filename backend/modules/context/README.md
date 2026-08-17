# Module: context / 上下文编译模块

## 定位

context 模块决定本次 AI 操作能看到哪些资料、哪些资料要被裁剪，以及哪些确认记录需要在资产变化后标脏。

RAG 负责“找”，context 负责“选、裁、确认、追踪”。

## 职责

- 按需聚合 `project / world / memory / outline / rag`
- 基于 `scope`、`scene_id`、`budget_tokens`、`reveal_mode` 进行裁剪
- 输出兼容 bundle 或分层 `CompiledContext`
- 手动 AI 操作前创建 `context_confirmations`
- 为自动 AI 流水线创建 `context_snapshots` 审计记录
- 在任务完成后把结果引用回写到确认记录
- 在资产变化后把历史确认记录标记为 stale
- 为前端 AI 参考资料审查台返回 section 元数据、激活原因、来源摘要和预算裁剪事件
- 为作者生成按需加载 `world_bible_synopsis`，并把实际 revision/source/block hash 写入
  编译结果、确认记录和生成响应 provenance
- 管理版本化 Activation Profile，用受限匹配规则把固定世界书页面/CoreEntity 编译为
  可解释、可预算裁剪的 P1 参考资料
- 为 `world.map_atlas.generate` operation 编译 author-full canonical 背景；只在作者显式开启时加入工作稿

## 不负责

- 不直接执行 LLM 调用
- 不直接做 RAG 检索算法
- 不做剧情推理
- 不默认保存完整 Markdown；完整 `rendered_context` 只能由调用方显式开启并受保留策略清理
- 不让用户直接编辑最终 prompt；用户确认的是结构化参考资料清单

## 核心 facade

所有项目级 context API（编译、渲染、确认、证据检索/回读、trace、
快照查询与维护）都在业务操作前通过 project facade 校验活跃项目。
不存在和已进入回收站的项目统一返回 404，不返回 confirmation、trace
或 snapshot 元数据。

```python
async def compile_structure_context(...) -> StructureContextBundle
async def compile_with_tiers(...) -> CompiledContext
async def render_compiled_context_markdown(...) -> str
async def compile_generation_background(...) -> dict
async def confirm_context(...) -> ContextConfirmationContract
async def require_confirmation(...) -> ContextConfirmationContract
async def require_fresh_confirmation(...) -> ContextConfirmationContract
async def prepare_confirmed_ai_action(..., for_update=False) -> ConfirmedAIActionContext
async def attach_result_ref(...) -> ContextConfirmationContract
async def mark_asset_context_changed(...) -> int
async def open_context_snapshot(db, request: ContextSnapshotRequest) -> ContextSnapshotContract
async def succeed_context_snapshot(...) -> ContextSnapshotContract
async def fail_context_snapshot(...) -> ContextSnapshotContract
async def open_generation_context_snapshot(db, request: ContextSnapshotRequest) -> ContextSnapshotContract
async def succeed_generation_context_snapshot(...) -> ContextSnapshotContract
async def fail_generation_context_snapshot(...) -> ContextSnapshotContract
async def build_snapshot_health_summary(...) -> dict
async def mark_stale_running_snapshots(...) -> int
async def prune_rendered_context(...) -> int
async def run_snapshot_maintenance(...) -> dict
async def list_retrieval_traces(...) -> list[ContextRetrievalTraceContract]
async def get_evidence_health(...) -> EvidenceHealthContract
async def retrieve_planned_context_evidence(...) -> StructureContextBundle
def compile_author_question_evidence(...) -> dict
async def grep_novel_evidence(...) -> dict
async def search_novel_evidence(...) -> dict
async def read_novel_evidence(...) -> dict
async def inspect_novel_target(...) -> dict
async def trace_novel_evidence(...) -> dict
async def record_evidence_link(...) -> EvidenceLinkContract
async def list_activation_profiles(...) -> list
async def create_activation_profile(...) -> ContextActivationProfileResponse
async def update_activation_profile(...) -> ContextActivationProfileResponse
async def publish_activation_profile(...) -> ContextActivationProfileResponse
async def list_activation_profile_revisions(...) -> list
async def restore_activation_profile_revision(...) -> ContextActivationProfileResponse
async def resolve_activation_profile(...) -> dict | None
async def preview_activation_profile(...) -> dict
```

`create_context_snapshot()`、`mark_context_snapshot_succeeded()` 和
`mark_context_snapshot_failed()` 保留为兼容 wrapper；新生产调用应使用
`ContextSnapshotRequest` + `open/succeed/fail` 生命周期入口。

## 数据表

| 表 | 说明 |
|----|------|
| `context_confirmations` | AI 参考资料确认记录，保存 `action`、`scope`、`context_mode`、`selected_asset_ids`、`result_refs`、`stale_reasons` |
| `context_confirmation_asset_refs` | confirmation 选中/结果资产的精确引用索引；与 JSON wire 同事务同步，资产失效只查询此表 |
| `context_snapshots` | 自动 AI 调用上下文审计记录，保存 `task_id`、`workflow_id`、`phase`、`context_mode`、`included_asset_ids`、摘要、`prompt_hash`、token/section metadata、`result_refs`、错误信息和可选 `rendered_context` |
| `evidence_links` | 使用 `TargetRef + claim_path` 将对象/人物知识/结构字段连到 `SourceRangeRef`；只记录 provenance，不判定事实真假 |
| `context_retrieval_traces` | 按 novel/content mode 保存查询计划哈希、clause 摘要、候选/回读/丢弃计数与 safe-empty 原因；不保存 raw task/query/正文 |
| `context_activation_profiles` | 项目级可编辑规则 aggregate；draft/published 状态与 CAS 版本分离运行时选择 |
| `context_activation_profile_revisions` | 每次发布的不可变规则快照与 rule hash；旧发布版可固定回放 |

`context_confirmations` 和 `context_snapshots` 是两套语义：

- `context_confirmations` 面向手动 AI 操作，表示用户确认过的参考资料选择。
- `context_snapshots` 面向自动流水线审计，表示一次真实 LLM 调用使用过的上下文视图。

地图册不增加新的公开 scope。generation-background 识别 `world.map_atlas.generate`，固定
`reveal_mode=author_full`，调用 atlas 专用 world loader 读取至多 160 个 canonical/已发布
条目，并以 RAG `purpose=map_atlas` 补证。run 只保存 secret-free snapshot、source manifest
与 hash；manifest 按来源类型/ID 保存 loader 计算的内容 hash，更新判断不接受
LLM 自报 hash。候选对象始终排除。

地图册的空间补充仍复用 `retrieve_planned_context_evidence()` 的既有 planner、RAG 与原文
rehydrate 门禁；不新增 RAG scope、port 或索引。失效/跨项目/旧正文片段在该门禁处被丢弃。

`selected_asset_ids` 与 `result_refs` 继续保持既有 JSON 对外形状，但不再承担失效查询。
新 confirmation 创建时同步写入 `selected` 引用，结果绑定时必须携带 `novel_id` 并在
`id + novel_id` 行锁内同步 `result` 引用；失效只通过精确表匹配类型与 ID，不回退扫描 JSON。
JSON wire 中为兼容保留 `world_entities/scenes/...` 等复数 key；精确引用表会规范为
`world_entity/scene/...` 单数资产类型，使各领域的失效命令使用同一类型词汇。

默认只保存可复现摘要和 metadata；`retain_rendered_context=True` 时才保存完整上下文并设置过期时间。清理任务只清空 `rendered_context` 和 `rendered_context_expires_at`，不删除快照行、hash、资产 ID、结果引用或 metadata。

作者端“问世界”调用 `retrieve_planned_context_evidence()` 复用现有 RAG 召回和正文回读，再把
world 已回读的正式页面候选一并交给 `compile_author_question_evidence()`。后者只做稳定排序、
去重、SHA-256 形状校验以及最多 5 个来源／24,000 字符的预算裁剪，并返回不含正文的
included／excluded／truncated trace；它不调用模型、不判断事实权威，也不持久化第二套索引。

## Activation Profile

Activation Profile 属于 context，不属于 World Bible 页面。规则只支持声明过的 action、
`author_safe/author_full` 模式、任务/当前 Scene/最多两个前序 brief/显式焦点文本，以及
Unicode NFKC + 大小写归一化的 substring 或 token-boundary 匹配；不支持 regex、随机概率、
任意表达式或无限递归。每个 Profile 最多 128 条稳定 rule ID，固定 TargetRef 只允许已采用的
World Bible 页面或 CoreEntity，页面链接/关系展开最大深度为 2。

编辑和 dry-run 可使用当前 draft；发布会校验目标并写不可变 revision。运行时只解析已发布
revision，编辑已发布 aggregate 会创建更高版本 draft，不改变旧运行时结果。编译器仅在调用方
显式选择 Profile 时增加可排除 P1 `world_bible_activation`，并把资料包在不可关闭的不可信数据
边界内。reader/character、candidate、P0 和 `novel_id` 门禁始终优先于规则。

trace 对每个候选保存 rule、命中/阻断原因、来源、展开父项、source hash、预算前后 token、
排除原因与 stale projection fallback。confirmation 与 snapshot 固定实际 profile version、
rule hash、来源 hash 和纳入目标 hash；页面发布会把消费该页的 confirmation 标脏。

## AI 参考资料审查台

手动 AI 操作的确认弹窗使用 `CompiledContext` 作为中间表示：

```text
Loader 聚合业务资料
  -> ContextCompiler 生成 ContextSection IR
  -> enforce_budget 记录 evicted/truncated budget_events
  -> API 返回 sections + selected_asset_ids + warnings
  -> 前端渲染“参考资料清单”，而不是 raw Markdown
```

`ContextSection` 除了 `key/tier/content/token_count` 外，还包含面向审查台的只读字段：

- `title`：作者可读标题，例如“本次任务”“当前 Scene”“RAG 证据包”
- `preview`：审查用预览，不替代真正送入 LLM 的 section 内容
- `status`：`system / canonical / working / candidate / mixed / unknown`
- `activation_reason`：本段被激活的原因，例如当前 `scene_id`、章节范围或 RAG 命中
- `sources`：来源摘要，包含 `type/id/label/status`
- `can_exclude` 与 `excluded`：本次操作是否允许排除、是否已排除
- `truncated_reason`：预算裁剪原因

`reader` 编译使用独立的最小 section 路径：只保留用户任务、
ReaderRevealPolicy/公开基线允许的世界信息、从 writing 回读且 hash
校验通过的正文证据和不含剧情事实的项目风格。完整 Scene 卡、
剧情线、记忆、篇章纲和未过滤的动态约束不进入 reader `CompiledContext`。

### 世界观简介与工作稿 section

`CompileOptions.include_world_synopsis` 默认 `false`；只有 `author_safe/author_full` 可得到
可排除的 P1 `world_bible_synopsis`。reader/character 即使请求开启也会返回可见性排除
warning，POV 因固定使用 character 模式同样不会读取作者简介。简介与页面正文均包在明确的
不可信数据边界中，不能作为 system 指令执行。

`selected_world_bible_draft_ids` 只加载作者显式选择且通过 `novel_id` 校验的工作稿，并放入
独立 P1 `world_bible_working_pages(status="working")`，不改变简介 source manifest。
确认记录把实际 `world_synopsis_revision_id` 固定到 `compile_options`；回放读取同一不可变版本。
生成中心通过注册的 `context.generation_background` DI port 获取上下文，world 不直接依赖
context ORM/service。对象生成响应的 `context_usage` 是实际调用 provenance，不通过事后重编译
猜测本次使用的 revision；同一次编译还会建立 `context_snapshots` 记录实际
revision/source/block hash、section/token metadata 和后续产物引用。

`budget_events` 记录预算执行过程，包含 `section_key`、`event_type`、`reason`、`before_tokens`、`after_tokens`、`tier`。被 evict 的 section 不再返回正文，但会通过 `budget_events` 告知前端“已移除”；被 truncate 的 section 保留裁剪后的正文和裁剪原因。

`context_confirmations` 仍只持久化摘要字段：`selected_asset_ids`、`compile_options`、`warnings`、`result_refs`、`stale_reasons` 等。`sections` 和 `budget_events` 是本次编译的实时展示结果，不写入确认记录。
当 Scene 跨章且编译器用 Scene 的末章作为相关性检索锚点时，
`compile_options.chapter_index` 记录该有效锚点，
`compile_options.requested_chapter_index` 保留用户确认的目标章节，供 writing 等消费方
校验本次确认没有被复用于其他章节。
任务 finalize 需要消费当前 confirmation owner 时可使用 `for_update=True`；
结果引用绑定本身也会锁定该行并刷新 identity map，避免并发 task/candidate
回写相互覆盖 `result_refs`。

## 检索计划与运行健康

`RetrievalQueryPlanner` 是 context 拥有的纯确定性函数，不调 LLM。它把 purpose、Scene、
entity/character/thread 和 visibility 组装为最多 3 条 clause；RAG 仍只执行单条受控检索。
loader 按稳定 RRF 合并，然后统一回读 writing 正文并复核 source hash/可见截止。

`GET /api/context/evidence-health` 组合 Outline SceneSpan 覆盖、RAG 映射覆盖和近期 trace；
`GET /api/context/retrieval-traces` 只返回隐私安全的运行摘要。无运行样本时 health 是
`insufficient_data`，不伪装成绿色通过。trace 默认保留 30 天且每项目最多保留
10,000 条，通过现有 snapshot maintenance 入口 dry-run/执行。近期统计和清理都由
数据库聚合/子查询执行，不用固定大 limit 加载 trace ORM，因此高于历史
100,000 条时也不会截断计数或遗漏过期记录。
PostgreSQL 下 trace 使用独立旁路会话并设置 2 秒事务级锁等待上限；诊断写入遇到
调用方未提交父行造成的 FK 锁竞争时降级为 warning，不阻塞检索或 LLM 工作流。

snapshot stale 优先与 owner task 对账：owner 心跳新鲜则长时运行不算 stale；
owner terminal 或 lease stale 则分别以 `owner_task_terminal` / `owner_task_stale` 关闭孤儿快照。

### Section 级排除

V1 复用 `excluded_asset_ids`，约定：

```json
{
  "excluded_asset_ids": {
    "context_sections": ["retrieval_evidence_packs", "style_assets"],
    "manual": ["asset-id-1"]
  }
}
```

- `excluded_asset_ids.context_sections` 表示本次 AI 操作临时排除的 section key。
- P0 section 不可排除，包括 `writing_objective`、`scene_blueprint` 和硬约束类 section。用户尝试排除时后端忽略，并返回 `核心参考资料不可排除：<key>` warning。
- `selected_asset_ids.context_sections` 记录最终参与编译且未被排除的 section key。
- `manual` 保留给既有资产 ID 排除输入，V1 不把它解释为 section key。
- V1 只支持 section 级控制，不做 item/entity 级事实编辑；更细粒度排除继续使用现有实体、人物、地点 ID 参数。

## Loader 依赖注入

`ContextCompiler` 的外部行为由 `SCOPE_LOADERS`、loader `name` 和 facade 入口保持稳定；loader 内部依赖统一通过构造函数注入 callable。生产默认 callable 仍委托既有 `project / world / memory / outline / rag` 稳定入口，测试可直接传入 fake callable，不需要在 `load()` 内 monkeypatch facade 或直接访问 DI container。多个 loader 共用调用方的同一 `AsyncSession`，因此前置与依赖阶段内均顺序执行，不在同一 session 上并发发起 SQL。

`load()` 只使用 `self._...` 依赖：

- `ProjectLoader(get_project_context_fn=...)`：进入 prompt bundle 前只投影标题、题材、
  语言、风格、创作阶段、目标规模和默认揭示策略等明确安全字段；完整
  `settings`、LLM API Key、Base URL 和其它运行时配置不得进入 section 或 prompt
- `WorldEntitiesLoader(get_world_context_fn=...)`
- `CharactersLoader(get_characters_context_fn=..., filter_context_by_character_knowledge_fn=..., get_scene_contract_fn=...)`
- `EventsLoader(get_events_context_fn=...)`
- `MemoryRecordsLoader(get_memory_panorama_fn=...)`
- `RagChunksLoader(retrieve_fn=...)`
- `SceneLoader(get_scene_contract_fn=...)`

`consumer_action=writing.generate` 使用写作专用加载顺序：先编译当前
Scene、当前章活跃剧情线、篇章和 RAG 证据，再从这些资料的关联 ID
选择人物与世界对象。显式 ID 优先，其次为 Scene、篇章、剧情线和
RAG 候选顺序；人物最多 6 个，相关世界对象最多 16 个。没有可用关联
ID 时，世界对象才回退到已采用对象的重要性排序。

`consumer_action=outline.analyze` 使用已有字段表达确认范围：
`chapter_index` 是起始章，`visible_until_chapter` 在作者模式下同时作为结束章和正文证据
上界。编译器先以顺序前置 loader 通过 outline 稳定 facade 加载范围内按叙事顺序排列的
Scene、重叠篇章、
区间重叠或被范围资产显式关联的剧情线，以及伏笔/揭示计划，并把这些 section 显示在
AI 参考资料审查台；该范围查询不进入共用 `AsyncSession` 的 dependent gather。随后再从
这些结构资产的关联 ID 选择人物 Top-6 和世界对象 Top-16；没有相关对象 ID 时不回退到项目全局
对象。在 P2 预算中剧情线优先于篇章，所有 P2 section 共享同一剩余预算；预算耗尽的 section
会被明确剔除并记录 budget event，source 与保留内容同步。confirmation 会记录实际纳入的结构资产
ID，任务回放只按该 confirmation 的 compile options 重编译，不在 LLM 阶段扩展未确认资料。作者显式
指定范围时，缺失精确范围 section 的确认和回放都失败关闭。

POV character reveal 在这一选择结果上继续分层：POV 人物得到
完整的安全档案；其他相关人物只渲染外观和语言风格，不渲染
身份、内心、渴望、恐惧、行为规则或隐藏关系。姓名只是供模型指代人物的
作者侧标签，不代表 POV 角色知道其姓名。世界对象仍先经
CharacterKnowledge 过滤。当前章活跃剧情线只向模型提供名称、公开目标和
当前进展，并标为 `director_only`；`summary / hidden_truth /
author_known_state` 不进入 character reveal section。

CharacterKnowledge 先由 world 按目标选出唯一 canonical 有效检查点：公开基线从开场生效，
章节记录仅在学习章严格早于目标章时生效，同章重复按更新时间和稳定 ID 确定结果。角色视角
`role_visible_knowledge` 展示该结果的完整内容、生效位置与作者可读知识级别；
`false_belief` / `misunderstood` 缺少明确误解内容时不进入上下文。剧情线等
`director_only` 作者约束保持独立，不伪装成角色已知事实。

带 `scene_id` 的 `writing.generate + reveal_mode=character` 还会通过 memory 稳定
facade 确保当前 Scene 四维 checkpoint（`entities`、`relations`、`locations`、`knowledge`），并编译不可排除的 P0
`scene_world_state`。只有可重放的 system `ready` 或已人工确认的状态会成为
`director_only` 环境约束；`knowledge` 只报 coverage，不覆盖上述
CharacterKnowledge。当前 Scene、POV 和显式选择对象没有命中实体投影时，只在
确认 UI 显示“尚无时间锚”，模型不收到该项，也不得用当前 World 回填。

`MemoryRecordsLoader` 同时把章级 panorama 规范为可读记忆列表，不再把 dict 塞入
`memory_records: list`。新的 Scene 确认会按固定四维顺序保存 checkpoint
ID/status 指纹；执行前指纹变化就拒绝回放并要求重新确认。旧确认没有该可选
字段时继续兼容。

`scope=generation_center` 供生成中心整个 world 工作区使用，覆盖共创聊天、只读收束、对象建议、
完善现有世界书页面和创建新页面。编译器接收来源页面、当前 Scene、显式剧情线/人物/对象、章节
索引、世界观简介开关和 Activation Profile revision；以最近作者意图作为确定性 RAG query，
按“显式选择与来源页引用 → 当前 Scene → 当前章活跃剧情线/篇章/RAG → 关联人物与对象 →
项目设定与可选简介”组织资料。人物自动候选最多 6 个，非人物世界对象最多 16 个，显式
选择优先占位；没有章节、Scene、页面引用或检索证据时不默认加载第一章剧情线。

generation center snapshot 保存 consumer action、Prompt 名称、来源页面/工作稿 hash、简介
revision、Activation Profile revision、实际纳入的剧情线/Scene/人物/对象和裁剪原因。用户
聊天正文不复制进 `compile_options`，只保存 focus hash；页面正文也由 world 在服务器端重载，
context 只消费经边界校验的来源投影。

`GenerationBackgroundService` 是这条能力的深模块：它在一个请求对象内拥有 focus
规范化、`CompileOptions` 建立、tier 编译、Markdown 渲染、usage 投影和 snapshot request
组装；facade 只保留既有 keyword contract 并委托。snapshot 的 `included_asset_ids` 只把
预算执行后完整保留在最终 section 中的工作稿、简介 revision、activation target 和 section
sources 记为实际纳入；请求过但被裁剪的内容仍可由 `compile_options` / budget events 审计，
不冒充已发送给模型。成功解析的 Activation Profile 即使没有保留对应资料 section，仍可作为
独立控制 provenance 保留；未解析的 Profile 不计入 `included_asset_ids`。

生成快照使用 context-owned durable transaction：
`compile_generation_background()` 独立持久化 running 状态，调用方通过
`succeed_generation_context_snapshot()` / `fail_generation_context_snapshot()` 独立收尾，
不会提交或回滚调用方的业务事务。生成中心在模型返回后可用
`capture_snapshot=false` 复编同一份当前上下文做来源新鲜度比较；该复编只读且不建立第二条
调用审计快照，真实模型调用仍始终保留一条完整快照。
- `PlotThreadsLoader(get_active_threads_fn=...)`
- `OutlineArcLoader(get_arc_by_chapter_fn=...)`

`RagChunksLoader` 会把 `CompileOptions.visible_until_chapter` 传给 RAG 的
`visible_until_chapter` 硬过滤；当该字段为空且存在 `chapter_index` 时，默认用当前章
作为读者进度上界。范围型上下文（例如深度导入 Phase 3 结构生成）必须显式传入范围
结束章，避免只用起始章过度过滤后续证据。`reference_chapter_index` 仍只作为 RAG
时间衰减评分 hint。

RAG loader 不会直接把 chunk text 视为事实。它按 `source_id` 从 writing 重读
当前原文、校验 source hash，然后才生成 section 的 source refs/hash metadata；
过期块被丢弃并返回降级警告。

手动智能检索与 `RagChunksLoader` 复用 `NovelEvidenceService` 的同一候选回读链路：
候选必须同时通过 `novel_id`、正文来源类型/ID、当前 source hash、offset/range 和
reader/character 可见性校验，随后才从 writing 读取当前原文。RAG 只负责候选排序，
任何缓存 chunk text 都不能绕过该链路进入证据响应或编译上下文。

## 小说证据服务与可见性

`NovelEvidenceService` 在 context 内集中编排 writing、RAG、outline 和 world，
对外只暴露确定性 grep/search/read/inspect/trace，不是自主选择工具的 Agent。

面向作者的小说检索按章节聚合正文结果：字面搜索汇总同章全部出现位置；智能搜索
先按语义召回并合并同章 chunk，再在索引新鲜时用精确字面命中补足章节覆盖。
响应中的 `match_count` 与 `match_basis` 分别说明聚合数量以及数量代表
`occurrence` 还是 `chunk`。索引过期时智能搜索不会绕过 freshness guard 直接读取新稿。
作者视角下，经 writing 原文回读与 hash 校验后的正文命中会通过精确
SceneSpan 补充父 Scene 序号、标题及由目标/冲突/情绪组成的短摘要。
`scene_refs` 始终只对应当前卡片展示的 `source_ref`；按章聚合时，
`parent_scene_contexts` 再去重汇总 `source_refs` 所代表的全部父 Scene，
避免字面补命中替换了范围却保留旧 Scene 元数据。
`context_scene_id` 可选指向当前写作 Scene，响应以 `writing_relevance`
确定性标记命中属于当前、前序、后续或未映射 Scene，不使用 LLM
臆测因果关系。读者/角色视角不返回这些作者专用 Scene 语义或写作关系。

`VisibilityContextContract` 有三种模式：

- `author`：无剧透截止。
- `reader`：必须有 `cutoff_chapter`，可选同章 `cutoff_scene_id/cutoff_offset`。
- `character`：除上述截止外必须有 `character_id`。

writing、RAG、SceneSpan/checkpoint、ReaderRevealPolicy 和 CharacterKnowledge 各层先过滤，
context 在返回前再校验来源位置。CharacterKnowledge 只在学习位置严格早于
截止章时生效；同章无顺序、缺少章且未标记 `is_public_baseline` 的旧数据默认排除并告警。
编译和对象检查会明示这类保守降级；inspect/trace 还会从 writing
回读 evidence link，伪造或失效引用不计入证据，并返回 `index_fresh=false`。

深度导入只在 schema 校验通过且 quote 能唯一定位到当前可见原文时，在事实写入同一
savepoint 记录 active evidence link。无法定位时只记 `needs_review` 与原因，
不伪造 offset/source ref。

```http
POST /api/context/evidence/grep
POST /api/context/evidence/search
POST /api/context/evidence/read
POST /api/context/evidence/inspect
POST /api/context/evidence/trace
GET/POST /api/context/activation-profiles
PATCH /api/context/activation-profiles/{profile_id}
POST /api/context/activation-profiles/{profile_id}/publish
GET /api/context/activation-profiles/{profile_id}/revisions
POST /api/context/activation-profiles/{profile_id}/revisions/{version}/restore-draft
GET/POST /api/context/activation-preview
```

## Deep Import Activation

`prepare_import_context_activation()` 是 Phase 2a 的唯一跨模块预检入口。它通过
outline facade 获取锁定 Scene 卡、当前章节范围内的 active working Scene / 篇章纲 / 剧情线
以及前序 brief，通过 world facade 装配身份候选，并读取当前 Scene 在可见截止章/offset
以前的完整精确正文范围。直接被正文名称或别名命中的候选全部保留，其余候选按 Scene / 大纲
关联和重要度选择人物 Top-6、非人物 Top-16；Top-K 是资产相关性边界，不是输入 token
预算。模型只看到服务端生成的 `entity-xxx` 引用，不看到可自由回传的数据库 ID。

`import-context-v2` 不裁剪当前 Scene，也不对 Phase 2a 输入实施应用层字符/token 预算；
provider 上下文超限时该 Scene 显式失败并进入复核。后续 Scene 和跨章 Scene 中越过截止的
span 永不进入 activation；可见范围内只要存在 `chapter_only / unresolved`、非法 offset 或
缺失 span，就不发送部分 Scene。context fingerprint 覆盖正文来源、Scene 卡、相关大纲、
身份候选、前序证据和相关既有关系，并进入 checkpoint/snapshot；provider 调用前关闭数据库事务。
Phase 2b 复用完整正文与同一相关性边界，以 `entity-xxx / relation-xxx` 完成别名和关系
连续性对账，同样不做应用层输入裁剪。activation 和来源摘要只用于审计，不产生正史事实。

## 快照生命周期维护

`context_snapshots` 的生命周期治理由 context 模块拥有，入口是 facade 和只读/维护 API：

生产代码通过 `open_context_snapshot()` 打开 running 快照，通过
`succeed_context_snapshot()` / `fail_context_snapshot()` 完成生命周期标记。宽参数
`create_context_snapshot()` 仅用于兼容旧调用。

生成中心调用使用独立的 `open/succeed/fail_generation_context_snapshot()` 生命周期；这些
入口由 context 创建并提交独立 session，确保业务 suggestion/chat 事务回滚时审计快照仍可
记录失败。普通 snapshot 入口继续参与调用方事务，不改变既有自动流水线的原子性。

```http
GET  /api/context/snapshots?novel_id=...&workflow_id=...
GET  /api/context/snapshots/{snapshot_id}?novel_id=...
POST /api/context/snapshots/maintenance
```

维护 API 默认 `dry_run=true`，只返回会变更的数量；调用方必须显式传 `dry_run=false` 才会修改数据库。请求字段包括：

- `novel_id` 必填
- `workflow_id` 可选
- `running_timeout_minutes` 默认 120
- `prune_rendered_context` 默认 true
- `retain_latest_full_context_per_project` 默认 200
- `dry_run` 默认 true

维护规则：

- 超时 `running` 快照会在执行模式下转为 `status="failed"`、`error_kind="stale_running"`。
- 完整 `rendered_context` 按过期时间和每项目最近保留上限清理。
- 维护不改 `result_refs`、hash、asset ids、section/token metadata 或快照行本身。

`SnapshotHealthSummary` 是轻量聚合，只包含数量、状态/phase 分布、超时 running、保留 full context 数和最近失败摘要；不返回完整 prompt、`rendered_context` 或完整 result refs。

## 主要选项

| 选项 | 含义 |
|------|------|
| `scope` | `project / world / world_character / arc / chapter / full` |
| `scene_id` | Scene-centric 编译入口 |
| `context_mode` | `canonical` 或 `working` |
| `content_mode` | 正文事实源和 RAG 索引视图：`canonical` / `working` |
| `chapter_index` | 实际检索锚点；跨章 Scene 可使用 Scene 的末章 |
| `requested_chapter_index` | confirmation 固定的作者目标章节；writing 等消费方优先用它校验任务目标，旧记录缺失时才回退 `chapter_index` |
| `include_pending_objects` | 是否显式纳入未采用/review 对象；默认 false |
| `reveal_mode` | `author_safe / author_full / reader / character` |
| `visible_until_chapter` | RAG 读者进度上界；为空时单章上下文默认使用 `chapter_index` |
| `visible_until_scene_id/visible_until_offset` | 可选同章 Scene/字符截止点 |
| `budget_tokens` | 总预算，前端默认 4000 |
| `excluded_asset_ids.context_sections` | 本次临时排除的可选 context section key |

`WorldEntitiesLoader` 会把 `include_pending_objects` 下推为 world facade 的 `include_review`，并在响应侧再按 `display_state/status` 防御过滤。`false` 只保留 active/canonical 对象；`true` 可额外包含 review 对象，但仍排除 archived，并返回“上下文包含未采用的世界对象”警告。

## 兼容字段说明

`StructureContextBundle` 里仍保留一些旧字段名：

- `memory_records`
- `timeline_events`
- `geo_locations`

这些名字主要是兼容现有渲染器和测试，不表示系统仍存在同名业务模块或数据表。

## 测试

```bash
cd backend
pytest modules/context/tests/ -v
```
