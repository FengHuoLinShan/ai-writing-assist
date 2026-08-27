# Module: evidence / 检索、编译与确认模块

## 定位

evidence 是小说证据的唯一领域实现：indexing 子域负责 chunk、混合检索、embedding 与索引
新鲜度，compilation 子域决定“这次 AI 操作到底能看到哪些资料”，并负责原文回读、可见性、
预算、confirmation、snapshot、trace 与 hidden guard。原 RAG/Context 表名和 HTTP 路径不变，
但不再存在两套服务或写入路径。

当前有两条能力线：

- `index_chapter_with_report()` / `retrieve()`：维护 chunk、embedding、索引新鲜度与混合召回
- `compile_structure_context()`：兼容旧调用方的结构化 bundle
- `compile_with_tiers()`：当前前端和 AI 参考资料确认流程使用的分层编译器
- `context_snapshots` facade：自动 AI 流水线的上下文快照审计记录
- `load_scene_lens()`：写作台显式点击后读取单个 Scene 的 POV 可见资料与已有时点状态

`compile_with_tiers()` 不只是生成最终 Markdown。它先生成可审查的 `CompiledContext` IR，再由 API 和前端把每个 section 的标题、状态、来源、激活原因、token 和裁剪结果展示给用户。

## 数据与来源

context 本身不拥有业务事实，但当前**有自己的确认与审计记录表**：

- `rag_chunks`：可重建的正文检索块，绑定 writing source ID/hash
- `rag_entity_appearances`：从当前正文索引派生的对象出场投影
- `rag_index_state`：索引请求源、已完成源、freshness 与 task owner/generation 状态
- `context_confirmations`：AI 参考资料确认记录，保存 action、scope、selected_asset_ids、warnings、result_refs、stale_reasons 等摘要
- `context_confirmation_asset_refs`：把确认记录精确索引到资产 kind/id、来源 hash 与失效检查
- `context_snapshots`：自动 AI 调用上下文快照，保存 task_id、workflow_id、phase、context_mode、included_asset_ids、摘要、prompt_hash、token/section metadata、result_refs 和错误信息
- `evidence_links`：使用 `TargetRef + claim_path` 将对象字段连到 `SourceRangeRef`；保存 precision/status/provenance，不创建独立 Claim 正史
- `context_retrieval_traces`：只保存查询计划 hash、clause 摘要、计数和 safe-empty 原因，不保存 raw query/正文
- PostgreSQL trace 旁路写入设置 2 秒事务级锁等待上限；FK 锁竞争只产生诊断 warning，
  不阻塞调用方检索或生成流程
- `context_activation_profiles` / `context_activation_profile_revisions`：项目级 AI 参考规则 aggregate 与不可变发布历史；运行时只消费已发布 revision

聚合来源仍来自：

- `project`
- `world`
- `memory`
- `outline`
- `evidence/indexing`

canonical world 来源现在只经 `world.facade.get_world_canon_context()` 读取：
`WorldEntitiesLoader` 消费 C 选中的 exact Entity/Page revisions 与
Name/typed scalar/binary relation Assert，不从 mutable Profile/Relation/MemoryEvent 回退。
`CompileOptions` 记录实际 `world_canon_revision_id` 和 manifest digest；confirmation 回放
重读同一 C，生成 snapshot 还在 `included_asset_ids.world_canon_revision` 固定该来源。
`context_mode=working` 或显式纳入待处理对象时才走 working projection。

## 编译模式

地图册不新增公开 scope。generation-background 对 `world.map_atlas.generate` 固定使用
`author_full` 与 canonical world background（上限 160），再通过 RAG `purpose=map_atlas`
补充已确认资料；工作稿只在作者显式开启时加入，候选对象始终排除。run 保存 secret-free
snapshot、source manifest 与 hash，用于更新时识别来源变化。manifest 按真实来源类型/ID
记录 loader 的内容敏感 hash；文本模型只能引用当次 manifest，不能决定 hash。

### 1. 兼容 bundle

`StructureContextBundle` 仍然保留一些历史字段名以兼容现有渲染器和测试，例如：

- `memory_records`：现在实际承载的是记忆全景/快照视图，不是旧表 `memory_records`
- `timeline_events`：来源于 `world` 的事件上下文
- `geo_locations`：当前通常为空，geo 模块已移除

### 2. 分层编译器

`CompiledContext` 是当前主路径，按 tier 组织内容并做预算裁剪。前端的生成中心任务页、AI 参考资料确认、outline 生成等都优先使用这一层；旧 `context` hash 入口已由路由层重定向到 `generate?tab=task`。

