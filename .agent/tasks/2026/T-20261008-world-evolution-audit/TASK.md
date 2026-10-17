---
id: T-20261008-world-evolution-audit
title: 世界演化实现现状审查
status: completed
created: 2026-10-08T20:10:00+09:00
updated: 2026-10-12T23:36:26+08:00
---

# 世界演化实现现状审查

## 当前恢复快照（2026-10-12 整理核实）

- 本审查及 `artifacts/runtime_probes.py` 是独有历史资料；2026-10-13用户授权整理本工作树并提交，纳入历史归档，不删除或作为当前契约测试。
- 其 f35c2bb0f / 312c68a64 基线上的发现是 2026-10-08 证据；PR #206 与 PR #220 已合入。旧 OPEN/BLOCKED、P0 未启动、无 World 分组审查与无选择性重做不再是当前状态。
- 原反例探针保留原样，仅适用于旧基线；本次未重跑或将其改成当前断言。当前能力与缺口见 P4 TASK、完整性报告及 main 代码，不由旧行号直接推断。
- 默认 deep_import 替代、真实模型质量/费用与缺失版本依赖仍未闭合；审查 completed 不等于产品完整验收。
- 下一步：历史审查已交付，本地资料继续保留；后续验证应绑定当前方法/来源版本，不重放旧授权或启动真实模型。

- 唯一后续主笔记：主工作树本路径 `/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261008-world-evolution-audit/TASK.md`；旧工作树副本只读。
- 最后核实：2026-10-12T23:36:26+08:00。以下各节保留原验收、失败和授权的历史证据，不代表当前交付状态。

## 历史记录

## 目标与验收

用户要求“审查世界演化实现情况”。交付实际能力、Standards/Spec 两轴发现和验证边界；不实施业务修复、提交、合并、部署或付费验收。

## 恢复快照

- 主干基线：f35c2bb0f119b7ebf557a9a3bbcf119f23dd91a8；既有任务笔记与 .workbuddy WIP 保留。
- 在途分支：world-foundation-plan worktree，HEAD 312c68a6449fec457a85f3213a7c5c8df8090c71；有后续未提交整改，不能用固定头 PR 的 CI 代表当前补丁。
- 当前进展：Standards / Spec 独立审查完成；主代理复跑两项纯内存反例。主干与在途未提交整改分别检查，见下。
- 下一步：若用户授权修复，先处理 World 采用的传递来源重验与 append 结构阶段；保留当前分支 WIP，修复后补实际公开入口回归。
- 阻塞：无。

## 上下文、发现与决定

- 昨日作者全景/细节台账/持续发现计划 P0 尚未开始；它与世界基础 P2-A/B/C 不是同一分期。
- 主干已有来源绑定、逐场景理解、独立复核、冻结恢复、保守失效和历史投影。
- PR #206 实时 head 为上述分支 HEAD，OPEN/BLOCKED；浏览器分片 1 与聚合失败，creative-rebase 三项失败；该结论仅对应远端固定头。
- 同一分支最新 TASK/REMEDIATION 声明旧 S1/S2/F1–F9 已本地整改；旧 REVIEW 与 handoff 的缺口不可直接当作当前缺陷。

## 验证证据

- 主干：backend 的 modules/evolution/tests、story/continuity/tests、simulation/observations/rehearsals 与 Scene Lens 定向 pytest：354 passed、1 deselected。
- 主干：ReadingFlow、StorySceneWorkspace、mapEvolution 三个 Vitest 文件：34 passed。
- 所有检查使用合成数据与离线测试；未调用模型，未触碰真实 Guimi 库。
- 分支当前未提交整改：p2_review_regressions、p2c_recompute_recovery、consumption_registry、p2c_revision_adoption 四个后端文件 82 passed；RecomputePanel、invalidationAutosave、invalidationModel 三个前端文件 52 passed。
- 主代理复跑 [runtime_probes.py](artifacts/runtime_probes.py)：旧 drained run 的 World 候选门正常返回，只读取第 2 章来源；结构游标 0、已提交场景 1、预算 100 仍直接 reading_complete=True。复跑：在 backend 执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python ../.agent/tasks/2026/T-20261008-world-evolution-audit/artifacts/runtime_probes.py`。这两项是替换 I/O seam 的纯内存行为证据，不是 PG/API 完整复现。
- 主干 make docs-check BASE_REF=origin/main、git diff --check 通过。

## Standards：两项运行缺陷

1. **P1：World 采用未重验前序来源。** reading.py:172–175 仅验证本 Scene；store.invalidate_sources:142–218 仅标 active run。旧 run 在 scoped_recompute 排空后，前序来源变化但本场未变、未产生替代回执时，其后场候选可继续采用。真实公开路径：world/api/entities.py promote_entity → entity_service.require_fresh_understanding_source → common.py:180 的 DI gate。应在共享采用门重验实际传递前缀；不能用只读理解路径已有检查代替采用门。
2. **P2：append 跳过新增结构整理。** workflow.py:552–554 原样保留 structure.complete=True，structure.py:22–23 直接返回完成。旧结构批次完成后追加 Scene，会跳过新增剧情线/人物弧/伏笔候选；应保留旧批次与游标，重新开放新增范围。

分支 HEAD 和未提交整改均未改 reading.py/workflow.py/structure.py，这两项也影响在途版本。

## Spec：四项重要未完成范围

1. E07.e/E08：旧 deep_import 仍是默认入口，adapter 未接生产入口，未完成等价迁移与退役。
2. World 审查容量：world.py:249–267 对特定模型超 45,000 字符直接 capacity_deferred，没有有来源分组审查。仓库 2026-09-27 Guimi 记录有真实 60 章/66 Scene/2754 观察，但 World 仅 4 场通过、43 场容量延后、471 项待裁定；这些是历史记录，未重查真实库。
3. 长程理解：前序主要注入最近 3 场、每场 20 条观察，并披露覆盖；定向重算仍是保守后缀，不是对象/命题精细依赖闭包，不能证明长程习惯/伏笔持续召回。
4. 作者全景/细节台账/持续发现：昨日 P0 六项仍没有实际产物；稳定主题修订、发生实例聚合、发现变化包与逐场学习未接线。现有排演仍生成 script_preview，不是纯记录终点。

## 在途基础分支边界

P2-A/B/C 的字段来源、知识值、读者揭示边界、实际消费登记与持久重算恢复已有实现，并有今天未提交修复。旧 REVIEW 的 S1/S2/F1–F9 不直接复报为当前缺陷；本轮只定向复跑补丁回归，未全面重新审查整个分支。其 world_valid_time、belief_fact_diff、world_canon_revision、map_atlas 仍显式 unsupported，父任务 R7 未闭合。PR #206 远端固定头 OPEN/BLOCKED，浏览器 creative-rebase 三项失败；远端 CI 不覆盖本地未提交修复。

## 交付结果

审查已交付：Standards 2 项（最高 P1，来源有效性），Spec 4 项未完成范围（主要是产品覆盖与质量）。业务代码零改动，只新增此任务记录和合成反例。不提交、推送、合并或部署；本次未运行完整浏览器、真实 PostgreSQL、真实模型或作者验收。
