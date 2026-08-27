# 世界对象—世界书统一：项目适配研究记录

> 状态：八项 P0 语义与四项项目事实已收敛；ADR-0017 已接受，Phase 0 Spec、
> canonical fixtures、C0/head、封闭 resolver/receipt 回放、Preview/Admit/Revert 和 PageRevision
> documentary selection 已实现。所有 formal family 仍为 `formal-disabled`；本文不是当前
> API 或数据库权威文档。
>
> 最近更新：2026-08-27。
>
> 当前实现仍以 [`CONTEXT.md`](../../CONTEXT.md)、
> [`docs/00_整体设计.md`](../00_整体设计.md)、
> [`docs/01_数据库设计.md`](../01_数据库设计.md) 和
> [`backend/modules/world/README.md`](../../backend/modules/world/README.md) 为准。

> 上游理论研究由
> [`world-model-evolution-research.md`](world-model-evolution-research.md) 持续维护。该文档研究
> RBOS、LWCM、CWEM 与可解释世界演化；本文只记录这些理论如何影响本项目的产品语义、卡片
> 模型、世界对象—世界书统一和潜在知识平台架构。

## 1. 文档目的

本文记录以下方向的项目适配研究、裁定、实现交接和仍需在 ADR／Spec 明示的选择：

- 融合现有“世界对象”和“世界书”系统；
- 以世界书主页面作为作者端“人物与世界”一级入口；
- 将人物、地点、势力、物品、事件、规则、秘密和作者自定义空白类型统一为卡片式管理；
- 让统一系统既适合作者编辑，也可继续发展为完整的知识表示、百科查询、关系推导和叙事一致性平台；
- 消费 RBOS、LWCM、CWEM 及其后续理论研究结论，但不在本文重复维护理论模型本身。

本文维护产品方向、项目适配判断和候选长期语义边界。具体实现方案、schema、API、迁移和
发布计划必须在方向获得作者确认后，另行进入 Spec 和 ADR 流程。

### 1.1 与探索式研究账本的职责分工

| 文档 | 唯一职责 | 不在其中维护 |
|---|---|---|
| `world-model-evolution-research.md` | 探索世界模型本身：RBOS、LWCM、CWEM、因果演化、形式模型和纵向基准 | 当前项目的产品入口、卡片工作流、代码映射和落地裁定 |
| 本文 | 把理论研究映射到当前项目：统一卡片、正典编辑、知识查询、当前资产和潜在重构影响 | CWEM 等理论分支的完整推演和基准实验 |

后续若出现新的纯理论结论，先记入探索式研究账本；只有它改变本项目的产品或架构判断时，才在
本文追加“项目影响”。不得复制两份完整研究正文或各自维护一套同名基线。

## 2. 状态标记

本文使用四种状态，避免把研究候选误写成当前事实：

| 状态 | 含义 |
|---|---|
| 当前实现 | 已由当前代码、ORM、migration、稳定接口或权威文档证明 |
| 方向已确认 | 作者已明确认可的产品或研究方向，但尚未成为实现契约 |
| 研究结论 | 当前证据下较强的判断，允许后续研究推翻或修订 |
| 开放问题 | 尚未裁定，不能据此修改当前实现 |

“方向已确认”和“研究结论”均不自动取得 ADR 或当前架构文档的权威性。

## 3. 产品目标与用户价值

### 3.1 方向已确认

- 作者端以“人物与世界”作为统一入口，世界书主页承担主要浏览、检索、创建和整理工作。
- 不再要求作者先理解“世界对象”和“世界书页”两套后台模型，所有常用类型都以卡片管理。
- 支持作者创建没有预设强字段的空白类型；类型可以逐渐形成模板，而不是创建前必须完成 schema 设计。
- 不排斥把该领域继续发展为完善的知识表示和百科查询平台。完整关系推导、时间查询、视角查询、
  来源解释和一致性检查是允许研究的长期能力，不因其复杂而预先排除。

### 3.2 目标画像与体验假设

主要目标是画像 A：长期维护小说和幻想世界的作者。用户价值是：

- 在一个入口找回人物、事件、关系、历史状态、来源和相关页面；
- 卡片既可直接编辑，又能回答“何时成立、谁知道、读者何时知道、为什么得到这个答案”；
- AI 可以抽取、整理和发现冲突，但不能静默决定正史；
- 自由文本、结构化事实和历史版本能够共存，不迫使作者维护数据库式界面。

前端舒适度的当前假设是：首层只呈现作者能理解的卡片、正文、关系、时间和来源；命题 ID、
推导等级、证明图、完备性范围和内部真值只在查询解释、冲突处理或高级设置中渐进展开。
该判断仍需通过真实作者任务、重复使用和采用/撤销行为验证。

## 4. 当前项目基线

以下是 2026-08-27 已核对的当前实现，不是未来目标：

1. `CoreEntity` 是世界对象身份根；人物和事件是它的类型化扩展，其他高频类型使用 Profile，
   没有专属强表的类型可使用 Generic Profile。
2. `WorldBiblePage` 是可编辑、可发布、可修订的作者手册页面。当前契约规定页面组织和解释
   事实，但不拥有 CoreEntity、Profile 或 EntityRelation 等结构化事实。
3. `EntityRelation` 主要表达两个 CoreEntity 之间的有向关系，保存详细类型、最小关系类别、
   来源章节、引文、强度、状态和复核信息。
4. `Event` 保存来源章节、地点、时间顺序和时间标签；当前没有统一的有效时间、事务时间、
   多元事件角色或 Fluent 语义。
5. `CharacterKnowledge` 表达人物对目标对象的稀疏知识检查点，能够区分未知、传闻、部分了解、
   完全了解、错误信念和误解，但目标粒度主要还是对象，不是对象上的具体命题。
6. Reader Reveal、Knowledge Visibility、TargetRef、Evidence、Context Confirmation 和
   CompiledContext 已形成视角、来源、可见性和上下文选择基础。
7. Scene 是叙事结构的基础阶段；历史状态由带 Scene 锚点的 MemoryEvent 确定性重放，禁止用
   当前 World 状态补写过去。
8. 普通 AI 输出进入临时预览、工作稿或待处理建议；只有作者采用或持久化授权范围内的受控
   流水线才能写入允许的已采用资产。

当前 ADR-0006 仍规定“页面不是事实源”，World README 仍把独立知识图谱数据库列为当前范围
外。这些是当前实现约束；若后续正式采用本文研究方向，需要显式修订或取代相应决定，不能靠
实现代码静默绕过。

## 5. HCSM 第十七轮裁决：P0 与项目事实闭合，ADR／Spec 尚待接受

第十四轮停止扩张理论并执行物理 deletion test；第十五轮用最小反例撤回“可直接完成数据库／API Spec”的过早结论；
第十六轮集中闭合八项 P0；第十七轮再次对照当前代码，把四项物理前提收敛为 Proposed ADR、实施 Spec 与 fixtures。
当前裁决是：

> 八项 P0 已获得相互一致的唯一语义：`novel_id` 域、完整 manifest、内联 receipt、封闭 resolver、完整 claim 引用、
> 唯一 Admit、C0／单父／追加式 revert 和单向 family cutover。无需新增通用 Card、KR/RR、Statement、receipt 或
> AuthorityTransaction 表。四项项目事实已固定为首批两类 resource、account/task-attempt principal、代码内 policy registry、
> 三种 StatementValue、封闭 selector 与 stdlib canonical fixtures；Phase 2+ 仍须先接受 ADR-0017，再按 Spec 实现。

更准确的闭合关系是：

```text
receipt = Admit(Auth_at_commit, manifest(C))
Closed(K, receipt, C)
```

查询旧 CanonRevision 只验证其不可变准入证据，不读取当前账户权限。权限撤销只阻止未来提交，不追溯改变历史正典。
Assert、CanonRevision、head、receipt、Schema／policy 选择与 formal evaluator 的唯一正典作用域均为单部小说的
`novel_id`；当前物理 `projects.id` 即使承载该外键，也不取得第二套“项目正典”语义。

### 5.1 第十至十七轮对既有结论的删除与改写

| 既有结论 | 最小反例 | 当前裁决 |
|---|---|---|
| 作者签署 finite mapping 可证明 opaque prose 完备 | 同一可见文本和 mapping 同时兼容语义集 `A` 与 `A∪{b}` | 只能 assumption-backed；签名证明采用行为，不证明无隐藏含义 |
| 构成性 mapping 必然使正文 excluded | 作者要求正文直接授权事实、派生 Assert 可删后重建且不得独立修改 | 保留 A：text owns、total `φ` 定义其全部权威语义 |
| A 型 text owner 与 B 型 Assert owner 可互换 | 删除 text、撤回 mapping 或独立修订 Assert 时，两者结果不同 | 只保留普通 WorldEval 外延的条件等价，不宣称系统观察等价 |
| 构成性切分与 evidence-only 全面收敛 | A 中 immediate owner 是 text，B 中是 Assert | 只有 B 与 evidence-only 在 ownership 上收敛 |
| correspondence 必须新增核心记录 | mapping 与 source revision 同生共撤时没有独立生命周期 | 默认作为 typed value；只有整份 manifest 独立审阅／版本／撤回时复用既有 KnowledgeResource |
| AI Interpretation 可被引用后取得权威 | 同一 AI 候选未经作者封存也能改变旧 C | 禁止；普通候选在 Admit 内封入 AdmissionInputValue 并创建 Assert+C，只有被作者采用为独立文档资源时才使用专用 RR |
| 每个范围必须有一个 mapping-root 实体 | 一份 C 固定的 total manifest 已能唯一列出并 flatten 多个 partial revision | `coverageRoot` 只是值；要求唯一 compiled total coverage manifest，不新增 root 实体 |
| partial mappings 的字符覆盖可证明 totality | 标题“以下均为传闻”未映射，却改变所有句子的断言力 | 字符／片段 union 不证明语义穷尽；totality 只能由构成性 manifest 声明并检查 residual |
| hardGround 需要一般 Boolean 公式 | 两组替代依据可由两个同语义 Assert 分别保存 | flat set 固定为合取；替代依据使用多个 Assert，不新增 Boolean ground language |
| grammar／lexicon 变化都需要新 kernelVersion | 项目新增一个受控词汇并未改变形式化器规范接口 | 具体 grammar／lexicon 固定于 SchemaRevision；只有核心解释语义变化才升级 K |
| 每个 `(coverageRoot,n)` 必须恰有一个 owner | 两个独立来源可同时支持或冲突；total manifest 也可定义精确空扩展 | 只要求同一表示链状态唯一；独立多 owner 与 total-empty 合法 |
| 切换必须避免任何阶段的“零个 owner” | `Aset=∅` 且 total manifest 明确该范围权威扩展为空 | 改为避免 uncovered；closed-empty 不虚构 Assert |
| A→B 只要查询答案相同就是纯切换 | B 新增了另一时段、制度或依据失效的同内容 Assert | 必须在 regime、polarity、Statement、TimeScope、identity 与有效性条件上保持规范化双射 |
| A↔B 可沿用 canon closure certificate | direct owner、S/F 证据、support identity 和 explanation 都改变 | 旧 acceptance／closure 不复用；最多运输对象层 proof skeleton 并在 C2 重放 |
| 权威切换需要 AuthorityTransaction | sealed candidates + 新 C 的完整 manifest + 单次 Admit 已提供原子边界 | 删除新记录；事务是 CanonRevision 准入 judgment |
| 四类 explanation edge 需要持久化 | 都能从 owns、hardGround、cite／DocCanon 和 formalizer／Assert 推导 | DirectAuthority、UltimateGround、DocumentarySource、ExecutableSupport 保持派生 |
| 回滚可原地恢复旧 C | head 后退后再次提交会隐式形成 v1 不支持的分支，原地修改还会使历史 receipt 漂移 | v1 历史浏览不移动 head；回滚只能追加选择旧状态的新 revert CanonRevision |
| `SchemaCompat(S1,S2,Need)` 足够 | 类型收窄可对当前正值兼容，却对未来负值不兼容 | 增加 `canon-pair | universal` 量化范围与 exact evidence |
| diff 不在 S1 旧 dependency slice 就安全 | S2 新增以所需 family 为 head 的规则或 owner surface | 在 S1、S2 分别求闭包并取并集，还要检查所有新入边 |
| 类型拓宽天然向后兼容 | 新 enum member 会改变 domain、absence、unique 和 exact count | compatibility 按 claim 分解；一个 positive witness 保持不代表闭合查询保持 |
| 字段重命名只需名字映射 | selector、ownership、hardGround、normalization 或 family 同时改变 | 声明式 translation 必须 total 且保持全部 required obligations |
| 新 Schema 可直接沿用旧 acceptance／closure | certificate 仍绑定 exact SchemaRevision 与旧上下文 | 只运输 proof skeleton；C2 重新 replay 并签发新 acceptance／closure |
| compatibility 需要新核心记录 | judgment 和 translation evidence 可内联 proof，需复用时进入既有 ResourceRevision | 删除 SchemaCompatibility／MigrationMap 核心记录 |
| 空白类型可以完全没有 Schema | 系统无法判断任意 extension 是资料、事实 owner 还是未知 surface | 必须有 minimal generic documentary BaseSchema；无类型专属模板不等于无 Schema |
| blank card title 自动是 Referent Name | 资料页标题可以只是作者导航标签，复制卡片也不决定世界身份 | title 默认 documentary；Referent／Name 由明确 entity-bearing policy 或 promotion 创建 |
| CreateTemplate／AdoptSchema／PromoteHistoricalContent 可合并 | 只建模板就让旧 `age="30"` 变成事实 | 三个作者行为严格分离；前两者默认不改变旧 WorldEval |
| parser 成功等于事实提升 | `"约三十"` 可解析成 30、区间、模态或人物观点 | parser／AI 只产生 candidate；作者以新 C 明确选择 A/B |
| default 可自动补历史缺值 | `missing alive` 因新 default 变成 `Alive=true` | default 默认仅构造预填；历史 absent-value semantics 属于显式 promotion |
| bulk promotion 可静默跳过失败项 | 100 张卡中 3 张失败却只采用 97 张，作者误以为完整 | 批次成员 exact；整批拒绝或作者重新确认 exact subset，不得静默部分成功 |
| DynamicType／TemplateBinding／FieldValueRevision 必需 | Schema RR、Card RR、compiled SchemaOfC 和现有 workflow candidate 已覆盖生命周期 | 删除所有新增 lifecycle core record |
| 六项职责必须各建一张通用表 | 现有 WorldBiblePageRevision、TextArchive、MemoryEvent 等历史有不同回滚／重放语义 | 六项是逻辑职责；保留专用物理历史，禁止万能 ResourceRevision |
| Card 需要统一持久表 | 页面、实体和 Profile 已有稳定身份，UI 只需 tagged union 与统一动作 | Card 保持 read model，不新增 `cards` |
| KnowledgeResource 需要总表 | `{resource_kind,resource_id}` 封闭引用与现有域 head 足够 | 不新增 `knowledge_resources`；准入时验证 kind、ID、novel 与 exact revision |
| Statement 首版需要独立表 | v1 只需 Name、typed scalar、binary relation，且不需要引用未断言内容 | 内联自包含 `StatementValue`；digest 只校验／去重，含 StatementRef 的 kind 未实现可解析引用前一律拒绝 |
| StatementRef 只需引用 StatementValue | “第 20 日否认第 10 日仍存活”还需要内层 regime、polarity 和 TimeScope | StatementRef 内联完整惰性 ClaimValue；外层 Assert 与内层 claim 分开求值 |
| receipt 只需一个 committer | 作者决定、worker 执行时单字段必然丢失一方 | 分离 authorizing principal 与 executing principal；C0 使用封闭 bootstrap subject |
| revert 可复制任意旧 manifest | 复制 pre-cutover C 会把 canon-owned family 退回 legacy authority | v1 cutover 单向；跨 cutover exact revert 拒绝，只能在当前 authority 下重建旧内容 |
| Canon 可由各表 `status=canonical` 拼出 | mutable Profile／关系更新会追溯改变旧答案，批量采用也无原子快照 | 必须新增 immutable CanonRevision + mutable CAS head |
| EntityRelation／Profile 可直接当统一 Assert | 缺负极性、regime、统一时间、不可变版本和 Canon 选择 | 新增窄 `world_assertions`，legacy 行在 family cutover 后只作编辑头／投影 |
| WorldBiblePageTemplate 可兼任事实 Schema | 页面布局与事实字段语义可以独立修订 | 保留页面模板职责；为 EntityProfileTemplate 增加专用 revision |

### 5.2 已核验的理论边界

