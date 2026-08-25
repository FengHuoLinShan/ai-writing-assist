# ADR-0015 — Story、Evidence 与 Settings 所有权融合

- **状态**: Accepted / Phased implementation
- **日期**: 2026-08-21
- **取代/修订**: ADR-0004 的 RAG/Context 物理分模块约束；修订 ADR-0006 的
  Context 物理 owner 与 ADR-0010 的 Settings 物理 owner

## 背景

作者的实际工作流需要同时跨越 Scene 结构、历史状态、人物认知、检索证据与
写作。现有 Outline/Memory、RAG/Context 以及 Settings 的物理拆分带来了大量跨模块
编排，但其数据历史、可见性、任务恢复与密钥边界不能因为融合而改变。

## 决策

1. 先以新 `story` 垂直切片交付 Scene 人物卡、反应推演和剧本区；该流程只写
   Story 派生资产，不写 World 正典、Memory 历史或 Writing 正文。
2. 物理融合按 `settings -> account/project`、`rag/context -> evidence`、
   `outline/memory/story -> story` 的顺序执行。
3. 物理移动不改数据库表名、已持久化 task type/action、Context snapshot 语义、
   DI key 或历史回滚语义。旧 HTTP 路由在一个完整发布周期内只是同处理器别名，
   不建立双服务或双写。
4. Evidence 仍保留 indexing、compilation、confirmation 和 guard 四个内部子域。
   RAG freshness 与 Context confirmation freshness 始终是两种状态。
5. Story 仍区分结构计划、反应提案、已执行 Delta 与 MemoryEvent。World 仍是
   正典人物、知识和关系的唯一 owner。
6. Account 拥有密钥、验证连接和全局账户偏好；Project 拥有非 secret 工作流设置、
   项目偏好与 effective 投影。`open_project_llm_client()` 仍是业务 LLM 的唯一入口。
7. 不引入通用事件总线、新工作流引擎、自治 Agent 或新基础设施。

## 分阶段门禁

- 新增能力先通过 owner + `novel_id`、版本/CAS、任务恢复、可见性与前端草稿恢复验收。
- 每次物理融合前后，`Base.metadata.tables`、TaskRegistry task type 集合、OpenAPI 路由/
  schema 和未完成任务恢复行为必须对等。
- 非空数据库使用增量 migration、备份和回滚演练；只有开发/测试库可重建。
- Activation Profile 的主 UI 可以收起，但在确认生产数量和历史引用前，不删表、
  revision 或 confirmation/snapshot 中的历史元数据。

## 兼容准备状态（2026-08-25）

前端、活跃测试、E2E、Prompt contracts 和工具已改用 canonical HTTP 与 Python
命名空间。旧 HTTP 挂载与 `modules.outline` / `modules.memory` / `modules.rag` /
`modules.context` 仍保留，只由专用兼容契约测试覆盖。删除必须等待该准备版本以
`origin/main` 可达的固定 SHA 发布一次，并核对生产发布状态后才能进行。
`/api/outline/*`、Memory HTTP 路径、既有 task type 和所有响应 schema 不在退场范围内。

## 结果

- 最终业务模块为 `account`、`project`、`imports`、`world`、`evidence`、
  `story`、`writing`、`interaction`。
- 允许移除重复页面、调参 UI 和已完成迁移的兼容入口；不允许损失数据历史、
  回滚、任务恢复、Map、RP、Imports Phase 2、Writing 或 Evidence 安全边界。

## 未采用方案

- 一次性改表名、task type 和 API：会让存量任务、历史引用与回滚同时失效。
- 保留新旧两套服务并双写：增加漂移和故障面。
- 用通用 revision/event 框架替换既有专用历史表：不能保证 TextArchive、MemoryEvent、
  Scene 版本和 Writing 版本的对等语义。
