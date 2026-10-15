# A1 源化字段复核器

基线为 R1 已合入的 `4efe7f21a08646e7051923a40df989608f40a8ee`；原旧 v2 运行和其请求身份没有继续。
主执行笔记仍在 wave3-r1 树的同任务 TASK.md，本文件只记录 A1 可验收结果。

工具迁入 `backend/evals/g7_review`，保留原快照精确序列化 SHA、inventory 主键/物理字段、JSON pointer、
0/false、来源正文与 draft/hash/offset、完整来源及截止检查。项目 ID 改为调用方显式传入，不内置旧运行身份。
原 60 项合成测试随迁；新增角色隔离、两套合成语料的未来区间和字段值漂移拒绝测试。

`G7ReviewScope` 只开放 `eval.g7.source_field_review` 的 Sol/xhigh，attempts=1，每次核验相同 owner/Project
Luna/max snapshot。Ask World scope 不可调用 G7，G7 scope 不可调用 Ask World；其他入口默认暂停。
请求环境白名单及取消 stop/reap 沿用已合入的执行器。业务模型仍走原生 Luna/max。

独占数据库 `agent_e2e_g7_review`，127.0.0.1:65196，新建且从空库迁移；没有接触共享库。
验收在首次连接验证前冻结于 G7-FREEZE.json。每阶段独占 `.started`，无自动重放。
原始请求/响应在仓库外私有目录；G7-CALIBRATION.json 仅保留去原文标签、哈希和调用回执。

真实结果：正常账户连接验证 1 次 Luna/max，seeded 1 次 Sol/xhigh（32/32），独立合成 debug 1 次
Sol/xhigh（12/12）。原生退出全部为 0，无 unknown。模型判定均通过确定性引用/覆盖校验。
主 Agent 独立逐项核对标签及输入原文：正确/明确矛盾/局部来源不足/空字段均匹配，无待裁分歧。
这只证明冻结合成集合的复核器校准，**不证明诡秘质量，也不证明真人验收**，human_validated=false。

G7b 应在最终不可变快照完整后调用 `review_case()`：提供显式 projects、完整 inventory、实际源化字段和
绑定真实 Scene-local visible_until_* 的 as_of。通用绑定器验证调用方给定截止的有效性；截止来源的领域绑定
由 G7b 单元构建器承担，不能声称仅传入任意 as_of 即证明 Scene-local 隔离。来源未述及与抽取错误分列。

最终离线验证：evals 314 passed/2 optional skipped；lint、repo-gates、docs-check
BASE_REF=origin/main、git diff --check 通过。角色/失效 scope、取消回收、来源伪造等关键失败路径均覆盖。
