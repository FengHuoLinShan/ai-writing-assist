# Module: frontend / 前端控制台（原设计以外新增）

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
| projectView | 新建/选择/编辑/删除项目 |
| worldView | 对象/候选/关系/别名 CRUD + 合并候选 |
| geoView | 地点树/关系边/历史时期 |
| characterView | 人物 CRUD + 知识边界 CRUD + AI 抽取（全部更新/单人物） + AI 建议对比确认 |
| memoryView | 记录列表 + 提案确认/拒绝 |
| timelineView | 事件 CRUD + 排序（v3 中 API 已迁移至 /api/world/events） |
| outlineView | 五标签 + 统一提取面板（世界对象抽取/剧情线生成/章节卡提取）|
| ragView | 检索 + 索引重建 + 状态 |
| contextView | 上下文编译 + 预算配置 |
| reviewView | 复查报告列表/详情 |
| writingView | 手动工作台（章节树+编辑器+细纲面板）+ 深度导入 + 章节卡提取 |
| generateView | 四大 Prompt 生成入口 |

## 状态保存机制

- 子标签记忆：`router.js` 维护 `_lastSubViewMap`，切换视图时恢复最后访问的子标签
- 编辑器内容保持：`state.js` 的 `viewStates` 命名空间独立存储各视图状态，`writingView` 切换时保存/恢复编辑器内容

## API 封装风格

- 统一 `request()` 函数：超时 / 错误映射 / FormData 自动处理
- 按模块分组：`api.projects.list()` / `api.world.listEntities()` / `api.imports.upload()`
- 查询字符串：`qs()` 辅助函数
- AI 抽取：`api.character.extract()` / `extractAll()` / `getSuggestions()` / `applySuggestions()`

## XSS 防护

- 使用 textContent 渲染用户/AI 内容
- 对所有输出调用 `esc()` 转义
- 不使用 innerHTML 处理动态内容
