# 场景覆盖矩阵

> 本文档基于 `docs/核心业务场景与预期行为.md` 中的场景覆盖矩阵，结合当前 E2E 测试实际状态维护。
> 更新日期：2026-07-19（Vue 前端路由迁移完成后）

## 图例

- `✅ 场景闭环`：文档中该场景的主要正常流、异常流、边界流均有自动化断言。
- `🟡 部分覆盖`：已有页面/API/基础 E2E，但至少一个文档化操作路径未断言或未实现。
- `⏳ 待实现`：功能或对应 E2E 测试尚未实现

| 场景 | 当前优先轮次 | 后端主模块 | 前端主视图 | 必须覆盖的测试 | 当前状态 |
|------|--------------|------------|------------|----------------|----------|
| 场景 1 项目创建与管理 | R1 | `project` | Vue 项目视图 | project 单测 + project E2E | ✅ 场景闭环 |
| 场景 2 文件上传与章节导入 | R1 | `imports`, `writing`, `rag` | 项目视图、Vue 写作工作台 | imports 单测 + import E2E | ✅ 场景闭环 |
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | Vue 写作工作台 | workflow 集成 + deep-import E2E | 🟡 部分覆盖 |
| 场景 4 手工写作工作台 | R3 | `writing`, `outline`, `rag` | Vue 写作工作台 | writing 单测 + writing E2E | ✅ 场景闭环 |
| 场景 5 世界对象管理 | R5 | `world`, `memory` | Vue 世界视图 | world 单测 + world E2E | ✅ 场景闭环 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | Vue 大纲视图 | outline 单测 + outline E2E | 🟡 部分覆盖 |
| A1 RAG 混合检索 | R6 | `rag` | Vue RAG 视图 | rag 单测 + rag E2E | 🟡 部分覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | Vue 生成中心 | context 单测 + context E2E | 🟡 部分覆盖 |

## E2E 文件与场景映射

| E2E 文件 | 覆盖场景 | 说明 |
|----------|----------|------|
| `home.spec.js` | — | 首页加载、导航切换、快捷键、命令栏；未纳入本次运行 |
| `project.spec.js` | 场景 1 | 创建项目、列表选择、编辑项目、删除项目（软删除）、点击切换项目；未纳入本次运行 |
| `project-recycle-bin.spec.js` | 场景 1 | 软删除后进入回收站可恢复、永久删除后不可恢复；2/2 通过 |
| `project-chaos.spec.js` | 场景 1 | 危险操作取消路径：取消永久删除后项目仍保留在回收站；1/1 通过 |
| `import.spec.js` | 场景 2 | 文件上传并解析（基础导入成功流）；1/1 通过 |
| `import-errors.spec.js` | 场景 2 | 格式不支持、超大文件前端拦截、空文件导入失败且不创建章节；3/3 通过 |
| `deep-import.spec.js` | 场景 3 | 从项目视图导入后经当前场景自动提取入口启动、active workflow 路由恢复、无章节时不显示按钮；3/3 通过 |
| `p1-lifecycle-health.spec.js` | 场景 3 / A1 | 后端 action 驱动的深度导入继续/放弃入口，以及 evidence health 展示；2/2 通过 |
| `deep-import-worker.spec.js` | 场景 3 | guarded worker E2E：提交异步深度导入后关闭页面，任务继续由 worker 完成；需 `RUN_WORKER_E2E=1` 和运行中的 backend worker |
| `deep-import-real.spec.js` | 场景 3 | 真实同步深度导入（`POST /api/imports/deep/sync`），不覆盖新版 Phase 0 / Phase 1a / Phase 1b 韧性策略 |
| `writing.spec.js` | 场景 4 | 空状态、新建章节、编辑并暂存、发布、Scene 切换不丢内容、版本历史查看与恢复、断章更新左侧树、光标位置联动右侧 Scene 卡面板、Scene 自动提取唯一入口、离线恢复 localStorage、多 Tab 冲突检测；11/11 通过 |
| `writing-conflict.spec.js` | 场景 4 | 409 冲突 — 其他会话已更新草稿版本；1/1 通过 |
| `world.spec.js` | 场景 5 | 对象库空态、创建/编辑/删除世界对象、关系子标签、别名子标签、实体合并、实体回滚、人物知识边界；9/9 通过 |
| `world-relations-aliases.spec.js` | 场景 5 | 创建关系、创建别名；2/2 通过 |
| `outline-scenes.spec.js` | 场景 6 | Scene 卡创建/编辑/移入历史、重排、工作台与正文 Scene 提取入口；P20 Planned Scene 由单元与后端契约测试覆盖 |
| `outline-threads-arcs.spec.js` | 场景 6 | 创建/编辑/删除剧情线、创建/编辑/删除篇章纲；6/6 通过 |
| `outline-foreshadowing-reveal.spec.js` | 场景 6 | 旧路由归并、同一 movement 的伏笔/揭示时间线、未归类计划分配 |
| `rag.spec.js` | A1 | 索引状态页面、搜索子标签、搜索空结果、真实 RAG chunk UI 召回、embedding 降级元数据与 warning、重建索引按钮；5/5 通过 |
| `generate.spec.js` | A2 | 生成中心页面、自由聊天/草稿/模板，以及上下文编译、预览与人物视角提交契约 |

