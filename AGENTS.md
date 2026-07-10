# AGENTS.md

AI 长篇小说结构化创作引擎 v2.0 — 多 Agent 协作开发规范。

**本文档定位**：面向所有参与本项目的 AI 编码 Agent（Claude Code、Codex CLI 等），定义 Agent 之间的协作体系、职责边界、冲突解决与终止条件。

**互补文档**：
- `CLAUDE.md` — Claude Code 专用开发参考（架构、流程、命名）
- `development-guide.md` — 完整开发命令与架构说明
- `testing-guide.md` — 测试规范与 Review 分级
- `docs/agents/` — Agent 操作细节（issue 管理、triage 标签、文档消费）

---

## 1. Agent 体系

本项目区分编码 Agent、运行时 LLM 工作流与可选的外部自动化：

| 类型 | 实例 | 职责 |
|------|------|------|
| **编码 Agent** | 任意遵守本文件的编码工具 | 功能开发、Bug 修复、代码审查、文档同步 |
| **运行时 LLM 工作流** | 受控结构化 LLM step | 生成、抽取、切分；由业务工作流编排 |
| **外部自动化** | CI、Issue/PR 工具（如已配置） | 可选的验证、协作与文档辅助 |

**关键约束**：项目不实现自治或多 Agent 运行时。运行时允许有超时、预算、schema guard、日志和明确权限级别的受控 LLM step，但不得自主选工具、跨模块编排业务或绕过用户确认。编码 Agent 是项目外部工具；其产品特性和内置流程不构成仓库契约。

### 1.1 编码 Agent 的工作模式

```
用户指令 → Agent 读取本文档 + CLAUDE.md → 理解约束 → 执行任务 → 遵守终止条件
```

所有编码 Agent 在开始任何工作前，必须读取：
1. 本文档 — 理解协作规则与禁止事项
2. `CLAUDE.md` — 理解架构与开发流程
3. 目标模块的稳定接口说明（`contracts.py` / `facade.py` / DI 注册说明，如存在）

非平凡计划必须说明受影响模块、稳定接口、API/schema/wire contract 风险、所需用户确认或 ADR，以及验证方式。是否使用子代理、计划模式或其他运行时能力由当前编码工具决定，不能取代这项检查。

### 1.2 运行时 LLM 工作流

- 结构化 Prompt、调用方和契约清单以 `docs/prompts/Prompt体系设计.md` 为准；不要在本文件固定 Prompt 数量或文件名。
- LLM 输出默认进入作者可见的“待处理”建议或临时预览；底层可继续用 `candidate` / `proposal` 兼容表达。只有用户明确授权启动的自动流水线，才可按领域规则写入派生或已采用数据，并且必须保留来源、workflow、可编辑/可回滚标记与测试。
- LLM 输出必须经过调用方 schema 校验；不允许用自主 loop、工具自主选择或未经确认的写操作代替确定性业务编排。

### 1.3 工具与 Skill

编码工具可使用当前运行时提供的 Skill、自动化或协作能力，但可用性、名称和内部工作流不属于仓库规范。它们不得覆盖用户指令、本文档硬约束、模块稳定接口或测试门禁。

---

## 2. Agent 职责边界

### 2.1 编码 Agent 能做什么

- 读写项目代码（Python/FastAPI + vanilla JS）
- 运行测试、lint、格式化
- 创建/修改模块（遵循模块结构规范）
- 同步受影响的权威设计文档与测试
- 管理 Git 分支、提交、PR
- 管理 GitHub Issues（triage、标签、关闭）
- 读取 `docs/` 下的设计文档和 ADR
- 创建/更新模块 CLAUDE.md（记录模块级禁止事项）

### 2.2 编码 Agent 不能做什么

**架构级约束**：
- 当前默认栈：FastAPI + PostgreSQL async task queue + vanilla JS。偏离默认栈必须先由用户明确确认或写入 ADR。
- 未经用户明确要求或 ADR，不引入新的运行时基础设施、前端技术栈、数据库/队列/向量存储或强制类型检查体系。
- 技术栈和目录结构是默认路径，不是永久禁令；真正不可放松的是 novel_id 隔离、schema 校验、API Key 安全、危险操作确认、模块稳定接口和可验证性。

