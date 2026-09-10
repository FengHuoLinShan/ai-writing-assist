# interaction — RP 互动旅程

## 定位

`interaction` 服务“进入幻想世界”的 RP 用户。它保存不可变消息树、当前分支选择、流式生成
attempt 与分支有效回顾。用户可继续直接使用模型知识，也可显式绑定同账号作者项目的
不可变资料版本。后者只通过 Evidence 读取截止点前的原作证据；RP 输出、回顾和原创身份仍只写
隐藏 interaction 项目，不写回作者正文、World 或 Story。

每个旅程独占一个 `project_kind=interaction` 的隐藏项目，以 `novel_id + owner_id` 作为硬隔离
根。作者项目 API 和工作台默认只接受 `project_kind=author`，interaction API 只接受隐藏项目。

## 稳定边界

- 跨模块只调用 project/imports/writing/evidence/world/story 的 facade/contracts 和
  `infrastructure.tasks.facade`。唯一跨项目例外见 ADR-0018：同 owner 的 author source
  revision 可被 interaction consumer 只读引用。
- 浏览器 API 只接受旅程 ID；服务端由当前 account principal 解析 `owner_id` 与 `novel_id`。
- 消息节点不可变。用户修改、重新生成和切换发展只创建 sibling 或更新 branch selection。
- 普通 Prompt、回顾与导出只编译代码层选中的路径。
- 流式可见正文持久化在 attempt，正式完成或用户主动停止后才创建模型节点。
- 模型附加元数据是可选的隐藏尾块；解析失败不使故事正文失败。
- 每个账户最多同时存在 8 个活跃故事 attempt；同一旅程当前路径只允许一个 active attempt。
- pending、preparing、running 和等待 `length` 续写的 attempt 都属于未解决生成；存在其中
  任一状态时，不能再发送、改选分支或创建 sibling。
- 看海由前台 heartbeat 驱动有界循环：当前 step 可收束，显式离开故事页会立即撤销前台
  heartbeat；浏览器短暂转入后台才使用宽限期，二者都不得继续创建后继 step。
- 普通 `length` 正在等待用户继续时，开启看海会在账户有空位后沿同一 attempt 自动续完一次，
  不另建 sibling；正式节点之后有 1 秒服务端节拍边界供已准备的手工操作先提交。它不是通用
  优先队列，也不会抢占已经创建或已经发给 provider 的自动 step。

## 数据与分支语义

| 表 | 责任 |
|---|---|
| `interaction_journeys` | 旅程、标题、模式、当前选中叶、selection/overview epoch |
| `interaction_source_revisions` | 作者项目的不可变 draft/hash manifest、剧情锚点、对象目录、歧义决议、整体 fingerprint 与就绪状态；不复制全文 |
| `interaction_message_nodes` | 不可变 setup/story 节点和 complete/partial 正文 |
| `interaction_branch_selections` | 每个分岔父节点当前选中的 child |
| `interaction_generation_attempts` | 幂等请求、流式 buffer、selection/source epoch、Evidence snapshot/fingerprint、安全引用摘要、usage、错误与终态 |
| `interaction_summary_segments` | 按 token 覆盖范围保存的分段概要及其直接上游总回顾 |
| `interaction_overview_revisions` | 自动或手工总回顾的不可变 revision |
| `interaction_account_preferences` | owner 级低频体验确认 |

旅程“已经发生的历史”由根节点、branch selection 和 selected leaf 确定性计算。重新生成会创建
新的模型 sibling；编辑旧用户消息会创建新的用户 sibling；晚到完成结果可以保留，但只有
selection epoch 仍匹配的第一个结果可成为当前路径。Prompt、回顾、树摘要、路径定位和默认
导出都不得读取未选 sibling。

## 上下文与回顾

- 无 source 旅程仍使用用户开场和模型训练知识。source-bound 旅程在每个 attempt
  通过 `evidence.compile_interaction_story_context()` 按固定 draft/hash manifest、章节、
  Scene 派生 offset、玩家身份和固定/忽略策略编译参考资料。interaction 先计算本轮固定输入，
  再把剩余额度传给 Evidence，且参考资料仍不得超过 16K；必需资料放不下时失败关闭。
- 引用激活顺序是玩家身份/剧情锚点 → 固定对象 → 本轮名称/别名命中 → 原文检索
  关联 → 有预算的一跳对象/关系。固定项失效或超预算时阻断；自动项可裁剪，忽略项不得
  被关系扩展带回。
