# P2-C 交接快照（world-foundation / 2026-10-08）

> 交接对象：继续推进 [第二阶段并行执行规划](../../../docs/plans/2026-10-07-world-foundation-phase2-parallel-execution.md)
> 的 P2-C 汇合批。主任务记录：[TASK.md](TASK.md)（权威，本文件只做恢复快照，不替代记录）。

## 1. 环境

| 项 | 值 |
|---|---|
| worktree | `/Users/tywww/.codex/worktrees/world-foundation-plan/ai-writing-assist` |
| 分支 | `codex/world-foundation-phase1-plan`（phase1+P2 一并走 PR 合入 main） |
| shell | 每次 Bash 调用后 cwd 重置，命令必须显式 `cd` 到上表绝对路径 |
| 真 PG | 127.0.0.1:5207（`novelist` / `novel_dev_pass`），本轮专用库 `agent_e2e_world_p2c_20261008`（已 `alembic upgrade head`） |
| 授权边界 | 全离线：零 LLM 调用、零真实数据写入、不延伸 USD 20 授权；R7 未闭合留在父任务 |

## 2. 进度

| 批次 | 状态 |
|---|---|
| P2-A（A0–A4 + 汇合） | 完成并已提交 |
| P2-B（B0–B3 + 汇合） | 完成并已提交 |
| P2-C C0 夹具 / C1 登记缝 | 完成并已提交（C1 在 `bb431027b`） |
| P2-C C2（evolution 登记与失效细化） | 完成，**未提交** |
| P2-C C3（writing 回执透传 + 重算编排） | 完成，**未提交** |
| P2-C C4（前端失效提示 + 重算面板） | 完成并对齐 C3 真实端点，**未提交** |
| P2-C 汇合批 | 进行中（见 §4） |

C0 十五例夹具已全绿（C2 转绿①③④，C3 转绿②）。

## 3. 未提交改动（文件级）

修改：

- `backend/app/bootstrap.py`、`backend/core/service_keys.py`（DI 键 `EVOLUTION_INVALIDATION_RECEIPT_VIEW`）
- `backend/modules/evolution/`：`invalidation.py`、`facade.py`、`README.md`、`tests/test_consumption_registry.py`、`tests/test_p2c_revision_adoption.py`（摘②xfail）
- `backend/modules/writing/`：`repositories.py`、`contracts.py`、`schemas.py`、`services.py`、`api.py`、`README.md`
- `docs/modules/11_writing.md`、`docs/modules/22_evolution.md`
- `frontend-console/api/evolution.js`、`frontend-console/vue/views/writing/components/WritingEditor.vue`、`frontend-console/vue/views/writing/controllers/editorController.js`

新增：

- `backend/modules/evolution/registration.py`（登记写入端：构建 + 幂等合并，零 DB/零 LLM）
- `backend/modules/evolution/impact.py`（失效影响组装层：登记读取 + 锚定合成 + 回执视图投影）
- `backend/modules/writing/recompute.py`（重算编排服务，独立新文件避开 services.py 热点）
- `backend/modules/writing/tests/test_p2c_recompute.py`（10 例）
- `backend/tests/e2e/test_p2c_invalidation_recompute.py`（真 PG API 级，3 例）
- 前端：`vue/views/writing/invalidationModel.js`、`components/InvalidationNotice.vue`、
  `components/RecomputePanel.vue` + `tests/vue/writing/` 下 4 个测试文件

## 4. 关键裁定（改动的事实基础，勿回退）

- **登记不加表**：`ConsumptionRecord` 内嵌产物行 `state_json["_consumption_registry"]`，随 supersede 软删，旧数据退化为空。
- **无接线期的可解释性**：锚定变更章且无真实登记时，按 outline 结构合成整章登记
  （`method_version="anchored-scene-implicit-v1"`）；真实登记优先；评估窗口与现状保守扩大逐位一致（`from == earliest`）。
- **回执通道**：`repositories._changed` 接住 DI 返回值 → `receipt_view` 投影为作者语言公共视图 →
  draft 行的**瞬态属性** `invalidation`（非映射列，不入库）→ `WritingDraftContract.invalidation`
  → autosave/publish/update 响应自动携带。
- **重算端点**：预览 `POST /api/writing/recompute`（纯读、零正史写入）；执行
  `POST /api/writing/recompute/{operation_id}/adopt`（`confirmed:true` +
  `expected_source_digest`）；来源漂移 → 409 `recompute_source_drift` 且 `keep_current_draft: true`；
  `regenerate_prose` 无白名单支撑 → 409 `recompute_scope_unsupported`（零 LLM）。
