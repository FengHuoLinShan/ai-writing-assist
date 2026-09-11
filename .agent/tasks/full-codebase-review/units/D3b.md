# D3b 槽位报告（R05 story：continuity 子域 + 版本/投影 + 旧公开前缀）

日期：2026-09-11。基线：main @ e7d0b8d5b（工作树）。全部只读完成；未运行任何测试/构建/make；未读密钥。
范围 14 路径逐一语义阅读；`models.py`/`repositories.py` 归 F4，本槽位为追调用链全文精读并只作引用；
人物卡/脚本主体在 story 根模块（`service.py`/`api.py`/`repositories.py`，归 D3a/F4），continuity 内无人物卡/脚本符号，仅 cross-ref 不重复审。
每个 facade 公开符号均已反查消费者；投影/失效状态图见「共享事实 1」。

## 覆盖行

```csv
path,审查状态,入口/消费者(可空),发现ID或无发现理由
backend/modules/story/continuity/__init__.py,已审,无符号（包 docstring）,无发现：docstring 仍自称独立 Memory 模块，与 story README 所有权描述一致
backend/modules/story/continuity/api.py,已审,app/main.py:765 注册 /api/novels/{novel_id}/memories（10 路由）；仓内消费者仅 backend/tests/test_api.py、tests/unit/test_memory_extra.py、route-closure 守卫（test_active_project_route_closure.py:395）；前端零引用,无发现：每路由 require_active_project 有守卫测试；旧公开前缀语义记共享事实 3（删除需产品确认，不立发现）
backend/modules/story/continuity/contracts.py,已审,schemas.py/scene_projection/services 内部消费；story/contracts.py:8-16 再导出；evidence test 消费 SCENE_MEMORY_DIMENSIONS,D3b-3（MemoryEventContract/ChapterPanoramaContract/SceneCheckpointRepairResult 仅再导出+形状测试，零生产消费）
backend/modules/story/continuity/facade.py,已审,story/facade.py:63-73 全量再导出；真实消费=evidence loaders(memory_records_loader/scene_lens)、imports(persistence/orchestrator/single_scene/bulk/parallel)、writing tasks.py:129 经 DI memory.service,D3b-1（get_continuity_evidence_for_writing 零生产调用）；D3b-3（create_delta_log/count_deep_import_delta_logs_by_workflow 导出零消费者）
backend/modules/story/continuity/scene_projection.py,已审,api.py(scene-checkpoints 4 路由)+facade(ensure/get_scene_checkpoints→evidence/imports),D3b-2（_project_dimension 与章级重放的 manual_correction 语义不对称）；D3b-5（每维度重复 unanchored 计数查询）；cross-ref F1-3（_hash 为 stable_hash majority 同语义副本）
backend/modules/story/continuity/schemas.py,已审,api.py 响应模型；EventType 被 services 重放消费,无发现（EventSource/SnapshotStatus 死枚举计入 D3b-3）
backend/modules/story/continuity/services.py,已审,api.py+facade+bootstrap.py:120 DI("memory.service")→writing/tasks.py:130 publish_chapter,D3b-2（唯一生产事件流全为 manual_correction，章级重放无该分支→快照/全景空转）；D3b-3（record_events/mark_stale/_apply_events/_diff_states 生产零调用）；D3b-4 关联
backend/modules/story/continuity/tests/__init__.py,已审,pytest 包标记,无发现（1 行）
backend/modules/story/continuity/tests/conftest.py,已审,本目录 fixtures（db_with_project/sample_novel_id/make_mock_event）,无发现
backend/modules/story/continuity/tests/test_api.py,已审,参数化验证 7 条旧前缀路由对回收项目返回 404,无发现：断言有效且与 active-project 门禁一致
backend/modules/story/continuity/tests/test_repositories.py,已审,repo 行为/孤立性/双方言 JSON 过滤/DeltaLog keyset,无新发现；覆盖死方法（delete_*/create_many/get_max_sequence/get_latest），清理时随批迁移（D3b-4）
backend/modules/story/continuity/tests/test_scene_projection.py,已审,ensure 全维度/stage0 稀疏快照/空重跑失效/序号带冲突/align 重排,无发现：有效覆盖投影失效关键路径
backend/modules/story/continuity/tests/test_schemas.py,已审,Pydantic 校验/ORM 转换,无发现（_MockORM 类属性跨用例复用为轻微气味，不立项）
backend/modules/story/continuity/tests/test_services.py,已审,delta 摄取/回滚/keyset、full_rebuild 保留历史、全景 stage0 禁 World 回填、evidence、死方法 not-awaited 守卫,无新发现；含被审死路径的大量测试（record_events/replay/_diff_states/evidence 3 例），清理时按 D3b-1/3/4 迁移
```

