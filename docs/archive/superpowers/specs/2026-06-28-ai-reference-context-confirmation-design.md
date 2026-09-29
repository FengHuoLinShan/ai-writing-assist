# AI 参考资料确认流程设计

## 1. 背景

`context` 模块当前已经能编译 LLM 上下文，并在独立“上下文”页面提供预览、渲染、复制和导出能力。但正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象等流程中，用户并没有在执行前显式确认“本次 AI 会参考什么”。

这导致两个问题：

- 用户无法判断 AI 输出是否基于正确资料，错误输出难以归因。
- “候选创作资产”与正式正史资产的边界没有在用户操作中体现，容易让未确认对象污染正式写作流程。

本设计把用户侧概念统一为 **AI 参考资料**。内部仍使用 `context.compile`、`context_mode`、`candidate` 等领域术语；前端面向普通用户时将候选资产称为 **待确认对象**。

## 2. 目标

- 手动 AI 操作执行前必须展示并确认“AI 参考资料”。
- 深度导入保持傻瓜式自动化，不插入手动参考资料确认。
- 引入 `context_mode="canonical" | "working"`：
  - `canonical`：正式/常规上下文，默认不包含待确认对象。
  - `working`：AI 流水线内部上下文，可包含待确认对象，用于深度导入等自动流程。
- 引入 `POST /api/context/confirm`，由后端按用户当前选择重新编译上下文并创建确认记录。
- 手动 AI 接口通过 `context_confirmation_id` 引用确认记录。
- 第一版保存确认摘要、选择参数和资产 ID，不保存完整 rendered context。
- 待确认对象变更后，只标记受影响结果，不自动重算或覆盖用户已编辑内容。

## 3. 非目标

- 不把深度导入改成分阶段人工确认流程。
- 不让用户直接编辑编译后的 Markdown 上下文正文。
- 手动 AI 第一版不写入完整上下文快照表、回放系统或审计 UI；深度导入的自动审计快照由 `context_snapshots` 单独承载。
- 不开放 prompt 模板选择、loader/tier 细节、token 预算调参给普通用户。
- 不让“AI 参考资料”弹窗替代“上下文”页；上下文页仍是高级预览/调试台。

## 4. 当前状态

### 4.1 已有能力

- `backend/modules/context/api.py`
  - `POST /api/context/compile`：返回 Tier 化编译结果。
  - `POST /api/context/render`：返回 Markdown。
- `backend/modules/context/contracts.py`
  - `CompileOptions` 定义 `scope`、`chapter_index`、`scene_id`、`entity_ids`、`character_ids`、`reveal_mode` 等编译参数。
- `frontend-console/views/contextView.js`
  - 提供独立上下文页面，可编译、渲染、复制和导出 Markdown。
- `frontend-console/views/generateView.js`
  - 自动调用过 `/api/context/compile`，但不展示编译结果，也不让用户确认。
- `frontend-console/views/outlineView.js`
  - 手动剧情结构生成只确认章节范围和覆盖风险，不确认参考资料。
- `frontend-console/views/writingView.js`
  - 深度导入只确认章节范围和重复导入风险，符合自动化定位。

### 4.2 缺口

| 缺口 | 影响 |
|---|---|
| 手动 AI 操作前没有参考资料确认 | 用户无法控制 AI 依据 |
| 上下文页与生成流程脱节 | 预览不能保证就是本次生成使用的资料 |
| 缺少 `context_mode` | 无法明确 canonical 与 working 的边界 |
| 缺少确认记录 | 后续结果无法追溯本次 AI 大致参考了什么 |
| 待确认对象变更后缺少影响标记 | 用户无法知道哪些结果需要复核 |

## 5. 核心概念

### 5.1 AI 参考资料

用户可见概念，表示本次 AI 操作会参考的资料包。它不是技术模块名，也不是完整 prompt。它包含：

- 章节/Scene 范围
- 揭示模式
- 是否包含待确认对象
- 被包含/排除的世界对象、人物、剧情线、伏笔等资产
- 本次 AI 额外注意事项
- 编译摘要、警告和截断信息

### 5.2 待确认对象

