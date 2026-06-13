# 世界对象管理用户路径实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐“世界对象管理”用户路径在前后端的缺口，并通过后端单测与前端 E2E 验收。

**Architecture:** 后端在现有 `modules/world` 服务层增加搜索、手动创建标记、关系创建校验；前端在 `worldView.js` 增加分页/过滤/搜索 UI 与下拉选择器；测试补充对应场景。

**Tech Stack:** Python FastAPI + SQLAlchemy async + Pydantic；vanilla JS SPA；pytest；Playwright。

---

### Task 1: Backend — 实体列表支持按名称/别名搜索

**Files:**
- Modify: `backend/modules/world/repositories.py:136-165`
- Modify: `backend/modules/world/services/entity_service.py:93-117`
- Modify: `backend/modules/world/api.py:70-91`
- Test: `backend/modules/world/tests/test_world.py`

- [ ] **Step 1: 在 `CoreEntityRepository.get_by_novel` 增加 `q` 参数**
  当 `q` 非空时，增加 `search_text.ilike(f"%{q}%")` 条件（SQLite 兼容），保留现有 `entity_type`/`status` 过滤与分页。

- [ ] **Step 2: 在 `WorldEntityService.list` 增加 `q` 参数并透传**

- [ ] **Step 3: 在 `api.list_entities` 增加 `q: str | None = Query(None)` 并透传**

- [ ] **Step 4: 添加/更新测试 `test_list_entities_with_search_by_name` 与 `test_list_entities_with_search_by_alias`**
  断言按名称和别名均能过滤到目标实体。

- [ ] **Step 5: 运行 `make test ARGS="-k test_list_entities"`** 确认通过。

---

### Task 2: Backend — 手动创建实体默认 `created_by=manual`

**Files:**
- Modify: `backend/modules/world/services/entity_service.py:52-87`
- Test: `backend/modules/world/tests/test_world.py`

- [ ] **Step 1: 在 `WorldEntityService.create` 中，若 `data.created_by` 为 None/空字符串，将其替换为 `"manual"` 后再调用 `repo.create`**

- [ ] **Step 2: 添加测试 `test_manual_create_sets_created_by`** 断言返回 `created_by == "manual"`

- [ ] **Step 3: 运行 `make test ARGS="-k test_create_entity or test_manual_create"`** 确认通过。

---

### Task 3: Backend — 关系创建增加业务校验

**Files:**
- Modify: `backend/modules/world/services/entity_relation_service.py:24-38`
- Test: `backend/modules/world/tests/test_world.py`

- [ ] **Step 1: 在 `EntityRelationService` 中覆盖基类 `create` 方法**
  解析 `source_id`/`target_id`，校验：
  - `source_id != target_id`
  - 两个实体均存在且 `novel_id` 匹配
  - 使用 `repo.find_duplicate_relation` 检查非 `deprecated` 的重复关系，存在则返回 409
  然后调用 `super().create(db, novel_id, data)`。

- [ ] **Step 2: 添加测试 `test_create_relation_self_loop_returns_400`、`test_create_relation_cross_novel_returns_404`、`test_create_relation_duplicate_returns_409`**

- [ ] **Step 3: 运行 `make test ARGS="-k test_create_relation"`** 确认通过。

---

### Task 4: Backend — 人物知识边界 `false_belief` 服务端二次校验

**Files:**
- Modify: `backend/modules/world/services/character_knowledge_service.py:29-84`
- Test: `backend/modules/world/tests/test_character_knowledge_levels.py`

- [ ] **Step 1: 将 `_require_misconception_for_misunderstood` 扩展为同时检查 `false_belief`**

- [ ] **Step 2: 在 `create` 与 `update` 中调用该校验**

- [ ] **Step 3: 添加/更新测试 `test_create_knowledge_false_belief_without_misconception_returns_422`** 断言 `false_belief` 缺少 `misconception` 时返回 422

- [ ] **Step 4: 运行 `make test ARGS="-k false_belief"`** 确认通过。

---

### Task 5: Frontend — 对象库分页、过滤与搜索

**Files:**
- Modify: `frontend-console/views/worldView.js:188-269, 280-321, 566-585`
- Modify: `frontend-console/api.js:252-253`
- Test: `frontend-console/tests/worldView.test.js`

- [ ] **Step 1: 在 `worldView` 状态中增加 `_filters = { entity_type: "", status: "", q: "", skip: 0, limit: 20 }`**

- [ ] **Step 2: 在 `_renderEntityList` 顶部渲染过滤栏**
  - `entity_type` `<select>`：空/character/location/faction/item/event/…
  - `status` `<select>`：空/draft/candidate/canonical/deprecated/merged
  - `q` `<input type="search">` 名称/别名搜索
  - 应用按钮触发 `router.navigate("world", "objects")` 并重新加载带过滤参数的数据。

- [ ] **Step 3: `onEnter` 从 URL 或状态读取过滤参数，调用 `api.world.listEntities({ novel_id, entity_type, status, q, skip, limit })`**

- [ ] **Step 4: 在表格底部渲染分页条**
  显示 `共 {total} 条 / 第 {skip/limit+1} 页`，提供上一页/下一页按钮，更新 `_filters.skip` 后重新加载。

- [ ] **Step 5: 更新单元测试 mock 与断言** 确认过滤参数正确传递。

---

### Task 6: Frontend — 关系/别名/知识边界下拉选择器

**Files:**
- Modify: `frontend-console/views/worldView.js:360-415, 455-506, 743-813`
- Test: `frontend-console/e2e/world-relations-aliases.spec.js`

- [ ] **Step 1: 抽取 `worldView._entityOptionsHtml()` 辅助函数**
  从 `_entities` 生成 `<option value="id">名称 (类型)</option>`。

- [ ] **Step 2: `showRelationCreateForm` 中源/目标改为 `<select id="rel-source">` / `<select id="rel-target">`**

- [ ] **Step 3: `showAliasCreateForm` 中实体改为 `<select id="alias-entity">`**

- [ ] **Step 4: `showKnowledgeForm` 中目标对象改为 `<select id="knowledge-target-id">`**

- [ ] **Step 5: 更新 E2E 用例** 使用 `selectOption` 替代 `fill` ID。

---

### Task 7: Frontend E2E — 补齐验收场景

**Files:**
- Modify: `frontend-console/e2e/world.spec.js`
- Modify: `frontend-console/e2e/world-relations-aliases.spec.js`
- Modify: `frontend-console/e2e/helpers/selectors.js`（如需新选择器）

- [ ] **Step 1: 在 `world.spec.js` 增加/确认覆盖**
  - 空态 + 新建按钮
  - 创建/编辑/删除
  - 关系子标签、别名子标签
  - 合并、回滚、知识弹窗
  - （可选）分页与过滤

- [ ] **Step 2: 在 `world-relations-aliases.spec.js` 中更新关系/别名创建流程** 使用下拉选择器

- [ ] **Step 3: 运行 Playwright E2E** `cd frontend-console && npx playwright test e2e/world.spec.js e2e/world-relations-aliases.spec.js`

---

### Task 8: 验收 — Lint 与全量测试

- [ ] **Step 1: 运行 `make lint`**，修复 ruff/format 问题。
- [ ] **Step 2: 运行 `make test`** 确认后端全量通过。
- [ ] **Step 3: 运行前端 E2E 并确认关键路径通过。**
