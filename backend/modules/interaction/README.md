# interaction — RP 互动旅程

## 定位

`interaction` 服务“进入幻想世界”的 RP 用户。它保存不可变消息树、当前分支选择、流式生成
attempt 与分支有效回顾；不复用作者 World、Outline、RAG 或 memory，也不会把模型输出写回
作者正史资产。

每个旅程独占一个 `project_kind=interaction` 的隐藏项目，以 `novel_id + owner_id` 作为硬隔离
根。作者项目 API 和工作台默认只接受 `project_kind=author`，interaction API 只接受隐藏项目。

## 稳定边界

- 跨模块只调用 `modules.project.facade`（其内部解析 account 拥有的连接与全局偏好）和
  `infrastructure.tasks.facade`。
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
| `interaction_message_nodes` | 不可变 setup/story 节点和 complete/partial 正文 |
| `interaction_branch_selections` | 每个分岔父节点当前选中的 child |
| `interaction_generation_attempts` | 幂等请求、流式 buffer、snapshot、usage、错误与终态；上下文只持久化叶节点和完整路径 hash |
| `interaction_summary_segments` | 按 token 覆盖范围保存的分段概要及其直接总回顾/checkpoint 来源 |
| `interaction_overview_revisions` | 自动或手工总回顾的不可变 revision |
| `interaction_account_preferences` | owner 级低频体验确认 |

旅程“已经发生的历史”由根节点、branch selection 和 selected leaf 确定性计算。重新生成会创建
新的模型 sibling；编辑旧用户消息会创建新的用户 sibling；晚到完成结果可以保留，但只有
selection epoch 仍匹配的第一个结果可成为当前路径。Prompt、回顾、树摘要、路径定位和默认
导出都不得读取未选 sibling。

## 上下文与回顾

- 首次故事只使用用户开场和模型训练知识；用户在旅程中的明确事实/纠正优先。
- 正常输入预算起点为 256K token 估算；超过 512K 时在同一 attempt 内先做紧急结构化回顾；
  超过 750K 时 fail-closed，不静默截断历史。这些数字是可校准实现参数，不是产品承诺。
- 分段概要和总回顾由一次结构化调用同时生成，只记录已选路径中用户已经看到的内容。
- 总回顾固定为世界与起点、我的角色、当前局面、重要人物与势力、关键转折、正在发展的事情、
  必须继续记住七个自然语言分区。用户保存修正会生成 manual revision，不改写原始消息。
- 每 8 个仍属于当前选中分支的有效分段，把当次不可变累计总回顾 revision 标为 memory
  checkpoint；后续分段记录直接上游总回顾和最近 checkpoint revision。这里不复制第二份
  checkpoint 正文或另建聚合表，故事编译仍消费当前有效总回顾加尚未覆盖的原始尾部。
- producer provenance 只保存 provider/model、Prompt/schema 版本和 token/call 统计等脱敏字段。

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
- 上述门禁通过前，256K/512K/750K 只代表内部防护阈值，不能对外表述为“Kimi 已启用”或
  “支持 1M 长旅程”。

## API 分组

路由前缀 `/api/interactions`：

- 旅程：创建/列表/详情、标题、归档/恢复/永久删除、导出；
- 故事：发送、从节点继续、重新生成、编辑旧用户消息、选择分支；
- 阅读：选中路径分页、完整轻量路径索引、最近分支、压缩树；
- attempt：状态、SSE、停止、保留失败残段、length 续写、重试；
- 记忆：读取/保存总回顾；
- 看海：旅程模式、前台 heartbeat、账户级费用提示确认。

所有浏览器 API 从当前 account principal 解析 owner；跨 owner、错误 kind、已归档不可写和
不属于该旅程的 node/attempt 统一拒绝。永久删除必须先归档并提交完整标题确认。

## 第一版边界

- 不读取作者 World、Outline、RAG、writing 或 memory；
- 不导入小说文件，不支持按第 N 章分叉或手工剧透范围；
- 不提供项目共享、公开发布、多人协作或复杂跑团数值；
- 不把模型固定称为 DM，也不构建自治、多 Agent 或工具选择运行时。
