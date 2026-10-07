# 事件软删合并审查

原被审提交 44c9cc1032d958ec484cefca9622b5c36a90adad，基线
9e98128775fc53d5672e8f47eccb5a325522fcf1。两路只读审查由 code-review 技能触发，
主 Agent 核查调用链并修复。下列原问题均已修复，不计为当前未解决问题。

## Standards

- P1：迁移 downgrade 对 deprecated 行执行 DELETE，违反已采用对象保留历史规则。
  改为在 events 表锁内检查，存在软删历史即拒绝降级，应用回退保留 schema。
- P2：并发复活以无锁读判断旧状态，两个请求可以成功并静默覆盖。
  改为复用既有 CoreEntity 锁与刷新后的 Event 读取。

本轴 2 项，原最高 P1；复核未发现剩余阻断或值得单列的架构异味。

## Spec

- P1：downgrade 硬删历史与 AO-12“删除只置 deprecated”不一致；已按上述方式修复。
- P2：并发首次创建/复活绕过 AO-12 的重复创建 409；创建前按 UUID 顺序锁定事件与地点，
  锁后读取当前状态，竞争者返回 409。
- P2：update 检查 canonical 后可能与 delete 交错，继续更新 deprecated 行。
  更新与删除共用父实体锁，更新锁后回读；未显式修改地点时检测地点漂移并返回 409。

本轴 3 项，原最高 P1；复核确认三个问题闭合，未发现新增产品范围。
主 Agent 另补锁前删除交错的确定性 PG 用例，避免仅用 stale Session 代替真实竞争验证。

## 验证边界

两轴复核只做代码审查；实际 PostgreSQL、单测与 CI 结果记于 [任务记录](TASK.md)。
活跃读取过滤、CoreEntity 不随扩展软删、fusion 排除 status 保持既有指纹均已核查。
未运行真实模型、作者试用或生产迁移/部署。
