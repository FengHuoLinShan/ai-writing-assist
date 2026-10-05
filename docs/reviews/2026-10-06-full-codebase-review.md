# 全库代码审查报告（2026-10-06）

> 审查角色：代码审查专家（码审官）
> 审查对象：分支 `codex/ring-worldbook-import`，HEAD `a62b77289`，工作树干净（无未提交改动）

## 一、审查范围与边界

**已覆盖**

- `backend/{app,core,shared,infrastructure,modules}`：1037 个 Python 文件（约 47.8 万行），对 664 个路由端点做过全量 AST 扫描
- `frontend-console/vue/`：295 个文件（Vue SFC 源码实际在该目录，非 `src/`）
- `backend/tests/`、`modules/*/tests/`、`evals/tests/`、`deploy/tests/`、`frontend-console` 测试与 e2e

**未覆盖（明确声明，不声称已审）**

- `alembic/versions` 历史迁移（仅关注结构与边界）、`node_modules/`、`frontend-console/dist/`、`tools/`、`scripts/` 深处、`docs/`
- ADR/设计文档只作判定依据，不逐篇复核

**已运行的门禁（真实结果）**

| 门禁 | 结果 |
|---|---|
| `ruff check .`（backend 全量） | 通过（All checks passed） |
| `scripts/check_module_imports.py` | 通过（12 业务模块 / 8 豁免） |
| `python -m tools.secret_hygiene` | 通过 |
| `pytest`（backend 默认层，`-q -x`，280s） | **7011 passed / 15 skipped / 7 deselected，2 warnings** |

**未运行的门禁（受环境限制）**：PostgreSQL e2e 与 merge-gate 子集、真实 LLM / 付费模型用例、Playwright e2e、覆盖率门禁。这些需要专用数据库与网络凭据，本报告不对其状态作任何结论。

## 二、结论

**P0（阻断）：未发现。**
**P1（应改）：11 条。**
**P2（建议）：14 条。**

整体判断：可以继续开发与合并；建议在合入 `main` 前至少处理 P1 中的第 1、2、4、11 项（debug 端点鉴权缺口、`world` 仓储 `novel_id` 纵深防御、语义评审重试失效、测试内未 await 的 rollback 会打断 CI 门禁）。

## 三、P1（应改）

### 1. debug 端点缺少 principal / owner 门禁

`backend/app/debug_api.py:76-78`、`96-107`、`110-116`、`81-93`

`_ensure_debug_allowed()` 只判断 `app_env != "production"`，**没有任何 account principal 或 owner 校验**。在任何非 production 环境（staging、closed_test 等）部署时，持有任意有效会话的用户可：

- `GET /api/debug/frontend-errors` 读取最近 200 条前端错误，含 `stack`（最长 6000 字符）、`page` 信息、`browser` 信息；
- `DELETE /api/debug/frontend-errors` 清空记录；
- `POST /api/debug/frontend-errors` 无需任何身份即可写入（有界：`deque(maxlen=200)`）。

`_redact` 只抹 key 名形似敏感字段与 `sk-`/`Bearer ` 正则，不抹堆栈与 URL payload。

建议（最小改动）：

```python
# before
def _ensure_debug_allowed() -> None: ...   # 仅判 app_env

# after：加账号门禁，或改用显式开关
async def _ensure_debug_allowed(principal=Depends(current_account_principal)) -> None:
    settings = get_settings()
    if settings.app_env.lower() == "production" or not settings.debug_api_enabled:
        raise HTTPException(status_code=404, detail="Not found")
```

### 2. `modules/world/repositories.py` 多处写操作未带 `novel_id`

`backend/modules/world/repositories.py:771`（`delete`）及 `:1229 / :1820 / :2337 / :2676`（`delete`）、`:1811`（`deprecate_many`）、`:2014`（`update_relation_endpoints`）、`:2321`（`migrate_entity_id`）、`:2367`（`update_character_meta_location`）

这些语句只按 `entity_id` / `rel_id` / `character_id` 过滤，不含 `novel_id`，与仓库「业务读写必须按 `novel_id` 隔离」的不变量不符。

