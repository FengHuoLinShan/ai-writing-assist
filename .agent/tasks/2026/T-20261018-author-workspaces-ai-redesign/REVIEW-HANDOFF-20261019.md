# 独立评审 Handoff：写作台、世界对象与 AI 协作统一改造（第二轮）

记录时间：2026-10-19T01:02:37+08:00（Asia/Shanghai）。用户先要求“review codex/writing-workbench-ai-research”，随后要求“写handoff”；评审和本次交接都没有改业务代码，也没有提交、推送。
评审者：Claude Sonnet 5.5（max effort，主会话，未委派子代理）。进度唯一记录：[TASK.md](TASK.md)。

## 1. 接手状态与范围

- 评审对象是分支 `codex/writing-workbench-ai-research` 的**未提交工作区**。HEAD `98598127f933782f26019ca0e9970c53849c2a97` 即 `origin/main` 合并基线，0 个领先提交。排除 `.agent/` 后为 129 个已跟踪修改（+5321/−302）和 45 个未跟踪文件。
- 工作区指纹（排除 `.agent/`，评审时取得）：

  ```bash
  git diff HEAD -- . ':(exclude).agent' | shasum -a 256 | cut -c1-16   # 32917a89f489aaf5
  git ls-files --others --exclude-standard -z -- . ':(exclude).agent' | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -c1-16   # f534fe8fe62290e2
  ```

  不一致说明评审后工作区又变了：先看 `git diff`，再使用本文行号。
- 本文不是授权：不授权提交、推送、合并、部署、子代理、真实模型调用，也不授权访问任何共享或真实数据库。整改须用户明确要求；“按 handoff 修复”即可，不必重复确认已定的产品选择。
- 与前一轮的关系：[REVIEW.md](REVIEW.md) 的 R1–R7 已整改并保留。本文 F1–F4 是之后另一轮独立评审的新发现，编号不要混用。前一轮记录的两个数字评审时独立复现：完整快速后端 9291 passed / 2 skipped，前端 267 文件 / 3318 passed。

## 2. 结论

1 项必修回归（F1），2 项低风险（F2、F3），另有 1 条不要求处理的加固说明（F4）。F1 落在本任务自己声明的“非 Chromium 未验”缺口里，已用真实 WebKit 复现，不是推测。

## 3. 待处理

### F1 · P2（必修）· WebKit 下引用选择器点选不中结果

- 入口：`frontend-console/shared/referencePicker.js` 的 `handleFocusOut`（约 :290）、监听注册（:360–361）、`destroy()`（约 :444–453）。使用方：WorldBibleTab、worldEntityHelpers/worldEntityOps、generate/ReferencePickerAdapter、scene/sceneModalController、smartDedup。
- 来源：[TASK.md](TASK.md) 的 20:17 检查点为修“切换输入焦点时旧结果残留/迟到重开”新增了 `focusout` 关闭，当时只在 Chromium 验证。
- 成因：处理器用 `event.relatedTarget` 判断焦点是否仍在选择器内。WebKit 点击 `<button>` 不会聚焦它，`relatedTarget` 为 `null`，mousedown 一落下列表就关闭，随后的 click 落在已隐藏的元素上。
- 实测（Playwright 1.60.0，真实鼠标点第一个结果，数选中项）：

  | 引擎 | HEAD | 当前工作区 | 加下述修复 |
  |---|---|---|---|
  | WebKit | 1 | **0**（`onChange` 未触发，列表已收起） | 1 |
  | Chromium | 1 | 1 | 1 |
  | Firefox | 1 | 1 | 1 |

- 修法（已在三个引擎验证）：给结果容器加 `mousedown` 的 `preventDefault`，让焦点留在输入框。写成具名函数并在 `destroy()` 里移除，和现有监听一致；该文件没有行注释，不要加。

  ```js
  resultsRoot.addEventListener("mousedown", (event) => event.preventDefault())
  ```

- 必守：保留 `focusout` 关闭与取消待处理搜索的原目的及其异步回归；不删除或削弱 `frontend-console/tests/shared/referencePicker.test.js` 的现有断言。
- 验收：
  1. 单测：选项上可取消的 `mousedown` 事件 `defaultPrevented === true`。happy-dom 不模拟 WebKit 的“点击不聚焦”，只能断言这一点（尚未运行）。
  2. 真实 WebKit：现有 WebKit 门禁碰不到选择器。`frontend-console/playwright.webkit.config.js` 只跑 `responsive-core.spec.js` 与 `interaction.spec.js`，`grep` 只放行标题含“移动核心流程”或“流式重复与缺口”的用例，设备为 iPhone 13；CI 在 `.github/workflows/frontend-ci.yml` 约 :228 以 `test:e2e:webkit` 运行。应加一条走真实点选的用例并让标题进入 `grep`；鼠标路径用 `click`，触屏路径另用 `tap` 各验一次（iOS 的合成 mousedown 上 `preventDefault` 是否同样保焦点，尚未验证）。选择器已有的 Chromium 用例在 `frontend-console/e2e/` 下的 `world.spec.js`、`generate.spec.js`、`scene-workbench.spec.js`、`outline-scenes.spec.js`、`world-outline-chaos.spec.js`，挑夹具最少的一条移植。
  3. 手动：macOS Safari（可行则 iOS Safari）点选一次关系或场景引用。
