# 分支与工作树完成度判断

核对基线：2026-10-17，`origin/main@a1b1053662d7`（地图 PR #249）。这是交付前快照；后续提交和 PR 状态以 Git/GitHub 为准。

## 覆盖与结论

- 126 个本地分支：118 个已有主干交付/等价或修正后继；3 个含本轮可交付实现或完成记录；1 个有未完成冻结验收工作；4 个明确的历史 archive。
- 实际远端仅 main 与 archive/main-legacy 两个分支；已用 `git ls-remote --heads origin` 核对。另有 26 个本机跟踪缓存（origin 21、upstream 5，两个 remote 是同一 URL），其中 origin 19 个、upstream 3 个缓存对应的远端分支已删除。缓存共 24 个已有交付/等价或后继，2 个为同一旧主干归档；upstream/main 缓存落后现 main。没有开放 PR。不 prune 缓存或删除实际分支。
- 63 个原有工作树，其中 16 个有未提交内容、共 210 个路径。本轮另建两个工作树，不切换或清理原工作树。
- 全量明细：[branches.csv](branches.csv)、[worktrees.csv](worktrees.csv)。私有保护快照记录完整 HEAD、逐路径状态与 SHA-256，不把本机原始证据或 ignored 数据打包进 PR。

## 判断方法

先检查 `merge-base --is-ancestor`，再检查 `git cherry origin/main <head>`；非等价历史查看原 PR 固定 head、重基后合并及同主题修正提交。分支名、ahead 数、干净状态、TASK 的 completed 均不能单独证明完成。

“已交付”只针对提交内容，不代表当前工作树的全部 WIP 已交付、真实质量已验收或可以删除。PR 后继类别明确保留旧 HEAD 与主干非逐补丁相同的事实，不重新合并较旧实现。

## 本轮选择

| 来源 | 选择与依据 | 保留的边界 |
|---|---|---|
| `codex/editorial-diagnosis-v1@dc0966c2f218`，22 个提交 | v1 审读提示词、跨章原文账本/引用重验、内部 A/B runner、v2–v4 合成集及多评阅者导入。两个原任务已有工程与冻结评测结果；新建 `completed-editorial-delivery` 从最新 main 集成，追加 review 和门禁 | 历史冻结 B 的真实模型结果不扩张成当前集成版本实测；S15 unchecked 两组 0/1 如实保留；不重跑模型 |
| `codex/guided-flow-borrowing` 的 `4116b657d`、`50281bd22`、`a14fb2cb2`、`1dae2f8f2`、`7eb8b3cc8`、`92ee66957`、`cd4bf9705` | 选取完成的恢复检查点、审计/文档刷新验证、审读设计及固定基线地图报告；按文件迁入文档交付分支并记录来源，避免重放旧的整树修改 | paused/active 的业务任务仍保留原状态；仅迁入已完成的 AGENTS/CLAUDE 去重，核对各转出规则仍在权威目标；旧运行时说明和全局导航不覆盖 main 后继内容 |
| `codex/audit-followup-plan@ab22fce43797` | 迁入两份完整规划/历史评审记录；三份实施计划已在 main，由现版保留 | 规划成果已完成，第三批实测目标仍 active；不按旧计划再次实现已合并工程 |
| 根目录三份研究及旧进度清单 | 文学技法、创作失配、导演分层均有完整报告、来源/反方核对和完成记录；原 10/16 进度清单按时点留档 | 不把研究建议变成 Accepted ADR、实现或效果证明；不重复文献检索或试用 |
| `director-scales-plan` 的六文件 WIP | 交付已完成 ADR-0042/计划起草、依据摘要、任务笔记和索引增量 | ADR 保持 Proposed，计划保持 Draft，全部业务实施未完成；B10-F2 延后决定不变 |
| `evolution-model-pools` 的三份关闭记录 | 产品实现和 CI 已随 PR #230 合入；只迁入合并后 TASK/REPORT/REVIEW | 不覆盖当前运行时或模型池实现，不做 500k 订阅能力/持续吞吐实测 |

## 已交付与保留对象

- 地图系列及修复已由 #249 交付。8 条 `map-review17-*` 补丁全部等价；助手地图结构、词表围栏、HTTP 留痕 guard 的非等价旧补丁分别有 main 后继 `416d44b39`、`8f27d3596`、`32e63b630`。不回灌旧实现。
- 九个 `map-fix-*` 原工作树仍有未提交文件，与 main 比较包括逐字相同及后续补修不同版本。其任务修复已由 #249 整合，原始补丁不自动等同新需求；全部保留。
- 审计工程 #241、#245–#248、能力尾项 #222、模型规则 #225、Luna 收敛 #226 等已有合并。后继 PR/patch 信息逐分支列在 CSV。
- `audit-wave3-evidence@cbe345504560` 的三项新提交及 A2/G7b/P4-E 终验尚不能认定完成，本轮不合入；不重启/重放 v3。
- G6b/G6c 原树、wave3-guimi-v3、wave3-r1 的冻结副本和运行证据保持原样。G6 产品修复已合并，不能因此宣布第三批真实终验完成。
- docs-refresh-luna 的产品文档已随 #238 合并。现 main 已有后续更新，原 67 路径 WIP 不整体覆盖；完成证据从已归档根记录选择。G2 的旧关闭文档也有较新 main 签收版，保持现版。
- 四条本地 archive 及远端 archive/main-legacy 仅保留：历史 Apple 方案、M4 主栈重写、formatter WIP、世界模型研究不满足当前直接集成条件，不据旧完成字样恢复实施。

## 验证与最终交付

审读的规范/规格 review、最新 main 集成验证和两个 PR 的最终结果记录在 [TASK.md](TASK.md)。只有必需门禁通过才按固定 head 普通 merge；不管理员绕过，不部署、不删除工作树或分支。

最终结果：审读实现 [#250](https://github.com/FengHuoLinShan/ai-writing-assist/pull/250) 与完成资料 [#251](https://github.com/FengHuoLinShan/ai-writing-assist/pull/251) 均已合入 main；三项本轮选择均已交付。原清单继续作为选择前时点快照保留，不将源分支 HEAD 改写成已被 main 逐提交包含。关闭证据及保留缺口见 TASK。
