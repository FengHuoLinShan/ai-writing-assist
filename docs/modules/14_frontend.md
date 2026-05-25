# Module: frontend / 前端控制台（原设计以外新增）

## 定位

前端是纯 Vanilla JS 单页面应用（SPA），无框架依赖。通过 REST API 与后端通信，提供命令行风格但易用的操作界面。

## 架构

```text
frontend-console/
├── index.html        — 主页面 DOM
├── styles.css        — CSS 变量暗色主题
├── state.js          — Proxy 响应式状态管理
├── router.js         — view + subView 两级路由
├── api.js            — 13 个模块 API 封装
├── commands.js       — Vim 风格命令系统
├── app.js            — 事件绑定 / 快捷键 / 生命周期
└── views/            — 14 个视图
```

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
| characterView | 人物 CRUD + 知识边界 CRUD |
| memoryView | 记录列表 + 提案确认/拒绝 |
| timelineView | 事件 CRUD + 排序 |
| outlineView | 五标签：剧情线/篇章纲/章节卡/伏笔/揭示 |
| ragView | 检索 + 索引重建 + 状态 |
| contextView | 上下文编译 + 预算配置 |
| reviewView | 复查报告列表/详情 |
| writingView | 草稿编辑 + 导入（文件上传/历史记录）|
| generateView | 四大 Prompt 生成入口 |

## 侧边栏导航

```
项目
草稿导出 (含导入)
—— 创作核心 ——
世界对象
人物档案
剧情结构
地理历史
时间线
长期记忆
▸ 更多
  RAG 检索
  上下文
  结构复查
  生成中心
```

## API 封装风格

- 统一 `request()` 函数：超时 / 错误映射 / FormData 自动处理
- 按模块分组：`api.projects.list()` / `api.world.listEntities()` / `api.imports.upload()`
- 查询字符串：`qs()` 辅助函数

## XSS 防护

- 使用 textContent 渲染用户/AI 内容
- 对所有输出调用 `esc()` 转义
- 不使用 innerHTML 处理动态内容
