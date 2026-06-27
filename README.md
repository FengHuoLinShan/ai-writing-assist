# AI 长篇小说结构化创作引擎

> FastAPI 后端 · 零框架前端 · PostgreSQL + pgvector · 异步任务队列

AI 长篇小说创作辅助系统，提供从**导入 → 世界构建 → 记忆管理 → 检索增强 → 上下文编译 → 正文写作**的全链路支持。

## 架构总览

![模块架构图](docs/architecture/module-architecture.html)

**三层结构：**

| 层级 | 模块 | 职责 |
|------|------|------|
| **事实层** | `project` · `world` · `memory` | 项目根聚合、世界对象/人物/事件、长期记忆 |
| **结构层** | `outline` | 剧情线、篇章纲、Scene、伏笔与揭示计划 |
| **辅助层** | `imports` · `rag` · `context` · `writing` | 文件导入、检索增强、上下文编译、正文写作 |

> 详细交互图 → [`docs/architecture/module-architecture.html`](docs/architecture/module-architecture.html)（浏览器打开，支持导出 PNG/PDF）

## 模块清单

| 模块 | 核心能力 |
|------|---------|
| **project** | 小说项目 CRUD、novel_id 全局隔离（零跨模块依赖） |
| **world** | 核心实体、人物、事件、关系、动态地图、AI 实体抽取、状态组装 |
| **memory** | `memory_events` 事件溯源与 `memory_snapshots` 全景快照 |
| **outline** | 剧情线、篇章纲、Scene、伏笔计划、揭示计划 |
| **rag** | 分块 → embedding → 混合检索（向量 + BM25 + 关键词）、三级仲裁 |
| **context** | 从所有数据模块拉取信息，编译为结构化 LLM 上下文 |
| **writing** | 草稿 CRUD、publish 自动触发 RAG 索引 + 记忆快照 |
| **imports** | 外部文件解析、深度导入三阶段工作流、自动触发实体抽取与剧情生成 |
| **infrastructure/tasks** | PostgreSQL 队列的异步任务调度（enqueuer → worker），不是业务模块 |

## 快速开始

```bash
# 启动数据库并迁移
make db && make migrate

# 启动全套开发服务（后端 + worker + 前端）
make dev

# 运行测试
make test

# 仅启动前端控制台
cd frontend-console
python -m http.server 8080
```

详见 [`development-guide.md`](development-guide.md) 和 [`testing-guide.md`](testing-guide.md)。

## 文档

- [整体设计](docs/00_整体设计.md)
- [数据库设计](docs/01_数据库设计.md)
- [模块文档索引](docs/README.md)
- [动态地图子系统](docs/modules/15_map.md)
- [CLAUDE.md](CLAUDE.md) — 开发约定与规则
- [AGENTS.md](AGENTS.md) — Agent 协作约束
