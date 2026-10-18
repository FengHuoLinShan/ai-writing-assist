# PostgreSQL 回归基线核对

2026-10-18；仅合成数据、同一确切隔离 E2E 库。当前完整套件为 384 passed / 24 failed / 7 deselected。
将 `git archive HEAD` 的已跟踪源码解包到仓库外临时目录，HEAD 固定为
`98598127f933782f26019ca0e9970c53849c2a97`，使用锁定的同一 Python 环境和
`RUN_E2E_TESTS=1`/显式 E2E URL，仅重放 24 个失败，结果 24 failed（16.71s），失败身份集合完全一致。
这证明这些失败不依赖本任务未提交改动；不证明其无害，也不将整个套件记为通过。

| 领域 | 数量 | 基线症状 |
| --- | --- | --- |
| Agent team | 2 | 无效响应/过滤负例运行根预算耗尽 |
| Creative engine | 3 | 全表回执计数包含同隔离库其他作品记录 |
| Creative worker | 2 | 未知用量停点及恢复错误文案与断言不符 |
| Forecast performance | 1 | retained-history 场景返回 None |
| Project task gate | 2 | 并发事件等待超时 |
| Task coalescing | 1 | pending follower 身份断言不符 |
| Understanding owner | 13 | 合成 snapshot 缺 provider_id / 准备回执不可用，导致调用未发出 |

原始日志仅包含合成测试资料，位于 `/tmp/author-workspaces-postgresql-e2e.log`、
`/tmp/author-workspaces-baseline-e2e.log`，JUnit 同前缀 `.xml`；无凭据落盘。
首次基线命令遗漏显式 `-m`，24 项被默认过滤；补上与 Makefile 相同 marker 后才取得上述有效结果。
后续涉及这些领域或改动共享运行时，必须重验受影响用例并区分已知基线与新增失败。

## 审查整改后的扩大门禁（2026-10-18）

本轮首次 PG critical 为 102 passed / 6 failed：三项空库/历史迁移失败来自本任务新清单
缺少 ORM 声明的 `novel_id` 索引，属于新增缺陷，已用增量迁移
`20261018_review_scope_index` 修复，不能归入上面的历史基线。另外两项 Project task gate
超时及一项 task coalescing follower 身份失败与上方已验证的干净 HEAD 失败身份一致。
最终重跑 **105 passed / 3 failed**，三项迁移失败均消除，只剩上述三个已确认历史失败。
原始失败日志为 `/tmp/author-workspaces-review/fix-pg-critical.log`，最终日志为
`/tmp/author-workspaces-review/fix-pg-critical-final.log`。

首次完整快速层为 9287 passed / 4 failed / 2 skipped，覆盖率 85.32%；四项均为本任务遗漏的
能力/路由/固定输出预算治理接线，已修正，治理 31 项通过。最终完整快速层为
**9291 passed / 2 skipped**，覆盖率 **85.32%**，`fix-backend-full-final.log`。
部署契约 324 项、锁定依赖审计、secret hygiene 及 Ruff lint 通过；不能把上述首次整条
`make test-ci` 记为成功，最终各子门禁另行记录。

全仓 Ruff format 当前 167 个未格式化文件，均在干净 HEAD 的 169 个失败文件集合内；
新增失败为空。用 `git archive 98598127f933782f26019ca0e9970c53849c2a97 backend`
在仓库外解包并使用当前相同 Ruff 核验，未批量改动历史文件。本任务新增帮助测试中的
一处格式问题已修，修复涉及的 17 个 Python 实现/测试/迁移文件格式检查通过。
证据：`/tmp/author-workspaces-review/fix-format-baseline.log`、`fix-format-rechecked.log`、
`fix-format-comparison.txt`、`fix-format-touched.log`；后续新格式问题仍须阻断。
