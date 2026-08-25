# 前端-后端能力差距分析

> 核对时间：2026-07-12
> 方法：对照后端路由、模块稳定接口、前端 API wrapper、实际视图调用和当前权威模块文档。
> 结论原则：“后端有端点”不等于“作者控制台必须有按钮”。

---

## 1. 需要前端实现的能力

### 1.1 可重试后台任务

| 项目 | 实际状态 |
|------|---------|
| 后端端点 | `POST /api/tasks/{task_id}/retry` |
| 前端契约 | `tasks.retry` 已定义 |
| 动作来源 | `GET /api/tasks/{task_id}` 返回 `available_actions` |
| 作者入口 | 共享任务卡仅在 `available_actions` 包含 `retry` 时显示“重试任务” |

实现约束：

- `retry` 只对 `auto_requeue` 且未耗尽尝试次数的失败任务开放。
- `restart_origin` 仍由领域原始表单重新提交，不伪装成 retry。
- `resume / abandon` 仍属于深度导入的专用恢复流程。
- 当前主要消费者为 RAG 索引任务和世界书投影刷新任务。

### 1.2 生成模板修订历史

| 项目 | 实际状态 |
|------|---------|
| 后端端点 | `GET /api/world/generation-prompt-templates/{id}/revisions` |
| 前端 wrapper | `generate.listPromptTemplateRevisions()` |
| 作者入口 | 自定义模板编辑器的“版本历史” |

作者可查看版本号、创建时间、校验状态和提示词预览。“载入到编辑器”只替换当前表单内容；用户再次点击“保存模板”后才会通过现有 update API 生成新修订。

### 1.3 RAG 检索追踪诊断

| 项目 | 实际状态 |
|------|---------|
| 后端端点 | `GET /api/evidence/compilation/retrieval-traces` |
| 前端 wrapper | `context.listRetrievalTraces()` |
| 作者入口 | `小说检索 → 索引维护 → 技术诊断详情` |

追踪记录按需加载，只展示后端保存的隐私安全摘要：检索用途、正文模式、候选/去重/回读/丢弃数量、safe-empty 原因和警告码。不展示 raw query 或正文。

---

## 2. 内部基础设施，不暴露作者 UI

### 2.1 Memory 模块

`memory_events`、`memory_snapshots` 和相关 API 是事件溯源、上下文编译和跨模块连续性检查的内部基础设施。

前端不新增 Memory 路由、一级导航、API wrapper 或手动快照/重建按钮。世界全景、时间变化和实体轨迹等作者需求后续由地图模块提供统一视图。

当前 `open_target.kind="memory_chapter"` 继续显示只读来源摘要，不导航到独立 Memory 页面。

### 2.2 Context snapshot maintenance

`POST /api/evidence/compilation/snapshots/maintenance` 是上下文快照和 retrieval trace 的生命周期治理入口，默认 `dry_run=true`。它属于内部维护能力，不进入作者控制台。

### 2.3 Debug frontend errors

`GET/POST/DELETE /api/debug/frontend-errors` 仅用于 development/test 环境的本地调试和 E2E 检查；生产环境返回 404。前端保留现有本地错误面板和单向脱敏上报，不新增 Debug 产品路由。

---

## 3. Legacy 或重复入口，不新增 UI

### 3.1 按 revision_id 回滚实体

`GET /api/world/entities/{entity_id}/revisions` 和 `POST /rollback-by-revision` 是 `entity_revisions` 的 legacy 兼容路径。

当前正式作者入口是按 Scene 索引回滚：

```http
POST /api/world/entities/{entity_id}/rollback
```

该路径优先使用 `TextArchive`，无归档时再回退到 `EntityRevision`。前端不再另建 legacy 版本回滚面板。

### 3.2 内置生成模板复制

`POST /api/world/generation-prompt-templates/{id}/copy` 已被当前交互消费：用户编辑内置模板并保存时，系统自动创建项目级副本后再更新。不增加语义重复的“复制模板”按钮。

---

## 4. 缺少后端前置契约，暂不做半套 UI

### 4.1 角色知识标签排除/锁定

已有的三个写端点只能按已知 `character_id + tag_id` 执行排除、撤销排除和锁定。当前缺少面向 UI 的完整读契约，包括：

- 角色当前获授标签列表；
- `grant_source` 和来源引用；
- `author_locked` 状态；
- 当前 exclusion 及原因；
- derived/manual/suggested 等作者可理解分类。

在后端提供上述读契约前，前端不只增加三个无法正确定位对象的写按钮。

### 4.2 LLM 健康检查边界

`GET /api/health/llm` 是无账户、无项目、无远程请求的服务配置检查，明确返回
`scope=service` 和 `remote_check=false`；它不读取当前项目的 effective profile，也不表示作者账户可连通。

因此前端不将它放到项目设置中伪装成“当前项目连通性”。真实连通性继续由账户设置页保存连接时验证；项目工作流按 `novel_id`、owner 和 effective profile 做前置检查，不新增公开的项目健康端点。

---

## 5. 有意的列表 + Modal 设计

以下实体已通过列表行和 Modal 完成查看/编辑，不因后端存在单条 GET 端点就增加独立详情页：

| 实体 | 当前交互 |
|------|---------|
| 剧情线 | 列表行 → Modal 编辑 |
| 篇章纲 | 列表行 → Modal 编辑 |
| 伏笔 | 列表行状态操作 → Modal 编辑 |
| 揭示 | 列表行状态操作 → Modal 编辑 |

---

## 6. 最终分类

| 分类 | 能力 |
|------|------|
| 需要前端实现 | 任务 retry、模板修订历史、RAG 检索追踪 |
| 内部基础设施 | Memory、Context snapshot maintenance、Debug frontend errors |
| Legacy/重复入口 | revision_id 回滚、独立模板复制按钮 |
| 后端前置未满足 | 知识标签管理、项目级 LLM 健康检查 |
| 无需独立详情页 | thread / arc / foreshadowing / reveal |
