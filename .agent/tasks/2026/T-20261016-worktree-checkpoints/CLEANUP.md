# 旧分支清理与恢复

核验时间：`2026-10-16T21:12:54.630001+08:00`。用户追加要求“清理旧分支”，仅处理上一轮已审查、修复并集成的9个固定旧HEAD。当前整合分支 `codex/map-enhancement-plan` 保留；未进行远端删除、推送、main合并或部署。

## 已清理范围

| 本地分支 | 原工作树目录 | 原HEAD |
|---|---|---|
| `codex/c2-ui-acceptance` | `map-assistant-operations` | `2c8c11c263da612af6a9b7ad8d40582d156871b1` |
| `codex/scene-director-impl` | `map-assistant-structure` | `1628717107a158b09f8f683c7223fbc65906e9ae` |
| `codex/map-clues-drafts` | `map-clues-drafts` | `a58027bedfca8f28bf6c14c71262d2e65848fe2a` |
| `codex/map-evolution-spatial` | `map-evolution-spatial` | `8a2aec71d974aa4915b065cc537eb5d5c30be2a1` |
| `codex/map-spatial-advisories` | `map-spatial-advisories` | `0369360723a7b48c3b7c1ba173f48becf54ee424` |
| `codex/map-spatial-brief` | `map-spatial-brief` | `4a39dd7524e3b7212a2eed785da757984e36cff7` |
| `codex/map-spatial-eval-driver` | `map-spatial-eval-driver` | `465a7e509f713ade38e0c8610d7fda501a2dc021` |
| `codex/operation-trace-report-impl` | `operation-trace-report-impl` | `b55497379b377dc8a5f12d6aa57c687d0c879598` |
| `codex/map-operation-catalog-impl` | `map-operation-catalog-impl` | `9fd1c83055db8390c0599b09825e3f5809089f57` |

这9个分支均已完成[语义对账与审查](INTEGRATION-REVIEW.md)，有效实现已集成或由后续更严格实现替代；原型是历史资料，没有独有待交付代码。清理前再次核实固定HEAD、干净状态、全部文件、符号链接及可见运行进程，使用普通 `git worktree remove` 和 `git branch -d` 逐项清理，没有强制丢弃。

## 恢复副本

私有恢复目录：`/Users/tywww/项目/ai-writing-assist/.git/cleanup-archives/map-old-branch-cleanup-20261016-210626`。目录权限700，位于共同Git目录中，不纳入源码提交。保留清理前全部工作树文件（包括ignored文件、空目录、原符号链接），约1.27 GB原始常规文件；未跟随符号链接读取外部目标。

- `reviewed-branches.bundle`：9个旧分支和清理前整合分支的完整历史；`git bundle verify`通过，已在独立临时裸库实际fetch全部10个分支，逐个核对9个旧HEAD，`git fsck --full`通过。
- 9份 `.tar.gz`：逐文件SHA-256及符号链接/目录清单与原现场一致；移除前再次核对现场和归档未变化。
- `manifest.json`、各工作树 `*-files.json`、`cleanup-progress.json`、`cleanup-verification.json`：固定HEAD、归档哈希及逐项结果。

例如恢复空间简报分支（命令在仓库根目录执行）：

```sh
git fetch '/Users/tywww/项目/ai-writing-assist/.git/cleanup-archives/map-old-branch-cleanup-20261016-210626/reviewed-branches.bundle' refs/heads/codex/map-spatial-brief:refs/heads/codex/map-spatial-brief
git worktree add .worktrees/map-spatial-brief codex/map-spatial-brief
```

若需还原原ignored文件，先将对应tar解压到临时目录，再复制该工作树目录内容到重新注册的工作树，**排除旧 `.git` 文件**。Git重新注册生成的 `.git` 必须保留。旧操作留痕原型migration仅为历史恢复资料，不应重新加入当前整合分支。

## 清理后核对

- 全仓库工作树由60降至51；地图系列由39降至30，其余29个地图工作树干净，整合工作树仅含本次任务记录变更。
- 其余50个工作树全部保留，49个HEAD和工作区状态未变；115个原受保护文件条目逐个复核一致，根工作树WIP和stash未变。
- 审稿工作树 `editorial-diagnosis-v1` 在本轮期间独立追加提交到 `30cf2ab3852de678b8250de457f97e6ccd4b99e3`，随后其任务笔记又出现WIP。本次只观察并记录，没有修改、恢复或提交这些内容；不能将并行变化称为未变。
- 除9个目标分支删除和上述独立审稿提交外，178项其他refs未变；整合分支随后仅追加本次文档提交。
- 整合工作树的生产代码、测试和正式文档与清理前 `2f9d2b1806b5bc0228d58e04e6b75ac1e1123bd0` 相同；本次Git清理不重跑业务测试。上轮完整离线CI和PG结果仍绑定原修复提交。

机器结果见[清理核验](artifacts/cleanup-verification.json)。本轮文档与secret门禁结果、最终本地提交状态以[TASK](TASK.md)和Git为准。
