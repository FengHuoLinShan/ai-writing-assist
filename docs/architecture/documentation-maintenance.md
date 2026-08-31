# 架构文档维护流程

本流程解决的不是“补写说明”，而是让每轮较大开发在合并前把当前架构事实、稳定边界和
验证证据同步到正确位置。所有 PR 都运行完整性检查；只有影响公共行为、数据或边界的改动
才要求改写当前文档。小型内部重排仍须显式核对，但不应为了形式制造文档噪声。

## 1. 基本原则

- **代码与迁移优先**：当前 ORM、Alembic、稳定接口和测试是事实判定依据；文档解释它们，
  不反向覆盖实现。
- **就近维护，单一事实源**：模块行为写模块 README，跨模块边界写整体设计或 `CONTEXT.md`，
  表与约束写数据库设计，Prompt 清单写 Prompt 设计。不要把相同事实复制到多个地方。
- **同一开发轮闭环**：若变更影响公共契约、用户可见行为、数据模型或跨模块调用，文档与
  测试是本轮交付的一部分；不能依赖“下次集中补”。
- **历史与当前分离**：计划、验收和审计说明当时的判断，不用于推断当前状态。过期内容要
  归档或明确标记，不把历史正文改写成当前契约。
- **机器清单防遗漏，人工判断语义**：脚本负责发现新增模块、表、任务、路由、Prompt、ADR、
  断链和差异影响；开发者与评审者仍负责判断字段、约束、状态和用户语义是否描述正确。
- **宽触发、窄改写**：业务模块、共享基础设施和前端生产代码的改动都会触发所属文档复核；
  测试改动不触发。复核不等于必须改写，纯内部变化用具体无影响说明闭环。

## 2. 当前文档清单与自动门禁

`architecture-documents.toml` 是当前架构文档的机器清单，登记：

- 中央设计、领域词汇、导航、维护流程和 ADR 索引；
- 8 个业务模块、共享基础设施、前端与 Prompt 的代码根、设计文档和代码邻近 README；
- 每个后端组件的 API 前缀；
- 代码路径到必查文档的差异影响规则。

`scripts/check_architecture_docs.py` 提供两层门禁：

1. **完整性门禁**：无须 Git base。验证清单文件存在、模块目录与模块文档一一对应、所有 ORM
   表在数据库设计和所属组件文档中可见、API 前缀/任务/路由/Prompt 已登记、ADR 全部进入
   `docs/adr/README.md`、本地链接可达、Draw.io XML/ID/edge endpoint 正常。
2. **差异影响门禁**：提供 `BASE_REF` 后，根据 API、facade、contracts、ORM、migration、
   task、业务模块/基础设施/前端生产代码、前端 route/wire 和 Prompt 的实际改动，列出本轮
   必查文档；未修改的必查文档必须在 PR 模板中逐项核对并说明无影响原因，否则 CI 失败。

新增、移动或归档 `docs/architecture/`、`docs/modules/`、模块 README 或 ADR 时，先更新
清单/ADR 索引，再运行门禁。清单只描述“哪些文档必须存在与何时检查”，不得复制易变实现。

## 3. 什么算“较大开发”

满足任一条件即启动本流程：

1. 新增、移除、合并业务模块，或改变模块拥有的数据/稳定边界；
2. 变更 API、Pydantic schema、前端 wire shape、facade、contracts 或 DI port；
3. 新增或修改 ORM 表、关键索引、隔离/采用/可见性等跨表不变量；
4. 改变用户工作流、自动流水线授权、LLM 输出落点、回滚或错误恢复语义；
5. 新增重要运行时工作流、任务处理器、Prompt 调用契约，或改变基础设施拓扑；
6. 一轮修改跨越两个以上业务模块，即使每一处变更都很小。

纯重命名、局部实现重排、测试加例或不改变外部语义的性能调整通常只需更新代码邻近
README（若其中描述了被重排的实现），无需更新总览。

