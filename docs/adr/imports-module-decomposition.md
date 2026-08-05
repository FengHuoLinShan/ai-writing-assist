# ADR — imports 模块子包拆分计划

- **状态**: Partially implemented
- **日期**: 2026-07-07
- **关联追踪**: H2

> 2026-07-29 复核：`entity_extraction/` 子包已经落地，并由原模块路径保留兼容 import；
> parsing、workflow 与 scene 仍主要使用扁平文件，因此 H2 只算部分完成。本文其余内容保留
> 原始拆分目标，不代表未落地目录已经成为当前契约。

## 背景

`imports` 模块承担文件解析、章节导入、Scene 自动提取、深度导入工作流、实体抽取和历史兼容 repair 入口。当前目录仍以扁平文件为主，维护成本随阶段和兼容路径增加。

旧 Scene prefetch/reinforcement pipeline 已删除。当前默认 Scene 自动提取路径是 `phase0_plan -> phase1a_scene_slicing -> phase1b_enrichment -> scene_commit`。

## 拟议布局

后续可按内部阶段拆分：

- `imports/parsing/`：上传文件解析、编码检测、章节切分和输入限制。
- `imports/workflow/`：任务编排、进度、恢复、放弃、workflow runtime 和 stage runner。
- `imports/entity_extraction/`：Phase 2 世界对象、别名、关系、记忆 delta 抽取。
- `imports/scene/`：Scene 切分、enrichment、commit、fusion/review 辅助，以及兼容 repair 入口。

## 当前兑现情况

- 已完成：`imports/entity_extraction/` 承载 Phase 2 世界对象、别名、关系和相关 checkpoint
  处理，旧模块路径只保留窄兼容 seam。
- 未完成：文件解析、workflow runtime 和 Scene 阶段尚未整体迁入独立子包；对应扁平模块
  仍是当前实现入口。
- 稳定边界未变化：外部仍只经 imports API、facade、contracts 或任务 handler 消费，
  不能直接依赖新子包内部实现。

## 边界

本文记录 H2 的完整目标；部分目录已兑现不表示整个拆分完成。

拆分不得改变：

- 上传白名单与 50MB 限制。
- HTTP response shape、任务类型、任务恢复/放弃语义。
- `PHASE1B_ENRICH_CONCURRENCY` 默认值 200。
- 不恢复已删除的 legacy Scene prefetch/reinforcement pipeline。
- 深度导入自动流水线写入 canonical 时的 provenance、可编辑/可回滚标记。

## 后续验证

- 针对默认 Scene 自动提取、Phase 2/3、legacy repair guard 分别保留测试。
- 跨模块调用仍走 imports API/facade/DI task handler，不让其他模块直接依赖新子包内部实现。
- 文档落地时同步 `backend/modules/imports/README.md` 和 `testing-guide.md`。
