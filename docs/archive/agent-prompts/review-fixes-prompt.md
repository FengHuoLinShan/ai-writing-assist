# 近期提交 Review 修复清单

以下问题来自对 `490815d..edc0063`（约 25 个 commit）的系统代码审查，覆盖后端 `world/imports/writing`、前端 map/workspace/core views 及相关测试。

审查范围：
- 后端：`backend/modules/world/`、`backend/modules/imports/`、`backend/modules/writing/`、相关 migrations
- 前端：`frontend-console/views/`、`frontend-console/shared/`、`frontend-console/router.js`、相关测试/E2E
- 项目约束：`AGENTS.md`、`CLAUDE.md`、`development-guide.md`、`testing-guide.md`

当前状态：前端单元测试 287/287 通过，后端相关测试 412/5 skipped 通过，`ruff` 通过。但审查发现文档与实现冲突、并发安全缺口、novel_id 校验缺口、前端运行时泄漏/注入面等问题。

---

## P0 级（阻塞，必须修复）

### 问题 1: `world/README.md` 与项目 Candidate→Canonical 硬约束冲突

**模块**: `modules/world`

**问题**: README 写明“AI 抽取对象直接以 `status='canonical'` 自动入库，不经过候选池”，并声明 `entity_candidates` 已废弃。这与 `AGENTS.md`/`CLAUDE.md` 的 candidate→canonical 硬性规则直接矛盾，也与实际代码 `extraction_service.py` 写入 `status='candidate'` 的行为不符。

**风险**: 后续开发者按 README 实现会绕过用户确认，直接将 AI 输出写入正史库，污染 canonical 数据。

**修复要求**:
1. 更新 `backend/modules/world/README.md:12` 和 `:56`
2. 明确 AI 抽取默认进入 `candidate` 状态
3. 明确只有“用户明确启动并确认的自动流水线”才能直接写 canonical，且必须保留来源、可编辑/可回滚标记和测试覆盖
4. 如果该模块确实需要特殊策略，走 ADR 流程并在 README 中引用 ADR 编号

**相关文件**:
- `backend/modules/world/README.md`
- `backend/modules/world/services/extraction_service.py`

---

### 问题 2: `MapMarkerService.update` 不校验 hex 边界

**模块**: `modules/world`

**问题**: `MapMarkerService.update` 未调用 `MapContext.assert_hex_in_bounds`，而 `create` 有校验。marker 可被移动到地图网格之外。

**风险**: 非法坐标破坏地图状态，前端渲染假设失效，可能产生不可见的或位置错误的 marker。

**修复要求**:
1. 在 `backend/modules/world/services/map_service.py:594-633` 中，持久化前加载 map config（已通过 `self._ctx` 可用）
2. 对新的 `hex_q`/`hex_r` 调用边界校验
3. 越界时返回 422 Validation Error
4. 补充回归测试：更新 marker 到越界坐标应失败

**相关文件**:
- `backend/modules/world/services/map_service.py`
- `backend/modules/world/tests/test_map_marker_service.py`

---

### 问题 3: 路由错误页存在 XSS（已修复，需确认保留）

**模块**: frontend router

**问题**: `frontend-console/router.js:233` 将 `${err.message}` 直接写入 `innerHTML`，API/后端错误消息可能包含任意文本。

**风险**: 攻击者可通过构造后端错误消息触发 XSS。

**修复状态**: 审查 subagent 已即时修复为 `${esc(err.message)}`，并新增 `tests/router.test.js` 回归测试。

**修复要求**:
1. 确认保留 `frontend-console/router.js:233` 的 `esc()` 包装
2. 确认保留 `frontend-console/tests/router.test.js`
3. 全仓库扫描类似模式：`grep -n "innerHTML.*err" frontend-console/views/*.js frontend-console/shared/*.js`

**相关文件**:
- `frontend-console/router.js`
- `frontend-console/tests/router.test.js`

---

## P1 级（重要，修复后再合并/发布）

