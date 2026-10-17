# Collaboration 创作试验

`/api/collaboration` 管理作者目标、持续授权、有限调查和隔离试改。模块持有派生工作区与
精确采用回执；正文、结构、世界书工作稿仍由 Writing、Story、World 持有。

`contracts.py` 冻结 Grant、InputManifest、Recipe、WorkProposal 与资源 port。
`creative_manifest.py`（AO-5 起自 evidence 迁入）物化作者授权的冻结输入：
按资源 port 收集与校验来源快照、构造并重验 InputManifest 指纹、附加持久
理解与 Evolution 观察，并渲染受 24000 字符复核上限约束的上下文文本；
evidence/story/writing 的 resource provider 由组合根装配。
`cases.py` 校验 owner、项目、目标版本、授权截止与累计用量；续期保留历史及已消费请求。
`runtime.py` 通过原 PostgreSQL task lease 执行有限规划和独立成员步骤，使用 Project
冻结连接与当前账户 Key。角色历史、原始 Prompt 和密钥不进入公开 API。

`workspaces.py` 保存不可变 baseline + 累积 overlay。删除是显式 tombstone；读取试改不回退到
当前领域对象。新修订自动失去旧检查资格。检查同时验证领域输入、作者保留项、配方要求，
并绑定原稿与试改的精确文本。复核无法覆盖或来源变化时保持不确定。

`merge.py` 先取原项目排他写锁，重验完整读集、授权及精确检查，按领域 prepare/apply 执行
短事务，最后写 receipt 与 outbox。领域 apply 只 flush。确认重复仅返回已有回执。
`recovery.py` 重建基线或准备反向试改；同字段冲突返回供作者选择，不覆盖后续人工修改。
反向试改也需要重新检查与确认，原采用历史继续保留。重定位授权与子试改血缘在写入后
必须显式 flush：生产会话 `autoflush=False`，`require_case`/`require_workspace`
以 `populate_existing` 重读会丢弃未 flush 的属性改写。

`assistant_tools.py` 导出纯 `OPERATIONS_SPEC`：隔离 workspace 创建、修订、读取、封存，R4
模型检查的资料/预算预览与确认，以及 R3 原子采用的完整读集预览与逐次确认。预览使用当前
owner/novel/case/workspace 双重范围校验与原 domain facade，不建 grant、不排 Task、不写作者
资产。检查确认复用 `cases.submit_run` 的 exact operation ID、TaskRegistry `collaboration.run`
（最多 30 provider request、1800 秒 deadline、manual_resume）和原 budget snapshot；目标运行
上下文拒绝该独立根。case 的 `AgentRunBudget` 在模型请求前持久化，累计已用额度跨恢复不重置；
unknown 用量会在每次新请求预留前 fail closed，manual resume 同样拒绝 `usage_unknown`。
`author_operations_api.py` 独立导出 `/api/collaboration/author-operations`，由组合根先注册
本模块操作目录再挂载，以便共享 HTTP trace adapter 校验每条 route 的精确 `op_id`、phase、
confirmation 与 schema 字段。准备不排队、不改作者资产，也不创建或扩大 Grant。采用预览复核完整
read set、来源与检查回执；执行仍只调用既有 `merge_workspace`，沿用排他项目锁、逐资源
validate/apply、receipt、outbox 与 CAS。`merge_policy=whitespace_only` 不再绕过每次明确确认。
旧 `/api/collaboration` 领域 API 保持在旧 router；作者操作 UI 使用独立的 operation-bound 路由。

当前 port：正文工作稿、Scene、伏笔/揭示安排、世界书工作稿。工作区删除覆盖不能直接作为
领域废弃；仍走原领域确认。自定义配方只改变问题与检查清单，不增加能力、资料或联网权限。
实验开关默认关闭，工程测试、真实模型质量和生产灰度分别验收。

设计及验证边界见 [模块设计](../../../docs/modules/21_collaboration.md)。

## 持久理解

`cognition.py` 在作者明确开启 `Grant.retain_understanding` 后，将当前成功工作项且通过复核的解释
保存为独立于 run retention 的 head/commit/record。CAS、operation 幂等和 no_change 保留旧版本；
作者修正或撤回追加记录，机器结果不能覆盖作者决定。历史由 PG 守卫保护，仅可退役 current 指针，
项目永久删除仍级联清理。终态先释放原事务，再取项目排他锁、重验来源与授权，避免与正文保存反锁。
完整限制与消费契约见 [模块设计](../../../docs/modules/21_collaboration.md#持久理解的保留与复用)。

理解保留 Evolution 原回执、完整传递来源和实际作者/工作输入，限定作者回顾用途；
Scene 与历史阅读不能借该理解引入后见资料。规划器、成员和审查均读取授权完整来源，
字面回读的范围回执同时提供给审查；配方限定实际输出 schema，不安排越权工作。

### 本场条件假设与试改

`Grant.scene_state_trial` 绑定同 Scene 原状态指纹与完整条件比较 digest；所选 Scene 必须在已授权且未排除资料中。collect/检查/采用重新比较，范围、知识或新鲜度变化拒绝旧回执。InputManifest 保存假设，仅追加至作者的原资料上下文，注明不是历史、不能授予人物知识；读者/角色或 workspace 新稿检查不自动带入。资源状态影响按真实章节/scene chunks 锚定，只有 ready 且直接来源匹配才列 affected，其余保留未检查。

窄屏从本场状态进入试改先交接资料抽屉；冲突就地三方选择并按当前稿重建，原稿不被静默覆盖。