用户可见名称，对应内部 `candidate` 状态的候选创作资产。前端不直接展示“候选资产 / candidate asset”等工程术语。

### 5.3 工作上下文

`working context` 是 AI 流水线内部使用的上下文层。它可以读取正史资产、草稿资产、待确认对象、证据片段、置信度和来源依赖，但不等同于正史上下文。

深度导入内部使用 working context，以支持长文档自动导入时“第二轮/后续阶段”基于待确认对象继续提取剧情线、关系、伏笔和篇章结构。

## 6. 用户流程

### 6.1 手动 AI 操作

适用范围：

- 正文生成
- 手动剧情分析
- 手动剧情结构生成
- 手动补抽世界对象

流程：

```text
用户点击 AI 操作
  → 打开“AI 参考资料”弹窗
  → 系统按默认参数编译预览
  → 用户调整范围/揭示模式/待确认对象/排除项/补充说明
  → 用户点击“重新整理参考资料”刷新预览
  → 用户点击“确认并生成/分析”
  → POST /api/context/confirm
      后端重新编译并创建确认记录
      返回 context_confirmation_id
  → 调用对应 AI 接口并传 context_confirmation_id
  → 结果 _meta 记录确认摘要或确认 ID
```

### 6.2 深度导入

深度导入不走“AI 参考资料”弹窗。

流程保持：

```text
用户选择章节范围
  → 确认重复导入/覆盖风险
  → 后台三阶段自动执行
  → 内部使用 working context
  → 完成后集中展示结果、降级原因和待复核资产
```

理由：深度导入的产品承诺是自动化和低操作成本。逐阶段确认上下文会破坏长文档批量导入体验。

## 7. 前端设计

### 7.1 组件边界

不复用整个 `contextView`。`contextView` 是独立页面，带路由状态、DOM id、复制/导出等高级调试能力，直接嵌入生成流程会耦合过重。

第一版新增共享弹窗组件：

```text
frontend-console/shared/aiReferenceModal.js
```

可选抽取摘要渲染 helper：

```text
frontend-console/shared/contextSummaryRenderer.js
```

复用现有全局 `showModal(...)` 作为 UI 容器，不新增抽屉基础设施。

### 7.2 弹窗布局

建议两栏布局：

- 左侧：设置
  - 章节/Scene 范围
  - 揭示模式
  - 是否包含待确认对象
  - 世界对象、人物、剧情线、伏笔的排除项
  - 本次 AI 额外注意事项
- 右侧：预览
  - 已加载段落/资产数量
  - 范围、揭示模式
  - 待确认对象提示
  - warnings
  - truncated / evicted 信息
  - 可展开查看参考文本摘要

### 7.3 编辑规则

- 用户编辑的是选择规则和本次补充说明，不直接编辑编译后的 Markdown。
- 调整范围、揭示模式、是否包含待确认对象或排除资产后，通过“重新整理参考资料”重新调用 `/api/context/compile` 刷新预览。
- 如果用户发现结构化资产本身错误，应跳转或弹出对应资产编辑表单；保存后再重新整理参考资料。
- “本次 AI 额外注意事项”作为临时高优先级上下文参与本次调用，记录到 `_meta.user_note`，但不写入正史资产。
- 第一版不支持手动粘贴或改写完整上下文 Markdown，避免产生脱离结构化资产体系的临时事实。

### 7.4 默认值

| 操作 | 是否默认包含待确认对象 |
|---|---|
| 正文生成 | 否 |
| 手动剧情分析 | 是，显示“包含待确认对象，结果需复核” |
| 手动剧情结构生成 | 是，显示“包含待确认对象，结果需复核” |
| 手动补抽世界对象 | 是，显示“包含待确认对象，结果需复核” |
| 深度导入 | 内部自动包含，不展示弹窗 |

### 7.5 提交后的进度感知

用户确认参考资料并提交 AI 任务后，前端必须继续展示任务进度，而不是只显示 toast 或“后台运行”。

第一版采用现有 `GET /api/tasks/{task_id}` 轮询，不引入 WebSocket/SSE。前端统一使用共享进度模型：