### 问题 4: 并发重复文件导入可能残留重复 draft

**模块**: `modules/imports`

**问题**: `backend/modules/imports/services.py:146-170` 中，重复检测依赖 partial unique index 在 `update_status(done)` 时抛出 `IntegrityError`。但此前章节写入已离开 savepoint，异常处理仅将 import record 标为 failed，外层事务仍可能提交，导致重复 `WritingDraft` 和重复 `publish_chapter`/`rag_index_chapter` 任务。

**风险**: 同时上传同名文件时，可能留下重复章节内容和重复任务。

**修复要求**:
1. 在 `IntegrityError` 处理器中 `await db.rollback()` 外层事务
2. 或重新设计为：先检查重复 → 再写入章节（但仍需 DB 约束兜底）
3. 补充并发回归测试：两个同名文件同时导入，最终只有一个成功的 import record 和对应 draft 集合

**相关文件**:
- `backend/modules/imports/services.py`
- `backend/modules/imports/tests/test_import_api.py`

---

### 问题 5: 关系写入 canonical，但关联实体是 candidate

**模块**: `modules/imports`

**问题**: `backend/modules/imports/scene_entity_extraction.py:462` 中 `_persist_relations` 显式 `status="canonical"`，但关联实体已被改为 `candidate`。导致 review UI 状态不一致，canonical 关系可能指向未批准的候选实体。

**风险**: 数据状态语义混乱；用户未确认实体前，关系已进入正史。

**修复要求**:
1. 关系也应写入 `status="candidate"`
2. 或在实体提升为 canonical 时延迟创建关系
3. 更新相关测试断言

**相关文件**:
- `backend/modules/imports/scene_entity_extraction.py`
- `backend/modules/imports/tests/test_scene_entity_extraction.py`

---

### 问题 6: 地图重名检查有分页上限，可能漏检

**模块**: `modules/world`

**问题**: `backend/modules/world/services/map_service.py:261-263` 中 `MapConfigService.create` 用 `limit=100` 拉取同级地图做重名检查。超过 100 张地图时可能漏检。

**风险**: 同名地图被创建成功，依赖 DB unique index 作为唯一兜底。

**修复要求**:
1. 用 count 查询或按 name 精确查询替代 `limit=100` 遍历
2. 补充边界测试：创建第 101 个同级地图时仍能被重名检查拦截

**相关文件**:
- `backend/modules/world/services/map_service.py`
- `backend/modules/world/tests/test_map_config_service.py`

---

### 问题 7: `EntityRevisionService.create_snapshot` 未校验 novel_id 归属

**模块**: `modules/world`

**问题**: `backend/modules/world/services/entity_revision_service.py:24-71` 接受 `novel_id` 参数，但仅检查 `entity is not None`，未校验 `entity.novel_id == nid`。

**风险**: 绕过已验证的 `WorldEntityService.update` 直接调用时，可创建跨 novel 的 revision 记录。

**修复要求**:
1. 在构建 snapshot 前添加 `if entity.novel_id != nid: raise HTTPException(404, ...)`
2. 补充跨 novel 失败测试

**相关文件**:
- `backend/modules/world/services/entity_revision_service.py`
- `backend/modules/world/tests/test_entity_rollback_snapshot.py`

---

### 问题 8: `EntityRelationService.upsert` 未校验 source/target 归属

**模块**: `modules/world`

**问题**: `backend/modules/world/services/entity_relation_service.py:188-208` 的 public `upsert` 方法直接委托 repository，未校验 `source_id` 和 `target_id` 是否属于当前 `novel_id`。

**风险**: facade 调用者可创建跨 novel 或孤立的关系边。

**修复要求**:
1. 在 `upsert` 中 fetch 两个 entity 并断言 `novel_id` 匹配
2. 复用 `create` 中已有的验证逻辑
3. 补充跨 novel 失败测试

**相关文件**:
- `backend/modules/world/services/entity_relation_service.py`
- `backend/modules/world/tests/test_repositories.py` 或新增 test file

