# 架构图分类

架构图用于帮助理解，不替代 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块 README
或代码。

| 文件或目录 | 分类 | 维护规则 |
|---|---|---|
| `module-architecture.drawio` | 当前模块总览的可编辑图源 | 模块数量、分层、归属、主要调用/资料流或共享基础设施变化时同步更新。 |
| `module-architecture.html` | 浏览器兼容交互预览 | 与当前模块清单和关键边界保持一致；不作为可编辑图源或代码 import 图。 |
| `architecture-documents.toml` | 当前架构文档机器清单 | 登记中央文档、模块/组件文档、API 前缀和代码差异影响规则；新增、移动、归档文档时先改清单。 |
| `documentation-maintenance.md` | 架构文档维护流程 | 每轮较大开发按变更影响矩阵更新当前文档，并保留验证证据。 |
| `../rag-architecture.html` | RAG 视觉参考 | 仅说明 RAG 内部关系；具体接口和 schema 以 rag 模块文档/代码为准。 |
| `../diagrams/architecture.html` | 历史架构快照 | 包含已移除的 geo/review 等模块，不可用于当前设计或实现决策。 |
| `../diagrams/system-architecture-slim.html` | 历史瘦身分析 | 记录过去的裁剪讨论，不可用于当前模块清单或数据库判断。 |

当前架构文档的维护入口见
[`documentation-maintenance.md`](documentation-maintenance.md)。

## 自动门禁

```bash
# 清单、模块、ORM 表、API 前缀、任务、路由、Prompt、ADR、链接和 Draw.io 结构
make docs-check

# 再检查当前分支相对主干的代码改动是否覆盖必查文档
make docs-check BASE_REF=origin/main
```

`scripts/check_architecture_docs.py` 使用 Python 3.12 标准库，不引入新的运行时或前端依赖。
PR 若确实没有当前文档变化，必须按脚本列出的未更新文档逐项核对，在 PR 模板勾选无影响并
写出原因；未说明的遗漏会令 CI 失败。新业务模块、`docs/modules/` 文档、
`docs/architecture/` 文件或 ADR 未登记时也会失败。

ADR-0013 记录作者长任务的 operation receipt、最多两个 attempt 和页内恢复边界；该决定
复用现有 tasks/LLM/project seams，不新增队列、表、全局任务中心或跨设备锁。ADR-0014 规定
世界对象图片的鉴权读取、私有双 bucket、最小权限应用凭据和单盘 32GiB MinIO 边界。

## 当前读图约定

- 业务模块共 11 个：`account`、`project`、`world`、`memory`、`outline`、`imports`、
  `rag`、`context`、`writing`、`settings`、`interaction`。
- 创作三层为事实层（`project/world/memory`）、结构层（`outline`）和辅助层
  （`imports/rag/context/writing/settings`）。`account` 是三层之外的公开身份与 owner
  边界；`interaction` 是三层之外的私人 RP 故事领域；`infrastructure/tasks`、
  `infrastructure/llm` 是共享基础设施。
- `map` 是 `world` 拥有的 AI 地图册子系统；地图册与世界对象图片共用受限 MinIO 连接、但使用
  私有分 bucket，边界见 ADR-0012 / ADR-0014。`geo/review/character/timeline` 已移除或并入现有模块。
- 世界观恢复、收束、检修、交接、影响预演和“问世界”仍是既有 `world/context/frontend`
  seam 上的固定工作流；本轮新增 CoreEntity 图片版本 metadata migration，但没有新增顶级模块、
  Agent 运行时或持久工作流表。
- 箭头表达主要调用或资料流，标签说明具体语义；完整生产依赖仍以
  `contracts.py`、`facade.py`、组合根 DI 注册和当前代码为准。

当前图源已通过 XML、唯一 ID、edge endpoint、悬空/交叉/重叠结构检查。无运行时拓扑变化的
文档流程调整不向模块图添加流程节点，避免把开发治理和产品运行架构混在一张图中。