**代码级禁止**：
- 生产业务代码不跨模块 import 其他模块的 `models.py` / `repositories.py` / `services.py`；跨模块调用只通过 `contracts.py` / `facade.py` / DI port。
- 例外：本模块内部测试可测试本模块内部实现；测试 fixture / Alembic / ORM metadata 注册可 import 模型；应用组合根（`app.main` / worker startup）可为路由、任务和 DI 注册导入实现，但不得在组合根写业务判断。
- 不在 API 层或 facade 层写复杂业务逻辑；facade 只能做参数适配、稳定返回形状和委托。非平凡编排应下沉到拥有领域概念的模块实现，并通过该模块接口测试。
- 不把未转义的用户/AI/API 动态内容写入 `innerHTML`；静态模板或经 `esc()` 处理的动态内容允许
- 不 `eval` / `exec` LLM 输出
- 不硬编码 API Key，不将 Key 写入日志或返回前端

**数据级禁止**：
- 不跨 novel_id 读写数据
- 不在无用户授权的情况下将 AI 输出直接写入已采用资产。普通流程是待处理建议/预览 → 用户采用 → 当前有效资产；内部可保留 `candidate` / `proposal` → `canonical` 兼容状态。用户明确批量授权的自动流水线可直接写入领域允许的派生或已采用资产，但必须持久化授权范围、来源、workflow、可编辑/可回滚标记，并有测试覆盖；冲突、低置信和无法消歧结果仍进入待处理。
- 业务运行时不默认硬 DELETE 已采用对象（优先使用历史状态；项目永久删除除外）
- 不上传非白名单格式文件（仅 `.txt .epub .html .htm .mobi .azw3`，≤50MB）
- 不绕过 Pydantic schema 校验直接入库

**操作级禁止**：
- 不绕过二次确认执行合并/删除/废弃操作
- 不跳过测试直接合并（"不跑受影响模块测试不合并"）
- 不提交 `.env` 文件
- 不在未理解模块边界的情况下修改共享层（`core/`、`shared/`、`infrastructure/`）

**Demo 阶段数据库规则**：
- 当前项目处于 demo 阶段，数据库 schema 重构不要求保留历史数据迁移路径。
- 修改表结构时，可以直接删除并重建开发数据库；同步更新 ORM、schema、测试和文档即可。
- 该规则只放宽开发期数据保留要求，不放宽 novel_id 隔离、Pydantic 校验、API Key 安全和用户操作确认。

### 2.3 架构约束质量标准

好的约束应该让系统更安全、更可演进，而不是把当前实现偶然性冻结成永久规则：

- **保护长期不变量**：novel_id 隔离、用户确认语义、schema 校验、安全规则、模块接口和测试门禁优先于风格偏好。
- **保留清晰逃生口**：默认栈或目录规则需要改变时，走用户确认或 ADR；ADR 记录替代方案、接受成本、验证方式和回滚方式。
- **避免浅接口**：新增 `facade.py` / `contracts.py` / DI port 前先做 deletion test。若删除后复杂度不会回到多个调用方，它可能只是 pass-through；只有能集中行为或存在明确变体时才引入 seam。
- **一个规则一个权威来源**：`AGENTS.md` 放硬约束和协作协议；`CLAUDE.md` / `development-guide.md` / `testing-guide.md` 只放执行入口、例外和测试细则，避免重复漂移。

### 2.4 创作 Agent 的边界

- 实体抽取 ≠ NER：只抽取长期创作资产，不抽取路人/普通道具/代词/一次性场景
- 别名不创建新对象：标记 `alias_of_existing`
- 不在缺少用户确认或已持久化流水线授权时自动合并已采用对象
- 宁可少抽，不让低质量对象污染当前有效资产

---

## 3. Agent 协作协议

### 3.1 并行开发隔离

当多个编码 Agent 同时工作时，使用 Git Worktree 隔离：

```
每个独立任务 → 独立 worktree / 分支 → 独立开发 → 独立 PR
```

- Agent A 修改 `modules/world/` 不影响 Agent B 修改 `modules/outline/`
- 共享层（`core/`、`shared/`、`infrastructure/`）的修改需在 PR 中显式标注冲突风险
- 合并前必须通过受影响模块的测试
- 两个 Agent 不应同时修改同一模块 — 如无法避免，后开始的 Agent 应等待前者 PR 合并后 rebase

### 3.2 并行开发启动前检查