- source 检索 query 由本轮输入、当前局面、重要人物、未决事项和最近发展确定性组成并有界
  截断；即使用户只说“继续”，也不会丢掉当前旅程态种子。
- 对象目录只收录冻结 draft/hash chunk 能证明的版本内出场，并保存首次出场章和最早完整 chunk
  的 end offset；身份、搜索、固定项和生成激活都按剧情截止点过滤，未证明字段不进入 Prompt。
- 关系只在其服务端 EvidenceLink 能回读并精确匹配当前冻结 `draft_id + source_hash + chapter` 时进入
  资料版本；仅有旧 `review_meta` 章节号、未定位证据或旧稿证据的关系会被省略。
- 原作角色使用截止点前的冻结 CharacterKnowledge 和精确原文；原创角色不创建 World
  对象，知识上限是截止点前的读者可见资料。
- `interaction-story-v7` 优先级是用户最新明确修正 → 已保存长期约定 → 当前选中旅程历史/有效回顾 →
  固定版本截止点前的作品资料 → 模型训练知识。来源归档、manifest 或必需引用失效时
  fail-closed，不退回纯模型知识。服务器在统一渲染边界中转义资料里的围栏结束标记，
  身份描述、人物知识和原文都只能作为引用数据，不能闭合资料块后注入指令。
- 输入预算来自 attempt 冻结的 model capability profile，并取字符估算与 shared tokenizer 的较大值。
  当前已校准 DeepSeek V4 Flash 使用 256K normal、360K compact、400K hard input；unknown model
  使用 16K/20K/24K short fallback。超过 compact trigger 时在同一 attempt 内先做紧急结构化回顾。
  整理只读取兼容回顾后的最老连续 whole-node prefix；DeepSeek 单次摘要输入不超过 256K，并保留近期
  至少一个完整对话节拍和约 16K 原文后缀；最多 4 个短事务 pass，仍无法容纳才 fail-closed。
  不把整条 530K+ tail 先发给摘要模型，也不依赖 provider 静默截头。这些数字仍是待校准参数，
  不是产品承诺。
- 分段概要和总回顾由一次结构化调用同时生成，只记录已选路径中用户已经看到的内容。
- 相关分段概要的确定性 selector、800-token/4-item 上限和“过去事件证据”数据块仅保留为
  eval candidate。冻结生产 holdout 未通过用户明确修正硬门，因此当前没有任何 model profile
  会把 segment 注入故事 Prompt；生产仍使用总回顾与未覆盖原文尾部。
- 总回顾固定为世界与起点、我的角色、当前局面、重要人物与势力、关键转折、正在发展的事情、
  必须继续记住七个自然语言分区。用户保存修正会生成 manual revision，不改写原始消息。
- 任一 authority-compatible overview revision 都是可恢复的 prefix 起点；segment ordinal 不参与
  选择、恢复或可用性判断。经 consumer audit 确认无运行时读取后，不再新增“每 8 段”标记；
  历史 nullable 字段只作数据库兼容，不形成第二套 checkpoint。
- 手工回顾 rebase 若再次整理同一 `path_hash + end_node_id`，复用已有 episode segment，只追加
  基于当前 manual revision 的新总回顾，避免唯一约束冲突和重复往事。
- 分支切换后重新选择回顾时，automatic revision 必须能沿 `based_on_revision_id` 追到当前路径上
  最新适用的 manual revision；锚点更远但属于旧权威链的回顾不会重新晋升。后续多段 reducer
  也沿 lineage 保留 manual 防复活约束，不只检查当前 head 的 `source`。
- 每个 summary pass 仍用完整 selected-path hash/节点清单做 stale fence，但 segment 与新 overview
  只覆盖本次 chunk-end prefix；输出至少净缩减 128 token 才原子推进 coverage。崩溃或重试从最近
  已提交 prefix 继续，近期 raw suffix 的 role 与原文不变。
- 故事页“记住这一点”把当前选中的故事片段与输入预填到“必须继续记住”，保留输入框原文并聚焦回顾字段；
  只有用户再次点击保存才创建 manual revision，不自动发送或静默写入。
- producer provenance 只保存 provider/model、Prompt/schema 版本和 token/call 统计等脱敏字段。
- 资料版本只有在正文整理、精确索引和对象重标注任务均成功后才会 ready；对象重标注
  `failed/cancelled` 会把版本置为可重试的 failed，不会静默 finalize。

## 长期约定与首次回顾

