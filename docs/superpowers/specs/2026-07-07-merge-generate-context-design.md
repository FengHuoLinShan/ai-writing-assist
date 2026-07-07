# 生成中心与上下文页面融合设计

## 状态

- 作者：Kimi Code CLI（Brainstorming + 用户确认）
- 日期：2026-07-07
- 版本：v1.0
- 范围：前端控制台（frontend-console），不修改后端 API

## 背景

当前前端控制台把 AI 相关能力拆成了两个独立页面：

- **生成中心**（`generateView.js`）：自由聊天、对象草稿生成、Prompt 模板库。
- **上下文 / 编译**（`contextView.js`）：配置上下文参数、编译、预览/导出 Markdown。

用户反馈上下文页面更像「开发者工具」，希望在 AI 生成页面获得所有 AI 对话与生成入口。因此本设计以生成中心为主体，把上下文能力收编进来，消除独立的「编译」导航入口。

## 目标

1. 侧边栏只保留一个「生成」入口。
2. 原上下文页面的任务模板（生成剧情线、润色正文、检查冲突）成为生成中心的一等公民。
3. 上下文编译从「独立工作流」退居为「生成流程的透明/调试视角」。
4. 不引入新的后端接口，完全复用现有 API。
5. 旧 `#context` 路由可平滑重定向到新页面。

## 非目标

- 本次设计不包含后端接口变更。
- 不包含任务执行后的真正生成/润色/冲突检查后端逻辑（仅先完成上下文编译与展示，后续可扩展）。
- 不改动写作台、世界对象等其他页面。

## 当前能力对照

| 能力 | 生成中心 | 上下文 |
|---|---|---|
| 核心交互 | 自由聊天 + 生成对象草稿 | 配置参数 + 编译上下文 |
| 任务模板 | 对象类型模板（人物/事件/物品…） | 任务模板（生成剧情线/润色/冲突检查） |
| 上下文控制 | 附带正文章节、质量模式 | 范围、揭示模式、预算、关联对象/人物 |
| 结果处理 | 保存为 world 对象草稿 | 预览/复制/导出 Markdown |
| 导航位置 | 侧边栏「生成」 | 侧边栏「编译」 |

## 总体方案

生成中心内部采用**两层标签**：

```
生成中心
├── 生成（一级标签）
│   ├── 自由对话（二级标签，默认）
│   ├── 任务（二级标签，承接原上下文页任务能力）
│   └── 上下文预览（二级标签，承接原上下文页输出能力）
└── 模板库（一级标签，保持现有模板库不变）
```

侧边栏删除「编译」入口；原 `#context` 路由重定向到 `#generate?tab=task`。

## 详细设计

### 1. 导航与信息架构

#### 1.1 侧边栏

- 删除 `index.html` 中 `data-view="context"` 的导航项。
- 保留 `data-view="generate"`，tooltip 仍为「生成中心」。

#### 1.2 路由

- `routes.context` 从 `router.js` 中移除。
- `registerView("context", ...)` 不再注册；旧 `#context` hash 进入时，由 `initRouter` 或 `onpopstate` 处理为 `navigate("generate", null, true)` 并附加 query `tab=task`。
- `generateView` 在 `render()` 时读取 URL query 参数决定默认二级标签。

### 2. 自由对话标签

基本保持现有 `generateView.js` 的「生成」页内容：

- 聊天消息区、输入框、发送 / 生成对象草稿。
- 右侧模板选择、变量表单、质量模式、附带正文。
- 结果卡片展示生成的 world 对象草稿。

**唯一新增**：结果卡片底部增加 subtle 链接「查看此次生成使用的上下文」，点击后：

1. 切换到「上下文预览」标签。
2. 使用当前 `messages` + `selectedTemplate` + `selectedChapters` + `qualityMode` 调用 `api.context.compile`。
3. 展示编译结果。

### 3. 任务标签

原上下文页面的核心迁移目标。

#### 3.1 布局

左右两栏：