## 发现

| ID | 位置/符号 | 问题与触发 | 调用链证据 | 现有契约 | 最小方案 | 预期收益 | 风险 | 依赖 | 验证命令/断言 | 回滚 | 裁定 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D3b-1 | `continuity/services.py:500-551 get_continuity_evidence_for_writing`；`continuity/facade.py:48-65`；`story/facade.py:68,394`；`story/contracts.py:11,70`（`MemoryContinuityEvidenceContract`）；文档 `writing/README.md:283`；失实测试 `writing/tests/test_conflict_checks_real_llm.py:209-211` | 「上一章位置连续性证据」seam 生产零调用，但文档宣称 writing 在用；且 real-LLM 测试断言冲突项 `continuity_location_mismatch`（`source_module=="memory"`），生产规则链只产 `forbidden_present/required_missing`（writing/services.py:1612,1646，`"sources": ["outline"]` :1177）——该测试在 fast 基线外（`make test-real-llm`）必败或从未对齐 | 全仓反查：`get_continuity_evidence_for_writing`/`MemoryContinuityEvidenceContract` 仅出现在 continuity 自身、story/facade 再导出、story/contracts 再导出、writing/README.md；writing 生产代码无任何调用（rg `continuity_evidence` 命中清单为证）；`continuity_location_mismatch` 全 backend 生产码零定义，仅 real-LLM 测试引用 | facade 导出为稳定 seam（AGENTS），但消费者为零；README 对外承诺与代码不符 | 二选一（需用户/产品裁定，不混入纯优化批）：a) 功能补齐——writing 冲突规则接入该 evidence（功能任务另立）；b) 优化删除——移除 services 方法+facade 双层导出+契约类+test_services 3 例，修正 writing/README.md:283，将 real-LLM 测试的 memory 断言移交 E1 复核 | 消除一整条死 seam（约 80 行+双层转发+3 测试）与文档失实；避免后来者按 README 误以为检查存在 | a 无兼容风险（新增输入属 LLM 兼容面单列）；b 需确认无仓外消费者按 `/api/story` facade 依赖该符号 | E1（real-LLM 测试归属）、D4（writing 冲突链）、产品裁定 | `make test TESTS="modules/story/continuity/tests modules/writing/tests"`；rg 断言零残留引用 | git revert 单批 | 实施候选（b 为优化批；a 为功能 backlog） | P2 |
| D3b-2 | `continuity/services.py:764-788 _apply_event_to_replay_state`（无 manual_correction 分支）× 生产唯一写入路径 `imports/entity_extraction/scene_entity_persistence.py:1024-1088 _record_deltas → facade.ingest_delta_events → services.record_scene_events:165`（event_type 恒 `"manual_correction"`） | 生产写入的全部 memory 事件都是 manual_correction 场景事件；章级重放对该类型无分支→完全忽略。后果：`MemorySnapshot.full_state`（writing publish_chapter 唯一自动捕获点）与 `ChapterPanorama`（evidence `memory_records_loader` 的 `bundle.memory_records` 长期记忆段）在当前流水线数据下恒为空壳；真实事实仅存在于 Scene checkpoint 的 `changes` 透明桶与 `delta_log`。双投影不对称：Scene 投影 `_apply_event`（scene_projection.py:491-527）把 manual_correction 记入 `changes`，章级重放连 changes 都不记 | 写入方反查：`MemoryEvent(` 生产实例化仅 scene_entity_persistence 链（tests 除外）；`record_events`（章级写入）生产零调用；`get_panorama` 消费=evidence memory_records_loader.py:27-29；快照捕获=writing/tasks.py:129-130；测试 `test_get_panorama_no_snapshot_no_events_returns_stage0_without_world` 证实无 World 回填（空态兜底） | panorama/快照语义为「确定性事件重放、禁读当前 World」（docstring+测试锁定）；无「必须吸收 delta」契约 | 领域裁定三选一：a) 重放吸收 manual_correction（按 dimension 归入 changes，与 Scene 投影对齐）；b) `memory_records_loader` 改用 Scene checkpoint 作为长期记忆来源、章级引擎降级/退役；c) 确认现状有意（章级引擎仅服务遗留数据）并注释声明。属 Context 输入语义变化，按 §2 LLM 兼容面单列，不进纯优化批 | 消除「写不入、读不出」的空转引擎（约半数 services 行数）或恢复记忆段真实内容；减少双投影心智负担 | a/b 改变生成输入（LLM 兼容面）；c 零风险 | 产品/领域确认；D6b（compilation 消费侧）；D4（publish 任务） | 固定输入契约对比（重放输入=同一事件集，输出 buckets 断言）；`make test TESTS="modules/story/continuity/tests modules/evidence/compilation/tests"` | git revert；快照为派生数据可重建 | 实施候选（先裁定后实施；当前先记共享事实 4） | P2 |
| D3b-3 | 死导出/死符号簇：`facade.py:25-36 __all__` 中 `create_delta_log`、`count_deep_import_delta_logs_by_workflow`（后者 services.py:405-417 + repositories.count_active_by_workflow 整链零消费）；`bootstrap.py:193` DI 键 `memory.capture_snapshot`（实际消费走 `memory.service`，writing/tasks.py:129）；`services.py:80-130 record_events`、`:557-567 mark_stale`、`:738-745 _apply_events`、`:795-907 _diff_states`；`contracts.py:21-41 MemoryEventContract/ChapterPanoramaContract`、`:84-88 SceneCheckpointRepairResult`；`schemas.py:36-48 EventSource/SnapshotStatus` | 各符号生产零消费者（仅测试直接调用或仅再导出链）；`test_memory_extra.py` 只测契约 dataclass 形状 | 逐符号 rg 反查（见覆盖行调用链列）：`count_deep_import_deep...` 仅 story/facade 两行；`create_delta_log` 外部零命中（服务内部 `self.create_delta_log` 供 ingest 使用，导出多余）；DI 键仅 tests/unit/test_container、test_run_worker 引用；`EventSource/SnapshotStatus` 全仓零命中 | facade `__all__` 为稳定 seam，但 AGENTS 允许清理已证实无消费者的转发/导出；「内部零引用只构成候选」 | 一批收敛：删两个死 facade 导出（保留服务内部方法）、删 DI 死键注册、删两个死枚举、三个死契约 dataclass 及其 story/contracts 再导出与形状测试；`record_events/mark_stale/_apply_events/_diff_states` 视 D3b-1/2 裁定结果决定删除或保留（record_events 是测试唯一的章级造数器，若章级引擎退役一并删） | 约 150-200 行死面 + 再导出链缩短；X1-S3 同类清理的 continuity 部分 | 低；需同步迁移 test_memory_extra/test_services 中对应断言，不得删有效行为断言 | D3b-1/D3b-2 裁定（record_events 去留） | `make lint` + `make test TESTS="modules/story/continuity/tests backend/tests/unit/test_memory_extra.py"` | git revert 单批 | 实施候选 | P3 |
| D3b-4 | `repositories.py`（F4 归属，本槽位仅引用）：`EventRepository.create_many(:69)/get_by_chapter_range(:204)/delete_by_chapter(:319)/delete_from_chapter(:335)/get_max_sequence(:351)`、`SnapshotRepository.get_latest(:675)/delete_stale(:782)`、`SceneCheckpointRepository.get_latest_ready_before(:854)` | 8 个仓储方法生产零调用。其中 `get_latest`、`get_latest_ready_before` 连测试都没有（完全死）；delete_* 仅有 repo 级行为测试 + test_services 的 not-awaited 回归守卫（证明 full_rebuild 不删历史——该语义守卫需保留，可改按行数断言） | 逐方法 rg：`get_latest_ready_before` 全仓零命中；`get_latest` 命中均为 writing/outline_state 同名异类；`create_many/delete_*/get_max_sequence` 仅 continuity 测试 | repo 方法为模块内部面，非跨模块契约 | 删 `get_latest`/`get_latest_ready_before` 无条件；其余 6 个按 D3b-2/3 裁定同批处理；「保留历史」语义守卫迁移为对 full_rebuild 后行数的断言 | 死代码约 90 行；仓储面与真实调用对齐 | 低；test_services 4 处 not-awaited 断言需随批改写（不削弱守卫语义） | D3b-2/D3b-3 | `make test TESTS="modules/story/continuity/tests"`；rg 断言零残留 | git revert | 实施候选 | P3 |
| D3b-5 | `scene_projection.py:408-423 _project_dimension`（`count_unanchored_through_chapter` 每 Scene×每维度执行一次，同一 novel+chapter 参数重复 4 次）；`ensure_scene:71-97` 对 0..target 全量逐 Scene×4 维度重建（含 batch import 每场景调用一次 ensure，imports single_scene:189/bulk:239/parallel:561） | 每次投影重建有 4 次语义相同的未锚定计数查询；批量导入 N 个 Scene 时查询数约 13×N（各查询均有索引且事件拉取按 `after_scene_index` 增量，行数有界，非 O(N²) 行扫描） | scene_projection.py 结构阅读；调用点见 imports 三处 ensure 调用 | 无性能契约；本机 performance_probe 必败，无法给前后数据 | 把 unanchored 计数提升到维度循环外（每 Scene 1 次）；ensure 可按 target 之前已有 current+hash 相同的短路现状保持（已有 source_hash 幂等短路 :335-341，无需再改） | 每 Scene 少 3 次查询；导入/修复路径耗时收益待测 | 低；纯查询上提不改语义 | 无 | `make test TESTS="modules/story/continuity/tests/test_scene_projection.py"`；固定数据集 SQL 计数对比 | git revert | 实施候选（顺手改） | P3 |

