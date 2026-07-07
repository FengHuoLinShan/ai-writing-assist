# AI 长篇小说结构化创作引擎文档索引

## 顶层文档

1. [`00_整体设计.md`](00_整体设计.md) — 项目定位、核心原则、三层架构、模块职责
2. [`01_数据库设计.md`](01_数据库设计.md) — 所有表的实际 SQL 定义与要点说明
3. [`AI开发规则.md`](AI开发规则.md) — 历史设计说明；Agent 运行时以根目录 `AGENTS.md` 为准
4. [`核心业务场景与预期行为.md`](核心业务场景与预期行为.md) — 用户可感知业务流程

## 指导文件分工

- 根目录 `AGENTS.md` 记录所有编码 Agent 的硬约束、协作协议和终止条件
- 根目录 `CLAUDE.md` 记录编码 Agent 的开发入口、架构导航和命名约定
- 项目结构、目录设计、分层架构写入 [`00_整体设计.md`](00_整体设计.md)
- 开发命令与工程规则写入根目录 `development-guide.md`
- 测试要求与 Review 分级写入根目录 `testing-guide.md`
- 模块专属约束写入模块 README 或模块级 `CLAUDE.md`

## 子模块文档

1. `modules/01_project.md` — 小说项目模块
2. `modules/02_world.md` — 世界对象模块
3. `modules/05_memory.md` — 长期记忆模块
4. `modules/07_outline.md` — 结构化剧情模块
5. `modules/08_rag.md` — 检索增强模块
6. `modules/09_context.md` — 上下文编译模块
7. `modules/11_writing.md` — 正文草稿承载模块
8. `modules/13_imports.md` — 小说导入模块
9. `modules/12_infrastructure.md` — 基础设施模块（LLM + PostgreSQL 任务队列）
10. `modules/14_frontend.md` — 前端控制台
11. `modules/15_map.md` — 动态地图子系统（world 模块子系统）

已移除的旧模块：`geo` / `character` / `timeline` / `review`。地点、人物、事件能力已并入 `world`，结构复查模块暂缓。

## Prompt 设计

1. `prompts/Prompt体系设计.md` — Prompt 体系总览

## 验收基线

1. [`acceptance/2026-07-07-single-character-pov-prose-acceptance-baseline.md`](acceptance/2026-07-07-single-character-pov-prose-acceptance-baseline.md) — 单角色 POV 正文候选生成能力（建议 1-4）最终验收对照基线

## 推荐阅读顺序

如果要理解全局：
1. `00_整体设计.md`
2. `01_数据库设计.md`
3. `AGENTS.md`
4. `CLAUDE.md`

如果要开发某个模块：
1. 先读根目录 `CLAUDE.md` 或 `AGENTS.md`
2. 再读 `development-guide.md` 和 `testing-guide.md`
3. 继续读对应 `modules/<模块>.md` 与模块 README
4. 最后读 `01_数据库设计.md` 中该模块相关表

## 代码审计

1. [`audit/2026-07-07-全量代码库审计报告.md`](audit/2026-07-07-全量代码库审计报告.md) — 全量三维度审计（性能、安全、架构），88 条优化项
2. [`audit/2026-07-07-文档审计报告.md`](audit/2026-07-07-文档审计报告.md) — 77 个文档分类审计，含归档/更新/新建计划
3. [`audit/2026-07-07-可优化清单.md`](audit/2026-07-07-可优化清单.md) — 可追踪的逐项优化 checklist

## 当前状态

当前代码注册 8 个业务模块：`project` / `imports` / `world` / `memory` / `outline` / `rag` / `context` / `writing`。

- `infrastructure/tasks` 提供 PostgreSQL 异步任务队列
- 动态地图是 `world` 的子系统，API 前缀为 `/api/world/maps`
- 前端一级入口为 `project / writing / world / map / rag / outline / generate / context`
- `world/map` 旧入口只做兼容跳转