- 有 `task.progress` 时显示真实百分比。
- 没有真实百分比时显示运行中状态、任务 ID、阶段文案和耗时感知，不伪造精确进度。
- `done` 时显示完成摘要和结果所在模块入口。
- `failed` / `cancelled` 时显示可见错误，不继续显示“后台运行”。
- 页面刷新后，仍可恢复深度导入、生成中心、RAG 重建、世界对象抽取等未完成任务。

适用工作流：

- 文件上传导入：保留 XHR 上传百分比，并显示“上传文件 / 解析章节 / 刷新项目”阶段。
- 深度导入：保持自动化，不插入参考资料确认，但显示三阶段进度、降级、部分完成和错误摘要。
- 正文发布：显示 RAG 写入和历史状态创建阶段。
- RAG 重建：使用 `rag_reindex_novel` 的真实 progress。
- 世界对象补抽：在无细粒度 progress 时显示 indeterminate 运行状态。
- 生成中心：上下文编译、任务提交、后台运行、完成/失败均在结果区域持续可见。

## 8. 后端设计

### 8.1 context_mode

在上下文编译请求中新增：

```json
{
  "context_mode": "canonical"
}
```

取值：

| 值 | 语义 |
|---|---|
| `canonical` | 常规用户确认上下文，默认不包含 `candidate` / 待确认对象 |
| `working` | AI 流水线内部上下文，可包含 `candidate` / 待确认对象 |

`canonical` 不表示只读取数据库 `status="canonical"` 的行；它的产品语义是“不混入未确认 AI 对象”。例如正文草稿、当前章节原文仍可作为任务输入进入上下文。

### 8.2 确认记录

第一版新增轻量确认记录，用于支持 `context_confirmation_id` 和未来手动 AI 快照扩展。它不是完整上下文快照表；深度导入自动审计使用独立的 `context_snapshots`。

建议表名：

```text
context_confirmations
```

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | UUID |
| `novel_id` | 项目 ID |
| `action` | `writing_generate` / `plot_analysis` / `plot_structure_generate` / `world_extract` |
| `context_mode` | `canonical` / `working` |
| `scope` | 与 context compile 一致 |
| `range_json` | 章节、Scene、arc 等范围 |
| `reveal_mode` | 揭示模式 |
| `include_pending_objects` | 是否包含待确认对象 |
| `included_asset_ids` | JSON：本次包含资产 ID |
| `excluded_asset_ids` | JSON：本次排除资产 ID |
| `asset_counts` | JSON：资产数量摘要 |
| `user_note` | 本次 AI 额外注意事项 |
| `warnings` | 编译警告 |
| `compiled_at` | 编译时间 |
| `created_at` / `updated_at` | 基础时间戳 |

手动 AI 第一版不保存完整 `rendered_context`。后续如果手动操作需要完整审计和回放，可迁移到 `context_snapshots` 或扩展确认记录。

### 8.3 API 契约

新增：

```text
POST /api/context/confirm
```

请求示例：

```json
{
  "novel_id": "uuid",
  "action": "plot_structure_generate",
  "task": "为第 1-5 章生成剧情结构",
  "scope": "chapter",
  "context_mode": "canonical",
  "start_chapter": 1,
  "end_chapter": 5,
  "scene_ids": [],
  "reveal_mode": "author_safe",
  "viewpoint_character_id": null,
  "include_pending_objects": true,
  "excluded_asset_ids": {
    "entities": ["uuid"],
    "characters": [],
    "plot_threads": [],
    "foreshadowing": []
  },
  "user_note": "本次不要提前揭示反派身份"
}
```

响应示例：

```json
{
  "context_confirmation_id": "uuid",
  "novel_id": "uuid",
  "action": "plot_structure_generate",
  "context_mode": "canonical",
  "scope": "chapter",
  "range": {
    "start_chapter": 1,
    "end_chapter": 5,
    "scene_ids": []
  },
  "reveal_mode": "author_safe",
  "include_pending_objects": true,
  "asset_counts": {
    "entities": 8,
    "characters": 3,
    "plot_threads": 2,
    "foreshadowing": 1
  },
  "included_asset_ids": {
    "entities": ["uuid"],
    "characters": ["uuid"],
    "plot_threads": ["uuid"],
    "foreshadowing": ["uuid"]
  },
  "excluded_asset_ids": {
    "entities": ["uuid"]
  },
  "warnings": [],
  "compiled_at": "2026-06-28T12:00:00Z"
}
```

