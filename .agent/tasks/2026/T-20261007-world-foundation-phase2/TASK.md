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
| P2-B 批1/批2 | B0 夹具 ∥ B1 方言统一；B2/B3/B4 | 待 P2-A |
| P2-C 批1/批2 | C0 夹具 ∥ C1 登记缝；C2/C3/C4 | 待 P2-B |

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

## 恢复快照

（交接/暂停前更新）当前：P2-A 全部完成（批1/批2/汇合），提交后进入 P2-B 批1（B0 六类知识夹具 + B1 方言统一两子代理并行）。

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