## 覆盖状态详细说明

### ✅ 场景闭环

- **项目创建与管理**：`project.spec.js` 与 `project-recycle-bin.spec.js` 覆盖创建、列表选择、编辑、软删除、回收站恢复和永久删除。创建和列表选择均进入写作视图（`#/workbench/:projectId/writing`）。
- **文件上传与基础导入**：`import.spec.js`（1/1）与 `import-errors.spec.js`（3/3）覆盖基础导入成功流、格式不支持、超大文件前端拦截、空文件导入失败且不创建章节。
- **手工写作工作台**：`writing.spec.js`（11/11）与 `writing-conflict.spec.js`（1/1）全部通过；覆盖写作核心流程与 409 冲突检测。
- **世界对象管理**：`world.spec.js`（9/9）与 `world-relations-aliases.spec.js`（2/2）全部通过；覆盖对象 CRUD、关系、别名、合并、回滚、知识边界。

### 🟡 部分覆盖（功能存在但 E2E 未完整断言）

以下功能已有页面/API/基础 E2E，但仍有文档化操作路径未完整断言或未实现：

- **深度导入流水线**：当前覆盖受支持的场景自动提取入口、异步任务提交、active workflow 刷新/路由恢复、后端 action 驱动的手动恢复提示，以及 guarded worker 浏览器关闭场景；阶段质量细节由前端单测和 imports 后端测试覆盖。
- **深度导入 chaos 待实现项**：成功导入后立即刷新恢复章节树、关闭浏览器后恢复异步深度导入、部分结果降级 warning。仅作为待实现矩阵记录，不再用数组长度伪装成 Playwright 产品覆盖。
- **真实异步深度导入质量验收**：旧真实 LLM 验收 harness 已废弃；当前以 staged async task 结果、后端 imports 单元/集成测试和必要的手动 provider probe 作为质量回归依据。
- **P20 当前层创作**：后端 strict schema、上下文、原子 apply 与前端表单/恢复由单元测试覆盖；
  真实 provider 质量验收按 Prompt 全量优化计划统一执行。浏览器 E2E 当前覆盖信息推进归并与
  未归类分配，尚未在 worker profile 中跑完三类生成/apply。
- **RAG 父子检索**：真实 chunk UI 召回与 embedding 降级 warning 已覆盖；父子检索补齐父 Scene 元数据和 Delta 摘要仍待实现/验收。
- **上下文人物视角隐藏真相转换**：前端已覆盖 `reveal_mode=character` 与 `viewpoint_character_id` 提交契约；真实数据下不同 `reveal_mode` 的内容差异主要由后端 context 测试覆盖，浏览器端仍未完整断言预算裁剪和 hidden_truth 差异。
- **RAG/Context chaos 待实现项**：降级检索 warning、揭示模式切换不泄露隐藏真相、激进预算裁剪可观察且不崩溃。仅保留在矩阵中，未实现前不进入 Playwright 收集。

## 验证命令与结果

```bash
# 前端单元测试
cd frontend-console && npm test
# 以当前运行输出为准；文档不固化易漂移的文件数和测试数

# 后端聚焦模块测试
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
# 以当前运行输出为准

# 历史 Playwright 场景套件基线（APP_ENV=test；本表用于覆盖映射，完整结果需按当前分支重跑刷新）
cd frontend-console && DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:functional -- project.spec.js import.spec.js writing.spec.js world.spec.js outline-scenes.spec.js rag.spec.js generate.spec.js --reporter=list
# 以当前运行输出为准，不在矩阵中固化历史通过数

# 生成中心合约验收
cd /path/to/repo && make generate-e2e

# 前端反馈优化定向 Playwright
cd frontend-console && DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:functional -- map.spec.js -g "should create a world map" --reporter=list
# 以当前运行输出为准
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 BACKEND_PORT=8010 FRONTEND_PORT=8090 npm run test:e2e:functional -- project-chaos.spec.js --reporter=list
# 若本地 PostgreSQL 不可用，先运行 backend/scripts/doctor.py --json
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 BACKEND_PORT=8011 FRONTEND_PORT=8091 npm run test:e2e:functional -- map.spec.js scene-workbench.spec.js world.spec.js project-chaos.spec.js --reporter=list
# 使用显式专用 PostgreSQL 测试库和隔离端口；不再收集 placeholder-only spec

# Lint
cd frontend-console && node --check app.js && node --check api.js
# exit 0
cd /Users/tywww/Desktop/项目/ai-writing-assist && make lint
# 以当前运行输出为准
```
