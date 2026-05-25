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
- 不把开发命令、测试策略、Review 分级写入根目录 `CLAUDE.md`；这些内容写入 `DEVELOPMENT_GUIDE.md` 和 `TESTING_GUIDE.md`

### 文档维护
- 不把根目录 `CLAUDE.md` 当作文档索引、开发指南或进度记录；它只维护禁止事项
- 不新增或修改根目录 `CLAUDE.md` 的结构设计、命令说明、测试流程、里程碑状态、模块职责正文
- 不只更新 `CLAUDE.md` 而忘记同步 `AGENTS.md` 中等价的 Codex 禁止事项，除非用户明确只维护 Claude
- 不在模块级 `CLAUDE.md` 写通用开发流程或完整模块说明；模块级 `CLAUDE.md` 只写该模块特殊禁令、风险陷阱和不可绕过的边界
- 不把项目结构、目录树、分层架构、技术栈写进 `docs/项目进度.md`；这些内容归 `docs/00_整体设计.md`
- 不把里程碑状态、完成情况、已知不足、后续维护项写进 `docs/00_整体设计.md`；这些内容归 `docs/项目进度.md`
- 不把开发命令、测试命令、Review 分级、测试夹具规范写进设计或进度文档；这些内容分别归 `DEVELOPMENT_GUIDE.md` 和 `TESTING_GUIDE.md`
- 不把历史计划 `DEVELOPMENT_PLAN.md` 当作当前设计入口；当前结构以 `docs/00_整体设计.md` 为准，当前进度以 `docs/项目进度.md` 为准
- 不复制同一段长规则到多个文档；需要复用时写清主文档位置并在其他文档做短引用
- 不修改 Prompt 数量、模块数量、目录结构、技术栈、里程碑状态而漏更新 `docs/README.md`、`docs/00_整体设计.md`、`docs/项目进度.md` 中的对应摘要
- 不新增模块或模块级指导文件而漏更新文档索引、整体设计中的模块列表、项目进度中的交付状态

### 数据与安全
- AI 输出绝不直接写入 canonical，必须经 candidate / proposal → review → 用户确认
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
- 修改 `contracts.py` / `facade.py` / API / DB schema 后，不允许漏更新 README / 测试 / 调用方 / docs
- 不跑受影响模块测试不合并

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles use their default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. See `docs/agents/domain.md`.