reader 视角不沿用作者 section 组装：编译器只纳入公开/已揭示世界信息、
回读 writing 且校验 hash 的正文证据与无剧情事实的风格资产。完整 Scene 卡、
剧情线、记忆、篇章纲和包含未来伏笔的动态约束一律排除。

每个 `ContextSection` 会携带审查台元数据：

| 字段 | 含义 |
|------|------|
| `title` | 面向作者的标题 |
| `preview` | 审查预览，不等同于最终 prompt |
| `status` | 内部审查标记：`system / canonical / working / candidate / mixed / unknown`；前端将 `candidate` 统一显示为待处理内容 |
| `activation_reason` | 本段为什么被选入 |
| `sources` | 来源摘要，包含 `type/id/label/status` |
| `can_exclude` | 本次操作是否允许排除 |
| `excluded` | 是否已被排除 |
| `truncated_reason` | 被预算裁剪时的原因 |

`enforce_budget()` 除了保留 `evicted_keys` 和 `truncated_keys`，还会生成 `budget_events`。前端据此显示“已裁剪 / 已移除”、裁剪前后 token 和原因。被 evict 的 section 不返回正文，但保留事件；被 truncate 的 section 返回裁剪后的正文。

## Loader 架构

`ContextCompiler` 使用 loader 策略按需拉取数据。当前主来源可概括为：

| Loader | 当前来源 |
|--------|----------|
| `ProjectLoader` | `project.facade` |
| `WorldEntitiesLoader` / `CharactersLoader` | canonical 读 `world.facade` 的 C-pinned 投影；working 读显式工作投影 |
| `EventsLoader` | `world.facade.get_events_context()` |
| `MemoryRecordsLoader` | `memory` 全景查询 |
| `OutlineArcLoader` / `SceneLoader` / `PlotThreadsLoader` | `outline` 服务与 facade |
| `RagChunksLoader` | `evidence.facade.retrieve()` |
| `WorldBibleLoader` | C-pinned 页面修订由 world context 投影输入；另读作者简介与显式选中工作稿 |

loader 的外部调度契约仍由 `SCOPE_LOADERS` 与各 loader `name` 决定；具体依赖统一为构造函数注入 callable。默认 callable 委托上表既有来源，因此 API、schema、bundle shape 和 ContextCompiler 外部行为不变。测试可直接传入 fake callable；`load()` 内不做 facade local import，也不直接访问 DI container。

写作台 Scene Lens 按 `scene → related world entities → POV character →
scene checkpoints` 的固定顺序只读。服务端校验 Scene 属于请求项目与章节，
从 Scene 推导 POV，并始终以请求章节作为可见性截止点。它只读已有 checkpoint，
不调用 ensure；没有显式关联对象时不回退全项目对象，也不包含 RAG、
embedding 或 retrieval trace。`POST /api/evidence/compilation/scene-lens` 先经过 owner-aware
`require_active_project()`，响应项只公开作者语言的 `label + summary + availability`
及 warnings。

RAG 文本只用于候选召回。`RagChunksLoader` 按 chunk 的 source draft/hash 从 writing
重读原文，不匹配则丢弃并告警；进入 `CompiledContext` 的 section metadata 保留
source refs/hash，不把未校验的 chunk text 当作事实。

## 小说证据编排

`NovelEvidenceService` 集中编排 writing、RAG、outline 和 world，暴露确定性
grep/search/read/inspect/trace。它不自主选工具，受控 LLM 工作流只能消费
已编译、已校验的证据包。

作者端“问世界”通过 `retrieve_planned_context_evidence()` 复用同一 RAG 回读路径，再由
`compile_author_question_evidence()` 对 world 已回读的正式页面和正文证据做稳定排序、去重、
hash 形状校验与最多 5 个来源／24,000 字符的预算裁剪。返回 trace 只列纳入、排除、缩短和
篇幅统计，不复制正文；该 helper 不调用 LLM、不判断权威，也不建立第二索引。

`VisibilityContextContract` 支持 `author/reader/character`。reader 必须提供截止章，
character 还必须提供人物 ID；两者可选同章 Scene/offset 截止。writing、RAG、
SceneSpan/checkpoint、ReaderRevealPolicy 和 CharacterKnowledge 各层先硬过滤，
context 返回前再校验 source location。同章无可判定先后、或缺少学习章且非明确
public baseline 的 CharacterKnowledge 默认排除。
这类保守排除会返回 warning。inspect/trace 会再从 writing 回读 evidence link；
伪造或失效引用不计入证据，并通过 `index_fresh=false` 与 warnings 报告。

