# AI 开发规则（Claude Code / Codex）

## 1. 指导文件分工

| 文件 | 职责 |
|------|------|
| 根目录 `CLAUDE.md` | 只记录“不能做什么” |
| 根目录 `AGENTS.md` | Codex 适配的“不能做什么”清单，原则上与 `CLAUDE.md` 同步 |
| 模块目录 `CLAUDE.md` | 只记录该模块的特殊禁止事项、风险陷阱和不可绕过的边界 |
| `development-guide.md` | 开发命令、模块结构、架构原则、工程规则 |
| `testing-guide.md` | 测试要求、Review 分级、安全测试清单 |
| `docs/00_整体设计.md` | 项目定位、分层架构、目录结构、模块职责、技术栈 |
| `docs/项目进度.md` | 里程碑状态、已交付内容、已知不足、后续维护项 |
| 模块 README / `docs/modules/*.md` | 单模块职责、表、API、facade、测试方式 |

根目录 `CLAUDE.md` / `AGENTS.md` 不承载项目结构、实施计划、命令说明或长篇设计说明。
这些内容按上表归档，避免指导文件互相复制后漂移。

## 2. 开发前读取顺序

本项目采用垂直模块化结构。进入模块开发时，优先读取：

1. 根目录 `CLAUDE.md` 或 `AGENTS.md` — 禁止事项
2. `development-guide.md` — 开发规则、命令、架构
3. `testing-guide.md` — 测试要求、Review 分级
4. 模块目录下的 `CLAUDE.md`（若有）和 `README.md`
5. `contracts.py` → `facade.py` → `models.py` → `services.py`

不要默认全仓库搜索，优先在模块内完成开发；涉及跨模块行为时再读相关模块的 `contracts.py` / `facade.py`。

## 3. 模块边界规则

**允许：**
- `modules/*` 导入 `core/` 和 `shared/`
- `modules/*` 导入 `infrastructure/llm/` 或 `infrastructure/tasks/`
- 模块 A 导入模块 B 的 `contracts.py` 和 `facade.py`

**禁止：**
- 模块 A 导入模块 B 的 `models.py` / `repositories.py` / `services.py`
- 模块 A 直接操作模块 B 的数据表
- API 层写复杂业务逻辑
- facade 内写复杂业务逻辑（facade 是薄层转发）

## 4. 数据与正史规则

- AI 生成内容默认不直接入正史，走 candidate / proposal → 用户确认 → canonical；用户确认启动的自动流水线可直接写入 canonical，并保留可编辑/可回滚标记。
- 所有 LLM 输出必须经过 Pydantic schema 校验。
- API 不允许跨 novel_id 读写数据。
- 当前处于 demo 阶段，数据库 schema 重构不要求保留旧数据迁移；可以直接删除并重建开发数据库。

## 5. 修改公共接口

如果修改 `contracts.py`、`facade.py`、API 路由、Pydantic schema、数据库表结构，必须同步更新：
- 模块 README
- 模块测试
- 所有调用方
- 文档（`docs/` 目录下对应文件）

## 6. 测试规则

- 每个模块自带 `tests/`。修改模块后至少运行该模块测试。
- 跨模块流程放在 `tests/integration/`。
- 使用 SQLite 内存引擎（`sqlite+aiosqlite:///:memory:`）。
- 每个 conftest 必须 import 所有 FK 依赖的模型。

## 7. 当前阶段禁止主动实现的复杂功能

除非用户明确要求，否则不要主动实现：多 Agent 协同系统、AI 自动生成完整正文、Neo4j、Qdrant、PostGIS、地图瓦片服务、复杂 GraphRAG 社区摘要、多用户权限系统、商业运营模块。

## 8. 代码风格

- 优先简单、可读、可测试
- 避免过度抽象
- 服务层只处理本模块业务
- 跨模块通过 facade
- Pydantic schema 明确输入输出
- 所有 LLM 输出必须校验

## 9. 实体抽取专门规则

- 实体抽取不是 NER — 只抽取长期创作资产，不抽取路人/普通道具/代词/一次性场景
- 别名不创建新对象，标记 `alias_of_existing`
- 不自动合并正史对象
- 宁可少抽，不让烂对象污染正史库

## 10. 安全规则

- API Key 从环境变量获取，不写日志，不返前端
- `.env` 不提交仓库
- 文件上传：白名单 `.txt .epub .html .htm .mobi .azw3`、50MB 上限、路径穿越防护
- 不 eval / exec LLM 输出
- 合并/删除/废弃操作需二次确认
