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
- [x] 2026-09-21 会话 2：E02 完成——`evolution/identity.py` 确定性解析内核：
      仅精确名/别名证据自动 reuse（阈值永不自动合并）；同名多候选保持竞争
      （ambiguous，绑定冲突时把绑定对象补进候选集满足 ≥2 契约）；无精确 →
      new_candidate 记录模糊候选；观察者自带 UUID 绑定必须重验否则 unrelated。
      观察积累分离：解析不改 observation_id 不吞观察。world 候选经
      `facade.find_similar_entities` 结构适配（`candidates_from_world_results`）。
- [x] 2026-09-21 会话 2：E03a 完成——`continuity/reducer.py::StoryStateReducer`
      单一语义内核，章节重放与 Scene 投影委托；统一语义：manual_correction 与
      未知实体 entity_updated 一律入 changes（不造幻影不丢信息）、knowledge 同 id
      后写覆盖；章节重放状态/快照续算携带 changes。G0 两个缺口钉住测试转为
      一致性断言；T04 强化（knowledge 替换 + changes 相等）。
- [x] 2026-09-21 会话 2：T13 第一段对齐——助手新章/改写应用保存后显式
      `request_chapter_index`（与 API/candidate 工具同一调用），
      `test_assistant_side_effects.py` 断言。协作/导入两处仍缺，留 I02。
- [x] 2026-09-21 会话 2：E03b 完成——`replace_scene_events` 家族分区 +
      稳定 `meta.event_key`：作者确认与其他 producer 家族永不参与本调用替换；
      按键匹配的行原地更新（行 ID/槽位不变，T06 重排不重建）；未匹配行
      Core 立即删除 + expunge 防幽灵行；服务层统一注入 event_key
      （content_hash 语义指纹，不含输出位置）；`ingest_delta_events` 按
      (scene, source) 分组传 family；imports 空 Delta 重跑限定
      `producer_family="deep_import"`；facade `replace_scene_memory_events`
      加性可选参数。测试：`test_producer_replacement.py` 4 例（重排稳定/
      家族隔离/内容换键重建/legacy 全派生面）。
- [x] 2026-09-21 会话 3：E03c 完成——`evolution/commit.py` 窄提交协议：
      freeze_attempt 先持久化冻结负载（T10 恢复基础）；apply_frozen 短事务内
      重验 owner epoch（T12 前置，StaleOwnerError）→ 来源 manifest
      （CommitConflictError source_changed）→ 父回执身份与前缀
      （parent_advanced/parent_missing），再执行注入 applier 并保存回执——
      游标只在回执持久化后推进；同 attempt 重入直接重放原回执（T11，不重复
      领域写入）；recover_attempt 复用冻结负载、全程不接触 provider。
      存储经 AttemptStore port 注入（InMemoryAttemptStore 供测试；生产 PG
      实现随 E04/E07 接线）。T10/T11/来源漂移/父推进/失败无回执/旧 owner
      拒绝共 6 例故障注入测试。测试坑：rollback 会过期 ORM 属性（固化
      scene_id 字符串）并把未 commit 的场景行卷走（先 db.commit() 封存）。
- [ ] E04 orchestrator（前序屏障、有限并行、游标与预算）（未开始）

## 验证

- 2026-09-21 会话 2（E03b 后终态）：`continuity` 109 passed；`evolution`
  33 passed；`imports` 717 passed（含更新后的空重跑签名断言）；`writing`
  仅 1 例既有基线失败；lint 与 docs-check 通过（05_memory.md 已同步替换
  接口语义）。
- 2026-09-21 会话 2（中段记录）：`continuity` 105 passed；`evolution` 33 passed；`writing`
  仅 1 例既有基线失败；`imports` 全通过；world 35 例失败为基线既有
  （未改动基线复现归属，本地环境问题）。lint 与 docs-check（带
  no-change-reason）通过。已回退 ruff format 对范围外文件的无关重排。
- 2026-09-21 会话 1：`modules/story/continuity + modules/imports` 815 passed；
  `modules/evolution + continuity` 121 passed；`make lint` 通过；
  `python3 scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason "..."`
  通过（Makefile 的 docs-check 目标不透传 NO_CHANGE_REASON，须直接调脚本，
  理由见当日命令记录：E01 无 make 目标/文档流程/测试分级变化）。
- 本机既有基线失败（与本改动无关，基线 commit 复现）：outline_state
  test_repositories 2 例、test_foreshadowing_reveal 2 例、writing
  test_create_many_reads_versions_once_and_flushes_once 1 例。

## 恢复快照（2026-09-21 会话 3 结束，含 E03c）

分支 `codex/novelcraft-v4-g0-baseline`，累计 11 个提交：G0×2、E01、E02
（00d92dfb9）、E03a（d9bacadc2）、T13 对齐（60879dfd3）、E03b（1a9bb215e）、
E03c（d11fb140c）及任务/文档记录。**未推送、未合 main、未部署、未建 PR。**
E03b 与计划 §2.2 的差异（有意收窄）：以 `meta.event_key` JSON 键替代新列
（避免生产迁移，语义等价——身份=语义指纹而非输出位置）；producer_family
暂用 source 字符串（deep_import/ai_extraction），generation/input_revision
登记在 delta meta，完整 `replace_derived_scene_events(...)` 签名留给 E03c
随 evolution/commit 落地。
下一步：E04 orchestrator——前序屏障（后一 Scene 的输入必须实际包含前一
Scene 已提交回执，T07）、有限并行（read-set/dependency key 证明）、游标与
预算（T21 原子预留）；需要先落 AttemptStore 的 PG 实现与 run 注册表
（Alembic migration）。协作/导入索引缺口留 I02。G0 可并行项（R00/V00）
尚未认领。