- **幂等**：`operation_id + request_hash` 双键；重放落在本身幂等的域动作上（reload 复用同一任务、rebuild 短路）。
  **已知缺口**：无持久 operation 台账，`replayed` 标记与"同 id 异内容拒绝"未实现（C2 回执落库可作后续锚点）。
- **import-gate 双向对**：`writing/recompute.py` 的 story 门面降为函数内导入；等量补偿把
  `repositories._changed` 与 `services.py` 两处 `evidence.facade.mark_asset_context_changed` 提升为顶层。
  gate 棘轮 65/9/0/525/0/26 未推高。
- **窗口语义**：物理投影失效仍是窗口语义，无关 Scene 仍被物理失效但**不进**归因/重算清单；
  按集合 supersede 与 story 侧真实登记接线留 B 类。
- 前端回执历史为**本地会话内**记录（刷新即失，跨会话经 adopt 幂等重放重查），limitation 写在模块头注记。

## 5. 汇合门禁执行结果（2026-10-08）

| 门禁 | 结果 |
|---|---|
| `modules/writing`+`modules/evolution`+`modules/collaboration` | 635 passed、1 deselected |
| `modules/story`+`modules/evidence`+`tests/unit` | 3070 passed（1 例 `test_dev_stack_entrypoint` 首次失败，独立复跑 24/24 全绿，属临时目录/环境噪声） |
| 真 PG `tests/e2e/test_p2c_invalidation_recompute.py` | 3 passed（专用库 `agent_e2e_world_p2c_20261008`） |
| `ruff check` | All checks passed |
| `ruff format --check`（仅本轮改动文件） | 15 files already formatted（全库 `--check` 的 162 条是 ruff 0.16.9 与仓库既有格式的基线差异，main 工作树同样 178 条，与本轮无关，不得顺手全量重排） |
| `make module-import-gate` | passed，棘轮未推高 |
| 前端 `vitest` 全量 | 230 文件 2863 例：2861 passed；2 例 `tests/api-contract.test.js` 报 `Test timed out in 5000ms`，单独复跑 14/14 全绿——全量并发下文件扫描变慢导致的超时，非契约缺陷（该测试默认 5s 超时，独立运行 1.3–1.9s） |
| 前端 `eslint` | 0 问题 |
| 浏览器关键流 `creative-rebase.spec.js` | 3 passed（真 PG + Chromium，含 390px：可见知识/历史依据/开锁假设比较/试改绑定）。本机跑 Playwright 必须绕代理：`NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1`，否则环境代理让所有 localhost 端口返回 502，webServer 误判端口被占用 |

## 6. 本轮修掉的两个汇合缺陷

1. **模块 README 链接断链**：`evolution/README.md`、`writing/README.md` 新增段落用了
   `../../docs/modules/2x_*.md`（指向不存在的 `backend/docs/`），已改 `../../../docs/...`。
   这是 `docs-check` 完整性门禁报的 ERROR。
2. **差异影响门禁的逐项核对**：`--base-ref origin/main` 列出 5 份必查文档未更新，已逐项核实并给出
   无影响说明（PR 正文第三项勾选时必填），在本轮以 `--no-change-reason` 验证降级为 WARNING、退出码 0：
   - `CLAUDE.md`：15 行纯导入指针，bootstrap 仅新增既有 DI 缝注册，不改导入结构与权限边界；
   - `module-architecture.drawio/html`：未新增/合并模块、未新增跨模块依赖边（棘轮未推高）；
   - `documentation-maintenance.md`：触发源是 Makefile 新增 `eval-rp-cost-baseline`（RP 成本基线，非文档门禁/CI 入口）；
   - `docs/modules/07_outline.md`：story 改动仅限 continuity（字段来源/知识方言/揭示边界）与 facade 再出口，
     未改 outline_state，语义已更新 05_memory.md、19_story.md 与 story README。

## 7. 收尾状态（2026-10-08 已完成）

1. ✅ 前端真实浏览器关键流 3 passed。
2. ✅ 固定提交 4 笔：`feat(evolution)` 登记与失效 → `feat(writing)` 透传与重算 →
   `feat(frontend)` 提示与面板 → `docs` 文档与任务记录同步。
3. ✅ PR [#206](https://github.com/FengHuoLinShan/ai-writing-assist/pull/206)（phase1+P2 一并合入 main）
   已开，正文含 §6.2 的无影响说明原文；待合并授权与 CI。
3. C2 记录的 B 类待办（story `_project_dimension` 真实登记接线、按集合 supersede、持久 operation 台账）不在本包授权内，留后续。