无 P0/P1：未发现安全、novel_id 隔离或数据丢失问题。所有写路径（replace_scene_events、replace_system、create_manual_repair、rollback）均带 novel_id 条件或复合唯一键；repair 的 CAS（expected_checkpoint_id）与 manual/confirmed 保护（fail-closed）经 `e2e/test_scene_memory_checkpoint_concurrency.py` 与 test_scene_projection 覆盖。

## 历史候选复核

| 候选 | 结论 | 证据 |
|---|---|---|
| A3-1 PlotThread/OutlineArc 两 repo 收敛（领域侧） | 仍成立（形态更新，与 F4-11 机制侧配对） | 领域消费者少而集中：`PlotThreadRepository` → outline_state/structure_dedup.py:455,676（+tests）；`OutlineArcRepository` → structure_dedup.py:456,695、outline_state/services.py:402（+tests）。二者 create/update/get_by_novel/delete 与 `StructurePlanRepository`（repositories.py:115-207，已有 Reveal/Foreshadowing 两个子类）语义同构；差异有业务意义的仅 PlotThread.update 白名单+`capture_change_scenes`+通知——基类 update 已内置该序列，子类 override 可表达。收敛后调用方零改动（消费面不感知）。约 300 行收益估计不继承，以实施时实测为准 |
| A3-2 reveal/foreshadowing 约 45 行重复 | 仍成立（实测约 50 行） | `reveal_repository.py:20-82` 与 `foreshadowing_repository.py:19-84` 的 `get_by_novel` 签名、`apply_structure_asset_filters` 调用、active_thread_ids 集合、`included` 闭包（requested/unassigned 过滤）、内存切片分页完全一致；差异仅 order_by（created_at vs planned_seed_chapter）。二者已继承 StructurePlanRepository，但 override 完全绕开基类 get_by_novel（基类为 SQL count+offset 分页）。最小方案：基类加 related-thread 过滤 hook 或共享 `_filter_by_active_threads` helper，两子类各保留 order_by 与特有方法（get_for_target/get_active_by_status/count_by_novel_and_range）。文件归 D3a；实施随 D3a 批次 |
| A3-3 业务枚举 Literal→StrEnum | 无 continuity 落点 | continuity 的 EventType/EventSource/SnapshotStatus 已是 StrEnum；无 Literal 枚举簇需迁移。EventSource/SnapshotStatus 是死枚举（归 D3b-3），不属 A3-3 范畴 |
| A3-4 | 不存在 | code-simplification-audit.md 原文无 A3-4 编号（A3 序列只有 1/2/3/5/6）；历史底稿已不可考，按现状关闭 |
| A3-5 手写 novel_id → NovelMixin（领域侧证据） | 仍成立（continuity 侧 4 类可无差异收敛） | continuity 5 个 ORM 类中 `DeltaLog`（models.py:189）已用 NovelMixin；`MemoryEvent`(:57-62)、`MemorySnapshot`(:152-157)、`MemorySceneCheckpoint`(:277-282)、`MemorySceneSnapshot`(:329-334) 均手写 `novel_id: FK projects.id CASCADE index=True`——与 NovelMixin（core/base.py:72-80）语义完全等价，无 F4-12 列出的差异点（无 index 缺失/无改名），属「无差异类先收敛」批次 |
| A5-2/A2-4 snapshot LLM client 链（调用方侧） | 无 continuity 落点 | continuity 全模块无 LLM 调用（rg provider/client 零命中）；六处 `_open_task_llm_client` 调用方均在 D3a（outline_state/ai_workflow_service.py、story_outline_generation.py）与 D4/F2 范围 |
| A5-10/F1-3 stable_hash 收敛 | 仍成立（清单漏计 +1） | `scene_projection.py:684-688 _hash`：`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)` + sha256，与 F1-3 的 majority 语义逐参一致；F1 按 `def _?stable_hash` 名称普查，改名 `_hash` 的同语义副本未入 13→17 清单。收敛裁定时应把本副本（及同类改名副本）一并纳入并保持指纹字节兼容——该 hash 是 checkpoint 幂等短路键，变更会使现有 system checkpoint 集体重算（历史 superseded 保留，无数据丢失） |
| X1-6 状态词汇收敛（continuity 面） | 不适用（领域工作流态，非队列态） | continuity 的 `current/stale`（MemorySnapshot）、`ready/retry_pending/manual_required/superseded`（checkpoint）、`missing/manual_required/retry_pending/ready/gap`（coverage_status）均为领域工作流/展示态，按计划 §6 不并入 TaskStatus 队列态收敛。注意 `SnapshotStatus` 枚举存在但实现用裸串「current/stale」——如做状态收敛应「删死枚举或真用枚举」二选一，勿新增第三种词汇（归 D3b-3 同批） |

