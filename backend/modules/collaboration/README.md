# Collaboration 创作试验

`/api/collaboration` 管理作者目标、持续授权、有限调查和隔离试改。模块持有派生工作区与
精确采用回执；正文、结构、世界书工作稿仍由 Writing、Story、World 持有。

`contracts.py` 冻结 Grant、InputManifest、Recipe、WorkProposal 与资源 port。
`cases.py` 校验 owner、项目、目标版本、授权截止与累计用量；续期保留历史及已消费请求。
`runtime.py` 通过原 PostgreSQL task lease 执行有限规划和独立成员步骤，使用 Project
冻结连接与当前账户 Key。角色历史、原始 Prompt 和密钥不进入公开 API。

`workspaces.py` 保存不可变 baseline + 累积 overlay。删除是显式 tombstone；读取试改不回退到
当前领域对象。新修订自动失去旧检查资格。检查同时验证领域输入、作者保留项、配方要求，
并绑定原稿与试改的精确文本。复核无法覆盖或来源变化时保持不确定。

`merge.py` 先取原项目排他写锁，重验完整读集、授权及精确检查，按领域 prepare/apply 执行
短事务，最后写 receipt 与 outbox。领域 apply 只 flush。确认重复仅返回已有回执。
`recovery.py` 重建基线或准备反向试改；同字段冲突返回供作者选择，不覆盖后续人工修改。
反向试改也需要重新检查与确认，原采用历史继续保留。

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
