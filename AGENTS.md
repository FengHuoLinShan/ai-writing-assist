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

本项目由三类 Agent 协作运行：

| 类型 | 实例 | 职责 |
|------|------|------|
| **编码 Agent** | Claude Code, Codex CLI | 功能开发、Bug 修复、代码审查、文档同步 |
| **创作 Agent** | 4 核心创作 Prompt + 4 工具提取 Prompt | 小说结构化创作（实体、情节、记忆、上下文） |
| **自动化 Agent** | `/structure-docs-update`, Triage Bot | 文档同步、Issue 分类分流 |

**关键约束**：本项目不实现多 Agent 协同系统。创作侧的 "Agent" 是结构化 LLM 调用链，不是自治 Agent。编码 Agent 是外部工具，不是项目运行时的一部分。

### 1.1 编码 Agent 的工作模式

```
用户指令 → Agent 读取本文档 + CLAUDE.md → 理解约束 → 执行任务 → 遵守终止条件
```

所有编码 Agent 在开始任何工作前，必须读取：
1. 本文档 — 理解协作规则与禁止事项
2. `CLAUDE.md` — 理解架构与开发流程
3. 目标模块的稳定接口说明（`contracts.py` / `facade.py` / DI 注册说明，如存在）

### 1.2 创作 Agent 的工作模式

创作 Agent 是确定性的 Prompt 链，不是自治系统：
- **4 核心 Prompt**：实体抽取、情节生成、记忆提案、上下文编译
- **4 工具 Prompt**：结构化提取、去重检测、别名识别、场景切分
- **默认输出**：进入 candidate 状态，用户确认后入正史；深度导入等用户确认启动的自动流水线可直接写入 canonical，并保留可回滚/可编辑标记

### 1.3 Skills 生态

编码 Agent 通过 Skills 系统获取专项能力。Skills 是 Agent 的 "能力插件"，不是独立 Agent。

**编码流程 Skills**（定义如何工作）：
- `/tdd` — 测试驱动开发
- `/brainstorming` — 设计前需求澄清
- `/systematic-debugging` — Bug 诊断
- `/code-review` — 代码审查
- `/verification-before-completion` — 完成前验证

**项目管理 Skills**（定义如何协作）：
- `/triage` — Issue 状态机流转
- `/to-issues` — 计划拆分为 Issue
- `/to-prd` — 对话转为 PRD
- `/grill-with-docs` — 设计决策压力测试

**自动化 Skills**（事件驱动）：
- `/structure-docs-update` — git push 后自动同步文档
- `/gen-tests` — 为遗留代码补充测试

Skills 使用规则：
- 编码 Agent 执行任务时，优先检查是否有匹配的 Skill 可用
- Skill 的规则优先级高于 Agent 的默认行为，但低于用户显式指令
- Skill 之间不应产生循环调用

---

## 2. Agent 职责边界

### 2.1 编码 Agent 能做什么

- 读写项目代码（Python/FastAPI + vanilla JS）
- 运行测试、lint、格式化
- 创建/修改模块（遵循模块结构规范）
- 同步设计文档（通过 `/structure-docs-update`）
- 管理 Git 分支、提交、PR
- 管理 GitHub Issues（triage、标签、关闭）
- 读取 `docs/` 下的设计文档和 ADR
- 创建/更新模块 CLAUDE.md（记录模块级禁止事项）

### 2.2 编码 Agent 不能做什么

**架构级禁止**：
- 未经用户明确要求或 ADR，不引入新的运行时基础设施、前端技术栈、数据库/队列/向量存储或类型检查体系
- 当前默认：FastAPI + PostgreSQL async task queue + vanilla JS；偏离默认栈必须先记录决策理由

**代码级禁止**：
- 不跨模块 import `models.py` / `repositories.py` / `services.py`
- 不在 API 层或 facade 层写复杂业务逻辑
- 不把未转义的用户/AI/API 动态内容写入 `innerHTML`；静态模板或经 `esc()` 处理的动态内容允许
- 不 `eval` / `exec` LLM 输出
- 不硬编码 API Key，不将 Key 写入日志或返回前端

**数据级禁止**：
- 不跨 novel_id 读写数据
- 不在无用户授权的情况下将 AI 输出直接写入正史（默认 candidate → 用户确认 → canonical；深度导入等确认启动的流水线除外）
- 业务运行时不默认硬 DELETE 正史对象（优先使用 status 字段；项目永久删除除外）
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

### 2.3 创作 Agent 的边界

- 实体抽取 ≠ NER：只抽取长期创作资产，不抽取路人/普通道具/代词/一次性场景
- 别名不创建新对象：标记 `alias_of_existing`
- 不自动合并正史对象
- 宁可少抽，不让烂对象污染正史库

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

Agent 启动新任务前：
1. `git fetch && git log origin/main..HEAD --oneline` — 了解当前分支状态
2. `git branch -r` — 检查是否有其他 Agent 的活跃分支
3. `gh issue list --label ready-for-agent` — 确认没有正在进行的冲突任务
4. 如目标模块已被其他 Agent 修改 → 协调优先级，或选择其他模块

### 3.3 文档同步协议

```
git push → 自动触发 /structure-docs-update → 对比代码与设计文档 → 同步不一致内容
```

- 公共契约、用户可见行为、数据模型或跨模块调用变化时，必须同步更新权威文档和受影响测试；纯内部重排不强制更新设计文档
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

1. **用户显式指令** — 最高优先级，覆盖所有文档规则
2. **本文档 + CLAUDE.md 的禁止项** — 绝对约束，不可绕过
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
- Lint 检查通过
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
- 任务需要引入被明确禁止的架构/技术
- 任务规模和复杂度超出单次会话合理范围（拆分为多个 Issue）
- Agent 发现自己对当前模块/领域缺乏足够上下文（报告，请求更多信息）

---

## 6. 编码 Agent 读取顺序

每次新会话开始时，按以下顺序读取：

1. **本文档 (AGENTS.md)** — Agent 协作规则与禁止事项（最高优先级）
2. **`CLAUDE.md`** — 架构、流程、命名约定
3. **`development-guide.md`** — 命令参考与架构详解
4. **`testing-guide.md`** — 测试规范
5. **目标模块** — `README.md` → 稳定接口文件（如存在）→ `models.py` → `services.py`

不要在模块外进行全仓库搜索，优先在目标模块内完成开发。

### 6.1 文档消费策略

- **首次接触项目**：按 1→2→3→4 顺序完整阅读
- **已熟悉项目**：重读 1+2，跳读 3+4 的相关章节
- **只改一个模块**：读 1+2 + 目标模块的文件 5
- **跨模块修改**：读 1+2 + 所有受影响模块的稳定接口

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
