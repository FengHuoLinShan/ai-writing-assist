# RP 长期记忆调研与持续决策台账

> 性质：基于 2026-09-01 当前 worktree 与外部官方资料形成的研究、候选架构和分阶段计划；
> 不构成已实现的 API、schema、wire 或运行时契约。进入实现前，涉及新表、跨模块稳定接口或
> 长期所有权的决定必须经用户确认并视影响补 ADR。
>
> 目标画像：希望长期进入一个幻想世界、重视人物质感、故事连贯和分支自由，但不愿理解作者
> 后台、Prompt、token、数据库或版本术语的 RP 用户。
>
> 术语说明：用户原话中的 “Cloud Code” 按上下文暂理解为 **Claude Code**。若实际指
> Google Cloud Code，应另补调研，不用本文推断替代。
>
> 影响面：候选涉及 `interaction`，并只读消费 `evidence`、作者 source revision 和可能的
> World 对象投影；不允许 RP 写回作者 World、Story、Writing 或正史。
>
> 实施状态（2026-09-02）：P0 standalone runner、v1/v2 合成 JSONL、五臂离线编译、原子报告、
> opt-in model/review CLI、窄测试与 Make 入口已实现；committed case 会把模板确定性展开到
> 24K～256K 的实际合成历史。第二次获批的官方 DeepSeek V4 Flash dev model run 已完成 35 个 v2 候选：
> A/B/C/D/E 的 case pass 为 3/5/5/6/3（各 7），fact match 为 5/9/9/10/7（各 11），
> manual hard retention 35/35、sentinel 泄漏 0。B 相对 A 有方向性提升，但 C 未超过 B；人工盲评
> 未导入，`quality_claim_allowed=false`，所以 B/C 均未启用，P2 仍不启动。P1 已修复旅程态 source query、同 path/end segment
> 幂等复用和 manual authority-aware overview 选择，并落地 oldest-prefix bounded reducer、
> protected raw suffix、净缩减门、4-pass urgent loop、snapshot-frozen capability profile 与“记住这一点”显式保存入口；segment/raw
> 检索注入尚未因完整真实配对门过门，未启用。用户已授权继续完整计划与后续必要 ADR/migration，
> 但授权不替代 B/C、gold/extracted D、人工盲评和安全硬门。
> 8-case untouched holdout 已冻结并通过 103/103 离线断言；没有校准 dev review 生成的 hash-valid
> threshold config 时，test model/review 会在 client 前失败，当前未运行任何 holdout 模型。

## 1. 结论先行

RP 长期记忆采用**混合路线**，但分阶段落地：

1. 保留现有“不可变选中路径 → 分段概要 → 七区总回顾 → 未覆盖原文尾部”的压缩骨架。
2. 先让已保存却未被后续生成消费的 `interaction_summary_segments` 成为可按需召回的
   “相关往事”索引；高置信命中再有界回读当前分支原始节点，不先加新表、向量库或第二套 RAG。
3. source-bound 旅程把冻结作者对象目录视为只读**基础对象库**；RP 后续生成的原创对象、
   状态变化和关系变化形成旅程私有、分支锚定、可重建的**事实增量覆盖层**，不维护一份可变
   “当前对象快照”作为真相。
4. “完整 RP 对象视图”是 `冻结来源对象投影 + 当前选中路径有效的 RP 增量`，不是复制作者
   对象，也不是把 RP 事实提升为作者正史。
5. 原始消息节点仍是 RP 已发生内容的审计来源。回顾、分段概要和结构化对象增量均是派生资产；
   路径、用户修正或 schema 漂移时可局部重建，不能反过来改写原始故事。
6. 首期先做长程回放评测、检索 query 修复和分段概要召回。只有评测证明压缩加召回仍持续丢失
   对象状态，才进入结构化增量的 schema/ADR 阶段。
7. 作者手工保存回顾后，新回顾立即成为叙事权威；结构化层先屏蔽全部旧自动事实，再用
   有界、可审计的补偿 operation 修复投影。修复未完成只降级结构化召回，不撤销已保存回顾，
   也不让旧事实自动复活。
8. 压缩、相关往事、source 与对象覆盖层只通过一个 capability-aware Prompt Pack 共享本轮预算；
   raw tail、manual/required 与 required source 先保留，optional 槽再竞争。禁止 provider 静默从头截断。
9. 周期/紧急整理共用 bounded raw-prefix reducer：从 authority-compatible overview 起步，只压最老连续
   prefix，保留当前请求与近期原文；每 pass 净缩减并形成可恢复 prefix revision，不重喂旧 segment 文本。
10. P0 用 standalone `rp_long_memory` runner 先证明 synthetic 数据、A–E pack、安全门与报告可复现；
    offline compile 默认无网络，付费模型和盲评分别显式运行，不扩通用 EvalSuite 也不冒充真实用户验证。

这不是在压缩与对象库之间折中各做一半。两者负责不同问题：

- **压缩**回答“故事走到哪里、现在发生什么、还有什么没解决”；
- **对象覆盖层**回答“谁是谁、当前拥有什么、在哪里、与谁是什么关系、何时发生了什么变化”；
- **原始路径**回答“这些判断从哪段故事而来，分支切换后还是否成立”。

## 2. 当前仓库证据

### 2.1 已存在、应复用

- 每条旅程已有独立隐藏 `project_kind=interaction` 项目，以 `owner_id + novel_id` 隔离。
- 消息节点不可变；branch selection 和 selected leaf 决定当前路径。未选 sibling 不进入 Prompt、
  回顾或默认导出。
- 约每 16K token 估算形成一个不可变分段概要，同时增量更新七区总回顾；每 8 个有效分段标记
  一个 checkpoint。
- 故事 Prompt 已消费“当前有效总回顾 + 尚未覆盖的原始尾部”，并允许用户手工修正总回顾。
- `interaction_summary_segments` 已保存起止节点、path hash、token 规模、上游 overview/checkpoint
  与自然语言分段概要，但当前故事编译不召回这些历史分段。
- source-bound 在途实现会冻结作者 Writing draft/hash manifest、剧情锚点、对象目录、人物知识和
  关键歧义，按每次 attempt 最多 16K 的独立资料预算编译原作证据。
- 作者侧已有 `CoreEntity`、关系、人物知识和 Story continuity 事件/快照；这些资产只服务作者
  正史与 Scene 时点投影，不能与 RP 分支事实混表。

### 2.2 已确认的真实缺口

1. 七区总回顾是单一累计压缩漏斗；早期细节一旦被概要遗漏，当前编译没有自动恢复路径。
2. checkpoint 目前主要证明 revision 血缘，不形成第二层可检索内容。
3. source-bound 资料检索主要使用最新用户消息。用户在长旅程中只说“继续”“看看情况”时，
   query 缺少当前局面、人物和未决线索。
4. 原 256K/512K/750K 共用字符阈值已被 versioned capability profile 替代；DeepSeek 使用
   256K/360K/400K，unknown 使用 16K/20K/24K，估算取字符法与 shared tokenizer 较大值。
5. `rp_context` 仍只提供 source context on/off 计分；`rp_long_memory` v2 已获得一次 DeepSeek V4 Flash
   dev model 证据，硬事实与 sentinel 门通过，但 B 尚无校准人工盲评、C 没有超过 B，因此仍不能
   启用候选记忆层或形成质量结论。
6. 本地没有 Kimi 长上下文校准报告；530K 真实门禁存在不等于已经通过。
7. 手工回顾从冻结旧 base 保存并重放期间新 tail 时，finalizer 会复用同
   `path_hash + end_node_id` episode segment；SQLite 领域回归与 fresh PostgreSQL 17 + pgvector
   实例均证明 segment 数量不增加，新的 automatic overview 仍直接基于当前 manual revision。
   PostgreSQL 超长旅程/真实模型门仍未运行。
8. source `reference_key` 随 manifest 版本变化，已有资料升级改用内部 `target_id` 重映射；
   当前 `reference_manifest.aliases` 又已折叠成纯字符串，不保留 candidate/canonical alias 权威。
   因此它尚不能直接承担跨 source 版本的 structured object identity resolver。
9. source context 在 Evidence 内独立使用 16K 上限，interaction 随后直接拼 overview/source/raw tail；没有
   一个总 Prompt IR 同时计算 segment recall、raw rehydration、未来 object facts 与 source 的额度，也没有
   记录跨层重复 token。局部预算通过不等于最终请求安全。
10. `_best_overview_for_path()` 已先定位当前路径最新适用 manual revision，再只允许该 revision
    或可沿 `based_on_revision_id` 追到它的 automatic descendant；回归覆盖“旧权威链 anchor 更远”时
    不得晋升。它仍不是 P2 barrier/recovery selector。

### 2.3 不能被新方案破坏的边界

- 用户最新明确修正 > 手工回顾 > 当前选中路径 > 自动派生记忆 > 冻结原作资料 > 模型知识。
- 只使用当前选中路径可证明有效的派生记忆；分叉前复用，分叉后隔离。
- RP 输出、原创对象、关系和事件不得写回作者 World、Story、Writing 或 Canon。
- 不因 provider/model 切换重建全部模型中立记忆。
- 不静默截断尚未被有效概要覆盖的原始消息。
- 普通界面继续只使用“旅程、发展、回顾、记住”等作者/读者语言，不暴露 ID、hash、token、
  checkpoint、overlay 或数据库状态。

## 3. 外部平台调研

### 3.1 OpenAI Codex / Responses compaction

官方资料：

