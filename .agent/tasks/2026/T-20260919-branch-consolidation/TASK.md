---
id: T-20260919-branch-consolidation
title: 逐分支审查、修复、合入 main 与安全清理
status: active
created: 2026-09-19T00:00:00+08:00
updated: 2026-09-19T00:00:00+08:00
---

# 分支整合

## 恢复快照

- 实际完成：已 fetch、盘点分支与 worktree；独立整合 worktree 从 origin/main d66eb40cb 建立。
- 当前里程碑：逐分支审查中。
- 下一步：核实领先分支的 Standards/Spec、依赖兼容性和适用测试后，顺序整合。
- 阻塞：无。
- 工作区：整合分支 codex/branch-consolidation-20260919；主工作树、ai-generation-quality、归档研究及 detached demo 均有受保护 WIP，不改动。
- 最后核实：2026-09-19。

## 目标与验收

- 目标与交付物：逐个审查待合并分支，修复发现的问题，验证后合入 main，安全清理已整合分支。
- 完成条件：每个分支有纳入/保留判断；纳入内容完成项目门禁；main 内容正确；不丢失 WIP 或归档历史。
- 非目标：生产发布、覆盖或删除真实项目数据。

## 上下文与边界

- 关键路径与来源：AGENTS.md、development-guide.md、testing-guide.md、各分支 diff、开放 PR。
- 硬约束与授权范围：用户明确授权审查、修复、合并和清理；推送与部署分别核实授权边界。
- 依赖：本地 Git 与适用测试环境。
- 已确认事实：旧 World/LLM 开发分支均已包含于 main；归档分支须保留；demo-copy、前端修复、resume-qr 及 8 个 Dependabot 分支领先 origin/main。
- 假设与待决问题：归档和未提交 WIP 不视为待合并提交；仅清理已证实整合且无工作树风险的本地引用。

## 里程碑与进度

- [ ] 逐分支审查并记录处置。
- [ ] 修复和验证纳入内容。
- [ ] 合入 main 并清理安全引用。

## 决策、发现与失败

- 2026-09-19：Dependabot 后端组把 langchain-community 0.4.1 改为已知不兼容的 0.4.2，须修复后纳入。

## 验证证据

- 2026-09-19：基线 `make docs-check` 通过；其余待执行。

## 交付结果

- 已交付：无。
- 未交付：整合、最终验证和清理。
- 交付边界：目前仅本地隔离分支；未修改 main、未推送、未部署。
- 正式知识与后续任务：无。