已核实：当前唯一可达的 service 入口 `modules/world/services/core/entity_service.py:801` 会先经 `_assert_found_in_novel`（第 815 行）做归属断言，**未发现可用利用链**。但这是纵深防御缺口，任何新调用方直接接 repository 就会越权。

建议：方法签名加 `novel_id` 并写入 `where()`；对确无调用方的方法直接删除。

### 3. `modules/evidence/indexing/repositories.py` 删除接口缺 `novel_id`

`backend/modules/evidence/indexing/repositories.py:476`（`delete`）、`:486`（`delete_many`）只按 `chunk_id` / `chunk_ids` 过滤 `RagChunk`；同文件 `:494`（`delete_by_novel`）、`:505`（`delete_by_chapter`）才带 novel 条件，约定自相矛盾。全仓未找到这两个方法的调用方（**需验证**是否为死代码）。

建议：统一加 `novel_id` 条件，或直接移除未使用方法。

### 4. 语义评审异常被 `from None` 抹类型，导致重试声明失效 ★

`backend/modules/writing/semantic_review.py:1143`、`:1868`

```python
except Exception as exc:
    safe = redact_diagnostic(f"{type(exc).__name__}: {exc}", limit=500)
    raise RuntimeError(safe) from None   # 原异常类型丢失
```

而 worker 侧重试判定 `infrastructure/llm/retry.py:53-63` 的 `is_retryable_llm_error` 按 `isinstance` 匹配异常类型。包装成 `RuntimeError` 后恒定判定为 False，导致 `modules/writing/tasks.py:253`（`writing_semantic_review`）与 `:304`（`writing_targeted_revision`）声明的 `retry_transient_llm_errors=True` **永不生效**：LLM 限流 / 超时会被直接判为 failed，而不是重试。

建议：改为 `raise RuntimeError(safe) from exc` 并让重试判定沿 `__cause__` 链回溯；或定义保留类型的领域异常（如 `TransientLLMError`）。

### 5. `comment_run` 吞异常后继续复用同一 session

`backend/modules/writing/comment_run.py:383-385`、`:399-400`

```python
except Exception as exc:
    result["post_review_error"] = str(exc)[:300]
task.update_progress(0.9)      # 同一 db 继续用
```

不 rollback、不记日志。若异常发生在 `review_for_task` 已 flush 之后，后续提交可能把半成品 findings 落库而任务仍返回成功。（**需验证**：该异常是 DB 异常时，后续语句会抛 `PendingRollbackError` 而非静默成功，实际影响取决于异常来源。）

建议：except 内先 `await db.rollback()`（或用 savepoint）+ `logger.warning`，并把结果显式标记为 degraded，不让任务以成功态收尾。

### 6. 冲突快照归档失败仅告警，发布照常返回 201

`backend/modules/writing/api.py:504`、`:520`

冲突快照查询/归档失败只 `logger.warning`，发布流程继续并返回 201。结果是冲突基线静默缺失，后续冲突比对没有参照物，而调用方完全无感。

建议：归档失败回滚发布，或返回 409；至少在响应体标记 `conflict_check_degraded: true`。

### 7. 大纲生成批量落库失败降级为「正常返回」

`backend/modules/story/outline_state/generation/persister.py:350`（`:470 / :497 / :554 / :579 / :648 / :677 / :752 / :776` 同型）

非 strict 模式下批量创建失败降级为逐条重试，仍失败只 warn 并正常返回。生成流程按成功提交，但下游可能引用未落库的 thread / arc。

建议：把失败计数写入 result，让任务落 `needs_review` / degraded，而不是成功。

### 8. `require_active_project` 在 principal 为空时跳过 owner 过滤

`backend/modules/project/services.py:666`、`:697`（`_request_owner_id()` 定义见 `:804`）

`_request_owner_id()` 返回 `None` 时，函数走无 `owner_id` 的分支查询（第 675-679、707-712 行）。这是有意的 worker/system seam（`modules/account/facade.py:63`），但同一函数也被公开浏览器路径复用：一旦某条 HTTP 路径在无 bound principal 的情况下到达这里，即绕过 owner 校验。

