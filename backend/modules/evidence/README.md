# Evidence 模块

编译产物的 Markdown 渲染（`render_compiled_context`）按资料性质标注事实等级并在有预算
裁剪时追加裁剪记录（详见 `compilation/README.md` 与 `docs/modules/08_evidence.md`）；
剧情线 loader 只取未终结线索、超期保留并标注，编辑约定 loader 仅在作者显式开启
「也用于 AI 写作」时注入。

## 统一 AI 运行信封

`evidence_focused_search` 在领取时冻结 `infrastructure.rag_query_planner` 和 9 次请求；planner
与 nomination 保留各自 30/600 秒 step timeout，但不把单 step timeout 冒充整个 run deadline。
索引与 embedding 任务（`rag_index_chapter` 64 / `rag_reindex_novel` 4096 /
`rag_retry_embeddings` 2048，含 token 上限与 run deadline）以宽上界声明信封，远程 embedding
经同一信封按 honest-unknown 计量；确定性回标不建立信封（详见 indexing README）。

小说证据的唯一领域实现。Evidence 把原 RAG 召回和 Context 编译放在同一所有权边界内，
但保留两条清晰的内部流水线：

- `indexing/`：chunk、混合检索、embedding、索引新鲜度、Scene 映射、对象出场与四个
  `rag_*` task handler；
- `compilation/`：检索计划、原文回读、可见性、Context Compiler、confirmation、snapshot、
  trace、Activation Profile 和 hidden guard。

两条流水线只共享本模块的 ORM、contracts 和 facade，不建立第二套服务、表或双写。
跨模块生产调用只允许使用 `modules.evidence.contracts` 与 `modules.evidence.facade`；调用方
不得直接读取 `rag_chunks`。内部细节见 `indexing/README.md` 与 `compilation/README.md`。

## 数据与不变量

- 表名保持 `rag_*`、`context_*` 和 `evidence_links`；RP `context_snapshots` 以 consumer
  `novel_id` 隔离审计写入，并用 source revision/SourceRangeRef 保留作者资料来源；
- task type、recovery policy、owner scope 与 action/payload 保持不变；
- 所有查询和写入保持 owner + `novel_id` 隔离；
- reader/character 可见性、hidden truth guard、confirmation 精确失效、snapshot 生命周期、
  retrieval trace 和索引 freshness 均沿用原行为；
- 检索结果只是候选，编译阶段按 source ID/hash 回读 writing 原文并再次执行可见性门禁。
- chapter-text chunk 按具体 Writing draft/hash 并存。普通作者 Context 自动物化当前
  Writing manifest；RP 传入冻结 source revision manifest。候选在排序前就过滤草稿/hash，
  历史版本回读不会被新章节版本覆盖。作者 evidence/manuscript search 同样先构建当前
  draft/hash manifest；低层 indexing retrieve 仍可诊断孤立或失败 chunk，不作为作者证据直接展示。
- `compile_interaction_story_context()` 是 Evidence 拥有的深层稳定入口；它固定
  `consumer_action=interaction.story`、读者/人物知识与章节/offset 截止。调用方可传本轮
  剩余预算，Evidence 将其限制在 0～16K；必需资料无法容纳时返回 blocker。
- RP 检索与编译重构（M3 切片 1/2 已落地）：该入口内部按「查询规划 → 候选召回与融合 →
  材料物化 → 预算编译 → 使用记录」五段拆分并逐段版本化。S3/S4/S5 已按 M1 契约等价
  落地：`services/interaction_source_material.py` 承载完整预算前材料
  （`InteractionSourceMaterial`）与纯函数按预算编译（`compile_source_material`，含
  material/render 方法版本常量）；S1 落地 `indexing/lexical_plan.py`——语义输入完整
  保留喂 embedding，词法词项按整条请求有界生成（冻结名称优先 + 跨句轮转，总上限 64），
  RP 编译把激活对象名称/别名作为冻结词项传入；S2 词法通道在 PG 走 `rag_chunks.
  lexical_terms` TEXT[] + GIN `&&` 召回（索引期生成、迁移回填，未就绪范围/SQLite 回退
  同批词项的有界 ILIKE 并记 `lexical_method` 诊断）。冻结样本族实测：M 档 fresh 编译
  中位 68.6ms（原 ~1905ms）、search 中位 32.3ms（原 ~1417ms）；引用激活集合、阻断与
  warnings 与旧路径一致，身份证明片段按 D7 允许选择不同有效章节。切片 3 持久缓存
  `context_interaction_source_cache`（ADR-0018 2026-10-07 修订例外）已接入：材料 key 覆盖
  全部材料输入（含语义输入与词法计划、方法版本），命中跳过检索/物化但仍重过门禁、按冻结
  source_ref 重读复验必需证明；预算变体从完整材料重裁剪并替换单版本派生正文，阻断结果
  不落编译缓存；TTL 24h、方法版本不匹配整行不消费、DB 故障向上传播不吞为 miss；M4 起 fetch 未命中带原因码（absent/expired/version_mismatch/integrity），来源失效沿 evolution 失效缝按 source_novel_id 立即清理派生行；snapshot
  与审查资格不缓存。PG 实测（冻结样本族 s/m）：同查询重查 3/3 命中、compile 中位
  9.5~11ms，8K/16K 预算对 2/2 材料复用，未命中场景成本与切片 2 持平。更大合成库的
  p95/规模/并发对照与索引体积校准（GIN ~33KB/chunk）待补。分工、key、版本与失败语义
  见 [M1 契约](../../../docs/plans/2026-10-07-rp-retrieval-refactor-m1-contract.md)。
