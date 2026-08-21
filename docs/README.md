# AI 长篇小说结构化创作引擎文档索引

本文档是受版本控制项目文档的分类入口。运行时产物（`.test-logs/`、
`.opencode/loop-history/`、缓存、虚拟环境）不属于项目文档，不在此索引或归档。

## 根目录保留文件

根目录只保留仓库入口和编码 Agent 必须在工作开始前发现的指导文件；它们不是未归类文档。

| 文件 | 分类 | 用途 |
|---|---|---|
| `README.md` | 项目入口 | 产品简介、启动方式与主要模块入口。 |
| `AGENTS.md` | Agent 硬约束 | 协作协议、安全/数据边界与终止条件。 |
| `CLAUDE.md` | Agent 开发导航 | 架构导航、开发入口、命名与测试约定。 |
| `CONTEXT.md` | 领域上下文 | 稳定领域术语与跨模块语义。 |
| `DECISIONS.md` | 临时决策日志 | 设计演进中的轻量决策；长期架构决策进入 `adr/`。 |
| `NOTES.md` | 实现笔记 | 仍在维护的实现边界和后续同步事项。 |
| `development-guide.md` | 开发指南 | 本地开发、工程命令与工作流。 |
| `testing-guide.md` | 测试指南 | 测试层级、Review 分级与门禁。 |

## 当前设计与契约

1. [`product/user-personas.md`](product/user-personas.md) — 两类核心用户、当前双入口，以及“用户会喜欢吗 / 前端舒服吗”判断门禁
2. [`00_整体设计.md`](00_整体设计.md) — 项目定位、核心原则、三层架构、模块职责
3. [`01_数据库设计.md`](01_数据库设计.md) — 当前数据库表、关系、约束与 schema 权威来源说明
4. [`AI开发规则.md`](AI开发规则.md) — 历史设计说明；Agent 运行时以根目录 `AGENTS.md` 为准
5. [`核心业务场景与预期行为.md`](核心业务场景与预期行为.md) — 用户可感知业务流程
6. [`architecture/documentation-maintenance.md`](architecture/documentation-maintenance.md) — 当前架构文档清单、影响矩阵、PR/CI 防遗漏流程

## 指导文件分工

- 根目录 `AGENTS.md` 记录所有编码 Agent 的硬约束、协作协议和终止条件
- 根目录 `CLAUDE.md` 记录编码 Agent 的开发入口、架构导航和命名约定
- 项目结构、目录设计、分层架构写入 [`00_整体设计.md`](00_整体设计.md)
- 开发命令与工程规则写入根目录 `development-guide.md`
- 测试要求与 Review 分级写入根目录 `testing-guide.md`
- 模块专属约束写入模块 README 或模块级 `CLAUDE.md`

## 权威性与历史分类

- 当前架构和数据库设计以 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、活跃模块
  README、ORM `models.py` 与 Alembic migration 共同为准；发生冲突时，当前代码和迁移优先。
- [`superpowers/README.md`](superpowers/README.md) 说明历史交付计划、设计快照、报告和验收
  记录的分类。`superpowers/plans/` 中的旧计划不是当前需求或架构契约，维护时只更新分类，
  不回写历史计划正文。
- `audit/`、`archive/maintenance/document-update-log.md` 和已完成验收报告是时间点记录，不作为当前状态判断依据。
- [`architecture/README.md`](architecture/README.md) 分类架构图：当前模块图以
  `module-architecture.drawio` 为可编辑图源、HTML 为兼容预览；`diagrams/` 下的旧图仅作
  历史视觉参考。
- [`architecture/architecture-documents.toml`](architecture/architecture-documents.toml)
  是当前架构文档、模块/API 前缀和差异影响规则的机器清单；`make docs-check` 验证完整性，
  `make docs-check BASE_REF=origin/main` 再验证本轮改动的必查文档。

## 子模块文档

