# AI 开发规则索引

> 本文档已精简为索引。原内容已分散到以下活跃文档，请以这些文档为准。

## 必读文件

| 文件 | 职责 |
|------|------|
| 根目录 `CLAUDE.md` | 编码 Agent 开发入口（架构、流程、命名） |
| 根目录 `AGENTS.md` | 所有编码 Agent 的协作规则与禁止事项 |
| `development-guide.md` | 开发命令、模块结构、架构原则、工程规则 |
| `testing-guide.md` | 测试要求、Review 分级、安全测试清单 |
| `docs/00_整体设计.md` | 项目定位、分层架构、目录结构、模块职责、技术栈 |
| `docs/核心业务场景与预期行为.md` | E2E 测试编写参考（Given-When-Then）与开发轮次计划 |
| 模块目录 `README.md` | 单模块职责、表、API、facade、测试方式 |
| 模块目录 `CLAUDE.md`（若有） | 该模块的特殊禁止事项、风险陷阱和不可绕过的边界 |

## 开发前读取顺序

1. `AGENTS.md` → 禁止事项与协作规则
2. `CLAUDE.md` → 开发入口与架构导航
3. 目标模块 `README.md` → 稳定接口 → 测试
4. 按任务补读：实现任务读 `development-guide.md` / `testing-guide.md`，架构或数据库任务读 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、相关 ADR 和 migration

## 关键规则速查

- **模块边界**：模块 A 只能导入模块 B 的 `contracts.py` / `facade.py`，禁止直接导入 `models.py` / `repositories.py` / `services.py`
- **数据规则**：AI 生成内容默认 candidate → 用户确认 → canonical；深度导入等用户确认的自动流水线可直接写入 canonical
- **安全规则**：API Key 不写日志/不返前端；不 `eval` / `exec` LLM 输出；合并/删除/废弃需二次确认
- **测试规则**：每个模块自带 `tests/`，修改后至少运行该模块测试；跨模块流程放在 `tests/integration/`
- **文档同步**：修改 `contracts.py`、`facade.py`、API 路由、Pydantic schema、数据库表结构后，必须同步更新模块 README、测试、调用方和 `docs/` 对应文件

详细规则请查阅上述活跃文档。
