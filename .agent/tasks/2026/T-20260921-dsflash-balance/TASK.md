---
id: T-20260921-dsflash-balance
title: DS Flash context 与 effort 平衡和质量优先统一
status: completed
created: 2026-09-21T13:00:00+08:00
updated: 2026-09-21T11:42:11+08:00
---

# DS Flash 参数调整

## 恢复快照
- 工作区：`/Users/tywww/.codex/worktrees/dsflash-balance/ai-writing-assist`，`codex/dsflash-balance`，origin/main 6e901693a。
- 已完成：普通RP high及128K/192K阈值；保留256K摘要/400K硬输入；World pro/导入高质量整条调用链max、至少65,536输出；同账户模型、已有RP快照和数据门禁保留。
- 参数依据与边界：[REPORT.md](REPORT.md)。
- 下一步：本地交付完成，后续仅在用户授权后提交/合并/部署或进行新的付费A/B。
- 阻塞：无。无付费调用、提交、推送、合并、部署授权。

## 目标与验收
- 依据已有实测优化普通路径 context/effort；已有 high_quality/pro 均质量优先。
- 保留确认/可见性/novel 隔离、审查资料等价、已冻结旧运行；有界超时和请求门禁仍保留。
- 相关测试、完整 make test、lint、docs-check BASE_REF=origin/main 和 diff 检查。

## 上下文与证据
- 原仓库忽略目录 `tools/deepseek_scene_probe/runs/`：Phase2 8K–16K 输出 53/60 截断，24K–32K 1/16 截断；Phase1b 2048 上限 1/57 截断。只证明这些历史配置的截断，不是当前质量/速度对照。
- `.agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/REPORT.md`：审查漏报，生成与审查资料曾不一致；不能靠裁掉资料/提高 effort 宣称质量改善。
- `.agent/tasks/2026/T-20260920-agent-teams/QUALITY.md`：单次审查 10–50s，多步 96–193s；不同路径非 effort A/B。
- 官方 thinking/API docs 2026-09-21 查询支持 low/high/max；只校核参数语义，不进行新付费实验。

## 决策与假设
- 普通复杂任务 high；窄查证 low；高质量 max 和更充足输出余量，不换账户 provider。
- RP 新默认更早整理历史，保持完整固定资料与400K硬输入边界；已有快照继续原参数。调优是待后续真实对照验证的策略，不能声称已达最优。

## 进度与验证
- [x] 调查与基线 docs-check。
- [x] 实现与参数回归。
- [x] 完整测试、lint、文档门禁、交付。

## 最终验证

- `PYTEST_ADDOPTS='-q -n 2 --dist=loadscope --tb=short' make test`：5882 passed，13 skipped，101.76s；一个既有同步测试带asyncio标记警告。
- 最终将普通摘要容量保留256K后，capability、interaction services、project runtime、Phase3回归111 passed，7.96s；同时覆盖两档连续摘要、原始尾部保留、应急恢复、账户max冻结和请求参数。
- `make lint`、`make docs-check BASE_REF=origin/main`、`git diff --check`：通过。
- 首轮失败包括旧替身不接受新quality参数，已同步；初次将并行参数放make ARGS触发测试harness的嵌套make比较冲突，改用PYTEST_ADDOPTS后原断言通过，没有修改门禁。
- 没有新增付费模型调用、真实数据修改或浏览器操作；没有文学质量或成本收益A/B结论。
- 本地未提交、未推送、未合并、未部署。原主工作区WIP未改。
