---
id: T-20261002-spreadsheet-migration
title: 表格（xlsx/csv）迁移作者在途项目资产
status: draft
created: 2026-10-02T21:32:00+09:00
updated: 2026-10-02T21:32:00+09:00
---

# 表格迁移

## 恢复快照

- 实际完成：L0 契约冻结已提交（`7ed082b47`）：依赖 openpyxl/defusedxml、
  `imports/spreadsheet_migration/` 全部契约文件（constants/schemas/repository 实现、
  parsing/classify/synonyms/ai stub、ai_schemas、planning/service 占位）、
  `ImportMigrationSession` model + 迁移 `20261003_import_migration_sessions`、
  world/story 迁移契约与 facade 接线、公共面回归测试更新。Wave 1 七车道已派发
  （分支 `codex/spreadsheet-migration-l1..l7`，worktree `../ai-writing-assist-sm-*`）。
- 当前里程碑：Wave 1 并行开发中；批次 1（L1/L2/L3）运行中，随后批次 2（L4/L5）、批次 3（L6/L7a）。
- 下一步：收集车道交接报告并审查契约偏离 → 按序合并 → L8 集成验收。
- 阻塞：无。推送、真实模型验收和合入 main 需用户另行授权。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist-spreadsheet`，分支 `codex/spreadsheet-migration`。
  L0 门禁：make lint 通过、make schema-check 通过（PG 开发库已升到 head）、
  公共面测试 5 通过、迁移 SQLite 隔离 up/down/up 与 PG 全链 up/down/up 均通过
  （全链在 SQLite 因既有 JSONB 迁移不可行，属基线事实）。
- 最后核实：2026-10-02（L0 提交后）。

## 目标与验收

- **目标与交付物**：作者上传 `.xlsx`/`.csv`，系统识别人物卡、世界对象、关系、卷纲、主线支线、伏笔、
  细纲和总纲，作者在预览中调整后确认，落为已采用资产。资产带“表格迁移”来源，整次可撤销。
  大纲类表可选 AI 整理，结果只进预览。
- **完成条件**：计划 §4 L8 的全部门禁通过；ADR-0030 改为 Accepted；权威文档已同步。
  只对跑过真实文件验收的来源宣称支持。
- **非目标**：
  - 不支持 `.xls`、`.et`、`.ods` 和 Notion zip；
  - 不扩展正文导入白名单；
  - 不修复 planned Scene 与深度导入可能重复的问题（与 P20 现状一致）。

## 上下文与边界

- **关键路径与来源**：以计划文档 §2–§4 为准，其中包含冻结契约和车道文件归属。
- **用户已确认的决策（2026-10-02）**：
  - 范围：世界对象与人物卡、人物关系、大纲和细纲（LLM 转化）；
  - 格式：只做 xlsx 和 csv；
  - 映射：规则识别，加上可选的 AI 整理；
  - 落库：确认即采用；同名只补空字段，绝不覆盖；冲突不落库，只展示给作者。
- **硬约束**：
  - `novel_id` 与 owner 隔离；匿名 demo 不可用；
  - LLM 只能经项目快照获取；
  - 会话和回执不长期保存正文；
  - `@patch` 必须 `autospec=True`。
- **依赖**：新增 `openpyxl`、`defusedxml`。若 storyforge-v6 先合入 main，需要 rebase。
- **假设**：迁移完成率、撤销率等产品指标还没有真实数据，目前属于产品假设。

## 里程碑与进度

- [x] 需求确认与架构计划（计划文档）。
- [x] Wave 0：L0 契约冻结并提交（7ed082b47）。
- [ ] Wave 1：L1–L6 与 L7a 并行完成，各自交接报告已审查。
- [ ] Wave 2：L8 集成，跑通 SQLite 真实链路、PG 关键路径和浏览器 e2e。
- [ ] 真实文件验收，以及经用户授权的真实模型验收。
- [ ] L7b 文档全量同步，ADR-0030 改为 Accepted，全量门禁通过。

## 决策、发现与失败

- **2026-10-02**：world 落库改用新的窄 seam，不复用 adoption package。原因：单包上限 32 项、没有人物字段、
  `force_create=False`，且回滚只覆盖 focused 包。
- **2026-10-02**：未识别列写入 `hidden_truth` 作为作者备注。该字段只在作者视图进入上下文，读者和 RP 侧已剔除。
- **2026-10-02**：origin/main 上没有 `project/model_routing.py`，Alembic head 为 `20260929_world_object_image_candidates`。
  因此 AI 任务暂不接入成本分档。

## 验证证据

- 2026-10-02T21:35+09:00：计划文档和任务记录跑了 `make docs-check`，结果为 “Architecture documentation checks passed”；`git diff --check` 无输出。工作树未提交。

## 交付结果

- **已交付**：计划文档与本任务记录（本地 worktree，未提交）。
- **未交付**：全部实现。
- **交付边界**：仅本地，没有提交、远端、CI 或部署。
- **正式知识与后续任务**：实施完成后以 ADR-0030 为准。
