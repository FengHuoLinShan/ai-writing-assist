---
id: T-20260917-immutable-copy-invariant-audit
title: demo copy 不可变历史修复与全库不变量冲突审计
status: delivered-on-branch
created: 2026-09-17T23:30:00+08:00
updated: 2026-09-17T23:30:00+08:00
---

# demo copy 不可变历史修复与全库不变量冲突审计

## 恢复快照

- 实际完成：根因修复 + 全库审计 + 测试 + ADR-0026 全部落地并提交。commit `2212e6dd9`（分支 `codex/demo-copy-immutable-history`，基线 origin/main d66eb40cb）。验证：backend 全量 5094 passed；e2e 133 passed + 新增 3 个 demo-copy e2e 全绿（真 PG 触发器、历史源、回滚无残留、重试幂等、并发）；lint 全过；docs-check 通过。e2e 有 3 个基线失败（test_02_world 两例 + test_assistant_migration 一例），在未改动 main 上同样失败，与本分支无关。
- 当前里程碑：已交付待评审。合入 main 与生产发布需另行授权。
- 下一步：评审合并；线上发布后用一个真实账号点击「创建演示副本」做一次线上验收。
- 阻塞：无。
- 生产核查（D4）：demo_project_copies=0（功能从未成功过，无残留）；demo 源 outline/page-revision/template-revision 均 0 行（outline 雷未引爆，修复顺带排除）；world_canon_revisions 仅 4 行全属源项目；每次失败尝试都死于媒体复制之前的同一条 DELETE 且单事务回滚——生产无脏数据、无孤儿对象。遗留 `deploy/.state/current-commit` 旧文件停在 8/6（deployment-state.json 为准，建议运维顺手清理）。
- 最后核实：2026-09-17。

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
