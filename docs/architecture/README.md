# 架构图分类

架构图用于帮助理解，不替代 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块 README
或代码。

| 文件或目录 | 分类 | 维护规则 |
|---|---|---|
| `module-architecture.drawio` | 当前模块总览的可编辑图源 | 模块数量、分层、归属、主要调用/资料流或共享基础设施变化时同步更新。 |
| `module-architecture.html` | 浏览器兼容交互预览 | 与当前模块清单和关键边界保持一致；不作为可编辑图源或代码 import 图。 |
| `documentation-maintenance.md` | 架构文档维护流程 | 每轮较大开发按变更影响矩阵更新当前文档，并保留验证证据。 |
| `../rag-architecture.html` | RAG 视觉参考 | 仅说明 RAG 内部关系；具体接口和 schema 以 rag 模块文档/代码为准。 |
| `../diagrams/architecture.html` | 历史架构快照 | 包含已移除的 geo/review 等模块，不可用于当前设计或实现决策。 |
| `../diagrams/system-architecture-slim.html` | 历史瘦身分析 | 记录过去的裁剪讨论，不可用于当前模块清单或数据库判断。 |

当前架构文档的维护入口见
[`documentation-maintenance.md`](documentation-maintenance.md)。

## 当前读图约定

- 业务模块共 10 个：`account`、`project`、`world`、`memory`、`outline`、`imports`、
  `rag`、`context`、`writing`、`settings`。
- 创作三层为事实层（`project/world/memory`）、结构层（`outline`）和辅助层
  （`imports/rag/context/writing/settings`）。`account` 是三层之外的公开身份与 owner
  边界；`infrastructure/tasks`、`infrastructure/llm` 是共享基础设施。
- `map` 是 `world` 子系统；`geo/review/character/timeline` 已移除或并入现有模块。
- 箭头表达主要调用或资料流，标签说明具体语义；完整生产依赖仍以
  `contracts.py`、`facade.py`、组合根 DI 注册和当前代码为准。
