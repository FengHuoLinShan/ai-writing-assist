---
id: T-20261009-world-evolution-phase4-plan
title: 世界演化第四阶段计划
status: completed
created: 2026-10-09T23:10:00+09:00
updated: 2026-10-09T23:50:00+09:00
---

# 世界演化第四阶段计划

## 恢复快照

- 实际完成：[第四阶段计划](../../../../docs/plans/2026-10-09-world-evolution-phase4.md)
  已保存，并加入 docs/README.md 的长程计划导航。
- 当前里程碑：仅完成规划；第四阶段实现、付费运行、真实数据写入均未启动。
- 下一步：PR #206 合入 main 后，从最新 origin/main 新建实施分支与实施任务记录，
  建诡秘前 60 章隔离库副本，按 P4-A/P4-B 并行开工。预算、Guimi 副本、作者试用执行者
  均已由用户定好，不再重复确认。
- 阻塞：无。实施的前提是 PR #206 合入，由该 PR 的集成工作负责。
- 工作区：/Users/tywww/.codex/worktrees/world-evolution-phase4/ai-writing-assist，
  分支 codex/world-evolution-phase4-plan，基于 2f32edc40（PR #206 当时的头）；
  计划与本记录未提交。world-foundation-plan 工作树另有会话在推进 PR #206
  （核查时已到 181d0d4d6），本任务没有触碰。
- 最后核实：2026-10-09T23:50:00+09:00。

## 目标与验收

- 目标与交付物：用户要求“做世界演化下一阶段的计划”。交付一份可执行的第四阶段计划。
- 完成条件：用户选定的方向准确落入计划；写清开始条件、基线缺口、工作包顺序、
  各包验收、边界、实施中的用户决策点和后续候选；文档门禁通过。
- 非目标：不实现功能，不调用模型，不写真实数据，不提交、推送、合并或部署。

## 上下文与边界

- 系列：第一阶段 docs/plans/2026-10-06-world-foundation-phase1.md（R7 未闭合，
  见 T-20261006-world-foundation-phase1-impl）；第二阶段 2026-10-07-world-foundation-phase2.md；
  第三阶段 2026-10-08-world-evolution-phase3.md（按用户验收调整完成，v29 的 S3/S6/S7
  质量 FAIL 与封存 9 场保留，见 T-20261008-world-evolution-phase3）。
- 作者全景方案 T-20261007-author-evolution-panorama 的 P0–P2 已由第三阶段交付；
  它的 P3（扩类、排演纯记录终点）、P4（受控推进、精细重算、规模）是本计划的来源之一。
- 与 T-20261004-world-edit-history §4 的势力与世界版本路线图是两条路线；本计划只在
  后续候选里标出“故事内时间与有效期”是两者的汇合点，没有合并路线图。
- 2026-09-27 Guimi 前 60 章代理验收：World 66 场中 4 通过、43 容量延后、471 待裁定
  （docs/plans/novelcraft-v4/guimi-evolution-agent-acceptance-20260924.md）。

## 里程碑与进度

- [x] 恢复前三阶段计划、完成审计、质量报告与 PR #206 状态。
- [x] 只读核对十项候选能力的代码现状（Explore 子代理，主会话抽查关键行号）。
- [x] 用户选择方向。
- [x] 写入计划与文档导航，运行文档门禁。

## 决策、发现与失败

- 2026-10-09 用户在四个候选中选择“1+4”：长篇跑通与可信，加扩类与精细依赖。
  受控短期推进、故事内时间与有效期列为后续候选。
- PR #206 当时为 OPEN/BEHIND。Backend quality 失败于依赖审计（pydantic-ai-slim 2.50.0
  两项公告，修复于 2.53.0；langchain-community 已归档），生产镜像契约与浏览器分片 1
  也失败。计划把合入列为开始条件，不计入第四阶段工作。
- 代码核对要点：world.py:14 与 :270-289 的 45,000 字符硬延后；discovery.py 每批带完整
  scene_text 与 theme_index，超过 50,000 字符整批 unsupported，召回按字面名；
  重做按场景后缀，消费登记只有 Story 投影一处、粒度为整章；台账三类且类别多处硬编码；
  rehearsals.py:244 强制生成剧本预览。详见计划第 2 节。
- 2026-10-09 用户为第四阶段实施明确三项：真实模型调用不设费用上限；允许用诡秘前 60 章
  测试（计划落为专用隔离库副本，原 Guimi 库不写）；作者试用交给 gpt-6.1-sol，以代理作者
  身份经真实浏览器执行，独立于实现与评阅，结果不改变 human_validated=false。
  这些授权覆盖实施阶段，不授权本规划任务调用模型或写数据。
- 扩类的首批四类（语言习惯、外在特征、重要物件、规则后果）是计划建议，实施前用长篇
  观察分布确认。

## 验证证据

- 2026-10-09 计划保存前基线 make docs-check 通过（12 模块、151 ORM 表、56 handler、
  16 路由、39 ADR）。
- 计划保存后：make docs-check BASE_REF=origin/main 失败，原因是本分支继承了 PR #206
  相对 main 的全部代码差异，要求复核 CLAUDE.md、backend/infrastructure/tasks/README.md、
  docs/architecture/documentation-maintenance.md。这与 PR #206 自身状态相同，不是本次
  文档改动引起；本任务未加 no-change-reason 声明。以真实分叉点
  `--base-ref 2f32edc40` 运行：无架构敏感源码变化，通过。
- git diff --check（含新文件）通过；三份文档的相对链接全部可解析。
- 未运行业务测试、模型或浏览器；本任务只改文档。

## 交付结果

- 已交付：docs/plans/2026-10-09-world-evolution-phase4.md、docs/README.md 导航（同时补上
  缺失的第三阶段入口）和本记录。
- 未交付：第四阶段任何实现与验证。
- 交付边界：仅在本地工作树，未提交、推送、合并或部署。
- 正式知识与后续任务：实施时新建实施任务记录，引用本计划。