`/api/context/confirm` 必须按用户当前选择重新编译上下文并创建确认记录，而不是保存前端已预览结果。这样可以避免预览与最终执行之间的数据漂移。

### 8.4 手动 AI 接口接入

手动 AI 接口改为接收：

```json
{
  "context_confirmation_id": "uuid"
}
```

适用接口包括：

- 正文生成接口
- 手动剧情分析接口
- `POST /api/outline/generate`
- 手动世界对象补抽接口

这些接口必须：

1. 校验确认记录存在。
2. 校验 `novel_id` 一致。
3. 校验 `action` 与当前接口匹配或兼容。
4. 使用确认记录的选择参数重新取得或引用已确认的上下文摘要。
5. 将 `context_confirmation_id` 和必要摘要写入生成结果或任务 `_meta`。

### 8.5 深度导入接入

深度导入不接收 `context_confirmation_id`，也不要求用户确认参考资料。

深度导入内部需要显式使用 `context_mode="working"`，允许待确认对象参与后续阶段；派生结果保持 `draft` / `candidate` / `pending` 等待确认状态。

## 9. 待确认对象变更与失效

第一版只标记受影响结果，不自动级联重算。

状态：

| 状态 | 含义 |
|---|---|
| `ready` | 当前参考资料仍有效 |
| `needs_review` | 结果依赖待确认对象，需要用户复核 |
| `stale_context` | 依赖对象已被忽略、合并、改名或结构性变化，建议重新分析/生成 |

触发：

- 结果 `_meta.included_asset_ids` 引用了被忽略的待确认对象。
- 结果 `_meta.included_asset_ids` 引用了被合并的待确认对象。
- 结果 `_meta.included_asset_ids` 引用了被改名的待确认对象。
- 结果 `_meta.included_asset_ids` 引用了从 candidate 提升为 canonical 的对象，可标记 `needs_review` 或保持 `ready`，由实现按影响范围决定。

第一版不自动覆盖正文草稿、剧情线、篇章纲或分析结果。用户可手动触发“用当前 AI 参考资料重新分析/重新生成”。

## 10. 分期

### 10.1 第一期

- `context_mode="canonical" | "working"`。
- `POST /api/context/confirm`。
- `context_confirmations` 轻量确认记录。
- 手动 AI 接口接收 `context_confirmation_id`。
- `frontend-console/shared/aiReferenceModal.js`。
- 共享上下文摘要渲染 helper。
- 正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象接入确认弹窗。
- 共享任务进度组件与轮询 helper。
- 导入、深度导入、正文发布、RAG 重建、世界对象补抽、生成中心接入进度感知。
- 深度导入保持自动化。
- 结果 `_meta` 保存 `context_confirmation_id`、摘要和资产 ID。
- 待确认对象变化后只标记 `needs_review` / `stale_context`。

### 10.2 后续

- 手动 AI 操作迁移到 `context_snapshots` 或补充回放入口。
- 上下文回放和审计 UI。
- 更细粒度资产编辑入口。
- 自动失效扫描。
- 批量重算建议。
- 更强的候选审查工作台。

## 11. 验收标准

- 正文生成、手动剧情分析、手动剧情结构生成、手动补抽世界对象在执行 LLM 前必须展示“AI 参考资料”确认弹窗。
- 深度导入不展示“AI 参考资料”确认弹窗，仍可一键启动并后台运行。
- 弹窗内用户可调整范围、揭示模式、是否包含待确认对象、排除资产和本次 AI 额外注意事项。
- 弹窗内用户不能直接编辑完整 Markdown 上下文正文。
- 点击确认后，后端重新编译上下文并创建确认记录，返回 `context_confirmation_id`。
- 手动 AI 接口必须校验并记录 `context_confirmation_id`。
- 正文生成默认不包含待确认对象。
- 手动剧情分析、手动剧情结构生成、手动补抽世界对象默认包含待确认对象，并显示“包含待确认对象，结果需复核”。
- 待确认对象被忽略、合并或改名后，依赖它的结果标记为 `needs_review` 或 `stale_context`，不自动覆盖用户内容。
- 用户可见文案使用“待确认对象”，不直接暴露“candidate asset”。
- 任务提交后必须显示持续进度；失败时显示后端错误，不停留在“后台运行”。
- 有真实 `task.progress` 的任务显示百分比；无真实 progress 的任务显示 indeterminate 状态。
- 深度导入、生成中心、RAG 重建和世界对象抽取在页面刷新后可恢复运行中任务。