```
┌─────────────────────────────┬─────────────────────────────┐
│  任务选择                     │  参数 / 结果                 │
│  ┌─────────────────────┐    │  ┌─────────────────────┐    │
│  │ 生成剧情线           │    │  │ 任务描述             │    │
│  │ 润色正文             │    │  │ [_______________]    │    │
│  │ 检查冲突             │    │  ├─────────────────────┤    │
│  │ + 自定义任务         │    │  │ 高级 ▾               │    │
│  └─────────────────────┘    │  │ 范围 / 揭示 / 预算…  │    │
│                              │  ├─────────────────────┤    │
│                              │  │ [执行任务] [预览上下文]│   │
│                              │  ├─────────────────────┤    │
│                              │  │ 结果 / 输出          │    │
│                              │  └─────────────────────┘    │
└─────────────────────────────┴─────────────────────────────┘
```

#### 3.2 任务卡片

| 卡片 | 默认任务描述 | 默认范围 | 默认揭示模式 |
|---|---|---|---|
| 生成剧情线 | 基于当前设定梳理主线、支线和伏笔推进 | arc | author_full |
| 润色正文 | 保持设定一致，优化语气、节奏和场景细节 | chapter | author_safe |
| 检查冲突 | 检查当前章节是否存在人物、世界对象或剧情设定冲突 | chapter | author_full |
| 自定义任务 | （空，由用户填写） | arc | author_safe |

点击卡片后右侧表单自动填充默认值，用户可再修改。

#### 3.3 参数表单

- **任务描述**（必填，textarea，2 行）：由卡片填充。
- **高级设置**（默认折叠的 `<details>`）：
  - 范围（select）：project / world / world_character / arc / chapter / full。
  - 相关对象（input，逗号分隔 world_entity ID）。
  - 相关人物（input，逗号分隔 character ID）。
  - 章节索引（number）。
  - Scene ID（input）。
  - 预算 tokens（number，默认 4000，min 500 / max 32000）。
  - 揭示模式（select）：author_safe / author_full / reader / character。

#### 3.4 动作按钮

- **执行任务**：调用 `api.context.compile`，成功后自动切换到「上下文预览」标签展示结果；未来可在此接入真正的剧情线/润色/冲突检查生成 API。
- **预览上下文**：仅调用 `api.context.compile`，成功后切换到「上下文预览」标签展示结果。

#### 3.5 结果展示

执行任务或预览上下文后，结果在「上下文预览」标签展示，沿用原上下文页面的输出：

- 已加载段落数、范围、揭示模式、token 占用。
- sections 表格（Tier / Section / Tokens / Truncated）。
- 已驱逐段落、已截断段落提示。
- 警告列表。
- 「渲染 Markdown」按钮，调用 `api.context.render`。
- 「复制」「导出」按钮。
- **新增**：「应用到聊天」按钮，把当前任务描述和编译结果一键带入「自由对话」标签。

### 4. 上下文预览标签

定位为**最近一次 AI 操作的上下文透视**，而非独立工作流。

#### 4.1 触发方式

1. 从「自由对话」点击「查看此次生成使用的上下文」。
2. 从「任务」点击「预览上下文」后切换进入。
3. 在「任务」点击「执行任务」并成功后自动切换进入。
4. 手动切换标签，显示最近一次缓存的编译结果。

#### 4.2 页面内容

- 顶部来源说明：「来自：自由对话」或「来自任务：生成剧情线」。
- 中间只读展示上下文摘要表格 + Markdown 渲染。
- 操作：复制 Markdown、导出 `.md`、返回来源标签。

#### 4.3 空状态

> 还未执行任何 AI 生成或上下文编译。去「自由对话」聊天，或在「任务」里执行一个任务。

### 5. 状态管理

#### 5.1 新增内部状态（`generateView`）

```javascript
_generateSubTab: "chat" | "task" | "preview"   // 默认 "chat"
_taskPreset: "plot" | "polish" | "conflict_check" | "custom"
_taskForm: {
  task: string,
  scope: string,
  reveal_mode: string,
  budget_tokens: number,
  entity_ids?: string[],
  character_ids?: string[],
  chapter_index?: number,
  scene_id?: string,
}
_lastContextBundle: object | null
_lastContextSource: "chat" | "task"
_lastContextMarkdown: string | null
```

#### 5.2 持久化

在现有 `_persistState` / `_restoreState` 中增加：

```javascript
{
  // ... 已有字段
  generateSubTab: this._generateSubTab,
  taskPreset: this._taskPreset,
  taskForm: this._taskForm,
  lastContextBundle: this._lastContextBundle,
  lastContextSource: this._lastContextSource,
  // 注意：不持久化完整 Markdown，只持久化摘要/参数
}
```

