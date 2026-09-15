---
id: T-20260915-main-integration
title: 整理新工作并合入本地 main
status: completed
created: 2026-09-15T09:30:00+08:00
updated: 2026-09-15T09:39:00+08:00
---

# 整理新工作并合入本地 main

## 恢复快照

- 实际完成：已刷新远端并盘点全部本地分支、远端候选和工作树；知识治理、任务轮询统一与 PR #136 已合入本地 `main`。PR #140 虽通过常规 CI，但 `eval` extra 真实导入复现不兼容，内容已从 `main` 撤出。
- 当前里程碑：集成树 `f3bc4614c` 已验证，本记录提交后快进本地 `main` 并清理已吸收的非归档工作树/分支。
- 下一步：无；如需远端交付须另行授权 push/PR merge。
- 阻塞：无。
- 工作区：主工作树 `codex/knowledge-governance` 已清洁；`codex/task-polling-unification` 工作树已清洁；archive 与脱离分支演示工作树均保留。
- 最后核实：2026-09-15T09:39:00+08:00。

## 目标与验收

- 目标与交付物：把分支和工作树中的已完成新工作组织成独立提交，验证后合入本地 `main`。
- 完成条件：候选有拓扑/冲突证据；全量 CI 与文档/空白检查通过；本地 `main` 指向已验证集成树；已吸收的干净非归档分支/工作树清理；受保护 WIP 指纹不变。
- 非目标：不推送、不合并远端 PR、不部署；不改动或删除 archive、演示工作树及其 WIP。

## 上下文与边界

- 关键路径与来源：仓库根 `AGENTS.md`、`.agent/PLANS.md`、安全分支整理 Skill。
- 硬约束与授权范围：用户授权本地整理、提交和合入 `main`；未授权 push、远端 PR merge 或部署。
- 依赖：`origin/main=4db3df9b6`；已采纳候选 `21ddd6f0a`、`5b32748e6`、`81216da51`；拒绝候选 `fbe10f811`。
- 已确认事实：PR #136 远端门禁全绿；PR #140 常规门禁除 MinIO 镜像 504 外通过，但把 `langchain-community` 升至 0.4.2 后，Python 3.13 真实 `import ragas` 报缺少 `langchain_community.chat_models.vertexai`。
- 假设与待决问题：无。

## 里程碑与进度

- [x] 盘点并保护所有工作树、未跟踪文件和 archive。
- [x] 将知识治理和轮询统一分别提交；格式化残留归档为 `archive/repo-formatting-wip-20260915`。
- [x] 在干净集成分支合并三个有效候选；撤出不兼容的 PR #140。
- [x] 完成全量验证并快进本地 `main`。
- [x] 清理已吸收的非归档分支/工作树并复核受保护 WIP。

## 决策、发现与失败

- 2026-09-15；archive 与脱离分支演示工作树均含历史或未提交 WIP，排除在本次合并/清理范围外。
- 2026-09-15；18 个格式化残留与功能无关，补丁已由 patch-id `14f799e5` 证明完整保存在 archive 提交 `6cba0f4cc`，不合入 `main`。
- 2026-09-15；PR #140 的浏览器失败虽是 MinIO 504，但其 `eval` extra 真实导入独立复现 `ModuleNotFoundError: langchain_community.chat_models.vertexai`；常规 CI 未安装该 extra，故拒绝该候选并恢复兼容钉死版本。

## 验证证据

- 知识治理：知识核心 45 passed；Prompt contracts 24 passed；docs-check 通过。
- 轮询统一：相关 Vitest 5 files / 226 tests passed；受影响文件 ESLint 与 docs-check 通过。
- 合并预览与实际合并：四候选均无冲突；PR #140 因补充验收失败撤出，其余三个候选保留。
- PR #140 对照检查：Python 3.13 + `eval` extra 使用 0.4.2 时 `import ragas` 复现缺失 `vertexai`；恢复 0.4.1 后 Ragas 0.4.3 与 `InstructorBaseRagasLLM` 导入通过。
- 最终 `main` 上 `make test-ci TEST_WORKERS=2`：deploy 270 passed；backend 5541 passed, 13 skipped，coverage 85.78%；frontend 191 files / 2491 tests passed；docs、secret hygiene、依赖审计和 Ruff 通过。

## 交付结果

- 已交付：三个有效候选已验证并合入本地 `main`；不兼容的 PR #140 已撤出；已吸收的干净 topic 分支/工作树已清理；受保护 WIP 保留。
- 未交付：无本地整理项。
- 交付边界：未 push、未远端合并、未部署。
- 正式知识与后续任务：无。