## 12. 测试建议

### 后端

- `modules/context/tests/test_context.py`
  - `context_mode="canonical"` 不包含 `candidate` 世界对象。
  - `context_mode="working"` 可包含 `candidate` 世界对象。
  - `/api/context/confirm` 创建确认记录并返回 `context_confirmation_id`。
  - `/api/context/confirm` 在 `reveal_mode="character"` 且缺少 `viewpoint_character_id` 时返回 400。
  - 确认记录强制 `novel_id` 隔离。

- 手动 AI 接口对应测试
  - 缺少 `context_confirmation_id` 时拒绝或走明确兼容路径。
  - `context_confirmation_id` 属于其他 `novel_id` 时返回 404/403。
  - 生成结果 `_meta` 包含 `context_confirmation_id` 和上下文摘要。

### 前端

- `frontend-console/tests/aiReferenceModal.test.js`
  - 默认值随 action 改变。
  - 点击“重新整理参考资料”调用 `api.context.compile`。
  - 点击确认调用 `api.context.confirm`。
  - 不渲染可编辑 Markdown textarea。
  - 用户可见文案包含“待确认对象”，不包含“candidate asset”。

- 相关 view 测试
  - `outlineView` 的 AI 生成剧情结构先打开参考资料弹窗。
  - `writingView` 的深度导入不打开参考资料弹窗。
  - 正文生成默认不包含待确认对象。
  - `workflowProgress` 覆盖百分比、无百分比、失败、取消、完成和 localStorage 恢复。
  - `progressRenderer` 覆盖动态文案和错误信息转义。
  - `generateView` 提交任务后轮询并显示完成/失败状态。
  - `ragView` 按真实 `task.progress` 显示 RAG 重建进度和完成摘要。
  - `worldView` 可恢复世界对象抽取任务，失败后保留错误卡片并允许重试。
  - `writingView` 发布和深度导入使用共享进度条，深度导入部分完成/降级可见。

### E2E

- 手动剧情结构生成：打开弹窗、重新整理参考资料、确认、提交生成。
- 深度导入：仍只显示范围选择和重复导入确认，不出现 AI 参考资料弹窗。
- 长任务 E2E：提交任务后刷新页面，确认进度卡恢复且失败态可见。

## 13. 风险

| 风险 | 缓解 |
|---|---|
| 弹窗变成复杂上下文编辑器 | 第一版只允许编辑选择规则和补充说明，不允许改 Markdown |
| 确认记录与最终生成上下文漂移 | `/api/context/confirm` 后端重新编译并保存确认记录 |
| 新表与未来快照表重复 | 第一版确认记录只存摘要和资产 ID，未来快照表可通过 `context_confirmation_id` 关联 |
| 深度导入体验被打断 | 深度导入明确不接入参考资料确认弹窗 |
| 待确认对象污染正式正文 | 正文生成默认不包含待确认对象，用户需显式开启 |
| 用户误以为任务仍在运行 | 所有异步任务统一轮询并展示 `done` / `failed` / `cancelled` |
| 伪造进度造成误导 | 无真实 progress 时只显示 indeterminate，不显示百分比 |

## 14. 与领域文档的关系

本设计落实 `CONTEXT.md` 中以下领域决策：

- 候选创作资产可进入工作上下文，但不进入正史上下文。
- 手动 AI 操作必须展示并确认“AI 参考资料”。
- 深度导入保持自动化，由系统内部维护 working context。
- 用户可见文案使用“待确认对象”。
- 第一版保存摘要与资产 ID，不保存完整 rendered context。
- 待确认对象变更后只标记受影响结果，不自动重算。
