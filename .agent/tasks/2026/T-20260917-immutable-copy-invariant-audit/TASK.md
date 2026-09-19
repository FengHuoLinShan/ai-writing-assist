---
id: T-20260917-immutable-copy-invariant-audit
title: demo copy 不可变历史修复与全库不变量冲突审计
status: delivered-on-branch
created: 2026-09-17T23:30:00+08:00
updated: 2026-09-19T21:00:00+08:00
---

# demo copy 不可变历史修复与全库不变量冲突审计

## 恢复快照

- 实际完成：原分支 tip `b62229e49` 已纳入整合分支；审查修正了关联资产快照 digest、跨模块 facade 边界和 demo-import 专用策略。D1–D5 与九项交付核查补在 [AUDIT.md](AUDIT.md)，正式决定见 ADR-0026。2026-09-19 定向单测 24 passed、真 PG E2E 2 passed、PostgreSQL 合并门禁 37 passed；跨栈总门禁见整合任务。
- 当前里程碑：整合验证中；旧记录中的 `2212e6dd9` 是重整前提交，旧测试总数不能当作当前结果。
- 下一步：整合分支合入 main 后，另行授权生产发布；发布后用真实账号验收「创建演示副本」。
- 阻塞：无。
- 生产核查（D4）：2026-09-17 旧快照见 [AUDIT.md](AUDIT.md)；2026-09-19 未重查生产数据，不对当前残留作断言。
- 最后核实：2026-09-19。

## 目标与验收

1. demo copy 复制协议重写：无 DELETE/占位回填落不可变表；行级拓扑 INSERT 最终状态；digest 按目标身份重算；canon 走追加导入修订（c0 → demo_import），receipt 用系统 demo-import 策略，不伪造作者授权；源 ID 零泄漏。
2. 全库「业务代码与数据库不变量冲突」审计（D1 触发器台账 / D2 写路径扫描 / D3 生命周期流 / D4 生产残留 / D5 测试覆盖矩阵），分类：确认缺陷（修）/ 高风险 / 设计债务 / 合理例外。
3. 测试：e2e 用 alembic head 库（触发器开启），语句监听器断言零不可变写；覆盖历史源、并发、回滚、幂等、泄漏扫描；补现有两个 demo copy 测试的源历史缺口。
4. ADR：持久化数据写入语义五分类与复制策略。
5. 九项交付报告（根因/模型/风险清单/逐项处置/不变量/测试矩阵/遗留/残留/已消除 bug 类别）。

## 关键决定与证据

- digest/receipt 绑定身份：`resource_revision_digest` 哈希含 novel_id+revision_id（modules/world/authority.py:652）；receipt 校验 receipt.novel_id/canon_revision_id/expected_previous_head（world_authority_service.py:809-817）⇒ canon 历史不可原样复制，重造 receipt 即伪造授权 ⇒ 用户拍板追加 demo_import 修订。
- story_outline_revisions：BEFORE UPDATE 触发器（20260716:60）+ 自引用 FK base/restored_from ⇒ demo copy 回填路径必炸（第二颗雷）。
- e2e conftest 跑 alembic head（触发器在），现有 demo copy 测试源无历史数据 ⇒ 分支覆盖缺口。
- 仅 demo_copy.py 用 Core 表级 SQL；ORM 层对四张 authority 守卫表无直接 UPDATE/DELETE。
- 线上：API 容器=f67845dc（deployment-state.json 为准，遗留 current-commit 文件陈旧停 8/6）；demo_project_copies=0；world_canon_revisions 全库 4 行（全部属 demo 源）。

上述线上数值仅为 2026-09-17 历史记录；当前生产状态须在发布验收时重新核实。