1. `modules/01_project.md` — 小说项目模块
2. `modules/02_world.md` — 世界对象模块
3. `modules/05_memory.md` — 长期记忆模块
4. `modules/07_outline.md` — 结构化剧情模块
5. `modules/08_rag.md` — canonical/working 派生索引、候选召回与可选证据重排序
6. `modules/09_context.md` — 上下文编译模块
7. `modules/11_writing.md` — 正文草稿承载模块
8. `modules/13_imports.md` — 小说导入模块
9. `modules/12_infrastructure.md` — 基础设施模块（LLM + PostgreSQL 任务队列）
10. `modules/14_frontend.md` — 前端控制台
11. `modules/15_map.md` — 动态地图子系统（world 模块子系统）
12. `modules/17_account.md` — 公开浏览器账号、身份、账户模型连接、全局偏好、会话与延期删除
13. `modules/18_interaction.md` — RP 互动旅程、不可变分支、流式恢复、回顾与看海
14. `modules/19_story.md` — Scene 人物卡、可编辑剧本 revision、采用与 one-click 预览

`modules/` 只放当前模块的设计与稳定接口说明；已替代的模块文档位于
`archive/modules/`，代码分析参考位于 `references/`。

已移除的旧模块：`geo` / `character` / `timeline` / `review`。地点、人物、事件能力已并入 `world`，结构复查模块暂缓。

## Prompt 设计

1. `prompts/Prompt体系设计.md` — Prompt 体系总览

## 架构决策

- [`adr/README.md`](adr/README.md) — 全部编号 ADR、主题 ADR、细化索引、当前状态及取代关系；
  新增或调整 ADR 状态只维护这一份完整索引，不再在此复制容易漏项的子集

## 参考与历史资料

- `references/` — 当前实现可查阅但不构成契约的分析和历史设计依据；包括
  [`map-prd-v1.1.md`](references/map-prd-v1.1.md)、
  [`2026-07-14-novalist-map-capability-analysis.md`](references/2026-07-14-novalist-map-capability-analysis.md)、
  [`2026-07-14-novalist-sillytavern-worldbook-design-analysis.md`](references/2026-07-14-novalist-sillytavern-worldbook-design-analysis.md)、
  [`2026-07-15-four-authoring-workbench-directions-design.md`](references/2026-07-15-four-authoring-workbench-directions-design.md)、
  [`2026-08-10-worldbook-system-continuous-improvement-plan.md`](references/2026-08-10-worldbook-system-continuous-improvement-plan.md)、
  [`deep-import-progress-backend-query-analysis.md`](references/deep-import-progress-backend-query-analysis.md)
  与 Scene 健康标记参考。
- `audit/` — 代码、性能、安全和文档审计的时间点记录。
- `acceptance/` — 验收基线、已完成验收报告和回归样本。
- `superpowers/` — 历史实施计划、设计快照、报告和验收记录；见
  [`superpowers/README.md`](superpowers/README.md)。
- `archive/` — 已完成、废弃或仅作追溯的文档；包含旧模块说明、维护记录、
  Agent 修复提示词及只读审查报告。详见 [`archive/README.md`](archive/README.md)。

## 代码邻近文档与运行记录

- 根目录 `deploy/README.md` 是 `zy` 的生产拓扑、决策门禁、发布、备份与恢复入口。
- `backend/modules/*/README.md`、模块级 `CLAUDE.md` 与 `backend/infrastructure/*/README.md`
  是代码邻近的模块接口/实现说明，随相应代码维护。
- `backend/prompts/` 是运行时 Prompt 模板；其清单与调用契约由
  `prompts/Prompt体系设计.md` 维护。
- `frontend-console/README.md` 与 `frontend-console/e2e/scenario-coverage.md` 是前端入口和
  测试覆盖文档；`frontend-console/docs/` 是前端历史分析和实施记录。
- `frontend/uiux/` 是前端「Editorial Archive 提纯」二次设计的权威规范集：`design-standard.md`
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
5. `CLAUDE.md`

如果要开发某个模块：
1. 先读根目录 `CLAUDE.md` 或 `AGENTS.md`
2. 用户可见功能加读 `product/user-personas.md`
3. 再读 `development-guide.md` 和 `testing-guide.md`
4. 继续读对应 `modules/<模块>.md` 与模块 README
5. 最后读 `01_数据库设计.md` 中该模块相关表

## 代码审计

