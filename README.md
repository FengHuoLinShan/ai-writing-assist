# AI 长篇小说结构化创作引擎

> FastAPI 后端 · 零框架前端 · PostgreSQL + pgvector · 异步任务队列

AI 长篇小说创作辅助系统，提供从**导入 → 世界构建 → 记忆管理 → 检索增强 → 上下文编译 → 正文写作**的全链路支持。

## 架构总览

![模块架构图](docs/architecture/module-architecture.html)

**四层结构：**

| 层级 | 模块 | 职责 |
|------|------|------|
| 🟡 **核心层** | `project` · `tasks` | 项目管理、异步任务调度 |
| 🟣 **数据层** | `world` · `memory` · `rag` | 世界观引擎、记忆系统、检索增强 |
| 🔵 **剧情结构** | `outline` | 剧情线 + 篇章纲 CRUD、AI 生成 |
| 🟢 **应用层** | `imports` · `context` · `writing` | 内容导入、上下文编译、正文写作 |

> 详细交互图 → [`docs/architecture/module-architecture.html`](docs/architecture/module-architecture.html)（浏览器打开，支持导出 PNG/PDF）

## 模块清单

| 模块 | 核心能力 |
|------|---------|
| **project** | 小说项目 CRUD、novel_id 全局隔离（零跨模块依赖） |
| **imports** | 外部文件解析、深层导入工作流、自动触发实体抽取+剧情生成 |
| **world** | 实体/人物/事件/关系管理、AI 实体抽取、状态组装 |
| **memory** | 按章节的事件记录、全景快照 |
| **rag** | 分块 → embedding → 混合检索（向量 + BM25 + 关键词）、三级仲裁 |
| **outline** | 剧情线 + 篇章纲 CRUD、AI 生成剧情结构 |
| **context** | 从所有数据模块拉取信息，编译为结构化 LLM 上下文 |
| **writing** | 草稿 CRUD、publish 自动触发 RAG 索引 + 记忆快照 |
| **tasks** | PostgreSQL 队列的异步任务调度（enqueuer → worker） |

## 快速开始

```bash
# 启动数据库并迁移
make db && make migrate

# 启动 API 服务
make dev

# 运行测试
make test
```

详见 [`development-guide.md`](development-guide.md) 和 [`testing-guide.md`](testing-guide.md)。

## 文档

- [整体设计](docs/00_整体设计.md)
- [数据库设计](docs/01_数据库设计.md)
- [模块文档索引](docs/README.md)
- [CLAUDE.md](CLAUDE.md) — 开发约定与规则
