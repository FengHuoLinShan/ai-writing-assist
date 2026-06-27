# 大纲与结构管理用户路径实现与验收计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Parallelize independent tasks with separate subagents.

**Goal:** 让作者在 outlineView 中浏览和维护 Scene 卡、剧情线、篇章纲、伏笔、揭示计划，并完成 AI 生成剧情结构。

**Architecture:** 后端基于已存在的 `backend/modules/outline`（FastAPI + SQLAlchemy async）；前端基于 `frontend-console/views/outlineView.js`（vanilla JS）。只填补验收缺口，不引入新运行时基础设施、前端框架、数据库或类型系统。

**Tech Stack:** FastAPI, async SQLAlchemy, SQLite 模块测试, PostgreSQL E2E 运行时, vanilla JS, Vitest, Playwright.

**Spec 依据:** `docs/核心业务场景与预期行为.md` 场景 6（浏览剧情结构、手动创建/编辑 Scene 卡）和场景 7（AI 生成剧情结构）。

---

## Acceptance Baseline

当前已实现大部分功能，验证缺口如下：

- `backend/modules/outline/api.py` 的伏笔和揭示计划缺少单条 `GET` 路由。
- `frontend-console/views/outlineView.js` 的伏笔标签只有状态切换，无创建/编辑/删除；揭示标签只读，无状态切换/创建/编辑/删除。
- AI 生成弹窗未在目标章节范围已有 plot_threads/outline_arcs 时给出警告并等待用户确认。
- 缺少对伏笔/揭示单条 GET 的后端测试，以及 AI 生成重复范围警告的显式测试。
- 缺少真实 LLM 验收数据：必须使用数据库中《诡秘之主 第一部》项目第 1-3 章真实内容调用 AI 生成，记录生成的 plot_threads 和 outline_arcs 数量，并验证 UI 刷新。

---

## File Structure

- Modify: `backend/modules/outline/api.py` — 添加 `GET /api/outline/foreshadowing/{plan_id}` 和 `GET /api/outline/reveals/{plan_id}`。
- Modify: `backend/modules/outline/services.py` — 如需要，为 foreshadowing/reveal 添加 `get_foreshadowing_plan` / `get_reveal_plan` 服务方法（薄封装，不引入复杂逻辑）。
- Modify: `backend/modules/outline/tests/test_foreshadowing_reveal.py` — 添加单条 GET 测试、创建/删除限定 novel_id 测试。
- Modify: `backend/modules/outline/tests/test_scene.py` — 确认 reorder/deprecate 测试已覆盖；如不足则补齐。
- Modify: `frontend-console/api.js` — 添加 foreshadowing/reveal 的 create/update/delete 方法。
- Modify: `frontend-console/views/outlineView.js` — 实现伏笔/揭示的创建/编辑/删除/状态更新 UI。
- Modify: `frontend-console/views/outlineView.js` — 在 AI 生成弹窗中，选择范围后检查现有 plot_threads/outline_arcs，若有则显示警告并要求确认。
- Add/Modify: `frontend-console/e2e/outline-foreshadowing-reveal.spec.js` — 覆盖伏笔/揭示创建、状态更新、删除二次确认、novel_id 隔离。
- Modify: `frontend-console/e2e/outline-scenes.spec.js` — 补充 AI 生成弹窗重复范围警告测试。
- Modify: `backend/tests/e2e/test_outline_generation.py` — 使用真实《诡秘之主 第一部》第 1-3 章内容，记录生成数量并断言 UI 刷新（配合 Playwright 或 API 验证）。
- Modify: `frontend-console/e2e/outline-real-llm.spec.js` — 真实 LLM 验收：选择 1-3 章，点击 AI 生成，等待完成，验证 threads/arcs 列表刷新并记录数量。

---

## Task 1: 补齐伏笔/揭示单条 GET 后端路由

