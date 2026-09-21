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
- [x] 2026-09-21 会话 4：E04 完成——三表 + 迁移 + 编排内核：
      `evolution_models`（evolution_runs：owner epoch/已提交前缀游标/根预算；
      evolution_frozen_attempts；evolution_receipts）+ Alembic
      `20260921_evolution_tables`（本地真 PG ai_novel_acceptance_guimi 验证
      到 head、三表建成；注意 alembic.ini 写的 ai_novel_engine 是旧库，
      实际走 settings 的 guimi 库）。`store.PostgresAttemptStore` 绑定
      (db, novel_id) 实现 AttemptStore：回执落库同事务推进游标+head、
      回执不可改写、reserve_budget 条件 UPDATE 原子预留（T21）。
      `orchestrator.py`：prepare_scene_input 前序屏障（T07：Scene N+1 输入
      实际包含 Scene N 已提交回执，前序未提交显式 blocked 不带假结论）；
      plan_parallel_batches 确定性准入（同 Scene 依赖键不相交并行、
      键冲突/叙事顺序分批）。10 例新测试（含并发预留恰好耗尽预算）。
      本机坑：出现 `* 2.py` 陈旧副本文件破坏 lint（第三次遇到，删除即可）。
- [x] 2026-09-21 会话 5：E05 完成——`evolution/invalidation.py`：
      compute_source_change 物理差异（同字数替换给出非空窗口，T08 的
      4000 字后场景有专测）；apply_source_invalidation 传播正文变更
      （evidence request_chapter_index 换源重建 + Scene 投影软 supersede，
      保守扩大自锚定受影响章的最早 Scene，回执记 coverage）；
      apply_scene_reorder_invalidation（align_scene_indices + 从最早移动
      Scene 起失效，T09）。失效不删历史（作者确认保留有专测）。未接缝
      消费者 world_knowledge/map_atlas/assistant_suggestions 显式
      unsupported（待 G2/V/R 接线）。新增 story facade 薄缝
      supersede_scene_projections_from（story/facade __all__ 已登记）。
      测试坑：全角句号与逗号同为一字符（长度变更用例别拿它造长度差）；
      stage0 快照 scene_index 为 None 断言要排除。
- [x] 2026-09-21 会话 6：G2 纵切完成——pipeline.run_scene_step 组合器
      （屏障→预算预留→采样→观察→身份解析→冻结→窄提交，sampler 注入）；
      consumers.check_suggestion_validity（T17：索引指纹分叉即失效，含
      "已请求未重建"态；失效回执接线 assistant_suggestion_validity）；
      story/continuity/presence.py 在场投影（T03：仅自带 moved_from 证据
      才 traveled，否则 unknown 不造路程）。端到端切片
      test_g2_vertical_slice.py（林舟/青竹/白石城/铜钥匙）：Scene0 重逢
      （身份 reuse×2）→ Scene1（输入含 Scene0 回执，T07）→ 新 case 重放
      读到 custody 知识 → Scene2 渡口（presence 两节点+unknown 段）→
      修订 Scene0 → 失效传播 → 旧建议 verdict=stale；全新 run 的 Scene1
      未提交前 BarrierBlocked。**边界**：worker/async_tasks 挂接有意不做
      （E07 前接 handler = 第二编排 owner，违反 N03）；world 知识与地图册
      资产仍 unsupported（V/MI 接线）。
- [x] 2026-09-21 会话 7：E06 完成——recovery.py：replay_committed_prefix
      键集分页有界重放（链缺口 ChainGapError fail-closed、checkpoint 信任锚
      跳过早期页、max_pages 拒绝无界扫描）；verify_run_checkpoint（游标与
      head 漂移 CheckpointDriftError + 恢复期 owner fence）。
      T12 完整：store.save_receipt 游标推进以 epoch 匹配为条件——中途切换
      的旧 worker 回执在持久化边界被拒（专测：applier 内推进 epoch →
      StaleOwnerError，游标不动，新代际可提交）。测量：
      tools/evolution_checkpoint_bench.py 在本地真 PG 专用库跑 1k/5k/10k
      档位——全量回放线性（5/25/50 页），增量回放三档均 1 页/100 行
      <10ms，检查点校验 <10ms；报告在
      docs/plans/novelcraft-v4/e06/E06-恢复与性能测量.md（本机档位非承诺）。
      bench 坑：create_all 前须 _register_orm_models()（FK 依赖）且库要先
      建 pgvector 扩展；种数据先插 Account 再 Project（owner FK）。
- [ ] E07 迁移切换（影子运行/canary/在途兼容/入口重定向）（未开始）
- [ ] E07 迁移切换（影子运行/canary/在途兼容/入口重定向）（未开始）
- [ ] E08 deep_import 退役（未开始）

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

## 恢复快照（2026-09-21 会话 7 结束，含 E06）

分支 `codex/novelcraft-v4-g0-baseline`，累计 19 个提交：G0×2、E01–E06
（E06=ed77e4021：分页恢复+T12 完整 fencing+1k/5k/10k 实测）及任务/文档
记录。**未推送、未合 main、未部署、未建 PR。**
E03b 与计划 §2.2 的差异（有意收窄）：以 `meta.event_key` JSON 键替代新列
（避免生产迁移，语义等价——身份=语义指纹而非输出位置）；producer_family
暂用 source 字符串（deep_import/ai_extraction），generation/input_revision
登记在 delta meta，完整 `replace_derived_scene_events(...)` 签名留给 E03c
随 evolution/commit 落地。
下一步：E07 迁移切换六步（E07.a 旧链保护已由 G0 完成）——E07.b 影子
运行（新引擎只读同源写隔离实验产物，禁止给正式 World/Story 第二套有效
事实）、E07.c 项目级 canary（active_engine/owner_epoch 排空切换）、
E07.d 在途兼容、E07.e 入口重定向（挂 async_tasks handler、deep_import
API 参数适配）、E08 退役清单核销。world 知识/地图册资产留 V/MI。
合并 main 需用户授权；建议合并前跑 PostgreSQL e2e 专用库（配方在 memory）。
