---
id: T-20261017-map-series-review-fixes
title: 地图系列 Claude review 并行修复与主会话验收
status: in_progress
created: 2026-10-17T13:50:25+08:00
updated: 2026-10-17T15:23:12+08:00
---

# 地图系列 review 修复

## 恢复快照

- 实际完成：原 31 项修复已工程验收；本次按后续复审修复 R1–R12，定向回归及最终 lint、文档和 diff 门禁通过。
- 后续核对更正：2026-10-17 15:16 的独立核对报告发现 V1/V2 两项 P2；本次按用户后续要求修复并补回归，详见 [核对报告](../T-20261017-map-series-sol-review/VERIFICATION.md)。
- 当前里程碑：原 31 项、R1–R12 及 V1/V2 均已完成本地工程修复与定向验收。
- 下一步：按用户新增授权提交修复、创建 PR，等待适用远端门禁通过后合入 main。部署与真实模型/作者验收不在本次范围。
- 阻塞：无。2026-10-17 用户已明确授权提交、开 PR 和合并；尚未授权部署。
- 工作区：`.worktrees/map-series-review-fixes`；基线 `3b2ac9441c0dc08533a3e62269cd054ff35c5302`，业务审查基线 `a479e006bc336c0009e5207f7659609ab483e901`。
- 专用 PostgreSQL 与 MinIO 已停止，测试数据/日志保留；未操作既有业务、诡秘验收和评测库。
- 最后核实：2026-10-17T15:23:12+08:00。

## 目标与验收

用户要求规划 Luna/xhigh 子代理并行修复一轮，由主会话验收并修复剩余项。
原 32 项以 [原审查汇总](../T-20261016-map-series-claude-review/SUMMARY.md) 和 BATCH-1..10 为准。
用户明确答复 B10-F2 “按既定计划留到 ADR-0042”，因此本轮验收 31 项；不将延期项记为已修复。
本轮目标用例均已移除 strict xfail/it.fails，补齐四项原无测试发现的回归。

## 分工与结果

所有子代理为 `gpt-6-luna/xhigh`，独立 `.worktrees/map-fix-*`，无提交；主会话统一应用补丁并审查。

| 分工 | Finding | 结果 |
|---|---|---|
| vocab | F1/F2 | 合并词条链使用有效目标特性；去重检查保留墓碑名称 |
| clues | B2-F4/F5 | 类型提议冲突仅撤可选提议；同地点采用与原词条修订可重验 |
| draft | B3-F1..6 | 线索状态、采用节点优先、局部失效、有效期、v1升级、读者行程证据 |
| evolution | B2-F1/F2/F3/F6、B4-F2 | 可选步骤 stale 结算、密度、当前证据、完成补扫复用、drained提醒 |
| dossier | B6-F1..3 | CoreEntity/档案双向同步、旧面向编辑导入、当前作者拒绝或更正优先 |
| director | B7-F1/F2 | 回合内硬预算、回合间软阈值；原分支检查点恢复；意图/结算同场门槛 |
| story | B7-F3/F4 | 档案与原确认交集；冻结来源身份复核；事件级重排时点投影 |
| frontend | B5-F1..4、B9-F1、B10-F1 | 阅读/补扫状态门槛、默认模式、选择恢复、409真实原因、作者语言 |
| assistant | B8-F1 | 规划目录与计划校验共用实际凭据依赖排除 |
| 主会话 | B4-F1/F3 及集成剩余项 | 文本途经点保留；引用绑定原确认；多组档案投影、遗漏适配器、技术文案和调用方补齐 |

## 决策与边界