operation receipt 或任务 attempt 策略变更还应同步 ADR、tasks/LLM README、数据库设计、
所属业务模块和前端页内恢复说明；只改 task handler 清单不足以表达用户可恢复语义。

## 4. 文档影响矩阵

| 变更事实 | 必查文档 | 何时更新 |
|---|---|---|
| 模块清单、职责、依赖方向、技术拓扑 | `docs/00_整体设计.md`、`docs/architecture/module-architecture.drawio`、`docs/architecture/module-architecture.html`、`docs/architecture/README.md` | 模块或跨模块边界改变时；Draw.io 是可编辑图源，HTML 是兼容预览 |
| 稳定接口、领域职责、路由、依赖、测试入口 | 对应 `backend/modules/<name>/README.md`；必要时 `docs/modules/<nn>_<name>.md` | 对外能力或本模块契约改变时 |
| 领域词汇、状态投影、资产归属、采用/可见性语义 | `CONTEXT.md` | 作者或跨模块消费者对概念的理解改变时 |
| 表、外键、索引、唯一约束、派生/事实边界 | `docs/01_数据库设计.md`、对应模块 README | ORM 或 Alembic 改变时 |
| API 请求/响应、canonical/兼容挂载、前端工作台、用户流程 | `docs/modules/14_frontend.md`、对应模块 README、`docs/核心业务场景与预期行为.md` | wire shape 或用户可见流程改变时；同 handler 多路径应有 OpenAPI 对等测试 |
| Prompt 清单、调用方、结构化输出约束 | `docs/prompts/Prompt体系设计.md`、`backend/prompts/` | Prompt 文件、调用方或 schema 契约改变时 |
| 受控 LLM、队列、任务恢复或观测 | `backend/infrastructure/*/README.md`、`docs/modules/12_infrastructure.md` | 基础设施行为或运行方式改变时 |
| 图片模型、私有对象存储或外部对象清理 | 所属模块 README、`docs/modules/12_infrastructure.md`、部署配置；长期拓扑取舍另写 ADR | 图片运行时、存储边界、bucket/凭据权限、容量配额或删除恢复语义改变时 |
| 设计取舍改变且会约束未来实现 | `docs/adr/`、`docs/adr/README.md` | 需要长期架构决策时；先取得用户确认或走 ADR 流程 |

`docs/README.md` 只在新增、移动、归档当前文档或改变阅读入口时更新。它是索引，不复制
模块细节。审计、验收与实施计划只记录时间点证据，不取代上述当前文档。

## 5. 每轮执行步骤

### A. 开工时建立影响清单

在任务说明、Issue 或 PR 描述写下：受影响模块、稳定接口、API/schema/wire contract 风险、
是否涉及数据模型或 ADR、以及计划验证方式。先读取矩阵对应的当前文档和模块 README，
不要从历史计划推导现状。开始实现前运行一次 `make docs-check`，确认不是在既有清单漂移上
继续开发。

### B. 实现中记录事实，而非记录过程

当接口、迁移或用户流程最终落定时，记录以下最小信息：

- 谁拥有这个概念和写入权；
- 调用者通过什么稳定入口消费它；
- 哪些状态、隔离、授权或回滚约束不能被绕过；
- 哪些测试或命令能证明该描述仍然正确。

这些信息应进入上表指定的权威文档；调研过程、备选方案和一次性排障放入 Issue、PR、
审计或归档，不污染当前设计。

### C. 收尾前做一次“代码到文档”的对照

以实际 diff、模块 README、`contracts.py` / `facade.py`、路由、ORM 和 migration 为输入，
逐项回答：

1. 是否新增或移除了公开能力、模块依赖或用户路径？
2. 是否改变了数据库事实源、唯一性、`novel_id` 隔离、状态/采用或回滚语义？
3. 是否让已有文档的文件名、表名、接口名、模块数量或流程描述失真？
4. 哪份权威文档应更新，哪份历史文档只需归档或保持不动？

