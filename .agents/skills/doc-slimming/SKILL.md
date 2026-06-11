---
name: doc-slimming
description: Slim and refine project documentation by removing stale content, merging duplicates, and preserving only decision-guiding knowledge. Acts as Documentation Architect — the goal is high signal-to-noise ratio, not completeness. Use when user says "slim docs", "精简文档", "refactor docs", "clean up documentation", or when design docs have grown bloated from continuous auto-updates by multiple AI agents.
---

# 文档精简

你是 Documentation Architect。项目长期由多个 AI Agent 协作开发，文档会持续膨胀。你的任务不是补充内容，而是持续"瘦身"和"提炼"，保持高信噪比。

## 核心哲学

> 文档不是知识仓库，而是决策操作系统。删除不能指导未来行动的信息。优先保留规则，而非历史。

## 快速判断（三问）

在开始精简前，对每一段内容问：

1. 这段内容会影响未来 AI 的开发决策吗？
2. 删除它会导致新 AI 做出错误判断吗？
3. 它是规则/约束，还是历史记录/过程描述？

**只有前两问任一 YES、且第三问是"规则/约束"时 → 保留。其余 → 删除或合并。**

## 工作流程

### Step 1：三级分类

对每段内容打标签：

| 标签 | 含义 | 行动 |
|------|------|------|
| **KEEP** | 影响未来决策的原则、约束、流程 | 保留 |
| **MERGE** | 与其他段落重复或可抽象的规则 | 合并后保留一个版本 |
| **DELETE** | 历史记录、过程描述、已过时信息 | 删除 |

### Step 2：执行精简

按保留→合并→删除的顺序操作。完整原则见 [REFERENCE.md](REFERENCE.md)。

### Step 3：重构目录

删除后重新审视目录结构 — 合并短章节、消除单一段落章节、确保逻辑流顺畅。

### Step 4：输出分析

对每个处理的文档，输出精简摘要（保留/删除/合并内容 + 新目录结构）。模板见 [REFERENCE.md](REFERENCE.md)。

### Step 5：最终验证

用终极问题验证结果：

> "如果未来只能保留这一版文档，新的 AI 是否仍然能够正确接手项目？"

否定 → 继续重构。肯定 → 停止。

## 重点处理文档

- `AGENTS.md` — 目标 300-500 行，回答 Agent 体系/职责/协作/冲突/终止/禁止
- `CLAUDE.md` — 目标 200-400 行，回答角色定位/开发流程/修改前后/高优原则/Spec 冲突

完整原则、输出模板和边界案例见 [REFERENCE.md](REFERENCE.md)。实战案例见 [EXAMPLES.md](EXAMPLES.md)。
