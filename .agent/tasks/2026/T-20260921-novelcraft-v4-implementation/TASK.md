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

## 恢复快照（2026-09-21 会话 9，历史参考；最新状态见下方会话 10）

分支 `codex/novelcraft-v4-g0-baseline`，累计 26 个提交：G0×2、E01–E07、
G2、E09 第一步 + 真实模型验收（0cee8a3c5）。**用户已授权推送并建 PR；
分支已推送，PR #158 已建（未自动合并，等 CI 与评审）。**
E09 真实模型验收已通过（用户授权，DeepSeek 实调：schema 化观察 + 计量
回执，`modules/evolution/tests/test_real_llm_sampler.py`，Makefile
BACKEND_REAL_LLM_TESTS 已登记；密钥从 ~/.zshrc 种入账户连接，不经环境
直连）。
E03b 与计划 §2.2 的差异（有意收窄）：以 `meta.event_key` JSON 键替代新列
（避免生产迁移，语义等价——身份=语义指纹而非输出位置）；producer_family
暂用 source 字符串（deep_import/ai_extraction），generation/input_revision
登记在 delta meta，完整 `replace_derived_scene_events(...)` 签名留给 E03c
随 evolution/commit 落地。
下一步：E09（真实模型采样器接线 + 真实质量验收——需要账户连接与
用户授权跑真实 LLM，超出纯代码范围）；或按计划并行推进 G3+（项目级
切换落地/前端统一宿主 U 系列/地图 V 系列/R 系列推荐）。E08 实际删码
被 E09+canary 阻断（登记表已列）。world 知识/地图册资产留 V/MI。
合并 main 需用户授权；建议合并前跑 PostgreSQL e2e 专用库（配方在 memory）。

## 评审返修（2026-09-21 会话 10，PR #158 Request changes → 全项修复）

**PR #159（独立前端修复）已全绿合入 main（610d3872a）**：main 上
"Frontend functional browser" 必需检查红的根因是 65df0c789（前瞻/创作
试验，直推未走 PR 门禁）——creative-forecast.spec.js 留在 functional 套件
（无 ASSISTANT_ENABLED/合成 provider，等「项目助手」按钮超时）+ RP 页
forecasts/capabilities 未 mock 打真实后端 403 噪声。修复：接线
playwright.creative.config.js（script+CI 步骤+functional testIgnore）、
mockRpApis 补 capabilities mock、useForecast.refresh() dirty/saving 期间
跳过（保存落库竞态必然 SOURCE_STALE 409，建议入口此间本就禁用）、spec
补资源勾选。本地专用库全绿（interaction 16/writing 28/agent-teams 1/
assistant 1/creative 1/vitest 2536/eslint）。

**PR #158 评审（用户提供的 Request changes 报告）R1–R6+P2×3 逐项核实
（全部属实）并返修**：

- R1：SceneSampler 协议改 async；提及身份宿主派生
  （observations.derive_mention_id，观察身份+表面名+序位）；采样器工厂改
  async context manager（客户端 __aexit__ 成对）；handler 集成测试经过
  registry async sampler→world facade 精确名召回→一致性门→领域 applier→
  数据库回执（test_e07_switching + test_review_remediation）。
- R2：SceneSourceBinding 锚定真实 Writing 草稿（指纹来自 DB；scene_text
  须与草稿逐字一致，sha256 同 writing.source_hashing）；提交时
  _source_verifier 重查当前草稿（非自比较）；一致性门——scene_events
  引用未解析实体的提议 gated 进 pending_decisions；编译后观察（含提及
  身份与解析结论）持久化进冻结负载；G2 夹具引文改逐字子串。
- R3：屏障顺序检查（head.through_scene_index 必须恰为 N-1；scene 0 有
  head 即拒；跳场/倒序显式 blocked）；plan_parallel_batches 每 Scene 取
  最大批次（后放小批不回写）；前序输入带 previous_observations（链头
  冻结负载观察谓词有界摘要），build_scene_messages 注入真实前序理解。
- R4：事务边界重排——预算预留先 commit 持久化；provider 调用在提交点
  之间；冻结单独 commit；apply 为最后一笔短事务。域失败回滚不抹预算与
  冻结（test_review_remediation 故障注入：budget 只扣 1、frozen 仍在、
  recover_scene_step 免采样重放、sampler.calls==1）。handler 恢复优先：
  已提交→原回执幂等重放（load_scene_receipt）；已冻结→recover_scene_step；
  才走新采样（test_task_handler_recovery_replays_frozen_without_resample）。
- R5：单写者改数据库不变量——部分唯一索引
  uq_evolution_run_single_live_writer（novel_id WHERE live+active，
  migration 20260921_evolution_single_writer）；register_run 捕
  IntegrityError→single_writer_violation；排空/停止 run 重复注册拒绝
  （run_not_active）；reserve_budget 仅 active。真实 PG 双会话竞态 e2e
  （tests/e2e/test_evolution_single_writer_concurrency.py，专用库
  ai_novel_agent_e2e_evolution 全迁移含新 head 验证）恰好一个 owner。
- R6：legacy_adapter 预算严格沿用 requested_budget（不再 max 抬额）；
  paid_call_receipts 类型放宽 dict[str,Any]，sampler 回执带 provider/
  model/usage，applier 并入 ApplierResult→EvolutionReceipt。
- P2×3：save_receipt 显式生成 record.id（head_attempt_id 指针非空断言）；
  consumers 有效性收窄（indexed None 或 claimed None→unknown，不宣称
  一致）；_shadow_applier 按本步真实位置推进影子游标。