**Files:**
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/services.py`（如 repository 未直接暴露 get）

- [ ] **Step 1: 读取当前 api.py 和 services.py**

  确认 `ForeshadowingPlanResponse` / `RevealPlanResponse` schema、repository 方法名称、novel_id 校验模式。

- [ ] **Step 2: 在 services.py 添加/确认 get 方法**

  如果 `ForeshadowingRepository`/`RevealRepository` 没有 `get_by_id`，在 services 层添加薄方法：

  ```python
  async def get_foreshadowing_plan(self, db: AsyncSession, plan_id: int, novel_id: int):
      plan = await self.foreshadowing_repo.get_by_id(db, plan_id)
      if not plan or plan.novel_id != novel_id:
          raise HTTPException(status_code=404, detail="Foreshadowing plan not found")
      return plan

  async def get_reveal_plan(self, db: AsyncSession, plan_id: int, novel_id: int):
      plan = await self.reveal_repo.get_by_id(db, plan_id)
      if not plan or plan.novel_id != novel_id:
          raise HTTPException(status_code=404, detail="Reveal plan not found")
      return plan
  ```

- [ ] **Step 3: 在 api.py 追加 GET 路由**

  在 `PATCH /foreshadowing/{plan_id}` 之前/之后追加：

  ```python
  @router.get("/foreshadowing/{plan_id}", response_model=ForeshadowingPlanResponse)
  async def api_get_foreshadowing(
      plan_id: int,
      novel_id: int = Query(...),
      db: AsyncSession = Depends(get_db),
      outline_service: OutlineService = Depends(get_outline_service),
  ):
      return await outline_service.get_foreshadowing_plan(db, plan_id, novel_id)
  ```

  同样方式追加 `GET /reveals/{plan_id}`。

- [ ] **Step 4: 运行 outline 模块测试**

  ```bash
  cd backend && pytest modules/outline/tests/test_foreshadowing_reveal.py modules/outline/tests/test_scene.py -q --tb=short
  ```

  Expected: all pass.

- [ ] **Step 5: 提交**

  ```bash
  git add backend/modules/outline/api.py backend/modules/outline/services.py
  git commit -m "feat(outline): add GET endpoints for single foreshadowing/reveal plan"
  ```

---

## Task 2: 补齐后端测试

**Files:**
- Modify: `backend/modules/outline/tests/test_foreshadowing_reveal.py`
- Modify: `backend/modules/outline/tests/test_scene.py`（如需要）
- Modify: `backend/modules/outline/tests/test_generation.py`（如存在；否则在 `test_foreshadowing_reveal.py` 追加）

- [ ] **Step 1: 添加 foreshadowing/reveal GET 测试**

  在 `test_foreshadowing_reveal.py` 中新增：

  ```python
  async def test_get_foreshadowing_plan(client, ...):
      # create a plan first
      resp = await client.get(f"/api/outline/foreshadowing/{plan_id}?novel_id={novel_id}")
      assert resp.status_code == 200
      data = resp.json()
      assert data["id"] == plan_id
      assert data["novel_id"] == novel_id

  async def test_get_foreshadowing_plan_wrong_novel(client, ...):
      resp = await client.get(f"/api/outline/foreshadowing/{plan_id}?novel_id={other_novel_id}")
      assert resp.status_code == 404
  ```

  对 reveal 做同样测试。

- [ ] **Step 2: 添加删除限定 novel_id 测试**

  断言：用错误的 novel_id DELETE 返回 404，目标 plan 仍存在；用正确 novel_id 删除后返回 204/200 且无法再 GET。

- [ ] **Step 3: 添加 AI generate 重复范围警告测试**

  如果 `POST /api/outline/generate` 已返回 `existing_threads_count` / `existing_arcs_count`，则测试：

  - 首次生成 1-3 章成功，返回 `existing_threads_count == 0`, `existing_arcs_count == 0`。
  - 第二次生成相同范围成功并返回非零计数（或后端返回警告需前端确认），UI 层给出二次确认。

  如果后端尚未返回这些字段，在 `services.py` 的 `generate` 返回 dict 中补充：

  ```python
  return {
      "total_threads": len(saved_threads),
      "total_arcs": len(saved_arcs),
      "extra_sections": extra_sections,
      "existing_threads_count": existing_threads_count,
      "existing_arcs_count": existing_arcs_count,
  }
  ```

  并更新 response schema。

- [ ] **Step 4: 运行 outline 模块全部测试**

  ```bash
  cd backend && pytest modules/outline/tests -q --tb=short
  ```

  Expected: all pass.

- [ ] **Step 5: 提交**

  ```bash
  git add backend/modules/outline/tests
  git commit -m "test(outline): add GET and duplicate-range warning tests"
  ```

---

## Task 3: 前端实现伏笔/揭示创建、编辑、删除、状态更新

**Files:**
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/outlineView.js`