## 共享事实（供 W3 链 4 及后续槽位引用）

### 1. continuity 投影/失效语义（合法状态图）

Scene checkpoint（`memory_scene_checkpoints`，唯一性=partial unique `(novel_id,scene_id,dimension) where is_current`）：

- 状态词：`ready` / `retry_pending`（retry_count≤2）/ `manual_required`（retry_count>2）/ `superseded`（历史终态）。`source`: system_generated|manual；`confirmed`: bool。manual 或 confirmed 的 current 行受保护：`_build_dimension` 只校正漂移的 stage 坐标（scene_projection.py:296-305），`supersede_system_from` 按 `source=="system_generated" and not confirmed` 过滤（repositories.py:896-897），`repair`/`create_manual_repair` 对受保护行 fail-closed（scene_projection.py:224-227、repositories.py:979）。
- 转换：a) ensure/rebuild/record_scene_events → `_build_dimension`：投影成功且 source_hash 相同→幂等短路返回现行（:335-341）；hash 不同→`replace_system` 旧行 superseded、新行 ready；`_CoverageGapError`→replace_system 为 retry_pending/manual_required（retry_count 累计跨调用）。b) repair（人工）=CAS（expected_checkpoint_id 不符→`checkpoint_version_conflict`）+创建 manual+confirmed+ready 行+supersede 下游同维度 system 行（include_start=False）+supersede 场景快照（include_start=True）+重建下游。c) record_scene_events 写入后立即 supersede 该 Scene 起全部 4 维 system checkpoint（include_start=True）与场景快照（services.py:183-195）。d) `_reconcile_event_order`（ensure/rebuild/repair 入口）在 outline 重排后由 `align_scene_indices` 对账冗余 scene_index 并同步重算 sequence=(scene_index+1)*1000+scene_sequence，返回最早受影响处并向上 supersede（repositories.py:457-505、scene_projection.py:640-665）。
- Scene 快照（`memory_scene_snapshots`）：stage0=initial；稀疏捕获条件=periodic（(scene_index+1)%10==0）/chapter_end（本 Scene 最大章 < 下一 Scene 最小章或无下一 Scene）/latest，且要求 4 维全 ready 才捕获（scene_projection.py:443-489）；`replace_for_scene` supersede 同 stage current 并全局让位 is_latest。
- 章级快照（`memory_snapshots`）：`current|stale`；`create` 同章 current→stale 后插新 current；`mark_stale_from` 用于 full_rebuild；历史 superseded/stale 行永不硬删（tests 断言锁定）。
- hash：`source_hash` 为幂等键（stable_hash majority 语义，见 A5-10 复核行）；改动会使 system checkpoint 集体重算（soft-supersede，可回放重建），不影响 manual/confirmed 行。

