# 理想用户路径全集与 Chaos 基线

## 目标

本报告把当前仓库中的“理想用户路径”统一成一份可执行基线，用于后续 chaos / monkey / recovery / regression 测试设计。

本轮不做产品补洞，只做三件事：

1. 固定一级路径全集
2. 标记每条路径当前实现状态
3. 为每条路径指定 chaos 分层和首批测试落点

## 权威来源

- 主业务 8 条路径：`docs/核心业务场景与预期行为.md`
- 地图 7 条路径：`docs/PRD-动态地图功能.md`
- 地图一级工作台承接规则：`docs/superpowers/specs/2026-06-26-map-workspace-design.md`
- 现有浏览器覆盖现状：`frontend-console/e2e/scenario-coverage.md`

## 状态语义

- `implemented`：主路径已落地，且仓库中存在代码入口与至少一种自动化覆盖证据
- `partial`：主路径已部分落地，但仍有明确缺口、降级分支、恢复路径或高级交互未封口
- `spec_only`：目前只有规格，不应被当成可执行能力

## 非一级路径

- `generate` 保持为衍生入口，不进入一级理想路径全集
- 原因：它复用世界/大纲/章节生成能力，没有单独的业务闭环规格

## 路径全集

| Path | 名称 | 来源 | 成功终点 | 模块 / 视图 | 状态 | 风险 | executable_now | chaos layers |
|------|------|------|----------|-------------|------|------|----------------|--------------|
| `S1` | 项目创建与管理 | 核心场景 1 | 项目可创建、选择、回收、恢复、永久删除 | `project` / `projectView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `S2` | 文件上传与章节导入 | 核心场景 2 | 外部文件被解析为 `writing_drafts` 并记录 `import_records` | `imports`, `writing`, `rag` / `projectView`, `writingView` | `implemented` | `high` | `yes` | `api_chaos`, `workflow_chaos`, `frontend_recovery` |
| `S3` | 深度导入流水线 | 核心场景 3 | 三阶段导入任务完成或降级完成且状态可恢复 | `imports`, `outline`, `world`, `memory`, `tasks` / `writingView` | `partial` | `high` | `yes` | `workflow_chaos`, `frontend_recovery` |
| `S4` | 手工写作工作台 | 核心场景 4 | 正文编辑、暂存、发布、断章、版本冲突处理可闭环 | `writing`, `outline`, `rag` / `writingView` | `implemented` | `high` | `yes` | `workflow_chaos`, `frontend_recovery` |
| `S5` | 世界对象管理 | 核心场景 5 | 对象、关系、别名、合并、回滚、知识边界可管理 | `world`, `memory` / `worldView` | `implemented` | `high` | `yes` | `api_chaos`, `frontend_recovery` |
| `S6` | 大纲与结构管理 | 核心场景 6 | Scene / 线程 / 篇章纲 / 伏笔 / 揭示可维护 | `outline`, `context` / `outlineView` | `partial` | `high` | `yes` | `api_chaos`, `workflow_chaos`, `frontend_recovery` |
| `S7` | RAG 混合检索 | 核心附录 A1 | 检索结果、降级 warning、重建状态可见 | `rag` / `ragView` | `partial` | `medium` | `yes` | `api_chaos`, `workflow_chaos`, `frontend_recovery` |
| `S8` | 上下文编译 | 核心附录 A2 | 编译、渲染、确认、预算裁剪和知识边界可观察 | `context`, `world`, `outline`, `rag` / `contextView` | `partial` | `medium` | `yes` | `api_chaos`, `workflow_chaos`, `frontend_recovery` |
| `M1` | 创建世界地图 | 地图路径 1 | 世界地图与初始 tile 集被创建 | `world maps` / `mapWorkspaceView`, `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M2` | 绑定地点 | 地图路径 2 | `location` 实体被绑定到地图 hex，中心点唯一 | `world maps` / `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M3` | 创建地点详图 | 地图路径 3 | 地点下钻图被创建并进入编辑模式 | `world maps` / `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M4` | 浏览地图 | 地图路径 4 | 地图总览、最近地图、面包屑与详情浏览成立 | `world maps` / `mapWorkspaceView`, `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M5` | Scene 时间层 | 地图路径 5 | Scene 过滤、时间层 marker、Scene 切换成立 | `world maps`, `outline` / `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M6` | 势力范围与聚焦模式 | 地图路径 6 | territory 与 focus state 可视化和过滤成立 | `world maps` / `mapView` | `implemented` | `medium` | `yes` | `api_chaos`, `frontend_recovery` |
| `M7` | AI 位置建议 | 地图路径 7 | AI 建议写入 `map_position_suggestions` 并待确认 | `world maps`, `llm` / 地图建议 UI | `spec_only` | `high` | `no` | `future_matrix_only` |

## Chaos 维度基线

所有路径统一使用以下维度，但不是每条路径都要全量命中：

- `validation`：空值、缺字段、越界、非法枚举、错误 query/body
- `isolation`：跨 `novel_id`、错项目资源、已删除资源、不可见资源
- `idempotency`：重复提交、重复创建、重复删除、重复覆盖
- `concurrency`：多标签页、双提交、重复 worker 受理、中心点竞争
- `recovery`：刷新、路由跳转、浏览器关闭重开、任务恢复
- `degraded_mode`：部分成功、失败降级、warning 暴露、缓存失效
- `stale_state`：旧 breadcrumb、旧列表、旧 Scene 面板、旧最近地图
- `dangerous_actions`：删除、回滚、覆盖、合并、清空等确认语义

## 每条路径至少应命中的维度

| Path | Required dimensions |
|------|---------------------|
| `S1` | `validation`, `isolation`, `dangerous_actions`, `stale_state` |
| `S2` | `validation`, `idempotency`, `recovery`, `stale_state` |
| `S3` | `idempotency`, `concurrency`, `recovery`, `degraded_mode`, `isolation` |
| `S4` | `concurrency`, `recovery`, `stale_state`, `validation` |
| `S5` | `isolation`, `idempotency`, `dangerous_actions`, `stale_state` |
| `S6` | `concurrency`, `idempotency`, `dangerous_actions`, `stale_state` |
| `S7` | `validation`, `degraded_mode`, `isolation`, `stale_state` |
| `S8` | `validation`, `degraded_mode`, `isolation`, `stale_state` |
| `M1` | `validation`, `isolation`, `idempotency` |
| `M2` | `validation`, `isolation`, `idempotency`, `concurrency` |
| `M3` | `validation`, `isolation`, `idempotency` |
| `M4` | `recovery`, `stale_state`, `dangerous_actions` |
| `M5` | `validation`, `isolation`, `recovery`, `stale_state` |
| `M6` | `validation`, `isolation`, `concurrency`, `stale_state` |
| `M7` | `future_only` |

## 测试文件落点

### 新增

- `backend/tests/chaos/core_paths_chaos.py`
- `backend/tests/chaos/workflow_paths_chaos.py`
- `frontend-console/e2e/project-chaos.spec.js`
- `frontend-console/e2e/import-workflow-chaos.spec.js`
- `frontend-console/e2e/writing-chaos.spec.js`
- `frontend-console/e2e/world-outline-chaos.spec.js`
- `frontend-console/e2e/rag-context-chaos.spec.js`
- `frontend-console/e2e/map-chaos.spec.js`
- `docs/superpowers/reports/2026-06-28-ideal-user-paths-chaos-matrix.json`

### 复用

- `backend/tests/chaos/map_chaos.py`
- `frontend-console/e2e/deep-import-worker.spec.js`
- `frontend-console/e2e/writing-conflict.spec.js`
- `frontend-console/e2e/map.spec.js`

## 当前结论

- `S3`, `S6`, `S7`, `S8` 仍应视为 `partial`
- `M5`, `M6` 已有代码与自动化证据，可视为 `implemented`
- `M7` 只进入矩阵，不应创建执行型 chaos 脚本
- `scenario-coverage.md` 继续只记录现有真实覆盖，不承载理想路径全集
