# CLAUDE.md

## Claude 的角色定位

你是本项目的编码 Agent，负责：功能开发、Bug 修复、代码审查、文档同步。你不是架构决策者 — 重大设计决策需经 ADR 流程（`docs/adr/`）或用户确认。

**互补文档**：
- `AGENTS.md` — Agent 协作体系与禁止事项（所有 Agent 通用）
- `development-guide.md` — 完整开发命令与架构说明
- `testing-guide.md` — 测试规范与 Review 分级

---

## 开发流程

### 修改代码前

1. 读取目标模块的 `README.md` → 稳定接口文件（`contracts.py` / `facade.py` / DI 注册说明，如存在）
2. 确认修改不违反模块边界规则（见下方"架构约束"）
3. 确认修改不违反禁止事项（见 `AGENTS.md` 第 2 节）
4. 如涉及跨模块影响，先读相关模块的 `contracts.py`
5. 如涉及 ADR 记录的决策，先读对应 ADR

### 修改代码后

1. 运行受影响模块的测试
2. 运行 `make lint`
3. 公共契约、用户可见行为、数据模型或跨模块调用变化时，同步更新权威文档和受影响测试；纯内部重排不强制更新设计文档
4. `git push` 后自动触发 `/structure-docs-update` 同步设计文档

### 合并前 Checklist

- [ ] 受影响模块测试全部通过
- [ ] Lint 通过
- [ ] 跨模块依赖仅通过稳定接口（contracts/facade/DI port）
- [ ] novel_id 隔离未破坏
- [ ] 无 AI 输出直接写入正史
- [ ] 无未转义动态 HTML / eval / exec 风险
- [ ] 危险操作（合并/删除/废弃）保留二次确认
- [ ] 不违反 `AGENTS.md` 的硬约束

---

## 高优先级原则

硬约束以 `AGENTS.md` 第 2 节为准；本文件不复制禁令清单，避免漂移。

开发时重点检查：
- `novel_id` 隔离、API Key 安全、LLM 输出 schema 校验
- 未转义用户/AI/API 动态内容不得进入 HTML
- 跨模块不直接 import 其他模块内部实现
- 默认 candidate → 用户确认 → canonical；用户确认启动的自动流水线可写 canonical，但必须保留可编辑/可回滚标记

### Demo 阶段数据库策略

- 当前项目处于 demo 阶段，数据库 schema 重构不需要设计向后兼容迁移或保留旧数据。
- 表结构重构时，可以直接删除并重建开发数据库；重点是 ORM、Pydantic schema、测试、调用方和文档保持一致。
- 不要把 demo 数据库重建规则扩展到生产/用户真实数据，也不要绕过 novel_id 隔离、schema 校验和安全规则。

---

## Spec 冲突处理

当实现过程中发现 Spec 矛盾：

1. **Spec 显式需求 vs 实现细节** → Spec 优先，在 PR 中说明偏差
2. **Spec 内部矛盾** → 停止实现，创建 `needs-triage` Issue，标记具体矛盾点，等待用户澄清
3. **Spec vs ADR** → ADR 优先（ADR 记录的是已验证的设计决策），在 PR 中引用 ADR 编号
4. **Spec vs 本文档/AGENTS.md 禁止项** → 禁止项优先，通知用户 Spec 需修订
5. **Spec 未覆盖的实现选择** → 自行判断，在 PR 描述中记录决策理由

---

## 架构约束

### 模块结构

```
modules/<name>/
├── README.md        — 职责、拥有的数据、稳定接口、测试方式
├── contracts.py     — 跨模块数据契约（有跨模块消费者时）
├── facade.py        — 公开跨模块 API（有真实抽象收益时）
├── models.py        — SQLAlchemy ORM（有持久化时）
├── schemas.py       — Pydantic 请求/响应
├── repositories.py  — 数据访问层（有持久化时）
├── services.py      — 业务逻辑
├── api.py           — FastAPI 路由（薄层：校验 → 委托）
└── tasks.py         — 异步任务（可选）
```

模块按职责选择文件；不要为了满足模板创建 pass-through facade 或空 contracts。

### 三层架构

| 层 | 模块 | 职责 |
|----|------|------|
| 事实层 | project, world, memory | 维护正史事实 |
| 结构层 | outline | 组织事实为执行计划（threads → arcs → chapter cards → scene cards） |
| 辅助层 | rag, context, writing, imports | 检索、上下文编译、草稿生成、文件导入 |

