---
id: T-20261001-anw-review-remediation
title: anw-improvements 批次审查整改（12 项 + 测试缺口）
status: completed
created: 2026-10-01T21:30:00+08:00
updated: 2026-10-01T23:05:00+08:00
---

# anw-improvements 批次审查整改（12 项 + 测试缺口）

## 恢复快照

- 实际完成：首轮 12 项整改（65eaf13cf）+ 复审二次整改（0642d7dcf），已合并最新 main，经 PR #186 合入 main；本记录随该 PR 关闭。
- 当前里程碑：完成。
- 下一步：无。后续如需动 rag `total` 语义（rerank 下为 2×top_k 候选数）另开任务。
- 阻塞：无。
- 最后核实：2026-10-01T23:05:00+08:00。

## 目标与验收

- 目标与交付物：修复审查报告的必须修 4（B2 身份碰撞、A2 门禁不对称、A2 前端死路、B3 视角门控）、应修 4（B5 能力名映射、B1 冲突标签、A3 资料性质、B3 首开状态）、小问题 5（A4 复核失效、B1 基稿跳过提示、B2 迁移继承、B3 来源标签、EditorialDesk 竞态）+ 补三测试缺口（A2 链路、B2 碰撞、B5 真实 id）；复审发现的 CI 阻断与遗留缺陷一并修复后合入 main。
- 完成条件：后端全量（含 `backend/tests/`）+ 前端全量 + lint 通过；docs-check BASE_REF=origin/main 通过（PR 模板说明无影响文档）；PR CI 全绿后合并。
- 非目标：B4、C1–C4（按方案不实施）；不部署。

## 上下文与边界

- 首轮关键改动见 65eaf13cf 提交说明（editorial 身份锚点、unmet 归一与 major、targetedRevisionReady、EditorialBriefLoader 门控、ai_usage 映射、渲染两级、PUT effective、populate_existing、复读覆盖缺口、约定来源标签、EditorialDesk 守卫）。
- 二次整改（0642d7dcf）：
  - CI：`story/outline_state/tests/test_services.py` 补 AsyncSession 导入；for-writing 读写、ai-usage 登记 `PROJECT_OWNED_ACTIVE_BOUNDARIES`，导出路由前置 `require_active_project`；`tests/unit/test_context.py` loader 名单纳入 editorial_brief；剧情线集成测试按"超期保留、resolved/paused 排除"改写。
  - editorial.py：`_assign_identities` 同批撞键（对象型意见同类目同对象同章）按首条引文锚点区分；`_save_findings` 先查精确 key，再查另一形态别名（引文一致才迁移），最后 legacy。
  - semantic_review prompt：unmet 必须附最应补写处的唯一 excerpt 作为返修锚点。
  - markdown_renderer：world_entities 来源含未采用状态时标混合；historical_role_context 标派生。
  - EditorialBriefLoader：约定本会生效时才对角色视角留警告；EditorialDesk 开关文案说明「AI 角色视角建议」不使用，finally 无条件解除处理中。
  - ConflictDetailDialog：复读缺口（原稿被改/不可用）说明原因，仅此缺口时不劝重跑。
- 硬约束与授权范围：用户拍板"全部修复"+"unmet 一律不可直接采用"；复审后用户授权"按推荐修复后合并"，并确认 B3 角色视角收窄是修真实缺陷（刻意留白不得进入角色已知资料），保留收窄，只改文案。
- 决策：定向返修/批注改写复用冻结 confirmation 不重新编译，B3 门控无返修回归；A3 混排 section 标 mixed；B1 静默跳过走既有 degraded+omissions 通道；撞键区分只在同批碰撞时启用，保留对象型意见"改写措辞仍继承"的主路径。

## 决策、发现与失败

- 2026-10-01；首轮把 `test_retrieve_with_custom_top_k` 失败判为"重排序降级路径真 bug"——判断有误：真实原因是本机 `backend/.env` 开了 `RERANKER_ENABLED`，测试未隔离本机开关；已由 PR #184（根 conftest 钉住全部布尔开关）解决，合并 main 后该用例通过。
- 2026-10-01；首轮只跑了模块目录（modules/…、infrastructure/tasks），漏跑 `backend/tests/`，导致 5 个失败（守卫清单、loader 名单、剧情线旧语义）与 ruff F821 未被发现；收尾须跑后端全量与 `make lint`。

## 验证证据

- 合并 origin/main（6ea09b614）后：后端全量 6447 passed / 15 skipped；前端 vitest 2649 passed；`make lint`、`eslint .`、`make audit-backend-deps`、`git diff --check` 通过。
- docs-check：要求核对 indexing README / 01_数据库设计 / 05_memory，经核对无 ORM/migration、无 indexing、无 memory 改动，按 PR 模板第三项说明。

## 交付结果

- 已交付：PR #186（codex/anw-improvements-batch-a → main）。
- 未交付：B4、C1–C4（按方案不实施）；未部署。
- 正式知识：docs/modules/01_project、08_evidence、11_writing、14_frontend、docs/prompts/Prompt体系设计 已同步。
