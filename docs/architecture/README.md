# 架构图分类

架构图用于帮助理解，不替代 `docs/00_整体设计.md`、`docs/01_数据库设计.md`、模块 README
或代码。

编码 Agent 的架构约束只维护在根目录与最近目录的 `AGENTS.md`；`CLAUDE.md` 是导入适配层。
因此模块图和本目录不复制 Agent 指令，避免运行架构、开发流程与工具配置互相漂移。

| 文件或目录 | 分类 | 维护规则 |
|---|---|---|
| `module-architecture.drawio` | 当前模块总览的可编辑图源 | 模块数量、分层、归属、主要调用/资料流或共享基础设施变化时同步更新。 |
| `module-architecture.html` | 浏览器兼容交互预览 | 与当前模块清单和关键边界保持一致；不作为可编辑图源或代码 import 图。 |
| `architecture-documents.toml` | 当前架构文档机器清单 | 登记中央文档、模块/组件文档、API 前缀和代码差异影响规则；新增、移动、归档文档时先改清单。 |
| `documentation-maintenance.md` | 架构文档维护流程 | 每轮较大开发按变更影响矩阵更新当前文档，并保留验证证据。 |
| `../rag-architecture.html` | RAG 视觉参考 | 仅说明历史 RAG 内部关系；具体接口和 schema 以 Evidence indexing 文档/代码为准。 |
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
普通实现变化只输出文档复核提示；API/schema/facade 等稳定边界命中硬门禁时，未更新的
必查文档仍须在 PR 模板勾选无影响并写出原因，不能静默略过。新业务模块、`docs/modules/` 文档、
`docs/architecture/` 文件或 ADR 未登记时也会失败。表、路由、任务各检查一个权威目录，
不再要求模块设计与 README 重复枚举全部条目。

ADR-0013 记录作者长任务的 operation receipt、最多两个 attempt 和页内恢复边界；该决定
复用现有 tasks/LLM/project seams，不新增队列、表、全局任务中心或跨设备锁。ADR-0014 规定
世界对象图片的鉴权读取、私有双 bucket、最小权限应用凭据和单盘 32GiB MinIO 边界。
ADR-0018 定义同 owner author source revision 到 hidden interaction consumer 的唯一跨项目只读
例外：Writing 保留原文，Evidence 按 manifest/截止点编译，interaction 只保存私人旅程。

## 当前读图约定

- 业务模块共 9 个：`account`、`project`、`world`、`evidence`、`story`、`imports`、
  `writing`、`interaction`、`assistant`。原 `memory` 与 `outline` 目录已在兼容准备版本发布后删除。
- Assistant 持有项目讨论、运行、成组确认和提醒投影；经 Evidence 只读查证，经领域操作提交
  具体修改。有限 PydanticAI 核心复用共享 LLM/队列，RP 继续持有自己的树、回顾和 attempt。
- 创作三层为事实层（`project/world`）、结构与连续性层（`story/outline_state`、
  `story/continuity`）和辅助层（`imports/evidence/story/writing`）。RAG 索引和 Context 编译/确认归 `evidence`；
  账户连接与全局偏好归 `account`，项目偏好与有效配置
  归 `project`；`account` 是三层之外的公开身份与 owner
  边界；`interaction` 是三层之外的私人 RP 故事领域，只能经 ADR-0018 版本化只读例外
  消费作者作品；`infrastructure/tasks`、
  `infrastructure/llm` 是共享基础设施。
- Canonical HTTP 所有权与模块一致：`/api/evidence/{indexing,compilation}/*`、
  `/api/account/settings/*`、`/api/projects/{project_id}/author-preferences`；旧
  `/api/rag/*`、`/api/context/*`、`/api/settings/*` 前缀已退场。
- `map` 是 `world` 拥有的 AI 地图册子系统；地图册与世界对象图片共用受限 MinIO 连接、但使用
  私有分 bucket，边界见 ADR-0012 / ADR-0014。`geo/review/character/timeline` 已移除或并入现有模块。
- 世界观恢复、收束、检修、交接、影响预演和“问世界”是既有 `world/evidence/frontend`
  seam 上的固定工作流。CoreEntity 图片只在表内保存版本 metadata，图片字节位于私有对象存储；
  这些能力没有引入新的顶级模块、Agent 运行时或持久工作流表。
- 箭头表达主要调用或资料流，标签说明具体语义；完整生产依赖仍以
  `contracts.py`、`facade.py`、组合根 DI 注册和当前代码为准。

当前图源已通过 XML、唯一 ID、edge endpoint、悬空/交叉/重叠结构检查。无运行时拓扑变化的
文档流程调整不向模块图添加流程节点，避免把开发治理和产品运行架构混在一张图中。

专项查证继续沿既有 imports/writing/world → Evidence → Writing/World 资料流，
一跳只读提名不是自治 Agent。模块图的节点、分层与基础设施保持不变；新增的
evidence_focused_search / targeted_completion 任务由原 task registry 登记。