- 环境坑：项目 Playwright 1.63 期望 webkit-2359 / firefox-1543，本机 `~/Library/Caches/ms-playwright` 只有 webkit-2287 / firefox-1522 / chromium-1223，直接启动会失败。两条路：`npx playwright install webkit`（需联网；本任务对 Chromium 也是这样处理，见 [TASK.md](TASK.md) 验证证据），或一次性实测改用 hermes 沙箱里的 Playwright 1.60.0：`/Users/tywww/.hermes/sandboxes/docker/default/workspace/ai-writing-assist/frontend-console/node_modules/playwright-core`（用前核实存在）。
- 复现要点（临时脚本可能已被清理）：用 `page.route` 把本地模块伪装成 `https://harness.test/...`；以 `mode:"multiple"`、`debounceMs:10` 和一个返回三项的 `entity` source 挂载 `createReferencePicker`；点 `[data-reference-query]`、输入 `a`、等 `[data-reference-result]` 可见、`page.click("[data-reference-result]")`、等 150ms，数 `[data-reference-chip]` 与 `onChange` 调用。现成脚本：`/private/tmp/claude-501/-Users-tywww----ai-writing-assist/c12e491f-e681-4986-8072-129229f032a3/scratchpad/picker/run-picker-check.cjs`。

### F2 · P3 · 恢复讨论时，已恢复的审批请求可能被清空

- 入口：`frontend-console/vue/composables/useProjectAssistant.js:107–109`，`selectSession` 先赋 `approvalRequest`、后赋 `blueprint`；`frontend-console/vue/components/ProjectAssistant.vue:137` 的同步 watcher 在 `context`、`blueprint`、`taskHint` 变化时把 `approvalRequest` 置空。
- 触发：当前讨论带 `research` 等蓝图，切到草稿里有 `approvalRequest`（只在无蓝图时可设）的讨论。用同顺序的 Vue 脚本重放：上一个讨论无蓝图时保留，有蓝图时变 `null`。
- 影响：失败关闭的方向，作者要重新选一次自动批准，不会多授权。
- 修法：把 `state.approvalRequest = …` 挪到这三项赋值的最后。watcher 的本意（范围变化即清除审批请求）不变；`ProjectAssistant.vue:184–197` 的 `open(request)` 在 `selectSession` 之后主动改 `context`、`blueprint`、`taskHint`，那里清除是预期行为，不要动。
- 验收：watcher 在组件里，composable 单测看不到它，用例要放进挂载组件的 `frontend-console/tests/vue/assistant/ProjectAssistant.test.js`：先带蓝图，再恢复无蓝图且有 `approvalRequest` 的草稿，断言请求保留；原用例不改。

### F3 · P3 · 关系修改历史没有上限，并随列表响应带出

- 入口：`backend/modules/world/relation_changes.py:259` 每次修改都把完整的 before/after/回执快照追加进 `review_meta["author_change_history"]`。`EntityRelationListResponse.items` 是 `EntityRelationResponse`（`backend/modules/world/schemas/relations.py:176–179`），其 `review_meta`（:140）原样返回；`backend/modules/world/assistant_validity_tools.py::_read`（:39–58）把同一份列表 dump 给助手。前端不读取这个键，历史走专用的 `change_history`（`relation_changes.py:173` 起，已按 `skip`/`limit` 分页）。
- 影响：反复修改的关系，列表和助手读取的载荷随修改次数一直变大。
- 修法（倾向）：存储保持完整，因为恢复需要全部历史；只在 `EntityRelationResponse` 输出时去掉 `author_change_history`（或只留条数），完整历史仍由 `change_history` 分页返回。若改为存储封顶，先回答“超出上限的旧修改是否还要能恢复”，并同步 `backend/modules/world/README.md` 和恢复测试。
- 必守：恢复不能丢快照；`project_relation_state(review_meta=…)` 等读取 `review_meta` 其他键的代码行为不变。
- 验收：同一关系连续修改 N 次后，列表响应和助手 `_read` 都不含完整历史、体积不随 N 增长；`change_history` 仍返回全部且可恢复。

### F4 · 不要求处理 · 审批尝试没有“已消费”标记

