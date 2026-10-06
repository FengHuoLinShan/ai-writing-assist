# AI 长篇小说结构化创作引擎文档索引

本文档是受版本控制项目文档的分类入口。运行时产物（`.test-logs/`、
`.opencode/loop-history/`、缓存、虚拟环境）不属于项目文档，不在此索引或归档。

## 根目录保留文件

根目录只保留仓库入口和编码 Agent 必须在工作开始前发现的指导文件；它们不是未归类文档。

| 文件 | 分类 | 用途 |
|---|---|---|
| `README.md` | 项目入口 | 产品简介、启动方式与主要模块入口。 |
| `AGENTS.md` | Agent 硬约束 | 协作协议、安全/数据边界与终止条件。 |
| `CLAUDE.md` | Claude Code 适配 | 通过 `@AGENTS.md` 导入共享规则，不维护第二套契约。 |
| `CONTEXT.md` | 领域上下文 | 稳定领域术语与跨模块语义。 |
| `DECISIONS.md` | 临时决策日志 | 保留根目录原用途；长期架构决策进入 `adr/`。 |
| `NOTES.md` | 实现笔记 | 保留根目录原用途；恢复旧工作时按需读取。 |
| `SECURITY.md` | 安全政策 | 支持范围与安全漏洞报告入口。 |
| `THIRD_PARTY_LICENSES.md` | 第三方许可 | 生产直接依赖的许可清单与权威来源说明。 |
| `development-guide.md` | 开发指南 | 本地开发、工程命令与工作流。 |
| `testing-guide.md` | 测试指南 | 测试层级、Review 分级与门禁。 |

## 当前设计与契约

1. [`product/user-personas.md`](product/user-personas.md) — 两类核心用户、当前双入口，以及“用户会喜欢吗 / 前端舒服吗”判断门禁
2. [`00_整体设计.md`](00_整体设计.md) — 项目定位、核心原则、三层架构、模块职责
3. [`01_数据库设计.md`](01_数据库设计.md) — 当前数据库表、关系、约束与 schema 权威来源说明
4. [`核心业务场景与预期行为.md`](核心业务场景与预期行为.md) — 用户可感知业务流程
5. [`architecture/documentation-maintenance.md`](architecture/documentation-maintenance.md) — 当前架构文档清单、影响矩阵、PR/CI 防遗漏流程

## 指导文件分工

- 根目录 `AGENTS.md` 记录所有编码 Agent 的共享硬约束、协作协议和终止条件
- 根目录及模块 `CLAUDE.md` 只为 Claude Code 导入同目录 `AGENTS.md`
- 项目结构、目录设计、分层架构写入 [`00_整体设计.md`](00_整体设计.md)
- 开发命令与工程规则写入根目录 `development-guide.md`
- 测试要求与 Review 分级写入根目录 `testing-guide.md`
- 模块专属硬约束写入最近的 `AGENTS.md`；模块 README 继续保存职责、接口和测试事实

## 复杂任务工作记忆

- [`.agent/PLANS.md`](../.agent/PLANS.md) — 按需读取的任务触发、恢复、更新、关闭协议及模板。
- [`.agent/TASKS.md`](../.agent/TASKS.md) — 开放任务导航；详细状态仅保存在对应 `TASK.md`。
- `.agent/tasks/` 保存可恢复执行记录，不替代正式文档、ADR、代码和测试；历史计划不批量迁移。

## 权威性与历史分类

- 当前架构和数据库设计以 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、活跃模块
  README、ORM `models.py` 与 Alembic migration 共同为准；发生冲突时，当前代码和迁移优先。
- [`archive/superpowers/README.md`](archive/superpowers/README.md) 说明历史交付计划、设计快照、报告和验收
  记录的分类。`archive/superpowers/plans/` 中的旧计划不是当前需求或架构契约，维护时只更新分类，
  不回写历史计划正文。
- `archive/audit/`、`archive/maintenance/document-update-log.md` 和已完成验收报告是时间点记录，不作为当前状态判断依据。
- [`architecture/README.md`](architecture/README.md) 分类架构图：当前模块图以
  `module-architecture.drawio` 为可编辑图源、HTML 为兼容预览；`diagrams/` 下的旧图仅作
  历史视觉参考。
- [`architecture/architecture-documents.toml`](architecture/architecture-documents.toml)
  是当前架构文档、模块/API 前缀和差异影响规则的机器清单；`make docs-check` 验证完整性，
  `make docs-check BASE_REF=origin/main` 再验证本轮改动的必查文档。

## 子模块文档