### 2. 与 outline_state 的权威边界

outline_state 是 Scene 身份与顺序的唯一权威（`scene_facade.get_scenes_by_novel` / `get_scene_contract`，status_filter=canonical+draft）；continuity 只读引用，把 scene_index 冗余进事件/checkpoint，并在每次 ensure/rebuild/repair 入口用 `_reconcile_event_order` 对账失效——重排不会产生陈旧投影。依赖方向单向：continuity→outline_state.facade；outline_state 不 import continuity（其文件中的 "continuity" 字符串是 Scene.continuity 字段/execution-bundle 键，无关）。跨模块统一经 `story/facade.py`（再导出 continuity facade 10 符号）与 `story/contracts.py`（再导出 continuity contracts）；真实外部消费者=evidence loaders/scene_lens、imports 抽取持久化与编排、writing publish 任务（经 DI `memory.service`）。

### 3. 旧公开前缀与消费者

`/api/novels/{novel_id}/memories`（continuity/api.py，main.py:765 注册，architecture-documents.toml:110 在册）与 `/api/outline`（归 D3a）为 README 声明保留的历史前缀。memories 前缀仓内消费者仅测试（backend/tests/test_api.py、tests/unit/test_memory_extra.py）+route-closure 守卫（test_active_project_route_closure.py:395）；frontend-console 零引用（rg "memories"/"scene-checkpoints" 无命中）。每路由均 `require_active_project` 且有回收项目 404 测试。按计划 §P1「对外接口无仓内消费者不构成删除证据」：保留现状，任何下线需产品/用户确认后另立兼容批次。