- RP 冻结目录中的精修身份依据按确切 draft/hash/范围回读；原作角色还须命中人物检索已经
  准入的范围。固定对象与玩家身份的原文证明一起计入必需预算，不能只保留对象名而省略证明。
- ADR-0024 仅为 `PUBLIC_DEMO_RP_SOURCE_REVISION_ID` 精确指向、ready、fingerprint 与 manifest
  均重验通过的公开 source 放宽一次 source/consumer 同 owner 比较；调用方必须显式携带该 contract，
  任意其它 source 仍按 ADR-0018 拒绝，渲染正文或临时 Key 不进入 snapshot。
- `author_safe + scene_id` 固定以当前 Scene 为同章截止点；后续或跨越截止点的正文候选在
  原文回读阶段 fail closed，`author_full` 不自动增加该截止。

## HTTP 与 import 边界

canonical HTTP 路径为 `/api/evidence/indexing/*` 与
`/api/evidence/compilation/*`。旧 `/api/rag/*`、`/api/context/*` 与
`modules.rag`、`modules.context` 已在兼容准备版本完成固定 SHA 生产发布后退场。

## 验证

```bash
cd backend
pytest modules/evidence/indexing/tests modules/evidence/compilation/tests -q
```

统一地图沿用本模块确认与来源回读：`world.map_atlas.structure` 只消费原确认中保留的空间资料；
图元阅读预览通过已有 `inspect_novel_target` / `read_novel_evidence` 获取受限可见性，
不新增检索 scope、索引表或第二套证据服务。

## 指定对象的补查

`retrieve_focused_evidence` / `revalidate_focused_evidence` 是 compilation 拥有的共享只读
专项能力，供导入、地图和写作消费。它复用 World 身份/一跳邻接和 Writing 冻结原文扫描，
输出可回读证据、完整性回执与独立预算后的 CompiledContext；只读结果不携带资产写入授权。
深度固定为 0 或 1，内部 continuation 和异步恢复沿用现有任务表，不新增检索设施或业务表。
HTTP 与内部边界、来源范围及恢复详见 compilation/README.md。
原文选择支持 `start_offset=0`，以半开区间定位章首；缺失或负数起点仍拒绝。地图的已保存图元
来源通过既有 pinned_refs 预填，仍受作者排除、预算、正文版本/hash与可见性重验约束。

## Agent 读取出口（ADR-0023）

Assistant 的搜索、精确原文、当前对象/Scene 和项目事项投影均经本模块出口。
author-only inspection 加入 World 工作稿、采用地图与 Scene 人物卡/剧本；reader/character
不能从这些作者入口获得内容。引用与实际读取分开计量，确认前重新物化/重验原来源。
资产失效事件在原事务向组合根注册的 source.changed port 发出；Evidence 不调度主动任务，
也不取得业务写入权限。专门 confirmation preview 与确认使用同一参数和指纹。
Confirmation 可经 canonical compilation API 按 owner + `novel_id` 精确回读，不重编译
历史 Context 或暴露私有编译选项。`stale_reasons` 独立于运行/采用状态；一旦非空，
后续结果绑定不会使记录恢复新鲜。

`list_author_task_evidence` 是作者待办的有界只读出口；调用方必须为作者视角，复用 Project
的日期/状态/分页查询，不将工作事项当成角色知识。TargetRef.target_path 继续只表示字段
路径，不复用为任意查询表达式。

writing_candidate 只对作者提供有界候选摘录及 ID/hash/版本定位。它不能伪装为 working 或
canonical 的 SourceRangeRef，reader/character 与越过章/Scene 范围的读取被拒绝。
read_organization_evidence 只返回原整理状态与恢复投影，不把任务进度当正文或世界事实。

### 作者规划与历史的读取边界

`world_bible_page_history`、`foreshadowing_plan`、`reveal_plan` 仅在无截止点的作者范围内读取，
分别标注历史非当前事实、规划非已发生故事。完整作者地图也不能进入带截止点的资料包；章节
阅读预览继续由 World 提供。地图读取附最近20张图片的状态及结果引用，不返回私有 URL、
存储 key 或生图 Prompt。正文精确回读、排除、同 owner 固定 RP 来源版本约束不变。

共享一跳提名使用明确的32768输出上限与600秒截止，首轮传完整schema并使用低强度low推理；恢复仍只重做未完成提名，不丢弃已查原文。

