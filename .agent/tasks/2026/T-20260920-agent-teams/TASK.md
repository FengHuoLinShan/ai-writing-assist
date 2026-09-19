---
id: T-20260920-agent-teams
title: Agent Teams 完整实施与分功能验收
status: completed
created: 2026-09-20T00:44:53+08:00
updated: 2026-09-20T04:35:00+08:00
---

# Agent Teams 完整实施

## 恢复快照

- 本地工程交付完成，验收详见 [ACCEPTANCE.md](ACCEPTANCE.md)。真实质量未准入，所有功能默认关闭。
- 工作区：/Users/tywww/.codex/worktrees/agent-teams/ai-writing-assist，codex/agent-teams；基线 main@9b7ba092a、origin/main@85d418b86。
- 2026-09-20 用户授权 Git 交付：本任务全部改动提交至 codex/agent-teams 并合并本地 main（合并门禁复验 docs-check 与影响门禁通过）；未推送、未部署。
- 2026-09-20 重新开启：用户要求核对并修复两项 P1 及所列 P2；仅本地修复、验证和文档，无发布/付费模型授权。
- 当前：审阅修复本地完成，定向后端/前端、专用 PG、迁移往返及 F1 浏览器均通过；详见 ACCEPTANCE.md 修复验收。
- 下一步：推送与远端 CI 待后续授权；修复轮未全量重跑 test-ci/覆盖率。
- 阻塞：无；真实质量与 F2–F8 浏览器覆盖仍为既有未验收边界，不宣称全功能准入。
- `forkRound` 旧桥调用当前不存在，现有 SceneRehearsalPanel 通过 run 事件携带分叉参数。
- 用户明确不使用开发子代理；允许 deepseek-flash。没有修改真实 Guimi 数据。

## 目标与验收

依据 /Users/tywww/Downloads/NovelCraft-Agent-Teams-完整实施计划-2026-09-20.md 完成阶段 0–8
必需工程实现、验证和文档。参考资料中的旧任务限制不构成当前授权。工程、质量和启用分别判定。

- [x] P0–P1：有限协作 ADR、版本化总预算/成员额度、DAG、来源投影、恢复和故障隔离。
- [x] P2：F1 三专项 → Writing 领域报告 → 汇总/知识复核；原位 UI 和有上限真实探索。
- [x] P3–P4：F2 情境/作者保留/定向重测；F3 多方案、diff、原批次确认与独立后续复核。
- [x] P5–P6：F4 独立意图/裁决/观察/持久回合/分叉；F5 原 attempt/held/正式节点与角色状态。
- [x] P7：F6 冻结逐章盲读，F7 本次联网研究，F8 原疑难组会诊与采用边界。
- [x] P8：独立默认关闭、迁移/保留历史回退、日志/用量、模块文档及本地门禁。
- 质量结果为不准入，并非待掩盖的绿色项；参见 [QUALITY.md](QUALITY.md)。可选异构顾问未纳入。

## 决策和计划差异

复用已有 Project gateway、PydanticAI、AIRunEnvelope、任务/确认/采用服务，不引入新服务。
工作板复用受限 JSON，未建立计划中的 Assistant v2 两表；当前 12 项/1 MiB 上限已覆盖固定蓝图。
Story/RP 新增三张回放/观察历史表。RP 多角色仅对已登录且有冻结作品来源的旅程提供。

## 关键发现与修复

- 模型错误翻页改为可重试输入错误，不能取消其他调查；JSON source_ref 在原工具边界重新构造。
- AnyIO 取消会破坏统一信封短事务的连接回收；在共享 keeper 事务入口处理，保留租约 fence。
- RP v3 必须由 Project 在签名之前冻结，禁止业务层追加字段破坏 profile_hash。
- 未建立讨论时刷新会覆盖本地草稿，已修复加载时不保存空初始态；保留项和重测范围随草稿恢复。
- 只读蓝图不能返回修改方案；导入会诊只能选择原组当前候选；World 独立报告复验所有关联来源。
- Alembic check 有旧 schema 漂移，已用基线 metadata 比对保留证据；未修改无关表。

## 验证与交付

make test-ci 通过（后端 5867、前端 2511、部署 270，覆盖率 86.02%），最后安全补强 6 项通过；
PostgreSQL 新功能 6 项通过；Playwright 原位/恢复/窄屏通过。全部具体范围和限制见 ACCEPTANCE.md。
DeepSeek 80 次 generate、已知输入 425430、已知输出 232474、2 次未知；健康探测另计，未估算金额。
样本受输出限额与失败影响，未完成盲评/留出，不开启默认功能。脱敏证据和最终本地文件指纹保存在 artifacts。