当任务涉及分支创建、并行开发、PR 或 Issue 协调时，Agent 启动前检查：
1. 尽量执行 `git fetch && git log origin/main..HEAD --oneline` — 了解当前分支状态；若网络/权限不可用，记录限制并使用本地 refs 判断
2. `git branch -r` — 检查是否有其他 Agent 的活跃分支
3. `gh issue list --label ready-for-agent` — 确认没有正在进行的冲突任务；若 GitHub 不可用，说明未检查远端 Issue
4. 如目标模块已被其他 Agent 修改 → 协调优先级，或选择其他模块

本地小修、静态代码审查、文档审查或无需分支/Issue 协调的任务，不强制执行远端 fetch / gh 检查。

### 3.3 文档同步协议

- 公共契约、用户可见行为、数据模型或跨模块调用变化时，必须在提交/评审前同步更新权威文档和受影响测试；纯内部重排不强制更新设计文档
- CI、git hook 或外部 Skill 可以辅助检查，但没有已验证的本地自动化时不得假定 `git push` 会完成同步。
- 文档更新不属于 "额外工作" — 是与代码修改同等的交付物

### 3.4 Issue 流转协议

```
needs-triage → needs-info（等回复）/ ready-for-agent（可执行）/ ready-for-human（需人工）
     ↓
ready-for-agent → Agent 认领 → 实现 → PR → 关闭
ready-for-human → 人工处理
wontfix → 关闭（不处理）
```

- Issue 和 PRD 以 GitHub Issues 形式管理
- 使用 `gh` CLI 进行所有操作
- Triage 标签映射见 `docs/agents/triage-labels.md`
- Agent 完成实现后，在 Issue 中评论 PR 链接和测试结果摘要

### 3.5 Agent 间知识传递

当一个 Agent 需要将上下文传递给另一个 Agent：

- **常规传递**：通过 Issue 评论和 PR 描述 — 下一个 Agent 读取 Issue 即可获取完整上下文
- **紧急传递**：在 Issue 上添加 `needs-info` 标签并 @提及 下一个 Agent
- **归档传递**：重大设计决策写入 ADR（`docs/adr/`），不依赖口头传递
- **禁止**：不在代码注释中写 "用于 Agent X" 或 "Agent Y 需要注意" — 这些属于 Issue/PR 描述

---

## 4. 冲突解决

### 4.1 代码冲突优先级

级别从高到低：

1. **用户显式指令** — 最高优先级，但不能要求绕过 API Key 安全、novel_id 隔离、生产/真实数据保护或破坏性 Git 操作二次确认
2. **本文档 + CLAUDE.md 的硬约束** — 安全、数据、模块接口和协作约束不可静默绕过；技术栈/目录形状变化需用户确认或 ADR
3. **ADRs 记录的设计决策** — 不得静默覆盖，推翻需走 ADR 更新流程
4. **模块稳定接口** — `contracts.py` / `facade.py` / DI port 等跨模块权威契约
5. **Spec 文件中的显式需求** — 实现必须满足
6. **Agent 自行判断** — 最低优先级，需在 PR 中记录决策理由

### 4.2 代码冲突处理流程

当 Agent 的修改与现有代码冲突时：

1. **Git 合并冲突** → 读取冲突双方的代码，理解各自意图，选择保留更符合当前规则的一方
2. **逻辑冲突（非 Git 冲突）** → 检查冲突双方的 PR 描述和关联 Issue，后提交者负责兼容
3. **无法判断孰优孰劣** → 在 Issue 中标记 `needs-triage`，列出两个方案及优劣，等待用户裁定

### 4.3 文档冲突

当多个 Agent 的文档修改冲突：

1. 后提交的 Agent 负责解决冲突
2. 如有歧义 → 回退到本文档 + `CLAUDE.md` 的规则
3. 如规则本身有歧义 → 标记为 `needs-triage` Issue，不自行裁定
4. 文档冲突解决方案必须记录在合并 commit 的 message 中

### 4.4 Spec 冲突

当实现与 Spec 冲突：

1. **Spec 显式需求 vs 实现细节** → Spec 优先，在 PR 中说明偏差
2. **Spec 内部矛盾** → 停止实现，标记 Issue 标注矛盾点，等待用户澄清
3. **Spec 未覆盖的实现选择** → Agent 自行判断，在 PR 描述中记录决策理由
4. **Spec vs ADR** → ADR 优先（ADR 记录已验证的设计决策）

---

## 5. Loop 终止条件

Agent 必须在以下条件之一满足时停止，不得无限循环：

