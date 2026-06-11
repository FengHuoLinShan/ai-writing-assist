---
name: doc-maintenance
description: After each development cycle, evaluate whether changes should be persisted to design docs (Spec/Guide/Archive). Judges by "will this affect future development decisions?" — defaults to NOT writing. Use when user says "update docs", "sync documentation", "maintain docs", or after completing a feature/bugfix/refactor and wanting to persist learnings.
---

# 文档维护

你是在 Spec-First 模式下工作的 Documentation Maintainer。设计文档是系统的 Single Source of Truth。

## 核心原则

- 文档记录的是**长期有效的决策**，不是本轮开发发生了什么
- **默认不写入**。只有未来 AI 仍需知道的信息才值得保留
- 优先修改已有内容，禁止"追加式写文档"

## 快速检查（30 秒判断）

问自己三个问题：

1. 这个变化会影响未来 AI 的开发决策吗？
2. 如果只看文档不看代码，AI 会因此做出错误判断吗？
3. 六个月后的新 AI 仍然需要知道这个吗？

**三个全否 → 不更新。任何一个 YES → 进入完整流程。**

## 工作流程

Step 1. **收集变化** — 新增/删除功能、行为变更、架构调整、数据模型变化、高代价经验

Step 2. **判断是否写入** — 对照 [REFERENCE.md](REFERENCE.md) 的准入/禁止清单

Step 3. **定位文档** — 按职责边界写入：

| 层级 | 文档 | 记录内容 |
|------|------|----------|
| Spec | `docs/` 设计文档 | 系统应该如何工作 |
| Guide | `AGENTS.md` `CLAUDE.md` | AI 应如何工作 |
| Archive | `docs/adr/` | 历史决策记录 |

Step 4. **最小修改** — 优先修改已有内容，不新增章节，消除重复

Step 5. **输出建议** — 对每个拟修改文档，按模板输出更新建议（见 REFERENCE.md）

Step 6. **一致性检查** — 确认不与现有 Spec/AGENTS.md/CLAUDE.md 冲突，无重复和过时信息

## 验收标准

- 能准确描述当前系统
- 新 AI 无需历史记录即可接手
- 文档之间职责清晰，无重复
- 不依赖隐含上下文

完整判断清单和输出模板见 [REFERENCE.md](REFERENCE.md)。实际案例见 [EXAMPLES.md](EXAMPLES.md)。
