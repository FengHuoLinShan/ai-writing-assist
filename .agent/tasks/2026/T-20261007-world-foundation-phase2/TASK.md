# T-20261007-world-foundation-phase2

---
id: T-20261007-world-foundation-phase2
title: 世界演化第二阶段实施（P2-A/B/C）：可信历史与低成本改稿
status: active
created: 2026-10-07T00:00:00+08:00
updated: 2026-10-07T00:00:00+08:00
parent: T-20261006-world-foundation-phase1-impl
---

## 目标与授权

实施 [第二阶段主计划](../../../docs/plans/2026-10-07-world-foundation-phase2.md)，按
[并行执行规划](../../../docs/plans/2026-10-07-world-foundation-phase2-parallel-execution.md)
以子代理批次推进三顺序包：P2-A 历史字段与来源 → P2-B 知识值与揭示边界 → P2-C 实际依赖与局部重做。

授权边界：全部批次离线执行，零 LLM 调用、零真实数据写入、不延伸 USD 20 授权；
R7（真实质量/费用/留出门禁）未闭合留在父任务，不得核销为 P2 工作；不默认开放 formal family。

工作区：worktree `/Users/tywww/.codex/worktrees/world-foundation-plan/ai-writing-assist`，
分支 `codex/world-foundation-phase1-plan`（领先 main 6 提交，落后 0，基线 `b40cd0c5a`）。
phase1+P2 一并走 PR 合入 main。

## 执行方式（来自并行规划，勿回退）

- 三包串行（scene_state_view.py / reducer.py+schemas.py / scene_projection.py+repositories.py /
  scene_lens.py / basis.py 是跨包写入热点）；包内"契约先行 → 2–3 子代理按独立文件组并行 → 汇合验收"。
- 子代理只改文件+跑测试，禁 git commit/push；主会话统一验证提交。
- 契约批独占 schemas/contracts/service_keys；facade 归当包主线单元。
- 每包第 0 步先固定验收夹具与预期（xfail 形态），汇合时转绿。
- 批量派发每批 ≤3 子代理。

## 批次状态

| 批次 | 内容 | 状态 |
|---|---|---|
| 启动 | 任务记录 + 并行规划提交 | 进行中 |
| P2-A 批1 | A0 夹具 ∥ A1 契约先行 | 待派 |
| P2-A 批2 | A2 写入端 ∥ A3 读取端 ∥ A4 展示端 | 待 P2-A 批1 |
| P2-B 批1/批2 | B0 夹具 ∥ B1 方言统一；B2/B3/B4 | 待 P2-A |
| P2-C 批1/批2 | C0 夹具 ∥ C1 登记缝；C2/C3/C4 | 待 P2-B |

## 关键代码事实（三个只读调查子代理确认，2026-10-07）

- 模块根在 `backend/modules/`（非 backend/app/modules）。
- 三母题字段全是自由 payload 无注册：`CharacterLocationInPanorama`（continuity/schemas.py:73）、
  custody_owner/custody_holder、opening_key_id/opening_moon_phase/opening_passphrase；moon_phase 在
  timeline facts payload。
- evidence_refs 现为维度级集合；`evidence/source_ref_contracts.py:19-28` 的 SourceRangeRefContract
  已存在可复用（continuity 未用——零成本接入点）。
- `scene_state_view.py`：_entries_for:303、_filter_entries:569、_knowledge_grants:530（值绑定经
  stable_hash）、_reveal_cache:608；UNSUPPORTED_DIMENSIONS:39。
- 历史 checkpoint 回开 `scene_projection.get_record:221` 返回 raw state_json 不过视角边界（P2-B 修）。
- 两套揭示系统默认相反：Story RevealPlan 无策略默认公开（outline_state/contracts.py:531）vs
  World ReaderRevealPolicy 无 cutoff 默认隐藏（knowledge_visibility_service.py:140-167）。
- Evolution 机器路径 `KnowledgeInPanorama`（schemas.py:81-91，state_gate.py:216 校验）无
  subject_id/fields/known_values，表达不了值绑定。
- `state_trial.py` 三值裁决（verdict:231-238）uncertain 分支零测试。
- `evolution/invalidation.py` coverage_note:227-230 明言细粒度登记缺失；apply_source_invalidation:209-232
  保守扩大；UNSUPPORTED_CONSUMERS:33-42。
- writing `repositories.py:38-62` 调 DI 缝（service_keys.py:131-133 / bootstrap.py:421-423）但丢弃
  InvalidationReceipt 返回值——P2-C 最小首步透传。
- 前端：SceneLensSummary.vue:111/:118 下钻入口已有；`POST /memories/scene-state-view`
  （continuity/api.py:187）无直接前端调用方；api/evolution.js 无失效端点。
- Collaboration 侧 P2-C 基本复用：试改零正史写入、merge.py:87-112 双幂等、recovery.py 三向 rebase。

## 跨会话陷阱（沿父任务，新会话必读）

- shell cwd 每次 Bash 调用后重置，命令必须显式 cd 到 worktree 绝对路径；子代理同。
- 生产 autoflush=False：改 ORM 属性后必须显式 flush（populate_existing 重读陷阱）。
- evals 模块严禁 import 时改 os.environ（模块级污染挂全量）。
- scene_lens(evidence)→story 保持函数内导入（顶层会成双向对，module-import-gate 基线 0）。
- 单测库 SQLite 无触发器；真 PG 在 5207（novelist/novel_dev_pass）；e2e 需 -m e2e。
- @patch/mock.patch 一律 autospec=True；生产禁 Mock。

## 验证与提交

每包收尾：受影响模块测试 + lint → `make docs-check`（world/story 影响）→ 真 PG migration（有 schema
变更的包）→ 前端关键流 → 固定提交 + 脱敏验证记录回写本文件。

## 恢复快照

（交接/暂停前更新）当前：启动批进行中，下一步派发 P2-A 批1（A0+A1 两个子代理）。