---

### 问题 9: `EntityDedupService.find_duplicates` 未校验 candidate 归属

**模块**: `modules/world`

**问题**: `backend/modules/world/services/dedup_service.py:141-158` 加载 candidate 后未检查 `candidate.novel_id == novel_id`。

**风险**: 可将另一个 novel 的 candidate 名称泄露到当前 novel 的实体搜索中。

**修复要求**:
1. 校验 candidate 的 `novel_id`，不匹配时返回 `[]` 或 404
2. 补充跨 novel 测试

**相关文件**:
- `backend/modules/world/services/dedup_service.py`
- `backend/modules/world/tests/test_entity_dedup_service.py`

---

### 问题 10: Real-LLM 测试断言 stale canonical 状态

**模块**: `modules/imports`

**问题**: `backend/modules/imports/tests/test_real_extraction.py:200, 242, 265-267, 451, 461-463` 仍断言 `status == "canonical"`，而生产已改为 candidate。

**风险**: `RUN_REAL_LLM_TESTS=1` 时测试失败；文档与实际行为不一致。

**修复要求**:
1. 更新断言为 `status == "candidate"`
2. 更新 docstring 和注释，移除“自动入库”等旧表述
3. 验证 real-LLM 测试通过

**相关文件**:
- `backend/modules/imports/tests/test_real_extraction.py`

---

### 问题 11: `/deep/sync` 绕开 orchestrator 策略

**模块**: `modules/imports`

**问题**: `backend/modules/imports/api.py:132-199` 的同步端点直接调用 `DeepImportWorkflow.run_step`，跳过了 `DeepImportOrchestrator` 的重复检测/废弃处理。返回字典也缺少 `quality_status`、`phase_errors` 等新字段。

**风险**: 异步与同步深度导入行为不一致；sync 模式缺少保护。

**修复要求**:
1. 将 sync 模式路由到 orchestrator，或
2. 在 API docstring 中明确标注 sync 模式仅用于测试且跳过重复保护
3. 统一返回字段

**相关文件**:
- `backend/modules/imports/api.py`
- `backend/modules/imports/orchestrator.py`

---

### 问题 12: `mapWorkspaceView` 路由切换泄漏旧 mapView 实例

**模块**: frontend map workspace

**问题**: `frontend-console/views/mapWorkspaceView.js:149-156, :287-291` 切换 overview↔map 时未调用 `mapView.unmount()`，旧的 Leaflet 实例、canvas 监听、tooltip timer 未清理。

**风险**: 重复导航造成内存泄漏、Detached DOM、事件重复触发。

**修复要求**:
1. 在 `router.refresh()` 离开地图前调用 `mapView.unmount()`
2. 确保 `unmount()` 清理 Leaflet map、canvas resize listener、tooltip timer
3. 补充测试验证重复 open/close 不会产生多个 Leaflet 容器

**相关文件**:
- `frontend-console/views/mapWorkspaceView.js`
- `frontend-console/views/mapView.js`

---

### 问题 13: `setTimeout` 挂载/绑定存在竞态

**模块**: frontend map workspace / map view

**问题**: `frontend-console/views/mapWorkspaceView.js:54, :58` 和 `frontend-console/views/mapView.js:285-286` 中 `render()` 用 `setTimeout(..., 0)` 延迟 mount/bind。若路由在 timeout 触发前重新渲染，可能挂载到已替换的 DOM 或重复挂载。

**风险**: 状态与 DOM 不一致，事件绑定到错误元素。

**修复要求**:
1. 记录 pending timer ID，在 `onLeave`/`unmount` 中 `clearTimeout`
2. 或当容器已在 DOM 时同步执行 mount/bind
3. 优先移除不必要的 `setTimeout`

**相关文件**:
- `frontend-console/views/mapWorkspaceView.js`
- `frontend-console/views/mapView.js`

---

### 问题 14: 地点搜索结果无点击处理