1. `modules/01_project.md` — 小说项目模块
2. `modules/02_world.md` — 世界对象模块
3. `modules/05_memory.md` — Story continuity 长期记忆兼容面
4. `modules/07_outline.md` — Story outline_state 结构化剧情兼容面
5. `modules/08_evidence.md` — canonical/working 索引、检索新鲜度、上下文编译、确认与追踪
6. `modules/11_writing.md` — 正文草稿承载模块
7. `modules/13_imports.md` — 小说导入模块
8. `modules/12_infrastructure.md` — 基础设施模块（LLM + PostgreSQL 任务队列）
9. `modules/14_frontend.md` — 前端控制台
10. `modules/15_map.md` — AI 地图册候选生成、作者采用、标注与私有图片存储（world 子系统）
11. `modules/17_account.md` — 公开浏览器账号、身份、账户模型连接、全局偏好、会话与延期删除
12. `modules/18_interaction.md` — RP 互动旅程、不可变分支、流式恢复、回顾与看海
13. `modules/19_story.md` — Scene 人物卡、可编辑剧本 revision、采用与 one-click 预览
14. `modules/20_assistant.md` — 项目助手的有界运行时、操作回执与恢复语义
15. `modules/21_collaboration.md` — 创作试验目标、授权、不可变试改与精确采用回执
16. `modules/22_evolution.md` — `evolution` V4 演化引擎 E01 契约层：来源引用、观察、身份解析、类型化操作与回执游标（建设中）
17. `modules/23_local_agent.md` — `local_agent` 作者 Mac 本机 CLI 的项目配对、逐任务权限与回执边界

`modules/` 只放当前模块的设计与稳定接口说明；已替代的模块文档位于
`archive/modules/`，代码分析参考位于 `references/`。

已移除的旧模块：`geo` / `character` / `timeline` / `review`。地点、人物、事件能力已并入 `world`，结构复查模块暂缓。

## 测试、诊断与 Agent 规则

- `testing/` — 测试技术覆盖主线与离线证据说明。
- `agents/` — Issue 约定、triage 标签与领域文档的 Agent 消费规则。
- `diagnostics/` — 本机性能诊断手册与带日期的时间点诊断记录，不作为 CI 门禁或当前性能事实。

## Prompt 设计

1. `prompts/Prompt体系设计.md` — Prompt 体系总览

## 架构决策

- [`adr/README.md`](adr/README.md) — 全部编号 ADR、主题 ADR、细化索引、当前状态及取代关系；
  新增或调整 ADR 状态只维护这一份完整索引，不再在此复制容易漏项的子集

## 长程计划

`docs/plans/` 是新实施计划的唯一入口；计划完成后移入 `docs/archive/` 作为历史记录，不在
`docs/plans/` 长期堆积已交付内容。

- [`plans/novelcraft-v4/`](plans/novelcraft-v4/) — NovelCraft V4 演化式小说整体引擎长期计划
  （G0–G8 里程碑、T01–T36 验收矩阵、48 画面 HiFi 与设计资产）。计划包为权威输入，
  实施进展与基线证据见 [`plans/novelcraft-v4/g0/G0-基线与保护.md`](plans/novelcraft-v4/g0/G0-基线与保护.md)；
  计划文档本身按交付原样保存，实施状态不回写计划正文。
- [`plans/2026-10-06-architecture-optimization.md`](plans/2026-10-06-architecture-optimization.md) —
  架构报告核验与架构优化计划（模块依赖方向棘轮、解环、按职责拆分、运行时与部署不变量），未实施

## 参考与历史资料

- `references/` — 当前实现可查阅但不构成契约的分析和历史设计依据；包括
  [`2026-09-01-rp-long-term-memory-research-and-decision-ledger.md`](references/2026-09-01-rp-long-term-memory-research-and-decision-ledger.md)（RP 长期记忆的跨平台调研、压缩与分支对象覆盖层持续决策台账）、
  [`world-object-worldbook-unification-research.md`](references/world-object-worldbook-unification-research.md)（世界对象、世界书与 Card 统一研究）、
  [`2026-08-27-frontend-world-task-workspace-research.md`](references/2026-08-27-frontend-world-task-workspace-research.md)（统一卡片后的世界资料库、作者任务与前端目录研究）、
  [`world-authority-canonical-fixtures-v1.json`](../backend/modules/world/tests/fixtures/world-authority-canonical-fixtures-v1.json)（World Authority v1 规范字节夹具）、
  [`map-prd-v1.1.md`](references/map-prd-v1.1.md)、
  [`2026-07-14-novalist-map-capability-analysis.md`](references/2026-07-14-novalist-map-capability-analysis.md)、
  [`2026-07-14-novalist-sillytavern-worldbook-design-analysis.md`](references/2026-07-14-novalist-sillytavern-worldbook-design-analysis.md)、
  [`2026-07-15-four-authoring-workbench-directions-design.md`](references/2026-07-15-four-authoring-workbench-directions-design.md)、
  [`2026-08-10-worldbook-system-continuous-improvement-plan.md`](references/2026-08-10-worldbook-system-continuous-improvement-plan.md)、
  [`deep-import-progress-backend-query-analysis.md`](references/deep-import-progress-backend-query-analysis.md)
  与 Scene 健康标记参考。
