# Module: interaction / RP 互动旅程

## 定位

interaction 为 `我是 RP 用户` 路径保存私人互动故事。用户可直接描述世界和开场，也可从
同账号作者项目选择或导入作品，在当前导入版本的全部现有章节完成深度整理、精确索引和关键
歧义确认后开始。作品不必完结。RP 故事、回顾与原创玩家身份仍只写隐藏 interaction
项目，不写回作者正文、World 或 Story。

每个旅程独占一个 `project_kind=interaction` 的隐藏项目。`novel_id + owner_id` 是隔离根；
作者项目 API 只接受 `author`，interaction API 只接受 `interaction`。

## 核心模型

| 表 | 职责 |
|---|---|
| `interaction_journeys` | 标题、模式、当前选中叶、selection/overview epoch、归档状态 |
| `interaction_source_revisions` | 不可变 Writing draft/hash manifest、剧情锚点、对象引用目录、关键歧义决议、整体 fingerprint 和整理就绪状态 |
| `interaction_message_nodes` | 不可变的用户/模型 setup/story 节点 |
| `interaction_branch_selections` | 每个分岔父节点当前选中的子节点 |
| `interaction_generation_attempts` | 幂等请求、流式 buffer、selection/source epoch、Evidence snapshot/fingerprint、引用摘要、usage、错误与终态 |
| `interaction_summary_segments` | 按 token 覆盖范围持久化的分段概要及直接上游总回顾 |
| `interaction_overview_revisions` | 自动或手工总回顾的不可变 revision |
| `interaction_account_preferences` | owner 级看海费用提示确认 |

重新生成、编辑旧用户消息和其他分支都创建 sibling，不原地改写节点。只有 branch selection
和 selected leaf 确定的路径进入下一次 Prompt、回顾、默认导出和路径定位；晚到结果可保留，
但 selection epoch 不匹配时不能抢当前路径。

## 生成与恢复

- `interaction_story_generate` 生成一次故事；普通错误不自动重放，`length` 最多续写一次。
- 可见正文保存在 attempt，checkpoint 起点为约 2 秒或累计 512 个新字符；SSE 可按 offset
  重连。
- 主动停止把已显示正文正式化为 partial 节点；技术失败残段仍留在 attempt，用户可保留或
  重试。
- pending、preparing、running 和等待 `length` 续写的 attempt 都视为未解决生成；在其
  正式收敛前禁止发送、编辑、重新生成或切换分支。
- worker 启动与 stale-task scanner 会调用 interaction reconciler。任务已终止而 attempt
  仍在运行时统一收敛为 failed；已有正文保留为待采用失败记录，只有用户确认后才进入
  selected history。
- 账户最多同时存在 8 个 active story attempt；同一旅程当前路径只有一个 active attempt。
- 看海是前台 heartbeat 驱动的确定性有界 step 循环。显式离开故事页立即撤销 heartbeat，
  浏览器短暂隐藏才使用宽限期；关闭或离开后都不再创建后继。模型不能调用工具或自主编排
  工作流。
- 普通 `length` 的待续 attempt 可被看海沿原 attempt 接管一次；账户 8 个名额已满时保持
  等待。每个正式节点后有 1 秒服务端节拍边界，让已经准备好的手工请求先提交；这不构成
  后端优先队列，也不抢占已经创建的自动调用。

浏览器 API 统一位于 `/api/interactions`，只接受旅程、节点或 attempt 的领域 ID；
`owner_id` 与隐藏 `novel_id` 均由当前 account principal 在服务端解析。

## 回顾与上下文

自动回顾一次结构化调用同时形成新分段概要和更新后的总回顾。总回顾使用七个用户可理解的
分区：世界与起点、我的角色、当前局面、重要人物与势力、关键转折、正在发展的事情、必须
继续记住。用户保存修改会创建 manual revision；旧原文保留，但不能越过手工基线复活已纠正
事实。

任一通过当前分支、coverage 与 manual authority lineage 校验的 overview revision 都能作为恢复
起点。segment ordinal 不参与选择或恢复；consumer audit 确认没有运行时读取后，系统不再新增
“每 8 段”标记，历史 nullable 字段仅保留数据库兼容。故事上下文继续使用当前有效总回顾和
未覆盖原文尾部；多段 reducer 沿 lineage 保留 manual 防复活约束，不会因当前 head 已变为
automatic descendant 就重新采用旧当前值。

输入预算由 attempt 的 project LLM snapshot 冻结 capability profile，并取字符估算与 shared tokenizer
的较大值。当前 DeepSeek 档案为 256K normal / 360K compact / 400K hard，unknown model 为同数值的
long-context fallback（`unknown_long_context_fallback`，2026-09-02 产品决策）。超过 compact 阈值时，同一 attempt 以最多 4 个短事务依次折叠
兼容回顾之后的最老连续 whole-node prefix；DeepSeek 单次摘要输入不超过 256K，近期至少一个完整
对话节拍和约 16K 原文后缀保持原 role/bytes。每次只把 coverage 推进到 chunk end，输出未净缩减
至少 128 token、单节点/完整节拍超限或 pass 用尽时均 fail-closed，不向 provider 发送整条 530K+
tail，也不依赖静默截头。只有通过真实 provider 校准的新模型才新增档案。

source-bound attempt 额外经 Evidence 编译最多 16K 的版本化原作参考块。RAG 候选在排序前
就按 source manifest 排除其他草稿版本，每个命中再从 Writing 历史 draft 回读并校验
hash/offset。章节上界和章内 offset 是硬边界；原作玩家再受该版本冻结的 CharacterKnowledge
约束。对象目录只接受 exact manifest chunk 证明的出场并冻结首次出场章和最早完整 chunk
end offset；身份、搜索、固定和激活都按截止点过滤。激活理由只由代码生成为
“玩家身份/已固定/本轮提到/原文片段关联/相关关系”。
必需固定项失效、超预算、来源归档或 epoch 漂移时失败关闭，不退回模型知识。

## 前端

首页提供 `我是作家` 和 `我是 RP 用户` 两个大框。新旅程保留直接开场，并增加可选的
“使用作品资料”向导：已有作品/导入新作、可离开的整理进度、按需歧义卡、章节+剧情点+自然
语言匹配、原作/原创身份。故事页只在“更多 → 作品资料”抽屉显示版本、进度、本轮引用理由与
固定/忽略，不在 composer 常驻专业按钮。RP 路径其余仍包含旅程列表、开场输入、安全
Markdown 故事显示、composer、并列的复制/重新生成按钮、其他分支、简单分支树、回顾抽屉、
看海开关和右侧生成段落定位轨。“记住这一点”把选中的故事片段和 composer 当前文本预填到
回顾的“必须继续记住”并保留原输入，用户检查后再次保存才生效。行动建议同样只填入输入框，
不自动发送。移动端使用
纯白简洁布局；定位轨降级，composer 保持在可视底部，工具行可横向滚动而不挤压输入区。

## 当前不做

- 多作品 crossover、自动旅程升级、回退已开始旅程的剧情锚点；
- 项目共享、公开发布、多人协作或公共作品库；
- D&D 数值、固定 DM 身份、复杂文风/篇幅设置；
- 通用实体抽取、矛盾审核、幕后承诺或自治/多 Agent 运行时。

代码邻近的稳定约束、API 分组和任务语义见
[`backend/modules/interaction/README.md`](../../backend/modules/interaction/README.md)。