### World 跨域复核消费

World 使用确认后保留的 compiled items 作为实际语义输入，Focused Evidence 继续只读且限深 0/1。Story/map 规划目标的 inspect 仅向无 Scene 截止的作者开放；其他视角因没有对应投影而失败关闭。原文 pinned_ref 只取经验证的 highlight 区间，不把整个段落追加到选择中；回执与修订仍归 World，Evidence 不写跨域资产。

### 审阅与导航体验约定

手动写作资料确认在未显式指定预算时采用有界的12000预算，预览与确认保持一致；容量不足返回主要必需资料名称。已保留正文片段的稳定来源同时投影到确认的正文版本集合，排除片段不进入该集合。

## 智能整理来源

导入候选整理使用 `read_review_resolution_sources` 回读完整精确场景、`read_review_resolution_chapters` 回读边界核对章节，再按问题复用 focused retrieval。每份来源受小说、章节、当前草稿/hash 约束；较晚章节的支持不能使事实提前进入原场景。`read_review_resolution_evidence` 仅向作者返回对应范围内的当前整理结果，建议不是已采用事实。

## 统一知识治理

`compilation/knowledge` 拥有 capability 策略、scope/director/audit 版本化契约、组级治理与采用门禁。其他模块只经 `modules.evidence.contracts`/`facade` 消费；回执是派生审计状态，不代替 Writing/World/Story 的事实与采用所有权。

输出权限区分创作新增与既有事实断言：获准的候选设定、正文局部行动和对话不因尚未写过而
单独判无来源；抽取、问答、既有事实、角色知识及隐藏真相仍须有据。未知与明确待定保持开放，
不强迫作者补全无关维度。审查中生成者与权威资料完全相同时仅渲染一次，保留完整冻结输入。
审查逐段核对实际行动；候选声明不能豁免硬边界，也不能把支撑方案可执行性的自相矛盾计算
降为轻微问题。真正未给定的参数仍允许留白。
世界共创使用候选提案权限，资料问答 `world.ask` 仍为有据回答；共创中明确要求回答既有事实
时同样不得补造。资源总量约束覆盖所有人物与段落，私人存量与替代渠道不能凭空绕过限制。

## 协作成果投影

`TeamProjection` 和 `project_team_artifact` 校验接收者的项目、scope hash 和完整来源依赖。
来源依赖由宿主根据成员实际输入和读取记录构造，不使用模型自报的引用替代。依赖受限资料
的摘要不能发给未获授权的成员；拒绝消息不包含被限制的资料内容。

## 有界父级原文

原文回读可显式请求 `expand_parent`，按精确 Scene span 或命中段落补齐前后文，
逐段保留 Writing 来源和版本。角色知识无法证明时不扩展。原文检索抽屉展示覆盖和遗漏，
不把父级元数据当作已读正文；默认 AI confirmation 的读取范围不会自动扩大。

## 精确试改与前瞻资料

Evidence 为 Collaboration 收集授权的冻结资源集合，manifest 同时绑定命中与查询范围，
因此新增来源也能使旧否定结论失效。试改 read overlay 不读取当前领域默认版本；读者投影
只接收截止前正文。前瞻沿原 confirmation 重新物化选中与排除资产，领域只读回执不会扩大
原确认。生成和审查都受可完整核对的上下文上限约束，超限保持明确未覆盖。

## 创作任务的跨轮理解

跨轮理解的物化入口 `creative_manifest.py` 已随 AO-5 迁入 Collaboration 模块
（授权输入冻结、InputManifest 重验与理解附加归 collaboration 协议所有）；
Evidence 仍经 `inspect_novel_target` / `prepare_confirmed_ai_action` 提供原
confirmation 的选中/排除边界与目标可见性判定，理解的完整约束见
[模块设计](../../../docs/modules/21_collaboration.md)。

作者编辑台复用 `compile_review_world_evidence` 选择并精确回读本章作者可见世界资料，调用时
声明 `assistant.editorial` 且保留排除与截断说明。世界资料只送作者判断，不进入顺序盲读；
找不到或未选中的资料不得写成已核实事实。编辑意见不生成 Context confirmation 或正文采用回执。


## 逐源证据字段（B8）

`KnowledgeScopeReceipt` 的来源条目带逐源 `token_count`（item 级 tiktoken）、
`state`（included/trimmed/omitted）与 `state_reason`、`hash_basis`
（content=正文哈希 / identity=身份哈希）。账本 `to_dict()` 输出完整证据，
指纹只哈希稳定子集（`_fingerprint_dict`）；增加审计字段本身不改变指纹。
无来源原生 hash 时使用实际 ContextItem 正文；正文确实未关联才标 identity。
`token_groups` 保留实际文本块及逐出状态，多来源不可分文本块标 `shared=true`，
按 group key 去重计数，不能把共享块 token 逐源相加；独立 item 的数量合计入
`token_count`。预算逐出保留全部来源与原始计数，账本不保存正文。