当前**未见可达路径**（**需验证**：worker 入口是否与 API 共用这些方法）。

建议：拆成两个入口——浏览器路径版本强制要求 principal 非空。

### 9. 空测试制造虚假覆盖

`backend/modules/world/tests/test_dedup_scorer.py:232`

```python
def test_exact_name_not_handled_by_cascade(self, dedup_svc) -> None:
    # 精确匹配在 find_similar_entities 中直接处理，不走 _cascade_score
    pass
```

恒定通过。建议：补上真实断言（断言 `find_similar_entities` 不经 `_cascade_score`），或删除并在文档中说明该分支由其他用例覆盖。

### 10. 永久 skip 的退役用例应删除而非留 skip

`backend/modules/story/outline_state/tests/test_tasks.py:178`、`backend/modules/story/outline_state/tests/test_foreshadowing_reveal.py:816`

两处 `@pytest.mark.skip(reason="legacy monolithic structure generation retired by P20 v2")` 属永久退役。留着会让读者误以为仍有覆盖，且不参与重构保护。建议删除。

### 11. 测试中 `rollback()` 漏 `await`，会在 CI 门禁下升级为错误 ★

`backend/modules/imports/tests/test_spreadsheet_migration_service.py:513`

```python
db_session.rollback()      # 缺 await
await db_session.refresh(session_row)
```

实测运行产出：`RuntimeWarning: coroutine 'AsyncSession.rollback' was never awaited`。后果有两层：

1. 该回滚实际未执行，用例的清理是空操作（虽然本次 7011 全绿，但隔离性不可靠）；
2. **CI 会以 `-W error::RuntimeWarning` 运行**（`Makefile:111` `test-fast-coverage ... -W error::RuntimeWarning`），该 Warning 会被升级为 Error，直接打断门禁。

建议：`await db_session.rollback()`。

## 四、P2（建议）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| 11 | `backend/modules/evidence/indexing/repositories.py:1175` | `text(f"SET LOCAL hnsw.ef_search = {ef_search_value}")` 手拼 SQL；第 1174 行 `max(1, int(ef_search))` 强转使其当前不可注入，但这是全仓唯一手拼 SQL | 保留 `int()` 断言并加注释，或改白名单常量 |
| 12 | `backend/modules/interaction/api.py:777`、`streaming.py:277 / :313` | 匿名 RP 的 BYOK Key 从 `x-deepseek-api-key` 头读取，只有长度 ≤512 校验，无字符集白名单 | 加 `[A-Za-z0-9_.\-]` 白名单。**已核查**：`infrastructure/llm` 无 settings/api_key 日志落点，`build_managed_llm_provenance`（`agent_step_harness.py:132-138`）为白名单字段、不含 api_key，**未见外泄路径** |
| 13 | `frontend-console/vue/bridge/index.js:199` | `getEsc()` 兜底为 `String(value ?? "")`，不做转义。当前靠 `index.html:17` 先加载 `shared/esc.js` 兜住，加载顺序一变所有模态 HTML 裸奔 | 兜底改本地最小转义实现 |
| 14 | `frontend-console/vue/auth/AuthGate.vue:33-34` | `config.terms_url` / `privacy_url` 直接绑 `:href`，无协议白名单（同项目 `RpMarkdownContent.vue:13` 已有 `safeHref`，此处不一致），且 `target="_blank"` 缺 `rel="noopener noreferrer"` | 复用 `safeHref` 并补 `rel` |
| 15 | `frontend-console/vue/views/world/library/WorldLibraryDirectory.vue:29-34` | `matchMedia` 监听器在 `<script setup>` 顶层注册，全文件无 `onBeforeUnmount` / `onScopeDispose`。island 每次 query-only 导航重挂，监听器与其闭包持续累积 | 加 `onBeforeUnmount(() => mql.removeEventListener("change", onChange))`（兼容 `removeListener`） |
| 16 | `frontend-console/vue/views/writing/components/ChapterTree.vue:114` | `visibleChapters` 无上限、无虚拟滚动，数百章时一次性渲染全部子组件 | 窗口化或分页 |
| 17 | `frontend-console/vue/components/EditorialDesk.vue:259-260` | 卸载时 `clearInterval(poller)` 后未置 `poller = null`；`props.projectId` 变化且仍 active 时不会重启轮询 | 置 null，并让 projectId 变化也重置 poller |
| 18 | `frontend-console/vue/views/generate/components/WorldWorkspace.vue:458-462` | `rememberRailClick` 未被模板引用（死代码），且其 `parentElement.open ? "closed" : "open"` 与 `onRailToggle` 的语义相反 | 删除 `rememberRailClick` |
| 19 | `backend/modules/writing/semantic_review.py:1376-1379` | 循环内逐条 `get_for_update` + hash 校验，N+1 且锁行数随目标线性增长 | 改 `id.in_(...)` 一次 `with_for_update()` 后分桶校验 |
| 20 | `backend/modules/story/outline_state/p20_service.py:833 / :904 / :960` | revise 模式在 `for draft in ...` 内按 id 单条 `db.scalar` | 预批量 `id.in_(...)` 一次取回 |
| 21 | `backend/modules/story/outline_state/repositories.py:1114-1116` | 无 limit 拉取 novel 全部 Scene 后在 Python 内过滤 `chapter_index` | 改 JSONB 包含查询或加 limit |
| 22 | `backend/modules/writing/tasks.py:110 / :161` | 重试循环无退避 | 指数退避 |
| 23 | `deploy/tests/fixtures/closed-test.env` | 入库夹具含形似凭证的占位值（非真实密钥），易被误配到准生产或被扫描器误报 | 文件头加 `# fixture-only, never use in deploy` |
| 24 | `backend/tests/unit/test_test_harness.py:163` | autospec 守卫根为 `backend/`（`tests/support/inventory.py:15`），`deploy/tests/`（15 个文件）不在扫描范围 | 守卫根改为仓库根，消除盲区（当前 `deploy/tests` patch 数为 0，风险为零） |
| 25 | `backend/modules/story/outline_state/tests/test_structure_dedup.py:747` | `test_candidate_pairs_cap_limits_each_asset_type` 是同步函数却标了 `@pytest.mark.asyncio`，运行期产出 `PytestWarning` | 删除多余的 asyncio 标记（该用例无 `await`，实际按同步执行） |