- `archive/audit/` — 代码、性能、安全和文档审计的时间点记录；新审计直接带日期新增到该处。
- [`acceptance/`](acceptance/) — 验收基线与历史验收记录；新的验收应新增带日期的记录。
- [`security/content-sanitization-policy.md`](security/content-sanitization-policy.md) — 内容清理政策草案（Draft，不替代已采纳的 ADR 与安全边界）。
- [`product/new-user-guide.md`](product/new-user-guide.md) — 新用户指南源文；[`product/NovelCraft-新用户指南.docx`](product/NovelCraft-新用户指南.docx) 为交付版，编辑时以 Markdown 源文为准重新生成。
- [`product/word-guide-source.md`](product/word-guide-source.md) — Word 指南的可编辑源文。
- [`references/典型用户路径_goal提示词.md`](references/典型用户路径_goal提示词.md) — Agent 验收与用户路径提示词参考。
- `archive/superpowers/` — 历史实施计划、设计快照、报告和验收记录；见
  [`archive/superpowers/README.md`](archive/superpowers/README.md)。
- `archive/` — 已完成、废弃或仅作追溯的文档；包含旧模块说明、维护记录、
  Agent 修复提示词及只读审查报告。详见 [`archive/README.md`](archive/README.md)。

## 代码邻近文档与运行记录

- 根目录 `deploy/README.md` 是 `zy` 的生产拓扑、决策门禁、发布、备份与恢复入口。
- `backend/modules/*/README.md`、模块级 `AGENTS.md` 与 `backend/infrastructure/*/README.md`
  是代码邻近的模块接口/实现说明，随相应代码维护。
- `backend/prompts/` 是运行时 Prompt 模板；其清单与调用契约由
  `prompts/Prompt体系设计.md` 维护。
- `frontend-console/README.md` 与 `frontend-console/e2e/scenario-coverage.md` 是前端入口和
  测试覆盖文档；`frontend-console/docs/` 是前端历史分析和实施记录。
- `docs/frontend/uiux/` 是前端「Editorial Archive 提纯」二次设计的权威规范集：`design-standard.md`
  为全站 UI/UX 设计标准，`pages/` 为分页执行规范，执行与认领规则见其 `README.md`。
- `workflows/` 是已落地工作流的实现说明；`tools/*/README.md` 是各开发工具的局部说明。
- `backend/evals/` 与 `.test-logs/` 保存可复现实验/测试产物，不是当前设计契约；其中受版本
  控制的报告仍保留在产生它们的评测目录中。

## 验收基线

1. [`acceptance/2026-07-07-single-character-pov-prose-acceptance-baseline.md`](acceptance/2026-07-07-single-character-pov-prose-acceptance-baseline.md) — 单角色 POV 正文候选生成能力（建议 1-4）最终验收对照基线

## 推荐阅读顺序

如果要理解全局：
1. `product/user-personas.md`
2. `00_整体设计.md`
3. `01_数据库设计.md`
4. `AGENTS.md`
5. `development-guide.md` 与 `testing-guide.md`

如果要开发某个模块：
1. 先读根目录及目标目录最近的 `AGENTS.md`
2. 用户可见功能加读 `product/user-personas.md`
3. 再读 `development-guide.md` 和 `testing-guide.md`
4. 继续读对应 `modules/<模块>.md` 与模块 README
5. 最后读 `01_数据库设计.md` 中该模块相关表

## 代码审计

历史代码、性能、安全与文档审计统一归档在 [`archive/audit/`](archive/audit/)，按日期命名；
新审计直接带日期新增到该处。它们是时间点记录，不作为当前状态判断依据。

## 当前状态

当前模块清单、组件归属、API 前缀与运行事实以
[`architecture/architecture-documents.toml`](architecture/architecture-documents.toml) 机器清单、
根目录 [`CONTEXT.md`](../CONTEXT.md) 领域词汇与 [`00_整体设计.md`](00_整体设计.md) 为单一
事实源；本索引不再复制模块数量与模块清单等易漂移事实。
