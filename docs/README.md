# AI 长篇小说结构化创作引擎文档索引

## 顶层文档

1. [`00_整体设计.md`](00_整体设计.md) — 项目定位、核心原则、三层架构、里程碑
2. [`01_数据库设计.md`](01_数据库设计.md) — 所有表的实际 SQL 定义与要点说明
3. [`AI开发规则.md`](AI开发规则.md) — AI 插件（Claude Code / Codex）开发规则
4. [`项目进度.md`](项目进度.md) — 里程碑完成情况追踪

## 指导文件分工

- 根目录 `CLAUDE.md` / `AGENTS.md` 只记录“不能做什么”
- 项目结构、目录设计、分层架构写入 [`00_整体设计.md`](00_整体设计.md)
- 里程碑、当前状态、已知不足写入 [`项目进度.md`](项目进度.md)
- 开发命令与工程规则写入根目录 `DEVELOPMENT_GUIDE.md`
- 测试要求与 Review 分级写入根目录 `TESTING_GUIDE.md`
- 模块专属约束写入模块 README 或模块级 `CLAUDE.md`

## 子模块文档

1. `modules/01_project.md` — 小说项目模块
2. `modules/02_world.md` — 世界对象模块
3. `modules/03_geo.md` — 地理关系与宏观历史模块
4. `modules/04_character.md` — 人物档案与知识边界模块
5. `modules/05_memory.md` — 长期记忆模块
6. `modules/06_timeline.md` — 轻量时间线模块
7. `modules/07_outline.md` — 结构化剧情模块
8. `modules/08_rag.md` — 检索增强模块
9. `modules/09_context.md` — 上下文编译模块
10. `modules/10_review.md` — 结构复查模块
11. `modules/11_writing.md` — 正文草稿承载模块
12. `modules/12_infrastructure.md` — 基础设施模块
13. `modules/13_imports.md` — 小说导入模块（原设计以外新增）
14. `modules/14_frontend.md` — 前端控制台

## Prompt 设计

1. `prompts/Prompt体系设计.md` — Prompt 体系总览

## 推荐阅读顺序

如果要理解全局：
1. `00_整体设计.md`
2. `01_数据库设计.md`
3. `项目进度.md`
4. `AI开发规则.md`

如果要开发某个模块：
1. 先读根目录 `CLAUDE.md` 或 `AGENTS.md`
2. 再读 `DEVELOPMENT_GUIDE.md` 和 `TESTING_GUIDE.md`
3. 继续读对应 `modules/<模块>.md` 与模块 README
4. 最后读 `01_数据库设计.md` 中该模块相关表

## 当前状态

截至 2026-05-25，项目已完成 MVP 全模块开发。后端 13 个模块全部实现（含 imports 和基础设施），前端 SPA 控制台已完成 14 个视图的覆盖。详情见 [`项目进度.md`](项目进度.md)。
