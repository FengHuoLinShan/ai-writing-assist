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
4. 新增或显著修改用户可见功能前，阅读 `docs/product/user-personas.md`；计划与 Review 必须
   明确目标画像、用户会喜欢它的理由、前端舒适度、主要摩擦和验证方式。功能可以只服务其中
   一类画像，但不得把作者后台复杂度无差别转嫁给阅读型用户。
5. 开始非平凡实现前运行 `make docs-check`，确认当前架构文档清单没有既有漂移；收尾运行
   `make docs-check BASE_REF=origin/main`，按输出更新文档，或在 PR 中逐项说明无当前文档
   影响。机器清单位于 `docs/architecture/architecture-documents.toml`。

Skill、自动化和编码工具的内部能力不构成仓库契约，不能覆盖本文件或稳定接口。

## 运行时 LLM

- 本项目不实现自治或多 Agent 运行时。LLM step 必须由确定性业务工作流编排，带 schema
  校验、预算、超时、日志和明确权限；不得自主选工具、跨模块编排或绕过确认。
- 新增任何带 `novel_id` 的业务 LLM 服务必须通过
  `modules.project.facade.open_project_llm_client()` 获取有效配置。provider、model 与 Key
  来自项目 owner 当前已验证的账户连接；项目仅提供非 secret 工作流设置。可恢复任务使用
  secret-free project snapshot seam，并以 snapshot 固定的 provider 读取当前轮换后的账户 Key。业务模块不得直接
  `LLMClient()`、`LLMClient.from_project_settings()` 或自行拼装 provider/profile。独立
  embedding 适配器仅可保留静态门禁中已有的窄例外，新增例外必须说明配置边界和迁移决定。
- Prompt 清单与调用契约见 `docs/prompts/Prompt体系设计.md`，不要在此复制易变文件清单。
- 普通 LLM 输出只进入待处理建议或临时预览。仅经持久化用户授权的自动流水线可写入允许的
  派生/已采用资产，且必须保存授权范围、来源、workflow、可编辑/可回滚标记与测试；冲突、
  低置信或无法消歧结果仍进入待处理。

## 不可违反的约束

### 架构与代码

- 默认栈为 FastAPI、PostgreSQL async task queue 与 Vue 3 SFC 前端（ADR-0009）。既有 hash
  router 仍是窄的 route-host seam；业务页经 `vue/mountIsland.js` 注册，组件只能经
  `vue/bridge/index.js` 访问 API、state、router、toast 等既有基建（禁裸全局）。新增基础设施、前端栈、
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

### 产品与前端体验

- 用户可见功能不能只以“技术可实现”或“测试通过”证明价值；按
  `docs/product/user-personas.md` 回答目标用户是否会喜欢、是否愿意重复使用，以及前端是否
  舒服。缺少真实数据时将结论标记为产品假设，不伪装成用户验证。
- 默认界面使用作者或读者能理解的语言，不暴露 raw ID、JSON、Prompt/token、内部枚举或
  数据库心智模型；诊断能力放入明确的次级入口。复杂能力渐进展开，高频任务就地完成。
- 用户可见行为验收除正常流外，还应覆盖适用的首次进入、空态、加载、失败/冲突、保存反馈、
  离开恢复、误操作保护和窄屏体验。草稿、当前上下文和长任务进度不得因导航或晚到响应静默丢失。

### 数据与安全

- 所有业务读写保持 `novel_id` 隔离；API、LLM 输出和入库必须经过 Pydantic/调用方 schema。
- 公开浏览器路径还必须同时遵守当前 account principal 与项目 `owner_id` 门禁；不得接受调用方
  指定的 owner，也不得用 worker/system 身份绕过用户请求的 owner 校验。owner 边界不替代
  `novel_id` 过滤。
- 已采用对象默认不硬删除，优先历史状态；项目永久删除除外。文稿导入上传仅允许
  `.txt .epub .html .htm .mobi .azw3`，且不超过 50MB。世界对象图片是受限例外：仅可经
  owner + `novel_id` 门禁的对象图片接口上传真实 PNG/JPEG，严格小于 6MiB、最大
  4096×4096，并由服务端去元数据后转换为 WebP；不得把该例外扩展为通用文件上传。
- 实体抽取只保留长期创作资产；别名附着已有对象，不创建重复实体。
- demo 阶段可重建开发库，不要求保留 schema 迁移数据兼容；仍必须同步 ORM、schema、调用方、
  测试和文档，且不放宽上述安全约束。

### 交付与操作

- 合并、删除、废弃等危险操作保留二次确认；不得提交 `.env`，不得跳过受影响模块测试合并。
- 公共契约、用户行为、数据模型或跨模块调用变化时，在评审前同步权威文档和测试。纯内部重排
  不强制改写设计文档，但必须显式核对并记录无影响原因。执行细则和自动门禁见
  `docs/architecture/documentation-maintenance.md`。
- 修改 `core/`、`shared/`、`infrastructure/` 前必须理解调用边界并显式说明风险。

## 协作与冲突

- 并行开发使用独立 worktree/分支；不同 Agent 不同时改同一模块。共享层修改在 PR 标注冲突
  风险。涉及分支、PR 或 Issue 协调时，尽力检查远端分支、`ready-for-agent` Issue 和本地
  改动；网络不可用时记录限制。小修、静态审查和文档审查无需远端检查。
- 本地实现不得直接提交到 `main`：从最新 `origin/main` 创建 `codex/<slug>` 主题分支，
  经受影响测试、lint、文档同步和评审后再合入 `main`。`main` 是唯一发布主干，不维护会与
  实际部署漂移的长期“生产分支”。
- 生产只允许通过 `deploy/scripts/release.sh <full-40-character-sha>` 部署
  `origin/main` 可达的固定 commit；服务器 checkout 保持 detached，发布状态以
  `deploy/.state/current-commit` 为准。主题分支、脏工作树、本地未推送 commit 和分支名
  均不得直接作为生产部署输入。
- Issue/PR 用 `gh` 管理；标签见 `docs/agents/triage-labels.md`。常规上下文放 Issue/PR，重大
  长期决策放 ADR；不要把 Agent 交接写进代码注释。
- 冲突优先级：用户指令（受安全例外限制）→ 本文件 → ADR → 模块稳定接口 → Spec → 自行判断。
  Spec 内部矛盾或无法裁定的设计冲突应标记 `needs-triage` 并等待澄清；后提交者负责兼容
  逻辑和文档冲突。

## 完成与停止

- 完成：指定功能、受影响测试、适用 lint、`make docs-check BASE_REF=origin/main` 和文档
  同步/无影响核对均已完成。
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