**G2 声明收窄（按评审）**：test_g2_vertical_slice 定位为「确定性夹具下的
存储/投影集成切片」（模块 README 已改）；完整 G2（持续认知闭环、真实模型
质量、独立 case 经 Evidence 消费、地图消费合法状态）留后续里程碑。
评审门槛第 6 条（独立 case 经 Evidence 消费+地图消费）未在本轮实施——
consumers seam 已收紧，Evidence 入模消费链待 E09+。

验证：modules/evolution 78 passed + 1 real-llm deselected；evidence fusion
contract 通过；ruff 全绿；docs-check 通过（01_数据库设计 §3.11 已登记新
索引）；真实 PG 迁移至新 head + 双会话并发 e2e 通过。全量后端单测运行中。

## 会话 10 收尾（2026-09-21）

- PR #158 CI 11/11 全绿（PostgreSQL critical 一次红为 artifact 上传 403
  基础设施抖动，测试本身 37 通过，rerun 即绿），已合入 main（41b2377d0）。
- main 现状：41b2377d0（V4 主链 + 评审返修 + 前端 CI 修复）。
- 下一里程碑（用户指令二选一）：E09 长书规模验证（真实作品多 Scene 影子
  运行对比）；或 G3+/U 系列前端统一宿主（R00 选区传递、U01 单右侧宿主）。
- 遗留（登记未做）：复审门槛第 6 条（独立 case 经 Evidence 入模消费 +
  地图消费合法状态）；E08 实际删码（待 canary+E09）；真实作者试用。

## E09 长书规模验证（2026-09-22 会话 11，分支 codex/evo-e09-scale-validation）

新增 `backend/tools/evolution_scale_harness.py`：专用空库上把
synthetic_ten_chapters（真实叙事，回归人物林舟/柳青/星盘/钥匙/顾遥）按章
建真实 Scene+Writing 草稿，shadow run 走真实 handler（evolution_scene_step）
逐 Scene 推进，按计划 §9 退出标准断言并出报告（stdout MD + --json-path）。

**deterministic 档**（10 Scene 0.26s；--repeat 5 → 50 Scene 1.12s，专用库
ai_novel_agent_e2e_evoscale）：链完整、前序状态注入 Scene 1..N-1、预算
恰尽且幂等重跑零扣减、影子零 MemoryEvent、跳场拒、重跑同回执、改原文后
旧文本推进被 source_changed 拒、引用逐字、提及有据——全部通过。

**real 档**（十幕，DeepSeek 经账户连接，用户已授权真实模型验证；~10 次
调用/轮）：43→41 条 schema 化观察、逐字引用、提及有据（模型实际跟踪了
顾遥/观星会/篡改星盘记忆等剧情线）、completion_tokens ~1.0-1.2k/幕进
回执；退出标准全过（耗时 ~52-89s/十幕）。

顺手修两处真实链路缺陷：①ProjectLLMSampler 经 generate_structured 的
diagnostics 通道捕获 structured_usage 计量（原 usage 恒 None）；②
_shadow_applier 现在把 provider 计量带入回执——影子运行消耗真实额度，
费用必须可审计（此前影子回执 paid_call_receipts 恒空）。

遗留：真实档观察里混有「本章标题为…」类平凡观察（质量噪音，非阻塞）；
身份全为 new_candidate（专用库无 World 实体，诚实待作者裁定）；跨模块
消费链（Evidence 入模+地图）仍属复审门槛第 6 条，未在本轮。

- PR #160 CI 11/11 全绿，已合入 main（2f3e6e9dd）。E09 里程碑完成。
- 下一候选：G3+/U 系列前端统一宿主（R00 选区传递、U01 单右侧宿主）；
  或复审门槛第 6 条（独立 case 经 Evidence 入模消费 + 地图消费）。

## U00+R00（2026-09-22 会话 12，分支 codex/u00-r00-entry-selection）

**U00**：`docs/plans/novelcraft-v4/u00/U00-入口与状态清单.md` 建立——15 路由
→岛→视图全清单、6 个命令模式命令、顶栏入口、公开演示白名单、状态面
必测清单、R00 断点事实底账与归宿决定记录（04-FRONTEND-HIFI §10 要求）。

**R00 三断点修复**（选区/intent 数据链一致传递）：
1. 选区 SourceRange：`captureWorkContext` 在写作页干净编辑器上捕获码点
   偏移（`Array.from` 计数，emoji 不漂移；dirty/saving 只留文本不带偏移）；
   `WorkContext` 新增 `selection_start/end`（成对+须绑定草稿+长度=码点数）；
   `AssistantService.submit` 载草稿后 `verify_selection_range` 逐字复核——
   漂移即 `assistant_selection_stale` 409 失败关闭。
2. task_hint/intent：`WorkContext.task_hint`（schemas.TASK_HINTS 封闭集，
   forecast 契约同源）；助手面板新增「这次要求」选择器（不限/续写/只润色/
   修改/设定设计/查证/检查/整理），经 withIntent 并入 turn 与前瞻上下文；
   `work_directive` 把意图行为边界渲染进最终 user 消息（如 polish="不得
   扩大情节、新增设定或改动事实"）——forecast 侧既有 polish 能力收窄
   （runtime 剔除扩情节项）自此可被触发。
3. forecast selected_range：`useForecast.focusFrom` 在干净写作页带
   draft+hash 时发送 `{start,end}`（契约本就要求并消费），前瞻实际分析
   选中段落。

验证：后端 assistant 89（77+12 新增）通过、ruff；前端 vitest 2538
（含 4 条 assistantContext 新用例：码点偏移/emoji/dirty 门控/项目隔离）、
eslint；assistant e2e 与 creative-forecast e2e（专用库）通过；docs-check
带理由通过。全量后端单测（无 .env）后台复核中。
