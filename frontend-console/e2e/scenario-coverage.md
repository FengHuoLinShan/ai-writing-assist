# 场景覆盖矩阵

> 本文档基于 `docs/核心业务场景与预期行为.md` 中的场景覆盖矩阵，结合当前 E2E 测试实际状态维护。
> 更新日期：2026-06-11

| 场景 | 当前优先轮次 | 后端主模块 | 前端主视图 | 必须覆盖的测试 | 当前状态 |
|------|--------------|------------|------------|----------------|----------|
| 场景 1 项目创建与管理 | R1 | `project` | `projectView` | project 单测 + project E2E | 🚧 部分覆盖 |
| 场景 2 文件上传与章节导入 | R1 | `imports`, `writing`, `rag` | `projectView`, `writingView` | imports 单测 + import E2E | 🚧 部分覆盖 |
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | `writingView` | workflow 集成 + deep-import E2E | 🚧 部分覆盖 |
| 场景 4 手工写作工作台 | R3 | `writing`, `outline`, `rag` | `writingView` | writing 单测 + writing E2E | 🚧 部分覆盖 |
| 场景 5 世界对象管理 | R5 | `world`, `memory` | `worldView` | world 单测 + world E2E | 🚧 部分覆盖 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | `outlineView` | outline 单测 + outline E2E | 🚧 部分覆盖 |
| A1 RAG 混合检索 | R6 | `rag` | `ragView` | rag 单测 + rag E2E | 🚧 部分覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | `contextView` | context 单测 + context E2E | 🚧 部分覆盖 |

## E2E 文件与场景映射

| E2E 文件 | 覆盖场景 | 说明 |
|----------|----------|------|
| `home.spec.js` | — | 首页加载、导航切换、快捷键、命令栏 |
| `project.spec.js` | 场景 1 | 创建项目、列表选择、编辑项目、删除项目（软删除）、点击切换项目 |
| `import.spec.js` | 场景 2 | 文件上传并解析（基础导入成功流） |
| `deep-import.spec.js` | 场景 3 | 启动深度导入弹窗、进度条、Mock 完成流、无章节时按钮隐藏 |
| `deep-import-real.spec.js` | 场景 3 | 真实深度导入三阶段进度与失败降级（非 Mock） |
| `writing.spec.js` | 场景 4 | 空状态、新建章节、编辑并暂存、发布、Scene 切换不丢内容、版本历史查看与恢复、断章更新左侧树、AI 提取章节卡弹窗、离线恢复 localStorage、多 Tab 冲突检测（草稿被删） |
| `world.spec.js` | 场景 5 | 对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签 |
| `world-relations-aliases.spec.js` | 场景 5 | 创建关系、创建别名（均为 `test.fixme`，后端 API 待补齐） |
| `outline-scenes.spec.js` | 场景 6 | Scene 卡默认标签、创建/编辑/删除 Scene 卡 |
| `outline-threads-arcs.spec.js` | 场景 6 | 创建/编辑/删除剧情线、创建/编辑/删除篇章纲 |
| `rag.spec.js` | A1 | 索引状态页面、搜索子标签、搜索空结果、重建索引按钮 |
| `context.spec.js` | A2 | 上下文编译页面加载、未选择项目警告、编译并显示结果 |
| `generate.spec.js` | — | 生成中心页面加载、选择生成类型、提交生成任务、未填写意图警告 |

## 覆盖状态详细说明

### ✅ 已覆盖

- **项目创建与删除**：`project.spec.js` 覆盖创建、列表、编辑、软删除、切换项目。
- **Scene 卡 CRUD**：`outline-scenes.spec.js` 覆盖创建、编辑、删除。
- **剧情线与篇章纲 CRUD**：`outline-threads-arcs.spec.js` 覆盖创建、编辑、删除。
- **基础 RAG 页面**：`rag.spec.js` 覆盖页面加载、搜索、重建索引按钮。
- **基础上下文编译**：`context.spec.js` 覆盖页面加载与编译调用。

### 🚧 部分覆盖

- **项目回收站**：`project.spec.js` 验证了软删除后列表消失，但未覆盖回收站列表（`GET /api/projects/recycle-bin`）和恢复/永久删除流程。
- **导入异常流**：`import.spec.js` 仅覆盖正常上传，未覆盖格式不支持（`.pdf` 400）、超大文件（413）、空文件/编码失败等异常流。
- **深度导入真实 workflow**：`deep-import.spec.js` 使用 Mock 加速，未覆盖真实三阶段推进、失败降级、重复导入确认、浏览器关闭后进度恢复。
- **写作工作台**：`writing.spec.js` 覆盖保存、版本历史、断章、Scene 切换，但未覆盖 409 多 Tab 版本冲突（预期版本号检测）、断章后 `scene_chunks` 物理映射更新、跨 Scene 光标切换右侧面板。
- **世界对象关系与别名**：`world-relations-aliases.spec.js` 中两个核心用例标记为 `test.fixme`，后端关系/别名 API 路由待补齐。
- **实体合并、去重确认、版本回滚**：无 E2E 覆盖。
- **大纲拖拽排序、AI 生成结构、伏笔管理**：无 E2E 覆盖。

### ⏳ 待实现

- 回收站恢复与永久删除 E2E
- 导入异常流 E2E（格式错误、超大文件、空文件）
- 真实深度导入三阶段进度与失败降级 E2E
- 409 多 Tab 冲突 E2E
- 关系与别名 CRUD E2E（解除 `test.fixme` 后）
- 实体合并与回滚 E2E
- 大纲拖拽排序、AI 生成结构、伏笔状态流转 E2E
- 父子检索、embedding 降级 warning E2E