### 4. 生产写入路径唯一性（当前流水线事实）

- `memory_events` 唯一生产写入方=imports 场景抽取持久化（`scene_entity_persistence._record_deltas` → facade.ingest_delta_events → record_scene_events），事件类型恒 `manual_correction`、全部带 scene 锚点；章级 `record_events` 生产零调用（unanchored 事件只可能来自遗留数据，Scene 投影的 coverage-gap 逻辑正是其防御）。
- `memory_snapshots` 唯一自动写入方=writing `publish_chapter` 任务（writing/tasks.py:129-130，DI 键 `memory.service`）；另有无人值守 HTTP `POST /memories/snapshots/capture`。
- `delta_log` 写入方=deep import 摄取（同上链）；回滚=imports/orchestrator.py:1666-1691（soft-rollback 保留审计）。
- 后果：章级重放引擎（replay/panorama/章级快照）对当前流水线数据为空转（D3b-2）；Context 的 `memory_records` 段与 Scene checkpoint（`changes` 桶）可见性不对称——W3 链 4 复核 Context 记忆输入时以此为准。

### 5. 人物卡/脚本归属（cross-ref，不重复审）

人物卡/脚本主体在 story 根模块（`story/service.py`、`story/api.py`、`story/schemas.py`、`story/repositories.py`、`story/models.py`），归 D3a（服务面）/F4（ORM/repo）。continuity 包内无人物卡/脚本符号。F4-3 共享事实 3 已记录 `story/repositories.py` 为全仓隔离最强 repo（全方法强制 novel_id）。

## 受阻

无。14 路径全部完成审查；未执行任何被禁命令。
