# 场景覆盖矩阵

> 本文档基于 `docs/核心业务场景与预期行为.md` 中的场景覆盖矩阵，结合当前 E2E 测试实际状态维护。
> 更新日期：2026-07-01（前端测试反馈优化后）

## 图例

- `✅ 场景闭环`：文档中该场景的主要正常流、异常流、边界流均有自动化断言。
- `🟡 部分覆盖`：已有页面/API/基础 E2E，但至少一个文档化操作路径未断言或未实现。
- `⏳ 待实现`：功能或对应 E2E 测试尚未实现
- `🧭 Placeholder`：仅记录待实现 chaos 场景元数据，不计入产品行为覆盖

| 场景 | 当前优先轮次 | 后端主模块 | 前端主视图 | 必须覆盖的测试 | 当前状态 |
|------|--------------|------------|------------|----------------|----------|
| 场景 1 项目创建与管理 | R1 | `project` | `projectView` | project 单测 + project E2E | ✅ 场景闭环 |
| 场景 2 文件上传与章节导入 | R1 | `imports`, `writing`, `rag` | `projectView`, `writingView` | imports 单测 + import E2E | ✅ 场景闭环 |
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | `writingView` | workflow 集成 + deep-import E2E | 🟡 部分覆盖 |
| 场景 4 手工写作工作台 | R3 | `writing`, `outline`, `rag` | `writingView` | writing 单测 + writing E2E | ✅ 场景闭环 |
| 场景 5 世界对象管理 | R5 | `world`, `memory` | `worldView` | world 单测 + world E2E | ✅ 场景闭环 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | `outlineView` | outline 单测 + outline E2E | 🟡 部分覆盖 |
| A1 RAG 混合检索 | R6 | `rag` | `ragView` | rag 单测 + rag E2E | 🟡 部分覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | `contextView` | context 单测 + context E2E | 🟡 部分覆盖 |

## E2E 文件与场景映射

| E2E 文件 | 覆盖场景 | 说明 |
|----------|----------|------|
| `home.spec.js` | — | 首页加载、导航切换、快捷键、命令栏；未纳入本次运行 |
| `project.spec.js` | 场景 1 | 创建项目、列表选择、编辑项目、删除项目（软删除）、点击切换项目；未纳入本次运行 |
| `project-recycle-bin.spec.js` | 场景 1 | 软删除后进入回收站可恢复、永久删除后不可恢复；2/2 通过 |
| `project-chaos.spec.js` | 场景 1 | 危险操作取消路径：取消永久删除后项目仍保留在回收站；1/1 通过 |
| `import.spec.js` | 场景 2 | 文件上传并解析（基础导入成功流）；1/1 通过 |
| `import-errors.spec.js` | 场景 2 | 格式不支持、超大文件前端拦截、空文件导入失败且不创建章节；3/3 通过 |
| `import-workflow-chaos.spec.js` | 场景 2/3 | 🧭 Placeholder metadata only；不计入导入/深度导入产品覆盖 |
| `deep-import.spec.js` | 场景 3 | 从项目视图导入后启动深度导入、进度条路由切换后恢复、无章节时不显示按钮；3/3 通过 |
| `deep-import-resilient.spec.js` | 场景 3 | 新版深度导入 Phase 0 / Phase 1a / Phase 1b 进度、422 阻断/降级、localStorage 恢复、手动继续/放弃恢复、移动端进度可读；7/7 通过 |
| `deep-import-worker.spec.js` | 场景 3 | guarded worker E2E：提交异步深度导入后关闭页面，任务继续由 worker 完成；需 `RUN_WORKER_E2E=1` 和运行中的 backend worker |
| `deep-import-real.spec.js` | 场景 3 | 真实同步深度导入（`POST /api/imports/deep/sync`），不覆盖新版 Phase 0 / Phase 1a / Phase 1b 韧性策略 |
| `writing.spec.js` | 场景 4 | 空状态、新建章节、编辑并暂存、发布、Scene 切换不丢内容、版本历史查看与恢复、断章更新左侧树、光标位置联动右侧 Scene 卡面板、AI 提取章节卡弹窗、离线恢复 localStorage、多 Tab 冲突检测；11/11 通过 |
| `writing-conflict.spec.js` | 场景 4 | 409 冲突 — 其他会话已更新草稿版本；1/1 通过 |
| `world.spec.js` | 场景 5 | 对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签、实体合并、实体回滚、人物知识边界；9/9 通过 |
| `world-relations-aliases.spec.js` | 场景 5 | 创建关系、创建别名；2/2 通过 |
| `outline-scenes.spec.js` | 场景 6 | Scene 卡默认标签、创建/编辑/删除 Scene 卡、上移/下移重排、AI 生成结构弹窗、伏笔创建/状态更新、揭示创建；8/8 通过 |
| `outline-threads-arcs.spec.js` | 场景 6 | 创建/编辑/删除剧情线、创建/编辑/删除篇章纲；6/6 通过 |
| `rag.spec.js` | A1 | 索引状态页面、搜索子标签、搜索空结果、真实 RAG chunk UI 召回、embedding 降级元数据与 warning、重建索引按钮；5/5 通过 |
| `context.spec.js` | A2 | 上下文编译页面加载、未选择项目警告、编译并显示结果、角色揭示模式视角人物校验与提交契约；5/5 通过 |
| `rag-context-chaos.spec.js` | A1/A2 | 🧭 Placeholder metadata only；不计入 RAG/Context 产品覆盖 |
| `generate.spec.js` | — | 生成中心页面加载、选择生成类型、提交生成任务、未填写意图警告；未纳入本次运行 |