CharacterKnowledge 还会按目标确定性选择唯一 canonical 有效检查点：公开基线从开场生效，
章节检查点仅在学习章严格早于目标章时生效，多个候选按生效章、更新时间和稳定 ID 决胜，
不依赖数据库返回顺序。`false_belief` / `misunderstood` 只提供明确填写的误解内容；缺失时
失败关闭，不以作者知道的真实内容兜底。

只在 `writing.generate + scene_id + reveal_mode=character` 中，context 才经
`memory.facade.ensure_scene_checkpoints()` 编译 P0 `scene_world_state`。system
`ready` 或明确人工确认的 `entities / relations / locations` 会以
`director_only` 进入模型；`knowledge` 维度只显示 coverage，角色所信仍只由
CharacterKnowledge 决定；AI 地图册不属于 Scene memory。`retry_pending / manual_required / gap` 以及当前相关
对象未命中 checkpoint 的项不进入模型；后者只在作者 UI 标为“尚无时间锚”，
不表示当时不存在。普通 author-safe 写作目前只获得 `memory_records`
dict/list 形状修正，不宣称有完整历史门禁。

新确认把四维 checkpoint ID/status 的排序 SHA-256 写入可选
`compile_options.scene_state_fingerprint`。回放时任一 checkpoint 被重建或人工修复即
拒绝旧确认；旧记录没有该字段仍可回放。这里借鉴
[KurrentDB projection/checkpoint](https://docs.kurrent.io/server/v26.1/features/projections/intro)
的派生投影纪律和
[optimistic concurrency](https://docs.kurrent.io/getting-started/concepts)
的期望版本思路，但不引入事件数据库。
[XTDB 的 valid time / system time](https://docs.xtdb.com/about/time-in-xtdb.html)
说明“故事中何时有效”不等于“作者何时修改”；首批只用 Scene 离散锚，不引入
双时态数据库。[MediaWiki 页面历史](https://www.mediawiki.org/wiki/Help%3AHistory/en)
只适合对比修订，不能充当故事 valid-time，因此当前 World revision 仅供修复参考。
全流程的 Scene 选择、事件重放、coverage、修复和指纹核对都是确定步骤，
因此本轮不引入 Pi 或任何 Agent 运行时。

深度导入在事实写入同一 savepoint 记录 evidence link；quote 只有在当前可见、
版本绑定的 Scene 原文中唯一命中才可形成 active source ref。无法定位时标记
`needs_review`，不伪造 offset。

## AI 参考资料确认

Activation Profile 是 AI 参考资料选择的一层确定性输入。每个 Profile 最多 128 条稳定规则，
仅支持声明 action、author 模式、受限文本来源、Unicode 归一化 substring/token-boundary、
固定 World Bible 页面/CoreEntity TargetRef，以及最大深度 2 的页面链接/关系展开；不支持
regex、随机概率或任意表达式。draft 只用于编辑和 dry-run，发布会校验目标并写不可变 revision。
调用方必须显式选择 Profile，编译器才增加可排除的 P1 `world_bible_activation` section。

规则不能放宽 reader/character、candidate、未来 Scene、P0 或 `novel_id` 门禁。逐项 trace
保存命中/阻断、展开来源、source hash、预算前后 token 和排除原因；confirmation/snapshot
固定实际 profile version、rule hash、来源 hash 与纳入目标 hash，确保回放和失效诊断。

手动 AI 操作在 world / outline / writing / generate 等入口发起前，可先创建确认记录：

- `confirm_context()`：编译并落一条 `context_confirmations`
- `require_confirmation()`：校验 action / novel_id / confirmation_id 是否匹配
- `prepare_confirmed_ai_action(..., for_update=True)`：任务 finalize 在重编译上下文前锁定 confirmation owner
- `attach_result_ref()`：把后续任务或产物回写到确认记录
- `mark_asset_context_changed()`：资产变更后把相关确认记录标脏

关键参数：

- `context_mode`：`canonical` / `working`
- `chapter_index`：实际检索锚点；跨章 Scene 可由编译器改为 Scene 的末章
- `requested_chapter_index`：确认记录固定的作者目标章节。创建 confirmation 时由 context
  从请求章节写入，writing 等消费者以此校验任务目标；仅旧确认记录缺失时才回退锚点
- `include_pending_objects`：是否允许待处理对象进入本次上下文，默认关闭
- `excluded_asset_ids`：显式排除的资产
- `user_note`：用户对本次 AI 操作的补充提醒
- `include_world_synopsis`：是否加入只供作者的 P1 世界观简介，默认关闭
- `selected_world_bible_draft_ids`：显式选中的世界书工作稿，放入独立 `working` section

确认弹窗展示的是结构化参考资料清单，不展示 raw Markdown textarea，也不允许用户直接编辑最终 prompt。用户确认的是“本次 AI 调用可参考哪些 section、哪些 section 被裁剪、哪些来源被激活”，不是直接确认一段 prompt 文本。

character 模式下，前端完整展示 `role_visible_knowledge`，并把它与 `director_only` 等
“仅供作者约束”的 section 分组。作者可从确认弹窗打开既有的人物知识管理器修正检查点；
修正不会自动重新编译或调用模型，返回后仍需作者明确触发“重新整理”。

`WorldEntitiesLoader` 会把该开关下推为 world facade 的 `include_review`。关闭时查询层只取
已采用对象；开启时额外取 review 对象但始终排除历史，并在编译结果中加入“包含未采用的
世界对象”警告。context confirmation 和 snapshot 是调用审计，不表示建议已被采用。

`POST /api/evidence/compilation/confirm` 会落库一条 `context_confirmations`，并在响应中返回本次编译的 `sections` 和 `budget_events` 供前端展示。这些展示详情不持久化；持久化仍只保存 `selected_asset_ids`、`compile_options`、`warnings`、`result_refs`、`stale_reasons` 等摘要。
其中 `compile_options.chapter_index` 是实际检索锚点，而 `requested_chapter_index` 是作者确认的
目标章节；两者在普通单章确认中相同。跨章 Scene 使用末章提高相关性时，必须保留后者，避免
writing 将同一确认错误复用于锚点章节。
结果引用回写使用行锁并刷新当前 ORM 快照，因此并发任务入队和产物 finalize
不会用旧 `result_refs` 相互覆盖。

### Section 级排除

V1 复用 `excluded_asset_ids`，新增约定：

```json
{
  "excluded_asset_ids": {
    "context_sections": ["retrieval_evidence_packs", "style_assets"],
    "manual": ["asset-id-1"]
  }
}
```

- `context_sections` 是本次 AI 操作临时排除的 section key，不写入长期偏好。
- `manual` 保留给既有“排除资产 ID”输入。
- P0 section 不可排除。尝试排除 `writing_objective`、`scene_blueprint` 或硬约束类 section 时，后端忽略并返回 `核心参考资料不可排除：<key>` warning。
- `selected_asset_ids.context_sections` 记录最终参与编译且未被排除的 section key。
- V1 只做 section 级控制，不做 item/entity 级事实编辑；实体、人物、地点级控制继续走既有 ID 参数。

## 自动上下文快照

深度导入 Phase 2/Phase 3 的真实 LLM 调用会通过 evidence facade 创建 `context_snapshots`：

- Phase 2 记录当前实体抽取实际送入 LLM 的 handcrafted context，不重接 context compiler。
- Phase 3 记录结构分析使用的 working context，并设置 `include_pending_objects=true`。
- 默认只保存摘要、资产 ID、hash 和 token/section metadata；完整 `rendered_context` 需要调用方显式开启，并由保留策略清理。
- `context_snapshots` 不替代 `context_confirmations`，也不替代 `memory_snapshots`。
- 生成中心的聊天、只读收束和建议会为实际编译的世界观背景建立快照，保存实际 synopsis revision/source/block hash、section/token metadata 和产物引用。

生成中心背景由 context 内部深模块 `GenerationBackgroundService` 完整拥有：它把 focus
规范化、tier 编译、渲染、usage/provenance 投影和 durable snapshot request 组装保持在同一
局部；公开 facade 只适配原有 keyword contract。内容型 `included_asset_ids`（工作稿、
synopsis revision、activation target 和 section sources）只表达预算执行后完整留在最终
section 的内容；仅请求过但被裁剪的内容只留在 compile options 与 budget events 中，不能
记作实际发送给模型。成功解析的 Activation Profile 即使没有保留对应资料 section，仍可作为
独立控制 provenance 保留；未解析的 Profile 不计入 `included_asset_ids`。

生产调用使用 `ContextSnapshotRequest` + lifecycle facade：

- `open_context_snapshot()`：创建 `running` 快照。
- `succeed_context_snapshot()`：写入 `result_refs` 并标记成功。
- `fail_context_snapshot()`：写入错误类型和摘要并标记失败。

旧 `create_context_snapshot()` / `mark_context_snapshot_*()` 保留为兼容 wrapper。

Lifecycle v1 为快照提供显式维护入口：

- `build_snapshot_health_summary()`：按 `novel_id` 和可选 `workflow_id` 聚合快照健康摘要。
- `mark_stale_running_snapshots()`：把超过运行超时的 `running` 快照标为 `failed/stale_running`，默认 dry-run。
- `prune_rendered_context()`：只清理完整 `rendered_context` 和过期时间，不删除快照或 provenance metadata。
- `run_snapshot_maintenance()`：组合超时标记、full context 清理和健康摘要返回。

维护 API 默认 `dry_run=true`；调用方必须显式传 `dry_run=false` 才会修改数据。

## 预算与裁剪

当前默认总预算由 `CompileOptions.budget_tokens` 控制，前端默认 4000。

`CompileOptions.visible_until_chapter` 是 RAG 证据加载的读者进度上界。为空且存在
`chapter_index` 时，RAG loader 默认使用当前章；范围型上下文必须显式传入范围结束章，
避免只用起始章排除同一范围内的后续证据。`reference_chapter_index` 仍只用于 RAG
时间衰减评分，不承担防剧透硬过滤。

`CompileOptions.content_mode` 独立选择 canonical/working 正文与索引；
`visible_until_scene_id/visible_until_offset` 表达同章可选截止点。旧
`reveal_mode` 由适配层映射为统一 visibility 语义。

分类预算仍由 `CONTEXT_BUDGET` 提供，包括：

- `core_entities`
- `normal_entities`
- `characters`
- `memory`
- `foreshadowing`
- `timeline`
- `geo_relations`
- `relationship_edges`
- `plot_threads`（8，用作风险提示阈值，不截断剧情线列表）
- `rag_chunks`

`timeline` / `geo_relations` 是历史命名的预算 key，仍属于当前
`CONTEXT_BUDGET` 契约和 `budget_used` wire 字段；实际数据所有权已迁入
`world` / `context`，不再表示存在独立的 timeline 或 geo 模块。不要只改文档
重命名这两个 key；如需改为 `world_events` / `map_relations`，必须做兼容迁移。

`project`、`scene`、`outline_arc` 属于 singleton 上下文，不进入 `CONTEXT_BUDGET` 预算表，避免把“最多 1 条”的结构信息误报为预算裁剪对象；对应 loader 仍会写入 `budget_used`，用于渲染和审计展示当前是否实际加载。

## API

Evidence 是唯一实现。canonical 路径分别使用 `/api/evidence/indexing/*` 与
`/api/evidence/compilation/*`。旧 `/api/rag/*` 和 `/api/context/*` 已在兼容准备版本
完成固定 SHA 生产发布并核验后退场。下表列出当前路径。

```http
POST /api/evidence/indexing/chunks
GET  /api/evidence/indexing/chunks
POST /api/evidence/indexing/retrieve
POST /api/evidence/indexing/rebuild
POST /api/evidence/indexing/retry-embeddings
POST /api/evidence/compilation/compile
POST /api/evidence/compilation/render
POST /api/evidence/compilation/confirm
POST /api/evidence/compilation/recompile
GET  /api/evidence/compilation/snapshots
GET  /api/evidence/compilation/snapshots/{snapshot_id}
POST /api/evidence/compilation/snapshots/maintenance
POST /api/evidence/compilation/evidence/grep
POST /api/evidence/compilation/evidence/search
POST /api/evidence/compilation/evidence/read
POST /api/evidence/compilation/evidence/inspect
POST /api/evidence/compilation/evidence/trace
GET/POST /api/evidence/compilation/activation-profiles
PATCH /api/evidence/compilation/activation-profiles/{profile_id}
POST /api/evidence/compilation/activation-profiles/{profile_id}/publish
GET /api/evidence/compilation/activation-profiles/{profile_id}/revisions
POST /api/evidence/compilation/activation-profiles/{profile_id}/revisions/{version}/restore-draft
GET/POST /api/evidence/compilation/activation-preview
```

## 不做

- 不把整个项目全量塞进一次请求
- 不绕过 reveal / knowledge / pending-object 约束
- 不负责剧情推理或生成正文
- 不提供完整上下文预设系统、作者长期偏好配置或 item 级事实编辑

## Deep Import Activation

`prepare_import_context_activation()` 是 Phase 2a 的冻结预检接口。它封装当前 Scene
精确 span 正文、最多两个前序 Scene brief、命中共享世界术语的前序证据、世界背景聚合、
来源与预算事件。它接受可见截止章/offset，会丢弃跨章 Scene 中的未来 span。
future Scene 永不进入该输出；别名/关系全局对账仍属于 Phase 2b。
