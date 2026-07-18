# AGENTS.md

本文件是本仓库所有编码 Agent 的硬约束与协作协议。用户指令优先，但不得绕过安全、
`novel_id` 隔离、真实数据保护或危险操作确认。`CLAUDE.md` 提供开发导航；实现与当前
事实以模块 README、稳定接口、ORM、migration 和测试为准。

## 开始工作

1. 阅读本文件、`CLAUDE.md` 与目标模块 README；跨模块任务再读相关
   `contracts.py` / `facade.py` / DI 注册。
2. 非平凡计划必须说明：影响模块、稳定接口、API/schema/wire 风险、是否需用户确认或 ADR、
   以及验证方式。
3. 架构、数据库、共享层或安全任务还应读 `CONTEXT.md`、相关 ADR、设计文档和 migration。

Skill、自动化和编码工具的内部能力不构成仓库契约，不能覆盖本文件或稳定接口。

## 运行时 LLM

- 本项目不实现自治或多 Agent 运行时。LLM step 必须由确定性业务工作流编排，带 schema
  校验、预算、超时、日志和明确权限；不得自主选工具、跨模块编排或绕过确认。
- 新增任何带 `novel_id` 的业务 LLM 服务必须通过
  `modules.project.facade.open_project_llm_client()` 获取有效配置，固定按“项目覆盖 →
  全局默认 → 系统默认”继承；可恢复任务使用 project snapshot seam。业务模块不得直接
  `LLMClient()`、`LLMClient.from_project_settings()` 或自行拼装 provider/profile。独立
  embedding 适配器仅可保留静态门禁中已有的窄例外，新增例外必须说明配置边界和迁移决定。
- Prompt 清单与调用契约见 `docs/prompts/Prompt体系设计.md`，不要在此复制易变文件清单。
- 普通 LLM 输出只进入待处理建议或临时预览。仅经持久化用户授权的自动流水线可写入允许的
  派生/已采用资产，且必须保存授权范围、来源、workflow、可编辑/可回滚标记与测试；冲突、
  低置信或无法消歧结果仍进入待处理。

## 不可违反的约束

### 架构与代码

- 默认栈为 FastAPI、PostgreSQL async task queue；前端为 Vanilla JS → Vue 3 渐进迁移中
  （ADR-0009）：迁移后的视图用 Vue SFC，经 `vue/mountIsland.js` 注册进既有 vanilla router，
  组件只能经 `vue/bridge/index.js` 访问 vanilla 基建（禁裸全局）。新增基础设施、前端栈、
  数据库/队列/向量存储或强制类型门禁，须用户确认或 ADR。
- 生产业务代码跨模块只能依赖 `contracts.py`、`facade.py` 或已注册 DI port；不得直接依赖
  其他模块的 `models.py`、`repositories.py`、`services.py`。测试、Alembic、ORM metadata
  注册与应用组合根可有限导入实现，但组合根不得承载业务判断。
- API 与 facade 保持薄层：参数适配、稳定返回形状和委托。非平凡编排下沉到拥有领域概念的
  模块实现。新增 facade/contracts/DI port 前做 deletion test，避免 pass-through seam。
- 动态用户、AI 或 API 内容不得未经转义进入 `innerHTML`；Vue 模板动态内容禁止 `v-html`
  （依赖 `{{ }}` 自动转义）；不得 `eval` / `exec` LLM 输出；不得硬编码、记录或返回 API Key。
- 生产代码不得 import 或检测 `Mock`；测试替身通过 DI。所有 `@patch` / `mock.patch` 使用
  `autospec=True`，无法使用时说明原因。

### 数据与安全

- 所有业务读写保持 `novel_id` 隔离；API、LLM 输出和入库必须经过 Pydantic/调用方 schema。
- 已采用对象默认不硬删除，优先历史状态；项目永久删除除外。上传仅允许
  `.txt .epub .html .htm .mobi .azw3`，且不超过 50MB。
- 实体抽取只保留长期创作资产；别名附着已有对象，不创建重复实体。
- demo 阶段可重建开发库，不要求保留 schema 迁移数据兼容；仍必须同步 ORM、schema、调用方、
  测试和文档，且不放宽上述安全约束。

### 交付与操作

- 合并、删除、废弃等危险操作保留二次确认；不得提交 `.env`，不得跳过受影响模块测试合并。
- 公共契约、用户行为、数据模型或跨模块调用变化时，在评审前同步权威文档和测试。纯内部重排
  不强制更新设计文档。执行细则见 `docs/architecture/documentation-maintenance.md`。
- 修改 `core/`、`shared/`、`infrastructure/` 前必须理解调用边界并显式说明风险。

## 协作与冲突

- 并行开发使用独立 worktree/分支；不同 Agent 不同时改同一模块。共享层修改在 PR 标注冲突
  风险。涉及分支、PR 或 Issue 协调时，尽力检查远端分支、`ready-for-agent` Issue 和本地
  改动；网络不可用时记录限制。小修、静态审查和文档审查无需远端检查。
- Issue/PR 用 `gh` 管理；标签见 `docs/agents/triage-labels.md`。常规上下文放 Issue/PR，重大
  长期决策放 ADR；不要把 Agent 交接写进代码注释。
- 冲突优先级：用户指令（受安全例外限制）→ 本文件 → ADR → 模块稳定接口 → Spec → 自行判断。
  Spec 内部矛盾或无法裁定的设计冲突应标记 `needs-triage` 并等待澄清；后提交者负责兼容
  逻辑和文档冲突。

## 完成与停止

- 完成：指定功能、受影响测试、适用 lint 和文档同步均已完成。
- 停止并报告：需要用户确认、Spec 矛盾、外部依赖连续 3 次不可用、同一测试修复尝试 3 次后
  仍失败，或任务需要未经确认的新架构。
- 立即停止：发现真实数据丢失风险、跨 `novel_id` 泄漏、安全规则绕过，或未确认的破坏性 Git
  操作（如 force push main、`reset --hard`）。

## 文档导航

- 单模块：模块 README → 稳定接口 → 测试；需要诊断内部行为时再读实现。
- 跨模块：加读全部相关稳定接口；架构/安全：加读 `CONTEXT.md`、ADR 与全仓库证据。
- 开发命令与测试门禁见 `development-guide.md`、`testing-guide.md`；Issue、triage 与领域文档
  消费细则见 `docs/agents/`。

本文件只放硬约束和协作协议；项目结构、计划和长篇设计说明分别放在设计文档、ADR 和开发指南。
