# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Prohibitions (不做xx)

### 架构与模块
- 不跨模块直接导入 `models.py` / `repositories.py` / `services.py` — 只能通过 `contracts.py` 和 `facade.py`
- API 层不写复杂业务逻辑，facade 不写复杂业务逻辑
- 不构建复杂多 Agent 系统 — 只保留 4 个核心 Prompt
- 不以全文正文生成为核心目标
- 不主动实现：Neo4j / Qdrant / PostGIS / GraphRAG 社区摘要 / 多用户权限 / 商业功能（除非用户明确要求）
- 场景卡不拆独立表，放在 `chapter_cards.scene_cards` JSONB
- 时间线不做复杂相对时间推理、日历系统、自动历史推演

### 数据与安全
- AI 输出绝不直接写入 canonical，必须经 candidate → review → 用户确认
- API 不允许跨 novel_id 读写数据
- 不拼接原始 SQL，使用 SQLAlchemy 参数绑定
- API Key 不写日志、不返回前端；.env 不提交仓库
- 文件上传不做：允许类型外的格式、超过 50MB、路径穿越
- 不 eval / exec LLM 输出
- 合并/删除/废弃操作不做：无二次确认

### 实体抽取
- 实体抽取不是 NER — 不抽取路人、普通道具、代词、一次性场景元素
- 别名不创建新对象，标记 `alias_of_existing`
- 不自动合并正史对象

### 前端
- UI 不暴露工程术语（显示"正史"而非 canonical）
- 不使用富文本编辑器、复杂图谱可视化、专业地图编辑器
- 不引入重型 UI 组件库
- 用户/AI 内容不通过 innerHTML 渲染（使用 textContent）
- 不做：无空状态提示、无操作确认、无错误提示

### 测试
- 修改 contracts/facade/API/DB schema 后不同步更新 README/测试/调用方
- 不做：不跑模块测试就合并

---

## 任务前置读取

开发、测试和代码审查时必须读取以下文件：

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) — 开发原则、模块结构、架构、设计决策
- [TESTING_GUIDE.md](TESTING_GUIDE.md) — 测试要求、Review 分级、安全测试

### 模块级 CLAUDE.md

操作特定模块时还需读取该模块的 `CLAUDE.md`：
- `backend/modules/imports/CLAUDE.md` — 导入模块开发规则
- `backend/modules/world/CLAUDE.md` — 世界对象/去重模块开发规则
