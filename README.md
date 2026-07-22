# AI 长篇小说结构化创作引擎

> FastAPI 后端 · 零框架前端 · PostgreSQL + pgvector · 异步任务队列

AI 长篇小说创作辅助系统，提供从**导入 → 世界构建 → 记忆与剧情组织 → 检索增强 → 上下文编译 → 正文写作 → 地图工作台**的全链路支持。

## 架构总览

![模块架构图](docs/architecture/module-architecture.html)

**三层结构：**

| 层级 | 模块 | 职责 |
|------|------|------|
| **事实层** | `project` · `world` · `memory` | 项目根聚合、世界对象/人物/事件、长期记忆 |
| **结构层** | `outline` | 剧情线、篇章纲、Scene、伏笔与揭示计划 |
| **辅助层** | `imports` · `rag` · `context` · `writing` · `settings` | 文件导入、检索增强、上下文编译、正文写作、LLM/作者偏好覆盖 |

> 详细交互图 → [`docs/architecture/module-architecture.html`](docs/architecture/module-architecture.html)（浏览器打开，支持导出 PNG/PDF）

## 模块清单

| 模块 | 核心能力 |
|------|---------|
| **project** | 小说项目 CRUD、novel_id 全局隔离（零跨模块依赖） |
| **world** | 核心实体、人物、事件、关系、动态地图、待处理建议与作者展示状态投影 |
| **memory** | `memory_events` 事件溯源与 `memory_snapshots` 全景快照 |
| **outline** | 剧情线、篇章纲、Scene、伏笔计划、揭示计划 |
| **rag** | canonical/working 独立分块、embedding 与混合候选召回；证据输出由 context 重读 writing 原文校验 hash |
| **context** | 分层编译 LLM 上下文、提供 AI 参考资料审查台、管理确认记录与自动上下文快照审计 |
| **writing** | 工作稿/已发布正文、AI 正文建议采用、Scene 树工作台、发布后索引与记忆更新 |
| **imports** | 外部文件解析、经批量授权的深度导入、Scene 切分、实体/结构抽取与异常汇总 |
| **settings** | 全局 LLM 默认、全局作者偏好与项目级偏好覆盖；API Key 始终项目级 |
| **infrastructure/tasks** | PostgreSQL 队列的异步任务调度（enqueuer → worker），不是业务模块 |

前端当前注册 11 个视图路由：`project` / `world` / `rag` / `outline` / `scene` / `writing` / `map` / `generate` / `llm` / `settings` / `project-settings`。`rag` 在产品导航显示为“小说检索”，默认进入检索页，索引维护为第二子页。主导航不显示兼容 `llm` 路由；旧 `context` hash 会重定向到生成中心任务页。地图已升级为侧边栏一级入口，`world` 内的旧地图子入口仅保留兼容跳转。

## 作者可见资产状态

产品界面不要求作者理解各模块的 `draft`、`candidate`、`proposal`、`canonical` 等内部状态：

- 结构化资产统一显示为“待处理 / 已采用 / 历史”；冲突、低置信和需人工检查作为注意原因展示。
- 正文只使用“工作稿 / 已发布”；AI 文本在采用前是待处理建议，采用后复制为普通工作稿。
- 人工创建世界对象、关系和别名时，保存即表示采用。
- 深度导入在启动时一次说明并记录自动采用范围；异常结果进入待处理，完成页汇总已采用/待处理/未采用。

兼容期 API 继续返回原始状态字段，并按领域增加 `display_state`、`source`、`attention_reasons`、`suggested_action` 等派生字段。任务状态、地图 Observation/Fact 分层和上下文 `canonical/working` 模式仍保留其技术含义。

## 快速开始

```bash
# 启动数据库并迁移
make db && make migrate

# 启动全套开发服务（后端 + worker + 前端）
make dev

# 本地环境异常时先运行只读诊断
make doctor

# 运行快速后端测试（不连接 PostgreSQL 或真实 LLM）
make test

# PostgreSQL E2E（必须显式指向已迁移到 head 的专用测试库）
E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-e2e

# 本地复现 PR 的 PostgreSQL 高风险门禁
E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-postgresql-critical

# 仅启动前端控制台
cd frontend-console
npm run dev
```

详见 [`development-guide.md`](development-guide.md) 和 [`testing-guide.md`](testing-guide.md)。

## 文档

- [整体设计](docs/00_整体设计.md)
- [数据库设计](docs/01_数据库设计.md)
- [模块文档索引](docs/README.md)
- [动态地图子系统](docs/modules/15_map.md)
- [设置模块](docs/modules/16_settings.md)
- [Prompt 体系设计](docs/prompts/Prompt体系设计.md)
- [CLAUDE.md](CLAUDE.md) — 开发约定与规则
- [AGENTS.md](AGENTS.md) — Agent 协作约束