## 五、已核查合规、未发现问题的项（重要，避免重复排查）

- **SQL 注入 / 命令注入 / 模板注入：未发现。** 范围内无 `eval` / `exec` / `os.system` / `subprocess` / `shell=True`。`modules/world/.../generation_prompt_template_service.py:827-828` 中的 `eval(` / `exec(` 是模板黑名单字符串，属正向校验。手拼 SQL 仅 P2 第 11 条一处，且已被 `int()` 约束。
- **SSRF：防护完整。** `infrastructure/llm/web_search.py:105-129`（scheme/端口/私有段/IP literal 多重拒绝）+ `:132-179`（自定义 DNS → `is_global` 校验 → 连接 pin 到 IP，杜绝 DNS rebinding）+ `:315-321`（每次重定向重校验）+ `infrastructure/llm/egress.py:37-137`（强制 HTTPS/443 + provider 白名单 + 请求钩子重校验）。
- **上传校验（不变量 3/4/5）：合规。** 文稿 `modules/imports/parsers.py:363-380` 在扩展名白名单之外做真实内容校验（ELF/Mach-O/PE 拒绝、EPUB 走 ZIP 签名 + `mimetype` 偏移/压缩方式 + container/package 命名空间、MOBI 走 `BOOKMOBI` + 记录表边界、txt/html 严格解码拒绝控制字符），50MB 上限在 `api.py:210-226` 按流式实测字节累计；`_archive_path_is_unsafe`（`:124-133`）+ 按实测解压输出计数的解压炸弹拦截（`:136-178`）已覆盖路径遍历与 zip bomb。表格 `spreadsheet_migration/parsing.py:174-225` 明确拒 `.xls` 与含宏工作簿。世界对象图片 `world_object_images.py:60-101` 用 PIL 真实解码、限 PNG/JPEG 单帧、≤4096×4096、`ImageOps.exif_transpose` + `convert` 去元数据后转 WebP。
- **密钥处理：合规。** Fernet 信封存储（`infrastructure/llm/secret_store.py:42-74`），project 级写 Key 被显式拒绝（`modules/project/services.py:297-298`），对外只返回 `api_key_configured` 布尔；异常回显统一过 `redact_diagnostic`（`infrastructure/llm/redaction.py:39-50`）。唯一遗留见 P2 第 12 条。
- **LLM 客户端收口：合规。** 业务客户端全部经 `modules.project.facade.open_project_llm_client()`；`modules/evidence/indexing/{embedding_writer.py:34,tuning.py:210,retrieval.py:48}` 的裸 `LLMClient()` 均属 embedding 窄例外。
- **ADR-0018 跨项目例外：实现正确。** `modules/interaction/source_service.py:105 / 465 / 583` 跨 `source_novel_id` 读取前调用 `require_author_project()`；写回用 consumer `novel_id`（`generation.py:439-440`）。
- **公开浏览器路径 owner 校验：合规。** 664 个端点中 5 处看似使用裸 `NovelIdQuery/Path/Form`，逐个 Read 确认全部为误报——`modules/imports/spreadsheet_migration/api.py:277/289/367/423` 经 `_load_session`（第 230-237 行）双重门禁；`modules/story/api.py:657` 委托给 `api_list_scene_script_files`（第 265 行内 `require_active_project`）。
- **前端 XSS：未发现可利用点。** `vue/` 内 0 处 `v-html`、0 处 `eval` / `new Function`；唯一 `innerHTML`（`sceneModalController.js:723`）内容经 `esc()` 且为纯数字枚举；所有 `showModalHtml` 动态片段均过 `esc()`；`RpMarkdownContent.vue` 用 `h()` 渲染函数，`safeHref()` 仅放行 `https?/mailto`；`index.html:6` 有 CSP `script-src 'self'` 兜底。
- **前端串项目数据 / 丢稿：未发现。** `mountIsland.js:47-54 / 65-69 / 82-89` 用 generation 作废晚到 `onEnter` 并处理 query 漂移；`useWritingWorkspace.js:533-545` 与 `editorController.js:468-501` 带 `generation + projectId + draftId` 三重校验；写作台备份失败有明示（`editorController.js:540-549`）。
- **基建绕过：未发现。** `vue/` 内 0 处裸 `fetch` / `axios`，API/state/router/toast 全经 `vue/bridge/index.js`。
- **测试规范：整体良好。** 1164 处 `patch` 中 1156 处带 `autospec=True`，未加的 7 处中 3 为守卫测试夹具、4 为已声明豁免，**真实违规 0**；生产目录 `Mock` / `MagicMock` 导入 **0**；`assert True` / `assert 1` **0**；`xfail` **0**；`skip` 2 处、`skipif` 10 处均带 reason；全仓 `toHaveScreenshot` 为 0，已删除的视觉用例（`e580950bc`）功能断言已迁移至 `themes.spec.js:35` 与 `interaction.spec.js:100,144`。
- **真实密钥 / 真实稿件入库：未发现。** 严格模式（`sk-` / `AKIA` / `AIza` / `ghp_` / `Bearer`）全仓扫描 0 命中；`backend/data`、`output/`、`.test-artifacts` 均未入库；`evals/datasets` 为虚构语料 + `source_hash` 快照，符合去原文约定。

## 六、建议的修复顺序

1. P1-1 `app/debug_api.py` 门禁（部署到非 production 环境即成真实暴露面）
2. P1-4 `semantic_review.py` 异常链（直接影响 LLM 抖动时的任务成功率）
3. P1-2 / P1-3 repository 层 `novel_id`（纵深防御，成本低）
4. P1-5 / P1-6 / P1-7 失败降级可观测性（避免「静默半成功」）
5. P1-11 测试内漏 `await` 的 rollback（一行改动，直接决定 CI 门禁能否通过）
6. P1-8 拆分 worker / 浏览器入口（需先做共用性验证）
6. P1-9 / P1-10 测试卫生；P2 按影响面排期

---

本内容由 AI 生成，请核实后使用。
