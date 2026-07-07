# ADR — imports 模块子包拆分计划

- **状态**: Proposed
- **日期**: 2026-07-07
- **关联追踪**: H2

## 背景

`imports` 模块承担文件解析、章节导入、Scene 自动提取、深度导入工作流、实体抽取和历史 legacy repair 入口。当前目录仍以扁平文件为主，维护成本随阶段和兼容路径增加。

旧 Scene prefetch/reinforcement 已默认禁用，仅在显式 `DEEP_IMPORT_LEGACY_SCENE_PIPELINE_ENABLED=1` 的 legacy repair 或历史验收路径可运行。当前默认 Scene 自动提取路径是 `phase0_plan -> phase1a_scene_slicing -> phase1b_enrichment -> scene_commit`。

## 拟议布局

后续可按内部阶段拆分：

- `imports/parsing/`：上传文件解析、编码检测、章节切分和输入限制。
- `imports/workflow/`：任务编排、进度、恢复、放弃、workflow runtime 和 stage runner。
- `imports/entity_extraction/`：Phase 2 世界对象、别名、关系、记忆 delta 抽取。
- `imports/scene/`：Scene 切分、enrichment、commit、fusion/review 辅助，以及 legacy guard 附近的维修入口。

## 边界

本文是设计计划，不表示 H2 已完成。当前代码仍可保持扁平 services/文件布局，直到单独的代码重构 PR 落地。

拆分不得改变：

- 上传白名单与 50MB 限制。
- HTTP response shape、任务类型、任务恢复/放弃语义。
- `PHASE1B_ENRICH_CONCURRENCY` 默认值 200。
- legacy Scene prefetch/reinforcement 默认禁用的 guard 语义。
- 深度导入自动流水线写入 canonical 时的 provenance、可编辑/可回滚标记。

## 后续验证

- 针对默认 Scene 自动提取、Phase 2/3、legacy repair guard 分别保留测试。
- 跨模块调用仍走 imports API/facade/DI task handler，不让其他模块直接依赖新子包内部实现。
- 文档落地时同步 `backend/modules/imports/README.md` 和 `testing-guide.md`。
