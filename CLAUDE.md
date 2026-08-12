# CLAUDE.md

本文件是本项目编码 Agent 的开发导航；硬约束、协作协议和停止条件以 `AGENTS.md` 为准。
重大架构决定需要用户确认或 ADR，不把工具、模型或自动化的实现细节当作仓库前提。

## 工作流

### 开始前

1. 读目标模块 README、稳定接口和测试；跨模块任务读调用方/被调用方接口。
2. 检查 `novel_id`、公开模式下的 account/owner、schema、API Key、用户确认、模块边界与
   API/schema/wire contract 风险。
3. 涉及架构、数据库、共享层或 ADR 时，补读 `CONTEXT.md`、`docs/00_整体设计.md`、
   `docs/01_数据库设计.md`、migration 和相关 ADR。
4. 涉及用户可见功能时，补读 `docs/product/user-personas.md`，在计划与 Review 中写明目标
   画像、用户会喜欢的理由、前端舒适度判断、主要摩擦和验证方式。

### 完成前

1. 运行受影响模块测试与适用 `make lint`。
2. 对公共行为、数据模型或跨模块调用，同步对应 README、设计文档和测试；使用
   `docs/architecture/documentation-maintenance.md` 判断影响与记录证据，并运行
   `make docs-check BASE_REF=origin/main`。脚本列出但未修改的文档必须在 PR 中逐项说明
   无当前架构影响。
3. 合并前确认：稳定接口仍正确、隔离与安全规则未破坏、LLM 输出仍满足待处理/授权语义，
   且危险操作仍需确认。
4. 用户可见功能确认主操作、状态、下一步和错误反馈使用用户语言；高频路径不暴露 raw ID、
   JSON、Prompt/token 或内部状态，适用的空态、恢复、窄屏与草稿保护已验证。

Spec 的显式需求优先于实现细节；Spec 内部矛盾应停止并请求 triage。ADR 优先于 Spec，
安全与本仓库硬约束优先于二者。

## 架构速览

| 层 | 模块 | 职责 |
|---|---|---|
| 事实层 | project, world, memory | 项目与正史事实、记忆 |
| 结构层 | outline | threads、arcs、Scene 与结构计划 |
| 辅助层 | imports, rag, context, writing, settings | 导入、检索、上下文、正文、配置 |
| 独立 RP 领域 | interaction | 隐藏项目、不可变选中历史、流式故事与回顾 |

`infrastructure/llm` 与 `infrastructure/tasks` 是共享基础层；`map` 是 `world` 拥有的 AI 地图册子系统。
当前业务模块共 11 个：`account`、`project`、`imports`、`world`、`memory`、`outline`、`rag`、
`context`、`writing`、`settings`、`interaction`。`account` 是公开身份与 owner 边界，
`interaction` 是 RP 私人故事领域，二者都不属于作者小说创作资产三层；
`geo`、`review`、`character`、`timeline` 已移除或合并，不再作为模块
依赖目标。

- Backend API：`backend/app/main.py`；worker：`backend/run_worker.py`；前端：
  `frontend-console/index.html`。
- 跨模块只用 contracts、facade 或 DI port；API/facade 不承载复杂业务。模块文件按需使用，
  不为形式建立空接口。
- 领域真相、状态投影、Scene、alias、RAG/context 分工与受控 LLM 语义见 `CONTEXT.md`；
  Prompt 清单和契约见 `docs/prompts/Prompt体系设计.md`。
- 用户画像、双入口产品方向和功能/前端体验判断门禁见
  `docs/product/user-personas.md`。

## 实现检查

- 新增接口前做 deletion test；只有稳定跨模块消费、真实替换实现或测试收益才增加 seam。
- 重复业务逻辑下沉到拥有领域概念的模块，不在 API、facade 或前端复制。
- 测试优先经过稳定接口；本模块复杂查询、状态机和错误路径可直接测试内部实现。
- demo schema 重构可重建开发库，但必须同步模型、Pydantic schema、调用方、测试和文档。

## 测试与工具

| 场景 | 约定 |
|---|---|
| Unit/Integration | SQLite 内存 + `pytest-asyncio` auto；每个 `conftest.py` 导入必要 FK 模型 |
| E2E | Docker PostgreSQL；外部 LLM 默认 mock/fixture，真实 LLM 只用于明确集成验收 |
| Lint | Ruff，line length 90，Python 3.12，规则 E/F/W/I/N/UP，双引号 |

常用命令：`make dev`、`make test`、`make test-fast-coverage TEST_WORKERS=2`、
`make test-frontend FRONTEND_ARGS="<test>"`、`make lint`、`make format`、`make db && make migrate`。
完整命令和 Review 门禁见 `development-guide.md`、`testing-guide.md`。架构文档完整性可用
`make docs-check` 随时验证；机器清单位于
`docs/architecture/architecture-documents.toml`。

Issue/PR 操作见 `docs/agents/issue-tracker.md`，标签见 `docs/agents/triage-labels.md`，领域
文档布局见 `docs/agents/domain.md`。