**模块**: frontend map workspace

**问题**: `frontend-console/views/mapWorkspaceView.js:304` 的 `_search()` 对地点结果 emit `data-action="map-search-location"`，但 `root.onclick` 未处理该 action。

**风险**: 用户点击搜索出的地点无任何反应。

**修复要求**:
1. 在 `root.onclick` 中添加 `map-search-location` 分支
2. 行为建议：打开对应地图并居中到该地点，或打开实体详情

**相关文件**:
- `frontend-console/views/mapWorkspaceView.js`

---

### 问题 15: Faction 颜色直接注入 `style`，存在 CSS 注入面

**模块**: frontend map view

**问题**: `frontend-console/views/mapView.js:1348, :1369-1370` 中 `background:${esc(color)}22` 和 `border-color:${esc(color)}` 只做了 HTML escape。`mapState.factionColors` 可从 console 设置，恶意值如 `red; background-image:url(...)` 可注入 CSS。

**风险**: CSS 注入可导致 UI 破坏或进一步攻击。

**修复要求**:
1. 使用颜色前校验匹配 `/^#[0-9A-Fa-f]{6}$/`
2. 或使用 CSS 自定义属性隔离
3. 非法颜色 fallback 到默认色

**相关文件**:
- `frontend-console/views/mapView.js`

---

### 问题 16: `worldView.js` render 周期内同步导航竞态（已修复，需确认保留）

**模块**: frontend world view

**问题**: `frontend-console/views/worldView.js:178` 在 `render()` 中同步调用 `router.navigate("map", null)`，触发嵌套路由渲染，可能使 UI 停留在 placeholder。

**修复状态**: 已改为 `setTimeout(() => router.navigate("map", null), 0)`，并更新测试。

**修复要求**:
1. 确认保留延迟导航
2. 确认 `tests/worldView.test.js` 使用 `vi.waitFor` 验证导航

**相关文件**:
- `frontend-console/views/worldView.js`
- `frontend-console/tests/worldView.test.js`

---

### 问题 17: `writingView.js` scene map summary 回调可能渲染旧 scene（已修复，需确认保留）

**模块**: frontend writing view

**问题**: `frontend-console/views/writingView.js:755` 中，若用户在 `getMapSceneSummary` 请求飞行期间切换 scene，回调会用旧 scene 数据重新渲染面板。

**修复状态**: 已增加 `if (this._currentSceneId !== currentScene.id) return` guard。

**修复要求**:
1. 确认保留 guard
2. 考虑在 `_loadCurrentSceneMapSummary` 内部也加 guard，避免旧数据污染缓存

**相关文件**:
- `frontend-console/views/writingView.js`
- `frontend-console/tests/writingView.test.js`

---

## P2 级（建议优化）

### 问题 18: 业务逻辑泄露到 API 路由

**模块**: `modules/world`

**问题**: `backend/modules/world/map_api.py:313-326` 在路由内按 faction 过滤 territory，并加载所有 territories/markers 后丢弃大部分。

**修复要求**: 将 faction 过滤下沉到 `MapConfigService.get_state` 或 dedicated focus method，并下推到 repository 查询。

**相关文件**:
- `backend/modules/world/map_api.py`
- `backend/modules/world/services/map_service.py`

---

### 问题 19: breadcrumbs 查询 N+1

**模块**: `modules/world`

**问题**: `backend/modules/world/map_repositories.py:166-181` 循环逐层重新 fetch parent map。

**修复要求**: 改用递归 CTE 一次查询完整路径。

**相关文件**:
- `backend/modules/world/map_repositories.py`

---

### 问题 20: `bulk_upsert` 逐 tile 执行

**模块**: `modules/world`

**问题**: `backend/modules/world/map_repositories.py:233-273` 对每格执行一次 upsert。

**修复要求**: 使用单次 `INSERT ... ON CONFLICT` 批量写入。

**相关文件**:
- `backend/modules/world/map_repositories.py`

