# structure-docs-update

> 已归档（2026-09-30）：依赖本机 ~/.claude/skills 私有 hook，非仓库共享流程，当前文档维护以 docs/architecture/documentation-maintenance.md 与 make docs-check 为准。

Git push 后自动同步所有设计文档。规则详见 `~/.claude/skills/structure-docs-update/SKILL.md`。

## 触发方式

- **自动**：`git push` 后 hook 自动执行 `/structure-docs-update`
- **手动**：任何时候输入 `/structure-docs-update`
