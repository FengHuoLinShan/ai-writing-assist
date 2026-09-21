# NovelCraft V4 长期计划实施

- id: T-20260921-novelcraft-v4-implementation
- title: NovelCraft V4 演化式小说整体引擎长期计划实施
- status: active
- created: 2026-09-21T00:00:00+08:00
- updated: 2026-09-21T00:00:00+08:00

## 意图与授权

用户指令（2026-09-21）：「实现此长期计划」，附件为 NovelCraft-V4-Long-Range-Plan-and-HiFi.zip。
按 AGENTS.md 自主决策条款视为执行授权；但该计划是 G0–G8 多里程碑长程计划，
单次会话不可能完成全部，按计划自带的关键依赖链推进：
`G0 → E01/E02/E03 → E04 → G2 → E07/E08 → G3`（地图壳/前端统一宿主可并行）。
每个里程碑独立分支提交；G0 为首个发布阻断修复包。

## 权威输入

- 计划包已复制到 `docs/plans/novelcraft-v4/`（来源 zip 在 ~/Downloads，勿再依赖）。
- 入口：`plans/00-MASTER-v4.md`；演化：`plans/01-EVOLUTION.md`；
  追踪与验收矩阵（T01–T36）：`plans/05-TRACEABILITY-ACCEPTANCE.md`；
  证据与代码核对（N01–N05）：`plans/06-SOURCES-AND-AUDIT.md`。
- 代码基线：`b5a3ef2e6`（计划即按此 commit 静态审查编写，与当前 main 一致）。

## 关键决定

1. **G0 = E00/E07.a**：人工事件保护 + 两视图归约契约测试 + 重复实现清单 + 入口副作用矩阵。
   这是计划 §7 表格与 01-EVOLUTION §7.2 明确的"新模块开发前先修旧链保护"。
2. **保护策略**：`replace_scene_events()` 内做权限分区（protected = author authority），
   机器行按"跳过保护槽位的顺序分配"落位，不引入序号带迁移（避免既有数据迁移），
   不改 `append_confirmed_scene_event` 语义。producer/generation 细分留给 E03。
3. **两套 reducer 分叉**（章节视图 `services._apply_event_to_replay_state` vs
   Scene 视图 `scene_projection._apply_event`）G0 只钉住共同路径契约并记录缺口，
   统一语义内核属 E03，不在 G0 顺手改。
4. 计划文档放 `docs/plans/`（历史/长程计划区，不进 architecture-documents.toml 注册表）。

## 进展

- [x] 2026-09-21 会话 1：调查确认 N01 风险在当前代码成立（replace_scene_events 无来源分区；
      空 Delta 重跑经 imports `_record_deltas` → facade `replace_scene_memory_events(events=[])`
      会删除 author_confirmation 事件）；两 reducer 分叉点确认。
- [x] 2026-09-21 会话 1：计划包入 `docs/plans/novelcraft-v4/`；分支 `codex/novelcraft-v4-g0-baseline`。
- [x] 2026-09-21 会话 1：G0 全部完成——人工事件保护修复（repositories.py 作者权威分区 +
      跳过保护槽位的机器行分配）、契约测试 5 例（T04/T05 + 两个缺口钉住）、
      G0 基线文档（重复实现清单、入口副作用矩阵、语义缺口）。
      入口副作用矩阵发现：助手应用/创意采用/协作采用/导入四类入口缺
      `request_chapter_index`（上下文失效已由仓储层 `_changed/_created` 收敛），
      留 I02 统一领域变更回执时修。
- [x] 2026-09-21 会话 1：E01 契约层完成——`backend/modules/evolution/`（contracts.py +
      observations.py + 23 测试）。SourceRevisionRef（range_hash 确定性推导）、
      ObservationEnvelope（modality 七态、MentionRef 禁伪造 UUID）、IdentityResolution
      （reuse 须候选证据、ambiguous 须 ≥2 候选）、TypedStateOperation（observe/move 分离、
      knowledge 须主体、documentary_assertion 不改状态）、EvolutionReceipt
      （failed/blocked/unknown_billing 游标必须等于前值且禁止倒退）。
      稳定观察 ID = sha256(来源范围+观察语义+契约版本)，无输出位置/run id（T06）。
      已注册 architecture-documents.toml / 00_整体设计 / CONTEXT / docs README /
      架构图 drawio+HTML（docs-check 带 no-change-reason 通过）。
- [ ] E02 world identity seam + evolution/identity（未开始）
- [ ] E03 story reducer 统一 + evolution/commit（未开始）

## 验证

- 2026-09-21 会话 1：`modules/story/continuity + modules/imports` 815 passed；
  `modules/evolution + continuity` 121 passed；`make lint` 通过；
  `python3 scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason "..."`
  通过（Makefile 的 docs-check 目标不透传 NO_CHANGE_REASON，须直接调脚本，
  理由见当日命令记录：E01 无 make 目标/文档流程/测试分级变化）。
- 本机既有基线失败（与本改动无关，基线 commit 复现）：outline_state
  test_repositories 2 例、test_foreshadowing_reveal 2 例、writing
  test_create_many_reads_versions_once_and_flushes_once 1 例。

## 恢复快照（2026-09-21 会话 1 结束）

分支 `codex/novelcraft-v4-g0-baseline`（自 origin/main 新建），3 个提交：
`6da363557` docs 计划包+G0 基线 → `9448184c2` fix(story) 人工事件保护 →
`752b5c5a7` feat(evolution) E01 契约层。**未推送、未合 main、未部署、未建 PR。**
下一步：E02（world facade + evolution/identity：身份去重与观察积累分离，
重点验证"已有身份不跳过新观察"）；随后 E03（统一两套 reducer 为单一语义内核 +
evolution/commit 窄提交，消化 G0 钉住的两个缺口测试）。
G0 可并行项（R00 前端选区传递、V00 地图壳）尚未认领。
