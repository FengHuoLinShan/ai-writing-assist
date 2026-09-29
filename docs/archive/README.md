# 文档归档

> 已完成/过时的项目文档，保留以供历史参考。

## 归档清单

| 文件 | 归档原因 | 原位置 |
|------|----------|--------|
| `.trae/` | Trae AI 工具的旧开发规格与任务，已完成 | 根目录 |
| `development-plan.md` | 自身标注"历史开发计划"；最新设计以 `docs/00_整体设计.md` 为准 | 根目录 |
| `02_v3重构实施计划.md` | v3 因果时空网重构已实施完毕 | `docs/` |
| `项目进度.md` | 所有里程碑已完成，不再追踪进度 | `docs/` |
| `前端测试框架计划.md` | 前端当前无测试框架，计划未执行 | `docs/` |
| `前端到后端可测试流程清单.md` | 逐个流程的测试清单，已过时 | `docs/` |
| `修复计划_E2E测试发现的问题.md` | E2E 测试发现的 DB/API 问题已修复 | `docs/` |
| `fix-plan-p0.md` | P0 阻塞项修复已完成 | 根目录 |
| `地图设计参考代码.md` | geo 模块已移除 | `docs/` |
| `地图需求文档.md` | geo 模块已移除 | `docs/` |
| `character-module-removed.md` | character 旧文档入口已移除，人物能力并入 world | `docs/modules/character/README.md` |
| `geo-module-removed.md` | geo 旧文档入口已移除，地点/地图能力归 world/map 文档维护 | `docs/modules/geo/README.md` |
| `review-module-removed.md` | review 旧文档入口已移除，结构复查模块暂缓 | `docs/modules/review/README.md` |
| `timeline-module-removed.md` | timeline 旧文档入口已移除，事件/时间线语义并入 world/context | `docs/modules/timeline/README.md` |
| `review_findings.json` | 代码审查临时输出 | 根目录 |
| `agent-prompts/chaos-test-fixes-prompt.md` | 2026-06-24 混沌测试修复清单；问题已进入后续修复轮次 | 根目录 |
| `agent-prompts/review-fixes-prompt.md` | 特定提交范围的历史 Review 修复清单 | 根目录 |
| `reports/frontend-ui-ux-review-report.md` | 只读 UI/UX 审查产物；不是当前前端设计契约 | 根目录 |
| `modules/04_settings.md` | 已被 `docs/modules/16_settings.md` 取代的 settings 模块说明 | `docs/modules/` |
| `maintenance/document-update-log.md` | 已完成的文档同步记录，不反映当前状态 | `docs/` |
| `test-plans/TDD_TEST_PLAN.md` | 已完成的测试重构计划；当前测试契约以 `testing-guide.md` 和活跃测试为准 | `backend/tests/` |
| `frontend-refactor-interface.md` | 写作台重构临时接口设计契约（自述重构完成后可归档）；此前已移入归档但漏登，此处补登 | `docs/` |
| `NOTES.md` | context_snapshots 设计期实现笔记；快照已实施且所有权归 evidence 模块 | 根目录 |
| `DECISIONS.md` | 轻量决策日志，抽查决策均已落地；长期决策以 `docs/adr/` 为准 | 根目录 |
| `AI开发规则.md` | 历史设计说明，Agent 运行时规则已被根目录 `AGENTS.md` 取代 | `docs/` |
| `skills-structure-docs-update.md` | 指向仓库外 `~/.claude/skills` 私有 skill 的孤儿文档；当前文档维护以 `docs/architecture/documentation-maintenance.md` 与 `make docs-check` 为准 | `docs/skills/structure-docs-update.md` |
| `world-library-completion-plan.md` | R0–R4 已实施并完成验收的世界书库完结计划（2026-09-10） | `docs/product/` |
| `superpowers/` | superpowers 历史工作记录（plans/specs/reports）整体归档；其中 `acceptance/` 四篇已并入 `docs/acceptance/` | `docs/superpowers/` |
| `audit/` | 2026-07~08 时间点审计整体归档；新的时间点审计直接带日期新增到本目录 | `docs/audit/` |

新的时间点审计不再进入 `docs/audit/`，直接带日期新增到 `archive/audit/`。

未迁移项：`docs/architecture/old-scene-pipeline.md` 当前无现存副本；旧 Scene prefetch/reinforcement 已由 legacy guard 和 imports 模块废弃说明替代，无需创建归档副本。
