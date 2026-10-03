# L7a 交接报告（ADR 与规则文档）

车道：L7a　分支：`codex/spreadsheet-migration-l7`　提交：见分支 log

> 执行说明：车道代理因模型配额中断未开工；本车道由集成者在主会话完成。

## 已完成

- `docs/adr/0030-spreadsheet-migration.md`：状态 Proposed（L8 验收后改 Accepted）。
  覆盖：独立入口与正文白名单不变、有界 OOXML 处理、确认即采用（owner 授权人）、
  窄 facade、AI 仅预览（ADR-0025 治理）、会话表与 CAS、回滚语义与限制、
  被拒方案（adoption package 复用/只落 candidate/AI 唯一路径/.xls/.et/.ods/
  Notion zip/扩展 /imports/upload）。
- `docs/adr/README.md`：索引加 ADR-0030 行。
- 根 `AGENTS.md`：数据与安全加一行边界（仅 `/api/imports/migrations`、仅
  `.xlsx/.csv`、窄 facade、同名补空、冲突不落地、AI 仅预览）。
- `backend/modules/world/AGENTS.md`：受限例外——表格迁移只经
  `plan/apply/rollback_author_migration_world` 窄 seam，确认即采用语义不得绕过。
- `backend/modules/imports/AGENTS.md`：表格会话保留规则（草稿期暂存有界单元格、
  采用/删除清空 rows、回执不存正文、revision CAS）。
- `docs/01_数据库设计.md`：`import_migration_sessions` 入 imports 表清单（提前于
  L7b，因 docs-check 对 L0 model 的表清单门禁在 Wave 1 即会触发）。

## 改动文件

全部在本车道独占清单内（`docs/**`、根/模块 AGENTS）。

## 契约偏离

无。

## 测试

- `make docs-check` → 通过（含新表清单门禁）。

## 文档要点

ADR-0030 的「后果」节列出三个已知产品限制（批量 reannotation 性能、planned Scene
与深度导入可能重复、作者自定义类型不对齐），L7b 需带入用户文档的预期管理。

## 风险与待决

- L5 合入后任务处理器计数变化可能触发 docs-check 的清单核对，L8 合并时统一处理。