- B10-F2 留到 ADR-0042；不实施旧前瞻人物反应的新生成入口，不覆盖其他 worktree 的 ADR 草案。
- 地图引用保存原 confirmation ID；回读重新物化同一确认。旧无范围凭据且内容变化的引用不展示扩大的正文。
- CoreEntity 三个旧文本列只汇总同一 `legacy_field_key` 的当前无锚条目；不拼入其他面向。双组编辑、清除、恢复均有实际 ORM 回归。
- 持续推进保持根 confirmation 截止点与累计预算。新 Scene 超出范围时持久化 `stop_reason` 并停用授权；免费 outbox 返回状态，不使已提交章节报失败。作者需从最新场景新建并确认推进，再开启提醒。这是当前产品限制。
- 新增非破坏性迁移 `20261017_wp_scope_stop`，追加 nullable 停止原因列；专用 PG 升级与 fresh migration 门禁通过。
- `evals/authoring_quality_product.py` 的遗漏读取调用方已接原确认编译和范围交集；未改冻结评测材料、账本或请求，未跑真实模型。

## 验证证据

日志在仓库外 `/tmp/`。以下为本地工程验收，不代表真实模型、作者或生产验收。

| 范围 | 最终结果 | 日志 |
|---|---|---|
| 实现前 docs | 通过 | `/tmp/map-series-fixes-docs-baseline.log` |
| 后端全量 + RuntimeWarning 门禁 + 覆盖率 | 9156 passed、2 skipped，85.23%，13 warnings | `/tmp/map-series-fixes-backend-final.log` |
| 前端全量 | 258 files、3246 passed | `/tmp/map-series-fixes-frontend-full.log` |
| deploy 静态/CLI 合同 | 324 passed | `/tmp/map-series-fixes-ci.log` |
| 依赖审计与 secret hygiene | 后端无已知漏洞、前端0漏洞、secret hygiene通过 | `/tmp/map-series-fixes-ci.log` |
| PG关键+受影响路径 | 174个不同用例在修正后均通过；首轮171通过/3失败，失败路径及相邻测试单独重验 | `/tmp/map-series-fixes-pg-final.log`、`-pg-recheck.log`、`-pg-readers-final.log`、`-pg-entry-fixed.log` |
| 浏览器11个相关文件 | 30个不同用例均通过；首轮28通过/1失败/1需专用harness，后者与修正用例共5项重验通过 | `/tmp/map-series-fixes-browser.log`、`-browser-recheck.log` |
| 前端 lint/build | 通过 | `/tmp/map-series-fixes-frontend-lint-final.log`、`-build.log` |
| 后端 lint/受影响文件格式 | 通过，59个Python文件格式通过 | `/tmp/map-series-fixes-final-ruff.log`、`-changed-format-final.log` |
| docs BASE_REF / repo gates | 通过；依赖指标517/517、规则未改 | `/tmp/map-series-fixes-docs-final.log`、`-repo-gates.log` |

首轮 `make test-ci` 因旧 mock/档案单条假设失败；修正后单独重跑完整后端覆盖率门禁、前端全量及必要检查，未宣称串联命令首轮全绿。

### 失败与补修

- 首轮后端7失败：6个 MagicMock 仓储单测未模拟新增异步档案同步，补 autospec stub 和 await 次数断言；导入测试改为指定词条查询，保留来源、秘密、内容与回滚断言。
- PG迁移降级复用一次性数据库，避免其他测试保留的 append-only 档案阻止降级；预算/HTTP用例改为先确认再完整预览，Assistant work 补真实确认前提；离线导演 helper 显式配置功能开关及缓存清理。
- 浏览器草图测试原把连接有效期附在地点上，改为断言地点有效期为空，采用后再次验证；正向 effective_change 区间由服务与 PG 参数化用例覆盖。
- 合并中漏掉的测试 import、重复的 Evidence facade 导入、未使用 enqueue helper、B10首段与无障碍标签技术术语均已由主会话补齐；未削弱断言或门禁。

## 保留限制与恢复

