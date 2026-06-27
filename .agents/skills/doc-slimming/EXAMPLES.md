# 文档精简 — 案例

## 案例 1：AGENTS.md 与 CLAUDE.md 高度重复

### 精简前状态

```
AGENTS.md (85 行)          CLAUDE.md (100 行)
├── Essential commands     ├── Essential commands      ← 重复
├── Architecture           ├── Architecture            ← 重复
├── Domain conventions     ├── Domain conventions      ← 重复
├── Testing                ├── Testing                 ← 重复
├── Toolchain quirks       ├── Toolchain quirks        ← 重复
├── Naming                 ├── Naming                  ← 重复
└── Meta                   ├── Agent skills
                           └── Meta
```

**问题**：两份文档约 95% 文本相同，职责完全重叠。新 AI 不清楚读哪份。

### 决策

分拆为两份职责明确的文档：

- **AGENTS.md**：Agent 协作体系（多 Agent 如何一起工作）
- **CLAUDE.md**：Claude 个体开发参考（单个 Agent 如何开发）

### 处理

| 内容块 | 去向 | 原因 |
|--------|------|------|
| Essential commands | CLAUDE.md | 开发命令属于开发参考 |
| Architecture | CLAUDE.md | 架构约束属于开发参考 |
| Domain conventions | CLAUDE.md | 核心保留，已存在于 development-guide.md 的删除 |
| Testing | CLAUDE.md（精简） | 保留要点，详细规范在 testing-guide.md |
| Toolchain quirks | CLAUDE.md | 工具链属于开发参考 |
| Naming | CLAUDE.md | 命名约定属于开发参考 |
| Agent skills | 分散到 CLAUDE.md + AGENTS.md | 工作流归 CLAUDE.md，协作归 AGENTS.md |

### 精简后状态

```
AGENTS.md (326 行)              CLAUDE.md (206 行)
├── 1. Agent 体系               ├── Claude 的角色定位
│   ├── 编码 Agent 工作模式      ├── 开发流程
│   ├── 创作 Agent 工作模式      │   ├── 修改代码前
│   └── Skills 生态             │   ├── 修改代码后
├── 2. Agent 职责边界            │   └── 合并前 Checklist
│   ├── 能做什么                 ├── 高优先级原则 (P0/P1)
│   ├── 不能做什么 (四级禁止)     ├── Spec 冲突处理
│   └── 创作 Agent 边界          ├── 架构约束
├── 3. Agent 协作协议            ├── 关键领域约定
│   ├── 并行开发隔离             ├── 测试
│   ├── 启动前检查               ├── 工具链
│   ├── 文档同步协议             ├── 命名约定
│   ├── Issue 流转协议           ├── 常用命令
│   └── 知识传递                 ├── Skills 参考
├── 4. 冲突解决                  └── Meta
│   ├── 优先级链条
│   ├── 代码冲突
│   ├── 文档冲突
│   └── Spec 冲突
├── 5. Loop 终止条件
├── 6. 读取顺序
├── 7. 常见协作场景
└── 8. Meta
```

**重复率**：95% → ~5%（仅禁止项同步）

---

## 案例 2：删除历史演进信息

### 精简前

```markdown
**8 active backend modules**: `project`, `imports`, `world`, `memory`,
`outline`, `rag`, `context`, `writing`. Removed: `geo`, `review`, `character`,
`timeline`. Character lives in `modules/world`.
```

### 分析

"Removed" 列出的是历史信息。新 AI 不需要知道曾经有过哪些模块。

### 精简后

```markdown
**8 个活跃模块**: `project`, `imports`, `world`, `memory`, `outline`,
`rag`, `context`, `writing`。Character 功能合并到 `modules/world`。
```

只保留对理解当前架构必要的信息。

---

## 案例 3：合并零散禁止项为分级清单

### 精简前

文档中散落各处的禁止项：

```
- 不跨模块 import models.py
- 不在 API 层写复杂业务逻辑
- 不对用户内容使用 innerHTML
- 不 eval LLM 输出
- 不硬编码 API Key
- 不跨 novel_id 读写
- 不直接 AI 输出写入正史
- 不硬 DELETE
- 不上传非白名单文件
- 不绕过二次确认
- 不跳过测试直接合并
- 不提交 .env
```

### 精简后

按层级归类：

```
**架构级禁止**：
- 不引入 Redis、Celery、前端框架、TypeScript、mypy

**代码级禁止**：
- 不跨模块 import models/repositories/services
- 不在 API/facade 层写复杂业务逻辑
- 不使用 innerHTML（必须 textContent 或 esc()）
- 不 eval/exec LLM 输出
- 不硬编码 API Key

**数据级禁止**：
- 不跨 novel_id 读写
- 不 AI 输出直接进正史
- 不硬 DELETE
- 不上传非白名单文件

**操作级禁止**：
- 不绕过二次确认
- 不跳过测试合并
- 不提交 .env
```

零散的 12 条禁止项 → 4 级分类的规则组。新 AI 按层级快速定位。

---

## 案例 4：多个示例总结为一个模式

### 精简前

```
- 命名示例：userService 是错的，用 user_service
- 命名示例：API_KEY 是错的，用 api_key
- 命名示例：getUser 是错的，用 get_user
```

### 精简后

```
| Python enum 成员 | `lowercase`（StrEnum 成员名 = DB 值） |
```

3 个命名示例 → 1 条命名规则。规则本身已足以指导所有命名场景。

---

## 案例 5：为 AGENTS.md 补充缺失的关键问题

### 精简前

旧版 AGENTS.md 没有回答的问题：
- ❌ Agent 体系是什么？（只有一行项目描述）
- ❌ 冲突如何解决？（完全没有）
- ❌ Loop 如何终止？（完全没有）
- ✅ 什么事情绝对不能做？（有，但散落在 Domain conventions 中）

### 新增内容

| 新增章节 | 内容来源 |
|----------|----------|
| Agent 体系 | 从 docs/agents/ 和 CLAUDE.md 的 Agent skills 节提炼 |
| 冲突解决（4.1-4.4） | 从开发经验中抽象出优先级链条和处理流程 |
| Loop 终止（5.1-5.4） | 新定义的四种终止条件 |
| 常见协作场景（第 7 章） | 归纳实际工作中遇到的 4 种模式 |

### 原则

补充内容不是从零编造，而是从已有文档、开发经验和隐含规则中**显式化**。新 AI 不需要通过试错来发现这些规则。
