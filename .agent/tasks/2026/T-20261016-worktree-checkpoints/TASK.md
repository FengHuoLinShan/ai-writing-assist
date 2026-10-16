---
id: T-20261016-worktree-checkpoints
title: 地图增强旧分支审查、修复、集成与清理
status: completed
created: 2026-10-16T20:05:54+08:00
updated: 2026-10-16T21:14:51+08:00
---

# 地图增强旧分支收尾

## 恢复快照

- 追加授权：用户明确要求“清理旧分支”，恢复本任务，仅清理本报告已审查集成的9个本地旧分支及对应工作树。当前整合分支、其余工作树、远端分支与范围外WIP保留。
- 清理进度：9个固定旧分支及工作树已在完整私有归档、逐文件校验后正常移除，bundle已实际恢复fetch并fsck通过。全仓库60→51、地图39→30；详细范围和恢复方式见[CLEANUP](CLEANUP.md)，机器结果见[清理核验](artifacts/cleanup-verification.json)。本轮文档与secret门禁通过，清理结果以本次主题分支提交留存；最终提交号由Git HEAD查询。

- 用户授权：先保存地图系列各工作树，再直接 review 旧分支、修复、集成、提交并收尾。所有工程动作在 `codex/map-enhancement-plan` 完成；没有 push、PR、main 合并或部署，也未调用真实模型或重放冻结评测。
- 审查基线：`34574f6cf70701116997a1aa7919468ff1391168`；本轮业务修复 `d4feba9023f5ed1daceb72e663f7ed88f000c297`，审查证据 `9e5726aaa5534ceca30a02b993ec60f4abe468b2`，历史归并 `8834efccd6aa05339dff141b5114f568ecf24cdd`。最后的任务关闭提交由 Git HEAD 查询；之后仅文档记录变化。
- 9个固定旧HEAD（8分支27个差异补丁、旧留痕原型1个）均已语义对账，有效能力在当前实现中保留或被更严格实现替代；无独有生产功能遗漏。两轴结论和逐分支处置见 [审查报告](INTEGRATION-REVIEW.md) 及 [机器对账](artifacts/old-branch-disposition.json)。
- 本轮修复：导演确认条目与各角色 POV 交集、父回合/冻结/恢复范围证明；空间提醒复用精确Story有效期策略；HTTP续算预算预览500；UTC历史恢复期限；C0配置状态文档。旧原型migration没有引入。
- 归并前后tree相同，9个旧HEAD已可达；39个地图工作树均已核对干净，其他59个worktree HEAD、其他refs与stash不变。该阶段保留全部旧分支、工作树及ignored数据；用户随后明确授权的9分支清理见上方最新记录。
- 下一步：本次旧分支审查、修复、集成与授权清理已完成，无剩余必需步骤。三份产品计划继续active，真实模型/作者、长篇、长期使用及外部路线图条件仍按原任务验收，不能从工程绿色推定通过。

## 目标与验收

- [x] 保全原WIP、本地提交、固定待review范围。
- [x] Standards / Spec 两轴审查9分支、按真实调用链修复并回归。
- [x] 完整本地门禁达到既有阈值，不删除断言、不改覆盖率范围。
- [x] 在地图主题分支记录已被替代的分支历史，核实文件树不变和旧HEAD可达。
- [x] 更新报告、开放任务索引及三份计划恢复快照，提交收尾记录。
- [x] 按追加授权归档并清理9个旧分支和对应工作树；核验可恢复性及范围外保护。
- [x] 通过本次清理文档门禁，提交清理结果并关闭任务。

## 验证

- 本次清理：9份完整现场归档逐文件核验、bundle实际恢复及fsck通过；49个其他工作树HEAD/状态和115个原受保护文件条目未变。审稿工作树发生独立提交及后续WIP，已保持原样。正式生产文件未变；本轮 `make docs-check BASE_REF=origin/main`、`make secret-hygiene`、`git diff --check` 通过；不重跑业务测试。

- 最终 `make test-ci TEST_WORKERS=2` exit0：后端**9108 passed / 2 skipped**，覆盖率**85.00%**（145112 statements / 21765 missing，门槛85%），前端**257文件 / 3234 passed**，部署契约**324 passed**；Ruff、依赖审计、secret hygiene与docs通过。
- 独立临时PostgreSQL 17导演历史/锁/预算/真实worker回归**10 passed**；传输使用合成响应，该专库已停止、保留数据和日志。
- `make docs-check BASE_REF=origin/main`、`make repo-gates`、12个变动Python文件格式及 `git diff --check` 通过；保留3个既有长度提示。
- 59项定向回归、12项确认范围与完整离线流程回归通过；首轮9101项通过但84.78%未达门槛及85.02%增量统计仅作过程记录，最终采用从头全量85.00%。
- [验证摘要](artifacts/verification.json)、[集成与范围外保护核对](artifacts/integration-verification.json)、[地图工作树快照](artifacts/worktrees-after-review.csv)。覆盖率刚达门槛，后续生产代码变动须继续运行同一门禁。

## 边界与保留

- R3–R6、holdout、能力默认开关、Guimi v3固定HEAD与受保护验收项目/数据库未更动；无真实模型、稿件、作者、浏览器或生产验收。
- 原126个范围外文件有125个原始字节不变；另一个editorial覆盖率说明文件在范围外被移除，现场还存在其任务笔记WIP，本轮未修改、恢复或提交。原副本在任务前备份保留。其他任务与范围外WIP不纳入本次提交。
- 新恢复快照 `/private/tmp/map-old-branch-integration-20261016-201744`；原WIP/文件哈希/归档 `/private/tmp/ai-writing-assist-worktree-commits-20261016-200554`。
- 上轮提交：整合业务 `651df05722abc7bbc6a47a42dbee77c43b5faf5f`、旧原型WIP `9fd1c83055db8390c0599b09825e3f5809089f57`、主目录历史报告 `cd4bf9705f4228b3b6163d749a3e499bf890cc0e`；原39树明细 [WORKTREES.csv](WORKTREES.csv)，原待审查清单 [REVIEW.md](REVIEW.md) 保留历史身份。
