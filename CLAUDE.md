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

1. 读取目标模块的 `README.md` → `contracts.py` → `facade.py`（如存在）
2. 确认修改不违反模块边界规则（见下方"架构约束"）
3. 确认修改不违反禁止事项（见 `AGENTS.md` 第 2 节）
4. 如涉及跨模块影响，先读相关模块的 `contracts.py`
5. 如涉及 ADR 记录的决策，先读对应 ADR

### 修改代码后

1. 运行受影响模块的测试
2. 运行 `make lint`
3. 如修改了 `contracts.py`、`facade.py`、API 路由、Pydantic schema、数据库表结构：
   - 更新模块 README
   - 更新模块测试
   - 更新所有调用方
   - 更新 `docs/` 下对应文档
4. `git push` 后自动触发 `/structure-docs-update` 同步设计文档

### 合并前 Checklist

- [ ] 受影响模块测试全部通过
- [ ] Lint 通过
- [ ] 跨模块 import 仅通过 contracts/facade
- [ ] novel_id 隔离未破坏
- [ ] 无 AI 输出直接写入正史
- [ ] 无 innerHTML / eval / exec 风险
- [ ] 危险操作（合并/删除/废弃）保留二次确认
- [ ] `AGENTS.md` 与 `CLAUDE.md` 禁止项保持同步

---

## 高优先级原则

### P0 — 违反即阻塞合并

1. **Candidate → Canonical 默认流程**：AI 输出默认进入 candidate，用户确认后入正史；深度导入等用户确认启动的自动流水线可直接写入 canonical，并保留可编辑/可回滚标记。
2. **业务删除优先状态化**：常规业务对象优先使用 `draft`/`candidate`/`canonical`/`deprecated`/`ignored`/`conflicted` 状态字段；项目永久删除和 demo 开发库重建可硬删除。
3. **novel_id 隔离**：所有 API 在 service 层强制校验跨 novel 访问控制。
4. **模块边界**：跨模块只 import `contracts.py` 和 `facade.py`，禁止 import `models.py` / `repositories.py` / `services.py`。
5. **无 innerHTML**：用户/AI 内容使用 `textContent` 或 `esc()`。
6. **无 eval/exec**：禁止对 LLM 输出执行 eval/exec。
7. **API Key 安全**：仅环境变量，不写日志，不返前端。
8. **危险操作确认**：合并/删除/废弃操作必须有用户二次确认。

### P1 — 发布前必须修复

- 模块直接 import 其他模块的内部实现
- Context Compiler 无预算控制
- LLM 输出未校验即入库
- 文件上传绕过类型/大小限制
- 缺少模块级基础测试

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
├── README.md        — 职责、表、facade、测试方式
├── contracts.py     — 跨模块数据契约
├── models.py        — SQLAlchemy ORM
├── schemas.py       — Pydantic 请求/响应
├── repositories.py  — 数据访问层
├── services.py      — 业务逻辑
├── facade.py        — 公开跨模块 API（薄层转发）
├── api.py           — FastAPI 路由（薄层：校验 → 委托）
└── tasks.py         — 异步任务（可选）
```

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

### 跨模块导入（严格）

- 允许：`modules/A` → `modules/B/contracts.py` 或 `facade.py`
- 允许：`modules/*` → `core/`, `shared/`, `infrastructure/llm/`, `infrastructure/tasks/`
- 禁止：直接 import 其他模块的 `models.py` / `repositories.py` / `services.py`
- 禁止：API 层或 facade 层写复杂业务逻辑

---

## 关键领域约定

- **实体抽取 ≠ NER**：只抽取长期创作资产，不抽取路人/普通道具/代词/一次性场景
- **别名内联存储**：`core_entities.aliases` JSONB，标记 `alias_of_existing`
- **场景卡 JSONB**：`chapter_cards.scene_cards` JSONB，无独立表
- **创作 Agent 非多 Agent 系统**：4 核心创作 Prompt + 工具提取 Prompt，非自治 Agent
- **无复杂多 Agent**：未经用户明确要求或 ADR，不引入多 Agent 协同框架

---

## 测试

| 上下文 | 数据库 | 模式 |
|--------|--------|------|
| Unit/Integration | SQLite 内存 (`aiosqlite`) | 每测试会话新建表 |
| E2E | 真实 PostgreSQL | Docker PG via `docker compose` |

- 优先通过 facade 测试（`from modules.x.facade import func`）
- 每个测试 `conftest.py` 必须 import 所有 FK 依赖的模型（至少 `modules.project.models`）
- `pytest-asyncio` 模式：`asyncio_mode = "auto"`
- E2E 测试使用真实 LLM 调用（不 mock）

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

- `AGENTS.md` ↔ `CLAUDE.md` 禁止项保持同步
- 用户显式指令 > 本文档 > 模块 CLAUDE.md
- `git push` 后运行 `/structure-docs-update`
- 本文档不承载项目结构、实施计划、长篇设计说明 — 此类内容见 `development-guide.md`