### 5.1 任务完成

- 所有指定的功能已实现且验证通过
- 所有受影响模块的测试通过
- 适用时 Lint 检查通过
- 文档已同步

### 5.2 阻塞条件

- 需要用户输入/确认但用户不在（等待，不猜测意图）
- 发现 Spec 矛盾无法自行解决
- 遇到本文档明确标记为 "需人工" 的操作
- 测试失败且已尝试 3 次修复仍未通过（停止，报告根因分析，等待指令）
- 依赖的外部服务不可用（不无限重试，最多 3 次后退避）

### 5.3 安全停止（立即停止，无例外）

- 检测到生产/用户真实数据丢失风险；demo 开发库 schema 重构可按上文规则直接重建
- 检测到跨 novel_id 的数据泄漏风险
- 检测到安全规则被绕过（API Key 打印、innerHTML 注入）
- 检测到破坏性 Git 操作（force push 到 main、reset --hard 未确认）

### 5.4 超范围停止

- 用户指令超出本文档定义的 Agent 能力边界
- 任务需要引入未经用户确认或 ADR 批准的架构/技术
- 任务规模和复杂度超出单次会话合理范围（拆分为多个 Issue）
- Agent 发现自己对当前模块/领域缺乏足够上下文（报告，请求更多信息）

---

## 6. 编码 Agent 读取顺序

每次新会话开始时，按以下顺序读取：

1. **本文档 (AGENTS.md)** — 协作规则与禁止事项（最高优先级）
2. **`CLAUDE.md`** — 开发入口、架构导航与命名约定
3. **目标模块** — `README.md` → 稳定接口文件（如存在）→ 测试；只有修改实现或诊断内部 Bug 时再读 `models.py` / `repositories.py` / `services.py`
4. **按任务补充** — 实现任务读 `development-guide.md` / `testing-guide.md` 的相关章节；架构或数据库任务读 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、相关 ADR 和迁移。

优先在目标模块内建立上下文。架构审查、安全审查、共享层修改、DI/路由注册、跨模块调用或测试失败需要定位调用方时，应扩大到相关模块或全仓库搜索。

### 6.1 文档消费策略

- **首次接触项目**：读 1→3，再按任务读第 4 项。
- **已熟悉项目**：重读 1+2，补读受影响模块和相关规范。
- **只改一个模块**：读 1+3 + 相关实现/测试规则。
- **跨模块修改**：读 1+2 + 所有受影响模块的稳定接口
- **架构/安全审查**：读 1+2 + `CONTEXT.md` + 相关 ADR，并允许全仓库搜索验证约束是否仍准确

---

## 7. 常见协作场景

### 7.1 单 Agent 独立任务

```
用户分配 Issue → Agent 创建分支 → 读取文档 → 实现 → 测试 → PR → 等待审查 → 合并
```

### 7.2 多 Agent 并行任务

```
用户分配 Issue A → Agent A 在 modules/world/ → 分支 feature/world-xxx
用户分配 Issue B → Agent B 在 modules/outline/ → 分支 feature/outline-xxx
各自独立开发 → 各自 PR → 互不影响 → 哪个先合并另一个 rebase 即可
```

### 7.3 多 Agent 串行任务

```
Agent A 修改 contracts.py → PR 合并 → Agent B 基于新 contracts 修改 facade.py → PR 合并
```

- 串行任务的依赖关系必须在 Issue 中明确标注
- 后执行的 Agent 等待前置 PR 合并后再开始

### 7.4 Agent + 人工混合

```
Agent 实现核心逻辑 → PR → 人工 Code Review → Agent 根据 Review 修改 → 人工确认 → 合并
```

- Agent 收到 Review 意见后：先理解，再修改。不盲目执行。
- Review 意见与本文档规则冲突时：以本文档规则为准，在 PR 评论中引用具体规则。

---

## 8. Meta

- **本文档 vs CLAUDE.md**：本文档定义硬约束和协作规则，CLAUDE.md 只补充开发入口和架构导航。
- **本文档 vs AI开发规则.md**：本文档是权威的 Agent 行为规范。AI开发规则.md 是设计说明，不直接约束 Agent 运行时行为。
- **优先级链条**：用户指令 > 本文档 > CLAUDE.md > 模块 CLAUDE.md > Agent 默认行为
- 本文档不承载项目结构、实施计划、命令说明或长篇设计说明。此类内容见 `development-guide.md`。
