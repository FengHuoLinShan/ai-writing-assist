---
id: T-20261016-branch-progress
title: 任务分支进度盘点与交付边界对账
status: completed
created: 2026-10-16T19:41:53+08:00
updated: 2026-10-16T19:48:00+08:00
---

# 任务分支进度

## 恢复快照

- 已完成：盘点全部本地分支与已注册 worktree，核实远端 main、PR 状态，按所属任务整理交付、验证、剩余工作及 WIP。
- 基线：远端 main 与本地 origin/main 均为 `00d861283e34bdc0ef3f34ee5605c71e1f89c553`。远端通过 `git ls-remote` 核实，没有 fetch、切分支或修改任何 Git ref。
- 清单时点：2026-10-16T19:41:53+08:00；随后复核审读 lint/17 项测试、近期 main CI、8 条 review17 分支补丁等价性。
- 当前工作区：主目录 `codex/guided-flow-borrowing@92ee66957114544889eca47956f9e9d22d2cf5b6`。
- 下一步：本次整理无剩余必需操作；继续具体任务时，先进入下表指定主工作区，读取其主 TASK 并核实现时状态。
- 授权范围：仅整理进度与任务记录。未提交、推送、创建 PR、合并、部署、删除或恢复分支，未运行模型或连接业务数据库。

## 目标与验收

- 覆盖全部本地分支与已注册工作区；将 Git 提交关系、PR 交付、工作区 WIP 与任务验收分开记录。
- 不把未被 main 按祖先关系包含的分支都算成未交付工作，也不以分支祖先关系或补丁等价性核销 WIP。
- 本地分支明细见 [branches.csv](branches.csv)，工作区与原始状态见 [worktrees.csv](worktrees.csv)。这是时点快照，继续开发后须重新检查，不作为长期事实源。

## 总览

- 共 **123 个本地分支**（含 main 与 4 个 archive 分支）、**60 个 worktree**，其中 **9 个 worktree 有未提交内容**。
- 26 个本地分支 HEAD 已被 main 按祖先关系包含（含 main 自身）；另 97 个未被这样包含，含 4 个历史归档。
- 上述 97 不等于 97 项未交付任务：例如 `audit-review-fixes`、`capability-tail-fixes`、`luna-business-model-rules`、`audit-wave3-r1` 的当前 HEAD 已分别随 PR #241/#222/#225/#245 合并，只是 squash 后提交身份不同。
- GitHub 当前 **无开放 PR**。地图整合与审读 A/B 的最新本地提交均不在 main 中。
- 8 条 `map-review17-*` 实现分支的 10 个非合并补丁经 `git cherry codex/map-enhancement-plan <branch>` 核实全部为 `-`，没有未匹配补丁。这批已经纳入本地整合分支，不再列成 8 项待集成工作；不是 main 交付或清理授权。

## 主要任务进度

