---
id: T-20260911-full-codebase-review
title: 全代码库全量优化审查（并行执行）
status: completed
created: 2026-09-11T18:07:04+08:00
updated: 2026-09-11T22:30:00+08:00
---

# 全代码库全量优化审查（并行执行）

## 恢复快照

- 实际完成：**冻结基线静态审查交付**——`main@e7d0b8d5b` 的 2453/2453 跟踪路径均有覆盖账本状态，28 份槽位报告 + 9 条 P2 链走读；原审查汇总发现 241 条（P0=0/P1=4/P2=58/P3=179），但现有索引缺完整逐 ID 去重映射，不能机械复算该总数。交付物：[review-report.md](../../full-codebase-review/review-report.md)、[batch-plan.md](../../full-codebase-review/batch-plan.md)、[implementation-plan.md](../../full-codebase-review/implementation-plan.md)、[findings-ledger.md](../../full-codebase-review/findings-ledger.md)、[coverage-ledger.csv](../../full-codebase-review/coverage-ledger.csv)、[baseline.md](../../full-codebase-review/baseline.md)、units/ 下 28 份槽位报告。
- 当前里程碑：全部完成。优化实施是独立验收结果，未开始、未授权。
- 下一步：无（本任务仍闭环）。若用户要实施，按 implementation-plan.md 逐批授权；推荐先 R0a（F4-1 测试扫描修复）。
- 阻塞：无。
- 工作区：原审查为 `main@e7d0b8d5b`。独立复核时主工作区已为 `codex/frontend-fixes-20260911@bfc766ec1`；相对冻结账本新增 1 个跟踪文件、19 个账本 blob 已变化，他人 WIP 未动。
- 最后核实：2026-09-11T22:30:00+08:00。

## 目标与验收

- 目标与交付物：按 [全代码库优化审查计划](../../full-codebase-optimization-review-plan.md) 完成全量审查，交付审查总报告、覆盖账本、发现账本与带依赖的可执行优化批次表。并行组织方式按计划 §10。
- 完成条件：计划 §1 的五条全量完成标准；账本在 `.agent/tasks/full-codebase-review/`。
- 非目标：不实施优化、不改功能代码、不提交/合并/推送/部署；PG/浏览器/性能/真实模型验收仅在获准范围运行并如实记录。

## 上下文与边界

- 关键路径与来源：计划文件 §1–§10；[历史简化审查主记录](../../code-simplification-audit.md)（约 70 项候选仅作线索，逐项重新取证）。
- 硬约束与授权范围：用户要求按并行方式组织审查（委派授权来源）；子代理只读代码、仅写各自 `units/<slot>.md`；不运行测试套件（主 Agent 统一跑基线）。
- 依赖：本机 PG 5207、MinIO 受代理干扰、performance_probe 本机必败（P0 现场复核）。
- 已确认事实：规模与槽位划分见计划 §10.1/§10.3（28 个槽位；现有材料未保存可独立核验的子代理运行到槽位映射）。
- 假设与待决问题：无；波次间可暂停，已完成部分保持可交付。

## 里程碑与进度

- [x] W0 基线与覆盖账本（2026-09-11，baseline.md）
- [x] W1 基础横切 F1–F6（2026-09-11，1033 路径）
- [x] W2 领域与页面 D/E 组（2026-09-11，W2a–W2d 四个子波、18 槽位，1420 路径）
- [x] W3 交叉链 X1–X4 与性能取证（2026-09-11，9 链闭环；动态基准如实受阻）
- [x] P3/P4 裁定与批次表、总报告（2026-09-11，review-report.md + batch-plan.md）

## 决策、发现与失败

- 2026-09-11：并行分工按"单元可拆槽位、账本按路径唯一归属"设计；world/imports/story/evidence/前端页面按子域拆 2–3 槽位。证据：计划 §10.3。
- 2026-09-11：历史候选多项重大纠偏——`deep_import_phase01`/`deepseek_scene_probe` 删除为误报（真实验收工具链）、`frontend-console/docs` 已跟踪、A3-5 规模 24→64 处、A1-1"恒 403"不成立、mock autospec 担忧不成立（AST 守卫零违规）、"evals 全部 CI 活跃"仅 1 目标。
- 2026-09-11：P1 四条中两条为生产功能性错误（D5a-1 prompt 硬编码第三方内容、D5b-1 窄进程死亡窗口的显式恢复再次失败），均经主 Agent 独立实锤；按 §2 单列修复不混入优化。
- 2026-09-11 独立复核：D5b-1 精确触发面是 `phase=failed` 与 `recovery_required=true` 同时保留的窄进程死亡窗口；普通优雅失败是 dismiss-only。原批次遗漏 F4-1，且 R/B 大组多处混合不同风险和回滚方式，已重写 batch-plan.md 并新增 implementation-plan.md。
- 2026-09-11：教训——一次性脚本的正则归属规则需对抽样输出核对（world 槽位拆分曾整体错位 176 文件与 W2C 规则未生效，均由账本统计异常暴露并修复）；子代理 prompt 必须内嵌精确路径来源（账本/JSON）而非目录描述。

## 验证证据

- 2026-09-11 W0：门禁基线见 baseline.md §5（docs-check/lint/前端三件套全过；fast 层 2 失败均根因定位，test_identity 独立复跑 27 分钟通过实锤 F4-1）。
- 2026-09-11 各波合并：主 Agent 独立抽查 9 条头部发现（F4-1、F3-1、F6-1、D5a-1、D5b-1、D3b-1、D8b-1、D8c-3、X1-1）全部属实，记录于 review-report.md §4。
- 2026-09-11 收尾：`make docs-check` 通过；`git diff --check` 通过；`git status` 确认审查零代码改动。
- 2026-09-11 独立复核：3 个 `gpt-5.6-sol / low` 子代理分别核 R 组、B 组与报告完整性，主 Agent 复核并落盘；`units/` 程序化计数 28，冻结账本 2453 行且无重复，当前 `git ls-files` 2454（新增 1 路径、19 个旧路径 blob 漂移）。修改后 `make docs-check`、本地 Markdown 链接检查与 `git diff --check` 通过；`BASE_REF=origin/main` 仅因现有 imports WIP 要求模块文档复核，经 `--no-change-reason` 明确本批只改 `.agent` 报告后通过。

## 交付结果

- 已交付：冻结基线审查总报告、覆盖账本（2453 路径全归属并有状态）、发现账本与证据槽位、修订候选批次表、逐批实施计划、28 份槽位报告、基线记录。
- 未交付：优化实施（按计划为独立验收结果，未授权未开始）；PG critical/E2E/浏览器/动态性能/真实模型验收（如实未运行，见报告 §9）。
- 交付边界：全部为本地未提交文件；无提交、无远端、无 CI、无部署；代码零改动。
- 正式知识与后续任务：审查结论以本目录为准；实施按批次表另行授权立项。
