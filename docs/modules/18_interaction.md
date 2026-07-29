# Module: interaction / RP 互动旅程

## 定位

interaction 为 `我是 RP 用户` 路径保存私人互动故事。用户用自然语言说明世界、身份和开场，
模型依据训练知识、当前代码级选中历史和有效回顾继续故事。该领域不读取作者 World、Outline、
RAG、writing 或 memory，也不把故事写回作者正史。

每个旅程独占一个 `project_kind=interaction` 的隐藏项目。`novel_id + owner_id` 是隔离根；
作者项目 API 只接受 `author`，interaction API 只接受 `interaction`。

## 核心模型

| 表 | 职责 |
|---|---|
| `interaction_journeys` | 标题、模式、当前选中叶、selection/overview epoch、归档状态 |
| `interaction_message_nodes` | 不可变的用户/模型 setup/story 节点 |
| `interaction_branch_selections` | 每个分岔父节点当前选中的子节点 |
| `interaction_generation_attempts` | 幂等请求、流式 buffer、snapshot、usage、错误与终态；仅保存上下文叶节点和路径 hash |
| `interaction_summary_segments` | 按 token 覆盖范围持久化的分段概要及上游总回顾/checkpoint 来源 |
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

## 回顾与上下文

自动回顾一次结构化调用同时形成新分段概要和更新后的总回顾。总回顾使用七个用户可理解的
分区：世界与起点、我的角色、当前局面、重要人物与势力、关键转折、正在发展的事情、必须
继续记住。用户保存修改会创建 manual revision；旧原文保留，但不能越过手工基线复活已纠正
事实。

每 8 个经当前分支 path hash 验证仍有效的分段，把当次不可变累计总回顾 revision 标记为
memory checkpoint；后续分段记录直接上游总回顾和最近 checkpoint revision。它不是第二张
checkpoint 正文表，也不复制一份平行记忆；故事上下文继续使用当前有效总回顾和未覆盖原文尾部。

正常/紧急整理/硬门禁的输入估算起点为 256K/512K/750K。超过紧急阈值时在同一 attempt
先整理再继续故事；超过硬门禁时 fail-closed，不静默截断。阈值和字符估算是待真实 tokenizer
校准的实现参数。

## 前端

首页提供 `我是作家` 和 `我是 RP 用户` 两个大框。RP 路径包含旅程列表、开场输入、安全
Markdown 故事显示、composer、并列的复制/重新生成按钮、其他分支、简单分支树、回顾抽屉、
看海开关和右侧生成段落定位轨。行动建议以完整卡片展示；点击只把自然语言填入输入框，
不自动发送或触发其他操作。移动端使用纯白简洁布局；定位轨降级，composer 保持在可视底部。

## 第一版不做

- 原作文件导入、按第 N 章分叉、剧透对象和隐藏章节范围；
- 项目共享、公开发布、多人协作或公共作品库；
- D&D 数值、固定 DM 身份、复杂文风/篇幅设置；
- 通用实体抽取、矛盾审核、幕后承诺或自治/多 Agent 运行时。

代码邻近的稳定约束、API 分组和任务语义见
[`backend/modules/interaction/README.md`](../../backend/modules/interaction/README.md)。
