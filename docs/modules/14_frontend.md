# Module: frontend / 前端控制台

## 定位

前端是纯 Vanilla JS 单页面应用（SPA），无框架依赖。通过 REST API 与后端通信，提供命令行风格但易用的操作界面。

## 架构

SPA 入口 `index.html`，文件职责：`state.js`（Proxy 响应式）、`router.js`（两级路由）、`api.js`（14 个模块封装）、`app.js`（生命周期）、`views/`（12 个视图）。

## 核心设计

- **中文优先**：所有 UI 文本中文，无工程术语
- **命令行 + 按钮并行**：支持鼠标操作和键盘快捷键
- **纯文字为主**：表格 / 树 / 卡片 / 折叠面板 / ASCII 地图
- **低依赖**：Vanilla JS，无框架
- **响应式状态**：使用 JS Proxy 实现 Observable 模式
- **二级子视图**：每个 view 可含 subView（如 worldView 有 objects/candidates/relations/aliases）

## 视图列表

| 视图 | 功能 |
|------|------|
| projectView | 新建/选择/编辑/删除项目；回收站管理（列出/恢复/永久删除）；文件上传进度条 |
| worldView | 实体/候选/关系/别名 CRUD + 合并候选 + 去重检测 |
| geoView | 已移除（页面保留，数据由 world 模块管理） |
| characterView | 已移除（页面保留，功能迁入 worldView character 子标签） |
| memoryView | 全景查询 + 事件列表 + 快照管理 + 全量重建 |
| timelineView | 已移除（页面保留，功能迁入 worldView events 子标签） |
| outlineView | 三个子标签：剧情线/篇章纲/Scene。Scene 卡片 CRUD + 拖拽重排 + AI 结构生成 + 章节卡提取 |
| ragView | 检索 + 索引重建 + 状态 |
| contextView | 上下文编译 + 渲染 |
| reviewView | 已移除（页面保留） |
| writingView | 写作工作台：左侧 Scene 树导航 → 中间编辑器 → 右侧 Scene 卡面板；版本历史模态框；深度导入三阶段进度条（40%/40%/20%）；章节卡提取；Ctrl+S 保存 |
| generateView | 四大 Prompt 生成入口 |

## 写作工作台布局

```
┌─────────────────┬─────────────────┬──────────────────┐
│  Scene 树       │  编辑器         │  Scene 卡面板    │
│                  │                  │                  │
│ ├─ Scene 1      │  textarea       │  goal: xxx      │
│ │  ├─ 第1章     │                  │  conflict: xxx  │
│ │  ├─ 第2章     │                  │  emotional: xxx │
│ │  └─ 第3章     │                  │  must_happen:   │
│ ├─ Scene 2      │                  │  must_not:      │
│ └─ ...          │                  │  tag: rising    │
└─────────────────┴─────────────────┴──────────────────┘
```

## 状态保存机制

- 子标签记忆：`router.js` 维护 `_lastSubViewMap`，切换视图时恢复最后访问的子标签
- 编辑器内容保持：`state.js` 的 `viewStates` 命名空间独立存储各视图状态，`writingView` 切换时保存/恢复编辑器内容
- Scene 切换：编辑器内容自动保存到 `viewStates`，加载目标 Scene 的第一个 Chapter

## API 封装风格

- 统一 `request()` 函数：超时 / 错误映射 / FormData 自动处理
- 按模块分组：`api.projects.list()` / `api.world.listEntities()` / `api.imports.upload()`
- 查询字符串：`qs()` 辅助函数
- AI 抽取：`api.world.extractEntities()` / outline 生成

## 深度导入进度轮询

writingView 的深度导入按钮每 3 秒轮询 `GET /api/tasks/{task_id}`，显示三阶段进度条：
- Phase 1: "Scene 切分: X/Y 批已完成"
- Phase 2: "实体提取: X/Y 个 Scene"
- Phase 3: "结构分析..."
- 降级标记：黄色警告显示降级批次数

## XSS 防护

- 使用 textContent 渲染用户/AI 内容
- 对所有输出调用 `esc()` 转义
- 不使用 innerHTML 处理动态内容