- 正向 Datalog 的最小不动点在有限模型上可构造，但加入 negation 后需要不同语义，不能沿用简单单调结论。
  参见 Abiteboul、Hull、Vianu 的 [Foundations of Databases](https://lsv.ens-paris-saclay.fr/~goubault/BD/abiteboul-vianu-foundations-of-databases.pdf)。
- 事件演算明确使用 negation as failure 表达惯性；新终止事件会非单调地撤回默认结论。
  参见 Kowalski、Sergot 的 [A Logic-based Calculus of Events](https://www.cs.brandeis.edu/~cs112/cs112-2004/newReadings/Kowalski-Sergot.pdf)。
- Lamport 的 happens-before 是因果偏序；其兼容总序需要任意打破不可比事件的平局，不能直接解释为小说世界的
  物理时刻、同时性或作者分支。参见 [Time, Clocks, and the Ordering of Events](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)。
- order-incomplete 数据可用部分序的线性扩展定义 possible／certain answers，并需用 occurrence ID 区分值相同的
  重复项；该模型不含同刻、事件效果或惯性，本文不能直接继承其复杂度结论。参见 Amarilli 等人的
  [原始论文](https://drops.dagstuhl.de/storage/00lipics/lipics-vol090-time2017/LIPIcs.TIME.2017.4/LIPIcs.TIME.2017.4.pdf)。
- Allen 的区间关系提供定性区间推理基础，但不直接规定本文的半开区间或模态轨迹；Dechter、Meiri、Pearl
  以时间点和差分约束定义 TCSP，并只对 STP 片段证明多项式求解。参见
  [Allen 1983](https://cse.unl.edu/~choueiry/Documents/Allen-CACM1983.pdf) 和
  [Temporal Constraint Networks](https://doi.org/10.1016/0004-3702(91)90006-6)。
- Event Structures 需要在偏序之外增加 conflict／enabling 才能表达真正互斥的事件存在；这支持把 chronology
  未知与作者分支分开，但不证明本项目应采用完整 Event Structure。参见 Winskel 的
  [原始讲义](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-95.pdf)。
- RDF 1.2 的 triple term 提供“引用一个命题但不自动断言它”的设计先例，支持 StatementRef 与真值效果分离；
  它目前是 W3C Candidate Recommendation，只作为设计参照。参见 [RDF 1.2 Schema](https://www.w3.org/TR/rdf12-schema/)。
- Web Annotation Selector 提供片段定位而非语义继承，PROV 谱系也不等于语义保持。参见
  [Web Annotation](https://www.w3.org/TR/annotation-model/) 和 [PROV Constraints](https://www.w3.org/TR/prov-constraints/)。
- 一般 Datalog 查询等价仍不可判定。参见 Shmueli 的
  [原始论文](https://lat.inf.tu-dresden.de/teaching/ss2014/Seminar/Papers/EquivalenceOfDatalogUndecidable.pdf)。
- 开放数据的否定和穷尽答案需要范围化完备性依据。参见 Darari 等人的
  [查询完备性研究](https://doi.org/10.3233/SW-190344)。
- Levy、Rajaraman、Ordille 证明了声明式 source descriptions 可用于组合异质结构化来源；这支持把来源目录与查询
  规划分离，但不证明描述真实、来源有正典权威或自然语言已完备。参见
  [Querying Heterogeneous Information Sources Using Source Descriptions](https://www.vldb.org/conf/1996/P251.PDF)。
- RDF 1.2 Semantics 明确不规范 IRI 与自然语言等其他媒介之间的社会性对应；它支持“形式图不能自动证明正文含义已
  覆盖”的边界，但不规定 HCSM 所有权。该文档当前是 W3C Candidate Recommendation。参见
  [RDF 1.2 Semantics](https://www.w3.org/TR/rdf12-semantics/)。
- SHACL 的固定输入验证报告可作为“被验证内容不能自称通过”的规范先例，但不直接证明本文证书设计。
  参见 [SHACL](https://www.w3.org/TR/shacl/)。
- Attempto Controlled English 展示了受控自然语言可以通过受限 grammar 取得非歧义形式语义；它不证明任意小说正文、
  隐喻、讽刺或作者语用可以总解析。参见 Fuchs、Kaljurand、Kuhn 的
  [ACE 研究](https://attempto.ifi.uzh.ch/site/pubs/papers/fuchs2003reasoningIn.pdf)。
- RFC 5147 的 text/plain fragment identifier 只解决精确文本版本内的字符／行定位，并明确暴露内容变化后的定位脆弱性；
  它不授予片段语义，也不证明跨版本 correspondence 保持。参见 [RFC 5147](https://www.rfc-editor.org/rfc/rfc5147.html)。
- Proof-Carrying Code 证明了“不可信生产者携带证明、可信消费者按预先固定政策检查”的可行架构；本文只借用信任
  分离，不把其机器码安全性结论移植到正典查询。参见 Necula 的
  [原始论文](https://doi.org/10.1145/263699.263712)。
- LRAT 展示了 SAT refutation 可由独立、形式认证的检查器重放；Alethe 展示了 SMT 证明交换格式、规则粒度和
  elaboration 的现实边界。二者支持“solver 输出不是 verdict”，但不证明 HCSM 的编码或 checker 正确。参见
  [Efficient Certified RAT Verification](https://findresearcher.sdu.dk/ws/portalfiles/portal/141252237/Efficient_Certified_RAT_Verification.pdf)
  和 [Alethe](https://www.verit-solver.org/papers/pxtp2021.pdf)。
- Cook—Reckhow 研究的是命题证明系统及最短证明长度的相对效率；它支持“不应预设所有证明都有多项式长度”的边界，
  不能直接给出 HCSM 证书下界。参见
  [The Relative Efficiency of Propositional Proof Systems](https://www.cs.toronto.edu/~sacook/homepage/cook_reckhow.pdf)。

### 5.3 无法靠增加记录类型消除的边界

1. 未形式化正文仍属正典、AI 解释没有正典权威、形式查询对全部正典自动完备，三者不能同时成立。
2. 任何可执行语义都依赖元语言、解释器和授权边界；不存在脱离这些外部根的绝对闭合。
3. 一般 Statement／Datalog 程序／Schema 升级语义等价不可通用自动判定。
4. 没有来源闭合和形式化覆盖证明，开放正文不能可靠回答“没有其他”。
5. 自然语言语用、正典合并意图和人物真实心理只能生成候选或由显式作者输入决定。
6. 受限 TemporalTheory 只能表达时间赋值不完整；事件是否存在、作者本体多时间线和一般对象层析取不能偷塞进
   chronology Scenario。
7. 有限可判定不等于多项式可求、可扩展或存在短证书；枚举 `n` 个独立局部选择可产生指数轨迹，但这不是所有
   证明系统的普遍指数下界。
8. 因果顺序与世界时间顺序必须分离；普通逆时因果不自动要求多时间线，真正本体分支也不能压成一个时间偏序。
9. checker、规范化器和精确算术仍在可信计算基中；证明重放不能证明检查器自身无 bug，同 K 的实现修复也必须让
   旧 acceptance cache 失效。
10. 形式输入上的 complete 不等于异质正典 complete；在来源所有权、形式化覆盖和身份域尚未闭合前，全小说范围
    最多是 assumption-backed 或 incomplete。
11. 机器能证明作者选择了某个构成性权威政策，不能证明该政策忠于作者未表达的意图，也不能把描述性完备声明变成事实。
12. arbitrary prose 若继续保留映射外的独立正典含义，任何有限抽取集都不能通用证明 F machine-closed；要么限制
    语言，要么构成性收束该 surface 的权威语义，要么把文本降为 evidence／documentary owner。
13. 作者确认 correspondence 只证明采用了这个 correspondence；若正文仍允许 mapping 外权威含义，它不能证明
    `FormalCover`，也不能把 assumed 升级为 machine。
14. 构成性形式化 text owner 与 Assert authority substitution 可以对普通 WorldEval 条件等价，但 immediate owner、
    撤回和删除语义仍不可由查询外延恢复；产品若要回答“谁直接授权该事实”，必须保留该区别。
15. selector 的字符覆盖不是语义覆盖。跨段否定、引语、传闻框架和篇章级语气即使不占独立句子，也可能改变多个
    Assert 的 regime 或 polarity；totality 必须是规范性定义，不是覆盖率启发式。

## 6. HCSM 第十五轮收敛语义内核

以下是逻辑职责和不变量，不是一表一类的数据库草案。

### 6.1 六项不可缺少的语义职责

| 语义职责 | 当前逻辑载体 | 不拥有 |
|---|---|---|
| 世界指称物身份 | `Referent` | 页面正文、当前状态快照和 AI 候选 |
| 知识资源身份 | `KnowledgeResource` | 世界对象身份和某一版本内容 |
| 不可变资源版本 | `ResourceRevision` | 跨版本可变片段身份 |
| 可独立引用的命题内容 | `Statement`；v1 为自包含不可变值 | 制度、极性、正典性、真值和来源 |
| 有身份的断言 | `Attestation = Assert` | 外部提交权限、自定义 force 和内容自动为真的资格 |
| 不可变正典输入清单 | `CanonRevision` | 派生闭包、当前状态快照、缓存和查询 verdict |

六项是职责，不是已证明最小的物理记录数。`TargetRef`、`Predication`、`StatementRef` 和 `TimeScope` 是值；
Schema、规则、世界规范、Proposal、Interpretation 和证明制品复用 KnowledgeResource／ResourceRevision；
Branch 是工作流指针；Card 是作者工作空间。

### 6.2 最小元内核、历史准入与 CanonRevision 闭合

当前经过 deletion test 的最小 `K` 规范职责是：

| K 职责 | 不可下放部分 |
|---|---|
| `TypedSyntax` | 有限类型、StatementRef、规则安全片段和静态拒绝条件 |
| `MetaFence` | 项目内容不得访问 Eval、verdict、授权、规则反射或动态解引用 |
| `AssertSemantics` | world／belief 两种制度、显式正反极性及其隔离 |
| `CanonClosure` | 精确引用、semantic surface／ownership contract 语法、硬依据闭合、历史准入证据与 manifest 绑定 |
| `TemporalEvaluation` | TimeScope、受限 TemporalTheory、边界转移、模态轨迹、冲突和时间未定状态 |
| `ProofVerdictSemantics` | proof judgment、有限 observation basis、可信重放、假设／残差和三类依赖的判定规则 |
| `KernelVersioning` | 旧 C 固定规范语义和跨 K 比较边界 |

这七项只是当前 deletion test 稳定的规范职责，不是唯一数学分解。项目 Schema 可以定义谓词、query family、
目标域、surface 枚举、ownership clause、persistent 标记、世界制度规则和事件效果，但不能改变上述解释边界。

`kernelVersion` 标识规范语义，不绑定二进制、部署版本或具体 checker build。规范不变的实现修复仍按同一 K
重新验证旧证明并使旧缓存 verdict 失效；规范行为改变才产生新 K。若旧 K 暂无可用合规实现，返回
`unsupported-kernel`，不得用 K2 猜测解释 C1。

正典作用域只有 `novel_id`。Assert、CanonRevision、Canon head、receipt、Schema／policy 选择、hardGround、
documentary source 和 formal evaluator 的所有引用必须属于同一 `novel_id`；上层 Project 若存在，只是组织容器。

CanonRevision 固定该小说在该版本下的**完整正典输入映射**，不是针对某次查询选取“必要输入”。其 compiled manifest
必须能唯一还原：每个活动 KnowledgeResource 到一个 exact immutable ResourceRevision 的选择或显式 inactive、selected
Assert 的完整集合、exact Schema／规则／policy／Calendar／kernel 引用，以及所有参与有效性的 exact hardGround、
correspondence 与 source revision。活动资源映射决定 DocCanon／Schema／policy；另列的 pinned dependency refs 可以指向旧
revision 作为 hardGround／cite／provenance，但不因此成为活动 DocCanon。其 closure 可以确定性编译和校验，不能独立编辑。
物理上允许 delta／压缩，但只能依赖 C 本身及不可变单父历史重建；未进入 active map 或 pinned dependency refs 的资源
不属 C 的任何输入，只有 active documentary resource 才满足 `DocCanon(C, ·)`。World Bible 发布必须 seal exact
PageRevision 并原子创建选择它的新 C；legacy published head 只可作为
工作流指针或可重建投影，DocumentSearch(C) 和旧 C 重放不得读取它。

提交时，当前 Auth 对 manifest、novel、权限范围、审批政策、作者决定主体和执行主体作出不可变准入判断。不新增 receipt 表，但
实施 Spec 必须内联这一不可变值，并至少固定 `novel_id`、`canon_revision_id`、完整 manifest digest、`decision_id`／
`decision_digest`、authorizing principal、executing principal、提交动作、affected families/resources、exact
authorization-policy ID／version／digest、allow decision、提交时刻和 CAS `expected_previous_head`。作者决定与执行主体可以
相同，但 worker 不得被伪装成作者；C0 使用封闭 bootstrap subject。不得依赖可变日志、当前角色或未版本化“授权摘要”。
查询只验证 receipt 与历史 manifest，当前访问权限仍只控制“谁现在能读”。

`Closed(K, receipt, C)` 还要求：所有引用精确、有限、不可变、可解析且同 novel；每个活动资源至多一个版本；
TargetRef 不指向 latest／head；Schema 与 hardGround 可获得；Assert 类型与时间有效；规则通过 MetaFence；v1 parent 为
`0..1`；receipt 与 novel、manifest、expected head 和当时 policy 匹配。

### 6.3 工作稿、断言、采用与 Canon head

```text
Mutable Draft ──seal──> ResourceRevision
Mutable AI／parser candidate ──preview validate──> non-authoritative judgment
explicit author adoption
  ──seal exact AdmissionInputValue + authoritative validate + single Admit transaction──>
    immutable Assert(s) + CanonRevision + inline receipt + head CAS
```

- Profile “保存即生效”可是一项产品操作，语义上仍是封存版本并原子提交新 CanonRevision。
- preview validation 只证明候选在某个 exact 上下文符合受限语法：不创建 `world_assertions`、不移动 head，也不允许候选
  成为 authoritative hardGround。作者决定必须内联封存 exact candidate／subset／source／目标变化与 expected head；Admit
  对该不可变值重新做 authoritative validation。现有 mutable `CreationSuggestion` 不能直接冒充 ResourceRevision。
- 只有明确的作者采用动作创建 Assert 与 C；后台服务可以执行已持久化授权，不能从置信度、验证成功或浏览行为推定采用。
- AI、人物和文档作者都不进入 Assert 的权威字段；若保留来源演员，只能命名为 audit-only
  `provenance_actor_ref`，WorldEval／BeliefEval／closure 不读取它。authorizer、executor 与授权只存在 receipt。
- 撤回由新 C 不再选择旧 Assert 表达；局部撤回用区间拆分，规则例外用显式事实或新规则版本。Defeat 不在最小 K。
- v1 每部小说只有一个 head，CanonRevision parent 为 `0..1`；历史浏览不移动 head，回滚追加一个以当前 head 为父、
  显式重选旧状态的新 revert C。`formal-disabled → canon-owned` 是单向 family authority 迁移；若目标 C 早于某 family
  cutover，exact revert 必须拒绝，作者只能在当前 authority 下用新 Assert 恢复旧内容。命名 branch、多 head、多父和
  merge 在另立 Spec 前一律拒绝。

### 6.4 Card 与最小资源边界

内容单元只有在需要相对于相邻内容独立保存版本、进入正典、撤回、恢复、分支、合并、追踪来源或被引用时，
才成为独立 KnowledgeResource；否则只是同一 ResourceRevision 内的 TargetRef。

Card 继续聚合 Referent、Profile、World Bible 正文、关系／事件断言、AI 审查和只读视图，但不是语义内核、
世界对象或最小正典单元。不得给整张 Card 设置一个 text-led／structure-led／dual 模式：同一卡片的不同
query family 和 semantic surface 可以分别由正文、结构、双方或双方都不拥有。AI 审查、编辑备注、检索摘要和
派生镜像默认没有独立世界真值权威，不能因位于 Card 内而升级。

### 6.5 唯一 Assert 与行为内容隔离

```text
Assert {
  regime: world | belief(ReferentID)
  polarity: positive | negative
  content: immutable self-contained StatementValue
  timeScope: TimeScope
  hardGrounds: finite set
  cites: finite set
  provenance: non-semantic value
}
```

Assert 没有 issuer、speaker、reporter、proposer、interpreter、committer 或可扩展 force。v1 Statement 的 canonical
identity 覆盖 `statement_kind`、statement version、exact SchemaRevision 和 canonical payload；digest 只用于完整性校验
与字面去重，不承担存储，也不证明一般语义等价。

人物和机构行为在长期模型中是普通 ground Statement：

```text
Uttered(甲, StatementRef(S))
Reported(乙, 甲, StatementRef(S))
Dreamed(甲, StatementRef(S))
Promised(甲, 乙, StatementRef(P))
ContainsClaim(文档D, StatementRef(S))
```

StatementRef 是完整、惰性的 ClaimValue，而不是裸 Atom 或 Assert ID：

```text
StatementRef {
  regime: world | belief(ReferentID)
  polarity: positive | negative
  statement: immutable self-contained StatementValue
  timeScope: TimeScope
  canonicalDigest
}
```

内层 claim 的 regime／polarity／time 与外层行为 Assert 完全独立；因此第 20 日的 `Uttered` 可以引用“world／negative／
Alive(国王)／day10”，而不把该 claim 断言为真或归因于说话者信念。项目规则不得用通用 `Eval(ref)`／`Holds(ref)` 解引用。
digest 覆盖完整规范化 claim 及所有嵌套值，只作完整性校验与字面去重；嵌套必须有限无环。

v1 不提供独立 Statement registry，也不允许裸 digest 或指向某个 Assert 来间接取得内容。若 wire 未实现完整 claim，v1
直接拒绝 `Uttered`、`Reported`、`Dreamed`、`Promised`、`ContainsClaim` 等含 StatementRef 的 kind；真实需求出现后重新
执行 Statement 表 deletion test。
制度性话语由项目固定规则从行为事实派生 Obligation、AtWar 等效果，不反射任意内容。

hardGround 决定失效传播，cite 只提供证据导航，derivedFrom 只记录生成谱系，provenance 永不授予真值。

### 6.6 受限 Statement 与规则语言

当前保守候选只允许 ground Atom 作为持久 Statement；Atom 参数来自固定有限 Sort，包括 Referent、StatementRef、
TimePoint、Scalar 和 Enum。规则无函数符号、无存在量词头、range-restricted、只允许正依赖递归，显式 `-p`
是独立有符号关系而非 negation-as-failure；禁止谓词变量、高阶量化、动态规则、脚本、AST 反射和 StatementRef 解引用。
命名时间变量、锚点和约束必须已由 C 固定，规则不得递归生成新时间；聚合只在闭包后的查询层执行。

TemporalTheory 是 `TemporalEvaluation` 唯一额外解释的受限值语法，不开放一般 Statement 逻辑：

```text
TemporalTheory := Scenario₁ ∨ ... ∨ Scenarioₙ       // 显式有限 DNF
Scenario       := finite conjunction of
                  Eq | Lt | Neq | Within | optional STP difference constraint
```

`Neq(t,u)` 表示“确知不同刻但先后未定”，是必要表达能力，但可作为 `Lt(t,u) ∨ Lt(u,t)` 的语法糖，
不要求独立核心类型。`Within(t,[a,b))` 复用既有半开 Interval 表示粗粒度时间窗；“同日”只约束两个时刻都在
同一日窗内，不推出 Eq。Calendar 及单位语义由 C 固定的资源给出。Scenario 析取只表达同一个 C 中相关的
chronology 未知，不获得 Hypothesis、CanonBranch 或本体时间线身份。禁止量词、递归公式、动态时间生成和脚本。

在固定有限输入上，局部正向规则阶段形成有限 signed Herbrand base，可用最小不动点终止求值。该结论不覆盖惯性，
也不推出一般程序等价或 Schema 迁移可判定。完整 Belnap 联结词没有被定义，本文只主张正负支持形成
true-only、false-only、both、neither 四种观察状态。

长期模型中的独立 Statement 可使用不透明稳定 ID；v1 只保存不可变、自包含的 StatementValue。两者都禁止原地修改
内容或 SchemaRevision；内容哈希只发现字面重复候选。
TargetRef 只在不可变 ResourceRevision 内稳定；跨版本重锚定只生成候选谱系，不自动继承语义。

### 6.7 TimeScope、TemporalTheory 与模态轨迹

```text
TimeScope = Timeless
          | Point(time, pre | at | post)
          | Interval(startBoundary, endBoundary)
```

同一时间满足 `pre(t) < at(t) < post(t)`；Interval 是边界序上的半开区间且 start < end。Timeless 表示该命题
没有 world-time 维度，不等于从负无穷持续到正无穷；时间未知的可变事实不得误标 Timeless。瞬时话语与事件使用
Point(t, at)，事件效果默认从 post(t) 开始。裸时间查询必须选择相位或由查询类型唯一决定。

一个时间实现 `ρ` 为每个命名时间变量赋予同一有序时间域中的值，并满足某个 Scenario；定性片段允许不同名字
映射到同一时刻，因此对应总预序而非严格线性扩展。occurrence 身份与时刻相等永久分离：两个事件可同刻但仍是
两个 occurrence。所有合法实现记为 `Ωtime(C,H)`；若为空，返回 `invalid-temporal-frame`，不得利用空集全称
把任意结论伪造为 necessary。

粗粒度日期由 `Within(time(e), [dayStart, nextDayStart))` 表达；没有形式边界的“初春”“傍晚”只使 F 不足。
精确 duration 只有在固定 metric/calendar 和单位下，TemporalTheory 在所有合法 metric realization 中蕴含
同一差值时才 verified；纯顺序只能回答定性关系。STP 的符号求解只作为受限候选，不把无限多个数值赋值枚举成记录。

固定 `ρ` 后，每个同边界、每个有符号 fluent `ℓ` 使用以下局部转移关系。guard 只读取边界前状态；`χ` 从非单值
后继集合中选择一个合法结果，但不保存或伪造事件排列：

| prior carry | Start(ℓ) | Stop(ℓ) | carry successor |
|---|---:|---:|---|
| inactive | 无 | 无 | inactive |
| active | 无 | 无 | active |
| 任意 | 有 | 无 | active |
| 任意 | 无 | 有 | inactive |
| 任意 | 有 | 有且无显式 subphase | `{active, inactive}` |

多个同类 Start／Stop 不增加结果数。无法确定 Stop 的 target 或 guard 时是 Schema／F 不完整，不允许 `χ` 猜测。
直接 Interval Assert 是独立支持，Stop 只终止对应惯性链；产生反面事实必须显式 Start 反极性。
`Start(+p)` 与 `Start(-p)` 分属两个有符号 fluent，同时 active 才形成同轨迹正典冲突。

完整求值轨迹为：

```text
w = (ρ, χ, Traceρ,χ)
Ω(C,H) = {w | ρ ∈ Ωtime(C,H) and χ is a legal local transition choice}
```

每条轨迹读取直接 Assert、求边界前正向闭包、应用事件效果、携带未被适用 Stop 终止的惯性支持，再求局部正向闭包。
惯性同时依赖起始支持、相关区间内不存在 Stop 以及 Stop 来源范围闭合，所以对新增输入非单调。

对每个有符号查询分别定义：

```text
Necessary(ℓ,q)  iff Ω ≠ ∅ and every w in Ω supports ℓ at q
Possible(ℓ,q)   iff some w in Ω supports ℓ at q
Impossible(ℓ,q) iff Ω ≠ ∅ and no w in Ω supports ℓ at q
```

`Impossible(+p)` 不等于 `Necessary(-p)`。同一轨迹同时支持正负才是 canon conflict；固定 `ρ`、不同 `χ`
改变结果可见 transition variance；但不同 `ρ` 上各取一条不同答案轨迹，并不足以证明 temporal variance。必须先定义：

```text
Out(ρ,q) = { Ans(ρ,χ,q) | χ is legal under ρ }

TransitionUndeterminedExists(q) iff some ρ has |Out(ρ,q)| > 1
TemporalUndeterminedExists(q)   iff some ρ₁,ρ₂ have Out(ρ₁,q) != Out(ρ₂,q)
```

裸 `transition-underdetermined` 当前只指存在式；若未来需要“每个时间实现都受局部转移歧义影响”，必须另证全称版本。
两种 variance 可以同时成立并分别报告 true／false／unproved；未找到见证只能得到 unproved，false 需要全域排除证明。
不同 H／CanonBranch 始终分开求值，不同轨迹的正负也不得并成 `both`。

`before/after/overlap` 对端点关系逐轨迹求值；`throughout` 量化区间内所有诱导状态 cell，`sometime` 量化至少
一个 cell。`∀w∃t` 不等于 `∃t∀w`。`first/last` 返回最小／最大 occurrence 集，并分别表达
possible-first、necessary-cofirst 和 unique-first；并列最早不自动选择一个对象。因果、ReaderAccess 和章节顺序
不产生时间边：普通时间旅行可有 `Arrival1900 < Departure2100` 同时 `Causes(Departure, Arrival)`；只有作品明确
让多条互斥历史在世界内同时存在时，才需要本体 timeline 维度，不能伪装成 chronology 未知。

### 6.8 两个真值求值器、一个覆盖层和两个非真值机制

| 机制 | 职责 |
|---|---|
| `WorldEval(K, C, timeScope, H, q)` | 返回 world 制度下正反支持、冲突、时间未定、证明与完备性 |
| `BeliefEval(K, C, timeScope, holder, H, q)` | 从 belief(holder) Assert、认知事件和显式规则求值，不读取客观世界全部真相 |
| `Hypothesis H` | 叠加于求值器的带标签假设集，结果不写回正典 |
| `ReaderAccess(C, path, position)` | 返回已展示 TargetRef、Reveal 和叙事顺序，不判断理解或相信 |
| `DocumentSearch(C, scope, query)` | 返回资源、TargetRef、相关度和非权威 AI 解释，不产生形式真值 |

StatementRef 不自动求值；说出不推出相信，报告不证明原来源，信念不推出世界为真，世界为真不自动进入人物知识，
读者访问不进入人物信念，假设结果不进入正典。任何例外都必须经过 C 固定的显式规则。

### 6.9 四项查询义务、证明 calculus、三类依赖与相对化 verdict

| 义务 | 问题 |
|---|---|
| 来源范围闭合 `S(Σ,J)` | 对具体 claim 的 witness 与 invalidator，全部有权影响它的 semantic surface 是否明确 |
| 语义覆盖充分 `F(Σ,J)` | 已知 owner 的日期、模态、效果 target、引语和断言力是否完整进入形式输入 |
| 身份闭合 `I(Σ,J)` | claim 所需别名、occurrence、same／different、时间身份和枚举域是否解决 |
| 求值执行完整 `X(Σ,J)` | TemporalTheory 一致性、相关 Scenario／时间实现／χ、规则闭包和证明搜索是否完整且未被预算截断 |

证明必须分开五层，禁止把其中任一层的“成功”直接冒充最终 verdict：

```text
object semantics:     Σ ⊨ J
calculus derivation:  Σ ⊢ P : J
implementation:       Check_build(Σ,P)
closure components:   required S/F/I each machine | assumed | open
product verdict:      formal-relative | canon-relative | assumption-backed | incomplete | invalid
```

其中 `Σ=(K,C,H,q,scope,regime,TimeScope)`。proof header 必须固定 normalized query 和一个完整不可变的
`interpretationContextDigest`，覆盖 TemporalTheory、Calendar／unit、Schema、occurrence identity、规则／effect、
phase 与规范化语义。任一组成变化默认使整份证明失效；若想跨解释上下文复用，必须另给 K 认可的语义兼容证明。

证明制品仍复用 ResourceRevision，并区分三类世界答案依赖：

- `supportDeps`：实际使用的正向依据；
- `antiDeps`：一旦新增就会推翻答案的模式和范围，例如惯性区间内的 Stop；
- `closureDeps`：证明 antiDeps 搜索空间完整的资源、Schema 和范围政策。

不新增 `interpretationDeps`：三类依赖解释对象层答案为何受 C1→C2 影响，完整解释上下文负责保守失效。
`lemmaDeps` 和 `replayContext(proofFormatVersion, checkerBuild, normalizerBuild, conformanceEpoch)` 是证明／验证元数据，
不是世界语义。最小 proof 可以完全 inline；只有共享或外部 lemma 才需不可变 digest、上下文匹配和 DAG 无环检查。

各 claim 的最小 proof obligation 为：

- possible：一个合法 `(Scenario,ρ,χ)` 与 checker 重算得到的答案见证；payload 中自报的 Trace 和 verdict 不可信；
- necessary：一个 `Ω≠∅` 见证，加 `Legal ∧ ¬q` 的可重放反驳或等价的完备覆盖证明；
- impossible：一个 `Ω≠∅` 见证，加 `Legal ∧ q` 的可重放反驳或等价的完备覆盖证明；
- transition variance：相同 `ρ` 下两个合法 `χ` 产生不同答案；
- temporal variance：对某个结果 `v`，给出 `v∈Out(ρ₁,q)` 的成员见证，以及固定 `ρ₂`、穷尽全部合法 `χ`
  的 `v∉Out(ρ₂,q)` 反驳；仅有两个不同答案轨迹不够。

producer、solver、作者、AI、普通 Statement 和 proof payload 全部不可信。K 定义规则，checker 重新验证精确有理数、
严格边界、Scenario 和局部选择；solver 的 UNSAT 字符串、缓存命中和旧 acceptance 均不是证明。

当前 calculus 的 universal proof 采用显式 case-refutation 候选：对有限 Scenario、时间关系、metric bound、`χ` 和
guard 分裂；叶要么携带差分约束不可满足的可检查负环，要么证明 query answer 在整个叶区域恒定。safe leaf 禁止只取
代表 metric assignment，必须对所有查询相关 observation 原子逐一证明蕴含其真或假，再符号重放求值器。

有限 observation basis 至少包含规则／effect／惯性／query 读取的时间比较、局部转移选择、有限 signed Herbrand
base、相关身份分区，以及 throughout／sometime／first／last／duration 所需比较。只有规则和查询不能动态产生时间点、
阈值或 occurrence，且 Calendar 可归约为有限窗口和有理差分谓词时，同 observation vector 才蕴含相同求值。
因此当前只得到**条件式构造性 completeness 候选**：仍需把 Normalization adequacy 与 Calendar reduction adequacy
写成 K 的精确规范并证明。裸 duration 只有全模型蕴含唯一差值才返回 exact，否则返回 range 或 underdetermined。

删除 `machine-proved`，并把 verdict 分为：

- `verified-formal-relative`：固定有限形式输入、查询规范化、相关 identity、proof replay 和 X 全部通过；只声称 J
  相对于该形式输入成立；
- `verified-canon-relative`：再要求 `Need(Σ,J)` 所需 S/F/I 全为 machine，无作者假设、AI 推断或 residual；
- `assumption-backed`：形式证明有效，所需 S/F/I 没有 open，且至少一项由绑定 C/J/family/domain/channel/gap 的
  已准入作者假设支撑；
- `incomplete`：任一必需 S/F/I 为 open，或 X 被截断；`invalid`：类型、上下文或 proof replay 失败。

当前尚无异质正典的语义所有权与来源穷尽契约，所以含自由正文、混合 Card 或未决提及的全小说范围，一般不能由机器
升级为 `verified-canon-relative`。只有闭合模型中仍经证明存在 variance，才可给 verified typed-underdetermined；
未形式化正文、身份未解或预算中断不得伪装成时间未定。

| 查询族 | 最低安全结论 | 额外义务 |
|---|---|---|
| 正向／显式负向 ground | 一个 verified support | 不足以声称 true-only／false-only |
| 存在 | 一个已验证见证 | 不要求全域闭合 |
| 缺失式否定／不存在 | 没有任何正向见证 | S/F/X；身份相关时加 I |
| 全称／唯一／精确计数／上界／极值 | 枚举范围和身份均闭合 | S/F/I/X 全部 |
| 计数下界 | 已证且两两不同的见证 | 局部 X/I，不要求穷尽 |
| 时间存在 | 一个时间片见证 | 局部时间证明 |
| throughout／first／last | 所有相关分段与终止事件闭合 | S/F/X、antiDeps；身份相关时加 I |
| temporal possible | 一个合法轨迹与支持见证 | 见证合法性、命中的惯性 antiDeps；正典级结论仍需适用 S/F/I/X |
| temporal necessary／impossible | 全部合法轨迹覆盖或符号反例排除 | 全称 antiDeps、closureDeps 和完整 X |
| transition variance | 同一 `ρ` 的双 `χ` 差异见证 | 当前裸诊断为存在式；报告 false 需要全域排除 |
| temporal variance | `Out(ρ₁,q)` 与 `Out(ρ₂,q)` 的包络差异证明 | 一个成员见证 + 另一固定 `ρ` 的全 `χ` 非成员证明 |

跨 CanonRevision 复用必须同时证明模型包含关系和 evaluation preservation，依赖切片只负责定位候选影响。若共享求值
保持不变，缩小 Ω 可保留旧 necessary／impossible，扩大 Ω 可保留仍合法的旧 possible 见证。Start／Stop、直接支持、
identity、Calendar、规则、effect、phase 或规范化变化通常改变共享轨迹求值，默认整证重放；缓存命中或三个依赖标签
均不能单独构成复用证明。

### 6.10 异质正典所有权与 claim-sensitive closure

规范化环境 `Σ` 和待证明的具体 claim `J` 共同产生有限反向切片：

```text
Need(Σ,J) ⊆ QueryFamily × TargetDomain × Channel

Channel = PositiveSupport | NegativeSupport | TemporalConstraint
        | EventEffect | Identity | DomainMember
```

`Need` 不能只由查询文本产生：同一个 `Alive(A)` 的单条正向 support、true-only、temporal necessary 和“没有任何
Alive 对象”需要不同 witness、invalidator、domain 与 identity 来源。QueryFamily catalog、静态规则依赖和项目域由 C
选中的 SchemaRevision 固定；K 固定 TargetDomain、selector 和 ownership 的规范语法。unknown family 返回
`unsupported-family`，unknown surface kind 降为 whole-resource opaque fallback，不能猜测相近类型或默认排除。

每个被 C 选择的 ResourceRevision 暴露有限 semantic surface：完整正文 body、结构字段、关系／事件值、TargetRef
片段或受限形式块。每个 `(surface, Need item)` 只接受以下最小条款：

```text
OwnershipClause {
  needPattern: (family, domain, channel)
  carrierSelector
  decision: owns | excluded
}
```

`owns` 表示该 surface 可以独立增加相应正典语义；`excluded` 只表示没有独立权威，不妨碍展示、索引或作为证据。
mirror／derived surface 使用 `excluded + hardGround/cite/derivedFrom` 已能表达失效、导航和谱系；delegation 编译为
owner 重分配或双 owner，未找到需要第三种所有权状态的反例。两个 owner 可以独立支持或冲突，但来源数绝不等于
Referent／occurrence 数。

active policy 只能由 C manifest 精确选择的 Schema／WorldSpec ResourceRevision 提供；selector 只允许 exact
ResourceRevision／TargetRef、有限 manifest metadata 匹配和有限集合运算，禁止读取内容真值、latest、branch head、
外部当前状态、递归 policy import 和 policy 自指。编译每个 key 时，相同决定合并，`owns + excluded` 为 invalid；
default 只作用于没有非默认匹配的 key，多个冲突 default 也 invalid；无匹配且无 default 为 S open。不存在
“更具体优先”“后提交优先”或列表顺序优先。未分类正文不能被 Schema 的沉默自动视为 excluded。

三项 closure component 分别取 `machine | assumed | open`：

- S 问“全部有资格影响 J 的 surface 是否已由有限 manifest 和唯一 effective map 找全”；
- F 问“这些 owner 的全部权威语义是否由 K 接受的总形式解释覆盖”；
- I 问“J 所需 mention、Referent、occurrence、time 和 DomainMember 的同一／不同是否完整”。

所需 S/F/I 全 machine 才能把有效 formal proof 升级为 canon-relative；没有 open 且至少一项依赖精确、已准入的作者
假设时是 assumption-backed；任一 open 都是 incomplete。模糊保证、AI 生成声明、已知 residual、预算截断或未分类
surface 不能把 open 改名为 assumed。局部 S/F 只有在 union 的 Need 恰为局部 Need 并集、无跨域上游规则、selector
扩张、shared-surface 冲突或覆盖缺口时才有条件组合；局部 I 永不自动合并，必须补跨域 identity bridge。

| Claim `J` | 最小 closure Need |
|---|---|
| 单条 `verified-support(+p(a))` | 一个 authoritative positive witness、其推导规则与局部 identity；不要求穷尽相反来源 |
| true-only／false-only | 一侧 witness + 可产生相反支持的全部 owner 与规则 |
| `exists x.p(x)`／`count≥k` | 一个或 k 个权威 witness；计数下界另需两两 different |
| 不存在／全称／唯一／精确计数／上界 | p owner、DomainMember 和 query-relevant identity 全闭合 |
| temporal possible | witness support + 所有可能使该 `ρ` 非法的硬时间约束 |
| temporal necessary／impossible | 全部反例／正例路径可能读取的 support、时间、Start／Stop、effect 和局部选择来源 |
| first／last | occurrence domain、time owner、identity 与相应模态量词来源 |

作者的构成性选择，例如“ExactBirthDate 只由 `Profile.birthDate` 拥有，人物简介对此 family excluded”，可由机器
验证为当前 C 的权威边界；“所有死亡事件已经提取”“页面列尽全部城市”则描述内容完备性，最多 assumption-backed。
arbitrary prose 若继续是 opaque independent owner，整体确认或逐条接受 AI 抽取仍不能证明没有第 n+1 条遗漏语义。

Contract 不新增核心记录：K 定义 grammar、闭合判断和禁区；项目条款复用 Schema／WorldSpec ResourceRevision；
CanonRevision 固定精确 policy/schema/source revisions 和 H/branch。当前 ADR-0006 等价于 World Bible page body 对
WorldEval 事实／关系／事件 family 为 excluded、对 DocumentarySearch 与页面自身内容仍有权威。长期 HCSM 若允许
prose owner，必须由新政策和 ADR 对新的 CanonRevision 明确生效，不能用新 evaluator 静默重解释旧页面。

跨 C 复用绑定 `ClosureContext(C,Σ,J)`：kernelVersion、claim-sensitive Need、精确 policy/schema/owner revisions、
finite surface catalog、compiled effective map、formalizer 与 coverage、identity/domain evidence、完整 interpretation
context 和 H/branch。当前只保留一个窄的条件引理：若 C2 唯一变化的 surface 对所有 required channel 均 excluded，
不是任何 owner 的 hardGround，不拥有 Identity／DomainMember，不改变 selector metadata、政策、Schema、规则或 H，
closure tier 与对象层 formal proof 才可复用。该引理尚未经过形式机证明；策略名相同、缓存命中或父分支 closure 均不够。

### 6.11 正文形式覆盖、correspondence 与直接权威

正文是否已发布与正文是否直接拥有某个 query family 的世界事实必须分开：

```text
DocCanon(C,t)             // 精确正文版本被 C 选择，可作为正式文档检索
Own(C,n,t)                // t 对 Need item n 可独立增加 WorldEval 语义
Corr(C,n,T,A)             // checker judgment：TargetRef 集 T 与 Assert 集 A 的对应合法
FormalCover(C,n,t,A)      // closure judgment：t 在 n 下的全部权威语义恰为 A
```

`Corr` 和 `FormalCover` 是判断，不是核心记录。`MappingEntry{targets,asserts}` 与 `coverageRoot` 是 correspondence
manifest 内的值。整份 manifest 默认内联 source revision；只有它需要独立审阅、版本、撤回、跨源复用或单独引用时，
才使用现有 `KnowledgeResource/ResourceRevision`，角色命名为 `correspondence-manifest`。不得复用 AI workflow
`Interpretation` 充当权威载体；作者采用 AI 候选时必须生成新的 sealed resource，再由新的 C 精确选择。

对一个 text surface 和 Need item `n`，当前只有以下可 machine-close F 的路径：

| 路径 | owner 与形式语义 | 关键失效条件 |
|---|---|---|
| controlled text | text owns；C 固定的 Schema grammar 被 total、确定、终止地解析，unsupported／residual 直接拒绝 | text、Schema、formalizer 核心语义或 coverage 改变 |
| A：constitutively formalized text owner | text owns；`Sem(C,n,t)=φ(C,n,t)=A`，派生 Assert 可重建且不得独立改权威语义 | text、total manifest、Schema 或 `φ` 失效 |
| B：authority substitution | text 对 n excluded；C 精确选择 Assert owners，mapping／hardGround 记录对应和失效 | authoritative Assert 或必要 hardGround 失效 |
| evidence-only | text 对 WorldEval excluded，仅参与 DocumentarySearch／cite；结构化 owner 独立成立 | 不要求正文形式覆盖；结构 owner 仍按自身依据失效 |

A 中 text 已不再是 opaque independent owner：mapping 外自然语言解释被规范排除，但 text 仍是直接授权来源。B 中
Assert 是直接 owner；text 可以是 ultimate hard ground 或 documentary source。若 `φ(t)` 与 B 中 Assert 在 regime、
polarity、Statement、TimeScope、identity 和有效性规则上完全相同，且查询不观察 immediate owner／support identity，
A 与 B 的普通 WorldEval 结果条件等价；删除 text、撤回 mapping、删除／独立修改 Assert 或解释“谁直接授权事实”时
二者不等价。当前 ADR-0006 对 World Bible page 采用 B／evidence-only 边界；未来启用 A 必须修订 ADR 且只作用新 C。

C 对每个需要 total formalization 的 `(coverageRoot,n)` 只选择一份 compiled total coverage manifest。它可以精确列出
多个 additive partial manifest revisions 并取集合并集；partial 自身不得声称局部 exhaustive，所有 component 必须绑定
同一 C、root、need key、formalizer、Schema、identity 和 normalization context。TargetRef 重叠允许，AssertID 重复
幂等；`+p/-p` 冲突照常进入 WorldEval conflict，不能由 mapping 顺序消解；两个结果不同的 total manifest 同时活动使
policy invalid。字符全覆盖、相似度或 AI 置信度均不证明 totality。

`hardGrounds(a)` 固定为有限合取：任一 ground 失效，该 Assert 不再提供有效支持。若 `G1` 或 `G2` 任一组都足以支持
同一 Statement／regime／polarity／TimeScope，则建立两个 Assert，分别绑定 `G1`、`G2`；查询对有效 AssertID 集合取
存在，不增加 Boolean ground formula。具体 controlled grammar、lexicon 与 family mapping 由 C 固定的
SchemaRevision 承担；K 只固定 total-formalizer 接口、accepted／rejected／residual 状态和核心解释语义。项目词汇或
grammar 变化产生新 SchemaRevision，只有上述规范语义变化才产生新 kernelVersion。

作者行为也必须分开：`RatifyCorrespondence` 只确认对应；`AssumeExhaustive` 只产生 assumption-backed；
`AdoptConstitutiveFormalization` 或 `AdoptAuthoritySubstitution` 才能通过新的 CanonRevision 改变规范权威。旧 C 永不被
新 mapping 或 evaluator 追溯重解释。下一轮还需定义这些转换的原子状态机、撤回／回滚与多父合并，当前不得把 A/B
选择或跨 C 转换当作已定实施契约。

### 6.12 权威状态与原子 CanonRevision 转换

对同一 `(text surface t, Need item n, representation chain)`，checker 派生三种状态；它们不是存储枚举：

```text
O(t,n)              text owns；没有 total constitutive formalizer；F=assumed|open
A(t,n,M,φ,Aset)     text owns；M 与 φ total；φ(t)=Aset；派生 Assert 不独立 owns
B(t,n,M?,Aset)      text excluded；exact Assert set Aset owns
```

独立来源分别形成自己的 representation chain，可以合法多 owner 并产生一致支持或 canon conflict。`Aset=∅` 也可合法，
但必须由 C 选择的 total manifest 明确把该范围定义为 closed-empty；没有 owner 且没有 totality 依据是 uncovered，使 S open。

```text
AtomicTransition(C1,C2,Δ) iff
  C1、C2 均不可变，且 C1 的语义与 receipt 不变；
  Δ 的新资源在被 C2 选择前已 seal 但没有 authority；
  C2 精确固定 K、Schema、policy、source、完整 manifest、Assert、
     hardGround 与 identity/domain；
  Admit 对完整 C2 manifest 一次判断，失败不产生半生效 C；
  每条受影响 representation chain 编译出唯一 O/A/B post-state；
  所有 TargetRef 精确指向 ResourceRevision，hardGround 有限、无环且终止；
  不读取 latest、branch head、可变草稿或当前权限解释历史输入。
```

| 转换 | 纯切换的最小准入条件 | 非纯切换或失败 |
|---|---|---|
| O→A | exact text、Schema、total M 与 `φ(t)=Aset` 同时准入；派生 Assert excluded | partial／residual、未解 identity/time 或 AI Interpretation 直接入 manifest 时失败 |
| O→B | text `owns→excluded` 与 exact Assert `→owns` 在一个新 C 生效；empty 需 total-empty | 分步提交会短暂无 owner 或重复 owner |
| A→B | `AsetB` 与旧 `φ(t)` 在 regime、polarity、Statement、TimeScope、identity 和有效性上相同 | 集合或条件不同即“权威切换 + 世界内容修订” |
| B→A | text 仍存在，新 total `φ(t)` 恰等于当前 owner Assert 集；原 Assert 变为非权威 executable representation | 独立来源 multiplicity 未被保留、独立修订未吸收时不可称纯切换 |
| A→O | text 继续 owns，M／φ 不再选择，派生 Assert 仍 excluded；F 降级 | 不得继续沿用 machine F |
| B→O | text owns 与 B Assert owners 撤回在同一 C 生效 | 保留 Assert owns 时是显式多 owner，不是 O |

A 中删除 text 或撤回 total manifest 会破坏 A；B 中 cite-only text 删除只损失 documentary source，hardGround text 删除
则使对应 Assert 失效。B 的 correspondence manifest 若只负责导航，撤回不改变真值；若还定义 exact owner set 或
closure evidence，则必须重算 S/F。A 的派生 Assert 独立修改没有正典效果；B 的 Assert 修改是新的世界语义修订，必须
由新 C 准入。

四类解释关系全部派生：DirectAuthority 来自 effective ownership；UltimateGround 来自 hardGround 的有限无环闭包；
DocumentarySource 来自 cite／TargetRef／DocCanon；ExecutableSupport 在 A 中由 `φ` 生成，在 B 中由 Assert 承担。
它们没有独立身份、版本或撤回周期，不新增持久核心记录。hardGround 的 flat set 是合取，因此权威支持图默认拒绝循环；
只作导航的 cite 不参与该有效性约束。

多父合并不能 union 父状态或按 latest／父顺序选择；该能力在 v1 中直接拒绝，未来另立 Spec 时才允许由新 C 逐
representation chain 选择最终 O/A/B、精确 text／Schema、owner Assert 集和 grounds。v1 历史浏览不移动 head；正典
revert 必须以当前 head 为父创建新的 C 并重新选择兼容旧状态，永不原地修改历史 C。目标 manifest 若会让任何已
`canon-owned` family 回到 legacy／`formal-disabled`，则返回 `incompatible-revert-target`；恢复旧值必须在当前 family
authority 与 Schema 下形成普通新 decision，而不是 exact revert。

A↔B 时旧 acceptance 和 canon-closure certificate 默认失效。只有查询不观察 owner／support／documentary source，
规范化 signed support 在制度、极性、内容、时间和身份上双射，grounds、TemporalTheory、Calendar、规则/effect、
antiDeps 与 closureDeps 搜索空间均保持，且没有新增反面 owner 时，才可把对象层 proof skeleton 运输到 C2，并使用新的
proof header 与 context digest 重新 replay；这产生新的 C2 acceptance，不是复用旧 verdict。

### 6.13 SchemaRevision 的 claim-sensitive compatibility

裸 `SchemaCompat(S1,S2,Need)` 不能区分“当前输入碰巧兼容”与“所有未来输入都兼容”，因此只保留两个 judgment：

```text
CanonSchemaCompatK(C1:S1,C2:S2,N,E)      // exact CanonRevision pair
UniversalSchemaCompatK(S1,S2,N,E)        // all admissible relevant inputs
N = Need(Σ,J)
```

两者都是 checker judgment，不是正典字段或核心记录。`DepS(N)` 至少闭包 family/channel、predicate/sort、owner surface、
selector、formalizer grammar/lexicon、normalization、identity/alias/occurrence、DomainMember、rule/effect 入边、time/unit/
Calendar、default／enum／constraint 以及 unknown-surface policy。实际检查使用 `U=DepS1(N)∪DepS2(N)`；只看旧 slice
会漏掉新 Schema 引入的 invalidator 或 owner。

machine-compatible 只保留两条充分路径：

1. `exact-unchanged`：K 相同，S1/S2 well-formed，U 内规范 digest 相同，S2 没有指向 U 的新入边，unknown/default
   编译结果相同；SchemaRevision 其他部分可以不同。
2. `verified-translation-relative`：K 接受有限声明式 `τ`，明确 `canon-pair | universal` scope，且对 required symbol、
   field、predicate、enum、carrier、selector、sort、identity/domain 和 normalized observation total；需要区分的值单射，
   exact count／unique／universal／absence 的 identity classes 双射；ownership/source obligations、regime、polarity、
   time/unit 和 rule/effect 保持。`τ` 禁止脚本、latest、动态发现和查询结果反射。

A 路径还需交换条件 `τAssert(φS1(t1)) = φS2(τText(t1))`；B 路径需 Assert 在两侧解释为相同 signed literal、
TimeScope 与制度。一个 ground support 只需 witness identity 保持；`count≥k` 需 k 个 witness 仍两两不同；absence、
unique、exact count、universal 和 first/last 则需相关 domain／occurrence identity 双射。相同 Schema diff 因 claim
不同可以得到不同 compatibility verdict。

| compatibility grade | 含义 | 对复用的影响 |
|---|---|---|
| exact-unchanged | 双 Schema relevant slice 规范相同 | proof skeleton 可在 C2 replay；新签 acceptance／closure |
| verified-translation-relative | 声明式 τ 在声明 scope 内通过 K 检查 | 经 τ 运输 skeleton，再在 C2 replay；不复用旧 certificate |
| assumption-backed | 作者确认语义相同，但关键等价不可检查 | 只能得到 assumption-backed 新判断 |
| open | unknown surface、未映射字段、残余规则或 identity/domain 缺口 | incomplete |
| invalid | τ 非 total、类型矛盾、悬空 selector、冲突 default、动态／自指或 replay 失败 | 拒绝兼容主张 |

字段纯重命名只有在 type、cardinality、default、ownership、selector、ground、family 与 normalization 均保持时才可
machine-verify；类型收窄通常只可能 canon-pair，类型拓宽也不保 absence／count／universal；default 可以制造新事实；
字段拆并必须证明 total 且信息保持；新 surface 明确 excluded 才可能是保守扩展，unknown surface 保持 S open；alias
merge/split、DomainMember 扩张和规则／effect／normalization 变化分别触发 I、S/F、proof 与时间重验。

translation evidence 单次使用时内联 proof payload；需要独立审阅、版本或复用时，才复用 proof 或 Schema/WorldSpec
的 `KnowledgeResource/ResourceRevision`。它不修改旧数据、不取得世界 authority，也不是 MigrationMap。多父合并必须
产生新的 exact Schema，并分别证明每个父到新 Schema 的 canon-pair compatibility；latest、父顺序和字段同名均不能
决定作者意图。

### 6.14 无模板卡、Schema 采用与历史事实提升

`UntemplatedBlank` 不是无 Schema，而是没有 type-specific semantics、所有 surface 都落入 C 固定的 BaseSchema：

```text
GenericBlankSurface = title | body
                    | customField[key].label
                    | customField[key].rawValue

DocCanon(C,s)                         if exact Card ResourceRevision is selected
OwnWorld(C,knownNeed,s) = excluded    for every generic surface
```

因此草稿不属正典；已准入 blank card 的标题、正文和 custom value 是 documentary content，但不自动是 Name、alias、
属性、关系或事件事实。真正无法被 BaseSchema selector 识别的 extension 不是 generic custom field，而是 unknown surface；
相关 S open 或提交 fail closed，不能默认 excluded。旧 C 固定旧 family catalog；新 family 只在新 C 重新分类 legacy surface。

卡片仍是作者工作空间，不是新的身份根。所有卡片都有 KnowledgeResource；内建 entity-bearing 类型可在同一作者操作中
显式创建／链接 Referent，generic blank 默认只创建资源，之后可提升为 entity-bearing。对 entity-bearing 新卡，界面可用
一个“名称”动作原子产生 documentary title 与 typed Name authority；generic blank title 仍只是标签。资源复制、同名标题
或同名字段都不决定 Referent identity。

三种作者行为的唯一效果必须分开：

| 行为 | 资源效果 | 对既有卡片 WorldEval 的效果 |
|---|---|---|
| CreateTemplate | seal Schema／WorldSpec ResourceRevision；AI 可生成候选 | 无 |
| AdoptSchema | 设置非正典 authoring creation default；不让 C 动态选择未来资源 | 无；每个新 RR seal 时另行固定 exact Schema，旧卡继续绑定旧 Schema |
| PromoteHistoricalContent | seal exact Card／Assert／mapping，验证后由新 C 选择 | 首次取得 A 或 B authority，必须重验 S/F/I 与 proof |

`AdoptSchema` 不得使某个 C 动态拥有尚未存在的 future ResourceRevision。面向未来的唯一效果是设置非正典 authoring
creation default；每个新 RR 在 seal 时把 exact SchemaRevision 写入不可变内容或可精确解析的 revision metadata，后续
C 再显式选择该 RR 及其 exact Schema。旧内容升级必须显式选择 exact revisions；evaluator、closure 和历史查询不得读取
latest template 或当前 creation default。
`SchemaOfC(resource,surface,Need)` 对每个 surface 唯一解析到 exact SchemaRevision，允许旧、新 Schema 共存。

typed-owner promotion 的派生状态为 `DRAFT → D(documentary/excluded) → V(validated candidate) → A|B`；V 复用现有
Proposal／Interpretation 或未被 C 选择的 sealed RR，不是新正典状态。A 只在作者要求原 surface 为 direct owner、
formalizer total／可拒绝且覆盖 residual 时使用；默认 B：原 surface excluded，exact typed Assert owns，原文只作 cite
或 hardGround。parser／AI confidence、模板创建和 Schema 采用都不能越过 V 自动进入 A/B。

missing、null、empty 必须区分。default 默认只在创建新 revision 时预填，只有持久化 exact value 并随 Schema 被准入后
才可能产生事实；`missing⇒value` 若要成为世界语义，就是 PromoteHistoricalContent。旧值类型失败时只能保留资料、
作者修改生成新 RR、显式 B Assert、或 A total formalization，不能 coercion。field split／merge、unit／enum／alias／
identity 只有在保持已有 authority 时才可用 SchemaCompat；documentary 内容首次变成事实始终是 promotion。

promotion batch 必须固定 exact 成员并原子准入。任一成员 invalid 时默认整批拒绝；作者可重新选择并确认 exact subset，
系统不得静默丢弃失败项。rollback 使用 branch navigation 或新 revert C；多父模板合并生成新的 exact Schema 和最终
authority map，禁止 union、latest、父顺序或字段同名裁决。

DynamicType、MigrationMap、TemplateLifecycle、SchemaAdoption、HistoricalPromotion、TemplateBinding、
FieldValueRevision、CompatibilityStatus 和 TypeVersion 均未通过 deletion test：类型／版本复用 Schema KR/RR，卡片值
复用 Card RR，行为差异由 C manifest/diff 与 provenance 表达，候选复用现有 workflow，兼容由 checker/proof 表达。

### 6.15 自动化安全边界

| 层级 | 当前允许范围 |
|---|---|
| 可自动执行 | 历史准入与引用闭合、ownership policy flatten、manifest selector 展开、typed surface 形式化、possible 见证与已定义 proof rules 重放 |
| 只能生成候选 | 文本重锚定、自由文本到 Assert／时间约束的解释、自然语言 correspondence、Schema 映射和复杂 Calendar 解释 |
| 必须作者确认 | 最终正典准入、构成性所有权选择、解释采用、Schema／Calendar 变更、正典冲突解决、作者分支合并和描述性闭合假设 |
| 不可通用决定 | 任意文本意图、一般程序等价、任意 Schema 语义保持、开放正文绝对完备、合并是否符合作者意图 |

## 7. 不因完整平台方向而放弃的边界

即使最终建设完整知识表示平台，以下边界仍属于产品和安全约束：

1. 所有业务读写保持 `novel_id` 隔离，公开请求同时执行当前账户 owner 门禁。
2. 当前访问权限、提交时准入、小说语义和 provenance 永久分离；权限撤销不能静默重写历史正典。
3. AI Proposal／Interpretation 默认不是真值输入；作者采用必须建立新 Assert 并保留来源和授权范围。
4. 资源发布与客观断言永久分离；人物话语、转述、梦境、世界内文档和不可靠叙述只成为行为事实。
5. world 与 belief(holder) 分开求值；ReaderAccess、Hypothesis 和 DocumentSearch 不得默认跨边界传播。
6. 基础状态、事件和校正共享唯一正典输入；Profile 当前值、MemoryEvent 重放和物化快照不得形成第二可写账本。
7. 自由文本未结构化不等于虚假；结构查询必须报告 S/F/I/X 和时间边界。
8. 被引用记录和 CanonRevision 不得原地改写；旧正典固定 kernelVersion，新内核不得重解释历史版本。
9. Card 可以统一作者体验，但不能强制统一内部资源生命周期，也不得向普通作者暴露内部证明模型。
10. FRI、检索、物化状态、验证器 verdict 和查询缓存均可删除并重建，永久非权威。

## 8. 对当前系统的潜在重构影响

只有目标模型被正式采用后，本节才可转为实施计划。

| 当前承载 | 第十五轮实现交接语义 |
|---|---|
| account principal、owner 门禁 | 实时访问和提交授权；提交时形成历史准入证据，不进入小说真值语义 |
| `CoreEntity` | Referent：只负责世界持续身份 |
| 类型化 Profile | cutover 前是 mutable authoring；世界语义进入 Assert，资料内容只有经封闭目录允许的 immutable revision 才能进入 C |
| World Bible 页面 | 当前 ADR-0006 对 WorldEval 事实 family 为 excluded，采用 B／evidence-only；未来 A 型 text owner 必须经新政策／ADR 和新 C 显式准入 |
| Scene | 叙事 KnowledgeResource，不是世界 Event；与 Event Referent 多对多联系 |
| 二元 `EntityRelation` | Predication／Statement + Assert；独立正文和版本生命周期才需要额外资源 |
| Event | Event Referent；发生、参与、时间和效果由 world Assert 与规则表达 |
| MemoryEvent | event/time cutover 前仅属 Story 连续性；cutover 后只能以 C-pinned immutable revision 或 promotion Assert 进入 WorldEval |
| CharacterKnowledge | belief(holder) Assert 和认知事件；对象级知识仅作兼容摘要 |
| Reader Reveal、Visibility | Statement／TargetRef 与叙事位置的访问关系，只形成 ReaderAccess 投影 |
| `TargetRef` | `(ResourceRevision, Selector)` 版本内寻址值；跨版本只生成重锚定候选 |
| Evidence | hardGround／cite／derivedFrom、三类世界依赖与 proof metadata，不自动决定正典、真值或 checker verdict |
| Suggestion、Adoption Package | mutable 非权威 workflow candidate；显式采用时把 exact candidate/subset 封入 AdmissionInputValue，重验后原子创建 Assert+C+receipt+CAS |
| Schema／规则／WorldSpec | 特殊 KnowledgeResource／ResourceRevision；定义 family、surface、selector、ownership clause 和规则依赖并由 C 固定 |
| AI Interpretation | 始终是非权威 workflow candidate；采用 correspondence 时产生新的 sealed ResourceRevision，不能原物升格 |
| correspondence／coverage | 默认是 source revision 内的 typed values；只有整份 manifest 独立审阅、版本、撤回或复用时才使用既有 KnowledgeResource 生命周期 |
| 发布／采用事务 | 候选资源先 seal；新的 CanonRevision 完整选择后一次 Admit，共同生效，不新增 AuthorityTransaction |
| 解释来源 | direct authority、ultimate ground、documentary source、executable support 从 ownership／hardGround／cite／formalizer 派生，不建第二账本 |
| 自定义字段／模板版本 | SchemaRevision；旧 C 固定旧 Schema，新版差异按 Need-sensitive 双 slice 或声明式 translation 重验 |
| 兼容与迁移报告 | checker/proof artifact 或 Schema/WorldSpec revision；不是世界事实、MigrationMap 或可直接采用的 AI 权威 |
| World Bible Category／Template | Category 只负责作者导航；Template 映射为 Schema candidate/RR，创建与采用分开 |
| generic blank card | Card KnowledgeResource + BaseSchema documentary surfaces；默认不创建 Referent、不产生 WorldEval facts |
| 历史 custom values | 继续由旧 exact Schema 解释；显式 promotion 默认生成 B 型 Assert，不能靠新模板或 parser 读取成事实 |
| `status=canonical`／published head | 继续表达作者采用／展示生命周期；family cutover 后不再单独决定 WorldEval |
| 新 Assert／Canon | world 内部的不可变事实与正典清单；不新增顶级模块，跨域只经 facade/contracts |
| Ask World 与 Context Compiler | 按 `Need(Σ,J)` 编排求值与检索，分开返回 formal proof、S/F/I/X、时间／转移 variance、所用 C 和最终 verdict |
| “人物与世界” Card | 聚合不同 family-local owner、证据和视图；没有一个全 Card 正文／结构主导开关 |

完整采用仍会影响 world、imports、evidence、story/continuity、writing、map 和前端“人物与世界”工作区，
不是只替换 `entity_relations` 的局部重构。

## 9. 当前裁定边界与开放问题

### 9.1 Proposed ADR 裁决：已起草，尚未接受

| 候选 | 当前 Proposed 裁决 |
|---|---|
| 六项语义职责 | 保留；仍不承诺物理类型数最小 |
| `Closed(K, Auth, C)` | 改写为提交时 Admit、历史 receipt 和 `Closed(K,receipt,C)` |
| 七种 act／AuthorialVoice | 删除；压缩为唯一 Assert，行为进入普通 Statement |
| StatementRef 不自动断言 | 保留为稳定候选；MetaFence 禁止通用解引用 |
| Proposal／Interpretation 是 Attestation | 删除；降为工作流资源 |
| Defeat | 从最小 K 删除；撤回由新 C 选择替换表达 |
| kernelVersion 固定 checker profile | 改写为固定规范证明语义，不固定 checker build |
| 有限快照整体单调 | 删除；仅局部正向闭包单调，惯性携带 antiDeps |
| TimeScope 和有限全序求值 | 改写为 TimeScope + 有限 DNF TemporalTheory + 合法模态轨迹 |
| 裸偏序／严格线性扩展 | 删除；无法表达可能同刻、粗粒度时间窗和相关顺序未知 |
| `Eq/Neq/Lt/Within` | 保留表达能力；Neq 可为受限析取语法糖，Within 复用 Interval |
| 同边界 Start／Stop | 保留 transition-underdetermined，并补充局部非确定转移关系 |
| temporal／transition/conflict／branch 单枚举 | 删除；改为正交诊断向量，禁止跨轨迹合并正负支持 |
| 两见证 temporal-underdetermined | 删除；改为 `Out(ρ,q)` 包络差异的成员／非成员证明 |
| 单值 first／last、纯顺序 duration | 删除；改为 occurrence 集与 modal first；精确 duration 要求 metric entailment |
| `machine-proved` | 删除；改为 verified-support／completeness-relative-to 与 assumption-backed |
| S/F/I/X | 保留，增加 supportDeps／antiDeps／closureDeps 和查询族差异 |
| 第四类 `interpretationDeps` | 删除；完整解释上下文进入 proof header，三类世界答案依赖保持不变 |
| 无条件 complete calculus | 删除；改为依赖两个 adequacy 引理的条件式构造性候选 |
| checker／normalizer build 属于 K | 删除；规范语义属于 K，具体 build 和 conformance epoch 属于 replay metadata |
| `Need(q)` | 删除；改为具体 claim 的 `Need(Σ,J)`，分别追踪 witness、invalidator、domain 和 identity |
| 全 Card text-led／structure-led／dual | 删除；改为 family/domain/channel/surface 上的 `owns | excluded` |
| 第三种 mirror／derived ownership | 删除；复用 excluded + hardGround／cite／derivedFrom |
| 全局 `closed=true` | 删除；S/F/I 分别为 machine／assumed／open，X 保持执行完整性 |
| 作者 completeness 声明可 machine-close | 删除；构成性权威选择可检查，描述性无遗漏声明最多 assumption-backed |
| ownership contract 新核心记录 | 删除；K 定义语义，Schema／WorldSpec ResourceRevision 保存条款，C 固定版本 |
| 局部 S/F/I 自动组合 | 删除；S/F 仅保留严格条件候选，I 还需跨域 identity bridge |
| policy latest／content selector／import | 删除；只允许有限 manifest metadata selector，禁自指与隐式优先级 |
| finite author-ratified mapping machine-closes opaque prose | 删除；只证明 correspondence 已采用，不能证明映射外无权威含义 |
| 构成性 mapping 必然 text excluded | 删除；保留 A 型 text owner 与 B 型 Assert authority substitution 两种不同政策 |
| `Corr`／`FormalCover`／`AuthoritySubstitution` 核心记录 | 删除；它们是 checker judgment，mapping entry／coverage root 是值 |
| `SemanticBinding` | 继续删除；完整 manifest 需要独立生命周期时复用 KnowledgeResource／ResourceRevision |
| AI Interpretation 直接成为 correspondence authority | 删除；普通候选只在 Admit 内封存 exact input 并创建 Assert+C；独立文档资源才产生专用 RR |
| 单一 mapping-root 实体 | 删除；C 只需选择一份唯一 compiled total coverage manifest，可安全 flatten 多个 additive partial revisions |
| Boolean hardGround 公式 | 删除；flat set 为合取，替代依据使用多个同语义 Assert |
| grammar／lexicon 变化必升级 K | 删除；项目语法固定于 SchemaRevision，K 只在形式化器核心规范语义改变时升级 |
| `AuthorityTransaction`／`AuthorityMode` | 删除；新 CanonRevision + Admit 表达原子切换，O/A/B 为 derived judgment |
| 每个 key 恰有一个 owner | 删除；只禁止同一 representation chain 的无意重复 owner，独立多 owner 合法 |
| exact-empty 创建虚构 Assert | 删除；total manifest 可以构成性定义 closed-empty，未覆盖则 S open |
| direct／ground／documentary／executable edge 记录 | 删除；分别从 ownership、hardGround、cite／DocCanon、formalizer／Assert 派生 |
| A/B 切换复用旧 closure certificate | 删除；仅允许满足保持条件的 proof skeleton 在 C2 重新 replay |
| 原地回滚 CanonRevision | 删除；v1 历史浏览不移动 head，回滚追加新的 revert C |
| 单一 `SchemaCompat(S1,S2,N)` | 删除；区分 exact canon-pair 与 universal scope |
| S1 旧 dependency slice 足够 | 删除；检查 S1/S2 slice 并集及 S2 新入边 |
| 类型拓宽／字段重命名自动兼容 | 删除；按 claim 检查 domain、identity、owner、selector、default 和 normalization |
| Schema 新版本沿用旧 certificate | 删除；proof skeleton 可条件运输，但 acceptance／closure 必须在 C2 新签 |
| `SchemaCompatibility`／`MigrationMap` 核心记录 | 删除；复用 checker judgment 与 proof／Schema ResourceRevision |
| 完全无 Schema 的 blank card | 删除；改为 BaseSchema 下无 type-specific semantics 的 generic documentary card |
| card title 自动 Name／Referent | 删除；generic title 只是资料标签，entity-bearing policy 才显式创建／链接身份与 Name |
| CreateTemplate=AdoptSchema=PromoteHistoricalContent | 删除；三个动作分离，只有 promotion 改变历史真值 |
| parser／AI 自动事实提升 | 删除；只生成 V candidate，作者经新 C 选择 A/B |
| default 补写历史卡 | 删除；仅预填新 revision，absent-value truth 属于 promotion |
| DynamicType／TemplateBinding／FieldValueRevision | 删除；复用 Schema RR、Card RR、compiled SchemaOfC 与现有 workflow |
| `cards`／`knowledge_resources`／通用 `resource_revisions` | 删除；统一逻辑引用与 read model，保留各域专用历史 |
| 独立 Statement 表 | v1 有条件删除；StatementValue 必须自包含，含 StatementRef 的 kind 在可解析表示完成前拒绝 |
| `world_assertions` | 必须新增；现有关系／Profile 不能表达不可变 signed、regime、time 与 exact grounds |
| `world_canon_revisions`／`world_canon_heads` | 必须新增；现有 status/head 不能固定旧正典或原子多资源采用 |
| `entity_profile_template_revisions` | typed custom Schema 开工前必须新增；现有 mutable template head 会追溯解释旧事实 |
| 新顶级 knowledge／canon 模块 | 删除；实现归 world，evidence／story 保留各自输入职责 |
| 旧表与 Assert 长期双写 | 删除；按 family 一次切换唯一 evaluator owner，旧字段随后只读投影或退场 |
| Card、双通道问世界、FRI 非权威 | 保留 |

可以继续稳定为未来 ADR 候选的是：六项职责、唯一 Assert、StatementRef 惰性引用、历史准入与当前权限分离、
规范 K 与实现 build 分离、不可写派生状态、受限 TemporalTheory、三类世界依赖、claim-sensitive Need、
family-local `owns | excluded`、S/F/I/X、B-default promotion、新 CanonRevision 原子切换、scoped Schema
compatibility 与 generic blank BaseSchema。八项 P0 语义已经闭合；仓库适配可起草 ADR，但第 12 节四项项目事实形成
数据库／wire／fixture 契约前，不得把 Phase 2+ 标为 implementation-ready。四项契约现已在 Proposed ADR-0017、Phase 0
Spec 与 fixtures 中形成唯一映射；ADR 接受和实际测试落地前，仍不得启动 Phase 2+。

### 9.2 必须保留人工裁决或受限语言的问题

- 一般 Statement／程序／kernel 等价不能通用自动判定。
- 任意自然语言改写、语用和断言内容不能仅由相似度或模型置信度证明。
- 没有来源闭合与形式化覆盖，开放正文不能自动证明缺失、唯一、计数或极值。
- Schema／Calendar 变更、正典冲突、多父合并和本体多时间线必须由作者确认；闭合模型内的 chronology 未知应返回
  possible／necessary 与正交诊断，不强迫作者先选一个顺序。
- admission receipt 只证明当时有权提交，不证明内容正确；历史密钥泄露等安全事件仍需独立治理。
- `verified-support` 只证明相对于固定输入存在支持，不代表 canonical true-only 或全世界完备。
- 哪些 family 允许 A 型正文直接 owner、哪些固定采用 B／evidence-only，是产品与 ADR 决定；checker 不能替作者选择。
- A 中派生 Assert 是否永远不可独立采用／修订，以及作者端是否必须保留“直接权威来源”解释，尚未裁定。
- Schema 可提供的 controlled grammar 表达力必须保持可判定、无项目脚本；当前只固定分层，不声称任意 grammar plugin 安全。
- exact-empty 的 manifest 语法、A 中 executable Assert 的稳定引用方式、多父合并的作者裁决契约仍需进入正式 Spec。
- hardGround 参与有效性，因此当前候选默认要求有限、无环并终止于 exact resource；是否存在值得支持的递归 ground
  语义尚无反例需求，不预建。
- 哪些 family 必须承诺 universal Schema compatibility、哪些只要求 canon-pair，是产品成本与作者预期选择；系统不能
  从 `major/minor/patch` 标签自动推导。
- 字段拆并、identity merge/split 和多父 Schema 冲突是否符合设定，只能由作者裁决；translation certificate 只验证
  已表达的选择是否保持其声明 scope。

以下作为实施 Spec 的推荐默认；它们是主代理结合当前 ADR、用户画像与 deletion test 作出的工程裁决，在新 ADR 评审
时仍可由用户覆盖，但不再作为继续理论研究的 blocker：

- 所有 Card 都有 KnowledgeResource；内建 entity-bearing 类型在同一作者操作中创建／链接 Referent，generic blank
  默认 resource-only，可显式提升；
- generic title/body/custom values 均 documentary／WorldEval excluded；entity-bearing 新卡的一个“名称”操作可原子
  建立 title 与 typed Name authority；
- default 只预填，持久化 exact value 后才可能按 Schema 成为事实；
- B 是默认历史 promotion，A 只对 total、controlled、可拒绝的 surface 开启；
- bulk invalid 默认整批拒绝，作者可重新确认 exact subset；
- AdoptSchema 只设置非正典 creation default；每个未来 RR 在 seal 时固定 exact Schema，历史提升显式选择 exact revisions；
- direct authority 是稳定查询解释语义，但只在高级诊断中展示；
- BaseSchema 接受已知 generic key/value，真正 unknown extension 在正典准入时 fail closed。
- Phase 2 为新旧每个 `novel_id` 创建唯一 empty C0；C0 固定 v1 K、BaseSchema 和 policy，但不选择任何 legacy Assert，
  也不把 legacy `canonical` 状态提升为 formal authority；C0 receipt 使用 `bootstrap-empty-canon` 与封闭 system bootstrap
  subject。旧小说的显式初始化从 C0 追加 C1 并选择作者确认的 exact subset。
- v1 CanonRevision parent 为 `0..1`，head 只能 CAS 前进到当前 C 的新直接子；历史浏览不移动 head，回滚追加 revert C；
  `formal-disabled→canon-owned` 单向；跨 family cutover exact revert 拒绝。命名 branch、多 head、多父和 merge 在另立
  Spec 前拒绝。
- v1 formal family 只包含 Name、有限 typed scalar、正／负 binary relation 与 timeless／简单 point-or-interval；惯性、
  branch、通用 belief、A 型正文 owner 与闭合计数后置。
- family cutover 顺序为 Name → custom typed fields → relation → event/time → belief；一个 family 切换后 evaluator 不再
  fallback 到 legacy current value。

### 9.3 实施交接与后置研究队列

本研究到此停止扩张。第 12 节要求的 Proposed
[`ADR-0017`](../adr/0017-world-fact-authority-and-canon-revisions.md)、
[`Phase 0 实施 Spec`](../superpowers/specs/2026-08-27-world-authority-phase0-spec.md) 与
[`canonical fixtures`](world-authority-canonical-fixtures-v1.json) 已完成起草。下一步是评审并接受或修订 ADR，之后按
Spec 实现；Phase 1 可独立规划，Phase 2+ 在 ADR 接受前不开工。

后置研究只在相应 Phase 出现真实需求或反例时启动：A 型受控正文 owner、TargetRef 自动重锚定、自然语言合并、
通用 belief、惯性／branch、多作者治理、kernel 兼容、闭合组合／复用引理与时态 adequacy 的形式机验证。当前实现迁移
属于 Spec／代码任务，不再包装成理论轮。

## 10. 研究提示词

### 10.1 已完成：LWCM 第二轮证伪

以下提示词专门研究“理论模型如何适配统一卡片与知识平台”，与探索式研究账本中研究 CWEM
世界演化的提示词并行而不重复。它不限制知识平台的完整度，也不要求模型迁就当前数据库或
迁移成本。

```text
请继续批判性推进你上一轮提出的 LWCM。不要复述原方案，也不要默认它已经正确；先尝试推翻其核心假设，再提出修订模型。

背景是一款长篇小说创作系统。它计划把“世界对象”和“世界书”彻底统一为“人物与世界”中的卡片式知识系统，支持人物、地点、势力、事件、规则、秘密以及作者创建的空白类型。系统可以进一步发展成完整的知识表示、百科查询、关系推导和叙事一致性平台。

当前领域中同时存在：

- 作者可编辑、发布和修订的卡片正文与结构化字段；
- 对象身份、属性、二元或多元关系、事件和随时间变化的状态；
- 来源文本、证据、AI 提取候选、作者采用与否；
- 作者正典、人物知识与误解、读者揭示、假设和可能的正典分支；
- Scene 与事件驱动的历史状态、冲突检查、上下文编译和可解释查询。

AI 生成或抽取的内容不能自动成为正典。与此同时，作者发布的自由文本本身具有正典效力，不可能要求每句话先被完整转化为形式命题，才能属于世界设定。

不要从现有代码、数据库、迁移成本、开发周期或“是否过度设计”出发。研究目标是寻找长期正确、能够逐层扩展的语义内核，同时明确哪些机制是不可缺少的，哪些只是高级能力。

重点解决：

1. 发布的卡片正文与结构化 Assertion / Commitment 应如何共同构成正典？如何避免双重真相源？
2. 哪些内容必须成为可寻址的一等命题，哪些可以留在正文或普通字段中？给出可判定的提升准则。
3. 卡片、知识资源、世界实体、事件、文档、命题和视图分别是什么？“卡片只是投影”是否成立，还是应采用混合模型？
4. 世界有效时间、数据库修订时间、人物获知时间和读者揭示位置，最少需要哪些独立维度？
5. 如何统一直接关系、共享锚点、多元事件角色、Fluent 和事件导致的状态变化，而不退化成缺乏语义的万能 tuple？
6. 开放世界、显式否定、未知、矛盾、传闻、误解、争议和假设需要怎样的真值与承诺模型？
7. 人物认知、读者视角、作者正典和正典分支应使用统一 Context 机制，还是保持不同语义系统？
8. 推导规则、缺省推理、证明链、真值维护、完备性契约和物化索引分别何时成为必要能力？
9. 原 LWCM 的六层中，哪些应保留、拆分、合并或删除？RBOS/FRI 最终应处在什么位置？

请提出一个修订后的长期目标模型，并至少给出：

- 核心概念及严格边界；
- 不变量和查询语义；
- 最小的一等记录类型；
- 文档正典与可计算正典的协调机制；
- 卡片编辑模型与百科查询模型的对应关系；
- 查询答案应返回的真值、来源、推导等级、完备性和解释信息；
- 能击穿错误设计的反例与压力测试；
- “必要内核—高级能力—纯性能优化”的分层。

可以借鉴时间数据库、数据库溯源、知识表示、事件演算、多上下文系统、信念修正、Datalog、RDF/OWL、属性图和因子化数据库，但只在它们真正解决上述矛盾时引入。

明确区分：

1. 已有理论；
2. 对已有理论的组合；
3. 你在本问题中提出的新设计判断。

不要输出 SQL、API、迁移方案或前端实现。重点是语义、数据结构、推理边界和反例。宁可推翻 LWCM，也不要为了维护上一轮结论而补丁式扩展它。
```

该轮输出形成了 HCSM，其历史结论保留在第 11 节；当前第 5～9 节已由后续 HCSM-R3 取代。

### 10.2 已完成：HCSM 第三轮工程语义证伪

```text
请把 HCSM（异质正典语义模型）视为候选，而不是既定答案，对它进行第三轮证伪，并把结论约束到一款真实的长篇小说创作系统。

系统当前已经分别拥有：CoreEntity 与类型化 Profile、可发布和修订的 World Bible 页面、二元关系、事件、人物知识、读者揭示、Evidence/TargetRef、AI 建议与作者采用、Scene/MemoryEvent 历史重放，以及只读“问世界”。目标是把世界对象和世界书统一为“人物与世界”的卡片系统，并允许它发展成完整知识表示和百科查询平台。

HCSM 当前主张：

- 正典异质但权威入口统一到作者发布或采用行为；
- Referent 与 KnowledgeResource 分离；
- ResourceRevision、Fragment、CanonRevision 构成发布权威平面；
- SemanticSchema、Predication、Statement、Attestation 构成选择性语义化平面；
- 客观世界、人物信念、读者可访问和假设使用不同求值制度；
- 正文与结构采用正文主导、结构主导或双重作者表达三种耦合所有权；
- Statement 按独立引用、模态、生命周期、跨资源同一、推理或事件身份需求惰性提升；
- FRI、缓存和物化始终非权威。

重点寻找 HCSM 在工程语义上的失败，而不是继续增加名词：

1. CanonRevision 如何与工作稿、页面发布、手工对象保存、AI 建议采用、批量采用包、撤回、恢复、分支和合并形成一个无歧义的状态机？
2. Referent、KnowledgeResource、Card、Document、Scene 和世界内文档的身份关系，是否仍有无法表达或产生重复身份的反例？
3. Fragment 怎样跨 ResourceRevision 保持可追踪锚定；文本移动、拆段、合并、改写和字段类型变化时，何时应继承、失效或要求作者复核？
4. 三种正文—结构耦合模式应绑定到 Schema、字段、Fragment 对齐还是单次作者行为？模式改变时怎样防止双写和历史语义漂移？
5. Predication 的即时编译与 Statement 的持久提升怎样共存；如何定义跨资源、跨版本的 Statement 同一性而不依赖脆弱内容哈希？
6. ObjectiveWorld、AgentBelief、ReaderAccessible、Hypothetical 和 DocumentarySearch 的输入、输出与显式桥接边界能否形式化；人物说话、观察、学习、遗忘和倒叙揭示怎样通过反例检验？
7. HCSM 怎样消费现有 Scene/MemoryEvent 历史重放，又不建立第二套竞争的世界状态账本？
8. 当正文证据足以让人类回答、结构层却未知时，百科查询怎样给出有用答案，同时不让 AI 临时解释取得正典权威？
9. 三种完备性——关系扩展、形式化覆盖、求值执行——怎样被声明、组合和传播？
10. 哪些 HCSM 类型是不可约的，哪些可以降为关系、用途或可重建视图？

请输出：

- 对 HCSM 最强的证伪和反例；
- 修订后的最小逻辑聚合、所有权和状态转换；
- 从当前项目概念到目标概念的语义映射，但不要写 SQL、API 或代码；
- 必须始终成立的不变量；
- 可验证这些不变量的叙事压力场景；
- 必要内核、高级语义能力和纯性能优化的边界；
- 哪些结论足以进入 ADR，哪些仍只能留在研究账本。

不要以迁移成本或开发周期压低长期目标，但必须指出任何会造成双重真相源、隐式正典晋升、历史覆盖、人物／读者泄漏或不可解释查询的设计。
```

该轮输出形成 HCSM-R3，其历史结论保留在第 11 节；当前第 5～9 节已由第四轮删除型修订取代。

### 10.3 已完成：HCSM-R3 最小闭合性与不变量证伪

```text
请对 HCSM-R3 进行第四轮证伪。它仍是候选，不是已证正确的架构。本轮目标不是继续增加知识类型，而是判断这个修订内核是否已经最小、闭合、无双重权威，并能在真实长篇小说编辑中维持历史语义。

系统目标是把世界对象和世界书统一为“人物与世界” Card 工作空间，并允许发展为完整知识表示与百科查询平台。作者可编辑 Profile、World Bible 正文、关系、Event 与 Scene；系统同时维护 AI Proposal、作者采用、人物信念、读者揭示、Scene/MemoryEvent 历史重放和只读“问世界”。

HCSM-R3 当前压缩为：

- 四个语义聚合：Referent；KnowledgeResource / ResourceRevision / FragmentOccurrence / FragmentLineage；Statement / Attestation / SemanticBinding；CanonRevision / CanonBranch；
- 一个版本化 Schema 注册表；
- ObjectiveWorld、AgentBelief、ReaderAccessible、Hypothetical、DocumentarySearch 五种隔离求值器；
- Predication 是无身份值，Statement 内容不可变；
- Card 是复合工作空间，不是最小发布单元；
- CanonRevision 是分支相对的不可变完整选择快照；
- SemanticBinding 分为写入方向、对应强度、生命周期依赖三轴；
- 每个时态 Schema 只有 direct、history、derived 中的一种权威生成方式；
- 查询同时区分形式结论、正典文档证据、非权威 AI 解释与三种完备性；
- FRI、物化、索引和缓存永久非权威。

请先尝试用反例推翻这些不变量，重点检查：

1. 四个聚合是否仍有职责重叠，或者某个核心类型可被删除；
2. 概念上的完整 CanonRevision 快照能否在撤回、恢复、批量采用、多父合并和 Schema 政策变更中保持无歧义；
3. 资源的最小生命周期边界能否避免 Card 内 Profile、正文、关系、事件和 AI 审查之间的误发布；
4. 人物对话、撒谎、转述、世界内信件、叙事旁白和作者说明是否需要更严格的断言力模型；
5. FragmentLineage 和三轴 Binding 在移动、拆分、合并、否定或模态改写后是否会错误继承语义；
6. 不可变 Statement 的同一性、等价、修订和 Schema 兼容关系能否在不依赖内容哈希时保持可判定；
7. direct、history、derived 唯一权威是否足以表达初始状态、历史校正、局部时间范围和 Schema 升级；
8. 五种求值器和显式桥接能否阻止“说出→相信”“看见→理解”“读者看到→人物知道”等泄漏；
9. 形式化覆盖的范围声明是否真能支撑负面、唯一性、计数和穷尽答案。

请输出：

- 对 HCSM-R3 最强的反例与不可兼容三难；
- 经过删除测试后的最小闭合记录类型和所有权图；
- 工作稿、资源版本、作者采用、正典快照、分支和合并的形式状态转换；
- 每条不变量的最小反例、验证方法和修订建议；
- 哪些候选 ADR 应保留、合并、改写或删除；
- 仍然不可判定、必须继续研究的问题。

不要输出 SQL、API、迁移、前端或性能优化方案。除非一个新类型能解决已证明无法由现有类型表达的反例，否则禁止增加名词。不要为了维护 HCSM-R3 而修补它；如果核心不成立，直接推翻。
```

该轮输出形成 HCSM 第四轮最小内核，并已记录在本文第 5～9 节。

### 10.4 已完成：六记录内核的可判定自动化边界

```text
请对 HCSM 第四轮得到的“六记录最小内核”进行第五轮证伪。它仍是候选，不是已证正确的架构。本轮不再追求更多记录类型，而是确定：在什么受限语言、断言力、版本规则和完备性条件下，哪些自动语义判断可被证明安全，哪些必须永久保留作者裁决。

背景是一款长篇小说创作系统。它要把世界对象和世界书统一为“人物与世界” Card 工作空间，并允许发展为完整知识表示与百科查询平台。系统同时存在 Profile、World Bible 正文、Scene、Event、MemoryEvent、AI Proposal、作者采用、人物信念、读者揭示和只读“问世界”。

当前候选仅保留：

- 六种核心记录：Referent、KnowledgeResource、ResourceRevision、Statement、Attestation、CanonRevision；
- TargetRef 作为 `(ResourceRevision, Selector)` 值，Predication 作为无身份值；
- Schema 和形式规则复用 KnowledgeResource / ResourceRevision；
- CanonRevision 只固定资源版本、作者准入 Attestation 与语义环境，不存派生闭包；
- Attestation 用 issuer、force、content、grounds、时间和溯源表达断言行为；
- 基础状态、事件、校正和撤回共同进入唯一正典基础，当前状态由固定规则版本求值；
- WorldEval 与 BeliefEval 是两个真值求值器，假设是覆盖层，ReaderAccess 和 DocumentSearch 不产生真值；
- 否定、计数、唯一性与穷尽答案需要来源闭合、语义覆盖、身份闭合和执行完整四项查询义务；
- FRI、检索、物化和缓存永久非权威。

请优先攻击以下问题：

1. 六种记录是否真的闭合；Schema、规则、完备性声明、编辑谱系和世界规范能否全部用现有记录表达，而不让 Attestation 成为新的万能 tuple？
2. “作者准入 Attestation”如何与 Attestation 自身的 issuer 分离；作者确认“人物说了这句话”时，是否需要嵌套行为，以及如何阻止人物内容泄漏为客观真相？
3. 删除 SemanticBinding 后，force、grounds、cites 和资源政策是否足以无歧义表达来源依赖解释、独立采用、结构生成正文、失效和冲突？
4. CanonRevision 的闭合条件能否阻止循环依赖、悬空 TargetRef、缺失 Schema、规则版本漂移、多父合并歧义和 AI Proposal 伪装成作者输入？
5. 直接有效区间、初始状态、事件效果和后续校正叠加时，版本化时态求值如何处理冲突、取代和未知，且不引入隐式优先级？
6. 哪个受限 Statement 语言是长期有用又可判定的；哪些等价、兼容、时间和规则判定可自动证明，哪些只能作为候选？
7. 四项完备性义务如何成为可失效、可组合、可验证的查询证书，而不是由作者或 AI 随意填写的四个布尔值？
8. 对文本重锚定、断言力识别、Statement 等价、Schema 迁移、合并解决和完备性认证，分别给出“可自动执行”“只能生成候选”“必须作者确认”“理论上不可通用决定”的边界。

请输出：

- 对六记录内核最强的反例、删除测试和闭合性证明或反证；
- 最小 Statement 语言、Attestation 断言力和 CanonRevision 闭合条件的形式定义；
- 基础状态、事件、校正、冲突和未知的小步求值语义；
- 四项查询义务的证书结构、失效规则和组合规则；
- 自动化安全边界决策矩阵；
- 哪些候选 ADR 可以进一步稳定，哪些必须改写、合并或删除；
- 哪些问题不可判定、不可通用自动化，必须永久保留作者裁决。

不要输出 SQL、API、迁移、前端或性能设计。除非新核心记录能解决一个已证明无法由六记录表达的反例，否则禁止增加名词。对每个自动化主张，都必须给出适用语言、前置条件、终止性、失败模式和最小反例。
```

该轮推翻了绝对闭合、记录类型数最小、单一 issuer 和可写完备性状态，形成相对 `K/Auth` 闭合、
六项语义职责、封闭行为类型、固定 kernelVersion 和可重放查询证书候选；其当前综合已由第六轮继续删除和改写。

### 10.5 已完成：元内核与证书可执行性证伪

```text
请对 HCSM 第五轮候选进行第六轮证伪，主题是“元内核与证书可执行性”。不要复述模型，也不要默认六项职责、K/Auth 边界、行为代数、时态语义或 S/F/I/X 已经正确；请优先寻找会导致自指、越权、非终止、隐式优先级或伪造证明的最小反例。

当前候选只主张：在外部授权根 Auth 和固定元内核 K 下，Referent、KnowledgeResource、ResourceRevision、Statement、Attestation、CanonRevision 六项语义职责相对闭合；物理记录数不限。CanonRevision 固定输入、kernelVersion 和 committer；项目 Schema 不能重定义 K。Attestation 使用封闭 act 联合类型，外部准入、对象层角色、内容归因和 provenance 分离。真值在固定有限域上以显式正反支持、Effect、persistent inertia 和 Defeat 求闭包。查询完备性由 S/F/I/X 证明制品表达，verdict 必须由可信检查器重算。

请集中攻击：

1. 给出 K 的最小规范内容。逐项证明某项必须在 K 中，或可安全下放为项目资源；检查项目规则能否通过自指、元谓词、动态规则、授权引用或证明内容绕过 K。
2. 为 act 代数建立不少于 30 个叙事压力案例，覆盖隐藏信念、撒谎、转述链、讽刺、玩笑、引用、梦境、幻觉、预言、命令、承诺、契约、法律宣告、仪式、世界内文档、不可靠旁白、作者说明和 AI 解释。逐例演算 WorldEval、BeliefEval 与行为事实，找出缺失 act 或错误桥接；只有现有类型确实无法表达反例时才允许增加 act。
3. 严格定义有限 Statement 语言与小步时态语义，证明或反证：终止性、确定性、冲突旁一致、无隐式优先级、Defeat 传播无环、时间边界一致。分别测试初始状态、直接区间、事件效果、延迟效果、并发事件、回溯校正和部分撤回。
4. 对正向、负向、存在、全称、唯一、计数、排序极值和时间区间查询，分别构造 S/F/I/X 证书、组合规则、失效规则和最小反例。明确哪些可 machine-proved，哪些最多 assumption-backed，哪些在开放正文中不可证明。
5. 证明制品复用普通 ResourceRevision 时，验证器如何拒绝作者或 AI 自称 proved、循环证明、陈旧依赖、替换 checker profile、跨 CanonRevision 偷用结果和通过世界内 Statement 断言元级证明。
6. 研究 CanonRevision C1→C2 的增量证明复用：只允许基于显式依赖切片和固定 K 的安全复用；给出会使复用失效的最小变化。不要把缓存命中当作证明。
7. 定义 kernelVersion 的身份和窄兼容判定。说明 K1 查询为何不能被 K2 重解释，以及新增未使用语法、规则效果变更、时间边界变更和证明检查器变更分别如何处理。
8. 用多作者、角色权限、撤销授权、并发提交和恶意 committer 反例检验 Auth 是否能始终留在语义层之外；若不能，指出泄漏发生在哪里，但不要把账户模型塞进 Statement 或 Attestation。

请输出：最小 K 规范；act 压力矩阵与修订；Statement 语法和求值规则；终止／确定性证明或反证；按查询族划分的 S/F/I/X 证书；证明攻击清单；跨版本复用与 kernel 兼容矩阵；主张的证明状态（已证、反例推翻、仅候选、不可通用决定）；应保留、改写或删除的候选 ADR；下一轮唯一最高价值研究问题。

不要输出 SQL、API、迁移、前端、性能或当前代码适配方案。不要以工程成本压低理论目标，也不要凭新名词掩盖反例。引用已有理论时标出原始来源，并严格区分文献结论、由文献支持的推论和你在本问题中的新设计判断。
```

该轮用 40 个叙事行为案例将 act 代数压缩为唯一 Assert，删除 Proposal／Interpretation／Defeat 的内核地位，
把 Auth 改为提交时历史准入，把惯性证明改为含 antiDeps 的非单调分段求值，并删除绝对化 `machine-proved`。
当前第 5～9 节已完成主验收后的第六轮修订。

### 10.6 已完成：有限偏序时间下的模态惯性

```text
请对 HCSM 第六轮候选进行第七轮证伪，唯一主题是“有限偏序世界时间下的分支敏感惯性与查询证书”。不要扩展到数据库、API、前端或当前项目迁移，也不要默认“枚举所有拓扑排序”就是正确语义。

当前已经保留：六项语义职责；唯一 Assert(regime=world|belief(holder), polarity, content, TimeScope)；惰性 StatementRef；固定规范内核 K；提交时历史准入；显式正负支持；supportDeps、antiDeps、closureDeps；S/F/I/X；相对化 verified-support。当前 TimeScope 区分 Timeless、Point(t,pre|at|post) 和半开 Interval，只对有限全序时间给出分段求值。惯性依赖区间内不存在 Stop，因此对输入非单调。同一相位 Start/Stop 无显式子顺序时返回 transition-underdetermined。若事件先后不可比较，当前只能返回 temporal-underdetermined。

请优先攻击以下问题：

1. 给出最小有限偏序时间模型。明确时间点、pre/at/post 相位、区间、相等、严格先后、并发、重叠和未知关系中哪些必须进入内核，哪些可由项目 Schema 表达。检查偏序、区间序或分支时间哪一种真正适合长篇叙事。
2. 判断“每个合法线性扩展是一条时间世界”是否充分。构造会因任意拓扑排序、重复事件、相等时间、区间重叠或相关约束而产生错误的最小反例；若线性扩展不充分，提出更小的替代语义。
3. 严格区分四类结果：同一时间世界中的正反支持冲突、同一边界的 transition-underdetermined、不同合法时间世界之间的 temporal-underdetermined、作者显式 Hypothesis／正典分支。禁止把互斥世界中的 +p 与 -p 合并成 both。
4. 定义每条时间世界上的惯性，再定义跨世界的 necessary、possible、impossible 和 underdetermined。说明正负支持、Start/Stop、直接区间、延迟效果、并发事件、回溯校正和局部撤回怎样组合。
5. 对 before／after／at／throughout／sometime／first／last／duration／overlap 查询分别给出语义。特别攻击“first/last”在多个不可比较最小／最大事件下是否仍有单一答案。
6. 为 necessary／possible 查询定义 proof payload。说明 supportDeps、antiDeps、closureDeps 如何量化到全部或部分时间世界；哪些证书可以用一个见证世界，哪些必须覆盖所有合法世界。
7. 给出 S/F/I/X 在偏序时间中的新含义。时间约束未闭合、自由文本事件未形式化、事件身份未合并、规则执行被截断时，分别应返回 verified、assumption-backed、incomplete 还是 temporal-underdetermined。
8. 研究 CanonRevision C1→C2 新增时间约束、事件、Stop、same-event、different-event 或顺序边时，哪些证书失效，哪些 possible／necessary 结论可安全复用。缓存命中不得充当证明。
9. 分析终止性、确定性、可判定性和复杂度。可以讨论符号化偏序、等价类或偏序约简，但不得用性能技巧掩盖语义错误；若某类查询不可通用自动决定，明确给出边界。
10. 用至少 20 个互不重复的叙事压力场景验证模型，覆盖倒叙、未知日期、同日无先后、并发战线、消息延迟、预言、死亡与复活、任期交叠、失踪、时间旅行叙述和作者后来补定顺序。

请输出：最小时间结构；形式求值规则；四类冲突／未定状态判别；查询语义矩阵；necessary／possible 证书结构；S/F/I/X 传播；跨 CanonRevision 失效矩阵；压力案例；每项主张的证明状态（已证、反例推翻、仅候选、不可通用决定）；应保留、改写或删除的候选 ADR；下一轮唯一最高价值研究问题。

引用已有理论时使用原始来源，并严格区分文献结论、由文献支持的推论和本问题中的新设计判断。除非一个新核心概念能解决现有值、规则和证书无法表达的反例，否则不要增加名词。
```

该轮推翻了严格线性扩展、不可比即整体未定、单值 first／last 和纯顺序 duration；经定向补证后，将当前候选
改写为显式有限 DNF TemporalTheory、允许同刻的时间实现和局部非确定转移轨迹，并把 chronology 未知与
Hypothesis／CanonBranch／本体多时间线分离。当前第 5～9 节已完成主验收后的第七轮修订。

### 10.7 已完成：受限时态模态证书 calculus

```text
请对 HCSM 第七轮候选进行第八轮证伪，唯一主题是“受限时态模态证书是否能够 sound、complete 且可重放”。不要扩展模型范围，也不要预设证书短、算法为多项式或 SAT/SMT 输出天然可信。

唯一研究语言如下：

- TemporalTheory 是显式有限 DNF；
- 每个 Scenario 只含 Eq、Neq、Lt、Within 和可选 STP 差分约束的有限合取；
- 时间相位固定为 pre/at/post，Interval 半开；命名时间、Calendar 和单位由 C 固定；
- 状态语言保持有限有符号 fluent 与第七轮受限正向规则；
- guard 只读边界前状态；同边界 Start/Stop 使用固定局部非确定转移关系；
- TemporalTheory 析取表示同一正典内相关 chronology 未知，不是 Hypothesis、CanonBranch 或本体多时间线；
- 不含任意 Boolean 压缩、量词、递归时间生成、自然语言日历、完整 Allen 代数和项目脚本。

请优先尝试推翻以下主张：

1. possible 可由一个合法 `(Scenario, ρ, χ, Trace)` 见证证明；necessary／impossible 可由对反例公式的可重放不可满足证明或完备世界覆盖证明；underdetermined 可由两个同范围、不同结果的合法见证证明。
2. 一个独立 checker 能仅依赖固定 K、C、规范化查询、TemporalTheory、规则/effect digest 和 proof payload 重放 verdict，且普通 Statement、作者或 AI 无法自称通过。
3. supportDeps、antiDeps、closureDeps 足以表达模态量词下的全部失效原因；特别检查惯性无 Stop、Scenario 覆盖、同边界 χ、occurrence identity、Calendar 和 metric entailment。
4. S/F/I/X 能给出 verified 的充分条件，并能区分真实 temporal/transition-underdetermined 与来源未闭合、文本未形式化、身份未解、求值截断。
5. C1→C2 新增／删除 Scenario、Eq/Neq/Lt/Within/STP 约束、Start、Stop、直接支持、same-event、different-event 或 Calendar 变更时，可以只凭显式依赖切片安全复用一部分证书。

至少构造：possible 见证被新约束排除；necessary 因新增 Scenario 失效；新增约束使 underdetermined 收敛；同一 ρ 下 χ 改变结果；不同 ρ 分别支持正负但没有同世界 conflict；`∀w∃t` 与 `∃t∀w`；并列 first；metric duration 多解；未形式化正文排除见证；checker bug 修复但 K 不变；恶意 proof payload、循环 proof、遗漏 Scenario 和伪造 closure 的攻击。

请输出：精确 proof judgment；possible／necessary／impossible／两类 underdetermined 的最小 payload 与检查规则；soundness 证明或最小反例；对该受限语言的 completeness 证明、反证或明确边界；证书长度下界与复杂度状态；S/F/I/X 充分条件；C1→C2 失效矩阵；攻击清单；候选 ADR 的保留／改写／删除；下一轮唯一最高价值研究问题。

每项结论标注“已证、文献结论、文献支持推论、仅候选、反例推翻或不可通用决定”。引用原始来源，不能把 STP、order-incomplete data、SAT/SMT proof 或线性扩展计数的结论直接移植到本模型。不要输出 SQL、API、数据库、前端、迁移或当前项目实现方案。
```

该轮推翻了“两条差异轨迹即可证明 temporal-underdetermined”、空模型上的真空 necessary、solver 自报 UNSAT、
无条件 completeness 和仅凭依赖标签安全复用。经定向补证后，当前第 5～9 节改为五层 proof judgment、完整解释
上下文、三类世界依赖、结果包络诊断、条件式构造性 completeness，以及 formal-relative／canon-relative／
assumption-backed 分层。没有新增第四类语义依赖。

### 10.8 已完成：异质正典的可组合闭合契约

```text
请对 HCSM 当前候选进行下一轮只读证伪，唯一主题是“异质正典的可组合闭合契约”。不要继续修改时态模型、proof calculus、Statement 语言、数据库、API、前端或迁移。

当前固定前提：

- 受限形式查询只能先得到 verified-formal-relative；
- verified-canon-relative 还需要 machine-closed 的 S/F/I；
- 自由正文、World Bible 页面、Profile、关系、Event、Scene 和混合 Card 可以同时具有正典权威；
- 页面不是默认事实源，结构也不能默认覆盖正文；
- 作者闭合声明只能产生 assumption-backed，不能伪装为机器证明；
- proof payload、AI、普通 Statement 和缓存不能自证 closure。

请优先证伪：

1. 为每个 query family 定义最小语义所有权契约：哪些资源、字段、正文片段和结构值可增加正向事实、负向事实、时间约束、事件效果、identity 或穷尽域。
2. 证明或反证多个资源契约能否组合为 S/F/I closure，而不产生双重真相源、遗漏来源或循环声明。
3. 处理同一 Card 中正文与结构的正文主导、结构主导、双重作者表达和纯说明字段，并给出各自最小反例。
4. 定义 machine-closed、assumption-backed、incomplete 的 closure judgment 和信任根；普通作者声明不得自行升级为 machine-closed。
5. 检查撤回、ResourceRevision 更新、CanonRevision 切换、资源新增、字段类型改变、same-event/different-event 和正文重锚定怎样使 closure 失效。
6. 对正向、负向、存在、全称、唯一、计数、first/last 和时间惯性分别给出最小 S/F/I；禁止假设一个全局 closure 对所有查询族通用。
7. 构造至少 25 个异质正典攻击案例，覆盖正文漏结构、正文结构冲突、穷尽页面后新增事件卡、别名未解、重复 occurrence、AI 解释误纳、纯说明字段误判、策略循环和作者错误声明闭合。
8. 判断 closure contract 应属于 K 规范、项目 Schema、ResourceRevision 内容还是 CanonRevision manifest；除非 deletion test 证明必要，不新增核心记录。
9. 给出 C1→C2 的 closure 复用定理或反例，区分来源新增、语义所有权改变、形式化覆盖改变和身份域改变。
10. 明确哪些 canon-relative verdict 可机器证明，哪些永久只能 assumption-backed，哪些在开放正文中不可通用决定。

请输出：精确 closure judgment；最小语义所有权契约；S/F/I 的组合与失效规则；攻击矩阵；formal-relative 到 canon-relative 的升级条件；候选 ADR 的保留／改写／删除；下一轮唯一最高价值问题。

每项主张标注已证、反例推翻、仅候选或不可通用决定。引用原始来源时严格说明来源只证明了什么。不要讨论工程实现或性能。
```

该轮推翻了 query-only Need、全 Card 正文／结构模式、全局 closure 布尔值、局部 identity 自动合并、policy 自指和
作者声明可自证内容完备。经定向补证后，当前第 5～9 节改为 claim-sensitive `Need(Σ,J)`、六个来源通道、
family-local `owns | excluded`、S/F/I 三值、有限 manifest selector、非循环 ClosureContext 与 ADR-0006 的当前
所有权映射。没有新增 Ownership 核心记录。

### 10.9 已完成：opaque 正文的构成性语义收束边界

```text
请对 HCSM 当前候选进行下一轮只读证伪，唯一主题是“opaque 正文的构成性语义收束边界”。不要修改时态模型、proof calculus、Statement 语言、ownership vocabulary，也不要讨论数据库、API、前端、迁移或性能。

固定前提：

- closure 使用 claim-sensitive Need(Σ,J)；
- ownership 只有 owns/excluded；
- arbitrary prose 若继续作为 independent owner，其形式化完整性默认只能 assumption-backed；
- 作者逐项确认 AI 提取，不自动证明不存在遗漏；
- TargetRef 只在不可变 ResourceRevision 内稳定；
- hardGround 决定失效，cite/derivedFrom/provenance 不授予真值；
- 当前 ADR-0006 使 World Bible page 对 WorldEval 事实 family excluded；
- 不恢复通用 SemanticBinding 核心记录，除非 deletion test 证明现有职责无法表达。

请只研究三条候选路径：

1. controlled language：正文语法是否足以由 K 总解析；
2. 构成性切分：作者能否把有限 text surface 的 family-specific 语义定义为一个精确 Statement/Assert 集，并明确放弃映射外的独立权威解释；
3. evidence-only：文本 excluded，结构 Assert owns，文本只保留 documentary/cite 作用。

请优先攻击：

- author-ratified mapping 在正文仍为 opaque independent owner 时为何仍不完备；
- 一对一、一对多、多对一和跨片段语义能否被构成性切分；
- 否定、模态、时间、引语、讽刺和隐含语义是否阻止总解析；
- 拆段、合段、改写、重锚定、字段变更和 CanonRevision 切换如何使 coverage 失效；
- 构成性切分是否实质上把文本降为展示／证据，从而失去“正文独立正典”；
- 是否存在必须新增核心 SemanticBinding 才能表达的最小反例；若 TargetRef、Statement、Assert、hardGround 和 ResourceRevision 足够，禁止新增；
- machine、assumed、open 的 F judgment 和 C1→C2 复用条件。

请输出：

- 三条路径各自的精确语义与 deletion test；
- opaque prose owner 可达／不可达 machine-closed F 的定理或反例；
- 最小 correspondence/coverage judgment；
- 至少 25 个文本语义攻击案例；
- ADR 保留、改写、删除；
- 下一轮唯一最高价值问题。

不得预设 author-ratified mapping 能升级为 machine-closed；如果它只能证明“作者确认过”，必须明确保留 assumption-backed。
```

该轮证明 finite author-ratified mapping 不能 machine-close opaque independent prose owner；同时推翻“构成性 mapping
必然让 text excluded”。经定向删除测试后保留 A 型 constitutively formalized text owner 与 B 型 Assert authority
substitution：二者只在不观察直接 owner 的普通 WorldEval 上条件等价。`Corr`／`FormalCover` 是 judgment，mapping
entry／coverage root 是值；没有新增 SemanticBinding、mapping root 或 Boolean hardGround language。

### 10.10 已完成：构成性形式化与权威切换事务

```text
请只读证伪 HCSM 的“构成性形式化与权威切换事务”。不要讨论 SQL、API、UI、迁移或性能。

固定前提：

- opaque independent owner 不能靠 finite author-ratified mapping machine-close；
- A：text owns，C 固定的 total constitutive formalizer φ 完全定义其权威语义，派生 Assert 没有独立 authority；
- B：text excluded，exact Assert surfaces owns，mapping/hardGround 表达对应与失效；
- A/B 对普通 WorldEval 可能条件等价，但 immediate owner、source explanation 与生命周期不同；
- Corr、FormalCover、AuthoritySubstitution 是 judgment，MappingEntry、coverageRoot 是值；
- correspondence manifest 复用 KnowledgeResource/ResourceRevision，不新增 SemanticBinding；
- AI Interpretation 是非权威 workflow candidate，采用后必须产生新的 sealed resource；
- flat hardGround set 是 conjunction，替代依据使用多个同语义 Assert；
- K 固定 total-formalizer interface，具体 grammar/lexicon 由 C 固定的 SchemaRevision 定义；
- 旧 C 不被新政策追溯重解释。

唯一研究目标：

1. 定义从 opaque owner 到 A 或 B 的原子 CanonRevision 转换；
2. 判断 A/B 哪些状态可互相转换、撤回或回滚而不形成双 owner或无 owner；
3. 定义 direct authority、ultimate ground、documentary source 和 executable support 的解释图；
4. 给 text 删除、mapping 撤回、Assert 独立修订、Schema 变化和多父合并的状态机；
5. 证明或反证多个 partial correspondence revisions 经一份 total coverage manifest 安全组合的条件；
6. 给 C1→C2 proof/closure 复用条件；
7. 对 authority transition、total manifest 和 explanation edge 逐项做 deletion test，除非既有六项职责不能表达，否则不新增核心记录。

输出：最小状态机、A/B 观察等价与区分反例、原子准入条件、撤回/合并矩阵、复用定理或反例、候选 ADR 保留/改写/删除。
每项结论标注已证、反例推翻、仅候选或不可通用决定；不要用新名词替代已有值、规则和 ResourceRevision。
```

该轮推翻“每个 key 恰有一个 owner”“A/B 可复用旧 closure certificate”和“权威切换需要新事务记录”。经主验收
收紧为 representation-chain-local 的 O/A/B 派生状态、显式 closed-empty、sealed candidates + 新 CanonRevision +
单次 Admit 的原子边界，以及 proof skeleton 运输后在 C2 重放。四类 explanation edge 均可由既有语义派生。

### 10.11 已完成：SchemaRevision 的 family-local 语义兼容

```text
请只读证伪 HCSM 的“SchemaRevision family-local 语义兼容”。不要讨论 SQL、API、UI、迁移或性能。

固定前提：

- 旧 CanonRevision 永远使用其 exact SchemaRevision；
- 新 Schema 不追溯重解释旧 C；
- K 只固定 total-formalizer interface 和核心语义；
- grammar、lexicon、family mapping、surface catalog、identity/domain 规则属于 SchemaRevision；
- A/B authority transition、proof acceptance 和 canon closure 分开；
- O/A/B 是同一 representation chain 上的 checker judgment，不是记录枚举；
- 不新增通用 SemanticBinding、迁移脚本或任意程序等价判定。

唯一目标：

1. 定义 `SchemaCompat(S1,S2,Need(Σ,J))` 的可检查充分条件；
2. 分别攻击字段重命名、类型收窄／拓宽、默认值、字段拆分／合并、grammar 与 lexicon 变化、identity/domain 扩张、规则依赖变化和 unknown surface；
3. 判断哪些变化允许 A 的 φ 输出、B 的 Assert 解释、S/F/I 和 proof skeleton 保持；
4. 给 exact unchanged、declarative translation certificate、assumption-backed compatibility 和不可通用决定的边界；
5. 给 C1→C2 复用与多父 Schema 合并的最小反例；
6. 对 compatibility record 做 deletion test，优先复用 Schema/ResourceRevision 与 proof artifact；
7. 输出完成本轮后距离完整实现 Spec 仍缺的产品／语义裁决，不能把形式推理无法决定的作者选择伪装成未完成证明。

输出 family-local compatibility judgment、攻击矩阵、复用定理或反例、ADR 裁决和实施 Spec 前剩余决策。每项主张标注
已证、反例推翻、仅候选或不可通用决定；不得把“新字段不需要新 K”偷换成“所有旧 query 都兼容”。
```

该轮推翻裸 `SchemaCompat(S1,S2,Need)`、单边旧 dependency slice、类型拓宽自动兼容和新 Schema 沿用旧证书。
当前只保留带 `canon-pair | universal` scope 的 exact relevant slice 与有限声明式 translation 两条 machine-compatible
路径；compatibility 是 judgment，translation 是 proof／Schema resource，没有新增 MigrationMap 或兼容核心记录。

### 10.12 已完成：空白自定义类型渐进 Schema 化

```text
请只读证伪 HCSM 的“空白自定义类型渐进 Schema 化”。不要讨论 SQL、API、UI、数据库迁移或性能。

固定前提：

- 旧 CanonRevision 固定 exact SchemaRevision，新 Schema 不重解释旧卡片；
- Schema compatibility 区分 exact、verified translation、assumption-backed、open/invalid；
- AI 只能建议字段和类型，不能自动授予 ownership 或 world truth；
- family/domain/channel/surface 使用 owns|excluded；
- A/B/O 是 representation-chain-local judgment；
- 新 CanonRevision 是 seal 后资源取得 authority 的唯一原子边界；
- 不新增 DynamicEntity、SemanticBinding、MigrationMap 或 compatibility 核心记录。

唯一目标：

1. 定义无模板空白卡片中标题、正文、自定义字段的初始 documentary／WorldEval authority；
2. 定义作者何时把字段构成性提升为 typed owner；
3. 处理已有自由值不满足新类型、缺字段、default、enum、字段拆分、alias／identity 和跨卡片模板采用；
4. 区分“只是新建模板”“采用新 Schema”“把历史内容解释为事实”三种作者行为；
5. 定义新 CanonRevision 的原子准入、回滚、分支和多父模板合并；
6. 给旧卡片继续使用旧 Schema、新卡片使用新 Schema以及显式 translation 的共存语义；
7. 对 DynamicType、MigrationMap、自动事实提升和每种新 lifecycle record 做 deletion test；
8. 输出完整实施 Spec 前最后的产品选择，并明确哪些不能继续靠形式研究解决。

输出最小状态机、authority matrix、至少 25 个历史卡片攻击案例、SchemaCompat 使用边界、ADR 裁决和实施就绪结论。
每项主张标注已证、反例推翻、仅候选或不可通用决定。
```

该轮推翻完全无 Schema 的 blank card、模板自动升级旧值、parser／default 自动产生历史事实和 DynamicType／
MigrationMap。当前保留 BaseSchema 下的 generic documentary card、CreateTemplate／AdoptSchema／
PromoteHistoricalContent 三动作、D→V→A|B 显式 promotion、旧新 exact Schema 并存与 B-default 产品候选。
删除测试范围内已没有新的理论 blocker。

### 10.13 已完成：当前项目实现就绪差距审计

```text
请只读审计当前 ai-writing-assist 仓库，判断本文语义研究是否已经足以支撑实施 Spec 与代码分阶段开工。不要继续扩张
理论模型，也不要修改仓库。

必须核对 AGENTS.md、CONTEXT.md、整体设计、数据库设计、ADR-0006／0015／0016、world README，world／evidence／
story 相关 ORM、contracts、facade，以及前端 router、WorldView 与 WorldBibleTab。

采用第 9.2 节的候选产品基线并做 deletion test。特别遵守：不以万能 revision 表替换 TextArchive、MemoryEvent 和专用
历史；不新增顶级模块、队列、数据库技术、通用事件总线、万能 tuple、双写或长期兼容层，除非现有边界无法表达且有
最小反例。

输出：

1. 当前资产到 HCSM 六职责、Card、CanonRevision 与查询的精确映射；
2. 必须新增、必须保留、可删除／后置的最小物理持久化和模块职责；
3. ADR-0006／0015／0016 的保留、修订或取代；
4. API／schema／wire、novel_id／owner 与 AI authority 风险；
5. 从“人物与世界”主入口到导入／采用／历史／查询／写作上下文的阶段顺序和每阶段可验收出口；
6. 需要同步的权威文档与最小测试矩阵；
7. 仍阻止代码开工的未决项；若没有，明确给出 implementation-ready 裁决。
```

该轮核对实际 ORM、contracts、facade、ADR 和前端后裁决 implementation-ready：删除 Card／KR／RR／Statement 通用
物理根与新顶级模块，只新增 `world_assertions`、`world_canon_revisions`、`world_canon_heads` 和 typed custom Schema
启用前的 `entity_profile_template_revisions`。主验收修正了阶段依赖：Assert／Canon 基座必须先于 entity-bearing Name
与历史 promotion。第 12 节是后续 ADR／Spec 的实现交接；不再生成第十五轮理论提示词。

## 11. 研究与决策日志

### 2026-08-27：RBOS → LWCM → 项目适配评估

**输入**

- 目标：彻底统一世界对象与世界书，并允许上下游重构；
- RBOS：以对象、属性、共享锚点和被动关系推导为核心；
- LWCM：增加命题、来源、承诺、时间、事件、上下文、规则、证明和索引分层；
- 当前项目的 World、World Bible、CharacterKnowledge、Reader Reveal、Evidence、Context 和
  Story Continuity 实际边界。
- 分支对话形成的探索式研究账本及其 CWEM 下一阶段方向。

**方向已确认**

- 世界书主页作为“人物与世界”统一主入口；
- 所有常用和自定义空白类型进入卡片式管理；
- 不排斥完整知识表示和百科查询平台，后续研究不以 YAGNI 或当前工程成本限制语义上限。

**研究结论**

- LWCM 比原 RBOS 更适合作为完整语义模型；RBOS 更适合作为底层 FRI 查询索引思想；
- 卡片应是作者可编辑的知识资源与上下文投影的混合体，不是纯查询投影；
- 正典需要同时容纳文档分辨率和结构化命题分辨率；
- 真值是上下文相关的查询结论，但 Assertion、Commitment 和 Evidence 仍需成为可寻址记录；
- 当前项目已经拥有身份、修订、采用、知识视角、读者揭示、证据和历史重放基础，完整重构不是
  从零开始。
- 纯理论演化研究与项目适配研究分文档维护；前者不替代本文的产品与正典边界判断。

**未裁定**

- 最终模型名称、正式分层和数据库形态；
- KnowledgeResource 与 Entity 是否共享身份根；
- 文档正典与可计算正典的同步协议；
- 四值逻辑、Datalog、Truth Maintenance、正典分支和 FRI 的正式采用范围；
- 当前 ADR-0006 和世界事实所有权边界如何被修订或取代。
- 探索式研究账本的“卡片是语义投影”与本文“卡片是可编辑资源 + 投影”的分歧如何解决。

### 2026-08-27：LWCM 第二轮证伪 → HCSM 工程候选

**输入**

- 《LWCM 的第二轮证伪与重构：异质正典语义模型 HCSM》；
- 上一轮项目适配文档提出的文档正典、可计算正典、卡片混合模型和类型化视角问题；
- 当前项目的 World Bible 发布、对象采用、CharacterKnowledge、Reader Reveal、TargetRef、
  Evidence 和 MemoryEvent 边界。

**主要证伪**

- 作者发布的自然语言即使尚未形式化也具有正典效力，因此命题闭包不是完整正典；
- `Commitment` 混淆资源发布、来源表态和查询真值，不能继续作为万能基础记录；
- 卡片具有作者原生内容和不可变版本身份，不能降为实体查询投影；
- 正典版本、人物信念、读者访问和假设环境不是同一种 Context；
- Event Calculus 不能强迫初始状态、周期规律和原因未知的结果全部事件化；
- 作者版本首先是可分支和合并的 CanonRevision 图，数据库事务时间只是可选审计维度。

**进入本文的研究结论**

- HCSM 成为当前最强工程候选；它仍不是已采用架构或 ADR；
- 目标结构改为发布权威、选择性语义化、类型化求值三个平面，加证明／溯源和 FRI 两种非权威
  机制；
- 世界指称物与知识资源分离，卡片是 KnowledgeResource 的作者工作形态，不与 Referent 共用身份；
- 正典权威统一追溯到作者行为，但正典表达保持异质；
- 正文—结构对应必须声明正文主导、结构主导或双重作者表达；
- 普通字段可即时编译 Predication，只有命中独立引用、模态、生命周期、跨资源同一、推理或
  事件身份需求时才提升 Statement；
- 查询必须分别报告关系扩展完备性、形式化覆盖度和求值执行完备性。

**对上一轮当前综合的取代**

- “LWCM 是完整目标模型候选”改为“LWCM 是中间阶段，HCSM 是当前工程候选”；
- “Assertion / Commitment / Evidence”改为“Fragment / Predication / Statement /
  Attestation / CanonRevision / EvidenceUse”；
- “通用 Context”改为共享查询封装下的类型化求值制度；
- “系统记录时间是核心时间维度”改为“世界有效时间 + CanonRevision 为核心，事务时间按审计需要
  启用”；
- “卡片分歧待研究”改为“本项目明确采用混合知识资源判断”。

**仍未裁定**

- HCSM 的最小聚合、稳定身份和数据库映射；
- CanonRevision 与现有不同资产 revision/head/CAS 的统一范围；
- Fragment 跨修订锚定及耦合模式的生命周期；
- Statement 同一性、Attestation 状态和三种完备性的形式化；
- HCSM 与 Scene/MemoryEvent 历史重放的唯一状态所有权；
- 正式采用时如何修订 ADR-0006、当前“页面不是事实源”和 World 事实所有权。

**证据状态**

本轮已完整阅读并进行项目语义对照，但没有重新核验研究稿中提到的 Web Annotation、时间数据库、
OWL、Belnap、多上下文系统、缺省逻辑、AGM、ATMS、数据库溯源和因子化数据库文献。它们目前
只作为待验证理论线索，不能在 ADR 中当作已核实依据。

### 2026-08-27：HCSM 第三轮证伪 → HCSM-R3 修订内核

**输入**

- 《HCSM 第三轮证伪：面向真实长篇小说创作系统的修订语义内核》；
- 上一轮 HCSM 的三平面、Card 混合资源、Fragment 锚定、惰性 Statement 和三种耦合模式；
- 当前项目中 Profile 即时保存、World Bible 草稿／发布、AI 采用、Scene／MemoryEvent 重放和只读问世界的不同生命周期。

**主要证伪**

- 未形式化正文、AI 非权威和自动形式查询完备性不可同时满足；
- 作者发布只确认内容的正典出现，不等于对人物对话或世界内文档中所有命题作客观断言；
- 一张 Card 内的 Profile、正文、AI 审查和计算视图生命周期不同，因而 Card 不能是不可分割的发布单元；
- Fragment 重锚定只能证明位置对应，不能证明语义连续；
- `CanonRevision` 若由操作重放隐式定义，分支合并会因重放顺序而产生不同结果；
- Profile 当前值与 MemoryEvent 历史若同时可写，将形成两套竞争的世界状态账本。

**进入本文的研究结论**

- HCSM-R3 取代原 HCSM 成为当前工程候选，但仍不是已采用架构或 ADR；
- 候选内核压缩为四个语义聚合、一个版本化 Schema 注册表、五种求值器和非权威执行层；
- Card 是复合工作空间，独立生命周期的内容必须分成独立 KnowledgeResource；
- `CanonRevision` 是概念上完整、不可变、分支相对的正典选择快照；
- 片段改为版本内 `FragmentOccurrence` 与跨版本 `FragmentLineage`；
- 正文—结构耦合改为写入方向、对应强度和生命周期依赖三轴 Binding；
- Statement 内容不可变，Predication 仅为无身份值，哈希不决定语义身份；
- 每个时态 Schema 在同一正典范围内只有 direct、history、derived 中的一种权威方式；
- 问世界采用形式—文档双通道，完备性必须有谓词、对象域、资源集、时间和正典版本范围。

**对上一轮当前综合的取代**

- “Card 是混合 KnowledgeResource”改为“Card 是组合多个独立 KnowledgeResource 的产品工作空间”；
- “Fragment 可在资源版本间保持身份”改为“FragmentOccurrence 身份仅局部于单一版本”；
- “三种耦合模式”改为“三条正交耦合轴”；
- “CanonRevision 是正典编辑状态”改为“CanonRevision 是完整选择快照，编辑操作只是溯源”；
- “Scene／MemoryEvent 所有权待定”改为“Schema 指定唯一状态权威，Scene 本身不改写世界状态”。

**仍未裁定**

- CanonRevision 的项目范围和物理表示；
- Statement 等价、Schema 版本兼容和 FragmentLineage 自动继承；
- 分支自然语言合并、旁一致真值、缺省推理、信念修正、读者推理和反事实因果；
- 形式化覆盖的可验证估计和三种完备性传播；
- 与当前 CharacterKnowledge、Reader Reveal、ADR-0006 和 Scene／MemoryEvent 账本的正式迁移决策。

**证据状态**

本轮已完整阅读并进行项目语义对照，但未重新核验研究稿引用的 Git 版本图、W3C Annotation、PROV、
BIBFRAME、OWL 开放世界、事件演算、多上下文系统、完备性查询和缺省推理文献。这些只是待验证理论线索，
不能直接作为 ADR 证据。

### 2026-08-27：HCSM-R3 第四轮证伪 → 六记录最小内核

**输入**

- 《HCSM-R3 第四轮证伪：删除后的最小闭合内核、状态语义与剩余不可能性》；
- R3 的四个语义聚合、三轴 SemanticBinding、direct／history／derived 互斥状态权威、五种求值制度和三种完备性；
- 当前项目的 CoreEntity、Profile、World Bible、Scene／MemoryEvent、TargetRef、AI 采用、人物知识和问世界边界。

**主要证伪**

- FragmentOccurrence 可由不可变 ResourceRevision 和 TargetRef 定位，FragmentLineage 只是溯源，二者都不应作为核心记录；
- 三轴 SemanticBinding 存在含混组合，Attestation 的断言力、依据和资源所有权已可表达必要语义；
- direct、history、derived 分别属于基础陈述、历史组织和求值来源等级，将它们作为互斥 Schema 模式是分类错误；
- 假设、读者访问和文档检索不是与客观世界、人物信念同类的真值求值制度；
- 关系扩展完备性依赖来源、语义和执行证明，而计数与唯一性还需要独立的身份闭合；
- CanonRevision 若包含派生闭包就会制造另一权威副本，因而其完整性只能针对正典输入和固定语义环境。

**进入本文的研究结论**

- 当前候选只保留 Referent、KnowledgeResource、ResourceRevision、Statement、Attestation、CanonRevision 六种不可约核心记录；
- TargetRef 与 Predication 是值，Schema 是特殊资源，Branch 是工作流指针，Card 是工作空间；
- CanonRevision 只固定资源版本、作者准入 Attestation 和 Schema／规则／政策版本；状态、证明和闭包均可重建；
- 发布准入与客观断言力分离，Attestation force 和显式世界规范决定信息能否支持客观命题；
- 基础状态、直接区间、事件、校正和撤回共同进入唯一正典基础，当前状态统一求值且物化快照不可写；
- 仅保留 WorldEval 和 BeliefEval 两个真值求值器；Hypothesis、ReaderAccess 和 DocumentSearch 分别是覆盖层、投影和检索；
- 完备性改为来源范围闭合、语义覆盖充分、身份闭合、求值执行完整四项查询义务。

**对 R3 当前综合的取代**

- “四聚合 + Schema 注册表”改为“六种核心记录，Schema 复用资源版本”；
- “FragmentOccurrence／FragmentLineage 核心类型”改为“TargetRef 值 + 普通溯源”；
- “三轴 SemanticBinding”改为“Attestation force／grounds + 无环编辑所有权”；
- “direct／history／derived 互斥权威”改为“单一正典基础 + 版本化状态求值”；
- “五求值器”改为“两求值器 + 假设覆盖 + 读者投影 + 文档检索”；
- “三种完备性”改为“四项可组合、可失效的查询证明义务”。

**仍未裁定**

- 六记录内核是否真的闭合，以及如何防止 Attestation 退化为万能 tuple；
- 受限 Statement 语言、可判定等价子集和 Schema 兼容证明；
- 断言力识别、TargetRef 重锚定与语义继承、自然语言合并和人物信念更新；
- 四项查询义务的证书、失效与传播规则；
- 与当前 CharacterKnowledge、Reader Reveal、ADR-0006 和 Scene／MemoryEvent 账本的正式迁移决策。

**证据状态**

本轮已完整阅读并进行项目语义对照，但未重新核验研究稿引用的 Git 版本图、Web Annotation、PROV、
BIBFRAME、RDF 1.2、OWL 2、事件演算、多上下文系统、数据完备性与一阶逻辑不可判定性来源。这些仍只是待验证理论线索，
不能直接作为 ADR 证据。

### 2026-08-27：六记录第五轮证伪 → 相对闭合职责模型

**输入与验收方式**

- 第四轮六记录内核和第 10.4 节研究问题；
- 只读研究代理提交的第五轮证伪报告；
- 主代理针对 issuer 角色过载、kernelVersion 历史解释和证明制品防伪要求的定向补证；
- 主代理对 Web Annotation、PROV、OWL 2 Profiles、Datalog 等价不可判定、RDF 查询完备性和 SHACL
  验证报告原始来源的核验。

研究代理只提供候选结论且未修改仓库；以下内容经主代理反例复查后才进入当前综合。

**主要证伪**

- 六项职责在物理上可以合并，因而“六种记录类型已证明最小”不成立；
- 六记录不能脱离解释规则和授权根绝对闭合，只能相对于固定 `K` 与 `Auth` 闭合；
- 单一 issuer 混淆对象层 actor、态度 holder、内容归因、数据 provenance 和外部 committer；
- 作者采用不等于把 issuer 改成作者；采用人物台词或隐藏信念时必须保留 speaker／holder；
- 开放 force、项目可重定义的语义效果和可写 `proved` 状态都能形成绕权通道；
- 固定快照而不固定 kernelVersion 仍会让旧正典被新程序静默重解释；
- 固定有限 Datalog 类语言的求值终止，不意味着一般程序等价或 Schema 迁移可自动判定。

**主验收对研究代理初稿的进一步修订**

- 拒绝 `WorldAssertion(assertor=Referent)` 直接产生客观真值；虚构人物或机构的断言先是 Utterance／Report，
  制度性效果必须由固定世界规则产生；
- 拒绝由虚构人物的 attributedBy 直接写入他人的 BeliefEval；只有作者叙事声音可直接建立隐藏信念，
  人物归因只形成 Report；
- Defeat 目标保留在封闭 act 中，不再同时扩展成泛化 basis 角色；
- act 列表、受限 Statement 语法、时态小步语义和证书组合规则只保留为下一轮待证候选，不伪装成已完成形式证明。

**进入本文的研究结论**

- 当前模型改为六项不可缺少的语义职责，不承诺物理记录类型数最小；
- `Closed(K, Auth, C)` 成为闭合性的准确边界；CanonRevision 固定不可浮动的 kernelVersion；
- 外部准入、对象层行为、内容归因和 provenance 四者严格分离；
- Attestation 使用由 K 定义的封闭行为联合类型和封闭依赖角色，项目内容不能自定义真值效果；
- 旧 CanonRevision 永远按原 K 查询；不支持旧 K 时显式失败，不用新 K 猜测；
- S/F/I/X 是可重放证明义务；证明材料可作为资源保存，但 verdict 只能由可信检查器派生；
- 自动化边界分为安全执行、候选生成、作者确认和不可通用决定四层。

**仍未裁定**

- 最小 K 规范、act 代数的叙事覆盖、时态小步语义的确定性与终止证明；
- 各查询族的 S/F/I/X 证书、组合和增量失效；
- kernelVersion 窄兼容证明与旧解释器保存策略；
- 多作者 Auth 是否能完全留在语义层外；
- 与当前 CharacterKnowledge、Reader Reveal、ADR-0006 和 Scene／MemoryEvent 账本的正式迁移。

**证据状态**

本轮已核验第 5.2 节列出的原始规范和论文，只把它们用于支持定位／谱系不等于语义继承、受限语言边界、
一般 Datalog 等价不可判定、开放数据完备性需显式依据，以及验证 verdict 与被验证内容分离。它们不直接证明
HCSM 的具体 act、时态或证书设计；后者仍需下一轮形式反例和证明。

### 2026-08-27：元内核第六轮证伪 → 唯一 Assert 与非单调时态

**输入与验收方式**

- 第五轮相对闭合职责模型和第 10.5 节研究问题；
- 只读研究代理提交的最小 K deletion test、40 个行为案例、查询族证书、攻击、复用、kernel 和 Auth 矩阵；
- 主代理针对当前 Auth 追溯失效、act 继续删除、惯性 anti-dependency、瞬时 TimeScope、同边界 Start／Stop
  和绝对化 verdict 的反例；
- 研究代理的三项定向补证与主代理对数据库不动点、事件演算、RDF 1.2 引用语义等原始来源的复核。

研究代理保持只读；第 5～9 节只写入经主代理反例复查后接受的结论。

**主要证伪**

- WorldAssertion、BeliefAttribution、Utterance、Report、Interpretation、Proposal、Defeat 不是最小 act 集；
- 人物行为可成为包含惰性 StatementRef 的普通世界命题，Proposal／Interpretation 可降为工作流资源；
- Defeat 与 CanonRevision 的取消选择、区间拆分和规则修订重复，应从最小 K 删除；
- 查询旧 C 时读取当前 Auth 会让权限撤销追溯改变历史正典；
- 惯性依赖“区间内没有终止事件”，因此整体时态求值不是输入单调；
- `[t,t)` 不能表达瞬时事件，裸时间不区分 pre／at／post 会产生边界歧义；
- `(Carry \ Stop) ∪ Start` 隐含 start-wins；无显式子顺序时应返回 transition-underdetermined；
- `machine-proved` 会把单条相对支持误读成世界完备真值。

**进入本文的研究结论**

- Attestation 压缩为唯一 `Assert(world|belief(holder), polarity, Statement, TimeScope)`；
- StatementRef 可以引用命题但不得被项目规则通用解引用；
- 最小 K 当前只保留 TypedSyntax、MetaFence、AssertSemantics、CanonClosure、TemporalEvaluation、
  ProofVerdictSemantics 和 KernelVersioning 七项规范职责；
- Auth 只在提交时形成与 manifest 绑定的历史准入证据，实时访问权限不改变旧 C；
- kernelVersion 固定规范语义而非 checker build；实现修复重算 verdict，不重解释正典；
- TimeScope 区分 Timeless、Point(pre／at／post) 和 Interval；当前只证明有限全序片段；
- 证明依赖拆为 supportDeps、antiDeps、closureDeps，verdict 全部相对于 C/K/范围/制度/时间；
- 查询族分别承担不同的 S/F/I/X，正向见证不需要穷尽，缺失／唯一／计数／极值需要闭合证明。

**主验收保留的限制**

- “唯一 Assert 已证明最小”只在 40 个案例和当前有限语言中得到构造性支持，仍不是全领域数学唯一性证明；
- admission receipt 是语义边界，不是已选择的密码学或数据库实现；
- 同边界转移未定的保守语义、TimeScope 边界和证书充分性尚未经过形式机验证；
- 完整 Belnap 逻辑未采用，当前只有独立正负支持的四种观察状态；
- 有限偏序时间的 possible／necessary 分支语义尚未建立。

**下一研究目标**

有限偏序世界时间下的分支敏感惯性，以及 necessary／possible／throughout／first／last 的 anti-dependency
证书。该问题优先于继续扩展行为词汇或实现映射。

**证据状态**

本轮已核验第 5.2 节新增的数据库不动点、事件演算和 RDF 1.2 原始来源。文献直接支持有限正向闭包、惯性的
非单调性质以及“引用不等于断言”的可行先例；唯一 Assert、历史准入、三类依赖和偏序时间研究优先级仍是本项目的新设计判断。

### 2026-08-27：时态第七轮证伪 → 有限 TemporalTheory 与模态轨迹

**输入与验收方式**

- 第六轮 TimeScope、有限全序惯性和第 10.6 节研究问题；
- 只读研究代理提交的最小时间结构、30 个叙事压力案例、查询语义、模态证书和跨 C 失效矩阵；
- 主代理针对无关不可比事件、同刻可能、同日粗粒度、相关顺序选择、局部转移、时间旅行和复杂度外推的反例；
- 研究代理对时间窗、有限析取、`χ`、因果／时间分离和下一轮范围的定向补证；
- 主代理对 Lamport、Allen、Temporal Constraint Networks、order-incomplete data 和 Event Structures 原始来源的复核。

研究代理保持只读；主代理没有修改探索式研究账本，只将通过反例复查的结论写入第 5～9 节。

**主要证伪**

- 严格线性扩展漏掉可能同刻，并会在同刻事件之间伪造中间状态；
- 一个无关的不可比事件不应让已经由约束蕴含的 `A before C` 变成 temporal-underdetermined；
- 裸 Eq／Neq／Lt 合取无法无损表达相关的顺序选择，逐对投影会增加不存在的交叉时间世界；
- “同一天”是两个时刻落在同一锚点窗，不是两个时刻相等；
- 同边界 Start／Stop 不能靠隐藏排列决定，必须产生固定的局部非确定后继集合；
- 不同时间实现中的正负支持不是同轨迹 conflict，`Impossible(+p)` 也不等于 `Necessary(-p)`；
- 普通时间旅行只要求因果边与世界时间边分离，不自动制造时间环或本体多时间线；
- 有限模型可判定、STP 多项式和线性扩展计数困难都不能证明本组合模型存在短证书或给出其复杂度分类。

**进入本文的研究结论**

- TemporalTheory 是显式有限 DNF；Scenario 是 Eq／Neq／Lt／Within 与可选 STP 差分约束的有限合取；
- 定性时间实现允许相等，occurrence 身份与时刻相等分离；TemporalTheory 无模型时返回 invalid-temporal-frame；
- 完整轨迹为 `(ρ,χ,Trace)`，其中 `χ` 只选择局部非确定转移结果，不伪造事件微观排列；
- possible／necessary／impossible 对每个有符号支持分别量化；canon conflict、transition-underdetermined、
  temporal-underdetermined 与显式 branch 是正交诊断；
- first／last 返回 occurrence 集和 modal 变体；throughout／sometime 保持正确量词次序；精确 duration 需要 metric entailment；
- possible 使用合法轨迹见证；necessary／impossible 需要全部轨迹覆盖或可重放符号证明；underdetermined 至少要两个差异见证；
- 只有 S/F/I/X 已满足而闭合模型仍有多个结果时，才可给 verified 时间未定。

**主验收进一步收敛**

- 不新增独立 `TimeWindow` 核心类型，粗粒度时间窗复用既有半开 Interval；
- Neq 是必须具备的表达能力，但可由受限析取定义，不宣称必须是独立原语或记录；
- DNF Scenario 没有正典分支身份，不允许改变事件存在、非时间事实或规则集合；
- metric realization 可以无限，当前只主张受限约束符号求解，不能沿用有限总预序的枚举证明；
- “证书可以保存”不等于其 soundness、completeness、长度和依赖切片失效规则已经证明。

**下一研究目标**

为第 10.7 节固定的显式有限 DNF + 可选 STP + 局部非确定转移语言，证伪 possible／necessary／impossible／
underdetermined 的可重放 modal certificate calculus；在此完成前不把时态自动证明提升为 ADR。

**证据状态**

文献直接支持因果偏序与任意总序的领域边界、区间／差分约束、STP 的受限复杂度、order-incomplete 数据的
possible／certain 语义及 occurrence identity、以及偏序之外的 conflict 结构。总预序时间实现、有限 DNF
TemporalTheory、局部转移关系和三类依赖证书仍是本项目的新设计判断。

### 2026-08-27：证书第八轮证伪 → 分层 proof judgment 与包络诊断

**输入与验收方式**

- 第七轮 TemporalTheory、模态轨迹和第 10.7 节研究问题；
- 只读研究代理提交的 proof judgment、必要／可能／不可能载荷、两类未定诊断、复杂度与跨 C 复用报告；
- 主代理针对 temporal 双见证、空 `Ω`、第四类依赖、safe leaf、metric duration 和 canon closure 的反例；
- 研究代理按 deletion test 补交的 observation-invariance、包络差异和三档 verdict 修正附录；
- 主代理对 Proof-Carrying Code、LRAT、Alethe、Cook—Reckhow 与 Temporal Constraint Networks 原始来源的复核。

研究代理保持只读；主代理没有修改探索式研究账本，只更新本文当前综合、历史日志和下一轮提示词。

**主要证伪**

- 不同 `ρ` 上两个不同答案见证可能来自相同 `{true,false}` 结果包络，不能证明 temporal variance；
- 不一致 TemporalTheory 上的全称式会真空成立，necessary／impossible 必须另证 `Ω≠∅`；
- solver 自报 UNSAT、payload 自报 Trace／verdict、缓存命中和作者 closure 声明都不能自证通过；
- `interpretationDeps` 未通过 deletion test：完整不可变解释上下文已经保守覆盖其 soundness 职责；
- 有限语言不自动带来当前 calculus 的无条件 completeness，Calendar 和 normalization 仍缺 adequacy 引理；
- safe leaf 取代表 metric assignment 会漏掉 duration 和 boundary comparison 在同一区域内的变化；
- dependency labels 只定位潜在影响，不能替代模型包含关系和 evaluation preservation 证明；
- formal input complete 不等于自由正文、Profile、Event 和混合 Card 组成的异质正典 complete。

**进入本文的研究结论**

- 对象语义、calculus 推导、checker 实现、closure grade 和产品 verdict 分成五层；
- proof header 完整绑定 interpretation context；checker／normalizer build 进入 replay metadata，同 K 修复要重放；
- 保留 supportDeps、antiDeps、closureDeps 三类世界答案依赖，不新增第四类；inline proof 为最小形式，lemma DAG 可选；
- possible 用单轨迹见证；necessary／impossible 用非空见证加反例排除；
- transition variance 用固定 `ρ` 双 `χ`，temporal variance 用 `Out(ρ,q)` 成员／非成员包络差异证明；
- case-refutation 与 observation-invariance 形成条件式构造性 completeness 候选，但仍有两个待证 adequacy 引理；
- verdict 区分 verified-formal-relative、verified-canon-relative、assumption-backed、incomplete 和 invalid；
- 异质正典尚无 machine closure 契约，因此全小说 canon-relative 强结论当前不可机器签发。

**下一研究目标**

第 10.8 节只研究异质正典的可组合闭合契约：按 query family 定义语义所有权、来源穷尽、形式化覆盖和 identity
domain，证明 S/F/I 怎样组合、失效并从 formal-relative 升级到 canon-relative。下一轮不继续扩张时态 calculus。

**证据状态**

文献直接支持不可信生产者／可信 checker 的架构分离、SAT／SMT 可检查证明格式和证明长度不能被轻率假定；它们不
直接证明 HCSM 的 calculus。五层 judgment、三类依赖 deletion test、结果包络诊断、observation basis 和 closure
分档仍是本项目候选，需继续形式化或用反例淘汰。

### 2026-08-27：闭合第九轮证伪 → claim-sensitive ownership contract

**输入与验收方式**

- 第八轮 formal-relative／canon-relative 分界和第 10.8 节研究问题；
- 只读研究代理提交的 closure judgment、40 个异质正典攻击案例、所有权合成与跨 C 失效报告；
- 主代理针对 query-only Need、作者策略与内容完备偷换、第三种 ownership、跨域 identity 和循环 fingerprint 的反例；
- 研究代理按 deletion test 补交的三值 S/F/I、唯一 flatten、非循环 ClosureContext 与 ADR-0006 映射；
- 主代理对当前 ADR／World README、RDF/SPARQL 完备性、source descriptions、RDF 1.2、SHACL 和 PROV 原始来源的复核。

研究代理保持只读；主代理没有修改探索式研究账本，也没有修改当前实现契约或 ADR。

**主要证伪**

- 同一 query 的 support、true-only、absence 和 necessary 需要不同闭合义务，`Need(q)` 过宽或过窄；
- Card 全局 text-led／structure-led／dual 会同时漏掉正文独占、结构独占、双权威和纯说明 surface；
- 机器检查作者选了策略，不等于机器证明任意正文已经完整形式化；
- 一个 global closure 布尔值混淆来源找全、owner 语义覆盖和跨来源身份解析；
- mirror／derived／delegated 没有通过第三所有权状态的 deletion test；
- 两个局部 closed domain 的 identity 不能直接合并，跨域 alias／occurrence 仍可能未解；
- content selector、latest 和 policy import 会产生查询自指、历史漂移或策略循环；
- S/F 的局部 union 会漏跨域规则和跨段关系，条件组合尚不是无条件定理；
- excluded surface 仍可能拥有 Identity 或充当 hardGround，因此“excluded 更新总安全”错误。

**进入本文的研究结论**

- `Need(Σ,J)` 按具体 claim 切分 witness、invalidator、DomainMember、Identity、规则、effect 与时间来源；
- 来源通道最小候选为 PositiveSupport、NegativeSupport、TemporalConstraint、EventEffect、Identity、DomainMember；
- ownership 只保留 family/domain/channel/surface 上的 `owns | excluded`；未分类 surface 使 S open；
- S/F/I 分别取 machine／assumed／open；只有无 open 且至少一项为 assumed 才是 assumption-backed；
- policy 由 C 选择的 Schema／WorldSpec revision 承载，按有限 manifest metadata 唯一 flatten；K 定义语义和禁区；
- 构成性权威选择可机器检查，描述性“无遗漏”声明不能；opaque independent prose owner 默认不能 machine-close F；
- ClosureContext 绑定精确 policy/schema/owner revisions、compiled map、formalizer、identity/domain 与解释上下文；
- 当前 ADR-0006 映射为 World Bible page 对 WorldEval 事实 family excluded；允许 prose owner 必须显式修订 ADR 并只作用新 C。

**主验收保留的限制**

- 六个 channel 和唯一 flatten 是 deletion-test 后候选，不是数学唯一分解；
- S/F 条件组合和 excluded-only 跨 C 复用只保留为定义内条件引理，尚未形式机证明；
- 构成性政策可能形式有效但产品选择糟糕，checker 不证明作者理解、意图或内容质量；
- DocumentSearch 仍是非真值机制，不能因页面对 documentary 内容有权威而穿透到 WorldEval。

**下一研究目标**

第 10.9 节只研究 opaque 正文能否通过 controlled language、构成性切分或 evidence-only 三条路径收束语义。
不得预设作者批准 mapping 可以 machine-close F；若正文保留映射外独立含义，必须保持 assumption-backed。

**证据状态**

文献直接支持 query-specific completeness、声明式异质来源描述、固定输入验证以及形式图与自然语言社会性对应的边界；
它们不证明本项目的 ownership vocabulary、构成性作者行为或组合规则。后者仍是待下一轮继续证伪的新设计判断。

### 2026-08-27：正文第十轮证伪 → A/B 构成性权威分叉

**输入与验收方式**

- 第九轮 opaque independent prose owner 的 F closure 缺口和第 10.9 节研究问题；
- 只读研究代理提交的正文不可闭合反例、controlled／constructional／evidence-only 路径、40 个文本攻击案例；
- 主代理针对“构成性 mapping 必然 text excluded”的删除反例：正文直接授权、派生 Assert 可重建且不可独立修改；
- 研究代理补交 A/B 对象层等价边界、撤回／删除矩阵、mapping 载体、partial union、hardGround 与 K/Schema 分层；
- 主代理对当前 ADR-0006、World README、Attempto Controlled English、Web Annotation、RFC 5147、RDF Semantics、
  SHACL 与 PROV 的适用边界复核。

研究代理保持只读；主代理只更新本文，没有修改探索式研究账本、当前实现契约或 ADR。

**主要证伪**

- 相同正文、有限 mapping 和签名可同时兼容 `A` 与 `A∪{b}`，所以确认已见映射不证明没有遗漏语义；
- 构成性 mapping 不必把 text 降为 excluded：若 total `φ` 规范性定义全部权威语义，text 可以继续是直接 owner；
- A 型 text owner 与 B 型 Assert owner 只在不观察来源身份的普通 WorldEval 上条件等价，删除、撤回和独立修订可区分；
- 字符／句子片段全部覆盖仍可能漏掉标题、引语框架、传闻或跨段作用，不能据此证明 totality；
- `Corr`、`FormalCover`、`AuthoritySubstitution`、`MappingEntry` 和 `coverageRoot` 均未通过独立核心记录 deletion test；
- AI Interpretation 不能靠被引用升格为元权威；采用必须产生新的 sealed correspondence resource；
- general Boolean hardGround language 没有必要：合取 flat set 加多个同语义 Assert 已覆盖替代依据。

**进入本文的研究结论**

- machine-close F 的正文路径是 controlled text、A 型 constitutive text owner、B 型 authority substitution 或正文
  对 WorldEval excluded 的 evidence-only；opaque independent owner 仍只能 assumed/open；
- A 中 `Sem(C,n,t)=φ(C,n,t)=A` 且派生 Assert 不可独立改变权威；B 中 text excluded、exact Assert owns；
- C 对每个 `(coverageRoot,n)` 选择唯一 compiled total coverage manifest，可精确 flatten 满足同上下文条件的 additive
  partial revisions；partial 自身和字符覆盖都不声称 exhaustive；
- 完整 manifest 仅在独立生命周期确有需要时复用 KnowledgeResource／ResourceRevision，其他 judgment/value 内联；
- K 固定 total-formalizer 接口和核心语义，具体 grammar、lexicon、family mapping 由 exact SchemaRevision 固定；
- 当前 ADR-0006 使用 B／evidence-only 边界；未来启用 A 必须经新 ADR／policy，只作用新的 CanonRevision。

**主验收保留的限制**

- A/B 哪些 family 可用、系统是否必须保存 direct authority、A 中派生 Assert 能否再被独立采用，仍是产品裁决；
- total manifest 的 flatten 条件、hardGround 查询语义和 A/B 外延等价是候选规范，尚未完成形式机证明；
- correspondence manifest 内联或独立资源取决于真实生命周期，不能预建一套通用 binding 子系统；
- 当前 B／evidence-only 窄路径已可进入实施 Spec，但完整统一尚缺原子 authority transition 与多父合并。

**下一研究目标**

第 10.10 节只研究 A/B 构成性权威切换事务：定义原子准入、撤回／回滚、多父合并、解释边和跨 C 复用，使任何
CanonRevision 都不会出现意外双 owner 或无 owner，并继续对新增记录逐项做 deletion test。

**证据状态**

ACE 支持“受限自然语言可有非歧义形式语义”的存在性先例；Web Annotation 与 RFC 5147 支持版本内片段寻址而不支持
语义继承；RDF／SHACL／PROV 不提供自然语言覆盖或正典权威证明。A/B ownership、total manifest 与 hardGround
组合仍是本项目候选，不能冒充这些文献的既有结论。

### 2026-08-27：权威第十一轮证伪 → CanonRevision 原子切换

**输入与验收方式**

- 第十轮 A/B 直接权威分叉和第 10.10 节研究问题；
- 只读研究代理提交的 O/A/B 状态机、原子准入条件、36 个攻击案例、撤回／合并矩阵与 proof transport 条件；
- 主代理对“每个 key 恰有一个 owner”“必须始终至少一个 owner”和 O/A/B 状态单位的反例复查；
- 当前 World Bible seal／publish／CAS、AI 建议采用、CoreEntity／relation／Event、EvidenceLink、MemoryEvent 与模块
  facade 边界的再次核对。

研究代理保持只读；主代理只更新本文，没有修改探索式研究账本、当前实现契约或代码。

**主要证伪**

- 独立来源可以合法多 owner，total manifest 也可定义事实扩展精确为空，故“每 key 恰一 owner”与“零 owner 必错”过强；
- O→B 分步提交会在中间形成未覆盖或同一表示链重复 owner，必须由新 CanonRevision 整体生效；
- A→B 后若规范化 Assert 集或有效性条件不同，就同时发生内容修订，不能借用 A/B 外延等价；
- A/B 切换改变 compiled ownership、S/F evidence、support identity 与 source explanation，旧 closure certificate 失效；
- hardGround 循环可让必要依据互相支撑却没有终端 ground，当前受限候选直接拒绝；
- 多父 A/B 即使事实相同也不能自动 union，因为 direct owner 未决；父优先级、latest 和相似度都不能代替作者选择；
- AuthorityTransaction、AuthorityMode、四类 explanation edge 和 RollbackRecord 均未通过核心记录 deletion test。

**进入本文的研究结论**

- O/A/B 是同一 representation chain 上的 checker judgment；独立多 owner 另行存在并按普通 conflict 语义求值；
- `AtomicTransition` 复用 sealed ResourceRevision、完整新 CanonRevision、单次 Admit 和不可变 receipt，失败不产生半状态；
- O→A、O→B、A↔B 和退回 O 都有明确前后不变量；pure switch 要求 signed support 与有效性条件双射；
- closed-empty 由 total manifest 表达；uncovered 才使 S open，不创建虚构空事实 Assert；
- DirectAuthority、UltimateGround、DocumentarySource、ExecutableSupport 全部从既有语义派生；
- rollback 分为 branch navigation 与新 revert C；旧 C 永不原地改写；
- A/B 切换只可能运输对象层 proof skeleton，且必须在 C2 的新 header／context 下 replay，acceptance 与 closure 不复用。

**主验收保留的限制**

- hardGround 默认有限无环是为避免无基础自支撑而取的受限候选；若未来出现真实递归依据需求再单独证明，当前不预建；
- proof transport 的 support 双射与 anti/closure space preservation 尚未形式机证明，只能作为充分条件候选；
- family 选择 A/B、是否对作者稳定暴露 direct authority、以及多父合并的作者裁决仍是产品／ADR 选择；
- complete platform 仍缺 SchemaRevision family-local compatibility，不能因“新字段不升级 K”推断旧查询可复用。

**下一研究目标**

第 10.11 节只研究 `SchemaCompat(S1,S2,Need(Σ,J))`：找出可检查的 family-local 保持条件和反例，完成后把无法由
形式研究代替的产品选择直接进入实施就绪裁决，不再用新抽象拖延落地。

**证据状态**

本轮主要是基于已定义 HCSM 语义的构造与反例，不引入新的外部理论移植。原子边界复用当前项目已有的不可变 revision、
CAS 和作者采用原则，但 CanonRevision、Admit、O/A/B 与 proof transport 仍是目标模型候选，不是当前代码事实。

### 2026-08-27：Schema 第十二轮证伪 → scoped family-local compatibility

**输入与验收方式**

- 第十一轮 authority transition 的 Schema 失效缺口和第 10.11 节研究问题；
- 只读研究代理提交的双 scope compatibility、双向 dependency slice、A/B/S/F/I 保持矩阵与 46 个攻击案例；
- 主代理对类型收窄、S2 新 dependency 入边、unknown surface 与证书复用的反例复查；
- 第六至十一轮已固定的 claim-sensitive Need、ownership、closure、proof replay 和旧 C 不重解释边界。

研究代理保持只读；主代理只更新本文，没有修改探索式研究账本、当前 ADR 或代码。

**主要证伪**

- `SchemaCompat(S1,S2,Need)` 缺量化范围：同一收窄可对当前 CanonPair 兼容、对未来输入不兼容；
- 只扫描 S1 旧依赖会漏掉 S2 新增的 owner、rule、effect、identity/domain、default 与 normalization 入边；
- 类型拓宽、新 enum member 和 default 对 positive witness 可能无影响，却可破坏 absence、count、unique 与 universal；
- 字段同名、类型相同、版本号或 minor／patch 标签都不能证明语义相同；
- A 的 `φ` 输出相同也不自动保持 S/F/I，新 owner surface、identity 或反面规则仍可改变 closure；
- 新 SchemaRevision 下旧 proof acceptance 与 closure certificate 均不可原样接受；
- SchemaCompatibility、Translation、MigrationMap 和 CompatibilityStatus 均未通过新核心记录 deletion test。

**进入本文的研究结论**

- compatibility 分为 `CanonSchemaCompat` 与 `UniversalSchemaCompat`，都绑定 `Need(Σ,J)` 和可检查 evidence；
- dependency slice 在 S1、S2 分别计算并取并集，还必须检查指向 required slice 的新入边；
- exact relevant slice unchanged 与 finite declarative translation 是 machine-compatible 的候选充分路径；
- translation 对 symbol／carrier／selector／identity/domain／rule/effect／normalization total，且按 claim 要求单射或双射；
- compatibility grade 为 exact-unchanged、verified-translation-relative、assumption-backed、open、invalid；
- proof skeleton 可经 translation 在 C2 replay；acceptance、closure 与 canon-relative verdict 必须在 C2 重验／新签；
- translation evidence 单次内联 proof，需复用时进入既有 proof 或 Schema/WorldSpec ResourceRevision，不取得事实 authority。

**主验收保留的限制**

- 声明式 translation grammar、slice element 目录、canonical digest、rule/effect 允许的 proof 片段仍需在实施 Spec 固定；
- 一般 Datalog／程序等价、自然语言字段同义和作者意图不可通用决定；sound 片段必须允许“不知道”；
- 哪些 family 承诺 universal compatibility、字段／identity 演化是否符合设定以及多父冲突选择属于产品／作者裁决；
- 空白类型从无模板正文到 typed owner 的首次 authority 变化仍未闭合，是实施前最后一个直接产品语义缺口。

**下一研究目标**

第 10.12 节只研究空白自定义类型渐进 Schema 化：区分模板、Schema 采用和历史事实提升，允许旧、新 Schema 并存，
并继续删除 DynamicEntity、MigrationMap 和自动事实升级。

**证据状态**

一般 Datalog 等价不可判定已有原始文献支持；双 scope judgment、双 Schema slice、translation obligations 与分级仍是
HCSM 的受限候选。它们提供 sound 的充分路径而不是通用必要充分算法。

### 2026-08-27：空白类型第十三轮证伪 → generic documentary BaseSchema

**输入与验收方式**

- 第十二轮 Schema compatibility 与最初“新增、修改、删除空白类型”的产品目标；
- 只读研究代理提交的 blank authority matrix、D→V→A/B 状态机、46 个历史卡攻击案例与 lifecycle deletion tests；
- 主代理对 card／resource／Referent、title／Name、default、bulk promotion 和 unknown surface 产品边界的复查；
- 当前 World Bible Category／Template／Draft／Revision、CoreEntity 自由类型与 Generic Profile 的实现证据。

研究代理保持只读；主代理只更新本文，没有修改探索式研究账本、当前 ADR 或代码。

**主要证伪**

- 完全无 Schema 的 blank card 无法分类 generic field 与 unknown extension，不能安全声明 closure；
- title/body/custom value 作为正式资料，不等于它们自动拥有 Name、属性、关系或事件事实；
- CreateTemplate、AdoptSchema 和 PromoteHistoricalContent 合并会让旧值静默取得新世界语义；
- parser 成功、AI confidence、字段同名和模板 seal 都不能替代作者授予 authority；
- missing／null／empty 与 default 不可混同，default 自动补旧卡会改写历史真值；
- SchemaCompat 只保持既有 authority，不能把 excluded documentary 首次提升成 owner；
- DynamicType、MigrationMap、TemplateLifecycle、TemplateBinding、FieldValueRevision 等均未通过 deletion test。

**进入本文的研究结论**

- BaseSchema 识别 title、body、custom label/rawValue，并使其 documentary canonical、对已知 WorldEval family excluded；
- Card 是工作空间；generic blank 默认只创建 KnowledgeResource，entity-bearing policy 才显式创建／链接 Referent；
- 三个作者行为分离，只有 PromoteHistoricalContent 通过新 C 选择 A/B 并改变历史事实；
- 旧卡默认绑定旧 exact Schema，AdoptSchema 默认只影响未来 revision；旧新 Schema 可并存；
- default 只预填新 revision，历史 absent-value semantics 是 promotion；旧自由值禁止 silent coercion；
- promotion 默认 B，A 仅限 total controlled surface；批次 invalid 默认整批拒绝，可重新确认 exact subset；
- unknown extension 正典准入 fail closed；direct authority 作为稳定解释语义，只在高级诊断显示。

**主验收保留的限制**

- generic blank 是否提升为 Referent、历史字段对应哪个 predicate／identity／time，以及多父模板冲突仍由作者决定；
- “任意旧自由文本可无损自动变成机器完备知识”仍不可实现，也不作为开工承诺；
- 上述产品基线是实施审计默认，不是已接受 ADR；最终代码前需在产品 ADR／Spec 明确；
- 语义内核的删除测试已没有新 blocker，下一轮只允许发现实际仓库落点缺口，不再添加抽象名词。

**下一研究目标**

第 10.13 节执行当前项目实现就绪审计，输出最小物理落点、ADR 改动、模块边界、阶段出口和测试矩阵；若无 blocker，
本文进入 implementation-ready，后续另建实施 Spec。

**证据状态**

本轮是 HCSM 内部定义与反例裁决，没有新的外部理论移植。BaseSchema、三动作与 B-default 是项目候选；当前代码已有
generic category/template/draft/revision 与 CoreEntity 自由类型基础，但尚未实现 CanonRevision／Assert 语义。

### 2026-08-27：实现第十四轮审计 → implementation-ready 交接

**输入与验收方式**

- 第十三轮完成后的 HCSM 语义内核和第 10.13 节仓库审计问题；
- 只读研究代理对 AGENTS、CONTEXT、整体／数据库设计、ADR-0006／0015／0016、world README、world／evidence／
  story ORM／contracts／facade，以及 router／WorldView／WorldBibleTab 的逐项核对；
- 主代理对 Card／KR／RR／Statement 通用表的 deletion test、Adoption Package 原子 seam 和 phase dependency 复查；
- 当前用户画像、novel_id／owner、安全、AI authority、专用历史、文档门禁和 demo／真实数据边界。

研究代理保持只读；主代理只更新本文，没有修改探索式研究账本、当前 ADR、schema、API 或生产代码。

**主要证伪**

- 六项逻辑职责不等于六张通用表；用万能 ResourceRevision 替换 TextArchive、MemoryEvent 和专用 revision 会丢失语义；
- Card 作为页面／实体 tagged read model 已足够，不需要第七个持久身份根；
- 首版封闭 Statement 可作为 Assert 内 canonical-digest value，不需要先建独立表；
- `status=canonical` 与 published head 不能固定旧正典，也不能原子选择跨资源事实；
- EntityRelation、Profile 和 CharacterKnowledge 无法统一表达 immutable signed/regime/time/ground Assert；
- WorldBiblePageTemplate 的布局生命周期不能兼任事实 Schema；EntityProfileTemplate 需要专用 revision；
- 长期 legacy／Assert 双写会形成双真相源；必须按 family 一次切换 evaluator owner；
- 初始审计阶段顺序让 Name Assert 早于 Assert／Canon 基座，主验收已改为先交付语义基座。

**进入实现交接的裁决**

- 必须新增且仅新增 `world_assertions`、`world_canon_revisions`、`world_canon_heads`，以及 typed custom Schema 启用前的
  `entity_profile_template_revisions`；
- `CoreEntity` 保留 Referent；WorldBiblePage／实体／Profile 等用封闭 tagged ref 组成 KR 逻辑并集；各域专用 history 保留；
- Card subject 首版使用 PageRevision `page_meta_json.card_subject_ref_v1` 的严格值，不从多值导航引用推断；
- Adoption Package 是 B promotion + new C 的原子 seam，不新增 AuthorityTransaction／队列；
- world 拥有 Assert／Canon evaluator，evidence 和 story 只通过稳定 contract 提供文档与 Scene-time 输入；
- Ask World 保持 evidence／RAG 回答；formal WorldEval 使用新接口，二者不互作兼容别名；
- 0006／0016 修订，0015 保留并交叉引用；新增一个窄的 world authority ADR；
- 分阶段交付与测试矩阵固定于第 12 节，Phase 1 UI 可先开工，语义写入在新 ADR／Spec 后开工。

**主验收保留的限制**

- 实施就绪不等于一次性全链路重写获准；每个 phase 仍需完成稳定 wire、失败语义、测试和文档门禁；
- 真实非空项目的首个 C 必须显式作者初始化；不能因开发库可重建而静默改写真实数据权威；
- v1 只承诺 Name、typed scalar、signed binary relation 与简单时间；A、belief、惯性、branch、FRI 后置；
- `world_assertions` 的 statement payload 必须是 Pydantic discriminated union，不得退化成任意 predicate tuple；
- family cutover 后不得 fallback legacy current value；旧字段只可作 authoring head／read projection 或后续退场。

**最终状态**

- 语义研究：完成，停止扩张；
- 工程研究文档：足以作为新 ADR 与实施 Spec 输入；
- 代码开工：Phase 1 可直接规划，Phase 2 以后先合并 ADR／Spec；
- 后续维护：实现发现反例时回到本文追加勘误，不再按惯性生成新研究轮。

**证据状态**

本轮裁决基于当前仓库事实，不把目标 `world_assertions`／CanonRevision 冒充现有实现。实际文件证据包括 CoreEntity／
Event／EntityRelation／Profile、WorldBible Page／Revision、CharacterKnowledge、MemoryEvent、EvidenceLink、Adoption
Package、world router 与 Vue 入口；权威细节仍以代码、ADR 和未来实施 Spec 为准。

### 2026-08-27：实施交接对抗审查 → 撤回 implementation-ready

**输入与验收方式**

- 将第十四轮工程文档作为 ADR、数据库/API Spec 和测试验收合同进行最小反例审查；
- 主代理逐项复核当前 `novel_id` 边界、Page／Entity revision、Relation／Event 可变载体、TargetRef、MemoryEvent 和
  Candidate／Adoption 语义；
- 只接受会让两种实现都符合原文、却产生不同历史答案、授权结果或 UI/WorldEval 状态的反例。

**成立的反例**

1. `project`／`novel_id` 双作用域会留下跨小说 head 和引用歧义；
2. “必要 documentary refs”不能重放旧 C 的完整文档正典；
3. 可变授权摘要不能承担历史 admission receipt；
4. 删除通用 KR/RR 后仍用“等”列举资源，无法保证每个引用落到 immutable revision；
5. 裸 digest 不能解析一个仅被说出、从未被 world／belief Assert 的 Statement；
6. `validate(K)→Assert` 与“作者采用才创建 Assert”形成两条候选状态机；
7. 旧小说无 head、head 后退式回滚与 v1 后置 branch 互相冲突；
8. cutover 只关闭 legacy read fallback，不能阻止 legacy save 成功而 Canon CAS 失败的双轨写入；
9. exact finite `AdoptSchema` scope 不能同时动态覆盖未知 future revision；
10. 未被 C 精确固定的 MemoryEvent replay 会使旧 C 时态答案漂移；
11. 项目映射漏写执行完整性 `X`，会把预算截断伪装成完整 unknown／false。

**修订裁决**

- 不新增理论类型，也不恢复通用 Card、KR/RR、Statement、AuthorityTransaction 或 receipt 表；
- `novel_id` 成为唯一正典作用域；CanonRevision 语义上固定完整输入映射，page publish 必须推进 documentary selection；
- receipt 使用唯一不可变载体；Phase 0 穷举封闭资源解析目录，不可变 carrier 缺失的资产不能直接进入 C；
- v1 StatementValue 自包含；StatementRef 未实现可解析表示前，相关 kind fail closed；
- validation 只产生 sealed candidate，作者采用事务才创建 Assert+C+receipt+head CAS；
- 新旧小说都建立 empty C0；v1 单 head、单父、只前进，回滚追加 revert C；
- 每个 family 同时切换 canonical read 与 write ownership；MemoryEvent 在 event/time cutover 前 formal-excluded；
- 当前状态降为 ADR-ready。Phase 1 可继续，Phase 2+ 必须先完成第 12 节 P0 契约和可执行测试。

**取代关系**

本节取代第十四轮日志中的 “implementation-ready” 最终状态，不改写其历史内容。第十四轮的 deletion test 和最小
物理新增结论仍保留，但全部受本轮闭合条件约束。

### 2026-08-27：八项 P0 集中收敛 → 语义闭合、四项项目事实待定

**输入与验收方式**

- 外部审查对八项 P0 逐项给出反例、候选语义、规范条款、状态机与压力矩阵；
- 主代理复查其三项新增组合反例，并对照当前 `TargetRef`、Page／Entity／Template revisions、`CreationSuggestion`、
  account principal、Project owner 与 validation policy 实现验证物理前提；
- 继续执行 deletion test：能用不可变值随 CanonRevision 内联的职责，不新增通用表。

**成立并进入当前综合**

- StatementRef 必须引用完整 claim：内层 regime、polarity、StatementValue 与 TimeScope 缺一不可；
- receipt 分离 authorizing principal 与 executing principal，并以 decision ID／digest 绑定 exact author choice；
- v1 family authority 只允许 `formal-disabled→canon-owned`，exact revert 不得跨 cutover 恢复 legacy authority；
- active resource map 与 pinned dependency refs 分离；旧 revision 可以是 ground/cite，但不因此成为活动 DocCanon；
- 每个 Assert 第一次持久化时必须由同一成功 Admit 创建的 C 选择，不保留候选 Assert 池。

**主代理修正**

外部结果要求 AI candidate 先成为 sealed Proposal／Interpretation ResourceRevision，但当前 `CreationSuggestion.payload_json`
可编辑，不能冒充 immutable carrier。v1 不为此新增通用 candidate revision 表：作者采用时把 exact candidate、subset、
source、目标变化与 expected head 封成内联 `AdmissionInputValue`，在同一 Admit 中 authoritative revalidate；预览 validation
仍是非权威。未来若候选确需独立历史或访问控制，再为该 family 做 revision carrier deletion test。

**当前代码核验出的四项剩余事实**

1. 当前 `shared.TargetRef` 只有 `target_type/target_id/target_path`，没有 resource/revision kind version、revision digest 或
   selector version，不能直接充当 Canon exact ref；
2. `WorldBiblePageTemplateRevision` 已有 content hash，但 `WorldBiblePageRevision`／`EntityRevision` 没有持久 digest；
   `EntityRevision` 只快照 CoreEntity 字段，不覆盖类型化／Generic Profile；`EntityProfileTemplateRevision` 尚不存在；
3. `AccountPrincipal.account_id` 可承担作者账户身份，但当前没有稳定的 worker execution subject，也没有专用于 Canon
   admission 的 authorization-policy ID／version／digest 载体；world validation policy 不能自动冒充授权政策；
4. `world_assertions` 尚未实现，因此 Name／typed scalar／binary relation 的封闭 variants、typed normalization、
   StatementRef claim wire 与 canonical-byte fixtures 均仍待 Spec。

**最终状态**

- 八项 P0：语义闭合；
- ADR：ready；
- 数据库 Spec、API Spec、executable tests：仍被上述四项项目事实阻塞；
- Phase 1：可继续；Phase 2+：四项完成前不开工。

### 2026-08-27：Phase 0 工程事实收敛 → Proposed ADR、Spec 与 fixtures

**仓库证据与 deletion test**

- 资源目录只开放 `world_bible_page/1` 与 `entity_profile_template/1`；页面布局模板、CoreEntity、
  EntityRevision、mutable Profile／Relation／Event／Suggestion 和 cache 均不冒充 ResourceRevision；
- PageRevision 补完整 revision digest；现有 `source_content_hash` 覆盖不全，不能复用；
  EntityProfileTemplate 使用专用 revision carrier，不增加通用资源版本表；
- authorizer 复用 `AccountPrincipal.account_id`；executor 复用 account request 或现有 task
  ID/type/attempt/lease，不建立 worker identity；authorization policy 使用代码内封闭版本 registry，不建表；
- Statement union 收敛为 Name、有限 typed scalar 与 binary relation；float／任意 JSON／递归 claim 后置；
  当前无 Calendar carrier，因此 point／interval wire 可规范化但 admission 失败关闭；
- selector 只保留 whole、页面 field／section／reserved metadata、ProfileTemplate field，不开放任意 JSON path。

**产物与状态**

- 新增 Proposed ADR-0017，只记录长期权威边界，不复制完整研究；
- 新增 Phase 0 实施 Spec，固定四张新表、两个 revision 字段、唯一 Admit、API/error 语义与实施顺序；
- 新增 stdlib canonical JSON/SHA-256 fixtures，覆盖 policy、exact TargetRef、三种 Statement、完整
  StatementClaimRef、空 C0 manifest/input/receipt；
- 四项项目事实不再存在两种兼容解释，但 ADR 尚未 Accepted，当前实现、数据库、API 与事实来源均未变化。

## 12. Phase 0 Proposed 实现交接

本节保留 ADR 接受前的实施基线与历史门禁；2026-08-27 的实施结果与剩余
门禁见第 15 节。

本节保留研究层面的完整交接。可执行工程合同以
[`Phase 0 实施 Spec`](../superpowers/specs/2026-08-27-world-authority-phase0-spec.md) 和
[`canonical fixtures`](world-authority-canonical-fixtures-v1.json) 为准；两者与 ADR-0017 一样仍是 Proposed。

### 12.1 当前资产到逻辑职责

| 目标职责 | 当前物理资产 | 最终裁决 |
|---|---|---|
| Referent | `CoreEntity` | 保留为 entity-bearing 世界身份根；generic blank 默认不创建 |
| KnowledgeResource | 当前各域稳定 head | 继续使用 `{resource_kind,resource_id}` 逻辑并集，不建总表；只有 Phase 0 封闭目录列出的 kind 可进入 C |
| ResourceRevision | 当前各域专用不可变历史 | 保留专用 carrier，不建万能表；缺少 exact immutable carrier 的 mutable 行不得被 C／TargetRef 直接选择 |
| Statement | 当前隐含在字段、关系和事件 payload | v1 为 Assert 内自包含 Pydantic discriminated value；digest 只校验／去重，不建表 |
| Assert | 当前资产只能近似表达局部正向事实 | 新建 immutable `world_assertions` |
| CanonRevision | 当前没有；canonical／published／adopted 分散 | 新建 immutable `world_canon_revisions` 和 per-`novel_id` CAS `world_canon_heads` |

`CoreEntity.name/summary/public_info/hidden_truth`、Profile、EntityRelation 和 Event 在 family cutover 前仍是当前实现；切换后
只有 C 选择的 Assert 决定相应 family 的 formal WorldEval。mutable legacy 行只能明确承担 draft／authoring head；canonical
Card 区域读取 C 的只读投影，不能读取未提交草稿。WorldBiblePage 是 generic resource-only Card 的默认 KR；Draft、
PageRevision、Projection 分别承担工作稿、不可变文档版本与可重建缓存。CharacterKnowledge 暂保留对象级 belief 摘要；
MemoryEvent 在 event/time cutover 前只属 Story 连续性；EvidenceLink 只表达 provenance／导航。

Phase 0 Spec 已给出**封闭资源解析目录**：首批只允许 `world_bible_page/1` 和
`entity_profile_template/1`，并逐项固定 resource identity、exact revision、digest、允许角色、selector、同 `novel_id`
校验、归档／删除与历史读取语义。`WorldBiblePageTemplateRevision` 虽有 digest 但只承担布局模板；`EntityRevision` 缺
digest 且只覆盖 CoreEntity，均明确排除。实现仍需为 PageRevision 补完整 digest，并新增
EntityProfileTemplateRevision；不得出现“等”、runtime discovery 或 latest resolver。

当前 `shared.TargetRef` 只有 mutable target 的 type／ID／path，不含 resource/revision kind version、revision digest 或
selector version，不能直接复用为 Canon exact ref。`CoreEntity` 本身只承担 Referent；EntityRelation、Event、Profile、
CreationSuggestion、current Story head、checkpoint 和 cache 在没有合格 immutable carrier 前不能作为 Canon resource
revision。其世界语义进入 Assert；mutable candidate 在采用时封入内联 AdmissionInputValue，采用前保持非权威。

Phase 0 的 exact ref 逻辑形状固定为：`ResourceRef(novel_id, kind, kind_version, resource_id)`；
`ExactResourceRevisionRef(ResourceRef, revision_id, revision_digest)`；
`TargetRef(ExactResourceRevisionRef, selector_kind, selector_version, selector_payload)`；
`AssertRef(novel_id, assert_id, assert_digest)`；`GroundRef = AssertRef | TargetRef`。具体 Pydantic variants、selector payload
和 canonical bytes 已由 Phase 0 Spec／fixtures 列举；不能把当前 `shared.TargetRef` 直接改名复用。

### 12.2 最小物理新增、保留与后置

必须新增：

1. `world_assertions`：`novel_id`、immutable ID、`regime`、`polarity`、封闭 `statement_kind/version/payload`、
   exact Schema ref、`time_scope`、exact source revision／selector、flat conjunctive hard grounds、audit-only
   `provenance_actor_ref` 与 content hash。未知 kind／version fail closed；v1 只开放 Spec 列举 family，禁止任意 predicate／程序；
   含 StatementRef 的 kind 必须内联完整 regime／polarity／StatementValue／TimeScope claim，否则拒绝。
2. `world_canon_revisions`：`novel_id`、parent `0..1`、kernel spec version、完整 active resource revision map、selected
   Assert 全集、exact Schema／rule／policy／Calendar refs、独立 pinned ground／correspondence／cite／source refs、manifest digest，
   以及 Spec 唯一确定载体中的 immutable admission receipt。物理 delta 合法，但必须能沿不可变单父链唯一还原完整 manifest。
3. `world_canon_heads`：每个 `novel_id` 恰有一个 current C 的 mutable CAS 指针；不能塞入 Project settings，也不能修改 C 的
   `is_current`。head 只前进到当前 C 的新直接子。
4. `entity_profile_template_revisions`：以现有 `EntityProfileTemplate` 为稳定 head，在 typed custom Schema 启用前补齐；页面
   template revision 仍只负责布局。

必须保留现有 CoreEntity／强类型 Profile／GenericEntityProfile、World Bible 全生命周期、Relation／Event／
CharacterKnowledge、TextArchive／EntityRevision、Story revisions／MemoryEvent、Evidence、Suggestion／Adoption Package、
validation run、PostgreSQL task transport，以及所有 novel_id／owner／CAS／source hash／恢复门禁。

明确删除或后置：通用 cards／knowledge_resources／resource_revisions／Statement 表，新顶级 knowledge/canon 模块，
SemanticBinding、AuthorityTransaction、MigrationMap、DynamicType、四类 explanation edge 表，长期双写、通用事件总线、
proof／FRI 持久化，以及 A、通用 belief、惯性、branch、多父合并和 machine-closure 主界面。

Page 与 Referent 的 subject 不从 `linked_asset_refs_json` 推断。首版使用 PageRevision `page_meta_json` 中严格校验的
`card_subject_ref_v1`：缺失表示 resource-only；存在时只能指向同 novel CoreEntity。它是 revision value，不是新绑定实体。

receipt 不单独建表，唯一载体是 CanonRevision 内联不可变值。它至少固定 `novel_id`、C ID、完整 manifest digest、
decision ID／digest、authorizing principal、executing principal、action、affected families/resources、exact
authorization-policy ID／version／digest、allow decision、提交时刻和 `expected_previous_head`。Phase 0 Spec 固定 Account ID
为普通 authorizer，account request 或 task ID/type/attempt/lease 为 executor，并以代码内封闭 descriptor registry 承载
authorization policy；不新增 worker identity 或 policy 表。

`AdmissionInputValue` 同样是 CanonRevision/receipt 内联值，不是新表。它固定 exact candidate snapshot、作者选择的 exact
subset、source refs、目标资源／family 变化与 expected head；其 digest 用于幂等和防篡改。现有 `CreationSuggestion` 只作
可变预览载体，Admit 必须基于内联值重新验证，不能把 suggestion row 的当前 payload 当历史输入。

### 12.3 模块、ADR 与稳定边界

- world 内部拥有 Assert、CanonRevision、head CAS、Schema admission 与 deterministic evaluator；不新增顶级模块。
- evidence 保留 documentary retrieval、TargetRef、visibility、budget、confirmation 与 ContextSnapshot；不得读取 world ORM，
  只经窄 facade 取得 canonical fact context。
- story 保留 Scene、MemoryEvent、checkpoint／snapshot 与重放；event/time cutover 前 formal WorldEval 不消费它们，cutover
  后也只消费 C 精确选择的 immutable Story／MemoryEvent revision 或由其 promotion 得到的 Assert。
- writing／imports／map 通过现有 contracts／facade 或新窄 port 消费，不跨模块导入 models／repositories／services。
- ADR-0006 保留并修订 Page=Card/KR、B-default 和 page publish≠fact promotion；ADR-0015 完整保留并交叉引用；
  ADR-0016 修订 import/validation receipt≠truth、include subset→Assert+C、invalid 全批回滚。
- 新增一份窄 ADR“世界事实权威、不可变断言与 CanonRevision”，固定 `novel_id` 作用域、完整 manifest、receipt 合同、
  authorizer/executor、完整 claim 引用、page publish、C0／单父／cutover-compatible revert、候选采用、family 单向读写
  权威、旧 C 不重解释、world evaluator 和 Card read model，不复制本文全部研究。

### 12.4 API、wire 与安全不变量

- 旧 `status=canonical` 继续表达 adopted/display lifecycle；不得在切换后作为 formal evaluator fallback。
- Card DTO 是封闭 tagged union，普通界面不暴露 raw JSON、ID、内部 status、S/F/I/X 或 proof。
- `content_json`／`data_json`／`page_meta_json` 的 documentary raw values 通过 BaseSchema；reserved metadata 使用封闭结构；
  unknown key/type/version 可留在非权威候选，但 Canon admission fail closed。
- default 只预填；只有作者实际保存的 exact value 才能进入 promotion，不能把 Pydantic／DB default 当作者事实。
- Phase 2 Canon 基座启用后，Page publish 原子 seal exact PageRevision 并创建选择它的新 C；发布不自动创建 world Assert，
  除非同一提交显式 promotion。legacy published head 仅是 workflow pointer／projection，DocumentSearch(C) 与旧 C 重放
  不得读取它。Phase 1 仍沿用当前发布流程，但不把该状态冒充 formal DocCanon。
- Adoption Package 扩展为唯一 B promotion seam：锁 novel+head，验证 exact revision／Schema／ownership／ground／head，
  任一 include invalid 则全部无写入，成功才插 Assert、C、receipt 并 CAS head；作者修改 exact subset 后重新预览提交。
- 同一 `decision_id + decision_digest` 的成功重试返回原 C；同 ID 不同 digest 拒绝。authorizer 是作出正典决定的账户，
  executor 是实际请求或 worker subject；CAS 失败禁止自动 rebase，必须基于新 head 重新确认。
- 所有新表含 `novel_id`；body/query `novel_id` 只是目标，owner 从 current principal 推导；JSON ref 必须逐个验证同 novel。
- 历史 C 查询验证其 admission receipt，不用当前权限重判当年准入；当前权限仍决定谁可读。
- AI／parser preview validation 只产生非权威 judgment，不创建 Assert、不移动 head、也不成为 authoritative hardGround。
  只有显式 author adoption 把 exact mutable candidate snapshot 封入 AdmissionInputValue，并在单一 Admit 内重验、创建
  Assert+C+receipt 与 CAS head。AI、Suggestion、proof、validation result 与 imported `canon/status` 均不能选择 ownership
  或自称 machine-closed。
- StatementClaimRef wire 必须是完整内联 claim：regime、polarity、StatementValue、
  TimeScope；claim digest 是该完整值的规范哈希，不作为被哈希值中的自引用字段。
  outer Assert 不继承或求值 inner claim。禁止裸 digest、Assert pointer、自指和无限嵌套。
- 每个 family cutover Spec 必须同时固定 mutable authoring/draft carrier、唯一 canonical write seam、canonical read
  projection 和 legacy 字段允许用途。canonical edit 原子 seal revision + Assert + C + receipt + head CAS；任一步失败都不改变
  canonical Card 或 WorldEval。legacy 独立保存只能是明确草稿；canonical projection 只读可重建，禁止异步双写。v1
  cutover 单向；revert 不得使 canon-owned family 回到 formal-disabled／legacy-owned。
- Ask World 保持 evidence/RAG 语义；formal query 使用新接口，返回 verdict、C 和作者可读来源摘要，高级诊断才展开
  direct authority 与 S/F/I/X。`X` 必须区分 complete、budget-truncated、unsupported family 与 invalid evaluation context，
  不得省略或并入 S/F/I。

### 12.5 修正后的实施阶段与验收出口

| Phase | 范围 | 最小验收出口 |
|---:|---|---|
| 0 | 新 ADR + 实施 Spec；把已闭合 P0 映射为实际 resource catalog、principal/policy、v1 Statement union、versioned selector 与 fixtures | 四项项目事实无缺口；OpenAPI、DB、模块、状态机与可执行测试清单明确 |
| 1 | `world/bible` 成为默认“人物与世界”主页；Page／Entity tagged Card read model | 混合卡、空态／失败／筛选／草稿恢复／390px；旧对象深链不丢目标；无 DB 变更 |
| 2 | Assert／CanonRevision／head／ProfileTemplateRevision 基座；为每个新旧 novel 建 empty C0；切换 Page documentary selection | immutable 约束、完整 manifest replay、receipt、同 novel refs、单父 head CAS；page publish 推进 C；C0 不提升 legacy 事实 |
| 3 | generic resource-only blank、entity-bearing 创建、BaseSchema；Name family 首次 cutover | blank 零 Referent／Assert；名称操作 title+Referent+Assert+C 全成全败；切换后无 legacy fallback |
| 4 | CreateTemplate／AdoptSchema／PromoteHistoricalContent；custom typed fields，再 relation cutover | 旧卡固定旧 Schema；default 零事实；B-default；A 拒绝；invalid 全批回滚；exact subset 可重试 |
| 5 | v1 deterministic query：Name、typed scalar、signed binary relation、简单 time scope | 正／负／both／unknown、S/F/I/X 与旧 C replay；页面正文／AI／proof 不自证 |
| 6 | 目录导入与 Adoption Package 闭环 | source→preview→exact subset→Assert+C；stale／invalid 全拒；open/rejected 零事实 |
| 7 | Evidence／Writing context 切到 C facts + documentary pages；Story Scene-time 仍独立 | ContextSnapshot 固定 C；MemoryEvent 只服务连续性且不进 WorldEval；不从 legacy Profile／Relation fallback |
| 8 | event/time 后续 cutover；belief、A、惯性、branch、proof cache／FRI 按真实需求另立 Spec | WorldEval 只消费 C-pinned immutable story/event input 或 promoted Assert；每个 family 同步切读写 ownership |

首个 C 的默认政策：Phase 2 为每个 `novel_id` 创建 empty C0；旧小说的 C0 不选择 legacy Assert，作者显式初始化时从 C0
追加 C1 并确认 exact subset。head 永不后退，revert 也是新 C；跨 cutover exact revert 拒绝。family cutover 固定为 Name →
custom typed fields → relation → event/time → belief；每个 family 切换后只有 canonical write seam 能改变正典，唯一事实
读取路径是 Canon evaluator。

### 12.6 最小测试矩阵与文档同步

| 层 | 必须覆盖 |
|---|---|
| ORM／约束 | Assert/C immutable、每 novel 唯一 head、parent 0..1、只前进 CAS、同 novel refs、novel cascade、禁止普通 hard delete |
| Manifest／receipt | 完整映射可重放、delta 唯一还原、旧 page 不漂移；decision 幂等；authorizer/executor 分离；receipt 与 manifest/parent 绑定 |
| Resource resolver | 每个允许 kind 的 exact revision／digest／selector／archive；现有 mutable TargetRef、latest、unknown kind 和跨 novel ref 全拒绝 |
| Statement | StatementValue 含 kind/version/Schema/payload；StatementRef 再含 regime/polarity/time；裸 digest、Assert pointer、循环均拒绝 |
| Card | tagged Page/Entity、blank 不建 Referent、subject 与导航引用分离 |
| 原子名称／cutover | draft save 与 canonical edit 分开；title+revision+Referent+Assert+C+receipt+CAS 全成全败；失败不改变 canonical Card；无异步双写 |
| Schema | exact revision、旧 C 固定旧版、creation default 非正典、每个新 RR seal 时 pin Schema、default 零事实、unknown fail closed |
| Promotion | preview validation 零权威；Admit 内联封存 candidate/subset 并重验；B-default、A 拒绝、invalid 全回滚、AI 零 authority |
| Canon／query | C0/C1 不漂移、历史浏览不动 head、revert 追加新 C、跨 cutover exact revert 拒绝、S/F/I/X、budget truncation、旧 C replay |
| Security | owner/novel gate、跨 novel body/ref 拒绝、归档小说 404、receipt 与当前权限分离、后台不得伪造 author adoption |
| Evidence／Story | DocumentSearch(C) 不读 published latest；compiler 只经 facade 取 C；event/time 前 MemoryEvent formal-excluded，cutover 后只读 C-pinned input |
| Frontend／E2E | 默认主页、混合卡、空态／失败／保存／离开恢复／390px；创建→导入→采用→历史→query→writing |

Phase 0 起必须同步新 ADR、ADR-0006／0016、`CONTEXT.md`、整体设计、数据库设计、`docs/modules/02_world.md`、world
README、evidence compilation README、frontend README／用户指南、OpenAPI contract tests、architecture documents 清单和
docs 索引。代码中“CoreEntity 是所有世界对象的正史记录”等旧措辞也随 family cutover 修订。每 phase 收尾运行受影响
tests、lint 和 `make docs-check BASE_REF=origin/main`。

### 12.7 就绪定义与当前门禁

八项 P0 与四项项目事实已经没有语义多解；Proposed ADR、数据库/API Spec 和 canonical fixtures 均已起草。
当前门禁从“补研究缺口”切换为“评审并接受或修订 ADR-0017”。Phase 1 可规划；Phase 2+ 在 ADR 接受前不开工。
fixture 目前是规范数据而非已接入测试套件；实现第一步必须让 Pydantic canonicalizer 逐例验证 expected JSON/SHA-256。

Phase 0 通过的最低判据是：四项事实均有封闭 wire、约束、事务、失败码和 fixture；同一输入不再允许两种都合文档却
产生不同正典、历史重放、授权或 Card/WorldEval 结果的实现。
之后若真实需求证明 StatementRef 必须独立于 Assert/RR 存活、Page subject 需要独立绑定生命周期，或某 family 无法通过
单一事务完成读写 cutover，再做 deletion test；否则不新增表、模块或兼容层。

## 13. 后续维护规则

每轮后续研究都在本文完成以下闭环：

1. 在“研究与决策日志”追加日期、输入材料、主要反例、结论变化和未决问题；不覆盖历史判断。
2. 只有作者明确确认的内容才进入“方向已确认”；模型提出但未确认的内容保持“研究结论”或
   “开放问题”。
3. 当新证据推翻旧结论时，在新日志中说明取代关系，并同步更新“阶段性评估”“候选长期语义
   结构”和“当前开放问题”；旧日志保留原貌。
4. 外部模型引用的理论和论文只有在核对原始来源后，才可写成已验证证据；未经核对只能记录为
   待验证来源线索。
5. 研究记录不得反向覆盖当前实现文档。准备落地时必须另建实施 Spec；涉及事实所有权、模块
   边界、数据库或长期查询语义时，先取得用户确认并新增或修订 ADR。
6. 实现完成后再同步 `CONTEXT.md`、整体设计、数据库设计、world README、稳定接口、测试和
   前端文档，并通过 `make docs-check BASE_REF=origin/main` 验证。
7. 纯 RBOS/LWCM/CWEM 理论、世界演化原语和纵向基准只维护在探索式研究账本；HCSM
   只在本文维护与统一卡片、正典、查询和项目边界直接相关的工程语义。
8. 研究代理只读研究并提交候选；主代理负责反例复查、原始来源核验、要求补证和文档落笔。未通过主验收的
   结论不得进入第 5～9 节当前综合。

## 14. 本轮文档影响

- 受影响模块：Proposed 范围涉及 world、account、project、tasks、evidence 和 frontend；探索式研究文档未改动。
- 稳定接口、API、schema、wire 风险：高，但仅记录于 Proposed ADR／Spec；本轮没有修改当前契约、migration 或生产代码。
- ADR：新增 Proposed ADR-0017 并更新 ADR 索引；接受前不构成当前实现约束。
- 工程产物：新增 Phase 0 实施 Spec 与 canonical fixtures，更新本文当前状态和研究日志。
- 当前文档：未修改 `CONTEXT.md`、整体设计、数据库设计或模块 README，因为当前实现事实没有变化。
- 验证：`make docs-check BASE_REF=origin/main` 与尾随空白检查。

## 15. 2026-08-27：ADR 接受与 Phase 0 实施记录

**已实现**

- ADR-0017 已接受；canonical fixtures 已成为可执行测试，封闭 Pydantic wire、
  stdlib canonical JSON/SHA-256、artifact/policy registry 和 selector catalog 均已落地。
- 新增 `world_assertions`、`world_canon_revisions`、`world_canon_heads`、
  `entity_profile_template_revisions`；PageRevision 增加持久化 digest，作者项目在同一
  创建事务中获得空 C0/head。
- 实现 exact resolver、manifest/receipt replay、owner/novel 门禁、decision 幂等、
  head CAS 和追加式 revert。World Bible 发布已收口到唯一 Admit 事务。
- receipt 的 authorizer/executor/policy 是封闭 union；历史回放核对 policy digest、
  admission input/decision、manifest、parent、committed time 和 exact resource digest。

**剩余门禁**

1. 所有 formal family 仍为 `formal-disabled`；Assert admission 和 `name → typed_scalar →
   binary_relation → event_time → belief` 的每次 cutover 都需独立 Spec、原子读写切换
   和无 legacy fallback 验证。
2. `task_attempt` 只有封闭 wire，没有可调用 admission 路径；出现真实持久化自动
   采用流程时，必须先实现提交时 owner/scope/lease 重验。
3. evidence/compiler、世界查询和写作上下文尚未以 CanonRevision 为输入；在读取
   cutover 前，现有 legacy 行仍承担其当前语义。
4. “人物与世界”统一卡片主页、历史与百科查询仍未实现；下一步宜先交付
   只读 Card union/read model，消费已有 Page/CoreEntity 与 Canon 摘要，不预支形式推理。

本次没有修改 `world-model-evolution-research.md` 或 MCEW 探索式文档。