先运行：

```bash
make docs-check BASE_REF=origin/main
```

脚本列出的文档是**必查面**，不是强制改写面。如果答案均为“否”，在 PR 模板勾选“已逐项
核对未更新文档，确认无当前架构影响”并写出具体原因；不要为了凑更新而改写文档。只写
“N/A”或不提供证据不能绕过门禁。

### D. 与测试一同验证

至少执行：

```bash
make docs-check BASE_REF=origin/main
git diff --check
rg -n "<已移除模块或旧术语>" docs CONTEXT.md backend/modules
```

再按改动运行受影响模块测试和 lint。涉及 schema 时，将 Alembic head、模型注册和对应测试
作为证据；涉及 API/wire 时，将 API 或前端测试作为证据；涉及 Prompt 时运行
`make prompt-contracts`（若该契约系统覆盖本次变更）。不要把“文档已写”当作实现正确的证据。
用户可见的检索或生成能力若另有离线准入评测，还应记录数据集 hash、阈值和实际覆盖范围；
确定性检索／引用门禁不能被表述为对生成内容质量的人工验收。
`make docs-check` 已自动验证 Draw.io XML、重复 ID、edge endpoint 和业务模块覆盖；修改图源
时仍需使用 Draw.io 结构校验/视觉预览确认无重叠、裁切和错误箭头，并核对 HTML 预览同步。

### E. 合并后的轻量复核

PR CI 和 `main` push 都运行完整性门禁。合并或一批 PR 落地后，由该轮负责人只做一次轻量
复核：确认差异门禁没有被无依据豁免，架构图视觉仍正确。发现跨 PR 漂移时，立即建立一个
范围明确的文档修复项并标注 owner；不得把未完成的当前文档修复藏进长期 backlog。

## 6. PR / 开发轮记录模板

在 PR 描述或开发轮收尾说明中添加以下片段：

```md
### 文档影响
- 受影响模块：...
- 稳定接口 / API / schema / wire 风险：无 / ...
- 已更新的当前文档：...
- 未更新原因：无影响 / 历史记录不回写 / ...
- 验证：`make docs-check BASE_REF=origin/main`；测试命令；`git diff --check`
```

仓库 `.github/pull_request_template.md` 还提供机器可读复选项。差异门禁列出的文档未全部
修改时，必须勾选无影响核对项并填写 `无影响说明`；脚本从 PR event 读取这两项。变更已经
改变当前用户语义或稳定契约时，不能用无影响说明跳过更新，也不能带着缺口合并。

## 7. 维护责任边界

- **改动模块的开发者**：维护该模块 README、受影响测试和矩阵指定的当前文档。
- **跨模块改动的负责人**：维护 `docs/00_整体设计.md`、`CONTEXT.md`、数据库设计和架构图中
  受影响的部分，并协调各模块说明。
- **评审者**：以实际 diff 对照影响矩阵，核实无影响说明是否逐项成立，拒绝“公共行为已变、
  文档以后再补”的交付；机器门禁通过不等于语义准确。
- **合并负责人**：确认本轮文档闭环和 CI 通过，不把历史计划误改为当前设计。

## 8. 本地与 CI 入口

```bash
make docs-check
make docs-check BASE_REF=origin/main
pytest backend/tests/unit/test_architecture_docs.py -q
```

GitHub Actions 的 `Architecture docs` workflow 在每个 PR 运行完整性与差异影响门禁，在
`main` push 运行完整性门禁。`make test-ci` 也包含完整性门禁，保证常规本地质量检查不会
绕过文档清单。

本流程是 `AGENTS.md` 中“公共契约/数据模型/跨模块调用变化必须同步文档”规则的操作化说明；
Claude Code 通过 `CLAUDE.md` 导入同一规则。安全、隔离、用户确认和模块边界仍以该共享约束
及当前代码为准。