`backend/modules/assistant/approval.py` 的 `require_execution_approval`（:628）不检查 attempt 是否已有 `execution`。我追过的路径里，run 和 grant 的行锁一直持有到领域事务结束，没有可达的重复执行，所以不是缺陷。按 AGENTS.md “不为假设需求新增”的原则建议不动；只有后续改动让重复进入成为可能时，再补一个已消费检查。

## 4. 建议顺序与门禁

1. 顺序：F1（含 WebKit 门禁用例，是合并阻断项）→ F2 → F3。每项先写出复现再修根因，完成受影响单测。
2. 收尾：`make lint`、`make docs-check BASE_REF=origin/main`、`git diff --check`、前端全量 vitest；F1、F2 另跑 WebKit 门禁；F3 跑 `backend/modules/world/tests` 与 Assistant 相关测试。
3. 门禁分母：`binary-growth-gate`、`file-size-gate`、`release-evidence-gate` 只比较 `origin/main..HEAD`，工作区未提交时检查 0 个文件，提交后必须重跑。

## 5. 评审时已验证，不必重做

以下以第 1 节指纹对应的工作区为准。

- 后端快速层完整：`cd backend && uv run --locked --extra ci -- pytest -n auto --dist=loadscope --timeout=120 -q -p no:cacheprovider` → 9291 passed、2 skipped、103.7s、exit 0（内存 SQLite）。
- 前端：`cd frontend-console && npx vitest run` → 267 文件 / 3318 passed。
- `make lint`、全量 eslint、module-import-gate、secret-hygiene、`git diff --check` 干净；`make docs-check BASE_REF=origin/main` 通过，且会纳入工作区与未跟踪文件，不是空跑。
- Alembic 单头；`20261018_assistant_approval`、`20261018_world_review_scope`、`20261018_review_scope_index` 线性衔接，外键目标有效；所有文件都在 5000 行以内。
- 读过且未发现问题：`approval.py` 全文、`approval_calibration.py`、`approval_cases.py`、`candidate_selection.py`、`localDraftBackup.js`、`WorldRelationMaintenance.vue`、`WritingReferenceSearch.vue`、`WritingRevisionGroups.vue`，以及 assistant `service.py`、`operation_scope.py`、`evidence_tools.py`、world 路由与 repositories、`codex_provider.py` 的 diff。
- 不是本分支引入：`WritingView.test.js` 的 `localhost:3000` ECONNREFUSED stderr。来源是 `toggleOutlineFloat → loadOutlineArcComparisons`（`useWritingWorkspace.js:1593/1505`）→ `api/_shared.js:428` 在 happy-dom 里发出真实 `fetch`；相关产品代码和该测试文件在工作区都未改动。这也回答了 [TASK.md](TASK.md) 里“该后台请求尚未归因”。要消除可让该测试 mock `fetch`，不属于本批。

## 6. 未验证，不得宣称

- 没有跑 PostgreSQL e2e 与 Playwright 套件，也没在 PG 上重跑迁移。本任务的专用容器 `ai-writing-assist-author-workspaces-e2e-20261018` 在 2026-10-19T01:02+08:00 为 Up（healthy）；库名、端口与环境变量约定见 [TASK.md](TASK.md) 的恢复快照和验证证据，凭据不入仓库。只复用该容器里确切的库；同机其它容器（`ai-novel-db`、`guimi60-v3-pg-*`、`map-*`、`g7-*`、`wave3-*`、`g6b-*` 等）属于真实数据或别的任务，不要碰。
- 真机 Safari / iOS、真实 Firefox-on-macOS 未验；WebKit 结论来自 Playwright 的 WebKit 构建。
- 真实 LLM 与校准运行未做，也不在本批范围。

## 7. 交付前待用户决定

- 全部是未提交改动，未跟踪文件需要 `git add`（含 `.agent/` 下 14 个）。
- 分支名 `codex/writing-workbench-ai-research` 与内容（作者工作台统一改造：+5321/−302，另有 45 个新文件）已不相称；是否改名、拆 PR 由用户定。不直接提交 `main`。

## 8. 可执行的第一步

核对第 1 节指纹；然后在 `frontend-console/shared/referencePicker.js` 按 F1 加 `mousedown` 守卫并在 `destroy()` 移除，在 `frontend-console/tests/shared/referencePicker.test.js` 加断言，运行 `cd frontend-console && npx vitest run tests/shared/referencePicker.test.js`，再按“环境坑”做一次真实 WebKit 点选。

## 9. 本轮交接验证

写完后 `make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过；本文的相对链接和明确的仓库路径均核对存在，行号逐项回查过。本轮只写 `.agent/` 下的任务笔记（本文、[TASK.md](TASK.md) 的恢复快照、里程碑与发现、`.agent/TASKS.md` 索引），第 1 节指纹复算不变。没有重跑业务测试，第 5 节数字是评审时点的证据。
