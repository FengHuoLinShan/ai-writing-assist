# structure-docs-update

Git push 后自动同步所有设计文档。详见 `~/.claude/skills/structure-docs-update/SKILL.md`。

## 触发方式

- **自动**：`git push` 后 hook 自动执行 `/structure-docs-update`
- **手动**：任何时候输入 `/structure-docs-update`

## 对照规则

| 代码 | 文档 |
|------|------|
| facade/contracts/services 签名 | docs/modules/*.md |
| modules/ 目录结构 | docs/00_整体设计.md |
| models.py 表结构 | docs/01_数据库设计.md |
| api.py 路由 | docs/modules/*.md API 节 |

只更新文档，不修改代码。