`sections.long_term_agreements` 是用户维护的自然语言规则/偏好，最多 4,000 字符，
存储在既有 overview revision 的 sections JSON；不新增表或 migration。旧记录默认为空，
旧客户端未传字段时保留当前值，显式空字符串清空；不把旧 `must_remember` 自动迁移为约定。
自动摘要 schema 只含原七区，finalizer 从当前有效 revision 复制约定，禁止模型改写。
`interaction-summary-v3` 明确自动回顾不等于用户逐项确认；只保存约定时，不将空的七区
当作手工修正基线。真正手工删改的回顾仍受旧值防复活保护，符合约定的新变化仍可演化。

故事与摘要单独渲染约定，优先级为最新明确修正 → 长期约定 → 当前选中历史/有效回顾 →
截止点前作品资料 → 模型知识。约定不能扩大账户权限、角色知识或来源可见范围。
固定输入预算先计入约定，剩余预算才分配 source；超限不静默丢弃必需输入。
新保存从下一次上下文准备生效，不替换正在输出的故事。

无自动回顾时 GET 仍返回当前叶与路径指纹，PUT 接受 `base_revision_id=null`，严格检查
初始 epoch、当前叶及路径；有其他回顾或路径改变则 409。首次手工 revision 绑定当前分支，
但 `coverage_anchor_node_id=null` 且 `coverage_path_hash=SHA256(空字符串)` 表达零摘要覆盖；
全部原文仍进入生成/首次摘要。历史 NULL/NULL coverage 继续按旧 anchor/path 解释。
只剩约定时允许清空，版本仍保留。包括回顾的导出展示约定，纯故事导出不包含它。

回顾抽屉顶部的“长期约定”沿用手动编辑、保存、草稿、冲突和焦点流程，首次即可编辑。
“记住这一点”仍只预填 `must_remember`，不会自动把选中文本提升为长期规则。

## 流式、停止与恢复

- worker 将可见正文按“约 2 秒或累计 512 个新字符”持久化 checkpoint，并在结束时立即刷新；
  这是写放大压测后可调整的起点。
- SSE 使用持久 offset 恢复，刷新后不会只依赖进程内缓冲；隐藏元数据不进入可见故事。
- 用户主动停止时，已经输出的正文正式化为 partial 节点并留在历史中；技术失败残段保持
  attempt 级待采用内容，用户可保留或重试。
- worker 重启先对照 task 生命周期收敛遗留 attempt：统一标记为 failed；已有可见正文仍只
  保存在失败记录中，必须由用户选择“保留这段”后才正式化为 partial，避免技术故障替用户
  决定旅程正史。
- `length` 截断最多继续同一 attempt 一次；普通网络/供应商错误不自动重放故事，避免重复付费
  和产生无法解释的 sibling。

## 任务

- `interaction_story_generate`：一次故事回复或同一 length attempt 的续写，禁止自动重放。
- `interaction_summary_refresh`：分段回顾和总回顾的异步整理；失败不影响原始历史。

## 手工启用门禁

- `make test-real-kimi` 是 Kimi K3 的显式付费兼容门禁，覆盖错误 Key 不落库、余额辅助查询、
  SSE 恢复、分支隔离、结构化回顾、DeepSeek→Kimi snapshot 固定，以及原 provider Key
  被清除后的 fail-closed。它要求临时 Kimi/DeepSeek Key，且只在测试进程设置
  `ENABLE_ACCOUNT_KIMI_K3=1`；普通运行时仍默认关闭。
- `make test-interaction-long-context` 使用 Kimi 返回的 `usage.prompt_tokens` 校准
  16K～730K 七档确定性混合语料，并在独立 PostgreSQL 库验证一次 530K
  “紧急整理→恢复故事”。缺少精确 usage、费用授权、官方上下文上限或专用数据库都会显式
  失败。报告只含数字与 provider/model，写入已忽略的
  `.test-artifacts/kimi-context-calibration.json`。
- 上述 Kimi 门禁通过前，Kimi/其他未知模型只使用 16K/20K/24K short fallback，不能对外表述为
  “Kimi 已启用”或“支持 1M 长旅程”。

## API 分组

路由前缀 `/api/interactions`：

- 旅程：创建/列表/详情、标题、归档/恢复/永久删除、导出；
- 作品资料：作者项目列表、两次文件校验导入、完整整理进度/恢复、关键歧义、章节内
  剧情锚点、自然语言匹配、对象查找、旅程升级和固定/忽略；