### 6. 数据流

#### 6.1 自由对话 → 上下文预览

```
用户发送消息 / 点击生成对象
  → 调用 api.generate.objectDraftChat / generateObjectDraft
  → 点击「查看上下文」
  → 用当前 messages + template + selectedChapters 调用 api.context.compile
  → 切换到上下文预览标签展示
```

#### 6.2 任务 → 结果

```
用户选择任务卡片
  → 填充 _taskForm
  → 用户修改参数（可选）
  → 点击「执行任务」或「预览上下文」
  → 调用 api.context.compile(payload)
  → 成功后切换到「上下文预览」标签展示编译结果
  → （执行任务时）后续可调用真正的生成/润色/检查 API
```

#### 6.3 路由重定向

```
访问 #context
  → router 识别旧路由
  → navigate("generate", null, true) 并附加 query tab=task
  → generateView 渲染任务标签
```

### 7. API 复用

无需新增后端接口：

- `api.generate.objectDraftChat` — 自由对话。
- `api.generate.generateObjectDraft` — 生成对象草稿。
- `api.context.compile` — 编译上下文。
- `api.context.render` — 渲染 Markdown。

未来任务执行可扩展：

- `api.outline.generatePlotThreads`
- `api.writing.polish`
- `api.world.checkConflicts`

### 8. 错误处理

沿用现有模式：

- 无项目选择：`toast("请先选择项目", "warning")`。
- 任务描述为空：`toast("请输入任务描述", "warning")`。
- 角色视角缺少人物：`toast("角色视角模式必须选择或输入视角人物 ID", "warning")`。
- 编译失败：在右侧结果区显示红色错误块，不弹 toast 打断。

新增：

- 旧 `#context` 路由重定向失败时静默 fallback 到 `#generate?tab=chat`。

### 9. 响应式

- 任务标签在 900px 以下改为单栏：任务卡片在上，参数/结果在下。
- 上下文预览的 Markdown pre 块保持横向滚动。
- 二级标签在移动端可横向滚动（`overflow-x: auto`）。

### 10. 测试策略

- `generateView.test.js`：
  - 保持现有自由对话用例。
  - 新增：任务标签渲染、任务卡片填充表单、编译成功展示结果、预览上下文切换标签。
- `contextView.test.js`：
  - 整体迁移为 `generateView` 任务标签测试；`contextView.js` 文件后续可删除。
- `context.spec.js` / `generate.spec.js`：
  - 合并为 `generate.spec.js`，覆盖三种二级标签。

## 迁移清单

| 步骤 | 文件 | 操作 |
|---|---|---|
| 1 | `index.html` | 删除「编译」导航项 |
| 2 | `router.js` | 移除 `context` 路由；增加旧路由重定向 |
| 3 | `views/contextView.js` | 删除（或先标记 deprecated） |
| 4 | `views/generateView.js` | 新增二级标签、任务标签、上下文预览标签 |
| 5 | `styles.css` | 补充任务标签、二级标签控件的样式 |
| 6 | 测试文件 | 迁移/合并 context 相关测试 |

## 决策记录

- **为什么删除「编译」导航而不是把生成中心合并到上下文？** 用户明确表示上下文页面像开发者工具，生成中心才是作者体感上的 AI 入口。
- **为什么保留「上下文预览」标签而不是完全隐藏？** 透明度是现有系统的卖点之一，完全隐藏会损失「AI 到底看到了什么」的调试能力，但把它从主工作流降为透视视角更符合产品定位。
- **为什么任务标签先只做上下文编译？** 真正的剧情线生成、润色、冲突检查后端能力可能尚未 ready，先做上下文编译可以保证前端改动可独立交付、可测试。

## 附录：URL 约定

| URL | 行为 |
|---|---|
| `#generate` | 进入生成中心，默认二级标签=自由对话 |
| `#generate?tab=chat` | 进入自由对话 |
| `#generate?tab=task` | 进入任务标签 |
| `#generate?tab=task&preset=plot` | 进入任务标签并选中「生成剧情线」卡片 |
| `#generate?tab=preview` | 进入上下文预览标签 |
| `#context` | 重定向到 `#generate?tab=task` |

---

*本设计由用户确认后保存为 spec，后续实现需再制定详细计划。*