---

### 问题 21: `models.py` 重复 import

**模块**: `modules/world`

**问题**: `backend/modules/world/models.py` 中 `from sqlalchemy import DateTime, func` 被导入两次。

**修复要求**: 删除重复 import。

**相关文件**:
- `backend/modules/world/models.py`

---

### 问题 22: `alembic/env.py` 修改全局 `os.environ`

**模块**: alembic

**问题**: `backend/alembic/env.py` 读取 `.env` 后设置 `os.environ["DATABASE_URL"]`。

**修复要求**: 返回解析后的 URL 而不修改全局环境。

**相关文件**:
- `backend/alembic/env.py`

---

### 问题 23: 使用已弃用 HTTP 常量

**模块**: `modules/imports`

**问题**: `backend/modules/imports/services.py:232` 使用 `HTTP_413_REQUEST_ENTITY_TOO_LARGE`，Starlette 已弃用，应替换为 `HTTP_413_CONTENT_TOO_LARGE`。

**相关文件**:
- `backend/modules/imports/services.py`

---

### 问题 24: `test_domain_handlers.py` 位置越界

**模块**: infrastructure / tasks

**问题**: `backend/infrastructure/tasks/test_domain_handlers.py` 导入 `modules.world.tasks` 和 `modules.outline.tasks`，模糊基础设施与业务层边界。

**修复要求**: 考虑迁移到 `backend/tests/integration/task_handlers/`。

**相关文件**:
- `backend/infrastructure/tasks/test_domain_handlers.py`

---

### 问题 25: 测试直接 import 其他模块内部实现

**模块**: `modules/imports`

**问题**: `imports/tests` 多处直接 import `modules.world.repositories.CoreEntityRepository`、`modules.writing.models.WritingDraft` 等内部实现。

**修复要求**: 跨模块行为通过 facade/contracts/API 测试，或将这些测试移到 `tests/integration/`。

**相关文件**:
- `backend/modules/imports/tests/test_real_extraction.py`
- `backend/modules/imports/tests/test_imports.py`
- `backend/modules/imports/tests/test_real_file_import.py`

---

### 问题 26: 缺少 cross-novel 文件上传重复测试

**模块**: `modules/imports`

**问题**: `test_import_api.py` 的重复文件测试只在同一项目中验证。

**修复要求**: 补充测试：同名文件上传到两个不同项目，均应成功。

**相关文件**:
- `backend/modules/imports/tests/test_import_api.py`

---

### 问题 27: 前端 UI/UX polish

**模块**: frontend map view / workspace

**问题**:
- canvas 未响应窗口 resize
- `_backToList()` 在工作区面板内嵌套地图列表
- `_bindSceneEvents()` 为空实现
- `_offset` 设置但未用于绘制
- overview 模式下 layer toggle 无效但仍显示

**修复要求**: 清理死代码，统一 canvas resize 监听，优化 overview 模式 UI。

**相关文件**:
- `frontend-console/views/mapView.js`
- `frontend-console/views/mapWorkspaceView.js`

---

## 全局检查项

修复后请确认：

1. **novel_id 隔离**: 所有新增/修改的 API、service、repository 查询均按 `novel_id` 过滤；跨 novel 失败测试覆盖新增入口。
2. **Candidate→Canonical**: 无 AI 输出默认直写 canonical；自动流水线有来源、可编辑/可回滚标记和测试。
3. **XSS 防护**: 全仓库 `innerHTML =` 使用点均经过 `esc()` 或来自静态模板；无 `eval`/`exec` LLM 输出。
4. **并发安全**: 重复导入、竞态写入场景有 DB 约束 + 应用层回滚兜底。
5. **测试**: 受影响模块测试通过；补充的回归测试覆盖 P0 和前 5 个 P1。
6. **Lint**: `make lint` 通过。
7. **文档同步**: 若修改 public contract、用户可见行为、数据模型或跨模块调用，同步更新 README/ADR/模块文档。