`infrastructure/tasks/` 和 `infrastructure/llm/` 是共享基础层，非业务模块。

### 入口点

- Backend API: `backend/app/main.py`（`uvicorn app.main:app`）
- Worker: `backend/run_worker.py`（PostgreSQL 任务队列，无 Redis/Celery）
- Frontend: `frontend-console/index.html`（`python -m http.server 8080`）

### 8 个活跃模块

`project`, `imports`, `world`, `memory`, `outline`, `rag`, `context`, `writing`

已移除：`geo`, `review`, `character`, `timeline`。Character 功能合并到 `modules/world`。

### 跨模块依赖

- 允许：`modules/A` → `modules/B/contracts.py`、`facade.py` 或已注册的 DI port
- 允许：`modules/*` → `core/`, `shared/`, `infrastructure/llm/`, `infrastructure/tasks/`
- 禁止：直接 import 其他模块的 `models.py` / `repositories.py` / `services.py`
- 禁止：API 层或 facade 层写复杂业务逻辑

---

## 关键领域约定

- **实体抽取 ≠ NER**：只抽取长期创作资产，不抽取路人/普通道具/代词/一次性场景
- **别名内联存储**：`core_entities.aliases` JSONB，标记 `alias_of_existing`
- **Scene 独立管理**：当前以 `scenes` 表作为最小叙事单元；旧 `chapter_cards.scene_cards` JSONB 只作为历史兼容语境
- **创作 Agent 非多 Agent 系统**：4 核心创作 Prompt + 工具提取 Prompt，非自治 Agent
- **无复杂多 Agent**：未经用户明确要求或 ADR，不引入多 Agent 协同框架

---

## 测试

| 上下文 | 数据库 | 模式 |
|--------|--------|------|
| Unit/Integration | SQLite 内存 (`aiosqlite`) | 每测试会话新建表 |
| E2E | 真实 PostgreSQL | Docker PG via `docker compose` |

- 优先通过模块稳定接口测试（facade、DI port 或 API/service 公共方法）
- 每个测试 `conftest.py` 必须 import 所有 FK 依赖的模型（至少 `modules.project.models`）
- `pytest-asyncio` 模式：`asyncio_mode = "auto"`
- 业务 E2E 默认使用 mock/fixture 隔离外部 LLM；真实 LLM 仅放在 provider 集成测试或手动验收

---

## 工具链

- **Ruff**: line-length=90, target py312, rules E/F/W/I/N/UP, 双引号
- **无 mypy/pyright** — 仅 ruff 做静态分析
- **Alembic**: demo 阶段用于初始化/重建 schema；重构时不要求编写保数据迁移
- **不提交 `.env`**：复制 `backend/.env.example`
- **pgvector**: SQLite 测试模式下向量以 JSON 文本存储

---

## 命名约定（非显而易见的）

| 约定 | 规则 |
|------|------|
| Python enum 成员 | `lowercase`（StrEnum 成员名 = DB 值） |
| Python 模块级 logger | `logger`（无下划线前缀） |
| JS 私有方法 | `_camelCase`（仅内部使用） |
| JS View 文件 | `PascalCaseView.js`（与导出对象名匹配） |

---

## 常用命令

| 操作 | 命令 |
|------|------|
| 启动全部服务 | `make dev` |
| 停止全部服务 | `make kill` |
| 后端测试 | `make test` 或 `make test-v` |
| 单个测试 | `make test ARGS="-k test_name -xvs"` |
| 前端测试 | `(cd frontend-console && npm test)` |
| Lint / 格式化 | `make lint` / `make format` |
| DB 启动 + 迁移 | `make db && make migrate` |
| 安装后端 | `pip install -e ".[dev]"`（在 `backend/` 中） |

详见 `development-guide.md` 和 `testing-guide.md`。

---

## Skills 参考

- `/tdd` — 测试驱动开发（RED→GREEN→REFACTOR）
- `/grill-with-docs` — 设计决策压力测试
- `/structure-docs-update` — git push 后自动同步设计文档

---

## Meta

- `AGENTS.md` 是硬约束源头；本文件只补充开发入口和架构导航
- 用户显式指令 > 本文档 > 模块 CLAUDE.md
- `git push` 后运行 `/structure-docs-update`
- 本文档不承载项目结构、实施计划、长篇设计说明 — 此类内容见 `development-guide.md`
