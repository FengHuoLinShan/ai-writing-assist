---
id: T-20260916-world-verified-review
title: World 共创可验证反例审查闭环
status: completed
created: 2026-09-16T17:38:58+08:00
updated: 2026-09-16T20:36:47+08:00
---

# World 共创可验证反例审查闭环

## 恢复快照

- 实际完成：后端实现与原有回归保持不变；已完成 11 组 baseline/candidate DeepSeek 真实调用、匿名双审与 Terra 裁决，以及 PR #143/#145 共用 Writing 真实 smoke。
- 当前里程碑：真实调用验收已结束，质量 gate 失败；不据此宣称 candidate 提升质量。
- 下一步：若继续修复，应先定位 candidate 11/11 被知识复审阻断的共同根因，再另行授权新一轮付费验收；代码交付动作仍按用户后续指令执行。
- 阻塞：当前 candidate 不满足发布质量门禁。baseline 严重错误 8，candidate 11，未严格减少。
- 工作区：`/Users/tywww/.codex/worktrees/world-verified-review/ai-writing-assist`，分支 `codex/world-verified-review`，基线 `f67845dc12e675af12b896e0d6b5328474c10810`；主工作区未提交宣传录屏 WIP 不属于本任务。
- 最后核实：2026-09-16T20:36:47+08:00。

## 目标与验收

- 目标与交付物：仅在 World 设计精细模式加入任务卡、两路隔离审查、逐项核验、最多一次定向返修、知识复审和终审；保存链绑定任务回执，作者界面只展示关键结论。
- 完成条件：计划指定后端、保存、恢复、前端和文档行为落地；受影响测试、Prompt 契约、lint/build、文档门禁与 diff 检查通过。
- 非目标：新的多 Agent 平台、队列、数据库表、通用事实库；更改快速模式、聊天、Story/Writing；真实付费模型盲评、提交、推送、合并或部署。

## 上下文与边界

- 关键路径与来源：`world_generation_center_service.py`、World schema/task/save 服务、`WorldDesignPanel.vue`；ADR-0023、ADR-0025、World/Frontend/Infrastructure/Prompt 当前文档。
- 硬约束与授权范围：沿用项目模型快照、Evidence confirmation、`world.generation.cocreation` 根能力、任务 lease/CAS 与 checkpoint；问题卡仅经独立核验后返修；作者编辑使审查失效。
- 依赖：现有 managed structured LLM、knowledge governance、stable hash、任务私有 result 过滤和 eval review/adjudication。
- 已确认事实：用户选择 World 优先、只看关键结论、完整闭环仅用于精细模式；快速模式保持现状。
- 假设与待决问题：无产品待决；实现中以当前代码与测试裁定兼容细节。

## 里程碑与进度

- [x] 完成后端 typed contract、固定编排、预算和恢复回执。
- [x] 完成保存绑定、作者编辑失效语义及前端关键结论。
- [x] 完成回归、离线 eval fixture/入口和当前文档同步。
- [x] 完成 11 类 World 双臂真实调用、盲评、裁决与离线 gate。
- [x] 完成 PR #143 运行信封和 PR #145 成果追踪/精确失效共享 Writing smoke。

## 决策、发现与失败

- 2026-09-16：复用现有确定性服务编排，不建设自治多 Agent 运行时；符合 ADR-0023 与已批准计划。
- 2026-09-16：使用独立 worktree，避免覆盖主工作区未提交 WIP。
- 2026-09-16：运行信封不缓存结构化响应，因此在业务 task 私有 result 增加稳定阶段 checkpoint；输入 hash 不同失败关闭，同输入重排逐阶段复用。
- 2026-09-16：质量评估只增加离线同预算配对门禁与 11 类覆盖清单；未授权真实付费模型调用，不声明质量提升。
- 2026-09-16：用户随后明确授权真实付费调用。正式配对冻结 8,650,752 tokens/arm；实际 World 模型均解析为 `deepseek-flash`。
- 2026-09-16：11/11 配对模型、归一化内容 hash 与 token ceiling 一致，全部请求 settled 且 unknown charge 为零；但两臂运行时新建 UUID/Confirmation 不同，未达到方案中“UUID/Confirmation 完全一致”的更强条件，故证据摘要明确保留此限制。
- 2026-09-16：baseline 3/11 done、candidate 0/11 done；独立 DeepSeek/Luna 盲评与 Terra 裁决后，严重错误为 8 vs 11，离线 gate 失败。未调参、未重跑正式成功样本。
- 2026-09-16：Writing 真实生成 4/4 请求 settled、12,013 tokens；公开 task wire 无私有信封。Confirmation 投影含 candidate draft；一次性数据显式绑定精确 working-draft 来源后，修改只使本项目产生 `source_changed`，邻居项目未失效。

## 验证证据

- 后端 World、Evidence、Story、Writing、Assistant、运行信封和 eval 回归：136 passed。
- 前端 `worldContinuation.test.js` + `GenerateView.test.js`：100 passed；ESLint 与生产构建通过（仅既有 classic-script 警告）。
- 变更 Python Ruff、24 项 Prompt 契约、`make docs-check BASE_REF=origin/main`、`git diff --check`：全部通过。
- World 正式真实调用：baseline 774,799 tokens/60 requests/3 done；candidate 1,118,598 tokens/93 requests/0 done；22 个运行均无 unknown charge。
- 匿名评测：Reviewer A=`deepseek-flash`，Reviewer B=`gpt-5.6-luna`，Adjudicator=`gpt-5.6-terra`；gate 结果位于 `backend/.test-artifacts/world-verified-review-live-20260916/world-design-gate.json`。
- PR #143/#145 smoke：`backend/.test-artifacts/world-verified-review-live-20260916/writing-pr143-pr145.json`；脱敏总览见同目录 `SUMMARY.md`。
- 证据导出后已删除 template/baseline/candidate 三个一次性数据库及 detached baseline worktree；受保护 Guimi 数据库和主工作区宣传录屏 WIP 未触碰。

## 交付结果

- 已交付：本地代码、测试、离线 eval 入口、作者界面、权威文档实现，以及 gitignored 脱敏真实调用证据。
- 未交付：质量 gate 通过；提交、推送、合并和部署。
- 交付边界：本地未提交；未推送、未合并、未部署。
- 正式知识与后续任务：无。

## 2026-09-17 审计修复（T-20260917-review-remediation Wave 5）

- 外部审计判定当前形态不可发布（RB-1/2/3）；根因修复在
  `codex/world-review-root-cause`（RB-1 矛盾决定卡、RB-2 审查冻结投影/输出权限语义）。
- 本分支 WIP 已整理为 5 个提交并 rebase 到该修复分支（关键合并结果经逐项验证）。
- 新增：失败路径公开脱敏停止回执 `world_design_review_failure`（阶段进度/attempt/信封用量/
  作者可见错误）；离线 gate 去除"同预算"表述，两臂真实 cap 与实际用量分别报告
  （requests_used/tokens_used/reasoning_effort）。
- 确定性回归：worktree world+evals 1139 passed；ruff、docs-check 通过。
- 下一步：等待 Wave 1–5 合并 main 授权；付费 11 对重跑需单独授权（gate 通过后再议）。
