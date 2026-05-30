# CLAUDE.md

## Prohibitions (不做xx)

### 架构与模块
- 不跨模块直接导入 `models.py` / `repositories.py` / `services.py`，跨模块只能通过 `contracts.py` 和 `facade.py`
- API 层不写复杂业务逻辑，facade 不写复杂业务逻辑
- 不构建复杂多 Agent 系统；核心创作 Prompt 保持 4 个，工具型抽取 Prompt 不扩展成 Agent 体系
- 不以全文正文生成为核心目标
- 不主动实现 Neo4j / Qdrant / PostGIS / GraphRAG 社区摘要 / 多用户权限 / 商业功能，除非用户明确要求
- 场景卡不拆独立表，放在 `chapter_cards.scene_cards` JSONB
- 时间线不做复杂相对时间推理、日历系统、自动历史推演
- 不把项目结构、目录设计、里程碑、实施计划写入根目录 `CLAUDE.md`；这些内容写入 `docs/00_整体设计.md` 和 `docs/项目进度.md`
- 不把开发命令、测试策略、Review 分级写入根目录 `CLAUDE.md`；这些内容写入 `development-guide.md` 和 `testing-guide.md`

### 文档维护
- git push 后自动执行 `/structure-docs-update` 同步所有设计文档
- 任何时候也可手动执行 `/structure-docs-update` 同步
- 不只更新 `CLAUDE.md` 而忘记同步 `AGENTS.md` 中等价的 Codex 禁止事项

### 数据与安全
- 导入管线全自动直写 canonical，实体和关系不经候选池审核；用户通过手动 CRUD 事后修正
- API 不允许跨 `novel_id` 读写数据
- 不拼接原始 SQL，使用 SQLAlchemy 参数绑定
- API Key 不写日志、不返回前端；`.env` 不提交仓库
- 文件上传不允许白名单外格式、超过 50MB、路径穿越
- 不 `eval` / `exec` LLM 输出
- 合并 / 删除 / 废弃操作不做无二次确认

### 实体抽取
- 实体抽取不是 NER，不抽取路人、普通道具、代词、一次性场景元素
- 别名不创建新对象，标记 `alias_of_existing`
- 不自动合并正史对象

### 前端
- UI 不暴露工程术语，显示“正史”而非 `canonical`
- 不使用富文本编辑器、复杂图谱可视化、专业地图编辑器
- 不引入重型 UI 组件库
- 用户 / AI 内容不通过 `innerHTML` 直接渲染，必须使用 `textContent` 或统一转义
- 不做无空状态提示、无操作确认、无错误提示的页面

### 测试
- 测试优先通过 facade + contracts 验证行为，而非直接 import 内部模块（repositories/services/models）
- 修改 `contracts.py` / `facade.py` / API / DB schema 后，不允许漏更新 README / 测试 / 调用方 / docs
- 不跑受影响模块测试不合并

## 命名规范

### 文件命名

| 范围 | 规范 | 说明 |
|---|---|---|
| Python 源文件 | `snake_case.py` | PEP 8 |
| JS 源文件 | `camelCase.js` | View 文件除外 |
| JS View 文件 | `PascalCaseView.js` | 匹配导出对象名 |
| JS 测试文件 | `*.test.js` | Vitest 单元测试 |
| JS E2E 文件 | `*.spec.js` | Playwright 惯例 |
| 根目录 md 文件 | `kebab-case.md` | 如 `development-guide.md` |
| 文档目录 | `NN_主题.md` 或 `主题.md` | 按需编号 |
| Alembic 迁移 | git-revision-hash 前缀 | Alembic 自动生成 |

### 代码命名

| 范围 | 规范 | 说明 |
|---|---|---|
| Python 类 | `PascalCase` | PEP 8 |
| Python 函数/变量 | `snake_case` | PEP 8 |
| Python 常量 | `SCREAMING_SNAKE_CASE` | PEP 8 |
| Python 枚举成员 | `lowercase` | StrEnum 成员名=DB值，保留与 DB 一致 |
| Python 模块级 logger | `logger` | 无下划线前缀：`logger = logging.getLogger(__name__)` |
| JS 函数/变量 | `camelCase` | |
| JS 私有方法 | `_camelCase` | 仅内部调用，外部通过公共方法调用 |

## 工作流

- 代码开发（新功能、bug 修复、重构）：调用 `/tdd` 技能，遵循 RED→GREEN→REFACTOR 循环
- 方案讨论、设计决策、需求澄清：调用 `/grill-with-docs` 技能，逐个深入直到达成共识

## Agent skills

### Structure docs update

Auto-sync design docs on git push. See `docs/skills/structure-docs-update.md`.

### Issue tracker

Issues and PRDs live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles use their default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. See `docs/agents/domain.md`.
