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
| 启动 | 任务记录 + 并行规划提交 | 完成 |
| P2-A 批1 | A0 夹具 ∥ A1 契约先行 | 完成（6 xfail 夹具 + 37 契约测试全绿） |
| P2-A 批2 | A2 写入端 ∥ A3 读取端 ∥ A4 展示端 | 完成 |
| P2-A 汇合 | 多实体 subject_ref 修复 + 夹具转绿 + 全量验证 | 完成 |
| P2-B 批1/批2 | B0 夹具 ∥ B1 方言统一；B2 机器接线 ∥ B3 边界揭示闸（B4 并入汇合） | 完成 |
| P2-C 批1/批2 | C0 夹具 ∥ C1 登记缝；C2/C3/C4 | 完成（C0 夹具 15/15 全绿），改动未提交 |
| P2-C 汇合批 | 门禁验证 + 文档同步 + 提交 + PR | 进行中（2026-10-08，见 [P2-C 汇合记录](#p2-c-汇合记录2026-10-08) 与 [交接快照](handoff-world-foundation-p2c-20261008.md)） |

### A0 产出（P2-A 批1，2026-10-07）

夹具文件：`backend/modules/story/continuity/tests/test_p2a_field_provenance.py`
（模块内 tests 惯例；全部 6 例 `xfail(reason="P2-A field provenance not implemented",
strict=False)`，当前输出 `6 xfailed`；夹具经 MemoryService / SceneMemoryProjectionService /
SceneStateViewService 公开入口真实落库执行，`--runxfail` 验证均在逐字段来源断言处失败，
非 setup 报错）。断言清单：

| 用例 | 场景 | 断言要点 |
|---|---|---|
| test_p2a_flashback_later_scene_facts_do_not_backflow | 倒叙 | 早场景位置(location_id)/指纹不回流；两场景 provenance 各指向自己事件+该章 v1 稿；timeline time_order 非母题字段不得宣称 exact |
| test_p2a_custody_handover_traces_per_scene_field_provenance | 保管交接×2 | owner 最后赋值停创建事件；holder 逐场景指向交接事件；三场景 checkpoint 可回开 |
| test_p2a_revision_keeps_old_checkpoint_on_its_version | 历史版本 | 旧 checkpoint get_record 回开且 provenance 留 v1（不洗成 v2）；新视图 provenance 形态合法 |
| test_p2a_unrelated_manuscript_change_keeps_field_fingerprint | 反向1 | 改无关章 v2 后 state_fingerprint/字段值/字段 provenance 均不变 |
| test_p2a_historical_read_does_not_backfill_current_world | 反向2 | 今日 World（summary/别名/标签/新知识）不回填历史视图值与 provenance |
| test_p2a_missing_manuscript_source_marks_fields_unverified | 来源缺失空态 | 无稿事件字段 provenance=unverified、source_refs 空，不拿整场事件列表冒充 |

逐字段来源期望契约形态决定（A1 对齐基准，文件头有同文）：

- 读取端：author 视图每条受控母题字段 fact 的 `source["provenance"]` 为单条记录
  `{field, event_id, source_refs, status}`；`status ∈ {exact, unverified, conflict}`；
  exact 要求 event_id 非空 + source_refs ≥1；非母题字段不带 provenance 或不得为 exact。
- `source_refs` 元素字段集直接从 `evidence/source_ref_contracts.py` 的
  SourceRangeRefContract dataclass 推导；content_mode 固定 `"working"`（与 basis.py 口径一致）。
- unverified：追不到赋值链（如无稿）→ source_refs 空、可留已知 event_id、禁整场列表。
- `field` 取受控母题 payload 键（custody_owner/custody_holder、location_id/text_state、
  opening_*），非视图聚合字段名——已与 A1 落地的 MOTIF_FIELD_REGISTRY 口径对齐
  （A1 用 field_key/`_field_provenance` 内嵌 state_json，读取端接线面以本夹具为准）。
- 历史回开端：`get_record` 暴露 `field_provenance`（响应属性或 state_json 的
  `_field_provenance` 内嵌键，两者取其一），保留构建当时版本语义。

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

## P2-A 汇合记录（2026-10-07）

主会话裁定并修复 A3 识别的契约缺口：`FieldProvenance` 增实体锚 `subject_ref`
（entities/locations=实体 ID，timeline=None），`summarize_field_provenance` 分组键改
`(field_key, subject_ref)`，`_entries_for` 三处查询带实体锚，`get_record` 响应每条
补 `subject` 键；A0 四键单记录形态不变（fact 自带 subject_id 不重复）。写入端
`_assigned_motif_fields` 返回 `(field_key, subject_ref)` 对。新增显式多实体隔离测试
（test_p2a_read_side.py::test_view_isolates_same_name_fields_across_entities）。

验收：A0 六夹具摘除 xfail 转真断言全绿；continuity 151 passed；story+evidence
1293 passed；后端全量 **7276 passed**（基线 7192 + 新增 84）；ruff/format 过；
module-import-gate 棘轮 65/9/0/525/0/26 未推高；前端 vitest 2822 passed（226 文件）
+ eslint 过；docs-check 过（05_memory.md 更新逐字段赋值链契约与 history 端点，
其余文档 no-change-reason：无模块边界/拓扑/schema 层变化，纯 state_json JSON 内嵌
无迁移、无新跨模块边）。零 LLM 调用、零真实数据写入。

超白名单但必要的子代理改动（主会话复核接受）：A3 改 continuity/schemas.py
（SceneCheckpointResponse.field_provenance 可选字段，向后兼容）、A4 改
evidence/compilation/schemas.py（SceneLensSource.provenance，不加则 provenance
到不了前端）。

## P2-B 汇合记录（2026-10-07）

主会话裁定：接受 B1 揭示调和（有主张锚→须证明域；无主张锚无策略→默认公开
结构信息），B3 据此实现后 B0 两个 xfail 转绿。B2 调查修正：KnowledgeInPanorama
实际定义在 continuity/schemas.py:81（非 evolution/schemas.py）。超白名单改动：
B3 的 SceneStateViewDetailResponse 响应子类（schemas.py 禁改下的最小承载，
pydantic v2 子类经父类 TypeAdapter 保留新字段已验证）。

验收：B0 六类夹具 8/8 全绿（同场旁观/后文揭密/uncertain 证实已实现或补齐，
两个真缺口=拒绝原因互斥与读者揭示闸已实现）；story+evidence+evolution 1573
passed；后端全量 **7324 passed**（P2-A 后 7276 + 48）；ruff/format/import-gate
棘轮 65/9/0/525/0/26 未推高；docs-check 过（05_memory.md 精确化无策略=公开
表述+denied_facts+get_record 标注+机器断言剥离）。预览零正史写入：state_trial
compare 纯读、ResolutionBatch 内存重放（既有测试钉死），P2-B 无新增写路径。
零 LLM、零真实数据写入。

## P2-C 汇合记录（2026-10-08）

C2/C3/C4 三个单元产出留在工作树未提交，汇合批统一验证。可恢复快照见
[handoff-world-foundation-p2c-20261008.md](handoff-world-foundation-p2c-20261008.md)。

修掉的两个汇合缺陷：

1. **模块 README 链接断链**（`docs-check` 完整性门禁 ERROR）：`evolution/README.md`
   与 `writing/README.md` 新增段落用了 `../../docs/modules/2x_*.md`（指向不存在的
   `backend/docs/`），已改 `../../../docs/...`（与其他模块 README 同口径）。
2. **差异影响门禁五项必查文档**：`--base-ref origin/main` 列出 CLAUDE.md、
   documentation-maintenance.md、module-architecture.drawio/html、07_outline.md
   未更新。逐项核对后按 PR 模板第三项给出无影响说明（原文存交接快照 §6.2），
   以 `--no-change-reason` 复跑降级为 WARNING、退出码 0。要点：bootstrap 只加既有
   DI 缝注册（CLAUDE.md 是纯导入指针）；未新增/合并模块与跨模块边（棘轮未推高，
   拓扑图不变）；Makefile 触发源是新增 `eval-rp-cost-baseline` 评估目标（非文档
   门禁/CI 入口）；story 改动只涉 continuity 与 facade 再出口，outline_state 未改，
   语义已落在 05_memory.md / 19_story.md / story README。

验证：writing+evolution+collaboration 635 passed；story+evidence+unit 3070 passed
（`test_dev_stack_entrypoint` 单例首次失败，独立复跑 24/24 全绿，属临时目录环境噪声）；
真 PG `tests/e2e/test_p2c_invalidation_recompute.py` 3 passed（专用库
`agent_e2e_world_p2c_20261008`，已 `alembic upgrade head`）；ruff check 过；
本轮改动文件 `ruff format --check` 15/15 已格式化（全库 162 条是 ruff 0.16.9 与仓库
既有格式的基线差异，main 工作树同为 178 条，与本轮无关，不得顺手全量重排）；
`module-import-gate` 棘轮 65/9/0/525/0/26 未推高。零 LLM、零真实数据写入。

## 恢复快照

（交接/暂停前更新）当前：P2-A、P2-B 完成并提交，P2-C 的 C0–C4 全部完成、改动未提交，
汇合门禁与真实浏览器关键流已过，改动已固定提交（4 笔）并开出
[PR #206](https://github.com/FengHuoLinShan/ai-writing-assist/pull/206)
（phase1+P2 一并合入 main），待合并授权与 CI；
快照见 [handoff-world-foundation-p2c-20261008.md](handoff-world-foundation-p2c-20261008.md)。

## A1 产出（契约先行单元，2026-10-07）

新模块 `backend/modules/story/continuity/field_provenance.py`（369 行，零 LLM、零接线）；
契约测试 `backend/tests/unit/test_p2a_field_provenance_contract.py`（37 用例全绿；主会话改名消歧，原与 A0 夹具同 basename）。

### 注册表字段清单（MOTIF_FIELD_REGISTRY，field_key → dimension/label/value_kind）

- 人物位置（locations）：`location_id`(entity_ref)、`text_state`(text)、`chapter_index`(integer)——对齐 CharacterLocationInPanorama。
- 物品所有者/保管者（entities）：`custody_owner`(entity_ref)、`custody_holder`(entity_ref)。
- 锁的有限条件：`opening_key_id`(entity_ref)、`opening_moon_phase`(moon_phase_enum)、`opening_passphrase`(text)（entities 锁对象 payload）+ `moon_phase`(moon_phase_enum)（timeline facts payload，state_trial 开锁判断的月相来源）。
- 语义：未登记 payload 键照旧透传但无来源语义；FieldProvenance 构造即校验 (field_key, dimension) 已登记（model_validator，未登记抛 ValidationError）。

### FieldProvenance 最终形态

```
ProvenanceSourceRef(BaseModel, frozen)  # evidence SourceRangeRefContract 的 Pydantic 镜像
  draft_id/chapter_index/version_number/content_mode/start_offset/end_offset/source_hash/range_hash
  + from_source_range_contract(contract) -> duck-typed model_validate(from_attributes=True)

FieldProvenance(BaseModel, frozen)
  field_key: str; dimension: str          # 必须已注册且维度一致
  event_id: str                            # 造成赋值的 MemoryEvent
  source_refs: tuple[ProvenanceSourceRef]  # 非空时 version_number 全一致且 == version
  version: int(ge=0)                       # 资料修订版本；无区间锚为 0
  recorded_at_sequence: int(ge=0)          # scene_sequence 优先，无 Scene 锚用章内 sequence
```

镜像而非 import 复用的裁定：module-import-gate 的 function_level_imports 棘轮 525 只减不增
（实测函数内 import evidence 即 526 FAIL），且 JSON 边界须 Pydantic 校验；契约测试对拍
`set(SourceRangeRefContract.__dataclass_fields__) == set(ProvenanceSourceRef.model_fields)` 防漂移。

### status 判定规则（resolve_field_status 纯函数，三态 + None）

1. 空记录 → `None`（展示层显示"来源待核实"）；2. 完全相同记录幂等去重；
3. 取 recorded_at_sequence 最大组（reducer 后者胜：保管转移等正常演化不算冲突）；
4. 同序仍多条不同链 → `conflict`（相对顺序未知不裁决）；5. 最新链唯一：有 refs → `exact`，只追到事件 → `unverified`。

### 存放规范结论：纯 JSON 内嵌，不需要新列

- 键：checkpoint `state_json["_field_provenance"]`（常量 `FIELD_PROVENANCE_STATE_KEY`；与 `_coverage` 内部元数据键同惯例，不进 `_entries_for` 展平路径）。键存在性即新旧格式判别，无版本字段。
- 读取：`read_field_provenance(state_json)` 旧格式/空载荷/非 dict → `[]` 不报错不冒充；新格式内容非法抛 ValidationError（写入端已校验，读回非法属数据损坏应显式暴露）。便捷入口 `provenance_status_for(state_json, field_key, dimension=None) -> ProvenanceStatus | None`。
- 不新列理由：字段级来源与 checkpoint 行生命周期完全一致（随 supersede 软删）、A3 读取端本就逐 checkpoint 读 state_json（零额外 I/O）、无跨行独立查询需求；省去 models+Alembic（A2 批如需重评依本记录）。

### timeline 受控发生时间（TIMELINE_WHEN_CONTROLLED_KEYS + TimelineWhenClause）

受控键：`scene_index`/`scene_sequence`（相对顺序锚，沿用 services 注入键形）、
`relative_to_fact_id`+`relative_order`(before/after)（成对相对锚）、`stated_date`（原文明示日期
原样保存，不换算日历）。`extract_timeline_when(payload)` 容错提取：类型不符视为缺失、未受控键
忽略、半个相对锚整体丢弃，永不因 payload 形状报错；直接构造 TimelineWhenClause 则严格校验成对。

### A2/A3 落点建议

- A2 写入端：`scene_projection.py` `_project_dimension`（:449 事件循环内，`_apply_event` 旁为登记字段构建 FieldProvenance 写入 `state["_field_provenance"]`，继承 previous 的历史链供时序裁决；evidence 区间经 duck-typed 转换）；timeline 受控键规范化在事件 payload 构造处（services.py `_with_scene_event_key` 注入链附近，A2 先调查）。reducer.py 保持纯状态解释内核，不建议挂链。
- A3 读取端：`scene_state_view.py` `_entries_for`（:303，entities `_flatten_fields` 与 timeline facts 生成 SceneStateFactEntry 时用 `provenance_status_for` 把 status 填进 source dict，None → "来源待核实"）；`state_trial.py`（:72-83）custody/opening/moon 取值处附带 status，exact 才显示精确回指。

## A2 产出（写入端单元，2026-10-07）

改动文件（本单元独占写入）：`backend/modules/story/continuity/scene_projection.py`、
`backend/modules/story/continuity/services.py`、新增
`backend/modules/story/continuity/tests/test_p2a_write_side.py`（7 例全绿）。
reducer.py 零改动。

### 挂链落点（file:line，改动后行号）

- `scene_projection.py:514-558` `_project_dimension` 事件循环：`_apply_event` 后经
  `_assigned_motif_fields`（:562）识别实际落入核心状态的注册字段，为每字段追加
  `FieldProvenance`，循环结束写 `state[FIELD_PROVENANCE_STATE_KEY]`（:554）。
  ensure_scene / rebuild_from_scene / repair 下游重建三条路径共用此单点，全部落链。
- 继承链：previous checkpoint 的 `_field_provenance` 随 `deepcopy(previous.state_json)`
  自然继承，写入侧先经 `read_field_provenance(state)` 校验归一再追加（内容非法显式抛错，沿 A1 裁定）。
- `recorded_at_sequence` 组装（`_provenance_sequence` :612）：`scene_index * 512 + Scene 内序`
  （Scene 内优先 `scene_sequence`，缺失回退章内 `sequence`）。**关键裁定**：A1 单 int 字段必须把
  scene_index 合成进主位，否则跨场景同字段链的 scene_sequence 互相打平 → 保管交接被误判
  conflict，违背「后者胜」；步长 512 > 单 Scene 事件上限 500。`get_through_scene` 只返回
  scene 锚事件，主位恒可用。
- source_refs（`_event_source_refs` :625 + `_working_refs` :645）：事件所属章最新
  working 稿的**整章区间**（`list_manuscript_sources` content_mode="working"，basis.py 同口径；
  经 `SourceRangeRefContract` 构造 + A1 `ProvenanceSourceRef.from_source_range_contract`
  duck-typed 转换）。抽取侧当前不记录更细区间，整章即诚实最大锚；无稿/空稿/无 content_hash
  → 空区间（unverified，version 0），禁止拿别章或整场事件冒充。同章并列最新版本按
  (version, id) 确定性取一防重建漂移。按次调用内逐章惰性缓存，无注册字段赋值时零查询。
- 赋值判定口径（`_assigned_motif_fields`）：只认 reducer 核心落点——entities 的
  created/已知实体 updated、locations 的 entity_moved、timeline 的 facts 追加；进观察层
  `changes` 的负载（manual_correction、未知实体 updated）不挂链。重复断言同值也算一次赋值
  （该事件即当前值最后陈述）。
- timeline 受控时间（`services.py`）：`_normalize_timeline_when`（:224，A1
  `extract_timeline_when` 口径）在 `record_scene_events`（:175，`_with_scene_event_key` 之前，
  事件键对规范化内容稳定）与 `confirm_scene_continuity_event`（:311）两处构造点规范化：
  成对相对锚/整数 Scene 锚/非空 stated_date 保留，半个相对锚与类型不符键丢弃，未受控键透传。
  moon_phase 为 timeline 注册字段，随 facts 追加自动挂链。

### drift 缓存路径一致性验证结论

`replace_system` 存 state_json 原文（repositories.py，无内部键裁剪）；`_build_dimension`
幂等短路比较的 `source_hash` 覆盖含 `_field_provenance` 的完整 state——旧格式行（无链）重算
后 hash 必不同 → 换行升级而非带旧 state 短路。`_capture_sparse_if_needed` 与 `_manual_state`
keep_current 均 deepcopy 保留。测试 `test_ensure_scene_idempotent_short_circuit_keeps_provenance`
端到端证明：幂等重跑同 checkpoint id、无 supersede churn、链内容不变。

### reducer 是否动了

未动（A1 裁定维持）。核实：`apply_scene_dimension_event` 只写维度容器与 `changes`，
从不触碰 `_field_provenance` 键与受控字段值；继承测试覆盖。

### 验证

`modules/story` 全量 626 passed + 6 xpassed（A0 夹具——本 worktree 并行 A3 读取端已落地，
write+read 合流后夹具真通过；strict=False 下绿）；A1 契约测试 37 例全绿；ruff check/format
通过；`make module-import-gate` 通过（function_level_imports 525/525 未推高；新增均为
story→writing 顶层导入，属冻结集合既有边；零 evidence 导入）。

### 给 A3 的注意点

- 链记录是**全字段流水**（含历史链），读侧按 field_key 过滤后用 `resolve_field_status`/
  `provenance_status_for`；「最后赋值事件」= 过滤后 `recorded_at_sequence` 最大的那条
  （同字段多条链按后者胜裁决）。
- 无链 ≠ 该字段无值：旧格式 checkpoint 与 manual/confirmed 行（`source != system_generated`）
  无 `_field_provenance`，应显示「来源待核实」，不得反推 exact。
- timeline 的 moon_phase 链挂在 timeline 维度 checkpoint；entities 的 opening_moon_phase 是
  另一条独立链（不同维度，`FieldProvenance.dimension` 已区分）。

## A3 产出（读取端：视图/试算/facade 出口，2026-10-07）

新测试 `backend/modules/story/continuity/tests/test_p2a_read_side.py`（7 例，手工构造
含 `_field_provenance` 的 state_json，不依赖 A2 写入端）。

### 接线落点

- `scene_state_view.py`：新增模块级 `summarize_field_provenance(state_json, dimension)`
  （读取端唯一聚合入口，A0 四键单记录形态）；`_entries_for` 在 entities
  `_flatten_fields`、locations 聚合 fact、timeline moon_phase fact 三处把摘要填进
  `source["provenance"]`。非母题字段/无记录/旧格式一律不带 provenance，绝不 exact。
  locations 聚合 fact（field="location"）挂主锚字段 location_id 的链，事件只写描述时
  退 text_state；timeline 仅 payload 自带 moon_phase 值的 fact 挂 moon_phase 链。
- `scene_projection.py` `get_record`（响应组装处唯一改动）：函数内导入
  `summarize_field_provenance`（scene_state_view 顶层导入本模块，顶层回导会成环），
  填 `response.field_provenance`；按字段名排序保证确定性。
- `state_trial.py`：`condition()` 从传入 fact source 派生 `source_status` 附进每条条件；
  新增 `_verdict_reasons` 生成 `verdict_reason`——exact 才精确回指（附稿件修订
  vN，事件+区间随条件 source 完整透出），unverified/conflict 显式降级明示；三值裁决
  failed/uncertain/succeeded 只看条件 met/unmet/unknown，不受来源状态影响。
- `repositories.py`：`SceneCheckpointRepository.list_history_for_scene`（只读，倒序含
  superseded）。
- `facade.py`：`list_scene_checkpoints` 出口（见下）。
- `schemas.py`：`SceneCheckpointResponse` 追加可选 `field_provenance: list[dict]`（默认
  空列表；当前集合读取与旧格式恒空，仅 get_record 回开填充）。

### provenance 单记录最终序列化形态（A0 钉定，恰四键）

```json
{
  "field": "custody_holder",
  "status": "exact | unverified | conflict",
  "event_id": "<最后赋值事件 id；conflict 无法唯一归因为 null>",
  "source_refs": [{"draft_id": "...", "chapter_index": 1, "version_number": 1,
                    "content_mode": "working", "start_offset": 0, "end_offset": 48,
                    "source_hash": "...", "range_hash": "..."}]
}
```

unverified 保留已知 event_id、source_refs 空且无 event_ids 列表；conflict 的
event_id=null、source_refs=[]（不冒充任一竞争链）；历史链（更低事件序）不参与展示。

### get_record 暴露方式选择

选「响应属性」：`SceneCheckpointResponse.field_provenance = [按字段聚合的单记录]`
（字段名排序）。理由：前端无需重实现三态裁决即可直接渲染；state_json 内嵌键是 A2
的原始流水（含历史链与全字段元数据），聚合口径读侧统一在 summarize；旧格式行为空
列表（非 None）。历史语义：直接读该行自身 state_json，不与当前 Canon head 重算
混合——测试覆盖 supersede 后旧行仍指 v1 稿。

### list_scene_checkpoints 签名与语义

```python
# facade 出口（薄层委托 scene_state_view.list_scene_checkpoints）
async def list_scene_checkpoints(
    db, novel_id: str, scene_id: str, *, dimension: str | None = None
) -> list[dict[str, Any]]
```

每项 `{checkpoint_id, dimension, scene_index, chapter_index, version, is_current,
created_at, has_field_provenance}`；按 created_at 倒序（id 决胜），含已 supersede 行，
novel_id+scene_id 双过滤隔离（跨 novel 同 scene_id 行不混入），非法 dimension 422。
`version` 是同维度链时间序号（1 起，越大越新，行序派生非存储列）；`chapter_index`
取 Scene 章节锚（chapter_ids 最大值，无锚为 None）；`created_at` 为 ISO 字符串。
偏差说明：任务卡所列 `scene_sequence` 在 checkpoint 行无此列，以 `scene_index` 表达
场景顺序（A4 api.py 消费端已按 `row.get("scene_sequence") or row["scene_index"]`
容忍）；任务卡参数名 `story_id` 即本仓 `novel_id`。

### 已知边界（契约限制，非本批缺陷）

`FieldProvenance` 无 subject 槽：同维度 checkpoint 内多实体同名受控字段（如两把钥匙
各自的 custody_holder）共享同一 field_key 链，读取端按字段聚合会把最新链挂到该字段
的全部 fact 上；跨实体同序赋值会裁决为 conflict。A0 六场景均为单实体主物，未钉定
多实体口径；如需按实体分链须 A1 契约扩展（加 subject 维度键），留待汇合批裁定。

### 验证

新测试 7 例全绿；`modules/story` 全量 633 passed + 6 xpassed（A0 夹具在 A2+A3 合流
后真通过，strict=False）；A1 契约测试 37 例全绿；`ruff check`/`format`（本单元七个
文件）通过（api.py 的 format 偏差属并行 A4 文件，未触碰）；`make module-import-gate`
通过（525/525 未推高）。零 LLM、零 git commit。

## A4 产出（展示端：Lens 字段来源 + 历史 checkpoint 端点 + 前端下钻，2026-10-07）

### 端点

`GET /api/novels/{novel_id}/memories/scene-checkpoints/history?scene_id=...`（continuity/api.py；
注册在 `/scene-checkpoints/{checkpoint_id}` 之前避免路径参数吞掉字面量；鉴权沿
`_require_active_project`，novel_id 路径隔离）。端点函数内导入调用 facade
`list_scene_checkpoints(db, novel_id, scene_id)`，不绕过 facade。响应形态：

```json
{
  "novel_id": "...", "scene_id": "...", "total": 2,
  "items": [{
    "checkpoint_id": "…", "dimension": "entities", "chapter_index": 2,
    "version": 1, "scene_sequence": 3, "is_current": true,
    "has_field_provenance": true, "created_at": "…",
    "label": "当前版本" | "历史版本"
  }]
}
```

旧版本不洗成当前：`label` 按 `is_current` 区分；技术 ID（checkpoint_id）留行内供回开，
语义位（label/章/批次/时间）先行。响应模型定义在 api.py 本文件（A4 写权限不扩
continuity/schemas.py）。行映射容忍 ORM 同义键（id/version_number/scene_index），
`chapter_index` 无章节锚为 None 如实透传。对 A3 的实际依赖点：facade 符号名
`list_scene_checkpoints` + `(db, novel_id, scene_id)` 位置参数 + 返回裸列表行或含 items
映射均可；A3 已在本 worktree 落地 facade 出口，端点测试同时含 DI 替身（monkeypatch
facade 属性）与真实 facade 路径（未知 Scene 404）两类验证。

### scene_lens 字段级来源（evidence 模块）

`scene_lens.py` `_source` 把 fact `source["provenance"]` 归一并聚进 Lens source（新增
`_provenance`/`_valid_ref`）：status 三态之外整条丢弃；refs 保留 SourceRangeRefContract
八字段但要求区间四整数键完整，**exact 无有效 refs 时降级 unverified（不制造精确性）**。
`evidence/compilation/schemas.py` 的 `SceneLensSource` 最小追加 `provenance`
（`SceneLensProvenance`/`SceneLensProvenanceRef`）——本单元超出枚举可写清单的唯一文件，
原因：response_model 校验默认丢弃未知键，不加 provenance 到不了前端。

### 前端改动清单

- 新增 `vue/views/writing/components/SceneFieldProvenance.vue`：字段下钻面板（状态徽章
  有据/来源待核实/来源冲突、事件诊断编号、稿段区间"第 N 章 · 第 V 版工作稿 · 第 a–b 字"）。
  稿段回开复用既有 `POST /evidence/read`（`api.context.readEvidence`，WorldPageReader
  同款作者可见 + before/after 上下文），面板内嵌 blockquote 展示回读文本，未新造阅读器；
  refs 缺 source_hash/range_hash 时不提供回开（readEvidence 契约要求 64 位指纹）。
- 新增 `vue/views/writing/components/SceneCheckpointHistory.vue`：历史版本次级入口
  （`<details>` 折叠渐进展开，默认不打扰），按批次分组（章/第 N 次整理/维度标签/时间/
  当前·历史徽章），行内"回看该版本依据"复用既有 `openSource({checkpoint_id})` 的
  get_record"状态依据"展示路径。
- `SceneLensSummary.vue`：字段行加状态徽章与"字段来源"开关（一次展开一个，切场景/重载
  复位）；挂接两个新组件。`SceneStateTrial.vue` 未改动（历史入口放 SceneLensSummary 即够）。
- `api/story.js`：新增 `sceneCheckpointHistory(novelId, sceneId)`。
- `sceneLensModel.js`：新增 `sceneFieldProvenance`（归一 + reopenable 判定）与
  `sceneCheckpointHistoryGroups`（按章+批次分组、当前/历史聚合）；`sceneObjectStates`
  字段附带 `provenance`。

### 三类空态最终文案

1. 首次进入（无任何 provenance）："本场状态还没有逐字段来源记录；随着正文推进和状态整理，
   每个字段会逐步标出具体依据。"（仅有对象状态但零 provenance 时出现）
2. 来源缺失（unverified）：徽章"来源待核实"+ 面板文案"来源待核实：这条状态暂时没有追到
   具体稿件段落，不会当作已核对的事实。"（exact 但区间不完整时后端同降级此态）
3. 旧稿无追踪信息（历史行 has_field_provenance=false）："这个版本早于逐字段来源功能上线，
   没有每个字段的依据记录；可回看当时的整体依据。"（历史列表自身空态另有："本场还没有
   历史版本记录；状态整理后会产生可回看的版本。"）

### 验证

后端：`modules/story` + `modules/evidence` 全量 1285 passed + 6 xpassed、
`tests/unit/test_p2a_field_provenance_contract.py` 37 passed、`tests/test_api.py` 48 passed
（scene-lens 相关无回归）；`ruff check` + `ruff format`（A4 五个后端文件）通过；
`make module-import-gate` 通过（function_level_imports 525/525 不变；api→continuity
facade 为同模块函数内导入，不推高棘轮）。前端：vitest 全量 226 files / 2822 tests
passed（新增 SceneFieldProvenance/SceneCheckpointHistory/SceneLensSummary 三套组件测试
+ sceneLensModel 适配测试）；`npm run lint` 通过。`make docs-check` 无基线通过；
`--base-ref origin/main` 报 architecture 文档复核要求（分支累计 phase1+P2 改动的通用
要求，非 A4 独有缺口，归 P2-A 包收尾统一处理）。零 LLM、零 git commit。
## B0 产出（P2-B 批1 知识边界夹具，2026-10-07）

夹具文件：`backend/modules/story/continuity/tests/test_p2b_knowledge_boundaries.py`
（8 用例：6 真绿 + 2 xfail（`reason="P2-B knowledge boundary not implemented",
strict=False`）；输出 `6 passed, 2 xfailed`；`--runxfail` 验证两处 xfail 均在
目标边界断言失败，非 setup 报错）。文件头含六类矩阵与知识期望契约全文（本节为摘要）。

### 六类矩阵（类别×视角×允许/拒绝×现状）

1. 旧值→新值（真绿）：口令改写后旧知识绑旧值——角色视角新口令 fact 不可见；
   trial 条件 unmet 且 observed=旧值/expected=新值（拒绝原因=值不匹配）。
   test_state_trial 既有主干覆盖，本夹具钉 belief `known_values` 与条件
   observed/expected 的双端值绑定。
2. 误信（真绿）：false 标记条目（含结构上可授予的 fields/known_values 形态）
   belief 可见带 possibly_false、事实零授予；trial 口令条件 unknown（候选被
   排除即无法证明），绝不为 met。
3. 部分知晓（真绿）：fields=["identity"] 只放行 identity fact，
   secret_relation 不可见（不知道≠知道没有）。注：name 是实体 meta 键
   （_ENTITY_META_KEYS，不作为状态字段输出），身份类字段夹具用非 meta 键。
4. 同场旁观（边界真绿）：同 Scene 有位置（在场）但无知识条目 → 他人事实
   不可见、本人位置可见（在场只证明位置）。**边界已在现实现成立**——前期
   调查所列缺口的实质在下行原因结构。
5. 后文揭密-character（真绿）：Scene N+1 的揭示事件（实体补秘密+获知知识）
   不回流 Scene N（checkpoint 截止语义）；对照获知后的 N+1 视角可见。
6. uncertain 三值（真绿，此前零断言）：三条件全 unknown 且无 unmet →
   verdict=uncertain + `unresolved_outcomes=[actor]`；有一条明确 unmet
   （所需钥匙记载为另一把）→ failed。三值裁决已实现，纯补断言。

### xfail 清单与失败点

- `test_p2b_bystander_denial_reason_distinguishes_no_knowledge_entry`：
  失败于"拒绝原因缺失"断言（前置三条事实确实被拒已通过）。缺口=同一
  character 视角下三类拒绝原因（无条目/旧值/误信）须互斥可区分，现状
  omissions 只有维度级计数（`人物与对象：角色视角未获得依据 N 项`）。
- `test_p2b_reader_before_reveal_scene_must_not_see_secret`：失败于
  "揭示前读者视图不得看到秘密"断言。缺口=无 reveal 策略默认公开
  （`ReaderRevealDecisionContract.revealed` 默认 True）→ Scene 0 就有
  记录的世界秘密泄露给揭示前读者视图；omissions 也不会报"尚未揭示"。
  （有策略未到揭示章的隐藏已被既有 test_reader_view_gates_entities_by_reveal
  覆盖，B1 裁定的是无策略默认方向。）

### 知识期望契约形态决定（供 B1 对齐）

- 知识条目 payload：`{character_id|holder_id, subject_id, fields:[str],
  known_values:{field:value}, false?:bool, knowledge:str}`；授予 =
  (holder, subject, field, stable_hash(value)) 四元组；fields/known_values
  缺失即纯 belief（知道有这么回事≠知道值）；false/false_belief 永不授予。
- 值的时间性：条目绑定记录当时的值，事实后续变更不自动更新知识；旧值
  授权对新值 = knowledge_value_mismatch 拒绝，只有新知识条目放行且只
  放行其后场景（后文获知不授权早场景）。
- 视角过滤：character fact 需四元组授予（唯一例外本人位置）；belief 只见
  本人；observation 仅作者。reader fact 需揭示判定且 layer=fact。
- 逐条拒绝原因（xfail 钉定的缺口）：character 视角每个被抑制 fact 可归因，
  cause 三类互斥——no_knowledge_entry / knowledge_value_mismatch /
  false_belief；承载形态不限（omissions 内 dict 或 facts 同级 denied/
  suppressed 结构），夹具 helper `_denial_reasons` 容忍多种承载，只钉
  "三类可区分"语义，不钉精确字符串。
- 揭示判定：reader 默认必须保守——无"已展示原文证明"不得默认公开秘密；
  揭示前 omissions 只报数量不泄露对象（沿用既有读者侧口径）。

**与 B1 裁定的张力（汇合/B4 须裁定）**：B1 裁定"两域不改默认值"——outline
RevealPlan 无策略默认公开保持；而本夹具 `test_p2b_reader_before_reveal_scene_
must_not_see_secret` 钉的是主计划验收句"读者揭示只在能够证明已展示的原文
范围内启用"在**无策略**形态下的体现（Scene 0 记录的世界秘密不得泄露给揭示前
读者）。两者仅在"作者未登记任何揭示/保密策略"时冲突；候选调和方向：World
对象级保密策略（ReaderRevealPolicy）接入 scene 读者视图（B1 记 World 层为
附加闸门但 B3 落点未含此接线）、证明闸对所有 secret 类 fact 生效、或夹具
改为带策略形态（带策略未揭示的隐藏已被既有测试覆盖，会失去缺口钉定）。
夹具按计划原文保留 xfail，最终口径由主会话裁定。

### 验证

`test_p2b_knowledge_boundaries.py` 6 passed + 2 xfailed（`--runxfail` 两处
均失败于目标边界断言：拒绝原因缺失断言 / 揭示前读者视图含秘密断言）；
continuity 全量 185 passed + 2 xfailed；`modules/story` 全量 675 passed +
2 xfailed（与 B1 并行合流后无回归）；ruff check/format 过（新夹具文件）。
零 LLM、零真实数据写入、零 git commit。


## B1 产出（方言统一与边界裁定单元，2026-10-07）

新模块 `backend/modules/story/continuity/knowledge_contract.py`（契约+纯函数，零接线）；
契约测试 `backend/modules/story/continuity/tests/test_p2b_knowledge_contract.py`
（30 例全绿；与 B0 夹具 `test_p2b_knowledge_boundaries.py` 不同文件，B0 的 xfail 不受影响；
含 B0 两个 xfail 缺口的纯函数承载——`denial_reason` 三类互斥拒绝原因、
`evaluate_reader_reveal` 无策略有揭示主张记录的保守判定）。

### 统一契约最终形态（KNOWLEDGE_CONTRACT_VERSION = "knowledge-dialect-v1"）

```
KnowledgeClass(StrEnum): known | unknown | false_belief
KnowledgeOrigin(StrEnum): scene_event | machine_observation
SceneAnchor(frozen): scene_id? | scene_index? | scene_sequence?（extract_scene_anchor 容错提取，
  bool/字符串数字不当 int，与 _occurred_at 同口径）

KnowledgeStatement(BaseModel, frozen)
  holder_id: str                      # 谁知道（character_id/holder_id）
  subject_id: str | None              # 值绑定对象锚（机器路径恒 None）
  knowledge_class: KnowledgeClass
  value_bindings: dict[str, str]      # field → stable_hash(known_values[field])
  known_fields: tuple[str, ...]       # 原 fields 列表保留（含绑不上的字段）
  text_summary: str | None            # 文本知识层
  origin: KnowledgeOrigin
  event_id: str | None                # 知识来源事件
  source_refs: tuple[ProvenanceSourceRef, ...]   # 稿源区间（沿 A1 结构）
  scene_anchor: SceneAnchor | None    # 当时适用范围
  unchecked_note: str | None          # 未检查说明（机器传闻级等）
  entry_id: str | None                # reducer 幂等键（knowledge_changed 按 id 去重）
  不变量（model_validator）：
    known ⇔ value_bindings 非空且 subject_id 非空；
    false_belief/unknown 结构上禁携绑定（误信永不授予在结构上杜绝）；
    unknown 必须保留 text_summary（无文本兜底"未记载内容的知识条目"，不静默丢弃）
```

三分类判定 `classify_knowledge(payload, *, origin)`——分类绑定来源方言：事件方言
误信标记先判（false/false_belief → false_belief，带三件套也不授予），三件套交集
（subject + fields list + known_values dict 且 fields∩known_values 非空）→ known，
其余 unknown；机器方言恒 unknown（方言本身表达不了值绑定）。

纯函数：`bind_value(v)=stable_hash(v)`、`value_matches(hash, v)`（视角过滤口径）、
`build_knowledge_grants(statements, target_id) -> {subject: {field: 值哈希集}}`
（只取 known 且 holder 匹配的条目——测试与 `scene_state_view._knowledge_grants`
对同一 checkpoint 逐位对拍相等）、`denial_reason(statements, *, holder_id,
subject_id, field, value) -> KnowledgeDenialCause | None`——B0 xfail 钉定的三类
互斥拒绝原因纯函数（no_knowledge_entry / knowledge_value_mismatch /
false_belief；授予返回 None；known 条目的授予与归因不受同对象误信条目影响，
unknown 文本条目不构成字段级授予等同无条目），B3 把它装进 omissions/denied
结构即转绿。

兼容读取：`read_knowledge_statement(payload, origin=...)` / `read_knowledge_statements(state_json)`
（character_knowledge 列表批读）/ `read_machine_knowledge(payload)`。旧格式/非 dict/无 holder
→ 跳过或 None，永不报错、不冒充；fields⊄known_values 时 known_fields 保留全集、只绑交集。

### 机器路径映射裁定（B2 沿此执行，字段级）

**裁定：选 (b) story 侧转换器降级为文本知识（unknown，无值绑定）；不选 (a) 扩展
evolution/KnowledgeInPanorama 声明可选绑定字段。**

- 红线（已钉死测试 `test_p2b_machine_smuggled_binding_keys_are_not_adopted`）：
  `KnowledgeInPanorama`（continuity/schemas.py:81，无 extra 配置）Pydantic 默认
  忽略额外键——机器 payload 偷带 subject_id/fields/known_values 会静默透传持久化、
  在 `_build_panorama` 的 `KnowledgeInPanorama(**k)` 读回时静默消失。方言统一时
  不得把透传键当作值绑定采信：`read_machine_knowledge` 只认白名单结构，
  `classify_knowledge(..., origin=machine_observation)` 恒 unknown。
- 选 (b) 理由：① 机器证据分级（state_gate GROUNDING_MODALITIES：knowledge 维度
  接受 event_observed/character_statement/belief/hypothesis）没有值级证据，让机器
  宣称"知道哪个值"等于制造无依据断言，违背阶段语义；② (a) 需同步动
  state_gate 的 uuid5 identity（锚内容变化使既有幂等键漂移）、panorama 读回与
  视图多处，超出 B2 范围且引入兼容风险；③ (b) 把统一动作收敛在 story 侧一个
  转换器，机器路径零 schema 变更。
- 字段映射（`read_machine_knowledge`）：`character_id`→holder_id（state_gate 已
  强制 == knowledge_subject）；`known_content`（belief 文本键兜底）→text_summary；
  `knowledge_level` ∈ {rumor, hearsay}→unchecked_note「传闻级证据，未直接目击」，
  其余级别不追加；`id`→entry_id。**不映射**：`target_type`/`target_id`/`status`
  ——target_id 无字段语义，不冒充值绑定对象锚 subject_id；透传出现的
  VALUE_BINDING_KEYS（subject_id/fields/known_values）一律不采信。
- B2 可选加强（不改裁定）：`backend/modules/evolution/state_gate.py:216`
  （validate_machine_event_snapshot 调用处）对 knowledge 维度追加 gate 拦截——
  payload 出现任一 VALUE_BINDING_KEYS 即 `reasons.append("value_binding_not_machine_grounded")`，
  把隐式透传从"静默"变"显式拒绝"。不建议给 KnowledgeInPanorama 加
  extra="forbid"（会拦掉 state_gate 注入的 meta/knowledge_subject 等合法键）。

### 揭示边界裁定（全文要点）

- **适用域调和（含 B0 张力的消解）**：两套揭示系统默认相反是各自域的既定语义，
  但 outline 域的"无策略默认公开"有精确边界。Story `RevealPlan`（outline_state，
  reveal_visibility.py）管 **outline 结构层**——揭示计划是作者大纲资产，
  **无策略且无揭示主张记录** = 没有读者限制 → 默认公开
  （test_reader_view_gates_entities_by_reveal 钉定）；一旦存在揭示主张锚
  （策略 reveal_stages 或 timeline 揭示事件记录的揭示章，B0 夹具形态即
  `field_path={subject}.{field}` 的揭示事件），对象即移入「须证明」域。
  World `ReaderRevealPolicy`（world，knowledge_visibility_service.py
  `_reader_revealed`）管 **世界知识层**——对象级保密策略，作为可见性判定的
  附加闸门（`_decide` 仅 has_policy 时介入），public_baseline 显式公开优先，
  无策略时对象默认可见性由 visibility_mode（public/tag/private）决定。
  **B0 xfail 张力在此消解**：其秘密夹具带揭示主张锚（第 2 章 > 读者 cutoff
  第 1 章），修正版 outline 判定为隐藏——无需改夹具、无需 World 接入
  scene 视图；与 world map_structure_service.py:893（无策略时仅
  revealed/fully_known 公开）同款保守口径。
- **共同保守红线**（统一纯函数 `evaluate_reader_reveal(domain, has_policy,
  cutoff_chapter, reveal_chapters, public_baseline)` 参数化承载，测试对拍
  `_reader_revealed` 行为矩阵与 outline 现状 + B0 秘密场景）：当章不揭示
  （严格 `<` cutoff）；无 cutoff 不猜；outline 有策略或有主张记录但无
  `< cutoff` 的锚 → False。
- **「读者揭示只在已证明展示的原文范围内启用」判定通路**（B3 接线）：
  1. 策略/揭示计划给出揭示主张锚 reveal_chapter；
  2. 证明材料：`proven_shown_chapters(FieldProvenance 记录)` 从已展示 Scene 的
     checkpoint/事件稿源提取（A2 的 source_refs[].chapter_index；unverified 空
     refs 链不构成证明——追到事件不等于读者见过原文）；
  3. 判定：`reveal_within_proven_shown(reveal_chapter, proven)`——锚缺失 False
     （不猜）、未落在证明集合 False（策略可计划未来揭示，正文证明展示前不得
     对读者启用）。与 cutoff 分工：cutoff 判"读者读到哪里"，本判定判"揭示主张
     有无已展示原文背书"，双闸都过才启用。
- **第一阶段未支持保持显式 unsupported**：`UNSUPPORTED_READER_VIEW_DIMENSIONS =
  ("timeline", "causality")` 契约常量钉死（reader timeline 揭示范围未登记、
  causality 是作者层断言），不得以作者全知视图补齐；B3 读者视图对这两维保持
  unsupported + omissions 现状。
- ADR 判断：本裁定为 P2-B 包内语义调和（不改跨模块公共契约、不新增授权），
  记 TASK.md 即可；若 B2/B3 落地后揭示双闸成为对外承诺语义，再由主会话评估
  是否升 ADR（草案要点：双域适用域划分 + 当章不揭示/无锚不猜/已展示证明三红线
  + 机器路径不采信透传绑定）。本单元不新建 ADR 文件。

### B2/B3 落点建议（file:line，改动后行号）

- B2（机器路径接线）：转换器直接复用 `knowledge_contract.read_machine_knowledge`
  （本包已给，含白名单与红线测试）；可选 gate 加强在
  `backend/modules/evolution/state_gate.py:216`（validate 调用后追加
  value_binding_not_machine_grounded 拦截）；`continuity/schemas.py:81`
  KnowledgeInPanorama 与 `services.py:1123` `_build_panorama` 读回均无需改动。
- B3（历史回开/读者揭示接线）：`backend/modules/story/continuity/scene_projection.py:221`
  `get_record`——knowledge 维度行经 `read_knowledge_statements(row.state_json)`
  组装响应时过契约（旧格式无法表达值绑定的条目落 unknown，不冒充，呼应 B0 夹具
  "历史回开知识维度不越视角边界"）；读者揭示双闸在
  `scene_state_view.py` `_reveal_cache:704`（cutoff 判定现状）之上叠
  `evaluate_reader_reveal`（合并 outline 策略锚与揭示主张记录锚——后者从
  timeline checkpoint 的 facts 里 `field_path={subject}.{field}` 揭示事件
  提取锚章，即 B0 秘密夹具形态）+ `reveal_within_proven_shown`（证明材料取
  该 Scene 已展示 checkpoint 的 `_field_provenance`，经 `read_field_provenance`）；
  拒绝原因结构用 `denial_reason` 三类互斥承载（B0 另一 xfail 的转绿路径）。
- 后文得知（后 Scene 事件不回灌早 Scene 知识）、角色误信、作者试改假设互不授权：
  已由三分类结构（false_belief 无绑定、unknown 不授予）+ checkpoint 按 Scene 截断
  （scene_projection 既有语义）承载，B3 勿在视图层重写判定。

### 验证

`modules/story` 全量 677 passed + 2 xfailed（B0 夹具保持 xfail 正常；对照 P2-A 基线
633+6xpassed→已转绿 675，本单元新增 30 契约测试后无回归）；新契约测试 30 例全绿；
`ruff check`/`format`（两个新文件）通过；`make module-import-gate` 通过
（65/65、9/9、0/0、525/525、0/0、26/26 未推高；新增 story 模块内导入，无新跨模块边，
零 evidence/world 生产导入）。零 LLM、零 git commit。

## B2 产出（机器知识接线单元，2026-10-07）

### 机器知识流向调查结论（真实调用链，改动前 file:line）

机器断言只有一条产消链，无第二写入路径：

1. 产出：`backend/modules/evolution/pipeline.py:466`（`gate_scene_events(payload["scene_events"], compiled_observations)`；world 侧 `evolution/world.py:397` `bind_scene_identities` 复用同一门）→ `backend/modules/evolution/state_gate.py` `knowledge_changed` 分支注入 `character_id`（== knowledge_subject）、uuid5 `id`、`meta`（authority_basis=derived_observation + source_receipts）、`knowledge_subject` 键，payload 即 `KnowledgeInPanorama` 方言（定义在 `backend/modules/story/continuity/schemas.py:81`，非 evolution 侧）。
2. 入库：`backend/modules/evolution/tasks.py:332-344` applier 打 `source="evolution"` 后 `replace_scene_memory_events(producer_family="evolution")`（`backend/modules/story/continuity/facade.py:95`）→ `MemoryService.record_scene_events`（`backend/modules/story/continuity/services.py:140` 起）原样持久化。
3. 投影：`scene_projection._apply_event` → `reducer._apply_knowledge_event`（`backend/modules/story/continuity/reducer.py:75`）把 payload dict 逐字追加进 checkpoint `state_json["character_knowledge"]`（按 id 去重）。
4. 读取：`scene_state_view._knowledge_grants`（`backend/modules/story/continuity/scene_state_view.py:628`）读**原始 payload dict**——机器方言本身无 `subject_id/fields/known_values` 故现状零授予；但 `KnowledgeInPanorama` 未声明 extra（Pydantic 忽略额外键），`state_gate` 的 `validate_machine_event_snapshot` 校验副本不改 `after`，**偷带绑定键的机器 payload 会静默透传持久化并被 `_knowledge_grants` 当值绑定授予**——B2 要堵的洞。

### 转换器落点（改动最小裁定：写侧信任边界，读侧归 B3）

- 落点：`backend/modules/story/continuity/services.py:252` `MemoryService._sanitize_machine_knowledge`，在 `record_scene_events` 循环（`services.py:181-182`）对 `dimension=="knowledge" and source==MACHINE_EVENT_SOURCE("evolution", services.py:65)` 的 payload 执行：剥除 `VALUE_BINDING_KEYS`（`knowledge_contract` 契约常量，services.py:30 模块内导入）后入库——continuity 状态里的机器条目恒为 `read_machine_knowledge` 白名单方言（unknown 文本知识、无值绑定；读取端经同一转换器物化 origin=machine_observation/传闻 unchecked_note，B2 测试对真实 checkpoint 状态逐字段钉死，B3 负责视图/get_record 的读取接线）。放在 `_with_scene_event_key` 之前，事件键对规范化内容稳定。
- 剥除不做"可归属才剥"前置判定：`_knowledge_grants` 的 holder 走 character_id/holder_id 双键，若以 `read_machine_knowledge` 返回非 None（要求 character_id）作剥除条件，holder_id 变体的旁路 payload 会带着绑定键原样入库——故范围内一律剥除（`test_holder_id_variant_bypass_also_strips_machine_bindings` 钉死该变体：剥除后状态无绑定键、转换器返回 None 不冒充、视角零授予）。
- 不落 reducer（纯解释内核，不知 source，且改形状会破坏 panorama 读回与 uuid5 幂等语义）；不动 `_build_panorama`（B1 裁定机器路径零 schema 变更）；读侧视图/get_record 归 B3。作者确认（source=author_confirmation）与 AI 抽取（默认 ai_extraction）路径不受影响（测试反证钉死：同 payload 无机器 source 不被清洗、Story 方言绑定照常授予）。
- 与 B1 裁定一致：产出门拒绝为主，信任边界剥除为同一不变量的防御纵深（模拟门禁旁路时 continuity 状态仍不可能携带机器值绑定）。

### gate 拦截行为（采纳 B1 可选加强）

`backend/modules/evolution/state_gate.py:206-207`：`knowledge_changed` 分支内，`snapshot_after` 出现任一 `_MACHINE_VALUE_BINDING_KEYS`（state_gate.py:60，`knowledge_contract.VALUE_BINDING_KEYS` 的镜像——knowledge_contract 自身镜像 scene_state_view 常量的同一裁定，避免产出门对读取端契约模块的实现向依赖；测试钉两者相等防漂移）即 `reasons.append("value_binding_not_machine_grounded")`，事件进 `gated_scene_events`/pending_decisions 待作者裁定，不静默透传。未用 `extra="forbid"`（会拦掉 meta/knowledge_subject 合法注入键）。无新增 import（镜像常量），import gate 零增量。

### 测试清单（`backend/modules/story/continuity/tests/test_p2b_machine_knowledge.py`，5 例真绿）

1. `test_gate_value_binding_keys_mirror_contract`——镜像常量与契约 `VALUE_BINDING_KEYS` 相等（防漂移）。
2. `test_gate_rejects_machine_knowledge_claiming_value_bindings`——干净机器知识过门；偷带 subject_id / fields / known_values（单键与三件套）均被 `value_binding_not_machine_grounded` 拒绝。
3. `test_machine_knowledge_lands_as_unbound_text_knowledge`——端到端（gate→source=evolution 入库→ensure_scene→视图）：状态条目无绑定键；`read_machine_knowledge` 落 unknown/无值绑定/无 subject 锚/origin=machine_observation/known_content→text_summary/传闻 unchecked_note/entry_id==gate uuid5；角色视角零事实授予（口令不可见）+ belief 文本层在场 + omissions 解释；作者视角对照可见。
4. `test_smuggled_binding_keys_never_reach_continuity_state`——不变量"机器断言不可能宣称值绑定"：模拟门禁旁路直写，绑定键在信任边界剥除（入库行与 checkpoint 状态均无），`read_machine_knowledge` 仍 unknown；同批 Story 方言条目（默认 source）绑定键原样入库并照常授予、无机器 source 的同 payload 也不被清洗——剥除只针对机器方言。
5. `test_holder_id_variant_bypass_also_strips_machine_bindings`——holder_id 变体（不可归属机器方言的旁路形态）同样剥除：状态无绑定键、转换器返回 None（不冒充归属）、角色视角零授予 + omissions 解释。

### 验证

`modules/story` 全量通过（689 passed——含本单元新文件 5 例；数字随 B3 并行合入波动，本单元基准为自身 5 例全绿且无回归）、`modules/evolution` 232 passed + 1 deselected；`ruff check`/`format` 通过；`make module-import-gate` 通过（65/65、9/9、0/0、**525/525 未推高**、0/0、26/26；services→knowledge_contract 为 story 模块内导入，state_gate 零新增 import）；`make docs-check` 通过（gate reason 字符串无文档登记义务）。注：B0 的 2 xfail 已由 B3 子代理并行转绿并移除标记（scene_state_view/scene_projection/夹具文件均 B3 所改，本单元未触碰）——B0 夹具走 story 事件方言（producer_family=p2b_knowledge_fixture、无 source=evolution），不经 gate 也不触机器边界，与本单元改动无交集。零 LLM、零 git commit。

## B3 产出（视角边界与揭示闸接线单元，2026-10-07）

B0 夹具 `test_p2b_knowledge_boundaries.py` 两个 xfail 摘除转真断言，8/8 全绿；
新增接线验收 `backend/modules/story/continuity/tests/test_p2b_boundary_wiring.py`
（5 例真绿：揭示双闸行为矩阵 ×2、三路径一致性、历史回开方言标注、API 出口编码）。
改动文件：`scene_state_view.py`、`scene_projection.py`（仅 get_record 响应组装段）、
B0 夹具（仅摘标记与文件头说明）、新测试、本节。`knowledge_contract.py` 契约零改动。

### 接线落点（file:line）

- **拒绝原因结构化**：`scene_state_view.py:193` 新增响应子类
  `SceneStateViewDetailResponse(SceneStateViewResponse)`——schemas.py 不在本卡
  可写范围，子类是"只增不删"的最小承载（实测 pydantic v2 下子类实例经
  TypeAdapter(父类) 校验原样通过、jsonable_encoder 按实例 dump 保留新字段，
  FastAPI response_model=父类 的 API 出口不丢 `denied_facts`，
  `test_denied_facts_survive_api_jsonable_encoding` 钉死）。
  `scene_state_view.py:706` `_filter_entries` 升级三元组返回
  `(visible, suppressed_count, denied)`：character 视角对每个被抑制的 fact 层
  条目经 `denial_reason`（三类互斥）归因装进 `denied_facts`；
  `scene_state_view.py:274` get_view 以 `read_knowledge_statements` 读入
  knowledge checkpoint、`build_knowledge_grants` 构建授予表（与原内联
  `_knowledge_grants` 对拍相等，B1 钉测试不变绿转），`scene_state_view.py:688`
  `_knowledge_grants` 保留为契约委托（对拍测试仍引用）。
- **读者揭示闸**：`scene_state_view.py:776` `_reveal_cache` 叠
  `evaluate_reader_reveal`（outline 域）+ `reveal_within_proven_shown` 双闸。
  主张锚合并：outline 策略已达到章（decision.reveal_chapter，has_policy 时）∪
  全书 timeline 揭示事件锚章——`scene_state_view.py:838`
  `_reveal_claim_chapters` 用 `EventRepository.get_through_scene(dimension=
  "timeline")` 全量拉取，payload 带 `field_path` 且首段命中本视图 subject 才算
  （`{subject}.{field}` 形态；既有 `handover` 无点号标签形态不算，test_reader_view_gates
  不回归）；锚章=事件 chapter_index（跨 Scene 生效：后文揭示事件把对象移入须证明域）。
  无策略且无主张锚 → 维持默认公开；有锚 → cutoff 闸（严格 `<`，当章不揭示、
  无 cutoff 不猜）∧ 证明闸。证明材料：`scene_state_view.py:873`
  `_proven_shown_by_subject` 从当前 Scene 各维度 checkpoint 的
  `summarize_field_provenance` 取 status=="exact" 的 source_refs[].chapter_index
  （unverified/conflict 不算——追到事件≠读者见过原文；checkpoint 继承链保证
  早章 exact 稿源在后续 Scene 仍构成证明）。
- **历史回开**：`scene_projection.py:286` get_record 对 knowledge 维度行经
  `_annotate_knowledge_dialect`（scene_projection.py:57）标注——逐条 payload 经
  `read_knowledge_statement`（`read_knowledge_statements` 的单条入口，保证
  payload↔分类一一对应不因批读跳过而错位）在深拷贝副本上追加
  `knowledge_class`（known/unknown/false_belief），原键全保留。

### 拒绝原因最终响应结构

`denied_facts` 仅 character 视角填充（reader 维持 omissions 数量口径不泄露对象，
B0 契约第 5 条；belief/observation 的视角层排除不是知识原因，不进 denied）：

```json
{"denied_facts": [
  {"dimension": "entities", "subject_id": "<uuid>", "subject_label": "铜钥匙",
   "field": "opening_passphrase", "cause": "knowledge_value_mismatch"}
]}
```

cause ∈ {no_knowledge_entry, knowledge_value_mismatch, false_belief}（契约
`KnowledgeDenialCause`）。不参与 `state_fingerprint`（视角解释不改状态本体）。
omissions 维度级计数字符串原样保留（既有断言全部兼容）。

### get_record 裁定与依据

**裁定：作者诊断用途，保留 raw + 补方言分类标注。** 依据：api.py:251 端点
`GET /scene-checkpoints/{checkpoint_id}` 无 viewpoint 参数、`_require_active_project`
门禁、docstring"回读当前或历史依据……不重建也不采用旧状态"；facade.py:168 注释
"版本回开（get_record）前端与 A4 历史列表消费"。它回开 checkpoint 原文供作者诊断，
视角过滤发生在 get_view（面向前端的视角路径已过边界），故不在此做视角过滤；
知识条目按该历史行自身 payload 分类（`test_get_record_annotates_knowledge_dialect_
and_survives_rebuild` 钉死：事件流追加改写 + rebuild 后历史行仍固化当时的
known/false_belief 分类；ORM 行载荷不被响应标注键污染；当前行新条目 unknown
不冒充值绑定）。

### 三路径一致性验证

`test_reveal_and_denial_boundaries_consistent_across_rebuild`：缓存命中路径
（ensure_scene 幂等命中既有 checkpoint 后读）与投影重建路径
（`rebuild_from_scene(from None)` supersede 全部系统行重算）下的 reader
可见事实签名（dimension, subject, field, value 全集）、omissions、character
`denied_facts` 归因签名逐位相等，并断言主张锚对象隐藏（reader）与旁观者
no_knowledge_entry（character）的具体判定；历史回开路径的一致性由
get_record 标注测试承载（同上）。fingerprint 不跨重建比对（重建换行 id 属
checkpoint 身份变化，非边界漂移）。揭示双闸行为矩阵另由两例钉死：
无 exact 稿源时 cutoff 过了仍隐藏（`test_reader_reveal_claim_anchor_gates_until_
proven_shown`）；锚章带 working 稿（exact 整章区间）时 cutoff 过后启用
（`test_reader_reveal_enabled_within_exact_proven_chapters`）。

### 与 B0/B1 契约的偏差与说明

- 无契约偏差；两处实现裁量：① 承载形态选 `denied_facts`（B0 允许的 facts 同级
  结构之一）；② `read_knowledge_statements` 的批读在非法条目上跳过会导致
  payload↔statement 错位，get_record 标注改用其单条入口 `read_knowledge_statement`
  逐条对应（同一契约、同一方言判定）。
- B1"B3 落点建议"中 get_record"经 read_knowledge_statements 组装"按上款裁量执行。
- 证明闸对非受控注册字段（如 secret_relation）当前无 exact 链可证——有主张锚的
  该类字段在受控字段稿源落地前对读者保持隐藏（保守方向，符合"无证明不启用"）；
  未注册字段的揭示证明材料是否扩展由主会话后续裁定。
- state_trial.py 未改：口令条件的 observed（旧值）/expected（新值）双值已可解释
  "值不匹配 ≠ 不知道"（B0 类别一断言满足），无必要新增 verdict reason。
- 文档未同步项（docs/ 本卡禁改，留主会话）：`docs/modules/05_memory.md:62`
  "读者视角经既有 reveal 判定过滤 subject（默认无策略=公开）"应精确为
  "无策略且无揭示主张记录才默认公开；timeline 揭示事件构成主张锚"，
  并补 `denied_facts` 响应字段与 get_record 知识标注说明。

### 验证

`modules/story` 全量 689 passed（含 B0 8/8、B3 新增 5、B2 并行 5；零失败零跳过）；
continuity 子集 199 passed；`ruff check`/`format` 通过（含新测试文件）；
`make module-import-gate` 通过（65/65、9/9、0/0、525/525 未推高、0/0、26/26——
新增导入均为 story 模块内 + shared/infrastructure 既有允许边）。零 LLM、零 git commit。

## C1 产出（消费登记缝设计与契约单元，2026-10-07）

新契约模块 `backend/modules/evolution/consumption.py`（约 830 行，零 DB/零
LLM/零接线）+ 契约测试 `backend/modules/evolution/tests/test_consumption_registry.py`
（34 例全绿，文件名避开 C0 的 `p2c_` 前缀）+ `backend/core/service_keys.py`
新增一个 DI 键常量。**选址裁定：放 evolution 模块内**——失效计算（登记集的
消费方）在本模块；story→evolution 依赖边在 import-gate 冻结集合内（合法），
writing→evolution **不在**（回执透传只能走 DI）；跨模块导入须经
`modules.evolution.contracts`/`facade` 再出口（形态门禁），再出口归 C2/C3。

### 与 C0 夹具的键名对齐（已按其目标形态逐键对齐）

C0 落盘于本单元写作中途，已按 `test_p2c_revision_adoption.py` 头部目标形态
同步：`ConsumerKind.story_scene_checkpoint`（非 scene_checkpoint）、
`RecomputeScope = {reload_evidence, rebuild_derived_state, regenerate_prose}`
（非 reread/rebuild_derived）、视图顶层 `affected`/`unknown_scope`(bool)/
`receipt_id` 最小键集、unknown 条目 `reason="conservative_expansion_unregistered"`
+ `basis="known"|"unknown"`、recompute 选项 `{kind, covers, affected?}` 三类
恒列（regenerate 带 `author_choice_only=True`）。
`ImpactReason`：`anchored_chapter_edited` / `offset_window_hit` /
`offset_window_miss` / `content_mode_mismatch` /
`conservative_expansion_unregistered` / `unregistered_consumer`。

### 契约原文（结构清单）

```
CONSUMPTION_CONTRACT_VERSION = "consumption-registry-v1"
CONSUMPTION_REGISTRY_STATE_KEY = "_consumption_registry"   # 产物行 JSON 内嵌键

ConsumerKind(StrEnum): story_scene_checkpoint | evidence_chapter_index | scene_lens
CONSUMER_REF_REQUIRED_KEYS: kind → 必填定位键（scene_checkpoint=scene_id+dimension；
  evidence=chapter_index+content_mode；lens=scene_id；缺锚构造即失败，不冒充覆盖）

ConsumerRef(frozen): kind + scene_id?/scene_index?/dimension?/chapter_index?/content_mode?
OffsetRange(frozen): start_offset/end_offset（码点，end 开区间，与 SourceChange 同口径）
ChapterConsumption(frozen): chapter_index + draft_id?/version_number?/source_hash?
  + ranges: tuple[OffsetRange]（空=整章消费，任何该章变更命中）
SourceBinding(frozen): content_mode(working|canonical) + chapters 非空且章号不重复
  （多章 Scene 跨章表达）+ .chapter(idx) 查询
BasisAnchor(frozen): anchor_kind(scene_checkpoint|chapter_basis|evidence_index_state)
  + ref_id + fingerprint?
AssetDigest(frozen): asset_kind + asset_id + digest?（摘要引用，重算按 id 重读）
ConsumptionRecord(frozen): novel_id（隔离锚，跨 novel 记录被评估直接忽略）
  + consumer + binding + basis? + selected_assets/excluded_assets
  + method_version + registered_at(datetime)

read_consumption_records(payload): 旧载荷（无键）/非 dict → [] 不报错不冒充；
  键存在内容非法 → ValidationError（写入端已校验，读回非法=数据损坏，沿 P2-A 裁定）

影响计算（纯函数 assess_source_impact）：
ConsumerImpact: affected | unaffected | unknown
ConsumerVerdict(frozen): consumer + impact + reason + note(作者语言)
UnknownScope(frozen): chapter_registration_missing / scenes_without_registration /
  scene_roster_unavailable / unregistered_consumers / note + .conservative
  （conservative 只衡量投影窗口能否收窄；unsupported 列表恒展示不参与窗口，
  对齐现状回执 unsupported_consumers 只展示的角色）
ImpactAssessment(frozen): nothing_to_do + verdicts + unknown_scope
  + conservative_from_scene_index(对拍锚) + from_scene_index + refined + .affected()

回执透传：
CONSUMER_LABELS（内部键→作者标签，未知键回退原键进诊断区）
receipt_fingerprint(receipt) -> str（稳定指纹=content_hash(关键内容)，receipt_id 的 C1 实现）
affected_view_entries(receipt, assessment=None) -> [{consumer, scene_id, scene_index,
  dimension, reason, basis, note}]（known=登记命中/确定性键；unknown=保守扩大场景；
  无关 Scene 不进列表；无 assessment 退化为回执确定性键）
derive_recompute_options(receipt, assessment=None) -> 三类恒列（nothing_to_do → []）
receipt_public_view(receipt, assessment=None) -> dict（C0 最小键集 + 作者语言字段
  invalidated/unsupported/coverage_note/diagnostics；JSON 可直接进响应）

重算三分类：
RECOMPUTE_SCOPE_COVERS: reload_evidence→(evidence_chapter_index,)
  rebuild_derived_state→(story_scene_projections,) regenerate_prose→(prose_generation,)
RECOMPUTE_SCOPE_EFFECTS: 各类 cost/write_effect（作者语言受控表）
RecomputeTargetRef(frozen): scene_index?/chapter_index?/dimension?（至少一锚）
RecomputeRequest(frozen): novel_id + operation_id + scope + targets(非空)
  + mode(preview|execute，execute⇒confirmed) + confirmed + baseline_receipt_digest?
  （validator：execute 未确认拒绝；regenerate_prose 必须锚章）
recompute_request_hash(request)：幂等第二键（不含 mode——预览/执行同操作；
  口径沿 collaboration merge 的 operation_id+request_hash 双幂等）
RecomputePreview(frozen)：domain_write_performed=False 字面量（结构上零正史写入）
  + build_recompute_preview(request, affected_consumers=...)
RecomputeOutcome(frozen)：replayed(幂等重放标记) + domain_write_performed + results
```

### 落点决策：纯 JSON 内嵌，不加表（C2 沿此执行）

- 登记记录随消费产物行内嵌（checkpoint `state_json["_consumption_registry"]`、
  evidence 索引 state 等价 JSON 载荷），沿 P2-A `_field_provenance` 先例：与产物行
  生命周期一致（随 supersede 软删）、JSON 边界过 Pydantic 校验、失效计算按
  novel+chapter 拉产物行时顺带读取，无跨行独立查询需求；省 models+Alembic。
- 契约提供 `read_consumption_records` 兼容读取，旧数据（无键）评估退化为纯保守
  （与现状等价），不迁移。若 C2/C3 发现需要按登记集独立检索（如"谁消费了这版稿"
  反查），再评估窄表——那属于新需求，不在本包。

### 影响计算与现状保守行为的对拍结论（测试钉死）

- **无登记 → 行为不变**：`from_scene_index` 恒等于传入的 earliest（=
  回执 `earliest_affected_scene_index`）。DB 对拍
  （test_no_registration_assessment_matches_real_invalidation_receipt）：真实
  `apply_source_invalidation` 改第 2 章后 receipt.earliest=1、库中 Scene 1
  checkpoint 全 superseded / Scene 0 保持 current，评估窗口与之逐位一致；
  unknown 来源显式列出（chapter_registration_missing + scenes_without_registration
  = (1,) + unsupported）。
- **有登记 → 仅细化、不隐藏**（test_registration_refines_real_conservative_window）：
  登记区间与变更窗口不相交 → verdict `offset_window_miss`、评估失效集合（∅）⊆
  现状失效集合（{1}）；全部登记证明无关且无 unknown → from=None（零投影失效，
  "已知依赖零无关重生成"的证明材料）。
- 保守收窄三前提：变更章有登记、保守窗口内全部场景有登记、调用方提供场景清单
  （`scene_indexes=None` 恒保守）。unknown 任一存在 → from=earliest 不收窄。
- 跨章 Scene 早于保守锚：from 取 `min(命中 scene, earliest)`（登记修复保守
  扩大漏掉的跨章前缀，只可能更早=更安全方向）。
- `changed=False` → nothing_to_do（回执同语义）；`changed=True` 但缺偏移窗口 →
  按整章消费保守命中。
- 评估纯函数不查库：earliest 由调用方经 `invalidation.affected_scene_window`
  查得、场景清单从 outline 查得（C2 接线时组装）。

### DI 缝结论

- `EVOLUTION_RECORD_WRITING_SOURCE_CHANGE` **签名不变**：`record_writing_source_change`
  已返回 `InvalidationReceipt`，writing 层只是丢弃（repositories.py:57-64）——
  C3 最小首步是接住返回值，无需改缝。
- 新增键常量 `EVOLUTION_INVALIDATION_RECEIPT_VIEW = ServiceKey(
  "evolution.invalidation.receipt_view")`（consumption.receipt_public_view 的注入位；
  writing 层不能 import evolution——冻结集合无 writing→evolution 边）。常量暂
  **不入 `ALL_SERVICE_KEYS`**：登记表与 bootstrap 注册须一一对应（AO-10 校验 +
  tests/unit/test_container.py::test_bootstrap_declared_keys_match_registered_services
  会对未注册键 get() 失败），组合根注册与补录归 C2/C3 接线一并完成。
- 重算编排键暂不加：C3 编排端点定形后再评估（预览/执行或经 collaboration
  现有 case/merge 端点承载，未必要新键）。

### C2/C3 落点建议（file:line）

- C2（evolution 侧）：
  - `backend/modules/evolution/invalidation.py:98-110` `InvalidationReceipt` 增补
    可选字段 `affected: list[dict]`、`unknown_scope: bool`、`receipt_id: str`、
    `recompute_options: list[dict]`（默认空，旧构造兼容；extra=forbid 注意存量
    测试构造不受影响——默认值即可）。
  - `invalidation.py:209-232` `apply_source_invalidation` 的 story_state 失效段：
    组装 `assess_source_impact`（earliest 已在 :209 查得；场景清单经 outline
    facade；records 从 checkpoint state_json 读 `read_consumption_records`——
    story 侧行的读取经函数内导入或 facade），用 `assessment.from_scene_index`
    替换 earliest 传入 `invalidate_sources`/`invalidate_derived_state`（unknown
    时两者相等=行为不变）；回执填 affected/unknown_scope/receipt_id/
    recompute_options（`affected_view_entries`/`derive_recompute_options`/
    `receipt_fingerprint`）。
  - 登记写入端（story 侧）：`backend/modules/story/continuity/scene_projection.py`
    `_project_dimension`（P2-A 挂链同位置 :514-558 一带）把 `ConsumptionRecord`
    写入 `state[CONSUMPTION_REGISTRY_STATE_KEY]`（binding 的 draft/version/
    source_hash 沿 A2 `_event_source_refs` 同源）；跨模块导入经
    `modules/evolution/contracts.py` 再出口（story→evolution 边合法但须
    contracts/facade 形态）。evidence 侧登记（evidence_chapter_index/scene_lens
    kind）在索引重建/lens 摘要处同理。
  - store 回执落库按 C2 任务卡原计划。
- C3（writing 侧）：
  - `backend/modules/writing/repositories.py:57-64` `_changed` 接住
    `await get(EVOLUTION_RECORD_WRITING_SOURCE_CHANGE)(...)` 返回值（receipt 鸭子
    类型），经 `get(EVOLUTION_INVALIDATION_RECEIPT_VIEW)(receipt, assessment=...)`
    投影成 dict 后随 draft 事件透传（create/update 链路加返回通道或挂
    provenance_json 旁路，按 C3 实际调用链定）。
  - `backend/modules/writing/api.py` 响应模型加 `invalidation: dict | None`
    （C0 xfail 用例 test_p2c_writing_revision_surfaces_invalidation_view 的目标：
    `WritingDraftContract.invalidation` 键集 ⊇ {affected, unknown_scope, receipt_id}，
    affected scene 集合 == {1,2}——由 receipt_public_view(assessment=) 产出）。
  - `backend/app/bootstrap.py` `_container_services` 注册
    `(EVOLUTION_INVALIDATION_RECEIPT_VIEW, consumption.receipt_public_view)` 并把
    键补进 `core/service_keys.ALL_SERVICE_KEYS`。
  - 重算编排端点：`RecomputeRequest(mode="preview")` → `build_recompute_preview`
    （零正史写入）+ `mode="execute"` 经 collaboration 试改生命周期（幂等
    operation_id+recompute_request_hash、三向 rebase、人工修改保留——本包 C0
    夹具 M2–M6 已钉基线）；`baseline_receipt_digest` 执行时重验（漂移 409）。

### 验证

`modules/evolution/tests/test_consumption_registry.py` 34 例全绿（含 2 例真库
对拍：无登记行为不变、有登记仅细化；结构校验/旧数据兼容/幂等键/预览零写入
全覆盖）；`modules/evolution` 全量 274 passed + 4 xfailed（C0 夹具 xfail 保持），
另有 3 failed **全部位于并行 C0 子代理仍在迭代中的 test_p2c_revision_adoption.py**
（setup 层 `get_latest_draft_for_chapter` 返回 None 等，零 import 本单元文件，
失败数随其修复持续下降 8→4→3，归 C0/汇合处理）；`tests/unit/test_container.py`
21 passed（service_keys 改动无回归）；ruff check/format 过；
`make module-import-gate` 过（65/65、9/9、0/0、525/525、0/0、26/26 未推高——
新模块仅同模块+infrastructure 导入）。零 LLM、零真实数据写入、零 git commit。

## C0 产出（P2-C 批1，2026-10-07）

夹具文件：`backend/modules/evolution/tests/test_p2c_revision_adoption.py`
（模块内 tests 惯例、`p2c_` 前缀，SQLite 合成库经真实公开入口执行：
WritingDraftService / MemoryService / SceneMemoryProjectionService /
collaboration cases·workspaces·merge·recovery / evolution 失效缝）。
当前输出 **11 passed + 4 xfailed**；`--runxfail` 验证四个 xfail 均失败在
目标断言（getattr 取不到结构即断言失败，非 setup 报错）。零 LLM、零真实数据。

### 场景×断言矩阵

| 用例 | 场景 | 断言要点 | 状态 |
|---|---|---|---|
| test_p2c_custody_revision_marks_failure_scope_and_adoption_conflict | §3 场景六 改稿×并发采用 | 改保管章 v2 保存即失效（s1 起软失效、s0 不牵连）；任务入队仅 rag_index_chapter（零昂贵生成）；同窗口采用被领域错误拒绝（selected 范围现状报 NotFoundError 资源不可重定位）、当前稿保留作者 v2、零回执；rebase 报同字段冲突且当前稿精确保留 | 真绿 |
| test_p2c_custody_revision_current_semantics_stay_conservative | 现状钉板 | earliest_affected_scene_index=1；evidence_chapter_index 换源（requested_hash 与库一致）；story_scene_projections.from_scene_index=1 且 superseded_checkpoints≥1 | 真绿 |
| test_p2c_unregistered_dependency_expands_conservatively_without_hiding | 未知消费者保守扩大 | s2（无登记）仍被扩大失效；unsupported_consumers=={world_knowledge,map_atlas} 且各带 reason；coverage_note 明言"保守扩大" | 真绿 |
| test_p2c_unrelated_chapter_edit_keeps_custody_scenes_current | 零无关重生成（现状） | 改无关第 3 章：earliest=2，s0/s1 checkpoint 保持 current | 真绿 |
| test_p2c_matrix_m1_source_change_preserves_versions_and_history | M1 来源变化 | 版本行 [v1,v2] 俱在；软失效 checkpoint 行保留；保管事件行保留 | 真绿 |
| test_p2c_matrix_m2_confirmation_drift_keeps_manual_draft | M2 确认漂移 | 采用被拒、当前稿=人工版、零回执、基线版本可回开 | 真绿 |
| test_p2c_matrix_m3_midway_failure_rolls_back_and_keeps_drafts | M3 途中失败 | 第二写注入失败 → 双章域写入全回滚、稿保持基线、零回执 | 真绿 |
| test_p2c_matrix_m4_merge_retry_is_idempotent_and_receipt_queryable | M4 重试 | 同 operation_id 回放同回执、仅 1 行；采用后人工再改不被重试覆盖；回执/合并试改仍可查 | 真绿 |
| test_p2c_matrix_m5_two_windows_merge_fields_and_keep_current | M5 双窗口修改 | 作者改标题+试改正文 → rebase 自动合并（回放幂等）；同字段 → conflict+当前稿保留 | 真绿 |
| test_p2c_matrix_m6_leave_and_restore_keeps_trial_and_draft | M6 离开恢复 | 重开 workspace 覆盖层仍在、可继续叠加（sequence+1）、当前稿不动 | 真绿 |
| test_p2c_cancel_after_preview_writes_nothing_canonical | 取消零正史副作用 | 预览后取消：当前稿零写入、零回执、零 DomainOutbox | 真绿 |
| test_p2c_custody_revision_affect_list_is_explainable | 场景六 目标形态 | receipt.affected 列表：s1 basis=known（reason 可解释）、s2 basis=unknown（conservative_expansion_unregistered）、s0 不入列；unknown_scope=True；receipt_id 非空 | xfail |
| test_p2c_writing_revision_surfaces_invalidation_view | 写作侧透传 目标形态 | WritingDraftContract.invalidation 视图（键集 affected/unknown_scope/receipt_id；scene_indexes=={1,2}；钩子确已执行仅回执被丢弃） | xfail |
| test_p2c_recompute_options_classify_three_cost_tiers | 重算三分类 目标形态 | recompute_options kinds=={reload_evidence, rebuild_derived_state, regenerate_prose}；rebuild.affected=={1,2}（含保守条目）、不含 s0 | xfail |
| test_p2c_unrelated_chapter_edit_enqueues_no_custody_scene_recompute | 零无关重生成 目标形态 | 改无关章的重算清单与 affected 均不含保管场景 s0/s1 | xfail |

xfail 统一 `pytest.mark.xfail(reason="P2-C dependency registration not implemented",
strict=False)`；失败点（--runxfail 实测）：前四者分别在 receipt.affected /
contract.invalidation / receipt.recompute_options 的结构存在断言处。

### 钉下的目标形态（键名级，C1/C3 对齐基准；详见夹具头注释）

- 失效可解释视图（InvalidationReceipt 增强并经 writing 契约透传的投影）：
  `{affected: [{consumer, scene_id, scene_index, reason, basis: known|unknown}],
  unknown_scope: bool, receipt_id}`；reason 机器可读（anchored_chapter_edited /
  conservative_expansion_unregistered）。现有 earliest_affected_scene_index /
  invalidated_consumers / unsupported_consumers / coverage_note 保守语义由真绿
  用例钉死不回归。
- 重算三分类：`recompute_options: [{kind: reload_evidence|rebuild_derived_state|
  regenerate_prose, covers: [...], affected: [scene 引用]}]`；编辑保存自动入队
  仅允许证据重读类（现状真绿：task_types ⊆ {rag_index_chapter}）。
- 重算预览/采用复用 Collaboration 试改生命周期（取消/冲突/幂等/双窗口断言即
  验收基线），采用重验接 revalidate_creative_manifest。

### 现状语义注记（C1/C2/C3 设计输入）

- selected 范围下来源漂移的采用拒绝现状是 NotFoundError（旧资源不可重定位），
  project 范围是 ConflictError(SOURCE_STALE/查询范围)——两者同为领域拒绝、
  均零域写入；C4 前端提示与 C3 编排需兼容两种错误面。
- request_chapter_index 在来源变化时入队 rag_index_chapter（one_pending_follower
  模式）——它属"重读证据"档，"编辑不自动触发生成"的真绿断言以任务类型白名单
  表达（≠ 零任务）。

## C4 产出（前端失效提示与重算入口，2026-10-07）

零 LLM、零 git commit；改动全部留在工作树。vitest 全量 230 文件 / 2857 用例
通过 + eslint 0 问题（新增 4 个测试文件共 35 用例）。

### 组件与文件

- `frontend-console/vue/views/writing/invalidationModel.js`（新增，纯模型层）：
  C1 `receipt_public_view` → 作者语言投影（`normalizeInvalidationNotice` 零打扰
  口径：缺字段/非对象/`nothing_to_do`/无任何失效信号 → null）；重算三分类文案
  （`RECOMPUTE_SCOPES`，成本/写入效果对齐 `RECOMPUTE_SCOPE_EFFECTS` 作者语言）；
  `recomputeRequestPayload` 按 `RecomputeRequest` 组装（preview/execute 共结构、
  `baseline_receipt_digest`=receipt_id、rebuild 以场景锚、regenerate/reload 以章锚）；
  预览/回执/历史条目防御性投影；`recomputeOperationKey`（randomUUID 优先、无
  Web Crypto 失败关闭）；`isRecomputeConflictError`（409 + SOURCE_STALE/
  baseline_drift，兼容 C0 注记的双错误面）。
- `frontend-console/vue/views/writing/components/InvalidationNotice.vue`（新增）：
  autosave 成功后就地温和提示条（role=status 非弹窗）：范围摘要 + 待核实说明
  + 「查看受影响与重算选项」入口；无失效时整条不渲染。
- `frontend-console/vue/views/writing/components/RecomputePanel.vue`（新增）：
  次级渐进面板（沿 CreativeExperiments 语言/交互）：受影响列表（场景+原因+
  已知/待核实徽章）、缺口可见（invalidated/unsupported/coverage_note 次级折叠）、
  三分类单选（每类成本/效果说明）、预览（独立只读+零写入说明）、采用（与预览
  共用同一 operation_id 的幂等对；执行中禁用+离开保护 canLeave/aux guard/
  beforeunload；编辑器 dirty 时禁止执行）、冲突（409/漂移：展示所基于的失效信息
  vs 服务器最新影响（invalidationReceipt 回读）+「保留当前稿」零写入返回）、
  非冲突失败可重试且复用同一幂等键、回执历史（懒加载、空态/失败/重读）、
  「暂不重算」= 纯本地关闭零请求；notice 更换（新回执）时面板复位。
- `frontend-console/api/evolution.js`：追加 `invalidationReceipt` /
  `recomputePreview` / `recomputeExecute` / `recomputeCancel` / `recomputeReceipts`
  封装（query novel_id + body 含 novel_id 双口径，按 C1 RecomputeRequest 形态）。
- `frontend-console/vue/views/writing/controllers/editorController.js`：autosave
  成功链最小接入——`state.invalidationNotice = normalizeInvalidationNotice(
  result?.invalidation, { chapterIndex: chapter })`（保存失败/无字段零打扰）；
  `applyDraft`（切章/切版本/checkpoint/载入服务器版）与 `restoreSession`
  （会话快照不复活旧提示）清空。
- `frontend-console/vue/views/writing/components/WritingEditor.vue`：渲染点
  （save-recovery 卡之后、candidate 区之前挂 InvalidationNotice + RecomputePanel，
  传 state.invalidationNotice/chapter/dirty；notice 清空时自动收起面板）。

### 范围裁定（假设记录）

可写清单未点名 WritingEditor.vue；失效提示「编辑器就地展示」没有渲染点则无法
交付，故在 writing 模块内的编辑器组件做最小挂载（约 20 行模板/脚本），未触碰
WritingView/useWritingWorkspace 及其他模块。测试替身走 bridge
`setBridgeOverrides`（DI 缝），生产零 Mock。

### 测试

- `tests/vue/writing/invalidationModel.test.js`（14）：零打扰口径、条目/徽章/
  标题投影、缺 options 默认三分类、payload 目标锚与幂等字段、预览回退、
  回执投影、幂等键失败关闭、冲突判定。
- `tests/vue/writing/InvalidationNotice.test.js`（3）：触发条件、待核实说明
  条件渲染、open 事件。
- `tests/vue/writing/RecomputePanel.test.js`（14）：受影响列表、三分类文案与
  预览门控、场景锚目标、预览失败重试、采用幂等键、editorDirty 禁止执行、
  冲突（比较+保留当前稿零写入）、失败重试同键、取消零请求、进行中禁止离开、
  回执历史（失败/成功/空态）、能力缺失失败态、新回执复位。
- `tests/vue/writing/invalidationAutosave.test.js`（4）：保存成功带视图生成
  提示、无字段/nothing_to_do 零打扰、保存失败不产生提示且错误通道不变、切章
  清空。

### 与 C3 的契约对接点（待汇合对齐项）

- 端点路径为前端先行拟定：GET `/evolution/invalidation/{receipt_id}`、POST
  `/evolution/recompute/preview|execute|cancel`、GET `/evolution/recompute/receipts`
  （query `novel_id` + body `novel_id` 双口径）。C3 落地路径若不同，仅需改
  `api/evolution.js` 五个方法体。
- 保存响应透传字段名按 C0 夹具 `WritingDraftContract.invalidation`；前端读
  `result.invalidation`（autosave 与 autosaveDraftOnly 两链路都读）。
- execute 的冲突响应面按 409 或 `code=SOURCE_STALE/baseline_drift` 判定；
  若 C3 用其他错误码，扩 `isRecomputeConflictError` 即可。
- 回执历史条目字段按 `operation_id/scope/created_at/replayed` 防御性读取，
  未知字段不冒充翻译；`recomputeCancel` 封装已备、面板取消目前纯本地零副作用
  （若 C3 要求显式取消未执行操作，再接调用点）。

## C2 产出（evolution 侧消费登记接线与失效细化，2026-10-07）

新文件 `backend/modules/evolution/registration.py`（登记写入端：构建 +
幂等合并，零 DB/零 LLM）与 `backend/modules/evolution/impact.py`（失效
影响组装层：登记读取 + 锚定合成 + 回执视图投影）；`invalidation.py` 扩展
（`InvalidationReceipt` 增量字段 + `apply_source_invalidation` 接
`assess_source_impact`）；`facade.py` 再出口 `receipt_view`；
`core/service_keys.py` 补录 `ALL_SERVICE_KEYS`；`app/bootstrap.py` 注册
`(EVOLUTION_INVALIDATION_RECEIPT_VIEW, evolution.facade.receipt_view)`。
测试：`test_consumption_registry.py` 扩 8 例（42 全绿）；C0 夹具 xfail
①③④ 摘标转绿（15 passed + 1 xfailed——②透传归 C3）。

### 登记写入落点调查结论（B 类待办在此）

真实写入点唯一：`story/continuity/scene_projection.py::_project_dimension`
（投影消费 working 稿；draft/version/source_hash 与 P2-A `_working_refs`
同源可锚）。该文件在 story 模块（B 类接线，本批不越权）；collaboration
manifest 消费为读侧（无产物行可内嵌）；evidence 章索引是确定性消费者
（失效引擎无条件重建，不依赖登记判定）；`scene_lens` kind 目前无生产
写入端（evidence compilation 的 memory loader 是读 checkpoint 侧）。
**接线方向**：story→evolution 边在 import-gate 冻结集合内，接线时在
`_project_dimension` 组 state 处调
`modules.evolution.contracts/facade` 再出口的
`registration.register_consumption` + `scene_checkpoint_registration`
（本批已实现并测试，接线零新增设计）；evidence 侧无边
（`evidence` 冻结集合不含 evolution），若未来需要经 DI 键注入。

### 无接线期的可解释性：锚定结构合成登记

`impact.anchored_registrations`：对锚定变更章、且该 `(scene_id,
dimension)` 无真实登记的投影，按 outline 结构事实（scene.chapter_ids
锚定）合成整章消费登记（`method_version="anchored-scene-implicit-v1"`
标识来源、无稿锚、`ranges=()`）。真实登记存在时不合成（登记是权威声明，
优先于结构事实）。效果：无登记场景下受影响列表可解释（锚定场景
basis=known + reason=anchored_chapter_edited、scene_id 真实；后续无事实
场景 basis=unknown + conservative_expansion_unregistered），且评估窗口
与现状保守扩大逐位一致（`from == earliest`，合成登记恒判整章命中不收窄
窗口）——C0 ①③④ 因此可在无 story 接线时转绿。

### InvalidationReceipt 增量字段（默认值，旧构造兼容、既有字段零改动）

`affected: list[dict]`（`affected_view_entries` 形态，known/unknown 分列、
无关 Scene 不进）、`unknown_scope: bool`（保守范围或 unsupported 存在）、
`receipt_id: str`（`receipt_fingerprint` 稳定指纹）、`recompute_options:
list[dict]`（三分类）、`impact_assessment: Any`（内嵌评估对象，供
`receipt_view` 重投影；不参与指纹）。失效路径 `apply_source_invalidation`
（含 `record_writing_source_change`）与重排/nothing_to_do 分支均填
`receipt_id`；evolution runs 失效保持保守锚 `earliest`（不随投影窗口
收窄），投影失效用 `assessment.from_scene_index`。

### 重算三分类规则（recompute_options）

恒列三类（nothing_to_do 除外）：`reload_evidence`（covers
evidence_chapter_index——对应现有 `rag_index_chapter` 任务白名单，编辑时
唯一自动入队档）、`rebuild_derived_state`（covers story_scene_projections
+ affected=scene 级条目，含保守 unknown、不含登记证明无关的 Scene）、
`regenerate_prose`（covers prose_generation，`author_choice_only=True`，
仅作者显式经 `RecomputeRequest(mode="execute", confirmed=True)` 触发）。
编排/执行端点归 C3。

### 窗口语义边界（汇合批/B 类需知）

物理投影失效仍是窗口语义（story `supersede_system_from` 自起点起全失效，
无按场景集合 supersede 的能力）："部分命中"场景下窗口内被证明无关的
Scene 仍被物理失效（与现状一致，零行为破坏），但归因列表/重算清单不含
它；"全部登记无关"时窗口收窄到零（`from=None`，零投影失效——
test_all_registered_unrelated_keeps_projections_current 钉死）。按集合
supersede 的对齐留 B 类（story 侧接线时一并评估）。

### 验证

`modules/evolution` 全量 288 passed + 1 xpassed（C3 透传 xfail 保持）+1
deselected（real LLM）；`test_consumption_registry.py` 42 全绿（含 4 例
真库端到端：部分命中归因、全无关零失效、offset_window_hit、无登记保守
可解释）；`tests/unit/test_container.py` 21 passed（键表-注册一一对应）；
`tests/unit/test_governance_gates.py` 中我的指标 65/65、9/9、0/0、
525/525 未推高、26/26（移开并行 C3 未跟踪的 `writing/recompute.py` 顶层
story import 后 gate 全绿——该双向对归 C3 汇合处理）；ruff
check/format 过；`make docs-check` 过。零 LLM、零 git commit。

## C3 产出（writing 侧回执透传与重算编排，2026-10-08）

改动文件（本单元独占写入）：`backend/modules/writing/repositories.py`、
`contracts.py`、`schemas.py`、`services.py`、`api.py`、新增 `recompute.py`
（编排服务，独立新文件避开 services.py 热点）、新测试
`backend/modules/writing/tests/test_p2c_recompute.py`（10 例全绿）、
C0 夹具 `test_p2c_revision_adoption.py` 仅摘②的 xfail、本节。

### 回执透传链路（file:line，改动后行号）

- `repositories.py:61-75` `_changed` 接住
  `EVOLUTION_RECORD_WRITING_SOURCE_CHANGE` 返回的 InvalidationReceipt，
  经 C2 注册的 DI 缝 `EVOLUTION_INVALIDATION_RECEIPT_VIEW`
  （`evolution.facade.receipt_view` → `impact.py`）投影为作者语言公共
  视图，挂到 draft 行的**瞬态属性** `invalidation`（`INVALIDATION_VIEW_ATTR`，
  repositories.py:28；非映射列不入库——测试钉死 WritingDraft 无同名列）。
  瞬态属性是并发安全的最小通道：回执在 `_changed` 单点产生（重算不得
  二次触发失效），视图随引发它的对象走，repo/service 单例无共享状态。
- `contracts.py:53` `WritingDraftContract.invalidation: dict | None`
  （additive 置尾，旧位置构造零破坏）；`services.py` `_to_contract` 读
  `getattr(draft, INVALIDATION_VIEW_ATTR)`；`schemas.py:213/280-282`
  `WritingDraftResponse.invalidation`（from_attributes 直取瞬态属性，
  before-validator 按本模型既有惯例把非 dict 来源置 None——publish/update/
  autosave 全部响应路径自动携带）。
- API 零破坏增量：autosave `POST /api/writing/drafts/autosave` 响应带
  `invalidation` 公共视图（affected/unknown_scope/receipt_id 最小键集 +
  invalidated/unsupported/coverage_note/recompute_options）。

### 重算编排端点（writing api：`/api/writing/recompute*`）

- `POST /api/writing/recompute`（api.py:497-510）：预览模式。入参
  `{novel_id, operation_id, scope, targets[{scene_index|chapter_index,
  dimension?}], baseline_receipt_digest?}`；返回独立预览
  `{request_hash, scope, covers, cost, write_effect, executable, actions[],
  affected[], source_digest, source_state, domain_write_performed: false}`。
  纯读组装，结构上零正史写入（测试钉死索引状态/任务/稿件逐位不变）。
- `POST /api/writing/recompute/{operation_id}/adopt`（api.py:513+）：执行。
  入参同预览 + `confirmed: true` + `expected_source_digest`（预览返回的
  来源指纹）；path/body operation_id 不一致 400。
  - 重验：目标章最新工作稿 (version, content_hash) 指纹漂移 → 409
    `recompute_source_drift`，context 携带 `current` 各章版本/指纹 +
    `keep_current_draft: true`（可比较数据，当前稿保留，零新任务）。
  - 执行只走既有白名单：reload_evidence → `evidence.facade.
    request_chapter_index(working)`（复用/合并 rag_index_chapter，
    one_pending_follower/reuse_active 幂等）；rebuild_derived_state →
    `story.facade.ensure_scene_checkpoints`（投影重建幂等、历史与作者
    确认保留）。regenerate_prose 无既有生成任务白名单支撑 → 409
    `recompute_scope_unsupported`（零 LLM；预览 `executable=false` 明示）。
  - 幂等：operation_id+request_hash 双键（`recompute_request_hash`
    与 C1 `recompute_request_hash` 对同一逻辑请求逐位相等，测试对拍）；
    重放落在本身幂等的域动作上——reload 重放复用同一任务（任务数/索引
    行数不变）、rebuild 重放 ensure_scene 幂等短路（checkpoint 行数不变）。
    **已知缺口（汇合批裁定）**：无持久 operation 台账，`replayed` 标记
    与"同 operation_id 异内容拒绝"（collaboration merge 语义）未实现，
    C2 回执落库 store 可作后续锚点。
  - 取消/过期零副作用：预览无服务端状态，不 adopt 即取消（测试钉死）。
- 目标解析：scene 锚经 `get_scenes_by_novel`（status canonical/draft，
  与失效引擎同口径）；章锚保守扩大到锚定该章的全部 Scene（受影响条目
  basis=unknown 显式标注"登记未接入前保守口径"，不冒充登记依据）；
  evidence 章条目 basis=known（确定性重建）。scene_index 不存在 →
  400 `recompute_target_not_found`。

### import-gate 裁定（回应 C2 产出的"该双向对归 C3 汇合处理"）

`writing/recompute.py` 顶层 `modules.story.facade` import 会与
story→writing 既有顶层反向导入（scene_projection 等）构成顶层双向对
（基线 0）。已改：recompute 内 story 门面降为函数内导入（沿
services.py 既有惯例）；等量补偿把 `repositories._changed` 与
`services.py`（checkpoint 确认段）两处函数内 `evidence.facade.
mark_asset_context_changed` 提升为顶层（evidence 无顶层反向导入 writing，
不构成双向对）。gate 全绿：65/65、9/9、0/0、**525/525 未推高**、0/0、26/26。

### C0 ②转绿

`test_p2c_writing_revision_surfaces_invalidation_view` 摘 xfail 后真绿
（C2 回执增强 + 本单元透传合流；affected scene_indexes=={1,2} 成立）。
C0 夹具 15/15 全绿（①③④已由 C2 先行转绿）。

### 验证

新测试 10 例全绿（镜像对拍×2、透传 service/API、瞬态不落库、预览零写入+
取消零副作用、确认门+unsupported、reload 幂等、rebuild 恢复+幂等、来源
漂移冲突保留当前稿、HTTP 契约含 400/409）；`modules/writing` 304 passed、
`modules/evolution`+`modules/collaboration`+`tests/unit/test_container.py`
656 passed 1 deselected；`make module-import-gate` 过；ruff check/format 过；
`make docs-check` 无基线过，`BASE_REF=origin/main` 报分支累计复核清单
（writing/evolution README、docs/modules/11_writing.md 等——docs/ 本卡
禁改，归 P2-C 汇合批统一同步，同 A4 先例）。零 LLM、零 git commit。

### C4 汇合对齐（2026-10-07，C3 真实端点落地后）

C3 落地 `backend/modules/writing/api.py` 的 `/writing/recompute`（预览）与
`/writing/recompute/{operation_id}/adopt`（执行）后，前端从拟定契约切到真实
契约。vitest 全量 230 文件 / 2863 用例通过 + eslint 0 问题（C4 测试 4 文件
41 用例）。

- `api/evolution.js`：只保留 `recomputePreview`（POST /writing/recompute）与
  `recomputeExecute`（POST /writing/recompute/{operation_id}/adopt，路径带
  operation_id）；删除 `recomputeCancel`/`invalidationReceipt`/
  `recomputeReceipts`（无后端对应；取消=不调用 adopt，预览无服务端状态）。
- `invalidationModel.js`：请求体对齐 WritingRecomputeRequest（extra=forbid，
  基础体仅 novel_id/operation_id/scope/targets/baseline_receipt_digest，
  **去掉 mode/confirmed**）；新增 `recomputeAdoptPayload`（+confirmed:true+
  expected_source_digest=预览 source_digest）；预览投影消费真实响应
  （executable/actions/covers/source_digest/source_state.chapters）；
  `recomputeConflictKind` 认 409+`recompute_source_drift`/
  `recompute_scope_unsupported`（SOURCE_STALE/baseline_drift 兼容保留）；
  `normalizeRecomputeDriftContext`+`driftRowLabel` 把 409 context.current 与
  预览 source_state 逐章比成「预览时第 a 版 → 当前第 b 版」；回执历史改
  **本地会话内记录**（`rememberRecomputeReceipt`/`listRecomputeReceipts`，
  按 novel 隔离、operation_id 去重、上限 20），口径与 limitation（刷新即失、
  跨会话经 adopt 幂等重放重查）写在模块头注记。
- `RecomputePanel.vue`：执行走 adopt 端点（同 operation_id 幂等对，重试复用
  同键同指纹）；regenerate_prose 预览 executable=false → 执行按钮禁用并显示
  「需要你的明确确认与生成额度，当前不可自动执行」；漂移冲突比较数据源改
  409 context（逐章版本对比），动作=「基于当前稿重新预览」/「保留当前稿」；
  回执历史读本地会话记录并明示 limitation；取消仍纯本地零请求。
- 测试同步：`invalidationModel.test.js` 18 例（白名单字段断言用 toEqual 钉
  死 extra=forbid 口径）、`RecomputePanel.test.js` 16 例（adopt 路径/体、
  executable=false、漂移重预览后成功、保留当前稿、scope_unsupported、
  本地回执隔离与空态）。