1. [`audit/2026-07-07-全量代码库审计报告.md`](audit/2026-07-07-全量代码库审计报告.md) — 全量三维度审计（性能、安全、架构），88 条优化项
2. [`audit/2026-07-07-文档审计报告.md`](audit/2026-07-07-文档审计报告.md) — 77 个文档分类审计，含归档/更新/新建计划
3. [`audit/2026-07-07-可优化清单.md`](audit/2026-07-07-可优化清单.md) — 可追踪的逐项优化 checklist
4. [`audit/2026-07-11-模块能力与跨模块需求分析.md`](audit/2026-07-11-模块能力与跨模块需求分析.md) — 9 个活跃模块的当前能力、跨模块需求、RAG 精度结论与系统级优先级
5. [`superpowers/plans/2026-07-11-p0-capability-closure-plan.md`](superpowers/plans/2026-07-11-p0-capability-closure-plan.md) — P0.1/P0.2/P0.3 详细实现计划、评测数据生产线、验收标准与首轮实测结果
6. [`audit/2026-07-12-P0能力闭环完成审计.md`](audit/2026-07-12-P0能力闭环完成审计.md) — P0 工程/评测基础设施闭环证据、Pilot v1.1 四 suite 结果、历史 timing 限制与未达质量项
7. [`superpowers/plans/2026-07-12-p1-observability-query-planning-stale-closure.md`](superpowers/plans/2026-07-12-p1-observability-query-planning-stale-closure.md) — P1.1 Scene/证据覆盖遥测、P1.2 context 确定性查询计划、P1.3 任务 stale 闭环的详细实现计划与验收标准
8. [`audit/2026-07-12-P1运行盲区收敛完成审计.md`](audit/2026-07-12-P1运行盲区收敛完成审计.md) — P1 工程闭环、context-planner 正式对比结果、放宽验收与仍未达的严格质量目标
9. [`superpowers/plans/2026-07-12-p2-compatibility-surface-doc-drift.md`](superpowers/plans/2026-07-12-p2-compatibility-surface-doc-drift.md) — P2 文档同步、world contract 解耦、facade 公共面冻结和 legacy 删除计划
10. [`audit/2026-07-12-P2兼容面与文档漂移收敛完成审计.md`](audit/2026-07-12-P2兼容面与文档漂移收敛完成审计.md) — P2 删除清单、稳定接口影响与仓库级验证结果
11. [`audit/2026-07-14-全量代码扫描修复收敛报告.md`](audit/2026-07-14-全量代码扫描修复收敛报告.md) — 全量 bug / 低效路径分批修复、独立复核、全仓库验证，以及 8 项未关闭 P1 结构债务、1 项已关闭重复路径与 1 项 P2 性能优化
12. [`audit/2026-07-20-全项目持续风险审查.md`](audit/2026-07-20-全项目持续风险审查.md) — 当前 checkout 的全项目持续审查台账：完成条件、逐模块覆盖、直接修复、决策项与独立验证证据
13. [`audit/2026-07-25-真实用户场景持续发散排查.md`](audit/2026-07-25-真实用户场景持续发散排查.md) — 持续进行中的真实用户操作台账：前端直观性、状态恢复、后端异常、真实 LLM 与逐轮未覆盖组合
14. [`references/2026-08-13-worldbook-system-enhancement-plan.md`](references/2026-08-13-worldbook-system-enhancement-plan.md) — 基于详细世界书样本与当前代码能力核对形成的增量需求、差距矩阵和分阶段计划
15. [`audit/2026-08-13-defensive-code-audit.md`](audit/2026-08-13-defensive-code-audit.md) — 仅后端生产代码的去冗余、哈希与异常定向审计

## 当前状态

当前代码注册 11 个业务模块：`account` / `project` / `imports` / `world` /
`memory` / `outline` / `rag` / `context` / `story` / `writing` / `interaction`。账户连接与全局偏好归
`account`，项目偏好与有效配置归 `project`；前端设置页和 `/api/settings` 兼容路由仍保留。

- `infrastructure/tasks` 提供 PostgreSQL 异步任务队列
- AI 地图册是 `world` 的子系统，API 前缀为 `/api/world/map-atlas`
- 前端注册视图包括 `home / project / journeys / interaction` 以及
  `world / rag / outline / scene / writing / map / generate / llm / settings / project-settings`；
  主导航不显示兼容 `llm` 路由
- `world/map` 旧入口只做兼容跳转
