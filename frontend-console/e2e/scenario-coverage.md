# 场景覆盖矩阵

> 本文档基于 `docs/核心业务场景与预期行为.md` 中的场景覆盖矩阵，结合当前 E2E 测试实际状态维护。
> 更新日期：2026-06-12（Task 4 实测修正后）

## 图例

- `✅ 已覆盖`：该场景下所有 E2E 测试用例均通过
- `🚧 已实现，E2E 待稳定`：功能已实现，但仍有部分 E2E 测试失败
- `⏳ 待实现`：功能或对应 E2E 测试尚未实现

| 场景 | 当前优先轮次 | 后端主模块 | 前端主视图 | 必须覆盖的测试 | 当前状态 |
|------|--------------|------------|------------|----------------|----------|
| 场景 1 项目创建与管理 | R1 | `project` | `projectView` | project 单测 + project E2E | 🚧 已实现，E2E 待稳定 |
| 场景 2 文件上传与章节导入 | R1 | `imports`, `writing`, `rag` | `projectView`, `writingView` | imports 单测 + import E2E | ✅ 已覆盖 |
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | `writingView` | workflow 集成 + deep-import E2E | 🚧 已实现，E2E 待稳定 |
| 场景 4 手工写作工作台 | R3 | `writing`, `outline`, `rag` | `writingView` | writing 单测 + writing E2E | 🚧 已实现，E2E 待稳定 |
| 场景 5 世界对象管理 | R5 | `world`, `memory` | `worldView` | world 单测 + world E2E | 🚧 已实现，E2E 待稳定 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | `outlineView` | outline 单测 + outline E2E | 🚧 已实现，E2E 待稳定 |
| A1 RAG 混合检索 | R6 | `rag` | `ragView` | rag 单测 + rag E2E | ✅ 已覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | `contextView` | context 单测 + context E2E | ✅ 已覆盖 |

## E2E 文件与场景映射

| E2E 文件 | 覆盖场景 | 说明 |
|----------|----------|------|
| `home.spec.js` | — | 首页加载、导航切换、快捷键、命令栏；未纳入本次运行 |
| `project.spec.js` | 场景 1 | 创建项目、列表选择、编辑项目、删除项目（软删除）、点击切换项目；未纳入本次运行 |
| `import.spec.js` | 场景 2 | 文件上传并解析（基础导入成功流；1/1 通过） |
| `deep-import.spec.js` | 场景 3 | 2/3 通过；通过：深度导入进度条在路由切换后恢复、无章节时深度导入按钮不显示；失败：从项目视图导入小说后启动深度导入 |
| `project-recycle-bin.spec.js` | 场景 1 | 软删除后进入回收站可恢复、永久删除后不可恢复；0/2 通过，回收站恢复与永久删除 E2E 仍失败 |
| `import-errors.spec.js` | 场景 2 | 格式不支持（`test.pdf`）、超大文件（51MB 触发前端 50MB 限制）、空文件（0 字节）；3/3 通过 |
| `deep-import-real.spec.js` | 场景 3 | 真实同步深度导入（`POST /api/imports/deep/sync`），不覆盖浏览器关闭恢复与后台任务轮询 |
| `writing.spec.js` | 场景 4 | 空状态、新建章节、编辑并暂存、发布、Scene 切换不丢内容、版本历史查看与恢复、断章更新左侧树、光标位置联动右侧 Scene 卡面板、AI 提取章节卡弹窗、离线恢复 localStorage、多 Tab 冲突检测；8/11 通过，失败：新 Scene 创建和断章更新左侧树、光标位置联动右侧 Scene 卡面板、AI 提取章节卡按钮和对话框 |
| `world.spec.js` | 场景 5 | 对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签、实体合并、实体回滚、人物知识边界；9/9 通过 |
| `world-relations-aliases.spec.js` | 场景 5 | 创建关系（通过）、创建别名（失败）；1/2 通过 |
| `outline-scenes.spec.js` | 场景 6 | Scene 卡默认标签、创建/编辑/删除 Scene 卡、上移/下移重排、AI 生成结构弹窗、伏笔与揭示管理；5/7 通过，失败：上移/下移 Scene 卡调整顺序、AI 生成结构弹窗 |
| `outline-threads-arcs.spec.js` | 场景 6 | 创建/编辑/删除剧情线、创建/编辑/删除篇章纲；6/6 通过 |
| `rag.spec.js` | A1 | 索引状态页面、搜索子标签、搜索空结果、重建索引按钮；4/4 通过 |
| `context.spec.js` | A2 | 上下文编译页面加载、未选择项目警告、编译并显示结果；3/3 通过 |
| `generate.spec.js` | — | 生成中心页面加载、选择生成类型、提交生成任务、未填写意图警告；未纳入本次运行 |

## 覆盖状态详细说明

### ✅ 已覆盖

- **文件上传与基础导入**：`import.spec.js`（1/1）与 `import-errors.spec.js`（3/3）全部通过；覆盖基础导入成功流、格式不支持、超大文件前端拦截、空文件解析为空章节。
- **世界对象管理**：`world.spec.js`（9/9）全部通过；覆盖对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签、实体合并、实体回滚、人物知识边界。
- **剧情线与篇章纲 CRUD**：`outline-threads-arcs.spec.js`（6/6）全部通过；覆盖创建、编辑、删除剧情线与篇章纲。
- **基础 RAG 页面**：`rag.spec.js`（4/4）全部通过；覆盖页面加载、搜索、搜索空结果、重建索引按钮。
- **基础上下文编译**：`context.spec.js`（3/3）全部通过；覆盖页面加载、未选择项目警告、编译并显示结果。

### 🚧 部分覆盖

- **项目回收站**：`project-recycle-bin.spec.js`（0/2）失败；恢复与永久删除流程均未通过验收，详见上表。
- **深度导入流水线**：`deep-import.spec.js`（2/3）部分通过；具体通过/失败用例见上表。
- **写作工作台**：`writing.spec.js`（8/11）部分通过；失败用例详见上表。
- **写作版本冲突**：`writing-conflict.spec.js`（0/1）失败：409 冲突 — 其他会话已更新草稿版本。
- **世界对象关系、别名**：`world-relations-aliases.spec.js`（1/2）部分通过；失败用例详见上表。
- **大纲 Scene 卡**：`outline-scenes.spec.js`（5/7）部分通过；失败用例详见上表。

### ⏳ 待实现

- 回收站恢复与永久删除 E2E（`project-recycle-bin.spec.js` 全部失败）
- 真实深度导入三阶段进度与失败降级 E2E（`deep-import-real.spec.js` 当前仅覆盖同步成功流，未覆盖失败降级与后台异步轮询）
- 409 多 Tab 冲突 E2E（`writing-conflict.spec.js` 失败）
- 写作工作台断章、光标联动、AI 提取章节卡修复后的 E2E 稳定
- 大纲自由拖拽排序、AI 生成结构真实 LLM 断言、揭示阶段编辑 UI
- 父子检索、embedding 降级 warning E2E