|任务 / 主分支|已完成与验证|未完成 / 可执行下一步|
|---|---|---|
|地图、助手操作与世界对象整合：`codex/map-enhancement-plan@59537b4cb`|相对 main 有 314 个提交、落后 0；覆盖地图、Goal Runs、档案、场景导演、人物卡、章节排序等。剩余 17 项审查工作的 10 个补丁已集成；后续 8 项及 4 项 P2 补修仍在本地 WIP。最新主任务记录：后端 9092 passed/2 skipped、前端 3234 passed、独立 PG 7 passed、Chromium 2 passed，lint/docs/repo-gates 通过。|**覆盖率 84.37%，低于 85%，完整 CI 未通过**；48 个改动路径未提交。先补足有效覆盖并复跑门禁、评审当前 WIP，再考虑 Git 交付。真实质量、作者验收、C1 长篇、A4 数周数据等缺口继续保留；R3–R6 等封存运行不重放。|
|编辑审读诊断 A/B：`codex/editorial-diagnosis-v1@2e3b4eb69`|相对 main 有 6 个提交、落后 0。新增 17 项回归和合并预算修复已随 `c0f4fd2b28237ff6ce1ed35c45d2644cf2a95a4c` 提交；当前重新执行 **17 passed**、**make lint 通过**，此前 27 项 lint 阻塞已解除。主任务另记录 186 项定向测试与 26 个 Prompt 合约通过。|**真实模型 0 请求**；专用 `codex_luna_runtime_test` 的 DATABASE_URL/认证缺失，尚无盲评包。恢复原任务时先配置专用库并核验 owner/Project profile，再按原授权 smoke。未重跑稳定版本的单次全库覆盖率门禁；本次补测说明仍未跟踪。|
|审计第三批 / Guimi v3：`codex/audit-wave3-evidence@cbe345504`；主笔记在 `wave3-r1`|第三批工程 PR #243–#248 均已合并；证据分支另有 3 个本地提交、落后 main 7 个。G6b/G6c 已关闭并保留失败样本与冻结证据。|A2/G7b/P4-E 尚未签收。主笔记最后记录演化 5/63、DeepImport failed、并发冻结偏差；这是旧观察，**本次没有连接真实库或复核运行进程，不能称仍在运行或已结束**。下一步仅在原任务范围内只读核实终态与累计账本；不重启、不重放、不热改 runtime。|
|根工作区文档归档与审读设计：`codex/guided-flow-borrowing@92ee66957`|7 个本地文档/任务记录提交，落后 main 48 个；审读改进设计已完成。|尚未推送、无 PR。5 个原有未跟踪文件（两份研究各 TASK/RESEARCH 与 out 审查报告）保留；需要交付时按主题核对文档与最新 main，不夹带其他工作区业务代码。|
|审计后续计划：`codex/audit-followup-plan@ab22fce43`|6 个本地计划/记录提交、落后 main 47 个；工作区干净。关联工程已有多批合并记录。|计划记录本身仍是本地提交；不因旧计划 open 状态重复实现已合入工程。按具体任务的剩余质量/验收缺口继续。|
|历史文档刷新：`codex/docs-refresh-luna@22bb49978`|成果已由 [PR #238](https://github.com/FengHuoLinShan/ai-writing-assist/pull/238) 集成 main；原工作区保留交付材料。|原树有 67 个未提交路径；与当前 main 对比仅 2 个逐字相同、31 个不同、34 个不在 main（含研究/验收资料）。保留全部材料，不能整体视为可丢弃副本。|

地图、审读及第三批的测试总数分别绑定各自工作区与时点，不能相加或互相替代。本轮只实际复跑审读 17 项和该树 lint；地图、PG、前端与模型结果均来自对应任务记录。

## 唯一主记录与恢复入口

- 地图/操作/世界推进的当前共同整合工作区是 `.worktrees/map-enhancement-plan`。主记录分别在该树 `.agent/tasks/2026/T-20261015-map-enhancement-design/TASK.md`、`T-20261015-agent-operation-surface/TASK.md`、`T-20261015-character-world-progression/TASK.md`；以最新修复账本与当前代码为准，旧段中的“剩余 17 项”已被后续完成记录替代。
- 审读主记录：`.worktrees/editorial-diagnosis-v1/.agent/tasks/2026/T-20261016-editorial-diagnosis-v1/TASK.md`；本轮只更新自己维护的 `TEST-COVERAGE.md`，不竞争主任务写入权。
- 第三批唯一主记录：`.worktrees/wave3-r1/.agent/tasks/2026/T-20261015-audit-wave3/TASK.md`。runtime 位于 `.worktrees/wave3-guimi-v3@4efe7f21a`，冻结 backend/HEAD 不动；交付证据位于 `.worktrees/wave3-evidence`。
- 旧 Guimi60 对比任务仍按根目录 `T-20261012-guimi60-codex-comparison/TASK.md` 的 paused 边界保留；第三批 v3 与旧 v2 不是同一运行，不从旧暂停记录推断 v3 当前状态。

## 未提交内容保留清单

数量按快照的文件路径计，包含展开后的未跟踪文件；根目录数字不含本次新建的进度记录。

|工作区|路径数|性质与处置|
|---|---:|---|
|主目录 `guided-flow-borrowing`|5|独立研究资料与审查报告；保留。|
|`docs-refresh-luna`|67|原文档、研究、图示与验收材料；保留。|
|`evolution-model-pools`（detached）|4|PR #230 合并后的关闭记录；产品已交付，记录未提交。|
|`g6b-recalibration`|28|G6b/G6c 源码/Prompt 副本与冻结证据；已消费评测不重放、不改写。|
|`editorial-diagnosis-v1`|1|本次补测说明；测试及预算修复已提交。|
|`map-enhancement-plan`|48|后续补修、回归、文档及交接，属于当前未交付 WIP。|
|`map-operation-catalog-impl`|9|旧操作留痕实现 WIP；9 个文件均与整合分支内容不同，未据此裁定删除。|
|`wave3-guimi-v3`|6|固定运行的驱动/冻结副本；保留。|
|`wave3-r1`|3|主任务进度、历史与清理记录；保留。|

4 个 archive 分支、其余干净工作区、stashes 和 ignored 数据均未清理。干净与已合并均不代表可自动删除。

## 远端验证边界

- 远端 main 固定在 `00d861283`；读取其 Actions 结果：Backend CI、Frontend CI、repo-gates、Architecture docs、Production Image CI、CodeQL 均为 completed/success。
- 同一 SHA 的后续定时 [Backend PostgreSQL E2E](https://github.com/FengHuoLinShan/ai-writing-assist/actions/runs/38804015571) 为 completed/failure（2026-10-16T04:41:42+08:00 启动），失败步骤为 `Run the full serial PostgreSQL E2E suite`，另有 Dependabot Updates failure。因此不报告“main 全部 CI 绿色”。已核实失败工作流与步骤，未分析日志或复现根因。
- 地图与审读当前提交均没有开放 PR；不以 main CI 替代它们的分支验收，也未核实生产部署版本。

## 验证与交付

- Git：`worktree list --porcelain`、`for-each-ref`、各工作区 `status`、`rev-list origin/main...HEAD`、远端 main 及 PR/Actions 元数据；8 条 review17 分支补丁等价性检查。
- 审读：`make lint` 通过；`test_editorial_execution_hooks.py` 17 passed（2.16s），对应 `2e3b4eb69`，工作区没有业务源码未提交差异。
- 文档：收尾 `make docs-check BASE_REF=origin/main` 与两处工作区的 `git diff --check` 通过；CSV 123/60 行、路径与 Markdown 链接核对通过。本次任务目录及自有补测说明之外的 170 份已有 WIP 文件 SHA-256 未变，123 个分支引用与 60 个 worktree HEAD 均未变。
- 已交付：本 TASK、123 行分支清单、60 行工作区清单、补测说明的最新进度补记。只写本地记录，不变更其他任务状态或全局记忆。
