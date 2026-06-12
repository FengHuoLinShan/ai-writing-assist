# 场景覆盖矩阵

> 本文档基于 `docs/核心业务场景与预期行为.md` 中的场景覆盖矩阵，结合当前 E2E 测试实际状态维护。
> 更新日期：2026-06-12

| 场景 | 当前优先轮次 | 后端主模块 | 前端主视图 | 必须覆盖的测试 | 当前状态 |
|------|--------------|------------|------------|----------------|----------|
| 场景 1 项目创建与管理 | R1 | `project` | `projectView` | project 单测 + project E2E | ✅ 已覆盖 |
| 场景 2 文件上传与章节导入 | R1 | `imports`, `writing`, `rag` | `projectView`, `writingView` | imports 单测 + import E2E | 🚧 部分覆盖 |
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | `writingView` | workflow 集成 + deep-import E2E | 🚧 部分覆盖 |
| 场景 4 手工写作工作台 | R3 | `writing`, `outline`, `rag` | `writingView` | writing 单测 + writing E2E | 🚧 部分覆盖 |
| 场景 5 世界对象管理 | R5 | `world`, `memory` | `worldView` | world 单测 + world E2E | 🚧 部分覆盖 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | `outlineView` | outline 单测 + outline E2E | 🚧 部分覆盖 |
| A1 RAG 混合检索 | R6 | `rag` | `ragView` | rag 单测 + rag E2E | ✅ 已覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | `contextView` | context 单测 + context E2E | ✅ 已覆盖 |

## E2E 文件与场景映射

| E2E 文件 | 覆盖场景 | 说明 |
|----------|----------|------|
| `home.spec.js` | — | 首页加载、导航切换、快捷键、命令栏 |
| `project.spec.js` | 场景 1 | 创建项目、列表选择、编辑项目、删除项目（软删除）、点击切换项目 |
| `import.spec.js` | 场景 2 | 文件上传并解析（基础导入成功流） |
| `deep-import.spec.js` | 场景 3 | 启动深度导入弹窗、进度条、Mock 完成流、无章节时按钮隐藏 |
| `deep-import-real.spec.js` | 场景 3 | 真实深度导入三阶段进度与失败降级（非 Mock） |
| `writing.spec.js` | 场景 4 | 空状态、新建章节、编辑并暂存、发布、Scene 切换不丢内容、版本历史查看与恢复、断章更新左侧树、光标位置联动右侧 Scene 卡面板、AI 提取章节卡弹窗、离线恢复 localStorage、多 Tab 冲突检测（当前验证草稿被删后 404；409 expected-version 冲突 E2E 待补充） |
| `world.spec.js` | 场景 5 | 对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签、实体合并、实体回滚（`test.fixme`）、人物知识边界 |
| `world-relations-aliases.spec.js` | 场景 5 | 创建关系、创建别名（已解除 `test.fixme`，对应后端端点 `/api/world/relations` 与 `/api/world/aliases`） |
| `outline-scenes.spec.js` | 场景 6 | Scene 卡默认标签、创建/编辑/删除 Scene 卡、上移/下移重排、AI 生成结构弹窗、伏笔/揭示管理（`test.fixme`） |
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
- **写作工作台 / 章节切分**：后端 `split_chapter_at_offset` 与前端 `writingView` 单元测试已覆盖切分、后续章节索引位移和 `scene_chunks` 重映射；`writing.spec.js` 已验证断章后左侧 Scene 树更新以及光标位置联动右侧 Scene 卡面板。
- **世界对象关系、别名**：关系/别名 E2E 已解除 `test.fixme`，对应后端端点 `/api/world/relations` 与 `/api/world/aliases`。
- **世界对象合并与回滚**：`world.spec.js` 已新增实体合并 E2E；实体回滚因缺少便捷的 TextArchive / revision 种子方式，仍标记为 `test.fixme`。
- **人物知识边界**：`world.spec.js` 已新增为人物添加知识边界 E2E。
- **大纲拖拽排序、AI 生成结构、伏笔管理**：当前 UI 提供"上移/下移"按钮式重排与"AI 生成结构"弹窗，已覆盖基础路径；自由拖拽排序、真实 LLM 生成、伏笔/揭示管理面板仍 deferred。

### ⏳ 待实现

- 回收站恢复与永久删除 E2E
- 导入异常流 E2E（格式错误、超大文件、空文件）
- 真实深度导入三阶段进度与失败降级 E2E
- 409 多 Tab 冲突 E2E
- 实体回滚 E2E（需后端在实体更新时自动写入 TextArchive 或暴露快照种子接口）
- 大纲自由拖拽排序、AI 生成结构真实 LLM 断言、伏笔/揭示管理面板 E2E
- 父子检索、embedding 降级 warning E2E