- [Compact a response](https://developers.openai.com/api/reference/java/resources/responses/methods/compact)
- [Model guidance: Compaction](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.2)

可借机制：

- 在接近上下文上限前主动压缩，而不是等待请求失败或从最旧消息机械截断。
- 压缩后保持后续调用的功能性 Prompt 不变，以减少行为漂移。
- 在任务里程碑压缩，不必每轮压缩；压缩本身也有成本。
- 压缩产物只负责继续工作，不等于可供业务查询的事实数据库。

不能照搬：

- OpenAI 的 compact item 可以是加密、opaque、实现可演化的 provider 产物。RP 必须允许用户查看、
  纠正回顾，并支持 DeepSeek/Kimi 等 provider 热切换，因此不能把 opaque compact item 当作
  旅程事实源或唯一记忆。

### 3.2 Claude Code

官方资料：

- [Explore the context window](https://code.claude.com/docs/en/context-window)
- [How Claude remembers your project](https://code.claude.com/docs/en/memory)

可借机制：

- 自动压缩会话历史，但把项目根指令、auto memory、计划和近期文件等从外部持久来源重新注入。
- “会话压缩”和“跨会话记忆”分层：前者是工作上下文，后者是可查看、可编辑的持久资料。
- 详细主题不全部常驻上下文；入口保持简洁，需要时再读具体主题文件。
- 可用明确 focus 指令影响一次压缩应该保留什么。

不能照搬：

- 代码仓库文件是可重新读取的外部事实源，RP 世界没有同等天然、结构化且始终正确的文件系统。
  若不额外保存来源锚点，压缩后“再读记忆文件”仍可能只是再读一次错误概要。
- 编码规则通常单线有效；RP 分支事实必须按 path hash/节点祖先判断，不能把整个旅程的记忆无条件
  注入每个 sibling。

### 3.3 Gemini CLI

官方资料：

- [Gemini CLI core: chat history compression](https://geminicli.com/docs/core/)
- [Gemini CLI configuration](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md)

可借机制：

- 压缩阈值按模型 context limit 计算，而不是所有模型共用一个永久常量。
- 保留一段最近 history，同时压缩更旧内容；最近回合和较老工具输出使用不同保护策略。
- `GEMINI.md` 类层级资料与会话 history compression 分开管理，可显示当前实际加载内容。
- PreCompress hook 表明“压缩前先备份、分析或提炼关键状态”是独立可验证阶段。

不能照搬：

- Gemini CLI 文档把 compression 描述为信息意义上的 lossless，但 RP 文学细节与人物关系具有高歧义，
  不能把任何 LLM 摘要宣称为真正无损。
- 大量可调阈值不应变成 RP 普通用户设置；它们只能是服务端 capability profile 与评测参数。

### 3.4 Cursor

官方资料：

- [Summarization](https://docs.cursor.com/en/agent/chat/summarization)
- [Memories](https://docs.cursor.com/en/context/memories)
- [Dynamic context discovery](https://cursor.com/blog/dynamic-context-discovery)

可借机制：

- Cursor 明确承认压缩会丢失关键细节，因此保留 chat history 文件引用，让 agent 在摘要不足时回查。
- 大结果保存在上下文外，只给模型一个可按需读取的引用；动态发现优于把所有资料常驻 Prompt。
- 自动生成的长期 memory 与普通对话摘要分开，并给用户查看/审批入口。
- 大文件先给结构轮廓，再按 query 展开局部内容。

不能照搬：

- RP 生成模型不能自行选择工具或自主搜索整棵故事树；检索必须由确定性业务工作流编排，并先做
  owner、novel、journey、selected path 与预算门禁。
- “让模型自己发现缺什么再搜”在 RP 中会造成不可预测费用和未来分支泄漏；应由服务端先提供
  有界相关往事，必要时再让用户显式查看完整历史。

### 3.5 跨平台共识与 RP 转译

| 平台共识 | RP 转译 |
|---|---|
| 压缩不是永久事实存储 | 总回顾负责工作上下文，不拥有原始故事事实 |
| 稳定资料从上下文外重新注入 | 冻结 source 对象、用户修正和 RP 对象增量按需编译 |
| 最近内容优先保真 | 保留未覆盖原文尾部，不只保留摘要 |
| 大历史可通过引用回查 | 召回 path-valid 分段概要，必要时回读原始节点范围 |
| 阈值应随模型能力变化 | capability profile 决定正常/整理/硬门禁预算 |
| 长期记忆需要可查看/可纠正 | 回顾和“记住此事”使用自然语言入口，不依赖 opaque provider state |

### 3.6 RP/Lorebook 产品：SillyTavern 与 NovelAI

官方资料：

- [SillyTavern World Info](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [SillyTavern Chat Vectorization](https://docs.sillytavern.app/extensions/chat-vectorization/)
- [SillyTavern Summarize](https://docs.sillytavern.app/extensions/summarize/)
- [NovelAI Lorebook](https://docs.novelai.net/en/text/lorebook/)

新增证据：

- SillyTavern 明确把 World Info 描述为运行时动态字典，chat/character/persona/global lore 只是不同
  source scope；关键词或向量命中之后仍需经过其它过滤和统一 token 预算。候选数量与最终注入预算
  是两道门，不应由一个 `top_k` 兼任。
- SillyTavern 的 chat vectorization 保存并召回**原始消息**；可选摘要只改善向量索引，不替换原文。
  官方同时警告它不保证改善记忆，并会因动态改变 Prompt 而降低 prefix cache 命中。
- SillyTavern summary 锚定生成时的最后消息；删除/编辑消息后会回退到前一个仍有效概要。它还允许
  手工修正、恢复上一版和暂停自动更新，说明“路径有效性 + 可纠正性”比一份永远前滚的概要重要。
- NovelAI 把人物、地点、物品、势力等资料放入 Lorebook entry，通过 activation key、search range、
  cascading activation、reserved tokens 和总预算编译；Context Viewer 会显示 inclusion/reason/token/
  trim 等信息。选中文本可快速加入 Lorebook，降低手工记忆成本。

对本方案的修订：

1. `interaction_summary_segments` 更适合做低成本**检索索引**；命中后应允许有界回读原始节点，不能
   把概要本身当作唯一事实载荷。
2. 召回候选数、必保留槽位和最终 token budget 必须分开。手工记忆/当前修正可预留预算，可选往事
   触顶后省略；不提供 `ignoreBudget` 绕过总门禁。
3. 动态召回必须记录 cache read/miss 影响；如果质量增益不足以覆盖延迟和费用，应撤销而不是默认常开。
4. 外部 RP 产品通常把 lore/memory 绑定到 story/chat/agent，未解决本项目的不可变 sibling 选择问题；
   “分支继承父状态”不能替代 path-prefix 验证。

本机当前活跃 SillyTavern release checkout 含未提交的用户自定义 Prompt、Pure Chat 和移动端修改，本轮
没有把该脏 checkout 当作上游产品事实；机制更新以最新官方文档为准，源码细节继续引用仓库既有的
固定提交研究。

### 3.7 分层/时间化记忆：Letta、Graphiti 与 Generative Agents

官方或一手资料：

- [Letta core memory block API](https://docs.letta.com/api/resources/agents/subresources/blocks/methods/attach)
- [Letta fork conversation API](https://docs.letta.com/api/resources/conversations/methods/fork)
- [Graphiti temporal context graph](https://github.com/getzep/graphiti)
- [Generative Agents paper](https://arxiv.org/abs/2304.03442)

可借机制：

- Letta 区分始终在上下文中的 core memory block 与可检索 archival memory，证明“常驻工作记忆”和
  “按需长期记忆”应有独立预算。
- Graphiti 把原始 episode 作为 provenance，实体和关系事实带有效期且不删除旧历史；这与本项目
  “原始消息为审计源、对象状态为可重建投影”方向一致。
- Generative Agents 使用完整自然语言 experience stream、higher-level reflection 和动态 retrieval，
  并以 relevance、recency、importance 组合选择记忆；其消融结果说明仅保留最近内容不足。

不能照搬：

- Letta 的 fork 仍属于同一个 agent，并用最新共享 memory block 重编 system message。RP sibling 若共享
  可变核心记忆，会让后来分支状态回流到早期 sibling。
- Graphiti 的 `valid_at/invalid_at` 适合单一时间线；RP 的事实可以在一个 sibling 失效、在另一个 sibling
  继续有效，不能用全局失效时间表达。
- Graphiti 需要新的图数据库/图检索基础设施，Letta/Generative Agents 依赖模型自主写入或搜索记忆；
  当前仓库禁止自治工具选择，且 PostgreSQL 不可变节点与事件式 delta 已足够表达首期问题。
- Generative Agents 论文也指出成本、长期鲁棒性、memory hacking 和 hallucination 仍是开放问题；其
  relevance/recency/importance 权重不能未经 RP 回放直接成为产品常量。

对本方案的修订：

- 对象覆盖层保存**事实增量/事件**，不保存一份可变“当前对象”作为真相；当前对象视图由当前路径
  上的增量折叠得到。
- RP 的有效顺序使用 message ancestry/节点位置，而不是墙钟或单一 `valid_at`；数据库 `created_at`
  只作审计时间。
- 检索不先上统一加权公式。首版使用保留槽位：手工记忆、开放事项、相关对象、相关往事、最近有效
  分段；每个槽位再受统一预算。权重方案只有在固定回放能证明更好时才加入。

### 3.8 实现级复核：压缩安装边界、近期尾部与派生身份

官方或一手资料：

- [OpenAI Compact a response](https://developers.openai.com/api/reference/java/resources/responses/methods/compact)
- [Claude Code agent loop: automatic compaction](https://code.claude.com/docs/en/agent-sdk/agent-loop)
- [Claude Code hooks: PreCompact/PostCompact](https://code.claude.com/docs/en/hooks)
- [Gemini CLI `chatCompressionService.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/context/chatCompressionService.ts)
- [OpenCode `session/compaction.ts`](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/compaction.ts)
- [Azure Event Sourcing pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)

新增实现证据：

- OpenAI 的 compact 返回保留用户消息并追加一个 compaction item，同时单独记录压缩 usage；
  新请求的 system/developer instructions 可以替换，不要求从 opaque item 解析规则。
- Claude Code 把 compaction 暴露为明确生命周期边界；持久规则从 `CLAUDE.md` 重新注入，
  `PreCompact` 可在安装新上下文前阻断/备份，`PostCompact` 可观察实际概要。
- Gemini CLI 的当前源码按模型窗口比例触发，保留一段近期 history，把上一个
  `state_snapshot` 与新历史融合，还额外调用一次模型检查概要；空概要或压缩后更大都不安装。
- OpenCode 的当前实现按完整 turn 选择有界近期尾部，用前一份 summary + 新 head 继续压缩，
  并另行裁剪旧工具输出。这证明“压缩边界”和“不同资料类型的保真策略”应分开。
- Event Sourcing 把 append-only event stream 作为事实源，把当前状态与 snapshot 定义为可重建投影；
  snapshot 只是真实性能门触发的优化，不替代 event stream，消费重复事件必须幂等。

对 RP 方案的进一步修订：

1. 一次压缩完成是“新活动回顾安装”，必须经 path/node list/overview epoch 门禁；
   不是对一个字符串的原地覆盖。
2. 硬规则、当前用户修正和冻结 source context 从各自的权威源重新编译；不让压缩文本
   或 provider opaque state 拥有它们。
3. 分段概要的身份是“某段已发生故事的索引”；同一段故事在新手工基线下可能产生
   不同的当前状态推导。二者不得共用一个可变存储身份。
4. 不照搬“保留最近 30%”或每次额外一次自检 LLM 调用。RP 已有明确 coverage frontier、
   未覆盖 raw tail 和长程 eval；只在固定回放证明另一次调用有净收益时才增加。

### 3.9 对象身份复核：稳定 ID、非唯一名称与派生 provenance

官方或标准资料：

- [Wikibase data model](https://www.mediawiki.org/wiki/Wikibase/DataModel)
- [Wikidata labels](https://www.wikidata.org/wiki/Help:Labels)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)

新增证据：

- Wikibase 把不变的 Item ID 与给人看的 label/description 分开；ID 不应随名称变化，label 只帮助
  找到对象。Wikidata 还明确允许多个 Item 共用同一 label，说明名字不能作为唯一键。
- PROV-O 把派生事实与其使用的 entity、生成 activity 和 `wasDerivedFrom` 链分开；同一对象的
  新推导不等于新对象身份。
- 当前 source revision 的 `reference_key` 由 `manifest_hash + entity_id` 生成，所以版本升级时会变；
  但已实现的升级路径正是用内部 `target_id` 重映射玩家/固定/忽略项。
- source manifest 已把同一归一化名称/别名指向多个对象的情况固结为 ambiguity；不由后续
  模型按“更像”自行选择。
- 作者 World 的融合工作流即使对高相似对象也保留 `keep_separate/needs_review`；已采用对象的
  canonical alias 还需明确授权。RP 派生层不应比作者正史更激进地自动合并。

对 RP 方案的修订：

1. `reference_key` 是某个 source revision 中的可见引用/证据键，不是跨版本对象身份。
2. 名称、别名、类型和语义相似度只用来生成候选；服务端稳定 object key 与 provenance 才能
   成为 delta 端点。
3. 同一个 RP 对象可有多个有证据的名称，同一名称也可对应多个对象；冲突时保留歧义，
   不用自动 merge “解决”。
4. 对象 operation 除 raw node/range 外还必须保留这次推导的 source revision/reference、summary task/
   derivation key 和 overview authority lineage；不需引入 RDF 或 PROV 库。

### 3.10 追溯修正复核：补偿事件、选择性重放与失效范围

资料与实现证据：

- [Azure Event Sourcing Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [Martin Fowler: Retroactive Event](https://martinfowler.com/eaaDev/RetroactiveEvent.html)
- [Graphiti edge operations 当前源码](https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/edge_operations.py)
- [Graphiti #1728：未限定失效候选导致无关事实互相退休的复现报告](https://github.com/getzep/graphiti/issues/1728)

新增证据：

- Event Sourcing 的基本修正方式不是原地改旧记录，而是追加 compensating event；当前状态是可重放的
  projection。原事件仍保留，修正和审计不会互相排斥。
- Retroactive Event 可以通过 snapshot 后重建、rewind/replay 或 parallel model 得到修正分支；但合并
  影响面很复杂。Fowler 明确把 selective replay 和限制到系统/时间子集作为降复杂度手段，也指出这不是
  常见的早期需求，前置改造不可低估。
- Graphiti 当前 ingestion 会把候选边交给矛盾解析后按时间失效。#1728 是一份带源码路径的失败复现：
  候选池失去端点范围后，模型可把语义相近但对象关系不同的边判为矛盾并退休。该 issue 不是 RP
  的现成实现规范，但提供了明确的反例：提高 Prompt 或换更强模型不能替代结构性候选边界。

对 RP 方案的修订：

1. 手工修正只追加新的 authority/barrier/compensating operations；不原地改写自动 delta。
2. 日常保存不默认全路径 rewind/replay。先对旧 active projection 建全局 manual barrier，再对该
   有界 projection 的候选逐项修复；section diff 只能排序或分批，不能排除候选。完整重建只保留为
   实验对照、schema 迁移或投影损坏的维修路径。
3. 服务器先按 owner、`novel_id`、journey、selected ancestry、source cutoff、authority lineage、
   object/field 或 relation endpoints 限定“可被替代”的候选；模型只能在候选内分类，不能返回任意
   持久 ID 退休别处事实。
4. “模型未提到某旧事实”不等于“保留”或“删除”。候选必须逐项得到 `keep/suppress/replace/uncertain`
   处置；缺项、歧义或校验失败继续 fail-closed。

### 3.11 并发快照复核：expected revision、原子 checkpoint 与 branch pointer

资料：

- [KurrentDB：Appending events / Handling concurrency](https://docs.kurrent.io/clients/node/v1.3/appending-events)
- [KurrentDB：Projections engine V2](https://docs.kurrent.io/server/v26.1/features/projections/engine-v2)
- [PostgreSQL：Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [Git data model](https://git-scm.com/docs/gitdatamodel.html)

新增证据：

- KurrentDB append 可携带精确 expected stream revision；流版本已变化就显式冲突，而不是 `any` 盲写。
- projection checkpoint 的进度、partition state 和 emitted events 必须构成一致观察边界；其 engine/schema
  版本不兼容时从头重建，不把旧 checkpoint 强行解释成新格式。
- PostgreSQL 默认 Read Committed 下，`SELECT FOR UPDATE` 会等待并取得已提交的新行版本，再重新判断
  条件。只要所有 interaction memory writer 都按既有 project/task fence → journey row lock 顺序入场，
  无需为了一个低频 reconcile 全仓切 Repeatable Read/Serializable。
- Git branch 只是指向一个 commit 的可移动 ref；历史有效性由 commit parents/reachability 决定，当前
  `HEAD` 不是其他分支对象的所有权边界。

对 RP 方案的修订：

1. manual save 在持有 journey 行锁的事务内冻结 candidate root；P2 delta writer 也必须持有同一锁并
   重验 `overview_epoch/source_context_epoch`，让“旧 writer 先提交并进入快照”或“manual barrier 先提交、
   旧 writer stale”二者线性化，不新增 `memory_epoch`。
2. candidate snapshot 使用 server canonical bytes 的 hash，绑定 manual revision、冻结 path/leaf、source
   context 和 compiler/schema version；任务只保存 root，不把整份私有对象库塞进通用 task meta。
3. reconcile 结果归属于冻结 anchor/path 的 branch lineage，不归属于完成时当前 selected branch。
   切换 sibling 不应让安全结果失去历史归属，也不得让它进入当前 sibling。
4. 内部分批只是计算 checkpoint；结构化 barrier 只在一次原子 recovery commit 后解除。任务显示 done、
   某批 LLM 已完成或部分 fact rows 已写入，都不能单独代表 projection 已发布。
5. 不引入 KurrentDB、Git 对象库、全仓 Serializable 或第二套队列；只复用当前 PostgreSQL、不可变消息树、
   overview/source epochs、journey lock 与 task lease fence。

### 3.12 混合上下文复核：opaque compaction、按需记忆与模型能力差异

资料：

- [OpenAI：Compact a response](https://developers.openai.com/api/reference/java/resources/responses/methods/compact)
- [OpenAI：Create a model response](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Claude Code：项目与自动记忆](https://code.claude.com/docs/zh-CN/memory)
- [Claude：长程与多 context-window prompting](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- [Kimi：模型列表](https://platform.kimi.com/docs/models) 与 [K3 当前产品页](https://platform.kimi.com/)
- [DeepSeek：V4 模型与上下文](https://api-docs.deepseek.com/quick_start/pricing)

新增证据：

- OpenAI `/responses/compact` 返回 continuation 用的 opaque compaction item 和 usage；它适合供应商会话延续，
  不提供 RP 所需的分支可审计事实结构。Responses 的 `truncation=auto` 会从对话开头丢 item，默认 disabled
  则超限失败；RP 不能把 silent head truncation 当成记忆策略。
- Claude Code 把每次都加载的 CLAUDE.md/短自动记忆与按需读取的 topic files 分开；当前文档明确建议
  常驻说明简短、路径/主题资料按需加载。Anthropic 的长程提示指南还指出，在某些任务里用文件系统状态
  开新 context 比继续压缩更合适。
- 当前支持面不是一个窗口：仓库 provider templates 同时列有 Moonshot 8K/32K/128K、Kimi 新系列与
  DeepSeek；当前官方页面显示的模型窗口从 8K 到 1M 都存在。现有 256K/512K/750K 共用阈值不能随热切换
  自动变安全。
- 2026-09-01 付费 pilot 前复核的 DeepSeek 官方页面把 `deepseek-v4-flash` 列为 1M context、最大
  384K output；eval-local profile 仍只取 400K verified input ceiling。官方峰值 cache-miss 输入价为
  $0.44/1M token、输出 $1.32/1M，实际费用仍以 provider usage/账单为准，不能由字符估算冒充。
- 当前代码又把 source packet 独立限制为 16K，随后直接拼 overview/source/raw tail；因此 16K 是 source
  局部上限，不是整个故事 Prompt 已为它预留的合法额度。未来再加入 segment/object block 会发生预算叠加。

对 RP 方案的修订：

1. 只保留一个 interaction-owned Prompt Pack：硬规则、overview、RP 当前态、相关往事、source packet 与
   raw tail 先成为带 token/provenance 的 sections，再统一分配本轮预算，最后渲染消息。
2. 常驻核心只含不可丢规则、manual/required、当前用户输入和尚未安全压缩的 raw tail；segment、原文回读、
   optional source 与对象关系均按 query 激活，不全量常驻。
3. provider compaction/cache 只能是可关闭的传输优化。业务编译始终能从模型中立资产重建；明确禁用
   silent head truncation，不因缓存命中改变事实选择或权威。
4. hard input、compaction trigger、输出预留和 estimator margin 从 server capability profile 派生；未知
   model 不继承 750K，只进入保守 short-context fallback，直到有官方规格与真实 usage 校准。
5. 不直接复用 author `CompiledContext` 的确认/可排除语义，也不跨模块 import 其 service；P1 先使用
   interaction 私有的最小 section IR。只有第二个业务消费者需要相同策略时，才评审公共 facade。

### 3.13 紧急整理复核：里程碑压缩、兼容 revision 与原始请求保护

外部与仓库证据：

- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.2) 建议监控
  context，并在重要里程碑后有意 compaction，而非每轮都压；compaction item 仍是 opaque continuation。
- [Claude long-horizon guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
  明确把外部文件/测试/进度状态作为跨窗口恢复源，并指出某些场景开新窗口读取这些状态优于继续摘要。
- 当前每次 `finalize_summary_task()` 同时创建一个 episode segment 和一份累计 overview revision；第 8 个
  segment 只在 producer 标记 checkpoint，所有 revision 本来都不可变且可按 path anchor 恢复。
- 当前 urgent flow 在 story Prompt 估算超过 512K 时，把 overview 后的**全部** tail 交给一次 summary；若
  summary input 超过 750K 就失败，成功时 coverage 直接推进到当前 leaf。当前 leaf 往往就是本次等待回答的
  user 节点，因此它可能只剩概要表达、失去原始 user role/字节。

对方案的修订：

1. segment content 继续只作 episode index/相关往事。相同 lineage 的 segment 已有配对 overview revision，
   应直接选最新兼容 revision；跨 manual lineage 重喂旧 segment 文本会复活旧状态，禁止作为 reducer 输入。
2. periodic 与 emergency 使用同一个 oldest-prefix reducer：从最新 path/authority 兼容 overview 开始，只按
   whole-node/完整对话节拍折叠更老 raw prefix，永远保留当前 request 与近期 raw suffix。
3. 一次 pass 的 full path/node list 仍用于 stale fence；domain segment/revision 只锚定本次已处理 prefix。
   这样每次调用有界、每次成功都推进 coverage，崩溃后从最新 revision 继续。
4. 每次 pass 必须证明未来 story Prompt 的估算 token 净减少；非缩减输出不安装，不再加一次 judge。
5. 一个 handler 内做固定最大 pass 数，并在每次 domain commit 后释放事务；不新增 task type、子 Agent 或
   长事务。worker 崩溃由现有 lease/restart 从已提交 revision 续跑；总预算耗尽时保留 path/attempt 并明确失败。
6. 第 8 段 checkpoint 不作为恢复门槛；任何兼容 overview revision 都是 restart point。若 P1 完成后仍无
   独立 consumer 使用 8 段 marker，应做删除审计，而不是围绕 write-only cadence 建新机制。

### 3.14 评测工程复核：严格数据 schema、同任务配对与本地正式入口

资料与仓库证据：

- [OpenAI Evals API](https://developers.openai.com/api/reference/java/resources/evals/methods/create) 把 evaluation
  定义为明确 data-source schema + testing criteria，并允许在不同 model/parameters 上运行同一评测。
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model) 建议从已工作的 baseline
  出发，每次只改一组 Prompt/模型参数并重跑同一代表性 eval；token/调用减少只有在最终质量仍过门时才算收益。
- 当前 `evals/rp_context.py` 故意只接受 corpus/scenario SHA-256 与 `SourceRangeRef`，并只汇总
  `context_on/context_off`；它没有消息树、五臂 pack、对象 operation 或 model executor。
- 通用 `DatasetCase/EvalSuite/readiness/report` 当前固定服务 RAG/Scene/World/Outline。增加 RP suite 会连带
  baseline minimums、scenario inventory、review/freeze/runner choices，远超 P0 所需。
- `evals.ask_world` 已证明一个 standalone module + Pydantic strict JSONL + 原子 JSON 报告 + exit 2 门禁足够；
  既有评测还记录了从 stdin 启动多进程导致 `/<stdin>` 失败，正式 module/CLI 是可靠性边界。
- `.gitignore` 已覆盖 `backend/evals/.cache/`、`evals/artifacts/` 与 `evals/datasets/local/`；模型输出、盲评包
  和本地扩展数据无需再造目录。

对 RP P0 的修订：

1. 不改 `rp_context.py`、通用 `EvalSuite` 或 hosted OpenAI Evals；新增一个正式
   `python -m evals.rp_long_memory` 本地入口，复用 Pydantic、`EvalCache`、project LLM facade、已有 rubric
   维度和临时文件 replace 惯例。
2. committed JSONL 只保存合成 operation、template ID/value、branch DAG、manual/source 事件和 oracle；运行时
   确定性渲染消息。禁止本地作品/Vault 文本、绝对路径、Key 或真实用户对话。
3. 离线 compile 是必跑基础门；真实模型阶段必须显式 `--novel-id + --allow-paid-model`，使用同一 project
   provider/profile 跑配对 arms，不自动换 Codex CLI 或备用模型。
4. 模型阶段分为 strict fact probe 与 production-shaped story candidate：前者测模型是否使用正确 pack，后者
   只进入盲评。首版不引入未校准 LLM judge；安全 sentinel 与 pack assertions 仍由代码决定。
5. 报告保留全部 metric inventory，缺证据写 `available=false + reason`。模型/人评未运行时离线门可通过，
   但 `quality_claim_allowed=false`；不能把 compile-ready 改写成长期体验验证。

## 4. 候选路线对照

### 4.1 路线 A：只做记忆压缩

优点：

- 复用当前表、任务、Prompt 和 UI；改动最小。
- 天然继承 selected path、overview epoch 和手工修正防晚到覆盖。
- provider 中立，热切换无需重建。

质疑：

- 累计概要会反复重写同一批事实，早期细节发生不可逆的信息衰减。
- 不能可靠回答“某物品现在归谁”“谁知道哪个秘密”“某承诺何时形成”等对象状态问题。
- 分段概要虽保存，却没有进入后续检索；仅继续优化总结 Prompt 无法恢复已经漏掉的事实。

优化后结论：

- 压缩必须保留，但不能单独承担全部长期记忆。先补“分段概要可召回”和“原始范围可回读”，
  再测量剩余对象状态缺口。

### 4.2 路线 B：直接复用作者 World / continuity 作为 RP 对象库

优点：

- 现成对象、关系、事件、知识边界、向量和时间投影能力完整。
- source-bound 已经需要读取作者对象目录和人物知识。

质疑：

- 作者 World 是单线作品正史；RP 有 sibling 和反事实分支，采用语义不同。
- `require_active_project()` 默认只接受 `project_kind=author`；让 interaction 项目直接写 World 会
  削弱当前硬隔离。
- 作者 `CoreEntity` 的 candidate/canonical/Canon head 与 RP “当前选中发展中已经发生”不是同一状态机。
- RP 事实写回作者对象会污染正史，复制作者对象又会产生版本漂移和删除难题。

优化后结论：

- 拒绝直接复用作者表作为 RP 写入库。只允许通过 ADR-0018 的冻结 source revision 只读消费
  版本化作者对象投影；RP 增量由 interaction 拥有。

### 4.3 路线 C：每个分支复制一套完整对象库

优点：

- 查询直观，每个分支都能得到一份当前完整状态。

质疑：

- 分叉越多，前缀对象被重复复制越多；切换和回滚需要维护大量同步状态。
- “分支”不是稳定用户对象；任意历史节点都可继续形成新 sibling，提前物化全量库会产生写放大。
- 复制后的对象状态仍要证明来自哪些消息，不能替代 path hash 和原始节点。

优化后结论：

- 拒绝“每个 sibling 一套物理库”。每个旅程只拥有一个 append-only 增量集合；对象变化锚定消息
  节点或分段范围。读取某分支时沿当前 ancestry 过滤和折叠，自然复用共同前缀。

### 4.4 路线 D：压缩 + 分支锚定对象覆盖层

优点：

- 回顾处理叙事连续性，对象增量处理精确状态，各自责任清楚。
- 冻结作者对象不复制，RP 原创和变化不写回正史。
- 分支通过不可变 ancestry 和 delta 重放，不需要复制整库。
- 对象增量可按 query 选择性注入，不让完整对象库常驻 Prompt。

质疑：

- 同一事实可能同时出现在总回顾、分段概要和对象增量，形成冲突。
- LLM 从文学文本抽取结构化变化仍会误判；错误对象状态可能比遗漏更顽固。
- 新 schema、重放、纠正和索引会显著增加实现成本。

优化后结论：

- 采用为目标方向，但首期不建完整对象平台。对象覆盖层必须是**派生、可重建、带原始节点证据、
  分支有效性可计算**的窄层；用户修正和原始路径始终拥有更高优先级。

## 5. 目标记忆模型

### 5.1 五层，而不是一张“万能记忆表”

| 层 | 当前/候选承载 | 责任 | 是否事实源 |
|---|---|---|---|
| L0 原始旅程 | `interaction_message_nodes` + branch selections | 用户实际看到、停止保留并选择的故事路径 | 是，RP 已发生内容的审计源 |
| L1 工作记忆 | 活动 overview + 未覆盖原始尾部 | 当前局面、角色、开放线索和近期高保真连续性 | 否，可纠正派生 |
| L2 情节记忆 | path-valid summary segments | 可检索的相关往事、关键转折和旧线索 | 否，可重建派生 |
| L3 对象覆盖层 | 候选的 interaction-owned memory deltas | RP 新对象及对象/关系/位置/知识/物品状态变化 | 否，可重放派生 |
| L4 原作基础库 | 冻结 source revision 的对象目录、知识和原文证据 | 截止剧情点前的原作事实与身份边界 | 是，只读来源证据 |

下一次故事编译不是把五层全部拼接，而是：

```text
硬规则与事实优先级
  + 当前手工/自动总回顾
  + 与本轮相关的少量历史分段
  + 当前选中路径有效、与本轮相关的对象覆盖项
  + 截止点前、与本轮相关的冻结原作资料
  + 尚未覆盖的最近原文与当前输入
```

### 5.2 完整 RP 对象视图

```text
RPObjectView(selected_path, source_revision) =
    FrozenSourceProjection(source_revision, progress_anchor)
    ⊕ Fold(PathValidInteractionDeltas(selected_path))
```

其中 `⊕` 不是数据库 merge：

- source 对象保持冻结版本；版本内 `reference_key` 作证据，跨允许升级的稳定身份由
  旅程 + source project + 内部 `target_id` 的服务端句柄表达；
- RP 变化只覆盖本旅程当前分支的派生状态，不修改 source；
- 原创人物、地点、物品和势力在首个有效 `create` 安装时使用服务端分配的
  interaction-local key；模型的临时句柄不直接持久为 ID；
- 分支切换后重新计算投影，不批量改写 delta；
- 未绑定 source 的旅程只有 interaction-local 对象覆盖层。

### 5.3 首批对象范围

只保存会影响后续叙事选择的长期状态：

- 人物/身份：稳定名称、别名、身份、能力边界、受伤/失踪/死亡等持续状态；
- 物品：持有者、位置、消耗/损坏/丢失等持续状态；
- 地点：当前可达性、占领/毁坏/封锁等变化；
- 关系：持续的人际、阵营、主从、敌对、承诺或知识关系变化；
- 开放事项：明确承诺、债务、长期目标和未解决线索；
- 事件：会改变上述状态或成为后续因果依据的关键事件。

不保存：普通路人、无后果道具、单次环境描写、纯修辞、未揭露幕后真相、模型推测、被用户拒绝
的 sibling、技术失败残段和行动建议。

### 5.4 对象身份、基础事实与 RP 变化的精确合成

| 来源 | 旅程内身份 | 可见条件 | 可作为 base 的内容 | RP 可做什么 |
|---|---|---|---|---|
| 冻结 source | 由 journey/source/`target_id` 确定的 server handle | 出现位置不超过 progress anchor，且未被 excluded | 稳定身份、名称/可用别名；只有已确认、读者可见、截止点前事实/关系 | 追加本旅程状态、关系、位置、物品、知识或 RP 别名变化；不改 source |
| RP local | 首个 path-valid `create` 安装时分配的 server key | `create` 的 effective node 在 selected ancestry，且 authority lineage 有效 | 该 `create` 的最小身份事实 | 应用当前 ancestry 上的后续 operation |
| 纯模型知识 | 无 source 身份 | 不适用 | 不是冻结 base | 若当前故事有原始节点证据，只能创建 RP-local 对象；不得伪装为 source |

source 对象的不可覆写核心是来源身份、基础名称/类型、source revision/provenance 和未达截止点的
不可见性。“原作中活着、RP 中后来死亡”不修改 base，而是当前 path 上的 `set state.life_status=dead`；
切换 sibling 后按 ancestry 折叠得到各自结果。

首版绑定算法：

1. 编译器先从截止点可见、未排除的 source handles 与当前 ancestry 的 local `create` operations
   构建 allowed candidates；Prompt 只给这一次调用内的 opaque candidate refs，不给持久 UUID/object key。
2. 名称/别名只做归一化精确候选召回，entity type 只用于缩小候选；它们不单独证明 identity。
3. 已冻结 source ambiguity 或后续明确用户决议可指定一个 candidate；否则候选为 1 才可绑定，
   候选大于 1 时 delta 不可用，候选为 0 只在有明确长期对象证据时声明 `new`。
4. `new` 只是本次结构化输出内的临时句柄。服务端在 CAS 有效安装时分配 local key，
   同一输出中的 relation/state operations 再统一重写为该 key。
5. 关系 operation 的两个端点都必须在当前组合视图中可见；任一端点只存在于 sibling、
   excluded/future source 或失效 derivation 时，整条 operation 不可用。

“完整对象库”是可查询的逻辑视图，不是每轮全量 Prompt。故事编译仍只取当前人物/地点、
开放事项和 query 相关的少量对象与关系。

### 5.5 手工回顾修正后的结构化恢复生命周期

目标流程不是让普通用户维护对象字段，而是复用当前七区回顾保存动作：

1. 用户基于冻结 base 保存完整七区回顾；保存成功后该 manual revision 立即成为 overview 权威。
2. 服务端比较冻结 base 与提交 payload，确定发生文本变化的 section；不要求浏览器新增
   `changed_sections` wire，也不相信调用方自行声明影响范围。
3. 在同一 manual authority 下立即建立全局旧投影 barrier。编译继续使用 manual overview、raw tail
   和不可变 source identity/provenance；旧 automatic facts 与可变 source base facts 暂停注入。
   不可变 source identity 不因一次自然语言编辑被重绑；故事也不被后台整理阻断。
4. 后台 `manual_reconcile` 只读取旧/新七区文本、保存时冻结的当前有效 structured projection 及其
   provenance，不默认回放整条 raw path。候选使用 call-local opaque refs；可按固定 object batch
   分批，但所有候选必须有 disposition，不能用 section 名称跳过一批。
5. 对每个旧候选强制输出 `keep/suppress/replace/uncertain`，并从新 manual 文本提取必要的新事实；
   服务端逐项重验候选成员、对象端点、path、source 可见性和 manual revision。
6. 校验通过的 batch 先作为私有 task checkpoint 保存；只有全部候选、关系依赖与 hash 一起通过，才在
   一个事务内追加补偿 operations + recovery commit 并解除整个 barrier。缺项、`uncertain`、错绑、
   任务失败或 commit 缺失时仍全量 degraded，不能因任务结束、部分 batch 或模型沉默自动解除。
7. 用户继续写作、切换页面或重进旅程时，已保存 overview 始终有效；后台整理的成功与否只影响
   结构化召回，不回滚用户文本。

以下 section → fact-kind 映射保留为 R2 实验的**成本启发式**，不是生产安全边界：

| 回顾 section | 首版可能受影响的 fact kinds |
|---|---|
| `world_and_start` | identity、location、event；世界规则继续只以 overview 文本表达 |
| `player_character` | identity、alias、ability、state、possession、knowledge、commitment |
| `current_situation` | state、location、possession、relation、event、open_thread |
| `important_people_and_factions` | identity、alias、relation、state、knowledge |
| `key_turning_points` | event、state、relation、possession、knowledge |
| `open_threads` | open_thread、commitment |
| `must_remember` | 当前投影中的全部 fact kinds；无法安全缩窄时等同 structured 全降级 |

七区允许任意自然语言，`world_and_start` 也可能修改人物关系；所以这张表即使偏保守仍会漏掉
跨 section 语义，不能据此让任何旧 fact 继续注入。12.10 只用它测量“如果冒这个风险能省多少”，
不把它作为默认实现。若 projection-wide bounded reconcile 无法在 stale 零复活前提下恢复应保留事实，
就不把 structured layer 发布为已恢复；也不为挽救一个未证明有净收益的层，先建设通用 retroactive engine。

### 5.6 Candidate snapshot、分支归属与原子发布

manual reconcile 的冻结点沿用浏览器已经提交的 edit context，而不是保存发生时的最新选中叶：

| 冻结项 | 语义 |
|---|---|
| `manual_revision_id` | 本次作者文本权威与 recovery root |
| base leaf + base path hash | 作者打开编辑器时实际看见的分支前缀；未看见的新 tail 不属于本次修正输入 |
| base overview revision/authority | 新 manual revision 从哪份已见回顾 rebase |
| source revision + `source_context_epoch` | 本次可见 source identity/mutable base；变化后整次 reconcile stale |
| candidate compiler/schema version | 定义 active projection 的折叠规则；版本不兼容时重建，不复用旧 hash |
| candidate snapshot hash | 按稳定排序对 source mutable candidates 与 path-valid operations 做 canonical hash |
| derivation root | 由上述字段服务端确定，用于 task retry、batch 分组和最终安装幂等 |

时间线：

1. manual save 锁 journey，验证现有 edit-context CAS，以 base leaf 的 ancestry 重建旧 candidate view，
   写入 manual revision 与 barrier root，再推进现有 `overview_epoch`。更早的 delta finalizer 要么已在锁前
   提交并进入 candidate hash，要么锁后发现旧 epoch 而 stale。
2. 保存期间已经新增但作者未见的 tail 不进 candidate snapshot；它继续由 manual overview descendant
   的正常 summary/delta 路径处理，避免被旧文本误判为应删除。
3. worker 可在无长事务下重建同一 candidate hash并调用模型。超过硬预算才确定性分批；批结果只作
   私有 checkpoint，不改变 Prompt 可见 projection。
4. finalize 重新取得 project/task lease fence 与 journey lock，按 manual anchor 加载精确 ancestry，重验
   path hash、manual authority、source epoch、candidate hash、schema 和 derivation idempotency。
5. 全部 disposition 与 relation 依赖通过后，在一个事务内追加补偿 facts 与 recovery commit；只有该
   commit 可解除当前 branch 上的 barrier。零 fact 变化也必须有 commit，不能用“没有 row”猜成功。
6. 完成时用户可以已经沿原分支继续写，也可以正在 sibling；只要冻结 anchor/path 仍存在，结果仍可
   安装为该历史分支资产。编译器只按当前 selected ancestry 选择 barrier/commit，绝不按完成时 selection。
7. source epoch 变化、同 anchor/path 出现更晚 manual revision、candidate hash 不同、任务 lease 丢失或
   journey 不再 active 时失败关闭。自动重试只能用同 derivation root；新权威需要新任务。

对象折叠不用数据库写入时间决定剧情顺序：source base 位于旅程前置位置；fact operation 按 selected
ancestry 中的 `effective_node_id` 排序，同 node 再按明确 authority/operation ordinal。manual reconcile
写入虽可能晚于新 tail，其有效位置仍是 manual anchor；后续节点有明确原始证据的真实状态转移可以
胜出，回头声称“更早其实不是这样”的 retrospective contradiction 不能只凭安装更晚覆盖作者修正。

### 5.7 单一 Interaction Prompt Pack 与预算执行

当前 `compile_story_messages()` 直接按消息顺序拼接，`estimate_input_tokens()` 再对完整结果做字符估算。
目标不是另建通用 Context 产品，而是在 interaction 内先形成一次调用专属、不可持久当真相的最小 IR：

| section | 预算语义 | 渲染位置/说明 |
|---|---|---|
| `hard_rules` | 必需；不可裁剪 | 第一条 system；稳定前缀 |
| `manual_overview_required` | 必需；用户修正与 `must_remember` 不静默裁剪 | hard rules 后；自然语言权威 |
| `raw_tail_current` | 必需；超限先整理，不从头截断 | 最后按原 role 渲染，保留最新 user 位置 |
| `required_source` | 玩家 identity、pinned 与 cutoff guard 必需；放不下则 blocker | source data block 的必需部分 |
| `active_state` | 独立有界槽：open threads、query-relevant object facts | overview 后；只渲染当前 winner |
| `episode_evidence` | 独立有界槽：高置信 segment 命中后的原始 node/自然段 | 明确标为过去事件数据 |
| `source_optional` | 独立有界槽：query-relevant source objects/excerpts | 低于旅程历史；仍由 Evidence 可见性门禁 |
| `segment_index` | 低成本补充槽；已有原文回读时不重复同一 segment summary | 只作定位/粗粒度往事 |
| `rejected_variant` | regenerate 专属固定小上限 | 不属于历史；在 raw tail 前 |

“分配优先级”与“渲染顺序”分开：raw tail 虽最后渲染，却在任何 optional memory 前预留；source 虽低于
RP 历史权威，也有自己的 required 项，不能被最近若干 segment 挤掉。事实优先级由显式 block contract
决定，不靠离 user 消息更近来暗示。

一次编译流程：

1. 从冻结 project LLM snapshot 取得 server capability profile，计算
   `hard_input = min(verified_input_ceiling, context_limit - output_reserve - safety_margin)`；未知模型只用
   保守 short fallback。普通用户不看也不调这些值。
2. 先构建 `hard_rules + manual overview + raw tail/current + required source + request-local control` 固定成本。
   固定成本超过 compaction trigger 时先走现有确定性 summary workflow；整理后仍超过 hard input 则
   fail-closed，绝不调用 provider 的 head truncation。
3. 用“最新输入 + current situation + important people + open threads + 最近故事节点”形成一次有界 query；
   先激活 player/pinned/本轮明确名称，再对可见 relation 做**一跳**扩展。低信息“继续”仍有旅程态种子；
   不递归图遍历、不让模型自主发起检索。
4. 各候选源先在本域做 path/source/authority 门禁，再进入独立 slot cap。slot cap 是 capability/eval 参数；
   无候选的额度可回流，但不得让一个大 source packet 或大量近期 segments 吞掉其他槽。
5. 先选 segment index，再对高置信项有界回读原始 node。若同一 segment 的原文已进入
   `episode_evidence`，渲染时删除它的 summary，只在 trace 合并 provenance。
6. P2 结构化层先按 `(object_handle, field/relation key)` 折叠当前 winner；同 key 同值只渲染最高权威一次，
   不同旧值只在被检索为历史 episode 时出现。manual overview 是自由文本，首版不做 LLM semantic dedup。
7. 以稳定 section/item 顺序渲染，记录 pack fingerprint、各槽 token、included/omitted ref hashes 与原因；
   不保存完整 Prompt，不新增记忆表。provider cache usage 只作成本指标。

P1 不解析 Evidence 已渲染的 `SOURCE_REFERENCE_DATA` 来猜对象字段；先把它当一个带 `token_count` 的 source
section，并给 `compile_interaction_story_context()` 一个由总包剩余额度导出的可选 budget。只有 P2 的
source+overlay 去重在 eval 中确有收益，才把 Evidence contract 加性扩展为 typed items；不得解析 Markdown
建立隐式 wire。

### 5.8 Bounded raw-prefix reducer 与覆盖推进

同一个 reducer 服务 16K 周期整理和 Prompt Pack 紧急超限，区别只在触发原因与本轮最大 passes：

1. **冻结输入**：读取 attempt 的完整 `context_node_ids/path_hash`、当前 overview authority/source snapshot
   与 capability profile；选出 selected ancestry 上最新兼容 overview revision。不能只取 promoted head，
   也不能跨 manual barrier 选更远旧 automatic revision。
2. **保护后缀**：从 leaf 向前保留 profile 决定的近期 token 目标，并确保包含当前 `response_to`、其必要
   user/assistant 对、setup boundary、continuation partial 和 request-local regenerate 控制。节点不拆开。
3. **确定 prefix**：compressible range 是 overview coverage 之后、protected suffix 之前的连续 nodes。
   若为空而 required Prompt 仍超限，直接 blocker；绝不摘要当前 user input 或从头截断。
4. **选择 chunk**：从 compressible range 最老端按 whole node/完整对话节拍装入
   `summary_input_ceiling - overview - output reserve - margin`。single old node 自身放不下时首版 blocker，
   不预建 paragraph-level partial-node checkpoint；真实用例出现后再重开。
5. **模型折叠**：输入只含当前兼容 overview + 本 chunk raw nodes；segment summaries、source packet、对象
   facts、sibling 和训练知识都不进 reducer。pre-manual raw 需标 `predates_manual_baseline`，不得恢复被作者
   删除的当前值。
6. **验证缩减**：令 `before = old_overview + chunk_raw`，`after = new_overview`；除了 schema/authority/evidence
   门，还要求 `after <= before - min_savings`。`min_savings` 是冻结 eval/profile 参数；不通过则不写 segment/
   revision，返回 `compaction_non_reducing`。
7. **prefix 安装**：prepared full path 继续做 selection/epoch stale fence；segment `path_hash/end_node_id` 与
   overview `anchor/coverage` 改为 chunk-end prefix。现有 full-leaf pass 是该规则的自然特例，不改 DB schema。
8. **幂等复用**：同 `(journey, prefix_path_hash, end_node_id)` 已有 episode segment 时不新建；若 exact range
   相同直接复用，若旧 segment 覆盖更大/不同 start，只保留旧 episode index并记录本 pass raw range，仍可
   新建当前 authority 的 overview revision。segment lineage 不冒充本次 overview 来源。
9. **继续或退出**：commit 后重新构建 required Prompt Pack。已低于 compaction trigger 就恢复同一 story
   attempt；否则处理下一 chunk，直到达到冻结 pass/cost/time 上限。每次 pass 都是独立 lease-fenced 短事务。
10. **近期保真**：后台 periodic summary 也保留近期 raw suffix，避免每到 16K 就把最近语气、对话节奏和
    当前场景全部只剩概要。due 判断只计算可压缩 prefix，不让受保护 suffix 触发无限整理。

不建立 map-reduce segment summary 树。overview revision 已是 rolling reducer state，raw message tree 是重放
源，segment 是索引；三者足够。只有 single-node 超限在真实数据中出现且用户无法换用合适模型时，才设计
node 内完整自然段 checkpoint。

### 5.9 `rp_long_memory` 最小可执行规格

首个实现只触碰五个已有位置，不建 package/runners 层：

| 文件 | 作用 |
|---|---|
| `backend/evals/rp_long_memory.py` | strict schema、模板渲染、A–E reference pack、offline/model/review CLI、报告 |
| `backend/evals/tests/test_rp_long_memory.py` | schema、确定性、隔离、盲化、atomic report 的窄测试 |
| `backend/evals/datasets/baselines/rp-long-memory-v1.jsonl` | 旧 exact-string contract，仅保留 compile 回归 |
| `backend/evals/datasets/baselines/rp-long-memory-v2.jsonl` | 当前 oracle-only semantic contract；无作品原文 |
| `backend/evals/datasets/README.md` | 数据边界、命令、非声称与本地 artifact 位置 |
| `Makefile` | 一个离线 `eval-rp-long-memory` 入口；付费/盲评阶段用显式 module CLI |

不修改 `evals/schemas.py`、`EvalSuite`、readiness、freeze、review 或 report 通用链；P0 runner 稳定且第二个
独立 consumer 需要时再评整合。

#### 5.9.1 JSONL case 最小模型

每行 `extra=forbid`，至少包含：

- identity：`schema_version=rp-long-memory-v1|v2`、`case_id`、`scenario_group_id`、`split=dev|test`、`seed`；
- length：`fact_distance_beats`、`target_history_tokens`；
- `initial_facts` 与 `events`：稳定 fact/object keys、beat、parent event、branch、role、`template_id/values`、
  封闭 operations；消息正文由代码模板渲染；
- selection：`selected_leaf_event_id`、明确 sibling/future sentinels；runner 从 parent DAG 算 selected ancestry，
  不接受 fixture 自报 selected path；
- `manual_revisions`、可选 synthetic `source_versions/identity_ambiguities/delta_batches`；
- artifacts：fixture overview、segments、raw rehydration ranges、gold overlay operations；它们只供对应 arm；
- `probe`：严格问答 protocol 的 probe ID/expected value/allowed unknown；
- `oracle`：required/forbidden facts、expected/forbidden ref hashes、current winner、coverage 与 hard sentinels；
  v2 另含不会渲染给模型的 accepted values、必含语义组、矛盾词和 hard 标记。

同 `scenario_group_id` 只能属于一个 split；parent 必须先出现、DAG 无环、selected leaf 可达、operation 引用
对象已创建或 source-visible。模板字典与 canonical JSON 序列化都带 version/hash；相同 dataset bytes + template
version + seed 必须生成相同消息、node IDs、fact keys 与 pack candidates。

#### 5.9.2 三个子命令

```bash
python -m evals.rp_long_memory compile DATASET --split dev --output REPORT.json
python -m evals.rp_long_memory model DATASET --split dev --novel-id ID \
  --allow-paid-model --runs 1 --output-dir evals/artifacts/rp-long-memory
python -m evals.rp_long_memory review MODEL_REPORT.json REVIEWS.jsonl \
  --arm-map ARM_MAP.json --output FINAL_REPORT.json
```

- `compile`：严格 load → materialize → A–E pack → hard assertions → atomic report；无 DB、网络、Key 或模型，
  是 Make/CI 唯一默认入口。
- `model`：先要求同 dataset 的 compile-ready 结果；一次冻结 project provider/model/profile，使用 production
  `story_request` + streaming framer 生成盲化 story candidates，并用独立 eval-only structured fact probe
  测 memory use。所有 arms 同 profile/params/run index，执行顺序由 case/run hash 决定。没有显式付费标志、
  model 不匹配、cache-only miss 或 project 非有效 interaction scope 时调用前失败。
- `review`：reviews 只含 opaque candidate ID 与 0–4 全 rubric 分数/严重 spoiler；arm map 单独保存，评分完成
  后才揭盲。沿用 `RUBRIC_DIMENSIONS`，但新模块实现 A–E 多臂配对，不改变旧 on/off summarizer。

`model` 不用 Codex CLI 代替产品 provider；Codex executor 的系统/工具外壳不是 RP SUT。它通过现有
project facade 获取当前已验证账户连接，不读取 env Key、不写项目业务数据；`novel_id` 只作为 owner/credential
scope，要求调用者使用可丢弃 interaction project。输出和 cache 只写既有 ignored dirs。

#### 5.9.3 Runner 阶段与报告

离线阶段固定顺序：`dataset_integrity → materialization → branch/source/authority → arm_pack → budget/dedup →
compaction/recovery assertions`。任何前序硬失败后仍可记录后续 `skipped_due_to`，但不能把缺失算通过。

模型阶段先跑 fact probe，再生成 story candidate；probe 只验证 pack 中事实是否被使用，不代表叙事质量。
Story 输出只做 exact safety sentinel/code assertions，内容质量交给盲评。首版没有 LLM judge、自动调 Prompt、
自动选 model 或自动重跑失败 arm。

报告顶层至少包含：dataset/template/compiler/prompt/profile hashes；repo source-file hashes；split/case/arm/run；
每阶段 started/completed/error；每 case pack included/omitted ref hashes、token sections、assertions、primary failure；
模型 usage/cache/latency；完整 metric inventory 的 `available/blocking/threshold/passed/reason`；blind mapping hash、
review calibration和 `quality_claim_allowed`。正文只在 ignored candidate/review artifact，主报告保存 hash/长度。

写入使用同目录 `.<name>.tmp → replace`；成功报告写完才返回。exit `0` 表示请求的 stage 完整且其 blocking
门通过，`2` 表示形成了完整 non-ready 报告，schema/config/runtime exception 保持普通非零错误。离线 compile
成功不要求 model/review metrics available，但必须明确其未运行；model/review stage 缺证据则不能 exit 0。

## 6. 决策台账：每项决定的质疑与升级

### MEM-DEC-001：混合路线是目标，压缩路线先行

- **状态**：方向已采用；结构化 schema 未批准。
- **初始决定**：使用回顾压缩与对象覆盖层组合。
- **质疑**：混合方案可能只是把两套复杂度叠加。
- **升级**：按缺口分期。P0/P1 只补评测、query 和分段召回；对象状态错误仍达到门槛才启动 P2。
- **重开条件**：压缩 + 分段召回在长程评测中已稳定满足对象状态连续性，则取消结构化层。

### MEM-DEC-002：原始选中路径是 RP 审计源

- **状态**：采用。
- **初始决定**：任何派生记忆都不能覆盖或删除原始节点。
- **质疑**：每次都回读原始路径会过慢、过贵。
- **升级**：正常生成不回读全部原文，只用 overview/tail/retrieval；原始节点用于重建、纠错和命中后的
  有界范围回读。
- **淘汰条件**：无；这是分支、纠正和可审计性的底线。

### MEM-DEC-003：一个旅程一个增量库，分支靠 ancestry 过滤

- **状态**：方向采用；物理 schema 待确认。
- **初始决定**：不给每个 sibling 复制完整对象库。
- **质疑**：共享增量集合是否会让兄弟分支互相污染。
- **升级**：每条 delta 保存来源节点/分段起止、path hash 和覆盖 fingerprint；编译时计算当前路径各
  anchor 的 prefix hash，只消费匹配项。晚到 delta 与 overview 使用同类 epoch/CAS fence。
- **重开条件**：真实 PostgreSQL 压测证明 ancestry 重放无法满足读取延迟，再考虑有版本指纹的分支投影缓存；
  仍不复制事实源。

### MEM-DEC-004：作者对象是只读基础库，不复制、不写回

- **状态**：采用。
- **初始决定**：冻结 source revision + RP overlay 形成组合视图。
- **质疑**：作者项目归档、正文更新或对象被纠正后，旧旅程是否失效。
- **升级**：沿用 ADR-0018：旅程冻结 source revision；新版只提示显式升级，旧版不自动漂移。来源归档时
  可读但停止新生成；永久删除仍由引用门禁阻止。
- **淘汰条件**：无；跨 owner、跨 `novel_id` 泄漏或 RP 写回正史属于立即停止风险。

### MEM-DEC-005：不持久化 provider opaque compaction 作为业务记忆

- **状态**：采用。
- **初始决定**：模型中立的 overview/segment/delta 承担业务记忆。
- **质疑**：provider 原生 compaction 可能比自建概要保真度更高。
- **升级**：可在单次 provider session 内作为不可依赖的传输优化实验，但必须能在关闭该能力后只凭模型中立
  资产继续；不能进入导出、分支判定或事实优先级。
- **第二轮质疑**：OpenAI Responses 还提供自动 context management 和 `truncation=auto`；若直接开启可少写
  预算代码。
- **第二轮升级**：opaque compaction 仍只允许做 provider-local continuation 实验；`truncation=auto` 会从
  对话开头丢 item，RP story 请求必须保持显式 fail-closed/自有整理，不能静默交给 provider 删除早期规则。
  cache/compaction item 不进入 Prompt Pack fingerprint 的业务事实部分。
- **重开条件**：只有全部已支持 provider 提供可迁移、可审计、分支可裁剪的共同契约，才评审业务化。

### MEM-DEC-006：先召回现有分段概要，不先建向量索引

- **状态**：采用到 P1。
- **初始决定**：从 path-valid segments 中按实体名称/别名命中、新近度和 open-thread 词面选择少量候选，
  使用独立小预算注入“相关往事”；`3–5` 只作 eval 参数，不是产品常量。
- **质疑**：中文无空格、代词和隐喻可能让简单词面召回漏掉真正相关段落。
- **升级**：P1 同时保留最近有效分段，并用 overview 的重要人物/开放事项扩展 query；segment 先作索引，
  命中后可回读有界原始节点。候选数和最终 token budget 分开；只在长程评测显示词面召回不足时，
  才把 segment 通过既有 Evidence facade 建模为 interaction 私有索引项。
- **重开条件**：召回精度不足，且误召/漏召能被固定夹具稳定复现；不得凭感觉新增 embedding。

### MEM-DEC-007：source 检索 query 必须带当前旅程态

- **状态**：采用到 P1。
- **初始决定**：不再只用最新用户输入。
- **质疑**：把总回顾全部拼入 query 会让检索过宽，反而拉入不相关原作资料。
- **升级**：只使用有界的“最新输入 + 当前局面 + 重要人物/势力 + 开放事项 + 最近一个故事节拍”；
  每部分有字符上限，忽略项和剧情截止点仍在检索前过滤。
- **验证**：加入“继续/看看情况/我等着”类低信息输入夹具，证明仍能命中当前地点与人物资料且不越过截止点。

### MEM-DEC-008：结构化变化与分段概要同一整理调用产生

- **状态**：候选，P2 前需评测与 Prompt/schema 设计确认。
- **初始决定**：扩展 `interaction-summary` 结构化输出，额外返回对象、关系、位置、知识、物品、承诺和
  open-thread delta；不增加第二次 LLM 调用。
- **质疑**：概要模型可能为了结构完整而编造对象或状态；同一调用失败会同时影响两种资产。
- **升级**：
  - delta 只能引用本次 segment 节点范围；
  - 每个非空变化必须提供可在原始节点中精确定位的 evidence range/hash；
  - 无证据或歧义项可留在自然语言 segment，不进入可用对象覆盖层；
  - overview 成功而 delta 校验失败时，仅丢弃 delta，不判废 overview；
  - 最近原始尾部在进入整理前已经覆盖即时连续性，因此延迟到分段边界抽取可接受。
- **重开条件**：如果单次结构化输出显著降低 overview 质量，则拆成用户授权的后台窄 step；仍不得自治选工具。

### MEM-DEC-009：派生对象不自动获得比用户修正更高的权威

- **状态**：采用。
- **初始决定**：对象 delta 是可重建投影，不是第二份旅程正史。
- **质疑**：即使 Prompt 声明优先级，错误结构化状态仍可能反复强化旧事实。
- **升级**：放弃“按名称猜测哪些字段被纠正”。手工 overview revision 成为对象派生层的 lineage barrier：
  只有 `based_on_overview_revision_id` 可证明从当前手工 revision 继续派生的 delta 才能注入；旧自动 delta
  暂停消费，故事仍以手工 overview + raw tail 继续。后续整理在手工基线上形成新 delta。界面不要求
  普通用户逐字段修对象库。新 delta 能继续安装不等于 barrier 之前的完整对象投影已恢复；
  完整 recovery 见 MEM-DEC-033。
- **权威澄清**：`manual_reconcile` operation 是“经用户保存动作授权、由系统从手工文本派生”的投影，
  `producer` 不能冒充 `user`。作者实际写下的 manual overview 文本始终高于 reconcile 派生结果；二者
  冲突或 provenance 不完整时丢弃派生项。
- **验证**：固定夹具“我从未告诉艾琳真相”必须阻止旧 `艾琳已知情` delta 再进入 Prompt。

### MEM-DEC-010：预算按模型能力档案计算，普通用户不可调

- **状态**：P1 首版已实现；DeepSeek 已校准，其他模型仍走 short fallback。
- **初始决定**：`context_window`、正常目标、整理阈值、硬上限、输出预留和估算余量属于 provider/model
  capability profile。
- **质疑**：供应商上下文规格和 tokenizer 会变化，硬编码仍会漂移。
- **升级**：能力档案带验证日期/来源，真实调用记录 estimator/provider usage 偏差；未知模型使用保守 fallback，
  不根据前端提交值放宽门禁。
- **第二轮证据**：当前 provider templates 同时包含 8K/32K/128K 与更长模型，官方当前 DeepSeek V4/Kimi K3
  又达到 1M；固定 750K 只对已校准大窗口模型可能安全，热切换到短窗口会在应用门禁前撞 provider。
- **第二轮升级**：`hard_input = min(verified_input_ceiling, context_limit - output_reserve - safety_margin)`；
  compaction trigger 与 normal target 也由同一 profile 给出。unknown model 只进入保守 short fallback，
  不继承上一个模型的档案；profile 是服务端受审计数据，不接受浏览器自报窗口。
- **验证**：各 provider 至少覆盖正常、紧急整理、hard fail-closed 和热切换；无精确 usage 时明确标记未校准。
- **实现证据**：`infrastructure.llm.capabilities` 是唯一 registry；DeepSeek 档案冻结官方 1M context、
  400K verified input ceiling、256K normal、360K compact、256K summary ceiling 与输出/margin。
  unknown/legacy 分别使用带状态的 short fallback，不接受项目或浏览器覆盖。

### MEM-DEC-011：先建立长程评测，再声称“记得更好”

- **状态**：采用。
- **初始决定**：技术门禁与内容质量证据分开。
- **质疑**：合成回放可能无法代表人物质感和真实长旅程。
- **升级**：确定性夹具验证泄漏/覆盖/重放，盲评验证连续性与人物表现，最后再做真实用户观察；三者不能互相替代。
- **对外口径**：在盲评和用户试用前，只能说“增加了可召回/可校验的记忆来源”，不能说“长期不出戏”。

### MEM-DEC-012：概要是索引，原始节点才是可回读载荷

- **状态**：采用到 P1。
- **初始决定**：相关分段命中后直接注入分段概要。
- **质疑**：这只能重新注入已经压缩过的文本，无法恢复概要遗漏；与“修复慢性失忆”的目标矛盾。
- **升级**：两阶段读取：先用短 segment summary 定位范围，再在该范围内按名称/别名、开放事项和当前
  query 选择 1–3 条完整原始消息或自然段。原文以“过去事件证据”的不可信数据块注入，不伪装成当前
  user 指令；必须仍在 selected path。早于当前手工基线的项只能作为带
  `predates_manual_baseline` 的历史 episode，不能覆盖手工当前状态。
- **第二轮质疑**：“名称附近字符窗口”可能切掉否定、不确定性或说话角色；把历史用户文本
  拆成无来源短句也会放大历史指令提权风险。
- **第二轮升级**：选择器先返回完整 node ID；若单 node 超出回读 cap，只在该 node 内选完整
  自然段，并保留 node ID、role、char offsets 与前后文截断标记。对话意义依赖一问一答时，
  在预算内成对取 selected user node + selected assistant child。不跨 node 拼接“名称附近窗口”。
- **预算**：原始回读独立 cap；无精确命中时只用 segment summary，不把整段约 16K token 原文重新塞回。
- **验证**：埋入只存在于原文、故意从 summary 省略的细节，B 组失败而 rehydrated 组应命中。

### MEM-DEC-013：对象覆盖层保存事实增量，不保存可变对象快照

- **状态**：方向采用；P2 schema 未批准。
- **初始决定**：为旅程维护一个“对象库”。
- **质疑**：若物理上保存当前对象行，分支切换、历史重抽和手工纠正都会要求回滚/复制这些行。
- **升级**：对象身份稳定，字段/关系变化 append-only。投影器按当前 path position 顺序应用
  `create/set/unset/add_relation/end_relation` 等封闭 operation；分叉前自然复用，分叉后互不覆盖。
  可选 projection cache 只能在真实性能门槛触发后增加，永远不是事实源。
- **验证**：同一对象在 A 分支持有钥匙、B 分支丢失钥匙；来回切换必须得到各自状态且零物理复制。

### MEM-DEC-014：RP 有两个时间轴，但首期不用双时态数据库

- **状态**：采用。
- **初始决定**：参考 temporal graph，为每项事实保存 `valid_at/invalid_at`。
- **质疑**：墙钟、故事内日期和分支顺序并不等价；一个全局 invalidation 会错误废弃 sibling 仍有效事实。
- **升级**：首期只保存 `effective_node_id/path_hash`（叙事顺序）与 `created_at`（审计时间）。故事内“昨晚、
  三年后”等时间作为证据化 value，不用于跨分支全局失效。某字段当前值由 selected ancestry 上最后一个有效
  operation 决定。
- **重开条件**：真实用例需要查询“故事内某日期当时的对象视图”，且节点顺序无法表达时，再设计叙事时间字段。

### MEM-DEC-015：记忆选择采用保留槽位，不先采用单一加权总分

- **状态**：采用到 P1/P2 eval。
- **初始决定**：按 relevance + recency + importance 排名后取 top-k。
- **质疑**：最近内容已由 raw tail 保真；统一分数容易让近期低价值段挤掉旧承诺、手工记忆或能力边界。
- **升级**：先分槽位并统一执行预算：`manual/required → open thread → active object facts → relevant episode →
  recent valid segment`。槽内使用稳定顺序和有限相关性评分；候选条数不等于最终 token 配额。
- **第二轮质疑**：上述次序漏掉 raw tail 和 required/optional source，也容易被误解成消息渲染顺序。
- **第二轮升级**：先从总预算扣除 hard rules、manual/required、完整 raw tail/current input 与 required source；
  剩余额度再分 `active_state / episode_evidence / source_optional / segment_index` 独立 cap。raw tail 虽最后
  渲染却先预留；一个槽空出的额度才可回流。完整规则见 5.7。
- **重开条件**：固定回放证明槽位策略稳定漏召，而可解释多因子排序显著改善时，再引入可版本化权重。

### MEM-DEC-016：branch memory 不使用 agent 级共享可变块

- **状态**：采用。
- **初始决定**：参考 Letta，用一个旅程级 core memory block 供所有分支共享。
- **质疑**：fork/sibling 共享最新可变 block 会把后发生的事实回流到旧分支。
- **升级**：只共享不可变 source base 与分叉前 delta；当前工作记忆由 selected path + overview lineage 编译。
  不存在一个可被任意 sibling 原地修改的旅程级“当前真相块”。
- **淘汰条件**：无；这是分支隔离的直接结果。

### MEM-DEC-017：不引入图数据库或自治记忆 Agent

- **状态**：采用到当前范围。
- **初始决定**：参考 Graphiti/Letta，建设 temporal graph 和能自行写入/搜索的 memory agent。
- **质疑**：这会新增基础设施、自治工具权限和第二套检索治理，而单旅程对象变化可由 PostgreSQL delta 重放表达。
- **升级**：只借 episode provenance、事实历史和分层预算；抽取仍由确定性 summary workflow 编排，检索由
  interaction service 选择并经 owner/novel/journey/path/预算门禁。
- **重开条件**：PostgreSQL 方案在已测规模下无法满足关系/时间查询，而且现有 Evidence facade 也无法承载，
  才能提出新架构 ADR；不得以功能丰富为理由提前引入。

### MEM-DEC-018：“记住这一点”先是手工高权威记忆，不是自动对象编辑

- **状态**：采用到 P1；结构化形态待 P2。
- **初始决定**：点击后让系统自动判断对象/字段并写入覆盖层。
- **质疑**：这会把低摩擦按钮变成一次不可见实体编辑，错误难发现。
- **升级**：P1 只把选中文字与用户补充预填到 `must_remember`，明确保存后生效。P2 若存在 delta 表，再把
  手工记忆保存为 `manual_note` operation，带原始 node/range 且优先于自动 delta；不要求用户选择数据库字段。
- **验证**：保存失败保留草稿；切换 sibling 后只在包含该来源节点的后代路径生效。

### MEM-DEC-019：source 盲评与长记忆回放保持两份窄协议

- **状态**：采用到 P0。
- **初始决定**：直接把现有 `rp_context.py` 扩展成五臂长旅程 runner。
- **质疑**：该模块的当前窄契约是只允许 hash 和 `SourceRangeRef`，且只汇总
  `context_on/context_off` 盲评。塞入合成旅程节点、五臂编译轨迹和对象状态，会同时放宽
  版权安全边界与现有报告形状。
- **升级**：保留 `rp-context-v1` 不变；长记忆使用独立 `rp-long-memory` versioned
  合成协议。提交的 JSONL 只保存结构化事实、事件、模板 ID、seed、位置和 sentinel，
  运行时再用确定性模板生成合成消息。它只复用现有 JSONL 加载错误、指标、校准、
  `available=false` 和原子报告惯例；首版不为此改通用 `EvalSuite`/`DatasetCase`。
- **重开条件**：只有在独立 runner 稳定后确需进入全局 eval 报告，且通用 schema 能在
  不放宽 source 文本禁止的前提下表达该协议，再增加适配。

### MEM-DEC-020：先用 gold overlay 验证架构上限，再评估抽取器

- **状态**：采用到 P0/P2 决策门。
- **初始决定**：D 臂直接调用 LLM 抽取 structured delta，与 C 臂比较。
- **质疑**：D 失败时无法知道是“结构化记忆没有价值”，还是“抽取 Prompt/schema 做坏了”。
- **升级**：五个主对照臂中的 D 先是 `hybrid_overlay_gold`，由夹具事实 operation 直接编译。
  若 gold D 不能稳定优于 C，立即淘汰结构化层，不写抽取器、schema 或 migration。只有
  gold D 过门后，才追加 `hybrid_overlay_extracted` 诊断臂；真实抽取臂也过门才可请求
  P2 存储确认。
- **诊断限制**：`oracle_segment` 与 `oracle_raw_node` 只用来分离选择器和模型失败，
  不是产品臂，不得进入增益声称。

### MEM-DEC-021：`full_raw_reference` 是参照组，不是当然的质量上界

- **状态**：采用到 P0。
- **初始决定**：完整原始路径给模型的质量必然最好。
- **质疑**：超长原文会产生 attention dilution/lost-in-the-middle，也可能超出当前模型能力、
  硬上限或费用范围；它输给压缩臂不能反证压缩更完整。
- **升级**：E 只在能装入同一已验证模型上下文的小/中档运行，作为“无压缩的参照”。
  超窗口时记为 `unavailable`，不是 0 分；E 的好坏都不直接决定 B/C/D 是否上线。

### MEM-DEC-022：“长”同时按事实距离和上下文规模分层

- **状态**：采用到 P0；数值是评测档位，不是产品常量。
- **初始决定**：只使用 20/50/100 个故事节拍区分长度。
- **质疑**：100 个短对话可能远没到整理阈值，而 20 个长回合已经触发多次分段；
  只看回合数无法验证 16K 分段、256K 常规输入和 512K 紧急整理边界。
- **升级**：同时分层：
  - 目标事实到 probe 的距离：20、50、100+ beats；
  - 历史总规模：至少跨过 32K（多分段）、256K（常规边界）和 530K（跨 512K 紧急边界）
    的仓库 `estimate_story_tokens()` 档位。
  首版不做全因子组合；覆盖每个距离和规模档，并至少有一组“多短回合”与
  “少长回合”对照。报告同时记录实际字符、节点、beat 和估算 token，不信任标签。

### MEM-DEC-023：硬不变量与方向性质量指标分开

- **状态**：采用到 P0/P1/P2 上线决策。
- **初始决定**：为所有指标预先拍一组总分阈值。
- **质疑**：无基线方差时的总分是伪精确；更严重的是，高叙事分不得抵消一次兄弟分支、
  未来原作、其他 owner/novel 或历史指令泄漏。
- **升级**：安全与血缘指标是全量 case 的独立硬门，适用分母上必须 100% 正确/
  0 泄漏；事实回忆、盲评、成本、延迟和 cache 使用配对差值。基线前不预设一个“综合
  80 分”；先用 dev/pilot 观察方差，冻结决策规则后再跑 holdout。
- **校准边界**：人工盲评可直接用于决策；LLM judge 只有在现有仓库校准门达到
  Cohen's kappa `>= 0.75` 且 Spearman rho `>= 0.70` 后才可 blocking。未校准分数只作方向性证据。

### MEM-DEC-024：episode segment 与结构化状态推导不共用存储身份

- **状态**：采用为 P2 架构边界；用户已给出条件授权，但评测门尚未允许落 schema。
- **初始决定**：在 `interaction_summary_segments` 上增加可空 `memory_delta_json`，让一次整理的
  概要和对象变化共用一行。
- **现有证据**：segment 已按 `(journey_id, path_hash, end_node_id)` 唯一，这一行标识一段不变的
  故事范围，其 `content` 是派生检索索引。用户可在后续自动回顾已经吸收新 tail 时，仍从
  早先冻结的 overview 基线保存
  手工修正；系统需要在新手工基线下重新推导同一段 tail。
- **质疑**：修改 segment 上的 JSON 会破坏不变性；允许同 path/end 的多个 segment 会制造召回重复；
  在单个 JSON 内积累多个推导版本又会让 lineage、查询和单项失效变成数组内编程。
- **升级**：segment 只保存历史 episode 摘要与范围。若 extracted D 过门，结构化 operation 使用独立
  append-only 记录，同时指向 evidence node/range 与 `based_on_overview_revision_id`。同一 episode 可在新
  手工基线下重新推导，但只有当前 authority lineage 的 operation 可进入投影。
- **第二轮质疑**：当前 summary Prompt 会把“已有总回顾”与新 tail 一起提供给模型，所以 segment
  文本可能含有手工修正前的人物身份或指代解释。“范围唯一”不能推出“旧索引文本永远足够”。
- **第二轮升级**：P1 先幂等复用旧 segment，并将它标为 `predates_manual_baseline` 的非权威索引；
  它只负责定位 raw nodes，不提供当前状态。若 manual-rebase 回放证明旧解释使 selector 稳定漏召，
  再只为 episode index 设计版本化派生文本；该结果也不会恢复 `memory_delta_json` 候选。
- **验证**：固定回放“自动回顾吸收 tail → 用户从旧基线修正 → 同一 tail 重放”；只能有一个
  episode segment，可有两条派生 lineage，且旧 lineage 的 delta 为零注入。
- **淘汰结果**：7.1 的 `memory_delta_json` 候选淘汰；不再等 P2 时二选一。

### MEM-DEC-025：手工回顾是一次 rebase，overview 不等待额外 checkpoint 恢复

- **状态**：overview 路径已实现并有定向测试；structured delta 为 P2 候选规则。
- **初始决定**：用户手工修正后，旧自动记忆全部停用，直到下一个八分段 checkpoint。
- **现有证据**：当前代码使用编辑时冻结的 revision/leaf/path hash；若当前 head 只是该基线的
  automatic descendant，保存仍成功，但 manual revision 从用户真正看过的 base 分叉并保留其
  coverage frontier。随后立即排队 refresh，只吸收 coverage 之后的 raw tail。
- **质疑**：额外等待 checkpoint 会让用户修正后长时间丢失自动记忆，且 checkpoint 目前只是
  provenance 标记，没有增加更强的内容证明。
- **升级**：第一个以 manual revision 为 `based_on_revision_id`、通过同一 path/node list/
  `overview_epoch` CAS 门的 automatic revision，就是 **overview** 恢复点。修正后的新 P2 delta 仍必须
  绑定该 manual base、本次 tail evidence 和安装 epoch；无需为 overview 新增 `memory_generation` 列或等待
  八分段 checkpoint。手工 barrier 之前的 structured object view 是否恢复属于 MEM-DEC-033，不由本条推导。
- **失败降级**：无模型连接、refresh 失败或输出 stale 时，继续使用 manual overview + 完整 raw tail；
  不恢复旧 delta，不阻断故事。
- **实现风险**：同 path/end 的 segment 可能已由用户编辑期间的 automatic descendant 写入。
  手工 rebase 重放同一 tail 时，segment 安装必须幂等复用该 episode，不能触发唯一约束、
  覆写旧行或创建重复召回项。现有定向测试验证基线/tail/CAS，尚未覆盖“segment 已存在”实例。
- **验证**：已有 `test_manual_overview_save_keeps_frozen_coverage_and_absorbs_new_tail`、
  `test_manual_overview_epoch_rejects_late_automatic_summary` 与
  `test_prepare_summary_reads_manual_baseline_and_only_new_tail`；P1 前必须补上述已存 segment 的 PostgreSQL 实例。

### MEM-DEC-026：分支归属、概要覆盖与记忆权威使用三个 frontier

- **状态**：采用；复用现有字段，不新增 schema。
- **初始决定**：使用一个“最新记忆节点”同时判断分支、raw tail 和对象 delta 是否有效。
- **质疑**：手工回顾可以挂在用户开始编辑时的 branch anchor，只声称覆盖更早的节点，并对
  之后的 tail 形成新 authority lineage。一个指针无法同时表达这三件事。
- **升级**：明确三个现有概念：
  1. **branch attachment frontier**：`anchor_node_id + path_hash`，判断这份 revision 是否属于当前 ancestry；
  2. **coverage frontier**：`coverage_anchor_node_id + coverage_path_hash`，只决定哪些 raw nodes 尚未被活动回顾吸收；
  3. **authority frontier**：`based_on_revision_id + source + overview_epoch`，决定哪条 overview/delta 派生链可被编译。
- **历史 segment 规则**：手工修正前的 path-valid segment 仍是 episode 索引，但只能进
  `relevant episode` 槽，不能填 `manual/required` 或 `active object facts` 槽。其回读原文必须标记
  `predates_manual_baseline`，当前状态仍以 manual overview 为准。
- **失败关闭**：如果 P0/P1 stale sentinel 证明仅靠权威标签仍会复活过期事实，先关闭自动
  pre-manual raw rehydration，不用词面猜测“用户只改了哪个字段”。P2 只有在结构化 manual operation
  过门后才可做精确冲突遮蔽。

### MEM-DEC-027：不常态化第二次同模型概要自检

- **状态**：采用到 P0/P1。
- **初始决定**：参考 Gemini CLI，每次 summary 都再调一次同模型，要求找出遗漏并重写。
- **质疑**：这会接近翻倍整理延迟/费用，两次调用还可能复制同一偏差；模型自称“已无遗漏”
  不是外部证据。
- **升级**：生产首版保持一次结构化整理，由 schema/CAS/path/sentinel 做确定性门禁；P0 只在
  `overview_loss` 为主因的 case 上追加 `summary_self_check` 诊断臂。它不进入五个主臂、不自动上线。
- **重开条件**：B/C 仍以 `overview_loss` 为主要错误，且配对 holdout 证明第二次调用在外部
  事实断言上有实用净改善、无新 stale/leak，其费用和延迟也在冻结门内。

### MEM-DEC-028：`reference_key` 是版本证据，不是 RP 对象的稳定身份

- **状态**：采用为 P2 身份边界；编码和 schema 未批准。
- **初始决定**：source-backed delta 的 `object_key` 直接使用冻结 manifest 中的 `reference_key`。
- **现有证据**：`reference_key = hash(manifest_hash, entity_id)`，同一作者对象在新 source revision 中
  会换键；现有旅程升级却使用内部 `target_id` 把玩家、固定和忽略项重映射到新键。
- **质疑**：用 `reference_key` 作对象身份会让允许的 source 升级孤立既有 RP delta；批量改写旧
  delta 又破坏 append-only 和审计。直接把作者 `CoreEntity.id` 暴露给模型/前端也没有必要。
- **升级**：使用两个旅程内 namespace：
  - `source`：服务端由 journey ID + source project ID + 冻结内部 `target_id` 确定稳定 handle；
    具体字符串/UUID 编码留到 P2，首版不建映射表。
  - `local`：服务端在首个 CAS 有效 `create` 安装时分配不变 key；模型只能使用这一次
    输出内的临时 `new` handle。
  source delta 另存创建时 `source_revision_id + reference_key` 作 provenance，但它们不参与稳定身份比较。
- **升级失败**：新 source revision 不再含同一 `target_id`，或该对象在新 anchor 不可见时，
  沿用 ADR-0018 失败关闭并要求新旅程；不按新名称/语义猜测迁移。
- **验证**：同 `target_id`、不同 manifest/reference key 的允许升级必须得到同一旅程 object handle；
  目标缺失时为零猜测重绑。

### MEM-DEC-029：名称、别名和语义相似只召回候选，不自动合并 identity

- **状态**：采用到 P2 eval。
- **初始决定**：同一归一化名称或精确别名命中时，直接把 RP 提及合并到已有对象。
- **现有证据**：source revision 已对一词多对象产生 ambiguity；World 融合也保留
  `keep_separate/needs_review` 并对 canonical alias 施加明确授权门。
- **质疑**：同名人物很普通，类型字符串也可自由；语义相似度会把“兄弟”“伪装”“同型道具”
  误当成同一身份。候选 alias 如果尚未被作者确认，更不能用来不可见地改变 RP 对象归属。
- **升级**：确定性绑定只接受：
  1. 当前冻结 source ambiguity 的明确 resolution；
  2. 已有 RP manual identity decision（P2 后若实际需要）；
  3. 归一化名称/可用别名 + 类型过滤后只剩一个 allowed candidate。
  候选为 0 时可经证据创建 local；候选大于 1 时 delta 失败关闭。模糊/向量分数只可排列诊断建议，
  不得让第一名自动绑定。
- **第二轮质疑**：纯 exact 绑定会漏掉中文代词、称谓和“那位守门人”类指代；但让模型从
  多个 active objects 中猜一个又会把不可验证的 coreference 变成持久 identity。
- **第二轮升级**：候选分两级：`deterministic_bindable` 按上述规则可安装；
  `contextual_candidate` 只供抽取器表达指代建议，默认 `usable=false`。只有新的封闭 coreference
  验证在 holdout 上显著提高连续性且零错绑，才能提升后者；首版宁可遗漏 delta，不持久猜测 identity。
- **alias 权威修订**：P2 的 source identity resolver 只使用作品对象名称和已确认/已采用 alias。
  当前 `reference_manifest.aliases` 已折叠为纯字符串，无法区分 candidate alias；因此进入 P2 前必须在内部
  frozen manifest 中保留一份可用 identity terms/状态证据，不要求扩大当前前端 wire。
- **验证**：source/local 同名、同路径两个同名对象、candidate alias 命中和高语义相似都不得自动合并。

### MEM-DEC-030：冻结 source 对象是权威包络，不是一行可任意覆写的基础 JSON

- **状态**：采用为组合视图规则。
- **初始决定**：把作者 CoreEntity 的所有字段复制到 RP 对象，然后用 delta 直接改这份 JSON。
- **现有证据**：frozen reference manifest 可包含 canonical/draft/candidate/conflicted identity handles，但只给
  canonical 对象写入 summary/character，只纳入 canonical relation，并继续受出场位置和读者/角色知识边界约束。
- **质疑**：复制会让旅程中出现一份伪 source truth；把 candidate 字段、hidden truth 或截止点后状态带入
  覆盖层还会绕过 ADR-0018 的 evidence/visibility 门。
- **升级**：组合视图只读投影：
  - 截止点前可见的 draft/candidate/conflicted 项最多提供身份 handle、名称、类型和出场证据；
    不提供可覆盖叙事的当前事实。
  - 只有已确认、读者/角色可见、截止点前的字段和关系进 base facts。
  - RP 可以用 operation 改变当前状态、位置、持有、关系、知识和 RP alias，但不能替换
    source identity/type/provenance，也不能取消未来/忽略门。
  - `end_relation`/状态覆盖只影响本旅程投影，不更新作者 relation/CoreEntity。
- **验证**：原作角色在截止点存活、A 分支后来死亡、B 分支受伤的组合视图各自正确；
  source base 和作者数据零写入。

### MEM-DEC-031：旅程共用一条 identity/operation stream，对象存在性由 `create` ancestry 决定

- **状态**：采用为分支语义。
- **初始决定**：旅程每个 sibling 拥有一套独立 local object rows，或全旅程按名称共享所有 local objects。
- **质疑**：前者复制共同前缀，后者让 A 分支后创建的人物出现在 B 分支；按名称共享还会合并
  两个 sibling 各自创作的同名对象。
- **升级**：每旅程一条 append-only operation stream。local object 只在其 `create.effective_node_id` 属于当前
  ancestry 时存在；分叉前 create 自然共享，分叉后 create 自然隔离。两个 sibling 独立出现的同名对象
  得到两个 key，不尝试跨分支合并。
- **关系边界**：只有两个 endpoint 都存在于当前视图，relation operation 才可折叠；切换分支后
  任一 endpoint 不可见，该 relation 同时不可见。
- **幂等**：每批抽取由服务端 derivation key + operation ordinal 识别；同一安装重试不可再创一个
  local key 或重复关系。具体唯一约束在 P2 schema 审议时再确定。
- **重开条件**：未来产品真正支持分支合并，而不是只切换 selected sibling；届时必须设计显式
  identity/relation 冲突决议，不复用当前折叠规则假装自动合并。

### MEM-DEC-032：模型知识不能创建 source identity

- **状态**：采用为 provenance 底线。
- **初始决定**：无 source 旅程中出现知名原作人物名称时，按模型训练知识创建一个 source object。
- **质疑**：没有 source revision、manifest、target ID、出场位置或权属证据；“模型知道这个名字”
  不足以让系统宣称它来自作者导入库。
- **升级**：未绑定 source 的旅程只有 local namespace。source-bound 旅程中，不在截止点可见
  frozen manifest 的对象也不能获得 source handle；只有当前 RP 原始节点确实创建了一个长期对象时，
  才能以 local 身份保存。这不阻止模型在正文中写出名字，只阻止伪 provenance 进入结构化库。
- **验证**：同一名字在 unbound journey 中只能是 local；在 source-bound 但超过 cutoff 时仍不能
  转为 source；两种情况都不泄漏未来 source facts。

### MEM-DEC-033：overview 恢复不等于 structured object view 已恢复

- **状态**：修正 MEM-DEC-025 的适用范围；已选 P2 目标臂，仍须 gold/extracted eval 才能上线。
- **初始决定**：第一个从 manual overview 派生的 CAS 有效 automatic revision 完成后，整个结构化
  对象库也自动恢复。
- **质疑**：该 revision 只会重新处理 coverage 之后的 tail。手工 barrier 之前的 automatic `create/state/relation`
  operations 不是 manual revision 的 descendants；若继续屏蔽它们，旧 local 对象和状态不会凭一个新 tail
  自动回来。若无条件恢复它们，又会让用户修正的旧错事实重新进 Prompt。
- **升级**：分开两个状态：
  - overview 在第一个 CAS 有效 automatic descendant 后恢复；
  - structured object view 在一个已验证的 recovery derivation 安装前仍标记 `degraded_manual_barrier`，
    编译时只使用 manual overview + raw tail + 不可变 source identity/provenance；旧 automatic operations
    与可能冲突的 mutable source facts 都不注入。
- **第二轮升级**：曾把 P2 目标收窄为 `section_scoped_barrier + bounded_manual_reconcile`；随后发现
  七区是自由文本，section 名称不能证明未修改其他 fact kind，因此该屏障只能作为 R2 风险臂。
- **当前升级**：生产目标改为 `global_manual_barrier + active_projection_reconcile`：先屏蔽旧自动投影，
  再逐项处置保存时冻结的 active candidates；所有内部 batch 完成后原子追加补偿 operations +
  recovery commit，一次解除整个 barrier。`reset_new_only` 是安全基线，`section_scoped_barrier` 是成本对照，`full_raw_rebuild` 只作为
  诊断上界。各臂仍与“无 structured view”比较；选出目标臂不等于预先宣称它会通过。
- **上线门**：P2 不得只用“新 delta 能继续写”声称对象库恢复。必须证明手工修正前仍应有效的
  identity/state 能恢复，被修正的 stale facts 为零复活，分支/source 门不退化；否则不上 structured layer。

### MEM-DEC-034：手工修正采用“全局止血 + 有界投影补偿”，不先建完整追溯引擎

- **状态**：采用为 P2 评测目标；运行时实现与 schema 未批准。
- **初始决定**：每次保存手工回顾后，从起点重放当前 selected path，重建整套对象投影。
- **质疑**：完整重放费用和延迟随旅程增长，还会重新解释作者刚刚否定的旧文本；若 manual authority
  没有贯穿重放，它反而是 stale resurrection 机器。为偶发修正预建 rewind、parallel model、全量 diff
  和合并基础设施，也违反 deletion test。
- **升级**：先由服务端比较现有完整七区 payload，安装 barrier；再用一个有界 reconcile 逐项处置
  active candidates。它复用现有 overview save、revision/CAS 和后台整理形态，不要求对象编辑器或
  第二个用户动作。补偿结果追加而非改旧 delta。
- **再质疑**：section → fact kind 很粗且七区是自由文本；把“没改这个 section”当作旧 fact 可继续
  注入，会让实际修正越过 barrier。自然语言新回顾也未必完整枚举所有仍有效对象状态。
- **再升级**：barrier 覆盖旧 active projection；section diff 只用于提示和分批，不用于排除候选。
  模型沉默不得解除 barrier；旧候选必须全量 disposition，`uncertain` 继续 degraded。
  12.10 先用 gold disposition 验证架构上限，再评 extracted reconcile。若 gold 仍不能同时达到“应保留
  状态全恢复 + stale 零复活”，说明 section 证据不足，目标臂淘汰，不用更强 Prompt 掩盖。
- **重开条件**：只有真实回放证明完整 raw rebuild 显著提高恢复且费用/延迟可接受，或出现 schema
  迁移、projection corruption 等维修需求，才把 full rebuild 从诊断工具升级为产品路径。

### MEM-DEC-035：模型不能自由选择要退休的旧事实

- **状态**：采用为 P2 安全/正确性不变量。
- **初始决定**：把当前旅程里语义相近的旧 facts 交给模型，让它返回矛盾项 ID。
- **质疑**：语义相近不等于同一对象的同一状态；未限定候选时，一个关于副业的新关系可能退休工作
  关系。模型判断错误会被持久化放大，换 Prompt 不能限制爆炸半径。
- **升级**：服务器先限定同 owner + `novel_id` + journey、selected ancestry、有效 source/authority 的
  保存时 active projection；section/fact-kind 猜测不能从池中排除对象。进一步要求：标量替换是同
  object + field；关系替换是同 endpoints + relation kind；
  identity create/merge 只走 MEM-DEC-028～032 的 resolver。模型只对 call-local refs 做
  `keep/suppress/replace/uncertain`，服务端拒绝集合外、缺端点和伪造 ID。
- **失败降级**：候选范围无法确定时不退休任何旧记录；对应 barrier 保持，Prompt 使用 manual overview
  作为当前真相。保守遗漏可以被用户文本托底，错误退休却会污染后续多轮。
- **验证**：同名不同人、同人不同关系、跨 sibling、future source、旧 authority、重复 retry 和集合外
  ref 均必须为 blocking case；wrong-object invalidation 为 0。

### MEM-DEC-036：一次“保存修改”可授权整理，但保存结果与整理结果必须分开陈述

- **状态**：产品行为采用；具体 read model/wire 待 P2 后复核。
- **初始决定**：回顾保存后静默运行 reconcile；失败时把整个动作显示为“保存失败”。
- **质疑**：用户只理解自己改了回顾，不知道系统还在改派生对象；静默扩大授权缺少掌控感。反过来，
  manual revision 已持久化时显示“保存失败”又是不真实反馈，可能诱导重复覆盖。
- **升级**：仍保持一次保存，不增加对象字段确认页；但按钮附近先用自然语言说明“保存后会按这份回顾
  重新整理长期记忆”。持久化成功立即显示“回顾已保存；正在按修改整理长期记忆”。reconcile 失败显示
  “回顾已生效，部分长期记忆暂以回顾为准”，草稿与 manual revision 都不回滚。
- **最小实现约束**：先尝试复用现有 summary background task 与 drawer。只有现有 read model 无法同时
  表达“manual 已保存”和“structured 整理未完成”时，才讨论一个 additive 用户态；不暴露 task ID、
  enum、对象 key 或 fact kind，也不为了诊断先建对象管理台。
- **验证**：正常、无模型连接、后台失败、409、晚到 automatic response、离开再进和 390px 窄屏均要
  证明保存反馈真实、正文可继续、用户修正不丢失。

### MEM-DEC-037：从手工回顾中删除文字只形成抑制证据，不自动形成反事实

- **状态**：采用为 manual reconcile 语义。
- **初始决定**：旧 section 有“艾琳知道真相”，新 section 删除该句，就追加
  `set 艾琳.knowledge=false`。
- **质疑**：用户可能只是缩短回顾或移动信息；文本缺席不证明相反命题。把 omission 当 negation 会制造
  用户从未写过的新事实。
- **升级**：删除或无法对应的旧表述足以让该旧派生 fact 停止注入，但只产生 `suppress`/barrier，
  不产生反值。只有新 manual 文本明确写出“不知道”“已经归还”等可定位陈述时，才生成对应
  `replace/unset` 候选。纯改写且语义等价可 `keep`，但必须逐项给证据，不能靠模型沉默。
- **权威边界**：manual 文本可改变 RP 当前态对 mutable source facts 的采用，但不能靠删字重绑
  source identity、改 source provenance 或把候选 alias 变成 canonical alias。
- **代价与兜底**：保守 suppression 可能暂时漏掉仍为真的旧事实；manual overview 与 raw tail 仍提供
  叙事连续性。若这种遗漏在 12.10 真实场景中不可接受，优先淘汰 structured recovery，而不是放宽为
  “模型猜用户想表达什么”。
- **验证**：明确否定、纯删句、同义改写、移段、只加新句和同时改多事实分别设 oracle；纯删句不得生成
  反值，明确否定必须保留，source identity/provenance 永不被自然语言 omission 改写。

### MEM-DEC-038：七区 section 名称不能作为事实失效的安全边界

- **状态**：淘汰 section-scoped barrier 作为生产默认；保留为 R2 实验臂。
- **初始决定**：只要 `important_people_and_factions` 没变，就继续使用所有 relation facts；只屏蔽
  修改 section 映射到的 fact kinds。
- **质疑**：七区只有展示意图，不是受约束 schema。用户可以在 `world_and_start` 写背叛关系，也可在
  `must_remember` 改任何状态。静态映射会产生安全假阴性；LLM section classifier 仍只是另一个会错的模型。
- **升级**：manual save 先屏蔽整个旧 active structured projection。reconcile 的候选池由保存时服务端
  快照决定，section diff 只可排序、提供证据或分固定 object batch；不得让未审候选穿过新 authority。
  object batch 可逐批计算和 checkpoint，但不得逐批解除屏障；发布边界见 MEM-DEC-045。
- **代价**：短时间内 structured recall 会全降级，长旅程 candidate 数可能较大；但 manual overview、raw
  tail 与 source identity 仍在，故事可继续。先测 active projection 大小和后台耗时，不预建分布式 replay。
- **重开条件**：只有固定回放证明某个确定性、更细的 changed-span → candidate 绑定规则无漏判，才允许
  缩小初始 barrier；“平均看起来没出错”或更强模型分类不足以重开。

### MEM-DEC-039：manual reconcile 默认一次调用，超硬预算才确定性分批

- **状态**：采用为 P2 eval 的执行顺序；不构成现有任务实现。
- **初始决定**：为任意长旅程先建一个多 worker、可并行、可恢复的对象 reconciliation pipeline。
- **质疑**：manual save 是低频路径，active projection 远小于 raw history；尚无规模证据时先建分布式调度
  是为假想负载买复杂度。反过来，把超限 projection 截断又会让未见候选被当作已处置。
- **升级**：按冻结模型 profile 的输入/输出预算计算；能容纳时一次 schema-validated 调用完成。只有硬预算
  超限才按 server object key 确定性分批，顺序为 local identity/create → 单对象字段 → relation；relation
  只有两端 identity 都在当前 manual authority 下恢复后才可安装。每批共享同一 candidate snapshot hash、
  manual revision 和 derivation root，重试不换分组。
- **第二轮升级**：分批只是内部计算和可恢复 checkpoint；所有 batch、relation 依赖和 completeness
  一起通过后才原子发布。达到冻结 batch/费用/时间上限就停止并保持整个 barrier，不自动切 full raw rebuild。
- **验证**：同一 snapshot 在不同 retry/worker 顺序下产生相同分组与最终 projection；缺失 endpoint 的
  relation 注入为 0；单调用与分批 gold 结果字节规范化后等价。只有真实规模稳定触发分批，才考虑并行化。

### MEM-DEC-040：candidate snapshot 锚定作者看见的 base leaf，不追到保存时最新叶

- **状态**：采用为 P2 snapshot 不变量；实现/schema 未批准。
- **初始决定**：用户点保存时，用 journey 当前 selected leaf 的对象投影作为 reconcile 输入。
- **质疑**：编辑 drawer 打开后故事可能继续。当前实现故意把 manual revision 锚定到冻结
  `base_selected_leaf_node_id/path_hash`，并让新 tail 由后续 automatic descendant 吸收；若 memory snapshot
  偷跑到最新叶，会拿作者没看见的事实与旧文本对比并错误 suppress。
- **升级**：candidate 只折叠到 edit context 的 base leaf，绑定 base overview authority；保存期间新增 tail
  明确排除。manual save 成功后，新 tail delta 走当前 manual lineage 的正常路径，reconcile 不代替它。
- **验证**：复用 `test_manual_overview_save_keeps_frozen_coverage_and_absorbs_new_tail` 的时序增加对象哨兵：
  base 前旧 fact 进入 candidates，编辑期间新 fact 不进入，后者在 recovery commit 后仍按后序 node 生效。

### MEM-DEC-041：不新增 `memory_epoch`；用既有行锁、epoch 与 candidate root 做精确 CAS

- **状态**：采用为最小并发方案。
- **初始决定**：在 journey 再加 `memory_epoch`，所有 fact/recovery 写入都递增。
- **质疑**：它与 `overview_epoch`、`source_context_epoch` 和 task lease 形成第四个易漂移计数器；分支切换
  还会让全局计数变化，却不一定使 branch-local recovery 失效。
- **升级**：manual save 与所有 P2 delta finalizer 统一锁 journey。pre-manual writer 用现有
  `started_overview_epoch` 线性化；source writer 重验 `source_context_epoch`；reconcile 用
  `manual_revision_id + base path hash + source epoch + compiler/schema version + candidate snapshot hash`
  做内容寻址 CAS，安装再用 derivation key 幂等。不要使用 `expected=any`。
- **重要限定**：reconcile finalize 不要求全局 `selection_epoch/overview_epoch` 与开始时完全相等；正常的
  path extension、automatic descendant 或临时切 sibling 都会改变它们。它重验冻结 branch authority，
  而不是误把“当前 HEAD 变了”当作历史输入被改写。
- **重开条件**：只有出现无法按 project/task fence → journey lock 进入的外部 writer，或实测 journey lock
  成为瓶颈，才讨论独立 stream revision；不得先为假想吞吐量加 epoch。

### MEM-DEC-042：安全的 reconcile 结果属于冻结 branch，不属于完成时当前 selection

- **状态**：采用为分支语义。
- **初始决定**：finalize 时 `selection_epoch` 或 selected leaf 不同就丢弃结果。
- **质疑**：用户继续写一轮、浏览 sibling 或离开再回来都会让低频长任务白跑；而消息节点不可变，原 branch
  仍可由 anchor ancestry 精确寻址。当前 overview 已能在切回分支时恢复对应 revision。
- **升级**：finalize 从 manual anchor 加载 ancestry 并重算 path hash；只要该 exact path 上的 barrier/
  manual authority 仍匹配、source epoch 未变、journey active，就可把结果安装为该 branch 的历史资产。
  当前 selection 可以是原路径后代或 sibling；编译时仍只消费 selected ancestry。
- **同线后续修正**：更晚 descendant manual barrier 会在其后代范围遮住旧 commit，但不抹掉旧 anchor 的
  历史有效性；同 anchor/path 的更新 manual revision 则使旧任务 stale，避免两个权威争同一位置。
- **验证**：prepare 后分别继续原分支、切 sibling、切回、在 descendant 再手改、同 anchor 再手改；只有
  最后一种旧任务不得发布，所有 sibling 注入仍为 0。

### MEM-DEC-043：剧情有效顺序按 ancestry/effective node，不按后台写入时间

- **状态**：采用为 projection fold 规则；呼应 MEM-DEC-014。
- **初始决定**：同 object/field 最后写入数据库的 operation 胜出。
- **质疑**：manual reconcile 可能比新 tail 的自动抽取更晚完成；按 `created_at` 会让较早修正覆盖后续
  已发生变化。重试时间、worker 速度和部署延迟都不应改变故事事实。
- **升级**：source base 位于虚拟根；operation 先按 selected ancestry 中 `effective_node_id` 的位置，
  再按同 node 的 authority 与 `operation_ordinal` 折叠。`created_at` 只审计。manual reconcile 的
  effective node 是 manual anchor，即使晚安装；后序节点有证据的真实 transition 可胜出。
- **失败关闭**：后序文本若只是声称“更早其实如此”的 retrospective contradiction，而不是在该节点发生
  的新变化，不能借较晚 node 自动覆盖 manual correction；精确边界见 MEM-DEC-044。
- **验证**：交换 worker 完成顺序、数据库时间并重试，规范化 projection 必须相同；切 sibling 后只按其
  ancestry 重放。

### MEM-DEC-044：后序 automatic fact 只有证明“新变化”才能覆盖 manual correction

- **状态**：P2 候选规则，必须先过 gold/extracted temporal eval。
- **初始决定**：任何后序 selected raw node 的冲突 fact 都按时间自动覆盖手工值。
- **质疑**：模型可能下一轮又复述被作者否定的旧错误；节点较晚只证明这句话后来生成，不证明它描述的
  事件后来发生。反过来，永远让 manual 值获胜又会阻止“后来把剑交给艾琳”等真实状态变化。
- **升级**：自动替换必须有后序 selected raw evidence，并区分：该节点明确发生的 forward transition、
  对过去的 retrospective claim、无法判断。只有 forward transition 可自动形成更晚状态；retrospective/
  ambiguous 候选 `usable=false`，manual 值继续生效。用户节点可帮助证明意图，但不能单独把“我尝试”
  当结果；NPC 自主事件有明确 assistant outcome 也不强制要求用户句。
- **再质疑**：transition 分类仍是语义判断，可能出错。
- **再升级**：12.10 先给 gold temporal labels；extracted arm 任何 manual-retcon resurrection 都 blocking。
  若达不到门槛，首版退回“automatic 不覆盖 manual-derived field，直到下一次 manual save”，而不是
  放宽证据或上第二个 judge。

### MEM-DEC-045：一个 manual revision 的 recovery 只允许原子发布，不暴露半套 projection

- **状态**：采用；修正 MEM-DEC-038/039 的逐批解除设想。
- **初始决定**：每完成一个 object batch 就解除对应 object/field barrier。
- **质疑**：人物 identity/state 已恢复而 relation endpoint 尚未恢复时，Prompt 会看到内部不一致；UI 还需
  解释多种“恢复了多少”的瞬时状态。部分写入失败也难以判断可否重试。
- **升级**：LLM batch 结果可通过既有 lease-fenced task checkpoint 持久化，但不进入可编译 projection。
  全部候选 disposition、依赖、hash 与预算门通过后，在一次短事务内追加 compensation rows 与
  recovery commit。commit 缺失时整个 barrier 保持；失败不影响 manual overview/raw tail。
- **重开条件**：只有真实 active projection 规模证明最终单事务成为瓶颈，才评估 per-object atomic generation；
  仍须显式 dependency closure，不默认回到逐批可见。
- **验证**：任一 batch 后崩溃、lease 丢失、relation 缺端点或最终 insert 冲突时，结构化注入均为 0；
  retry 成功后一次出现完整 projection。

### MEM-DEC-046：barrier/recovery 完成是业务 stream 事实，不能借通用 task 状态代替

- **状态**：语义采用；单表 control row 还是 generation 表待 P2 schema deletion test。
- **初始决定**：`AsyncTask.status=done` 就表示 memory barrier 已解除。
- **质疑**：task done 只证明 handler 返回；task 可重排、清理或隐藏私有 checkpoint，零 compensation 的
  正确 recovery 也没有 fact row 可证明完成。业务编译依赖通用队列表会把生命周期当领域真相。
- **升级**：append-only memory 领域必须表达 `manual_barrier` 与 `recovery_commit`。commit 至少绑定
  manual revision、candidate/output hashes、operation count、source context、schema/compiler version 和
  derivation root；编译器只认 commit，不认 task 状态。新的 manual barrier 自动遮住该 ancestry 上较早 commit。
- **物理质疑**：把 control record 塞进 fact table 会引入 nullable object 字段和 CHECK 约束；另建 generation
  表又增加 schema/事务面。P2 在“一张带 `record_kind` 的 stream 表”与“generation header + fact rows”间
  做 deletion test；不在评测证明结构化层有价值前拍板。
- **验证**：zero-op success、task done 但提交回滚、commit 存在但 count/hash 不符、重复 commit、新 barrier
  覆盖旧 commit均失败关闭；task 被清理后已提交 projection 仍可重建。

### MEM-DEC-047：压缩、对象与 source 只进入一个 Prompt Pack，不各自拼接后再算总长

- **状态**：采用为 P1/P2 编译边界；实现未开始。
- **初始决定**：保留当前 source 16K，再分别给 segment、raw rehydration、object facts 各一个固定预算，
  最后把四段直接拼进 `compile_story_messages()`。
- **质疑**：局部 cap 相加仍可能超模型窗口；同一事实重复，optional source 还可能挤掉 raw tail。各模块
  单独“未超限”不能证明整次调用安全。
- **升级**：interaction 先把各域已门禁结果转换为一次调用私有的 typed sections，统一预算后才渲染。
  Evidence 继续拥有 source 检索/可见性，interaction 拥有 branch/overview/segment/object 语义；不新建
  跨模块 memory service。
- **删除测试**：P1 不公开新 facade、不持久化 IR；一个私有 pack builder 足够。只有第二个模块需要同一
  RP 分配策略时才抽公共纯函数，不能直接 import Evidence `services/compiled_context.py`。
- **验证**：每次最终 message token 合计等于 pack 各 section + envelope，任何 omitted item 都有原因；
  禁止“各局部预算均通过、总 Prompt 超限”。

### MEM-DEC-048：预算分配顺序与消息渲染顺序是两个契约

- **状态**：采用。
- **初始决定**：把更重要资料放得离最终 user message 更近，同时按该顺序从前向后裁剪。
- **质疑**：Chat 消息语义要求当前 user/raw tail 保持原 role 且位于末尾；若以位置表达权威，会和稳定前缀、
  provider cache、历史数据不提权发生冲突。
- **升级**：分配先保护 hard rules、manual/required、raw tail/current input 和 required source；渲染固定为
  `hard rules → overview → active state → episode/index → source data → rejected control → raw tail/current`。
  每个数据 block 显式写 authority/untrusted-data 语义，不能靠消息远近裁决事实。
- **验证**：交换 optional section 的候选量只影响其 slot，不改变最新 user 的位置、role 或必需内容；
  相同 pack 始终得到相同 message 顺序/hash。

### MEM-DEC-049：估算器不直接改用单一 tokenizer；取保守上界并用 provider usage 校准

- **状态**：采用为 P0/P1 预算实现要求。
- **初始决定**：删除 interaction 字符估算，直接调用现有 `estimate_token_count(model=...)`。
- **质疑**：现有 helper 对未知 model 回退 `cl100k_base`，并不证明适配 DeepSeek/Kimi/其他兼容端；当前字符
  估算虽粗，却在中文长文本上提供了另一个保守边界。
- **升级**：不加 tokenizer 依赖。section/message 估算取 `max(当前字符+envelope估算, shared tokenizer估算)`，
  再应用 capability margin；真实 provider 返回 usage 时记录 estimated/actual ratio 并按 model/profile 分层。
  只有固定校准证明更窄 estimator 仍不低估，才降低 margin。
- **验证**：中文、英文、数字、emoji、混合引号及超长段落；任何样本 `actual + output reserve` 越过 hard
  ceiling 都 blocking。无 usage 的模型保持 `uncalibrated`，不把缺值当 0 偏差。

### MEM-DEC-050：source 16K 是局部最大值，不是总 Prompt 的预留权利

- **状态**：采用为 P1 contract 调整候选；需同步 Evidence README/tests，但不改浏览器 wire。
- **初始决定**：`compile_interaction_story_context()` 永远先填满最多 16K，interaction 再装其他记忆。
- **质疑**：短窗口模型或巨大 raw tail 下没有 16K 可用；反过来，大窗口也不应因 source 无候选浪费额度。
- **升级**：interaction 先算固定成本，再把 `min(16K, source_slot_available)` 作为 server-derived 可选 budget
  交给 Evidence。player identity/pinned/cutoff guard 是 required；它们放不下就 blocker，optional references/
  excerpts 才裁剪。空余 source 额度可回流其他 slot。
- **兼容边界**：P1 只给现有 facade 增加带默认值的内部参数并仍返回 rendered packet/token_count；不解析
  Markdown。只有 P2 证明 source+overlay 重复值得解决，才考虑加 typed items。
- **验证**：0/小/16K/超大 source slot、required 超限、无 source journey、热切换短窗口；任何 pinned/source
  cutoff 项不得因 optional memory 静默丢失。

### MEM-DEC-051：跨层去重只使用确定性身份，不增加一次 LLM “整理 Prompt”

- **状态**：采用到 P1/P2 eval。
- **初始决定**：把 overview、source、object facts、segments 和 raw nodes 全交给模型，先生成一份去重上下文。
- **质疑**：这增加费用/延迟并让一个不可审计判断决定哪些高权威事实消失；去重输出本身又成第三份摘要。
- **升级**：首版只做：同 segment 已回读 raw node 时不再渲染该 segment summary；同 source/evidence ref
  合并 trace；P2 同 `(object_handle, field/relation key)` 同值只渲染最高权威 winner，不同旧值仅作为明确
  historical episode。manual overview 是自由文本，不做语义去重，也不解析 source Markdown 猜字段。
- **代价**：overview 与 current object fact 可能仍有少量重复；先记录 duplicate token ratio。只有该比例
  明显侵蚀质量/成本，才扩展 typed provenance，不用 LLM 猜删。
- **验证**：raw-over-summary、same-key-same-value、same-key-old-value、同名不同对象、manual 同义文本；
  任何错误折叠或权威下降 blocking。

### MEM-DEC-052：候选激活只做一次 seed + 一跳扩展，不递归图搜索

- **状态**：采用为 P1/P2 首版 selector。
- **初始决定**：让模型根据当前 Prompt 自主反复检索，或从命中对象递归展开整张关系图直到预算满。
- **质疑**：费用、结果和深度不可预测；一条 source/future/sibling 错边会扩大泄漏面。低信息“继续”又不能
  只靠最新输入。
- **升级**：seed 固定来自 player/pinned/manual、最新输入、current situation、important people、open threads
  与最近故事节点；名称/已确认 alias 精确激活对象。只对 active seed 展开一跳可见关系和 endpoint，随后
  用选中 label 扩展 segment/source query 一次，不做 fixpoint。
- **重开条件**：固定夹具证明关键二跳事实持续漏召，且一跳 + episode 回读不能补救，才评估版本化二跳；
  不先上图数据库或自治 tool loop。
- **验证**：低信息输入、代词歧义、环关系、超大 hub、future/excluded endpoint 和 sibling local object；
  候选集合/hash 必须确定且有上限。

### MEM-DEC-053：Prompt Pack 只留脱敏清单与 hash，不新增完整 Prompt/记忆快照表

- **状态**：采用。
- **初始决定**：为每轮保存完整统一 Prompt，方便调试和以后做记忆浏览器。
- **质疑**：会复制用户正文与版权 source，放大隐私、删除和存储边界；完整 Prompt 也不是事实源。
- **升级**：复用 attempt usage 与现有 Evidence context snapshot：保存 pack/compiler version、总量/各槽 token、
  included/omitted ref hashes、budget events、source snapshot/fingerprint 和 prompt hash；默认不保存 rendered
  content。P3 用户界面只从领域资料重建自然语言“为什么记得”，不暴露 raw Prompt。
- **重开条件**：只有受控诊断明确需要短期 full context，才复用现有 `retain_rendered_context` 过期策略；
  不新建永久 prompt table。
- **验证**：诊断记录不含正文、Key、持久 object UUID 或其他 novel 数据；删除旅程/项目后不留孤立正文副本。

### MEM-DEC-054：capability profile 的版本/hash 随 LLM execution snapshot 冻结

- **状态**：P1 已实现并同步 project/infrastructure/interaction README 与测试。
- **初始决定**：worker prepare 时按 provider/model 读取当前 capability table；task 只冻结原有 LLM profile。
- **质疑**：任务排队、崩溃重试或滚动部署期间 capability table 可能更新；同一 task 会在不同 attempt 得到
  不同 compaction/hard ceiling，破坏幂等和单变量评测。
- **升级**：创建 story attempt 时把 capability profile ID/version/hash、verified source date 与预算字段作为
  非 secret 元数据并入现有 project LLM execution snapshot；Prompt Pack fingerprint 也包含该 hash。
  worker 恢复使用同一档案，不按当前默认静默升级。档案被安全撤销时 fail-closed，并要求新 attempt。
- **实现复核**：现有 snapshot 由 `modules.project.llm_runtime` 统一构造、签 `profile_hash` 并在 restore
  重验。interaction 不得在返回后附加字段、复制私有 `_stable_hash` 或再包一层 snapshot；capability registry
  应由现有 infrastructure/project LLM seam 持有，再由 project snapshot 一次冻结。
- **架构门**：P0 可用 eval-local profile，不改共享层。进入 P1 生产实现前，必须就
  `infrastructure/llm` + project snapshot 的共享契约变化请求用户确认并同步 README/tests；不以“内部字段”
  名义绕过 AGENTS.md 的 shared/infrastructure 风险门。
- **热切换**：新用户操作通过当前账户连接解析新 model + 新 capability snapshot；不会沿用上一模型 ceiling。
  这不把 context limit 变成项目可编辑设置，也不把 provider Key 放进 snapshot。
- **验证**：enqueue 后修改 server defaults、切 model、重排 task、崩溃恢复和 profile revoke；同 task 的 pack
  hash/预算稳定，新的 attempt 才采用新 profile。
- **实现**：project 生成的既有 secret-free snapshot 加性保存 `llm_capability_profile` 与独立 hash，
  外层 `profile_hash` 同时签名；restore 重验 provider/model 与 capability hash，并把冻结档案交给
  interaction。旧 snapshot 缺字段时使用 `legacy-unfrozen-short-v1`，不静默套用当前 DeepSeek ceiling。

### MEM-DEC-055：overview restart point 必须验证 manual authority lineage，不能只取最远 anchor

- **状态**：已实现。`_best_overview_for_path()` 先选最新适用 manual lineage，旧链更远 anchor
  不再胜出；story/reducer 只接受当前 promoted head 与该 selector 一致的结果。
- **初始决定**：沿用 `_best_overview_for_path()`，在 path 上选择 anchor 最远的 revision 作为 reducer base。
- **质疑**：该函数只校验 anchor/prefix hash。若用户从较早 base 保存 manual revision，而更远位置残留一个
  基于旧 automatic lineage 的 revision，切 sibling 再切回可能让旧 revision 因 anchor 更远获胜。
- **升级**：新增/收窄一个 authority-aware selector：先验证 path/coverage；找当前 path 上最新适用 manual
  barrier（同 anchor 取较新 revision）；automatic candidate 只有 `based_on_revision_id` 链能回到该 manual
  barrier 才兼容。无 manual 时按现有 automatic chain；最后才按 coverage/anchor 远近选最佳。
- **删除测试**：优先让 branch activation、story prepare 与 reducer 共用这一窄 selector，而不是分别再写 lineage
  判断；但不把它提升为跨模块 facade。
- **验证**：manual anchor A、旧 automatic B>A、切 sibling/切回时 A 必须胜；从 A 产生的新 automatic C>A
  才可胜。环、缺 parent、超过链深、other journey/novel 均 fail-closed。

### MEM-DEC-056：当前 request 与近期完整节拍是不可压缩 raw suffix

- **状态**：已实现为 periodic/emergency compaction 硬门；当前生产默认保护近期至少一个完整
  user/assistant 节拍、至少两个节点和约 16K raw suffix。
- **初始决定**：summary 可覆盖 overview 后到当前 selected leaf 的全部 tail。
- **质疑**：urgent story attempt 的 leaf 通常是正等待回答的 user node。覆盖到 leaf 后，它只剩模型概要，失去
  原始 role、措辞和指令边界；背景整理若总清空最近 tail，也会损失当前场景语气。
- **升级**：从 leaf 向前保留 profile/eval 冻结的 recent-tail token 目标，并强制包含 response target、必要
  user/assistant pair、setup boundary、continuation partial。只压更老 prefix，节点不拆分；最新 user 字节与
  role 必须原样进入最终 story Prompt。
- **失败边界**：required suffix 自身超过 hard input 时 blocker；不得通过摘要用户当前输入、裁一半 node 或
  provider truncation 伪装成功。
- **验证**：普通 send、setup、regenerate、continue、see-sea、单个超长 current user node和最近一问一答。

### MEM-DEC-057：segment summary 是检索索引，不是 emergency reducer 的替代输入

- **状态**：采用；修正 Phase P1 早期“overview/segments + tail 重建”措辞。
- **初始决定**：530K tail 先用已有 segment summaries 做 map-reduce，再更新 overview。
- **质疑**：每个 segment 已与累计 overview revision 同时产生；同 lineage 的最佳 revision 直接可用，再喂
  summary 是重复。跨 manual lineage 的 segment 又是旧解释，会恢复作者删改的当前事实。
- **升级**：reducer 只读当前 compatible overview + contiguous raw nodes。segment 只用于 path coverage、
  episode retrieval 和幂等识别；`predates_manual_baseline` segment 永不作为 current-state reducer 文本。
- **验证**：同 lineage checkpoint、manual rebase、旧 segment 含 stale value、segment 内容正确但 overview
  lineage 错误；无一允许通过重喂 summary 绕过 barrier。

### MEM-DEC-058：周期整理与紧急整理共用一个 oldest-prefix bounded reducer

- **状态**：已实现。两条路径共用 `_summary_compressible_prefix_end()` 与同一 prepare/finalize；
  periodic 只在可压 prefix 自身达到 16K 时入队，urgent 在同 attempt 内循环。
- **初始决定**：后台 16K 整理保持一次全 tail，紧急超限另写 map-reduce 流程。
- **质疑**：两套 coverage、chunk、幂等与 Prompt 契约必然漂移；正常链路没测过的 emergency 特例最容易
  在真正超长时失败。
- **升级**：同一 reducer 从 compatible overview coverage 后选择最老 contiguous whole-node chunk；背景与
  urgent 只传不同 trigger/max-pass policy。先从 required Prompt 移除 optional items，只有 required pack
  超 compact trigger 才 emergency compact；optional 装不下只省略，不为它付一次 lossy summary。
- **分块边界**：按完整 node/自然 user-assistant beat，不跨 sibling、不拆 role。单个旧 node 放不进 summary
  input 时首版 blocker；出现真实样本再评 paragraph checkpoint。
- **验证**：相同 path/profile 下 periodic 多次与一次 urgent backlog 最终 coverage/overview gold 等价；
  允许文本措辞不同，但事实 oracle、authority 和 included node ranges 相同。

### MEM-DEC-059：full path 负责 stale fence，chunk prefix 负责 segment/revision 身份

- **状态**：已实现；不需要 DB schema。PreparedSummary 保留 full path fence，segment/revision
  已改为 chunk-end prefix hash/anchor/coverage。
- **初始决定**：每个 summary pass 都把 revision/segment 锚到 prepared full selected leaf。
- **质疑**：多 pass 第一轮只处理旧 prefix；若仍把 coverage 推到 leaf，会跳过未处理 nodes 和 protected suffix。
- **升级**：PreparedSummary 保留 full path hash/node list/leaf 做 prepare/finalize CAS；安装时用
  `segment_nodes[-1]` 计算 prefix hash，segment end 与 overview anchor/coverage 都只到 chunk end。当前全 tail
  pass 因 chunk end=leaf 自然兼容。
- **并发**：urgent attempt 未解决时 path 本应冻结；即便 late writer/branch mutation 出现，full fence 也使
  pass stale。prefix revision 成功后可立即成为同 path 的最佳兼容 head，余下 nodes 仍是 raw tail。
- **验证**：三 chunk 覆盖必须无 gap/overlap；任一 pass 后构建 story Prompt 都包含全部未覆盖 nodes，protected
  suffix 始终 raw。

### MEM-DEC-060：每次 compaction pass 必须可量化净缩减，不增加第二个 judge

- **状态**：已实现 fail-closed 安装门；当前 provisional `min_savings=128` 只作为安全下限，
  仍需付费 dev pilot 校准后才可形成质量/成本结论。
- **初始决定**：只要 summary JSON 合法就安装，假设概要一定更短。
- **质疑**：累计 overview 会增长，过小 chunk 甚至可能让未来 Prompt 更大；反复安装会形成不终止循环。
- **升级**：安装前以同一 estimator/profile 计算 `before=old_overview+chunk_raw` 与 `after=new_overview`，要求
  `after <= before - min_savings`，同时 overview/segment 非空、authority 正确。min savings 在 dev 冻结；
  不达标返回 `compaction_non_reducing`，不写任何 domain row。
- **再质疑**：可再叫一次模型自评/压短。
- **再升级**：不常态化第二个 judge；summary output budget、chunk lower bound 和 Prompt 先约束长度。一次合法
  结果仍不缩减就 fail-closed，交给评测调整，不在运行时追问。
- **验证**：概要缩短、等长、膨胀、只挪 section、估算器边界与 retry；coverage 只在净缩减时推进。

### MEM-DEC-061：在同一 story task/attempt 内有界循环，每 pass 是可恢复短事务

- **状态**：已实现为最小运行方式；urgent 最多 4 pass，每 pass finalize+commit 后重新编译同一
  attempt，达到上限转 context-budget failure，不创建 successor DAG。
- **初始决定**：为 emergency map-reduce 新建 task type、workflow run 和子任务 DAG。
- **质疑**：现有 story handler 已有 lease heartbeat、origin attempt、summary finalize commit 和 restart-origin；
  新编排只会复制权限/恢复逻辑。
- **升级**：handler 循环 `prepare bounded chunk → provider → finalize+commit → rebuild required pack`；达到
  compact target 即恢复同一 attempt。每轮释放事务，worker 崩溃后从已提交 overview 继续。固定
  max passes/calls/tokens/time，超过后明确 context-budget failure，path、user input和已完成 checkpoints 保留。
- **重开条件**：只有真实运行持续越过 worker/drain 上限且 restart 代价不可接受，才考虑 successor task；
  不先建 DAG。
- **验证**：第 0/N pass 崩溃、lease 丢失、SIGTERM 后 restart、达到 cap、provider transient/schema failure；
  不重复 coverage，不创建 sibling，不换 LLM snapshot。

### MEM-DEC-062：manual rebase 命中旧 episode segment 时复用/跳过，不重复插入

- **状态**：已实现并通过 SQLite 领域回归与 fresh PostgreSQL 17 + pgvector 专用实例；同
  path/end 复用既有 segment，新 automatic overview 仍基于 manual revision。
- **初始决定**：新 authority 每次 raw fold 都创建一个新 segment。
- **质疑**：segment 唯一键是 `(journey_id, path_hash, end_node_id)`，与 overview authority 无关；同 path/end
  重放会冲突。复制 segment 也会把不变 episode index 误作可变 current-state derivation。
- **升级**：finalize 先查 existing segment：exact start/end/path 直接复用；range 不同但同 end/path 时保留已有
  episode row、不覆盖 content，并在新 overview producer 记录实际 raw range/reused segment ref。新 authority
  overview revision 可创建，segment 不必一对一新建。
- **验证**：已存 exact segment、覆盖更大 old segment、并发 retry、manual rebase 与不同 ordinal；
  segment 行数不增，overview lineage 正确，旧 segment content 不作为本次 reducer 输入。

### MEM-DEC-063：八段 checkpoint 不是恢复门槛；任何兼容 overview revision 都可续跑

- **状态**：consumer audit 与删除已完成。生产代码不再写入或传播八段 marker；既有 nullable
  `based_on_checkpoint_revision_id` 列暂留数据库兼容，不参与运行时判断。
- **初始决定**：只有 producer 带 `memory_checkpoint` 的每第 8 个 revision 才可作为 emergency restart point。
- **质疑**：每个 automatic/manual overview revision 都不可变且有 anchor/path/parent；等待 8 段会丢掉最近
  已提交进度。当前 marker 主要传播 lineage metadata，没有编译消费者。
- **升级**：authority-aware selector 可从任一兼容 revision 续跑；第 8 段 marker不参与正确性或可用性判断。
  全仓库 audit 只找到 producer 与自证测试，没有恢复、selector、Prompt 或 UI consumer；因此删除生产写入、
  传播 helper 与 task-result 标记，不为清理历史 nullable 列新增 migration。
- **验证**：从 ordinal 1/7/8/9 revision 崩溃恢复结果一致；删除 marker 的实验不能改变 coverage、selector、
  segment recall 或 Prompt Pack。

### MEM-DEC-064：P0 使用 standalone runner，不扩通用 `EvalSuite`

- **状态**：采用。
- **初始决定**：给 `EvalSuite` 增加 `rp_long_memory`，复用通用 generate/QC/review/freeze/report 全链。
- **质疑**：通用 schema 绑定作品 source groups、四套 suite minimums 与现有 review/readiness；RP 的 branch DAG、
  operations、manual barriers、A–E arms 和 compaction passes 不匹配，适配层会比 runner 本身大。
- **升级**：仿照 `evals.ask_world` 新建一个正式 standalone module、一个测试、一份 synthetic JSONL、README
  和一个 Make 入口。可复用纯 helper/`EvalCache`/project facade，但不为复用修改通用 schema。
- **重开条件**：runner 稳定、第二个 RP eval 也需要相同 data/review/freeze 流程，且映射无需大量 optional
  字段时再整合；不是因为“已有框架看起来完整”就提前接入。
- **验证**：新增文件/修改面保持 5 处；`eval-fast` 之外不改变现有四 suite readiness、CLI choices 或报告。

### MEM-DEC-065：case 保存合成事件与模板参数，不保存渲染后的长对话

- **状态**：采用为数据安全/可复现契约。
- **初始决定**：直接把每条 32K～530K synthetic 对话正文写进 committed JSONL，方便读取。
- **质疑**：文件巨大、diff 无法审查，模板修复需批量改正文，也容易混入本地作品/用户文本。
- **升级**：JSONL 只保存 strict operations、parent DAG、template IDs/values、source/manual events 与 oracle；
  runner 用 versioned code templates 生成内容并记录 template hash。禁止绝对路径、Vault 专名、Key、真实正文。
- **split 门**：同 `scenario_group_id` 只能在 dev 或 test 一边；不提供 train。调参数只看 dev，test/holdout
  在门冻结后运行。
- **验证**：同 bytes/version/seed materialization byte-equal；unknown template、额外字段、DAG 环、跨 split group、
  未创建 object ref 和 sentinel 冲突均拒绝并带 line/case ID。

### MEM-DEC-066：offline compile 是默认/CI 门，模型与人工阶段必须显式请求

- **状态**：采用。
- **初始决定**：`make eval-rp-long-memory` 默认连接数据库并跑所有模型/盲评。
- **质疑**：CI 没有账户 Key、真实模型有费用和随机性，人工评分也不可能自动完成；将其混在默认命令会让
  评测不可复现或被跳过后伪装全绿。
- **升级**：默认 `compile` 只做 strict load、materialize、A–E pack 与硬断言，无 DB/网络。`model` 必须显式
  `--novel-id --allow-paid-model` 或 cache-only；`review` 必须显式提供 reviews + arm map。各 stage 独立报告
  availability，离线通过不放行质量声称。
- **验证**：monkeypatch network/client 为必炸仍能 compile；model 无付费标志、cache-only miss 或 project/profile
  不匹配时在 client 创建前失败。

### MEM-DEC-067：reference arm 与 production arm 必须标明实现来源

- **状态**：采用为报告不变量。
- **初始决定**：P0 里生成 B/C/D Prompt 后统一标成“系统输出”。
- **质疑**：P1/P2 尚未实现；eval-local gold builder 只能证明架构上限。若不标来源，漂亮结果会被误当当前产品。
- **升级**：每 arm/run 记录 `compiler_kind=production_baseline|eval_reference|production_candidate`、compiler version
  与 source hashes。A 首先调用现有 `compile_story_messages`；B/C/D/E reference pack 在新模块内最小构造。
  P1/P2 实现后新增 production-candidate adapter，与 reference/旧 baseline 同案比较。
- **限制**：reference compiler 不 import ORM repository、不复制 production safety filter；fixture hard oracle 在其
  输出后独立验证，避免“编译器和测试共用同一错误”。
- **验证**：任何 `eval_reference` 结果的 `production_capability_claim_allowed=false`；只有 production candidate
  通过相同硬门和回归才可改变实现状态。

### MEM-DEC-068：真实 story eval 使用 project provider 与 production request，不用 Codex CLI 代替

- **状态**：采用为 optional model stage；不授权本轮付费调用。
- **初始决定**：复用现有 `CodexStructuredExecutor` 生成 RP story，省去 project DB/Profile。
- **质疑**：Codex CLI 带自己的 agent system/context 行为，且不是产品当前 DeepSeek/Kimi provider；结果不能
  代表 RP runtime。直接环境 Key 又违反 project/owner seam。
- **升级**：model stage 要求可丢弃 interaction `novel_id`，通过 project facade 冻结/打开当前已验证账户连接；
  同 profile/params 调 `story_request` 与 streaming framer。不得读 env Key、自动 fallback 或写项目业务数据。
  model/profile mismatch、非 interaction project 或 owner 门失败关闭。
- **成本门**：显式付费标志是本次 CLI 授权；`EvalCache` content-addressed 复用，cache-only miss 绝不启动 client。
- **验证**：client close、secret-free report、同 run index 所有 arms profile hash 相同、provider usage 可用则记录，
  不可用显式 unavailable。

### MEM-DEC-069：strict fact probe 与 production story blind review 分开

- **状态**：采用。
- **初始决定**：从自由故事文本用 substring 直接计算所有事实 accuracy，或增加一个 LLM judge。
- **质疑**：合理改写会造成 substring 假阴性；未校准 judge 又会把风格偏好冒充事实。反过来，只做盲评难定位
  是 pack 没给、模型没用还是叙事表现问题。
- **升级**：同 pack 先跑独立 eval-only structured fact probe，回答 fixture probe IDs/values/unknown；它只测
  memory availability/use，不冒充产品 story。再用 production `story_request` 生成候选，只做 exact safety
  sentinel/metadata 检查并交人工 0–4 rubric 盲评。首版无 LLM judge。
- **验证**：pack 正确/probe 错归 `model_nonuse`；probe 对/story 盲评差归 quality；两者指标与调用成本分开。

### MEM-DEC-070：arm 顺序和 candidate ID 确定性盲化，映射单独保存

- **状态**：采用。
- **初始决定**：固定 A→B→C→D 执行并把 arm 名写进 review 文件。
- **质疑**：provider 顺序/缓存/限流与 reviewer 预期会产生偏差；随机且不留 seed 又不可复现。
- **升级**：执行顺序由 `sha256(dataset_hash + case_id + run_index + model_profile_hash)` 排列；candidate ID
  由同 root + arm 生成 opaque hash。review artifact 无 arm；单独 arm-map 保存 mapping/hash，评分后才导入。
- **安全**：arm-map 不是加密安全边界，但 review 流程不得同时展示；同一 candidate ID 不能跨 dataset/profile
  复用。
- **验证**：相同 root 顺序/ID 稳定，换 profile/dataset 改变；缺 candidate、重复 review、评分前含 arm 字段均拒绝。

### MEM-DEC-071：报告原子写入并保留 metric availability；不为缺证据创造零分

- **状态**：采用。
- **初始决定**：模型/盲评没跑就把相关指标写 0，所有 stage 共用一个最终 ready。
- **质疑**：0 既可能是真实失败也可能是完全没测；中途写一半 JSON 会污染后续比较。
- **升级**：每个 metric 使用 `available/blocking/threshold/passed/reason`；stage 级 readiness 分离，顶层明确
  `quality_claim_allowed`。报告先写同目录临时文件再 replace；主报告仅存 output hash/长度，正文留 ignored
  candidates/reviews。
- **exit**：请求 stage 完整且 blocking 门通过为 0；形成完整 non-ready 报告为 2；schema/config/runtime
  exception 保持普通非零。compile 不要求 model/review available，model/review 请求了就不得以 unavailable 退出 0。
- **验证**：写入前/中断崩溃不覆盖旧报告；unknown metric、缺 usage、缺 review 都保留 inventory 和 reason。

### MEM-DEC-072：只在 dev 冻结方向性阈值，test 不参与调参

- **状态**：采用。
- **初始决定**：看完全部结果再挑 slot/阈值，使新方案刚好胜出。
- **质疑**：合成数据也会过拟合；多臂、多长度、多指标更容易事后选择。
- **升级**：hard invariants 预先固定；dev pilot 冻结 practical minimum、pairing/statistics、盲评非劣界、slot/
  compaction/profile 参数与模型 runs。写入一个 threshold/config hash 后才允许 test；test 只报告一次，失败返回
  dev 形成新版本，不改旧报告。
- **验证**：同 scenario_group 不跨 split；test 命令要求 frozen threshold hash；任何 test 后参数变化生成新
  compiler/eval version，不能覆盖原结果。

### MEM-DEC-073：committed v1 是 contract dataset，不是长期质量 baseline

- **状态**：采用为命名/口径。
- **初始决定**：只要 committed JSONL 和离线 compile 绿，就称 RP 长期记忆 baseline 已通过。
- **质疑**：small synthetic cases 证明 schema/安全和可复现，不证明真实模型、盲评或用户长期体验。
- **升级**：report 固定 `quality_scope=synthetic_contract_and_directional_memory_eval`；committed v1 先承担 smoke/
  dev contract。只有 model repeats、test holdout、盲评校准和已冻结门都通过，才产生带独立 version/hash 的
  quality baseline；真实用户试用仍是更高证据层。
- **验证**：compile-only 报告 `quality_claim_allowed=false`；文档/CLI 输出不使用“用户验证完成”“长期不出戏”。

### MEM-DEC-074：首轮 DeepSeek V4 Flash dev pilot 拒绝启用 B/C，也不触发 P2

- **状态**：真实 model stage 已完成，结果 `non_ready`；人工 blind review 未导入。
- **授权与环境**：用户于 2026-09-01 明确批准付费 `deepseek-v4-flash`；runner 只使用一个无旅程的
  disposable interaction project，完成后已软归档。现有真实旅程未读、未改。
- **冻结输入**：官方当前 1M context；本地 7 个可执行 dev case 使用 400K verified input ceiling，
  contract blocker case 继续保持 uncalibrated 且不发请求。dataset hash
  `718fe7703db9acb16703123f330e5791751c377aa082014d3a4b48dbfde0b8fd`，profile hash
  `e6787e9bbdd5c9dec1b344261c6698f29ace19b44b879be2f8fff042e398cf83`。
- **结果**：35/35 candidate 完成；exact probe 为 A `2/7`、B `5/7`、C `2/7`、D `7/7`、E `2/7`；
  所有 arm 的 branch/future/owner/historical/stale sentinel 命中均为 0。raw story usage 记录到
  1,454,035 input、32,684 output token；probe usage 在本轮 runner 中漏计，不能当作总费用。
- **解释边界**：部分 exact failure 是语义正确但未复制 canonical 短值，另一些确实遗漏“不能负重”、
  “仍保留戒心”或“尚未完成”等关键限定。不得事后把全部 mismatch 归为评分器误报，也不得用 D 的
  7/7 上限替代 extracted overlay 与人工叙事质量证据。
- **决定**：B 虽相对 A 有方向性提升，但未通过全硬门；C 未相对 B 提升。生产继续只用 A，不注入
  segment/raw recall；D 只保留 eval gold upper bound，P2 schema 不启动。
- **证据 hash**：原始 model report stable hash
  `f1a70577381e2ed2d4e765299e48f366a26c4e3bfd22565377caa35ac6cf35a8`，candidate hash
  `6eb08e7e18f9c962471c93b5621f1ae0729cee30b94e4dc918730fa90cc66b23`，arm-map hash
  `8ba385f6be2c52fd2d0af708605930777d617de459fefdd723371b25a55894eb`；详细 prose/cache 保持 ignored。
- **重开条件**：先修订不泄漏 gold 的 canonical-choice probe 或冻结语义等价规则，再获批运行新版本；
  同时导入校准人工盲评。不能在旧结果上调字符串阈值让 C 过门。

### MEM-DEC-075：provider usage 必须同时覆盖 probe 与 story，缺一层就 unavailable

- **状态**：runner 与共享 structured diagnostics 已修复；本轮旧 cache 不回填不存在的 probe usage。
- **发现**：原 model report 把 streaming story usage 当成全部 provider usage，漏掉 35 个 probe 及观测到的
  8 次首发 JSON/schema repair，却错误标 `provider_input_output_usage.available=true`。
- **升级**：`structured_usage` 无论 provider 是否返回 cache 明细，都记录安全的 prompt/completion/total token；
  runner 为 probe 聚合 call/repair/usage。只有每个 candidate 的 probe 与 story usage 都完整时，总 usage 才
  available；legacy cache 缺字段时明确 unavailable，不为补账自动重跑付费模型。
- **兼容性**：只增加内部诊断计数字段，不改变 provider request、业务 schema、API、task 或浏览器 wire。
- **验证**：无 cache 明细、截断修复、schema 修复、cache hit 与 legacy cache-only 路径；任何缺失不得变成 0。

### MEM-DEC-076：v2 使用 oracle-only 语义规则重跑；B 有方向性增益，C 仍不过门

- **状态**：v2 runner 与一次获批 DeepSeek V4 Flash dev model stage 已完成；等待校准人工盲评。
- **旧问题**：v1 要求模型逐字复制 canonical 短值，既把“米娅只能操纵水流，不能使用火焰”误判，
  又把方向性事实 accuracy 错当成全部 arm 共用的硬门。旧报告继续保留，不能在原 hash 上改分。
- **升级**：`rp-long-memory-v2` 把每个 fact 的 accepted value、必含语义组、矛盾词和 hard 标记保存在
  oracle-only fixture；模型只看到事实 key，不看到 scorer 规则。报告将一般事实命中作为方向指标，
  仅让明确手工修正、answer shape 与安全 sentinel 进入硬门。模型 cache 保存原始 probe/story；
  cache-only replay 每次用当前确定性 scorer 重算，不信任旧 scorer 字段，也不打开 provider client。
- **scorer 修复**：首次 v2 报告发现禁止词“知道门后的真相”是允许短语“不知道门后的真相”的子串。
  matcher 改为先匹配正向语义片段并从剩余文本检查矛盾；同一 35 份原始输出 cache-only 重评分，
  没有重复付费。稳定 replay 连跑两次 hash 相同。
- **冻结输入**：官方规格于 2026-09-01 再核验为 1M context；eval 继续使用 400K verified input
  ceiling。dataset hash `5f9477823ddef29ea5ff57b295473ead4404d71bfe35bfa44f03035cd83cbefc`，
  compiler hash `167680d31dae3ac0cf528221e373c3ae61082e6e9d755e9a6bcdb323f41fe29a`，
  story Prompt hash `dc7b9cc51cd15b7cedaceac7997938d6876061551aad515a7a9855a6821a86aa`，
  probe Prompt hash `62c245f09a8fa2d9eae84c184451f40cd500b32965fc61c6f93e641733f7a2fd`。
- **结果**：35/35 candidate 完成；A/B/C/D/E 的 case pass 分别为 `3/7`、`5/7`、`5/7`、
  `6/7`、`3/7`，fact match 分别为 `5/11`、`9/11`、`9/11`、`10/11`、`7/11`；
  manual hard retention `35/35`，全部 branch/future/owner/historical/stale sentinel 命中为 0。
  probe + story usage 完整为 3,589,834 input、48,376 output、3,638,210 total token，
  probe repair 9 次；provider 未提供可用 cache token 明细或可信请求价格。
- **盲评 artifact**：35 行候选、7 个 blind group，候选不含 arm/case/run；candidate hash
  `e077858024bc6dd9e2104c55324054bf4c40394b5447f49d35d60dd6a686a531`，arm-map hash
  `171c1785201cf159cd49bab90f0b825de457aad5cd4a6bf1af5ab32c8eb685e5`，review-template hash
  `3540fed833d698d83e429a67a3d05e8e35ff8e5af9fb9e3d0ee8539232bea3f9`，稳定报告 hash
  `5ab7db82a2f08b76088fedc94b669e02f01de2a75a27782f0970c5599d5b3d83`。
- **人工校准包**：8 个固定正/反例只含合成文本；候选包不含 constraint/答案。reference hash
  `a575aec12b59a12bf88391a64261069856cfa7a392252778133fae260c28fbb4`，rubric hash
  `ec81667f380883f22b869df906897f9ddb90a4ac3865025d175ae5422c558c6c`，blind calibration
  candidate hash `b5f4bad3096f93699db79344245f1db89ef02b0f02bc4f64bfa93f49e0f8c1af`，
  blank template hash `cc0ea5d42d2edc97f040ba84196b252376495b057de85ea465b83a2b1635a818`。
  review 只在同一 reviewer 覆盖全部正式候选与校准项、并命中所有预冻结约束时标 calibrated。
- **决定**：B 相对 A 有方向性事实提升且未破坏硬门，但在校准人工盲评证明叙事非退化前继续禁用。
  C 与 B 的 case/fact 命中完全持平，且失败场景互换，不满足 `C > B`，保持淘汰候选。
  D 只比 C 多 1 fact/1 case，且仍有 ability miss；没有 extracted D、manual recovery 和人工盲评，
  不请求/不落 P2 memory schema。临时 interaction project 无旅程，完成后已软归档。
- **重开条件**：先完成 blind packet 的校准人工评分。只有 B 叙事非退化，才实现 summary recall；
  C 需新 selector/compiler version 在未看 holdout 前提出并重新配对。P2 仍按 12.7 的 gold/extracted/
  recovery 全门执行，不能用本轮 D 的 aggregate 数字越过。

### MEM-DEC-077：holdout 先冻结契约与阈值门，不在人工 review 前调用模型

- **状态**：holdout contract、冻结配置生成器与 test fail-closed 门已实现；test model 尚未运行。
- **holdout 契约**：committed `rp-long-memory-v2-holdout.jsonl` 含 8 个只属于 `test` 的独立
  scenario group，与 dev group 无交集，离线 compile 为 103/103。committed synthetic profile 文件 hash
  `0e5e5f034432e878a5ad375fd6ddb5209cf1bc6d950d642b30f991664b06ff5b`；ignored 的当前
  DeepSeek V4 Flash verified-profile 副本 hash
  `641abcc7d7d0eb86128503af520a69089629f7d8d2616c6e448ee90a762965ff`。
- **冻结规则**：只有完整 ready 的 dev model stage、全部硬门和同 reviewer 的校准盲评通过后才可生成
  hash-valid threshold config。B 相对 A、C 相对 B 逐级要求 case pass `+1`、fact match `+1`、blind
  mean 不退化且 candidate severe spoiler 为 0；前一层不过门时不冻结后一层。当前 dev 数字只可能让 B
  进入候选，C 因 case/fact 均为 `+0` 不能进入。
- **重放与一次性边界**：config 固定 test dataset、compiler、story/probe Prompt、semantic scorer、
  project profile、runs、reviewer set 及 dev model/review stable report hash；时间戳不进入 config identity，
  因此相同评分重新 export 不能生成第二个 holdout 身份。candidate ID、arm 顺序与 model cache key 额外绑定 config hash。
  test 侧缺 config、hash/profile/runs 不符或 model stage 不完整时均失败关闭，不打开 provider client；
  同 config hash 一旦已有 test report，只允许 cache-only 确定性重放，不允许再次调用 provider。
- **决定**：人工 review 未导入前不生成 threshold config，也不消费已冻结 holdout 的任何模型结果。
  test 通过后最多形成 `synthetic_contract_and_directional_memory_eval` 的质量证据，仍不等于真实用户验证。

## 7. 物理存储候选：P2 未批准，segment JSONB 已淘汰

### 7.1 已淘汰 A：给 `interaction_summary_segments` 增加 `memory_delta_json`

原始优点：天然拥有 segment 范围、path hash、ordinal 和 producer；只需一个可空 JSONB 列。

淘汰原因：按 object key 查询、单项修复和跨 segment 折叠较弱；更关键的是，segment 是一段不变
episode 的唯一索引，而对象增量必须能在新 manual overview lineage 下对同一 episode 重新推导。
把多个推导版本塞进同一 JSONB、覆写原值或复制 segment 都破坏其中一个边界。见 MEM-DEC-024。

### 7.2 P2 保留的语义候选：append-only interaction memory stream

无论物理采用一表还是 generation header + fact rows，都必须表达同一条 journey stream 中的
fact operations、manual barrier 与 recovery commit，不能依赖 task status。单表最小字段候选：

- `novel_id`, `journey_id`；
- `record_kind=fact|manual_barrier|recovery_commit`；
- `start_node_id`, `end_node_id`, `effective_node_id`, `path_hash`；
- fact row：`object_key`, `object_origin`, `fact_kind`, `field_key`, `operation`, `value_json`, `target_object_key`；
- `source_ranges`, `source_revision_id`, `source_reference_key`, `confidence`, `usable`；
- `derivation_key`, `operation_ordinal`（服务端幂等身份，不由模型任意生成）；
- `based_on_overview_revision_id`, `source_context_epoch`, `producer`, `schema_version`；
- control row：`manual_revision_id`, `candidate_snapshot_hash`, `output_hash`, `expected_operation_count`；
- `created_at`（审计时间，不代表故事内有效时间）。

单表优点：一次 append-only transaction 即可发布 facts + commit，重放源只有一处。问题是 control row
会让 object 字段可空并依赖较多 CHECK 约束。

两表备选：`interaction_memory_generations` 保存 barrier/commit header，`interaction_memory_deltas` 只存
fact rows 并 FK generation。约束更直观，但增加一张表、生命周期与 join。两者都需要 migration、索引、
幂等安装、重放和删除/并发测试；若评测表明对象增量收益有限，它们都没有存在价值。

### 7.3 当前决定

P0/P1 不改 schema。完成压缩 + segment recall 基线后，用固定回放比较：

- A：overview + raw tail；
- B：A + relevant segment summaries；
- C：B + 命中范围的有界原始节点回读；
- D：C + 由夹具 gold operations 编译的临时 structured delta；

只有 D 在对象状态、关系、物品、位置或承诺连续性上稳定优于 C，且没有提高分支泄漏/错误固化，
才请求用户确认 P2 schema。先做“业务 memory stream 对完全不要结构化层”的 deletion test；结构化层
确有价值后，再以约束清晰度和原子发布证据比较“一张 `record_kind` 表”与“generation + fact 两表”。
未获确认前不建表。

明确拒绝把业务 delta 塞入现有 `producer` JSON。`producer` 只保存脱敏来源与调用统计，混入对象状态会
破坏 provenance 边界。

## 8. 分阶段实施计划

### Phase P0：长程评测与现状基线（offline 已实现；无生产行为、无 schema）

候选最小实现面：独立 `backend/evals/rp_long_memory.py`、一份合成 JSONL、一份窄测试与
一个 Make target。`rp_context.py`、通用 eval schema 和生产 API/schema/wire 均不改。实现前再做
deletion test；若一个 runner 模块能承担，不新增抽象层。

1. 先在一个模块内实现 strict Pydantic case、versioned templates、DAG/materialization 与 canonical hashes；
   只加一份测试，不接 DB/LLM/通用 EvalSuite。
2. 提交 versioned `rp-long-memory` synthetic contract JSONL；v1 保留历史 exact-string 协议，v2
   使用 oracle-only semantic matcher；均按“事实到 probe 的 beat 距离”与“目标 token”分层，
   在早、中、晚位置注入：
   - 身份与能力边界；
   - 物品归属、人物位置和伤势；
   - 关系变化与承诺；
   - 传闻、误信和角色知识；
   - 用户明确纠正；
   - 一个已拒绝 sibling sentinel；
   - 一个 source cutoff 之后的剧透 sentinel。
3. 实现 `compile` 子命令：A 使用 current production baseline，B/C/D/E 使用明确标识的 eval reference；
   跑 12.9～12.12 全部 hard assertions，原子写报告并接一个 `make eval-rp-long-memory`。
4. 先让 committed dataset + offline compile 在 CI 可重复通过；报告仍写 model/review unavailable，
   `quality_claim_allowed=false`。不过门不接付费模型。
5. 再实现 opt-in `model`：要求 disposable interaction project、显式费用授权、同 project profile 配对 arms、
   content-addressed cache；先 strict fact probe，后 production-shaped story candidate。E 只在可容纳档运行。
6. 最后实现 `review`：确定性 arm 顺序/opaque candidate IDs、独立 arm-map、完整 0–4 rubric 和 spoiler flag；
   没有校准的 LLM judge。
7. 记录 provider 返回的 cache read/write tokens 或可用等价指标，测量动态召回是否抵消前缀
   缓存收益；不可用时显式记录 `unavailable`。
8. 只用 dev 冻结 slot/profile/compaction/统计门及 config hash，再运行 test 一次；单变量变化使用同 case/
   model/profile 重新配对，不复用不相容结果。
9. 不把静态 Pydantic 测试、单次真实生成、未校准 LLM judge 或完成的自动门禁当作
   真实用户长期不出戏的结论。

退出证据：基线报告能逐案、按固定顺序定位夹具错误、安全泄漏、记忆安装/幂等冲突、记忆内容错误、
概要遗漏、segment 候选遗漏、raw rehydration 遗漏、overlay 遗漏、模型忽略与叙事退化；
且同一报告保留成本/cache/延迟证据。

### Phase P1：压缩路线补全（部分已实现；零新增 memory schema/wire）

受影响：`interaction/generation.py`、repositories/services、Prompt/tests；source retrieval 通过既有
Evidence facade。

当前落地 1、4、6、9、10，并完成八段 checkpoint consumer deletion audit。v2 证明 B 相对 A 有方向性
事实提升，但人工盲评尚未导入；C 与 B 持平。2、3、5、7、8 仍受真实配对增益门约束，未向生产
Prompt 注入；6 已经用户授权并通过 shared infrastructure/project snapshot 唯一 seam 实现。
下列编号保留完整目标，不把未过门候选写成已支持能力。

1. source query 使用有界旅程态，不只使用最新输入。
2. 从现有 summary segments 过滤当前路径有效项，先选择少量“相关往事”索引，再对高置信命中范围
   有界回读原始节点；候选数与 token budget 独立。
3. 相关概要和历史原文以明确的“过去事件证据”数据块注入，不重排为当前 user/assistant 回合。
   回读优先保留完整 node；超预算时只取带 node/role/offset 的完整自然段，不跨 node 拼无来源窗口。
4. 手工 rebase 需重放已有 path/end tail 时，segment 安装必须幂等复用已有 episode；
   新 overview 仍必须从 manual revision 派生。这一 PostgreSQL 实例在启用 segment recall 前先补。
5. 在 interaction 内建立一次调用私有的最小 Prompt Pack；先保护 hard rules、manual/required、raw tail/current
   input 和 required source，再给 active state、episode、optional source、segment index 分独立槽。
   分配顺序与渲染顺序分开，事实冲突由显式 authority 裁决。
6. P0 先冻结 eval-local capability profiles；P1 生产通过现有 infrastructure/project LLM profile seam 派生
   hard/compact/output/margin。估算取当前字符法与 shared tokenizer 的较大值；unknown model 只走保守
   short fallback。profile version/hash 随现有 project LLM execution snapshot 冻结；这是 shared/infrastructure
   契约变化，进入实现前单独请求架构确认，interaction 不维护平行 registry/snapshot。
7. interaction 先计算固定成本，再把剩余 source slot 作为可选内部参数传给 Evidence，且不超过现有 16K；
   required source 放不下 blocker。P1 不解析 source Markdown，也不扩大浏览器 wire。
8. 同 segment 的 raw node 已回读时不再渲染 summary；其他跨层只做确定性 ref/key 去重。candidate 激活
   采用一次旅程态 query + 一跳关系扩展，不递归、不新增模型调用。
9. 紧急整理先用 authority-aware selector 选最新兼容 overview，再从未覆盖 raw prefix 做 whole-node 有界
   rolling fold；segments 只作 coverage/index，不作为 reducer 文本。始终保留当前 request + 近期 raw suffix，
   不先发送 530K 全路径，也不启用 provider silent head truncation。
10. 为“记住这一点”设计最低摩擦入口：首版复用 `must_remember` 与现有 overview 更新 CAS，不新增 endpoint；
   点击后只预填自然语言并由用户保存，不自动发送或静默写入。

退出证据：分别证明 B（summary recall）和 C（raw rehydration）的增益；任一层未改善长程事实连续性，
或使 branch/spoiler/stale sentinel 泄漏、cache/延迟成本失衡，就撤销该层。手工 rebase 下重放
同一 tail 还必须证明 segment 幂等、新 automatic overview 从 manual revision 派生且旧派生记忆零注入。

### Phase P2：结构化对象覆盖层实验（已获条件授权；过门后才落 ADR/migration）

受影响：interaction 数据模型、Prompt/schema、任务 finalizer、数据库设计；只读消费 source projection。

1. 先在 eval 内用 gold operations 编译临时 structured delta，验证状态层本身是否优于
   已经能回读原文的 C；不过门就停止。
2. gold D 过门后再试真实抽取 D；它也过门后，才对“新增 append-only memory stream”
   与“不要结构化层”做 deletion test，再比较单表与 generation + fact 两表。
3. 在内部 frozen source manifest 中保留已确认 `identity_terms` 与 alias status/provenance；
   candidate alias 可留作检索线索，不进 deterministic identity resolver。当前浏览器对象摘要 wire 不因此扩大。
4. 整理调用同时生成封闭事实 operation；输入只给本次调用的 opaque candidate refs 和受限 `new`
   临时句柄。服务端重验 evidence range、path、overview lineage、epoch、schema、candidate membership
   与 derivation idempotency；模型不能自由伪造 UUID/object key。
5. 编译冻结 source handles + path-valid local `create` + 当前 authority lineage operations 的组合对象视图，
   只注入本轮相关对象；忽略项、未来原作对象、不可见 endpoint 和其他 sibling delta 不得出现。
6. 允许的 source revision 升级按内部 `target_id` 重建同一旅程 source handle 并重验可见性；
   新 `reference_key` 只更新证据编译，不批量改写旧 delta identity。
7. 手工 overview 保存事务以作者看见的 base leaf/path 冻结 candidate snapshot；同事务表达
   `manual_barrier` 并推进现有 overview epoch。整个旧 projection 进入 `degraded_manual_barrier`；
   七区 diff 只作 reconcile 证据/排序，不允许未处置旧 fact 跨过新 authority。
8. 运行 bounded `manual_reconcile`：输入只含旧/新 sections 与服务端冻结的 active candidates；可按
   预算先尝试一次调用，只有硬超限才按 identity → field → relation 的固定 object batch 处理；最终对每个候选要求
   `keep/suppress/replace/uncertain`，集合外 invalidation、模型 ID、遗漏 disposition 一律失败关闭。
9. batch 只写 lease-fenced 私有 checkpoint；所有候选、temporal labels、relation 依赖与 hashes 通过后，
   才在一个事务内追加补偿 operation + `recovery_commit` 并解除整个 barrier。task done 不代表已发布。
10. reconcile finalize 按 manual anchor/path ancestry，而非当前 selection 安装；用户继续原分支或切 sibling
    不使安全结果越界。source epoch、同 anchor 新 manual authority 或 candidate hash 变化则 stale。
11. projection 按 effective node/ancestry 而非 `created_at` 折叠；后序明确 transition 可胜出，回述过去的
    contradiction 不得自动覆盖 manual 值。full raw rebuild 只跑诊断臂。
12. 失败/歧义 delta 可舍弃并重建；不得让对象抽取或 reconcile 失败阻断已经成功的故事或 overview。

退出证据：gold D 与 extracted D 都对对象状态/关系/物品/位置/承诺的确定性断言
稳定优于 C；对象身份补充协议的硬门全通过；global manual barrier 后的 recovery 恢复仍有效状态、
零复活 stale facts；人工盲评不退化，错误固化率不增加。

### Phase P3：用户可理解的记忆控制与恢复

受影响：`InteractionView.vue`、现有回顾 drawer；是否新增 wire 取决于 P2 结果。

1. 普通用户只看到“回顾”“相关往事”“记住这一点”“最近剧情尚未整理”。
2. 不新增对象库一级入口；若需要诊断，放在“更多 → 记忆使用情况”次级入口，只显示自然语言名称、来源发展和
   “为什么本轮记得它”。
3. 保存前明确说明“保存后会按这份回顾重新整理长期记忆”；manual revision 落库后显示
   “回顾已保存；正在按修改整理长期记忆”。
4. reconcile 失败不把已成功保存的回顾显示成失败；显示“回顾已生效，部分长期记忆暂以回顾为准”，
   允许继续写作和稍后重试。分支切换、资料版本升级、409 与离开恢复均保留草稿和真实反馈。
5. 390px 下 composer 不被记忆入口挤压；按钮触控目标、焦点恢复和键盘流保持现有基线。

退出证据：RP 用户无需理解作者对象库即可完成“发现记错 → 纠正 → 继续 → 重新进入仍生效”。

### Phase P4：仅在真实规模触发时归一化或索引

触发条件任一成立才讨论：

- 单旅程有效 delta 达到真实测量规模后，按路径重放超过预算；
- 简单 segment/object 词面召回在固定回放中持续漏召，且现有 Evidence 索引实验显著改善；
- 用户确实需要按人物/物品浏览长期旅程，而不是只在故事中继续；
- append-only delta 在真实规模下的重放/查询超过冻结预算，且窄索引不足以解决。

在触发前不新增 interaction 专用向量库、知识图谱、通用规则引擎、对象管理工作台或自治记忆 Agent。

## 9. 验证矩阵

| 风险 | 最小证明 |
|---|---|
| 兄弟分支污染 | 未选 sibling sentinel 永不进入 overview、segment recall、delta、source query 或故事输出 |
| 手工修正复活旧事实 | 保存修正后，晚到 overview/delta 不晋升；非当前手工 lineage 的旧 delta 不编译 |
| 手工 rebase 重放同一 tail | 已有 path/end segment 幂等复用；新 overview/delta 从 manual revision 派生，旧派生项零注入 |
| 手工 barrier 后伪称对象库恢复 | recovery 前明确 degraded 并退回 overview/tail/source；recovery 后应保留状态恢复、stale 零复活 |
| 无关事实被退休 | invalidation 候选先按旅程、路径、authority、object/field 或 relation endpoints 限定；wrong-object retirement 为 0 |
| source 未来泄漏 | 章节/offset 截止后的对象、关系、知识和原文 sentinel 全部不可检索 |
| 跨旅程/跨 owner | 所有读取同时带 owner、consumer novel、journey；错误组合统一 fail-closed |
| 摘要错误固化 | delta 必须有原始节点 evidence；校验失败只丢 delta，不污染路径 |
| 历史指令回放 | rehydrated 用户文本只作为带来源的过去事件数据，不能取得当前指令或工具权限 |
| 本地对象串身份 | 模型只能选择服务端给出的 existing key 或声明 new；不能伪造 source/local ID |
| source 版本升级换引用键 | 同 `target_id` 在新 manifest 中仍得到同一旅程 source handle；旧 delta 不批量改写 |
| 同名/别名误合并 | source/local 同名、两个 local 同名、candidate alias 与高语义相似都不自动绑定 |
| branch-local 对象泄漏 | 分叉后 `create` 及其 relation 只在包含该 effective node 的后代路径存在；分叉前 create 在两边共享 |
| 伪 source provenance | unbound 旅程和 cutoff 之后的名称永不产生 source handle；有节点证据时也只能是 local |
| 模型热切换 | 旧模型产出的模型中立 segment/delta 可复用；provider 私有 state 不成为依赖 |
| 超限恢复 | 紧急整理完成后恢复同一 attempt；失败保留用户输入和完整路径 |
| 延迟/费用 | 记录 story、summary、retrieval/delta 的调用数、输入/输出/cache usage 和端到端延迟 |
| 产品可理解性 | 用户不接触 token/hash/object key；能发现、纠正并确认保存结果 |

建议的离线对照臂：

1. `overview_tail`：当前方案；
2. `overview_tail_segments`：加相关往事概要；
3. `overview_tail_rehydrated`：命中概要后有界回读原始节点；
4. `hybrid_overlay_gold`：再加由夹具事实生成的临时 structured delta，先测架构价值；
5. `full_raw_reference`：只作能容纳档的无压缩参照，不作为生产候选或当然的质量上界。

`hybrid_overlay_extracted`、`oracle_segment`、`oracle_raw_node` 和定向 `summary_self_check` 是后续
诊断臂，不增加主对照臂数量。

评价维度：角色声音、能力边界、关系一致、时间/位置、物品归属、人物知识、未决线索、用户修正、
原作剧透、分支泄漏、叙事自然度、调用成本和延迟。自动评分只能筛查；人物质感和是否出戏使用随机
盲评，最终仍需真实用户观察。

## 10. 当前开放问题

1. P1 的简单 segment 索引在中文代词和隐喻场景下是否足够；回读单位已收窄为完整 node，
   超预算时才用带 role/offset 的完整自然段，但自然段最小上下文和成对回读阈值仍需回放回答。
2. “记住这一点”在 P2 后是否需要形成 `manual_note` delta；先保持自然语言，不让用户选择数据库字段。
3. structured delta 的 evidence 最小单位使用消息 node + char offsets，还是复用 SourceRangeRef 形状的
   interaction-local variant；不能直接复用 Writing draft 语义。
4. 手工 overview 的恢复点已收敛为“第一个 CAS 有效的 automatic descendant”。当前尚未证明的是：
   automatic descendant 已为同 path/end 写入 segment 时，manual rebase 重放如何幂等复用 episode 而不触发唯一约束。
5. 双 namespace 语义已固定，但 source handle 的具体编码还需在 P2 二选一：可验证的 tagged string
   或服务端确定性 UUID。默认不建 mapping table；只有编码无法支持升级/审计时才重开。
6. 结构化层若只提高检索解释性、未提高连续性，是否仍值得保留；默认答案是否，除非真实用户需要浏览。
7. 当前 frozen `reference_manifest.aliases` 丢失 alias status。P2 前应以哪个现有 World facade 输出形成
   已确认 `identity_terms`，并在不扩大当前浏览器 wire 的前提下冻结其状态证据。
8. `summary_self_check` 是否能够修复主要 `overview_loss`，以及其改善是否足以覆盖第二次调用的
   延迟、费用和 cache 损失；在 holdout 前不设为生产常态。
9. 同一 selected path 上长期存在两个同名同类对象时，何时值得给用户一个轻量“你指的是谁”
   决议入口。默认不建全量对象管理台；只在重复 ambiguity 实际阻断长期状态时触发。
10. 只增加新句、没有删除或改写的 save 是否可缩窄 global barrier。默认不能；只有 12.10 证明一个
    确定性 changed-span → candidate 规则无漏判，才优化范围，section 名称本身不够。
11. 现有 overview/background-task read model 能否同时准确表达“回顾已保存”和“长期记忆整理失败”。
    若不能，P2/P3 只讨论一个 additive 用户态，不复用 `overview_failure` 制造错误含义。
12. P2 语义过门后，barrier/recovery control record 与 fact rows 采用一张 `record_kind` 表还是 generation
    header + fact 两表；以 CHECK/FK 清晰度、零操作 commit 和原子发布证明做 deletion test，不凭少一张表拍板。
13. bounded reconcile 对没有出现在新 manual 文本中的旧事实能否给出可靠 `keep` 证据。若 gold
    可以、extracted 不可以，保持 suppression/degraded；不把 omission 默认为 keep。
14. candidate snapshot canonical bytes 的字段顺序、JSON 数值/Unicode 规范和 compiler version 如何冻结；
    默认复用仓库现有 canonical hash helper，只有不能覆盖嵌套 value 时才加窄实现。
15. source epoch 改变时是否值得只挽救 local-only batch。默认整次 stale 并重跑；只有真实 source 升级频率
    与 reconcile 成本证明浪费明显，才引入分区 CAS。
16. manual-derived field 的 forward transition 分类能否稳定区分“后来改变”与“后来回述过去”。若
    extracted temporal gate 不过，首版 manual 值持续到下一次 manual save，不增加第二个 judge。
17. capability profile 首批只校准 `deepseek-v4-flash`；unknown/legacy short fallback 已冻结。
    尚未解决的是 Kimi K3：只有真实长上下文 calibration 门通过后才新增档案，不能沿用 DeepSeek。
18. `active_state / episode_evidence / source_optional / segment_index` 的 slot cap 与空槽回流比例。它们是
    12.11 dev 参数；在 holdout 前冻结，不写成前端设置。
19. Evidence source facade 的可选 budget 参数应只表达总上限，还是还需返回 required/optional token 分解。
    P1 默认只加总上限；只有 required blocker 无法解释或调试时才扩 contract。
20. P2 是否值得让 source contract 返回 typed items 以去重 source base 与 overlay。默认不做；先用 12.11
    duplicate token ratio 和 gold typed variant 证明收益，严禁解析 rendered Markdown 建隐式契约。
21. protected recent suffix 的 token 目标、最少对话 beat 与不同 request kind 的强制节点集合；它们由 12.12
    dev 回放冻结，不用“最近 N 条”一个常量覆盖 send/regenerate/continue/see-sea。
22. summary chunk ceiling、min savings 和单 story task 最大 passes/cost/time。默认按 capability profile 派生并
    设质量上限，不因 1M 窗口就把 500K raw 塞给一次 summary。
23. existing segment 同 end/path 但 start 不同的 producer 应如何记录实际 raw fold range。默认只在新 overview
    producer 留脱敏 range/hash，不修改 episode segment；若审计不足再评独立 derivation ref。
24. authority-aware overview selector 是否能完全替代当前 `_best_overview_for_path()`。默认共用一处；若现有
    branch UI 确实需要“展示最远旧 revision”而非 active authority，必须拆成明确 read-only 历史查询，不能混用。
25. single old node 超 summary ceiling 的真实发生率。默认 blocker；只有真实用户数据证明 100K 单消息常见且
    换模型不可行，才设计按完整自然段的 node-internal checkpoint。
26. committed v1 的最小 case/group 数与 dev/test 比例。先覆盖每个 hard scenario 至少一例，不在看结果前
    宣称统计功效；方向性阈值由更大的 local dev generation 冻结。
27. CLI model stage 如何在本地正式建立 account principal 并验证 disposable interaction project，而不复用
    浏览器 owner cookie。实现前沿用当前 `ProjectStructuredExecutor` 路径做 read-only spike；若 principal 不成立，
    停止并补稳定 eval facade，不用 system 身份绕过 owner。
28. strict fact probe 的最小 response schema：默认 `probe_id/value/unknown`，不要求模型回显 object UUID、
    evidence chain 或自由解释；只有根因定位不足时才加安全的 candidate ref。
29. arm-map 是单独 JSON 还是由 review export 延迟生成。默认单独 ignored JSON + hash；不加加密/签名，
    因为它是流程盲化而非敌对安全边界。
30. 首个 committed contract dataset 是否命名 `baseline`。默认文件可放既有 baselines 目录，但报告必须标
    `contract_candidate`；只有 frozen test+review 过门后才生成独立 quality baseline version。

## 11. 文档与交付影响

当前实现与边界：

- P0 standalone runner、contract JSONL、A–E materializer、compile/model/review CLI、原子报告、
  content-addressed cache、盲化 arm-map、自契约测试和 Make 入口均已落地；不修改通用 `EvalSuite`。
- offline compile 当前为 `status=ready`、103/103 hard assertions、0 个 hard failure；真实 DeepSeek
  v2 model stage 的硬门为 `ready`、35/35 manual retention、0 sentinel leak，A/B/C/D/E 的语义
  case pass 为 3/5/5/6/3。人工盲评仍 unavailable，`quality_claim_allowed=false`。
- P1 已落地 source 旅程态 query、manual-authority selector、bounded oldest-prefix reducer、protected
  raw suffix、净缩减门、最多 4 pass、同 segment 幂等复用、“记住这一点”和 checkpoint marker 删除。
- 评审收口已让当前正文检索按 draft/hash manifest 排除旧稿 chunk，冻结 manifest 批量回读避免 N+1；
  source fence、空参考包、歧义状态和 migration downgrade 均失败关闭。RP 页在完整整理前明确确认模型
  额度，轮询失败退避且恢复后清除旧错误，资料对象类型和失败原因使用读者可理解的文案。
- long-memory 本身没有新增 API、memory schema 或 browser wire；历史 checkpoint nullable 列保留兼容。
  用户已授权继续到必要 migration/ADR，但 P2 仍需 gold/extracted/recovery 与盲评过门，未进入实现。
- 当前窄证据为 P0 runner `43 passed`、capability/project/interaction `97 passed`、P1/source/evidence/import
  `98 passed`、InteractionView
  `45 passed`，并在 fresh PostgreSQL 17 + pgvector 空库验证 manual rebase segment 复用 `1 passed`。
  本轮最终 `test-fast-coverage` 为 `4828 passed, 12 skipped`、coverage `86.13%`；`eval-fast`
  `137 passed`，完整前端 `2141 passed`；fresh PostgreSQL source-version/manual-rebase `3 passed`，
  独立端口 RP Playwright `6 passed`，专用 PostgreSQL migration `head → previous → head` 通过。
  生产构建、Ruff、ESLint、secret hygiene、Prompt contract、受改 Python format、
  `git diff --check` 与带显式无影响说明的 `docs-check BASE_REF=origin/main` 均通过。
- B/C segment recall、raw rehydration、统一 Prompt Pack 与 typed overlay 均未过真实 paired
  model/review 门，因此没有注入生产 Prompt。capability profile 已经 shared infrastructure/project
  snapshot 唯一 seam 冻结并通过相关测试，不增加浏览器 wire。
- 本地自动门禁与付费 model run 不构成真实用户长期不出戏验证；没有校准盲评前，
  不形成质量结论。
- ADR：本阶段不新增；P2 若通过 eval 并准备落 schema，再请求用户确认并创建/更新 ADR。

## 12. P0 长记忆评测协议 v1/v2

本节是已落地的 P0 runner 协议。v1 保留 exact-string 历史证据，v2 使用不进入模型 Prompt 的
确定性语义 oracle。offline compile 只回答“夹具、pack 与安全门是否正确”；DeepSeek V4 Flash
v2 dev model run 已给出方向性证据，但 calibrated human review 未导入，
仍不能形成“哪一臂已可上线”的质量结论。

### 12.1 评测对象与不评测的东西

- 评测对象是同一 selected path 上，不同记忆编译臂对“下一个 RP 回合”的影响。
- A–D 固定同一硬规则、当前用户输入、source context、raw tail、输出预留、provider/model/
  profile 和采样参数；只替换历史记忆区。为某臂保留的空槽不回填其他内容，避免偷换预算。
- E 使用完整 selected raw path 代替概要/召回区，其余项保持一致；超窗口即不可用。
- 评测不证明用户愿意重复使用，不证明人物已经“像真人”，不以合成数据替代真实试用。

### 12.2 合成 JSONL 契约

每行一个 case，Pydantic `extra="forbid"`，最小字段为：

- `case_id`, `schema_version`, `generator_version`, `seed`, `split=dev|test`；
- `length`：`fact_distance_beats`, `target_history_tokens`；
- `scenario_kind`：下述六个通用家族之一，或 12.9～12.13 的 identity/recovery/budget/compaction/runner 补充家族；
- `initial_facts`：稳定 key 与初始值；
- `events`：`event_id`, `beat`, `branch`, 封闭 operation，以及合成消息 `template_id/values`；
- `branch_plan`：当前 leaf、未选 sibling 和共享 ancestor；
- `manual_revisions`：明确修正、用户编辑时冻结的 base/coverage、生效 beat，以及该期间 tail
  是否已被 automatic descendant 整理；
- `probe`：当前输入模板和要观察的事实；
- `oracle`：`expected_fact_keys`, `forbidden_fact_keys`, sentinel，以及期望 segment/node ID；
- source-bound case 额外使用合成 source revision/cutoff 和逻辑 ref，不放本地路径或作品原文。

模板生成器必须对同一 version + seed 产生字节级一致的消息。提交数据不保存大段正文、
用户资料、secret 或本地绝对路径。真实模型输出、盲评包和详细轨迹使用现有忽略目录：
`backend/evals/datasets/local/`、`backend/evals/artifacts/` 或 `backend/evals/.cache/`。

### 12.3 六个场景家族与 sentinel

1. **身份/能力边界**：稳定别名、能做/不能做的事，在早期给出并经过长距离 probe。
2. **物品/位置/伤势**：创建、转移、丢失、移动或恢复，probe 要求使用最新有效值。
3. **关系/承诺/未决事项**：关系变化、尚未履行承诺与已关闭线索分开。
4. **人物知识/传闻/source cutoff**：该角色所知、作者真相与截止点之后的信息分开。
5. **用户修正/过期事实**：用户明确否定旧值，验证 manual overview lineage barrier；
   至少一组 case 在用户编辑期间先让 automatic descendant 整理新 tail，再从冻结旧 base 保存，
   要求同一 episode 幂等复用、新权威链吸收 tail 且旧派生状态零注入。
6. **分支分歧**：同一 ancestor 后两个 sibling 发生相反变化，只有 selected sibling 可用。

每个相关 case 使用不可自然猜中的唯一 token：

- `branch_only_sentinel`：未选 sibling 专有，不得进入编译包或输出；
- `future_source_sentinel`：source cutoff 之后专有，不得进入编译包或输出；
- `other_owner_sentinel`：同名其他 owner/novel 专有，只在隔离集成夹具中使用；
- `historical_instruction_sentinel`：位于历史用户消息的诱导指令。C/E 可以在明确的
  “过去事件证据/不可信数据”块内读到它，但输出不得复读或执行；
- `stale_value_sentinel`：旧事实的错值。它可存在于历史证据，但不得被编译为当前事实或出现于回答。

### 12.4 五个主臂的精确输入

| 臂 | 历史记忆区 | 要回答的问题 |
|---|---|---|
| A `overview_tail` | 当前有效手工/自动 overview + 未覆盖 raw tail | 现行基线在哪里丢失记忆 |
| B `overview_tail_segments` | A + 该臂 selector 选中的 path-valid segment summaries | 已有分段概要召回是否有用 |
| C `overview_tail_rehydrated` | B + 命中范围内有界原始节点/自然段 | 回读原文能否修复概要丢失 |
| D `hybrid_overlay_gold` | C + gold append-only fact operations 编译的当前相关状态 | 结构化状态本身是否有净价值 |
| E `full_raw_reference` | 完整 selected raw path，不使用 overview/segment/overlay | 无压缩参照在可容纳档的表现 |

A–D 的记忆区均使用相同总 cap 与保留槽位：`manual/required`、`open thread`、
`active object facts`、`relevant episode`、`recent valid segment`。候选条数与最终 token 配额分开。
报告必须列出每个区的
included/omitted ref hash 和 token，不只保存整个 Prompt。

诊断臂规则：

- B 失败时运行 `oracle_segment`；它成功则主因是 segment selector，仍失败则是 segment
  内容丢失或模型未使用。
- C 失败时运行 `oracle_raw_node`；它成功则主因是 rehydration selector，仍失败且事实已在
  输入则是模型未使用。
- gold D 失败就停止；成功后才运行 `hybrid_overlay_extracted`，将抽取失败与状态编译价值分开。
- `summary_self_check` 只在主因已判定为 `overview_loss` 的 case 上运行，只检验第二次压缩调用的
  边际价值，不作为第六主臂。

### 12.5 夹具前置门与四层证据

1. **L0 夹具完整性（无 LLM）**：schema、唯一 case/event ID、seed 可复现、字节 hash、分支图、
   oracle 引用、长度档实测值全部有效。
2. **L1 编译包（无 LLM）**：检查 selected ancestry、overview lineage、source cutoff、owner/novel、
   branch attachment/coverage/authority 三个 frontier、required/omitted ref、槽位预算和 sentinel。
   A 必须调当前生产编译 seam；未实现臂的试验组装
   必须标记 `experimental_packet_only`，不得冒充生产行为。
3. **L2 事实 probe（真实模型）**：使用合成唯一值和可观测行动，自动断言当前事实、
   过期值、泄漏值和历史指令是否被使用。它测事实连续性，不测文风。
4. **L3 叙事盲评（真实模型 + 人工评审）**：每个 case 随机化候选标签，打分后才解盲；
   使用 0–4 分，保留现有七维，增加 `inventory_location_state`、`open_thread_continuity`、
   `correction_obedience`、`narrative_naturalness`。
5. **L4 真实用户试用**：观察是否出戏、是否愿意继续使用以及纠错是否可理解；
   它是上线后证据，不属于 P0 runner。

L0 是发起评测的前置门，L1–L4 才是四层证据。L2/L3 的 system-under-test 输出必须使用
一个可丢弃项目、生产 interaction workflow 与 project LLM execution snapshot/facade；不直接构造
`LLMClient` 或读取 Key。盲评 judge 是独立评测角色，不冒充 system under test。

真模型运行先做小 dev pilot 估计方差与费用，再冻结 test/holdout 样本量和决策规则；
不在没有 pilot 数据时伪造一个精确 N。

### 12.6 根因分类顺序

每个 case/arm 只给一个 `primary_failure`，按以下顺序取第一个适用项；同时可附加多个不改写主因的
performance flag：

1. `fixture_invalid`：schema/hash/分支图/oracle/长度档无效，不允许发起模型请求；
2. `safety_or_lineage_leak`：branch/source/owner/novel 越界，或历史指令被提权执行；
3. `object_identity_violation`：模型伪造 key、歧义/语义候选被自动绑定、source/local provenance 错置，
   或 relation endpoint 不在当前可见视图；
4. `memory_install_conflict`：manual rebase 对同一 path/end episode 重复安装、命中唯一约束，或把新
   overview/delta 绑到错误 authority lineage；此类失败不允许进入模型质量评分；
5. `compiled_memory_wrong`：编译包包含错误当前值，或过期值被当作当前事实；
6. `required_fact_absent`：事实未进编译包，继续按 `overview_loss`、`segment_candidate_miss`、
   `rehydration_miss`、`overlay_extraction_miss` 或 `budget_eviction` 细分；
7. `model_nonuse`：正确当前事实已在输入，但输出事实断言失败；
8. `quality_regression`：事实断言正确，但人工盲评的叙事表现退化；
9. `cost_cache_latency_regression`：无更早正确性失败，但资源或延迟越过已冻结决策门。

若一个指标所需的 provider usage、cache 或盲评证据不存在，报告必须写
`available=false + reason`，不得转成 0、通过或推测值。

### 12.7 指标与决策门

**不可被平均分抵消的硬指标**：

- 适用 case 的 path/source/owner/novel 血缘验证 100%；
- 未选 branch、future source、other owner/novel 的编译包与输出泄漏各为 0；
- 历史指令执行为 0；
- 任何准备上线的候选臂必须 100% 保留用户明确修正，且不把 stale value 编译为当前值；
- manual rebase 重放同 path/end tail 时 episode segment 重复数为 0，新 overview/delta 的 authority lineage
  正确率为 100%；
- 已被标记 `required` 且在当前臂契约内的记忆不得因预算静默丢弃；超预算必须 fail-closed
  或带明确 omitted reason。

**方向性指标**：按场景、beat 距离、token 档和事实类型分层的当前事实 accuracy/recall、
stale resurrection rate、未决事项延续率、0–4 盲评各维、输入/输出/cache tokens、调用数、费用与
端到端延迟。先报告分层和配对差，不把它们压成一个总分。

本节的“严格正向”不是样本均值刚好大于 0。dev pilot 必须先确定实用最小改善、配对
区间/检验方法与盲评非劣界，在看 test/holdout 前冻结；只有 holdout 区间下界越过该门才成立。

P1 候选层的保留规则：B 相对 A、C 相对 B 必须在目标长程分层上有正向配对改善、
不破坏任何硬门，并在相关场景不出现系统性退化；否则删掉该层。所有臂还必须先通过 12.11 的
provider ceiling、required/tail 保留、deterministic pack、无 silent truncation 和跨层 winner 硬门；
需要 compaction 的 case 还必须通过 12.12 的 compatible overview、protected suffix、连续 prefix 与净缩减门。

P2 的请求确认门：

1. gold D 相对 C 必须在中、长 token 档的结构状态场景上都有严格正向配对改善，且没有相关
   场景退化或新的 stale/leak；
2. gold D 过门后，extracted D 必须独立重跑同一决策门；不能用 gold 成绩代替抽取质量；
3. 12.9 对象身份补充协议的 source/local 稳定身份、歧义、branch、future/excluded、relation endpoint
   与 derivation idempotency 硬门全部通过；
4. 12.10 的 gold recovery 必须先证明全部候选可显式处置；extracted recovery 再证明仍有效
   identity/state 全恢复、被修正 stale facts 零复活、wrong-object invalidation 为 0。任一失败则
   structured view 保持 degraded，不得进入发布候选；
5. 人工随机盲评不得显示结构化臂的叙事质量退化；未过校准的 LLM judge 不可单独放行；
6. 只有以上条件同时成立，才回到 7.2/7.3 做“业务 memory stream vs 不要结构化层”
   deletion test；确需 stream 后再比较单表/两表，并向用户请求 schema/ADR 确认。

### 12.8 报告与可复现性

每次报告至少保存：

- dataset 字节 hash、schema/generator version、模板 hash、seed 和实际长度；
- 每臂 compiler version/hash，实际 included/omitted ref hash、section token，branch attachment/coverage/authority
  frontier 与 path/overview/source fingerprint；
- D 臂的 allowed candidate-set hash、每个 call-local ref 的 source/local 类型、绑定理由、歧义/舍弃原因和
  derivation idempotency key；普通报告不回显服务端持久 UUID；
- Prompt version/hash、provider/model、脱敏 profile hash、采样参数、输出预留和可用的 usage/cache 证据；
- 每 case/arm 的自动断言、`primary_failure`、performance flags 和解盲后的候选对应；
- 开始/结束时间、运行错误、指标 `available/blocking/threshold/passed/reason` 以及未完成原因。

报告原子写入本地忽略目录，不含 Key、未脱敏 project profile、用户正文或版权作品原文。
如果模型、profile、Prompt、dataset 或 compiler hash 不同，不将两次结果声称为单变量配对比较。

### 12.9 structured overlay 对象身份补充协议

这一补充只在 D gold 评估中生效，不要求 A/B/C 伪造尚未存在的对象库。合成 case 额外保存：

- `source_versions`：各版 `manifest_hash`、合成 source project ID、progress anchor，以及
  `target_id/reference_key/label/entity_type/status/identity_terms/first_appearance`；
- `identity_ambiguities`：term、candidate target IDs 与可选 frozen resolution；
- `delta_batches`：derivation key、overview base、path/end、临时 `new` handles 和封闭 operations；
- `expected_handles`：由 runner 在服务端算法下产生，不接受 fixture 中自由填写的模型 UUID。

最小场景集：

1. `source_key_rotation`：同 `target_id`、两个 manifest/reference keys；允许升级后 handle 不变，证据键更新。
2. `source_target_missing`：新版本缺少旧 target；升级失败关闭，不按新名称重绑。
3. `source_local_homonym`：一个 source handle 与一个 path-valid local 同名同类；无决议时 operation 不可用。
4. `candidate_alias_collision`：未确认 source alias 唯一命中一个对象；它可帮助检索，但不能成为 identity binding。
5. `pre_fork_shared_create`：local object 在分叉前创建；两个 descendant 使用同一 key，后续状态各自折叠。
6. `post_fork_same_name`：两个 sibling 分别创建同名对象；得到两个 key，互不可见，不跨分支 merge。
7. `unbound_known_name`：无 source 旅程使用一个众所周知的作品名称；有 RP 证据时也只产生 local provenance。
8. `future_source_name`：名称存在于 frozen manifest 但首次出场超过 cutoff；不进 candidates，不产生 source handle。
9. `relation_hidden_endpoint`：关系一端只存在于 sibling/excluded/future source；整条 relation operation 不可用。
10. `derivation_retry`：同 derivation key 重复安装；local create 和关系各只产生一次。
11. `pronoun_coreference`：一个代词可指向多个 active candidates；可记录 contextual suggestion，但首版
    `usable=false`，不持久猜测身份。
12. `manual_barrier_existing_local_state`：手工修正前已有多个 local identities/states；分别回放
    12.10 的各 recovery 臂，测量仍有效状态恢复、stale 复活和无关事实退休。

硬断言：

- object key 从不由名称、alias 或相似度直接生成；所有 persisted key 都能追到 server candidate
  或一个 CAS 有效 local `create`；
- source handle 稳定率、不可见对象排除率、歧义 fail-closed 率、branch ancestry 隔离率和安装幂等率
  在适用 case 均为 100%；
- manual barrier 后、原子 recovery commit 前，除不可变 source identity/provenance 外的 structured fact
  注入数为 0；旧 facts、保存后新 delta 和任何内部 batch 都不可见。
  commit 后夹具标记的仍有效 identity/state 一次完整恢复，被修正 stale fact 复活率为 0；
- 任何 source/local 错绑、跨 sibling endpoint、future/excluded source handle 或模型伪造 ID 都是 blocking，
  不被更高的事实 recall 抵消。

方向性指标另行记录：可绑定 mention recall、新 local object precision、歧义率、因保守失败关闭造成的
delta omission，以及对后续事实连续性的影响。这些指标只决定结构化层是否值得保留，不放宽上述硬门。

### 12.10 manual recovery 专用对照协议

这一协议回答三个不同问题，不能只看最终故事盲评混在一起：barrier 是否先阻止旧错事实复活；
reconcile 是否只改正确对象；被手工修正波及前仍有效的事实能否恢复。

每个 case 在 12.2 基础上增加：

- `base_sections`、`saved_sections` 和由 runner 计算的 `changed_sections`；fixture 不直接替服务端声明 diff；
- manual 保存前的 active source/local operations、各自 object/field/relation endpoints、authority 与 provenance；
- 每个候选的 gold disposition：`keep|suppress|replace|uncertain`，以及允许的新 manual-derived operations；
- `expected_affected_scope`、`expected_retained_facts`、`expected_suppressed_facts`、
  `forbidden_inverse_facts` 和保存期间新增 raw tail；
- `manual_revision_id`、base leaf/path hash、base authority、source revision/epoch、candidate compiler/schema
  version、candidate snapshot hash、derivation root、expected output hash/operation count；
- manual save、background task、late automatic writer 与 retry 的确定性时序。

固定 recovery 臂：

1. `R0_no_structured`：只用 manual overview + raw tail +允许的 source identity，作为安全/叙事基线；
2. `R1_reset_new_only`：屏蔽全部旧 delta，只接受保存后的新 tail delta；
3. `R2_section_barrier_only`：应用 5.5 静态映射并让映射外旧 fact 继续注入，不运行 reconcile；专门测
   该优化的漏判风险，任何 stale resurrection 即淘汰它作为生产候选；
4. `R3_global_barrier_gold_reconcile`：使用全 active projection 的 gold disposition，验证候选范围、
   补偿语义和编译器上限；
5. `R4_global_barrier_extracted_reconcile`：使用真实受限输出，评估抽取/判断错误；
6. `R5_full_raw_rebuild_diagnostic`：在同一 manual authority 下重放 raw selected path，只作质量、费用和
   延迟上界；它即使得分更高也不会自动成为生产方案。

最小场景：

1. `explicit_scalar_correction`：明确把知道改为不知道；旧值必须退休，新值可安装。
2. `deletion_without_negation`：删掉一句旧状态但不写反值；旧状态停止注入，反值禁止产生。
3. `semantic_rewrite`：只改写措辞；同一对象/字段可 keep，identity 不变化。
4. `add_only_section_edit`：只增加新承诺；验证 barrier 是否造成过宽遗漏，并记录受影响范围假阳性。
5. `one_of_many_same_kind`：同一 fact kind 有多个对象，只修一个；其他对象不得被错误退休。
6. `same_name_cross_branch`：两个 sibling 同名 local 对象；只允许当前 ancestry 的目标进入候选。
7. `relation_endpoint_change`：关系一端变化；同人其他关系不得被语义相似度误伤。
8. `mutable_source_fact_override`：RP 当前态修正可变 source fact；source identity/provenance 保持。
9. `candidate_omission_or_uncertain`：模型漏回一个候选或返回 uncertain；对应范围保持 degraded。
10. `retry_late_writer_and_failure`：重复任务、晚到旧 automatic writer、无模型连接和后台失败；manual
    overview 始终已生效，补偿 operation 幂等且 UI 不谎报保存失败。
11. `oversized_projection_batches`：候选超过单调用预算并含跨对象关系；固定分组可重试，identity 未恢复时
    relation 不发布，达到 batch 上限或任一依赖失败时整个 barrier 保持 degraded。
12. `unseen_tail_during_manual_edit`：打开 editor 后新增 tail、再保存旧 base；tail fact 不进 candidate hash，
    后续仍按更晚 effective node 生效。
13. `continue_or_switch_during_reconcile`：prepare 后继续原 branch、切 sibling、再切回；结果归属于冻结
    anchor，当前 sibling 注入为 0，返回原 branch 后可见完整 commit。
14. `same_anchor_new_manual_authority`：同 anchor/path 再保存新 manual revision；旧 recovery 不得 commit。
15. `source_epoch_changed`：prepare 后升级 source 或改 pin/exclude；整次 stale，不挽救 local-only batch。
16. `forward_transition_vs_retrospective_claim`：后序节点分别明确发生新变化、回述过去相反事实和时间不明；
    只有第一类可覆盖 manual-derived value。
17. `zero_op_and_task_done_without_commit`：零事实变化也要 recovery commit；task done 或私有 batch 完成但
    commit 缺失时结构化注入仍为 0。
18. `crash_before_atomic_publish`：任一 batch 后崩溃、lease 丢失或最终 insert 冲突；重试前无半套 projection，
    同 derivation root 成功后一次发布。

硬门：

- user explicit correction 保留率 100%；stale resurrection、forbidden inverse、wrong-object invalidation、
  跨 branch/source/owner/novel 操作和 source identity/provenance 改写均为 0；
- `R3` 的 candidate disposition completeness 为 100%，仍有效事实恢复率为 100%；否则说明候选模型或
  manual evidence 本身不足，停止 `R4`，不靠 LLM 调参补架构缺口；
- `R4` 只有在上述硬门全通过且所有未决范围继续 degraded 时，才可声称 recovery 完成；
- manual save 锁内 candidate root 可复现；pre-manual writer 只有“先进入 hash”或“旧 epoch stale”两种结果；
- task/batch 状态不能解除 barrier；fact rows + recovery commit 原子出现，retry 后 operation 数不增加；
- 单调用与确定性分批的 gold projection 等价；batch 顺序变化不改变 snapshot hash、分组或最终状态，
  任一中间 checkpoint 的 Prompt structured 注入数为 0；
- path extension/sibling switch 不错误使 branch-local commit stale，也不产生 sibling 注入；同 anchor 新 manual、
  source epoch 漂移、candidate/output hash 或 expected count 不符全部 fail-closed；
- 相同 events 在不同 worker 完成/数据库时间顺序下 projection 一致；retrospective/ambiguous automatic
  contradiction 覆盖 manual 值的次数为 0；
- UI 状态断言分别验证 `manual_saved=true` 与 reconcile pending/failed/succeeded，不把后台失败改写成
  manual save 失败。

方向性指标：受影响范围 precision、应保留事实 recall、barrier 造成的临时 omission、reconcile 调用/
batch 数、tokens/费用/延迟、恢复完成时间和后续 probe 连续性。根因依次归类为
`barrier_scope_error`、`snapshot_drift`、`candidate_scope_error`、`disposition_error`、
`temporal_classification_error`、`authority_stale`、`partial_publish`、`install_conflict`、
`incomplete_recovery`、`stale_revival`、`model_nonuse`；第一处确定性失败即为 primary failure。

决策顺序：先比较 R3 与 R0/R1/R2，证明机制上限；再运行 R4；R5 只回答“全量重放最多能多恢复多少、
代价多少”。若 R4 不过门，保持 R0/R1 的安全降级或删除 structured layer；R2 已是风险臂，不能因成本
较低直接采用，也不默认升级到 R5。

### 12.11 unified Prompt Pack 预算、去重与 provider profile 协议

这一协议不增加新的产品记忆臂。每个 A–D case 分别用 `legacy_concat` 与 `unified_pack` 编译；先比较
确定性 pack，再在完全相同的 model/profile/Prompt 下比较输出。E `full_raw_reference` 仍只在可容纳档运行。

每个 case 增加：

- `capability_profile`：provider/model、官方规格来源与核验日期、context limit、verified input ceiling、
  normal/compact/hard 阈值、output reserve、safety margin、calibration status；
- `pack_candidates`：section/item key、allocation class、authority、content/ref hash、dedup key、估算 token、
  required/pinned、activation reason、path/source/overview lineage；不把真实正文写入报告；
- `expected_pack`：必须保留/允许省略的 item refs、各 slot 上限、回流规则、最终 render order 与 blocker；
- 可用时保存 provider actual input/cache/output usage；不可用时为 `available=false`，不伪造精确 tokenizer 结论。

最小场景：

1. `required_exact_fit`：hard rules + manual + tail + required source 恰好可容纳；optional 全空也必须调用成功。
2. `required_over_budget`：固定成本超 hard input；在 provider I/O 前整理或 blocker，不能裁 manual/tail/pinned。
3. `low_information_continue`：最新输入只有“继续”；overview 人物/open thread/最近节点仍激活相关 source、
   object 与旧 episode，且不越 cutoff。
4. `source_slot_saturation`：required source 很小、optional source 很大；optional 截断，其他 slot 不被吞掉。
5. `empty_slot_reflow`：无 source 或无 episode；空额度可回流，但不改变 required/authority。
6. `segment_raw_dedup`：同一 segment summary 命中并成功回读 raw node；只渲染 raw，trace 同时保留两者来源。
7. `overlay_source_same_field`：source base 与 RP overlay 对同 object/field 给出旧/新值；current block 只出现
   overlay winner，source identity/provenance 保留。
8. `current_and_historical_value`：当前状态与旧 episode 的历史值都与 query 相关；分别标成 current/past，
   不把旧值折叠为第二个 current winner。
9. `manual_overview_synonym`：overview 与 structured fact 语义相近但无确定性 key；允许少量重复，不调用 LLM 删。
10. `one_hop_hub_and_cycle`：active object 连到大 hub/环；只展开一跳、固定上限，二跳 sentinel 不出现。
11. `provider_hot_switch`：1M → 256K → 128K → unknown profile；每次从模型中立资产重编译，不复用前一
    model hard ceiling，必要时整理/省略 optional/blocker。
12. `multilingual_estimator`：中文、英文、数字、emoji 和混合标点；记录 char/shared estimator/actual 三者。
13. `head_truncation_sentinel`：最早 hard rule 与 manual sentinel 距离超长；永不依赖 provider auto truncation，
    最终请求包含它们或调用前失败。
14. `regenerate_and_continuation`：完整 rejected variant、continuation text 与 raw tail 同时存在；当前 user/续写
    控制保持正确 role/order，旧 rejected 文本不进入历史事实。
15. `manual_barrier_degraded`：structured layer unavailable；active_state 槽为空并把额度回流，manual overview/
    tail/source identity 仍完整，不能用旧 object facts 填空。
16. `cache_prefix_churn`：连续若干 turn 只有 dynamic query/tail 改变；记录 pack/prompt hash 与 provider cache
    usage，不能为了缓存把 stale dynamic block 固定在前缀。

硬门：

- `estimated_input <= hard_input`；有 actual usage 时 `actual_input + reserved_output <= context_limit - margin`；
- hard rules、manual/required、latest current input、完整未覆盖 raw tail、player/pinned/cutoff guard 保留率 100%；
  放不下必须在 provider I/O 前 summary 或 blocker；
- provider silent head truncation 使用次数为 0，head/manual sentinel 丢失为 0；
- current user/raw tail 的 role、字节内容和最终相对顺序保持；历史 episode 永不取得 current user 指令权；
- path/source/owner/novel/future/excluded/sibling 泄漏为 0；manual barrier 下旧 structured 注入为 0；
- 同输入/profile/compiler version 的 pack fingerprint、item order、budget events 和 omitted reasons 字节稳定；
- raw rehydration 成功时相同 segment summary 重复渲染数为 0；同 object/field 的 current winner 最多 1 个；
- unknown/uncalibrated model 不继承其他模型 ceiling；无 actual usage 不得标记 calibrated。

方向性指标：每层 selected/omitted/token、required headroom、slot utilization/reflow、duplicate token ratio、
segment→raw 命中率、active object recall、provider cache read/write、调用数、费用、延迟、事实 probe 与盲评。
先报告分层，不把“省 token”与“记忆正确”压成一个分数。

根因顺序：`profile_missing_or_stale` → `estimator_underflow` → `required_over_budget` →
`candidate_scope_error` → `slot_starvation` → `dedup_error` → `render_order_error` → `compiled_memory_wrong` →
`model_nonuse` → `cost_cache_latency_regression`。第一处确定性失败是 primary failure。

决策门：

1. `unified_pack` 必须先在所有 case 通过硬门，且相对 `legacy_concat` 不降低 A 臂事实正确性；否则不进入 B/C/D。
2. segment/raw/object 层仍分别按 12.7 增益门决定去留；pack 安全通过不能替它们证明产品价值。
3. slot cap、compact trigger 和 margin 在 dev pilot 冻结，holdout 前不得按结果调参；普通用户不获得旋钮。
4. P2 typed source items 只在 legacy rendered packet 的 duplicate token ratio 越过预先冻结阈值、且 gold typed
   variant 有净收益时讨论；否则继续把 source packet 当原子 section。
5. cache 命中改善只能支持渲染优化，不能放宽 authority、visibility、required 或 stale 门禁。

### 12.12 bounded compaction、protected suffix 与 prefix checkpoint 协议

本协议比较四个 reducer 策略，不把 provider opaque state 变成产品事实：

1. `C0_full_tail_once`：当前基线，一次向 summary 发送全部 uncovered tail；
2. `C1_segment_text_fold`：用旧 segment summaries 替代 raw 的风险对照；预期在 manual case 淘汰；
3. `C2_bounded_raw_prefix`：目标策略，compatible overview + oldest contiguous raw chunk + protected suffix；
4. `C3_provider_compaction_diagnostic`：仅在 provider 支持时测 token/质量上界，不参加 branch/export/恢复契约。

每个 case 增加：

- full path node IDs/prefix hashes、role/message kind、每 node 估算 token、current response target 与 request kind；
- overview revisions 的 anchor/coverage/parent/source/promoted/authority oracle，segment ranges 与 checkpoint metadata；
- protected suffix oracle、compressible prefix、chunk boundaries、summary input ceiling、min savings、max passes/
  tokens/time、每 pass expected coverage；
- provider call/usage、domain commits、crash point、task lease/attempt 与最终 story Prompt included node refs；
- 只保存模板/hash/offset，不把真实长对话正文写入 fixture/report。

最小场景：

1. `urgent_current_user_preserved`：530K 旧历史后用户发一条含 sentinel 的请求；所有 passes 后该 user node
   仍以原始 role/字节位于最终 story Prompt，未进入 overview coverage。
2. `recent_dialogue_pair_preserved`：最新 user/assistant 对包含语气和指代；periodic summary 只压更老 prefix。
3. `continue_partial_preserved`：length continuation 的 persisted partial 与 response target 都在 protected suffix。
4. `regenerate_control_not_history`：just-rejected variant 保留为 request-local control，不进 summary/overview。
5. `no_overview_large_backlog`：无 overview 的 530K selected path 被多个 whole-node chunks 连续覆盖；每次调用
   低于 summary ceiling，最终恢复同一 attempt。
6. `compatible_revision_selection`：manual A、旧 automatic B>A、新 automatic C descends A；selector 拒 B、用 C。
7. `branch_switch_roundtrip_stale_auto`：切 sibling/切回后不因 B anchor 更远恢复旧 manual 前事实。
8. `manual_predates_segment`：旧 segment 含作者已删除值；C1 复活即失败，C2 raw input 有
   `predates_manual_baseline` guard 且最终 current value保持 manual。
9. `three_prefix_chunks`：每个 chunk end/path hash 连续；中间任一点生成 Prompt 都无 coverage gap/overlap。
10. `existing_exact_segment`：manual rebase 处理已有相同 start/end/path；复用 segment，新 overview lineage 安装。
11. `existing_wider_segment_same_end`：旧 segment start 更早；不覆盖/复制 episode row，新 revision 记录实际 raw range。
12. `non_reducing_output`：new overview 等长或更大；不写 segment/revision，coverage 不推进。
13. `single_old_node_over_ceiling`：一个旧 user node 大于 summary input；首版 blocker，当前 request/path 不丢。
14. `optional_memory_pressure_only`：required pack 可容纳、只是 source/episode optional 超限；省略 optional，
    compaction 调用数保持 0。
15. `pass_crash_matrix`：provider 前、provider 后/commit 前、commit 后/下一 prepare 前、lease 丢失和 SIGTERM；
    restart 只从最新 committed revision继续。
16. `max_pass_budget_exhausted`：达到 calls/tokens/time 上限仍超 compact target；明确失败，已完成 prefix 保留，
    不新建 task DAG 或静默继续收费。
17. `ordinal_checkpoint_independence`：从 segment ordinal 1/7/8/9 分别恢复；第 8 段 marker 不改变选择/结果。
18. `sibling_and_future_sentinels`：任一 summary input/output/overview/segment/最终 Prompt 均无 sibling、future source
    或 historical instruction 提权。

硬门：

- current response target、required recent suffix 的 node/role/bytes 保留率 100%；它们的 ID 不得落入 coverage；
- 每 pass summary input 低于 profile ceiling，provider head truncation 为 0；
- processed ranges 在 selected ancestry 上单调、连续、无 gap/overlap；chunk end prefix hash 正确率 100%；
- automatic reducer base 必须 descendant from 最新适用 manual barrier；old-lineage/furthest-anchor 误选为 0；
- 每次已安装 pass 的估算净缩减至少为冻结 min savings；non-reducing domain writes 为 0；
- crash/retry 后每个 prefix segment 至多一行，overview parent/authority 正确；task/lease stale writer 晋升为 0；
- max-pass 失败保留 path、current input、attempt 可恢复信息和已提交 prefix，不产生 selected sibling；
- C1 在 manual stale case 不得通过；C3 的 opaque output 不进入业务 fingerprint、export 或 branch selector。

方向性指标：pass/call 数、每 pass raw/overview/total tokens、累计 provider input/output/cache、首 token 延迟、
恢复总时长、summary 事实 precision/recall、manual retention、recent-style 盲评、重启重复工作量和 segment reuse。
按历史规模/模型 profile/是否 manual rebase 分层报告。

根因顺序：`compatible_overview_miss` → `protected_suffix_violation` → `chunk_boundary_error` →
`summary_input_over_budget` → `manual_stale_revival` → `non_reducing_output` → `prefix_install_conflict` →
`restart_duplicate` → `max_pass_exhausted` → `model_nonuse` → `cost_latency_regression`。

决策门：

1. C2 必须先通过所有硬门，再与 C0 比事实/成本；C0 单次调用较快不能抵消 current-user loss 或超硬上限。
2. C1 只有在所有 manual/authority case 与 raw C2 等价时才可能保留；当前架构预期淘汰，不为省调用放宽。
3. protected-tail target、summary chunk ceiling、min savings 与 max passes 在 dev pilot 冻结，holdout 前不调。
4. single-node paragraph checkpoint、successor task 和第 8 段特殊 checkpoint 都是被真实失败数据触发的后续项，
   不进入首版。
5. 若 C2 在适用长档不能稳定优于“明确 context-budget failure”，宁可 fail-closed，也不回退 silent truncation
   或一次不受控超大 summary。

### 12.13 P0 runner 自身契约与完成门

Runner 不能只测试被测系统，还必须证明自己的输入、盲化、费用门和报告不会制造假结论。最小自测矩阵：

1. `strict_schema`：未知字段、未知 template/schema version、raw/copyright text 字段、绝对路径和 malformed hash
   在带 line/case ID 的错误中拒绝。
2. `deterministic_materialization`：同 dataset/template/seed 连跑两次，messages/node IDs/facts/pack refs/hash
   byte-equal；修改一个 template value 只改变对应 case/root。
3. `split_group_isolation`：同 scenario group 同时出现在 dev/test 必须 blocking；case 顺序变化不改变 split。
4. `branch_dag_validation`：missing parent、cycle、parent 后置、unreachable selected leaf、duplicate event/object ID、
   sibling sentinel 落入 selected ancestry 均拒绝。
5. `arm_source_label`：A 标 `production_baseline`；未实现 B/C/D/E 标 `eval_reference`；reference 结果永不允许
   production capability claim。
6. `hard_assertion_independence`：故意让 reference builder 输出 sibling/future/错误 winner，oracle 必须抓到，
   证明测试不是简单信任同一 builder。
7. `metric_unavailable`：compile-only 报告的 model/review/actual usage 指标存在且 `available=false + reason`，
   value/passed 均不伪造。
8. `atomic_report`：临时写失败、replace 前崩溃不覆盖旧报告；成功 JSON 尾部完整且 dataset/report hash 对应。
9. `paid_gate_before_client`：无 `--allow-paid-model`、缺 novel ID、cache-only miss、project/model/profile mismatch
   时 mock client open 调用数为 0。
10. `project_scope_and_secret_hygiene`：model stage 只接受 active interaction project；report/cache/meta 不含 API Key、
    full base URL、账户 ID 或未脱敏 profile。
11. `paired_order_and_cache`：同 case/run/profile 的 arm order/candidate IDs 稳定；所有 arms profile/params 相同；
    cache key 包含 dataset/template/compiler/prompt/profile/arm/run，禁止跨版本复用。
12. `blind_export_import`：review artifact 不含 arm；arm-map hash匹配才可揭盲；缺 candidate、重复 reviewer、少 rubric
    dimension、越界分数与评分前 arm 泄露均拒绝。
13. `probe_story_separation`：fact probe failure 与 story rubric failure 分别归因；probe 分数不能替代盲评，story
    substring 不能冒充完整事实 accuracy。
14. `exit_semantics`：compile ready=0、完整 non-ready=2、invalid schema/runtime exception 普通非零；请求 model/
    review 而其证据 unavailable 时不能返回 0。
15. `existing_eval_non_regression`：现有 `test_rp_context.py`、四个 `EvalSuite`、readiness/CLI choice 和 Ask World
    命令/报告字节契约不因 standalone runner 改变。

P0 runner 完成必须同时有：formal module CLI、committed synthetic JSONL、窄测试、Make offline target、README
边界、一次可复现 compile report，以及 12.2～12.13 适用 hard metrics 的完整 inventory。真实 model/review 可
作为后续 stage unavailable，但不能缺字段、不能被写成已通过。首个 model stage 完成还需 project-backed
paired outputs、sealed arm map 与显式 cost/profile provenance；首个 quality baseline 则额外需要 frozen dev
threshold hash、一次 untouched test run 和校准人工盲评。

后续每形成新决定，必须在对应 `MEM-DEC-*` 下补：证据、质疑、升级后的决定、验证和重开/淘汰条件；
不得只在聊天中形成口头方案。