- 持续推进跨新场景需重新确认；B10-F2 延期。真实模型/稿件、冻结评测、完整365项功能浏览器、生产镜像与真实部署未执行。
- 后端日志保留 Pydantic schema 与 SQLite ResourceWarning；构建保留 chunk 大小提示。全库 format check 的159个既有未格式化文件与原 review 树一致，未扩大本轮格式化；受影响文件均通过。
- 修复分支、本轮9个子工作树及原用户WIP保留；没有 commit/push/merge/deploy。任务唯一主记录在本目录。
- 专用 PG `/private/tmp/map-series-fixes-pg-20261017`（56173，`test_map_series_fixes`）和容器 `map-series-fixes-minio-20261017`（56174）已停止，保留合成数据供复查；浏览器使用全新56175/56176端口，专用HTTP app禁止调用模型。

## 后续复审 R1–R12 修复

- 依据：[Sol 复审汇总](../T-20261017-map-series-sol-review/SUMMARY.md) 与 WORLD/STORY/ASSISTANT 分组报告。用户要求修复 12 项；保留本 worktree 现有 31 项补丁及迁移，不切换或覆盖其他 worktree。
- 当前实现：R1/R2 修正 CoreEntity 旧字段同步范围与清空幂等；R3 让共享回滚同步追加档案修订；R4 允许地图草图/托盘/通知重验同词条作者新修订；R5 确认求交前保留 Scene 身份；R6 服务端 append 预览和锁内启动均拒绝活动空间补扫；R7 pending 启动可用原 operation_id 幂等核对；R8/R9 首次/重开入口及跨根实际授权定位与关闭；R10 预览/启动复用相同预算指示；R11 离场收听者在裁决请求前拒绝；R12 明确 422 清除 pending 并保留可编辑输入。
- 决策边界：继续保留 B10-F2 按 ADR-0042 延后；不运行真实模型、真实稿件、作者质量验收或生产操作。
- 定向验证：`UV_CACHE_DIR=/tmp/ai-writing-assist-uv-cache make test TESTS="modules/world/tests/test_b6_core_entity_dossier_sync.py modules/world/tests/test_map_series_review_regressions.py modules/evolution/tests/test_map_series_review_regressions.py modules/story/tests/test_map_series_review_regressions.py modules/story/tests/test_world_progression_api.py"`，45 passed；在 `frontend-console/` 运行三个受影响 Vitest 文件，57 passed。
- 最终验证：定向后端 45 passed；三个受影响 Vitest 文件 57 passed；`make lint`、前端 `npm run lint`、`make docs-check BASE_REF=origin/main`、`git diff --check` 全部通过。
- 验证边界：本地离线工程证据；本轮未运行 PostgreSQL、浏览器、真实模型或作者验收。当前未提交、推送、合并或部署。

## 独立核对 V1/V2 补修

- V1：实体兼容同步先取真实最新字段修订；有可复用的无锚 active 组时续用该组的当前修订，否则新建无锚组。已锚定的 v2 不会让旧 v1 被当作组 head，时点条目仍保持 active。
- V2：截止点变化自动停止的授权继续留在旧根并显示停止原因；最新已完成新根显示重新授权入口。重开沿用项目当前 revision CAS，重新确认新根 Scene，并清空旧参与者选择，要求作者明确选择新根参与者。
- 验证：五个定向后端测试文件 46 passed；ReadingFlow、GoalRunsPanel、WorldProgressionPanel 三个 Vitest 文件 58 passed；`make lint`、前端 `npm run lint`、`make docs-check`、`make docs-check BASE_REF=origin/main` 与 `git diff --check` 均通过。
- 未执行：PostgreSQL 并发、真实浏览器、真实模型或作者验收。当前补丁留在原 dirty worktree，未提交或交付远端。

## 提交与合并交付

- 用户新增授权：提交，开 PR 合并。
- 已 fetch origin，当前 main 是修复分支祖先（0 behind / 388 ahead），未改写已有历史。PR 包含尚未合入的地图系列及 review 历史。
- 最新修复已由独立核对验收；提交前重新执行完整 `make test-ci TEST_WORKERS=2`，日志 `/tmp/map-series-delivery-ci.log`；结果待记录。
- 远端 PR 的 PostgreSQL、浏览器、镜像及其他适用检查通过后再合并，不跳过或削弱门禁。保留其他 worktree 与 WIP；不部署。