## 覆盖状态详细说明

### ✅ 场景闭环

- **项目创建与管理**：`project.spec.js` 与 `project-recycle-bin.spec.js` 覆盖创建、列表选择、编辑、软删除、回收站恢复和永久删除。创建和列表选择均进入写作视图（`#/workbench/:projectId/writing`）。
- **文件上传与基础导入**：`import.spec.js`（1/1）与 `import-errors.spec.js`（3/3）覆盖基础导入成功流、格式不支持、超大文件前端拦截、空文件导入失败且不创建章节。
- **手工写作工作台**：`writing.spec.js`（11/11）与 `writing-conflict.spec.js`（1/1）全部通过；覆盖写作核心流程与 409 冲突检测。
- **世界对象管理**：`world.spec.js`（9/9）与 `world-relations-aliases.spec.js`（2/2）全部通过；覆盖对象 CRUD、关系、别名、合并、回滚、知识边界。

### 🟡 部分覆盖（功能存在但 E2E 未完整断言）

以下功能已有页面/API/基础 E2E，但仍有文档化操作路径未完整断言或未实现：

- **深度导入流水线**：当前覆盖异步任务提交、轮询 UI、刷新/路由恢复、新版 Phase 0 / Phase 1a / Phase 1b 韧性进度、422 阻断/降级、手动恢复提示，以及 guarded worker 浏览器关闭场景。
- **真实异步深度导入质量验收**：`deep-import-real.spec.js` 当前仅覆盖同步成功流；前 60 章真实 LLM 质量验收由 `backend/modules/imports/tests/test_deep_import_real_llm.py` 提供，默认跳过，需显式环境变量开启。
- **伏笔/揭示高级管理**：基础创建、删除与伏笔状态更新已有覆盖；回收率统计、积压高亮、手动标记回收仍待实现/验收。
- **RAG 父子检索**：真实 chunk UI 召回与 embedding 降级 warning 已覆盖；父子检索补齐父 Scene 元数据和 Delta 摘要仍待实现/验收。
- **上下文人物视角隐藏真相转换**：前端已覆盖 `reveal_mode=character` 与 `viewpoint_character_id` 提交契约；真实数据下不同 `reveal_mode` 的内容差异主要由后端 context 测试覆盖，浏览器端仍未完整断言预算裁剪和 hidden_truth 差异。

## 验证命令与结果

```bash
# 前端单元测试
cd frontend-console && npm test
# 30 files, 423 tests passed

# 后端聚焦模块测试
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
# 287 passed, 1 existing warning

# 历史 Playwright 场景套件基线（APP_ENV=test；本表用于覆盖映射，完整结果需按当前分支重跑刷新）
cd frontend-console && npx playwright test project.spec.js project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
# 历史记录：61 passed, 0 failed

# 前端反馈优化定向 Playwright
cd frontend-console && npx playwright test map.spec.js -g "should create a world map" --reporter=list
# 1 passed
BACKEND_PORT=8010 FRONTEND_PORT=8090 npx playwright test project-chaos.spec.js --reporter=list
# 1 passed；若 sandbox 阻断本地 PostgreSQL 5207，需要提升权限或先运行 backend/scripts/doctor.py --json
BACKEND_PORT=8011 FRONTEND_PORT=8091 npx playwright test map.spec.js scene-workbench.spec.js world.spec.js project-chaos.spec.js import-workflow-chaos.spec.js rag-context-chaos.spec.js --reporter=list
# 30 passed；使用隔离端口避免复用默认端口上的旧 backend/frontend server

# Lint
cd frontend-console && node --check app.js && node --check api.js
# exit 0
cd /Users/tywww/Desktop/项目/ai-writing-assist && make lint
# 仍存在 105 条预存 lint 警告（主要为 E402/E501/F841/N8xx/UP040），与本轮修复无关；本轮修改的 backend 文件已通过 ruff check。
```