- [ ] **Step 1: 在 api.js 添加 foreshadowing/reveal 客户端方法**

  在 `outline:` 对象内追加：

  ```javascript
    // ---- Foreshadowing ----
    async createForeshadowing(novelId, data) {
      return request(`/outline/foreshadowing?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        body: JSON.stringify(data),
      })
    },
    async updateForeshadowing(planId, novelId, data) {
      return request(`/outline/foreshadowing/${planId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      })
    },
    async deleteForeshadowing(planId, novelId) {
      return request(`/outline/foreshadowing/${planId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },

    // ---- Reveal ----
    async createReveal(novelId, data) {
      return request(`/outline/reveals?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        body: JSON.stringify(data),
      })
    },
    async updateReveal(planId, novelId, data) {
      return request(`/outline/reveals/${planId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      })
    },
    async deleteReveal(planId, novelId) {
      return request(`/outline/reveals/${planId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },
  ```

- [ ] **Step 2: 实现伏笔标签的完整 UI**

  在 `_renderForeshadowing()` 中：

  - 顶部添加「新建伏笔」按钮。
  - 每个 item 右侧添加编辑、删除按钮。
  - 保留状态 select。
  - 编辑/新建使用统一 modal，字段：`description`（必填）、`target_chapter`（整数，默认当前项目最后一章或 1）、`status`（select：planted / triggered / resolved / abandoned）。
  - 删除调用二次确认 toast/dialog。

- [ ] **Step 3: 实现揭示标签的完整 UI**

  在 `_renderReveals()` 中：

  - 顶部添加「新建揭示」按钮。
  - 每个 item 右侧添加编辑、删除按钮。
  - 每个 item 添加状态 select：`status`（select：planned / revealed / resolved / abandoned）。
  - 编辑/新建 modal 字段：`description`（必填）、`reveal_chapter`（整数）、`foreshadowing_plan_id`（可选 select，从当前伏笔列表选）、`status`。
  - 删除二次确认。

- [ ] **Step 4: 处理 novel_id 隔离**

  所有 API 调用必须携带 `state.currentProjectId`。测试切换项目后列表正确刷新（已有 `onEnter` 逻辑应处理，确保 modal 中不缓存旧数据）。

- [ ] **Step 5: 验证前端静态语法**

  ```bash
  cd frontend-console && node --check api.js && node --check views/outlineView.js
  ```

- [ ] **Step 6: 运行前端单元测试**

  ```bash
  cd frontend-console && npm test -- --run outlineView.test.js
  ```

  Expected: pass。

- [ ] **Step 7: 提交**

  ```bash
  git add frontend-console/api.js frontend-console/views/outlineView.js
  git commit -m "feat(outline): full CRUD UI for foreshadowing and reveal plans"
  ```

---

## Task 4: AI 生成弹窗重复范围警告

**Files:**
- Modify: `frontend-console/views/outlineView.js`

- [ ] **Step 1: 在打开弹窗时预取现有结构计数**

  在 AI 生成按钮点击 handler 中，根据当前选择的 start_chapter / end_chapter（默认 1-3 或用户上次选择）调用：

  ```javascript
  const threads = await api.outline.listThreads(state.currentProjectId)
  const arcs = await api.outline.listArcs(state.currentProjectId)
  const existingThreads = threads.items.filter(t => /* overlap with selected range */)
  const existingArcs = arcs.items.filter(a => /* overlap with selected range */)
  ```

  或者如果后端 generate 接口返回计数，则直接使用返回。

- [ ] **Step 2: 显示警告并等待确认**

  若 `existingThreads.length > 0 || existingArcs.length > 0`，在弹窗中显示：

  > 第 X-Y 章已存在 N 条剧情线、M 条篇章纲。继续生成将追加新结构，是否继续？

  不勾选/不确认则不调用 `api.outline.generate`。

- [ ] **Step 3: 范围选择变化时重新计算**

  给 start/end select 添加 `change` 监听器，实时更新警告文案。

- [ ] **Step 4: 提交**

  ```bash
  git add frontend-console/views/outlineView.js
  git commit -m "feat(outline): warn before AI generate when target range already has threads/arcs"
  ```

---

## Task 5: Playwright E2E 覆盖

**Files:**
- Add/Modify: `frontend-console/e2e/outline-foreshadowing-reveal.spec.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`

- [ ] **Step 1: 创建 foreshadowing/reveal E2E**

  测试：

  1. 进入 outlineView，切到「伏笔」子标签。
  2. 点击「新建伏笔」，填写描述和目标章节，保存。
  3. 列表出现新伏笔；状态 select 可切换为 triggered。
  4. 点击编辑，修改描述，保存后列表更新。
  5. 点击删除，确认二次确认，列表移除。
  6. 切到「揭示」子标签，同样流程。
  7. （可选 novel_id 隔离）创建第二个项目，进入 outlineView 伏笔标签，断言列表为空。

- [ ] **Step 2: 扩展 outline-scenes E2E**

  在已有 Scene CRUD 测试后追加：

  1. 点击「AI 生成结构」。
  2. 弹窗默认范围 1-3。
  3. 在弹窗内将 end_chapter 改为已有结构的范围（利用前面创建的 Scene 或 threads），断言出现警告文案。
  4. 取消后不调用生成；确认后调用并等待成功 toast。

  如果真实 LLM 在 E2E 中不稳定，用 stub backend route 测试警告分支；真实 LLM 验收放到 Task 6。

- [ ] **Step 3: 运行 Playwright E2E**

  ```bash
  cd frontend-console && npx playwright test outline-foreshadowing-reveal.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js --reporter=list
  ```

  Expected: pass。

- [ ] **Step 4: 提交**

  ```bash
  git add frontend-console/e2e
  git commit -m "test(e2e): foreshadowing/reveal CRUD and AI generate duplicate warning"
  ```

---

## Task 6: 真实 LLM 验收（《诡秘之主 第一部》第 1-3 章）

**Files:**
- Modify: `backend/tests/e2e/test_outline_generation.py`
- Add: `frontend-console/e2e/outline-real-llm.spec.js`

- [ ] **Step 1: 准备真实内容**

  确认数据库中已有《诡秘之主 第一部》项目及第 1-3 章正文。若不存在，通过 deep import 或 seed 脚本导入 `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt` 的前 3 章。

- [ ] **Step 2: 修改 E2E API 测试使用真实 LLM**

  在 `backend/tests/e2e/test_outline_generation.py` 中：

  - 找到或创建小说项目，确保 chapter 1-3 有真实文本。
  - 调用 `POST /api/outline/generate?novel_id={id}` with JSON `{"start_chapter": 1, "end_chapter": 3}`。
  - 断言 `total_threads > 0` 和 `total_arcs > 0`。
  - 打印并记录 `total_threads` / `total_arcs`。
  - 再次调用相同范围，断言 `existing_threads_count` / `existing_arcs_count` 与首次生成的数量一致（或 UI 给出确认）。

- [ ] **Step 3: 运行真实 LLM API 验收**

  ```bash
  cd backend && pytest tests/e2e/test_outline_generation.py -v -s --tb=short
  ```

  记录输出中的数量。

- [ ] **Step 4: 添加前端真实 LLM 验收测试**

  在 `frontend-console/e2e/outline-real-llm.spec.js` 中：

  1. 登录并选择《诡秘之主 第一部》项目。
  2. 进入 outlineView → 剧情线/篇章纲 子标签。
  3. 点击「AI 生成结构」，范围保持 1-3，确认。
  4. 等待请求完成（设置长 timeout，如 120s）。
  5. 断言剧情线列表和篇章纲列表非空。
  6. 记录页面中出现的条目数量。
  7. 刷新页面，断言列表仍非空（验证持久化）。

- [ ] **Step 5: 运行前端真实 LLM 验收**

  ```bash
  cd frontend-console && npx playwright test outline-real-llm.spec.js --reporter=list --timeout=180000
  ```

  记录数量。

- [ ] **Step 6: 提交验收记录**

  在 plan 文件末尾或 `docs/superpowers/acceptance/` 下创建 `outline-structure-management-acceptance.md`，记录：

  - 使用的模型/环境变量（不记录 API key）。
  - 第 1-3 章字符数/字数。
  - 首次生成 `total_threads` / `total_arcs`。
  - 重复范围生成的行为（追加/警告）。
  - UI 刷新是否成功。

  ```bash
  git add backend/tests/e2e/test_outline_generation.py frontend-console/e2e/outline-real-llm.spec.js docs/superpowers/acceptance/outline-structure-management-acceptance.md
  git commit -m "test(outline): real-LLM acceptance with Lord of Mysteries chapters 1-3"
  ```

---

## Task 7: 全量回归验证

- [ ] **Step 1: 后端模块测试**

  ```bash
  cd backend && pytest modules/outline/tests -q --tb=short
  ```

- [ ] **Step 2: 前端单元测试**

  ```bash
  cd frontend-console && npm test -- --run
  ```

- [ ] **Step 3: Playwright 相关 E2E**

  ```bash
  cd frontend-console && npx playwright test outline-*.spec.js --reporter=list
  ```

- [ ] **Step 4: Lint/类型检查**

  ```bash
  make lint
  ```

  或分别运行：

  ```bash
  cd backend && ruff check .
  cd frontend-console && node --check app.js && node --check api.js
  ```

- [ ] **Step 5: 提交最终调整**

  如有格式修复：

  ```bash
  git add -A && git commit -m "chore(outline): final lint and regression fixes"
  ```

---

## Completion Criteria

- [ ] `outlineView` 包含 场景卡、剧情线、篇章纲、伏笔、揭示 五个子标签/入口。
- [ ] Scene 卡列表按 `scene_index` 展示 title、narrative_tag、goal 摘要、状态、来源。
- [ ] Scene 可手动创建/编辑指定字段；默认 `narrative_tag=draft`, `source=manual`。
- [ ] Scene 上移/下移调用 reorder，不修改 chapter/scene_chunks 映射。
- [ ] 删除 Scene 标记 `deprecated`。
- [ ] 剧情线/篇章纲支持创建、编辑、删除，按类型/arc_index/start_chapter 展示。
- [ ] 伏笔/揭示计划支持列表、创建、状态更新、删除；删除二次确认并限定 novel_id。
- [ ] 后端提供 `GET /api/outline/foreshadowing/{plan_id}` 和 `GET /api/outline/reveals/{plan_id}`。
- [ ] AI 生成调用 `POST /api/outline/generate`，编译上下文 → LLM → schema 校验 → 去重 → 持久化；extra_sections 只展示不持久化。
- [ ] 目标章节范围已有结构数据时前端弹窗警告并需用户确认。
- [ ] 后端测试覆盖 Scene CRUD/reorder/delete、剧情线 CRUD、篇章纲 CRUD、伏笔/揭示 CRUD、AI generate schema 和重复范围警告。
- [ ] 前端 E2E 覆盖 Scene 默认标签、创建/编辑/删除、上移/下移、AI 生成弹窗、伏笔创建/状态更新、揭示创建、剧情线/篇章纲 CRUD。
- [ ] 真实 LLM 验收使用《诡秘之主 第一部》第 1-3 章，记录 `plot_threads` 和 `outline_arcs` 数量，验证 UI 刷新。