- 故事：发送、从节点继续、重新生成、编辑旧用户消息、选择分支；
- 阅读：选中路径分页、完整轻量路径索引、最近分支、压缩树；
- attempt：状态、SSE、停止、保留失败残段、length 续写、重试；
- 记忆：读取/保存总回顾；
- 看海：旅程模式、前台 heartbeat、账户级费用提示确认。

所有浏览器 API 从当前 account principal 解析 owner；跨 owner、错误 kind、已归档不可写和
不属于该旅程的 node/attempt 统一拒绝。永久删除必须先归档并提交完整标题确认。

## 当前边界

- 一条旅程只绑定一部作品的一个资料版本，不做 crossover；
- RP 导入对外只宣称 `.txt/.epub/.html/.htm`；MOBI/AZW3 未经真实文件门禁前不展示；
- 不提供项目共享、公开发布、多人协作或复杂跑团数值；
- 不把模型固定称为 DM，不构建自治多 Agent；工具选择只允许 ADR-0023 的有限单 Agent 路径。

## DeepSeek RP 执行参数

新建执行快照使用 `deepseek-v4-flash-rp-max-20260908-v2`：正文、看海、续写及后台/紧急摘要
均启用 max，单次总输出 65,536 token，专用超时 900 秒。领域请求覆盖账户通用输出默认值，
不修改账户连接。其他模型沿用原规则；旧快照缺少思考字段时保留原输出与超时，恢复任务不升级。
输入阈值不变，最终检查包括实际输出预留。策略及预算通过既有 capability snapshot/hash 固定，
客户端继续通过 Project facade 创建，不新增表或公开接口。

首段尚未出现时显示等待状态，超过30秒提示“仍在生成，可随时停止”；收到正文或终态后清除。
`interaction-story-v7` 保留长期约定接入，正文风格沿用 v5；未通过评审的 v6 写作实验已撤下。
保存可靠与调用完成不等于模型遵守约定，实验结论见2026-09-09保留成果记录。

## 有界 Agent 接入（ADR-0023）

启用 INTERACTION_AGENT_ENABLED 后，新 snapshot 使用 interaction_agent_story_generate：PydanticAI
自主选择选中历史/固定来源/通用事实工具，随后由原故事流式 finalizer 落入同一 attempt。
旧 snapshot 继续 interaction_story_generate。预算含准备、紧急回顾和最终故事，恢复不重置；
消息树、知识截止、回顾权威、停止残段和离页停止看海继续由 Interaction 控制。私有准备内容
不混入正文。工具响应和联网结果进入故事前检验来源/原作线索；无法证明时保留遗漏。

变化驱动的 interaction_continuity_review 只读近期选中故事、有效回顾及固定版本资料，
引用必须逐字存在于所读片段；不修改历史。站内提醒经 journey ID 解析项目，不能由浏览器
提供隐藏 novel_id。规则/边界测试不代表人物质感或用户满意度，模型盲评仍是独立门禁。

Agent 准备阶段仅替换故事执行指令，保留已物化的长期约定、有效回顾、固定来源与重抽参考。
通用事实联网同时过滤作品标题、实际目录的 label/aliases、全部准备消息及工具回读私文；
返回文本和引用地址同样检查。普通供应商异常的未满检查点尾段由原 attempt 失败事务保存，
仅在选中路径与来源 epoch 仍匹配时追加；没有绕过 worker lease 或取消。

增量连续性检查的第二条证据可引用选中消息、当前有效回顾的指定分区或固定来源包。引用
必须属于本次物化版本且引文唯一匹配；不能用虚构 UUID 或任意网页补齐证据。


### Agent v2 的公开资料查证

旅程 `web_search_enabled` 默认关闭，由原模式更新接口按 owner/selection epoch 保存。
新 attempt 的 v2 快照固定搜索后端与渠道授权；旧 v1 仍保留原生联网语义。准备阶段可自主
搜索通用问题并读取本轮网页引用，原作信息与私文在发送/接收两端排除。联网额度耗尽返回
遗漏，保留最终故事请求；关闭后不再检索，不破坏不依赖新检索的长度续写。

后台连续性结果保存可重验的 source_state。提醒展示只检查原固定版本、owner、来源可用性、
选中叶节点和回顾 epoch，不在 GET 中重编译 Context 或发模型请求。旧结果缺少来源状态时
标记需要重新检查。care/notices/{id}/recheck 复用 Assistant 调度与幂等回执，准备失败也可恢复。
